"""Validadores do texto que sai da máquina como issue pública (porta 7).

O repo do framework é público: o que o cérebro escreve ali não pode carregar gente, print, link interno nem
segredo. Esta é a trava de TODO caminho de publicação (`feedback push`, aceite de proposta `framework`,
`feedback add/revise`, `proposal add --kind framework`) — sem override.

Regras (cada uma devolve só o TIPO e a LINHA do achado, nunca o valor: o valor iria parar no chat/log):
  · dado do dono — nomes, e-mails, domínios, destinatários, caminhos, tokens (as regras do `upstream scan`)
  · ID do vault — TASK-####, OPP-####, ASK-#### … (o leitor público não os resolve e dizem do dono)
  · imagem/print — `![](…)`, `<img>`, anexos do GitHub, data: URI, nome de arquivo de imagem/vídeo/PDF
  · link — só github.com, example.* e localhost; o resto (Drive, Slack, Jira, Notion, Granola…) é interno
  · e-mail — só em domínio reservado (example.com/.org/.net, .test) ou com `-demo` no nome
  · @menção — o GitHub avisaria uma pessoa real (decorador em código `inline` é ignorado)
  · telefone, CPF, CNPJ, IP — dado pessoal
  · ID opaco — id de doc do Drive/Slack: sequência longa de letras e números

O que NÃO dá para detectar: nome de pessoa que não está no ledger, ou frase que descreve um caso real.
Contra isso vale a regra do template: exemplos sempre com os dados fictícios da padaria (`marina-demo`,
`heitor-demo`, "Padaria Pão Quente"), e o formulário da issue pede a confirmação humana.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config, util

ALLOWED_HOSTS = {"github.com", "www.github.com", "docs.github.com", "example.com", "example.org", "example.net",
                 "localhost", "127.0.0.1"}
RESERVED_MAIL = {"example.com", "example.org", "example.net"}

_IMG_RES = [
    re.compile(r"!\[[^\]]*\]\([^)]*\)"),
    re.compile(r"<img\b", re.I),
    re.compile(r"user-attachments|user-images\.githubusercontent", re.I),
    re.compile(r"data:[a-z0-9/+.-]+;base64", re.I),
    re.compile(r"\b[\w./-]+\.(?:png|jpe?g|gif|webp|heic|bmp|tiff?|svg|mp4|mov|mkv|webm|m4a|mp3|wav|pdf)\b", re.I),
]
_URL_RE = re.compile(r"\bhttps?://([^\s/)>\]\"'`]+)", re.I)
_INTERNAL_RE = re.compile(
    r"\b(?:docs|drive|mail|calendar|meet)\.google\.com|\.atlassian\.net|notion\.(?:so|site)|granola\.ai|"
    r"\.slack\.com|figma\.com|miro\.com|zoom\.us|\.sharepoint\.com|\.box\.com|dropbox\.com", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_MENTION_RE = re.compile(r"(?<![\w@./`-])@([A-Za-z0-9][A-Za-z0-9-]{0,38})\b")
_PHONE_RE = re.compile(r"(?<![\d-])(?:\+?55[\s.-]?)?(?:\(\d{2}\)\s?|\b\d{2}\s)9?\d{4}[\s.-]\d{4}(?![\d-])|"
                       r"(?<![\d-])9?\d{4}-\d{4}(?![\d-])")
_CPF_RE = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_CNPJ_RE = re.compile(r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)")
_IP_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IP_OK = {"127.0.0.1", "0.0.0.0"}
_OPAQUE_RE = re.compile(r"(?<![\w-])[A-Za-z0-9_-]{28,}(?![\w-])")
_SLACK_ID_RE = re.compile(r"\b[CDGUW](?=[A-Z0-9]*\d)[A-Z0-9]{8,11}\b")
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_DEMO_RE = re.compile(r"[\w.]+-demo\b", re.I)
_FENCE_RE = re.compile(r"```.*?```", re.S)
_INLINE_RE = re.compile(r"`[^`\n]*`")


def _code_free(text: str) -> str:
    """Texto sem blocos/trechos de código, preservando as quebras de linha (para a linha do achado)."""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))  # noqa: E731
    return _INLINE_RE.sub(blank, _FENCE_RE.sub(blank, text))


def _opaque(token: str) -> bool:
    return (any(c.isdigit() for c in token) and any(c.isalpha() for c in token) and not _SHA_RE.match(token.lower())
            and token.count("-") + token.count("_") < len(token) // 4)


def scan(inst: config.Instance, text: str, extra_hosts: tuple[str, ...] = ()) -> list[tuple[str, int]]:
    """[(tipo, linha)] de cada achado, sem repetir o mesmo tipo na mesma linha. Nunca devolve o valor."""
    from . import upstream
    term_res = [(kind, re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])", re.I))
                for t, kind in upstream._leak_terms(inst)]
    home = str(Path.home())
    hosts = ALLOWED_HOSTS | {h.lower() for h in extra_hosts}
    found: list[tuple[str, int]] = []
    text = text or ""
    plain = _DEMO_RE.sub(lambda m: "x" * len(m.group(0)), text)       # `-demo` marca dado fictício declarado
    nocode = _code_free(plain)
    raws, lines, bares = text.splitlines() or [""], plain.splitlines() or [""], nocode.splitlines() or [""]
    for n, (raw, line, bare) in enumerate(zip(raws, lines, bares), start=1):
        hits: list[str] = [h[0] for h in upstream._scan_line(raw, term_res, home)]
        if any(rx.search(line) for rx in _IMG_RES):
            hits.append("imagem ou print")
        if any(m.group(1).split(":")[0].lower() not in hosts for m in _URL_RE.finditer(line)):
            hits.append("link externo")
        if _INTERNAL_RE.search(line):
            hits.append("link interno")
        if any(m.group(1).lower() not in RESERVED_MAIL and not m.group(1).lower().endswith((".test", ".example", ".invalid"))
               for m in _EMAIL_RE.finditer(line)):
            hits.append("e-mail")
        if _MENTION_RE.search(bare):
            hits.append("@menção")
        if _PHONE_RE.search(line):
            hits.append("telefone")
        if _CPF_RE.search(line) or _CNPJ_RE.search(line):
            hits.append("CPF/CNPJ")
        if any(m.group(0) not in _IP_OK and all(int(x) <= 255 for x in m.group(0).split("."))
               for m in _IP_RE.finditer(line)):
            hits.append("endereço IP")
        if _SLACK_ID_RE.search(line) or any(_opaque(m.group(0)) for m in _OPAQUE_RE.finditer(bare)):
            hits.append("ID opaco (Drive/Slack…)")
        found += [(kind, n) for kind in dict.fromkeys(hits)]
    return found


def guard(inst: config.Instance, title: str = "", body: str = "", what: str = "o texto") -> None:
    """Recusa o texto público que carrega algo que não sai da máquina. Sem override; sem eco do valor."""
    hosts = tuple(inst.cfg.get("feedback", {}).get("allow_hosts", []))
    places: dict[str, list[str]] = {}
    for kind, _ in scan(inst, title, hosts):
        places.setdefault(kind, []).append("título")
    for kind, ln in scan(inst, body, hosts):
        places.setdefault(kind, []).append(f"corpo, linha {ln}")
    if not places:
        return
    where = "; ".join(f"{k} ({', '.join(dict.fromkeys(v[:4]))})" for k, v in places.items())
    raise util.BrainError(
        f"{what} vira issue pública e carrega o que não sai da máquina: {where}. Reescreva sem pessoas, prints, "
        "links internos ou números reais — para exemplos use os dados fictícios da padaria "
        "(`marina-demo`, \"Padaria Pão Quente\", `contato@example.com`). Descreva o problema, não o caso.", code=4)
