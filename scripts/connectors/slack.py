#!/usr/bin/env python3
"""Conector Slack — pull-only, read-only.

Uso (noturno, via watch.yaml):  python3 slack.py            # canais+users watchlist
Uso (/slack sob demanda):       python3 slack.py #canal 30d
                                python3 slack.py @user 7d

Requer: SLACK_TOKEN (escopos de leitura: channels:history, im:history,
conversations:read, users:read — ver README.md).

Usa apenas urllib (stdlib). NENHUMA chamada de escrita existe (chat.postMessage
não aparece neste arquivo — por design e por constituição).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import common  # noqa: E402

API = "https://slack.com/api"


def token() -> str:
    return os.environ["SLACK_TOKEN"]


def get(method: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{API}/{method}?{qs}",
                                 headers={"Authorization": f"Bearer {token()}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        common.die(f"Slack API falhou ({type(e).__name__}): {e}", code=2)
    if not data.get("ok"):
        # erro de escopo/permissão vem aqui — reportar bruto, sem retry
        common.die(f"Slack API erro: {data.get('error')} (checar escopos do token)", code=3)
    return data


def load_watch_slack() -> tuple[list[str], list[str], str]:
    """Watchlist do slack via common.load_watch() (mesmo parser dos outros)."""
    slack = common.load_watch().get("slack") or {}
    channels = [c if str(c).startswith("#") else f"#{c}" for c in slack.get("channels") or []]
    users = [u if str(u).startswith("@") else f"@{u}" for u in slack.get("users") or []]
    return channels, users, str(slack.get("default_window") or "7d")


def resolve_channel(name: str) -> str:
    """'#canal' → channel id via conversations.list."""
    want = name.lstrip("#")
    cursor = None
    while True:
        params = {"types": "public_channel,private_channel", "limit": 200,
                  "exclude_archived": True}
        if cursor:
            params["cursor"] = cursor
        data = get("conversations.list", params)
        for ch in data.get("channels", []):
            if ch["name"] == want:
                return ch["id"]
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            common.die(f"canal '{name}' não encontrado (ou sem acesso)", code=4)


def resolve_user(name: str) -> tuple[str, str]:
    """'@user' → (user id, nome real) via users.list."""
    want = name.lstrip("@")
    cursor = None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = get("users.list", params)
        for u in data.get("members", []):
            if u["name"] == want or u.get("profile", {}).get("real_name", "").lower() == want.lower():
                return u["id"], u.get("profile", {}).get("real_name", want)
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            common.die(f"usuário '{name}' não encontrado", code=4)


def history(conversation_id: str, oldest: float, name: str) -> str:
    msgs, cursor = [], None
    while True:
        params = {"channel": conversation_id, "oldest": str(oldest), "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = get("conversations.history", params)
        msgs += data.get("messages", [])
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    users_cache: dict[str, str] = {}

    def who(uid: str) -> str:
        if uid not in users_cache:
            try:
                users_cache[uid] = get("users.info", {"user": uid})["user"]["name"]
            except Exception:  # noqa: BLE001
                users_cache[uid] = uid
        return users_cache[uid]

    lines = []
    for m in sorted(msgs, key=lambda x: float(x.get("ts", 0))):
        t = common.datetime_from_ts(float(m["ts"]))
        body = m.get("text", "").replace("\n", " ").strip()
        prefix = "  ↳" if m.get("thread_ts") and m["thread_ts"] != m.get("ts") else ""
        lines.append(f"- `{t:%d %b %H:%M}` **{who(m.get('user', 'bot'))}**: {body} {prefix}".rstrip())
    return "\n".join(lines) if lines else "_(sem mensagens na janela)_"


def snapshot_for(target: str, window: str | None) -> str:
    since_dt, wlabel = common.parse_window(window)
    oldest = since_dt.timestamp()
    if target.startswith("#"):
        cid = resolve_channel(target)
        body = history(cid, oldest, target)
        title = f"canal {target}"
    elif target.startswith("@"):
        uid, real = resolve_user(target)
        # conversations.open abre/retorna a DM — exige POST na API do Slack;
        # é leitura do ponto de vista do cérebro (não envia mensagem alguma)
        qs = urllib.parse.urlencode({"users": uid})
        req = urllib.request.Request(f"{API}/conversations.open?{qs}",
                                     data=b"", method="POST",
                                     headers={"Authorization": f"Bearer {token()}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                dm = json.loads(resp.read().decode())
        except Exception as e:  # noqa: BLE001
            common.die(f"Slack API falhou ({type(e).__name__}): {e}", code=2)
        if not dm.get("ok"):
            common.die(f"Slack API erro: {dm.get('error')} (checar escopos do token)", code=3)
        cid = dm["channel"]["id"]
        body = history(cid, oldest, target)
        title = f"DM com {target} ({real})"
    else:
        common.die(f"alvo inválido: '{target}' — use #canal ou @user", code=5)
    return f"# Slack · {title}\n_pull: {common.ts()} · janela: {wlabel}\n\n{body}\n"


def main() -> None:
    common.load_env()
    state = common.load_state()
    args = sys.argv[1:]
    if args:  # modo sob demanda: /slack #canal 30d
        target = args[0] if args[0].startswith(("#", "@")) else f"#{args[0]}"
        _, _, default_window = load_watch_slack()
        window = args[1] if len(args) > 1 else default_window
        text = snapshot_for(target, window)
        common.changed_since_last(f"slack:adhoc:{target}", text, state)
        path = common.write_snapshot("slack", target.strip("#@"), text)
        common.save_state(state)
        print(f"  slack/{target}: snapshot → {path.relative_to(common.INSTANCE_ROOT)}")
        print("→ rode /dump para processar")
        return
    # modo noturno: watchlist
    channels, users, _ = load_watch_slack()
    if not channels and not users:
        print("slack: watchlist vazia — nada a fazer")
        return
    print("slack: puxando…")
    any_new = False
    for ch in channels:
        text = snapshot_for(ch, "7d")
        changed, _ = common.changed_since_last(f"slack:watch:{ch}", text, state)
        if changed:
            path = common.write_snapshot("slack", ch.strip("#"), text)
            print(common.summary_line(f"slack/{ch}", True, path)); any_new = True
        else:
            print(common.summary_line(f"slack/{ch}", False, None))
    for u in users:
        try:
            text = snapshot_for(u, "7d")
        except SystemExit as e:
            print(f"  slack/{u}: FALHOU (permissão DM?) — {e}")
            continue
        changed, _ = common.changed_since_last(f"slack:watch:{u}", text, state)
        if changed:
            path = common.write_snapshot("slack", u.strip("@"), text)
            print(common.summary_line(f"slack/{u}", True, path)); any_new = True
        else:
            print(common.summary_line(f"slack/{u}", False, None))
    common.save_state(state)
    print("→ rode /dump para processar" if any_new else "→ nada novo")


if __name__ == "__main__":
    main()
