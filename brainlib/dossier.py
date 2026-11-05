"""Dossiê determinístico (Fase 5 do plano da memória) — o substituto honesto dos mental
models quando não há LLM: a página "onde estamos com X" é MONTADA na hora da leitura,
a partir de fontes citáveis — sem síntese pré-computada, nunca velha.

Três camadas, toda com fonte:
  1. Ficha da entidade — índice SQLite (estado de hoje);
  2. Decisões e entregas ligadas — edges do índice (texto integral do DEC/WIN);
  3. Melhores trechos do banco com as tags da entidade (pessoa:/proj:/goal:) —
     só com a memória ligada; sem servidor, o dossiê vale com as duas primeiras.

Não vira arquivo do FRESH: montado na leitura, como o render deriva views.
"""
from __future__ import annotations

import re
import sqlite3

from . import ids, index, util

PLANNING_PREFIXES = ("GOAL", "PROJ")
PERSON_KINDS = {"person": "pessoa", "project": "projeto", "goal": "goal"}


def _resolve(con, ref: str) -> tuple[str, str] | None:
    """(kind, id) — entidade do PLANNING/ledger ou pessoa por alias; None se não acha."""
    norm = ids.normalize(ref)
    if isinstance(norm, str):
        m = re.match(r"^[A-Z]+", norm)
        pre = m.group(0) if m else ""
        if pre in PLANNING_PREFIXES:
            if con.execute("SELECT 1 FROM planning WHERE id = ?", (norm,)).fetchone():
                return ("goal" if pre == "GOAL" else "project"), norm
            return None                              # GOAL-/PROJ- inexistente: não cai no alias
        if pre == "DEC":
            if con.execute("SELECT 1 FROM decisions WHERE id = ?", (norm,)).fetchone():
                return "decision", norm
            return None
    # não é entidade com prefixo conhecido: pessoa por alias (ou id) — normalize passa
    # strings soltas adiante, por isso o fallthrough é o caminho normal de nomes
    row = con.execute("SELECT person_id FROM aliases WHERE alias_fold = ?", (util.fold(ref),)).fetchone()
    if row:
        return "person", row[0]
    row = con.execute("SELECT id FROM people WHERE id = ?", (util.fold(ref),)).fetchone()
    if row:
        return "person", row[0]
    return None


def _project_scope(con, kind: str, eid: str) -> list[str]:
    """Projetos no escopo: o próprio (PROJ) ou todos os projetos do goal (GOAL)."""
    if kind == "project":
        return [eid]
    return [r[0] for r in con.execute("SELECT id FROM planning WHERE kind = 'project' AND parent = ?", (eid,))]


def _decisions_win(con, kind: str, eid: str, limit: int = 6) -> tuple[list[dict], list[dict]]:
    decs, wins = [], []
    if kind == "person":
        dec_rows = con.execute(
            "SELECT id, title, date, status, project, rationale FROM decisions d "
            "JOIN edges e ON e.src = d.id AND e.rel = 'decided_by' WHERE e.dst = ? "
            "ORDER BY date DESC LIMIT ?", (eid, limit)).fetchall()
        win_rows = con.execute(
            "SELECT w.id, w.title, w.date, w.result FROM deliveries w "
            "JOIN edges ea ON ea.src = w.ref AND ea.rel = 'owner' WHERE ea.dst = ? "
            "ORDER BY w.date DESC LIMIT ?", (eid, limit)).fetchall()
    else:
        scope = _project_scope(con, kind, eid)
        if not scope:
            return decs, wins
        qmarks = ",".join("?" * len(scope))
        dec_rows = con.execute(
            f"SELECT id, title, date, status, project, rationale FROM decisions "
            f"WHERE project IN ({qmarks}) ORDER BY date DESC LIMIT ?", (*scope, limit)).fetchall()
        win_rows = con.execute(
            f"SELECT w.id, w.title, w.date, w.result FROM deliveries w "
            f"JOIN edges ep ON ep.src = w.ref AND ep.rel = 'project' "
            f"WHERE ep.dst IN ({qmarks}) ORDER BY w.date DESC LIMIT ?", (*scope, limit)).fetchall()
    for r in dec_rows:
        decs.append({"id": r[0], "title": r[1], "date": r[2], "status": r[3],
                     "project": r[4], "rationale": r[5], "source": f"ledger/{r[0]}"})
    for r in win_rows:
        wins.append({"id": r[0], "title": r[1], "date": r[2], "result": r[3],
                     "source": f"ledger/{r[0]}"})
    return decs, wins


