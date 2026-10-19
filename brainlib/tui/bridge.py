"""Ponte do TUI com o resto do brain.

Toda ESCRITA passa por `./brain` como subprocesso — a mesma linha que o dono veria no terminal.
O TUI nunca toca no ledger nem no FRESH. Agente (⚡) roda headless com o runner configurado.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import runner

FRAMEWORK = Path(__file__).resolve().parents[2]      # onde mora o script `brain` (≠ BRAIN_HOME em instâncias de demo)


@dataclass
class Result:
    args: list[str]
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


MAX_ARG = 300


def display(args: list[str]) -> str:
    """A linha que o dono veria no terminal. Argumento enorme (texto de nota) é encurtado só na exibição."""
    shown = [a if len(a) <= MAX_ARG else f"{a[:MAX_ARG - 30]}…(+{len(a) - MAX_ARG + 30} caracteres)" for a in args]
    return "brain " + shlex.join(shown)


def _env(inst) -> dict:
    env = {**os.environ, "BRAIN_HOME": str(inst.root)}
    env.pop("BRAIN_NIGHTLY", None)
    return env


def run_brain(inst, args: list[str], timeout: int = 300) -> Result:
    """Chama `./brain <args>` (lista de argumentos, sem shell)."""
    argv = [sys.executable, str(FRAMEWORK / "brain"), *args]
    try:
        p = subprocess.run(argv, cwd=inst.root, env=_env(inst), capture_output=True, text=True,
                           timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Result(args, 124, "", f"tempo esgotado ({timeout}s)")
    return Result(args, p.returncode, p.stdout.strip(), p.stderr.strip())


# ── agente ⚡ ───────────────────────────────────────────────────────────────
OWNER_PREFIX = "O dono está presente (sessão do TUI) e pediu esta tarefa. "


def agent_argv(cfg: dict, prompt: str) -> list[str] | None:
    """Comando headless do agente configurado ([runner] em brain.toml), com o prompt dado."""
    r = cfg["runner"]
    extra = runner.read_allow(cfg) + [t for t in cfg.get("tui", {}).get("agent_allow", []) if t]
    full = OWNER_PREFIX + prompt
    if r.get("command"):
        return [part.replace("{prompt}", full) for part in shlex.split(r["command"])]
    names = runner.AUTO_ORDER if r["agent"] == "auto" else [r["agent"]]
    import shutil
    for name in names:
        if name == "none":
            return None
        preset = runner.PRESETS.get(name)
        if preset and shutil.which(preset[0]):
            argv = [p.replace("{prompt}", full) for p in preset]
            if name == "claude" and extra:
                argv += extra
            return argv
    return None


async def run_agent(inst, argv: list[str], on_line: Callable[[str], None]) -> int:
    """Roda o agente e entrega a saída linha a linha. Devolve o código de saída."""
    timeout = inst.cfg["runner"]["timeout_min"] * 60
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(inst.root), env=_env(inst), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    async def pump() -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            on_line(raw.decode("utf-8", "replace").rstrip())

    try:
        await asyncio.wait_for(pump(), timeout=timeout)
        return await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        on_line(f"tempo esgotado ({timeout // 60} min)")
        return 124
