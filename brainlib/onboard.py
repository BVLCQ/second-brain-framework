"""Onboarding no navegador: o app Brain abre aqui enquanto a instância não está configurada.

Servido pela ponte local (`brain serve`, rota `/onboarding`), com as mesmas travas dela (só 127.0.0.1, Origin do
próprio painel, token). Cada passo é uma ação pequena e determinística deste módulo — nada passa pela allowlist de
comandos da ponte, e nenhum segredo vai para o log:

* **Você** — nome completo, apelido, cargo, e-mail → `person.added` (`[declarado]`, `by owner`). O id interno sai do
  nome enquanto o dono ainda não tem ficha (instância de uma pessoa só: ninguém escolhe id).
* **Sobre você** — o texto vira o `PROFILE/profile.md`, mostrado como prévia antes de gravar (o clique é a aprovação).
* **Rotina** — fuso e expediente (`[owner]`, `[work]`).
* **Conectores** — o estado vem do `claude mcp list` (rodado em segundo plano, só nome → status); ligar um conector
  libera as ferramentas de LEITURA dele em `[runner].allow` e cria as fontes simples no `watch.toml`. Escrita no mundo
  exterior continua só pelas portas.
* **Permissões** — `.claude/settings.local.json` (`perms.sync`), para o agente não pedir licença a cada comando.
* **Memória** — nenhuma · embed (na API, `lite`: local, nada sai da máquina) · full (com a sua API key). A chave vai direto para o
  `config/.env` (0600) e nunca volta para o navegador; o modo full exige o aceite explícito do envio de texto.
* **Chaves** — só os nomes de `KEY_NAMES`; a resposta diz apenas se cada uma está definida.
* **Goals e projetos** — texto e documentos entram na `RAW/inbox/` (porta única); o agente *propõe* a árvore; o dono
  revisa e aprova no navegador, e só então os goals/projetos nascem pelo mesmo caminho com gate do `brain plan`.

O progresso fica em `logs/onboarding.json` (estado de interface, não verdade: a verdade é o ledger, a config e o vault).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import config, util

STEPS = ("voce", "sobre", "rotina", "conectores", "permissoes", "memoria", "chaves", "planejamento", "pronto")
PROFILE_TEMPLATE_MARK = "(a preencher no /init)"
KEY_NAMES = {
    "GITHUB_TOKEN": "Token do GitHub (sugestões e bugs do Brain viram issues)",
}
UPLOAD_MAX = 25 * 1024 * 1024
UPLOAD_EXT = {".pdf", ".md", ".txt", ".docx", ".doc", ".pptx", ".xlsx", ".csv", ".json", ".html", ".rtf", ".odt",
              ".png", ".jpg", ".jpeg"}

# Conectores do claude.ai que o Brain sabe ler. `match` casa com o nome que o `claude mcp list` mostra
# ("claude.ai Slack"); `tools` = só LEITURA. O prefixo das regras é o que o Claude Code usa para conectores
# do claude.ai: mcp__claude_ai_<Nome>__<ferramenta>.
CONNECTORS: dict[str, dict] = {
    "slack": {"label": "Slack", "server": "Slack", "match": ("slack",),
              "what": "mensagens e threads dos canais que você escolher",
              "tools": ("slack_read_channel", "slack_read_thread", "slack_read_canvas", "slack_read_file",
                        "slack_read_user_profile", "slack_search_channels", "slack_search_public",
                        "slack_search_public_and_private", "slack_search_users")},
    "gmail": {"label": "Gmail", "server": "Gmail", "match": ("gmail",),
              "what": "um resumo diário da sua caixa de entrada",
              "tools": ("search_threads", "get_thread", "get_message")},
    "calendar": {"label": "Google Calendar", "server": "Google Calendar", "match": ("google calendar", "calendar"),
                 "what": "sua agenda — o Brain planeja blocos de foco em volta das reuniões",
                 "tools": ("list_events", "get_event", "search_events", "list_calendars")},
    "drive": {"label": "Google Drive", "server": "Google Drive", "match": ("google drive", "drive"),
              "what": "documentos de uma pasta que você escolher",
              "tools": ("search_files", "read_file_content", "get_file_metadata", "list_recent_files",
                        "download_file_content")},
    "granola": {"label": "Granola", "server": "Granola", "match": ("granola",),
                "what": "notas e transcrições das suas reuniões",
                "tools": ("list_meetings", "get_meetings", "search_meetings", "get_meeting_transcript",
                          "search_transcripts", "list_meeting_folders", "get_meeting_attachment",
                          "get_account_info")},
    "jira": {"label": "Jira (Atlassian)", "server": "Atlassian", "match": ("atlassian", "jira"),
             "what": "os cards atribuídos a você",
             "tools": ("searchJiraIssuesUsingJql", "getJiraIssue", "getAccessibleAtlassianResources",
                       "lookupJiraAccountId")},
}
# fontes simples, sem parâmetro do dono (as que precisam de canal/pasta usam os campos do passo)
DEFAULT_SOURCES = {
    "gmail": ("gmail-hoje", {"kind": "gmail", "window": "1d", "note": "digest do dia"}),
    "calendar": ("gcal-agenda", {"kind": "gcal", "window": "14d", "note": "agenda — alimenta o planejador de foco"}),
    "granola": ("granola-reunioes", {"kind": "granola", "window": "auto", "note": "notas e transcrições"}),
}


def rule_prefix(server: str) -> str:
    return "mcp__claude_ai_" + re.sub(r"[^A-Za-z0-9]", "_", server) + "__"


# ── progresso (estado de interface) ──────────────────────────────────────────
def _progress_file(inst) -> Path:
    return inst.logs / "onboarding.json"


def progress(inst) -> dict:
    try:
        data = json.loads(_progress_file(inst).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_progress(inst, **changes) -> dict:
    data = progress(inst)
    data.update(changes)
    inst.logs.mkdir(parents=True, exist_ok=True)
    util.atomic_write(_progress_file(inst), json.dumps(data, ensure_ascii=False, indent=2))
    return data


def _mark(inst, step: str) -> None:
    done = list(dict.fromkeys([*progress(inst).get("done", []), step]))
    _save_progress(inst, done=done)


def profile_is_template(inst) -> bool:
    p = inst.vault / "PROFILE" / "profile.md"
    try:
        return PROFILE_TEMPLATE_MARK in p.read_text(encoding="utf-8")
    except OSError:
        return True


def needed(brain) -> bool:
    """O app abre o onboarding (e não o painel)? Sim enquanto ele não foi concluído e a instância ainda não tem
    dono ou perfil — ou quando o dono começou e parou no meio. Instância antiga já configurada à mão: não."""
    pg = progress(brain.inst)
    if pg.get("finished"):
        return False
    if brain.owner not in brain.state.people or profile_is_template(brain.inst):
        return True
    # começou numa instância ainda sem dono/perfil e parou no meio: o clique retoma. Quem já tinha o Brain
    # configurado e só reabriu a configuração (`brain open --setup`) não fica preso nela.
    return bool(pg.get("done")) and bool(pg.get("started_unconfigured"))


# ── jobs em segundo plano (claude mcp list, memória, proposta do agente) ─────
class _Job:
    def __init__(self, kind: str):
        self.id = secrets.token_hex(6)
        self.kind = kind
        self.status = "running"
        self.log: list[str] = []
        self.result: dict | None = None
        self.started = time.time()

    def say(self, line: str) -> None:
        for ln in str(line).splitlines():
            if ln.strip():
                self.log.append(ln.rstrip())
        del self.log[:-200]

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "log": self.log[-60:],
                "result": self.result, "elapsed": round(time.time() - self.started)}


_JOBS: dict[str, _Job] = {}
_JOBS_LOCK = threading.Lock()
_MCP_CACHE: dict = {"at": 0.0, "servers": None, "job": None}


def _start(kind: str, fn) -> _Job:
    job = _Job(kind)
    with _JOBS_LOCK:
        for old in [k for k, j in _JOBS.items() if time.time() - j.started > 3600]:
            _JOBS.pop(old, None)
        _JOBS[job.id] = job

    def run():
        try:
            job.result = fn(job) or {}
            job.status = "done"
        except util.BrainError as e:
            job.say(f"✗ {e}")
            job.result = {"error": str(e)}
            job.status = "error"
        except Exception as e:  # noqa: BLE001 — o job relata, a ponte segue
            job.say(f"✗ erro inesperado: {e!r}")
            job.result = {"error": "erro inesperado — detalhe no log da ponte"}
            job.status = "error"
    threading.Thread(target=run, daemon=True, name=f"onboard-{kind}").start()
    return job


def job(job_id: str) -> dict | None:
    j = _JOBS.get(job_id)
    return j.as_dict() if j else None


# ── leitura do estado ────────────────────────────────────────────────────────
def _agent_name(cfg) -> str | None:
    from .tui import bridge
    return bridge._agent_name(cfg)


def parse_mcp_list(text: str) -> dict[str, str]:
    """`claude mcp list` → {nome: connected|auth|error}. URLs e o resto da linha ficam de fora."""
    out: dict[str, str] = {}
    for ln in text.splitlines():
        m = re.match(r"^(.+?):\s.*-\s*(✔|✓|!|✗|✘|×)\s*(.*)$", ln.strip())
        if not m:
            continue
        name, mark, rest = m.group(1).strip(), m.group(2), m.group(3).lower()
        out[name] = "connected" if mark in "✔✓" else ("auth" if "auth" in rest else "error")
    return out


def scan_connectors(force: bool = False) -> dict:
    """Dispara (ou reaproveita) o `claude mcp list` em segundo plano — leva 30–60 s. Nunca segura a trava da ponte."""
    if _MCP_CACHE["job"] and _JOBS.get(_MCP_CACHE["job"]) and _JOBS[_MCP_CACHE["job"]].status == "running":
        return {"job": _MCP_CACHE["job"]}
    if not force and _MCP_CACHE["servers"] is not None and time.time() - _MCP_CACHE["at"] < 600:
        return {"servers": _MCP_CACHE["servers"]}

    def run(j: _Job) -> dict:
        claude = shutil.which("claude")
        if not claude:
            raise util.BrainError("o Claude Code (comando `claude`) não está instalado nesta máquina")
        j.say("verificando os conectores do Claude…")
        p = subprocess.run([claude, "mcp", "list"], capture_output=True, text=True, timeout=180,
                           stdin=subprocess.DEVNULL)
        servers = parse_mcp_list(p.stdout + "\n" + p.stderr)
        _MCP_CACHE.update(at=time.time(), servers=servers)
        j.say(f"✓ {len(servers)} conectores encontrados")
        return {"servers": servers}
    j = _start("connectors", run)
    _MCP_CACHE["job"] = j.id
    return {"job": j.id}


def connector_status(servers: dict[str, str] | None, cfg: dict) -> list[dict]:
    allow = set(cfg["runner"].get("allow", []))
    out = []
    for key, c in CONNECTORS.items():
        status = "unknown"
        if servers is not None:
            status = "missing"
            for name, st in servers.items():
                low = name.lower().removeprefix("claude.ai").strip()
                if any(low == mm or low.startswith(mm) for mm in c["match"]):
                    status = st if st != "error" or status == "missing" else status
                    if st == "connected":
                        break
        prefix = rule_prefix(c["server"])
        out.append({"key": key, "label": c["label"], "what": c["what"], "status": status,
                    "enabled": any(r.startswith(prefix) for r in allow)})
    return out


_PREREQ: dict = {"at": 0.0, "value": None}


def _prereqs() -> dict:
    """Docker/OrbStack e LM Studio no ar? (até 13 s de checagem — guardado por 60 s, o painel consulta toda hora)."""
    from . import setup
    if _PREREQ["value"] is None or time.time() - _PREREQ["at"] > 60:
        _PREREQ.update(at=time.time(), value={"docker": setup.docker_available(), "lmstudio": setup.lmstudio_up()})
    return _PREREQ["value"]


def state(brain) -> dict:
    from . import memory, perms, setup
    inst, cfg = brain.inst, brain.inst.cfg
    person = brain.state.people.get(brain.owner)
    env = config.load_env(inst)
    mem_mode = memory.mode(cfg["memory"])
    try:
        perm = perms.status(inst)
    except Exception:  # noqa: BLE001
        perm = {"static": "missing", "local": "missing"}
    pre = _prereqs()
    plan_goals = len(brain.plan.goals) if getattr(brain, "plan", None) else 0
    st = {
        "owner": {"id": brain.owner, "registered": person is not None,
                  "name": person.name if person else ("" if cfg["owner"]["name"] == "Dono do cérebro"
                                                      else cfg["owner"]["name"]),
                  "nickname": (person.aliases[0] if person and person.aliases else ""),
                  "role": person.role if person else "", "email": person.email if person else "",
                  "suggested_name": setup._system_full_name()},
        "profile": {"template": profile_is_template(inst),
                    "text": (inst.vault / "PROFILE" / "profile.md").read_text(encoding="utf-8")
                    if (inst.vault / "PROFILE" / "profile.md").exists() else ""},
        "routine": {"timezone": cfg["timezone"], "start": cfg["work"]["start"], "end": cfg["work"]["end"],
                    "lunch": cfg["work"].get("lunch", "")},
        "agent": _agent_name(cfg),
        "claude_installed": bool(shutil.which("claude")),
        "connectors": connector_status(_MCP_CACHE["servers"], cfg),
        "connectors_scanned": _MCP_CACHE["servers"] is not None,
        "permissions": {"ok": perm.get("local") == "ok", "static": perm.get("static")},
        "memory": {"mode": {"embed": "lite"}.get(mem_mode, mem_mode),
                   "docker": pre["docker"], "lmstudio": pre["lmstudio"],
                   "llm_key": bool(env.get("HINDSIGHT_API_LLM_API_KEY")),
                   "llm_provider": cfg["memory"].get("llm_provider", "")},
        "keys": {k: {"label": v, "set": bool(env.get(k))} for k, v in KEY_NAMES.items()},
        "planning": {"goals": plan_goals, "proposal": progress(inst).get("proposal")},
        "inbox": sum(1 for p in inst.inbox.iterdir() if p.is_file() and p.name != ".keep.md")
        if inst.inbox.exists() else 0,
        "progress": progress(inst),
        "steps": list(STEPS),
        "needed": needed(brain),
    }
    st["setup"] = setup_status(st)
    return st


def setup_status(st: dict) -> dict:
    """Cada aba da face Configurações: `feito` vem do estado real, não da lista de passos vistos — pular um
    passo marca o passo como visto (`skip`), e isso não pode aparecer como feito na Visão geral."""
    return {
        "perfil": st["owner"]["registered"] and not st["profile"]["template"],
        "rotina": bool(st["routine"]["timezone"] and st["routine"]["start"] and st["routine"]["end"]),
        "conectores": any(c.get("enabled") for c in st["connectors"]),
        "memoria": st["memory"]["mode"] != "none",
        "integracoes": any(k["set"] for k in st["keys"].values()),
    }


# ── passos ───────────────────────────────────────────────────────────────────
def _text(v, limit: int = 4000) -> str:
    return str(v or "").strip()[:limit]


def save_about(brain, data: dict) -> dict:
    name, nick = _text(data.get("name"), 120), _text(data.get("nickname"), 60)
    role, email = _text(data.get("role"), 120), _text(data.get("email"), 160)
    if not name:
        raise util.BrainError("o nome completo é obrigatório", code=4)
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise util.BrainError("e-mail inválido", code=4)
    inst = brain.inst
    if brain.owner not in brain.state.people:
        # ainda sem ficha: o id nasce do nome (o placeholder "eu" do template, ou um id antigo sem eventos)
        owner_id = util.owner_slug(name)
        config.set_keys(inst, "owner", {"id": owner_id, "name": name})
        brain.inst = config.reload(inst)
        brain.reload()
        brain.record_one({"type": "person.added", "id": brain.owner, "by": "owner", "prov": "declarado",
                          "source": "chat",
                          "data": {"name": name, "aliases": [nick] if nick else [], "role": role,
                                   "email": email, "relation": "dono do cérebro"}})
    else:
        person = brain.state.people[brain.owner]
        config.set_keys(inst, "owner", {"name": name})
        brain.inst = config.reload(inst)
        brain.reload()
        brain.record_one({"type": "person.updated", "id": brain.owner, "by": "owner", "prov": "declarado",
                          "source": "chat", "data": {"name": name, "role": role, "email": email}})
        if nick and nick.lower() not in {a.lower() for a in person.aliases}:
            brain.record_one({"type": "person.updated", "id": brain.owner, "by": "owner", "prov": "declarado",
                              "source": "chat", "data": {"aliases_add": [nick]}})
    _mark(brain.inst, "voce")
    return {"id": brain.owner}


def profile_markdown(brain, data: dict) -> str:
    """O PROFILE a partir do que o dono escreveu — mesmas seções do template, conteúdo dele."""
    person = brain.state.people.get(brain.owner)
    name = person.name if person else brain.inst.cfg["owner"]["name"]
    role = (person.role if person else "") or "—"
    nick = person.aliases[0] if person and person.aliases else ""
    about, how, focus = _text(data.get("about")), _text(data.get("how")), _text(data.get("focus"))
    lines = ["# PROFILE", "",
             "_Quem é o dono, como opera, o que importa. Curado — o agente propõe diffs;",
             "só aplica depois de aprovação explícita._", "",
             "## Papel", "", f"{name}" + (f" ({nick})" if nick else "") + f" — {role}.", ""]
    if about:
        lines += ["## Sobre mim", "", about, ""]
    lines += ["## Como opera", "", how or "(a completar)", "",
              "## O que importa agora", "", focus or "(a completar)", ""]
    return "\n".join(lines)


def save_profile(brain, data: dict) -> dict:
    text = str(data.get("markdown") or "")
    if not text.strip().startswith("# PROFILE") or len(text) > 60000:
        raise util.BrainError("perfil inválido — gere a prévia de novo", code=4)
    if not profile_is_template(brain.inst) and not data.get("overwrite"):
        raise util.BrainError("já existe um perfil escrito — confirme para substituir", code=4)
    path = brain.inst.vault / "PROFILE" / "profile.md"
    util.atomic_write(path, text if text.endswith("\n") else text + "\n")
    _mark(brain.inst, "sobre")
    return {"path": brain.inst.rel(path)}


def save_routine(brain, data: dict) -> dict:
    from zoneinfo import ZoneInfo
    tz = _text(data.get("timezone"), 64)
    start, end, lunch = _text(data.get("start"), 5), _text(data.get("end"), 5), _text(data.get("lunch"), 11)
    try:
        ZoneInfo(tz)
    except Exception as e:  # noqa: BLE001
        raise util.BrainError(f"fuso desconhecido: {tz}", code=4) from e
    hhmm = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    if not (hhmm.match(start) and hhmm.match(end)) or start >= end:
        raise util.BrainError("expediente inválido — use HH:MM, com o início antes do fim", code=4)
    if lunch and not re.match(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$", lunch):
        raise util.BrainError("almoço inválido — use HH:MM-HH:MM, ou deixe vazio", code=4)
    config.set_keys(brain.inst, "owner", {"timezone": tz})
    config.set_keys(brain.inst, "work", {"start": start, "end": end, "lunch": lunch})
    brain.inst = config.reload(brain.inst)
    brain.reload()
    _mark(brain.inst, "rotina")
    return {}


def enable_connectors(brain, data: dict) -> dict:
    from . import watch
    from . import perms
    keys = [k for k in data.get("connectors") or [] if k in CONNECTORS]
    off = [k for k in CONNECTORS if k not in keys]               # desligado na tela = o Brain deixa de ler
    off_prefixes = tuple(rule_prefix(CONNECTORS[k]["server"]) for k in off)
    allow = [r for r in brain.inst.cfg["runner"].get("allow", []) if not r.startswith(off_prefixes)]
    for key in keys:
        prefix = rule_prefix(CONNECTORS[key]["server"])
        for tool in CONNECTORS[key]["tools"]:
            if prefix + tool not in allow:
                allow.append(prefix + tool)
    config.set_keys(brain.inst, "runner", {"allow": allow})
    have = {s.get("key") for s in watch.list_sources(brain.inst)}
    removed = []
    for key in off:                                             # só as fontes simples que este passo cria
        if key in DEFAULT_SOURCES and DEFAULT_SOURCES[key][0] in have:
            watch.remove(brain.inst, DEFAULT_SOURCES[key][0])
            removed.append(DEFAULT_SOURCES[key][0])
    have -= set(removed)
    added = []
    for key in keys:
        if key in DEFAULT_SOURCES and DEFAULT_SOURCES[key][0] not in have:
            watch.add(brain.inst, *DEFAULT_SOURCES[key])
            added.append(DEFAULT_SOURCES[key][0])
    if "slack" in keys:
        for ch in [c.strip() for c in _text(data.get("slack_channels"), 600).split(",") if c.strip()][:12]:
            ch = "#" + ch.lstrip("#")
            skey = "slack-" + util.slugify(ch, 40)
            if skey not in have and re.match(r"^#[\w.-]{1,80}$", ch):
                watch.add(brain.inst, skey, {"kind": "slack", "channel": ch, "window": "1d"})
                added.append(skey)
    folder = _text(data.get("drive_folder"), 200)
    if "drive" in keys and folder:
        m = re.search(r"folders/([A-Za-z0-9_-]{10,})", folder)
        fid = m.group(1) if m else folder
        if re.match(r"^[A-Za-z0-9_-]{10,}$", fid) and "drive-pasta" not in have:
            watch.add(brain.inst, "drive-pasta", {"kind": "drive", "folder": fid, "window": "1d"})
            added.append("drive-pasta")
    brain.inst = config.reload(brain.inst)
    brain.reload()
    perms.try_sync(brain.inst)                                  # a sessão interativa enxerga a lista nova
    _mark(brain.inst, "conectores")
    return {"enabled": keys, "sources": added, "removed": removed}


def apply_permissions(brain) -> dict:
    from . import perms
    res = perms.sync(brain.inst)
    _mark(brain.inst, "permissoes")
    return {"ok": True, "detail": {k: v for k, v in (res or {}).items() if isinstance(v, (str, int, bool, list))}}


def save_keys(brain, data: dict) -> dict:
    from . import setup
    updates = {k: str(v).strip() for k, v in (data or {}).items() if k in KEY_NAMES and str(v or "").strip()}
    for k, v in updates.items():
        if len(v) > 400 or any(ch.isspace() for ch in v):
            raise util.BrainError(f"{k}: valor inválido", code=4)
    if updates:
        setup.set_env(brain.inst, updates)
    _mark(brain.inst, "chaves")
    env = config.load_env(brain.inst)
    return {"keys": {k: bool(env.get(k)) for k in KEY_NAMES}}


class _WebUI:
    """Responde às perguntas do passo `memoria` do wizard com o que o dono escolheu no navegador."""
    interactive = False

    def __init__(self, job_: _Job, choices: dict[str, str], key: str, consent: bool):
        self.job, self.choices, self.key, self.consent = job_, choices, key, consent

    def say(self, msg: str) -> None:
        self.job.say(msg)

    def ask(self, prompt: str, default: str = "") -> str:
        if prompt.startswith("Modo full"):
            return "ok" if self.consent else ""
        return default

    def choice(self, prompt: str, options: list[str], default: str) -> str:
        for slot in ("LLM", "embeddings", "reranker"):
            if slot in prompt and self.choices.get(slot) in options:
                return self.choices[slot]
        return default

    def confirm(self, prompt: str, default: bool = False) -> bool:
        return default

    def secret(self, prompt: str) -> str:
        if not self.key:
            raise util.BrainError("falta a API key — cole a chave ou escolha \"fazer depois\"", code=4)
        return self.key


def apply_memory(brain, data: dict) -> dict:
    from . import memory, setup
    mode = {"lite": "embed"}.get(str(data.get("mode")), str(data.get("mode")))
    if mode not in ("none", "embed", "full"):
        raise util.BrainError("modo de memória inválido", code=4)
    if data.get("later"):                               # "fazer depois": guarda a intenção, não liga nada
        _save_progress(brain.inst, memory_later={"embed": "lite"}.get(mode, mode))
        return {"later": True}
    if mode == "full" and not data.get("consent"):
        raise util.BrainError("o modo full precisa do seu aceite: o texto do vault vai para a API com a sua chave",
                              code=4)
    provider = str(data.get("provider") or "anthropic")
    if provider not in ("anthropic", "openai"):
        raise util.BrainError("provedor de LLM inválido", code=4)
    key = str(data.get("key") or "").strip()
    if key and (len(key) > 400 or any(ch.isspace() for ch in key)):
        raise util.BrainError("API key inválida", code=4)
    if mode == "none":
        memory._apply_mode(brain, "none")
        _mark(brain.inst, "memoria")
        return {"mode": "none"}
    inst0 = brain.inst

    def run(j: _Job) -> dict:
        from .core import Brain
        b = Brain(config.reload(inst0))
        emb = "local"
        if mode == "full" and provider == "openai" and not setup.lmstudio_up():
            emb = "openai"
        ui = _WebUI(j, {"LLM": provider, "embeddings": emb, "reranker": "off"}, key, bool(data.get("consent")))
        if emb == "openai" and key:
            setup.set_env(b.inst, {"HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY": key})
        setup._run_memoria(b, ui, mode_hint=mode)
        final = memory.mode(config.reload(inst0).cfg["memory"])
        if final == "none":
            raise util.BrainError("a memória não ligou — veja o que faltou acima")
        _mark(b.inst, "memoria")
        return {"mode": {"embed": "lite"}.get(final, final)}
    return {"job": _start("memory", run).id}


# ── goals e projetos ─────────────────────────────────────────────────────────
def save_planning_note(brain, data: dict) -> dict:
    from . import notes
    text = _text(data.get("text"), 20000)
    if not text:
        raise util.BrainError("escreva algo sobre seus objetivos (ou envie um documento)", code=4)
    path = notes.create(brain, "Objetivos, projetos e contexto (onboarding)\n\n" + text)
    pg = progress(brain.inst)
    _save_progress(brain.inst, planning_sources=list(dict.fromkeys([*pg.get("planning_sources", []),
                                                                     brain.inst.rel(path)])))
    return {"path": brain.inst.rel(path)}


def _safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    stem, ext = os.path.splitext(base)
    if ext.lower() not in UPLOAD_EXT:
        raise util.BrainError(f"tipo de arquivo não aceito ({ext or 'sem extensão'})", code=4)
    stem = re.sub(r"[^\w.-]+", "-", util.fold(stem)).strip("-.")[:80] or "documento"
    return f"{stem}{ext.lower()}"


def save_upload(brain, filename: str, body: bytes) -> dict:
    if not body:
        raise util.BrainError("arquivo vazio", code=4)
    if len(body) > UPLOAD_MAX:
        raise util.BrainError("arquivo grande demais (máximo 25 MB)", code=4)
    inbox = brain.inst.inbox
    inbox.mkdir(parents=True, exist_ok=True)
    name = _safe_filename(filename)
    target = inbox / name
    n = 2
    while target.exists():
        stem, ext = os.path.splitext(name)
        target = inbox / f"{stem}-{n}{ext}"
        n += 1
    if target.resolve().parent != inbox.resolve():
        raise util.BrainError("nome de arquivo inválido", code=4)
    target.write_bytes(body)
    pg = progress(brain.inst)
    _save_progress(brain.inst, planning_sources=list(dict.fromkeys([*pg.get("planning_sources", []),
                                                                     brain.inst.rel(target)])))
    return {"path": brain.inst.rel(target), "name": target.name, "size": len(body)}


PROPOSAL_PROMPT = """Você está ajudando a montar o planejamento inicial do Brain do dono (onboarding).
Leia SOMENTE estes arquivos (relativos a {root}): {files}
Com base neles, proponha a árvore de objetivos do dono: goals (objetivos maiores, com horizonte se houver data),
projetos dentro de cada goal e entregáveis de cada projeto (com prazo AAAA-MM-DD quando o texto disser).
Não invente o que não está escrito: campo sem informação fica "" (vazio) — nunca escreva "não consta".
Não rode ./brain, não edite nenhum arquivo, não use ferramentas MCP.
Responda APENAS com um bloco ```json contendo exatamente:
{{"goals": [{{"title": "...", "horizon": "AAAA-MM-DD ou vazio", "why": "o que isto destrava",
  "projects": [{{"title": "...", "deliverables": [{{"title": "...", "due": "AAAA-MM-DD ou vazio"}}]}}]}}],
 "summary": "duas frases, falando diretamente com a pessoa (\"você quer…\"), sobre o que você entendeu"}}"""


def _parse_proposal(text: str) -> dict:
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S) or re.findall(r"(\{.*\})", text, re.S)
    for raw in reversed(blocks):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("goals"), list):
            return clean_proposal(data)
    raise util.BrainError("o agente não devolveu uma proposta legível — tente de novo ou monte à mão")


def clean_proposal(data: dict) -> dict:
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    goals = []
    for g in (data.get("goals") or [])[:8]:
        if not isinstance(g, dict) or not _text(g.get("title"), 160):
            continue
        projects = []
        for p in (g.get("projects") or [])[:10]:
            if not isinstance(p, dict) or not _text(p.get("title"), 160):
                continue
            dels = [{"title": _text(d.get("title"), 160),
                     "due": _text(d.get("due"), 10) if date_re.match(_text(d.get("due"), 10)) else ""}
                    for d in (p.get("deliverables") or [])[:15] if isinstance(d, dict) and _text(d.get("title"), 160)]
            projects.append({"title": _text(p.get("title"), 160), "deliverables": dels})
        horizon = _text(g.get("horizon"), 10)
        why = _text(g.get("why"), 300)
        why = "" if util.fold(why).strip(" .") in ("nao consta", "-", "—", "n/a") else why
        goals.append({"title": _text(g.get("title"), 160), "horizon": horizon if date_re.match(horizon) else "",
                      "why": why, "projects": projects})
    return {"goals": goals, "summary": _text(data.get("summary"), 600)}


def draft_planning(brain) -> dict:
    from .tui import bridge
    files = progress(brain.inst).get("planning_sources") or []
    files = [f for f in files if (brain.inst.root / f).exists() or (brain.inst.vault / f).exists()]
    if not files:
        raise util.BrainError("escreva sobre seus objetivos ou envie um documento primeiro", code=4)
    if _agent_name(brain.inst.cfg) is None:
        raise util.BrainError("nenhum agente de IA instalado (Claude Code) — monte os goals à mão", code=4)
    inst = brain.inst
    paths = [str((inst.vault / f) if (inst.vault / f).exists() else (inst.root / f)) for f in files]
    argv = bridge.agent_argv(inst.cfg, PROPOSAL_PROMPT.format(root=inst.root, files=", ".join(paths)))

    def run(j: _Job) -> dict:
        j.say("o agente está lendo o que você escreveu…")
        info = bridge.RunInfo()
        lines: list[str] = []
        rc = asyncio.run(bridge.run_agent(inst, argv, lines.append, info))
        if rc != 0 and not info.result:
            raise util.BrainError(f"o agente parou com erro (código {rc})")
        proposal = _parse_proposal(info.result or "\n".join(lines))
        _save_progress(inst, proposal=proposal)
        j.say(f"✓ proposta com {len(proposal['goals'])} goal(s)")
        return {"proposal": proposal}
    return {"job": _start("planning", run).id}


def apply_planning(brain, data: dict) -> dict:
    """Cria a árvore aprovada pelo dono no navegador — o botão "Aprovar e criar" é a aprovação explícita."""
    from . import cli, planning
    if os.environ.get("BRAIN_NIGHTLY") == "1":
        raise util.BrainError("o planejamento nunca nasce no noturno", code=4)
    proposal = clean_proposal(data.get("proposal") or {})
    if not proposal["goals"]:
        raise util.BrainError("nenhum goal para criar", code=4)
    if not data.get("approved"):
        raise util.BrainError("confirme a aprovação para criar os goals", code=4)
    approval = "ok (aprovado no onboarding)"
    same = lambda a, b: util.fold(a).strip() == util.fold(b).strip()          # noqa: E731
    created = []
    # idempotente por título: repetir depois de uma falha no meio não duplica o que já nasceu
    for g in proposal["goals"]:
        gid = next((k for k, v in brain.plan.goals.items() if same(v.title, g["title"])), None)
        if gid is None:
            gid, _ = cli._create_goal(brain, g["title"], g["why"], approval, g["why"] or "goal do onboarding",
                                      "onboarding", horizon=g["horizon"])
            created.append(gid)
        for p in g["projects"]:
            pid = next((k for k, v in brain.plan.projects.items() if v.goal_id == gid and same(v.title, p["title"])),
                       None)
            if pid is None:
                pid, _ = cli._create_project(brain, gid, p["title"], brain.owner, approval,
                                             "projeto do onboarding", "onboarding")
                created.append(pid)
            for d in p["deliverables"]:
                if any(same(x.title, d["title"]) for x in brain.plan.deliverables_of(pid)):
                    continue
                did = planning.add_deliverable(brain.inst.planning_file, pid, d["title"], d["due"] or "", 1)
                cli._append_plan_log(brain.inst, f"{util.today().isoformat()} · {did} entregável criado sob {pid}: "
                                                 f"{d['title']} · sem gate (não é goal nem projeto)")
                created.append(did)
                brain.reload()
    _save_progress(brain.inst, proposal=None)
    _mark(brain.inst, "planejamento")
    return {"created": created}


def finish(brain) -> dict:
    from . import render
    _mark(brain.inst, "pronto")
    _save_progress(brain.inst, finished=util.today().isoformat())
    render.render_all(brain)
    return {"ok": True}


ACTIONS = {
    "about": save_about, "profile_preview": lambda b, d: {"markdown": profile_markdown(b, d)},
    "profile_save": save_profile, "routine": save_routine,
    "connectors_scan": lambda b, d: scan_connectors(bool(d.get("force"))),
    "connectors_enable": enable_connectors, "permissions": lambda b, d: apply_permissions(b),
    "keys": save_keys, "memory": apply_memory, "planning_note": save_planning_note,
    "planning_draft": lambda b, d: draft_planning(b), "planning_apply": apply_planning,
    "skip": lambda b, d: (_mark(b.inst, str(d.get("step"))) if d.get("step") in STEPS else None) or {},
    "finish": lambda b, d: finish(b),
}


def run_action(brain, name: str, data: dict) -> dict:
    fn = ACTIONS.get(name)
    if fn is None:
        raise util.BrainError("ação desconhecida", code=4)
    if "started_unconfigured" not in progress(brain.inst):     # foto do começo: era uma instância nova?
        _save_progress(brain.inst, started_unconfigured=brain.owner not in brain.state.people
                       or profile_is_template(brain.inst))
    return fn(brain, data or {}) or {}
