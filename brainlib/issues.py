"""Templates das issues públicas do cérebro (porta 7) — a fonte única do formato.

Três moldes, os mesmos campos dos formulários de `.github/ISSUE_TEMPLATE/*.yml` (um teste confere os dois):

  sugestao   — ideia de melhoria vinda do dono (ou do agente, depois do ok dele)
  bug        — defeito observado
  framework  — proposta do cérebro que muda código/estrutura, aceita pelo dono (`proposal add --kind framework`)

Cada campo vira `### <Título>` — o mesmo que o GitHub escreve ao enviar um formulário —, então issue aberta
pelo cérebro e issue aberta à mão têm a mesma cara. Todo exemplo usa os dados fictícios da padaria
(`marina-demo`, "Padaria Pão Quente", `contato@example.com`): nada do dono sai (ver `publicguard`).
"""
from __future__ import annotations

import re

from . import util

# (chave, título do campo, dica, obrigatório)
TEMPLATES: dict[str, dict] = {
    "sugestao": {
        "label": "sugestão",
        "tag": "[Sugestão]",
        "title": "Sugestão",
        "fields": [
            ("resumo", "Resumo", "Uma ou duas frases: o que melhoraria.", True),
            ("problema", "Problema", "O que dói hoje e para quem. Use um exemplo fictício, ex.: a Padaria Pão Quente com 36 fichas "
                                     "de receita para conferir uma a uma.", True),
            ("proposta", "Proposta", "O que você propõe, de forma concreta (comando, tela ou regra).", True),
            ("alternativas", "Alternativas consideradas", "O que mais foi pensado e por que não.", False),
            ("validacao", "Como validar", "Como saber que ficou bom (teste, antes/depois).", False),
        ],
    },
    "bug": {
        "label": "bug",
        "tag": "[Bug]",
        "title": "Bug",
        "fields": [
            ("resumo", "Resumo", "Uma frase: o que quebra.", True),
            ("obtido", "O que aconteceu", "O comportamento errado, com a mensagem de erro (sem dados reais).", True),
            ("esperado", "O que era esperado", "O que deveria acontecer.", True),
            ("passos", "Como reproduzir", "Passos numerados com dados fictícios da padaria "
                                          "(ex.: `brain action open \"Conferir o forno\" --owner marina-demo`).", True),
            ("ambiente", "Ambiente", "Versão do brain (`brain --version`) e sistema operacional.", False),
            ("logs", "Trecho do log", "Só o trecho relevante, já sem nomes, e-mails, caminhos ou links reais. Sem prints.", False),
        ],
    },
    "framework": {
        "label": "sugestão",
        "tag": "[Proposta]",
        "title": "Proposta de código do cérebro",
        "fields": [
            ("resumo", "Resumo", "Uma ou duas frases: o que muda no framework.", True),
            ("contexto", "Contexto", "Por que agora: o problema geral, sem citar o caso do dono.", True),
            ("proposta", "Proposta", "O que muda: comandos, arquivos, comportamento.", True),
            ("fora", "Fora do escopo", "O que não entra nesta mudança.", False),
            ("aceite", "Critérios de aceite", "Lista do que precisa valer para considerar pronto.", True),
        ],
    },
}
KINDS = tuple(TEMPLATES)
HEADING_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
PLACEHOLDER_RE = re.compile(r"^\s*(?:_?\(?preencha\)?_?|_no response_|\.\.\.|…|-|—)?\s*$", re.I)


def template(kind: str) -> dict:
    if kind not in TEMPLATES:
        raise util.BrainError(f"molde de issue inválido: {kind!r} — {', '.join(KINDS)}", code=2)
    return TEMPLATES[kind]


def skeleton(kind: str) -> str:
    """O molde em branco, para o agente preencher (cada campo com a dica e se é obrigatório)."""
    t = template(kind)
    out = []
    for _key, head, hint, req in t["fields"]:
        out += [f"### {head}", f"<!-- {'obrigatório' if req else 'opcional'} — {hint} -->", "", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def parse(body: str) -> dict[str, str]:
    """{título do campo: texto}. Comentários `<!-- -->` não contam como conteúdo."""
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    marks = list(HEADING_RE.finditer(body))
    return {m.group(1): body[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(body)].strip()
            for i, m in enumerate(marks)}


def has_structure(body: str) -> bool:
    return bool(HEADING_RE.search(re.sub(r"<!--.*?-->", "", body or "", flags=re.S)))


def problems(kind: str, body: str) -> list[str]:
    """O que falta para o corpo seguir o molde (campos obrigatórios presentes e preenchidos)."""
    t, got = template(kind), parse(body)
    out = []
    for _key, head, _hint, req in t["fields"]:
        if req and (head not in got or PLACEHOLDER_RE.match(got[head])):
            out.append(f"campo obrigatório vazio ou ausente: ### {head}")
    known = {head for _k, head, _h, _r in t["fields"]}
    out += [f"campo fora do molde: ### {h}" for h in got if h not in known]
    return out


def require(kind: str, body: str, what: str = "o corpo da issue") -> None:
    ps = problems(kind, body)
    if ps:
        raise util.BrainError(f"{what} não segue o molde '{kind}': " + "; ".join(ps) +
                              f". Veja o molde: `brain feedback template --kind {kind}`", code=4)


TAG_PREFIX_RE = re.compile(r"^\s*(?:\[[^\]]{1,24}\]|\bFB?-\d+\b)[\s:·-]*", re.I)


def strip_tag(title: str) -> str:
    """Título sem tag nem id local na frente (`[bug] x`, `FB-0003: x`): a tag oficial é posta na hora de publicar,
    e o id é dado local — publicado, geraria duplicidade entre instâncias."""
    out = (title or "").strip()
    while True:
        new = TAG_PREFIX_RE.sub("", out, count=1).strip()
        if new == out or not new:
            return out
        out = new


def tag(kind: str) -> str:
    return template(kind)["tag"]


def resolve_kind(fb_kind: str, from_proposal: bool) -> str:
    """Molde de uma issue: proposta de código aceita → `framework`; senão o tipo do FB."""
    return "framework" if from_proposal else fb_kind


def render_body(kind: str, body: str, title: str = "") -> str:
    """Corpo estruturado vai como está; texto livre (dono pela TUI/painel, FB antigo) vira o campo Resumo."""
    if has_structure(body):
        return body.strip()
    return f"### {template(kind)['fields'][0][1]}\n{(body or title).strip()}"
