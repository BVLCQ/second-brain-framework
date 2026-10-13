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
from datetime import date
from pathlib import Path

from . import model, planning, util


def _sections_project(m: dict, pid: str) -> tuple[str, list, list[str]]:
    p = next((x for x in m["projects"] if x["id"] == pid), None)
    if p is None:
        raise util.BrainError(f"projeto {pid} não existe", code=3)
    goal = next(g for g in m["goals"] if g["id"] == p["goal"])
    acts = {a["id"]: a for a in m["actions"]}
    decs = {d["id"]: d for d in m["decisions"]}
    sources: list[str] = []
    intro = [f"**Objetivo:** {goal['title']}" + (f" — {goal['why']}" if goal["why"] else ""),
             f"**Saúde:** {p['health']['label']} — {p['health']['reason']}",
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
    lines = [f"{p['title']} — {planning.format_progress(p['progress'])} · "
             f"{p['health']['label']} ({p['health']['reason']})"
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
        e = html.escape(s)
        while "**" in e:
            e = e.replace("**", "<b>", 1).replace("**", "</b>", 1)
        return e
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


def export(brain, kind: str, target: str | None, fmt: str) -> Path:
    m = model.build(brain)
    if kind == "project":
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
    while path.exists():
        path, n = out_dir / f"{base}-{n}.{fmt}", n + 1
    path.write_text(text, encoding="utf-8")
    return path


def cli_export(args, brain) -> None:
    path = export(brain, args.kind, args.target, args.format)
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
