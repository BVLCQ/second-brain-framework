"""Views FRESH do portfólio: processes.md, opportunities.md e as fichas records/processes|opportunities.

Tudo vem de `m["portfolio"]` (brainlib/portfolio.py) — aqui só se formata. A ficha de OPP aceita editar
`status:` (colhido em harvest.py no próximo render).
"""
from __future__ import annotations

from . import util
from .render_md import Pages, _cell, _clip, _frontmatter
from .schema import OPP_STATUS

LEDGER = "PROCESSED/_ledger/events.jsonl"
PLANNING = "PLANNING/goals.md"
REC_LABEL = {"diaria": "diária", "semanal": "semanal", "quinzenal": "quinzenal", "mensal": "mensal",
             "trimestral": "trimestral", "sob-demanda": "sob demanda", "por-evento": "por evento"}


def hours(v) -> str:
    return "—" if v is None else f"{v:g}".replace(".", ",") + " h/mês"


def ice(o: dict) -> str:
    if o["score"] is None:
        return "sem ICE"
    return f"{o['impact']}×{o['confidence']}×{o['ease']} = **{o['score']}**" + (" (sugerido)" if o["ice_suggested"] else "")


def render(pg: Pages) -> dict[str, str]:
    """Escreve as páginas do portfólio em `pg` e devolve {id: status} das fichas de OPP (para a colheita)."""
    pf = pg.m["portfolio"]
    areas = {a["id"]: a for a in pf["areas"]}
    opps = {o["id"]: o for o in pf["opportunities"]}
    procs = {p["id"]: p for p in pf["processes"]}

    def area(a: str) -> str:
        return areas[a]["name"] if a in areas else a

    def who(frm: str, pid: str | None) -> str:
        return pg.person(frm, pid) if pid else "—"

    def plink(frm: str, pid: str) -> str:
        return pg.link(frm, f"records/processes/{pid}.md", pid) if pid in procs else pid

    def olink(frm: str, oid: str) -> str:
        return pg.link(frm, f"records/opportunities/{oid}.md", oid) if oid in opps else oid

    # ── processes.md ──
    f = "processes.md"
    out = [pg.header("Processos", [LEDGER]), ""]
    active = [p for p in pf["processes"] if p["status"] == "ativo"]
    if not active:
        out.append("_Nenhum processo cadastrado — `brain process add` (ou deixe o `/dump` extrair)._")
    for a in pf["areas"]:
        rows = [p for p in active if p["area"] == a["id"]]
        if not rows:
            continue
        total = sum(p["hours_month"] or 0 for p in rows)
        out += [f"## {a['name']} · {len(rows)} processos · {hours(total)}", "",
                "| ID | Processo | Responsável | Recorrência | Horas | Playbook | Lacunas |", "|---|---|---|---|---|---|---|"]
        for p in rows:
            pb = p["playbook"]
            pbtxt = "—" if not pb else (f"lido {util.fmt_date(pb['read'])}" if pb["read"] else "ligado")
            out.append(f"| {plink(f, p['id'])} | {_cell(p['title'])} | {who(f, p['owner'])} | "
                       f"{REC_LABEL.get(p['recurrence'], '—')} | {hours(p['hours_month'])} | {pbtxt} | "
                       f"{', '.join('⚠ ' + g for g in p['gaps']) or '✓'} |")
        out.append("")
    retired = [p for p in pf["processes"] if p["status"] != "ativo"]
    if retired:
        out += ["## Aposentados", ""] + [f"- {plink(f, p['id'])} {p['title']} — {p['retired_reason']}" for p in retired] + [""]
    pg.put(f, "\n".join(out))

    # ── opportunities.md ──
    f = "opportunities.md"
    out = [pg.header("Oportunidades", [LEDGER, PLANNING]), "", "## Funil", ""]
    out.append(" · ".join(f"{s} **{n}**" for s, n in pf["funnel"].items() if n) or "_Nenhuma oportunidade ainda._")
    out += ["", "## Ranking (ICE = impacto × confiança × facilidade)", ""]
    if pf["ranking"]:
        out += ["| # | ID | Oportunidade | Área | ICE | Status | Quadrante | Ganho |", "|---|---|---|---|---|---|---|---|"]
        for i, oid in enumerate(pf["ranking"], 1):
            o = opps[oid]
            out.append(f"| {i} | {olink(f, oid)} | {_cell(o['title'])} | {area(o['area'])} | {ice(o)} | {o['status']} | "
                       f"{o['quadrant']} | {hours(o['hours_saved'])} |")
    else:
        out.append("_Nenhuma oportunidade com ICE._")
    out += ["", "## Matriz impacto × facilidade", "",
            "| | Facilidade alta (≥3) | Facilidade baixa (<3) |", "|---|---|---|"]
    mx = pf["matrix"]

    def cell(q: str) -> str:
        return " ".join(olink(f, i) for i in mx[q]) or "—"
    out += [f"| **Impacto alto (≥3)** | ganho rápido: {cell('ganho rápido')} | aposta: {cell('aposta')} |",
            f"| **Impacto baixo (<3)** | preencher depois: {cell('preencher depois')} | evitar: {cell('evitar')} |"]
    out += ["", "## Por status", ""]
    for s in pf["funnel"]:
        items = [o for o in pf["opportunities"] if o["status"] == s]
        if items:
            out.append(f"- **{s}**: " + "; ".join(
                f"{olink(f, o['id'])} {_clip(o['title'], 40)}" + (f" ({o['project']})" if o["project"] else "")
                for o in items))
    g = pf["gaps"]
    out += ["", "## Lacunas", ""]
    lacunas = []
    if g["areas_without_process"]:
        lacunas.append("áreas sem processo: " + ", ".join(area(a) for a in g["areas_without_process"]))
    for p in g["processes"]:
        lacunas.append(f"{plink(f, p['id'])}: {', '.join(p['gaps'])}")
    if g["no_ice"]:
        lacunas.append("sem ICE: " + " ".join(olink(f, i) for i in g["no_ice"]))
    if g["ice_suggested"]:
        lacunas.append("ICE só sugerido (confirme ou mude): " + " ".join(olink(f, i) for i in g["ice_suggested"]))
    for s in g["stale"]:
        lacunas.append(f"{olink(f, s['id'])} parada há {s['days']} dias")
    out += [f"- {x}" for x in lacunas] or ["_Nenhuma lacuna._"]
    pg.put(f, "\n".join(out))

    # ── fichas ──
    for p in pf["processes"]:
        f = f"records/processes/{p['id']}.md"
        fm = {"id": p["id"], "titulo": p["title"], "area": area(p["area"]), "status": p["status"],
              "responsavel": p["owner_name"], "recorrencia": p["recurrence"] or None,
              "horas_mes": p["hours_month"], "maturidade": p["maturity"], "fonte": p["source"] or None,
              "prov": p["prov"], "tags": ["processo"]}
        body = [f"# {p['id']} · {p['title']}", "",
                f"Área: {area(p['area'])} · responsável: {who(f, p['owner'])} · {hours(p['hours_month'])}"
                + (f" · executores: {', '.join(who(f, x) for x in p['executors'])}" if p["executors"] else ""), ""]
        if p["duration_min"] or p["recurrence"]:
            body.append(f"Recorrência: {REC_LABEL.get(p['recurrence'], '—')}"
                        + (f" ({p['per_month']:g}/mês)" if p["per_month"] else "")
                        + f" · duração por execução: {util.fmt_duration(p['duration_min'])}")
        if p["tools"]:
            body.append("Ferramentas: " + ", ".join(p["tools"]))
        if p["io"]:
            body.append(f"Entradas → saídas: {p['io']}")
        for x in p["pains"]:
            body.append(f"- dor: {x}")
        for n in p["notes"]:
            body.append(f"- nota: {n}")
        if p["gaps"]:
            body += ["", "⚠ " + "; ".join(p["gaps"])]
        body += ["", "## Documentos", ""]
        for d in p["docs"]:
            read = f" · lido em {util.fmt_date(d['read'])}" if d["read"] else ""
            body.append(f"- [{d['kind']}] {d['title'] or d['ref']} — {d['ref']}{read}")
        if not p["docs"]:
            body.append("_nenhum_")
        body += ["", "## Oportunidades ligadas", ""]
        body += [f"- {olink(f, i)} {opps[i]['title']} ({opps[i]['status']})" for i in p["opportunities"]] or ["_nenhuma_"]
        pg.put(f, _frontmatter(fm) + "\n".join(body))

    statuses: dict[str, str] = {}
    for o in pf["opportunities"]:
        f = f"records/opportunities/{o['id']}.md"
        statuses[o["id"]] = o["status"]
        fm = {"id": o["id"], "titulo": o["title"], "status": o["status"], "area": area(o["area"]),
              "tipo": o["kind"], "impacto": o["impact"], "confianca": o["confidence"], "facilidade": o["ease"],
              "score": o["score"], "ice_sugerido": bool(o["ice_suggested"]), "quadrante": o["quadrant"],
              "processo": o["process"], "goal": o["goal"], "projeto": o["project"],
              "fonte": o["source"] or None, "prov": o["prov"], "tags": ["oportunidade"]}
        body = [f"# {o['id']} · {o['title']}", "",
                "> Edite `status:` acima (" + " · ".join(sorted(OPP_STATUS)) + ") — vira declaração sua no próximo render. "
                "`em-andamento` só existe depois de promover (`brain opportunity promote`).", "",
                f"ICE: {ice(o)}" + (f" — {o['ice_reason']}" if o["ice_suggested"] and o["ice_reason"] else ""),
                f"Área: {area(o['area'])} · tipo: {o['kind']}"
                + (f" · processo: {plink(f, o['process'])}" if o["process"] else ""),
                f"Ganho esperado: {o['gain'] or '—'}" + (f" ({hours(o['hours_saved'])})" if o["hours_saved"] else "")]
        if o["project"]:
            pr = o["project_progress"]
            body.append(f"Projeto: {pg.proj(f, o['project'], short=False)} em {o['goal']}"
                        + (f" · {pg.bar(pr['pct'])}" if pr else ""))
        elif o["goal"]:
            body.append(f"Goal: {o['goal']} {o['goal_title'] or ''}")
        if o["people"]:
            body.append("Pessoas: " + ", ".join(who(f, x) for x in o["people"]))
        body += ["", "## Problema", "", o["problem"] or "_não consta_", "", "## Sugestão", "", o["suggestion"] or "_não consta_",
                 "", "## Histórico de status", ""]
        body += [f"- {util.fmt_date(h['date'])} · {h['from']} → {h['to']}" + (f" · {h['reason']}" if h["reason"] else "")
                 for h in o["status_history"]] or [f"_criada em {util.fmt_date(o['added'])} como {o['status']}_"]
        body += ["", f"## Evidências ({o['evidence_count']})", ""]
        body += [f"- `{e}`" for e in o["evidence"]] or ["_nenhuma_"]
        body += ["", "## Documentos", ""]
        for d in o["docs"]:
            body.append(f"- [{d['kind']}] {d['title'] or d['ref']} — {d['ref']}")
        if not o["docs"]:
            body.append("_nenhum_")
        pg.put(f, _frontmatter(fm) + "\n".join(body))
    return statuses
