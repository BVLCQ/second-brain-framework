"""Compartilhar: exports autocontidos (para colegas) e a porta de publicação (espaço do time).

Exports vão para vault/reports/share/ — point-in-time, nunca reescritos (regerar cria
arquivo novo). Escritos para quem NÃO tem acesso ao cérebro: sem jargão interno, IDs
só na seção de fontes, nada da lista "observando", nada de rascunhos.
Publicar (Slack canvas / Drive) é porta estreita: destino listado em [publish],
aprovação explícita por publicação, conteúdo travado por hash.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

from . import model, planning, util

# IDs internos que podem vir embutidos em textos calculados (ex.: motivo da saúde do projeto).
_ID = re.compile(r"\b(?:(?:TASK|DEC|WIN|PROP|MSG|PUB|FOCUS|PROC|OPP|ASK)-\d{4,}|PROJ-\d+(?:\.\d+)?|GOAL-\d+)\b")


def _names(m: dict) -> dict[str, str]:
    out = {g["id"]: g["title"] for g in m["goals"]}
    for p in m["projects"]:
        out[p["id"]] = p["title"]
        out.update({d["id"]: d["title"] for d in p["deliverables"]})
    out.update({a["id"]: a["title"] for a in m["actions"]})
    out.update({d["id"]: d["title"] for d in m["decisions"]})
    return out


def _plain(text: str, names: dict[str, str]) -> str:
    """Motivo de saúde sem jargão: "PROJ-1.1 venceu há 3d (Título)" → "Título venceu há 3d"; ID solto → título."""
    text = re.sub(r"^\S+ venceu há (\d+)d \((.*)\)$", r"\2 venceu há \1d", text or "")
    return _ID.sub(lambda mm: names.get(mm.group(0), "item"), text)


def _sections_project(m: dict, pid: str) -> tuple[str, list, list[str]]:
    p = next((x for x in m["projects"] if x["id"] == pid), None)
    if p is None:
        raise util.BrainError(f"projeto {pid} não existe", code=3)
    goal = next(g for g in m["goals"] if g["id"] == p["goal"])
    acts = {a["id"]: a for a in m["actions"]}
    decs = {d["id"]: d for d in m["decisions"]}
    sources: list[str] = []
    intro = [f"**Objetivo:** {goal['title']}" + (f" — {goal['why']}" if goal["why"] else ""),
             f"**Saúde:** {p['health']['label']} — {_plain(p['health']['reason'], _names(m))}",
             f"**Progresso:** {planning.format_progress(p['progress'])} entregáveis"]
    deliv = []
    for d in p["deliverables"]:
        if d["status"] == "cancelado":
            continue
        mark = "✓" if d["status"] == "feito" else "○"
        when = f"concluído em {util.fmt_date(d['done_date'])}" if d["done_date"] else \
            (f"prazo {util.fmt_date(d['due'])}" + (" (atrasado)" if d["overdue_days"] else "") if d["due"] else "sem prazo")
        deliv.append(f"{mark} {d['title']} — {when}")
    decisions = []
    for did in p["decisions"]:
        d = decs[did]
        if d["status"] != "ativa":
            continue
        decisions.append(f"{util.fmt_date(d['date'])} — {d['title']} — decidido por {', '.join(d['decided_by_names'])}")
        sources.append(f"{did}: {d['source_label']}")
    wins = []
    for e in m["deliveries"]:
        if e["project"] == pid:
            wins.append(f"{util.fmt_date(e['date'])} — {e['title']} — {e['result']}")
            sources.append(f"{e['id']}: {e['source_label']}")
    doing = []
    for aid in p["actions"]["mine"]:
        a = acts[aid]
        doing.append(f"{a['title']}" + (f" — prazo {util.fmt_date(a['due'])}" if a["due"] else ""))
        sources.append(f"{aid}: {a['source_label']}")
    deps = []
    for aid in p["actions"]["waiting"]:
        a = acts[aid]
        deps.append(f"{a['owner_name']} — {a['title']}" + (f" (prazo {util.fmt_date(a['due'])}"
                                                           + (", atrasado" if a["overdue_days"] else "") + ")"
                                                           if a["due"] else ""))
    nxt = [f"{util.fmt_date(d['due'])} — {d['title']}" for d in sorted(
        (d for d in p["deliverables"] if d["due"] and d["status"] not in ("feito", "cancelado")),
        key=lambda d: d["due"])[:5]]
    sections = [("", intro), ("Entregáveis", deliv), ("Decisões", decisions), ("Entregue", wins),
                ("Em andamento", doing), ("Dependências de outras pessoas", deps), ("Próximos marcos", nxt)]
    return f"{p['title']}", sections, sources


def _sections_goal(m: dict, gid: str) -> tuple[str, list, list[str]]:
    g = next((x for x in m["goals"] if x["id"] == gid), None)
    if g is None:
        raise util.BrainError(f"goal {gid} não existe", code=3)
    projs = [x for x in m["projects"] if x["goal"] == gid]
    intro = [f"**Por quê:** {g['why'] or '—'}",
             f"**Progresso:** {planning.format_progress(g['progress'])} entregáveis · **Saúde:** {g['health_label']}"]
    names = _names(m)
    lines = [f"{p['title']} — {planning.format_progress(p['progress'])} · "
             f"{p['health']['label']} ({_plain(p['health']['reason'], names)})"
             + (f" · próximo: {p['next_due']['title']} em {util.fmt_date(p['next_due']['date'])}" if p["next_due"] else "")
             for p in projs]
    ids = {p["id"] for p in projs}
    wins = [f"{util.fmt_date(e['date'])} — {e['title']} — {e['result']}" for e in m["deliveries"] if e["project"] in ids]
    decs = [f"{util.fmt_date(d['date'])} — {d['title']} — {', '.join(d['decided_by_names'])}"
            for d in m["decisions"] if d["project"] in ids and d["status"] == "ativa"][:10]
    sources = [f"{e['id']}: {e['source_label']}" for e in m["deliveries"] if e["project"] in ids]
    return g["title"], [("", intro), ("Projetos", lines), ("Entregue", wins), ("Decisões recentes", decs)], sources


def _sections_status(m: dict) -> tuple[str, list, list[str]]:
    goals = [f"**{g['title']}** — {planning.format_progress(g['progress'])} · "
             f"{g['health_label']}" + (lambda nd: f" · próximo marco: {nd['title']} ({util.fmt_date(nd['date'])})"
                                       if nd else "")(min((p["next_due"] for p in m["projects"]
                                                          if p["goal"] == g["id"] and p["next_due"]),
                                                         key=lambda x: x["date"], default=None))
             for g in m["goals"]]
    mine = sorted((a for a in m["actions"] if a["open"] and a["mine"] and a["list"] == "mine" and a["due"]),
                  key=lambda a: a["due"])[:4]
    focus = [f"{a['title']} — até {util.fmt_date(a['due'])}" for a in mine]
    wins = [f"{util.fmt_date(e['date'])} — {e['title']} — {e['result']}" for e in m["deliveries"][:5]]
    wins += [f"{util.fmt_date(x['date'])} — {x['title']} (entregável concluído)" for x in m["deliverables_done"][:3]]
    blockers = [f"{a['owner_name']} — {a['title']}" + (f" (prazo {util.fmt_date(a['due'])}"
                                                       + (", atrasado" if a["overdue_days"] else "") + ")" if a["due"] else "")
                for a in m["actions"] if a["open"] and a["list"] == "waiting"][:8]
    return f"Status — {m['owner']['name']}", [("Por objetivo", goals), ("Foco da semana", focus),
                                               ("Entregue recentemente", wins or ["nada declarado no período"]),
                                               ("Bloqueios que dependem de outras pessoas", blockers)], []


def _sections_period(m: dict, rng: str) -> tuple[str, list, list[str]]:
    try:
        a, b = (date.fromisoformat(x) for x in rng.split(":"))
    except ValueError as e:
        raise util.BrainError("período: use AAAA-MM-DD:AAAA-MM-DD", code=1) from e
    inr = lambda d: d and a.isoformat() <= d <= b.isoformat()  # noqa: E731
    wins = [f"{util.fmt_date(e['date'])} — {e['title']} — {e['result']}" for e in m["deliveries"] if inr(e["date"])]
    wins += [f"{util.fmt_date(x['date'])} — {x['title']} (entregável)" for x in m["deliverables_done"] if inr(x["date"])]
    decs = [f"{util.fmt_date(d['date'])} — {d['title']} — {', '.join(d['decided_by_names'])}"
            for d in m["decisions"] if inr(d["date"])]
    closed = [f"{util.fmt_date(x['closed'])} — {x['title']}" for x in m["actions"]
              if x["mine"] and x["status"] == "fechada" and inr(x["closed"])]
    sources = [f"{e['id']}: {e['source_label']}" for e in m["deliveries"] if inr(e["date"])]
    return (f"Recap {util.fmt_date(a)}–{util.fmt_date(b)}",
            [("Entregue", wins or ["nada registrado"]), ("Decisões", decs), ("Ações concluídas", closed)], sources)


def _area_filter(m: dict, area: str | None) -> tuple[str | None, str]:
    """Área por id, nome ou alias → (id, nome). Sem filtro: (None, 'todas as áreas')."""
    if not area:
        return None, ""
    key = util.fold(area)
    hit = next((a for a in m["portfolio"]["areas"] if key in {util.fold(a["id"]), util.fold(a["name"]),
                                                              *(util.fold(x) for x in a["aliases"])}), None)
    if hit is None:
        raise util.BrainError(f"área '{area}' não cadastrada", code=3)
    return hit["id"], hit["name"]


def _prio(o: dict) -> str:
    if o["score"] is None:
        return "sem pontuação"
    return f"prioridade {o['score']}" + (" (preliminar)" if o["ice_suggested"] else "")


def _sections_portfolio(m: dict, area: str | None) -> tuple[str, list, list[str]]:
    """Roadmap priorizado: ranking, matriz e status. Sem IDs no texto; ICE aparece como pontuação de prioridade."""
    pf = m["portfolio"]
    aid, aname = _area_filter(m, area)
    opps = [o for o in pf["opportunities"] if not aid or o["area"] == aid]
    by_id = {o["id"]: o for o in opps}
    names = {a["id"]: a["name"] for a in pf["areas"]}
    rank = [by_id[i] for i in pf["ranking"] if i in by_id]
    intro = ["Pontuação de prioridade = impacto × confiança × facilidade, cada um de 1 a 5 (máximo 125)."
             + (f" Recorte: {aname}." if aname else "")]
    ranking = [f"{o['title']} — {_prio(o)} · {o['status']}" + (f" · {names.get(o['area'], o['area'])}" if not aid else "")
               + (f" · ganho declarado: {o['hours_saved']:g} h/mês" if o["hours_saved"] else "") for o in rank]
    matrix = []
    for q, ids in pf["matrix"].items():
        got = [by_id[i]["title"] for i in ids if i in by_id]
        if got:
            matrix.append(f"**{q}:** " + "; ".join(got))
    live = [o for o in opps if o["status"] in ("em-andamento", "piloto", "validando")]
    running = [f"{o['title']} — {o['status']}" + (f" · projeto {o['project_title']} ({planning.format_progress(o['project_progress'])})"
                                                     if o["project_progress"] else "") for o in live]
    funnel: dict[str, int] = {}
    for o in opps:
        funnel[o["status"]] = funnel.get(o["status"], 0) + 1
    status = [f"{s}: {n}" for s, n in pf["funnel"].items() if funnel.get(s)] if not aid else [f"{s}: {n}" for s, n in funnel.items()]
    sources = [f"{o['id']}: {o['source'] or 'sem fonte registrada'}" for o in rank]
    return ("Roadmap de oportunidades" + (f" — {aname}" if aname else ""),
            [("", intro), ("Prioridades", ranking or ["nenhuma oportunidade pontuada ainda"]), ("Matriz impacto × facilidade", matrix),
             ("Em andamento", running), ("Por status", status)], sources)


def _sections_opportunity(brain, m: dict, oid: str) -> tuple[str, list, list[str]]:
    o = next((x for x in m["portfolio"]["opportunities"] if x["id"] == oid), None)
    if o is None:
        raise util.BrainError(f"oportunidade {oid} não existe", code=3)
    pf = m["portfolio"]
    area = next((a["name"] for a in pf["areas"] if a["id"] == o["area"]), o["area"])
    proc = next((p for p in pf["processes"] if p["id"] == o["process"]), None)
    label = model.ModelBuilder(brain).source_label
    intro = [f"**Área:** {area} · **Tipo:** {o['kind']} · **Status:** {o['status']}"]
    prio = [f"{_prio(o)}: impacto {o['impact']} × confiança {o['confidence']} × facilidade {o['ease']}"
            + (" (estimativa preliminar, ainda não confirmada)" if o["ice_suggested"] else "")] if o["score"] is not None else         ["ainda sem pontuação de prioridade"]
    gain = [o["gain"]] if o["gain"] else []
    if o["hours_saved"]:
        gain.append(f"Horas poupadas declaradas: {o['hours_saved']:g} por mês")
    related = []
    if proc:
        related.append(f"Processo: {proc['title']}" + (f" ({proc['hours_month']:g} h/mês hoje)" if proc["hours_month"] else ""))
    if o["project"]:
        related.append(f"Projeto: {o['project_title']}" + (f" — {planning.format_progress(o['project_progress'])}"
                                                           if o["project_progress"] else ""))
    sections = [("", intro), ("Problema", [o["problem"]] if o["problem"] else ["não consta"]),
                ("Sugestão", [o["suggestion"]] if o["suggestion"] else ["não consta"]),
                ("Ganho esperado", gain or ["não consta"]), ("Prioridade", prio), ("Relacionado", related),
                ("Evidências", [label(e) for e in o["evidence"]])]
    return o["title"], sections, [f"{oid}: {label(o['source'])}"] + [f"evidência: {e}" for e in o["evidence"]]


def _md(title: str, sections, sources, stamp: str) -> str:
    out = [f"# {title}", f"_Gerado em {stamp} · ponto no tempo (não é atualizado)_", ""]
    for name, items in sections:
        if not items:
            continue
        if name:
            out += [f"## {name}", ""]
        out += [f"- {i}" if name else i for i in items] + [""]
    if sources:
        out += ["---", "", "**Fontes** (para auditoria):", ""] + [f"- {s}" for s in sources]
    return "\n".join(out) + "\n"


def _html(title: str, sections, sources, stamp: str) -> str:
    def inline(s: str) -> str:
        # só pares fecham negrito: um `**` solto num título não deixa <b> aberto até o fim do item
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s))
    body = [f"<h1>{html.escape(title)}</h1>", f"<p class=meta>Gerado em {stamp} · ponto no tempo</p>"]
    for name, items in sections:
        if not items:
            continue
        if name:
            body.append(f"<h2>{html.escape(name)}</h2><ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
        else:
            body.append("".join(f"<p>{inline(i)}</p>" for i in items))
    if sources:
        body.append("<h2>Fontes</h2><ul class=src>" + "".join(f"<li>{html.escape(s)}</li>" for s in sources) + "</ul>")
    css = ("body{font:15px/1.55 system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#16181d}"
           "h1{font-size:24px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #e5e7eb;padding-bottom:4px}"
           ".meta{color:#6b7280}.src{color:#6b7280;font-size:13px}li{margin:4px 0}"
           "@media print{body{margin:0}}")
    return (f"<!doctype html><html lang=pt-BR><meta charset=utf-8><title>{html.escape(title)}</title>"
            f"<style>{css}</style><body>{''.join(body)}</body></html>\n")


def export(brain, kind: str, target: str | None, fmt: str, area: str | None = None) -> Path:
    m = model.build(brain)
    if kind == "portfolio":
        title, sections, sources = _sections_portfolio(m, area)
        target = area
    elif kind == "opportunity":
        title, sections, sources = _sections_opportunity(brain, m, target or "")
    elif kind == "project":
        title, sections, sources = _sections_project(m, target or "")
    elif kind == "goal":
        title, sections, sources = _sections_goal(m, target or "")
    elif kind == "status":
        title, sections, sources = _sections_status(m)
    else:
        title, sections, sources = _sections_period(m, target or "")
    stamp = util.now().strftime("%d/%m/%Y %H:%M")
    text = _html(title, sections, sources, stamp) if fmt == "html" else _md(title, sections, sources, stamp)
    out_dir = brain.inst.reports / "share"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{util.today().isoformat()}-{kind}" + (f"-{util.slugify(target)}" if target else "")
    path, n = out_dir / f"{base}.{fmt}", 2
    while True:                      # criação exclusiva: report já gerado nunca é sobrescrito (nem em corrida)
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except FileExistsError:
            path, n = out_dir / f"{base}-{n}.{fmt}", n + 1


def cli_export(args, brain) -> None:
    path = export(brain, args.kind, args.target, args.format, getattr(args, "area", None))
    if args.json:
        print(json.dumps({"path": str(path)}))
    else:
        print(f"✓ export pronto: {brain.inst.rel(path)} — autocontido; revise antes de enviar a alguém")


def _file_sha(brain, report: str) -> tuple[Path, str]:
    """Só arquivos dentro de vault/reports/. `..` e links para fora são recusados."""
    vault = brain.inst.vault.resolve()
    reports = (vault / "reports").resolve()
    path = (vault / report).resolve()
    if not path.is_file() or reports not in path.parents:
        raise util.BrainError(f"{report} não existe em vault/reports/ — gere com `brain share` antes", code=3)
    return path, util.sha(path.read_bytes())


def cli_publish(args, brain) -> None:
    st, c = brain.state, args.pbcmd
    if c == "request":
        dests = brain.inst.cfg["publish"]["destinations"]
        if args.to not in dests:
            raise util.BrainError(f"destino '{args.to}' não está em [publish].destinations do config/brain.toml", code=4)
        report = brain.inst.rel(Path(args.report).resolve()) if Path(args.report).is_absolute() else args.report
        report = report[len("vault/"):] if report.startswith("vault/") else report
        _, h = _file_sha(brain, report)
        ev = brain.record_one({"type": "share.requested", "by": "agent", "prov": "sistema", "source": "chat",
                               "data": {"report": report, "destination": args.to, "content_sha": h}})
        print(f"✓ {ev['id']}: publicar {report} em {args.to} — mostre ao dono e peça aprovação explícita")
    elif c == "approve":
        s = st.shares.get(args.id)
        if s is None or s.status != "solicitada":
            raise util.BrainError(f"{args.id} inexistente ou não está aguardando aprovação", code=4)
        _, h = _file_sha(brain, s.report)
        if h != s.content_sha:
            raise util.BrainError(f"{s.report} mudou depois do pedido — refaça o pedido", code=4)
        brain.record_one({"type": "share.approved", "id": args.id, "by": "owner",
                          "data": {"quote": args.quote, "content_sha": h}})
        print(f"✓ {args.id} aprovada — publique o conteúdo de vault/{s.report} em {s.destination} e rode "
              f"`brain publish done {args.id} --link <url>`")
    elif c == "done":
        s = st.shares.get(args.id)
        if s is None or s.status != "aprovada":
            raise util.BrainError(f"{args.id} não está aprovada — publicação exige aprovação explícita", code=4)
        _, h = _file_sha(brain, s.report)
        if h != s.content_sha:
            raise util.BrainError(f"{s.report} mudou depois da aprovação — não publique; refaça o pedido", code=4)
        brain.record_one({"type": "share.published", "id": args.id, "by": "system", "data": {"link": args.link}})
        print(f"✓ {args.id} registrada como publicada")
    elif c == "cancel":
        brain.record_one({"type": "share.cancelled", "id": args.id, "by": "owner", "data": {}})
        print(f"✓ {args.id} cancelada")
    elif c == "list":
        rows = list(st.shares.values())
        print("\n".join(f"{s.id} · {s.status} · {s.report} → {s.destination}" for s in rows) or "(nenhuma)")
