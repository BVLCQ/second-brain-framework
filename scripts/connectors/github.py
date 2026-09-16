#!/usr/bin/env python3
"""Conector GitHub — pull-only, read-only.

Repos definidos em config/watch.yaml (github: [owner/repo, ...]).
Requer: GITHUB_TOKEN (fine-grained PAT, permissão de Leitura nos repos listados).

Usa apenas urllib (stdlib). Chamadas: list PRs/issues recentes.
NENHUMA chamada de escrita existe.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import common  # noqa: E402

API = "https://api.github.com"


def headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def get(path: str) -> list | dict:
    req = urllib.request.Request(f"{API}{path}", headers=headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        common.die(f"GitHub API falhou ({type(e).__name__}): {e}", code=2)


def since_iso(days: int = 7) -> str:
    from datetime import timedelta
    return (common.now_utc() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%MZ")


def pr_line(pr: dict) -> str:
    draft = " (draft)" if pr.get("draft") else ""
    user = (pr.get("user") or {}).get("login", "?")
    return (f"- **#{pr.get('number', '?')}** {pr.get('title', '')}{draft} · {pr.get('state', '?')}"
            f" · author: {user} · updated {pr.get('updated_at', '?')[:10]}")


def issue_line(i: dict) -> str:
    assignees = ", ".join(a.get("login", "?") for a in i.get("assignees") or []) or "—"
    return (f"- **#{i.get('number', '?')}** {i.get('title', '')} · {i.get('state', '?')}"
            f" · assignees: {assignees} · updated {i.get('updated_at', '?')[:10]}")


def main() -> None:
    common.load_env()
    state = common.load_state()
    repos, off = common.watch_items(common.load_watch().get("github") or [], "repo")
    for r in off:
        print(f"  github/{r}: desligado no watch.yaml (mudo — não puxa, não debuga)")
    repos = [r for r in repos if r not in off]
    if not repos:
        print("github: nenhum repo habilitado no config/watch.yaml — nada a fazer")
        return
    print("github: puxando…")
    any_new = False
    for repo in repos:
        since = since_iso(7)
        prs = [p for p in get(f"/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=30")
               if p.get("updated_at", "") >= since]
        issues = [i for i in get(f"/repos/{repo}/issues?state=all&sort=updated&direction=desc&per_page=30")
                  if "pull_request" not in i and i.get("updated_at", "") >= since]
        lines = [f"# GitHub · {repo}", f"_pull: {common.ts()} · janela: 7d_", "",
                 "## PRs", *map(pr_line, prs), "", "## Issues", *map(issue_line, issues)]
        text = "\n".join(lines) + "\n"
        changed, _ = common.changed_since_last(f"github:{repo}", text, state)
        if changed:
            path = common.write_snapshot("github", repo.replace("/", "-"), text)
            print(common.summary_line(f"github/{repo}", True, path))
            any_new = True
        else:
            print(common.summary_line(f"github/{repo}", False, None))
    common.save_state(state)
    print("→ rode /dump para processar" if any_new else "→ nada novo")


if __name__ == "__main__":
    main()
