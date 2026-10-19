"""Programas swift pequenos (PDFKit, AVFoundation, Speech) compilados uma vez e guardados em cache — só macOS."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ("Library/Caches" if sys.platform == "darwin" else ".cache"))
    d = Path(base) / "segundo-cerebro"
    d.mkdir(parents=True, exist_ok=True)
    return d


def swift_tool(source: str, name: str, library: bool = False) -> list[str] | None:
    """Compila (uma vez) o programa e devolve o comando. `library=True` para fontes com @main.

    Sem `swiftc`, tenta o interpretador `swift` (só para scripts sem @main). Fora do macOS devolve None.
    """
    if sys.platform != "darwin":
        return None
    sha = hashlib.sha256(source.encode()).hexdigest()[:12]
    exe = cache_dir() / f"{name}-{sha}"
    if exe.exists():
        return [str(exe)]
    src = cache_dir() / f"{name}-{sha}.swift"
    src.write_text(source, encoding="utf-8")
    swiftc = shutil.which("swiftc")
    if swiftc:
        cmd = [swiftc, "-O", *(["-parse-as-library"] if library else []), str(src), "-o", str(exe)]
        if subprocess.run(cmd, capture_output=True, text=True, check=False).returncode == 0:
            return [str(exe)]
    swift = shutil.which("swift")
    return [swift, str(src)] if swift and not library else None
