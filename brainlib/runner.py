"""Rotina noturna + agendamento — agnóstica de agente (Cursor, Claude, Codex, Antigravity, Gemini).

Ordem: render (sempre, sem LLM) → agente headless roda /update (puxa fontes via MCP,
/dump) → sync de foco → memória → backup semanal → brief → render final. Cada passo isolado:
falha em um não derruba os outros. O agente roda com BRAIN_NIGHTLY=1: o ledger recusa
qualquer evento "do dono", aprovação, envio ou publicação — não há dono presente.
"""
from __future__ import annotations

import argparse
import hashlib
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

BASH_ALLOW = "Bash"   # qualquer comando de shell, sempre liberado para o agente headless (noturno e ações ⚡ do TUI)
# Toda ferramenta nativa do claude, sem restrição: o agente headless não consegue pedir permissão, então cada uma
# fora da lista virava um ASK `permissao`. MCP não entra aqui: leitura vai em [runner].allow, escrita só pelas portas.
CLAUDE_TOOLS = [BASH_ALLOW, "Read", "Edit", "Write", "Glob", "Grep", "NotebookEdit", "WebFetch", "WebSearch", "Task"]

PRESETS: dict[str, list[str]] = {
    "cursor": ["cursor-agent", "-p", "--force", "--output-format", "text", "{prompt}"],
    # `Bash` sem restrição: o agente headless nunca consegue pedir permissão, e cada comando fora de `./brain`
    # (ls, cat, cd, grep…) virava um ASK `permissao`. Escrita no mundo exterior continua só pelas portas (AGENTS.md).
    "claude": ["claude", "-p", "{prompt}", "--permission-mode", "acceptEdits",
               "--allowedTools", *CLAUDE_TOOLS],
    "codex": ["codex", "exec", "--full-auto", "{prompt}"],
    "agy": ["agy", "-p", "{prompt}", "--dangerously-skip-permissions"],
    "gemini": ["gemini", "-p", "{prompt}", "--yolo"],
}
AUTO_ORDER = ["cursor", "claude", "codex", "agy", "gemini"]
NIGHT_PROMPT = ("{base} — MODO NOTURNO: o dono não está presente. Permitido: ler fontes pelas ferramentas MCP de "
                "LEITURA listadas no config/watch.toml, gravar snapshots (./brain snapshot), processar a inbox (/dump) "
                "e registrar fatos com ./brain. PROIBIDO: qualquer ferramenta MCP de escrita (enviar mensagem, criar "
                "canvas/doc, mover card), aprovações, envios, publicações e mudanças de PLANNING. Única exceção: a porta "
                "oppdrive (pastas de oportunidade no Drive), se ligada — criar pasta/one-pager dentro da raiz, manter o "
                "Resumo (tabelas) igual ao Brain só pelos intervalos brain:* do plano do `brain oppdrive sync` e deixar "
                "SUGESTÕES (writeMode SUGGEST) no Detalhamento; nunca editar fora do Resumo, apagar, renomear ou mover; siga "
                "commands/opportunity/SKILL.md. Na dúvida, não faça — registre uma proposta.")


def preset_argv(name: str, cfg: dict, prompt: str) -> list[str] | None:
    """argv do preset `name` com `prompt`, ou None sem binário no PATH. claude ganha --model e as regras MCP."""
    preset = PRESETS.get(name)
    if not preset or not shutil.which(preset[0]):
        return None
    argv = [p.replace("{prompt}", prompt) for p in preset]
    if name == "claude":
        r = cfg["runner"]
        if r.get("model"):   # antes do --allowedTools (variádico): flag depois dele seria engolida
            argv = [argv[0], "--model", str(r["model"])] + argv[1:]
        argv += read_allow(cfg) + door_allow(cfg)
    return argv


