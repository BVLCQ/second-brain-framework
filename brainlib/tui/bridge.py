"""Ponte do TUI com o resto do brain.

Toda ESCRITA passa por `./brain` como subprocesso — a mesma linha que o dono veria no terminal.
O TUI nunca toca no ledger nem no FRESH. Agente (⚡) roda headless com o runner configurado.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import runner, util

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
_PARSER = None


def _parser():
    global _PARSER
    if _PARSER is None:
        from .. import cli
        _PARSER = cli.build_parser()
    return _PARSER


def _subcommands(p) -> dict:
    return next((a.choices for a in p._actions if isinstance(a, argparse._SubParsersAction)), {})


def safe_args(args: list[str]) -> list[str]:
    """Texto digitado que começa com '-' ("-urgente", "--no") o argparse lê como opção e o comando falha. Valor de opção
    vira `--opt=valor`; argumento posicional com '-' vai para depois de `--`, com as opções antes. Mesmo comando, só blindado."""
    try:
        p = _parser()
    except Exception:  # noqa: BLE001 — sem o parser, segue a linha como veio
        return list(args)
    i, head = 0, []
    while i < len(args) and args[i] in _subcommands(p):
        head.append(args[i])
        p = _subcommands(p)[args[i]]
        i += 1
    opts: list[str] = []
    pos: list[tuple[int, str]] = []                  # (posição em opts, valor): a ordem original se não precisar de `--`
    while i < len(args):
        a = args[i]
        act = p._option_string_actions.get(a)
        if act is None:
            pos.append((len(opts), a))
            i += 1
        elif act.nargs == 0 or i + 1 == len(args):
            opts.append(a)
            i += 1
        else:
            v = args[i + 1]
            opts += [f"{a}={v}"] if v.startswith("-") else [a, v]
            i += 2
    if any(v.startswith("-") and v != "-" for _, v in pos):
        return head + opts + ["--"] + [v for _, v in pos]
    out = list(opts)
    for n, (at, v) in enumerate(pos):
        out.insert(at + n, v)
    return head + out


def display(args: list[str]) -> str:
    """A linha que o dono veria no terminal (a que roda, blindada). Argumento enorme (texto de nota) é encurtado só na exibição."""
    shown = [a if len(a) <= MAX_ARG else f"{a[:MAX_ARG - 30]}…(+{len(a) - MAX_ARG + 30} caracteres)" for a in safe_args(args)]
    return "brain " + shlex.join(shown)


def _env(inst) -> dict:
    env = {**os.environ, "BRAIN_HOME": str(inst.root)}
    env.pop("BRAIN_NIGHTLY", None)
    return env


def run_brain(inst, args: list[str], timeout: int = 300) -> Result:
    """Chama `./brain <args>` (lista de argumentos, sem shell)."""
    argv = [sys.executable, str(FRAMEWORK / "brain"), *safe_args(args)]
    try:
        p = subprocess.run(argv, cwd=inst.root, env=_env(inst), capture_output=True, text=True,
                           timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Result(args, 124, "", f"tempo esgotado ({timeout}s)")
    except OSError as e:                     # brain sumiu, permissão, fd esgotado: vira erro visível, não exceção no TUI
        return Result(args, 127, "", f"não consegui rodar {argv[1]}: {e}")
    return Result(args, p.returncode, p.stdout.strip(), p.stderr.strip())


# ── agente ⚡ ───────────────────────────────────────────────────────────────
OWNER_PREFIX = "O dono está presente (sessão do TUI) e pediu esta tarefa. "
STREAM_FLAGS = ["--output-format", "stream-json", "--verbose"]


def new_run_id() -> str:
    return "run-" + util.now().strftime("%Y%m%d-%H%M%S")


def run_prefix(run_id: str | None) -> str:
    if not run_id:
        return OWNER_PREFIX
    return (OWNER_PREFIX + f"Id desta rodada: {run_id}. Dúvida que precisa do dono vira pergunta: "
            f"`./brain ask add \"…\" --run {run_id} --source …` (não deixe só no relatório). ")


def _claude_flags(cfg: dict) -> list[str]:
    tui = cfg.get("tui", {})
    flags = [x for opt, key in (("--model", "model"), ("--effort", "effort")) if tui.get(key) for x in (opt, str(tui[key]))]
    return flags + STREAM_FLAGS


def _agent_name(cfg: dict) -> str | None:
    """Nome do preset que rodaria (None = nenhum agente, ou comando próprio)."""
    r = cfg["runner"]
    if r.get("command"):
        return None
    import shutil
    names = runner.AUTO_ORDER if r["agent"] == "auto" else [r["agent"]]
    for name in names:
        if name == "none":
            return None
        preset = runner.PRESETS.get(name)
        if preset and shutil.which(preset[0]):
            return name
    return None


def agent_argv(cfg: dict, prompt: str, run_id: str | None = None, extra_allow: list[str] | None = None) -> list[str] | None:
    """Comando headless do agente configurado ([runner] em brain.toml), com o prompt dado. `run_id` entra no prompt."""
    r = cfg["runner"]
    extra = runner.read_allow(cfg) + runner.door_allow(cfg) + [t for t in cfg.get("tui", {}).get("agent_allow", []) if t] + list(extra_allow or [])
    full = run_prefix(run_id) + prompt
    if r.get("command"):
        return [part.replace("{prompt}", full) for part in shlex.split(r["command"])]
    name = _agent_name(cfg)
    if name is None:
        return None
    argv = [p.replace("{prompt}", full) for p in runner.PRESETS[name]]
    if name == "claude":
        argv[3:3] = _claude_flags(cfg)     # antes de --allowedTools (variádico): as opções não viram nome de ferramenta
        argv += list(dict.fromkeys(extra))
    return argv


def resume_argv(cfg: dict, session_id: str, prompt: str, extra_allow: list[str] | None = None, run_id: str | None = None) -> list[str] | None:
    """Retoma a MESMA sessão do agente (`claude -p --resume <id>`) com o prompt e o allowlist atualizado.
    Agente sem resume conhecido (outros presets, comando próprio) → None: a fila de reserva (ASK respondida) assume."""
    if not session_id or _agent_name(cfg) != "claude":
        return None
    argv = agent_argv(cfg, prompt, run_id, extra_allow)
    return None if argv is None else [*argv[:3], "--resume", session_id, *argv[3:]]


@dataclass
class RunInfo:
    """O que a TUI guarda de uma rodada: sessão (para retomar), resultado final e o que o agente não pôde fazer."""
    id: str = ""
    session_id: str = ""
    result: str = ""
    rc: int = 0
    denials: list[dict] = field(default_factory=list)      # [{tool_name, tool_input}]
    asks: list[str] = field(default_factory=list)          # ASK-#### abertos nesta rodada
    resumed_from: str = ""
    structured: bool = False


class StreamParser:
    """Lê as linhas do `claude -p --output-format stream-json`. Cada linha devolve o que vai ao log; sessão, resultado e
    negações de permissão ficam em `info`. Linha que não é JSON passa como texto (os outros agentes continuam valendo)."""

    def __init__(self, info: RunInfo):
        self.info = info

    def feed(self, raw: str) -> list[str]:
        line = raw.strip()
        if not line.startswith("{"):
            return [raw] if raw.strip() else []
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return [raw]
        if not isinstance(ev, dict) or "type" not in ev:
            return [raw]
        self.info.structured = True
        if ev.get("session_id"):
            self.info.session_id = ev["session_id"]
        kind = ev.get("type")
        if kind == "assistant":
            out = []
            for blk in (ev.get("message") or {}).get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    out += [ln for ln in blk.get("text", "").splitlines() if ln.strip()]
            return out
        if kind == "result":
            self.info.result = ev.get("result") or ""
            self.info.denials = [{"tool_name": d.get("tool_name", ""), "tool_input": d.get("tool_input", {})}
                                 for d in ev.get("permission_denials") or [] if isinstance(d, dict)]
            if ev.get("is_error"):
                return [f"erro do agente: {self.info.result or ev.get('subtype', '')}"]
        return []


async def run_agent(inst, argv: list[str], on_line: Callable[[str], None], info: RunInfo | None = None) -> int:
    """Roda o agente e entrega a saída linha a linha. Devolve o código de saída; `info` (opcional) recebe a sessão, o resultado e
    as negações quando o agente fala stream-json."""
    timeout = inst.cfg["runner"]["timeout_min"] * 60
    info = info if info is not None else RunInfo()
    parser = StreamParser(info)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(inst.root), env=_env(inst), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, limit=16 * 1024 * 1024)
    except OSError as e:                     # agente desinstalado depois do which(): erro no log, TUI segue
        on_line(f"não consegui rodar {argv[0]}: {e}")
        return 127

    async def pump() -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            for ln in parser.feed(raw.decode("utf-8", "replace").rstrip()):
                on_line(ln)

    try:
        await asyncio.wait_for(pump(), timeout=timeout)
        info.rc = await proc.wait()
    except asyncio.TimeoutError:
        on_line(f"tempo esgotado ({timeout // 60} min)")
        info.rc = 124
    finally:
        if proc.returncode is None:       # tempo esgotado, ou o dono saiu do TUI no meio: o agente não fica rodando sozinho
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await asyncio.shield(proc.wait())
    return info.rc


def record_run(inst, info: RunInfo, argv: list[str], prompt: str) -> None:
    """Uma linha por rodada em vault/logs/agent-runs.jsonl: id, argv SEM o prompt, sessão, código, negações e ASKs abertos.

    Exceção deliberada à regra "o TUI só escreve chamando ./brain": é um log de observabilidade da própria
    ponte (zona logs/, sem dado de entidade) — não há o que registrar pelo ledger."""
    try:
        from ..core import Brain
        info.asks = [q.id for q in Brain(inst).state.questions.values() if info.id and q.run == info.id]
    except Exception:  # noqa: BLE001 — registro de rodada nunca derruba o TUI
        pass
    # comando próprio ([runner].command) pode repartir o prompt em vários argv (shlex): além do argumento
    # inteiro, token longo do prompt também é redigido — num log, redigir a mais é seguro; a menos, não
    toks = {t for t in prompt.split() if len(t) > 4} if prompt else set()
    shown = ["<prompt>" if (prompt and prompt in a) or a in toks else a for a in argv]
    inst.logs.mkdir(parents=True, exist_ok=True)
    row = {"id": info.id, "ts": util.iso_now(), "argv": shown, "session_id": info.session_id, "rc": info.rc,
           "denials": info.denials, "asks": info.asks, "resumed_from": info.resumed_from or None}
    with open(inst.logs / "agent-runs.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
