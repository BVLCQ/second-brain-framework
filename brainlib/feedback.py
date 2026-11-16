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

from . import config, issues, publicguard, schema, util
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
    """O issue é público: tipo, o corpo no molde (`issues.py`) e o id do FB — nada do vault sai (nem refs a
    TASK/PROC/OPP/PROP, que o leitor público não resolve e são dado do dono)."""
    kind = issues.resolve_kind(f.kind, bool(f.proposal))
    tipo = "🧩 proposta de código do cérebro" if kind == "framework" else \
        ("💡 sugestão" if f.kind == "sugestao" else "🐞 bug")
    lines = [f"**Tipo:** {tipo}", "", issues.render_body(kind, f.body, f.title), "", "---",
             f"`{f.id}` · registrado pelo Segundo Cérebro (`brain feedback`)"]
    return "\n".join(lines)


VAULT_REF_RE = re.compile(r"\b(?:TASK|DEC|WIN|PROP|MSG|PUB|FOCUS|PROC|OPP|ASK|FB)-\d{3,}\b|\b(?:GOAL|PROJ)-\d+(?:\.\d+)?\b")


def refs_guard(*texts: str) -> None:
    """Texto que vira issue pública não cita ID do vault (TASK-####, OPP-####…): o leitor não os resolve e
    dizem do dono. Vale para o que o AGENTE escreve para a issue; o rodapé `FB-####` que a própria porta
    acrescenta não passa por aqui (por isso se varre o título e o corpo CRUS, não o corpo renderizado)."""
    hits = sorted({m.group(0) for t in texts for m in VAULT_REF_RE.finditer(t or "")})
    if hits:
        raise util.BrainError("o texto vira issue pública e cita IDs do vault (" + ", ".join(hits[:4]) +
                              ") — descreva o problema sem referências internas", code=4)


def public_text_guard(inst: config.Instance, title: str, body: str) -> None:
    """A trava única do texto público: IDs do vault + os validadores de `publicguard` (pessoas, prints, links
    internos, e-mails, @menções, telefones, ids opacos, segredos, caminhos). Sem override."""
    refs_guard(title, body)
    publicguard.guard(inst, title, body)


def leak_guard(inst: config.Instance, *texts: str) -> None:
    """Compat: varre os textos como corpo (as regras de dado do dono continuam as do `upstream`)."""
    publicguard.guard(inst, "", "\n".join(texts))


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
    return {"number": data["number"], "url": data["html_url"],
            "labels": [x.get("name", "") for x in data.get("labels", []) if isinstance(x, dict)]}


def issue_state(inst: config.Instance, repo: str, number: int) -> dict:
    """GET /repos/<repo>/issues/<n> → {state, reason}. state: 'open'|'closed'; reason: completed|not_planned|''."""
    token = config.load_env(inst).get("GITHUB_TOKEN")
    if not token:
        raise util.BrainError("GITHUB_TOKEN ausente no config/.env", code=4)
    req = urllib.request.Request(f"{API}/repos/{repo}/issues/{number}", method="GET",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28",
                                          "User-Agent": "second-brain-feedback"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):                    # issue apagada do repo (o dono pode apagar): estado, não erro
            return {"state": "gone", "reason": ""}
        raise util.BrainError(f"GitHub respondeu {e.code} ao issue #{number}", code=4) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise util.BrainError(f"sem contato com {API} ({e})", code=4) from e
    return {"state": data.get("state", ""), "reason": data.get("state_reason") or ""}


# ── fluxo da entidade ────────────────────────────────────────────────────────

def _dup(brain: Brain, kind: str, title: str, skip: str = "") -> str | None:
    key = (kind, " ".join(util.fold(title).split()))
    return next((f.id for f in brain.state.feedbacks.values()
                 if f.id != skip and (f.kind, " ".join(util.fold(f.title).split())) == key), None)


def revise(brain: Brain, fid: str, title: str | None = None, body: str | None = None, proposal: str = "",
           by: str = "owner", prov: str = "declarado", source: str = "chat") -> dict:
    """Corrige título/corpo (e a origem, se veio de uma proposta) de um FB que ainda não virou issue.

    O ledger é append-only: grava `feedback.revised` e o estado passa a valer o texto novo. Só enquanto o FB
    está `pendente`/`falhou` — issue já criada não se edita por aqui. Título repetido segue recusado."""
    f = _need(brain, fid)
    data: dict = {}
    if title is not None and title.strip() != f.title:
        data["title"] = title.strip()
    if body is not None and body.strip() != f.body:
        data["body"] = body.strip()
    if proposal:
        data["proposal"] = proposal
    if not data:
        raise util.BrainError(f"{fid}: nada a revisar (texto igual ao atual)", code=2)
    if "title" in data and (dup := _dup(brain, f.kind, data["title"], skip=fid)):
        raise util.BrainError(f"já existe {dup} com o mesmo título e tipo", code=4)
    return brain.record_one({"type": "feedback.revised", "id": fid, "by": by, "prov": prov, "source": source or "chat",
                             "data": data})


