"""`brain area|process|opportunity|doc` — portfólio de processos (PROC-####) e oportunidades (OPP-####).

Mesmo padrão de `action`/`decision`: o agente extrai, o CLI numera e calcula (horas/mês, ICE).
Promover oportunidade a projeto é o gate estrutural (`plan add-project`); o resto é livre.
"""
from __future__ import annotations

import argparse
import json
import os

from . import planning, portfolio, util, watch
from .cli import _common, _create_project, _fact_opts, _out, _resolve_people
from .core import Brain

REC_LABEL = {"diaria": "diária", "semanal": "semanal", "quinzenal": "quinzenal", "mensal": "mensal",
             "trimestral": "trimestral", "sob-demanda": "sob demanda", "por-evento": "por evento"}


def _hours(v) -> str:
    return "—" if v is None else f"{v:g}".replace(".", ",") + " h/mês"


def _area(b: Brain, value: str | None) -> str | None:
    """id da área a partir de id, nome ou alias."""
    if not value:
        return None
    if value in b.state.areas:
        return value
    key = util.fold(value)
    hits = [a.id for a in b.state.areas.values()
            if key in {util.fold(a.id), util.fold(a.name), *(util.fold(x) for x in a.aliases)}]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise util.BrainError(f"área '{value}' é ambígua: {', '.join(hits)}", code=2)
    raise util.BrainError(f"área '{value}' não cadastrada — `brain area add` primeiro "
                          f"(cadastradas: {', '.join(b.state.areas) or 'nenhuma'})", code=3)


def _jsonable(o):
    from dataclasses import asdict
    return json.loads(json.dumps(asdict(o), default=str))


# ── área ────────────────────────────────────────────────────────────────────
def cmd_area(args, b: Brain) -> None:
    st = b.state
    if args.acmd == "add":
        ev = b.record_one(_common({"type": "area.added", "id": args.slug, "data": {
            "name": args.name or args.slug, "aliases": util.split_csv(args.alias), "note": args.note}}, args))
        _out(args, ev, f"✓ área {ev['id']} · {args.name or args.slug}")
    elif args.acmd == "update":
        ev = b.record_one(_common({"type": "area.updated", "id": _area(b, args.slug), "data": {
            "name": args.name, "aliases_add": util.split_csv(args.alias), "note": args.note}}, args))
        _out(args, ev, f"✓ área {ev['id']} atualizada")
    else:
        rows = [{"id": a.id, "name": a.name, "aliases": a.aliases,
                 "processes": sum(1 for p in st.processes.values() if p.area == a.id and p.status == "ativo"),
                 "opportunities": sum(1 for o in st.opportunities.values() if o.area == a.id)}
                for a in st.areas.values()]
        _out(args, rows, "\n".join(f"{r['id']:<20} {r['name']} · {r['processes']} processos · "
                                   f"{r['opportunities']} oportunidades" for r in rows) or "(nenhuma área)")


# ── processo ────────────────────────────────────────────────────────────────
def _proc_line(b: Brain, p) -> str:
    bits = [p.id, p.title, b.state.areas[p.area].name if p.area in b.state.areas else p.area,
            f"resp. {b.state.person_name(p.owner)}" if p.owner else "sem responsável", _hours(p.hours_month)]
    if p.status != "ativo":
        bits.append("aposentado")
    bits += [f"⚠ {g}" for g in portfolio.process_gaps(p)] if p.status == "ativo" else []
    return " · ".join(bits)


def _proc_data(b: Brain, args, adding: bool) -> dict:
    data = {"title": args.title if adding else args.new_title, "area": _area(b, args.area),
            "recurrence": args.recurrence, "per_month": args.per_month, "duration": args.duration,
            "io": args.io, "maturity": args.maturity, "note": args.note}
    if args.owner:
        data["owner"] = _resolve_people(b, [args.owner])[0]
    if args.executor:
        data["executors"] = _resolve_people(b, args.executor)
    if args.tools is not None:
        data["tools"] = util.split_csv(args.tools)
    if args.pain:
        data["pains" if adding else "pains_add"] = args.pain
    return {k: v for k, v in data.items() if v not in (None, "", [])}