def agent_candidates(cfg: dict) -> list[tuple[str, list[str]]]:
    """(nome, argv) na ordem de tentativa. `command` próprio: só ele. auto: a AUTO_ORDER com binário.
    Escolhido: ele primeiro; com [runner].fallback, depois o resto da AUTO_ORDER com binário."""
    r = cfg["runner"]
    prompt = NIGHT_PROMPT.format(base=r["prompt"])
    if r.get("command"):
        return [("command", [part.replace("{prompt}", prompt) for part in shlex.split(r["command"])])]
    if r["agent"] == "none":
        return []
    names = list(AUTO_ORDER) if r["agent"] == "auto" else [r["agent"]] + (
        [n for n in AUTO_ORDER if n != r["agent"]] if r.get("fallback", True) else [])
    return [(n, a) for n in names if (a := preset_argv(n, cfg, prompt))]


def agent_command(cfg: dict) -> list[str] | None:
    c = agent_candidates(cfg)
    return c[0][1] if c else None


AUTH_RE = re.compile(r"authenticat|not logged in|log ?in required|please log ?in|sign ?in|unauthori[sz]ed|\b401\b|api[ _-]?key|credential", re.I)
PROBE_PROMPT = "Responda apenas: ok"
LOGIN_HINT = {"claude": "abra `claude` num terminal e rode /login",
              "cursor": "cursor-agent login",
              "codex": "codex login",
              "agy": "abra `agy` num terminal e faça o login",
              "gemini": "abra `gemini` num terminal e escolha o login (ou defina GEMINI_API_KEY)"}