def add(brain: Brain, kind: str, title: str, body: str = "",
        by: str = "owner", prov: str = "declarado", source: str = "chat", date: str | None = None,
        force: bool = False, proposal: str = "") -> dict:
    """Grava `feedback.added` (FB-#### pendente). Título igual ao de um FB existente exige --force.

    Sem campo de contexto de propósito: o issue é público e refs do vault (TASK/PROC/OPP) não saem
    da máquina — nem o leitor as resolve, nem são dado que deva vazar."""
    dup = _dup(brain, kind, title)
    if dup is not None and not force:
        raise util.BrainError(f"já existe {dup} com o mesmo título e tipo — acrescente detalhe ao existente "
                              f"(`brain feedback show {dup}`) ou use --force", code=4)
    return brain.record_one({"type": "feedback.added", "by": by, "prov": prov, "source": source or "chat",
                             "date": date,
                             "data": {"kind": kind, "title": title, "body": body,
                                      **({"proposal": proposal} if proposal else {})}})


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
    public_text_guard(brain.inst, f.title, f.body)    # público: regra dura, sem override (título e corpo CRUS)
    title, body = issue_title(f), issue_body(f)
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
        ev = brain.record_one({"type": "feedback.pushed", "id": fid, "by": "system",
                               "data": {"number": res["number"], "url": res["url"]}})
        want = KIND_LABEL[f.kind]
        if "labels" in res and want not in res["labels"]:       # quem não é colaborador (ou o token sem permissão) fica sem label
            ev = {**ev, "label_note": f"a issue saiu sem o label '{want}' (o GitHub só aplica label com permissão de "
                                      "triagem no repo) — o dono do repo aplica na triagem"}
        return ev
    except util.BrainError:
        raise util.BrainError(f"{fid}: a issue {res['url']} foi criada mas o registro falhou — "
                              f"`brain feedback pushed {fid} --number {res['number']} --url {res['url']}`",
                              code=5)


def from_proposal(brain: Brain, pid: str) -> tuple[str | None, str]:
    """Proposta `framework` aceita → issue no repo do framework. → (FB-####, aviso).

    O "aceito" do dono é a aprovação do texto (ele o viu na proposta). Nunca falha o aceite: sem token,
    rede, dado do dono no texto ou título repetido, o FB fica `pendente` (ou nem nasce) e o aviso diz o
    que falta — `brain feedback push FB-####` resolve depois."""
    p = brain.state.proposals[pid]
    if p.kind != "framework":
        return None, ""
    if p.feedback:
        return p.feedback, ""
    try:
        public_text_guard(brain.inst, p.issue_title, p.issue_body)
        fb = add(brain, "sugestao", p.issue_title, p.issue_body, by="owner", prov="declarado",
                 source="chat", proposal=pid)
    except util.BrainError as e:
        return None, f"⚠ a issue não foi registrada: {e}"
    fid = fb["id"]
    try:
        push(brain, fid)
    except util.BrainError as e:
        return fid, f"⚠ {fid} ficou pendente: {e}"
    return fid, ""


def line(f) -> str:
    bits = [f.id, f.status, KIND_TAG[f.kind] + " " + f.title]
    if f.status == "criado":
        issue = f"#{f.number}"
        if f.issue_state:
            issue += " · issue " + {"open": "aberta", "gone": "apagada"}.get(f.issue_state, "fechada")
        bits.append(f"{issue} {f.url}")
    elif f.status == "falhou":
        bits.append(f"última tentativa falhou: {f.error[:80]}")
    return " · ".join(bits)


def sync(brain: Brain) -> tuple[list[dict], list[str]]:
    """Relê o estado de cada issue no GitHub e grava `feedback.synced` quando mudou. → (eventos, avisos)

    Observação de porta já aberta: roda de dia ou no noturno (como connector.pulled). Sem token, pula
    com aviso em vez de erro — é checagem de status, não publicação. Erro por item não para os demais."""
    st = brain.state
    repo = brain.inst.cfg["feedback"]["repo"]
    if not config.load_env(brain.inst).get("GITHUB_TOKEN"):
        return [], ["⚠ GITHUB_TOKEN ausente no config/.env — sync pulado"]
    events: list[dict] = []
    notes: list[str] = []
    for f in sorted(st.feedbacks.values(), key=lambda f: f.id):
        if f.status != "criado" or not f.number or f.issue_state == "gone":
            continue
        try:
            got = issue_state(brain.inst, repo, f.number)
        except util.BrainError as e:
            notes.append(f"⚠ {f.id}: {e}")
            continue
        if got["state"] != f.issue_state or got["reason"] != f.issue_reason:
            events.append({"type": "feedback.synced", "id": f.id, "by": "system",
                           "data": {"state": got["state"], "reason": got["reason"]}})
        notes.append(f"{f.id}: issue " + {"open": "aberta", "gone": "apagada (removida do GitHub)"}
                     .get(got["state"], "fechada"))
    if events:
        brain.record(events)
    return events, notes


