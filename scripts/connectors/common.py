#!/usr/bin/env python3
"""Second Brain — utilidades comuns dos conectores (pull-only, read-only).

Regras da constituição que este arquivo encarna:
- Conectores LEM fontes externas e ESCREVEM snapshots Markdown em RAW/inbox/.
- Estado (hashes) em config/.state.json — nunca commitado.
- Nenhuma chamada de escrita existe aqui, por design.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

# Paths — instância é o cwd do script: scripts/connectors/../../
CONNECTORS_DIR = Path(__file__).resolve().parent
INSTANCE_ROOT = CONNECTORS_DIR.parent.parent
INBOX = INSTANCE_ROOT / "RAW" / "inbox"
CONFIG_DIR = INSTANCE_ROOT / "config"
STATE_FILE = CONFIG_DIR / ".state.json"


def die(msg: str, code: int = 1) -> NoReturn:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(code)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ts() -> str:
    return now_utc().strftime("%Y-%m-%dT%H%M%SZ")


def load_env() -> None:
    """Carrega config/.env (KEY=VALUE) sem imprimir NADA do conteúdo."""
    env_file = CONFIG_DIR / ".env"
    if not env_file.exists():
        die("config/.env não encontrado — copie config/.env.example e preencha (chmod 600).")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            die(f"{STATE_FILE} corrompido — apague-o (será reconstruído).")
    return {}


def save_state(state: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    try:
        os.chmod(STATE_FILE, 0o600)
    except OSError:
        pass


def _parse_list(rhs: str) -> list[str]:
    """Parse de lista inline do watch.yaml (fallback sem PyYAML).
    Itens entre aspas vêm inteiros (canais '#x' têm # legítimo); fora de
    aspas, comentário é só ' # espaço-hash'."""
    quoted = re.findall(r'"([^"]+)"', rhs)
    if quoted:
        return quoted
    rhs = re.split(r"\s+#", rhs)[0].strip()
    items = [i.strip().strip("[]\"'") for i in rhs.split(",")]
    return [i for i in items if i]


def load_watch() -> dict:
    """Lê config/watch.yaml — PyYAML se disponível, senão parse minimalista."""
    watch_file = CONFIG_DIR / "watch.yaml"
    if not watch_file.exists():
        return {}
    text = watch_file.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        watch: dict = {"jira": {"me": True, "following": True, "boards": []},
                       "github": [], "slack": {"channels": [], "users": []},
                       "gdocs": []}
        section = None
        for ln in text.splitlines():
            if not ln.strip() or ln.strip().startswith("#"):
                continue
            if not ln[0].isspace():
                section = ln.rstrip(":").strip()
                continue
            s = ln.strip()
            if section == "github" and s.startswith("- "):
                item = s[2:].split("#")[0].strip().strip('"\'')
                if item:
                    watch["github"].append(item)
            elif section == "slack":
                if s.startswith("channels:"):
                    watch["slack"]["channels"] = _parse_list(s.split(":", 1)[1])
                elif s.startswith("users:"):
                    watch["slack"]["users"] = _parse_list(s.split(":", 1)[1])
                elif s.startswith("default_window:"):
                    watch["slack"]["default_window"] = s.split(":", 1)[1].strip()
            elif section == "gdocs":
                if s.startswith("- id:"):
                    watch["gdocs"].append({"id": _unquote(s.split(":", 1)[1]), "name": ""})
                elif s.startswith("name:") and watch["gdocs"]:
                    watch["gdocs"][-1]["name"] = _unquote(s.split(":", 1)[1])
            elif section == "jira":
                if s.startswith("me:"):
                    watch["jira"]["me"] = "true" in s.lower()
                elif s.startswith("following:"):
                    watch["jira"]["following"] = "true" in s.lower()
                elif s.startswith("boards:"):
                    watch["jira"]["boards"] = _parse_list(s.split(":", 1)[1])
        return watch


def _unquote(v: str) -> str:
    return v.strip().strip("\"'").strip()


def google_access_token() -> str:
    """OAuth refresh do Google (.env: GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN)
    → access token. Educado no erro clássico: app em 'Testing' = refresh
    token de 7 dias (docs/google-oauth.md)."""
    data = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"],
        "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        if "invalid_grant" in body:
            die("refresh token inválido/expirado — provável app em 'Testing' no GCP (expira em "
                "7 dias): publique em produção (docs/google-oauth.md) e rode google_auth.py de novo.")
        die(f"token Google falhou ({e.code}): {body}", code=2)
    except KeyError:
        die("resposta do Google sem access_token — cheque GOOGLE_* no config/.env", code=2)


def content_hash(text: str) -> str:
    """Hash estável do CONTEÚDO: linhas '_pull:' (timestamp do pull) são
    normalizadas fora antes de hashear — senão todo pull 'mudaria' mesmo
    idêntico, quebrando a idempotência (silêncio se nada mudou)."""
    norm = "\n".join(l for l in text.splitlines() if not l.startswith("_pull:"))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def changed_since_last(key: str, text: str, state: dict) -> tuple[bool, str]:
    """(mudou?, hash atual). Atualiza o estado em memória (salve depois)."""
    h = content_hash(text)
    prev = state.get(key, {}).get("hash") if isinstance(state.get(key), dict) else None
    state[key] = {"hash": h, "pulled_at": ts()}
    return (h != prev), h


def write_snapshot(prefix: str, name: str, text: str) -> Path:
    """Escreve snapshot em RAW/inbox/ com prefixo da fonte. Retorna o path."""
    INBOX.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-").lower() or "item"
    path = INBOX / f"{prefix}-{safe}-{ts()}.md"
    n = 2
    while path.exists():  # colisão de nome → sufixo -2 (regra da constituição)
        path = INBOX / f"{prefix}-{safe}-{ts()}-{n}.md"
        n += 1
    path.write_text(text, encoding="utf-8")
    return path


def summary_line(source: str, changed: bool, path: Path | None) -> str:
    if path is None:
        return f"  {source}: sem novidades (hash idêntico — nada arquivado)"
    return f"  {source}: NOVIDADES → {path.relative_to(INSTANCE_ROOT)}"


def parse_window(window: str | None) -> tuple[datetime, str]:
    """Converte '7d'/'30d'/'24h' em (datetime desde, rótulo). Default: 7d."""
    from datetime import timedelta
    w = (window or "7d").strip().lower()
    m = re.fullmatch(r"(\d+)([dh])", w)
    if not m:
        die(f"Janela inválida: '{window}' — use Nd (dias) ou Nh (horas), ex.: 7d")
    qty, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return now_utc() - timedelta(hours=qty), f"{qty}h"
    return now_utc() - timedelta(days=qty), f"{qty}d"


def datetime_from_ts(epoch: float) -> datetime:
    """ts do Slack (segundos com fração) → datetime UTC."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc)
