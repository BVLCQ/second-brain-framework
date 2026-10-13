"""Snapshot de leituras externas (via MCP) na inbox — a disciplina "snapshot antes de usar".

O agente lê uma fonte pelo MCP e entrega o resultado bruto aqui (stdin ou --file).
Hash igual ao último pull da mesma chave → silêncio (nada escrito). Diferente →
arquivo novo em vault/RAW/inbox/<prefixo>-<chave>-<ts>.<ext>. Falhas também viram
evento: 2+ falhas seguidas aparecem no doctor e devem ser escaladas ao dono.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import util


def _normalize(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("_pull:")).strip()


def take(brain, key: str, content: str, prefix: str | None = None, ext: str = "md") -> dict:
    inst = brain.inst
    if not content.strip():
        ev = brain.record_one({"type": "connector.failed", "id": key, "by": "system",
                               "data": {"error": "conteúdo vazio (o MCP não devolveu nada)"}})
        return {"changed": False, "failed": True, "event": ev}
    state = util.read_json(inst.state_file, {})
    slot = f"snapshot:{key}"
    h = util.sha(_normalize(content))
    if state.get(slot, {}).get("hash") == h:
        brain.record_one({"type": "connector.pulled", "id": key, "by": "system", "data": {"changed": False}})
        return {"changed": False, "failed": False, "path": None}
    inst.inbox.mkdir(parents=True, exist_ok=True)
    stamp = util.now().strftime("%Y-%m-%dT%H%M%S")
    base = f"{util.slugify(prefix or key.split('-')[0], 16)}-{util.slugify(key, 40)}-{stamp}"
    path, n = inst.inbox / f"{base}.{ext}", 2
    while path.exists():
        path, n = inst.inbox / f"{base}-{n}.{ext}", n + 1
    path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    state[slot] = {"hash": h, "at": util.iso_now(), "path": inst.rel(path)}
    util.write_json(inst.state_file, state)
    brain.record_one({"type": "connector.pulled", "id": key, "by": "system",
                      "data": {"changed": True, "snapshot": inst.rel(path)}})
    return {"changed": True, "failed": False, "path": path}


def cli(args, brain) -> None:
    if args.fail:
        brain.record_one({"type": "connector.failed", "id": args.key, "by": "system", "data": {"error": args.fail}})
        c = brain.state.connectors[args.key]
        print(f"✓ falha registrada em {args.key} ({c.consecutive_failures} seguidas)"
              + (" — ESCALAR ao dono" if c.consecutive_failures >= 2 else ""))
        return
    content = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    res = take(brain, args.key, content, args.prefix, args.ext)
    if res["failed"]:
        print(f"⚠ {args.key}: conteúdo vazio — registrado como falha")
    elif res["changed"]:
        print(f"✓ {args.key}: novidades → {brain.inst.rel(res['path'])} (rode /dump)")
    else:
        print(f"✓ {args.key}: sem novidades (hash idêntico — nada escrito)")
