"""Linhas das listas e conteúdo do painel de detalhe — tudo Rich `Text`, sem markup.

Cores são nomes ANSI (red, yellow, green, cyan, magenta, dim) para acompanhar o tema do terminal.
Links no detalhe usam `meta={"@click": "app.jump('A-0021')"}`: clicar leva ao item.
"""
from __future__ import annotations

from datetime import date

from rich.style import Style
from rich.text import Text

from .. import util
from . import dates

RED, AMB, GRN, CYN, VIO, DIM, FAINT = "red", "yellow", "green", "cyan", "magenta", "dim", "dim italic"
GLYPH = {"aberta": ("○", DIM), "fazendo": ("◐", CYN), "aguardando": ("◔", AMB), "bloqueada": ("⊘", AMB),
         "fechada": ("✓", GRN), "descartada": ("✗", FAINT)}
DELIV_GLYPH = {"feito": ("[x]", GRN), "em-andamento": ("[~]", CYN), "nao-iniciado": ("[ ]", DIM),
               "cancelado": ("[-]", FAINT)}
PROV_STYLE = {"doc": CYN, "observado": VIO, "declarado": GRN, "sem-fonte": RED, "sistema": DIM}
MSG_STYLE = {"rascunho": AMB, "aprovada": CYN, "enviada": GRN, "falhou": RED, "cancelada": FAINT}
ART_ABBR = {"reuniao": "reun", "documento": "doc ", "nota": "nota", "conector": "conn"}


def T(*parts) -> Text:
    """T('texto', ('outro', 'red')) → Text sem quebra de linha automática."""
    t = Text(no_wrap=True, overflow="ellipsis")
    for p in parts:
        if isinstance(p, Text):
            t.append_text(p)
        elif isinstance(p, tuple):
            t.append(p[0], p[1])
        else:
            t.append(p)
    return t


def link(text: str, node: str, style: str = "") -> Text:
    st = Style(meta={"@click": f"app.jump('{node}')"})
    if style:
        st = Style.parse(style) + st
    return Text(text, style=st)


def wd_day(iso: str | None) -> str:
    d = util.parse_date(iso)
    return f"{util.WEEKDAYS_PT[d.weekday()]} {d.day:02d}" if d else "—"


def two(left: Text, right: Text, width: int) -> Text:
    """Esquerda truncada com reticências, direita colada na borda."""
    width = max(width, 10)
    avail = max(1, width - right.cell_len - 1)
    l = left.copy()
    l.truncate(avail, overflow="ellipsis", pad=True)
    out = Text(no_wrap=True, overflow="ellipsis")
    out.append_text(l)
    out.append(" ")
    out.append_text(right)
    return out


def bar(pct: int | None, w: int = 10) -> str:
    n = round((pct or 0) * w / 100)
    return "█" * n + "░" * (w - n)


def pct_txt(p: dict) -> str:
    return "—" if p.get("pct") is None else f"{p['pct']}%"


def due_tag(a: dict) -> Text:
    if not a["open"]:
        return T((wd_day(a["closed"] or a["due"]), FAINT))
    if not a["due"]:
        return T(("sem prazo", FAINT))
    if a["overdue_days"]:
        return T((f"{a['overdue_days']}d atraso", RED))
    di = a["due_in"]
    if di == 0:
        return T(("hoje", AMB))
    if di == 1:
        return T(("amanhã", AMB))
    return T((wd_day(a["due"]), DIM))


