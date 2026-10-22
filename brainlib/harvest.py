"""Colheita: edições do dono em superfícies derivadas viram eventos declarados.

FRESH é regenerado inteiro a cada render — então, ANTES de sobrescrever, olhamos
o que o dono mudou desde o último render:
  · checkbox de ação em FRESH/todo.md            → fechar / reabrir
  · `status:` de FRESH/records/actions/A-*.md     → ficha da ação (qualquer editor)
  · `status:` de FRESH/records/opportunities/OPP-*.md → status da oportunidade (valor inválido: aviso, não grava)
  · checkbox de entregável em PLANNING/goals.md   → estado factual do entregável
Só essas mudanças são colhidas; qualquer outra edição em FRESH é descartada.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import util

STATE_FILE = ".render-state.json"
TODO_LINE = re.compile(r"^\s*-\s+\[( |x|X)\]\s+.*?\b(A-\d{4,})\b")
FRONT_STATUS = re.compile(r"^status:\s*\"?([^\"\n]+?)\"?\s*$", re.M)

KANBAN_TO_EVENT = {
    "feita": ("action.closed", {"how": "marcada como feita na ficha (status)"}),
    "descartada": ("action.dropped", {"reason": "descartada na ficha (status)"}),
    "fazendo": ("action.updated", {"status": "fazendo", "note": "movida para fazendo (status)"}),
    "a fazer": ("action.updated", {"status": "aberta", "note": "movida para a fazer (status)"}),
    "aguardando": ("action.updated", {"status": "aguardando", "note": "movida para aguardando (status)"}),
}


def load_state(fresh: Path) -> dict:
    return util.read_json(fresh / STATE_FILE, {})


def _owner_event(t: str, aid: str, data: dict, source: str) -> dict:
    return {"type": t, "id": aid, "by": "owner", "prov": "declarado", "source": source, "data": data}


def _opportunity_events(brain, last: dict, notices: list[dict]) -> list[dict]:
    from .schema import OPP_REASON_STATUS, OPP_STATUS
    out = []
    rec_dir = brain.inst.fresh / "records" / "opportunities"
    for path in sorted(rec_dir.glob("OPP-*.md")) if rec_dir.exists() else []:
        oid = path.stem
        o = brain.state.opportunities.get(oid)
        prev = last.get("records", {}).get(oid)
        m = FRONT_STATUS.search(path.read_text(encoding="utf-8"))
        if not o or not m or prev is None:
            continue
        now_val = util.fold(m.group(1))
        if now_val == util.fold(prev) or now_val == o.status:
            continue
        src = f"FRESH/records/opportunities/{oid}.md"
        if now_val not in OPP_STATUS:
            notices.append({"level": "warn", "title": "ficha", "detail": f"{oid}: status '{m.group(1)}' inválido — "
                            f"nada gravado (use {', '.join(sorted(OPP_STATUS))})"})
        elif now_val == "em-andamento" and not o.project:
            notices.append({"level": "warn", "title": "ficha", "detail": f"{oid}: 'em-andamento' só depois de promover "
                            "(`brain opportunity promote`) — nada gravado"})
        else:
            data = {"status": now_val}
            if now_val in OPP_REASON_STATUS:
                data["reason"] = "alterado na ficha (status)"
            out.append(_owner_event("opportunity.status", oid, data, src))
    return out


def collect(brain, notices: list[dict] | None = None) -> list[dict]:
    st = brain.state
    fresh = brain.inst.fresh
    last = load_state(fresh)
    events: list[dict] = []
    touched: set[str] = set()

    rec_dir = fresh / "records" / "actions"
    for path in sorted(rec_dir.glob("A-*.md")) if rec_dir.exists() else []:
        aid = path.stem
        a = st.actions.get(aid)
        prev = last.get("records", {}).get(aid)
        m = FRONT_STATUS.search(path.read_text(encoding="utf-8"))
        if not a or not m or prev is None:
            continue
        now_val = util.fold(m.group(1))
        if now_val == util.fold(prev) or now_val not in KANBAN_TO_EVENT:
            continue
        t, data = KANBAN_TO_EVENT[now_val]
        src = f"FRESH/records/actions/{aid}.md"
        if t == "action.updated" and not a.open:
            events.append(_owner_event("action.reopened", aid, {"reason": data["note"]}, src))
        if t == "action.closed" and not a.open:
            continue
        if t == "action.dropped" and not a.open:
            continue
        events.append(_owner_event(t, aid, dict(data), src))
        touched.add(aid)

    todo = fresh / "todo.md"
    if todo.exists():
        prev_todo = last.get("todo", {})
        for ln in todo.read_text(encoding="utf-8").splitlines():
            m = TODO_LINE.match(ln)
            if not m:
                continue
            checked, aid = m.group(1) in "xX", m.group(2)
            a = st.actions.get(aid)
            if not a or aid in touched or aid not in prev_todo or prev_todo[aid] == checked:
                continue
            if checked and a.open:
                events.append(_owner_event("action.closed", aid, {"how": "marcada como feita em todo.md"},
                                           "FRESH/todo.md"))
            elif not checked and not a.open:
                events.append(_owner_event("action.reopened", aid, {"reason": "desmarcada em todo.md"},
                                           "FRESH/todo.md"))
            touched.add(aid)

    events += _opportunity_events(brain, last, notices if notices is not None else [])

    plan = brain.plan
    for did, d in plan.deliverables.items():
        hist = st.deliverable_events.get(did, [])
        known = hist[-1]["data"]["status"] if hist else "nao-iniciado"
        if d.status != known:
            ev = {"type": "deliverable.updated", "id": did, "by": "owner", "prov": "declarado",
                  "source": "PLANNING/goals.md (edição manual)", "data": {"status": d.status}}
            if d.status == "feito" and d.done_date:
                ev["date"] = d.done_date.isoformat()
            events.append(ev)
    return events


def run(brain, notices: list[dict] | None = None) -> list[dict]:
    events = collect(brain, notices)
    return brain.record(events) if events else []


def save_state(fresh: Path, todo: dict[str, bool], records: dict[str, str]) -> None:
    util.write_json(fresh / STATE_FILE, {"rendered_at": util.iso_now(), "todo": todo, "records": records})