def cmd_process(args, b: Brain) -> None:
    st, c = b.state, args.pcmd
    if c == "add":
        ev = b.record_one(_common({"type": "process.added", "data": _proc_data(b, args, True)}, args))
        _out(args, ev, "✓ " + _proc_line(b, b.state.processes[ev["id"]]))
    elif c == "update":
        _need_proc(b, args.id)
        data = _proc_data(b, args, False)
        if not data:
            raise util.BrainError("process update: nada para mudar", code=3)
        ev = b.record_one(_common({"type": "process.updated", "id": args.id, "data": data}, args))
        _out(args, ev, "✓ " + _proc_line(b, b.state.processes[args.id]))
    elif c == "retire":
        _need_proc(b, args.id)
        ev = b.record_one(_common({"type": "process.retired", "id": args.id, "data": {"reason": args.reason}}, args))
        _out(args, ev, f"✓ {args.id} aposentado: {args.reason}")
    elif c == "show":
        p = _need_proc(b, args.id)
        if getattr(args, "json", False):
            print(json.dumps({**_jsonable(p), "hours_month": p.hours_month, "gaps": portfolio.process_gaps(p)},
                             ensure_ascii=False, indent=2))
            return
        print(_proc_line(b, p))
        print(f"  recorrência: {REC_LABEL.get(p.recurrence, '—')}"
              + (f" ({p.per_month:g}/mês)" if p.per_month else "")
              + f" · duração: {util.fmt_duration(p.duration_min)} · maturidade: {p.maturity or '—'}")
        print(f"  executores: {', '.join(st.person_name(x) for x in p.executors) or '—'}")
        print(f"  ferramentas: {', '.join(p.tools) or '—'} · entradas → saídas: {p.io or '—'}")
        for x in p.pains:
            print(f"  dor: {x}")
        for d in p.docs:
            print(f"  doc [{d.kind}] {d.title or d.ref} · {d.ref}")
        for n in p.notes:
            print(f"  nota: {n}")
    else:
        rows = [p for p in st.processes.values() if p.status == "ativo"]
        if args.area:
            rows = [p for p in rows if p.area == _area(b, args.area)]
        if args.gaps:
            rows = [p for p in rows if portfolio.process_gaps(p)]
        rows.sort(key=lambda p: (p.area, p.id))
        _out(args, [{**_jsonable(p), "hours_month": p.hours_month, "gaps": portfolio.process_gaps(p)}
                    for p in rows], "\n".join(_proc_line(b, p) for p in rows) or "(nenhum processo)")


def _need_proc(b: Brain, pid: str):
    p = b.state.processes.get(pid)
    if p is None:
        raise util.BrainError(f"{pid} não existe", code=3)
    return p


# ── oportunidade ────────────────────────────────────────────────────────────
def _opp_line(b: Brain, o) -> str:
    bits = [o.id, o.status, o.title, b.state.areas[o.area].name if o.area in b.state.areas else o.area]
    if o.score is not None:
        bits.append(f"ICE {o.impact}×{o.confidence}×{o.ease}={o.score}" + (" (sugerido)" if o.ice_suggested else ""))
    if o.project:
        bits.append(f"{o.project}/{o.goal}")
    return " · ".join(bits)


def _need_opp(b: Brain, oid: str):
    o = b.state.opportunities.get(oid)
    if o is None:
        raise util.BrainError(f"{oid} não existe", code=3)
    return o


def _opp_data(b: Brain, args, adding: bool) -> dict:
    data = {"title": args.title if adding else args.new_title, "area": _area(b, args.area),
            "process": args.process, "kind": args.kind, "problem": args.problem,
            "suggestion": args.suggestion, "gain": args.gain, "hours_saved": args.hours_saved,
            "goal": args.goal, "note": getattr(args, "note", None)}
    if args.person:
        data["people" if adding else "people_add"] = _resolve_people(b, args.person)
    return {k: v for k, v in data.items() if v not in (None, "", [])}


