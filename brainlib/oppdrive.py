"""`brain oppdrive` — porta das pastas de oportunidade no Google Drive.

Quem escreve no Drive é o agente, pelas ferramentas MCP do Drive/Docs; este módulo só contabiliza: diz o que falta
(pasta, one-pager), monta o rascunho inicial a partir do ledger e grava no ledger o que o agente criou ou sugeriu.
Regras da porta (AGENTS.md): só dentro de `[oppdrive].root`; cria pasta e one-pager uma vez; depois disso o conteúdo é
de quem edita no Drive — o agente só deixa SUGESTÕES (Docs `writeMode=SUGGEST`), nunca edita, apaga, renomeia ou move.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import model, share, util, watch
from .cli import _common, _fact_opts, _out
from .core import Brain

SKIP_STATUS = {"descartada"}
TITLE_MAX = 120


def root(b: Brain) -> str:
    cfg = b.inst.cfg.get("oppdrive") or {}
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
                         "in_onepager": any(d.ref in s["what"] for od in onepager for s in od.suggestions)}
                        for d in related],
            "todo": todo}


def status(b: Brain, only: str | None = None) -> list[dict]:
    opps = b.state.opportunities
    if only:
        if only not in opps:
            raise util.BrainError(f"oportunidade {only} não existe", code=3)
        return [entry(opps[only])]
    return [entry(o) for o in opps.values() if o.status not in SKIP_STATUS]


def onepager_md(b: Brain, oid: str) -> str:
    """Rascunho inicial do one-pager (Markdown → Google Doc no create_file). Mesmo conteúdo do `share opportunity`."""
    title, sections, sources = share._sections_opportunity(b, model.build(b), oid)
    o = b.state.opportunities[oid]
    related = [f"[{d.title or d.ref}]({d.ref})" for d in o.docs if d.kind not in ("pasta", "one-pager")]
    sections = list(sections) + [("Arquivos relacionados", related or ["não consta"])]
    stamp = util.now().strftime("%d/%m/%Y %H:%M")
    text = share._md(f"{oid}: {title}", sections, sources, stamp)
    return text.replace("_Gerado em", "_Rascunho inicial gerado em", 1).replace(
        "ponto no tempo (não é atualizado)", "daqui em diante o conteúdo é de quem edita; o cérebro só deixa sugestões", 1)


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
        root(b)
        text = onepager_md(b, args.id)
        if args.out:
            out = Path(args.out)
            out.write_text(text, encoding="utf-8")
            print(f"✓ rascunho em {out} — create_file com contentMimeType text/markdown, parentId = pasta da {args.id}")
        else:
            print(text, end="")
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
    x = s.add_parser("onepager", help="rascunho inicial do one-pager (Markdown) a partir do ledger")
    x.add_argument("id")
    x.add_argument("--out", help="grava o Markdown neste arquivo (senão, stdout)")
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
