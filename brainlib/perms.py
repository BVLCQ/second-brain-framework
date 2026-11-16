"""Permissões da sessão interativa do Claude Code (chat do dono) — o cérebro nunca deve pedir licença para trabalhar.

O agente headless (noturno, ações ⚡) já roda com as ferramentas nativas liberadas (`runner.CLAUDE_TOOLS`). A sessão
interativa (terminal, app desktop) não tinha nada equivalente e perguntava a cada `ls`, `cat`, pasta fora do cwd e MCP de
leitura. Duas camadas, ambas lidas pelo Claude Code sem nenhum passo manual:

* `.claude/settings.json` (git, genérico): ferramentas nativas liberadas + os limites duros da Constituição em `deny`.
* `.claude/settings.local.json` (gitignorado, gerado aqui): o que é da instância — MCP de leitura (`[runner].allow`),
  a porta oppdrive (`[oppdrive].tools`), extras do dono (`[tui].agent_allow`) e `additionalDirectories` (a raiz da
  instância e as pastas de repositórios do `watch.toml`, para a sessão num worktree ou noutra pasta enxergar o vault).

Escrita no mundo exterior continua só pelas portas: `check_allow_rule` já recusa esses MCP em `agent allow`, e este módulo
refiltra o que lê do brain.toml antes de gravar.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config, runner, util

STATIC_FILE = ".claude/settings.json"
LOCAL_FILE = ".claude/settings.local.json"

# Limites duros da Constituição que valem mesmo com tudo liberado (deny vence allow).
DENY = [
    "Edit(/vault/PROCESSED/_ledger/**)",     # o livro-razão só se escreve via ./brain
    "Edit(/config/.env)", "Read(/config/.env)", "Edit(/.env)", "Read(/.env)",    # segredos nunca no chat
    "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push * --force*)", "Bash(git push * -f*)",
    "Bash(*--no-verify*)",                   # porta 5: nunca force, nunca --no-verify
]


def static_settings() -> dict:
    """O conteúdo esperado de `.claude/settings.json` (versionado)."""
    return {
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": list(runner.CLAUDE_TOOLS),
            "deny": list(DENY),
        },
        # worktree novo (app desktop) nasce sem o settings.local.json, que é gitignorado: a abertura da sessão o gera
        "hooks": {"SessionStart": [{"hooks": [{
            "type": "command",
            "command": '"$CLAUDE_PROJECT_DIR"/brain agent permissions >/dev/null 2>&1 || true',
        }]}]},
    }


def mcp_rules(cfg: dict) -> list[str]:
    """MCP liberadas na sessão interativa: leitura ([runner].allow), porta oppdrive e extras do dono ([tui].agent_allow).
    Ferramenta de escrita externa fora da porta oppdrive é descartada, mesmo que alguém a tenha escrito à mão no brain.toml."""
    door = set(runner.door_allow(cfg))
    out: list[str] = []
    for rule in runner.read_allow(cfg) + sorted(door) + [t for t in cfg.get("tui", {}).get("agent_allow", []) if t]:
        if rule in out:
            continue
        if rule.startswith("mcp__") and config.is_external_write(rule) and rule not in door:
            continue
        out.append(rule)
    return out


def extra_directories(inst) -> list[str]:
    """Raiz da instância (+ vault/config se moram fora dela) e as pastas de repositórios acompanhados no watch.toml."""
    dirs = [inst.root, inst.vault, inst.config_dir]
    try:
        from . import watch
        for src in watch.list_sources(inst):
            if src.get("kind") == "github" and src.get("path"):
                dirs.append(Path(os.path.expanduser(str(src["path"]))))
    except (util.BrainError, OSError):   # sem watch.toml (instância nova): só a raiz
        pass
    seen: list[Path] = []
    for d in dirs:
        d = Path(d).resolve()
        if not any(d == k or k in d.parents for k in seen):   # vault/ e config/ dentro da raiz já estão cobertos
            seen.append(d)
    return [str(d) for d in seen]


def abs_denies(inst) -> list[str]:
    """Os mesmos limites do `deny` estático, com caminho ABSOLUTO (`//…`): numa sessão em worktree, `/vault/…` relativo ao
    projeto aponta para um vault que não existe, e a raiz da instância entra como pasta extra — sem isto o `.env` real
    ficaria legível por baixo do `Read` liberado."""
    r = Path(inst.root).resolve()
    ledger = Path(inst.vault).resolve() / "PROCESSED" / "_ledger"
    env = [Path(inst.config_dir).resolve() / ".env", r / ".env"]
    return [f"Edit(/{ledger}/**)"] + [f"{t}(/{e})" for e in env for t in ("Read", "Edit")]


def local_permissions(inst) -> dict:
    return {"allow": mcp_rules(inst.cfg), "deny": abs_denies(inst), "additionalDirectories": extra_directories(inst)}


def session_roots(inst) -> list[Path]:
    """Onde uma sessão do Claude Code lê `.claude/settings.local.json`: a raiz da instância e os worktrees dela
    (`.claude/worktrees/*` — o app desktop abre a sessão no worktree e lê o arquivo de lá, não o da raiz)."""
    root = Path(inst.root).resolve()
    wt = root / ".claude" / "worktrees"
    return [root] + ([p.resolve() for p in sorted(wt.iterdir()) if p.is_dir()] if wt.is_dir() else [])


def _here(roots: list[Path]) -> list[Path]:
    """A raiz da instância + o worktree em que o comando roda (o que o doctor precisa conferir)."""
    cwd = Path.cwd().resolve()
    return [r for i, r in enumerate(roots) if i == 0 or r == cwd or r in cwd.parents]


def local_path(inst, root: Path | None = None) -> Path:
    return Path(root or inst.root) / LOCAL_FILE


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _merged(inst, root: Path | None = None) -> dict:
    """O settings.local.json como deve ficar: o que o brain gerencia (anotado em `brainManaged`) é recalculado — sai o que
    o dono tirou do brain.toml —, e tudo que o dono pôs à mão no arquivo é preservado."""
    cur = _read(local_path(inst, root))
    perms = dict(cur.get("permissions") or {})
    mine = local_permissions(inst)
    prev = cur.get("brainManaged") if isinstance(cur.get("brainManaged"), dict) else {}
    for key in ("allow", "deny", "additionalDirectories"):
        old = set(prev.get(key, []))
        have = [x for x in perms.get(key, []) if isinstance(x, str) and x not in old]
        perms[key] = have + [x for x in mine[key] if x not in have]
    cur["permissions"] = perms
    cur["brainManaged"] = mine
    return cur


def status(inst) -> dict:
    """{'static': ok|missing|drift, 'local': ok|missing|stale, 'missing': [...]} — o que o doctor mostra."""
    st: dict = {"static": "ok", "local": "ok", "missing": []}
    sf = inst.root / STATIC_FILE
    if not sf.exists():
        st["static"] = "missing"
    else:
        have = (_read(sf).get("permissions") or {})
        want = static_settings()["permissions"]
        if (set(want["allow"]) - set(have.get("allow", []))) or (set(want["deny"]) - set(have.get("deny", []))):
            st["static"] = "drift"
    mine = local_permissions(inst)
    for root in _here(session_roots(inst)):
        lf = local_path(inst, root)
        if not lf.exists():
            st["local"] = "missing"
            continue
        cur = (_read(lf).get("permissions") or {})
        miss = [x for k in ("allow", "deny", "additionalDirectories") for x in mine[k] if x not in cur.get(k, [])]
        st["missing"] += miss
        if miss and st["local"] == "ok":
            st["local"] = "stale"
    return st


def sync(inst) -> dict:
    """Grava o settings.local.json em cada raiz de sessão (idempotente). Devolve {'path', 'changed', 'allow', 'directories', 'roots'}."""
    changed, first = False, None
    for root in session_roots(inst):
        if not root.is_dir():
            continue
        data = _merged(inst, root)
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        path = local_path(inst, root)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            util.atomic_write(path, text)
            changed = True
        first = first or (path, data)
    path, data = first
    perms = data["permissions"]
    return {"path": str(path), "changed": changed, "allow": len(perms["allow"]),
            "directories": len(perms["additionalDirectories"]), "roots": len(session_roots(inst))}


def try_sync(inst) -> None:
    """Para quem chama de passagem (init, agent allow, update): nunca derruba o comando por causa disto."""
    try:
        sync(inst)
    except (OSError, util.BrainError):
        pass
