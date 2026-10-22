"""Servidor MCP somente-leitura (stdio) — outras IAs consultam o mesmo cérebro.

Nenhuma ferramenta aqui escreve. Cada chamada relê o ledger (dado sempre fresco).
Configuração no cliente MCP: {"command": "<instância>/brain", "args": ["mcp"]}.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import __version__, ids, model, people, rawsort, search, util
from .core import Brain

PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
INSTRUCTIONS = ("Segundo Cérebro (somente leitura). Cite sempre a fonte (source_label/caminho) e a proveniência "
                "([doc], [observado], [declarado], [sem-fonte]). 'Não consta' é resposta válida — nunca invente. "
                "Para escrever (ações, decisões, mensagens) use o agente da instância com ./brain, não este servidor.")


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


S = {"type": "string"}
I = {"type": "integer"}
TOOLS = [
    ("brain_overview", "Panorama: goals com progresso e saúde, contagens, agenda de 7 dias, o que aguarda o dono.",
     _schema({})),
    ("brain_search", "Busca sem LLM em ações, decisões, pessoas, projetos, entregas e artefatos.",
     _schema({"query": S, "limit": I}, ["query"])),
    ("brain_project", "Página de um projeto (PROJ-#): entregáveis, decisões (quem/quando/fonte), ações, linha do tempo, pessoas.",
     _schema({"id": S}, ["id"])),
    ("brain_person", "Pessoa por nome/alias/e-mail: papel, última interação, o que deve/devem, decisões que tomou.",
     _schema({"name": S}, ["name"])),
    ("brain_decisions", "Decisões, filtráveis por projeto, pessoa e data mínima (AAAA-MM-DD).",
     _schema({"project": S, "person": S, "since": S})),
    ("brain_actions", "Ações (ACT-####). list: mine|waiting|watching. Por padrão só abertas.",
     _schema({"list": S, "project": S, "owner": S, "include_closed": {"type": "boolean"}})),
    ("brain_timeline", "Linha do tempo: o que aconteceu (dias para trás) e prazos (dias à frente).",
     _schema({"days_back": I, "days_ahead": I})),
    ("brain_wins", "Conquistas por semana: entregas, entregáveis concluídos, ações fechadas.", _schema({"weeks": I})),
    ("portfolio_overview", "Portfólio de processos e oportunidades: áreas, funil por status, matriz impacto × facilidade, "
     "ranking por ICE (top 10) e lacunas. Números calculados pelo CLI.", _schema({})),
    ("process", "Ficha de um processo (PROC-####): responsável, executores, recorrência, horas/mês, playbook, dores, lacunas, oportunidades ligadas.",
     _schema({"id": S}, ["id"])),
    ("opportunity", "Ficha de uma oportunidade (OPP-####): problema, sugestão, ICE (e se é só sugerido), status e histórico, evidências, projeto/goal.",
     _schema({"id": S}, ["id"])),
    ("opportunities", "Oportunidades, filtráveis por status e área (id, nome ou alias), da maior para a menor pontuação.",
     _schema({"status": S, "area": S})),
    ("brain_read", "Lê um arquivo de texto do vault (caminho relativo ao vault: PROCESSED/…, PLANNING/…, RAW/…).",
     _schema({"path": S}, ["path"])),
]


def _overview(m: dict, _args) -> dict:
    return {"today": m["today"], "counts": m["counts"],
            "goals": [{k: g[k] for k in ("id", "title", "status", "progress", "health_label", "declared")} |
                      {"projects": [{"id": p["id"], "title": p["title"], "progress": p["progress"],
                                     "health": p["health"], "next_due": p["next_due"]}
                                    for p in m["projects"] if p["goal"] == g["id"]]} for g in m["goals"]],
            "agenda_7d": m["agenda"], "proposals": m["proposals"],
            "focus": {k: m["focus"][k] for k in ("id", "status", "blocks")} if m["focus"] else None}


def _project(m: dict, args) -> dict:
    p = next((x for x in m["projects"] if x["id"] == args.get("id")), None)
    if p is None:
        return {"erro": f"projeto {args.get('id')} não consta", "projetos": [x["id"] for x in m["projects"]]}
    decs = {d["id"]: d for d in m["decisions"]}
    acts = {a["id"]: a for a in m["actions"]}
    return {**{k: p[k] for k in ("id", "title", "goal", "goal_title", "status", "progress", "health",
                                 "deliverables", "people", "timeline", "next_due")},
            "decisions": [decs[d] for d in p["decisions"]],
            "actions": {k: [acts[a] for a in v] for k, v in p["actions"].items()}}


def _person(brain, m: dict, args) -> dict:
    cands = people.resolve(brain.state, args.get("name", ""))
    if not cands:
        return {"erro": "não consta"}
    if len(cands) > 1:
        return {"ambiguo": [{"id": c, "name": brain.state.people[c].name} for c in cands]}
    return next(p for p in m["people"] if p["id"] == cands[0])


def _decisions(m: dict, args) -> list:
    out = m["decisions"]
    if args.get("project"):
        out = [d for d in out if d["project"] == args["project"]]
    if args.get("person"):
        out = [d for d in out if args["person"] in d["decided_by"]]
    if args.get("since"):
        out = [d for d in out if (d["date"] or "") >= args["since"]]
    return out


def _actions(m: dict, args) -> list:
    out = m["actions"] if args.get("include_closed") else [a for a in m["actions"] if a["open"]]
    for k in ("list", "project", "owner"):
        if args.get(k):
            out = [a for a in out if a[k] == args[k]]
    return [{k: v for k, v in a.items() if k != "history"} for a in out]


def _timeline(m: dict, args) -> dict:
    today = date.fromisoformat(m["today"])
    back = (today - timedelta(days=int(args.get("days_back") or 30))).isoformat()
    ahead = (today + timedelta(days=int(args.get("days_ahead") or 30))).isoformat()
    return {"past": [x for x in m["timeline"]["past"] if x["date"] >= back],
            "future": [x for x in m["timeline"]["future"] if x["date"] <= ahead]}


def _portfolio_overview(m: dict, _args) -> dict:
    pf = m["portfolio"]
    by_id = {o["id"]: o for o in pf["opportunities"]}
    return {"counts": pf["counts"], "areas": pf["areas"], "funnel": pf["funnel"], "matrix": pf["matrix"],
            "ranking": [{k: by_id[i][k] for k in ("id", "title", "area", "status", "score", "ice_suggested", "quadrant")}
                        for i in pf["ranking"][:10]],
            "gaps": pf["gaps"]}


def _process(m: dict, args) -> dict:
    p = next((x for x in m["portfolio"]["processes"] if x["id"] == str(args.get("id", "")).upper()), None)
    return p or {"erro": f"processo {args.get('id')} não consta",
                 "processos": [x["id"] for x in m["portfolio"]["processes"]]}


def _opportunity(m: dict, args) -> dict:
    o = next((x for x in m["portfolio"]["opportunities"] if x["id"] == str(args.get("id", "")).upper()), None)
    return o or {"erro": f"oportunidade {args.get('id')} não consta",
                 "oportunidades": [x["id"] for x in m["portfolio"]["opportunities"]]}


def _opportunities(m: dict, args) -> list:
    out = m["portfolio"]["opportunities"]
    if args.get("status"):
        out = [o for o in out if o["status"] == args["status"]]
    if args.get("area"):
        key = util.fold(args["area"])
        ids = {a["id"] for a in m["portfolio"]["areas"]
               if key in {util.fold(a["id"]), util.fold(a["name"]), *(util.fold(x) for x in a["aliases"])}}
        out = [o for o in out if o["area"] in ids]
    out = sorted(out, key=lambda o: (-(o["score"] or 0), o["id"]))
    return [{k: v for k, v in o.items() if k not in ("status_history", "docs", "notes")} for o in out]


def _read(brain, args) -> dict:
    rel = str(args.get("path", "")).lstrip("/")
    rel = rel[len("vault/"):] if rel.startswith("vault/") else rel
    vault = brain.inst.vault.resolve()
    path = (vault / rel).resolve()
    if rel.startswith("RAW/") and not path.is_file():
        found = rawsort.resolve(brain.inst, rel)          # caminho antigo do ledger → pasta do tipo
        path = found.resolve() if found else path
    if vault not in path.parents or not path.is_file():
        return {"erro": "caminho fora do vault ou inexistente"}
    if path.suffix.lower() not in {".md", ".txt", ".csv", ".json", ".jsonl", ".html", ".vtt", ".srt"}:
        return {"erro": "só arquivos de texto (PDF/planilha: leia o artefato do PROCESSED)"}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"path": rel, "truncated": len(text) > 60000, "text": text[:60000]}


def call_tool(name: str, args: dict) -> object:
    args = {k: (ids.normalize(v) if k in ("id", "project") else v) for k, v in args.items()}   # nomes antigos valem
    brain = Brain()
    if name == "brain_read":
        return _read(brain, args)
    if name == "brain_search":
        return search.search(brain, args.get("query", ""), int(args.get("limit") or 20)) or {"resultado": "não consta"}
    m = model.build(brain)
    if name == "brain_overview":
        return _overview(m, args)
    if name == "portfolio_overview":
        return _portfolio_overview(m, args)
    if name == "process":
        return _process(m, args)
    if name == "opportunity":
        return _opportunity(m, args)
    if name == "opportunities":
        return _opportunities(m, args)
    if name == "brain_project":
        return _project(m, args)
    if name == "brain_person":
        return _person(brain, m, args)
    if name == "brain_decisions":
        return _decisions(m, args)
    if name == "brain_actions":
        return _actions(m, args)
    if name == "brain_timeline":
        return _timeline(m, args)
    if name == "brain_wins":
        weeks = int(args.get("weeks") or 4)
        return {"weeks": m["wins"]["weeks"][:weeks], "last_30d": m["wins"]["last_30d"],
                "deliveries": [e for e in m["deliveries"][:20]]}
    raise KeyError(name)


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        return None
    try:
        if method == "initialize":
            asked = (msg.get("params") or {}).get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "segundo-cerebro", "version": __version__},
                      "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": d, "inputSchema": s,
                                 "annotations": {"readOnlyHint": True, "openWorldHint": False}} for n, d, s in TOOLS]}
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name not in {t[0] for t in TOOLS}:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"ferramenta desconhecida: {name}"}}
            try:
                data = call_tool(name, params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}],
                          "isError": False}
            except util.BrainError as e:
                result = {"content": [{"type": "text", "text": f"erro: {e}"}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"método não suportado: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except Exception as e:  # noqa: BLE001 — servidor não pode cair por um pedido ruim
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)[:500]}}


def serve(_brain=None) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": "JSON inválido"}}) + "\n")
            sys.stdout.flush()
            continue
        batch = msg if isinstance(msg, list) else [msg]
        for item in batch:
            resp = handle(item)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
