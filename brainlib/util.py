"""Utilidades sem dependência: tempo, texto, arquivos."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_TZ_NAME = "America/Sao_Paulo"

WEEKDAYS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]


class BrainError(Exception):
    """Erro de uso/validação: mensagem curta, sem stack, exit code != 0."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def set_timezone(name: str) -> None:
    global _TZ_NAME
    ZoneInfo(name)  # valida cedo
    _TZ_NAME = name


def tz() -> ZoneInfo:
    return ZoneInfo(_TZ_NAME)


def now() -> datetime:
    """Agora no fuso da instância. BRAIN_NOW (ISO) congela o relógio — testes e demo."""
    fixed = os.environ.get("BRAIN_NOW")
    if fixed:
        dt = datetime.fromisoformat(fixed)
        return dt if dt.tzinfo else dt.replace(tzinfo=tz())
    return datetime.now(tz())


def today() -> date:
    return now().date()


def iso_now() -> str:
    return now().isoformat(timespec="seconds")


def parse_date(value: str | date | None) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as e:
        raise BrainError(f"data inválida: {value!r} (use AAAA-MM-DD)") from e


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=tz())


def fold(text: str) -> str:
    """Forma canônica para comparar nomes: minúsculas, sem acento, espaços colapsados."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    no_marks = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_marks).strip().lower()


def slugify(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return s[:max_len].strip("-") or "item"


def sha(text: str | bytes, n: int = 16) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()[:n]


def atomic_write(path: Path, text: str) -> bool:
    """Escreve só se o conteúdo mudou (não perturba editores/sync abertos). Retorna True se escreveu."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data) -> None:
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


_DUR_RE = re.compile(r"^\s*(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*(?:m|min)?)?\s*$", re.I)


def parse_duration(value: str | int | None, day_minutes: int = 480) -> int | None:
    """'90m' · '2h' · '1h30' · '1d' (= um dia de trabalho) · 45 → minutos."""
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    v = str(value).strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d+)h(\d+)", v)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = _DUR_RE.fullmatch(v)
    if not m or not any(m.groups()):
        raise BrainError(f"duração inválida: {value!r} (ex.: 90m, 2h, 1h30, 1d)")
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return d * day_minutes + h * 60 + mi


def fmt_duration(minutes: int | None) -> str:
    if not minutes:
        return "—"
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h}h{m:02d}"
    return f"{h}h" if h else f"{m}min"


def fmt_date(d: date | str | None, with_weekday: bool = False) -> str:
    d = parse_date(d) if not isinstance(d, date) else d
    if d is None:
        return "—"
    s = f"{d.day:02d}/{d.month:02d}"
    return f"{WEEKDAYS_PT[d.weekday()]} {s}" if with_weekday else s


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_label(key: str) -> str:
    y, w = key.split("-W")
    monday = date.fromisocalendar(int(y), int(w), 1)
    sunday = monday + timedelta(days=6)
    return f"semana {int(w)} · {fmt_date(monday)}–{fmt_date(sunday)}"


def days_between(a: date, b: date) -> int:
    return (b - a).days


def split_csv(value: str | list | None) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            out.extend(split_csv(v))
        return out
    return [p.strip() for p in str(value).split(",") if p.strip()]


def relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
