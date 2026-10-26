"""Repositórios git locais observados — fonte `kind = "github"` do watch.toml.

Uma pasta (`path`, ex.: `~/Github/`) guarda os clones que o dono acompanha. Cada repositório é um **item** da
fonte (hash próprio, como as pastas do Drive): o `/update` roda `brain repos pull <key>` antes do `/dump`, e só
o repo que mudou vira arquivo na inbox (`github-<repo>-<ts>.md`), arquivado depois em `RAW/<ano>/<mês>/github/`.

Antes de ler, `git fetch` em cada repo (só baixa; `fetch = "false"` na fonte ou `--no-fetch` desliga).

**Primeira leitura = o repositório inteiro**, por mais antigo que seja: todo o histórico (todas as branches e
tags), a árvore de arquivos e o conteúdo dos documentos (README, `.md`, `.txt`…). `--full` refaz isso.
Depois, "novo" é exato, sem janela de tempo: os commits alcançáveis pelas pontas de hoje e não pelas pontas do
último pull. Determinístico — o LLM não lê o git nem decide o que é novo.

Leitura só: `fetch`, `log`, `for-each-ref`, `diff-tree`, `ls-tree`, `show`, `rev-list`. Nada de pull, merge,
checkout ou push; o working tree do dono nunca é tocado.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from . import snapshot, util, watch

KIND = "github"
PREFIX = "github"
MAX_COMMITS = 200         # leitura incremental: um rebase gigante não vira um snapshot de 5 mil commits
MAX_FILES = 25            # arquivos listados por commit
MAX_BODY_LINES = 15       # linhas do corpo da mensagem por commit
MAX_TREE = 1000           # arquivos na árvore da primeira leitura
DOC_MAX_LINES = 400       # por documento, na primeira leitura
DOC_TOTAL_LINES = 6000    # todos os documentos somados
DOC_EXT = {".md", ".markdown", ".txt", ".rst", ".adoc"}
GIT_TIMEOUT = 30
FETCH_TIMEOUT = 120
FALSE = {"0", "false", "nao", "não", "no", "off"}
REF_PATTERNS = ("refs/heads", "refs/remotes", "refs/tags")
_CRED_RE = re.compile(r"(://)[^/@\s]+@")      # https://user:token@host → https://host
_SEP, _END = "\x1f", "\x1e"


def _slot(key: str, repo: str) -> str:
    return f"repos:{key}#{repo}"


def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT, stdin: str | None = None) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat"}
    try:
        r = subprocess.run(["git", "-C", str(repo), "-c", "core.fsmonitor=false", *args], input=stdin,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
    except FileNotFoundError as e:
        raise util.BrainError("git não encontrado no PATH", code=5) from e
    except subprocess.TimeoutExpired as e:
        raise util.BrainError(f"git {args[0]} passou de {timeout}s", code=5) from e
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().splitlines()
        last = _CRED_RE.sub(r"\1", msg[-1]) if msg else "falhou"
        raise util.BrainError(f"git {args[0]}: {last}", code=5)
    return r.stdout


def source(inst, key: str) -> dict:
    src = next((s for s in watch.list_sources(inst) if s.get("key") == key), None)
    if src is None:
        raise util.BrainError(f"fonte '{key}' não está no watch.toml", code=3)
    if src.get("kind") != KIND:
        raise util.BrainError(f"fonte '{key}' é kind={src.get('kind')!r}, não {KIND!r}", code=4)
    if not src.get("path"):
        raise util.BrainError(f"fonte '{key}' precisa de `path` (pasta com os clones, ex.: ~/Github/)", code=4)
    return src


def discover(root: Path) -> list[Path]:
    """`root` se ele mesmo for um repo; senão os repos até dois níveis abaixo (`~/Github/<repo>` ou `<org>/<repo>`)."""
    if (root / ".git").exists():
        return [root]
    found = []
    for child in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if (child / ".git").exists():
            found.append(child)
            continue
        found += [g for g in sorted(child.iterdir()) if g.is_dir() and not g.name.startswith(".") and (g / ".git").exists()]
    return found


def _tips(repo: Path) -> list[str]:
    out = _git(repo, "for-each-ref", "--format=%(objectname)", *REF_PATTERNS)
    return sorted({ln.strip() for ln in out.splitlines() if ln.strip()})


def _exists(repo: Path, sha: str) -> bool:
    try:
        _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except util.BrainError:
        return False


def _remote(repo: Path) -> str:
    try:
        url = _git(repo, "remote", "get-url", "origin").strip()
    except util.BrainError:
        return ""
    return _CRED_RE.sub(r"\1", url)


def _main_ref(repo: Path) -> str:
    """O que o time vê: o upstream da branch atual (atualizado pelo fetch); sem upstream, o HEAD local."""
    try:
        return _git(repo, "rev-parse", "--abbrev-ref", "@{u}").strip()
    except util.BrainError:
        return "HEAD"


def _branch(repo: Path) -> str:
    try:
        head = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except util.BrainError:
        return "—"
    try:
        behind, ahead = _git(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD").split()
        up = _git(repo, "rev-parse", "--abbrev-ref", "@{u}").strip()
        return f"{head} · upstream {up} (atrás {behind} / à frente {ahead})"
    except (util.BrainError, ValueError):
        return f"{head} · sem upstream"


def _commits(repo: Path, tips: list[str], old: list[str] | None) -> list[dict]:
    """`old` None = histórico inteiro; senão só o que as pontas de hoje alcançam e as antigas não."""
    fmt = _SEP.join(["%H", "%h", "%an", "%ae", "%aI", "%D", "%s", "%b"]) + _END
    revs = tips + [f"^{p}" for p in (old or [])]
    cap = [] if old is None else [f"--max-count={MAX_COMMITS + 1}"]
    out = _git(repo, "log", "--stdin", "--date-order", f"--format={fmt}", *cap, stdin="\n".join(revs) + "\n",
               timeout=GIT_TIMEOUT * 4)
    rows = []
    for rec in out.split(_END):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = (rec.split(_SEP) + [""] * 8)[:8]
        rows.append(dict(zip(["sha", "short", "author", "email", "date", "refs", "subject", "body"], parts)))
    return rows


def _files(repo: Path, sha: str) -> list[str]:
    out = _git(repo, "diff-tree", "--no-commit-id", "--name-status", "-r", "-M", "--root", sha)
    return [" ".join(ln.split("\t")) for ln in out.splitlines() if ln.strip()]


def _is_doc(path: str) -> bool:
    p = Path(path)
    return p.suffix.lower() in DOC_EXT or p.name.lower().startswith("readme")


def _overview(repo: Path, ref: str) -> list[str]:
    """Primeira leitura: árvore de arquivos e conteúdo dos documentos no `ref`."""
    tree = [ln for ln in _git(repo, "ls-tree", "-r", "--name-only", ref).splitlines() if ln.strip()]
    lines = [f"## Árvore de arquivos ({ref}, {len(tree)} arquivos)", ""]
    lines += [f"- {t}" for t in tree[:MAX_TREE]]
    if len(tree) > MAX_TREE:
        lines.append(f"- … (+{len(tree) - MAX_TREE})")
    docs = sorted((t for t in tree if _is_doc(t)), key=lambda t: (not Path(t).name.lower().startswith("readme"), t))
    lines += ["", f"## Documentos ({len(docs)})", ""]
    budget = DOC_TOTAL_LINES
    for d in docs:
        if budget <= 0:
            lines.append(f"### {d}\n\n(omitido: teto de {DOC_TOTAL_LINES} linhas de documentos atingido)\n")
            continue
        try:
            body = _git(repo, "show", f"{ref}:{d}").splitlines()
        except util.BrainError:
            continue
        take = body[:min(DOC_MAX_LINES, budget)]
        budget -= len(take)
        lines += [f"### {d}", "", "````", *take, "````"]
        if len(body) > len(take):
            lines.append(f"(… +{len(body) - len(take)} linhas)")
        lines.append("")
    return lines


def render(name: str, repo: Path, commits: list[dict], how: str, fetched: str, files: dict[str, list[str]],
           overview: list[str] | None = None) -> str:
    capped = overview is None and len(commits) > MAX_COMMITS
    shown = commits[:MAX_COMMITS] if capped else commits
    title = "leitura completa" if overview is not None else "commits novos"
    lines = [f"# GitHub · {name} — {title}", "",
             f"_pull: {util.iso_now()} · {how} · fetch: {fetched}", "",
             f"- repo: {name} (local: {repo.name})",
             f"- remoto: {_remote(repo) or '—'}",
             f"- branch: {_branch(repo)}",
             f"- commits: {len(shown)}" + (f" (mostrando os {MAX_COMMITS} mais recentes; há mais)" if capped else ""),
             ""]
    if overview is not None:
        lines += overview + [f"## Histórico completo ({len(shown)} commits)", ""]
    for c in shown:
        lines += [f"### {c['short']} — {c['subject']}" if overview is not None else f"## {c['short']} — {c['subject']}",
                  f"- autor: {c['author']} <{c['email']}> · data: {c['date']}" + (f" · refs: {c['refs']}" if c["refs"] else "")]
        fl = files.get(c["sha"], [])
        if fl:
            lines.append(f"- arquivos ({len(fl)}): " + " · ".join(fl[:MAX_FILES]) + (" · …" if len(fl) > MAX_FILES else ""))
        body = c["body"].strip().splitlines()[:MAX_BODY_LINES]
        if body:
            lines += [""] + [f"> {b}" if b.strip() else ">" for b in body]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _pull_repo(brain, key: str, root: Path, repo: Path, do_fetch: bool, full: bool) -> dict:
    inst = brain.inst
    name = repo.relative_to(root).as_posix() if repo != root else repo.name
    row = {"repo": name, "new": 0, "full": False, "snapshot": None, "warning": None, "error": None}
    fetched = "não"
    if do_fetch:
        try:
            _git(repo, "fetch", "--all", "--prune", "--tags", "--quiet", timeout=FETCH_TIMEOUT)
            fetched = "sim"
        except util.BrainError as e:
            fetched, row["warning"] = "falhou (dados locais)", f"fetch falhou: {e}"
    prev = [] if full else (util.read_json(inst.state_file, {}).get(_slot(key, name)) or {}).get("tips", [])
    tips = _tips(repo)
    if tips and tips == prev:
        snapshot._pulled(brain, key, name, False)
        return row
    old = [p for p in prev if _exists(repo, p)]
    if not tips:
        commits, overview, how = [], None, "repo sem commits"
    elif old:
        commits, overview, how = _commits(repo, tips, old), None, "desde o último pull"
    else:                                   # primeira leitura, --full, ou as pontas antigas sumiram (force-push)
        why = "--full" if full else ("primeira leitura" if not prev else "pontas antigas sumiram (force-push?)")
        commits, overview, how = _commits(repo, tips, None), _overview(repo, _main_ref(repo)), f"{why} — repositório inteiro"
        row["full"] = True
    if commits or overview is not None:
        shown = commits if overview is not None else commits[:MAX_COMMITS]
        files = {c["sha"]: _files(repo, c["sha"]) for c in shown}
        res = snapshot.take(brain, key, render(name, repo, commits, how, fetched, files, overview),
                            prefix=PREFIX, item=name, name=name, with_key=False)
        row["new"] = len(shown)
        row["snapshot"] = inst.rel(res["path"]) if res.get("changed") else None
    else:
        snapshot._pulled(brain, key, name, False)
    state = util.read_json(inst.state_file, {})
    state[_slot(key, name)] = {"tips": tips, "at": util.iso_now()}
    util.write_json(inst.state_file, state)
    return row


def pull(brain, key: str, fetch: bool | None = None, full: bool = False) -> dict:
    src = source(brain.inst, key)
    root = Path(os.path.expanduser(str(src["path"]))).resolve()
    repos = discover(root) if root.is_dir() else []
    if not repos:
        err = f"pasta não existe: {src['path']}" if not root.is_dir() else f"nenhum repositório git em {src['path']}"
        brain.record_one({"type": "connector.failed", "id": key, "by": "system", "data": {"error": err}})
        return {"key": key, "failed": True, "error": err, "repos": []}
    do_fetch = (str(src.get("fetch", "true")).strip().lower() not in FALSE) if fetch is None else fetch
    rows = []
    for repo in repos:
        try:
            rows.append(_pull_repo(brain, key, root, repo, do_fetch, full))
        except util.BrainError as e:
            rows.append({"repo": repo.relative_to(root).as_posix() if repo != root else repo.name, "new": 0, "full": False, "snapshot": None, "warning": None, "error": str(e)})
    failed = all(r["error"] for r in rows)
    if failed:
        brain.record_one({"type": "connector.failed", "id": key, "by": "system",
                          "data": {"error": "; ".join(f"{r['repo']}: {r['error']}" for r in rows)[:500]}})
    return {"key": key, "failed": failed, "fetch": do_fetch, "repos": rows}


def cli(args, brain) -> None:
    if args.rcmd == "list":
        src = source(brain.inst, args.key)
        root = Path(os.path.expanduser(str(src["path"]))).resolve()
        found = discover(root) if root.is_dir() else []
        if args.json:
            print(json.dumps([str(p.relative_to(root)) if p != root else p.name for p in found], ensure_ascii=False))
            return
        if not found:
            print(f"nenhum repositório git em {src['path']}")
        for p in found:
            print(f"{p.relative_to(root).as_posix() if p != root else p.name}\t{_remote(p) or '—'}")
        return
    r = pull(brain, args.key, fetch=args.fetch, full=args.full)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    if r.get("error"):
        print(f"⚠ {args.key}: {r['error']} — registrado como falha")
        return
    for x in r["repos"]:
        if x["error"]:
            print(f"⚠ {x['repo']}: {x['error']}")
        elif x["snapshot"] and x["full"]:
            print(f"✓ {x['repo']}: leitura completa ({x['new']} commits + árvore + documentos) → {x['snapshot']} (rode /dump)")
        elif x["snapshot"]:
            print(f"✓ {x['repo']}: {x['new']} commit(s) novo(s) → {x['snapshot']} (rode /dump)")
        else:
            print(f"✓ {x['repo']}: sem novidades")
        if x["warning"]:
            print(f"  ⚠ {x['warning']}")
    if r["failed"]:
        print(f"⚠ {args.key}: todos os repositórios falharam — registrado como falha")
