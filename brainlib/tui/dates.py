"""Datas em linguagem natural para os formulários do TUI (PT-BR, sem LLM)."""
from __future__ import annotations

import re
from datetime import date, timedelta

from .. import util

_WEEKDAYS = {"seg": 0, "segunda": 0, "ter": 1, "terca": 1, "qua": 2, "quarta": 2, "qui": 3, "quinta": 3,
             "sex": 4, "sexta": 4, "sab": 5, "sabado": 5, "dom": 6, "domingo": 6}
HELP = "hoje · amanhã · sex · +3d · 20/10 · 2026-10-20"


def parse_due(text: str, today: date | None = None) -> date | None:
    """'' → None. Levanta ValueError quando não reconhece a data."""
    today = today or util.today()
    s = util.fold(text or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    if s == "hoje":
        return today
    if s == "amanha":
        return today + timedelta(days=1)
    m = re.fullmatch(r"\+(\d{1,3})d?", s)
    if m:
        return today + timedelta(days=int(m.group(1)))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", s)
    if m:
        return date(int(m.group(3) or today.year), int(m.group(2)), int(m.group(1)))
    name = s.removesuffix("-feira")
    if name in _WEEKDAYS:
        ahead = (_WEEKDAYS[name] - today.weekday()) % 7
        return today + timedelta(days=ahead or 7)
    raise ValueError(f"data não reconhecida: {text!r} ({HELP})")


def describe(text: str, today: date | None = None) -> str:
    """Texto curto para mostrar ao lado do campo: '→ 2026-10-16 (sex 16/10)'."""
    try:
        d = parse_due(text, today)
    except ValueError as e:
        return str(e)
    return f"→ {d.isoformat()} ({util.fmt_date(d, True)})" if d else ""
