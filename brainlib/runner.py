"""Rotina noturna + agendamento — agnóstica de agente (Cursor, Claude, Codex, Antigravity, Gemini).

Ordem: render (sempre, sem LLM) → agente headless roda /update (puxa fontes via MCP,
/dump) → sync de foco → memória → backup semanal → render final. Cada passo isolado:
falha em um não derruba os outros. O agente roda com BRAIN_NIGHTLY=1: o ledger recusa
qualquer evento "do dono", aprovação, envio ou publicação — não há dono presente.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import traceback

from . import util

PRESETS: dict[str, list[str]] = {
    "cursor": ["cursor-agent", "-p", "--force", "--output-format", "text", "{prompt}"],
    "claude": ["claude", "-p", "{prompt}", "--permission-mode", "acceptEdits",
               "--allowedTools", "Bash(./brain:*)", "Read", "Edit", "Write", "Glob", "Grep"],
    "codex": ["codex", "exec", "--full-auto", "{prompt}"],
    "agy": ["agy", "-p", "{prompt}", "--dangerously-skip-permissions"],
    "gemini": ["gemini", "-p", "{prompt}", "--yolo"],
}
AUTO_ORDER = ["cursor", "claude", "codex", "agy", "gemini"]
NIGHT_PROMPT = ("{base} — MODO NOTURNO: o dono não está presente. Permitido: ler fontes pelas ferramentas MCP de "
                "LEITURA listadas no config/watch.toml, gravar snapshots (./brain snapshot), processar a inbox (/dump) "
                "e registrar fatos com ./brain. PROIBIDO: qualquer ferramenta MCP de escrita (enviar mensagem, criar "
                "canvas/doc, mover card), aprovações, envios, publicações e mudanças de PLANNING. Na dúvida, não faça "
                "— registre uma proposta.")


def agent_command(cfg: dict) -> list[str] | None:
    r = cfg["runner"]
    prompt = NIGHT_PROMPT.format(base=r["prompt"])
    if r.get("command"):
        return [part.replace("{prompt}", prompt) for part in shlex.split(r["command"])]
    names = AUTO_ORDER if r["agent"] == "auto" else [r["agent"]]
    for name in names:
        if name == "none":
            return None
        preset = PRESETS.get(name)
        if preset and shutil.which(preset[0]):
            return [p.replace("{prompt}", prompt) for p in preset]
    return None


def _log(brain, line: str) -> None:
    brain.inst.logs.mkdir(parents=True, exist_ok=True)
    with open(brain.inst.logs / "nightly.log", "a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def nightly(brain, skip_agent: bool = False) -> dict:
    from . import render
    steps: dict[str, str] = {}
    ok = True
    _log(brain, f"──── nightly {util.iso_now()} ────")

    def step(name: str, fn) -> None:
        nonlocal ok
        try:
            res = fn()
            steps[name] = res or "ok"
            _log(brain, f"✓ {name}: {steps[name]}")
        except Exception as e:  # noqa: BLE001 — isolar falhas é o requisito
            ok = False
            steps[name] = f"falhou: {e}"
            _log(brain, f"✗ {name}: {e}\n{traceback.format_exc(limit=3)}")

    step("render", lambda: render.summary(render.render_all(brain)).splitlines()[0])
    if not skip_agent:
        cmd = agent_command(brain.inst.cfg)

        def run_agent():
            if not cmd:
                return "nenhum agente headless encontrado — inbox espera o primeiro chat do dia"
            env = {**os.environ, "BRAIN_NIGHTLY": "1"}
            timeout = brain.inst.cfg["runner"]["timeout_min"] * 60
            with open(brain.inst.logs / "nightly-agent.log", "a", encoding="utf-8") as fh:
                fh.write(f"──── {util.iso_now()} · {cmd[0]} ────\n")
                fh.flush()
                proc = subprocess.run(cmd, cwd=brain.inst.root, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                      timeout=timeout, check=False)
            if proc.returncode:
                raise RuntimeError(f"{cmd[0]} saiu com código {proc.returncode} (vault/logs/nightly-agent.log)")
            return f"{cmd[0]} ok"
        step("agente", run_agent)
        brain.reload()
    if brain.state.focus_plans:
        from . import focus
        step("foco", lambda: f"{len(focus.sync(brain))} blocos de ações fechadas removidos")
    if brain.inst.cfg["memory"]["engine"] == "hindsight":
        from . import memory
        step("memória", lambda: (lambda r: f"{r['sent']} enviados, {r['remaining']} pendentes")(memory.sync(brain)))
    bk = brain.inst.cfg["backup"]
    if bk["enabled"] and util.today().isoweekday() == bk["weekday"]:
        from . import backup
        step("backup", lambda: backup.run(brain))
    brain.reload()
    step("render final", lambda: render.summary(render.render_all(brain)).splitlines()[0])
    brain.record_one({"type": "run.completed", "id": "nightly", "by": "system", "data": {"ok": ok, "steps": steps}})
    print(("✓" if ok else "⚠") + " noturno: " + " · ".join(f"{k}: {v}" for k, v in steps.items()))
    return {"ok": ok, "steps": steps}


MARK = "# segundo-cerebro nightly"


def _crontab() -> list[str]:
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    return res.stdout.splitlines() if res.returncode == 0 else []


def schedule_cli(args, brain) -> None:
    if not shutil.which("crontab"):
        raise util.BrainError("crontab não encontrado — agende `./brain nightly` no agendador do seu sistema "
                              "(launchd no macOS: guides/user-guide.md §Noturno)", code=3)
    lines = [ln for ln in _crontab() if MARK not in ln]
    if args.action == "status":
        mine = [ln for ln in _crontab() if MARK in ln]
        print(mine[0] if mine else "não agendado — `./brain schedule install --time 05:00`")
        return
    if args.action == "install":
        hh, mm = args.time.split(":")
        root = shlex.quote(str(brain.inst.root))
        lines.append(f"{int(mm)} {int(hh)} * * * cd {root} && ./brain nightly >> vault/logs/cron.log 2>&1 {MARK}")
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    print(f"✓ noturno agendado às {args.time} (crontab)" if args.action == "install" else "✓ agendamento removido")
