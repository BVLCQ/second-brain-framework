"""Arquivos do vault ligados a um item. A TUI e o painel chamam a mesma função."""
from __future__ import annotations

import re
from pathlib import Path

from . import opener

_DELIV = re.compile(r"^PROJ-\d+\.\d+$")


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

    Cada um: {kind, name, rel, ext, app}. O artefato traz também `raw` (o bruto dele, quando existe no
    vault), `deliverable`, `projects` e `date`; a linha do bruto traz `of` (o artefato). Quem mostra pode
    juntar os dois num documento só (Resumo · Original); quem lista linha a linha continua tendo o bruto.
    `notes_by_link` mapeia id → notas. `artifacts` tem id, title, raw, projects e deliverable.
    `projects_of(node)` devolve os projetos do nó, se houver.

    Entregável (`PROJ-#.#`) leva só os artefatos ligados a ele — não herda a lista inteira do projeto.
    """
    out: dict[str, dict] = {}
    by_id = {a["id"]: a for a in artifacts}

    def add(kind: str, name: str, ref: str, **extra) -> str:
        f = vault_file(inst, ref)
        if f is None:
            return ""
        rel = inst.rel(f)
        if rel not in out:
            out[rel] = {"kind": kind, "name": name or f.name, "rel": rel,
                        "ext": f.suffix.lstrip(".").lower(), "app": opener.app_for(inst.cfg, f)}
        for k, v in extra.items():                    # o bruto citado antes como fonte ganha o vínculo depois
            if v and k not in out[rel]:
                out[rel][k] = v
        return rel

    def add_art(art: dict) -> None:
        raw_f = vault_file(inst, art.get("raw") or "")
        rel = add("artefato", art.get("title") or "", art["id"],
                  raw=inst.rel(raw_f) if raw_f is not None else "",
                  deliverable=art.get("deliverable") or "", projects=list(art.get("projects") or []),
                  date=art.get("date") or "")
        add("RAW", Path(art["raw"]).name if art.get("raw") else "", art.get("raw") or "", of=rel)

    for n in (notes_by_link.get(node, []) if node else []):
        add("nota", f"{n.created} {n.title}", n.path)
    if node and _DELIV.match(node):
        for a in artifacts:
            if (a.get("deliverable") or "") == node:
                add_art(a)
    else:
        pids = set(projects_of(node)) if projects_of and node else set()
        for a in artifacts:
            if pids & set(a.get("projects") or []):
                add_art(a)
    for src in sources:
        key = (src or "").split("#")[0]
        art = by_id.get(key)
        if art:
            add_art(art)
        else:
            add("RAW" if key.startswith("RAW/") else "documento", "", key)
    for d in docs or []:
        add("documento", d.get("title") or "", d["ref"])
    return list(out.values())
