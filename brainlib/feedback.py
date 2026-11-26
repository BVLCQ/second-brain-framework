"""`brain feedback` — sugestões e bugs do próprio cérebro (`FB-####`): registra e vira issue no GitHub.

Porta estreita (AGENTS.md, porta 7): cada sugestão/bug registrado cria uma issue no repo público do
framework listado em `[feedback].repo` (padrão: o upstream). `add` grava o item e empurra a issue na
sequência — sem token, de noite ou com texto carregando dado do dono, o item fica `pendente` e o `push`
resolve depois. Título `[Sugestão]`/`[Bug]`/`[Proposta]` (sem id local) + label do tipo; `feedback.pushed` guarda número e URL,
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

from . import ask, config, gates, ids, issues, publicguard, schema, util
from .cli import _fact_opts, _out
from .core import Brain

KINDS = ("sugestao", "bug")
KIND_LABEL = {"sugestao": "sugestão", "bug": "bug"}          # label do issue no GitHub
API = "https://api.github.com"
TIMEOUT_S = 20


# ── o issue que a porta publica ──────────────────────────────────────────────

def issue_kind(f) -> str:
    """Molde da issue: proposta de código aceita → `framework`; senão o tipo do FB."""
    return issues.resolve_kind(f.kind, bool(f.proposal))


def issue_title(f) -> str:
    """`[Sugestão] …` · `[Bug] …` · `[Proposta] …` — a origem e o assunto à primeira vista. Nunca leva o id local
    (`FB-####`) nem tag escrita à mão: id de instância no repo público gera duplicidade entre instâncias."""
    return f"{issues.tag(issue_kind(f))} {issues.strip_tag(f.title)}"


def public_text(f) -> str:
    """O texto exato que a porta publica: título com a tag, corpo com cabeçalho, molde e rodapé."""
    return issue_title(f) + "\n\n" + issue_body(f)


def public_sha(f) -> str:
    return util.sha(public_text(f))


def _as_feedback(kind: str, title: str, body: str, proposal: str = ""):
    return type("F", (), {"kind": kind, "title": title, "body": body, "proposal": proposal})()


def issue_body(f, body: str | None = None) -> str:
    """O issue é público: tipo, o corpo no molde (`issues.py`) e um rodapé — nada local sai: nem refs do vault
    (TASK/PROC/OPP/PROP) nem o id do próprio FB, que é numeração da instância e geraria duplicidade."""
    kind = issue_kind(f)
    tipo = "🧩 proposta de código do cérebro" if kind == "framework" else \
        ("💡 sugestão" if f.kind == "sugestao" else "🐞 bug")
    raw_body = f.body if body is None else body
    lines = [f"**Tipo:** {tipo}", "", issues.render_body(kind, raw_body, f.title), "", "---",
             "Registrado pelo Segundo Cérebro (`brain feedback`)"]
    return "\n".join(lines)


_NEW_LONG = "|".join(ids.LONG_PREFIXES)
_OLD_LONG = "|".join(sorted(ids.LEGACY_LONG))
# Formas longas e GOAL/PROJ em qualquer caixa. As formas curtas legadas (P3.2, G1) só em maiúsculas, como
# se escrevem no goals.md: "p1"/"g2"/"p10" minúsculos são texto comum (prioridade de fila, geração) — o
# próprio `brain migrate ids` trata esses como ambíguos fora do vault.
VAULT_REF_RE = re.compile(
    rf"\b(?:(?i:(?:{_NEW_LONG})-\d{{3,}}|(?:{_OLD_LONG})-\d{{3,}}|(?:GOAL|PROJ)-\d+(?:\.\d+)?)"
    r"|P\d+(?:\.\d+)?|G\d+)\b"
)


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

def _github_request(inst: config.Instance, method: str, path: str, payload: dict | None = None, *,
                    urlopen=None, err_prefix: str = "GitHub recusou", err_suffix: str = "") -> dict:
    """Chamada autenticada à API REST do GitHub (stdlib urllib). Token nunca aparece em mensagens."""
    token = config.load_env(inst).get("GITHUB_TOKEN")
    if not token:
        raise util.BrainError("GITHUB_TOKEN ausente no config/.env — grave um token com permissão de criar "
                              "issues no repo de [feedback] (o valor nunca aparece no chat)", code=4)
    body_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "second-brain-feedback"}
    if body_bytes is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API}{path}", method=method, data=body_bytes, headers=headers)
    open_fn = urlopen or urllib.request.urlopen
    try:
        with open_fn(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("message", "")
        except Exception:
            pass
        raise util.BrainError(
            f"{err_prefix} ({e.code}{f' {detail}' if detail else ''}){err_suffix}", code=4) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise util.BrainError(f"sem contato com {API} ({e})", code=4) from e


class _InvalidResponseUrl(util.BrainError):
    """URL devolvida pela API externa falhou na validação de esquema/host após a chamada HTTP."""

    def __init__(self, msg: str, *, number=None):
        super().__init__(msg, code=5)
        self.number = number


def _http_url_or_blank(url) -> str:
    """URL devolvida pela API depois de uma escrita que JÁ aconteceu (comentário postado, issue atualizado).
    Inválida vira vazia, não vira erro: o ledger precisa registrar a escrita, e não pode guardar um link de
    esquema arbitrário para o painel abrir."""
    try:
        return util.require_http_url(url, "html_url")
    except util.BrainError:
        return ""


def create_issue(inst: config.Instance, repo: str, title: str, body: str, labels: list[str], *,
                 urlopen=None) -> dict:
    """POST /repos/<repo>/issues → {number, url}. Falha é dura: quem chama decide o que registrar."""
    data = _github_request(inst, "POST", f"/repos/{repo}/issues",
                           {"title": title, "body": body, "labels": labels},
                           urlopen=urlopen, err_prefix="GitHub recusou o issue", err_suffix=f" — repo {repo}")
    number = data["number"]
    try:
        url = util.require_http_url(data.get("html_url", ""), "html_url")
    except util.BrainError as e:
        raise _InvalidResponseUrl(str(e), number=number) from e
    return {"number": number, "url": url,
            "labels": [x.get("name", "") for x in data.get("labels", []) if isinstance(x, dict)]}


def add_comment(inst: config.Instance, repo: str, number: int, body: str, *, urlopen=None) -> dict:
    """POST /repos/<repo>/issues/<n>/comments → {html_url} (vazia se a API devolver link inválido)."""
    data = _github_request(inst, "POST", f"/repos/{repo}/issues/{number}/comments",
                           {"body": body}, urlopen=urlopen,
                           err_prefix=f"GitHub recusou comentar o issue #{number}", err_suffix=f" — repo {repo}")
    return {"html_url": _http_url_or_blank(data.get("html_url", ""))}


def update_issue(inst: config.Instance, repo: str, number: int, *, body: str | None = None,
                 state: str | None = None, state_reason: str | None = None, urlopen=None) -> dict:
    """PATCH /repos/<repo>/issues/<n> → {number, url, state, state_reason} (url vazia se a API devolver link inválido)."""
    payload = {k: v for k, v in (("body", body), ("state", state), ("state_reason", state_reason)) if v is not None}
    data = _github_request(inst, "PATCH", f"/repos/{repo}/issues/{number}",
                           payload, urlopen=urlopen,
                           err_prefix=f"GitHub recusou atualizar o issue #{number}", err_suffix=f" — repo {repo}")
    return {"number": data.get("number", number),
            "url": _http_url_or_blank(data.get("html_url", "")),
            "state": data.get("state", ""), "state_reason": data.get("state_reason") or ""}


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
    return {"state": data.get("state", ""), "reason": data.get("state_reason") or "",
            "body": data.get("body") or ""}


# ── fluxo da entidade ────────────────────────────────────────────────────────

def _dup(brain: Brain, kind: str, title: str, skip: str = "") -> str | None:
    norm = lambda t: " ".join(util.fold(issues.strip_tag(t)).split())  # noqa: E731
    return next((f.id for f in brain.state.feedbacks.values()
                 if f.id != skip and (f.kind, norm(f.title)) == (kind, norm(title))), None)


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
                             "data": {**data, "text_sha": public_sha(
                                 _as_feedback(brain.state.feedbacks[fid].kind,
                                              data.get("title", brain.state.feedbacks[fid].title),
                                              data.get("body", brain.state.feedbacks[fid].body),
                                              data.get("proposal") or brain.state.feedbacks[fid].proposal))}})


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
    stamped = _as_feedback(kind, title, body, proposal)
    return brain.record_one({"type": "feedback.added", "by": by, "prov": prov, "source": source or "chat",
                             "date": date,
                             "data": {"kind": kind, "title": title, "body": body, "text_sha": public_sha(stamped),
                                      **({"proposal": proposal} if proposal else {})}})


def withdraw(brain: Brain, fid: str, reason: str, by: str = "owner", prov: str = "", source: str = "") -> dict:
    """Retira um rascunho (`pendente`/`falhou`) antes de virar issue no GitHub."""
    f = _need(brain, fid)
    if f.number:
        raise util.BrainError(f"{fid}: issue #{f.number} já foi criada — use `brain feedback retract {fid}`", code=4)
    if f.status not in ("pendente", "falhou"):
        raise util.BrainError(f"{fid} está '{f.status}' — só rascunho pendente ou que falhou pode ser retirado", code=4)
    reason = (reason or "").strip()
    if not reason:
        raise util.BrainError("motivo obrigatório (--reason)", code=2)
    if by == "agent" and f.added_by != "agent":
        raise util.BrainError(f"{fid}: agente só pode retirar rascunho criado por agente", code=4)
    use_prov = prov or ("declarado" if by == "owner" else "observado")
    return brain.record_one({"type": "feedback.withdrawn", "id": fid, "by": by, "prov": use_prov,
                             "source": source or "chat", "data": {"reason": reason}})


def approve(brain: Brain, fid: str, quote: str, by: str = "owner") -> dict:
    """Grava o ok amarrado ao texto exato. Um revise depois disso invalida o push até novo ok."""
    f = _need(brain, fid)
    if f.status not in ("pendente", "falhou"):
        raise util.BrainError(f"{fid} está '{f.status}' — só rascunho pode ser aprovado", code=4)
    if util.is_nightly():
        raise util.BrainError(f"{fid}: aprovar issue é do dia — no noturno a porta não abre", code=4)
    if by != "owner":
        raise util.BrainError(f"{fid}: aprovar issue exige o dono (--by owner)", code=4)
    quote, origin = gates.verify_approval(quote, what=f"feedback approve {fid}")
    data = {"quote": quote, "text_sha": public_sha(f)}
    if origin == "surface":
        data["surface"] = quote
    return brain.record_one({"type": "feedback.approved", "id": fid, "by": "owner", "data": data})


def _bound_sha(f) -> str:
    approved = [e for e in f.history if e["type"] == "feedback.approved"]
    return approved[-1]["data"].get("text_sha", "") if approved else ""


def push(brain: Brain, fid: str, *, approval: str = "", by: str = "owner") -> dict:
    """Cria a issue no GitHub e grava `feedback.pushed` (número + URL). Erros de API gravam `feedback.failed`.

    Pré-cheques (aprovação, noturno, texto, token) falham ANTES de qualquer chamada na rede: nada é registrado
    como falha porque nada foi tentado — o item segue pendente."""
    f = _need(brain, fid)
    if f.status in ("retirado", "retratado"):
        raise util.BrainError(f"{fid} está '{f.status}' — não pode ser publicado", code=4)
    if f.status == "criado":
        raise util.BrainError(f"{fid}: issue já criada — {f.url}", code=4)
    if util.is_nightly():
        raise util.BrainError(f"{fid}: publicar issue é do dia — no noturno a porta não abre "
                              f"(registrar ficou; `brain feedback push {fid} --approval ok` amanhã)", code=4)
    if by != "owner":
        raise util.BrainError(f"{fid}: publicar issue exige o dono (--by owner)", code=4)
    sha = public_sha(f)
    bound_ev = next((e for e in reversed(f.history) if e["type"] == "feedback.approved"), None)
    bound_data = (bound_ev or {}).get("data") or {}
    bound = bound_data.get("text_sha", "")
    if bound and bound != sha:
        raise util.BrainError(f"{fid}: o texto mudou depois do ok — aprove de novo "
                              f"(`brain feedback approve {fid} --quote ok`) e publique com "
                              f"`brain feedback push {fid}`", code=4)
    approval = str(approval or "").strip()
    if approval:
        quote, origin = gates.verify_approval(approval, what=f"feedback push {fid}")
    elif bound:
        gates.require_owner_present(what=f"feedback push {fid}")
        quote = bound_data.get("quote", "")
        origin = "surface" if bound_data.get("surface") else "literal"
    else:
        raise util.BrainError(public_text(f) + f"\n\n{fid}: sem aprovação — o texto acima é o que subiria. "
                              f"`brain feedback approve {fid} --quote ok` e, em seguida, "
                              f"`brain feedback push {fid}`", code=4)
    repo = brain.inst.cfg["feedback"]["repo"]
    public_text_guard(brain.inst, f.title, f.body)    # público: regra dura, sem override (título e corpo CRUS)
    title, body = issue_title(f), issue_body(f)
    refs_guard(title, body)            # o que realmente sobe: nenhum id local (FB-####, TASK-####…), nem do rodapé
    if not config.load_env(brain.inst).get("GITHUB_TOKEN"):
        raise util.BrainError("GITHUB_TOKEN ausente no config/.env — grave um token com permissão de criar "
                              "issues no repo de [feedback] e tente de novo (o valor nunca aparece no chat)", code=4)
    try:
        res = create_issue(brain.inst, repo, title, body, [KIND_LABEL[f.kind]])
    except _InvalidResponseUrl as e:
        num = e.number if e.number is not None else "<n>"
        raise util.BrainError(
            f"{fid}: a issue pode já existir no GitHub mas a URL devolvida é inválida ({e}) — "
            f"confira e registre com `brain feedback pushed {fid} --number {num} --url <url>`",
            code=5,
        ) from e
    except util.BrainError as e:
        try:
            brain.record_one({"type": "feedback.failed", "id": fid, "by": "system", "data": {"error": str(e)}})
        except util.BrainError:
            pass                                  # a falha original é a que importa
        raise util.BrainError(f"{fid}: {e} — ficou '{brain.state.feedbacks[fid].status}'; "
                              f"`brain feedback push {fid} --approval ok` de novo", code=4) from e
    try:
        url = util.require_http_url(res.get("url", ""), "url")
    except util.BrainError as e:
        num = res.get("number")
        num_hint = num if num is not None else "<n>"
        raise util.BrainError(
            f"{fid}: a issue pode já existir no GitHub mas a URL devolvida é inválida ({e}) — "
            f"confira e registre com `brain feedback pushed {fid} --number {num_hint} --url <url>`",
            code=5,
        ) from e
    try:
        if approval and not bound:
            approve(brain, fid, approval, by=by)
            f = brain.state.feedbacks[fid]
        data: dict = {"number": res["number"], "url": url, "quote": quote, "text_sha": public_sha(f)}
        if origin == "surface":
            data["surface"] = quote
        ev = brain.record_one({"type": "feedback.pushed", "id": fid, "by": "owner", "data": data})
        want = KIND_LABEL[f.kind]
        if "labels" in res and want not in res["labels"]:       # quem não é colaborador (ou o token sem permissão) fica sem label
            ev = {**ev, "label_note": f"a issue saiu sem o label '{want}' (o GitHub só aplica label com permissão de "
                                      "triagem no repo) — o dono do repo aplica na triagem"}
        return ev
    except util.BrainError:
        raise util.BrainError(f"{fid}: a issue {url} foi criada mas o registro falhou — "
                              f"`brain feedback pushed {fid} --number {res['number']} --url {url}`",
                              code=5)


def retract(brain: Brain, fid: str, *, mode: str, reason: str, body: str | None = None,
            evidence: str = "", approval: str = "", by: str = "owner", prov: str = "",
            source: str = "", urlopen=None) -> dict:
    """Retrata uma issue publicada no GitHub: `--withdraw` (comenta + fecha como não planejada) ou `--correct`
    (atualiza o corpo + comenta; exige dono e aprovação literal). No noturno (`BRAIN_NIGHTLY=1`), vira ASK."""
    if mode not in ("withdraw", "correct"):
        raise util.BrainError(f"modo inválido: {mode!r} — use withdraw ou correct", code=2)
    f = _need(brain, fid)
    if not f.number:
        raise util.BrainError(f"{fid}: ainda não tem issue publicada — use `brain feedback withdraw {fid}`", code=4)
    if f.status in ("retirado", "retratado"):
        raise util.BrainError(f"{fid} já está '{f.status}'", code=4)
    reason = (reason or "").strip()
    if not reason:
        raise util.BrainError("motivo obrigatório (--reason)", code=2)

    evidence = (evidence or "").strip()
    approval = (approval or "").strip()
    if mode == "correct":
        if by != "owner":
            raise util.BrainError(f"{fid}: corrigir issue publicada (--correct) exige o dono (--by owner)", code=4)
        approval, _ = gates.verify_approval(approval, what=f"feedback retract --correct {fid}")
        if not (body or "").strip():
            raise util.BrainError(f"{fid}: --correct exige o novo corpo (--body ou --body-file)", code=2)
    else:
        if body is not None and body.strip():
            raise util.BrainError(f"{fid}: --withdraw não altera o corpo da issue — use --correct para corrigir texto",
                                  code=2)
        if by == "agent":
            if f.added_by != "agent" and f.pushed_by != "agent":
                raise util.BrainError(f"{fid}: agente só pode retratar issue criada ou publicada por agente", code=4)
            if not evidence:
                raise util.BrainError(f"{fid}: retratar como agente exige evidência (--evidence ou --source)", code=4)

    comment_body = (f"Retratado pelo Segundo Cérebro: {reason}" if mode == "withdraw"
                    else f"Texto corrigido pelo Segundo Cérebro: {reason}")
    public_text_guard(brain.inst, "", comment_body)
    clean_body = ""
    rendered_body = ""
    if mode == "correct":
        clean_body = body.strip()
        _check_public(brain, issue_kind(f), f.title, clean_body, agent=False)
        rendered_body = issue_body(f, clean_body)
        refs_guard(rendered_body)

    if util.is_nightly():
        parts = [f"Retratar {fid} (#{f.number}, modo={mode}): {reason}"]
        if evidence:
            parts.append(f"evidência: {evidence}")
        if mode == "correct":
            parts.append(f"novo corpo: {clean_body[:120]}")
        ask_text = " · ".join(parts)
        ev, qid, created = ask.add(
            brain, ask_text,
            options=["aprovar retratação", "manter issue"],
            context=[fid], kind="permissao",
            by="agent", prov="observado",
            source=source or evidence or "chat",
        )
        return ev or {"type": "question.asked", "id": qid,
                      "data": {"text": ask_text, "context": [fid], "kind": "permissao"}, "created": created}

    if not config.load_env(brain.inst).get("GITHUB_TOKEN"):
        raise util.BrainError("GITHUB_TOKEN ausente no config/.env — grave um token com permissão de comentar/fechar "
                              "issues no repo de [feedback] e tente de novo (o valor nunca aparece no chat)", code=4)

    repo = brain.inst.cfg["feedback"]["repo"]
    net_kw = {"urlopen": urlopen} if urlopen is not None else {}
    try:
        if mode == "withdraw":
            cm = add_comment(brain.inst, repo, f.number, comment_body, **net_kw)
            update_issue(brain.inst, repo, f.number, state="closed", state_reason="not_planned", **net_kw)
        else:
            update_issue(brain.inst, repo, f.number, body=rendered_body, **net_kw)
            cm = add_comment(brain.inst, repo, f.number, comment_body, **net_kw)
    except util.BrainError as e:
        try:
            brain.record_one({"type": "feedback.failed", "id": fid, "by": "system",
                              "data": {"error": str(e), "op": "retract"}})
        except util.BrainError:
            pass
        raise util.BrainError(f"{fid}: {e}", code=4) from e

    use_prov = prov or ("declarado" if by == "owner" else "observado")
    comment_url = cm.get("html_url") or ""
    data: dict = {
        "mode": mode,
        "reason": reason,
        "number": f.number,
        "url": f.url,
        "comment_url": comment_url,
    }
    if evidence:
        data["evidence"] = evidence
    if mode == "correct":
        data["body"] = clean_body
        data["approval"] = approval
    return brain.record_one({
        "type": "feedback.retracted",
        "id": fid,
        "by": by,
        "prov": use_prov,
        "source": source or evidence or "chat",
        "data": data,
    })


def from_proposal(brain: Brain, pid: str, *, approval: str = "ok") -> tuple[str | None, str]:
    """Proposta `framework` aceita → issue no repo do framework. → (FB-####, aviso).

    O "aceito" do dono é a aprovação do texto (ele o viu na proposta). Nunca falha o aceite: sem token,
    rede, dado do dono no texto ou título repetido, o FB fica `pendente` (ou nem nasce) e o aviso diz o
    que falta — `brain feedback push FB-#### --approval ok` resolve depois."""
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
        push(brain, fid, approval=approval, by="owner")
    except util.BrainError as e:
        return fid, f"⚠ {fid} ficou pendente: {e}"
    return fid, ""


def line(f) -> str:
    bits = [f.id, f.status, issue_title(f)]
    if f.status == "criado":
        issue = f"#{f.number}"
        if f.issue_state:
            issue += " · issue " + {"open": "aberta", "gone": "apagada"}.get(f.issue_state, "fechada")
        bits.append(f"{issue} {f.url}")
    elif f.status == "falhou":
        bits.append(f"última tentativa falhou: {f.error[:80]}")
    elif f.status == "retirado":
        if f.reason:
            bits.append(f"motivo: {f.reason}")
    elif f.status == "retratado":
        if f.number:
            issue = f"#{f.number}"
            if f.issue_state:
                issue += " · issue " + {"open": "aberta", "gone": "apagada"}.get(f.issue_state, "fechada")
            bits.append(f"{issue} {f.url}")
        if f.retract_mode:
            bits.append(f"modo: {f.retract_mode}")
        if f.reason:
            bits.append(f"motivo: {f.reason}")
        if f.comment_url:
            bits.append(f"comentário: {f.comment_url}")
    return " · ".join(bits)


def _diverged(f, got: dict) -> bool:
    """True se o GitHub devolveu um corpo diferente do texto que o Brain enviou. Sem corpo, não acusa."""
    body = got.get("body")
    if not isinstance(body, str) or got.get("state") == "gone":
        return False
    sent = " ".join(issue_body(f).split())
    return " ".join(body.split()) != sent


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
        if f.status not in ("criado", "retratado") or not f.number or f.issue_state == "gone":
            continue
        try:
            got = issue_state(brain.inst, repo, f.number)
        except util.BrainError as e:
            notes.append(f"⚠ {f.id}: {e}")
            continue
        diverged = _diverged(f, got)
        if got["state"] != f.issue_state or got["reason"] != f.issue_reason or diverged != f.issue_diverged:
            data = {"state": got["state"], "reason": got["reason"]}
            if diverged or f.issue_diverged:
                data["diverged"] = diverged
            events.append({"type": "feedback.synced", "id": f.id, "by": "system", "data": data})
        note = f"{f.id}: issue " + {"open": "aberta", "gone": "apagada (removida do GitHub)"}.get(got["state"], "fechada")
        if _diverged(f, got):
            note += " · o texto no GitHub divergiu do que foi enviado"
        notes.append(note)
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
        if args.by == "agent":
            print(f"  rascunho guardado — publicar no repo público pede aprovação do dono: `brain feedback push {f.id} --approval ok`")
            return
        if args.no_push:
            return
        try:                                       # add empurra a issue na sequência (porta 7)
            ev = push(brain, f.id, approval=args.approval or "", by=args.by)
            print(f"✓ issue criada: {ev['data']['url']}")
            if ev.get("label_note"):
                print(f"⚠ {ev['label_note']}")
        except util.BrainError as e:
            print(f"⚠ {e}")
    elif c == "approve":
        ev = approve(brain, args.id, args.quote or args.approval or "", args.by)
        print(f"✓ {args.id} aprovado · {ev['data']['text_sha']}")
    elif c == "push":
        ev = push(brain, args.id, approval=args.approval or "", by=args.by)
        print(f"✓ issue criada: {ev['data']['url']}")
        if ev.get("label_note"):
            print(f"⚠ {ev['label_note']}")
    elif c == "withdraw":
        ev = withdraw(brain, args.id, args.reason, by=args.by,
                      prov=args.prov or "", source=args.source or "")
        _out(args, ev, f"✓ {line(brain.state.feedbacks[args.id])}")
    elif c == "retract":
        mode = "withdraw" if args.withdraw else "correct"
        body = _read_body(args)
        evidence = args.evidence or args.source or ""
        ev = retract(brain, args.id, mode=mode, reason=args.reason, body=body,
                     evidence=evidence, approval=args.approval or "",
                     by=args.by, prov=args.prov or "", source=args.source or "")
        if ev.get("type") == "question.asked":
            _out(args, ev, f"✓ noturno: retratação de {args.id} ficou como pergunta {ev['id']} — aprove no dia")
        else:
            _out(args, ev, f"✓ {line(brain.state.feedbacks[args.id])}")
    elif c == "pushed":
        _need(brain, args.id)
        url = util.require_http_url(args.url, "--url")
        brain.record_one({"type": "feedback.pushed", "id": args.id, "by": "owner",
                          "data": {"number": args.number, "url": url}})
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
        tail = ""
        if f.reason:
            tail += f"\nmotivo: {f.reason}"
        if f.comment_url:
            tail += f"\ncomentário: {f.comment_url}"
        _out(args, {"id": f.id, "kind": f.kind, "title": f.title, "body": f.body, "proposal": f.proposal,
                    "status": f.status, "number": f.number, "url": f.url, "added": f.added,
                    "reason": f.reason, "comment_url": f.comment_url, "retract_mode": f.retract_mode,
                    "evidence": f.evidence, "added_by": f.added_by, "pushed_by": f.pushed_by,
                    "issue_title": issue_title(f), "issue_body": issue_body(f)},
             f"{f.id} · {f.status}" + (f" · {f.url}" if f.url else "") + tail + "\n\n"
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
    x.add_argument("--approval", default="", help="aprovação literal do dono (ex.: 'ok') para publicar na sequência")
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
    x = s.add_parser("approve", help="amarra o ok do dono ao texto exato que subiria")
    x.add_argument("id")
    x.add_argument("--quote", default="", help="aprovação literal (ok)")
    x.add_argument("--approval", default="", help="sinônimo de --quote")
    x.add_argument("--by", choices=["owner", "agent"], default="owner")
    x = s.add_parser("push", help="cria a issue de um FB pendente/falhou no GitHub e registra número+URL")
    x.add_argument("id")
    x.add_argument("--approval", default="", help="aprovação literal do dono (ex.: 'ok')")
    x.add_argument("--by", choices=["owner", "agent"], default="owner")
    x = s.add_parser("withdraw", help="retira um rascunho pendente/falhou antes de publicar")
    x.add_argument("id")
    x.add_argument("--reason", required=True, help="motivo da retirada")
    _fact_opts(x)
    x = s.add_parser("retract", help="retrata uma issue publicada no GitHub (--withdraw ou --correct)")
    x.add_argument("id")
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--withdraw", action="store_true", help="comenta e fecha a issue como não planejada")
    g.add_argument("--correct", action="store_true", help="atualiza o corpo da issue e comenta o motivo (exige dono + --approval)")
    x.add_argument("--reason", required=True, help="motivo público da retratação")
    x.add_argument("--body", help="novo corpo da issue (em --correct)")
    x.add_argument("--body-file", help="arquivo com o novo corpo da issue (em --correct)")
    x.add_argument("--evidence", help="evidência que justifica a retratação pelo agente")
    x.add_argument("--approval", default="", help="aprovação literal do dono (obrigatória em --correct)")
    _fact_opts(x)
    x = s.add_parser("sync", help="relê o estado dos issues no GitHub (aberta/fechada) e grava as mudanças")
    x = s.add_parser("pushed", help="registra issue criada por fora (--number/--url) — se o push morreu depois de criar")
    x.add_argument("id")
    x.add_argument("--number", type=int, required=True)
    x.add_argument("--url", required=True)
    x.set_defaults(by="owner")
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