def cmd_opportunity(args, b: Brain) -> None:
    st, c = b.state, args.ocmd
    if c == "add":
        data = _opp_data(b, args, True)
        dups = portfolio.duplicates(args.title, args.problem or "", st.opportunities.values())
        if dups and not args.force:
            msg = "\n".join(f"  {o.id} ({o.status}) · {o.title} · similaridade {s:.2f}" for o, s in dups)
            raise util.BrainError(f"possível duplicata — nada gravado:\n{msg}\n"
                                  f"Se for a mesma ideia: `brain opportunity evidence <OPP> --source …`; "
                                  f"se for nova: repita com --force", code=2)
        ev = b.record_one(_common({"type": "opportunity.added", "data": data}, args))
        _out(args, ev, "✓ " + _opp_line(b, b.state.opportunities[ev["id"]]))
    elif c == "update":
        _need_opp(b, args.id)
        data = _opp_data(b, args, False)
        if not data:
            raise util.BrainError("opportunity update: nada para mudar", code=3)
        ev = b.record_one(_common({"type": "opportunity.updated", "id": args.id, "data": data}, args))
        _out(args, ev, "✓ " + _opp_line(b, b.state.opportunities[args.id]))
    elif c == "status":
        _need_opp(b, args.id)
        ev = b.record_one(_common({"type": "opportunity.status", "id": args.id, "data": {
            "status": args.status, "reason": args.reason}}, args))
        _out(args, ev, "✓ " + _opp_line(b, b.state.opportunities[args.id]))
    elif c == "score":
        _need_opp(b, args.id)
        args.by = args.by or ("agent" if args.suggest else "owner")
        data = {"impact": args.impact, "confidence": args.confidence, "ease": args.ease}
        if args.suggest:
            data.update(ice_suggested=True, reason=args.reason)
        ev = b.record_one(_common({"type": "opportunity.scored", "id": args.id, "data": data}, args))
        _out(args, ev, "✓ " + _opp_line(b, b.state.opportunities[args.id]))
    elif c == "evidence":
        _need_opp(b, args.id)
        ev = b.record_one(_common({"type": "opportunity.evidence", "id": args.id,
                                   "data": {"source": args.source}}, args))
        o = b.state.opportunities[args.id]
        _out(args, ev, f"✓ {args.id} · evidência {o.evidence_count} (fonte: {args.source})")
    elif c == "promote":
        _promote(args, b)
    elif c == "show":
        o = _need_opp(b, args.id)
        if getattr(args, "json", False):
            print(json.dumps({**_jsonable(o), "score": o.score}, ensure_ascii=False, indent=2))
            return
        print(_opp_line(b, o))
        print(f"  tipo: {o.kind} · processo: {o.process or '—'} · ganho: {o.gain or '—'}"
              + (f" ({o.hours_saved:g} h/mês)" if o.hours_saved else ""))
        print(f"  problema: {o.problem or '—'}\n  sugestão: {o.suggestion or '—'}")
        if o.ice_suggested and o.ice_reason:
            print(f"  ICE sugerido porque: {o.ice_reason}")
        for h in o.status_history:
            print(f"  {h['date']} · {h['from']} → {h['to']}" + (f" · {h['reason']}" if h["reason"] else ""))
        for e in o.evidence:
            print(f"  evidência: {e}")
        for d in o.docs:
            print(f"  doc [{d.kind}] {d.title or d.ref} · {d.ref}")
    else:
        rows = list(st.opportunities.values())
        if args.status:
            rows = [o for o in rows if o.status == args.status]
        if args.area:
            rows = [o for o in rows if o.area == _area(b, args.area)]
        rows.sort(key=(lambda o: (-(o.score or 0), o.id)) if args.sort == "score" else (lambda o: o.id))
        _out(args, [{**_jsonable(o), "score": o.score} for o in rows],
             "\n".join(_opp_line(b, o) for o in rows) or "(nenhuma oportunidade)")


