"""Abre um arquivo do vault no programa certo da máquina do dono (Cursor para .md, VLC para vídeo, …).

O mapa vive em `[open]` do brain.toml (sinônimo antigo: `[tui.open]`): extensão sem ponto → nome do aplicativo (`md = "Cursor"`).
Extensão fora do mapa: o programa padrão do sistema (`open` no macOS, `xdg-open` no Linux).
Só abre arquivo que está dentro do vault; nunca escreve nada.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from . import util


def app_for(cfg: dict, path: str | Path) -> str:
    """Aplicativo configurado para a extensão do arquivo; vazio = padrão do sistema.

    `[open]` vence. `[tui.open]` continua aceito. `mode` e `ide` não são extensões.
    """
    ext = Path(path).suffix.lstrip(".").lower()
    opened = cfg.get("open")
    section = opened if isinstance(opened, dict) else {}
    raw = (cfg.get("tui") or {}).get("open") if isinstance(cfg.get("tui"), dict) else {}
    legacy = raw if isinstance(raw, dict) else {}
    mapping = {k: v for k, v in {**legacy, **section}.items() if k not in ("mode", "ide")}
    mapped = str(mapping.get(ext) or "")
    if mapped:
        return mapped
    return str(section.get("ide") or "")


def set_prefs(inst, mode: str, ide: str | None = None) -> list[str]:
    """Grava `[open]` (mode e, se vier, ide). Devolve as chaves que mudaram."""
    from . import config
    mode = (mode or "").strip()
    if mode not in ("auto", "ide", "brain"):
        raise util.BrainError("mode é auto, ide ou brain", code=4)
    updates: dict = {"mode": mode}
    if ide is not None:
        updates["ide"] = ide.strip()
    return config.set_keys(inst, "open", updates)


def prefer_reader(cfg: dict, which=None) -> bool:
    """True quando o clique deve abrir o leitor do Brain, não o editor."""
    import shutil
    raw = cfg.get("open") if isinstance(cfg.get("open"), dict) else None
    section = raw if isinstance(raw, dict) else {}
    mode = str(section.get("mode") or "auto")
    if mode == "brain":
        return True
    if mode == "ide":
        return False
    if str(section.get("ide") or ""):
        return False
    which = which or shutil.which
    return not any(which(n) for n in ("cursor", "code", "zed"))


def read_text(inst, rel: str, limit: int = 200_000) -> str:
    """Texto de um arquivo do vault. Recusa o que sai do vault."""
    path = resolve(inst, rel)
    if path.stat().st_size > limit:
        raise util.BrainError(f"{rel}: arquivo grande demais para o leitor", code=4)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise util.BrainError(f"{rel}: não é texto", code=4) from e


def resolve(inst, rel: str) -> Path:
    """Caminho absoluto de um arquivo do vault; recusa o que sai do vault ou não existe.

    Mesma regra do coletor e do /api/file: tira fragmento (`#L12`) e acha RAW já arquivado.
    """
    from . import linked
    found = linked.vault_file(inst, rel)
    if found is None:
        raise util.BrainError(f"{rel}: arquivo fora do vault ou não encontrado", code=4)
    return found


def argv_for(cfg: dict, path: Path, platform: str | None = None) -> list[str]:
    """Argumentos para abrir `path` no macOS/Linux. No Windows não há argv seguro (tudo passa por cmd.exe): []."""
    platform = platform or sys.platform
    app = app_for(cfg, path)
    if platform == "darwin":
        return ["open", "-a", app, str(path)] if app else ["open", str(path)]
    if platform.startswith("win"):
        return []
    return [app, str(path)] if app else ["xdg-open", str(path)]


def _shellexecute(path: Path, app: str = "", shell32=None) -> None:
    """Windows: abre pelo ShellExecuteW — sem cmd.exe, então `&`, `|` e `^` no nome do arquivo não viram comando (#130)."""
    if shell32 is None:
        import ctypes
        shell32 = getattr(ctypes, "windll").shell32      # só existe no Windows
    rc = shell32.ShellExecuteW(None, "open", app or str(path), f'"{path}"' if app else None, None, 1)
    if rc <= 32:
        raise OSError(f"ShellExecuteW retornou {rc}")


def _spawn(argv: list[str], popen=None) -> subprocess.Popen:
    """Dispara processo em POSIX e colhe o filho em thread daemon para não acumular zumbis."""
    proc = (subprocess.Popen if popen is None else popen)(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    threading.Thread(target=proc.wait, daemon=True, name="brain-opener-reap").start()   # colhe o filho; nunca bloqueia
    return proc


def open_file(inst, rel: str) -> str:
    """Abre `rel` (relativo ao vault) sem bloquear; devolve o aplicativo usado ('padrão do sistema' se não houver mapa)."""
    path = resolve(inst, rel)
    app = app_for(inst.cfg, path)
    try:
        if sys.platform.startswith("win"):
            _shellexecute(path, app)
        else:
            _spawn(argv_for(inst.cfg, path))
    except OSError as e:
        raise util.BrainError(f"não consegui abrir {path.name}: {e}", code=4) from e
    return app or "padrão do sistema"
