"""`brain feedback` — sugestões e bugs do próprio cérebro (`FB-####`): registra e vira issue no GitHub.

Porta estreita (AGENTS.md, porta 7): cada sugestão/bug registrado cria uma issue no repo público do
framework listado em `[feedback].repo` (padrão: o upstream). `add` grava o item e empurra a issue na
sequência — sem token, de noite ou com texto carregando dado do dono, o item fica `pendente` e o `push`
resolve depois. Título `[sugestão]`/`[bug]` + label do tipo; `feedback.pushed` guarda número e URL,
`feedback.failed` a última tentativa que não subiu. O texto do issue é público: a porta recusa
título/corpo com dado pessoal (as mesmas regras da varredura do `upstream`), sem override.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from . import config, ids, schema, util
from .cli import _fact_opts, _out
from .core import Brain

KINDS = ("sugestao", "bug")
KIND_LABEL = {"sugestao": "sugestão", "bug": "bug"}          # label do issue no GitHub
KIND_TAG = {"sugestao": "[sugestão]", "bug": "[bug]"}        # tag do título (GiftHub: [request: …]/[bug])
API = "https://api.github.com"
TIMEOUT_S = 20


# ── o issue que a porta publica ──────────────────────────────────────────────

def issue_title(f) -> str:
    return f"{KIND_TAG[f.kind]} {f.title}"


def issue_body(f) -> str:
    lines = [f"**Tipo:** {'💡 sugestão' if f.kind == 'sugestao' else '🐞 bug'}", "",
             "## Descrição", f.body or f.title, ""]
    if f.context:
        lines += ["## Contexto", *[f"- {c}" for c in f.context], ""]
    lines += ["---", f"`{f.id}` · registrado pelo Segundo Cérebro (`brain feedback`)"]
    return "\n".join(lines)


def leak_guard(inst: config.Instance, *texts: str) -> None:
    """O issue é público: título e corpo passam pelas mesmas regras da varredura do upstream. Sem override."""
    from . import upstream
    term_res = [(kind, re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])", re.I))
                for t, kind in upstream._leak_terms(inst)]
    home = str(Path.home())
    hits: list[tuple[str, str]] = []
    for text in texts:
        for line in (text or "").splitlines() or [""]:
            hits += upstream._scan_line(line, term_res, home)
    if hits:
        what = ", ".join(sorted({h[0] for h in hits}))
        raise util.BrainError(f"o issue é público e o texto carrega dado que não sai da máquina ({what}) — "
                              "descreva sem nomes, e-mails, caminhos ou segredos", code=4)


# ── GitHub (stdlib, token em config/.env — o valor nunca aparece em chat/log) ─

def create_issue(inst: config.Instance, repo: str, title: str, body: str, labels: list[str]) -> dict:
    """POST /repos/<repo>/issues → {number, url}. Falha é dura: quem chama decide o que registrar."""
    token = config.load_env(inst).get("GITHUB_TOKEN")
    if not token:
        raise util.BrainError("GITHUB_TOKEN ausente no config/.env — grave um token com permissão de criar "
                              "issues no repo de [feedback] (o valor nunca aparece no chat)", code=4)
    req = urllib.request.Request(
        f"{API}/repos/{repo}/issues", method="POST",
        data=json.dumps({"title": title, "body": body, "labels": labels}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
                 "User-Agent": "second-brain-feedback"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("message", "")
        except Exception:
            pass
        raise util.BrainError(f"GitHub recusou o issue ({e.code}{f' {detail}' if detail else ''}) — repo {repo}",
                              code=4) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise util.BrainError(f"sem contato com {API} ({e})", code=4) from e
    return {"number": data["number"], "url": data["html_url"]}


# ── fluxo da entidade ────────────────────────────────────────────────────────

def add(brain: Brain, kind: str, title: str, body: str = "", context: list[str] | None = None,
        by: str = "owner", prov: str = "declarado", source: str = "chat", date: str | None = None,
        force: bool = False) -> dict:
    """Grava `feedback.added` (FB-#### pendente). Título igual ao de um FB existente exige --force."""
    context = [ids.normalize(c) for c in (context or [])]
    key = (kind, " ".join(util.fold(title).split()))
    dup = next((f.id for f in brain.state.feedbacks.values()
                if (f.kind, " ".join(util.fold(f.title).split())) == key), None)
    if dup is not None and not force:
        raise util.BrainError(f"já existe {dup} com o mesmo título e tipo — acrescente detalhe ao existente "
                              f"(`brain feedback show {dup}`) ou use --force", code=4)
    return brain.record_one({"type": "feedback.added", "by": by, "prov": prov, "source": source or "chat",
                             "date": date, "data": {"kind": kind, "title": title, "body": body,
                                                    "context": context}})


def push(brain: Brain, fid: str) -> dict:
    """Cria a issue no GitHub e grava `feedback.pushed` (número + URL). Erros de API gravam `feedback.failed`.

    Pré-cheques (token, noturno, texto) falham ANTES de qualquer chamada na rede: nada é registrado como
    falha porque nada foi tentado — o item segue pendente."""
    f = brain.state.feedbacks.get(fid)
    if f is None:
        raise util.BrainError(f"{fid} não existe", code=3)
    if f.status == "criado":
        raise util.BrainError(f"{fid}: issue já criada — {f.url}", code=4)
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError(f"{fid}: publicar issue é do dia — no noturno a porta não abre "
                              "(registrar ficou; `brain feedback push {fid}` amanhã)", code=4)
    repo = brain.inst.cfg["feedback"]["repo"]
    title, body = issue_title(f), issue_body(f)
    leak_guard(brain.inst, title, body)          # público: regra dura, sem override
    if not config.load_env(brain.inst).get("GITHUB_TOKEN"):
        raise util.BrainError("GITHUB_TOKEN ausente no config/.env — grave um token com permissão de criar "
                              "issues no repo de [feedback] e tente de novo (o valor nunca aparece no chat)", code=4)
    try:
        res = create_issue(brain.inst, repo, title, body, [KIND_LABEL[f.kind]])
    except util.BrainError as e:
        try:
            brain.record_one({"type": "feedback.failed", "id": fid, "by": "system", "data": {"error": str(e)}})
        except util.BrainError:
            pass                                  # a falha original é a que importa
        raise util.BrainError(f"{fid}: {e} — ficou '{brain.state.feedbacks[fid].status}'; "
                              f"`brain feedback push {fid}` de novo", code=4) from e
    try:
        return brain.record_one({"type": "feedback.pushed", "id": fid, "by": "system",
                                 "data": {"number": res["number"], "url": res["url"]}})
    except util.BrainError:
        raise util.BrainError(f"{fid}: a issue {res['url']} foi criada mas o registro falhou — "
                              f"`brain feedback pushed {fid} --number {res['number']} --url {res['url']}`",
                              code=5)


def line(f) -> str:
    bits = [f.id, f.status, KIND_TAG[f.kind] + " " + f.title]
    if f.status == "criado":
        bits.append(f"#{f.number} {f.url}")
    elif f.status == "falhou":
        bits.append(f"última tentativa falhou: {f.error[:80]}")
    return " · ".join(bits)


def _need(brain: Brain, fid: str):
    f = brain.state.feedbacks.get(fid)
    if f is None:
        raise util.BrainError(f"{fid} não existe", code=3)
    return f


def cli(args, brain: Brain) -> None:
    c = args.fbcmd
    if c == "add":
        ctx = [x for part in (args.context or []) for x in util.split_csv(part)]
        ev = add(brain, args.kind, args.title, args.body or "", ctx, args.by,
                 args.prov or ("declarado" if args.by == "owner" else "observado"),
                 args.source or "", args.date, args.force)
        f = brain.state.feedbacks[ev["id"]]
        print(f"✓ {line(f)}")
        if args.no_push:
            return
        try:                                       # add empurra a issue na sequência (porta 7)
            ev = push(brain, f.id)
            print(f"✓ issue criada: {ev['data']['url']}")
        except util.BrainError as e:
            print(f"⚠ {e}")
    elif c == "push":
        ev = push(brain, args.id)
        print(f"✓ issue criada: {ev['data']['url']}")
    elif c == "pushed":
        _need(brain, args.id)
        brain.record_one({"type": "feedback.pushed", "id": args.id, "by": "system",
                          "data": {"number": args.number, "url": args.url}})
        print(f"✓ {line(brain.state.feedbacks[args.id])}")
    elif c == "failed":
        _need(brain, args.id)
        brain.record_one({"type": "feedback.failed", "id": args.id, "by": "system",
                          "data": {"error": args.error}})
        print(f"✓ falha registrada em {args.id}")
    elif c == "show":
        f = _need(brain, args.id)
        _out(args, {"id": f.id, "kind": f.kind, "title": f.title, "body": f.body, "context": f.context,
                    "status": f.status, "number": f.number, "url": f.url, "added": f.added,
                    "issue_title": issue_title(f), "issue_body": issue_body(f)},
             f"{f.id} · {f.status}" + (f" · {f.url}" if f.url else "") + "\n\n"
             f"issue → {issue_title(f)}\n\n{issue_body(f)}")
    else:                                          # list
        rows = [f for f in brain.state.feedbacks.values()
                if args.all or f.status in ("pendente", "falhou")]
        rows.sort(key=lambda f: f.id)
        _out(args, [dict(f.__dict__) for f in rows], "\n".join(line(f) for f in rows) or "(nada pendente)")


def add_parsers(sub) -> None:
    p = sub.add_parser("feedback", help="sugestões e bugs do cérebro FB-#### — viram issues no repo público do framework")
    s = p.add_subparsers(dest="fbcmd", required=True)
    x = s.add_parser("add", help="registra sugestão/bug e cria a issue no GitHub (a menos que --no-push)")
    x.add_argument("title")
    x.add_argument("--kind", choices=list(KINDS), required=True, help="sugestao | bug")
    x.add_argument("--body", help="descrição completa: o que, onde, como reproduzir")
    x.add_argument("--context", action="append", help="refs: TASK-…, PROC-…, OPP-… (vírgula ou repetido)")
    x.add_argument("--no-push", action="store_true", help="só registra (FB-#### pendente); `brain feedback push` depois")
    x.add_argument("--force", action="store_true", help="registra mesmo com título igual ao de um FB existente")
    _fact_opts(x)
    x = s.add_parser("push", help="cria a issue de um FB pendente/falhou no GitHub e registra número+URL")
    x.add_argument("id")
    x = s.add_parser("pushed", help="registra issue criada por fora (--number/--url) — se o push morreu depois de criar")
    x.add_argument("id")
    x.add_argument("--number", type=int, required=True)
    x.add_argument("--url", required=True)
    x.set_defaults(by="system")
    x = s.add_parser("failed", help="registra falha de tentativa (uso manual)")
    x.add_argument("id")
    x.add_argument("--error", required=True)
    x.set_defaults(by="system")
    x = s.add_parser("show", help="o item e o issue exato que a porta publica")
    x.add_argument("id")
    x.add_argument("--json", action="store_true")
    x = s.add_parser("list", help="pendentes e falhas (a fila); --all traz tudo")
    x.add_argument("--all", action="store_true")
    x.add_argument("--json", action="store_true")
    p.set_defaults(fn=cli)
