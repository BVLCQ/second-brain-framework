"""`brain tui` — cockpit de terminal (Textual) para o ./brain.

Dependência OPCIONAL: o núcleo do brain segue só com a stdlib. `./brain tui --setup` cria a venv
`.venv-tui` com as versões e hashes travados em requirements-tui.txt; `./brain tui` usa essa venv
sozinho. O desenho e o guia de uso: guides/tui-mockup.html.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from .. import util

FRAMEWORK = Path(__file__).resolve().parents[2]
VENV = ".venv-tui"
REQS = "requirements-tui.txt"


def _venv_python(root: Path) -> Path:
    return root / VENV / "bin" / "python"


def setup(root: Path = FRAMEWORK) -> None:
    """Cria a venv e instala as dependências travadas por hash (pip --require-hashes)."""
    reqs = root / REQS
    if not reqs.exists():
        raise util.BrainError(f"{REQS} não encontrado em {root}", code=3)
    venv = root / VENV
    if not _venv_python(root).exists():
        print(f"→ criando {VENV}")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    print("→ instalando dependências (versões e hashes travados)")
    subprocess.run([str(_venv_python(root)), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "--require-hashes", "-r", str(reqs)], check=True)
    print("✓ TUI pronta: ./brain tui")


def cli(args, brain) -> None:
    inst = brain.inst
    if args.setup:
        setup()
        return
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("o TUI não abre no modo noturno (BRAIN_NIGHTLY=1): não há dono presente", code=4)
    if importlib.util.find_spec("textual") is None:
        py = _venv_python(FRAMEWORK)
        if py.exists() and not os.environ.get("BRAIN_TUI_REEXEC"):
            os.environ["BRAIN_TUI_REEXEC"] = "1"
            os.environ["BRAIN_HOME"] = str(inst.root)
            os.execv(str(py), [str(py), str(FRAMEWORK / "brain"), "tui"])
        raise util.BrainError("o TUI precisa do Textual (extra opcional): rode `./brain tui --setup` "
                              "(cria .venv-tui com versões e hashes travados)", code=3)
    try:
        from .app import run
    except ModuleNotFoundError as exc:
        # venv parcial (instalação interrompida): textual existe, dependência dele não.
        raise util.BrainError(f"dependência do TUI ausente ({exc.name}): rode `./brain tui --setup` "
                              "para completar a instalação em .venv-tui", code=3) from exc
    run(inst)
