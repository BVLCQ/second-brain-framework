"""Harnesses de código com memória no MESMO servidor do cérebro.

Um serviço, dois mundos:

  brain        ← derivado do vault (embed e full) — `memory rebuild` apaga e recria
  harness_bank ← memória dos agentes (default "hermes", decisão do dono 2026-11-05):
                 conversa/git dos harnesses — NUNCA tocada pelo `memory rebuild`,
                 nunca vira fato do vault.

Claude Code / Cursor CLI / Codex são conectados pelo INSTALADOR OFICIAL
(@vectorize-io/hindsight-coding-agents) em modo self-hosted apontado ao nosso
servidor — o encanamento é do upstream, não nosso. O Hermes ganha config escrita
aqui (~/.hermes/hindsight/config.json + memory.provider); o plugin em si pede
consentimento interativo e fica como receita impressa. Tudo termina em
verificação (recall ping) — perguntar é a prova.
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
INSTALLER = "@vectorize-io/hindsight-coding-agents"
AGENTS = {"claude-code": "Claude Code", "cursor-cli": "Cursor CLI", "codex": "Codex CLI"}
HERMES = "hermes"
MCP_NAME = "brain"
MARK_BEGIN = "# >>> brain: servidor MCP somente-leitura (gerenciado por `brain memory harness`) >>>"
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


def coding_agent_config(home: Path | None = None) -> Path:
    return _home(home) / ".hindsight" / "coding-agent.json"


def hermes_config(home: Path | None = None) -> Path:
    return _home(home) / ".hermes" / "hindsight" / "config.json"


def hermes_yaml(home: Path | None = None) -> Path:
    return _home(home) / ".hermes" / "config.yaml"


def hermes_provider(home: Path | None = None) -> str | None:
    """memory.provider do config.yaml do Hermes, lido por linhas (stdlib, sem subprocess)."""
    p = hermes_yaml(home)
    if not p.exists():
        return None
    in_mem = False
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            in_mem = line.split("#", 1)[0].strip() == "memory:"
            continue
        if in_mem:
            m = re.match(r"\s+provider:\s*[\"']?([\w.-]+)", line)
            if m:
                return m.group(1)
    return None


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


def merge_coding_agent(path: Path, url: str, bank: str) -> dict:
    """Escreve o ~/.hindsight/coding-agent.json do dono: servidor self-hosted, banco
    único de agente com PROVENÂNCIA (tags/metadata por repo/harness — plano §2.4).
    Merge: chaves estranhas do dono são preservadas; remove o `bankId` para voltar
    ao padrão por-repo do upstream (coding-agent::<repo>)."""
    cfg: dict = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            cfg = {}
    cfg.update({"serverMode": "self-hosted", "apiUrl": url, "bankId": bank,
                "retainTags": ["project:{gitProject}", "harness:{harness}"],
                "retainMetadata": {"repo": "{gitProject}"}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg


def _npx_ok() -> bool:
    return bool(shutil.which("npx")) and bool(shutil.which("node"))


def install(brain, agents: list[str], home: Path | None = None,
            run=subprocess.run, recall: bool = True, mcp: bool = True) -> list[dict]:
    """Cabla CLIs de código pelo instalador oficial / wire_hermes + canais do cérebro (MCP + hook de recall).

    Sem node/npm: o instalador oficial não roda (devolve a receita), mas os canais do próprio cérebro ainda são gravados."""
    from . import perms
    url = brain.inst.cfg["memory"]["url"]
    results = []
    npx = _npx_ok()
    for a in agents:
        if a == HERMES:
            wh = wire_hermes(brain, home=home, run=run)
            results.append({"agent": HERMES, **wh})
            continue
        if a not in AGENTS:
            results.append({"agent": a, "ok": False, "hint": f"harness desconhecido: {a!r}"})
            continue
        if not npx:
            results.append({"agent": a, "ok": False,
                            "hint": f"node/npm ausentes — rode depois: npx -y {INSTALLER} install {a} "
                                    f"--server self-hosted --api-url {url}"})
            continue
        try:
            r = run(["npx", "-y", INSTALLER, "install", a, "--server", "self-hosted",
                     "--api-url", url], capture_output=True, text=True, timeout=300, cwd=str(_home(home)))
            ok = r.returncode == 0
            results.append({"agent": a, "ok": ok,
                            "hint": "" if ok else (r.stderr or r.stdout or "falhou")[:300]})
        except (OSError, subprocess.TimeoutExpired) as e:
            results.append({"agent": a, "ok": False, "hint": str(e)[:300]})
    done_coding = {r["agent"] for r in results if r["agent"] in AGENTS and r["ok"]}
    if done_coding:
        bank = brain.inst.cfg["memory"]["harness_bank"]
        merge_coding_agent(coding_agent_config(home), url, bank)
        mem = brain.inst.cfg["memory"]
        config.set_keys(brain.inst, "memory", {"harnesses": sorted(set(mem.get("harnesses") or []) | done_coding)})
        brain.inst = config.load(brain.inst.root)     # reload() não relê config (pitfall do setup)
        brain.reload()
    for r in results:
        a = r["agent"]
        if a not in AGENTS and a != HERMES:
            continue
        if mcp:
            r["mcp"] = wire_mcp(brain.inst, a, home=home, run=run)
        if a == "claude-code":
            config.set_keys(brain.inst, "memory", {"recall_hook": bool(recall)})
            brain.inst = config.load(brain.inst.root)
            brain.reload()
            perms.try_sync(brain.inst)
            r["recall"] = {"ok": bool(recall),
                           "hint": ("hook de recall registrado (abra uma sessão nova do Claude)"
                                    if recall else "hook de recall desligado (--no-recall)")}
    return results


def remove(brain, agents: list[str] | str, home: Path | None = None,
           run=subprocess.run) -> list[dict]:
    """Desconecta harnesses: remove o canal MCP, tira de [memory].harnesses e devolve recall_hook a 'auto'."""
    from . import perms
    if isinstance(agents, str):
        agents = [agents]
    results = []
    for a in agents:
        mcp_res = unwire_mcp(brain.inst, a, home=home, run=run)
        cur_list = list(brain.inst.cfg["memory"].get("harnesses") or [])
        drop = {a, "cursor-cli"} if a == "cursor" else {a}
        updates: dict = {"harnesses": [h for h in cur_list if h not in drop]}
        if a == "claude-code":
            updates["recall_hook"] = "auto"
        config.set_keys(brain.inst, "memory", updates)
        brain.inst = config.load(brain.inst.root)
        brain.reload()
        if a == "claude-code":
            perms.try_sync(brain.inst)
        results.append({"agent": a, "ok": True, "mcp": mcp_res})
    return results


def format_install_lines(r: dict, mem: dict) -> list[str]:
    """Linhas de feedback por canal para CLI (`brain memory harness install`) e wizard (`setup._harness_step`)."""
    a = r["agent"]
    lines: list[str] = []
    if a == HERMES:
        if r.get("config"):
            lines.append(f"✓ config do Hermes: {r['config']} (local_external → {mem['url']}, banco {mem['harness_bank']})")
        if r["ok"]:
            lines.append("✓ hermes: memory.provider hindsight gravado")
        else:
            lines.append(f"✗ hermes: {r.get('hint') or 'rode: hermes config set memory.provider hindsight'}")
        if r.get("plugin_recipe"):
            lines.append("⚠ plugin do Hindsight ausente — rode você mesmo (pede confirmação interativa): "
                         "hermes plugins install hindsight — vale na PRÓXIMA sessão do Hermes")
    else:
        label = AGENTS.get(a, a)
        if r["ok"]:
            lines.append(f"✓ {label} conectado (instalador oficial → {mem['url']}, banco {mem['harness_bank']})")
        else:
            lines.append(f"✗ {a}: {r.get('hint', 'falhou')}")
    if "recall" in r:
        rec = r["recall"]
        if rec.get("ok"):
            lines.append(f"✓ {a}: {rec['hint']}")
        else:
            lines.append(f"⚠ {a}: {rec['hint']}")
    if "mcp" in r:
        m = r["mcp"]
        if m.get("ok"):
            lines.append(f"✓ {a}: servidor MCP somente-leitura do cérebro registrado ({m.get('how', 'ok')})")
        else:
            lines.append(f"⚠ {a}: servidor MCP não registrado ({m.get('how', 'manual')}) — {m.get('hint', '')}")
    return lines


def wire_hermes(brain, home: Path | None = None,
                run=subprocess.run, which=None) -> dict:
    """Hermes aponta para o servidor do cérebro: config local_external + memory.provider.
    O PLUGIN em si pede consentimento interativo (TTY) — nada automatiza; a receita
    volta no resultado para o dono rodar. Ativação vale na PRÓXIMA sessão do Hermes."""
    which = which or shutil.which
    mem = brain.inst.cfg["memory"]
    url, bank = mem["url"], mem["harness_bank"]
    p = hermes_config(home)
    cfg: dict = {}
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8")) or {}
        except (ValueError, OSError):
            cfg = {}
    cfg.update({"mode": "local_external", "api_url": url, "bank_id": bank})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out: dict = {"config": str(p), "cli": False, "plugin_recipe": False}
    has_cli = bool(which("hermes"))
    if has_cli:
        try:
            r = run(["hermes", "config", "set", "memory.provider", "hindsight"],
                    capture_output=True, text=True, timeout=60)
            out["cli"] = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            out["cli"] = False
        # plugin: o consentimento de dependências exige TTY de verdade — só detectamos
        try:
            r = run(["hermes", "memory", "status"], capture_output=True, text=True, timeout=60)
            if "not installed" in (r.stdout or "").lower():
                out["plugin_recipe"] = True
        except (OSError, subprocess.TimeoutExpired):
            pass
    ok = bool(out["cli"]) or hermes_provider(home) == "hindsight"
    out["ok"] = ok
    if ok:
        out["hint"] = ""
        config.set_keys(brain.inst, "memory", {"harnesses": sorted(set(mem.get("harnesses") or []) | {HERMES})})
        brain.inst = config.load(brain.inst.root)         # reload() não relê config (pitfall do setup)
        brain.reload()
    elif not has_cli:
        out["hint"] = ("CLI do Hermes não encontrada no PATH — instale o Hermes e rode de novo "
                       "`brain memory harness install hermes` (`hermes config set memory.provider hindsight`)")
    else:
        out["hint"] = ("memory.provider não ficou em hindsight — rode "
                       "`hermes config set memory.provider hindsight` e depois `brain memory harness install hermes`")
    return out


def ping(hs, bank: str) -> bool:
    """Recall ping: pergunta qualquer coisa no banco — 200 é a prova (resposta vazia vale)."""
    try:
        hs.recall(bank, "verificação do brain: qualquer memória?")
        return True
    except util.BrainError:
        return False


def _claude_hook_present(inst) -> bool:
    from . import perms
    if not perms.recall_hook_on(inst):
        return False
    data = perms._read(perms.local_path(inst))
    ups = (data.get("hooks") or {}).get("UserPromptSubmit") or []
    return any(isinstance(e, dict) and perms._is_recall(e) for e in ups)


def verify(brain, hs, home: Path | None = None, online: bool = False,
           run=subprocess.run) -> dict:
    """Estado da conexão: banco existe? ping responde? configs e canais apontam pra cá?"""
    mem = brain.inst.cfg["memory"]
    bank = mem["harness_bank"]
    harnesses = list(mem.get("harnesses") or [])
    channels: dict[str, dict[str, bool]] = {}
    for name in harnesses:
        if name == "claude-code":
            channels[name] = {
                "hook": _claude_hook_present(brain.inst),
                "mcp": mcp_present(brain.inst, "claude-code", home=home),
            }
        elif name == HERMES:
            ch = {
                "provider": hermes_provider(home) == "hindsight",
                "mcp": mcp_present(brain.inst, HERMES, home=home),
            }
            if online and shutil.which("hermes"):
                plug_ok = False
                try:
                    r = run(["hermes", "memory", "status"],
                            capture_output=True, text=True, timeout=10)
                    out_txt = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
                    plug_ok = r.returncode == 0 and "hindsight" in out_txt and "not installed" not in out_txt
                except (OSError, subprocess.TimeoutExpired):
                    plug_ok = False
                ch["plugin"] = plug_ok
            channels[name] = ch
        else:
            channels[name] = {"mcp": mcp_present(brain.inst, name, home=home)}
    out: dict = {"bank": bank, "bank_exists": False, "ping": False, "hermes_config": False,
                 "coding_agent": False, "harnesses": harnesses, "channels": channels}
    p = hermes_config(home)
    if p.exists():
        try:
            out["hermes_config"] = json.loads(p.read_text(encoding="utf-8")).get("api_url") == mem["url"]
        except (ValueError, OSError):
            pass
    p = coding_agent_config(home)
    if p.exists():
        try:
            out["coding_agent"] = json.loads(p.read_text(encoding="utf-8")).get("apiUrl") == mem["url"]
        except (ValueError, OSError):
            pass
    try:
        ids = {b.get("bank_id") for b in hs.banks().get("banks", [])}
        out["bank_exists"] = bank in ids
    except util.BrainError:
        return out
    out["ping"] = out["bank_exists"] and ping(hs, bank)   # banco ausente: nem pergunta
    return out
