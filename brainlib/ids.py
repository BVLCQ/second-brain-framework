"""Registro único dos prefixos de ID — o resto do código não escreve prefixo literal.

Prefixos declarativos: `ACT-0146` (ação), `DEC-` (decisão), `WIN-` (entrega/conquista), `PROP-` (proposta),
`MSG-` (mensagem), `PUB-` (publicação), `FOCUS-` (plano de foco), `PROC-` (processo), `OPP-` (oportunidade),
`GOAL-1` · `PROJ-3` · `PROJ-3.2` (goal · projeto · entregável, sem zeros: nascem do `goals.md`, que o dono edita).

Os nomes antigos (`A-0146`, `D-`, `E-`, `R-`, `M-`, `S-`, `F-`, `G1`, `P3`, `P3.2`) continuam **aceitos na entrada**
(CLI, `brain add`, parser do `goals.md`, TUI, MCP) como sinônimo: `normalize` traduz na hora e nada é reescrito. O código só
**emite** os nomes novos. Quem reescreve o histórico é `brain migrate ids` (migrate_ids.py).
"""
from __future__ import annotations

import re

# entidade → (prefixo, largura do número; 0 = sem zeros à esquerda)
PREFIXES: dict[str, tuple[str, int]] = {
    "action": ("ACT", 4), "decision": ("DEC", 4), "delivery": ("WIN", 4), "proposal": ("PROP", 4),
    "message": ("MSG", 4), "share": ("PUB", 4), "focus": ("FOCUS", 4),
    "process": ("PROC", 4), "opportunity": ("OPP", 4),
    "goal": ("GOAL", 0), "project": ("PROJ", 0),
}
# prefixo antigo (letra) → prefixo novo, para as entidades de ID longo (`A-0146`)
LEGACY_LONG = {"A": "ACT", "D": "DEC", "E": "WIN", "R": "PROP", "M": "MSG", "S": "PUB", "F": "FOCUS"}
LONG_PREFIXES = [PREFIXES[e][0] for e in ("action", "decision", "delivery", "proposal", "message", "share", "focus",
                                          "process", "opportunity")]

_LONG = "|".join(LONG_PREFIXES)
_OLD = "".join(LEGACY_LONG)

# IDs novos (anchored) — o que o ledger e o PLANNING guardam
ACTION_ID = re.compile(r"^ACT-\d{4,}$")
LONG_ID = re.compile(rf"^(?:{_LONG})-\d{{4,}}$")
GOAL_ID = re.compile(r"^GOAL-\d+$")
PROJ_ID = re.compile(r"^PROJ-\d+$")
DELIV_ID = re.compile(r"^PROJ-\d+\.\d+$")
PLAN_NODE = re.compile(r"^(GOAL-\d+|PROJ-\d+|PROJ-\d+\.\d+)$")
LINK_ID = re.compile(r"^(ACT-\d{4,}|GOAL-\d+|PROJ-\d+(?:\.\d+)?)$")           # alvo de nota / vínculo
ANY_ID = re.compile(rf"^(?:(?:{_LONG})-\d{{4,}}|GOAL-\d+|PROJ-\d+(?:\.\d+)?)$")

# fragmentos para compor outras regexes (sem âncoras)
PLAN_NODE_SRC = r"GOAL-\d+|PROJ-\d+\.\d+|PROJ-\d+"
LINK_SRC = r"ACT-\d{4,}|GOAL-\d+|PROJ-\d+(?:\.\d+)?"

# fragmentos dos nomes ANTIGOS, só para quem lê arquivos ainda não migrados (goals.md, nome de nota)
LEGACY_GOAL_SRC, LEGACY_PROJ_SRC, LEGACY_DELIV_SRC = r"G\d+", r"P\d+", r"P\d+\.\d+"
LEGACY_LINK_SRC = r"A-\d{4,}|G\d+|P\d+(?:\.\d+)?"
LEGACY_ACTION_SRC = r"A-\d{4,}"

_SHORT = re.compile(rf"^([{_OLD}])-(\d+)$", re.I)
_G = re.compile(r"^G(\d+)$", re.I)
_P = re.compile(r"^P(\d+)(?:\.(\d+))?$", re.I)
_NEW_LONG = re.compile(rf"^({_LONG})-(\d+)$", re.I)
_NEW_PLAN = re.compile(r"^(GOAL|PROJ)-(\d+)(?:\.(\d+))?$", re.I)


def normalize(ref):
    """Antigo → novo; novo passa intacto; o que não é ID volta como veio. Aceita minúsculas e zeros a menos (`a-146`, `p3.2`).

    Listas e tuplas são normalizadas elemento a elemento; valores que não são texto passam sem mudança."""
    if isinstance(ref, (list, tuple)):
        return type(ref)(normalize(x) for x in ref)
    if not isinstance(ref, str):
        return ref
    v = ref.strip()
    m = _SHORT.match(v)
    if m:
        return f"{LEGACY_LONG[m.group(1).upper()]}-{int(m.group(2)):04d}"
    m = _G.match(v)
    if m:
        return f"GOAL-{int(m.group(1))}"
    m = _P.match(v)
    if m:
        return f"PROJ-{int(m.group(1))}" + (f".{int(m.group(2))}" if m.group(2) is not None else "")
    m = _NEW_LONG.match(v)
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2)):04d}"
    m = _NEW_PLAN.match(v)
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2))}" + (f".{int(m.group(3))}" if m.group(3) is not None else "")
    return ref


def normalize_csv(value):
    """'A-1, A-2' → 'ACT-0001,ACT-0002' (para opções da CLI que aceitam vírgula)."""
    if not isinstance(value, str):
        return normalize(value)
    return ",".join(normalize(p.strip()) for p in value.split(",") if p.strip())


def is_id(ref: str) -> bool:
    return bool(ANY_ID.match(ref or ""))


def entity_of(ref: str) -> str | None:
    """`ACT-0001` → 'action'; `GOAL-1` → 'goal'; `PROJ-3` → 'project'; `PROJ-3.2` → 'deliverable'; senão None."""
    ref = normalize(ref or "")
    if DELIV_ID.match(ref):
        return "deliverable"
    for ent, (prefix, _) in PREFIXES.items():
        if ref.startswith(prefix + "-") and ANY_ID.match(ref):
            return ent
    return None


def prefix(entity: str) -> str:
    return PREFIXES[entity][0]


def make(entity: str, n: int) -> str:
    p, width = PREFIXES[entity]
    return f"{p}-{n:0{width}d}" if width else f"{p}-{n}"


def number(ref: str) -> int:
    """Número de um ID longo ou de goal/projeto (`ACT-0146` → 146, `PROJ-3` → 3, `PROJ-3.2` → 3)."""
    return int(re.search(r"-(\d+)", ref).group(1))


# ── migração: o mesmo mapa, só para quem escreve o texto antigo ─────────────────────────────────────────
OLD_LONG_RE = re.compile(rf"(?<![A-Za-z0-9_-])([{_OLD}])-(\d{{4,}})(?![A-Za-z0-9_])")
OLD_PLAN_RE = re.compile(r"(?<![A-Za-z0-9_.-])(?:P(\d+)\.(\d+)|P(\d+)|G(\d+))(?![A-Za-z0-9_]|\.\d)")


def old_to_new(old: str) -> str:
    """Tradução do nome antigo de um ID que existe (sem tocar em largura de zeros: `A-0146` → `ACT-0146`)."""
    return normalize(old)
