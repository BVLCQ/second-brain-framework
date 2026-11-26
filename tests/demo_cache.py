"""Instância demo pronta, montada uma vez por processo e copiada para cada teste.

`demo.cli` leva ~1,6 s (monta o vault, grava o ledger, renderiza o painel); a cópia, ~0,25 s. Mais de cem
testes (TUI e painel) pediam a mesma demo no `setUp`. O molde nunca é entregue: cada teste recebe a sua
cópia e pode alterá-la à vontade, como antes.

- A chave é o valor de `BRAIN_NOW`: a demo depende do relógio, e um teste não pode receber uma demo
  montada sob outro.
- `shutil.copy` (não `copy2`) deixa as datas de modificação como as de uma demo recém-montada; há código
  que compara mtime (frescor do painel).
- A demo não grava o próprio caminho em nenhum arquivo (conferido), então a cópia não aponta para o molde.
"""
from __future__ import annotations

import argparse
import atexit
import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from brainlib import demo as demo_mod  # noqa: E402

_templates: dict[str | None, Path] = {}
_scratch: list[Path] = []


def _cleanup() -> None:
    for p in _scratch:
        shutil.rmtree(p, ignore_errors=True)


atexit.register(_cleanup)


def _template() -> Path:
    key = os.environ.get("BRAIN_NOW")
    if key not in _templates:
        base = Path(tempfile.mkdtemp(prefix="brain-demo-template-"))
        _scratch.append(base)
        root = base / "inst"
        with contextlib.redirect_stdout(io.StringIO()):
            demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
        _templates[key] = root
    return _templates[key]


def build(dest: Path | str) -> Path:
    """Equivale a `demo.cli(Namespace(dir=dest, open=False))`, sem a saída e bem mais rápido."""
    dest = Path(dest)
    shutil.copytree(_template(), dest, copy_function=shutil.copy)
    return dest
