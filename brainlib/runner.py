"""Rotina noturna + agendamento — agnóstica de agente (Cursor, Claude, Codex, Antigravity, Gemini).

Ordem: render (sempre, sem LLM) → agente headless roda /update (puxa fontes via MCP,
/dump) → sync de foco → memória → backup semanal → render final. Cada passo isolado:
falha em um não derruba os outros. O agente roda com BRAIN_NIGHTLY=1: o ledger recusa
qualquer evento "do dono", aprovação, envio ou publicação — não há dono presente.
"""
from __future__ import annotations

import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

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
            argv = [p.replace("{prompt}", prompt) for p in preset]
            if name == "claude":
                argv += read_allow(cfg)
            return argv
    return None


def read_allow(cfg: dict) -> list[str]:
    """Ferramentas MCP de LEITURA que o agente headless pode usar ([runner].allow) — vale para o noturno e o TUI."""
    return [t for t in cfg["runner"].get("allow", []) if t]


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
        step("memória", lambda: (lambda r: f"{r['sent']} enviados, {r['remaining']} pendentes"
                                                   + (f", {len(r['resent'])} reenviados por retain falho" if r.get("resent") else ""))(memory.sync(brain)))
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


LAUNCHD_LABEL = "com.segundo-cerebro.nightly"


def _launchd_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _use_launchd() -> bool:
    # cron no macOS roda fora da sessão de login: o agente (claude) sai com "Not logged in".
    # Um LaunchAgent roda na sessão do usuário e ainda recupera a execução perdida com o Mac dormindo.
    return sys.platform == "darwin" and shutil.which("launchctl") is not None


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _launchd_remove() -> None:
    _launchctl("bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}")
    _launchd_plist().unlink(missing_ok=True)


def _schedule_launchd(args, brain) -> None:
    plist = _launchd_plist()
    if args.action == "status":
        if plist.exists():
            spec = plistlib.loads(plist.read_bytes()).get("StartCalendarInterval", {})
            loaded = _launchctl("print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}").returncode == 0
            print(f"launchd: {LAUNCHD_LABEL} às {spec.get('Hour', 0):02d}:{spec.get('Minute', 0):02d}"
                  + ("" if loaded else " (plist existe, mas não carregado)"))
        else:
            print("não agendado — `./brain schedule install --time 05:00`")
        return
    old = _crontab()
    if any(MARK in ln for ln in old):  # migra: tira a linha antiga do cron
        keep = [ln for ln in old if MARK not in ln]
        subprocess.run(["crontab", "-"], input="\n".join(keep) + ("\n" if keep else ""), text=True, check=True)
    _launchd_remove()
    if args.action == "remove":
        print("✓ agendamento removido")
        return
    hh, mm = args.time.split(":")
    root = brain.inst.root
    brain.inst.logs.mkdir(parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps({
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [str(root / "brain"), "nightly"],
        "WorkingDirectory": str(root),
        # PATH de quem instalou (mise/agente), como no cron
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        "StartCalendarInterval": {"Hour": int(hh), "Minute": int(mm)},
        "StandardOutPath": str(brain.inst.logs / "cron.log"),
        "StandardErrorPath": str(brain.inst.logs / "cron.log"),
        "ProcessType": "Background",
    }))
    res = _launchctl("bootstrap", f"gui/{os.getuid()}", str(plist))
    if res.returncode:
        raise util.BrainError(f"launchctl bootstrap falhou: {(res.stderr or res.stdout).strip()}", code=3)
    print(f"✓ noturno agendado às {args.time} (launchd: {LAUNCHD_LABEL})")


def _check_time(value: str) -> None:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (value or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        # launchd aceita Hour=25 calado (e nunca roda) — e o agendamento anterior já teria sido removido
        raise util.BrainError(f"--time inválido: {value!r} (use HH:MM, ex.: 05:00)", code=2)


def schedule_cli(args, brain) -> None:
    if args.action == "install":
        _check_time(args.time)
    if _use_launchd():
        return _schedule_launchd(args, brain)
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
        # cron roda com PATH mínimo (python do sistema, sem mise/agente) — fixa o PATH de quem instalou
        path = shlex.quote(os.environ.get("PATH", "/usr/bin:/bin"))
        lines.append(f"{int(mm)} {int(hh)} * * * cd {root} && PATH={path} ./brain nightly "
                     f">> vault/logs/cron.log 2>&1 {MARK}")
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    print(f"✓ noturno agendado às {args.time} (crontab)" if args.action == "install" else "✓ agendamento removido")
