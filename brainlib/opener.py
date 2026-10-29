"""Abre um arquivo do vault no programa certo da máquina do dono (Cursor para .md, VLC para vídeo, …).

O mapa vive em `[tui.open]` do brain.toml: extensão sem ponto → nome do aplicativo (`md = "Cursor"`).
Extensão fora do mapa: o programa padrão do sistema (`open` no macOS, `xdg-open` no Linux).
Só abre arquivo que está dentro do vault; nunca escreve nada.
"""
from __future__ import annotations

import subprocess
import sys
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
    platform = platform or sys.platform
    app = app_for(cfg, path)
    if platform == "darwin":
        return ["open", "-a", app, str(path)] if app else ["open", str(path)]
    if platform.startswith("win"):
        return ["cmd", "/c", "start", "", str(path)]
    return [app, str(path)] if app else ["xdg-open", str(path)]


def open_file(inst, rel: str) -> str:
    """Abre `rel` (relativo ao vault) sem bloquear; devolve o aplicativo usado ('padrão do sistema' se não houver mapa)."""
    path = resolve(inst, rel)
    argv = argv_for(inst.cfg, path)
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        raise util.BrainError(f"não consegui abrir {path.name}: {e}", code=4) from e
    return app_for(inst.cfg, path) or "padrão do sistema"
