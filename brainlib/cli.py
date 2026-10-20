"""`brain` — a única porta de escrita do livro-razão e o motor das views.

Códigos de saída: 0 ok · 1 uso · 2 ambíguo · 3 não encontrado · 4 validação · 5 ledger corrompido.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, config, people, planning, util
from .core import Brain


def _out(args, payload, human: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(human)


def _common(ev: dict, args) -> dict:
    for f in ("by", "prov", "source", "date", "actor"):
        v = getattr(args, f, None)
        if v:
            ev[f] = v
    return ev


def _fact_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--by", choices=["owner", "agent", "system"], default="agent",
                   help="quem registra: owner (declaração do dono) | agent (extração)")
    p.add_argument("--prov", choices=["doc", "observado", "declarado", "sem-fonte"],
                   help="proveniência (obrigatória para --by agent)")
    p.add_argument("--source", help="artefato/RAW de origem (caminho relativo ao vault) ou 'chat'")
    p.add_argument("--date", help="quando aconteceu no mundo (AAAA-MM-DD; padrão: hoje)")
    p.add_argument("--actor", help="quem fez, no mundo (id de pessoa)")
    p.add_argument("--json", action="store_true")


def _resolve_people(b: Brain, values: list[str]) -> list[str]:
    out = []
    for v in util.split_csv(values):
        if v in b.state.people:
            out.append(v)
            continue
        cands = people.resolve(b.state, v)
        if len(cands) == 1:
            out.append(cands[0])
        elif not cands:
            raise util.BrainError(f"pessoa '{v}' não encontrada — `brain person add` primeiro", code=3)
        else:
            raise util.BrainError(f"'{v}' é ambíguo: {', '.join(cands)} — pergunte ao dono", code=2)
    return out


def _effort(b: Brain, v):
    if v is None:
        return None
    return util.parse_duration(v)


# ── comandos ────────────────────────────────────────────────────────────────
def cmd_init(args, b: Brain) -> None:
    from . import upstream
    inst = b.inst
    created = upstream.seed_template(inst)
    upstream.hook(inst, "install")
    inst.config_dir.mkdir(parents=True, exist_ok=True)
    for name in ("brain.toml", "watch.toml", ".env"):
        dst = inst.config_dir / name
        src = inst.config_dir / f"{name}.example"
        if not dst.exists() and src.exists():
            text = src.read_text(encoding="utf-8")
            if name == "brain.toml" and args.owner_id:
                text = text.replace('id = "eu"', f'id = "{args.owner_id}"', 1)
                if args.owner_name:
                    text = text.replace('name = "Dono do cérebro"', f'name = "{args.owner_name}"', 1)
            dst.write_text(text, encoding="utf-8")
            if name == ".env":
                dst.chmod(0o600)
            created.append(f"config/{name}")
    if args.owner_id:
        b.inst = config.load(inst.root)
        b.reload()
        if args.owner_id not in b.state.people:
            b.record_one({"type": "person.added", "id": args.owner_id, "by": "owner",
                          "data": {"name": args.owner_name or args.owner_id,
                                   "aliases": util.split_csv(args.alias), "email": args.email or "",
                                   "relation": "dono do cérebro"}})
            created.append(f"pessoa: {args.owner_id}")
    print("✓ instância pronta" + (":\n  " + "\n  ".join(created) if created else " (nada a criar)"))


def cmd_person(args, b: Brain) -> None:
    st = b.state
    if args.pcmd == "add":
        ev = b.record_one(_common({"type": "person.added", "id": args.id, "data": {
            "name": args.name, "aliases": util.split_csv(args.alias), "role": args.role,
            "relation": args.relation, "email": args.email}}, args))
        _out(args, ev, f"✓ pessoa {ev['id']} · {args.name}")
    elif args.pcmd == "alias":
        ev = b.record_one(_common({"type": "person.updated", "id": args.id,
                                   "data": {"aliases_add": util.split_csv(args.aliases)}}, args))
        _out(args, ev, f"✓ {args.id} +aliases: {', '.join(util.split_csv(args.aliases))}")
    elif args.pcmd == "update":
        ev = b.record_one(_common({"type": "person.updated", "id": args.id, "data": {
            "name": args.name, "role": args.role, "relation": args.relation, "email": args.email}}, args))
        _out(args, ev, f"✓ {args.id} atualizado")
    elif args.pcmd == "merge":
        ev = b.record_one(_common({"type": "person.merged", "id": args.id,
                                   "data": {"into": args.into, "reason": args.reason}}, args))
        _out(args, ev, f"✓ {args.id} fundida em {args.into}")
    elif args.pcmd == "resolve":
        cands = people.resolve(st, args.text)
        payload = [{"id": c, "name": st.people[c].name, "role": st.people[c].role} for c in cands]
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False))
        elif not cands:
            print(f"não encontrado: {args.text}")
        else:
            for c in payload:
                print(f"{c['id']}\t{c['name']}\t{c['role']}")
        if not cands:
            raise SystemExit(3)
        if len(cands) > 1:
            raise SystemExit(2)
    elif args.pcmd == "list":
        rows = [{"id": p.id, "name": p.name, "aliases": p.aliases, "role": p.role, "relation": p.relation}
                for p in st.people.values()]
        _out(args, rows, "\n".join(f"{r['id']:<22} {r['name']} · {r['role'] or '—'} · "
                                   f"aliases: {', '.join(r['aliases']) or '—'}" for r in rows) or "(ninguém)")


def _action_line(b: Brain, aid: str) -> str:
    a = b.state.actions[aid]
    bits = [a.id, b.state.effective_status(a), a.title, f"dono: {b.state.person_name(a.owner)}"]
    if a.due:
        bits.append(f"prazo {a.due.isoformat()}")
    if a.effort_min:
        bits.append(f"esforço {util.fmt_duration(a.effort_min)}")
    if a.project:
        bits.append(a.project)
    if a.list != "mine":
        bits.append(a.list)
    return " · ".join(bits)


def cmd_action(args, b: Brain) -> None:
    c = args.acmd
    if c == "open":
        owner = _resolve_people(b, [args.owner])[0] if args.owner else b.owner
        lst = args.list or ("mine" if owner == b.owner else "waiting")
        ev = b.record_one(_common({"type": "action.opened", "data": {
            "title": args.title, "owner": owner, "list": lst, "due": args.due,
            "effort_min": _effort(b, args.effort), "project": args.project, "deliverable": args.deliverable,
            "blocked_by": util.split_csv(args.blocked_by), "unblocks": util.split_csv(args.unblocks),
            "people": _resolve_people(b, args.people or []), "priority": args.priority,
            "link": args.link, "origin": args.origin}}, args))
        _out(args, ev, "✓ " + _action_line(b, ev["id"]))
    elif c == "update":
        data = {"note": args.note, "status": args.status, "due": args.due, "list": args.list,
                "effort_min": _effort(b, args.effort), "project": args.project,
                "deliverable": args.deliverable, "priority": args.priority, "title": args.title}
        if args.owner:
            data["owner"] = _resolve_people(b, [args.owner])[0]
        if args.blocked_by is not None:
            data["blocked_by"] = util.split_csv(args.blocked_by)
        if args.unblocks is not None:
            data["unblocks"] = util.split_csv(args.unblocks)
        if args.people:
            data["people_add"] = _resolve_people(b, args.people)
        clean = {k: v for k, v in data.items() if v not in (None, "", [])}
        if args.clear_due:
            clean.pop("due", None)
            clean["clear"] = ["due"]
        ev = b.record_one(_common({"type": "action.updated", "id": args.id, "data": clean}, args))
        _out(args, ev, "✓ " + _action_line(b, args.id))
    elif c == "close":
        _close_action(args, b)
    elif c in ("drop", "reopen"):
        ev = b.record_one(_common({"type": f"action.{'dropped' if c == 'drop' else 'reopened'}",
                                   "id": args.id, "data": {"reason": args.reason}}, args))
        _out(args, ev, "✓ " + _action_line(b, args.id))
    elif c == "show":
        from . import model
        m = model.ModelBuilder(b)
        a = b.state.actions.get(args.id)
        if a is None:
            raise util.BrainError(f"{args.id} não existe", code=3)
        view = m.action(a)
        if getattr(args, "json", False):
            print(json.dumps(view, ensure_ascii=False, indent=2))
        else:
            print(_action_line(b, args.id))
            for h in view["history"]:
                print(f"  {h['date']} · {h['type']} · {h['note']}")
    elif c == "list":
        from . import model
        m = model.ModelBuilder(b)
        rows = [m.action(a) for a in b.state.actions.values()]
        if args.list:
            rows = [r for r in rows if r["list"] == args.list]
        if args.project:
            rows = [r for r in rows if r["project"] == args.project]
        if args.owner:
            pid = _resolve_people(b, [args.owner])[0]
            rows = [r for r in rows if r["owner"] == pid]
        if not args.all:
            rows = [r for r in rows if r["open"]]
        rows.sort(key=lambda r: (r["due"] or "9999", r["id"]))
        _out(args, rows, "\n".join(_action_line(b, r["id"]) for r in rows) or "(nenhuma)")


def _close_action(args, b: Brain) -> None:
    st = b.state
    a = st.actions.get(args.id)
    if a is None:
        raise util.BrainError(f"{args.id} não existe", code=3)
    events = [_common({"type": "action.closed", "id": args.id,
                       "data": {"how": args.how or "concluída", "outcome": args.outcome}}, args)]
    for other in st.actions.values():
        if other.open and other.id != args.id and args.id in other.blocked_by:
            others = [x for x in st.blocked(other) if x != args.id]
            events.append({"type": "action.updated", "id": other.id, "by": "system",
                           "date": args.date, "data": {"note": f"desbloqueada ({args.id} fechada)"
                                                       if not others else
                                                       f"{args.id} fechada; ainda bloqueada por {', '.join(others)}"}})
    for ref in a.unblocks:
        if ref in st.actions and st.actions[ref].open and args.id not in st.actions[ref].blocked_by:
            events.append({"type": "action.updated", "id": ref, "by": "system", "date": args.date,
                           "data": {"note": f"{args.id} (que a destravava) foi fechada"}})
    delivered = args.delivery or (args.outcome and (a.project or a.deliverable or a.unblocks))
    if delivered:
        events.append(_common({"type": "delivery.recorded", "data": {
            "title": args.delivery_title or a.title, "ref": args.id, "result": args.outcome,
            "evidence": args.evidence}}, args))
    recorded = b.record(events)
    lines = ["✓ " + _action_line(b, args.id)]
    for ev in recorded[1:]:
        if ev["type"] == "action.updated":
            lines.append(f"  ↳ {ev['id']}: {ev['data']['note']}")
        elif ev["type"] == "delivery.recorded":
            lines.append(f"  ↳ entrega {ev['id']} registrada")
    if b.state.focus_plans:
        lines.append("  (blocos de foco futuros desta ação saem no próximo `brain focus sync`)")
    _out(args, recorded, "\n".join(lines))


def cmd_decision(args, b: Brain) -> None:
    if args.dcmd == "add":
        ev = b.record_one(_common({"type": "decision.made", "data": {
            "title": args.title, "decided_by": _resolve_people(b, args.decided_by),
            "project": args.project, "context": args.context, "rationale": args.rationale,
            "supersedes": args.supersedes}}, args))
        names = ", ".join(b.state.person_name(p) for p in ev["data"]["decided_by"])
        _out(args, ev, f"✓ {ev['id']} · {args.title} · decidido por {names} · {ev['date']}")
    elif args.dcmd == "supersede":
        ev = b.record_one(_common({"type": "decision.superseded", "id": args.id,
                                   "data": {"by": args.by_decision, "reason": args.reason}}, args))
        _out(args, ev, f"✓ {args.id} substituída")
    elif args.dcmd == "list":
        from . import model
        m = model.ModelBuilder(b)
        rows = sorted((m.decision(d) for d in b.state.decisions.values()), key=lambda d: d["date"] or "",
                      reverse=True)
        if args.project:
            rows = [r for r in rows if r["project"] == args.project]
        _out(args, rows, "\n".join(f"{r['id']} · {r['date']} · {r['title']} · {', '.join(r['decided_by_names'])}"
                                   f" · {r['status']}" for r in rows) or "(nenhuma)")


def cmd_delivery(args, b: Brain) -> None:
    ev = b.record_one(_common({"type": "delivery.recorded", "data": {
        "title": args.title, "ref": args.ref, "result": args.result, "evidence": args.evidence,
        "impact": args.impact}}, args))
    _out(args, ev, f"✓ {ev['id']} · entrega: {args.title}")


def cmd_artifact(args, b: Brain) -> None:
    ev = b.record_one(_common({"type": "artifact.added", "id": args.path, "data": {
        "kind": args.kind, "title": args.title, "raw": args.raw, "summary": args.summary,
        "people": _resolve_people(b, args.people or []), "projects": util.split_csv(args.projects)}}, args))
    _out(args, ev, f"✓ artefato {ev['id']} ({args.kind})")


def cmd_proposal(args, b: Brain) -> None:
    if args.rcmd == "add":
        ev = b.record_one(_common({"type": "proposal.opened", "data": {
            "kind": args.kind, "summary": args.summary, "target": args.target,
            "evidence": args.evidence}}, args))
        _out(args, ev, f"✓ {ev['id']} · proposta ({args.kind}): {args.summary}")
    elif args.rcmd in ("accept", "reject"):
        t = "proposal.accepted" if args.rcmd == "accept" else "proposal.rejected"
        ev = b.record_one({"type": t, "id": args.id, "by": "owner", "data": {"quote": args.quote}})
        _out(args, ev, f"✓ {args.id} {'aceita' if args.rcmd == 'accept' else 'rejeitada'} ({args.quote!r})")
    elif args.rcmd == "list":
        rows = [p.__dict__ for p in b.state.proposals.values() if args.all or p.status == "aberta"]
        _out(args, rows, "\n".join(f"{p['id']} · {p['kind']} · {p['summary']} · alvo {p['target'] or '—'}"
                                   for p in rows) or "(nenhuma aberta)")


def cmd_plan(args, b: Brain) -> None:
    inst = b.inst
    if args.plcmd == "show":
        from . import model
        mdl = model.build(b)
        if getattr(args, "json", False):
            print(json.dumps({"goals": mdl["goals"], "projects": mdl["projects"],
                              "warnings": b.plan.warnings}, ensure_ascii=False, indent=2))
            return
        for g in mdl["goals"]:
            print(f"{g['id']} {g['title']} · {g['status']} · {planning.format_progress(g['progress'])}"
                  f" · {g['health_label']}")
            for pid in g["projects"]:
                p = next(x for x in mdl["projects"] if x["id"] == pid)
                print(f"   {pid} {p['title']} · {planning.format_progress(p['progress'])} · {p['health']['label']}"
                      f" — {p['health']['reason']}")
        for w in b.plan.warnings:
            print(f"⚠ {w}")
    elif args.plcmd == "deliverable":
        when = util.parse_date(args.date) or util.today()
        changed = planning.set_deliverable(inst.planning_file, args.id, args.status,
                                           when if args.status == "feito" else None)
        b.reload()
        ev = b.record_one(_common({"type": "deliverable.updated", "id": args.id,
                                   "data": {"status": args.status, "evidence": args.evidence}}, args))
        _append_plan_log(inst, f"{util.today().isoformat()} · {args.id} estado → {args.status} · "
                               f"factual (sem mudança de estrutura) · evidência: {args.evidence or '—'}")
        _out(args, ev, f"✓ {args.id} → {args.status}" + ("" if changed else " (goals.md já estava assim)"))
    elif args.plcmd.startswith("add-"):
        _plan_add(args, b)
    elif args.plcmd == "log":
        ev = b.record_one({"type": "plan.changed", "by": "owner", "data": {
            "diff": args.diff, "reason": args.reason, "evidence": args.evidence, "approval": args.approval}})
        _append_plan_log(inst, f"{util.today().isoformat()} · {args.diff} · {args.reason} · "
                               f"evidência: {args.evidence or '—'} · aprovado: \"{args.approval}\"")
        _out(args, ev, "✓ mudança registrada em PLANNING/log.md e no ledger")


def _plan_add(args, b: Brain) -> None:
    """Cria goal/projeto (gate: exige --approval do dono, vira plan.changed + PLANNING/log.md) ou entregável (sem gate)."""
    inst, kind = b.inst, args.plcmd.removeprefix("add-")
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError(f"plan {args.plcmd}: proibido no noturno — a árvore é do dono, que precisa estar presente", code=4)
    plan, today = b.plan, util.today().isoformat()
    if kind == "goal":
        nid, what = planning.next_goal_id(plan), f"goal criado: {args.title}"
        reason = args.reason or args.why or "novo goal"
    elif kind == "project":
        if args.goal not in plan.goals:
            raise util.BrainError(f"goal {args.goal} não existe em PLANNING/goals.md", code=3)
        nid, what = planning.next_project_id(plan), f"projeto criado sob {args.goal}: {args.title}"
        reason = args.reason or f"novo projeto sob {args.goal}"
    else:
        if args.project not in plan.projects:
            raise util.BrainError(f"projeto {args.project} não existe em PLANNING/goals.md", code=3)
        nid = planning.next_deliverable_id(plan, args.project)
    if kind != "deliverable" and not (args.approval or "").strip():
        raise util.BrainError(f"criar {kind} é mudança estrutural: exige --approval com a resposta literal do dono", code=4)
    owner = ""
    if kind == "project" and args.owner:
        owner = _resolve_people(b, [args.owner])[0]
    path = inst.planning_file
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    if kind == "goal":
        planning.add_goal(path, args.title, args.horizon or "", args.why or "")
    elif kind == "project":
        planning.add_project(path, args.goal, args.title, owner)
    else:
        planning.add_deliverable(path, args.project, args.title, args.due or "", args.weight)
    try:
        if kind != "deliverable":
            ev = b.record_one({"type": "plan.changed", "by": "owner", "data": {
                "diff": f"{nid} {what}", "reason": reason, "evidence": args.evidence, "approval": args.approval}})
            _append_plan_log(inst, f"{today} · {nid} {what} · {reason} · evidência: {args.evidence or '—'}"
                                   f" · aprovado: \"{args.approval}\"")
        else:
            ev = {"id": nid}
            _append_plan_log(inst, f"{today} · {nid} entregável criado sob {args.project}: {args.title} · "
                                   "sem gate (não é goal nem projeto)")
    except util.BrainError:
        util.atomic_write(path, before)          # o ledger recusou: o goals.md volta ao que era
        raise
    b.reload()
    _out(args, {"id": nid, "event": ev}, f"✓ {nid} criado em PLANNING/goals.md" + ("" if kind == "deliverable" else " (aprovado, registrado em PLANNING/log.md e no ledger)"))


def _append_plan_log(inst, line: str) -> None:
    path = inst.planning_log
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def cmd_progress(args, b: Brain) -> None:
    ev = b.record_one({"type": "progress.declared", "id": args.node, "by": "owner",
                       "data": {"pct": args.pct, "note": args.note}})
    _out(args, ev, f"✓ {args.node} progresso declarado: {args.pct}%")


def cmd_add(args, b: Brain) -> None:
    raw = Path(args.file).read_text(encoding="utf-8") if args.file and args.file != "-" else sys.stdin.read()
    items = json.loads(raw)
    if isinstance(items, dict):
        items = [items]
    recorded = b.record(items)
    _out(args, recorded, "\n".join(f"✓ {e['type']} {e.get('id', '')}" for e in recorded))


def cmd_validate(args, b: Brain) -> None:
    problems = b.validate_all()
    warnings = b.plan.warnings
    for w in warnings:
        print(f"⚠ PLANNING: {w}")
    for p in problems:
        print(f"✗ {p}")
    for alias, ids in people.alias_collisions(b.state):
        print(f"⚠ alias ambíguo '{alias}': {', '.join(ids)}")
    if not problems:
        print(f"✓ ledger íntegro ({len(b.state.events)} eventos)")
    if problems:
        raise SystemExit(4)


def cmd_status(args, b: Brain) -> None:
    from . import model
    m = model.build(b)
    c = m["counts"]
    inbox = [p for p in b.inst.inbox.glob("*") if p.is_file() and p.name != ".keep.md"]
    payload = {**c, "inbox": len(inbox), "events": len(b.state.events)}
    _out(args, payload,
         f"minhas abertas {c['mine_open']} (atrasadas {c['mine_overdue']}, 7d {c['mine_due_7d']}) · "
         f"aguardando outros {c['waiting_open']} · conquistas 30d {c['wins_30d']} · "
         f"propostas {c['proposals_open']} · rascunhos {c['outbox_pending']} · inbox {len(inbox)}")


def cmd_search(args, b: Brain) -> None:
    from . import search
    hits = search.search(b, args.query, limit=args.limit)
    text = "\n".join(f"[{h['kind']}] {h['id']} · {h['title']} · {h.get('date') or ''}" for h in hits)
    if hits and hits[0].get("match") == "parcial":
        text = "(nenhum resultado com todos os termos — mostrando os que casam com algum)\n" + text
    _out(args, hits, text or "não consta")


def cmd_render(args, b: Brain) -> None:
    from . import render
    report = render.render_all(b, do_harvest=not args.no_harvest)
    _out(args, report, render.summary(report))
    if args.open:
        render.open_dashboard(b)


def cmd_sync(args, b: Brain) -> None:
    from . import harvest
    evs = harvest.run(b)
    _out(args, evs, "\n".join(f"✓ {e['type']} {e['id']} (edição do dono)" for e in evs)
         or "nenhuma edição do dono para colher")


def cmd_focus(args, b: Brain) -> None:
    from . import focus
    focus.cli(args, b)


def cmd_outbox(args, b: Brain) -> None:
    from . import outbox
    outbox.cli(args, b)


def cmd_share(args, b: Brain) -> None:
    from . import share
    share.cli_export(args, b)


def cmd_publish(args, b: Brain) -> None:
    from . import share
    share.cli_publish(args, b)


def cmd_snapshot(args, b: Brain) -> None:
    from . import snapshot
    snapshot.cli(args, b)


def cmd_note(args, b: Brain) -> None:
    from . import notes
    notes.cli(args, b)


def cmd_pdf(args, b: Brain) -> None:
    from . import pdf
    pdf.cli(args, b)


def cmd_video(args, b: Brain) -> None:
    from . import video
    video.cli(args, b)


def cmd_doctor(args, b: Brain) -> None:
    from . import doctor
    doctor.cli(args, b)


def cmd_memory(args, b: Brain) -> None:
    from . import memory
    memory.cli(args, b)


def cmd_mcp(args, b: Brain) -> None:
    from . import mcp_server
    mcp_server.serve(b)


def cmd_nightly(args, b: Brain) -> None:
    from . import runner
    runner.nightly(b, skip_agent=args.skip_agent)


def cmd_schedule(args, b: Brain) -> None:
    from . import runner
    runner.schedule_cli(args, b)


def cmd_backup(args, b: Brain) -> None:
    from . import backup
    backup.cli(args, b)


def cmd_watch(args, b) -> None:
    from . import watch
    watch.cli(args, b)


def cmd_tui(args, b) -> None:
    from . import tui
    tui.cli(args, b)


def cmd_update(args, b) -> None:
    from . import upstream
    upstream.cli_update(args, b)


def cmd_upstream(args, b) -> None:
    from . import upstream
    upstream.cli_upstream(args, b)


# ── parser ──────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="brain", description="Segundo Cérebro v2 — livro-razão, views e portas.")
    ap.add_argument("--version", action="version", version=f"brain {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="semeia o vault a partir de template/ (nunca sobrescreve)")
    p.add_argument("--owner-id")
    p.add_argument("--owner-name")
    p.add_argument("--alias", action="append")
    p.add_argument("--email")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("person", help="pessoas e aliases")
    ps = p.add_subparsers(dest="pcmd", required=True)
    x = ps.add_parser("add")
    x.add_argument("name")
    x.add_argument("--id")
    x.add_argument("--alias", action="append")
    x.add_argument("--role")
    x.add_argument("--relation")
    x.add_argument("--email")
    _fact_opts(x)
    x = ps.add_parser("alias")
    x.add_argument("id")
    x.add_argument("aliases", nargs="+")
    _fact_opts(x)
    x = ps.add_parser("update")
    x.add_argument("id")
    for f in ("--name", "--role", "--relation", "--email"):
        x.add_argument(f)
    _fact_opts(x)
    x = ps.add_parser("merge", help="funde uma ficha duplicada em outra (a duplicada é aposentada)")
    x.add_argument("id", help="ficha duplicada, que deixa de existir")
    x.add_argument("--into", required=True, help="ficha que fica")
    x.add_argument("--reason")
    _fact_opts(x)
    x = ps.add_parser("resolve")
    x.add_argument("text")
    x.add_argument("--json", action="store_true")
    x = ps.add_parser("list")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_person)

    p = sub.add_parser("action", help="ações A-####")
    acs = p.add_subparsers(dest="acmd", required=True)
    x = acs.add_parser("open")
    x.add_argument("title")
    x.add_argument("--owner", help="id/alias do dono da ação (padrão: você)")
    x.add_argument("--list", choices=["mine", "waiting", "watching"])
    x.add_argument("--due")
    x.add_argument("--effort", help="90m · 2h · 1h30 · 1d")
    x.add_argument("--project")
    x.add_argument("--deliverable")
    x.add_argument("--blocked-by")
    x.add_argument("--unblocks")
    x.add_argument("--people", action="append", help="pessoas envolvidas (ids/aliases, vírgula)")
    x.add_argument("--priority", choices=["alta", "normal", "baixa"])
    x.add_argument("--link")
    x.add_argument("--origin")
    _fact_opts(x)
    x = acs.add_parser("update")
    x.add_argument("id")
    x.add_argument("--note")
    x.add_argument("--status", choices=["aberta", "fazendo", "aguardando"])
    x.add_argument("--title")
    x.add_argument("--owner")
    x.add_argument("--list", choices=["mine", "waiting", "watching"])
    x.add_argument("--due")
    x.add_argument("--clear-due", action="store_true")
    x.add_argument("--effort")
    x.add_argument("--project")
    x.add_argument("--deliverable")
    x.add_argument("--blocked-by")
    x.add_argument("--unblocks")
    x.add_argument("--people", action="append")
    x.add_argument("--priority", choices=["alta", "normal", "baixa"])
    _fact_opts(x)
    x = acs.add_parser("close")
    x.add_argument("id")
    x.add_argument("--how")
    x.add_argument("--outcome", help="resultado observável (vira entrega se houver projeto)")
    x.add_argument("--delivery", action="store_true", help="força registro em entregas")
    x.add_argument("--delivery-title")
    x.add_argument("--evidence")
    _fact_opts(x)
    for name in ("drop", "reopen"):
        x = acs.add_parser(name)
        x.add_argument("id")
        x.add_argument("--reason", required=True)
        _fact_opts(x)
    x = acs.add_parser("show")
    x.add_argument("id")
    x.add_argument("--json", action="store_true")
    x = acs.add_parser("list")
    x.add_argument("--list", choices=["mine", "waiting", "watching"])
    x.add_argument("--project")
    x.add_argument("--owner")
    x.add_argument("--all", action="store_true")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_action)

    p = sub.add_parser("decision", help="decisões D-####")
    ds = p.add_subparsers(dest="dcmd", required=True)
    x = ds.add_parser("add")
    x.add_argument("title")
    x.add_argument("--decided-by", action="append", required=True, help="quem decidiu (ids/aliases)")
    x.add_argument("--project")
    x.add_argument("--context")
    x.add_argument("--rationale")
    x.add_argument("--supersedes")
    _fact_opts(x)
    x = ds.add_parser("supersede")
    x.add_argument("id")
    x.add_argument("--by-decision")
    x.add_argument("--reason", required=True)
    _fact_opts(x)
    x = ds.add_parser("list")
    x.add_argument("--project")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_decision)

    p = sub.add_parser("delivery", help="entregas E-#### (conquistas)")
    p.add_argument("title")
    p.add_argument("--ref", help="A-#### / P# / P#.n / G#")
    p.add_argument("--result")
    p.add_argument("--evidence")
    p.add_argument("--impact")
    _fact_opts(p)
    p.set_defaults(fn=cmd_delivery)

    p = sub.add_parser("artifact", help="registra artefato do PROCESSED (idempotência do /dump)")
    p.add_argument("path")
    p.add_argument("--kind", required=True, choices=["reuniao", "documento", "nota", "conector"])
    p.add_argument("--title", required=True)
    p.add_argument("--raw", help="arquivo bruto no RAW (idempotência por fonte)")
    p.add_argument("--people", action="append")
    p.add_argument("--projects")
    p.add_argument("--summary")
    _fact_opts(p)
    p.set_defaults(fn=cmd_artifact)

    p = sub.add_parser("proposal", help="propostas R-#### (o dono aceita/rejeita)")
    rs = p.add_subparsers(dest="rcmd", required=True)
    x = rs.add_parser("add")
    x.add_argument("--kind", required=True,
                   choices=["fechar-acao", "atualizar-acao", "mudar-plano", "reestimar", "outro"])
    x.add_argument("--summary", required=True)
    x.add_argument("--target")
    x.add_argument("--evidence")
    _fact_opts(x)
    for name in ("accept", "reject"):
        x = rs.add_parser(name)
        x.add_argument("id")
        x.add_argument("--quote", required=True, help="a resposta literal do dono")
        x.add_argument("--json", action="store_true")
    x = rs.add_parser("list")
    x.add_argument("--all", action="store_true")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_proposal)

    p = sub.add_parser("plan", help="PLANNING: árvore, estado factual, log do gate")
    pls = p.add_subparsers(dest="plcmd", required=True)
    x = pls.add_parser("show")
    x.add_argument("--json", action="store_true")
    x = pls.add_parser("deliverable")
    x.add_argument("id")
    x.add_argument("--status", required=True, choices=["nao-iniciado", "em-andamento", "feito", "cancelado"])
    x.add_argument("--evidence")
    _fact_opts(x)
    x = pls.add_parser("log", help="registra mudança APROVADA de goal/projeto")
    x.add_argument("--diff", required=True)
    x.add_argument("--reason", required=True)
    x.add_argument("--evidence")
    x.add_argument("--approval", required=True, help="resposta literal do dono (ex.: 'ok')")
    x.add_argument("--json", action="store_true")
    x = pls.add_parser("add-goal", help="cria goal (GATE: exige --approval)")
    x.add_argument("title")
    x.add_argument("--horizon", help="AAAA-MM-DD")
    x.add_argument("--why", help="por quê: o que isto destrava")
    x = pls.add_parser("add-project", help="cria projeto sob um goal (GATE: exige --approval)")
    x.add_argument("goal")
    x.add_argument("title")
    x.add_argument("--owner", help="id ou alias da pessoa dona")
    x = pls.add_parser("add-deliverable", help="cria entregável num projeto (sem gate)")
    x.add_argument("project")
    x.add_argument("title")
    x.add_argument("--due", help="AAAA-MM-DD")
    x.add_argument("--weight", type=int, default=1)
    for x in [pls.choices["add-goal"], pls.choices["add-project"]]:
        x.add_argument("--reason", help="motivo (padrão: derivado)")
        x.add_argument("--evidence")
        x.add_argument("--approval", help="resposta literal do dono (ex.: 'ok')")
    for x in [pls.choices["add-goal"], pls.choices["add-project"], pls.choices["add-deliverable"]]:
        x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("progress", help="progresso DECLARADO pelo dono (G#/P#)")
    p.add_argument("node")
    p.add_argument("pct", type=int)
    p.add_argument("--note")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_progress)

    p = sub.add_parser("add", help="lote de eventos JSON (arquivo ou stdin) — usado pelo /dump")
    p.add_argument("file", nargs="?", default="-")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("validate", help="revalida o ledger inteiro + PLANNING + aliases")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("status", help="contagens rápidas")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("search", help="busca no ledger + artefatos (sem LLM)")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("render", help="colhe edições do dono e regenera TODAS as views (sem LLM)")
    p.add_argument("--no-harvest", action="store_true")
    p.add_argument("--open", action="store_true", help="abre o painel no navegador")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("sync", help="só colhe edições do dono (checkbox/status/goals.md)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("focus", help="planejador de foco + porta do calendário")
    fs = p.add_subparsers(dest="fcmd", required=True)
    x = fs.add_parser("plan")
    x.add_argument("--days", type=int)
    x.add_argument("--busy-file", help="JSON de eventos (snapshot do calendário)")
    x.add_argument("--json", action="store_true")
    x = fs.add_parser("approve")
    x.add_argument("id")
    x.add_argument("--quote", required=True)
    x = fs.add_parser("apply")
    x.add_argument("id")
    x.add_argument("--mode", choices=["google", "ics"])
    x = fs.add_parser("sync")
    x.add_argument("--dry-run", action="store_true")
    x = fs.add_parser("show")
    x.add_argument("id", nargs="?")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_focus)

    p = sub.add_parser("outbox", help="mensagens M-#### (Slack) — rascunho → aprovação → envio")
    os_ = p.add_subparsers(dest="ocmd", required=True)
    x = os_.add_parser("draft")
    x.add_argument("--to", required=True, help="id de pessoa ou #canal (precisa estar na allowlist)")
    x.add_argument("--text", required=True)
    x.add_argument("--ref")
    x.add_argument("--why")
    x.add_argument("--channel", default="slack")
    for name in ("show", "approve", "sent", "failed", "cancel"):
        x = os_.add_parser(name)
        x.add_argument("id")
        if name == "approve":
            x.add_argument("--quote", required=True, help="resposta literal do dono (ex.: 'enviar 1')")
        if name == "sent":
            x.add_argument("--link")
        if name == "failed":
            x.add_argument("--error", required=True)
        if name == "cancel":
            x.add_argument("--reason")
        x.add_argument("--json", action="store_true")
    x = os_.add_parser("list")
    x.add_argument("--all", action="store_true")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_outbox)

    p = sub.add_parser("share", help="exporta página compartilhável (HTML/MD) em vault/reports/share/")
    p.add_argument("kind", choices=["project", "goal", "status", "period"])
    p.add_argument("target", nargs="?", help="P#/G# ou AAAA-MM-DD:AAAA-MM-DD")
    p.add_argument("--format", choices=["html", "md"], default="html")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_share)

    p = sub.add_parser("publish", help="porta de publicação no espaço do time (aprovação por publicação)")
    pbs = p.add_subparsers(dest="pbcmd", required=True)
    x = pbs.add_parser("request")
    x.add_argument("report")
    x.add_argument("--to", required=True, help="slack:#canal | drive:<pasta> (configurado em [publish])")
    x = pbs.add_parser("approve")
    x.add_argument("id")
    x.add_argument("--quote", required=True)
    x = pbs.add_parser("done")
    x.add_argument("id")
    x.add_argument("--link")
    x = pbs.add_parser("cancel")
    x.add_argument("id")
    x = pbs.add_parser("list")
    for sp in pbs.choices.values():
        sp.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("snapshot", help="grava leitura de MCP na inbox (dedup por hash)")
    p.add_argument("--key", required=True, help="identidade estável da fonte (ex.: jira-me)")
    p.add_argument("--prefix", help="prefixo do arquivo (jira, gmail, gcal…)")
    p.add_argument("--ext", default="md", choices=["md", "json", "txt", "csv"])
    p.add_argument("--file", help="conteúdo (padrão: stdin)")
    p.add_argument("--fail", metavar="ERRO", help="registra falha do pull em vez de conteúdo")
    p.add_argument("--item", help="arquivo/subpasta de uma pasta observada (id estável, ex.: id do Drive): hash próprio por item")
    p.add_argument("--rev", help="revisão do item (ex.: modifiedTime do Drive); igual ao último pull = nada a ler")
    p.add_argument("--name", help="nome legível do item (só para o nome do arquivo na inbox)")
    p.add_argument("--check", action="store_true", help="só pergunta se --rev já foi lido (não grava, não lê conteúdo)")
    p.add_argument("--empty", action="store_true",
                   help="a leitura funcionou e a janela não tem nada novo (window=auto): registra o pull sem gravar arquivo")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_snapshot)

    p = sub.add_parser("pdf", help="lê um PDF sem poppler: texto por página ou PNGs (pdftotext/pdftoppm → PDFKit do macOS → pypdf)")
    ps = p.add_subparsers(dest="pcmd", required=True)
    x = ps.add_parser("text", help="texto, com `=== PÁGINA n ===` entre as páginas")
    x.add_argument("file")
    x.add_argument("--pages", help="ex.: 1-3,5 (padrão: todas)")
    x = ps.add_parser("render", help="PNG de cada página, para PDF escaneado (o agente lê a imagem)")
    x.add_argument("file")
    x.add_argument("--pages", help="ex.: 1-3,5 (padrão: todas)")
    x.add_argument("--out", help="pasta de saída (padrão: temporária)")
    x.add_argument("--dpi", type=int, default=110)
    p.set_defaults(fn=cmd_pdf)

    p = sub.add_parser("video", help="analisa vídeo/áudio no dispositivo (macOS 26+): transcrição por idioma e quadros amostrados")
    vs = p.add_subparsers(dest="vcmd", required=True)
    x = vs.add_parser("transcribe", help="texto com `[hh:mm:ss]`; vários idiomas = escolhe o falado em cada minuto")
    x.add_argument("file")
    x.add_argument("--locales", default="pt-BR", help="ex.: pt-BR,es-MX (reunião bilíngue)")
    x.add_argument("--start", type=float, default=0, help="início em segundos")
    x.add_argument("--length", type=float, default=0, help="duração em segundos (padrão: até o fim)")
    x.add_argument("--out", help="grava o texto neste arquivo (padrão: stdout)")
    x = vs.add_parser("frames", help="PNG a cada N segundos (slides, tela compartilhada); o agente lê as imagens")
    x.add_argument("file")
    x.add_argument("--every", type=int, default=150)
    x.add_argument("--width", type=int, default=900)
    x.add_argument("--start", type=float, default=0)
    x.add_argument("--end", type=float, default=0)
    x.add_argument("--out", help="pasta de saída (padrão: temporária)")
    p.set_defaults(fn=cmd_video)

    p = sub.add_parser("note", help="notas avulsas na inbox, com vínculo opcional a A-####/G#/P#/P#.n")
    ns = p.add_subparsers(dest="ncmd", required=True)
    x = ns.add_parser("add", help="cria AAAA…-note.md na inbox (o /dump arquiva)")
    x.add_argument("--link", help="A-#### · G# · P# · P#.n (opcional)")
    x.add_argument("--text", help="texto da nota (padrão: stdin)")
    x.add_argument("--json", action="store_true")
    x = ns.add_parser("edit", help="reescreve o texto de uma nota que ainda está na inbox")
    x.add_argument("path", help="RAW/inbox/….md (relativo ao vault)")
    x.add_argument("--text", help="novo texto (padrão: stdin)")
    x.add_argument("--json", action="store_true")
    x = ns.add_parser("list", help="notas na inbox e no RAW")
    x.add_argument("--link")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("doctor", help="saúde da instância")
    p.add_argument("--json", action="store_true")
    p.add_argument("--online", action="store_true", help="testa também o servidor de memória, se estiver ligado")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("memory", help="camada de memória (Hindsight), alimentada pelo vault")
    ms = p.add_subparsers(dest="mcmd", required=True)
    for name in ("setup", "sync", "rebuild", "status"):
        x = ms.add_parser(name)
        x.add_argument("--json", action="store_true")
        if name in ("sync", "rebuild"):
            x.add_argument("--limit", type=int)
            x.add_argument("--dry-run", action="store_true")
    for name in ("recall", "reflect"):
        x = ms.add_parser(name)
        x.add_argument("query")
        x.add_argument("--bank", choices=["mem", "raw"], default="mem")
        x.add_argument("--tags")
        x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_memory)

    p = sub.add_parser("mcp", help="servidor MCP somente-leitura (stdio) para outras IAs")
    p.set_defaults(fn=cmd_mcp)

    p = sub.add_parser("nightly", help="rotina noturna: render → agente → memória → backup → render")
    p.add_argument("--skip-agent", action="store_true")
    p.set_defaults(fn=cmd_nightly)

    p = sub.add_parser("schedule", help="agenda o noturno (launchd no macOS, crontab nos demais)")
    p.add_argument("action", choices=["install", "remove", "status"])
    p.add_argument("--time", default="05:00")
    p.set_defaults(fn=cmd_schedule)

    p = sub.add_parser("backup", help="zip do vault → Drive (porta do backup)")
    p.add_argument("--status", action="store_true")
    p.add_argument("--local", help="grava o zip numa pasta local em vez do Drive")
    p.set_defaults(fn=cmd_backup)

    p = sub.add_parser("update", help="traz melhorias do framework (git pull seguro) sem tocar no vault")
    p.add_argument("--check", action="store_true", help="só mostra o que há de novo; não altera nada")
    p.add_argument("--rebase", action="store_true", help="re-aplica seus commits locais por cima do upstream")
    p.add_argument("--remote", help="padrão: origin")
    p.add_argument("--branch", help="padrão: o branch atual")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_update, no_brain=True)

    p = sub.add_parser("upstream", help="guarda o caminho de volta ao repo público: varredura de dado pessoal + hook pre-push")
    us = p.add_subparsers(dest="ucmd", required=True)
    x = us.add_parser("scan", help="varre o que ainda não foi enviado ao framework; código 4 se achar dado pessoal/segredo")
    x.add_argument("--committed", action="store_true", help="só commits (o que um git push enviaria) — usado pelo hook")
    x.add_argument("--fetch", action="store_true", help="atualiza o remoto antes (padrão: sem rede)")
    x.add_argument("--remote", help="padrão: origin")
    x.add_argument("--branch", help="padrão: o branch atual")
    x.add_argument("--json", action="store_true")
    x = us.add_parser("hook", help="instala/remove o hook pre-push que roda a varredura")
    x.add_argument("action", choices=["install", "remove", "status"])
    p.set_defaults(fn=cmd_upstream, no_brain=True)

    p = sub.add_parser("demo", help="cria uma instância fictícia para ver o painel (não toca no seu vault)")
    p.add_argument("--dir", required=True)
    p.add_argument("--open", action="store_true")
    p.set_defaults(fn=cmd_demo, no_brain=True)

    p = sub.add_parser("watch", help="fontes do config/watch.toml (o universo observável do /update): listar, adicionar, editar, remover")
    ws = p.add_subparsers(dest="wcmd", required=True)
    x = ws.add_parser("list")
    x.add_argument("--json", action="store_true")
    x = ws.add_parser("add")
    x.add_argument("key", help="identidade estável da fonte (ex.: slack-time-dados)")
    x.add_argument("--kind", required=True, help="gmail · slack · gcal · drive · jira …")
    x.add_argument("--window", help="janela de leitura: auto (desde o último pull) · 12h · 1d · 7d")
    x.add_argument("--note")
    x.add_argument("--set", action="append", metavar="CAMPO=VALOR", help="outro campo (channel, jql, …); repita a opção")
    x = ws.add_parser("edit")
    x.add_argument("key")
    x.add_argument("--rename", metavar="NOVA_KEY")
    x.add_argument("--kind")
    x.add_argument("--window")
    x.add_argument("--note")
    x.add_argument("--set", action="append", metavar="CAMPO=VALOR")
    x.add_argument("--unset", action="append", metavar="CAMPO", help="remove um campo opcional")
    x = ws.add_parser("remove")
    x.add_argument("key")
    x = ws.add_parser("since", help="início da janela de leitura da fonte (o agente não calcula datas)")
    x.add_argument("key")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_watch)

    p = sub.add_parser("tui", help="cockpit de terminal (Textual, extra opcional): painéis, teclas contextuais e log da CLI")
    p.add_argument("--setup", action="store_true", help="cria a venv .venv-tui com as dependências travadas por hash")
    p.set_defaults(fn=cmd_tui)
    return ap


def cmd_demo(args, b) -> None:
    from . import demo
    demo.cli(args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        b = None if getattr(args, "no_brain", False) else Brain()
        args.fn(args, b)
    except util.BrainError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return e.code
    except BrokenPipeError:
        return 0
    return 0
