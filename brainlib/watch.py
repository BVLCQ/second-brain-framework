"""Edição segura do config/watch.toml — o universo observável do /update e do noturno.

Fonte não listada ali NÃO é puxada. O arquivo é do dono (config/, fora do git), então este módulo só mexe
nos blocos `[[source]]`: o resto (comentários, exemplos comentados, outras tabelas) fica intacto. Toda
mudança é validada relendo o TOML inteiro antes de gravar; se não parsear, nada é escrito.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import util

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
HEADER = ("# Universo observável do /update e do noturno.\n"
          "# Fonte não listada aqui NÃO é puxada — sem exceção.\n"
          "# Leituras passam pelos MCPs do agente; o resultado cai na inbox via:\n"
          "#   ./brain snapshot --key <key> --prefix <kind>\n"
          "# Hash idêntico ao último pull da mesma key = silêncio (nada escrito).\n")
FIELD_ORDER = ["key", "kind", "window", "channel", "jql", "note"]
SOURCE_RE = re.compile(r"^\[\[source\]\]\s*(#.*)?$")
TABLE_RE = re.compile(r"^\s*\[")
ASSIGN_RE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)(.*)$")


def path(inst) -> Path:
    return inst.config_dir / "watch.toml"


def _read(inst) -> str:
    p = path(inst)
    return p.read_text(encoding="utf-8") if p.exists() else ""


@dataclass
class Block:
    start: int          # índice da linha `[[source]]`
    end: int            # exclusivo; sem as linhas em branco finais
    data: dict


def _blocks(lines: list[str]) -> list[Block]:
    heads = [i for i, ln in enumerate(lines) if SOURCE_RE.match(ln)]
    out = []
    for n, h in enumerate(heads):
        stop = len(lines)
        for j in range(h + 1, len(lines)):
            if TABLE_RE.match(lines[j]) and not lines[j].lstrip().startswith("#"):
                stop = j
                break
        while stop > h + 1 and not lines[stop - 1].strip():
            stop -= 1
        try:
            data = tomllib.loads("\n".join(lines[h:stop])).get("source", [{}])[0]
        except tomllib.TOMLDecodeError as e:
            raise util.BrainError(f"watch.toml: bloco da linha {h + 1} inválido: {e}", code=4) from e
        out.append(Block(h, stop, data))
    return out


def list_sources(inst) -> list[dict]:
    text = _read(inst)
    if not text.strip():
        return []
    try:
        return [dict(s) for s in tomllib.loads(text).get("source", [])]
    except tomllib.TOMLDecodeError as e:
        raise util.BrainError(f"watch.toml inválido: {e}", code=4) from e


def _q(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)      # string básica TOML: mesmas regras de escape do JSON


def _clean(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if v is None or str(v).strip() == "":
            continue
        if not FIELD_RE.match(k):
            raise util.BrainError(f"campo inválido: {k!r} (minúsculas, números e _)", code=4)
        out[k] = str(v).strip()
    return out


def _split_value(rhs: str) -> tuple[str, str]:
    """('"valor" # nota') → ('"valor"', ' # nota'). Só entende string entre aspas; o resto vai inteiro."""
    rhs = rhs.rstrip()
    if rhs.startswith('"'):
        i = 1
        while i < len(rhs):
            if rhs[i] == "\\":
                i += 2
                continue
            if rhs[i] == '"':
                return rhs[: i + 1], rhs[i + 1:]
            i += 1
    return rhs, ""


def _commit(inst, lines: list[str]) -> None:
    text = "\n".join(lines).rstrip("\n") + "\n"
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise util.BrainError(f"a mudança deixaria o watch.toml inválido ({e}); nada foi gravado", code=4) from e
    keys = [s.get("key") for s in doc.get("source", [])]
    if any(not k for k in keys):
        raise util.BrainError("toda fonte precisa de `key`", code=4)
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise util.BrainError(f"key duplicada no watch.toml: {', '.join(sorted(dup))}", code=4)
    p = path(inst)
    mode = p.stat().st_mode & 0o777 if p.exists() else 0o644
    util.atomic_write(p, text)
    os.chmod(p, mode)


def _find(blocks: list[Block], key: str) -> Block:
    for b in blocks:
        if b.data.get("key") == key:
            return b
    raise util.BrainError(f"fonte '{key}' não está no watch.toml", code=3)


def _format_block(fields: dict) -> list[str]:
    ordered = [k for k in FIELD_ORDER if k in fields] + sorted(k for k in fields if k not in FIELD_ORDER)
    return ["[[source]]"] + [f"{k} = {_q(fields[k])}" for k in ordered]


def add(inst, key: str, fields: dict) -> dict:
    if not KEY_RE.match(key or ""):
        raise util.BrainError(f"key inválida: {key!r} (minúsculas, números, '.', '_' e '-'; ex.: slack-time-dados)", code=4)
    f = _clean(fields)
    if "kind" not in f:
        raise util.BrainError("a fonte precisa de `kind` (gmail, slack, gcal, drive, jira…)", code=4)
    if key in {s.get("key") for s in list_sources(inst)}:
        raise util.BrainError(f"já existe uma fonte com a key '{key}'", code=4)
    text = _read(inst)
    lines = text.splitlines() if text.strip() else HEADER.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    lines += ["", *_format_block({"key": key, **f})]
    _commit(inst, lines)
    return {"key": key, **f}


def edit(inst, key: str, set_: dict | None = None, unset: list[str] | None = None, rename: str | None = None) -> dict:
    lines = _read(inst).splitlines()
    blk = _find(_blocks(lines), key)
    changes = _clean(set_ or {})
    drop = [u for u in (unset or []) if u]
    if rename:
        if not KEY_RE.match(rename):
            raise util.BrainError(f"key inválida: {rename!r}", code=4)
        if rename != key and rename in {s.get("key") for s in list_sources(inst)}:
            raise util.BrainError(f"já existe uma fonte com a key '{rename}'", code=4)
        changes["key"] = rename
    if "kind" in drop or "key" in drop:
        raise util.BrainError("`key` e `kind` são obrigatórios e não podem ser removidos", code=4)
    body = lines[blk.start + 1: blk.end]
    seen: set[str] = set()
    new_body: list[str] = []
    for ln in body:
        m = ASSIGN_RE.match(ln)
        name = m.group(2) if m and not ln.lstrip().startswith("#") else None
        if name in drop:
            continue
        if name in changes:
            _, trail = _split_value(m.group(4))
            ln = f"{m.group(1)}{name}{m.group(3)}{_q(changes[name])}{trail}"
            seen.add(name)
        new_body.append(ln)
    extra = [f"{k} = {_q(v)}" for k, v in changes.items() if k not in seen]
    insert_at = len(new_body)
    while insert_at > 0 and not new_body[insert_at - 1].strip():
        insert_at -= 1
    new_body[insert_at:insert_at] = extra
    _commit(inst, lines[: blk.start + 1] + new_body + lines[blk.end:])
    return next(s for s in list_sources(inst) if s["key"] == (rename or key))


def remove(inst, key: str) -> None:
    lines = _read(inst).splitlines()
    blk = _find(_blocks(lines), key)
    end = blk.end
    while end < len(lines) and not lines[end].strip():       # leva junto a linha em branco que separava
        end += 1
    start = blk.start
    new = lines[:start] + lines[end:]
    _commit(inst, new)


def parse_pairs(items: list[str] | None) -> dict:
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep:
            raise util.BrainError(f"use campo=valor (recebi {it!r})", code=1)
        out[k.strip()] = v
    return out


def cli(args, brain) -> None:
    inst, c = brain.inst, args.wcmd
    if c == "list":
        rows = list_sources(inst)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return
        if not rows:
            print(f"nenhuma fonte em {util.relpath(path(inst), inst.root)} — `brain watch add KEY --kind gmail`")
        for s in rows:
            rest = " · ".join(f"{k}={v}" for k, v in s.items() if k not in ("key", "kind"))
            print(f"{s['key']}\t{s.get('kind', '?')}\t{rest}")
    elif c == "add":
        f = {"kind": args.kind, "window": args.window, "note": args.note, **parse_pairs(args.set)}
        add(inst, args.key, f)
        print(f"✓ fonte {args.key} adicionada ao watch.toml — o /update passa a puxá-la")
    elif c == "edit":
        f = {"kind": args.kind, "window": args.window, "note": args.note, **parse_pairs(args.set)}
        edit(inst, args.key, f, args.unset, args.rename)
        extra = (" · o histórico de pulls fica na key antiga" if args.rename and args.rename != args.key else "")
        print(f"✓ fonte {args.rename or args.key} atualizada{extra}")
    elif c == "remove":
        remove(inst, args.key)
        print(f"✓ fonte {args.key} removida do watch.toml — o /update deixa de puxá-la (snapshots e ledger ficam)")
