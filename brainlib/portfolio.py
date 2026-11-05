"""Portfólio (processos e oportunidades): cálculos determinísticos, sem LLM.

O LLM extrai e redige; aqui só se contabiliza: duplicatas, lacunas, matriz, funil.
"""
from __future__ import annotations

import re

from . import util

STOPWORDS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas",
             "para", "pra", "por", "com", "um", "uma", "que", "se", "ao", "ou", "sem", "mais", "como"}
DUP_THRESHOLD = 0.5


def tokens(text: str) -> set[str]:
    """Tokens normalizados: minúsculas, sem acento, sem stopwords curtas do PT-BR."""
    words = re.findall(r"[a-z0-9]+", util.fold(text))
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def duplicates(title: str, problem: str, opps, limit: int = 3) -> list[tuple]:
    """Oportunidades parecidas com (título, problema): [(opp, similaridade)] com sim ≥ 0,5, melhores primeiro."""
    probe = tokens(f"{title} {problem}")
    scored = [(o, jaccard(probe, tokens(f"{o.title} {o.problem}"))) for o in opps]
    hits = [(o, round(s, 2)) for o, s in scored if s >= DUP_THRESHOLD]
    hits.sort(key=lambda x: (-x[1], x[0].id))
    return hits[:limit]


def process_gaps(p) -> list[str]:
    """Lacunas de cadastro de um processo ativo."""
    out = []
    if p.playbook is None:
        out.append("sem playbook")
    if not p.owner:
        out.append("sem responsável")
    if not p.recurrence or not p.duration_min or (p.runs_month is None):
        out.append("sem recorrência/duração")
    return out


# ── matriz, funil, lacunas ───────────────────────────────────────────────────
QUADRANTS = ["ganho rápido", "aposta", "preencher depois", "evitar"]
FUNNEL_ORDER = ["ideia", "triagem", "priorizada", "em-andamento", "piloto", "validando", "entregue",
                "em-espera", "descartada"]
CLOSED = {"entregue", "descartada"}          # fora da matriz e de "parada"
STALE_DAYS = 30


def quadrant(o) -> str | None:
    """Impacto (≥3 alto) × Facilidade (≥3 alta). None enquanto faltar ICE."""
    if not (o.impact and o.ease):
        return None
    high_i, high_e = o.impact >= 3, o.ease >= 3
    return QUADRANTS[0] if high_i and high_e else QUADRANTS[1] if high_i else \
        QUADRANTS[2] if high_e else QUADRANTS[3]


def matrix(opps) -> dict[str, list]:
    """Quadrante → oportunidades com ICE (ordenadas por score desc, id); encerradas ficam de fora."""
    out: dict[str, list] = {q: [] for q in QUADRANTS}
    for o in opps:
        q = None if o.status in CLOSED else quadrant(o)
        if q:
            out[q].append(o)
    for v in out.values():
        v.sort(key=lambda o: (-(o.score or 0), o.id))
    return out


def funnel(opps) -> dict[str, int]:
    out = {s: 0 for s in FUNNEL_ORDER}
    for o in opps:
        out[o.status] = out.get(o.status, 0) + 1
    return out


def by_area(opps) -> dict[str, list]:
    out: dict[str, list] = {}
    for o in opps:
        out.setdefault(o.area, []).append(o)
    return out


def by_goal(opps) -> dict[str, list]:
    out: dict[str, list] = {}
    for o in opps:
        out.setdefault(o.goal or "", []).append(o)       # "" = sem goal ainda
    return out


def gain_hours(opp, state=None) -> float | None:
    """Horas/mês poupadas: só o que o dono declarou — o cérebro não estima ganho sozinho."""
    return opp.hours_saved


def gaps(state, today) -> dict:
    """O que falta no portfólio. `total` soma todas as lacunas (para a linha do home)."""
    active = [p for p in state.processes.values() if p.status == "ativo"]
    with_proc = {p.area for p in active}
    live = [o for o in state.opportunities.values() if o.status not in CLOSED | {"em-espera"}]
    stale = []
    for o in live:
        last = o.last_activity or o.added
        if last and (today - last).days > STALE_DAYS:
            stale.append({"id": o.id, "days": (today - last).days})
    out = {
        "areas_without_process": [a for a in state.areas if a not in with_proc],
        "processes": [{"id": p.id, "gaps": g} for p in active if (g := process_gaps(p))],
        "no_ice": [o.id for o in live if o.score is None],
        "ice_suggested": [o.id for o in live if o.score is not None and o.ice_suggested],
        "stale": sorted(stale, key=lambda s: -s["days"]),
    }
    out["total"] = (len(out["areas_without_process"]) + len(out["processes"]) + len(out["no_ice"])
                    + len(out["ice_suggested"]) + len(out["stale"]))
    return out


