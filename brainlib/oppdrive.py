"""`brain oppdrive` — porta das pastas de oportunidade no Google Drive.

Quem escreve no Drive é o agente, pelas ferramentas MCP do Drive/Docs; este módulo só contabiliza: diz o que falta
(pasta, one-pager), monta o rascunho inicial a partir do ledger e grava no ledger o que o agente criou ou sugeriu.
Regras da porta (AGENTS.md): só dentro de `[oppdrive].root`; cria pasta e one-pager uma vez. O one-pager tem duas
metades (`brainlib/onepager.py`): o **Resumo** (tabelas) é do cérebro — o agente reescreve sozinho, só pelos intervalos
nomeados `brain:*`, e divergência com o que alguém escreveu ali vira pergunta; o **Detalhamento** é de quem edita no
Drive — o agente só deixa SUGESTÕES (Docs `writeMode=SUGGEST`). Nunca apaga, renomeia, move ou compartilha.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import ask, onepager, util, watch
from .cli import _common, _fact_opts, _out
from .core import Brain

SKIP_STATUS = {"descartada"}
TITLE_MAX = 120


def root(b: Brain) -> str:
    cfg = b.inst.cfg.get("oppdrive") or {}
    onepager.use_brand(cfg.get("brand"))
    if not cfg.get("enabled"):
        raise util.BrainError("porta oppdrive desligada — [oppdrive].enabled = true no config/brain.toml", code=4)
    rid = watch.drive_doc_id(cfg.get("root", ""))
    if not rid:
        raise util.BrainError("[oppdrive].root vazio ou inválido — id (ou URL) da pasta Oportunidades no Drive", code=4)
    return rid


SOURCE_KEY = "oppdrive"


def ensure_source(b: Brain, rid: str) -> dict | None:
    """Fonte `drive` da raiz no watch.toml: o /update desce nas pastas e acha o que o dono (ou alguém) soltou lá."""
    have = next((s for s in watch.list_sources(b.inst) if s.get("key") == SOURCE_KEY), None)
    if have is not None:
        return None if have.get("folder") == rid else watch.edit(b.inst, SOURCE_KEY, {"folder": rid})
    return watch.add(b.inst, SOURCE_KEY, {"kind": "drive", "folder": rid, "note": "pastas de oportunidade (porta 6)"})


def folder_title(o) -> str:
    return f"{o.id}: {o.title}"[:TITLE_MAX]


def _drive_docs(o, kind: str) -> list:
    return [d for d in o.docs if d.kind == kind and watch.drive_doc_id(d.ref)]


def entry(o) -> dict:
    folder, onepager = _drive_docs(o, "pasta"), _drive_docs(o, "one-pager")
    related = [d for d in o.docs if d.kind not in ("pasta", "one-pager")]
    todo = ([] if folder else ["pasta"]) + ([] if onepager else ["one-pager"])
    return {"id": o.id, "title": o.title, "status": o.status, "folder_title": folder_title(o),
            "folder": folder[0].ref if folder else None, "onepager": onepager[0].ref if onepager else None,
            "related": [{"ref": d.ref, "kind": d.kind, "title": d.title,
                         "in_onepager": any(d.ref in s["what"] for od in onepager for s in od.suggestions)
                         or any(d.ref in od.synced.get("arquivos", "") for od in onepager)}
                        for d in related],
            "template": ("novo" if onepager[0].synced else "antigo") if onepager else None,
            "todo": todo}


def status(b: Brain, only: str | None = None) -> list[dict]:
    opps = b.state.opportunities
    if only:
        if only not in opps:
            raise util.BrainError(f"oportunidade {only} não existe", code=3)
        return [entry(opps[only])]
    return [entry(o) for o in opps.values() if o.status not in SKIP_STATUS]


def _doc(b: Brain, oid: str):
    o = b.state.opportunities.get(oid)
    if o is None:
        raise util.BrainError(f"oportunidade {oid} não existe", code=3)
    d = next((d for d in _drive_docs(o, "one-pager")), None)
    return o, d


def onepager_md(b: Brain, oid: str, detail: str | None = None) -> str:
    """Prévia do one-pager em Markdown (tabelas GFM) — o mesmo conteúdo que o `build` escreve no Docs."""
    if oid not in b.state.opportunities:
        raise util.BrainError(f"oportunidade {oid} não existe", code=3)
    title, f = onepager.fields(b, oid)
    return onepager.markdown(title, oid, f, detail)


def _read(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise util.BrainError(f"{path} não existe", code=3)
    return p.read_text(encoding="utf-8")


def _write_plan(out: str, plan: dict) -> None:
    Path(out).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


def build(b: Brain, oid: str, detail: str, end: int, force: bool = False) -> dict:
    o, d = _doc(b, oid)
    if d is None:
        raise util.BrainError(f"{oid} sem one-pager registrado — crie o Doc vazio na pasta e `oppdrive record --onepager`", code=4)
    if d.synced and not force:
        raise util.BrainError(f"{oid} já está no template novo: o Detalhamento é de quem edita — use `oppdrive sync` "
                              "(Resumo) ou sugestões; reescrever tudo só com --force, por pedido do dono", code=4)
    if not detail.strip():
        raise util.BrainError("Detalhamento vazio — todo one-pager criado pelo agente traz um", code=4)
    title, f = onepager.fields(b, oid)
    return {"id": oid, "documentId": d.ref, "mode": "build", "fields": f,
            "writeControl": {"writeMode": "EDIT"}, "requests": onepager.build_requests(title, oid, f, detail, end)}


def restyle(b: Brain, oid: str, doc_json: str) -> dict:
    o, d = _doc(b, oid)
    if d is None or not d.synced:
        raise util.BrainError(f"{oid} sem one-pager no template novo — `oppdrive build` já sai no padrão", code=4)
    doc = json.loads(doc_json)
    got = doc.get("content", doc).get("documentId")
    if got and got != d.ref:
        raise util.BrainError(f"o JSON é do doc {got}, não do one-pager da {oid} ({d.ref})", code=4)
    try:
        reqs = onepager.restyle_requests(doc)
    except ValueError as e:
        raise util.BrainError(f"{oid}: {e} — nada a aplicar", code=4)
    return {"id": oid, "documentId": d.ref, "mode": "restyle", "fields": d.synced,
            "writeControl": {"writeMode": "EDIT"}, "requests": reqs}


def sync(b: Brain, oid: str, snapshot: str | None, force: bool = False, source: str = "") -> dict:
    o, d = _doc(b, oid)
    if d is None:
        raise util.BrainError(f"{oid} sem one-pager registrado", code=4)
    _, f = onepager.fields(b, oid)
    doc = onepager.parse_markdown(snapshot) if snapshot is not None else None
    cmp = onepager.compare(f, d.synced or None, doc)
    plan = {"id": oid, "documentId": d.ref, "mode": "sync", **cmp, "fields": f, "writeControl": {"writeMode": "EDIT"}}
    if cmp["state"] == "template-antigo":
        plan["requests"] = []
        plan["hint"] = "one-pager no template antigo: `oppdrive build` (confira antes que ninguém escreveu nele)"
        return plan
    if cmp["state"] in ("divergente", "resumo-ausente") and not force:
        if cmp["state"] == "divergente":
            diff = "; ".join(f"{onepager.LABEL[k]}: doc diz {onepager.norm(doc[k])!r}, Brain diz {onepager.norm(f[k])!r}"
                             for k in cmp["divergent"])
            text = f"O Resumo do one-pager da {oid} foi editado e diverge do Brain — {diff}. Qual vale?"
        else:
            text = f"O Resumo (tabelas) sumiu do one-pager da {oid}. Como seguimos?"
        opts = (["o Brain vale: reescrever o Resumo", "o doc vale: corrigir o Brain"] if cmp["state"] == "divergente"
                else ["deixar o doc sem Resumo", "reescrever o doc inteiro a partir do Brain (o Detalhamento atual se perde)"])
        _, qid, _ = ask.add(b, text, opts, [oid, d.ref], "confirmacao", source=source or f"drive:{d.ref}")
        plan.update(requests=[], ask=qid)
        return plan
    keys = onepager.KEYS if force else cmp["changed"]
    plan["requests"] = onepager.sync_requests(f, keys)
    return plan


def cmd(args, b: Brain) -> None:
    c = args.odcmd
    if c == "status":
        rid = root(b)
        rows = status(b, args.id)
        if args.pending:
            rows = [r for r in rows if r["todo"] or any(not x["in_onepager"] for x in r["related"])]
        if args.json:
            print(json.dumps({"root": rid, "opportunities": rows}, ensure_ascii=False, indent=2))
            return
        print(f"raiz: {rid}")
        for r in rows:
            todo = ("falta " + " + ".join(r["todo"])) if r["todo"] else "pasta e one-pager ok"
            loose = sum(1 for x in r["related"] if not x["in_onepager"])
            print(f"{r['id']} · {todo}" + (f" · {loose} arquivo(s) a sugerir no one-pager" if loose else "")
                  + f" · {r['folder_title']}")
        if not rows:
            print("nada pendente")
    elif c == "onepager":
        text = onepager_md(b, args.id, _read(args.detail))
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"✓ prévia em {args.out}")
        else:
            print(text, end="")
    elif c == "build":
        root(b)
        plan = build(b, args.id, _read(args.detail) or "", args.end, args.force)
        _write_plan(args.out, plan)
        print(f"✓ {args.id} · {len(plan['requests'])} pedidos em {args.out} — update_doc(documentId={plan['documentId']}, "
              "requests, writeControl EDIT); depois `oppdrive synced --plan`")
    elif c == "restyle":
        root(b)
        plan = restyle(b, args.id, _read(args.doc_json) or "{}")
        _write_plan(args.out, plan)
        print(f"✓ {args.id} · {len(plan['requests'])} pedidos de estilo em {args.out} — update_doc (EDIT); depois `oppdrive synced --plan`")
    elif c == "sync":
        root(b)
        plan = sync(b, args.id, _read(args.snapshot), args.force, args.source or "")
        _write_plan(args.out, plan) if args.out else None
        if args.json:
            print(json.dumps({k: v for k, v in plan.items() if k != "requests"} | {"n_requests": len(plan["requests"])},
                             ensure_ascii=False, indent=2))
            return
        msg = {"ok": "Resumo em dia — nada a escrever",
               "desatualizado": (f"{len(plan['requests'])} pedido(s) em {args.out}: " if args.out else
                                 "rode de novo com --out para gerar os pedidos: ") + ", ".join(plan["changed"]),
               "template-antigo": plan.get("hint", ""),
               "divergente": f"diverge em {', '.join(plan['divergent'])} — nada escrito; pergunta {plan.get('ask')}",
               "resumo-ausente": f"Resumo não encontrado no doc — nada escrito; pergunta {plan.get('ask')}"}[plan["state"]]
        if args.force and plan["requests"]:
            msg = f"--force: {len(plan['requests'])} pedido(s) em {args.out}"
        print(f"{args.id} · {plan['state']} · {msg}")
    elif c == "synced":
        root(b)
        plan = json.loads(_read(args.plan) or "{}")
        o, d = _doc(b, args.id)
        if d is None or plan.get("id") != args.id or plan.get("documentId") != d.ref or not plan.get("requests"):
            raise util.BrainError(f"plano não é do one-pager da {args.id} (ou não tinha pedidos) — nada gravado", code=4)
        args.source = args.source or f"drive:{d.ref}"
        ev = b.record_one(_common({"type": "doc.synced", "data": {"target": args.id, "ref": d.ref, "fields": plan["fields"],
                                                                  "mode": plan["mode"]}}, args))
        _out(args, ev, f"✓ {args.id} · Resumo registrado ({plan['mode']}) no one-pager {d.ref}")
    elif c == "record":
        rid = root(b)
        o = b.state.opportunities.get(args.id)
        if o is None:
            raise util.BrainError(f"oportunidade {args.id} não existe", code=3)
        if args.folder:
            if watch.drive_doc_id(args.parent or "") != rid:
                raise util.BrainError(f"a pasta precisa estar direto na raiz [oppdrive].root ({rid}); --parent "
                                      f"{args.parent!r} — nada gravado", code=4)
            ref, kind, title = watch.drive_doc_id(args.folder), "pasta", folder_title(o)
        else:
            e = entry(o)
            if not e["folder"] or watch.drive_doc_id(args.parent or "") != e["folder"]:
                raise util.BrainError(f"o one-pager precisa estar na pasta da {args.id} ({e['folder'] or 'sem pasta'}); "
                                      f"--parent {args.parent!r} — nada gravado", code=4)
            if e["onepager"]:
                raise util.BrainError(f"{args.id} já tem one-pager ({e['onepager']}): a porta cria uma vez só; "
                                      "mudanças viram sugestão (`oppdrive suggested`)", code=4)
            ref, kind, title = watch.drive_doc_id(args.onepager), "one-pager", f"One-pager {o.id}"
        if not ref:
            raise util.BrainError("id/URL do Drive inválido", code=4)
        data = {"target": o.id, "kind": kind, "ref": ref, "title": title, "watch": True if kind == "one-pager" else None}
        args.source = args.source or f"drive:{ref}"
        ev = b.record_one(_common({"type": "doc.linked", "data": data}, args))
        extra = ""
        if kind == "pasta" and ensure_source(b, rid):
            extra = f"\n  ↳ fonte {SOURCE_KEY} no watch.toml: o /update desce nas pastas de oportunidade"
        if kind == "one-pager":
            src = watch.link_playbook(b, o.id, ref, "one-pager")
            extra = f"\n  ↳ fonte {src['key']} no watch.toml: o /update relê quando o doc mudar"
        _out(args, ev, f"✓ {o.id} · {kind} {ref}{extra}")
    elif c == "suggested":
        root(b)
        e = entry(b.state.opportunities[args.id]) if args.id in b.state.opportunities else None
        if e is None:
            raise util.BrainError(f"oportunidade {args.id} não existe", code=3)
        ref = watch.drive_doc_id(args.doc)
        if not ref or ref != e["onepager"]:
            raise util.BrainError(f"sugestão só no one-pager da {args.id} ({e['onepager'] or 'sem one-pager'})", code=4)
        args.source = args.source or f"drive:{ref}"
        ev = b.record_one(_common({"type": "doc.suggested", "data": {"target": args.id, "ref": ref, "what": args.what}}, args))
        _out(args, ev, f"✓ {args.id} · sugestão registrada no one-pager: {args.what}")


def add_parsers(sub) -> None:
    p = sub.add_parser("oppdrive", help="porta das pastas de oportunidade no Drive (pasta + one-pager + sugestões)")
    s = p.add_subparsers(dest="odcmd", required=True)
    x = s.add_parser("status", help="o que falta por OPP (pasta, one-pager, arquivos a sugerir)")
    x.add_argument("id", nargs="?")
    x.add_argument("--pending", action="store_true", help="só as que têm algo a fazer")
    x.add_argument("--json", action="store_true")
    x = s.add_parser("onepager", help="prévia do one-pager (Markdown: Resumo em tabelas + Detalhamento)")
    x.add_argument("id")
    x.add_argument("--detail", help="arquivo Markdown com o Detalhamento que o agente escreveu")
    x.add_argument("--out", help="grava o Markdown neste arquivo (senão, stdout)")
    x = s.add_parser("build", help="pedidos batchUpdate que escrevem o one-pager inteiro (criação ou troca do template antigo)")
    x.add_argument("id")
    x.add_argument("--detail", required=True, help="arquivo Markdown com o Detalhamento")
    x.add_argument("--end", type=int, required=True, help="endIndex do último elemento do corpo (read_doc); 2 = doc vazio")
    x.add_argument("--out", required=True, help="arquivo JSON do plano (documentId, requests, fields)")
    x.add_argument("--force", action="store_true", help="reescrever doc já no template novo (só por pedido do dono)")
    x = s.add_parser("restyle", help="padrão visual de tabela ([oppdrive.brand]) nas tabelas do Resumo de um doc já escrito")
    x.add_argument("id")
    x.add_argument("--doc-json", required=True, help="o JSON do read_doc desse one-pager (arquivo)")
    x.add_argument("--out", required=True, help="arquivo JSON do plano")
    x = s.add_parser("sync", help="compara o Resumo do doc com o Brain: pedidos de atualização ou pergunta ao dono")
    x.add_argument("id")
    x.add_argument("--snapshot", help="export Markdown do doc (o snapshot do /update) para checar edições no Resumo")
    x.add_argument("--out", help="arquivo JSON do plano")
    x.add_argument("--force", action="store_true", help="reescreve todos os campos (resposta 'o Brain vale' a uma pergunta)")
    x.add_argument("--source", help="caminho do snapshot (vai na pergunta, se houver)")
    x.add_argument("--json", action="store_true")
    x = s.add_parser("synced", help="registra o Resumo que o agente escreveu (depois do update_doc)")
    x.add_argument("id")
    x.add_argument("--plan", required=True, help="o JSON do build/sync aplicado")
    _fact_opts(x)
    x.set_defaults(prov="observado")
    x = s.add_parser("record", help="registra pasta/one-pager que o agente criou no Drive")
    x.add_argument("id")
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--folder", help="id/URL da pasta criada")
    g.add_argument("--onepager", help="id/URL do Google Doc criado")
    x.add_argument("--parent", required=True, help="parentId devolvido pelo Drive (confere a raiz / a pasta da OPP)")
    _fact_opts(x)
    x.set_defaults(prov="observado")
    x = s.add_parser("suggested", help="registra uma sugestão deixada no one-pager (writeMode=SUGGEST)")
    x.add_argument("id")
    x.add_argument("--doc", required=True, help="id/URL do one-pager")
    x.add_argument("--what", required=True, help="o que foi sugerido (curto; inclua a URL ao sugerir um arquivo)")
    _fact_opts(x)
    x.set_defaults(prov="observado")
    p.set_defaults(fn=cmd)
