"""Utilidades sem dependência: tempo, texto, arquivos."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import threading
import sys
import unicodedata
import webbrowser
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import fcntl
except ImportError:  # pragma: no cover — Windows não é alvo (cron/launchd)
    fcntl = None

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
        # com fuso explícito (`…Z`, `+00:00`), converte: "hoje" é sempre no fuso da instância
        return dt.astimezone(tz()) if dt.tzinfo else dt.replace(tzinfo=tz())
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


def owner_slug(name: str, max_len: int = 32) -> str:
    """Id do dono gerado a partir do nome ("Marina Demo" → "marina-demo"). Instância é de uma pessoa só:
    ninguém precisa inventar id. Nome sem nenhuma letra/dígito latino (ex.: só ideogramas) cai em "dono"."""
    if not re.search(r"[a-z0-9]", fold(name)):
        return "dono"
    return slugify(name, max_len)


def sha(text: str | bytes, n: int = 16) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()[:n]


def atomic_write(path: Path, text: str) -> bool:
    """Escreve só se o conteúdo mudou (não perturba editores/sync abertos). Retorna True se escreveu."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())                # goals.md/brain.toml: sem fsync, queda de energia deixa o arquivo vazio
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)        # sem `.goals.md.xxxx` órfão no vault
        raise
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


_held_locks = threading.local()          # caminhos já travados nesta thread (re-entrância do flock)


@contextlib.contextmanager
def locked_state(path: Path) -> Iterator[None]:
    """Trava cross-processo (flock em `<path>.lock`) para leitura-modificação-escrita de JSON de estado —
    dois `brain` concorrentes (TUI + noturno, snapshot + repos) não se pisam.

    Re-entrante na thread: `repos pull` segura o estado e chama `snapshot.take`, que também trava."""
    key = str(path)
    held = getattr(_held_locks, "paths", None)
    if held is None:
        held = _held_locks.paths = set()
    if key in held:
        yield
        return
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        if fcntl:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            held.add(key)
            try:
                yield
            finally:
                held.discard(key)
        finally:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_UN)


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


# ── abrir o painel: reaproveita a aba do Brain que já está aberta (macOS) ──────────────────────────────────
# bundle id (minúsculo) do navegador padrão → (nome do app, família do AppleScript). Só o navegador PADRÃO é consultado:
# o macOS pede uma permissão de automação por app, e perguntar a todos os navegadores abertos seria invasivo.
_SCRIPTABLE = {
    "com.apple.safari": ("Safari", "safari"),
    "com.google.chrome": ("Google Chrome", "chromium"),
    "com.brave.browser": ("Brave Browser", "chromium"),
    "com.microsoft.edgemac": ("Microsoft Edge", "chromium"),
    "company.thebrowser.browser": ("Arc", "chromium"),
    "org.chromium.chromium": ("Chromium", "chromium"),
    "com.vivaldi.vivaldi": ("Vivaldi", "chromium"),
    "com.operasoftware.opera": ("Opera", "chromium"),
}
_FIND_TAB = {   # argv: prefixo da aba · URL de destino. Só roda com o app já aberto (o chamador confere): nunca o abre.
    "safari": '''on run argv
  set prefix to item 1 of argv
  set target to item 2 of argv
  tell application "{app}"
    repeat with w in windows
      repeat with t in tabs of w
        try
          if (URL of t) starts with prefix then
            if (URL of t) is not target then set URL of t to target
            set current tab of w to t
            try
              set miniaturized of w to false
            end try
            set index of w to 1
            activate
            return "ok"
          end if
        end try
      end repeat
    end repeat
  end tell
  return ""
end run''',
    "chromium": '''on run argv
  set prefix to item 1 of argv
  set target to item 2 of argv
  tell application "{app}"
    repeat with w in windows
      set i to 0
      repeat with t in tabs of w
        set i to i + 1
        try
          if (URL of t) starts with prefix then
            if (URL of t) is not target then set URL of t to target
            set active tab index of w to i
            try
              set minimized of w to false
            end try
            set index of w to 1
            activate
            return "ok"
          end if
        end try
      end repeat
    end repeat
  end tell
  return ""
end run''',
}