def failure_reason(text: str) -> str:
    """A linha que explica a falha: a primeira com cara de autenticação, senão a última não vazia (≤160)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    hit = next((ln for ln in lines if AUTH_RE.search(ln)), None)
    return (hit or (lines[-1] if lines else ""))[:160]


def _probe_argv(name: str, cfg: dict) -> list[str] | None:
    """argv da sonda: preset com prompt mínimo, ou `[runner].command` próprio com o mesmo prompt."""
    if name == "command":
        cmd = cfg["runner"].get("command") or ""
        if not cmd:
            return None
        return [p.replace("{prompt}", PROBE_PROMPT) for p in shlex.split(cmd)]
    return preset_argv(name, cfg, PROBE_PROMPT)


def probe(name: str, cfg: dict, cwd: Path | None = None, timeout: int = 60, run=subprocess.run) -> dict:
    """Sonda barata: o runner de verdade (preset ou [runner].command) com um prompt mínimo.
    → {'name','ok','auth','reason'}"""
    argv = _probe_argv(name, cfg)
    if argv is None or not shutil.which(argv[0]):
        return {"name": name, "ok": False, "auth": False,
                "reason": "binário não encontrado no PATH"
                          + ("" if name == "command" else f" ({name})")}

    try:
        p = run(argv, cwd=cwd, env={**os.environ, "BRAIN_NIGHTLY": "1"}, capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"name": name, "ok": False, "auth": False, "reason": f"sem resposta em {timeout}s"}
    out = f"{p.stdout or ''}\n{p.stderr or ''}"
    auth = bool(AUTH_RE.search(out))
    ok = p.returncode == 0 and not auth
    return {"name": name, "ok": ok, "auth": auth and not ok,
            "reason": "" if ok else (failure_reason(out) or f"código {p.returncode}")}


def mcp_gap(brain) -> str | None:
    """Aviso quando o runner ativo não é o claude e há fontes/regras MCP de leitura (issue #7)."""
    cfg = brain.inst.cfg
    if cfg["runner"].get("command"):
        return None
    cands = agent_candidates(cfg)
    if not cands or cands[0][0] == "claude":
        return None
    from . import watch
    try:
        n = len(watch.list_sources(brain.inst))
    except Exception:  # noqa: BLE001 — aviso é informativo
        n = 0
    if not n and not read_allow(cfg):
        return None
    a = cands[0][0]
    return (f"o runner ativo é {a}: as regras MCP de leitura ([runner].allow) só valem para o claude — as {n} "
            f"fontes do watch.toml só são lidas no noturno se o {a} tiver os mesmos conectores configurados nele "
            f"(confira vault/logs/nightly-agent.log) ou com `runner = claude`")


def read_allow(cfg: dict) -> list[str]:
    """Ferramentas MCP de LEITURA que o agente headless pode usar ([runner].allow) — vale para o noturno e o TUI."""
    return [t for t in cfg["runner"].get("allow", []) if t]


def door_allow(cfg: dict) -> list[str]:
    """Ferramentas MCP de escrita da porta oppdrive, só com a porta ligada. O dono as lista à mão em [oppdrive].tools:
    `brain agent allow` continua recusando escrita externa."""
    od = cfg.get("oppdrive") or {}
    return [t for t in od.get("tools", []) if t] if od.get("enabled") and od.get("root") else []


def _log(brain, line: str) -> None:
    brain.inst.logs.mkdir(parents=True, exist_ok=True)
    with open(brain.inst.logs / "nightly.log", "a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def _footprint(brain) -> tuple:
    led = brain.ledger_path
    inbox = brain.inst.inbox
    return (led.stat().st_size if led.exists() else 0,
            tuple(sorted(p.name for p in inbox.glob("*"))) if inbox.exists() else ())


def _attempt(brain, cmd: list[str], env: dict, timeout: int) -> tuple[int, str]:
    log = brain.inst.logs / "nightly-agent.log"
    start = log.stat().st_size if log.exists() else 0
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(f"──── {util.iso_now()} · {cmd[0]} ────\n")
        fh.flush()
        proc = subprocess.run(cmd, cwd=brain.inst.root, env=env, stdout=fh, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, timeout=timeout, check=False)
    with open(log, "rb") as fh:
        fh.seek(start)
        tail = fh.read().decode("utf-8", "replace").split("\n", 1)[-1]
    return proc.returncode, failure_reason(tail[-4000:])


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

    from . import perms
    perms.try_sync(brain.inst)    # o brain.toml pode ter mudado desde a última vez: o chat do dono acompanha
    step("render", lambda: render.summary(render.render_all(brain)).splitlines()[0])
    if not skip_agent:
        ran: dict = {}

        def run_agent():
            cands = agent_candidates(brain.inst.cfg)
            if not cands:
                return "nenhum agente headless encontrado — inbox espera o primeiro chat do dia"
            env = {**os.environ, "BRAIN_NIGHTLY": "1"}
            timeout = brain.inst.cfg["runner"]["timeout_min"] * 60
            failed: list[str] = []
            for name, cmd in cands:
                before = _footprint(brain)
                rc, why = _attempt(brain, cmd, env, timeout)     # TimeoutExpired sobe: rodou de verdade, não há fallback
                if rc == 0:
                    ran["name"] = name
                    return f"{name} ok" + (f" (fallback: {'; '.join(failed)})" if failed else "")
                if _footprint(brain) != before:
                    raise RuntimeError(f"{name} saiu com código {rc} depois de começar — {why} (vault/logs/nightly-agent.log)")
                failed.append(f"{name} — {why or f'código {rc}'}")
            raise RuntimeError("nenhum agente conseguiu rodar: " + "; ".join(failed) + " (vault/logs/nightly-agent.log)")
        step("agente", run_agent)
        gap = mcp_gap(brain)
        if ran.get("name") and ran["name"] != "claude" and gap:
            steps["fontes MCP"] = f"{ran['name']} não recebe [runner].allow — a leitura das fontes depende dos conectores do próprio {ran['name']}"
        brain.reload()
    if brain.state.focus_plans:
        from . import focus
        step("foco", lambda: f"{len(focus.sync(brain))} blocos de ações fechadas removidos")
    if brain.inst.cfg["memory"]["engine"] == "hindsight":
        from . import memory
        step("memória", lambda: (lambda r: f"{r['sent']} enviados, {r['remaining']} pendentes"
                                                   + (f", {len(r['resent'])} reenviados por retain falho" if r.get("resent") else ""))(memory.sync(brain)))
        from . import providers as _prov

        def _auth_guard() -> str:
            # o access token o Hindsight renova sozinho; o que mata a memória é o login/token
            # raiz expirado — vira tarefa acionável do dono (uma só), não falha do noturno
            auth = _prov.auth_state(brain)
            st = auth.get("state", "na")
            if st != "pending":
                return {"ok": "autenticada", "unknown": "não verificada (servidor fora do ar?)",
                        "manual": "verificação manual", "na": "não é assinatura"}.get(st, st)
            fix = auth.get("fix") or "brain memory auth"
            title = f"Reautenticar a memória ({auth.get('provider')}) — {fix}"
            if any(a.open and a.title == title for a in brain.state.actions.values()):
                return "pendente — tarefa já aberta no TODO"
            brain.record_one({"type": "action.opened", "by": "agent", "prov": "observado", "source": "nightly",
                              "data": {"title": title, "owner": brain.owner, "list": "mine", "due": None,
                                       "due_suggested": None, "due_reason": "",
                                       "due_none_reason": "reautenticação pede o dono presente (login/token) — "
                                                          "rode o comando do título",
                                       "effort_min": None, "project": None, "deliverable": None, "blocked_by": [],
                                       "unblocks": [], "people": [], "priority": None, "link": "",
                                       "origin": "nightly"}})
            return "pendente — tarefa aberta no TODO"
        step("memória autenticação", _auth_guard)
    bk = brain.inst.cfg["backup"]
    if bk["enabled"] and util.today().isoweekday() == bk["weekday"]:
        from . import backup
        step("backup", lambda: backup.run(brain))
    brain.reload()
    from . import notes as _notes

    def _ensure_brief() -> str:
        had_today = _notes.daily_brief(brain.inst.fresh)["is_today"]
        _notes.ensure_daily_brief(brain)
        return "ok" if had_today else "sem novidades"

    step("brief", _ensure_brief)
    step("render final", lambda: render.summary(render.render_all(brain)).splitlines()[0])
    try:
        from . import upstream as _up
        c = _up.check_update(brain.inst, force=False)   # renova o cache de versão/atualização (painel/TUI/doctor)
        if (c.get("behind") or 0) > 0:
            steps["atualização"] = f"{c['behind']} commits disponíveis — brain update"
    except Exception:                                   # noqa: BLE001 — sem rede no noturno é normal
        pass
    brain.record_one({"type": "run.completed", "id": "nightly", "by": "system", "data": {"ok": ok, "steps": steps}})
    print(("✓" if ok else "⚠") + " noturno: " + " · ".join(f"{k}: {v}" for k, v in steps.items()))
    return {"ok": ok, "steps": steps}


MARK = "# segundo-cerebro nightly"


def _crontab(run=None) -> list[str]:
    try:
        res = (run or subprocess.run)(["crontab", "-l"], capture_output=True, text=True, check=False)
    except OSError:
        return []
    return (res.stdout or "").splitlines() if res.returncode == 0 else []


def _cron_matches(line: str, root: Path) -> bool:
    if MARK not in line:
        return False
    for r in {str(root), str(Path(root).resolve())}:
        if f"cd {r} " in line or f"cd {shlex.quote(r)} " in line:
            return True
    return False


LAUNCHD_LABEL = "com.segundo-cerebro.nightly"          # legado: um rótulo para a máquina toda (só migração/leitura)


def launchd_label(root: Path) -> str:
    r = Path(root).resolve()
    return f"{LAUNCHD_LABEL}.{util.slugify(r.name, 24)}-{hashlib.sha1(str(r).encode()).hexdigest()[:8]}"


def _launchd_plist(root: Path | None = None) -> Path:
    """Plist desta instância; root=None = o plist legado."""
    label = launchd_label(root) if root is not None else LAUNCHD_LABEL
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def plist_root(plist: Path) -> Path | None:
    """Raiz da instância que o plist roda (WorkingDirectory ou a pasta de ProgramArguments[0]); None se ilegível."""
    try:
        with open(plist, "rb") as fh:
            d = plistlib.load(fh)
    except Exception:  # noqa: BLE001
        return None
    env = d.get("EnvironmentVariables") or {}
    wd = (env.get("BRAIN_HOME")
          or d.get("WorkingDirectory")
          or (Path(d["ProgramArguments"][0]).parent if d.get("ProgramArguments") else None))
    return Path(wd).resolve() if wd else None


def _use_launchd() -> bool:
    # cron no macOS roda fora da sessão de login: o agente (claude) sai com "Not logged in".
    # Um LaunchAgent roda na sessão do usuário e ainda recupera a execução perdida com o Mac dormindo.
    return sys.platform == "darwin" and shutil.which("launchctl") is not None


def _launchctl(*args: str, run=None) -> subprocess.CompletedProcess:
    return (run or subprocess.run)(["launchctl", *args], capture_output=True, text=True, check=False)


DEFAULT_SCHEDULE = "09:00"
OFF_SCHEDULES = {"off", "nao-agendar", "não-agendar"}


def _configured_schedule(brain) -> str:
    if brain is None:
        return DEFAULT_SCHEDULE
    raw = str((brain.inst.cfg.get("runner") or {}).get("schedule", DEFAULT_SCHEDULE) or DEFAULT_SCHEDULE).strip()
    return raw or DEFAULT_SCHEDULE


def _ctl_call(run, *args: str) -> subprocess.CompletedProcess:
    return _launchctl(*args, run=run) if run is not None else _launchctl(*args)


def _cron_call(run) -> list[str]:
    if run is not None and getattr(_crontab, "__module__", "") == __name__:
        return _crontab(run=run)
    return _crontab()


def _launchd_remove(root: Path, run=None) -> None:
    r = Path(root).resolve()
    plist = _launchd_plist(r)
    _ctl_call(run, "bootout", f"gui/{os.getuid()}/{launchd_label(r)}")
    plist.unlink(missing_ok=True)
    legacy = _launchd_plist(None)
    if legacy != plist and legacy.exists() and plist_root(legacy) == r:
        _ctl_call(run, "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}")
        legacy.unlink(missing_ok=True)


def scheduled_here(root: Path) -> bool:
    r = Path(root).resolve()
    if _use_launchd():
        if _launchd_plist(r).exists():
            return True
        legacy = _launchd_plist(None)
        return legacy.exists() and plist_root(legacy) == r
    return any(_cron_matches(ln, r) for ln in _crontab())


def foreign_schedule(root: Path) -> Path | None:
    """Legado apontando para outra raiz."""
    r = Path(root).resolve()
    if _use_launchd():
        legacy = _launchd_plist(None)
        other = plist_root(legacy) if legacy.exists() else None
        return other if other and other != r else None
    return None


def _schedule_launchd(args, brain, run=None, msg: str | None = None) -> None:
    root = brain.inst.root
    label = launchd_label(root)
    plist = _launchd_plist(root)
    if args.action == "status":
        if plist.exists():
            spec = plistlib.loads(plist.read_bytes()).get("StartCalendarInterval", {})
            loaded = _ctl_call(run, "print", f"gui/{os.getuid()}/{label}").returncode == 0
            print(f"launchd: {label} às {spec.get('Hour', 0):02d}:{spec.get('Minute', 0):02d}"
                  + ("" if loaded else " (plist existe, mas não carregado)"))
        elif (legacy := _launchd_plist(None)).exists() and plist_root(legacy) == root.resolve():
            spec = plistlib.loads(legacy.read_bytes()).get("StartCalendarInterval", {})
            loaded = _ctl_call(run, "print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}").returncode == 0
            print(f"launchd: {LAUNCHD_LABEL} às {spec.get('Hour', 0):02d}:{spec.get('Minute', 0):02d}"
                  + ("" if loaded else " (plist existe, mas não carregado)"))
        else:
            print(f"não agendado — `./brain schedule install --time {DEFAULT_SCHEDULE}`")
        return
    old = _cron_call(run)
    if any(_cron_matches(ln, root) for ln in old):  # migra: tira a linha antiga do cron
        keep = [ln for ln in old if not _cron_matches(ln, root)]
        (run or subprocess.run)(["crontab", "-"], input="\n".join(keep) + ("\n" if keep else ""), text=True, check=True)
    if args.action == "remove":
        _launchd_remove(root, run=run)
        print(msg or "✓ agendamento removido")
        return
    raw_time = getattr(args, "time", None)
    time_str = _check_time(raw_time if raw_time else _configured_schedule(brain))
    _ctl_call(run, "bootout", f"gui/{os.getuid()}/{label}")
    plist.unlink(missing_ok=True)
    hh, mm = time_str.split(":")
    brain.inst.logs.mkdir(parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps({
        "Label": label,
        "ProgramArguments": [str(root / "brain"), "nightly"],
        "WorkingDirectory": str(root),
        # PATH de quem instalou (mise/agente), como no cron
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        "StartCalendarInterval": {"Hour": int(hh), "Minute": int(mm)},
        "StandardOutPath": str(brain.inst.logs / "cron.log"),
        "StandardErrorPath": str(brain.inst.logs / "cron.log"),
        "ProcessType": "Background",
    }))
    res = _ctl_call(run, "bootstrap", f"gui/{os.getuid()}", str(plist))
    if res.returncode:
        raise util.BrainError(f"launchctl bootstrap falhou: {(res.stderr or res.stdout).strip()}", code=3)
    legacy = _launchd_plist(None)
    if legacy != plist and legacy.exists() and plist_root(legacy) == root.resolve():
        _ctl_call(run, "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}")
        legacy.unlink(missing_ok=True)
        print("↻ agendamento antigo (rótulo único da máquina) migrado para o rótulo desta instância")
    print(f"✓ noturno agendado às {time_str} (launchd: {label})")


def _check_time(value: str) -> str:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (value or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        # launchd aceita Hour=25 calado (e nunca roda) — e o agendamento anterior já teria sido removido
        raise util.BrainError(f"--time inválido: {value!r} (use HH:MM, ex.: {DEFAULT_SCHEDULE})", code=2)
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"


def schedule_cli(args, brain, run=None) -> None:
    raw_time = getattr(args, "time", None)
    explicit_time = raw_time is not None and str(raw_time).strip() != ""
    resolved_time = str(raw_time).strip() if explicit_time else _configured_schedule(brain)
    if args.action == "install":
        if not explicit_time and resolved_time.lower() in OFF_SCHEDULES:
            off_msg = f"✓ agendamento desligado (schedule = {resolved_time})"
            if _use_launchd():
                return _schedule_launchd(argparse.Namespace(action="remove", time=DEFAULT_SCHEDULE),
                                         brain, run=run, msg=off_msg)
            if not shutil.which("crontab"):
                print(off_msg)
                return
            root = brain.inst.root
            cron_list = _cron_call(run)
            lines = [ln for ln in cron_list if not _cron_matches(ln, root)]
            if len(lines) != len(cron_list):
                (run or subprocess.run)(["crontab", "-"], input="\n".join(lines) + ("\n" if lines else ""),
                                        text=True, check=True)
            print(off_msg)
            return
        resolved_time = _check_time(resolved_time)
    effective = argparse.Namespace(action=args.action, time=resolved_time)
    if _use_launchd():
        return _schedule_launchd(effective, brain, run=run)
    if not shutil.which("crontab"):
        raise util.BrainError("crontab não encontrado — agende `./brain nightly` no agendador do seu sistema "
                              "(launchd no macOS: guides/user-guide.md §Noturno)", code=3)
    root = brain.inst.root
    cron_list = _cron_call(run)
    lines = [ln for ln in cron_list if not _cron_matches(ln, root)]
    if args.action == "status":
        mine = [ln for ln in cron_list if _cron_matches(ln, root)]
        print(mine[0] if mine else f"não agendado — `./brain schedule install --time {DEFAULT_SCHEDULE}`")
        return
    if args.action == "install":
        hh, mm = resolved_time.split(":")
        qroot = shlex.quote(str(root))
        # cron roda com PATH mínimo (python do sistema, sem mise/agente) — fixa o PATH de quem instalou
        path = shlex.quote(os.environ.get("PATH", "/usr/bin:/bin"))
        lines.append(f"{int(mm)} {int(hh)} * * * cd {qroot} && PATH={path} ./brain nightly "
                     f">> vault/logs/cron.log 2>&1 {MARK}")
    (run or subprocess.run)(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    print(f"✓ noturno agendado às {resolved_time} (crontab)" if args.action == "install" else "✓ agendamento removido")
