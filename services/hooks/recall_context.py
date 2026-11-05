#!/usr/bin/env python3
"""Hook UserPromptSubmit do Claude Code: injeta o contexto da camada CERTA (Fase 4 do plano da memória).

Roteador §3.3, determinístico (zero LLM): estado/ID/título de PROJ/GOAL → até 3 linhas
exatas do ledger; sinal literal ("o que foi dito", aspas) → 1–2 trechos de origem;
pessoa detectada → ledger (pendências) + contexto; demais → até 3 itens de contexto.
Teto **5 itens** por mensagem; **abstenção** quando nada passa do corte (0.62 — 4.2,
sem reranker aprovado). Perna vetorial com prazo próprio (700 ms): Hindsight lento ou
fora degrada para o que o ledger tiver — o hook nunca atrasa nem bloqueia (~2 s no
total). Só biblioteca padrão (roda até no python3 do sistema).

Variáveis de ambiente (opcionais):
  BRAIN_RECALL_ROUTE       off | ledger | embed — padrão **embed** (esta fase)
  BRAIN_HINDSIGHT_URL      padrão http://127.0.0.1:8888
  BRAIN_RECALL_BANKS       padrão brain
  BRAIN_RECALL_MIN_SCORE   corte semântico (sem reranker), padrão 0.62
  BRAIN_RECALL_MAX         teto de itens por mensagem, padrão 5
  BRAIN_RECALL_SEMANTIC_MS prazo da perna vetorial, padrão 700
  BRAIN_RECALL_OFF=1       desliga o hook
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = os.environ.get("BRAIN_HINDSIGHT_URL", "http://127.0.0.1:8888").rstrip("/")
BANKS = [b for b in os.environ.get("BRAIN_RECALL_BANKS", "brain").split(",") if b]
MIN_SCORE = float(os.environ.get("BRAIN_RECALL_MIN_SCORE", "0.62"))
MAX_ITEMS = int(os.environ.get("BRAIN_RECALL_MAX", "5"))
SEMANTIC_MS = float(os.environ.get("BRAIN_RECALL_SEMANTIC_MS", "700"))
ROUTE = os.environ.get("BRAIN_RECALL_ROUTE", "embed")
TIMEOUT_S = 2.0
MIN_PROMPT_CHARS = 12

HEADER_LEDGER = ("Estado do Segundo Cérebro (ledger, leitura exata) — confira no livro-razão com "
                 "`brain query entity <ID>`. Ignore se não for pertinente.\n")
HEADER_MIXED = ("Pistas do Segundo Cérebro (ledger + memória semântica) — são pistas, não verdade: "
                "confirme no citado antes de afirmar (vault/… ou ledger/<id> via `brain`). "
                "Ignore se não for pertinente.\n")


def _brainlib():
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    from brainlib import route
    return route


def recall(bank, query, timeout):
    body = json.dumps({"query": query, "budget": "low", "max_tokens": 1500,
                       "include": {"source_facts": {"max_tokens": 500}}}).encode()
    req = urllib.request.Request(f"{URL}/v1/default/banks/{bank}/memories/recall", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    # observações consolidadas não têm document_id próprio: herda dos fatos de origem
    facts = data.get("source_facts") or {}
    for res in data.get("results", []):
        if not res.get("document_id"):
            docs = {(facts.get(i) or {}).get("document_id") for i in res.get("source_fact_ids") or []}
            res["document_id"] = ", ".join(sorted(d for d in docs if d)) or None
    return bank, data.get("results", [])


def _ledger_leg(prompt):
    """(classificação, ≤3 linhas do ledger) — nunca lança."""
    try:
        route = _brainlib()
        return route.classify(prompt), route.ledger_lines(prompt)
    except Exception:  # noqa: BLE001 — hook nunca quebra a conversa
        return {}, []


def _expand(prompt: str, cls: dict) -> list[str]:
    """Fase 4.1: consulta original + variante com aliases da pessoa detectada (dedup)."""
    queries = [prompt]
    people = (cls or {}).get("people") or []
    if people:
        try:
            route = _brainlib()
            db = route._find_db()
            aliases = []
            if db is not None:
                for pid in people[:2]:
                    aliases += route.person_aliases(pid, db)[:3]
            extra = (prompt + " " + " ".join(dict.fromkeys(aliases))).strip()
            if aliases and extra != prompt:
                queries.append(extra)
        except Exception:  # noqa: BLE001
            pass
    return queries


def _semantic_leg(queries, cap, timeout):
    """Recall semântico com prazo próprio; corta por score (abstenção), dedup por texto."""
    if cap <= 0 or not BANKS:
        return []
    items, seen = [], set()
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(queries) * len(BANKS)))) as pool:
        futs = [pool.submit(recall, b, q, timeout) for q in queries for b in BANKS]
        for fut in futs:
            try:
                bank, results = fut.result(timeout=timeout + 0.3)
            except Exception:  # noqa: BLE001 — banco fora/lento: entrega o que tiver
                continue
            for r in results:
                score = (r.get("scores") or {}).get("semantic") or 0
                text = " ".join((r.get("text") or "").split("|")[0].split())
                key = text.lower().rstrip(". ")[:120]
                if not text or key in seen:
                    continue
                seen.add(key)
                items.append((score, text, r.get("document_id") or "?", r.get("occurred_start")))
    if not items:
        return []
    if not any(s > 0 for s, *_ in items):
        cut = items                                  # sem score no payload: confia na ordem do servidor
    else:
        cut = [i for i in items if i[0] >= MIN_SCORE]  # abstenção: nada passa do corte
    cut.sort(key=lambda x: -x[0])
    return cut[:cap]


def _emit(header: str, lines: list[str]) -> None:
    context = header + "\n".join(f"- {ln}" for ln in lines)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": context}}, ensure_ascii=False))


def main():
    if os.environ.get("BRAIN_RECALL_OFF") == "1" or ROUTE == "off":
        return
    prompt = (json.load(sys.stdin).get("prompt") or "").strip()
    cls: dict = {}
    lines: list[str] = []
    if ROUTE in ("ledger", "embed"):
        cls, lines = _ledger_leg(prompt)
    if ROUTE == "ledger":
        if lines:
            _emit(HEADER_LEDGER, lines)
        return
    # ── rota embed (§3.3) ─────────────────────────────────────────────────────────
    # pergunta de estado/ID sem pessoa e sem sinal literal: o vetor não soma
    if lines and cls.get("route") == "ledger" and not cls.get("people") and not cls.get("literal"):
        _emit(HEADER_LEDGER, lines)
        return
    if len(prompt) < MIN_PROMPT_CHARS and not cls.get("people"):
        if lines:
            _emit(HEADER_LEDGER, lines)
        return
    sem_cap = min(2 if cls.get("literal") else 3, MAX_ITEMS - len(lines))
    items = _semantic_leg(_expand(prompt, cls), sem_cap, min(SEMANTIC_MS / 1000, TIMEOUT_S - 0.3))
    out = list(lines)
    for score, text, doc, date in items:
        if len(text) > 400:
            text = text[:400] + "…"
        when = f", {date[:10]}" if date else ""
        out.append(f"{text} ⟶ {doc}{when}")
    if out:
        _emit(HEADER_LEDGER if not items else HEADER_MIXED, out)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — hook nunca quebra a conversa
        pass