def _need(brain: Brain, fid: str):
    f = brain.state.feedbacks.get(fid)
    if f is None:
        raise util.BrainError(f"{fid} não existe", code=3)
    return f


def _read_body(args) -> str | None:
    """`--body-file` (headless não passa heredoc) ou `--body`; None = não informado."""
    if getattr(args, "body_file", None):
        try:
            return Path(args.body_file).read_text(encoding="utf-8")
        except OSError as e:
            raise util.BrainError(f"não li --body-file ({e})", code=2)
    return args.body


def _check_public(brain: Brain, kind: str, title: str, body: str, agent: bool) -> None:
    """Antes de gravar: o agente segue o molde da issue; todo texto passa pelos validadores públicos."""
    if agent or issues.has_structure(body):
        issues.require(kind, body, "o corpo")
    public_text_guard(brain.inst, title, body)


def cli(args, brain: Brain) -> None:
    c = args.fbcmd
    if c == "template":
        print(issues.skeleton(args.kind))
    elif c == "revise":
        f = _need(brain, args.id)
        body = _read_body(args)
        title = args.title if args.title is not None else f.title
        new_body = body if body is not None else f.body
        origin = bool(args.proposal or f.proposal)
        _check_public(brain, issues.resolve_kind(f.kind, origin), title, new_body, agent=args.by == "agent" or origin)
        revise(brain, args.id, args.title, body, args.proposal or "", args.by)
        print(f"✓ {line(brain.state.feedbacks[args.id])}\n  confira o texto exato: `brain feedback show {args.id}`")
    elif c == "add":
        body = _read_body(args) or ""
        _check_public(brain, args.kind, args.title, body, agent=args.by == "agent")
        ev = add(brain, args.kind, args.title, body, args.by,
                 args.prov or ("declarado" if args.by == "owner" else "observado"),
                 args.source or "", args.date, args.force)
        f = brain.state.feedbacks[ev["id"]]
        print(f"✓ {line(f)}")
        if args.no_push:
            return
        try:                                       # add empurra a issue na sequência (porta 7)
            ev = push(brain, f.id)
            print(f"✓ issue criada: {ev['data']['url']}")
            if ev.get("label_note"):
                print(f"⚠ {ev['label_note']}")
        except util.BrainError as e:
            print(f"⚠ {e}")
    elif c == "push":
        ev = push(brain, args.id)
        print(f"✓ issue criada: {ev['data']['url']}")
        if ev.get("label_note"):
            print(f"⚠ {ev['label_note']}")
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
    elif c == "sync":
        events, notes = sync(brain)
        for n in notes:
            print(n)
        print(f"✓ {len(events)} mudança(s) de estado registrada(s)" if events else "= nada mudou")
    elif c == "show":
        f = _need(brain, args.id)
        _out(args, {"id": f.id, "kind": f.kind, "title": f.title, "body": f.body, "proposal": f.proposal,
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
    x.add_argument("--body", help="descrição no molde da issue (`brain feedback template --kind …`); o agente é obrigado a segui-lo")
    x.add_argument("--body-file", help="o mesmo, de um arquivo (headless não passa heredoc)")
    x.add_argument("--no-push", action="store_true", help="só registra (FB-#### pendente); `brain feedback push` depois")
    x.add_argument("--force", action="store_true", help="registra mesmo com título igual ao de um FB existente")
    _fact_opts(x)
    x = s.add_parser("template", help="o molde (campos e dicas) da issue pública: sugestao | bug | framework")
    x.add_argument("--kind", choices=list(issues.KINDS), default="sugestao")
    x = s.add_parser("revise", help="corrige título/corpo (ou liga a uma proposta aceita) de um FB que ainda não virou issue")
    x.add_argument("id")
    x.add_argument("--title")
    x.add_argument("--body")
    x.add_argument("--body-file")
    x.add_argument("--proposal", help="PROP-#### framework já aceita que originou este FB (a issue usa o molde de proposta)")
    x.add_argument("--by", choices=["owner", "agent"], default="owner")
    x = s.add_parser("push", help="cria a issue de um FB pendente/falhou no GitHub e registra número+URL")
    x.add_argument("id")
    x = s.add_parser("sync", help="relê o estado dos issues no GitHub (aberta/fechada) e grava as mudanças")
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
