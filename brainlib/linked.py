"""Arquivos do vault ligados a um item. A TUI e o painel chamam a mesma função."""
from __future__ import annotations

from pathlib import Path

from . import opener


def vault_file(inst, ref: str) -> Path | None:
    """Arquivo real de um caminho do ledger. None se não for arquivo dentro do vault."""
    ref = (ref or "").split("#")[0].strip()
    p = Path(ref)
    if not ref or ref == "chat" or p.is_absolute() or ".." in p.parts:
        return None
    from . import rawsort
    f = rawsort.resolve(inst, ref) if p.parts and p.parts[0] == "RAW" else inst.vault / p
    if not f or not f.is_file():
        return None
    try:
        if not f.resolve().is_relative_to(inst.vault.resolve()):
            return None
    except (OSError, ValueError):
        return None
    return f


def collect(inst, notes_by_link: dict, artifacts: list[dict], *,
            node: str = "", sources: tuple = (), docs: list | None = None,
            projects_of=None) -> list[dict]:
    """Arquivos ligados a um item, sem repetir.

    Cada um: {kind, name, rel, app}. `notes_by_link` mapeia id → notas. `artifacts` tem
    id, title, raw e projects. `projects_of(node)` devolve os projetos do nó, se houver.
    """
    out: dict[str, dict] = {}
    by_id = {a["id"]: a for a in artifacts}

    def add(kind: str, name: str, ref: str) -> None:
        f = vault_file(inst, ref)
        if f is None:
            return
        rel = inst.rel(f)
        if rel not in out:
            out[rel] = {"kind": kind, "name": name or f.name, "rel": rel,
                        "app": opener.app_for(inst.cfg, f)}

    for n in (notes_by_link.get(node, []) if node else []):
        add("nota", f"{n.created} {n.title}", n.path)
    pids = set(projects_of(node)) if projects_of and node else set()
    for a in artifacts:
        if pids & set(a.get("projects") or []):
            add("artefato", a.get("title") or "", a["id"])
            add("RAW", Path(a["raw"]).name if a.get("raw") else "", a.get("raw") or "")
    for src in sources:
        key = (src or "").split("#")[0]
        art = by_id.get(key)
        if art:
            add("artefato", art.get("title") or "", art["id"])
            add("RAW", Path(art["raw"]).name if art.get("raw") else "", art.get("raw") or "")
        else:
            add("RAW" if key.startswith("RAW/") else "documento", "", key)
    for d in docs or []:
        add("documento", d.get("title") or "", d["ref"])
    return list(out.values())
