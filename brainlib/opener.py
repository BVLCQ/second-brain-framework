"""Abre um arquivo do vault no programa certo da máquina do dono (Cursor para .md, VLC para vídeo, …).

O mapa vive em `[tui.open]` do brain.toml: extensão sem ponto → nome do aplicativo (`md = "Cursor"`).
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
    """Aplicativo configurado para a extensão do arquivo; vazio = padrão do sistema."""
    ext = Path(path).suffix.lstrip(".").lower()
    mapping = (cfg.get("tui") or {}).get("open") or {}
    return str(mapping.get(ext) or "")


def resolve(inst, rel: str) -> Path:
    """Caminho absoluto de um arquivo do vault; recusa o que sai do vault ou não existe."""
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise util.BrainError(f"{rel}: caminho fora do vault", code=2)
    path = (inst.vault / p).resolve()
    if not path.is_relative_to(inst.vault.resolve()):
        raise util.BrainError(f"{rel}: caminho fora do vault", code=2)
    if not path.is_file():
        raise util.BrainError(f"{rel}: arquivo não encontrado", code=3)
    return path


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