def _chunks(brain, kind: str, eid: str, name: str, hs, limit: int = 5) -> list[dict]:
    """Melhores trechos do banco com as tags da entidade — memória ligada e servidor no ar."""
    from . import memory
    if hs is None:
        try:
            if memory.mode(brain.inst.cfg["memory"]) == "none":
                return []
            hs = memory.client(brain)
        except Exception:                                       # noqa: BLE001 — sem servidor: só as 2 primeiras camadas
            return []
    tags = {f"pessoa:{eid}"} if kind == "person" else {f"proj:{eid}"}
    if kind == "goal":
        tags = {f"goal:{eid}"}
    try:
        res = hs.recall(brain.inst.cfg["memory"]["bank"], name, tags=sorted(tags))
    except util.BrainError:
        return []
    out = []
    for r in (res.get("results") or [])[:limit]:
        text = " ".join((r.get("text") or "").split())
        if not text:
            continue
        out.append({"text": text[:400] + ("…" if len(text) > 400 else ""),
                    "doc": r.get("document_id") or "?",
                    "date": (r.get("occurred_start") or "")[:10] or None})
    return out


def build(brain, ref: str, hs=None) -> dict:
    """Dossiê da entidade (Fase 5). Levanta BrainError se não resolver o ref."""
    db = index.db_path(brain.inst)
    if not db.exists():
        raise util.BrainError("índice SQLite ausente — rode `brain index rebuild` "
                              "(ou `brain render`) antes do dossiê", code=1)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
    try:
        con.execute("PRAGMA busy_timeout=2000")
        con.execute("PRAGMA query_only=1")
        resolved = _resolve(con, ref)
        if resolved is None:
            raise util.BrainError(f"não consta: {ref!r} não é entidade nem pessoa do índice", code=1)
        kind, eid = resolved
        out: dict = {"ref": ref, "kind": kind, "id": eid}
        if kind == "person":
            row = con.execute("SELECT name, role, relation, email FROM people WHERE id = ?", (eid,)).fetchone()
            out["ficha"] = ({"id": eid, "name": row[0], "role": row[1], "relation": row[2], "email": row[3]}
                            if row else {"id": eid})
            open_actions = con.execute(
                "SELECT id, title, due, is_overdue FROM actions WHERE owner = ? AND is_open = 1 "
                "ORDER BY is_overdue DESC, due LIMIT 5", (eid,)).fetchall()
            out["open_actions"] = [{"id": r[0], "title": r[1], "due": r[2], "overdue": bool(r[3])}
                                   for r in open_actions]
            name = (row[0] if row else eid)
        else:
            row = con.execute("SELECT title, status, parent, progress FROM planning WHERE id = ?", (eid,)).fetchone()
            out["ficha"] = ({"id": eid, "title": row[0], "status": row[1], "parent": row[2],
                             "progress": row[3], "source": f"PLANNING/goals.md"}
                            if row else {"id": eid})
            name = row[0] if row else eid
        out["decisions"], out["deliveries"] = _decisions_win(con, kind, eid)
        out["chunks"] = _chunks(brain, kind, eid, name, hs)
        return out
    finally:
        con.close()


def render(d: dict) -> str:
    """Markdown compacto — todo parágrafo com fonte."""
    f = d["ficha"]
    L = [f"# Dossiê — {f.get('name') or f.get('title') or d['id']} ({d['kind']}, {d['id']})"]
    L.append("")
    if d["kind"] == "person":
        L.append(f"Papel: {f.get('role') or '—'} · relação: {f.get('relation') or '—'} · "
                 f"e-mail: {f.get('email') or '—'}  ⟶ ledger/person/{d['id']}")
        if d.get("open_actions"):
            L.append("")
            L.append("Ações abertas:")
            for a in d["open_actions"]:
                flag = " ⚠ atrasada" if a["overdue"] else ""
                L.append(f"- {a['id']} · {a['title']}" + (f" · vence {a['due']}" if a["due"] else "")
                         + f"{flag} ⟶ ledger/{a['id']}")
    else:
        pct = f"{(f.get('progress') or 0):.0%}" if f.get("progress") is not None else "—"
        L.append(f"Status: {f.get('status') or '—'} · progresso {pct}  ⟶ PLANNING/goals.md")
    if d["decisions"]:
        L.append("")
        L.append("Decisões:")
        for dec in d["decisions"]:
            L.append(f"- {dec['date']} · {dec['title']} ({dec['status']})"
                     + (f" — {dec['rationale']}" if dec.get("rationale") else "")
                     + f"  ⟶ {dec['source']}")
    if d["deliveries"]:
        L.append("")
        L.append("Entregas:")
        for w in d["deliveries"]:
            L.append(f"- {w['date']} · {w['title']}"
                     + (f" — {w['result']}" if w.get("result") else "") + f"  ⟶ {w['source']}")
    if d["chunks"]:
        L.append("")
        L.append("Na memória (trechos):")
        for c in d["chunks"]:
            when = f", {c['date']}" if c["date"] else ""
            L.append(f"- {c['text']}  ⟶ {c['doc']}{when}")
    elif d["kind"] == "person" and not d["decisions"] and not d.get("open_actions"):
        L.append("")
        L.append("Sem decisões, entregas nem trechos indexados — só a ficha (não inventa).")
    L.append("")
    L.append("*Montado agora pelo índice + memória (Fase 5) — nada pré-computado.*")
    return "\n".join(L)