def _iso(d):
    return d.isoformat() if d else None


def _doc(d) -> dict:
    return {"ref": d.ref, "kind": d.kind, "title": d.title, "date": _iso(d.date), "watch": d.watch,
            "read": _iso(d.read)}


def build(state, plan, today) -> dict:
    """Seção `portfolio` do model: tudo calculado aqui, sem LLM; as views só formatam."""
    gp = gaps(state, today)
    gaps_by_proc = {g["id"]: g["gaps"] for g in gp["processes"]}
    opps = list(state.opportunities.values())
    procs = []
    for p in sorted(state.processes.values(), key=lambda p: p.id):
        procs.append({
            "id": p.id, "title": p.title, "area": p.area, "status": p.status, "owner": p.owner,
            "owner_name": state.person_name(p.owner) if p.owner else None,
            "executors": p.executors, "executor_names": [state.person_name(x) for x in p.executors],
            "recurrence": p.recurrence, "per_month": p.per_month, "duration_min": p.duration_min,
            "hours_month": p.hours_month, "tools": p.tools, "io": p.io, "pains": p.pains,
            "maturity": p.maturity, "notes": p.notes, "docs": [_doc(d) for d in p.docs],
            "playbook": _doc(p.playbook) if p.playbook else None, "gaps": gaps_by_proc.get(p.id, []),
            "retired_reason": p.retired_reason, "source": p.source, "prov": p.prov,
            "added": _iso(p.added), "last_activity": _iso(p.last_activity),
            "opportunities": [o.id for o in opps if o.process == p.id]})
    out_opps = []
    for o in sorted(opps, key=lambda o: o.id):
        out_opps.append({
            "id": o.id, "title": o.title, "area": o.area, "process": o.process, "kind": o.kind,
            "problem": o.problem, "suggestion": o.suggestion, "gain": o.gain, "hours_saved": gain_hours(o, state),
            "status": o.status, "impact": o.impact, "confidence": o.confidence, "ease": o.ease,
            "score": o.score, "ice_suggested": o.ice_suggested, "ice_reason": o.ice_reason,
            "quadrant": quadrant(o), "goal": o.goal, "goal_title": plan.title(o.goal) if o.goal else None,
            "project": o.project, "project_title": plan.title(o.project) if o.project else None,
            "project_progress": plan.progress(o.project) if o.project and o.project in plan.projects else None,
            "deliverable": o.deliverable, "deliverable_title": plan.title(o.deliverable) if o.deliverable else None,
            "promoted": o.promoted,
            "people": o.people, "people_names": [state.person_name(x) for x in o.people], "notes": o.notes,
            "evidence": o.evidence, "evidence_count": o.evidence_count,
            "docs": [_doc(d) for d in o.docs],
            "status_history": [{**h, "date": _iso(h["date"])} for h in o.status_history],
            "source": o.source, "prov": o.prov, "by": o.by,
            "added": _iso(o.added), "last_activity": _iso(o.last_activity)})
    return {
        "areas": [{"id": a.id, "name": a.name, "aliases": a.aliases, "note": a.note,
                   "processes": sum(1 for p in state.processes.values() if p.area == a.id and p.status == "ativo"),
                   "opportunities": sum(1 for o in opps if o.area == a.id)} for a in state.areas.values()],
        "processes": procs, "opportunities": out_opps, "gaps": gp,
        "funnel": funnel(opps),
        "matrix": {q: [o.id for o in v] for q, v in matrix(opps).items()},
        "by_area": {k: [o.id for o in v] for k, v in by_area(opps).items()},
        "by_goal": {k: [o.id for o in v] for k, v in by_goal(opps).items()},
        "ranking": [o.id for o in sorted((o for o in opps if o.score is not None and o.status not in CLOSED),
                                         key=lambda o: (-o.score, o.id))],
        "counts": {"opportunities": len(opps), "prioritized": sum(1 for o in opps if o.status == "priorizada"),
                   "processes": sum(1 for p in state.processes.values() if p.status == "ativo"),
                   "gaps": gp["total"]},
    }