def _default_browser() -> tuple[str, str] | None:
    """(app, família) do navegador padrão do macOS, se for um que o AppleScript controla; senão None."""
    import plistlib
    path = Path.home() / "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"
    try:
        handlers = plistlib.loads(path.read_bytes()).get("LSHandlers", [])
    except Exception:  # noqa: BLE001 — ausente/ilegível: sem padrão conhecido
        return None
    for h in handlers:
        if h.get("LSHandlerURLScheme") in ("https", "http") and h.get("LSHandlerRoleAll"):
            return _SCRIPTABLE.get(str(h["LSHandlerRoleAll"]).lower())
    return None


def _tab_prefix(url: str) -> str | None:
    """O que identifica uma aba do Brain já aberta: a origem da ponte local (qualquer rota/token) ou o arquivo `file://`.
    Qualquer outro endereço não é reaproveitado."""
    m = re.match(r"(https?://127\.0\.0\.1:\d+/)", url)
    if m:
        return m.group(1)
    return url.split("#", 1)[0] if url.startswith("file://") else None


def focus_open_tab(url: str) -> bool:
    """macOS: já existe uma aba do Brain em ALGUM navegador aberto? Então a traz para a frente (e, se a ponte
    mudou de token, aponta ela para a URL nova) em vez de abrir outra. Varre o padrão primeiro e depois os
    demais controláveis que estiverem rodando — o dono nem sempre guarda o painel no navegador padrão.
    False = não achou em nenhum / sem permissão — quem chama abre normalmente. Nunca abre navegador: só
    consulta os que já estão rodando."""
    import subprocess
    prefix = _tab_prefix(url)
    if not prefix or sys.platform != "darwin":
        return False
    default = _default_browser()
    cands = ([default] if default else []) + [v for v in _SCRIPTABLE.values() if v != default]
    for app, family in cands:
        try:
            if subprocess.run(["/usr/bin/pgrep", "-x", app], capture_output=True, timeout=3).returncode != 0:
                continue                                          # fechado: osascript o abriria à toa
            r = subprocess.run(["/usr/bin/osascript", "-e", _FIND_TAB[family].format(app=app), prefix, url],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue                                              # permissão negada, osascript ausente, travou…
        if r.returncode == 0 and r.stdout.strip() == "ok":
            return True
    return False


class _MacOpen(webbrowser.BackgroundBrowser):
    """`/usr/bin/open` (traz o navegador para a frente), depois de tentar reaproveitar a aba do Brain que já está aberta."""

    def open(self, url, new=0, autoraise=True):  # noqa: A002
        return focus_open_tab(url) or super().open(url, new, autoraise)


_MAC_REGISTERED = False


def open_url(url: str) -> bool:
    """Abre `url` no navegador padrão. No macOS usa `/usr/bin/open`, que traz o navegador para a frente
    (o caminho padrão do `webbrowser`, via osascript, abre a aba mas não ativa o app — vindo do ícone
    do painel, parecia que nada acontecia) e, se o Brain já estiver aberto lá, reaproveita a aba em vez de abrir outra
    (`focus_open_tab`). Segue sendo `webbrowser.open`: um só ponto de abertura, que os testes conseguem interceptar
    — e, interceptado, nunca mexe nas abas do dono."""
    global _MAC_REGISTERED
    if sys.platform == "darwin" and os.access("/usr/bin/open", os.X_OK) and not _MAC_REGISTERED:
        webbrowser.register("macos-open", None, _MacOpen("/usr/bin/open"), preferred=True)
        _MAC_REGISTERED = True
    return webbrowser.open(url)
