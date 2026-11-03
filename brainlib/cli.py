"""`brain` — a única porta de escrita do livro-razão e o motor das views.

Códigos de saída: 0 ok · 1 uso · 2 ambíguo · 3 não encontrado · 4 validação · 5 ledger corrompido.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, config, dupes, ids, people, planning, schema, util
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
    # o ledger grava a pessoa com id em slug: o brain.toml precisa do MESMO id, senão o dono não casa com a ficha
    owner_id = util.slugify(args.owner_id, 32) if args.owner_id else ""
    created = upstream.seed_template(inst)
    upstream.hook(inst, "install")
    inst.config_dir.mkdir(parents=True, exist_ok=True)
    for name in ("brain.toml", "watch.toml", ".env"):
        dst = inst.config_dir / name
        src = inst.config_dir / f"{name}.example"
        if not dst.exists() and src.exists():
            text = src.read_text(encoding="utf-8")
            if name == "brain.toml" and args.owner_id:
                # json.dumps = string TOML válida (aspas e barras escapadas): aspas no nome quebravam o brain.toml
                text = text.replace('id = "eu"', f'id = {json.dumps(owner_id, ensure_ascii=False)}', 1)
                if args.owner_name:
                    text = text.replace('name = "Dono do cérebro"',
                                        f'name = {json.dumps(args.owner_name, ensure_ascii=False)}', 1)
            dst.write_text(text, encoding="utf-8")
            if name == ".env":
                dst.chmod(0o600)
            created.append(f"config/{name}")
    if owner_id:
        b.inst = config.load(inst.root)
        b.reload()
        if owner_id not in b.state.people:
            b.record_one({"type": "person.added", "id": owner_id, "by": "owner",
                          "data": {"name": args.owner_name or args.owner_id,
                                   "aliases": util.split_csv(args.alias), "email": args.email or "",
                                   "relation": "dono do cérebro"}})
            created.append(f"pessoa: {owner_id}")
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
        bits.append(f"prazo {a.due.isoformat()}" + (" (sugerido)" if a.due_suggested else ""))
    if a.effort_min:
        bits.append(f"esforço {util.fmt_duration(a.effort_min)}")
    if a.parked and a.open:
        bits.append("não agora")
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
        item = _common({"type": "action.opened", "data": {
            "title": args.title, "owner": owner, "list": lst, "due": args.due,
            "due_suggested": args.due_suggested or None, "due_reason": args.due_reason,
            "due_none_reason": args.due_none_reason,
            "effort_min": _effort(b, args.effort), "project": args.project, "deliverable": args.deliverable,
            "blocked_by": util.split_csv(args.blocked_by), "unblocks": util.split_csv(args.unblocks),
            "people": _resolve_people(b, args.people or []), "priority": args.priority,
            "link": args.link, "origin": args.origin}}, args)
        schema.require_due_decision(item)
        if args.force:
            # quem criou olhou os candidatos e disse "é outra": o par fica julgado e não volta na varredura
            probe = dupes.profile_from_data(item["data"])
            item["data"]["not_dup"] = [h["id"] for h in dupes.similar(b.state, probe, threshold=dupes.STRONG)]
        else:
            dupes.require_checked(item, b.state)
            near = dupes.similar(b.state, dupes.profile_from_data(item["data"]))
            if near:
                print("↳ parecidas (confira se não é a mesma): " + " · ".join(f"{h['id']} {h['title']} ({h['score']:.2f})"
                                                                             for h in near), file=sys.stderr)
        ev = b.record_one(item)
        _out(args, ev, "✓ " + _action_line(b, ev["id"]))
    elif c == "update":
        data = {"note": args.note, "status": args.status, "due": args.due, "list": args.list,
                "effort_min": _effort(b, args.effort), "project": args.project,
                "deliverable": args.deliverable, "priority": args.priority, "title": args.title}
        if args.due_suggested:
            data["due_suggested"], data["due_reason"] = True, args.due_reason
        if args.confirm_due:
            data["due_confirmed"] = True
        if args.park or args.unpark:
            data["parked"] = bool(args.park)
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
        data = {"reason": args.reason}
        if c == "drop" and args.duplicate_of:
            data["duplicate_of"] = ids.normalize(args.duplicate_of)
        ev = b.record_one(_common({"type": f"action.{'dropped' if c == 'drop' else 'reopened'}",
                                   "id": args.id, "data": data}, args))
        _out(args, ev, "✓ " + _action_line(b, args.id))
    elif c == "dupes":
        _action_dupes(args, b)
    elif c == "not-dup":
        other = ids.normalize(args.other)
        ev = b.record_one(_common({"type": "action.updated", "id": args.id, "data": {
            "not_dup_add": [other], "note": f"não é duplicada de {other}: {args.reason}"}}, args))
        _out(args, ev, f"✓ {args.id} × {other}: par julgado como ações diferentes (não volta na varredura)")
    elif c == "merge":
        _merge_action(args, b)
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
        if args.undated:
            rows = [r for r in rows if r["open"] and not r["due"] and r["list"] != "watching"]
        rows.sort(key=lambda r: (r["due"] or "9999", r["id"]))
        _out(args, rows, "\n".join(_action_line(b, r["id"]) for r in rows) or "(nenhuma)")


def _action_dupes(args, b: Brain) -> None:
    """Sem --title: pares de ações abertas parecidas, ainda não julgados. Com --title: candidatos para uma ação nova."""
    th = args.threshold if args.threshold is not None else dupes.CANDIDATE
    if args.title:
        probe = {"title": args.title, "link": args.link or "", "project": args.project or "",
                 "deliverable": args.deliverable or "", "people": _resolve_people(b, args.people or [])}
        hits = dupes.similar(b.state, probe, threshold=th)
        _out(args, hits, "\n".join(f"{h['id']} ({h['status']}) · {h['title']} · {h['score']:.2f} · {'; '.join(h['why'])}"
                                    for h in hits) or "(nenhuma parecida)")
        return
    rows = dupes.pairs(b.state, threshold=th)
    _out(args, rows, "\n".join(f"{r['score']:.2f} · {r['a']} {r['a_title']}\n       {r['b']} {r['b_title']}\n"
                                f"       ({'; '.join(r['why'])})" for r in rows) or "(nenhum par parecido)")


def _merge_action(args, b: Brain) -> None:
    """Unifica: a duplicada (id) é descartada e o que ela tinha de próprio passa para a que fica (--into)."""
    if args.by != "owner":
        raise util.BrainError("action merge: unificar é decisão do dono (--by owner, depois do \"ok\" dele); "
                              "o agente propõe com `brain proposal add --kind unificar-acao`", code=4)
    st = b.state
    keep_id = ids.normalize(args.into)
    dup, keep = st.actions.get(args.id), st.actions.get(keep_id)
    if dup is None or keep is None or dup.id == keep.id:
        raise util.BrainError("action merge: informe duas ações existentes e diferentes (ID --into ID)", code=3)
    if not dup.open or not keep.open:
        raise util.BrainError(f"action merge: {dup.id} e {keep.id} precisam estar abertas", code=4)
    data = {"note": f"unificada com {dup.id}: {dup.title}"}
    if args.title:
        data["title"] = args.title
    extra = [p for p in dup.people + ([dup.owner] if dup.owner != keep.owner else []) if p not in keep.people]
    if extra:
        data["people_add"] = extra
    if dup.link and not keep.link:
        data["link"] = dup.link
    if dup.due and not dup.due_suggested and (not keep.due or keep.due_suggested or dup.due < keep.due):
        data["due"] = dup.due.isoformat()
    for f in ("blocked_by", "unblocks"):
        merged = [x for x in getattr(keep, f) + getattr(dup, f) if x not in (keep.id, dup.id)]
        merged = list(dict.fromkeys(merged))
        if merged != getattr(keep, f):
            data[f] = merged
    events = [_common({"type": "action.updated", "id": keep.id, "data": data}, args)]
    for other in st.actions.values():
        if other.open and other.id not in (dup.id, keep.id) and dup.id in other.blocked_by:
            events.append({"type": "action.updated", "id": other.id, "by": "system", "date": args.date, "data": {
                "blocked_by": list(dict.fromkeys(keep.id if x == dup.id else x for x in other.blocked_by)),
                "note": f"bloqueio passou de {dup.id} para {keep.id} (unificadas)"}})
    events.append(_common({"type": "action.dropped", "id": dup.id, "data": {
        "reason": args.reason or f"unificada em {keep.id}", "duplicate_of": keep.id}}, args))
    recorded = b.record(events)
    lines = [f"✓ {dup.id} unificada em {keep.id}", "  " + _action_line(b, keep.id)]
    for ev in recorded:
        if ev["type"] == "action.updated" and ev["id"] not in (keep.id, dup.id):
            lines.append(f"  ↳ {ev['id']}: {ev['data']['note']}")
        elif ev["type"] == "proposal.superseded":
            lines.append(f"  ↳ proposta {ev['id']} {ev['data'].get('outcome', 'encerrada')}: {ev['data']['reason']}")
    _out(args, recorded, "\n".join(lines))


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
        elif ev["type"] == "proposal.superseded":
            lines.append(f"  ↳ proposta {ev['id']} {ev['data'].get('outcome', 'encerrada')}: {ev['data']['reason']}")
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
        "people": _resolve_people(b, args.people or []), "projects": util.split_csv(args.projects),
        "link": args.link}}, args))
    _out(args, ev, f"✓ artefato {ev['id']} ({args.kind})")


def cmd_proposal(args, b: Brain) -> None:
    if args.rcmd == "add":
        ev = b.record_one(_common({"type": "proposal.opened", "data": {
            "kind": args.kind, "summary": args.summary, "target": args.target,
            "into": ids.normalize(args.into) if args.into else None, "evidence": args.evidence}}, args))
        _out(args, ev, f"✓ {ev['id']} · proposta ({args.kind}): {args.summary}")
    elif args.rcmd in ("accept", "reject"):
        t = "proposal.accepted" if args.rcmd == "accept" else "proposal.rejected"
        ev = b.record_one({"type": t, "id": args.id, "by": "owner", "data": {"quote": args.quote}})
        _out(args, ev, f"✓ {args.id} {'aceita' if args.rcmd == 'accept' else 'rejeitada'} ({args.quote!r})")
    elif args.rcmd == "list":
        for ev in b.sweep_proposals():
            print(f"↳ proposta {ev['id']} {ev['data'].get('outcome', 'encerrada')}: {ev['data']['reason']}", file=sys.stderr)
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
        path = inst.planning_file
        before = path.read_text(encoding="utf-8") if path.exists() else None
        changed = planning.set_deliverable(path, args.id, args.status,
                                           when if args.status == "feito" else None)
        b.reload()
        try:
            ev = b.record_one(_common({"type": "deliverable.updated", "id": args.id,
                                       "data": {"status": args.status, "evidence": args.evidence}}, args))
        except util.BrainError:
            # o ledger recusou (sem --prov/--source, --by owner no noturno…): o goals.md volta ao que era — senão a
            # próxima colheita leria o checkbox como edição do dono e gravaria `by: owner` no lugar do agente
            if changed and before is not None:
                util.atomic_write(path, before)
            raise
        _append_plan_log(inst, f"{util.today().isoformat()} · {args.id} estado → {args.status} · "
                               f"factual (sem mudança de estrutura) · evidência: {args.evidence or '—'}")
        _out(args, ev, f"✓ {args.id} → {args.status}" + ("" if changed else " (goals.md já estava assim)"))
    elif args.plcmd.startswith("add-"):
        _plan_add(args, b)
    elif args.plcmd == "edit":
        _plan_edit(args, b)
    elif args.plcmd == "log":
        if not args.approval.strip():          # como nos outros gates: aprovação em branco não é aprovação
            raise util.BrainError("plan log: --approval vazio — exige a resposta literal do dono", code=4)
        ev = b.record_one({"type": "plan.changed", "by": "owner", "data": {
            "diff": args.diff, "reason": args.reason, "evidence": args.evidence, "approval": args.approval}})
        _append_plan_log(inst, f"{util.today().isoformat()} · {args.diff} · {args.reason} · "
                               f"evidência: {args.evidence or '—'} · aprovado: \"{args.approval}\"")
        _out(args, ev, "✓ mudança registrada em PLANNING/log.md e no ledger")


def _create_project(b: Brain, goal: str, title: str, owner: str, approval: str, reason: str,
                    evidence: str | None = None, why: str = "", extra=None) -> tuple[str, list[dict]]:
    """Cria projeto num goal (GATE: exige `approval`): goals.md + plan.changed (+ eventos `extra(nid)`) no
    mesmo lote do ledger + linha no PLANNING/log.md. Se o ledger recusar, o goals.md volta ao que era."""
    inst = b.inst
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("plan add-project: proibido no noturno — a árvore é do dono, que precisa estar presente", code=4)
    if goal not in b.plan.goals:
        raise util.BrainError(f"goal {goal} não existe em PLANNING/goals.md", code=3)
    if not (approval or "").strip():
        raise util.BrainError("criar project é mudança estrutural: exige --approval com a resposta literal do dono", code=4)
    path, today = inst.planning_file, util.today().isoformat()
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    nid = planning.add_project(path, goal, title, owner, why)
    what = f"projeto criado sob {goal}: {title}"
    reason = reason or f"novo projeto sob {goal}"
    try:
        events = b.record([{"type": "plan.changed", "by": "owner", "data": {
            "diff": f"{nid} {what}", "reason": reason, "evidence": evidence, "approval": approval}},
            *(extra(nid) if extra else [])])
        _append_plan_log(inst, f"{today} · {nid} {what} · {reason} · evidência: {evidence or '—'}"
                               f" · aprovado: \"{approval}\"")
    except util.BrainError:
        util.atomic_write(path, before)          # o ledger recusou: o goals.md volta ao que era
        raise
    b.reload()
    return nid, events


def _plan_add(args, b: Brain) -> None:
    """Cria goal/projeto (gate: exige --approval do dono, vira plan.changed + PLANNING/log.md) ou entregável (sem gate)."""
    inst, kind = b.inst, args.plcmd.removeprefix("add-")
    if kind == "project":
        owner = _resolve_people(b, [args.owner])[0] if args.owner else ""
        nid, events = _create_project(b, args.goal, args.title, owner, args.approval, args.reason,
                                      args.evidence)
        _out(args, {"id": nid, "event": events[0]},
             f"✓ {nid} criado em PLANNING/goals.md (aprovado, registrado em PLANNING/log.md e no ledger)")
        return
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError(f"plan {args.plcmd}: proibido no noturno — a árvore é do dono, que precisa estar presente", code=4)
    plan, today = b.plan, util.today().isoformat()
    if kind == "goal":
        nid, what = planning.next_goal_id(plan), f"goal criado: {args.title}"
        reason = args.reason or args.why or "novo goal"
    else:
        if args.project not in plan.projects:
            raise util.BrainError(f"projeto {args.project} não existe em PLANNING/goals.md", code=3)
        nid = planning.next_deliverable_id(plan, args.project)
    if kind != "deliverable" and not (args.approval or "").strip():
        raise util.BrainError(f"criar {kind} é mudança estrutural: exige --approval com a resposta literal do dono", code=4)
    path = inst.planning_file
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    if kind == "goal":
        planning.add_goal(path, args.title, args.horizon or "", args.why or "")
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


def _plan_edit(args, b: Brain) -> None:
    """Edita goal/projeto (gate: exige --approval, vira plan.changed + PLANNING/log.md) ou entregável (sem gate)."""
    inst = b.inst
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("plan edit: proibido no noturno — a árvore é do dono, que precisa estar presente", code=4)
    kind = planning.node_kind(b.plan, args.id)
    if kind is None:
        raise util.BrainError(f"{args.id} não existe em PLANNING/goals.md", code=3)
    fields = {"title": args.title, "status": args.status, "horizon": args.horizon, "why": args.why,
              "owner": args.owner, "due": args.due, "weight": args.weight}
    if args.owner:
        fields["owner"] = _resolve_people(b, [args.owner])[0]
    if not any(v is not None for v in fields.values()):
        raise util.BrainError("plan edit: nada para mudar (use --title, --status, --horizon, --why, --owner, --due, --weight)", code=3)
    if kind != "deliverable" and not (args.approval or "").strip():
        raise util.BrainError(f"editar {kind} é mudança estrutural: exige --approval com a resposta literal do dono", code=4)
    path = inst.planning_file
    before = path.read_text(encoding="utf-8")
    changes = planning.edit_node(path, args.id, **fields)
    if not changes:
        _out(args, {"id": args.id, "changes": []}, f"{args.id}: nada mudou (goals.md já estava assim)")
        return
    what = "; ".join(f"{f}: {old} → {new}" for f, old, new in changes)
    today = util.today().isoformat()
    try:
        if kind != "deliverable":
            reason = args.reason or f"edição de {args.id}"
            ev = b.record_one({"type": "plan.changed", "by": "owner", "data": {
                "diff": f"{args.id} editado · {what}", "reason": reason, "evidence": args.evidence, "approval": args.approval}})
            _append_plan_log(inst, f"{today} · {args.id} editado · {what} · {reason} · evidência: {args.evidence or '—'}"
                                   f" · aprovado: \"{args.approval}\"")
        else:
            ev = None
            _append_plan_log(inst, f"{today} · {args.id} entregável editado · {what} · sem gate (não é goal nem projeto)")
    except util.BrainError:
        util.atomic_write(path, before)          # o ledger recusou: o goals.md volta ao que era
        raise
    b.reload()
    _out(args, {"id": args.id, "changes": changes, "event": ev},
         f"✓ {args.id} editado ({what})" + ("" if kind == "deliverable" else " · aprovado, registrado em PLANNING/log.md e no ledger"))


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
    src = args.file_opt or args.file
    try:
        raw = Path(src).read_text(encoding="utf-8") if src and src != "-" else sys.stdin.read()
    except (OSError, UnicodeDecodeError) as e:
        raise util.BrainError(f"add: não consegui ler {src}: {e}", code=1) from e
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        raise util.BrainError(f"add: JSON inválido ({e}) — nada gravado", code=4) from e
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
        raise util.BrainError("add: o lote é um objeto JSON ou uma lista de objetos (um por evento) — nada gravado", code=4)
    if any(x.get("type") == "deliverable.updated" for x in items):
        # o estado do entregável mora no goals.md: evento sem o checkbox seria desfeito na próxima colheita,
        # gravado como edição do dono
        raise util.BrainError("add: deliverable.updated não entra por lote — use `brain plan deliverable` "
                              "(atualiza o goals.md e o ledger juntos); nada gravado", code=4)
    gates = sorted({x.get("type") for x in items} & schema.OWNER_ONLY)
    if gates:
        # aprovação/gate tem porta própria (outbox approve, focus approve, plan log, opportunity promote…), que
        # confere a fala literal do dono; pelo lote o agente forjaria um "by": "owner"
        raise util.BrainError(f"add: {', '.join(gates)} não entra por lote — use o comando da porta; nada gravado",
                              code=4)
    for it in items:
        schema.require_due_decision({"by": "agent", **{k: v for k, v in it.items() if v not in (None, "")}})
        dupes.require_checked(it, b.state)
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
        render.open_dashboard(b, args.open)


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


def cmd_repos(args, b: Brain) -> None:
    from . import repos
    repos.cli(args, b)


def cmd_note(args, b: Brain) -> None:
    from . import notes
    notes.cli(args, b)


def cmd_raw(args, b: Brain) -> None:
    from . import rawsort
    rawsort.cli(args, b)


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


def cmd_migrate(args, b) -> None:
    from . import migrate_ids
    migrate_ids.cli(args, b)


def cmd_agent(args, b) -> None:
    from . import config
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("agent allow: proibido no noturno — liberar permissão é decisão do dono, presente", code=4)
    rule, existed = config.add_allow(b.inst, args.rule, args.scope)
    table = config.ALLOW_SCOPES[args.scope]
    _out(args, {"rule": rule, "scope": args.scope, "existed": existed},
         f"= {rule} já estava em [{table[0]}].{table[1]}" if existed else f"✓ {rule} liberada em [{table[0]}].{table[1]} (config/brain.toml)")


def cmd_tui(args, b) -> None:
    from . import tui
    tui.cli(args, b)


def cmd_setup(args, b) -> None:
    from . import setup
    setup.cli(args, b)


def cmd_serve(args, b) -> None:
    from . import serve
    raise SystemExit(serve.serve(b.inst, port=args.port, open_browser=args.open))


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

    p = sub.add_parser("action", help="ações TASK-####")
    acs = p.add_subparsers(dest="acmd", required=True)
    x = acs.add_parser("open")
    x.add_argument("title")
    x.add_argument("--owner", help="id/alias do dono da ação (padrão: você)")
    x.add_argument("--list", choices=["mine", "waiting", "watching"])
    x.add_argument("--due")
    x.add_argument("--due-suggested", action="store_true",
                   help="o prazo é sugestão do agente (--by agent); aparece em roxo até o dono definir/confirmar")
    x.add_argument("--due-reason", help="por que essa data (com --due-suggested)")
    x.add_argument("--due-none-reason", help="agente, sem --due: por que não há base para sugerir prazo ('não consta')")
    x.add_argument("--effort", help="90m · 2h · 1h30 · 1d")
    x.add_argument("--project")
    x.add_argument("--deliverable")
    x.add_argument("--blocked-by")
    x.add_argument("--unblocks")
    x.add_argument("--people", action="append", help="pessoas envolvidas (ids/aliases, vírgula)")
    x.add_argument("--priority", choices=["alta", "normal", "baixa"])
    x.add_argument("--link")
    x.add_argument("--origin")
    x.add_argument("--force", action="store_true",
                   help="grava mesmo parecida com outra (você conferiu: é outra ação); o par fica julgado")
    _fact_opts(x)
    x = acs.add_parser("update")
    x.add_argument("id")
    x.add_argument("--note")
    x.add_argument("--status", choices=["aberta", "fazendo", "aguardando"])
    x.add_argument("--title")
    x.add_argument("--owner")
    x.add_argument("--list", choices=["mine", "waiting", "watching"])
    x.add_argument("--due")
    x.add_argument("--due-suggested", action="store_true",
                   help="o prazo é sugestão do agente (--by agent); aparece em roxo até o dono definir/confirmar")
    x.add_argument("--due-reason", help="por que essa data (com --due-suggested)")
    x.add_argument("--confirm-due", action="store_true",
                   help="dono aceita o prazo sugerido como está (--by owner)")
    x.add_argument("--clear-due", action="store_true")
    x.add_argument("--park", action="store_true",
                   help='"não agora": adia de propósito (--by owner); sai do foco e da vista "esta semana"')
    x.add_argument("--unpark", action="store_true", help='tira da vista "não agora" (--by owner)')
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
        if name == "drop":
            x.add_argument("--duplicate-of", help="descartada por ser duplicada desta ação (TASK-####)")
        _fact_opts(x)
    x = acs.add_parser("dupes", help="ações parecidas: pares abertos ainda não julgados, ou candidatos para um título novo")
    x.add_argument("--title", help="título de uma ação que vai nascer (checa antes de criar)")
    x.add_argument("--project")
    x.add_argument("--deliverable")
    x.add_argument("--people", action="append")
    x.add_argument("--link")
    x.add_argument("--threshold", type=float, help=f"similaridade mínima (padrão {dupes.CANDIDATE})")
    x.add_argument("--json", action="store_true")
    x = acs.add_parser("not-dup", help="marca um par como ações diferentes (sai da varredura)")
    x.add_argument("id")
    x.add_argument("other")
    x.add_argument("--reason", required=True)
    _fact_opts(x)
    x = acs.add_parser("merge", help="unifica: ID é descartada e passa pessoas/link/prazo/bloqueios para --into (dono)")
    x.add_argument("id", help="a duplicada (sai)")
    x.add_argument("--into", required=True, help="a ação que fica")
    x.add_argument("--title", help="novo título para a que fica")
    x.add_argument("--reason")
    _fact_opts(x)
    x = acs.add_parser("show")
    x.add_argument("id")
    x.add_argument("--json", action="store_true")
    x = acs.add_parser("list")
    x.add_argument("--list", choices=["mine", "waiting", "watching"])
    x.add_argument("--project")
    x.add_argument("--owner")
    x.add_argument("--undated", action="store_true", help="abertas (mine/waiting) sem prazo — fila para sugerir prazo")
    x.add_argument("--all", action="store_true")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_action)

    p = sub.add_parser("decision", help="decisões DEC-####")
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

    p = sub.add_parser("delivery", help="entregas WIN-#### (conquistas)")
    p.add_argument("title")
    p.add_argument("--ref", help="TASK-#### / PROJ-# / PROJ-#.# / GOAL-#")
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
    p.add_argument("--link", help="PROC-####/OPP-#### a que o artefato pertence (ex.: leitura de playbook)")
    _fact_opts(p)
    p.set_defaults(fn=cmd_artifact)

    p = sub.add_parser("proposal", help="propostas PROP-#### (o dono aceita/rejeita)")
    rs = p.add_subparsers(dest="rcmd", required=True)
    x = rs.add_parser("add")
    x.add_argument("--kind", required=True, choices=sorted(schema.PROPOSAL_KINDS))
    x.add_argument("--summary", required=True)
    x.add_argument("--target")
    x.add_argument("--into", help="descartar-acao/unificar-acao: a ação que fica (--target é a duplicada)")
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
    x = pls.add_parser("edit", help="edita goal/projeto (GATE: exige --approval) ou entregável (sem gate)")
    x.add_argument("id", help="GOAL-# · PROJ-# · PROJ-#.#")
    x.add_argument("--title")
    x.add_argument("--status", help="goal/projeto: ativo · congelado · fechado")
    x.add_argument("--horizon", help="goal: AAAA-MM-DD (vazio remove)")
    x.add_argument("--why", help="goal: por quê (vazio remove)")
    x.add_argument("--owner", help="projeto: id ou alias da pessoa dona (vazio remove)")
    x.add_argument("--due", help="entregável: AAAA-MM-DD (vazio remove)")
    x.add_argument("--weight", type=int, help="entregável: inteiro a partir de 1")
    x = pls.add_parser("add-deliverable", help="cria entregável num projeto (sem gate)")
    x.add_argument("project")
    x.add_argument("title")
    x.add_argument("--due", help="AAAA-MM-DD")
    x.add_argument("--weight", type=int, default=1)
    for x in [pls.choices["add-goal"], pls.choices["add-project"], pls.choices["edit"]]:
        x.add_argument("--reason", help="motivo (padrão: derivado)")
        x.add_argument("--evidence")
        x.add_argument("--approval", help="resposta literal do dono (ex.: 'ok')")
    for x in [pls.choices["add-goal"], pls.choices["add-project"], pls.choices["add-deliverable"], pls.choices["edit"]]:
        x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_plan)

    from . import ask, cli_portfolio, feedback, oppdrive
    cli_portfolio.add_parsers(sub)
    ask.add_parsers(sub)
    oppdrive.add_parsers(sub)
    feedback.add_parsers(sub)

    p = sub.add_parser("progress", help="progresso DECLARADO pelo dono (GOAL-#/PROJ-#)")
    p.add_argument("node")
    p.add_argument("pct", type=int)
    p.add_argument("--note")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_progress)

    p = sub.add_parser("add", help="lote de eventos JSON (arquivo ou stdin) — usado pelo /dump")
    p.add_argument("file", nargs="?", default="-")
    p.add_argument("--file", dest="file_opt", help="o lote num arquivo (escreva com a ferramenta Write: heredoc e pipe não passam no allowlist `Bash(./brain:*)`)")
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
    p.add_argument("--open", nargs="?", const="execucao", choices=["execucao", "portfolio"],
                   help="abre no navegador o painel da face Execução (padrão) ou o mapa de oportunidades (portfolio)")
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

    p = sub.add_parser("outbox", help="mensagens MSG-#### (Slack) — rascunho → aprovação → envio")
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
    p.add_argument("kind", choices=["project", "goal", "status", "period", "portfolio", "opportunity"])
    p.add_argument("target", nargs="?", help="PROJ-#/GOAL-# · AAAA-MM-DD:AAAA-MM-DD · OPP-#### (opportunity)")
    p.add_argument("--area", help="portfolio: só uma área (id, nome ou alias)")
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

    p = sub.add_parser("repos", help="fonte kind=github: commits novos dos clones locais → snapshot por repo na inbox")
    rs = p.add_subparsers(dest="rcmd", required=True)
    x = rs.add_parser("pull", help="git fetch + lê cada repo da pasta `path`: 1ª vez o repo inteiro, depois só commit novo")
    x.add_argument("key", help="fonte do watch.toml (kind = \"github\")")
    x.add_argument("--fetch", action=argparse.BooleanOptionalAction, default=None,
                   help="git fetch antes de ler (padrão: sim, salvo `fetch = \"false\"` na fonte)")
    x.add_argument("--full", action="store_true", help="relê o repositório inteiro (histórico, árvore, documentos)")
    x.add_argument("--json", action="store_true")
    x = rs.add_parser("list", help="repositórios que a fonte enxerga")
    x.add_argument("key")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_repos)

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

    p = sub.add_parser("note", help="notas avulsas na inbox, com vínculo opcional a TASK-####/GOAL-#/PROJ-#/PROJ-#.#")
    ns = p.add_subparsers(dest="ncmd", required=True)
    x = ns.add_parser("add", help="cria AAAA…-note.md na inbox (o /dump arquiva)")
    x.add_argument("--link", help="TASK-#### · GOAL-# · PROJ-# · PROJ-#.# (opcional; os nomes antigos A-/G#/P# valem)")
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

    p = sub.add_parser("raw", help="RAW organizado por tipo: RAW/<ano>/<mês>/<tipo>/ (slack, meetings, documents, …, misc)")
    rs = p.add_subparsers(dest="rcmd", required=True)
    x = rs.add_parser("archive", help="move itens da inbox para a pasta do tipo (o que o /dump faz no passo de arquivar)")
    x.add_argument("files", nargs="*", help="nomes na inbox (padrão: tudo)")
    x.add_argument("--type", choices=rawsort_categories(), help="força o tipo (padrão: classificação por nome/extensão)")
    x.add_argument("--date", help="data de captura AAAA-MM-DD (padrão: hoje)")
    x.add_argument("--json", action="store_true")
    x = rs.add_parser("sort", help="arruma o RAW antigo: arquivos soltos em <ano>/<mês>/ vão para a pasta do tipo")
    x.add_argument("--dry-run", action="store_true")
    x.add_argument("--json", action="store_true")
    x = rs.add_parser("where", help="onde está hoje um caminho RAW/… guardado no ledger")
    x.add_argument("path")
    p.set_defaults(fn=cmd_raw)

    p = sub.add_parser("doctor", help="saúde da instância")
    p.add_argument("--json", action="store_true")
    p.add_argument("--online", action="store_true", help="testa também o servidor de memória, se estiver ligado")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("memory", help="camada de memória (Hindsight), alimentada pelo vault")
    ms = p.add_subparsers(dest="mcmd", required=True)
    for name in ("setup", "sync", "rebuild", "status", "cost"):
        x = ms.add_parser(name)
        x.add_argument("--json", action="store_true")
        if name in ("sync", "rebuild"):
            x.add_argument("--limit", type=int)
            x.add_argument("--dry-run", action="store_true")
        if name == "setup":
            x.add_argument("--mode", choices=["none", "embed", "full"],
                           help="grava as chaves do modo antes de criar os bancos (guides/memory.md)")
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

    p = sub.add_parser("agent", help="permissões do agente headless (config/brain.toml): `agent allow`")
    asub = p.add_subparsers(dest="agcmd", required=True)
    x = asub.add_parser("allow", help="libera uma ferramenta para o agente (valida a regra; recusa MCP de escrita no mundo exterior)")
    x.add_argument("rule", help='Bash(./brain:*) · mcp__servidor__ferramenta_de_leitura · Read…')
    x.add_argument("--scope", choices=["tui", "runner"], default="tui",
                   help="tui = [tui].agent_allow (só as ações ⚡) · runner = [runner].allow (leitura MCP: noturno e TUI)")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_agent)

    p = sub.add_parser("migrate", help="migrações de formato (exceção histórica ao append-only, com backup): `migrate ids`")
    ms = p.add_subparsers(dest="what", required=True)
    x = ms.add_parser("ids", help="A-0146→TASK-0146, G1→GOAL-1, P3.2→PROJ-3.2 em ledger, PLANNING, notas, PROCESSED, reports e nomes de arquivo")
    x.add_argument("--apply", action="store_true", help="aplica (sem isto é dry-run: só escreve o relatório em vault/reports/migration/)")
    x.add_argument("--include-external", action="store_true",
                   help="migra também G#/P# em RAW externo (reuniões, Slack…), onde 'P1' costuma ser outra coisa")
    p.set_defaults(fn=cmd_migrate)

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
    x = ws.add_parser("folders", help="de uma pasta observada, quais subpastas descer (pela data da call no nome × último pull)")
    x.add_argument("key")
    x.add_argument("--file", help="JSON com [{id, name, modifiedTime?}] (padrão: stdin)")
    x.add_argument("--margin", default="3d", help="folga antes do último pull para notas editadas depois da call (padrão 3d)")
    x.add_argument("--full", action="store_true", help="varredura completa: desce em todas")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_watch)

    p = sub.add_parser("tui", help="cockpit de terminal (Textual, extra opcional): painéis, teclas contextuais e log da CLI")
    p.add_argument("--setup", action="store_true", help="cria a venv .venv-tui com as dependências travadas por hash")
    p.set_defaults(fn=cmd_tui)

    p = sub.add_parser("setup", help="setup assistido (idempotente): instância, rotina, comando brain, "
                                     "memória none/embed/full, TUI, noturno, portas — guides/setup.md")
    p.add_argument("--only", help="re-visitar só estes passos (ids separados por vírgula)")
    p.add_argument("--yes", action="store_true", help="não-interativo com defaults (caminho das IAs)")
    p.add_argument("--mode", choices=["none", "embed", "full"], help="modo do passo memória (full exige o ok literal)")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("serve", help="ponte CLI do painel: 127.0.0.1 + token — o HTML executa as mesmas linhas do TUI")
    p.add_argument("--port", type=int, default=8787, help="porta local (padrão 8787)")
    p.add_argument("--open", action="store_true", help="abre o painel no navegador com o token na URL")
    p.set_defaults(fn=cmd_serve)
    return ap


def rawsort_categories() -> list[str]:
    from .rawsort import CATEGORIES
    return list(CATEGORIES)


def cmd_demo(args, b) -> None:
    from . import demo
    demo.cli(args)


# argumentos da CLI que guardam IDs: nomes antigos (A-0146, G1, P3.2…) são aceitos e traduzidos aqui, na entrada
_ID_ARGS = ("id", "goal", "project", "deliverable", "ref", "link", "target", "node", "process", "by_decision")
_ID_CSV_ARGS = ("blocked_by", "unblocks", "projects")


def normalize_ids(args: argparse.Namespace) -> argparse.Namespace:
    if getattr(args, "cmd", "") in ("person", "area"):          # `id` aqui é slug de pessoa/área, não ID de entidade
        return args
    for name in _ID_ARGS:
        if isinstance(getattr(args, name, None), str):
            setattr(args, name, ids.normalize(getattr(args, name)))
    for name in _ID_CSV_ARGS:
        if isinstance(getattr(args, name, None), str):
            setattr(args, name, ids.normalize_csv(getattr(args, name)))
    return args


def _print_completions(argv: list[str]) -> int:
    """`brain --completions [--opts] [palavras…]` → candidatos, um por linha, `nome:descrição`.
    Fonte única: o próprio argparse — o que o shell completa é exatamente o que existe.
    Com `--opts` (ou parado numa folha), devolve as opções do subcomando resolvido.
    Interceptado ANTES do parse (flag oculta: não polui --help nem as coberturas de superfície)."""
    import argparse as _ap
    want_opts = "--opts" in argv
    words = [w for w in argv if not w.startswith("-")]

    def walk(action):
        helps = {c.dest: c.help for c in getattr(action, "_choices_actions", [])}
        return action.choices, {k: (v or "") for k, v in helps.items()}

    def sub_action(parser):
        return next((a for a in parser._actions if isinstance(a, _ap._SubParsersAction)), None)

    p = build_parser()
    cur, cur_help = walk(sub_action(p))
    node = p
    for w in words:
        if w in cur:
            node = cur[w]
            sa = sub_action(node)
            cur, cur_help = walk(sa) if sa else ({}, {})
        else:
            cur, cur_help = {}, {}
    if cur and not want_opts:
        for name in sorted(cur):
            desc = (cur_help.get(name) or "").split(".")[0][:60].replace(":", " -").strip().rstrip(",(")
            if len(desc) > 48:
                desc = desc[:48].rsplit(" ", 1)[0]
            print(f"{name}:{desc}" if desc else name)
        return 0
    # folha (ou --opts pedido): opções do subcomando resolvido
    for a in node._actions:
        for opt in a.option_strings:
            if opt.startswith("--"):
                print(opt)
    return 0


def main(argv: list[str] | None = None) -> int:
    real = list(sys.argv[1:]) if argv is None else argv
    if "--completions" in real:
        return _print_completions([w for w in real if w != "--completions"])
    args = normalize_ids(build_parser().parse_args(argv))
    try:
        b = None if getattr(args, "no_brain", False) else Brain()
        args.fn(args, b)
    except util.BrainError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return e.code
    except BrokenPipeError:
        return 0
    return 0