# ── linhas ──────────────────────────────────────────────────────────────────
def row(store, it, width: int) -> Text:
    k, d = it.kind, it.data
    if k == "action":
        g, gs = GLYPH.get(d["status"], ("○", DIM))
        left = T((g, gs), " ", (d["id"], DIM), " ", ("! ", RED) if d["priority"] == "alta" else "", d["title"])
        return two(left, due_tag(d), width)
    if k == "g":
        mark = "▸" if it.extra.get("collapsed") else "▾"
        decl = f"·{d['declared']['pct']}" if d["declared"] else ""
        return two(T((mark, DIM), " ", (d["id"], DIM), " ", (d["title"], "bold")),
                   T(pct_txt(d["progress"]), (decl, FAINT)), width)
    if k == "p":
        late = sum(1 for x in d["deliverables"] if x["overdue_days"])
        mark = "▸" if it.extra.get("collapsed") else "▾"
        pc = d["progress"]["pct"]
        right = T((f"⚠{late} ", RED) if late else "", (f"{bar(pc, 6)} {pct_txt(d['progress'])}", GRN if pc == 100 else DIM))
        return two(T("  ", (mark, DIM), " ", (d["id"], DIM), " ", d["title"]), right, width)
    if k == "d":
        g, gs = DELIV_GLYPH.get(d["status"], ("[ ]", DIM))
        if d["status"] == "feito" and d["done_date"]:
            when = util.fmt_date(d["done_date"])
        else:
            when = util.fmt_date(d["due"]) if d["due"] else "sem prazo"
        return two(T("    ", (g, gs), " ", (d["id"], DIM), " ", d["title"]), T((when, RED if d["overdue_days"] else DIM)), width)
    if k == "prop":
        live = d.status == "aberta"
        return two(T(("◆", AMB if live else FAINT), " ", (d.id, DIM), " ", d.summary),
                   T((d.kind if live else d.status, DIM if live else FAINT)), width)
    if k == "msg":
        st = d["status"]
        return two(T(("●", MSG_STYLE.get(st, DIM)), " ", (d["id"], DIM), " → ", store.first_name(d["to"]), " · ", d["text"]),
                   T((st, MSG_STYLE.get(st, DIM))), width)
    if k == "fday":
        mins = sum(_mins(b) for b in d["blocks"])
        n = len(d["blocks"])
        return two(T((wd_day(d["day"]), DIM), "  ", f"{n} bloco{'s' if n != 1 else ''}"),
                   T((f"{bar(min(100, mins / 240 * 100), 8)} {util.fmt_duration(mins)}", CYN)), width)
    if k == "fwarn":
        no_due = sum(1 for a in store.m["actions"] if a["open"] and a["list"] == "mine" and not a["due"])
        risk = len((d or {}).get("at_risk", []))
        return T(("⚠", AMB), f" não cabe: {risk} · sem prazo: {no_due}")
    if k == "pub":
        return two(T(("●", AMB), " ", (d["id"], DIM), " ", d["destination"], " · ", d["report"].split("/")[-1]),
                   T((d["status"], AMB if d["status"] in ("solicitada", "aprovada") else DIM)), width)
    if k == "dec":
        return two(T((d["id"], DIM), " ", d["title"]), T((util.fmt_date(d["date"]), DIM)), width)
    if k == "del":
        return two(T((d["id"], DIM), " ", d["title"]), T((util.fmt_date(d["date"]), DIM)), width)
    if k == "per":
        return two(T((d["id"], DIM), " ", d["name"]), T((d["relation"] or "", DIM)), width)
    if k == "art":
        return two(T((ART_ABBR.get(d["kind"], d["kind"][:4]), DIM), " ", d["title"]), T((util.fmt_date(d["date"]), DIM)), width)
    if k == "doc":
        lvl = d["level"]
        mark, st = {"ok": ("✓", GRN), "warn": ("⚠", AMB), "error": ("✗", RED)}[lvl]
        agent = (it.extra.get("fix") or {}).get("agent")
        return two(T((mark, st), " ", f"{d['title']}: {d['detail']}"), T(("⚡", VIO) if agent else ""), width)
    if k == "src":
        mark, st = ("●", GRN) if d["last_ok"] and not d["failures"] else (("✗", RED) if d["failures"] else ("○", AMB))
        if not d["in_watch"]:
            mark, st = "◌", FAINT
        right = (T((f"{d['failures']} falha(s)", RED)) if d["failures"] else
                 T(("fora do watch", FAINT)) if not d["in_watch"] else
                 T((util.fmt_date(d["last_ok"][:10]), DIM)) if d["last_ok"] else T(("nunca puxada", AMB)))
        extra = " · ".join(x for x in (d.get("kind"), d.get("window")) if x)
        return two(T((mark, st), " ", d["key"], ("  " + extra if extra else "", DIM)), right, width)
    if k == "sys":
        return two(T(("▸", DIM), " ", d["name"]), T(("porta ", AMB) if d.get("door") else "", ("info" if d.get("info") else "⏎", DIM)), width)
    return T(str(it.id))


