#!/usr/bin/env python3
"""Hook UserPromptSubmit do Claude Code: anexa ao contexto o que o Hindsight lembra sobre a mensagem.

Só biblioteca padrão (roda até no python3 do sistema). Qualquer falha — servidor fora, timeout,
nada relevante — sai em silêncio: o hook nunca atrasa nem bloqueia uma mensagem por mais de ~2 s.

Ajustes por variável de ambiente (opcionais):
  BRAIN_HINDSIGHT_URL      padrão http://127.0.0.1:8888
  BRAIN_RECALL_BANKS       padrão brain-mem,brain-raw
  BRAIN_RECALL_MIN_SCORE   similaridade semântica mínima (bge-m3), padrão 0.55
  BRAIN_RECALL_MAX         máximo de itens injetados, padrão 8
  BRAIN_RECALL_OFF=1       desliga o hook
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = os.environ.get("BRAIN_HINDSIGHT_URL", "http://127.0.0.1:8888").rstrip("/")
BANKS = [b for b in os.environ.get("BRAIN_RECALL_BANKS", "brain-mem,brain-raw").split(",") if b]
MIN_SCORE = float(os.environ.get("BRAIN_RECALL_MIN_SCORE", "0.55"))
MAX_ITEMS = int(os.environ.get("BRAIN_RECALL_MAX", "8"))
TIMEOUT_S = 2.0
MIN_PROMPT_CHARS = 12


def recall(bank, query):
    body = json.dumps({"query": query, "budget": "low", "max_tokens": 1500,
                       "include": {"source_facts": {"max_tokens": 500}}}).encode()
    req = urllib.request.Request(f"{URL}/v1/default/banks/{bank}/memories/recall", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        data = json.load(r)
    # observações consolidadas não têm document_id próprio: herda dos fatos de origem
    facts = data.get("source_facts") or {}
    for res in data.get("results", []):
        if not res.get("document_id"):
            docs = {(facts.get(i) or {}).get("document_id") for i in res.get("source_fact_ids") or []}
            res["document_id"] = ", ".join(sorted(d for d in docs if d)) or None
    return bank, data.get("results", [])


def main():
    if os.environ.get("BRAIN_RECALL_OFF") == "1":
        return
    prompt = (json.load(sys.stdin).get("prompt") or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS:
        return
    query = prompt[:2000]
    items, seen = [], set()
    with ThreadPoolExecutor(len(BANKS)) as pool:
        for fut in [pool.submit(recall, b, query) for b in BANKS]:
            try:
                bank, results = fut.result()
            except Exception:  # noqa: BLE001 — um banco fora não derruba o outro
                continue
            for r in results:
                score = (r.get("scores") or {}).get("semantic") or 0
                text = " ".join((r.get("text") or "").split("|")[0].split())
                key = text.lower().rstrip(". ")[:120]
                if score < MIN_SCORE or not text or key in seen:
                    continue
                seen.add(key)
                items.append((score, bank, text, r.get("document_id") or "?", r.get("occurred_start")))
    if not items:
        return
    items.sort(key=lambda x: -x[0])
    lines = []
    for score, bank, text, doc, date in items[:MAX_ITEMS]:
        if bank.endswith("raw") and len(text) > 400:
            text = text[:400] + "…"
        when = f", {date[:10]}" if date else ""
        lines.append(f"- {text} ⟶ {doc}{when}")
    context = ("Memória do Segundo Cérebro (Hindsight, ~/brain) — itens que parecem relacionados à mensagem. "
               "São pistas, não verdade: o vault e o livro-razão mandam. Antes de afirmar algo com base "
               "nelas, confirme no arquivo citado (caminho relativo a ~/brain/vault, ou ledger/<id> via "
               "`brain`). Ignore se não for pertinente.\n" + "\n".join(lines))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": context}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — hook nunca quebra a conversa
        pass
