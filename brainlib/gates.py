"""Gates de aprovação literal do dono (e atestação de superfície).

Módulo central que valida a resposta literal do dono em todos os gates do CLI:
`ok` / `aprovo` (e `enviar N` / `Na` na porta de mensagens). TUI e painel
enviam `tui` / `painel` como atestação de superfície, exceto onde a Constituição
exige aceite digitado (`memory setup --mode full`).
"""
from __future__ import annotations

import re

from . import util

ACCEPTED_WORDS = frozenset({"ok", "aprovo"})            # resposta literal do dono (CLI ou digitação)
SURFACES = frozenset({"tui", "painel"})                 # atestação da superfície
OUTBOX_RE = re.compile(r"^(ok|aprovo|enviar \d+|\d+a)$")   # a constituição também aceita "enviar 1" / "1a" no outbox


def require_owner_present(what: str = "aprovação") -> None:
    """Recusa aprovação ou ato privativo do dono sob `BRAIN_AGENT` ou `BRAIN_NIGHTLY` (code 4)."""
    agent = util.is_agent()
    nightly = util.is_nightly()
    if not (agent or nightly):
        return
    if agent and nightly:
        who, env_hint = "o agente no noturno", "BRAIN_AGENT/BRAIN_NIGHTLY"
    elif agent:
        who, env_hint = "o agente", "BRAIN_AGENT"
    else:
        who, env_hint = "o noturno", "BRAIN_NIGHTLY"
    raise util.BrainError(
        f"{what}: {who} não pode aprovar no lugar do dono ({env_hint})",
        code=4,
    )


def verify_approval(
    value: str | None,
    *,
    what: str = "aprovação",
    words: frozenset[str] | set[str] = ACCEPTED_WORDS,
    pattern: re.Pattern[str] | None = None,
    allow_surface: bool = True,
) -> tuple[str, str]:
    """Devolve `(valor_normalizado, origem)` com `origem` em `{"literal", "surface"}`; recusa qualquer outra coisa (code 4)."""
    require_owner_present(what=what)
    val = " ".join(str(value or "").strip().lower().split()) if isinstance(value, str) else ""
    if allow_surface and val in SURFACES:
        return val, "surface"
    if val in words or (pattern is not None and pattern.match(val)):
        return val, "literal"
    hint = " ou 'enviar N'/'Na'" if pattern is OUTBOX_RE else ""
    if not val:
        detail = "recebido vazio"
    elif len(val) <= 40:
        detail = f"recebido {val!r}"
    else:
        detail = "recebido outra coisa"
    raise util.BrainError(
        f"{what}: exige a resposta literal do dono ('ok' ou 'aprovo'{hint}) — {detail}",
        code=4,
    )
