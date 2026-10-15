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
    "memory": {
        "engine": "none",                  # "hindsight" quando o servidor estiver no ar
        "url": "http://localhost:8888",
        "raw_bank": "brain-raw",
        "mem_bank": "brain-mem",
        "max_file_mb": 25,
        "timeout_s": 120,
    },
    "extractor": {
        "enabled": False,                  # true quando o LM Studio estiver no ar
        "base_url": "http://localhost:1234/v1",
        "model": "",                       # ex.: "qwen/qwen3-4b-2507" — `lms ls` lista os carregados
        "api_key_env": "",                 # LM Studio dispensa chave; gateway: nome da variável de ambiente
        "temperature": 0.1,
        "max_tokens": 4096,
        "timeout_s": 180,
    },
    "runner": {"agent": "auto", "command": "", "prompt": "/update", "timeout_min": 45},
    "tui": {"agent_allow": []},            # ferramentas extras do agente nas ações ⚡ do TUI (ex.: MCP de escrita)
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
    util.set_timezone(cfg["timezone"])
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
