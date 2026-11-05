"""Eval de memória (Fase 0 do plano) — recuperação determinística, sem LLM no julgamento.

Roda o conjunto-ouro (vault/eval/memory-gold.jsonl — zona curada do dono) contra as duas
pernas do sistema (ledger pelo roteador + vetor pelo banco) e devolve métricas por tipo:
recall@k, MRR, citação correta, itens injetados, precisão da injeção, taxa de abstenção
nas `nada` e tokens aproximados por pergunta. Barato de repetir; baseline salvo em
vault/eval/runs/. Disciplina R4: até ~25 perguntas por tipo o eval é DIRECIONAL, não gate.
"""
from __future__ import annotations

import json
import re

from . import util

TYPES = ("estado", "contexto", "decisao", "detalhe", "literal", "conclusao", "nada")
ARROW = re.compile(r"⟶ (?:ledger/)?([A-Z]+-?\d+(?:\.\d+)?)")


def load_gold(path) -> list[dict]:
    """Parser do conjunto-ouro: pula linhas vazias e comentários (#); valida o esquema."""
    if not path.exists():
        raise util.BrainError(f"conjunto-ouro não encontrado: {path}", code=1)
    out: list[dict] = []
    seen: set[str] = set()
    for ln, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        try:
            d = json.loads(s)
        except ValueError as e:
            raise util.BrainError(f"gold linha {ln}: JSON inválido ({e})", code=4) from e
        for f in ("id", "q", "type"):
            if not d.get(f):
                raise util.BrainError(f"gold linha {ln}: campo {f!r} faltando", code=4)
        if d["type"] not in TYPES:
            raise util.BrainError(f"gold linha {ln}: tipo {d['type']!r} fora de {TYPES}", code=4)
        if d["id"] in seen:
            raise util.BrainError(f"gold linha {ln}: id {d['id']!r} duplicado", code=4)
        seen.add(d["id"])
        d.setdefault("lang", "pt")
        d.setdefault("expect_ids", [])
        d.setdefault("expect_docs", [])
        out.append(d)
    if not out:
        raise util.BrainError("gold vazio — copie o exemplo de template/eval/memory-gold.example.jsonl "
                              "para vault/eval/memory-gold.jsonl e curie (~60 perguntas, Fase 0)", code=4)
    return out


def _ledger_leg(brain, q: str) -> tuple[list[str], list[str]]:
    """(ids citados nas linhas, linhas) — silêncio é lista vazia. O db é o DA INSTÂNCIA:
    sem passar o caminho, o roteador sobe do cwd e pode achar outro vault."""
    from . import index as _index, route
    db = _index.db_path(brain.inst)
    if not db.exists():
        return [], []
    c = route.classify(q, db)
    if c["route"] != "ledger":
        return [], []
    lines = route.ledger_lines(q, db)
    ids = list(dict.fromkeys([*c.get("ids", []), *(ARROW.findall(" ".join(lines)))]))
    return ids, lines


def _vector_leg(brain, q: str, hs, k: int) -> list[dict]:
    from . import memory
    if hs is None or memory.mode(brain.inst.cfg["memory"]) == "none":
        return []
    try:
        res = hs.recall(brain.inst.cfg["memory"]["bank"], q)
    except util.BrainError:
        return []
    out = []
    for r in (res.get("results") or [])[:k]:
        doc = r.get("document_id")
        if doc:
            out.append({"doc": doc, "text": (r.get("text") or "")[:200]})
    return out


