"""Validadores do texto que sai da máquina como issue pública (porta 7).

O repo do framework é público: o que o cérebro escreve ali não pode carregar gente, print, link interno nem
segredo. Esta é a trava de TODO caminho de publicação (`feedback push`, aceite de proposta `framework`,
`feedback add/revise`, `proposal add --kind framework`) — sem override.

Regras (cada uma devolve só o TIPO e a LINHA do achado, nunca o valor: o valor iria parar no chat/log):
  · dado do dono — nomes, e-mails, domínios, destinatários, caminhos, tokens (as regras do `upstream scan`)
  · ID do vault — TASK-####, OPP-####, ASK-#### … (o leitor público não os resolve e dizem do dono)
  · imagem/print — `![](…)`, `<img>`, anexos do GitHub, data: URI, nome de arquivo de imagem/vídeo/PDF
  · link — só github.com, example.* e localhost; o resto (Drive, Slack, Jira, Notion, Granola…) é interno
  · e-mail — só em domínio reservado (example.com/.org/.net, .test, .localhost) ou com `-demo` no nome
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
RESERVED_MAIL_SUFFIXES = (".test", ".example", ".invalid", ".localhost")
VALID_DDDS: frozenset[str] = frozenset(f"{a}{b}" for a in "123456789" for b in "123456789")

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
# Resíduo aceito: timestamp Unix de 10 dígitos de meados de 2024–2025 (172…–175…) pode casar forma fixa
_PHONE_COMPACT_RE = re.compile(r"(?<!\d)(?:\+?55)?(\d{2})(\d{8,9})(?!\d)")
_CPF_RE = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_CNPJ_RE = re.compile(r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)")
_CPF_FLEX_RE = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_CNPJ_FLEX_RE = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_IP_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IP_OK = {"127.0.0.1", "0.0.0.0"}
_OPAQUE_RE = re.compile(r"(?<![\w-])[A-Za-z0-9_-]{28,}(?![\w-])")
_SLACK_ID_RE = re.compile(r"\b[CDGTUW](?=[A-Z0-9]*\d)[A-Z0-9]{8,11}\b")
_SHORT_MIXED_ID_RE = re.compile(r"\b[A-Z]\d(?=(?:[A-Z]*\d){2})[A-Z0-9]{6,10}\b")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.I)
_COMMIT_CTX_RE = re.compile(
    r"\b(?:commit|commits|sha|sha-?1|git|rebase|cherry-?pick|revert|merge|hash)\b|github\.com/[^\s]+/commit/",
    re.I,
)
_DEMO_RE = re.compile(r"[\w.]+-demo\b", re.I)
_FENCE_RE = re.compile(r"```.*?```", re.S)
_INLINE_RE = re.compile(r"`[^`\n]*`")


def _code_free(text: str) -> str:
    """Texto sem blocos/trechos de código, preservando as quebras de linha (para a linha do achado)."""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))  # noqa: E731
    return _INLINE_RE.sub(blank, _FENCE_RE.sub(blank, text))


def _opaque(token: str, line: str = "") -> bool:
    """Identifica sequências opacas (chaves, tokens, IDs), isentando apenas SHAs de git com contexto de commit."""
    if not (any(c.isdigit() for c in token) and any(c.isalpha() for c in token)):
        return False
    if _GIT_SHA_RE.match(token) and _COMMIT_CTX_RE.search(line):
        return False
    return token.count("-") + token.count("_") < len(token) // 4


def _valid_cpf(digits: str) -> bool:
    """Valida CPF de 11 dígitos ASCII pelos dois dígitos verificadores (módulo 11)."""
    if len(digits) != 11 or not (digits.isascii() and digits.isdigit()) or len(set(digits)) <= 1:
        return False
    r1 = sum(int(c) * w for c, w in zip(digits[:9], range(10, 1, -1))) % 11
    d1 = 0 if r1 < 2 else 11 - r1
    r2 = sum(int(c) * w for c, w in zip(digits[:10], range(11, 1, -1))) % 11
    d2 = 0 if r2 < 2 else 11 - r2
    return int(digits[9]) == d1 and int(digits[10]) == d2


def _valid_cnpj(digits: str) -> bool:
    """Valida CNPJ de 14 dígitos ASCII pelos dois dígitos verificadores (módulo 11)."""
    if len(digits) != 14 or not (digits.isascii() and digits.isdigit()) or len(set(digits)) <= 1:
        return False
    w1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    w2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    r1 = sum(int(c) * w for c, w in zip(digits[:12], w1)) % 11
    d1 = 0 if r1 < 2 else 11 - r1
    r2 = sum(int(c) * w for c, w in zip(digits[:13], w2)) % 11
    d2 = 0 if r2 < 2 else 11 - r2
    return int(digits[12]) == d1 and int(digits[13]) == d2


def _has_cpf_or_cnpj(line: str) -> bool:
    """Recusa CPF/CNPJ pontuado sempre e formas coladas/mistas com dígitos verificadores válidos."""
    if _CPF_RE.search(line) or _CNPJ_RE.search(line):
        return True
    if any(_valid_cpf(re.sub(r"\D", "", m.group(0))) for m in _CPF_FLEX_RE.finditer(line)):
        return True
    return any(_valid_cnpj(re.sub(r"\D", "", m.group(0))) for m in _CNPJ_FLEX_RE.finditer(line))


def _has_compact_phone(line: str) -> bool:
    """Detecta telefone brasileiro compacto (DDD válido + 8 dígitos fixo ou 9 dígitos celular)."""
    for m in _PHONE_COMPACT_RE.finditer(line):
        ddd, sub = m.group(1), m.group(2)
        if ddd in VALID_DDDS and ((len(sub) == 9 and sub[0] == "9") or (len(sub) == 8 and sub[0] in "2345")):
            return True
    return False


def _is_version_like(line: str, m: re.Match) -> bool:
    """Identifica falsos positivos de IP em strings de versão (v1.2.3.4, Chrome/120.0.1.2, versão 1.2.3.4)."""
    prefix = line[:m.start()]
    # `v` solto (colado em palavra é host: `srv10.0.0.5`) · `produto/` começando numa borda, sem ponto nem barra antes
    # (caminho de URL é IP: `example.com/192.168.1.42`) · operador de versão
    if re.search(r"(?:(?<![A-Za-z0-9])[vV]|(?<![\w./:@-])[A-Za-z][\w+-]*/|==|>=|<=|~=)$", prefix) \
            and not prefix.endswith("://"):
        return True
    return bool(re.search(r"\b(?:vers[aã]o|version|ver\.?|release|build)\s*[:=]?\s*v?$", prefix, re.I))


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
        if any(m.group(1).lower() not in RESERVED_MAIL and not m.group(1).lower().endswith(RESERVED_MAIL_SUFFIXES)
               for m in _EMAIL_RE.finditer(line)):
            hits.append("e-mail")
        if _MENTION_RE.search(bare):
            hits.append("@menção")
        if _PHONE_RE.search(line) or _has_compact_phone(line):
            hits.append("telefone")
        if _has_cpf_or_cnpj(line):
            hits.append("CPF/CNPJ")
        if any(m.group(0) not in _IP_OK and not _is_version_like(line, m)
               and all(int(x) <= 255 for x in m.group(0).split("."))
               for m in _IP_RE.finditer(line)):
            hits.append("endereço IP")
        if (_SLACK_ID_RE.search(line) or _SHORT_MIXED_ID_RE.search(bare)
                or any(_opaque(m.group(0), bare) for m in _OPAQUE_RE.finditer(bare))):
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
