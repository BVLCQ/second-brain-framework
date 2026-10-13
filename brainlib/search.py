"""Busca determinística (sem LLM) no ledger, no PLANNING e nos artefatos do PROCESSED.

Ranking simples: termos dobrados (sem acento) contados no título pesam 3×, no corpo 1×.
A camada de memória (Hindsight) é a busca semântica; esta é a rede de segurança.
"""
from __future__ import annotations

from . import model, util


def _score(terms: list[str], title: str, body: str = "") -> int:
    t, b = util.fold(title), util.fold(body)
    if not all(term in t or term in b for term in terms):
        return 0
    return sum(3 * t.count(term) + b.count(term) for term in terms)


def search(brain, query: str, limit: int = 20) -> list[dict]:
    terms = [t for t in util.fold(query).split() if len(t) > 1]
    if not terms:
        return []
    m = model.build(brain)
    hits: list[dict] = []

    def add(kind, id_, title, body, date=None, path=None):
        s = _score(terms, f"{id_} {title}", body)
        if s:
            hits.append({"kind": kind, "id": id_, "title": title, "date": date, "path": path, "score": s})

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
    vault = brain.inst.vault
    for a in m["artifacts"]:
        path = vault / a["id"]
        body = path.read_text(encoding="utf-8", errors="replace") if path.suffix == ".md" and path.exists() else ""
        add("artefato", a["id"], a["title"], f"{a['summary']} {body}", a["date"], a["id"])
    hits.sort(key=lambda h: (-h["score"], h.get("date") or ""), reverse=False)
    return hits[:limit]