def _question(brain, g: dict, hs, route_on: bool, k: int) -> dict:
    ids, lines = _ledger_leg(brain, g["q"]) if route_on else ([], [])
    chunks = _vector_leg(brain, g["q"], hs, k)
    retrieved = [(f"ledger/{i}", "ledger") for i in ids[:k]] + [(c["doc"], "chunk") for c in chunks]
    exp_ids = [e.upper() for e in g.get("expect_ids", [])]
    exp_docs = list(g.get("expect_docs", []))
    hit_rank = None
    for rank, (src, _kind) in enumerate(retrieved, 1):
        if src in exp_docs or (src.startswith("ledger/") and src.split("/", 1)[1] in exp_ids) \
                or (g["type"] == "conclusao" and src.startswith("mm-")):
            hit_rank = rank
            break
    injected = len(lines) + len(chunks)
    abstain = injected == 0
    return {"id": g["id"], "type": g["type"], "hit": hit_rank is not None, "rank": hit_rank,
            "recalled_doc": hit_rank is not None and retrieved[hit_rank - 1][0] if hit_rank else None,
            "injected": injected, "abstained": abstain,
            "tokens": (len(g["q"]) + sum(len(c["text"]) for c in chunks)) // 4}


def run(brain, gold: list[dict], hs=None, route_on: bool = True, k: int = 5) -> dict:
    rows = [_question(brain, g, hs, route_on, k) for g in gold]
    by_type: dict[str, dict] = {}
    for t in TYPES:
        tr = [r for r in rows if r["type"] == t]
        if not tr:
            continue
        nada = t == "nada"
        by_type[t] = {
            "n": len(tr),
            "recall_at_k": round(sum(r["hit"] for r in tr) / len(tr), 3),
            "mrr": round(sum(1 / r["rank"] for r in tr if r["rank"]) / len(tr), 3),
            "avg_injected": round(sum(r["injected"] for r in tr) / len(tr), 2),
            "abstention": round(sum(r["abstained"] for r in tr) / len(tr), 3) if nada else None,
            "avg_tokens": round(sum(r["tokens"] for r in tr) / len(tr)),
        }
    total_hit = [r for r in rows if r["type"] != "nada"]
    return {"k": k, "route": "on" if route_on else "off", "questions": len(rows), "by_type": by_type,
            "overall": {"recall_at_k": round(sum(r["hit"] for r in total_hit) / len(total_hit), 3) if total_hit else None,
                        "mrr": round(sum(1 / r["rank"] for r in total_hit if r["rank"]) / len(total_hit), 3) if total_hit else None},
            "rows": rows}


def cli(args, brain) -> None:
    from . import memory
    from pathlib import Path
    gold_path = Path(args.gold) if args.gold else brain.inst.vault / "eval" / "memory-gold.jsonl"
    if not gold_path.exists():
        raise util.BrainError(f"conjunto-ouro não encontrado: {gold_path} — copie o exemplo de "
                              "template/eval/memory-gold.example.jsonl e cure (~60 perguntas, Fase 0)", code=1)
    gold = load_gold(gold_path)
    hs = None
    if memory.mode(brain.inst.cfg["memory"]) != "none" and args.route != "ledger":
        try:
            hs = memory.client(brain)
            hs.health()
        except util.BrainError:
            hs = None
    res = run(brain, gold, hs=hs, route_on=args.route != "off", k=args.k)
    if args.save:
        dest = Path(args.save)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        res = {**res, "saved_to": str(dest)}
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    print(f"eval · {res['questions']} perguntas · k={res['k']} · rota {res['route']} · vetor "
          f"{'sim' if hs else 'não'}")
    for t, m in res["by_type"].items():
        extra = f" · abstenção {m['abstention']:.0%}" if m["abstention"] is not None else ""
        print(f"  {t:9} n={m['n']:2} · recall@{res['k']} {m['recall_at_k']:.0%} · MRR {m['mrr']:.2f}"
              f" · {m['avg_injected']:.1f} itens · ~{m['avg_tokens']} tokens/perg{extra}")
    if res["overall"]["recall_at_k"] is not None:
        print(f"  total     recall@{res['k']} {res['overall']['recall_at_k']:.0%} · "
              f"MRR {res['overall']['mrr']:.2f}  (R4: direcional até ~25/tipo)")
