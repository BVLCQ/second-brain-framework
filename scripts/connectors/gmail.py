#!/usr/bin/env python3
"""Conector Gmail — pull-only, read-only, via OAuth (mesma família do jira/github/slack).

Uso (noturno):   python3 scripts/connectors/gmail.py            # digest do dia anterior
Uso (/gmail):    python3 scripts/connectors/gmail.py 30d        # janela
                 python3 scripts/connectors/gmail.py from:ana   # filtro gmail

Requer no config/.env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
(gerados via google_auth.py — guides/google-oauth.md). Escopo: gmail.readonly.
Usa apenas urllib (stdlib). NENHUMA chamada de escrita existe.
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import common  # noqa: E402

API = "https://gmail.googleapis.com/gmail/v1/users/me"


def get(path: str, token: str) -> dict:
    req = urllib.request.Request(f"{API}{path}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        common.die(f"Gmail API falhou ({type(e).__name__}): {e}", code=2)
    raise AssertionError("unreachable")  # die é NoReturn


def snippet(msg: dict) -> str:
    return (msg.get("snippet") or "").replace("\n", " ")[:120]


def header(msg: dict, name: str) -> str:
    for h in (msg.get("payload") or {}).get("headers", []):
        if h.get("name", "").lower() == name:
            return h.get("value", "")
    return ""


def main() -> None:
    common.load_env()
    state = common.load_state()
    w = common.load_watch()
    # noturno: kill-switch da seção inteira
    if w.get("gmail", {}).get("enabled") is False:
        print("gmail: desligado no watch.yaml (mudo — não puxa, não debuga)")
        return
    token = common.google_access_token()
    args = sys.argv[1:]
    if args and args[0].startswith(("from:", "to:", "subject:", "q:", "is:", "in:")):
        q = args[0]
        label = f"filtro-{args[0].split(':', 1)[0]}"
    else:
        window = (args[0] if args else "1d").strip().lower()
        days = window[:-1] if window[:-1].isdigit() else "1"
        q = f"newer_than:{days}d"
        label = "daily" if days == "1" else f"janela-{days}d"

    data = get(f"/messages?maxResults=100&q={urllib.parse.quote(q)}", token)
    ids = [m["id"] for m in data.get("messages", [])]
    lines = [f"# Gmail · {label}", f"_pull: {common.ts()} · query: {q} · {len(ids)} mensagens_", ""]
    for mid in ids:
        m = get(f"/messages/{mid}?format=metadata"
                f"&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date", token)
        lines.append(f"- **{header(m, 'From')}** · {header(m, 'Subject')}")
        lines.append(f"  {snippet(m)}")
    text = "\n".join(lines) + "\n"
    changed, _ = common.changed_since_last(f"gmail:{label}", text, state)
    common.save_state(state)
    if changed:
        path = common.write_snapshot("gmail", label, text)
        print(f"  gmail/{label}: snapshot → {path.relative_to(common.INSTANCE_ROOT)} ({len(ids)} emails)")
        print("→ rode /dump para processar")
    else:
        print("  gmail/{label}: sem novidades (hash idêntico)")


if __name__ == "__main__":
    main()
