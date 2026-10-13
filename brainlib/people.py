"""Resolução de identidade: "Bia", "Beatriz C.", "beatriz.costa@…" → uma pessoa só."""
from __future__ import annotations

import re

from . import util


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9@._-]+", util.fold(text).lstrip("@")) if t]


def resolve(state, text: str) -> list[str]:
    """Candidatos em ordem de confiança: igualdade exata em nome/id/alias/email;
    senão, todos os tokens da consulta são prefixos de tokens de algum nome."""
    q = util.fold(text).lstrip("@")
    if not q:
        return []
    exact = [pid for pid, p in state.people.items() if any(util.fold(n) == q for n in p.names())]
    if exact:
        return exact
    q_tokens = [t.rstrip(".") for t in _tokens(text)]
    partial = []
    for pid, p in state.people.items():
        for name in p.names():
            n_tokens = _tokens(name)
            if q_tokens and all(any(nt.startswith(qt) for nt in n_tokens) for qt in q_tokens):
                partial.append(pid)
                break
    return partial


def alias_collisions(state) -> list[tuple[str, list[str]]]:
    """Aliases (forma canônica) apontando para mais de uma pessoa — ambiguidade séria."""
    seen: dict[str, set[str]] = {}
    for pid, p in state.people.items():
        for n in p.names():
            seen.setdefault(util.fold(n), set()).add(pid)
    return sorted((alias, sorted(ids)) for alias, ids in seen.items() if len(ids) > 1)
