"""Portfólio (processos e oportunidades): cálculos determinísticos, sem LLM.

O LLM extrai e redige; aqui só se contabiliza: duplicatas, lacunas, matriz, funil.
"""
from __future__ import annotations

import re

from . import util

STOPWORDS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas",
             "para", "pra", "por", "com", "um", "uma", "que", "se", "ao", "ou", "sem", "mais", "como"}
DUP_THRESHOLD = 0.5


def tokens(text: str) -> set[str]:
    """Tokens normalizados: minúsculas, sem acento, sem stopwords curtas do PT-BR."""
    words = re.findall(r"[a-z0-9]+", util.fold(text))
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def duplicates(title: str, problem: str, opps, limit: int = 3) -> list[tuple]:
    """Oportunidades parecidas com (título, problema): [(opp, similaridade)] com sim ≥ 0,5, melhores primeiro."""
    probe = tokens(f"{title} {problem}")
    scored = [(o, jaccard(probe, tokens(f"{o.title} {o.problem}"))) for o in opps]
    hits = [(o, round(s, 2)) for o, s in scored if s >= DUP_THRESHOLD]
    hits.sort(key=lambda x: (-x[1], x[0].id))
    return hits[:limit]


def process_gaps(p) -> list[str]:
    """Lacunas de cadastro de um processo ativo."""
    out = []
    if p.playbook is None:
        out.append("sem playbook")
    if not p.owner:
        out.append("sem responsável")
    if not p.recurrence or not p.duration_min or (p.runs_month is None):
        out.append("sem recorrência/duração")
    return out
