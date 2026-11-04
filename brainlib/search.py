"""Busca determinística (sem LLM) no ledger, no PLANNING e nos artefatos do PROCESSED.

Ranking simples: termos dobrados (sem acento) contados no título pesam 3×, no corpo 1×.
Todos os termos precisam casar (AND); se isso não achar nada, refaz com qualquer termo (OR),
ordenando por quantos termos distintos casaram, e marca os hits com `match: "parcial"`.
A camada de memória (Hindsight) é a busca semântica; esta é a rede de segurança.
"""
from __future__ import annotations

from pathlib import Path

from . import model, notes, util


def _score(terms: list[str], title: str, body: str = "", any_term: bool = False) -> int:
    t, b = util.fold(title), util.fold(body)
    matched = [term for term in terms if term in t or term in b]
    if not matched or (not any_term and len(matched) < len(terms)):
        return 0
    base = sum(3 * t.count(term) + b.count(term) for term in matched)
    return base + 1000 * len(matched) if any_term else base      # OR: sobreposição de termos manda


def _note_hits(brain, terms: list[str], limit: int, any_term: bool) -> list[dict]:
    """Notas avulsas ao vivo (inbox + RAW): entidade de arquivo, sem evento no ledger —
    o índice SQLite não as cobre entre updates."""
    out = []
    for n in notes.scan(brain.inst):
        sc = _score(terms, f"{n.link or ''} {n.title}", n.text, any_term)
        if sc:
            out.append({"kind": "nota", "id": n.link or Path(n.path).name, "title": n.title,
                        "date": (n.created or "")[:10], "path": n.path, "score": sc})
    out.sort(key=lambda h: (-h["score"], h.get("date") or ""))
    return out[:limit]


def search(brain, query: str, limit: int = 20) -> list[dict]:
    terms = [t for t in util.fold(query).split() if len(t) > 1]
    if not terms:
        return []
    from . import index
    hits = index.search_index(brain, query, limit)      # índice SQLite (FTS5) quando existe
    if hits is not None:
        live = _note_hits(brain, terms, limit, any_term=all(h.get("match") == "parcial" for h in hits) and bool(hits))
        seen = {h["id"] for h in hits}
        merged = hits + [h for h in live if h["id"] not in seen]
        if not merged and len(terms) > 1:               # índice e notas mudos: parcial nas notas
            merged = [dict(h, match="parcial") for h in _note_hits(brain, terms, limit, any_term=True)]
        merged.sort(key=lambda h: -h["score"])
        return merged[:limit]
    m = model.build(brain)
    cands: list[tuple] = []

    def add(kind, id_, title, body, date=None, path=None):
        cands.append((kind, id_, title, body, date, path))

    for a in m["actions"]:
        add("ação", a["id"], a["title"], " ".join([a["owner_name"], a["how"] or "", a["outcome"] or "",
                                                     a["project_title"] or ""]), a["opened"])
    for d in m["decisions"]:
        add("decisão", d["id"], d["title"], " ".join([*d["decided_by_names"], d["context"], d["rationale"],
                                                     d["project_title"] or ""]), d["date"])
    for e in m["deliveries"]:
        add("entrega", e["id"], e["title"], " ".join([e["result"], e["evidence"], e["impact"]]), e["date"])
    for p in m["people"]:
        add("pessoa", p["id"], p["name"], " ".join([*p["aliases"], p["role"], p["relation"], p["email"]]))
    for g in m["goals"]:
        add("goal", g["id"], g["title"], g["why"] or "")
    for p in m["projects"]:
        add("projeto", p["id"], p["title"], " ".join(d["title"] for d in p["deliverables"]))
    for pr in brain.state.processes.values():
        add("processo", pr.id, pr.title, " ".join([pr.io, *pr.pains, *pr.tools, *pr.notes]),
            pr.added.isoformat() if pr.added else None)
    for o in brain.state.opportunities.values():
        add("oportunidade", o.id, o.title, " ".join([o.problem, o.suggestion, o.gain, *o.notes]),
            o.added.isoformat() if o.added else None)
    vault = brain.inst.vault
    for a in m["artifacts"]:
        path = vault / a["id"]
        body = path.read_text(encoding="utf-8", errors="replace") if path.suffix == ".md" and path.exists() else ""
        add("artefato", a["id"], a["title"], f"{a['summary']} {body}", a["date"], a["id"])
    for n in notes.scan(brain.inst):          # notas avulsas (inbox + RAW); o id leva ao alvo do vínculo
        add("nota", n.link or Path(n.path).name, n.title, f"{n.link} {n.text}", n.created[:10], n.path)

    def rank(any_term: bool) -> list[dict]:
        hits = []
        for kind, id_, title, body, date, path in cands:
            sc = _score(terms, f"{id_} {title}", body, any_term)
            if sc:
                hits.append({"kind": kind, "id": id_, "title": title, "date": date, "path": path, "score": sc,
                             **({"match": "parcial"} if any_term else {})})
        hits.sort(key=lambda h: (-h["score"], h.get("date") or ""))
        return hits

    hits = rank(False)
    if not hits and len(terms) > 1:
        hits = rank(True)
    return hits[:limit]