def _promote(args, b: Brain) -> None:
    """Promove OPP a projeto num goal. Sem --approval só mostra o diff proposto e sai com código de gate."""
    o = _need_opp(b, args.id)
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("opportunity promote: proibido no noturno — a árvore é do dono, que precisa estar presente", code=4)
    if o.project:
        raise util.BrainError(f"{o.id} já foi promovida ({o.project} em {o.goal})", code=4)
    if args.goal not in b.plan.goals:
        raise util.BrainError(f"goal {args.goal} não existe em PLANNING/goals.md", code=3)
    title = args.title or o.title
    why = " ".join((o.problem or "").split())[:160]
    owner = b.owner if b.owner in b.state.people else ""
    nid = planning.next_project_id(b.plan)
    diff = [f"### {nid} — {title}", "- status: ativo"] + ([f"- dono: {owner}"] if owner else []) \
        + ([f"- por quê: {why}"] if why else [])
    if not (args.approval or "").strip():
        print(f"Proposta (sob {args.goal} — {b.plan.goals[args.goal].title}):\n  " + "\n  ".join(diff))
        raise util.BrainError(f"promover {o.id} cria projeto: mudança estrutural — exige --approval com a "
                              "resposta literal do dono", code=4)
    nid, events = _create_project(
        b, args.goal, title, owner, args.approval, args.reason or f"promoção de {o.id}: {o.title}",
        args.evidence, why,
        extra=lambda pid: [
            {"type": "opportunity.promoted", "id": o.id, "by": "owner",
             "data": {"project": pid, "goal": args.goal}},
            {"type": "opportunity.status", "id": o.id, "by": "owner",
             "data": {"status": "em-andamento", "reason": f"promovida a {pid}"}}])
    _out(args, {"id": nid, "events": events}, f"✓ {o.id} → {nid} em {args.goal} (aprovado; goals.md, log e ledger)\n  "
         + _opp_line(b, b.state.opportunities[o.id]))


# ── documentos ──────────────────────────────────────────────────────────────
def cmd_doc(args, b: Brain) -> None:
    if args.dcmd == "link":
        if args.watch and args.kind != "playbook":
            raise util.BrainError("--watch vale só para --kind playbook (doc do Drive)", code=4)
        if args.watch and not watch.drive_doc_id(args.ref):
            raise util.BrainError(f"--watch pede um doc do Drive (URL ou id); recebi {args.ref!r}", code=4)
        data = {"target": args.target, "kind": args.kind, "ref": args.ref, "title": args.title,
                "watch": True if args.watch else None}
        ev = b.record_one(_common({"type": "doc.linked", "data": data}, args))
        watched = ""
        if args.watch:
            src = watch.link_playbook(b, args.target, args.ref)
            watched = f"\n  ↳ fonte {src['key']} no watch.toml: o /update relê quando o doc mudar"
        _out(args, ev, f"✓ {args.target} · doc [{args.kind}] {args.title or args.ref}{watched}")
    else:
        ev = b.record_one(_common({"type": "doc.unlinked", "data": {"target": args.target, "ref": args.ref}}, args))
        gone = watch.unlink_playbook(b, args.target, args.ref)
        _out(args, ev, f"✓ {args.target} · doc desligado: {args.ref}" + (" (fonte do watch removida)" if gone else ""))


# ── parser ──────────────────────────────────────────────────────────────────
def _owner_default(x: argparse.ArgumentParser) -> None:
    x.set_defaults(by="owner")


