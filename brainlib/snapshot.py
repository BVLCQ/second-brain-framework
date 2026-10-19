"""Snapshot de leituras externas (via MCP) na inbox — a disciplina "snapshot antes de usar".

O agente lê uma fonte pelo MCP e entrega o resultado bruto aqui (stdin ou --file).
Hash igual ao último pull da mesma chave → silêncio (nada escrito). Diferente →
arquivo novo em vault/RAW/inbox/<prefixo>-<chave>-<ts>.<ext>. Falhas também viram
evento: 2+ falhas seguidas aparecem no doctor e devem ser escaladas ao dono.

Pastas observadas (Drive): cada arquivo e cada subpasta é um **item** da fonte
(`--item <id>`), com o próprio hash. Só o que mudou vira arquivo na inbox:
  · `--empty`: janela `auto` sem nada novo — o pull conta como ok (move o `last_ok`), sem arquivo;
    conteúdo vazio vindo do MCP continua sendo falha;
  · `--rev` (ex.: modifiedTime do Drive) igual ao último pull do item → nada a ler;
    `--check` pergunta isso antes de o agente gastar uma leitura MCP;
  · mesmo conteúdo já guardado sob outra chave/item (atalho, arquivo movido de
    subpasta, chave antiga) → não duplica; o item passa a apontar para o arquivo existente.
O estado de cada item mora em `snapshot:<chave>#<item>`; o doctor continua vendo uma
única fonte (a chave).
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from . import util

HEARTBEAT_MIN = 5   # item sem novidade só registra evento se a fonte não pulsou há pouco (evita inundar o ledger)


def _normalize(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("_pull:")).strip()


def _slot(key: str, item: str | None) -> str:
    return f"snapshot:{key}" + (f"#{item}" if item else "")


def _twin(state: dict, h: str, slot: str) -> str | None:
    """Outro slot que já guarda este mesmo conteúdo (só para itens de pasta)."""
    for s, v in state.items():
        if s != slot and s.startswith("snapshot:") and isinstance(v, dict) and v.get("hash") == h:
            return s
    return None


def _pulled(brain, key: str, item: str | None, changed: bool, **extra) -> None:
    data = {"changed": changed, **extra}
    if item:
        data["item"] = item
        if not changed:
            c = brain.state.connectors.get(key)
            if c and c.last_ok and util.now() - util.parse_dt(c.last_ok) < timedelta(minutes=HEARTBEAT_MIN):
                return
    brain.record_one({"type": "connector.pulled", "id": key, "by": "system", "data": data})


def unchanged(brain, key: str, rev: str, item: str | None = None) -> bool:
    """True se a revisão informada é a do último pull do item — nada a ler."""
    prev = util.read_json(brain.inst.state_file, {}).get(_slot(key, item))
    return bool(rev and isinstance(prev, dict) and prev.get("rev") == rev)


def take(brain, key: str, content: str, prefix: str | None = None, ext: str = "md",
         item: str | None = None, rev: str | None = None, name: str | None = None) -> dict:
    inst = brain.inst
    state = util.read_json(inst.state_file, {})
    slot = _slot(key, item)
    prev = state.get(slot) if isinstance(state.get(slot), dict) else {}
    if rev and prev.get("rev") == rev:
        _pulled(brain, key, item, False, rev=rev)
        return {"changed": False, "failed": False, "path": None, "why": "rev"}
    if not content.strip():
        ev = brain.record_one({"type": "connector.failed", "id": key, "by": "system",
                               "data": {"error": "conteúdo vazio (o MCP não devolveu nada)"}})
        return {"changed": False, "failed": True, "event": ev}
    h = util.sha(_normalize(content))
    if prev.get("hash") == h:
        if rev:
            state[slot] = {**prev, "rev": rev}
            util.write_json(inst.state_file, state)
        _pulled(brain, key, item, False)
        return {"changed": False, "failed": False, "path": None, "why": "hash"}
    twin = _twin(state, h, slot) if item else None
    if twin:
        state[slot] = {"hash": h, "at": util.iso_now(), "path": state[twin].get("path"), "alias": twin,
                       **({"rev": rev} if rev else {})}
        util.write_json(inst.state_file, state)
        _pulled(brain, key, item, False, alias=twin)
        return {"changed": False, "failed": False, "path": None, "why": "alias", "alias": twin}
    inst.inbox.mkdir(parents=True, exist_ok=True)
    stamp = util.now().strftime("%Y-%m-%dT%H%M%S")
    parts = [util.slugify(prefix or key.split("-")[0], 16), util.slugify(key, 40 if not item else 32)]
    if item:
        parts.append(util.slugify(name or item, 24))
    base = "-".join(parts) + f"-{stamp}"
    path, n = inst.inbox / f"{base}.{ext}", 2
    while path.exists():
        path, n = inst.inbox / f"{base}-{n}.{ext}", n + 1
    path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    state[slot] = {"hash": h, "at": util.iso_now(), "path": inst.rel(path), **({"rev": rev} if rev else {})}
    util.write_json(inst.state_file, state)
    _pulled(brain, key, item, True, snapshot=inst.rel(path))
    return {"changed": True, "failed": False, "path": path}


def cli(args, brain) -> None:
    item = getattr(args, "item", None)
    label = f"{args.key}#{item}" if item else args.key
    if args.check:
        if not args.rev:
            raise util.BrainError("--check pede --rev (a revisão atual do item, ex.: modifiedTime)", code=2)
        same = unchanged(brain, args.key, args.rev, item)
        print(f"{'inalterado' if same else 'mudou'}: {label}")
        return
    if args.fail:
        brain.record_one({"type": "connector.failed", "id": args.key, "by": "system", "data": {"error": args.fail}})
        c = brain.state.connectors[args.key]
        print(f"✓ falha registrada em {args.key} ({c.consecutive_failures} seguidas)"
              + (" — ESCALAR ao dono" if c.consecutive_failures >= 2 else ""))
        return
    if args.empty:
        _pulled(brain, args.key, item, False, empty=True)
        print(f"✓ {label}: janela sem novidades (pull registrado, nada escrito)")
        return
    skip_read = bool(args.rev) and unchanged(brain, args.key, args.rev, item)
    content = "" if skip_read else (Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read())
    res = take(brain, args.key, content, args.prefix, args.ext, item=item, rev=args.rev, name=args.name)
    if res["failed"]:
        print(f"⚠ {label}: conteúdo vazio — registrado como falha")
    elif res["changed"]:
        print(f"✓ {label}: novidades → {brain.inst.rel(res['path'])} (rode /dump)")
    elif res.get("why") == "alias":
        print(f"✓ {label}: mesmo conteúdo já guardado em {res['alias']} (nada escrito)")
    elif res.get("why") == "rev":
        print(f"✓ {label}: revisão {args.rev} já lida (nada escrito)")
    else:
        print(f"✓ {label}: sem novidades (hash idêntico — nada escrito)")
