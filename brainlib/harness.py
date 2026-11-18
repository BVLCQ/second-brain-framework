"""Canais de leitura do cérebro nos agentes (MCP somente-leitura + hook de recall no Claude Code).

O cérebro não cria, não aponta e não verifica bancos de memória de agentes: memória dos
agentes fica com os próprios agentes (o guia traz a receita de cada um). Aqui moram só
os canais de LEITURA do vault/ledger expostos pelo próprio cérebro (`brain mcp` e o hook
`UserPromptSubmit` de recall no Claude Code).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from . import config, util

FRAMEWORK = Path(__file__).resolve().parents[1]
AGENTS = {"claude-code": "Claude Code", "cursor-cli": "Cursor CLI", "codex": "Codex CLI"}
HERMES = "hermes"
MCP_NAME = "brain"
MARK_BEGIN = "# >>> brain: servidor MCP somente-leitura (gerenciado por `brain harness`) >>>"
MARK_END = "# <<< brain <<<"
# binário que denuncia o harness na máquina (PATH) + pista do diretório do dono
_DETECT = {"claude-code": ("claude", ".claude"), "cursor-cli": ("cursor-agent", ".cursor"),
           "codex": ("codex", ".codex"), HERMES: ("hermes", ".hermes")}


def _home(home: Path | None = None) -> Path:
    if home is not None:
        return Path(home)
    env_home = os.environ.get("HOME")
    return Path(env_home) if env_home else Path.home()


def _inst(inst_or_brain):
    return getattr(inst_or_brain, "inst", inst_or_brain)


def hermes_yaml(home: Path | None = None) -> Path:
    return _home(home) / ".hermes" / "config.yaml"


def mcp_spec(inst) -> dict:
    inst = _inst(inst)
    return {"command": str(FRAMEWORK / "brain"), "args": ["mcp"], "env": {"BRAIN_HOME": str(inst.root)}}


def _strip_marked_block(text: str) -> str:
    if MARK_BEGIN not in text or MARK_END not in text:
        return text
    i = text.index(MARK_BEGIN)
    j = text.index(MARK_END, i) + len(MARK_END)
    if j < len(text) and text[j] == "\n":
        return text[:i] + text[j + 1:]
    if i > 0 and text[i - 1] == "\n":
        return text[:i - 1] + text[j:]
    return text[:i] + text[j:]


def _hermes_mcp_info(inst, home: Path | None = None) -> dict:
    inst = _inst(inst)
    spec = mcp_spec(inst)
    p = hermes_yaml(home)
    if not p.exists():
        return {"present": False, "enabled": None}
    in_mcp = False
    in_brain = False
    brain_indent: int | None = None
    cmd_ok = False
    enabled: bool | None = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            head = line.split("#", 1)[0].strip()
            in_mcp = head == "mcp_servers:"
            in_brain = False
            brain_indent = None
            continue
        if not in_mcp:
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.split("#", 1)[0].strip()
        if brain_indent is None or indent <= brain_indent:
            if stripped == f"{MCP_NAME}:":
                in_brain = True
                brain_indent = indent
            else:
                in_brain = False
                if brain_indent is None:
                    brain_indent = indent
            continue
        if in_brain and indent > brain_indent:
            m = re.match(r"command:\s*(.+)$", stripped)
            if m and m.group(1).strip().strip("\"'") == spec["command"]:
                cmd_ok = True
            me = re.match(r"enabled:\s*(\w+)", stripped)
            if me:
                enabled = me.group(1).lower() == "true"
    return {"present": cmd_ok, "enabled": enabled}


def mcp_present(inst, agent: str, home: Path | None = None) -> bool:
    """Confere por leitura de arquivo se o servidor MCP somente-leitura do cérebro está registrado."""
    inst = _inst(inst)
    spec = mcp_spec(inst)
    h = _home(home)
    if agent == "claude-code":
        p = h / ".claude.json"
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        srv = data.get("mcpServers") if isinstance(data, dict) else None
        entry = srv.get(MCP_NAME) if isinstance(srv, dict) else None
        return isinstance(entry, dict) and entry.get("command") == spec["command"]
    if agent in ("cursor", "cursor-cli"):
        p = h / ".cursor" / "mcp.json"
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        srv = data.get("mcpServers") if isinstance(data, dict) else None
        entry = srv.get(MCP_NAME) if isinstance(srv, dict) else None
        return isinstance(entry, dict) and entry.get("command") == spec["command"]
    if agent == "codex":
        p = h / ".codex" / "config.toml"
        if not p.exists():
            return False
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return False
        srv = data.get("mcp_servers") if isinstance(data, dict) else None
        entry = srv.get(MCP_NAME) if isinstance(srv, dict) else None
        return isinstance(entry, dict) and entry.get("command") == spec["command"]
    if agent == HERMES:
        return bool(_hermes_mcp_info(inst, home)["present"])
    return False


def wire_mcp(inst, agent: str, home: Path | None = None, run=subprocess.run) -> dict:
    """Registra o servidor MCP somente-leitura do cérebro no agente. Devolve {'ok', 'how', 'hint'}."""
    inst = _inst(inst)
    spec = mcp_spec(inst)
    h = _home(home)
    if agent == "claude-code":
        cmd_str = (f"claude mcp add --scope user {MCP_NAME} "
                   f"--env BRAIN_HOME={inst.root} -- {spec['command']} mcp")
        if not shutil.which("claude"):
            return {"ok": False, "how": "manual",
                    "hint": f"CLI `claude` ausente no PATH — rode: `{cmd_str}`"}
        p = h / ".claude.json"
        has_foreign = False
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
                    entry = data["mcpServers"].get(MCP_NAME)
                    if isinstance(entry, dict):
                        if entry.get("command") == spec["command"]:
                            return {"ok": True, "how": "cli", "hint": ""}
                        has_foreign = True
            except (ValueError, OSError):
                pass
        if has_foreign:
            try:
                run(["claude", "mcp", "remove", "--scope", "user", MCP_NAME],
                    capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            r = run(["claude", "mcp", "add", "--scope", "user", MCP_NAME,
                     "--env", f"BRAIN_HOME={inst.root}", "--", spec["command"], "mcp"],
                    capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return {"ok": True, "how": "cli", "hint": ""}
            return {"ok": False, "how": "manual",
                    "hint": ((r.stderr or r.stdout or "").strip() or f"rode: `{cmd_str}`")[:300]}
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "how": "manual", "hint": f"{e} — rode: `{cmd_str}`"[:300]}

    if agent in ("cursor", "cursor-cli"):
        p = h / ".cursor" / "mcp.json"
        data = {}
        if p.exists():
            try:
                raw = p.read_text(encoding="utf-8")
                loaded = json.loads(raw) if raw.strip() else {}
                if not isinstance(loaded, dict):
                    return {"ok": False, "how": "manual",
                            "hint": "~/.cursor/mcp.json inválido — confira o arquivo"}
                if "mcpServers" in loaded and not isinstance(loaded["mcpServers"], dict):
                    return {"ok": False, "how": "manual",
                            "hint": "~/.cursor/mcp.json inválido — mcpServers não é objeto"}
                data = loaded
            except (ValueError, OSError):
                return {"ok": False, "how": "manual",
                        "hint": "~/.cursor/mcp.json inválido — confira o arquivo"}
        data.setdefault("mcpServers", {})[MCP_NAME] = spec
        util.atomic_write(p, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return {"ok": True, "how": "file", "hint": ""}

    if agent == "codex":
        p = h / ".codex" / "config.toml"
        raw = ""
        if p.exists():
            try:
                raw = p.read_text(encoding="utf-8")
                tomllib.loads(raw)
            except (tomllib.TOMLDecodeError, OSError):
                return {"ok": False, "how": "manual",
                        "hint": "~/.codex/config.toml inválido — confira o arquivo"}
        outside = _strip_marked_block(raw)
        try:
            parsed_out = tomllib.loads(outside) if outside.strip() else {}
        except tomllib.TOMLDecodeError:
            return {"ok": False, "how": "manual",
                    "hint": "~/.codex/config.toml inválido — confira o arquivo"}
        if isinstance(parsed_out.get("mcp_servers"), dict) and MCP_NAME in parsed_out["mcp_servers"]:
            return {"ok": False, "how": "manual",
                    "hint": "já existe um servidor `brain` no config do Codex — confira"}
        body = (
            f"{MARK_BEGIN}\n"
            f"[mcp_servers.{MCP_NAME}]\n"
            f"command = {json.dumps(spec['command'])}\n"
            f"args = {json.dumps(spec['args'])}\n"
            f"env = {{ BRAIN_HOME = {json.dumps(spec['env']['BRAIN_HOME'])} }}\n"
            f"{MARK_END}"
        )
        new = (outside + body + "\n") if (not outside or outside.endswith("\n")) else (outside + "\n" + body)
        try:
            chk = tomllib.loads(new)
            if chk.get("mcp_servers", {}).get(MCP_NAME, {}).get("command") != spec["command"]:
                return {"ok": False, "how": "manual", "hint": "falha ao validar ~/.codex/config.toml"}
        except tomllib.TOMLDecodeError:
            return {"ok": False, "how": "manual", "hint": "falha ao validar ~/.codex/config.toml"}
        util.atomic_write(p, new)
        return {"ok": True, "how": "file", "hint": ""}

    if agent == HERMES:
        cmd_str = (f"hermes mcp add {MCP_NAME} --command {spec['command']} "
                   f"--env BRAIN_HOME={inst.root} --args mcp")
        if not shutil.which("hermes"):
            return {"ok": False, "how": "manual",
                    "hint": f"CLI do Hermes ausente no PATH — rode: `{cmd_str}`"}
        try:
            r = run(["hermes", "mcp", "add", MCP_NAME, "--command", spec["command"],
                     "--env", f"BRAIN_HOME={inst.root}", "--args", *spec["args"]],
                    capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "how": "manual", "hint": f"{e} — rode: `{cmd_str}`"[:300]}
        combined = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
        if r.returncode != 0 or "save config anyway" in combined or not mcp_present(inst, HERMES, home=home):
            return {"ok": False, "how": "manual",
                    "hint": f"servidor MCP não foi gravado no Hermes — rode: `{cmd_str}`"}
        return {"ok": True, "how": "cli", "hint": ""}

    return {"ok": False, "how": "manual", "hint": f"agente desconhecido: {agent!r}"}


def unwire_mcp(inst, agent: str, home: Path | None = None, run=subprocess.run) -> dict:
    """Remove o servidor MCP somente-leitura do cérebro do agente."""
    inst = _inst(inst)
    h = _home(home)
    if agent == "claude-code":
        if not shutil.which("claude"):
            return {"ok": False, "how": "manual",
                    "hint": f"rode: `claude mcp remove --scope user {MCP_NAME}`"}
        try:
            r = run(["claude", "mcp", "remove", "--scope", "user", MCP_NAME],
                    capture_output=True, text=True, timeout=30)
            return {"ok": r.returncode == 0, "how": "cli", "hint": ""}
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "how": "manual", "hint": str(e)[:200]}

    if agent in ("cursor", "cursor-cli"):
        p = h / ".cursor" / "mcp.json"
        if not p.exists():
            return {"ok": True, "how": "file", "hint": ""}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"ok": False, "how": "manual", "hint": "~/.cursor/mcp.json inválido"}
        except (ValueError, OSError):
            return {"ok": False, "how": "manual", "hint": "~/.cursor/mcp.json inválido"}
        srv = data.get("mcpServers")
        if isinstance(srv, dict) and MCP_NAME in srv:
            srv.pop(MCP_NAME, None)
            util.atomic_write(p, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return {"ok": True, "how": "file", "hint": ""}

    if agent == "codex":
        p = h / ".codex" / "config.toml"
        if not p.exists():
            return {"ok": True, "how": "file", "hint": ""}
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError as e:
            return {"ok": False, "how": "manual", "hint": str(e)[:200]}
        stripped = _strip_marked_block(raw)
        if stripped != raw:
            util.atomic_write(p, stripped)
        return {"ok": True, "how": "file", "hint": ""}

    if agent == HERMES:
        if not shutil.which("hermes"):
            return {"ok": False, "how": "manual",
                    "hint": f"rode: `hermes mcp remove {MCP_NAME}`"}
        try:
            r = run(["hermes", "mcp", "remove", MCP_NAME],
                    capture_output=True, text=True, timeout=30)
            return {"ok": r.returncode == 0, "how": "cli", "hint": ""}
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "how": "manual", "hint": str(e)[:200]}

    return {"ok": False, "how": "manual", "hint": f"agente desconhecido: {agent!r}"}


def detect(home: Path | None = None) -> dict[str, bool]:
    """Harness presente na máquina? (PATH primeiro, diretório como pista)."""
    h = _home(home)
    out = {}
    for name, (bin_, dirname) in _DETECT.items():
        out[name] = bool(shutil.which(bin_)) or (h / dirname).exists()
    return out


def _claude_hook_present(inst) -> bool:
    from . import perms
    inst = _inst(inst)
    if not perms.recall_hook_on(inst):
        return False
    data = perms._read(perms.local_path(inst))
    ups = (data.get("hooks") or {}).get("UserPromptSubmit") or []
    return any(isinstance(e, dict) and perms._is_recall(e) for e in ups)


def connect(brain, agents: list[str] | str | None = None, home: Path | None = None,
            run=subprocess.run, recall: bool = True, mcp: bool = True) -> list[dict]:
    """Registra o canal MCP somente-leitura do cérebro nos agentes (e o hook de recall no Claude Code)."""
    from . import perms
    inst = _inst(brain)
    if not agents:
        agents = [k for k, on in detect(home).items() if on]
    elif isinstance(agents, str):
        agents = [agents]
    results: list[dict] = []
    for a in agents:
        if a not in AGENTS and a not in (HERMES, "cursor"):
            mcp_res = wire_mcp(inst, a, home=home, run=run)
            results.append({"agent": a, "ok": False, "mcp": mcp_res, "hint": mcp_res["hint"]})
            continue
        mcp_res = (wire_mcp(inst, a, home=home, run=run) if mcp
                   else {"ok": False, "how": "off", "hint": "MCP desligado (--no-mcp)"})
        item: dict = {"agent": a, "ok": bool(mcp_res.get("ok")) if mcp else bool(recall), "mcp": mcp_res}
        if a == "claude-code":
            config.set_keys(inst, "memory", {"recall_hook": bool(recall)})
            inst = config.reload(inst)
            if hasattr(brain, "inst"):
                brain.inst = inst
            if hasattr(brain, "reload"):
                brain.reload()
            perms.sync(inst)
            item["recall"] = {
                "ok": bool(recall),
                "hint": ("hook de recall registrado (abra uma sessão nova do Claude)"
                         if recall else "hook de recall desligado (--no-recall)"),
            }
        results.append(item)
    return results


def disconnect(brain, agents: list[str] | str | None = None, home: Path | None = None,
               run=subprocess.run) -> list[dict]:
    """Remove o canal MCP somente-leitura do cérebro dos agentes (e desliga o hook de recall no Claude Code)."""
    from . import perms
    inst = _inst(brain)
    if not agents:
        agents = [k for k, on in detect(home).items() if on]
    elif isinstance(agents, str):
        agents = [agents]
    results: list[dict] = []
    for a in agents:
        mcp_res = unwire_mcp(inst, a, home=home, run=run)
        if a == "claude-code":
            config.set_keys(inst, "memory", {"recall_hook": False})
            inst = config.reload(inst)
            if hasattr(brain, "inst"):
                brain.inst = inst
            if hasattr(brain, "reload"):
                brain.reload()
            perms.try_sync(inst)
        results.append({"agent": a, "ok": bool(mcp_res.get("ok")), "mcp": mcp_res})
    return results


def status(brain, home: Path | None = None) -> dict[str, dict[str, bool]]:
    """Estado do canal MCP somente-leitura do cérebro por agente detectado na máquina."""
    inst = _inst(brain)
    det = detect(home)
    return {
        name: {"detected": bool(is_det), "mcp": mcp_present(inst, name, home=home)}
        for name, is_det in det.items()
    }


def format_connect_lines(results: list[dict] | dict) -> list[str]:
    """Feedback PT-BR por agente para `brain harness connect`."""
    if isinstance(results, dict):
        results = [results]
    lines: list[str] = []
    for r in results:
        a = r["agent"]
        m = r.get("mcp") if isinstance(r.get("mcp"), dict) else r
        if m.get("ok"):
            lines.append(f"✓ {a}: servidor MCP somente-leitura do cérebro registrado ({m.get('how', 'ok')})")
        else:
            lines.append(f"⚠ {a}: servidor MCP não registrado ({m.get('how', 'manual')}) — {m.get('hint', '')}")
        if "recall" in r:
            rec = r["recall"]
            if rec.get("ok"):
                lines.append(f"✓ {a}: {rec['hint']}")
            else:
                lines.append(f"⚠ {a}: {rec['hint']}")
    return lines