def add_parsers(sub) -> None:
    from .schema import DOC_KINDS, OPP_KINDS, OPP_STATUS, RECURRENCE

    p = sub.add_parser("area", help="áreas do portfólio (slug, nome, aliases)")
    s = p.add_subparsers(dest="acmd", required=True)
    x = s.add_parser("add")
    x.add_argument("slug")
    x.add_argument("--name")
    x.add_argument("--alias", action="append", help="apelidos (vírgula ou repetido)")
    x.add_argument("--note")
    _fact_opts(x)
    _owner_default(x)
    x = s.add_parser("update")
    x.add_argument("slug")
    x.add_argument("--name")
    x.add_argument("--alias", action="append", help="adiciona apelidos")
    x.add_argument("--note")
    _fact_opts(x)
    _owner_default(x)
    x = s.add_parser("list")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_area)

    def proc_fields(x, adding: bool) -> None:
        x.add_argument("--area", required=adding)
        x.add_argument("--owner", help="responsável (1 pessoa)")
        x.add_argument("--executor", action="append", help="quem executa (repetível)")
        x.add_argument("--recurrence", choices=sorted(RECURRENCE))
        x.add_argument("--per-month", type=float, help="execuções/mês (sob-demanda/por-evento)")
        x.add_argument("--duration", help="por execução: 45m · 1h30m")
        x.add_argument("--tools", help="ferramentas (vírgula)")
        x.add_argument("--io", help='"entradas → saídas"')
        x.add_argument("--pain", action="append", help="dor (repetível)")
        x.add_argument("--maturity", type=int, help="1–5")
        x.add_argument("--note")
        _fact_opts(x)

    p = sub.add_parser("process", help="processos PROC-####")
    s = p.add_subparsers(dest="pcmd", required=True)
    x = s.add_parser("add")
    x.add_argument("title")
    proc_fields(x, True)
    x = s.add_parser("update")
    x.add_argument("id")
    x.add_argument("--title", dest="new_title")
    proc_fields(x, False)
    x = s.add_parser("retire")
    x.add_argument("id")
    x.add_argument("--reason", required=True)
    _fact_opts(x)
    x = s.add_parser("show")
    x.add_argument("id")
    x.add_argument("--json", action="store_true")
    x = s.add_parser("list")
    x.add_argument("--area")
    x.add_argument("--gaps", action="store_true", help="só os com lacuna (playbook, responsável, recorrência)")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_process)

    def opp_fields(x, adding: bool) -> None:
        x.add_argument("--area", required=adding)
        x.add_argument("--process", help="PROC-####")
        x.add_argument("--kind", choices=sorted(OPP_KINDS))
        x.add_argument("--problem")
        x.add_argument("--suggestion")
        x.add_argument("--gain", help="ganho esperado (texto)")
        x.add_argument("--hours-saved", type=float, help="horas/mês poupadas (declaradas)")
        x.add_argument("--person", action="append", help="pessoas envolvidas (ids/aliases)")
        x.add_argument("--goal", help="G# ao qual a ideia se liga")
        _fact_opts(x)

    p = sub.add_parser("opportunity", help="oportunidades/iniciativas OPP-####")
    s = p.add_subparsers(dest="ocmd", required=True)
    x = s.add_parser("add")
    x.add_argument("title")
    opp_fields(x, True)
    x.add_argument("--force", action="store_true", help="grava mesmo com possível duplicata")
    x = s.add_parser("update")
    x.add_argument("id")
    x.add_argument("--title", dest="new_title")
    x.add_argument("--note")
    opp_fields(x, False)
    x = s.add_parser("status")
    x.add_argument("id")
    x.add_argument("status", choices=sorted(OPP_STATUS))
    x.add_argument("--reason", help="obrigatório para em-espera/descartada")
    _fact_opts(x)
    _owner_default(x)
    x = s.add_parser("score", help="ICE: impacto × confiança × facilidade (1–5); o CLI calcula o score")
    x.add_argument("id")
    x.add_argument("--impact", type=int, required=True)
    x.add_argument("--confidence", type=int, required=True)
    x.add_argument("--ease", type=int, required=True)
    x.add_argument("--suggest", action="store_true", help="sugestão do agente (--by agent); fica em rosa até o dono confirmar")
    x.add_argument("--reason", help="por que esse ICE (com --suggest)")
    _fact_opts(x)
    x.set_defaults(by=None)
    x = s.add_parser("evidence", help="mais uma fonte que reforça a oportunidade")
    x.add_argument("id")
    _fact_opts(x)
    x = s.add_parser("promote", help="vira projeto num goal (GATE: sem --approval só mostra o diff)")
    x.add_argument("id")
    x.add_argument("--goal", required=True)
    x.add_argument("--title")
    x.add_argument("--reason")
    x.add_argument("--evidence")
    x.add_argument("--approval", help="resposta literal do dono (ex.: 'ok')")
    x.add_argument("--json", action="store_true")
    x = s.add_parser("show")
    x.add_argument("id")
    x.add_argument("--json", action="store_true")
    x = s.add_parser("list")
    x.add_argument("--status", choices=sorted(OPP_STATUS))
    x.add_argument("--area")
    x.add_argument("--sort", choices=["id", "score"], default="id")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_opportunity)

    p = sub.add_parser("doc", help="documentos ligados a PROC-####/OPP-####")
    s = p.add_subparsers(dest="dcmd", required=True)
    x = s.add_parser("link")
    x.add_argument("target", help="PROC-#### ou OPP-####")
    x.add_argument("--kind", required=True, choices=sorted(DOC_KINDS))
    x.add_argument("--ref", required=True, help="URL, id do Drive ou caminho RAW/PROCESSED")
    x.add_argument("--title")
    x.add_argument("--watch", action="store_true", help="playbook do Drive: o /update relê quando mudar")
    _fact_opts(x)
    x = s.add_parser("unlink")
    x.add_argument("target")
    x.add_argument("--ref", required=True)
    _fact_opts(x)
    p.set_defaults(fn=cmd_doc)
