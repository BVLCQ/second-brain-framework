"""Views Markdown em FRESH/ — legíveis em qualquer editor de texto.

Links relativos padrão. Uma nota por ação e por decisão em FRESH/records/
mantém o histórico citável; editar `status:` numa ficha vira declaração do
dono no próximo render (colheita em brainlib/harvest.py).
Mermaid é gerado por código, com sanitização — nunca quebra por sintaxe.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from . import planning, util

LEDGER = "PROCESSED/_ledger/events.jsonl"
PLANNING = "PLANNING/goals.md"
HEALTH_ICON = {"em-risco": "⚠", "travado": "⚠", "atencao": "·", "em-dia": "✓", "concluido": "✓",
               "congelado": "·", "fechado": "·"}


class Pages:
    def __init__(self, inst, m: dict):
        self.inst, self.m = inst, m
        self.fresh = inst.fresh
        self.files: dict[Path, str] = {}
        self.actions = {a["id"]: a for a in m["actions"]}
        self.decisions = {d["id"]: d for d in m["decisions"]}
        self.projects = {p["id"]: p for p in m["projects"]}
        self.goals = {g["id"]: g for g in m["goals"]}
        self.people = {p["id"]: p for p in m["people"]}
        self.today = date.fromisoformat(m["today"])

    # ── helpers ─────────────────────────────────────────────────────────────
    def link(self, frm: str, to: str, text: str) -> str:
        rel = os.path.relpath(to, os.path.dirname(frm) or ".")
        return f"[{text}]({rel.replace(' ', '%20')})"

    def proj(self, frm: str, pid: str | None, short: bool = True) -> str:
        if not pid or pid not in self.projects:
            return "—"
        label = pid if short else f"{pid} {self.projects[pid]['title']}"
        return self.link(frm, f"projects/{pid}.md", label)

    def person(self, frm: str, pid: str) -> str:
        p = self.people.get(pid)
        return self.link(frm, f"people/{pid}.md", p["name"]) if p else pid

    def act(self, frm: str, aid: str) -> str:
        return self.link(frm, f"records/actions/{aid}.md", aid)

    def dec(self, frm: str, did: str) -> str:
        return self.link(frm, f"records/decisions/{did}.md", did)

    def header(self, title: str, fontes: list[str], extra: dict | None = None) -> str:
        fm = {"generated-at": self.m["generated_at"], "fontes": fontes, **(extra or {})}
        lines = ["---"] + [f"{k}: {_yaml(v)}" for k, v in fm.items()] + ["---", "", f"# {title}", ""]
        return "\n".join(lines)

    @staticmethod
    def bar(pct: int | None) -> str:
        if pct is None:
            return "sem entregáveis"
        filled = round(pct / 10)
        return f"{'▰' * filled}{'▱' * (10 - filled)} {pct}%"

    def due_txt(self, a: dict) -> str:
        if not a["open"]:
            return f"{'feita' if a['status'] == 'fechada' else 'descartada'} {util.fmt_date(a['closed'])}"
        if not a["due"]:
            return "sem prazo"
        txt = util.fmt_date(a["due"], with_weekday=True)
        if a.get("due_suggested"):
            txt += " (sugerido)"
        if a["overdue_days"]:
            return f"⚠ {txt} (atrasada {a['overdue_days']}d)"
        if a["due_in"] is not None and a["due_in"] <= 7:
            return f"{txt} (em {a['due_in']}d)" if a["due_in"] else f"{txt} (hoje)"
        return txt

    def put(self, rel: str, text: str) -> None:
        self.files[self.fresh / rel] = text.rstrip() + "\n"

    # ── páginas ─────────────────────────────────────────────────────────────
    def home(self) -> None:
        m, c, f = self.m, self.m["counts"], "home.md"
        gen = util.parse_dt(m["generated_at"])
        out = [self.header(f"☀ Início — {util.fmt_date(self.today, True)} · gerado {gen:%H:%M}",
                           [PLANNING, LEDGER]),
               f"> **{c['mine_open']}** minhas abertas · **{c['mine_overdue']}** atrasadas · "
               f"**{c['mine_due_7d']}** vencem em 7 dias · **{c['waiting_open']}** aguardando outros · "
               f"**{c['wins_30d']}** conquistas em 30 dias",
               ]
        pf = m["portfolio"]
        if pf["areas"] or pf["processes"] or pf["opportunities"]:
            pc = pf["counts"]
            out.append(f"> Portfólio: **{pc['opportunities']}** oportunidades · **{pc['prioritized']}** priorizadas · "
                       f"**{pc['gaps']}** lacunas — {self.link(f, 'opportunities.md', 'oportunidades')} · "
                       f"{self.link(f, 'processes.md', 'processos')}")
        out += ["", "## Goals", ""]
        if not m["goals"]:
            out.append("_Nenhum goal no PLANNING ainda — rode `/init` ou `/goal`._")
        for g in m["goals"]:
            out.append(f"### {g['id']} — {g['title']} · {self.bar(g['progress']['pct'])} · "
                       f"{planning.format_progress(g['progress'])} · "
                       f"{HEALTH_ICON.get(g['health'], '')} {g['health_label']}")
            if g["declared"]:
                out.append(f"_declarado pelo dono: {g['declared']['pct']}% em "
                           f"{util.fmt_date(g['declared']['date'])}_")
            for pid in g["projects"]:
                p = self.projects[pid]
                nxt = f" · próximo: {p['next_due']['id']} {util.fmt_date(p['next_due']['date'])}" \
                    if p["next_due"] else ""
                out.append(f"- {self.proj(f, pid, short=False)} · {self.bar(p['progress']['pct'])} · "
                           f"{HEALTH_ICON.get(p['health']['level'], '')} {p['health']['label']} — "
                           f"{p['health']['reason']}{nxt}")
            out.append("")
        out += ["## Hoje e próximos 7 dias", ""]
        if not m["agenda"]:
            out.append("_Nada com data nos próximos 7 dias._")
        for it in m["agenda"]:
            warn = f"⚠ atrasado {it['overdue_days']}d · " if it["overdue_days"] else ""
            ref = self.act(f, it["id"]) if it["id"].startswith("TASK-") else it["id"]
            out.append(f"- {util.fmt_date(it['date'], True)} · {it['kind']} · {warn}{ref} {it['title']}"
                       + (f" · {self.proj(f, it['project'])}" if it.get("project") else ""))
        out += ["", "## Precisa de você", ""]
        needs = []
        for p in m["proposals"]:
            needs.append(f"- proposta **{p['id']}** ({p['kind']}): {p['summary']}"
                         + (f" — evidência: `{p['evidence']}`" if p["evidence"] else ""))
        fo = m["focus"]
        if fo and fo["status"] == "proposto":
            needs.append(f"- plano de foco **{fo['id']}** com {len(fo['blocks'])} blocos aguardando seu "
                         f"\"ok\" — {self.link(f, 'focus.md', 'ver plano')}")
        for msg in m["outbox"]:
            if msg["status"] == "rascunho":
                needs.append(f"- rascunho **{msg['id']}** para {msg['to_name']}: "
                             f"\"{_clip(msg['text'], 80)}\" — {self.link(f, 'outbox.md', 'revisar')}")
        if c["mine_no_due"]:
            needs.append(f"- {c['mine_no_due']} ações suas sem prazo (o foco não consegue agendar)")
        out += needs or ["_Nada aguardando sua decisão._"]
        out += ["", "## Conquistas recentes", ""]
        wins = self.recent_wins(6)
        out += wins or ["_Nenhuma entrega registrada nos últimos 30 dias — declare no `/week` ou com `/done`._"]
        out += ["", "## Decisões recentes", ""]
        for d in m["decisions"][:6]:
            out.append(f"- {util.fmt_date(d['date'])} · {self.dec(f, d['id'])} {d['title']} — "
                       f"{', '.join(d['decided_by_names'])}" + (f" · {self.proj(f, d['project'])}"
                                                                if d["project"] else ""))
        if not m["decisions"]:
            out.append("_Nenhuma decisão registrada._")
        out += ["", "## Aguardando de outros", ""]
        waiting = [a for a in m["actions"] if a["open"] and a["list"] == "waiting"]
        by_owner: dict[str, list] = {}
        for a in waiting:
            by_owner.setdefault(a["owner"], []).append(a)
        for owner, items in sorted(by_owner.items(), key=lambda kv: -len(kv[1])):
            out.append(f"- {self.person(f, owner)}: " + "; ".join(
                f"{self.act(f, a['id'])} {_clip(a['title'], 50)} ({a['aging_days']}d)" for a in items))
        if not waiting:
            out.append("_Ninguém te devendo nada registrado._")
        out += ["", "---", "", "Painel completo: " + " · ".join([
            self.link(f, "dashboard/index.html", "painel (HTML)"), self.link(f, "todo.md", "TODO"),
            self.link(f, "goals.md", "Goals"), self.link(f, "decisions.md", "Decisões"),
            self.link(f, "wins.md", "Conquistas"), self.link(f, "timeline.md", "Linha do tempo"),
            self.link(f, "map.md", "Mapa"), self.link(f, "focus.md", "Foco"),
            self.link(f, "outbox.md", "Mensagens"), self.link(f, "health.md", "Saúde")]
            + ([self.link(f, "opportunities.md", "Oportunidades"), self.link(f, "processes.md", "Processos")]
               if pf["areas"] or pf["processes"] or pf["opportunities"] else []))]
        self.put(f, "\n".join(out))

    def recent_wins(self, n: int) -> list[str]:
        items = []
        for e in self.m["deliveries"]:
            items.append((e["date"] or "", f"entrega {e['id']}: {e['title']} — {e['result']} [{e['prov']}]"))
        for x in self.m["deliverables_done"]:
            items.append((x["date"] or "", f"entregável {x['id']} concluído: {x['title']}"))
        items.sort(reverse=True)
        return [f"- {util.fmt_date(d)} · {t}" for d, t in items[:n]]

    def todo(self) -> list:
        f, m = "todo.md", self.m
        out = [self.header("TODO", [LEDGER]),
               "> Marque `[x]` para fechar uma ação (vira declaração sua no próximo `brain render`). "
               "Desmarcar reabre. Outras edições neste arquivo são descartadas.", ""]
        mine = [a for a in m["actions"] if a["list"] == "mine" and a["mine"]]
        recent_cut = (self.today.toordinal() - 14)
        groups = [("Fazendo", lambda a: a["open"] and a["status"] == "fazendo"),
                  ("A fazer", lambda a: a["open"] and a["status"] == "aberta"),
                  ("Bloqueadas", lambda a: a["open"] and a["status"] == "bloqueada"),
                  ("Aguardando terceiros", lambda a: a["open"] and a["status"] == "aguardando"),
                  ("Feitas (14 dias)", lambda a: a["status"] == "fechada" and a["closed"]
                   and date.fromisoformat(a["closed"]).toordinal() >= recent_cut)]
        checks: dict[str, bool] = {}
        out.append("## Minhas")
        for title, pred in groups:
            items = sorted((a for a in mine if pred(a)),
                           key=lambda a: (a["due"] or "9999", a["priority"] != "alta", a["id"]))
            out += ["", f"### {title} ({len(items)})", ""]
            for a in items:
                done = a["status"] == "fechada"
                checks[a["id"]] = done
                bits = [f"- [{'x' if done else ' '}] **{a['id']}** {a['title']}", self.due_txt(a)]
                if a["effort_min"]:
                    bits.append(util.fmt_duration(a["effort_min"]))
                if a["project"]:
                    bits.append(self.proj(f, a["project"]))
                if a["blocked_by"]:
                    bits.append("⛔ " + ", ".join(
                        f"{b} ({self.actions[b]['owner_name']})" for b in a["blocked_by"] if b in self.actions))
                if a["priority"] == "alta":
                    bits.append("prioridade alta")
                out.append(" · ".join(bits))
            if not items:
                out.append("_—_")
        out += ["", "## Aguardando de outros (o que me devem)", ""]
        waiting = [a for a in m["actions"] if a["open"] and a["list"] == "waiting"]
        by_owner: dict[str, list] = {}
        for a in waiting:
            by_owner.setdefault(a["owner"], []).append(a)
        for owner, items in sorted(by_owner.items(), key=lambda kv: kv[0]):
            out += [f"### {self.people.get(owner, {}).get('name', owner)}", ""]
            for a in sorted(items, key=lambda a: a["due"] or "9999"):
                checks[a["id"]] = False
                out.append(f"- [ ] **{a['id']}** {a['title']} · {self.due_txt(a)} · há {a['aging_days']}d"
                           + (f" · {self.proj(f, a['project'])}" if a["project"] else ""))
            out.append("")
        if not waiting:
            out.append("_—_")
        watching = [a for a in m["actions"] if a["open"] and a["list"] == "watching"]
        out += ["", f"> [!note]- Observando — contexto, não cobra ({len(watching)})"]
        for a in watching:
            out.append(f"> - {a['id']} {a['title']} · {a['owner_name']}"
                       + (f" · {a['project']}" if a["project"] else ""))
        self.put(f, "\n".join(out))
        return checks

    def goals_page(self) -> None:
        f = "goals.md"
        out = [self.header("Goals — árvore e progresso", [PLANNING, LEDGER]),
               "> Progresso = entregáveis feitos (por peso) ÷ não cancelados. A estrutura é editada no "
               "`PLANNING/goals.md` (com gate); aqui é só leitura.", ""]
        for g in self.m["goals"]:
            out.append(f"## {g['id']} — {g['title']}")
            out.append(f"status: {g['status']} · horizonte: {g['horizon'] or '—'} · "
                       f"{self.bar(g['progress']['pct'])} {planning.format_progress(g['progress'])} · "
                       f"{g['health_label']}")
            if g["why"]:
                out.append(f"_por quê: {g['why']}_")
            if g["declared"]:
                out.append(f"_declarado: {g['declared']['pct']}% em {util.fmt_date(g['declared']['date'])}"
                           + (f" — {g['declared']['note']}" if g["declared"]["note"] else "") + "_")
            out.append("")
            for pid in g["projects"]:
                p = self.projects[pid]
                out.append(f"### {self.proj(f, pid, short=False)} · {self.bar(p['progress']['pct'])} · "
                           f"{p['health']['label']} — {p['health']['reason']}")
                for d in p["deliverables"]:
                    box = {"feito": "x", "cancelado": "-"}.get(d["status"], " ")
                    extra = f" · feito {util.fmt_date(d['done_date'])}" if d["done_date"] else \
                        (f" · prazo {util.fmt_date(d['due'])}" if d["due"] else " · sem prazo")
                    if d["overdue_days"]:
                        extra += f" ⚠ venceu há {d['overdue_days']}d"
                    if d["status"] == "em-andamento":
                        extra += " · em andamento"
                    out.append(f"- [{box}] {d['id']} {d['title']}{extra}")
                out.append("")
        if self.m["plan_warnings"]:
            out += ["## ⚠ Avisos do parser", ""] + [f"- {w}" for w in self.m["plan_warnings"]]
        self.put(f, "\n".join(out))

    def project_pages(self) -> None:
        for p in self.m["projects"]:
            f = f"projects/{p['id']}.md"
            nd = p["next_due"]
            out = [self.header(f"{p['id']} — {p['title']}", [PLANNING, LEDGER], {
                "id": p["id"], "titulo": p["title"], "goal": p["goal"], "status": p["status"],
                "saude": p["health"]["level"], "progresso": p["progress"]["pct"],
                "proximo_prazo": nd["date"] if nd else None, "tags": ["projeto"]}),
                f"{self.link(f, 'goals.md', p['goal'] + ' ' + p['goal_title'])} · saúde: "
                f"**{p['health']['label']}** — {p['health']['reason']} · {self.bar(p['progress']['pct'])} "
                f"{planning.format_progress(p['progress'])}"
                + (f" · dono: {self.person(f, p['owner'])}" if p["owner"] in self.people else ""), ""]
            if p["declared"]:
                out += [f"_progresso declarado pelo dono: {p['declared']['pct']}% em "
                        f"{util.fmt_date(p['declared']['date'])}_", ""]
            out += ["## Entregáveis", ""]
            for d in p["deliverables"]:
                box = {"feito": "x", "cancelado": "-"}.get(d["status"], " ")
                extra = f"feito {util.fmt_date(d['done_date'])}" if d["done_date"] else \
                    (f"prazo {util.fmt_date(d['due'], True)}" if d["due"] else "sem prazo")
                if d["overdue_days"]:
                    extra += f" ⚠ venceu há {d['overdue_days']}d"
                elif d["due_in"] is not None and d["status"] not in ("feito", "cancelado") and d["due_in"] <= 14:
                    extra += f" (em {d['due_in']}d)"
                out.append(f"- [{box}] **{d['id']}** {d['title']} · {extra}")
            if not p["deliverables"]:
                out.append("_Sem entregáveis no PLANNING — progresso não calculável._")
            out += ["", "_Estado dos entregáveis: edite o checkbox em `PLANNING/goals.md` ou peça ao agente._",
                    "", "## Decisões — quem decidiu o quê, quando", ""]
            if p["decisions"]:
                out += ["| Data | ID | Decisão | Quem decidiu | Estado | Fonte |", "|---|---|---|---|---|---|"]
                for did in p["decisions"]:
                    d = self.decisions[did]
                    who = ", ".join(self.person(f, x) for x in d["decided_by"])
                    st = d["status"] + (f" → {d['superseded_by']}" if d["superseded_by"] else "")
                    out.append(f"| {util.fmt_date(d['date'])} | {self.dec(f, did)} | {_cell(d['title'])} | "
                               f"{who} | {st} | {_cell(d['source_label'])} [{d['prov']}] |")
            else:
                out.append("_Nenhuma decisão registrada para este projeto._")
            out += ["", "## Ações", ""]
            sections = [("Minhas abertas", p["actions"]["mine"]), ("Aguardando de outros", p["actions"]["waiting"]),
                        ("Observando", p["actions"]["watching"])]
            for title, ids in sections:
                out += [f"### {title} ({len(ids)})", ""]
                if ids:
                    out += ["| ID | Quem | O quê | Prazo | Estado | Idade |", "|---|---|---|---|---|---|"]
                    for aid in ids:
                        a = self.actions[aid]
                        out.append(f"| {self.act(f, aid)} | {self.person(f, a['owner'])} | {_cell(a['title'])} | "
                                   f"{_cell(self.due_txt(a))} | {a['status']} | {a['aging_days']}d |")
                else:
                    out.append("_—_")
                out.append("")
            if p["actions"]["closed"]:
                out += ["### Fechadas recentemente", ""]
                for aid in p["actions"]["closed"]:
                    a = self.actions[aid]
                    out.append(f"- {util.fmt_date(a['closed'])} · {self.act(f, aid)} {a['title']} "
                               f"({a['owner_name']}) — {a['how'] or a['status']}")
                out.append("")
            out += ["## Linha do tempo", ""]
            for it in p["timeline"][:40]:
                who = f" ({it['who']})" if it.get("who") else ""
                ref = self.act(f, it["id"]) + " " if it["id"].startswith("TASK-") else \
                    (self.dec(f, it["id"]) + " " if it["id"].startswith("DEC-") else
                     ("" if "/" in it["id"] else it["id"] + " "))
                out.append(f"- {util.fmt_date(it['date'])} · {it['kind']} · {ref}{it['title']}{who}")
            if not p["timeline"]:
                out.append("_Sem eventos registrados._")
            out += ["", "## Pessoas", ""]
            for person in p["people"]:
                out.append(f"- {self.person(f, person['id'])} — {', '.join(person['roles'])} ({person['count']})")
            if not p["people"]:
                out.append("_—_")
            self.put(f, "\n".join(out))

    def decisions_page(self) -> None:
        f = "decisions.md"
        out = [self.header("Decisões — quem decidiu o quê, quando", [LEDGER]),
               f"> {len(self.m['decisions'])} decisões · substituídas ficam riscadas, nunca apagadas.", ""]
        groups: dict[str, list] = {}
        for d in self.m["decisions"]:
            groups.setdefault(d["project"] or "—", []).append(d)
        for pid in sorted(groups, key=lambda k: (k == "—", k)):
            title = f"{pid} {self.projects[pid]['title']}" if pid in self.projects else "Sem projeto"
            out += [f"## {title}", "", "| Data | ID | Decisão | Quem decidiu | Fonte |", "|---|---|---|---|---|"]
            for d in groups[pid]:
                text = _cell(d["title"])
                if d["status"] == "substituida":
                    text = f"~~{text}~~ → {d['superseded_by'] or '?'}"
                out.append(f"| {util.fmt_date(d['date'])} | {self.dec(f, d['id'])} | {text} | "
                           f"{', '.join(self.person(f, x) for x in d['decided_by'])} | "
                           f"{_cell(d['source_label'])} [{d['prov']}] |")
            out.append("")
        if not self.m["decisions"]:
            out.append("_Nenhuma decisão registrada ainda._")
        self.put(f, "\n".join(out))

    def wins_page(self) -> None:
        f = "wins.md"
        w = self.m["wins"]
        out = [self.header("Conquistas — o que foi entregue", [LEDGER, PLANNING]),
               f"> Últimos 30 dias: **{w['last_30d']}** entregas/entregáveis · **{w['closed_30d']}** ações suas "
               f"fechadas. Resultado sem fonte aparece como \"não declarado\" — nunca inventado.", ""]
        dl = {e["id"]: e for e in self.m["deliveries"]}
        dd = {x["id"]: x for x in self.m["deliverables_done"]}
        for wk in w["weeks"]:
            n = len(wk["deliveries"]) + len(wk["deliverables"])
            out += [f"## {wk['label']} — {n} entregas · {len(wk['closed'])} ações fechadas · "
                    f"{len(wk['decisions'])} decisões", ""]
            for eid in wk["deliveries"]:
                e = dl[eid]
                out.append(f"- ✓ **{e['title']}** ({util.fmt_date(e['date'])}) — {e['result']}"
                           + (f" · impacto: {e['impact']}" if e["impact"] else "")
                           + (f" · {self.proj(f, e['project'])}" if e["project"] else "") + f" [{e['prov']}]")
            for did in wk["deliverables"]:
                x = dd[did]
                out.append(f"- ✓ entregável **{did}** {x['title']} ({util.fmt_date(x['date'])})"
                           f" · {self.proj(f, x['project'])}")
            if wk["closed"]:
                out.append("- ações fechadas: " + ", ".join(
                    f"{self.act(f, a)} {_clip(self.actions[a]['title'], 40)}" for a in wk["closed"]))
            if not n and not wk["closed"]:
                out.append("_nada registrado_")
            out.append("")
        self.put(f, "\n".join(out))

    def people_pages(self) -> None:
        idx = ["| Pessoa | Papel | Última interação | Me deve | Devo |", "|---|---|---|---|---|"]
        for p in self.m["people"]:
            f = f"people/{p['id']}.md"
            li = p["last_interaction"]
            out = [self.header(p["name"], [LEDGER], {"id": p["id"], "papel": p["role"], "relacao": p["relation"],
                                                     "aliases": p["aliases"], "tags": ["pessoa"]}),
                   f"{p['role'] or 'papel não registrado'} · relação: {p['relation'] or '—'} · aliases: "
                   f"{', '.join(p['aliases']) or '—'}", ""]
            out.append(f"**Última interação:** {util.fmt_date(li['date'])} — {li['title']}" if li
                       else "**Última interação:** não consta")
            out += ["", "## O que me deve", ""]
            out += [f"- {self.act(f, a)} {self.actions[a]['title']} · {self.due_txt(self.actions[a])}"
                    for a in p["owes_me"]] or ["_nada_"]
            out += ["", "## O que eu devo", ""]
            out += [f"- {self.act(f, a)} {self.actions[a]['title']} · {self.due_txt(self.actions[a])}"
                    for a in p["i_owe"]] or ["_nada_"]
            out += ["", "## Decisões que tomou", ""]
            out += [f"- {util.fmt_date(self.decisions[d]['date'])} · {self.dec(f, d)} {self.decisions[d]['title']}"
                    for d in p["decisions"]] or ["_nenhuma registrada_"]
            out += ["", "## Projetos", ""]
            out += [f"- {self.proj(f, x, short=False)}" for x in p["projects"]] or ["_—_"]
            out += ["", "## Menções recentes", ""]
            arts = {a["id"]: a for a in self.m["artifacts"]}
            out += [f"- {util.fmt_date(arts[a]['date'])} · {arts[a]['title']} (`{a}`)" for a in p["artifacts"]
                    if a in arts] or ["_—_"]
            self.put(f, "\n".join(out))
            idx.append(f"| {self.link('people.md', f, p['name'])} | {_cell(p['role'])} | "
                       f"{util.fmt_date(li['date']) + ' ' + _cell(_clip(li['title'], 40)) if li else '—'} | "
                       f"{len(p['owes_me'])} | {len(p['i_owe'])} |")
        self.put("people.md", self.header("Pessoas", [LEDGER]) + "\n".join(idx))

    def timeline_page(self) -> None:
        f, tl = "timeline.md", self.m["timeline"]
        out = [self.header("Linha do tempo", [LEDGER, PLANNING]),
               f"> Passado: {util.fmt_date(tl['back'])} → hoje · Futuro: hoje → {util.fmt_date(tl['ahead'])}. "
               "Período sem evento fica de fora — timeline honesta.", "", "## Próximos prazos", ""]
        if tl["future"]:
            out += ["```mermaid", "gantt", "    title Próximos prazos", "    dateFormat YYYY-MM-DD",
                    "    axisFormat %d/%m", "    todayMarker stroke-width:3px,stroke:#e5484d"]
            groups: dict[str, list] = {}
            for it in tl["future"]:
                groups.setdefault(it["project"] or "sem projeto", []).append(it)
            n = 0
            for pid, items in groups.items():
                label = f"{pid} {self.projects[pid]['title']}" if pid in self.projects else pid
                out.append(f"    section {_mm(label, 40)}")
                for it in items:
                    n += 1
                    crit = "crit, " if it["overdue"] else ""
                    out.append(f"    {_mm(it['id'] + ' ' + it['title'], 50)} :{crit}milestone, m{n}, {it['date']}, 0d")
            out += ["```", ""]
            for it in tl["future"]:
                out.append(f"- {util.fmt_date(it['date'], True)} · {it['kind']} {it['id']} {it['title']}"
                           + (" ⚠ atrasado" if it["overdue"] else ""))
        else:
            out.append("_Nenhum prazo nos próximos dias — ações e entregáveis sem data não aparecem aqui._")
        out += ["", "## O que aconteceu", ""]
        if tl["past"]:
            weeks: dict[str, list] = {}
            for it in tl["past"]:
                weeks.setdefault(util.week_key(date.fromisoformat(it["date"])), []).append(it)
            out += ["```mermaid", "timeline", "    title O que aconteceu"]
            for wk in sorted(weeks):
                out.append(f"    section {_mm(util.week_label(wk), 40)}")
                for it in sorted(weeks[wk], key=lambda x: x["date"])[:8]:
                    ref = "" if "/" in it["id"] else it["id"] + " "
                    out.append(f"        {util.fmt_date(it['date'])} : {_mm(it['kind'] + ' ' + ref + it['title'], 60)}")
            out += ["```", ""]
            for it in tl["past"]:
                who = f" — {it['who']}" if it.get("who") else ""
                ref = "" if "/" in it["id"] else f"{it['id']} "
                out.append(f"- {util.fmt_date(it['date'])} · {it['kind']} · {ref}{it['title']}{who}")
        else:
            out.append("_Nada registrado no período._")
        self.put(f, "\n".join(out))

    def map_page(self) -> None:
        f = "map.md"
        out = [self.header("Mapa", [PLANNING, LEDGER]), "## Goals e projetos", "", "```mermaid", "graph TD"]
        for g in self.m["goals"]:
            out.append(f'    {g["id"]}["{_mm(g["id"] + " " + g["title"], 40)} · {g["progress"]["pct"] or 0}%"]')
            for pid in g["projects"]:
                p = self.projects[pid]
                out.append(f'    {pid}["{_mm(pid + " " + p["title"], 40)} · {p["progress"]["pct"] or 0}% · '
                           f'{p["health"]["label"]}"]')
                out.append(f"    {g['id']} --> {pid}")
                if p["health"]["level"] in ("em-risco", "travado"):
                    out.append(f"    class {pid} risco")
        out += ["    classDef risco fill:#fde2e1,stroke:#e5484d", "```", "", "## Pessoas × projetos", "",
                "```mermaid", "graph LR"]
        edges = []
        for p in self.m["projects"]:
            for person in p["people"][:8]:
                edges.append((person["count"], person["id"], p["id"], "/".join(person["roles"][:2])))
        top = sorted(edges, reverse=True)[:30]
        nodes = {pid for _, pid, _, _ in top}
        for pid in nodes:
            out.append(f'    ST_{_mmid(pid)}["{_mm(self.people[pid]["name"], 30)}"]')
        for _, person, pid, role in top:
            out.append(f'    ST_{_mmid(person)} -->|"{_mm(role, 20)}"| {pid}')
        out += ["```", "", "## Dependências entre ações abertas", ""]
        dep_lines = []
        for a in self.m["actions"]:
            if not a["open"]:
                continue
            for b in a["blocked_by_all"]:
                if b in self.actions and self.actions[b]["open"]:
                    dep_lines.append(f'    {_mmid(b)}["{_mm(b + " " + self.actions[b]["title"], 35)}"] -->|bloqueia| '
                                     f'{_mmid(a["id"])}["⛔ {_mm(a["id"] + " " + a["title"], 35)}"]')
            for u in a["unblocks"]:
                tgt = self.actions.get(u)
                label = _mm(u + " " + (tgt["title"] if tgt else self.projects.get(u, {}).get("title", "")), 35)
                dep_lines.append(f'    {_mmid(a["id"])}["{_mm(a["id"] + " " + a["title"], 35)}"] -->|destrava| '
                                 f'{_mmid(u)}["{label}"]')
        if dep_lines:
            out += ["```mermaid", "graph LR"] + dep_lines[:30] + ["```"]
        else:
            out.append("_Nenhuma dependência registrada entre ações abertas._")
        self.put(f, "\n".join(out))

    def focus_page(self) -> None:
        f, fo = "focus.md", self.m["focus"]
        out = [self.header("Foco — tempo protegido para as suas ações", [LEDGER, "config/brain.toml"])]
        if not fo:
            out.append("_Nenhum plano ainda. Peça `/focus` (o agente lê sua agenda e propõe os blocos da semana)._")
            self.put(f, "\n".join(out))
            return
        status_txt = {"proposto": "**aguardando seu \"ok\"** (nada foi para o calendário)",
                      "aprovado": "aprovado — falta aplicar", "aplicado": f"aplicado ({fo['mode']})",
                      "substituido": "substituído por um plano mais novo"}[fo["status"]]
        out += [f"Plano **{fo['id']}** · {status_txt}"
                + (f" · aprovação: \"{fo['quote']}\"" if fo["quote"] else ""), ""]
        blocks = fo["applied"] if fo["status"] == "aplicado" else fo["blocks"]
        days: dict[str, list] = {}
        for blk in blocks:
            days.setdefault(blk["start"][:10], []).append(blk)
        for day in sorted(days):
            out += [f"### {util.fmt_date(day, True)}", ""]
            for blk in sorted(days[day], key=lambda x: x["start"]):
                a = self.actions.get(blk["action"])
                out.append(f"- {blk['start'][11:16]}–{blk['end'][11:16]} · {self.act(f, blk['action'])} "
                           f"{a['title'] if a else ''}" + (f" · {self.proj(f, a['project'])}" if a and a['project'] else ""))
            out.append("")
        if fo["at_risk"]:
            out += ["## ⚠ Não cabe antes do prazo", ""]
            for r in fo["at_risk"]:
                out.append(f"- {self.act(f, r['action'])} prazo {util.fmt_date(r['due'])}: faltam "
                           f"{util.fmt_duration(r['shortfall_min'])} de {util.fmt_duration(r['needed_min'])} — "
                           "renegociar prazo, cortar escopo ou liberar agenda")
            out.append("")
        if fo["missing_effort"]:
            out += ["## Sem estimativa de esforço (usei o padrão)", "",
                    ", ".join(self.act(f, a) for a in fo["missing_effort"]), ""]
        if fo["consumed"]:
            out += ["## Esforço consumido e ainda aberta — reestimar?", "",
                    ", ".join(self.act(f, a) for a in fo["consumed"]), ""]
        if fo["status"] == "proposto":
            out.append("> Para aprovar, responda **ok** no chat — o agente registra sua resposta literal e aplica.")
        self.put(f, "\n".join(out))

    def outbox_page(self) -> None:
        f = "outbox.md"
        out = [self.header("Mensagens — rascunhos, aprovações e envios", [LEDGER]),
               "> Nada é enviado sem a sua aprovação do texto exato. Todo envio fica registrado aqui.", ""]
        for title, sts in (("Aguardando sua aprovação", {"rascunho"}), ("Aprovadas, não enviadas", {"aprovada"}),
                           ("Enviadas", {"enviada"}), ("Falhas / canceladas", {"falhou", "cancelada"})):
            items = [x for x in self.m["outbox"] if x["status"] in sts]
            out += [f"## {title} ({len(items)})", ""]
            for x in items:
                out.append(f"**{x['id']}** → {x['to_name']}" + (f" · ref {x['ref']}" if x["ref"] else "")
                           + (f" · por quê: {x['why']}" if x["why"] else "")
                           + (f" · enviada {util.fmt_date(x['sent'])}" if x["sent"] else ""))
                out += ["", *[f"> {ln}" for ln in x["text"].splitlines()], ""]
            if not items:
                out += ["_—_", ""]
        self.put(f, "\n".join(out))

    def records(self) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for a in self.m["actions"]:
            statuses[a["id"]] = a["kanban"]
            fm = {"id": a["id"], "titulo": a["title"], "status": a["kanban"],
                  "lista": {"mine": "minhas", "waiting": "aguardando", "watching": "observando"}[a["list"]],
                  "dono": a["owner_name"], "prazo": a["due"], "prazo_sugerido": bool(a["due_suggested"]), "esforco_min": a["effort_min"],
                  "projeto": a["project"], "goal": a["goal"], "atraso_dias": a["overdue_days"],
                  "idade_dias": a["aging_days"], "aberta_em": a["opened"], "fechada_em": a["closed"],
                  "prioridade": a["priority"], "fonte": a["source_label"], "prov": a["prov"], "tags": ["acao"]}
            f = f"records/actions/{a['id']}.md"
            body = [f"# {a['id']} · {a['title']}", "",
                    "> Edite `status:` acima (a fazer · fazendo · aguardando · feita · descartada) — vira declaração sua no próximo render.",
                    "", f"Dono: {self.person(f, a['owner'])} · lista: {fm['lista']} · {self.due_txt(a)}"
                    + (f" · projeto {self.proj(f, a['project'], short=False)}" if a["project"] else ""), ""]
            if a["blocked_by"]:
                body.append("⛔ bloqueada por " + ", ".join(self.act(f, b) for b in a["blocked_by"]))
            if a["unblocks"]:
                body.append("destrava: " + ", ".join(a["unblocks"]))
            if a["outcome"]:
                body.append(f"Resultado: {a['outcome']}")
            body += ["", "## Histórico", ""]
            body += [f"- {h['date']} · {h['type']} · {h['note']} ({h['by']})" for h in a["history"]]
            self.put(f, _frontmatter(fm) + "\n".join(body))
        for d in self.m["decisions"]:
            f = f"records/decisions/{d['id']}.md"
            fm = {"id": d["id"], "titulo": d["title"], "data": d["date"], "quem_decidiu": d["decided_by_names"],
                  "projeto": d["project"], "goal": d["goal"], "status": d["status"],
                  "substituida_por": d["superseded_by"], "fonte": d["source_label"], "prov": d["prov"],
                  "tags": ["decisao"]}
            body = [f"# {d['id']} · {d['title']}", "",
                    f"Decidido por {', '.join(self.person(f, x) for x in d['decided_by'])} em "
                    f"{util.fmt_date(d['date'])}" + (f" · {self.proj(f, d['project'], short=False)}" if d["project"] else ""),
                    ""]
            if d["context"]:
                body.append(f"**Contexto:** {d['context']}")
            if d["rationale"]:
                body.append(f"**Por quê:** {d['rationale']}")
            body.append(f"**Fonte:** {d['source_label']} (`{d['source']}`) [{d['prov']}]")
            if d["supersedes"]:
                body.append(f"Substitui {self.dec(f, d['supersedes'])}")
            if d["superseded_by"]:
                body.append(f"Substituída por {self.dec(f, d['superseded_by'])}")
            self.put(f, _frontmatter(fm) + "\n".join(body))
        return statuses

    def health_page(self, checks: list[dict]) -> None:
        out = [self.header("Saúde da instância", ["brain doctor"])]
        icon = {"ok": "✓", "warn": "⚠", "error": "✗"}
        for c in checks:
            out.append(f"- {icon[c['level']]} **{c['title']}** — {c['detail']}")
        self.put("health.md", "\n".join(out))


def _yaml(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return json.dumps(v, ensure_ascii=False)
    s = str(v)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return json.dumps(s, ensure_ascii=False)


def _frontmatter(fm: dict) -> str:
    return "---\n" + "\n".join(f"{k}: {_yaml(v)}" for k, v in fm.items()) + "\n---\n\n"


def _clip(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def _mm(s: str, n: int = 50) -> str:
    """Texto seguro para Mermaid: sem aspas, dois-pontos, ponto-e-vírgula, # ou colchetes."""
    s = re.sub(r"[\"`]", "'", s or "")
    s = re.sub(r"[:;#<>{}\[\]|]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _clip(s, n)


def _mmid(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", s)