def _mins(b: dict) -> int:
    s, e = util.parse_dt(b["start"]), util.parse_dt(b["end"])
    return int((e - s).total_seconds() // 60)


# ── detalhe ─────────────────────────────────────────────────────────────────
class Doc:
    def __init__(self) -> None:
        self.lines: list[Text] = []

    def blank(self) -> "Doc":
        self.lines.append(Text(""))
        return self

    def h(self, *parts) -> "Doc":
        """Título: str vira negrito; ('txt', 'estilo') e Text entram como vieram."""
        t = Text()
        for p in parts:
            if isinstance(p, Text):
                t.append_text(p)
            elif isinstance(p, tuple):
                t.append(p[0], p[1])
            else:
                t.append(p, "bold")
        self.lines.append(t)
        return self

    def p(self, *parts) -> "Doc":
        t = Text()
        for p in parts:
            if isinstance(p, Text):
                t.append_text(p)
            elif isinstance(p, tuple):
                t.append(p[0], p[1])
            else:
                t.append(p)
        self.lines.append(t)
        return self

    def sec(self, title: str) -> "Doc":
        self.blank()
        self.lines.append(Text.assemble((f"{title} ", DIM), ("─" * 60, "dim")))
        return self

    def kv(self, rows: list) -> "Doc":
        rows = [r for r in rows if r]
        w = max((len(r[0]) for r in rows), default=0) + 2
        for label, val in rows:
            t = Text()
            t.append(label.ljust(w), DIM)
            t.append_text(val) if isinstance(val, Text) else t.append(str(val))
            self.lines.append(t)
        return self

    def cmd(self, line: str) -> "Doc":
        self.lines.append(Text.assemble(("  $ ", CYN), (line, CYN)))
        return self

    def text(self) -> Text:
        out = Text()
        for i, l in enumerate(self.lines):
            if i:
                out.append("\n")
            out.append_text(l)
        return out


def prov(p: str | None) -> Text:
    return Text(f"[{p}]", PROV_STYLE.get(p or "", DIM))


def _links(store, ids: list[str]) -> Text:
    t = Text()
    for i, x in enumerate(ids):
        t.append_text(link(x, x))
        if i < len(ids) - 1:
            t.append(", ")
    return t


def detail(store, it) -> Text:
    if it is None:
        return Text("Nada aqui.", DIM)
    fn = {"resumo": d_resumo, "action": d_action, "g": d_plan, "p": d_plan, "d": d_plan, "prop": d_prop,
          "msg": d_msg, "fday": d_focus, "fwarn": d_focus, "pub": d_pub, "dec": d_dec, "del": d_del,
          "per": d_person, "art": d_art, "doc": d_doc, "sys": d_sys, "src": d_src}[it.kind]
    return fn(store, it).text()


def d_doc(store, it) -> Doc:
    c = it.data
    mark, st = {"ok": ("✓", GRN), "warn": ("⚠", AMB), "error": ("✗", RED)}[c["level"]]
    doc = Doc().h(Text(mark + " ", st), (c["title"], "bold")).p(c["detail"])
    fix = it.extra.get("fix")
    if fix:
        doc.sec("Como resolver").p(Text("⚡ " if fix.get("agent") else "▸ ", VIO if fix.get("agent") else CYN),
                                   fix["label"], ("  (tecla f)", DIM))
    return doc.sec("Equivalente na CLI").cmd("brain doctor --online")


def d_src(store, it) -> Doc:
    s = it.data
    doc = Doc().h(Text(s["key"], "bold"), (f"  · {s['kind']}" if s.get("kind") else "", DIM))
    if not s["in_watch"]:
        doc.blank().p(Text("Fonte puxada avulso (/connect). Não está no watch.toml, então o /update e o noturno não a puxam.", AMB))
        doc.p(("Tecla w inclui no watch.toml.", DIM))
    skip = {"key", "kind", "in_watch", "last_ok", "last_error", "failures", "pulls", "last_changed"}
    fields = [(k, Text(str(v))) for k, v in s.items() if k not in skip]
    last = Text(f"{s['last_ok'][:16].replace('T', ' ')} · {s['pulls']} pull(s)") if s["last_ok"] else Text("nunca puxada", AMB)
    rows_ = [("kind", Text(s.get("kind") or "—"))] + fields + [
        ("último pull", last),
        ("novidade", Text(util.fmt_date(s["last_changed"][:10]))) if s["last_changed"] else None,
        ("falhas seguidas", Text(str(s["failures"]), RED if s["failures"] else DIM)),
        ("último erro", Text(s["last_error"][:200], RED)) if s["last_error"] else None]
    doc.blank().kv(rows_)
    if s["in_watch"]:
        doc.sec("O que acontece").p("O /update lê esta fonte pelo MCP de leitura e grava com brain snapshot (hash igual = silêncio). "
                                    "Duas falhas seguidas pedem a sua atenção.")
        doc.p(("Tecla c puxa só esta fonte; u atualiza todas.", DIM))
    doc.sec("Arquivo").p(("config/watch.toml (fora do git). Fonte que não está lá NÃO é puxada.", DIM))
    return doc.sec("Equivalente na CLI").cmd(f"brain watch edit {s['key']} --window 7d" if s["in_watch"] else f"brain watch add {s['key']} --kind …")


def d_sys(store, it) -> Doc:
    o = it.data
    doc = Doc().h(o["name"]).blank().p(o["desc"])
    if o.get("door"):
        doc.blank().p(Text(" porta · " + o["door"] + " ", "bold yellow"), ("  pede confirmação antes de rodar", DIM))
    doc.sec("Equivalente na CLI").cmd("brain " + (" ".join(o["args"]) if o.get("args") else "memory recall|reflect …"))
    if not o.get("info"):
        doc.blank().p(("⏎ executa e mostra a saída no log", DIM))
    return doc


def d_welcome(store) -> Doc:
    return (Doc().h("Cérebro novo").blank()
            .p("Ainda não há goals, pessoas nem ações aqui. Um caminho para começar:")
            .sec("Primeiros passos")
            .p(("1  ", "bold"), Text("⚡ i", VIO), "  primeira entrevista: monta PROFILE e PLANNING e espera o seu ok (é o /init do agente)")
            .p(("2  ", "bold"), "jogue arquivos em vault/RAW/inbox/ e processe com ", Text("⚡ d", VIO), " (é o /dump)")
            .p(("3  ", "bold"), "ou crie ações à mão: painel 2, tecla ", ("n", "bold cyan"))
            .blank().p(("? ajuda do contexto · : paleta de comandos · q sai", DIM)))


def d_resumo(store, it) -> Doc:
    if store.is_empty():
        return d_welcome(store)
    m, c = store.m, store.counts
    today = util.today()
    doc = Doc().h(f"Hoje · {util.fmt_date(today, True)} {today.year}")
    age = store.rendered_age_h
    doc.p((f"views geradas há {age:.0f}h · fontes: PLANNING + ledger" if age is not None
           else "views ainda não geradas · rode r", DIM))
    doc.sec("Precisa de você")
    n = 0
    for a in m["actions"]:
        if a["open"] and a["mine"] and a["list"] == "mine" and a["overdue_days"]:
            n += 1
            doc.p(Text("⚠ ", RED), link(a["id"], a["id"], "bold"), f" {a['title']} ", (f"{a['overdue_days']}d de atraso", RED))
    for a in m["actions"]:
        if a["open"] and a["list"] == "waiting" and a["overdue_days"]:
            n += 1
            doc.p(Text("⚠ ", AMB), f"cobrar {a['owner_name'].split(' ')[0]}: ", link(a["id"], a["id"], "bold"),
                  f" {a['title']} ", (f"{a['overdue_days']}d", AMB))
    if c["proposals_open"]:
        n += 1
        first = m["proposals"][0]["id"]
        doc.p(Text("◆ ", AMB), link(f"{c['proposals_open']} proposta(s)", first, "bold"), " aguardando resposta")
    drafts = [x for x in m["outbox"] if x["status"] == "rascunho"]
    approved = [x for x in m["outbox"] if x["status"] == "aprovada"]
    if drafts:
        n += 1
        doc.p(Text("● ", AMB), link(f"{len(drafts)} rascunho(s)", drafts[0]["id"], "bold"), " para aprovar")
    if approved:
        n += 1
        doc.p(Text("● ", CYN), link(f"{len(approved)} mensagem(ns) aprovada(s)", approved[0]["id"], "bold"),
              " aguardando envio ", ("⚡ S", VIO))
    f = m["focus"]
    if f and f["status"] == "proposto":
        n += 1
        days = store.focus_days()
        doc.p(Text("◆ ", AMB), link(f"plano de foco {f['id']}", f"d:{days[0][0]}" if days else "f:warn", "bold"),
              " aguardando o seu ok")
    if store.inbox:
        n += 1
        doc.p(Text("⚡ ", VIO), f"{store.inbox} item(ns) na inbox · tecla ", ("d", "bold magenta"), " para processar")
    if not n:
        doc.p(("Nada aguardando você.", DIM))
    doc.sec("Foco de hoje")
    todays = [b for d, bl in store.focus_days() if d == today.isoformat() for b in bl]
    if not todays:
        doc.p(("Sem blocos hoje.", DIM))
    for b in todays:
        a = store.by_action.get(b["action"])
        doc.p((f"{b['start'][11:16]}–{b['end'][11:16]} ", CYN), (b["action"], "bold"), f" {a['title'] if a else ''}")
    doc.sec("Próximos 3 dias")
    near = [i for i in m["agenda"] if i["kind"] == "ação" and 0 < (util.parse_date(i["date"]) - today).days <= 3]
    if not near:
        doc.p(("Nada com prazo nos próximos 3 dias.", DIM))
    for i in near:
        doc.p((wd_day(i["date"]) + " ", DIM), link(i["id"], i["id"], "bold"), f" {i['title']}")
    doc.sec("Goal em foco")
    active = [g for g in m["goals"] if g["status"] in ("ativo", "ativa")]
    if not active:
        doc.p(("Nenhum goal ativo. Rode /init no agente para montar o PLANNING.", DIM))
    else:
        g = active[0]
        decl = f" · {g['declared']['pct']}% declarado" if g["declared"] else ""
        doc.p(link(g["id"], g["id"], "bold"), f" {g['title']}")
        doc.p((bar(g["progress"]["pct"], 20), CYN), f" {pct_txt(g['progress'])} calculado", (decl, DIM))
    return doc


def d_action(store, it) -> Doc:
    a = it.data
    g, gs = GLYPH.get(a["status"], ("○", DIM))
    doc = Doc().h(Text(a["id"] + " · ", "bold"), (a["title"], "bold"))
    bl = store.by_action.get(a["blocked_by"][0]) if a["blocked_by"] else None
    un = [store.by_action.get(x) for x in a["unblocks"] if x in store.by_action]
    due = Text(a["due"] + f" · {wd_day(a['due'])} · ") if a["due"] else Text("sem prazo · o foco ignora esta ação", AMB)
    if a["due"]:
        due.append_text(due_tag(a))
    rows = [("lista", Text(a["list"] + ("" if a["mine"] else f" · dono {a['owner_name']}"))),
            ("status", Text.assemble((f"{g} {a['status']}", gs), ("  alta", RED) if a["priority"] == "alta" else "")),
            ("prazo", due), ("esforço", Text(util.fmt_duration(a["effort_min"]))),
            ("projeto", Text.assemble(link(a["project"], a["project"]), f" {a['project_title']}") if a["project"] else Text("—", DIM)),
            ("entregável", link(a["deliverable"], a["deliverable"])) if a["deliverable"] else None,
            ("pessoas", Text(", ".join(store.first_name(p) for p in a["people"]) or "—")),
            ("bloqueada por", Text.assemble(link("⊘ " + bl["id"], bl["id"], AMB), " " + bl["title"])) if bl and bl["open"] else None,
            ("destrava", Text.assemble(*[(link(u["id"], u["id"]), " " + u["title"] + "  ") for u in un])) if un else None,
            ("origem", Text.assemble(a["origin"] or "—", " ", prov(a["prov"]))),
            ("fonte", Text(a["source_label"], DIM))]
    doc.kv(rows)
    doc.sec("Histórico")
    for h in reversed(a["history"]):
        kind = {"opened": "aberta", "updated": "atualizada", "closed": "fechada", "dropped": "descartada", "reopened": "reaberta"}.get(h["type"], h["type"])
        by = {"owner": "declarado", "agent": "observado", "system": "sistema"}.get(h["by"], h["by"])
        doc.p((util.fmt_date(h["date"]) + " ", DIM), f"{kind}: {h['note']}" if h["note"] else kind, " ", prov(by))
    if a["how"]:
        doc.p((util.fmt_date(a["closed"]) + " ", DIM), f"fechada: {a['how']}")
    return doc.sec("Equivalente na CLI").cmd(f"brain action show {a['id']}")


def d_plan(store, it) -> Doc:
    k, d = it.kind, it.data
    doc = Doc()
    if k == "g":
        doc.h(f"{d['id']} · {d['title']}")
        rows = [("status", Text(d["status"])), ("horizonte", Text(d["horizon"] or "—")), ("por quê", Text(d["why"] or "—")),
                ("saúde", Text(d["health_label"])),
                ("progresso", Text.assemble((bar(d["progress"]["pct"], 20), CYN), f" {pct_txt(d['progress'])}  ",
                                            (f"({d['progress']['weight_done']} de {d['progress']['weight_total']} pesos)", DIM))),
                ("declarado", Text.assemble((f"{d['declared']['pct']}%", GRN), f" em {util.fmt_date(d['declared']['date'])} ",
                                            (f"\"{d['declared']['note']}\"", DIM))) if d["declared"] else None]
        doc.kv(rows).sec("Projetos")
        for pid in d["projects"]:
            p = store.by_project[pid]
            late = sum(1 for x in p["deliverables"] if x["overdue_days"])
            doc.p(link(pid, pid, "bold"), f" {p['title']} ", (bar(p["progress"]["pct"], 10), CYN), f" {pct_txt(p['progress'])} ",
                  (f"⚠ {late} atrasado" if late else p["health"]["label"], RED if late else GRN))
    elif k == "p":
        late = [x for x in d["deliverables"] if x["overdue_days"]]
        doc.h(f"{d['id']} · {d['title']}")
        doc.kv([("goal", Text.assemble(link(d["goal"], d["goal"]), f" {d['goal_title']}")), ("dono", Text(store.person_name(d["owner"] or "") if d["owner"] else "—")),
                ("progresso", Text.assemble((bar(d["progress"]["pct"], 20), CYN), f" {pct_txt(d['progress'])}")),
                ("saúde", Text.assemble((d["health"]["label"], RED if d["health"]["level"] in ("em-risco", "travado") else GRN), f" · {d['health']['reason']}"))])
        doc.sec("Entregáveis")
        for x in d["deliverables"]:
            g, gs = DELIV_GLYPH.get(x["status"], ("[ ]", DIM))
            doc.p((g + " ", gs), link(x["id"], x["id"], "bold"), f" {x['title']} ", (f"· prazo {util.fmt_date(x['due'])} · peso {x['weight']}", DIM))
        doc.sec("Ações abertas ligadas")
        ids = d["actions"]["mine"] + d["actions"]["waiting"] + d["actions"]["watching"]
        if not ids:
            doc.p(("Nenhuma.", DIM))
        for i in ids:
            a = store.by_action[i]
            doc.p(link(i, i, "bold"), f" {a['title']} ", due_tag(a))
    else:
        p, g = it.extra["project"], it.extra["goal"]
        doc.h(f"{d['id']} · {d['title']}")
        doc.kv([("projeto", Text.assemble(link(p["id"], p["id"]), f" {p['title']}")), ("estado", Text(d["status"])),
                ("prazo", Text.assemble(f"{d['due']} · {wd_day(d['due'])}" if d["due"] else "sem prazo",
                                        (f"  {d['overdue_days']}d de atraso", RED) if d["overdue_days"] else "")),
                ("peso", Text(str(d["weight"]))), ("feito em", Text(d["done_date"])) if d["done_date"] else None])
        doc.sec("Ações ligadas")
        ac = [a for a in store.m["actions"] if a["deliverable"] == d["id"]]
        if not ac:
            doc.p(("Nenhuma ação aponta para este entregável.", AMB))
        for a in ac:
            doc.p(link(a["id"], a["id"], "bold"), f" {a['title']} ", due_tag(a))
        doc.blank().p(("Marcar estado é um fato, não um gate: space ou s. Criar, renomear ou fechar goal e projeto é gate: E.", DIM))
    return doc


EFFECT = {"fechar-acao": "brain action close {t} --how … --by owner", "reestimar": "brain action update {t} --effort … --by owner",
          "atualizar-acao": "aplique a mudança na ação {t} (e para editar: e)", "mudar-plano": "abre o gate: edite o goals.md com E",
          "outro": "só registra a resposta"}


def d_prop(store, it) -> Doc:
    r = it.data
    doc = Doc().h(f"{r.id} · {r.kind}", (f" · {r.status}" if r.status != "aberta" else "", DIM)).blank().p(r.summary)
    doc.kv([("alvo", link(r.target, r.target) if r.target else Text("—", DIM)), ("evidência", Text(r.evidence or "—"))])
    doc.sec("Se você aceitar").cmd(f"brain proposal accept {r.id} --quote \"…\"")
    doc.p(("  depois: " + EFFECT.get(r.kind, EFFECT["outro"]).format(t=r.target or "A-####"), DIM))
    doc.blank().p(("O cérebro não fecha nem altera nada sozinho. Rejeitada, a proposta só volta com evidência nova.", DIM))
    return doc


def d_msg(store, it) -> Doc:
    m = it.data
    steps = ["rascunho", "aprovada", "enviada"]
    ix = steps.index(m["status"]) if m["status"] in steps else -1
    doc = Doc().h(f"{m['id']} → {m['to_name']}", (" · slack", DIM))
    t = Text()
    for i, s in enumerate(steps):
        done = i < ix or m["status"] == "enviada"
        t.append(f" {s} ", (GRN if done else ("bold cyan" if i == ix else DIM)))
        if i < 2:
            t.append("→", DIM)
    doc.lines.append(t)
    doc.blank().p(("Texto exato que será enviado:", DIM))
    doc.lines.append(Text.assemble(("▌ ", CYN), m["text"]))
    allowed = m["to"] in store.allow()
    sha = store.text_sha(m["id"])
    doc.blank().kv([("ref", Text.assemble(link(m["ref"], m["ref"]) if m["ref"] else Text("—"), f"  {m['why'] or ''}", style=DIM)),
                    ("destinatário", Text("✓ em [outbound].allow", GRN) if allowed else Text("✗ fora da allowlist", RED)),
                    ("teto diário", Text(f"{store.sent_today()} de {store.inst.cfg['outbound']['daily_max']} hoje", DIM)),
                    ("trava", Text(f"sha256:{sha}…", DIM)), ("permalink", Text(m["link"], DIM)) if m["link"] else None])
    if m["status"] == "rascunho":
        doc.blank().p(("Mudou uma vírgula? Cancele e rascunhe de novo: a aprovação não é herdada.", DIM))
    elif m["status"] == "aprovada":
        doc.blank().p(("⚡ O agente envia pelo Slack MCP como você e registra o permalink com S. O TUI não envia sozinho.", VIO))
    return doc


def d_focus(store, it) -> Doc:
    f = store.m["focus"]
    if not f:
        return Doc().h("Nenhum plano de foco ainda").blank().p("Tecla p planeja blocos EDF para as suas ações com prazo. "
                                                              "Nada vai ao calendário sem o seu ok.")
    doc = Doc().h(f"{f['id']} · plano de foco · {f['status']}", (f"  modo {f['mode']}" if f["mode"] else "", DIM))
    cfg, w = store.inst.cfg["focus"], store.inst.cfg["work"]
    doc.p((f"EDF nas ações mine com prazo · expediente {w['start']}–{w['end']} · almoço {w['lunch'] or '—'} · teto {util.fmt_duration(cfg['daily_max_min'])}/dia", DIM))
    sel = it.id[2:] if it.kind == "fday" else None
    for day, blocks in store.focus_days():
        mins = sum(_mins(b) for b in blocks)
        doc.blank().p((f"{util.fmt_date(day, True)} · {util.fmt_duration(mins)}", "bold cyan" if day == sel else "bold"))
        for b in blocks:
            a = store.by_action.get(b["action"])
            doc.p((f"  {b['start'][11:16]}–{b['end'][11:16]} ", CYN), link(b["action"], b["action"], "bold"), f" {a['title'] if a else ''}")
    doc.sec("Não cabe")
    if not f["at_risk"]:
        doc.p(("Tudo coube.", DIM))
    for r in f["at_risk"]:
        doc.p(Text("⚠ ", AMB), link(r["action"], r["action"], "bold"), f" faltam {util.fmt_duration(r['shortfall_min'])} até {util.fmt_date(r['due'], True)}")
    doc.sec("Sem prazo, ignoradas pelo foco")
    nd = [a for a in store.m["actions"] if a["open"] and a["list"] == "mine" and not a["due"]]
    for a in nd:
        doc.p(("○ ", FAINT), link(a["id"], a["id"], "bold"), f" {a['title']}")
    if not nd:
        doc.p(("Nenhuma.", DIM))
    doc.blank().p(("Para mudar um horário, altere o prazo ou o esforço da ação e planeje de novo.", DIM))
    return doc


def d_pub(store, it) -> Doc:
    s = it.data
    order = ["solicitada", "aprovada", "publicada"]
    flow = Text(" report ", GRN)
    for name in order:
        flow.append("→", DIM)
        done = s["status"] in order and (order.index(name) < order.index(s["status"]) or s["status"] == "publicada")
        flow.append(f" {name} ", "bold cyan" if s["status"] == name and name != "publicada" else (GRN if done else DIM))
    if s["status"] == "cancelada":
        flow.append("  cancelada", FAINT)
    doc = Doc().h(f"{s['id']} · publicação").blank()
    doc.kv([("report", Text(s["report"])), ("destino", Text.assemble(s["destination"], (" ✓ em [publish].destinations" if s["destination"] in store.destinations() else " ✗ fora de [publish].destinations", GRN if s["destination"] in store.destinations() else RED))),
            ("estado", Text(s["status"], AMB)), ("link", Text(s["link"], DIM)) if s["link"] else None])
    doc.lines.append(flow)
    doc.blank().p(("Se o arquivo mudar depois da aprovação, o pedido precisa ser refeito (conteúdo travado por hash).", DIM))
    if s["status"] == "aprovada":
        doc.blank().p(("⚡ O agente posta no destino e registra o link com P.", VIO))
    return doc


def d_dec(store, it) -> Doc:
    d = it.data
    return Doc().h(f"{d['id']} · {d['title']}").kv([
        ("data", Text(f"{d['date']} · {wd_day(d['date'])}")), ("quem decidiu", Text(", ".join(d["decided_by_names"]))),
        ("projeto", Text.assemble(link(d["project"], d["project"]), f" {d['project_title']}") if d["project"] else Text("—", DIM)),
        ("contexto", Text(d["context"] or "—")), ("porquê", Text(d["rationale"] or "—")),
        ("estado", Text(d["status"], DIM)) if d["status"] != "ativa" else None,
        ("substitui", Text(d["supersedes"])) if d["supersedes"] else None,
        ("fonte", Text.assemble((d["source_label"], DIM), " ", prov(d["prov"])))]).sec("Equivalente na CLI").cmd("brain decision list" + (f" --project {d['project']}" if d["project"] else ""))


def d_del(store, it) -> Doc:
    e = it.data
    return Doc().h(f"{e['id']} · {e['title']}").kv([
        ("data", Text(e["date"] or "—")), ("ligada a", Text(e["ref"] or "—")), ("resultado", Text(e["result"])),
        ("impacto", Text(e["impact"] or "—")), ("evidência", Text(e["evidence"] or "—", DIM))]).blank().p(
        ("Entregas alimentam o /recap e o /week. Fechar uma ação com --outcome cria uma automaticamente.", DIM))


def d_person(store, it) -> Doc:
    p = it.data
    doc = Doc().h(Text(p["name"], "bold"), (f"  · {p['id']}", DIM))
    doc.kv([("papel", Text(p["role"] or "—")), ("relação", Text(p["relation"] or "—")), ("e-mail", Text(p["email"] or "—")),
            ("aliases", Text(", ".join(p["aliases"]) or "—"))])
    doc.sec("Te deve")
    for i in p["owes_me"] or []:
        a = store.by_action[i]
        doc.p(link(i, i, "bold"), f" {a['title']} ", due_tag(a))
    if not p["owes_me"]:
        doc.p(("Nada em aberto.", DIM))
    doc.sec(f"Você deve a {p['name'].split(' ')[0]}")
    for i in p["i_owe"] or []:
        a = store.by_action[i]
        doc.p(link(i, i, "bold"), f" {a['title']} ", due_tag(a))
    if not p["i_owe"]:
        doc.p(("Nada em aberto.", DIM))
    doc.sec("Última interação")
    li = p["last_interaction"]
    doc.p(f"{util.fmt_date(li['date'])} · {li['title']}" if li else ("Sem registro.", DIM))
    return doc


def d_art(store, it) -> Doc:
    a = it.data
    return Doc().h(a["title"]).kv([("tipo", Text(a["kind"])), ("data", Text(a["date"] or "—")),
                                   ("pessoas", Text(", ".join(store.first_name(x) for x in a["people"]) or "—")),
                                   ("projetos", Text(", ".join(a["projects"]) or "—")), ("resumo", Text(a["summary"] or "—")),
                                   ("fonte RAW", Text.assemble((a["raw"] or "—", DIM), " · imutável"))]).blank().p(
        ("Artefatos são append-only. Para a letra exata, abra o RAW (tecla o) no seu editor.", DIM))
