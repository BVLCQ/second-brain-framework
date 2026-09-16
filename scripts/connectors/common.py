#!/usr/bin/env python3
"""Second Brain — utilidades comuns dos conectores (pull-only, read-only).

Regras da constituição que este arquivo encarna:
- Conectores LEM fontes externas e ESCREVEM snapshots Markdown em vault/RAW/inbox/.
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
INBOX = INSTANCE_ROOT / "vault" / "RAW" / "inbox"
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
    Comentário inline (' # …') sai PRIMEIRO — senão aspas dentro de comentário
    (ex.: 'channels: []  # ex.: ["#x"]') vazam como itens reais."""
    rhs = re.split(r"\s+#", rhs)[0].strip()
    quoted = re.findall(r'"([^"]+)"', rhs)
    if quoted:
        return quoted
    items = [i.strip().strip("[]\"'") for i in rhs.split(",")]
    return [i for i in items if i]


def _parse_item(s: str) -> str | dict:
    '''"- repo: owner/x" → {"repo": "owner/x"} · "- owner/x" → "owner/x".
    Comentário inline (" # …") sai antes — valor nunca vem com # grudado.'''
    body = re.split(r"\s+#", s[2:].strip())[0].strip()
    m = re.match(r"^([a-zA-Z_]+):\s*(.+)$", body)
    if m:
        return {m.group(1): _unquote(m.group(2))}
    return _unquote(body)


def watch_items(raw: list, key: str) -> tuple[list[str], list[str]]:
    """Normaliza itens do watch (string curta OU objeto com enabled) →
    (habilitados, desligados). Item desligado = MUDO: não puxa, não debuga."""
    enabled, disabled = [], []
    for it in raw or []:
        if isinstance(it, dict):
            name = str(it.get(key) or it.get("id") or it.get("name") or "").strip()
            if not name:
                continue
            (enabled if it.get("enabled", True) else disabled).append(name)
        else:
            enabled.append(str(it).strip())
    return enabled, disabled


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
                       "gdocs": [], "gmail": {"enabled": True}}
        section = None
        last_list: list | None = None
        for ln in text.splitlines():
            if not ln.strip() or ln.strip().startswith("#"):
                continue
            if not ln[0].isspace():
                # cabeçalho de seção — comentário inline (' # …') fora
                section = re.split(r"\s+#", ln)[0].strip().rstrip(":").strip()
                continue
            s = re.split(r"\s+#", ln.strip(), 1)[0].strip() if section == "gdocs" else ln.strip()
            if section == "github":
                if s.startswith("- "):
                    item = _parse_item(s)
                    watch["github"].append(item)
                    last_list = watch["github"] if isinstance(item, dict) else None
                elif s.startswith("enabled:") and last_list is watch["github"] and watch["github"] and isinstance(watch["github"][-1], dict):
                    watch["github"][-1]["enabled"] = "true" in s.lower()
            elif section == "slack":
                if s.startswith("channels:"):
                    watch["slack"]["channels"] = _parse_list(s.split(":", 1)[1])
                    last_list = watch["slack"]["channels"]
                elif s.startswith("users:"):
                    watch["slack"]["users"] = _parse_list(s.split(":", 1)[1])
                    last_list = watch["slack"]["users"]
                elif s.startswith("enabled:"):
                    watch["slack"]["enabled"] = "true" in s.lower()
                elif s.startswith("default_window:"):
                    watch["slack"]["default_window"] = s.split(":", 1)[1].strip()
                elif s.startswith("- ") and last_list is not None:
                    item = _parse_item(s)
                    last_list.append(item)
                    if not isinstance(item, dict):
                        last_list = None
                elif s.startswith("enabled:") and last_list and isinstance(last_list[-1], dict):
                    last_list[-1]["enabled"] = "true" in s.lower()
            elif section == "jira":
                if s.startswith("me:"):
                    watch["jira"]["me"] = "true" in s.lower()
                elif s.startswith("following:"):
                    watch["jira"]["following"] = "true" in s.lower()
                elif s.startswith("boards:"):
                    watch["jira"]["boards"] = _parse_list(s.split(":", 1)[1])
                    last_list = watch["jira"]["boards"]
                elif s.startswith("- ") and last_list is not None:
                    item = _parse_item(s)
                    last_list.append(item)
                    if not isinstance(item, dict):
                        last_list = None
                elif s.startswith("enabled:") and last_list and isinstance(last_list[-1], dict):
                    last_list[-1]["enabled"] = "true" in s.lower()
            elif section == "gdocs":
                if s.startswith("- id:"):
                    watch["gdocs"].append({"id": _unquote(s.split(":", 1)[1]), "name": ""})
                elif s.startswith("name:") and watch["gdocs"]:
                    watch["gdocs"][-1]["name"] = _unquote(s.split(":", 1)[1])
                elif s.startswith("enabled:") and watch["gdocs"]:
                    watch["gdocs"][-1]["enabled"] = "true" in s.lower()
            elif section == "gmail":
                if s.startswith("enabled:"):
                    watch["gmail"]["enabled"] = "true" in s.lower()
        return watch


def _unquote(v: str) -> str:
    return v.strip().strip("\"'").strip()


def google_access_token() -> str:
    """OAuth refresh do Google (.env: GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN)
    → access token. Educado no erro clássico: app em 'Testing' = refresh
    token de 7 dias (guides/google-oauth.md)."""
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
                "7 dias): publique em produção (guides/google-oauth.md) e rode google_auth.py de novo.")
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
    """Escreve snapshot em vault/RAW/inbox/ com prefixo da fonte. Retorna o path."""
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
