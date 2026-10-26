"""Configuração da instância (config/brain.toml) + caminhos do vault."""
from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import util

DEFAULTS: dict = {
    "owner": {"id": "eu", "name": "Dono do cérebro"},
    "timezone": "America/Sao_Paulo",
    "work": {
        "days": [1, 2, 3, 4, 5],          # ISO: 1=seg … 7=dom
        "start": "09:00",
        "end": "18:00",
        "lunch": "12:00-13:00",            # "" desliga
    },
    "vacations": [],                       # [{start="2026-10-21", end="2026-10-30"}]
    "focus": {
        "mode": "ics",                     # "google" (porta do calendário) | "ics" (sem escrita)
        "calendar": "primary",
        "horizon_days": 7,
        "block_min": 30,
        "block_max": 120,
        "daily_max_min": 180,
        "buffer_min": 10,
        "default_effort_min": 60,
        "title_prefix": "Foco",
        "decline_message": "Em bloco de foco planejado.",
    },
    "outbound": {"allow": [], "daily_max": 10},
    "publish": {"destinations": []},       # ["slack:#seu-canal", "drive:<folder-id>"]
    "oppdrive": {"enabled": False,         # porta das pastas de oportunidade (AGENTS.md, porta 6)
                 "root": "",               # id/URL da pasta-raiz no Drive: o agente só cria DENTRO dela
                 "tools": []},             # ferramentas MCP da porta liberadas ao agente headless (criar arquivo, sugerir no Docs)
    "memory": {
        "engine": "none",                  # "hindsight" quando o servidor estiver no ar
        "url": "http://localhost:8888",
        "raw_bank": "brain-raw",
        "mem_bank": "brain-mem",
        "max_file_mb": 25,
        "timeout_s": 120,
    },
    "runner": {"agent": "auto", "command": "", "prompt": "/update", "timeout_min": 45,
               "allow": []},              # ferramentas MCP de LEITURA do agente headless (noturno e TUI)
    "tui": {"agent_allow": [],             # ferramentas extras do agente nas ações ⚡ do TUI (ex.: MCP de escrita)
            "model": "", "effort": ""},   # modelo e esforço do claude nas ações ⚡ ("" = padrão do claude)
    "backup": {"enabled": False, "max_file_mb": 50, "keep": 8, "weekday": 7},
    "views": {"wins_weeks": 8, "timeline_back_days": 90, "timeline_ahead_days": 45,
              "stale_project_days": 14, "aging_warn_days": 7},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Instance:
    root: Path
    vault: Path
    config_dir: Path
    cfg: dict

    @property
    def owner_id(self) -> str:
        return self.cfg["owner"]["id"]

    @property
    def inbox(self) -> Path:
        return self.vault / "RAW" / "inbox"

    @property
    def processed(self) -> Path:
        return self.vault / "PROCESSED"

    @property
    def fresh(self) -> Path:
        return self.vault / "FRESH"

    @property
    def planning_file(self) -> Path:
        return self.vault / "PLANNING" / "goals.md"

    @property
    def planning_log(self) -> Path:
        return self.vault / "PLANNING" / "log.md"

    @property
    def reports(self) -> Path:
        return self.vault / "reports"

    @property
    def logs(self) -> Path:
        return self.vault / "logs"

    @property
    def state_file(self) -> Path:
        return self.config_dir / ".state.json"

    @property
    def env_file(self) -> Path:
        return self.config_dir / ".env"

    def rel(self, path: Path) -> str:
        return util.relpath(path, self.vault)


def _find_home() -> Path:
    """BRAIN_HOME vence; senão, sobe do cwd até achar config/brain.toml; senão, o repo."""
    env = os.environ.get("BRAIN_HOME")
    if env:
        return Path(env)
    here = Path.cwd().resolve()
    for cand in (here, *here.parents):
        if (cand / "config" / "brain.toml").exists() or (cand / "vault" / "PLANNING" / "goals.md").exists():
            return cand
    return Path(__file__).resolve().parent.parent


def load(root: Path | None = None) -> Instance:
    """Raiz explícita vence o ambiente; sem ela, BRAIN_HOME / cwd / repo."""
    if root is not None:
        root = Path(root)
        vault, config_dir = root / "vault", root / "config"
    else:
        root = _find_home()
        vault = Path(os.environ.get("BRAIN_VAULT") or root / "vault")
        config_dir = Path(os.environ.get("BRAIN_CONFIG") or root / "config")
    cfg_file = config_dir / "brain.toml"
    user: dict = {}
    if cfg_file.exists():
        try:
            user = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise util.BrainError(f"config/brain.toml inválido: {e}") from e
    cfg = _merge(DEFAULTS, user)
    try:
        util.set_timezone(cfg["timezone"])
    except (KeyError, ValueError, TypeError) as e:     # ZoneInfoNotFoundError é KeyError: BrainError em vez de traceback
        raise util.BrainError(f"config/brain.toml: timezone inválido {cfg['timezone']!r}", code=5) from e
    return Instance(root=root, vault=vault, config_dir=config_dir, cfg=cfg)


def load_env(inst: Instance) -> dict[str, str]:
    """Lê config/.env sem nunca imprimir valores. Ambiente do processo tem precedência."""
    values: dict[str, str] = {}
    if inst.env_file.exists():
        for line in inst.env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip().strip('"').strip("'")
    for k in list(values):
        if os.environ.get(k):
            values[k] = os.environ[k]
    return values


# ── permissões do agente (brain agent allow) ─────────────────────────────────
# Verbos que, no nome de uma ferramenta MCP, indicam ESCRITA no mundo exterior: nunca são liberados por `brain agent allow`.
# Enviar, postar ou mover algo de verdade passa pelas portas (/outbox, /publish, /focus), cada uma com o seu gate.
WRITE_VERBS = {"send", "post", "create", "update", "delete", "remove", "move", "schedule", "add", "upload", "share", "transition",
               "edit", "reply", "forward", "trash", "untrash", "publish", "write", "patch", "put", "respond", "invite",
               "archive", "label", "unlabel", "complete", "reopen", "resolve", "save", "append", "copy", "insert", "assign",
               "merge", "approve", "reject", "cancel", "import", "submit"}
# nomes de ferramenta que não trazem verbo de escrita óbvio, mas escrevem (lista explícita; some conforme os MCPs que você usa)
EXTERNAL_WRITE_TOOLS: set[str] = {"mcp__slack__slack_send_message", "mcp__slack__slack_send_message_draft"}
PLAIN_TOOLS = {"Read", "Edit", "Write", "Glob", "Grep", "NotebookEdit", "WebFetch", "WebSearch", "Task"}
ALLOW_SCOPES = {"tui": ("tui", "agent_allow"), "runner": ("runner", "allow")}


def _words(name: str) -> set[str]:
    import re
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return {w.lower() for w in re.split(r"[_\-.*\s]+", spaced) if w}


def is_external_write(rule: str) -> bool:
    """Regra de ferramenta MCP que escreve fora (heurística por verbo no nome + lista explícita)."""
    if rule in EXTERNAL_WRITE_TOOLS:
        return True
    if not rule.startswith("mcp__"):
        return False
    tool = rule.split("__")[-1] if rule.count("__") >= 2 else ""
    if not tool or "*" in tool:          # `mcp__slack`, `mcp__slack__*`: o servidor inteiro, envio incluso — não dá para provar leitura
        return True
    return bool(_words(tool) & WRITE_VERBS)


def check_allow_rule(rule: str) -> str:
    """Valida o formato da regra. Devolve a regra normalizada; levanta BrainError(code=4) se for inválida ou de escrita externa."""
    import re
    rule = (rule or "").strip()
    if not rule or "\n" in rule or len(rule) > 300:
        raise util.BrainError("regra de permissão vazia, com quebra de linha ou grande demais", code=4)
    m = re.fullmatch(r"Bash\((.+)\)", rule)
    if m:
        body = m.group(1).strip()
        if body in {"*", ":*", "**"}:
            raise util.BrainError("Bash(*) liberaria qualquer comando — escreva o prefixo, ex.: Bash(./brain:*)", code=4)
        return rule
    if re.fullmatch(r"mcp__[A-Za-z0-9_.-]+(__[A-Za-z0-9_.*-]+)?", rule):
        if is_external_write(rule):
            raise util.BrainError(f"{rule} escreve no mundo exterior (enviar, postar, criar, mover…): não é liberada por aqui — "
                                  "isso passa pelas portas (/outbox, /publish, /focus), cada uma com o seu gate", code=4)
        return rule
    if re.fullmatch(r"(%s)(\(.+\))?" % "|".join(sorted(PLAIN_TOOLS)), rule):
        return rule
    raise util.BrainError(f"regra inválida: {rule!r} — use Bash(prefixo:*), mcp__servidor__ferramenta ou uma ferramenta "
                          f"({', '.join(sorted(PLAIN_TOOLS))})", code=4)


def _array_span(text: str, start: int) -> int:
    """Índice logo depois do `]` que fecha o array que abre em `start` (respeita strings e comentários de linha)."""
    depth, i, in_str, esc = 0, start, False, False
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "#":
            i = text.find("\n", i)
            if i == -1:
                break
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise util.BrainError("config/brain.toml: array de permissões sem fechamento", code=5)


def add_allow(inst, rule: str, scope: str = "tui") -> tuple[str, bool]:
    """Grava `rule` em [tui].agent_allow (scope tui) ou [runner].allow (scope runner) preservando comentários e o resto do arquivo.
    Valida o TOML inteiro antes de gravar. Devolve (regra, já_existia)."""
    import json
    import re
    if scope not in ALLOW_SCOPES:
        raise util.BrainError(f"scope inválido: {scope!r} — use tui ou runner", code=4)
    rule = check_allow_rule(rule)
    table, key = ALLOW_SCOPES[scope]
    path = inst.config_dir / "brain.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    cur = tomllib.loads(text) if text.strip() else {}
    have = list((cur.get(table) or {}).get(key, []))
    if rule in have:
        return rule, True
    new_list = json.dumps(have + [rule], ensure_ascii=False)
    head = re.search(rf"^\[{table}\]\s*(#.*)?$", text, re.M)
    if head is None:
        text = text.rstrip("\n") + (f"\n\n[{table}]\n" if text.strip() else f"[{table}]\n") + f"{key} = {new_list}\n"
    else:
        nxt = re.search(r"^\[", text[head.end():], re.M)
        end = head.end() + nxt.start() if nxt else len(text)
        body = text[head.end():end]
        km = re.search(rf"^{key}\s*=\s*\[", body, re.M)
        if km is None:
            text = text[:head.end()] + f"\n{key} = {new_list}" + text[head.end():]
        else:
            open_at = head.end() + km.end() - 1
            close = _array_span(text, open_at)
            text = text[:head.end() + km.start()] + f"{key} = {new_list}" + text[close:]
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise util.BrainError(f"a mudança deixaria o brain.toml inválido ({e}); nada foi gravado", code=5) from e
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    util.atomic_write(path, text if text.endswith("\n") else text + "\n")
    os.chmod(path, mode)
    return rule, False
