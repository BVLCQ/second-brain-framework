#!/usr/bin/env python3
"""Conector Jira — pull-only, read-only.

Escopos definidos em config/watch.yaml (jira: me/following/boards).
Requer: JIRA_BASE_URL, JIRA_EMAIL, JIRA_TOKEN (read-only API token).

Usa apenas urllib (stdlib) — zero dependências para instalar.
Chamadas: search JQL + campos básicos. NENHUMA chamada de escrita existe.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import common  # noqa: E402

FIELDS = "summary,status,assignee,reporter,updated,created,issuetype,priority,issuelinks"


def auth_header() -> dict:
    token = f"{os.environ['JIRA_EMAIL']}:{os.environ['JIRA_TOKEN']}"
    b64 = base64.b64encode(token.encode()).decode()
    return {"Authorization": f"Basic {b64}",
            "Accept": "application/json"}


def jql_for(watch: dict) -> list[tuple[str, str]]:
    """[(rótulo do escopo, JQL)] conforme watch.yaml. boards = project keys."""
    queries: list[tuple[str, str]] = []
    if watch.get("me"):
        queries.append(("meus-cards",
                        "assignee = currentUser() AND updated >= -7d ORDER BY updated DESC"))
    if watch.get("following"):
        queries.append(("seguidos",
                        "watcher = currentUser() AND updated >= -7d ORDER BY updated DESC"))
    for board in watch.get("boards") or []:
        key = str(board)
        queries.append((f"board-{key}",
                        f"project = \"{key}\" AND updated >= -3d ORDER BY updated DESC"))
    return queries


def search(jql: str) -> list[dict]:
    """Busca JQL com paginação (startAt) — sem truncar silenciosamente em 100."""
    base = os.environ["JIRA_BASE_URL"].rstrip("/")
    issues: list[dict] = []
    start_at = 0
    while True:
        url = (f"{base}/rest/api/2/search?jql="
               f"{urllib.parse.quote(jql)}&maxResults=100&startAt={start_at}&fields={FIELDS}")
        req = urllib.request.Request(url, headers=auth_header())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:  # noqa: BLE001 — reporta bruto, interpreta nada
            common.die(f"Jira API falhou ({type(e).__name__}): {e}", code=2)
        batch = data.get("issues", [])
        issues += batch
        total = data.get("total", len(issues))
        start_at += len(batch)
        if not batch or start_at >= total:
            return issues


def fmt(issue: dict) -> str:
    f = issue.get("fields", {})
    key = issue.get("key", "?")
    status = (f.get("status") or {}).get("name", "?")
    assignee = (f.get("assignee") or {}).get("displayName", "sem assignee")
    updated = (f.get("updated") or "?")[:16].replace("T", " ")
    summary = f.get("summary", "")
    itype = (f.get("issuetype") or {}).get("name", "?")
    return f"- **{key}** [{itype}/{status}] {summary} · assignee: {assignee} · atualizado {updated}"


def main() -> None:
    common.load_env()
    state = common.load_state()
    print("jira: puxando…")
    any_new = False
    for label, jql in jql_for(common.load_watch().get("jira", {}) or {}):
        issues = search(jql)
        if not issues:
            print(common.summary_line(f"jira/{label}", False, None))
            continue
        lines = [f"# Jira · {label}", f"_pull: {common.ts()} · janela: JQL abaixo_",
                 f"```jql\n{jql}\n```", ""]
        lines += [fmt(i) for i in issues]
        text = "\n".join(lines) + "\n"
        changed, _ = common.changed_since_last(f"jira:{label}", text, state)
        if changed:
            path = common.write_snapshot("jira", label, text)
            print(common.summary_line(f"jira/{label}", True, path))
            any_new = True
        else:
            print(common.summary_line(f"jira/{label}", False, None))
    common.save_state(state)
    print("→ rode /dump para processar" if any_new else "→ nada novo")


if __name__ == "__main__":
    main()
