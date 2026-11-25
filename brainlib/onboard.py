"""Onboarding no navegador: o app Brain abre aqui enquanto a instância não está configurada.

Servido pela ponte local (`brain serve`, rota `/onboarding`), com as mesmas travas dela (só 127.0.0.1, Origin do
próprio painel, token). Cada passo é uma ação pequena e determinística deste módulo — nada passa pela allowlist de
comandos da ponte, e nenhum segredo vai para o log:

* **Você** — nome completo, apelido, cargo, e-mail → `person.added` (`[declarado]`, `by owner`). O id interno sai do
  nome enquanto o dono ainda não tem ficha (instância de uma pessoa só: ninguém escolhe id).
* **Sobre você** — o texto vira o `PROFILE/profile.md`, mostrado como prévia antes de gravar (o clique é a aprovação).
* **Rotina** — fuso e expediente (`[owner]`, `[work]`).
* **Conectores** — quando o Claude Code está presente, o estado vem do `claude mcp list` (rodado em segundo plano, só
  nome → status) e ligar um conector libera as ferramentas de LEITURA dele em `[runner].allow` e cria as fontes simples
  no `watch.toml`; caso contrário, o passo orienta a conectar pelo agente configurado e cadastrar a fonte em `watch.toml`.
  Escrita no mundo exterior continua só pelas portas.
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
import tempfile
import threading
import time
from pathlib import Path

from . import config, harness, runner, setup, util

STEPS = tuple(s[0] for s in setup.WEB_STEPS)      # registro único (setup.WEB_STEPS): ids que o navegador grava
WEB_STEPS = setup.WEB_STEPS                       # (id, título, grupo) — a barra lateral agrupa por grupo
PROFILE_TEMPLATE_MARK = "(a preencher no /init)"
KEY_NAMES = {
    "GITHUB_TOKEN": "Token do GitHub (sugestões e bugs do Brain viram issues)",
    "GOOGLE_CLIENT_ID": "Google OAuth — Client ID (foco na agenda + backup no Drive)",
    "GOOGLE_CLIENT_SECRET": "Google OAuth — Client Secret",
    "GOOGLE_REFRESH_TOKEN": "Google OAuth — Refresh Token (gerado pelo fluxo de conexão)",
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
JOB_TIMEOUT_S = 900  # 15 min: job travado expira como 'stale' em vez de prender o polling
JOB_TTL_S = 3600     # 1 h: jobs antigos saem da memória em partida ou leitura


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

    def check_timeout(self) -> None:
        if self.status == "running" and time.time() - self.started > JOB_TIMEOUT_S:
            self.status = "stale"
            self.result = {"error": "tempo esgotado (15 min) — rode `brain doctor --online` no terminal"}

    def as_dict(self) -> dict:
        self.check_timeout()
        return {"id": self.id, "kind": self.kind, "status": self.status, "log": self.log[-60:],
                "result": self.result, "elapsed": round(time.time() - self.started)}


_JOBS: dict[str, _Job] = {}
_JOBS_LOCK = threading.Lock()
_MCP_CACHE: dict = {"at": 0.0, "servers": None, "source": None, "hint": "", "job": None}


def _purge_jobs_locked(now: float | None = None) -> None:
    t = time.time() if now is None else now
    for old in [k for k, j in _JOBS.items() if t - j.started > JOB_TTL_S]:
        _JOBS.pop(old, None)


def _start(kind: str, fn) -> _Job:
    job = _Job(kind)
    with _JOBS_LOCK:
        _purge_jobs_locked()
        _JOBS[job.id] = job

    def run():
        try:
            res = fn(job) or {}
            if job.status == "running":
                job.result = res
                job.status = "done"
        except util.BrainError as e:
            job.say(f"✗ {e}")
            if job.status == "running":
                job.result = {"error": str(e)}
                job.status = "error"
        except Exception as e:  # noqa: BLE001 — o job relata, a ponte segue
            job.say(f"✗ erro inesperado: {e!r}")
            if job.status == "running":
                job.result = {"error": "erro inesperado — detalhe no log da ponte"}
                job.status = "error"
    threading.Thread(target=run, daemon=True, name=f"onboard-{kind}").start()
    return job


def job(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        _purge_jobs_locked()
        j = _JOBS.get(job_id)
        return j.as_dict() if j else None


class _JobUI:
    """UI de passos do setup dirigida por JOB (plano F2/F6): `say` vira linha do log, perguntas vêm
    de respostas programadas da tela — nenhuma pergunta sem resposta pode existir na porta roteada."""

    interactive = False

    def __init__(self, job_: _Job, answers: dict[str, str] | None = None):
        self.job, self.answers = job_, answers or {}

    def say(self, msg: str) -> None:
        self.job.say(str(msg))

    def ask(self, prompt: str, default: str = "") -> str:
        for k, v in self.answers.items():
            if prompt.startswith(k):
                return v
        return default

    def choice(self, prompt: str, options: list[str], default: str) -> str:
        for k, v in self.answers.items():
            if prompt.startswith(k) and v in options:
                return v
        return default

    def confirm(self, prompt: str, default: bool = False) -> bool:
        return default

    def secret(self, prompt: str) -> str:
        raise util.BrainError("este passo não pede segredo pela ponte — grave no config/.env", code=4)


# ── leitura do estado ────────────────────────────────────────────────────────
def _agent_name(argv) -> str | None:
    if isinstance(argv, dict):
        argv = runner.agent_command(argv)
    if not argv:
        return None
    return next((n for n, p in runner.PRESETS.items() if p[0] == argv[0]), Path(argv[0]).name)


def _no_claude_hint(label: str | None = None) -> str:
    """Sem Claude Code não há o que escanear: a dica aponta pro agente ESCOLHIDO no passo
    "Seu agente" (label), não pro primeiro binário achado no PATH."""
    ag = label or ("Hermes" if shutil.which("hermes") else "o seu agente")
    return (f"Os conectores ligam no {ag} — conecte Slack/Gmail/Calendar lá e use o botão "
            "\"+ Adicionar fonte\" abaixo para dizer o que o Brain deve observar.")


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


def scan_connectors(force: bool = False, run=subprocess.run) -> dict:
    """Dispara (ou reaproveita) o `claude mcp list` em segundo plano — leva 30–60 s. Nunca segura a trava da ponte."""
    if not force:
        with _JOBS_LOCK:
            _purge_jobs_locked()
            cached_job_id = _MCP_CACHE["job"]
            cached_job = _JOBS.get(cached_job_id) if cached_job_id else None
            is_running = bool(cached_job and cached_job.status == "running")
        if is_running:
            return {"job": cached_job_id}
    if not force and _MCP_CACHE["servers"] is not None and time.time() - _MCP_CACHE["at"] < 600:
        return {"source": _MCP_CACHE.get("source") or "claude", "servers": _MCP_CACHE["servers"],
                "hint": _MCP_CACHE.get("hint") or ""}

    def _run(j: _Job) -> dict:
        claude = shutil.which("claude")
        if not claude:
            hint = _no_claude_hint()
            _MCP_CACHE.update(at=time.time(), servers={}, source="none", hint=hint)
            j.say(hint)
            return {"source": "none", "servers": {}, "hint": hint}
        j.say("verificando os conectores do Claude…")
        p = run([claude, "mcp", "list"], capture_output=True, text=True, timeout=180,
                stdin=subprocess.DEVNULL)
        servers = parse_mcp_list(p.stdout + "\n" + p.stderr)
        _MCP_CACHE.update(at=time.time(), servers=servers, source="claude", hint="")
        j.say(f"✓ {len(servers)} conectores encontrados")
        return {"source": "claude", "servers": servers, "hint": ""}
    j = _start("connectors", _run)
    _MCP_CACHE["job"] = j.id
    return {"job": j.id}


def connector_status(servers: dict[str, str] | None, cfg: dict, sources: set[str] | None = None) -> list[dict]:
    allow = set(cfg["runner"].get("allow", []))
    srcs = sources or set()
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
        enabled = any(r.startswith(prefix) for r in allow)
        # sem Claude Code as ferramentas não têm allow-rule: vale a FONTE — o Brain observa do mesmo jeito
        if not enabled and key in DEFAULT_SOURCES and DEFAULT_SOURCES[key][0] in srcs:
            enabled = True
        out.append({"key": key, "label": c["label"], "what": c["what"], "status": status,
                    "enabled": enabled})
    return out


_PREREQ: dict = {"at": 0.0, "value": None}


def _llm_auth_state(brain, _providers) -> dict:
    """Estado de autenticação do LLM por assinatura, à prova de falha (docker lento nunca
    derruba o passo Memória — vira unknown e a tela mostra o que sabe)."""
    try:
        return _providers.auth_state(brain)
    except Exception:                                        # noqa: BLE001 — estado é informativo
        return {"provider": brain.inst.cfg["memory"].get("llm_provider", ""), "state": "unknown",
                "note": "", "fix": "", "flow": "", "family": ""}


def _prereqs() -> dict:
    """Docker/OrbStack e LM Studio no ar? (até 13 s de checagem — guardado por 60 s, o painel consulta toda hora).
    `lmstudio` é o booleano (servidor responde); `lmstudio_state` distingue instalado (o Brain sobe ao ativar)
    de ausente (o Brain instala ao ativar) — instalado nunca mais vira "falta — baixar"."""
    from . import setup
    if _PREREQ["value"] is None or time.time() - _PREREQ["at"] > 60:
        up = setup.lmstudio_up()
        dup = setup.docker_available()
        _PREREQ.update(at=time.time(), value={"docker": dup,
                                              "docker_state": setup.docker_state(up=dup),
                                              "lmstudio": up,
                                              "lmstudio_state": setup.lmstudio_state(up=up)})
    return _PREREQ["value"]


def state(brain) -> dict:
    from . import memory, perms, providers as _providers, setup
    providers_registry = _providers.PROVIDERS
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
    from . import watch as _watch
    try:
        sources = _watch.list_sources(inst)
    except util.BrainError:
        sources = []
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
        "agent": _agent_name(runner.agent_command(cfg)),
        "agents": agents_state(brain),
        "mcp_snippets": harness.mcp_snippets(brain.inst),
        "agent_mode": progress(inst).get("agent_mode", ""),
        "claude_installed": bool(shutil.which("claude")),
        "connectors": connector_status(_MCP_CACHE["servers"], cfg, {s["key"] for s in sources if s.get("key")}),
        "connectors_scanned": _MCP_CACHE["servers"] is not None,
        "connectors_source": "claude" if shutil.which("claude") else "none",
        "connectors_hint": "" if shutil.which("claude") else _no_claude_hint(_chosen_agent_label(brain)),
        "sources": sources,
        "watch_kinds": [list(k) for k in _watch.KINDS],
        "permissions": {"ok": perm.get("local") == "ok", "static": perm.get("static")},
        "memory": {"mode": {"embed": "lite"}.get(mem_mode, mem_mode),
                   "docker": pre["docker"], "docker_state": pre["docker_state"],
                   "lmstudio": pre["lmstudio"],
                   "lmstudio_state": pre["lmstudio_state"],
                   "llm_key": bool(env.get("HINDSIGHT_API_LLM_API_KEY")),
                   "llm_provider": cfg["memory"].get("llm_provider", ""),
                   "emb_provider": cfg["memory"].get("embeddings_provider", ""),
                   "emb_key": bool(env.get("HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY")),
                   "rer_provider": cfg["memory"].get("reranker_provider", ""),
                   "rer_key": bool(env.get("HINDSIGHT_API_RERANKER_LITELLM_SDK_API_KEY")
                                   or env.get("HINDSIGHT_API_RERANKER_COHERE_API_KEY")),
                   "dec_provider": cfg["memory"].get("decision_provider", "") or "off",
                   "dec_key": bool(env.get("HINDSIGHT_API_DECISION_MODEL_API_KEY"))
                              and cfg["memory"].get("decision_provider") != "local",
                   "dec_local_key": bool(env.get("BRAIN_DECISION_LOCAL_API_KEY")),
                   "dec_base_url": (env.get("HINDSIGHT_API_DECISION_MODEL_BASE_URL")
                                    or cfg["memory"].get("decision_base_url", "")),
                   "dec_recall": bool(cfg["memory"].get("decision_recall")
                                      or env.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER") == "hindsight"),
                   "dec_candidates": int(cfg["memory"].get("decision_max_candidates")
                                         or env.get("HINDSIGHT_API_RERANKER_MAX_CANDIDATES") or 0),
                   "providers": {slot: [{"key": k, "label": v["label"], "recommended": bool(v.get("recommended")),
                                         "recommended_cloud": bool(v.get("recommended_cloud")),
                                         "cloud": not (v.get("local") or k == "off"),
                                         "local": bool(v.get("local")),
                                         "subscription": slot == "llm" and v.get("family") == "subscription",
                                         "docker_auth": v.get("docker_auth", "") if slot == "llm" else "",
                                         "auth_command": v.get("auth_command", "") if slot == "llm" else "",
                                         "flow": _providers.AUTH_FLOWS.get(k, "") if slot == "llm" else "",
                                         "hint": v.get("setup_hint", "") or v.get("note", ""),
                                         "model": _providers.default_model(k) if slot == "llm" else v.get("model", ""),
                                         "base_url": v.get("base_url", "") if (slot == "decision" and k == "local") else "",
                                         "key_required": bool(v.get("key_env")) and not v.get("managed"),
                                         "managed": bool(v.get("managed")),
                                         "key_set": bool(v.get("key_env") and not v.get("managed") and env.get(v["key_env"]))}
                                        for k, v in _providers.menu_providers(slot, include_custom=True, include_unavailable=False)]
                                 for slot in ("llm", "embeddings", "reranker", "decision")},
                   "llm_auth": _llm_auth_state(brain, _providers),
                   "stack": {"llm": cfg["memory"].get("llm_provider", ""),
                             "embeddings": cfg["memory"].get("embeddings_provider", ""),
                             "reranker": cfg["memory"].get("reranker_provider", ""),
                             "decision": cfg["memory"].get("decision_provider", "") or "off"}},
        "keys": {k: {"label": v, "set": bool(env.get(k))} for k, v in KEY_NAMES.items()},
        "planning": {"goals": plan_goals, "proposal": progress(inst).get("proposal")},
        "maquina": maquina_state(brain),
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
        "agente": (True if any(a.get("mcp") for a in st["agents"])
                   else ("manual" if st["progress"].get("agent_mode") == "manual" else False)),
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
    claude = bool(shutil.which("claude"))
    if claude:                                                   # allow-rules são o vocabulário do Claude Code
        allow = [r for r in brain.inst.cfg["runner"].get("allow", []) if not r.startswith(off_prefixes)]
        for key in keys:
            prefix = rule_prefix(CONNECTORS[key]["server"])
            for tool in CONNECTORS[key]["tools"]:
                if prefix + tool not in allow:
                    allow.append(prefix + tool)
        config.set_keys(brain.inst, "runner", {"allow": allow})
        rules = "liberadas"
    else:
        allow = [r for r in brain.inst.cfg["runner"].get("allow", []) if not r.startswith(off_prefixes)]
        config.set_keys(brain.inst, "runner", {"allow": allow})  # só a limpeza: sem Claude não há regra nova
        rules = "puladas — permissões de ferramenta são do seu agente (Hermes/Cursor/Codex)"
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
    return {"enabled": keys, "sources": added, "removed": removed, "allow_rules": rules}


# ── editor de fontes (plano F4): o watch.toml na tela, com validação na hora ──
_SOURCE_FIELDS = ("channel", "folder", "jql", "path", "doc", "query", "note", "window")


def source_add(brain, data: dict) -> dict:
    from . import watch
    kind = _text(data.get("kind"), 40)
    key = _text(data.get("key"), 80)
    if not key or not kind:
        raise util.BrainError("key e kind são obrigatórios (ex.: slack-#time, slack)", code=4)
    if kind not in {k for k, _ in watch.KINDS}:
        raise util.BrainError(f"tipo de fonte desconhecido: {kind!r}", code=4)
    fields = {"kind": kind}
    for f in _SOURCE_FIELDS:
        v = _text(data.get(f), 400)
        if v:
            fields[f] = v
    src = watch.add(brain.inst, key, fields)                    # valida key, janela e id do Drive — ou recusa
    return {"source": src}


def source_remove(brain, data: dict) -> dict:
    from . import watch
    key = _text(data.get("key"), 80)
    if key not in {s.get("key") for s in watch.list_sources(brain.inst)}:
        raise util.BrainError(f"fonte '{key}' não existe", code=4)
    watch.remove(brain.inst, key)
    return {"removed": key}


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


# ── "fazer depois": UMA tarefa por passo ────────────────────────────────────────────────────────────────────
_LATER_MEM_STEMS = ("Configurar memória semântica do Brain", "Decidir e configurar a memória semântica do Brain")
_LATER_MEM_SUF = " (`brain setup --only memoria`)"
_LATER_AGENT_PRE, _LATER_AGENT_SUF = "Conectar o ", " ao Brain (MCP somente-leitura + permissões)"


def _later_task(brain, title: str, step: str, *, stems: tuple[str, ...] = ("",), suffix: str = "") -> str:
    """"Fazer depois" vira TASK `mine` no ledger — uma por passo: a ainda aberta não é cunhada de novo (clique
    duplo, retry de job, duas abas). `stems`/`suffix` dizem que títulos contam como a mesma tarefa (outro agente,
    outro modo de memória) — e a escolha mais recente vira o título dela, porque é o que o dono decidiu por último.
    Devolve o id da que existe ou da nova."""
    for a in sorted(brain.state.actions.values(), key=lambda x: x.id):
        same = any(a.title.startswith(s) for s in stems if s) and (not suffix or a.title.endswith(suffix))
        if a.open and a.list == "mine" and (a.title == title or same):
            if a.title != title:
                brain.record_one({"type": "action.updated", "id": a.id, "by": "owner", "prov": "declarado",
                                  "source": "onboarding", "data": {"title": title}})
            return a.id
    ev = brain.record_one({"type": "action.opened", "by": "owner", "prov": "declarado", "source": "onboarding",
                           "data": {"title": title, "owner": brain.owner, "list": "mine"}})
    _mark(brain.inst, step)
    return ev["id"]


def apply_memory(brain, data: dict) -> dict:
    from . import setup
    mode = {"lite": "embed"}.get(str(data.get("mode")), str(data.get("mode")))
    if mode not in ("none", "embed", "full"):
        raise util.BrainError("modo de memória inválido", code=4)
    if data.get("later"):                               # "fazer depois": vira TASK nomeada no ledger
        if util.is_nightly():
            raise util.BrainError("memória é escolha do dono presente — nunca no noturno", code=4)
        if brain.owner not in brain.state.people:
            raise util.BrainError("preencha o passo Você primeiro — a tarefa precisa do dono registrado", code=4)
        title = (
            f"Configurar memória semântica do Brain no modo {mode} (`brain setup --only memoria`)"
            if mode in ("embed", "full")
            else "Decidir e configurar a memória semântica do Brain (`brain setup --only memoria`)"
        )
        task = _later_task(brain, title, "memoria", stems=_LATER_MEM_STEMS, suffix=_LATER_MEM_SUF)
        _save_progress(brain.inst, memory_later={"embed": "lite"}.get(mode, mode))
        return {"later": True, "id": task, "mode": mode}
    setup.validate_memory_setup(data)                    # erros de escolha sobem ANTES do job (sem rodar nada)
    if mode == "none":
        from . import memory
        memory._apply_mode(brain, "none")
        _mark(brain.inst, "memoria")
        return {"mode": "none"}
    inst0 = brain.inst

    def run(j: _Job) -> dict:
        from .core import Brain
        b = Brain(config.reload(inst0))
        final = setup.configure_memory(b, data, say=j.say)
        _mark(b.inst, "memoria")
        return {"mode": {"embed": "lite"}.get(final, final)}
    return {"job": _start("memory", run).id}


# ── passo "Seu agente" (plano F3): harness antes dos conectores ───────────────
AGENT_KEYS = tuple(harness._DETECT)
_RUNNER_OF = {"claude-code": "claude", "cursor-cli": "cursor", "codex": "codex"}


def _agent_label(key: str) -> str:
    return harness.AGENTS.get(key, "Hermes")


def _chosen_agent_label(brain) -> str | None:
    """O agente que manda nesta instância: o selecionado no passo "Seu agente" ([runner].agent);
    sem seleção, o primeiro detectado; sem nenhum, None (a dica genérica)."""
    ags = agents_state(brain)
    sel = next((a["label"] for a in ags if a["selected"]), None)
    if sel:
        return sel
    return next((a["label"] for a in ags if a["detected"]), None)


def agents_state(brain) -> list[dict]:
    """Detectados na máquina + canal MCP do cérebro já registrado? (mesma detecção do `brain harness status`)."""
    det = harness.detect()
    cur = brain.inst.cfg["runner"].get("agent", "") or ""
    out = []
    for key in AGENT_KEYS:
        detected = bool(det.get(key))
        try:
            mcp = bool(harness.mcp_present(brain.inst, key))
        except Exception:                                      # noqa: BLE001 — status é informativo
            mcp = False
        preset = _RUNNER_OF.get(key, "")
        out.append({"key": key, "label": _agent_label(key), "detected": detected, "mcp": mcp,
                    "runner": preset, "selected": bool(preset) and cur == preset})
    return out


def connect_agent(brain, data: dict) -> dict:
    """Conecta o agente escolhido (job visível): [runner].agent + MCP somente-leitura + permissões
    (claude). Hermes é chat, não runner headless — os canais conectam, o runner segue no automático."""
    if util.is_nightly():
        raise util.BrainError("conectar agente é decisão do dono presente — nunca no noturno", code=4)
    key = str(data.get("agent") or "")
    if key == "other":
        _save_progress(brain.inst, agent_mode="manual")
        _mark(brain.inst, "agente")
        return {"mode": "manual"}
    if key not in AGENT_KEYS:
        raise util.BrainError(f"agente desconhecido: {key!r}", code=4)
    inst0 = brain.inst

    def run(j: _Job) -> dict:
        from . import perms
        from .core import Brain
        b = Brain(config.reload(inst0))
        preset = _RUNNER_OF.get(key, "")
        if preset:
            config.set_keys(b.inst, "runner", {"agent": preset})
            b.inst = config.reload(b.inst)
            b.reload()
            j.say(f"✓ [runner].agent = {preset} — é ele quem responde pelo cérebro (noturno, propostas)")
        else:
            j.say("• Hermes é o seu chat: o runner headless segue no automático (cursor/claude/codex/agy/gemini)")
        res = harness.wire_mcp(b.inst, key)
        if res.get("ok"):
            _save_progress(b.inst, agent_mode="")
            j.say(f"✓ servidor MCP somente-leitura do cérebro registrado no {_agent_label(key)} ({res.get('how')})")
        else:
            j.say(f"⚠ MCP não registrado — {res.get('hint')}")
        if key == "claude-code":
            perms.sync(b.inst)
            j.say("✓ permissões do Claude nesta pasta liberadas (leitura + comandos do brain; segredo e ledger seguem trancados)")
        _mark(b.inst, "agente")
        return {"mcp": bool(res.get("ok")), "runner": preset or "",
                "how": res.get("how", ""), "hint": res.get("hint", "")}
    return {"job": _start("agent", run).id}


def agent_later(brain, data: dict) -> dict:
    """"Fazer depois" com entidade: TASK nomeada no ledger, não frase de ajuda (plano F3).
    Só nomeia o agente que o dono ESCOLHEU na tela (clique no card); sem escolha, genérico —
    detecção no PATH nunca decide por ele (ruling: "allow the user to choose")."""
    if util.is_nightly():
        raise util.BrainError("\"fazer depois\" é escolha do dono presente — nunca no noturno", code=4)
    if brain.owner not in brain.state.people:
        raise util.BrainError("preencha o passo Você primeiro — a tarefa precisa do dono registrado", code=4)
    key = str(data.get("agent") or "")
    title = (f"Conectar o {_agent_label(key)} ao Brain (MCP somente-leitura + permissões)"
             if key in AGENT_KEYS else "Conectar o seu agente de IA ao Brain (MCP somente-leitura + permissões)")
    return {"id": _later_task(brain, title, "agente", stems=(_LATER_AGENT_PRE,), suffix=_LATER_AGENT_SUF)}


def apply_foco_google(brain, data: dict) -> dict:
    """Conectar Google AGORA (ruling do dono: o wizard não manda pedir ao agente). Job visível:
    grava id/secret → abre o navegador no consentimento (loopback) → captura o refresh token →
    foco em modo google. Escopo mínimo: calendar.events.owned + drive.file."""
    from . import setup
    if util.is_nightly():
        raise util.BrainError("conectar o Google é decisão do dono presente — nunca no noturno", code=4)
    env = config.load_env(brain.inst)
    cid = _text(data.get("client_id"), 200) or env.get("GOOGLE_CLIENT_ID", "")
    sec = str(data.get("client_secret") or "").strip() or env.get("GOOGLE_CLIENT_SECRET", "")
    if not (cid and sec):
        raise util.BrainError("preencha Client ID e Client Secret — ou crie em "
                              "console.cloud.google.com → APIs e serviços → Credenciais → ID do cliente OAuth (app Desktop)",
                              code=4)
    if len(sec) > 400 or any(ch.isspace() for ch in sec):
        raise util.BrainError("client secret inválido", code=4)
    inst0 = brain.inst

    def run(j: _Job) -> dict:
        from .core import Brain
        b = Brain(config.reload(inst0))
        setup.set_env(b.inst, {"GOOGLE_CLIENT_ID": cid, "GOOGLE_CLIENT_SECRET": sec})
        j.say("✓ credenciais OAuth gravadas no config/.env (0600)")
        j.say("abrindo o navegador para você autorizar o Google — escopo mínimo: "
              "só eventos que marcamos + os zips de backup")
        refresh = setup.google_refresh_token(cid, sec, open_browser=True, say=j.say)
        setup.set_env(b.inst, {"GOOGLE_REFRESH_TOKEN": refresh})
        j.say("✓ refresh token gravado no config/.env (nunca impresso)")
        config.set_keys(b.inst, "focus", {"mode": "google"})
        j.say("✓ foco em modo google — os blocos aprovados entram direto na sua agenda")
        _mark(b.inst, "chaves")
        return {"mode": "google"}
    return {"job": _start("foco_google", run).id}


def maquina_state(brain) -> dict:
    """Estado dos passos de máquina (plano F2) — derivado, mesma régua do `brain setup`."""
    from . import launcher
    try:
        plat = launcher._platform()
    except util.BrainError:
        plat = ""
    ours = bool(launcher.find_for_instance(brain.inst.root, platform=plat)) if plat else False
    pinned = launcher.pin_status(root=brain.inst.root, platform=plat or None) if ours else False
    other_dock = launcher.docked_other(brain.inst.root, platform=plat or None) if (plat and not pinned) else None
    icon_hint = ""
    if other_dock:
        icon_hint = (
            f"o atalho atual abre outra instância ({other_dock}) — clique para pregar o app desta instância"
            if ours else
            f"o atalho atual abre outra instância ({other_dock}) — instale o app desta instância com `brain app install`"
        )
    return {
        "comando": setup._st_comando(brain),
        "noturno": setup._st_noturno(brain),
        # sem o app instalado o pin é recusa honesta: pill de atenção, não "pendente" fingido
        "icon": ("warn" if not ours else "done" if pinned else "pending"),
        "icon_hint": icon_hint,
        "platform": plat,
        "tui": setup._st_tui(brain),
        "foco": setup._st_foco(brain),
        "framework": setup._st_framework(brain),
    }


def apply_maquina(brain, data: dict) -> dict:
    """Passo "A máquina" (plano F2): noturno · comando no PATH · TUI · foco ics · regra de fetch/hook.
    Cada item é opcional e idempotente — o default da tela é "ligar tudo" com os horários dados."""
    if util.is_nightly():
        raise util.BrainError("a máquina não se configura no noturno — abra o app com o dono presente", code=4)
    hhmm = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    noturno = str(data.get("noturno") or "").strip()          # "" = não agendar / não mexer; "05:00" = instalar no horário
    if noturno and not hhmm.match(noturno):
        raise util.BrainError("horário da sincronização inválido — use HH:MM", code=4)
    # foco/agenda: NÃO é daqui — quem decide é a conexão Google em "Chaves e portas" (ruling:
    # Google Calendar é o caminho do wizard; .ics fica como default silencioso do framework).
    wants = {"comando": bool(data.get("comando", True)), "tui": bool(data.get("tui", True)),
             "icon": bool(data.get("icon", True)),
             "framework": bool(data.get("framework", True))}
    inst0 = brain.inst

    def run(j: _Job) -> dict:
        from .core import Brain
        b = Brain(config.reload(inst0))
        ui = _JobUI(j)
        done: list[str] = []
        if wants["comando"]:
            setup._run_comando(b, ui)
            done.append("comando")
        else:
            j.say("– comando `brain` no PATH: deixado como está")
        if noturno:
            ui.answers["Horário do noturno"] = noturno
            setup._run_noturno(b, ui)
            done.append("noturno")
        else:
            j.say("– noturno: sem mudança")
        if wants["tui"]:
            setup._run_tui(b, ui)
            done.append("tui")
        else:
            j.say("– TUI: fica para depois (`brain tui --setup` quando quiser)")
        if wants["icon"]:
            from . import launcher
            try:
                j.say(launcher.pin_shortcut(root=b.inst.root))
                done.append("icon")
            except (util.BrainError, OSError, subprocess.SubprocessError) as e:
                j.say(f"– ícone: {e}")                  # cosmético: nunca derruba os passos seguintes
        if wants["framework"]:
            setup._run_framework(b, ui)
            done.append("framework")
        _mark(b.inst, "maquina")
        return {"done": done}
    return {"job": _start("maquina", run).id}


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
    fd, tmp_name = tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=str(inbox))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
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
    argv = runner.agent_command(brain.inst.cfg)
    if argv is None:
        raise util.BrainError("nenhum agente headless encontrado (procurei: cursor-agent, claude, codex, agy, gemini) "
                              "— instale um deles ou defina [runner] no config", code=4)
    agent = _agent_name(argv)
    inst = brain.inst
    paths = [str((inst.vault / f) if (inst.vault / f).exists() else (inst.root / f)) for f in files]
    prompt = PROPOSAL_PROMPT.format(root=inst.root, files=", ".join(paths))
    run_argv = bridge.agent_argv(inst.cfg, prompt) or argv

    def run(j: _Job) -> dict:
        j.say(f"o agente ({agent}) está lendo o que você escreveu…")
        info = bridge.RunInfo()
        lines: list[str] = []
        rc = asyncio.run(bridge.run_agent(inst, run_argv, lines.append, info))
        if rc != 0 and not info.result:
            raise util.BrainError(f"o agente ({agent}) parou com erro (código {rc})")
        proposal = _parse_proposal(info.result or "\n".join(lines))
        _save_progress(inst, proposal=proposal)
        j.say(f"✓ proposta com {len(proposal['goals'])} goal(s)")
        return {"proposal": proposal, "agent": agent}
    return {"job": _start("planning", run).id, "agent": agent}


def apply_planning(brain, data: dict) -> dict:
    """Cria a árvore aprovada pelo dono no navegador — o botão "Aprovar e criar" é a aprovação explícita."""
    from . import cli, planning
    if util.is_nightly():
        raise util.BrainError("o planejamento nunca nasce no noturno", code=4)
    proposal = clean_proposal(data.get("proposal") or {})
    if not proposal["goals"]:
        raise util.BrainError("nenhum goal para criar", code=4)
    if not data.get("approved"):
        raise util.BrainError("confirme a aprovação para criar os goals", code=4)
    # atestado de superfície (o wizard é o painel): o clique de confirmar acima é a aprovação do dono
    approval = "painel"
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


def apply_entrevista(brain, data: dict) -> dict:
    """A conversa acontece AQUI também (ruling do dono): responder já no wizard ou pular —
    pular vira TASK no TODO, não só ASK esperando o agente. As respostas ficam no progresso
    (logs/onboarding.json) e o finish() aplica: pessoas viram fichas na hora, fontes viram
    resposta da ASK para o agente aplicar (/dump passo 0)."""
    if util.is_nightly():
        raise util.BrainError("a entrevista é fala do dono — nunca no noturno", code=4)
    people = _text(data.get("people"), 4000)
    sources = _text(data.get("sources"), 4000)
    answered = bool(people.strip() or sources.strip())
    _save_progress(brain.inst, entrevista={"people": people, "sources": sources, "answered": answered})
    _mark(brain.inst, "conversa")
    return {"answered": answered}


def _apply_people(brain, text: str) -> list[str]:
    """Linhas `Nome — apelido, e-mail` viram fichas agora. Duplicado (mesma pessoa resolvida)
    é pulado — nunca segunda ficha. Máx. 20 linhas."""
    from . import people
    done: list[str] = []
    for raw in [l.strip() for l in text.splitlines() if l.strip()][:20]:
        parts = re.split(r"\s+[—–]\s+|\s*;\s*", raw, maxsplit=1)
        name = parts[0].strip()
        rest = parts[1] if len(parts) > 1 else ""
        if not name or len(name) > 80:
            continue
        email = next((tok.strip() for tok in re.split(r"[,;]", rest) if "@" in tok), "")
        aliases = [util.slugify(name)] + [t.strip() for t in re.split(r"[,;]", rest) if t.strip() and "@" not in t]
        pid = util.slugify(name)
        if pid in brain.state.people or people.resolve(brain.state, name):
            continue                      # já tem ficha — o agente une os apelidos depois, se sobrar
        brain.record_one({"type": "person.added", "id": pid, "by": "owner", "prov": "declarado",
                          "source": "onboarding", "data": {"name": name, "aliases": aliases,
                                                           "email": email, "relation": "contato recorrente"}})
        done.append(pid)
    return done


def finish(brain) -> dict:
    from . import ask, render
    if util.is_nightly():
        raise util.BrainError("o onboarding nunca termina no noturno — o dono fecha no app", code=4)
    try:
        # a entrevista que o /init faz de profundidade não morre com o formulário: vira ASK aberta —
        # o agente retoma sozinho na próxima sessão (/dump passo 0 aplica a resposta) ou pela TUI ⚡
        _, ask_id, _ = ask.add(
            brain,
            "Terminar a entrevista do onboarding: quem são as pessoas recorrentes (nome, e-mail, como te chamam) "
            "e quais fontes além das conectadas valem observar?",
            options=["conversar agora", "deixar para depois"], kind="outro",
            by="agent", prov="observado", source="onboarding")
        stash = progress(brain.inst).get("entrevista") or {}
        people_txt, sources_txt = str(stash.get("people") or ""), str(stash.get("sources") or "")
        applied_inline: list[str] = []
        if people_txt.strip():
            applied_inline = _apply_people(brain, people_txt)
        if sources_txt.strip():
            brain.record_one({"type": "question.answered", "id": ask_id, "by": "owner", "prov": "declarado",
                              "source": "onboarding",
                              "data": {"answer": f"fontes que valem observar: {sources_txt.strip()}", "free": True}})
        elif applied_inline:
            brain.record_one({"type": "question.answered", "id": ask_id, "by": "owner", "prov": "declarado",
                              "source": "onboarding", "data": {"answer": "conversar agora", "free": None}})
            brain.record_one({"type": "question.applied", "id": ask_id, "by": "agent", "prov": "observado",
                              "source": "onboarding",
                              "data": {"how": f"pessoas viraram fichas no onboarding: {', '.join(applied_inline)}"}})
        elif not stash.get("answered") and brain.owner in brain.state.people:
            # pulou a conversa: não se perde — vira TASK no TODO do dono (a ASK segue aberta pro agente;
            # sem a ficha do dono (passo Você pulado) a ASK sozinha cobre — nada de ficha fantasma)
            brain.record_one({"type": "action.opened", "by": "agent", "prov": "observado", "source": "onboarding",
                              "data": {"title": "Terminar a entrevista do Brain — pessoas recorrentes e fontes que valem observar",
                                       "owner": brain.owner, "list": "mine", "due": None, "due_suggested": None,
                                       "due_reason": "", "due_none_reason": "entrevista pós-onboarding — responda quando quiser (chat ou TUI ⚡)",
                                       "effort_min": None, "project": None, "deliverable": None, "blocked_by": [],
                                       "unblocks": [], "people": [], "priority": None, "link": "", "origin": "onboarding"}})
        render.render_all(brain)
        brain.record_one({"type": "onboarding.finished", "by": "owner", "prov": "declarado",
                          "source": "onboarding", "data": {}})
    except util.BrainError:
        raise
    except Exception as e:  # noqa: BLE001 — falha parcial não fecha onboarding
        raise util.BrainError(f"não consegui concluir o onboarding: {e}", code=3) from e
    _mark(brain.inst, "pronto")
    _save_progress(brain.inst, finished=util.today().isoformat())
    return {"ok": True, "ask": ask_id, "people_added": applied_inline}


def memory_auth(brain, data: dict) -> dict:
    """Autentica o provedor de assinatura do slot LLM (botão Autenticar do passo Memória) —
    job visível: cada linha do fluxo (token/setup-token, URL do device-code) cai no log."""
    if util.is_nightly():
        raise util.BrainError("autenticar provedor é ato do dono presente — nunca no noturno", code=4)
    from . import providers as _providers
    provider = str(data.get("provider") or "")
    reg = _providers.PROVIDERS["llm"].get(provider)
    if not reg or reg.get("family") != "subscription":
        raise util.BrainError(f"provedor de LLM (assinatura) desconhecido: {provider!r}", code=4)
    inst0 = brain.inst

    def run(j: _Job) -> dict:
        from . import setup
        from .core import Brain
        b = Brain(config.reload(inst0))
        ok = setup.run_llm_auth(b, _JobUI(j), provider)
        return {"ok": ok}
    return {"job": _start("memory_auth", run).id}


ACTIONS = {
    "about": save_about, "profile_preview": lambda b, d: {"markdown": profile_markdown(b, d)},
    "profile_save": save_profile, "routine": save_routine,
    "connectors_scan": lambda b, d: scan_connectors(bool(d.get("force"))),
    "connectors_enable": enable_connectors, "permissions": lambda b, d: apply_permissions(b),
    "source_add": source_add, "source_remove": source_remove,
    "keys": save_keys, "memory": apply_memory, "memory_auth": memory_auth,
    "maquina": apply_maquina, "foco_google": apply_foco_google,
    "entrevista": apply_entrevista,
    "agent_connect": connect_agent, "agent_later": agent_later,
    "planning_note": save_planning_note,
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
