"""Edição segura do config/watch.toml — o universo observável do /update e do noturno.

Fonte não listada ali NÃO é puxada. O arquivo é do dono (config/, fora do git), então este módulo só mexe
nos blocos `[[source]]`: o resto (comentários, exemplos comentados, outras tabelas) fica intacto. Toda
mudança é validada relendo o TOML inteiro antes de gravar; se não parsear, nada é escrito.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from . import util

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
HEADER = ("# Universo observável do /update e do noturno.\n"
          "# Fonte não listada aqui NÃO é puxada — sem exceção.\n"
          "# Leituras passam pelos MCPs do agente; o resultado cai na inbox via:\n"
          "#   ./brain snapshot --key <key> --prefix <kind>\n"
          "# Hash idêntico ao último pull da mesma key = silêncio (nada escrito).\n")
FIELD_ORDER = ["key", "kind", "window", "channel", "jql", "doc", "link", "note"]
DRIVE_DOC = "drive-doc"             # playbook de um processo: relido só quando o modifiedTime muda
DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
DRIVE_URL_RE = re.compile(r"/(?:d|folders)/([A-Za-z0-9_-]{10,})|[?&]id=([A-Za-z0-9_-]{10,})")
SOURCE_RE = re.compile(r"^\[\[source\]\]\s*(#.*)?$")
TABLE_RE = re.compile(r"^\s*\[")
ASSIGN_RE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)(.*)$")
WINDOW_RE = re.compile(r"^(\d{1,3})([hdw])$")
WINDOW_UNITS = {"h": "hours", "d": "days", "w": "weeks"}
AUTO_FIRST = timedelta(days=7)       # fonte nunca puxada
AUTO_MAX = timedelta(days=14)        # teto: Mac parado semanas não vira uma leitura gigante
AUTO_OVERLAP = timedelta(hours=2)    # o pull só é registrado depois da leitura — sobrepõe para não perder o que chegou no meio


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
        if k == "window":
            parse_window(out[k])
    return out


def parse_window(value: str) -> timedelta | None:
    """'auto' → None (desde o último pull); '1d' · '12h' · '2w' → o intervalo fixo."""
    v = str(value).strip().lower()
    if v == "auto":
        return None
    m = WINDOW_RE.match(v)
    if not m or int(m.group(1)) == 0:
        raise util.BrainError(f"window inválida: {value!r} (use auto, 12h, 1d, 2w…)", code=4)
    return timedelta(**{WINDOW_UNITS[m.group(2)]: int(m.group(1))})


def since(brain, key: str) -> dict:
    """Início da janela de leitura de uma fonte — o LLM não calcula datas, pergunta aqui.

    window = "auto": desde o último pull bem-sucedido (menos a sobreposição), com teto; falhas seguidas
    alargam a janela sozinhas porque só um pull ok move o `last_ok`. Janela fixa: agora − janela.
    """
    src = next((s for s in list_sources(brain.inst) if s.get("key") == key), None)
    if src is None:
        raise util.BrainError(f"fonte '{key}' não está no watch.toml", code=3)
    spec = str(src.get("window") or "1d")
    delta, now = parse_window(spec), util.now()
    if delta is not None:
        start, why = now - delta, f"janela fixa {spec}"
    else:
        c = brain.state.connectors.get(key)
        if c and c.last_ok:
            start = max(util.parse_dt(c.last_ok) - AUTO_OVERLAP, now - AUTO_MAX)
            why = f"desde o último pull ({c.last_ok[:16].replace('T', ' ')}), com {int(AUTO_OVERLAP.total_seconds() // 3600)}h de sobreposição"
        else:
            start, why = now - AUTO_FIRST, f"primeiro pull — {AUTO_FIRST.days}d para trás"
    return {"key": key, "window": spec, "since": start.isoformat(timespec="seconds"), "epoch": int(start.timestamp()),
            "jql": start.strftime("%Y/%m/%d %H:%M"), "hours": round((now - start).total_seconds() / 3600, 1), "why": why}


NAME_TS = [
    (re.compile(r"(\d{4})[/-](\d{2})[/-](\d{2})(?:[ T_]+(\d{1,2})[:h.](\d{2}))?"), ("y", "m", "d", "H", "M")),
    (re.compile(r"(\d{2})[/-](\d{2})[/-](\d{4})(?:[ T_]+(\d{1,2})[:h.](\d{2}))?"), ("d", "m", "y", "H", "M")),
]
FOLDER_MARGIN = "3d"   # a nota do Meet pode sair/ser editada dias depois da call


def name_timestamp(name: str):
    """Data/hora da call escrita no nome ('Retro MOps - 2026/10/16 14:00'), no fuso local. None = não achou."""
    from datetime import datetime
    for rx, order in NAME_TS:
        m = rx.search(name or "")
        if not m:
            continue
        f = dict(zip(order, m.groups()))
        try:
            return datetime(int(f["y"]), int(f["m"]), int(f["d"]), int(f["H"] or 0), int(f["M"] or 0),
                            tzinfo=util.tz())
        except ValueError:
            continue
    return None


def plan_folders(brain, key: str, folders: list[dict], margin: str = FOLDER_MARGIN, full: bool = False) -> dict:
    """Quais subpastas de uma fonte `folder` vale descer — decidido pelo carimbo do último pull, sem LLM.

    Uma subpasta é PULADA só quando a call dela (data no nome) é anterior a `since − margem` e a própria pasta
    não foi modificada desde `since`. Sem data legível no nome → desce (não dá para provar que é antiga).
    `full` desce em todas (varredura completa, p.ex. semanal ou depois de falhas).
    """
    st = since(brain, key)
    start = util.parse_dt(st["since"])
    delta = parse_window(margin)
    if delta is None:
        raise util.BrainError("margem inválida (use 12h, 3d, 1w…)", code=4)
    cutoff = start - delta
    rows = []
    for f in folders:
        name = str(f.get("name") or f.get("title") or "")
        at, mod = name_timestamp(name), f.get("modifiedTime")
        if full:
            go, why = True, "varredura completa"
        elif at is None:
            go, why = True, "sem data no nome"
        elif at >= cutoff:
            go, why = True, "call dentro da janela"
        elif mod and util.parse_dt(mod) >= start:
            go, why = True, "pasta modificada desde o último pull"
        else:
            go, why = False, "call anterior à janela"
        rows.append({"id": f.get("id", ""), "name": name, "call_at": at.isoformat(timespec="minutes") if at else None,
                     "descend": go, "why": why})
    return {"key": key, "since": st["since"], "margin": margin, "cutoff": cutoff.isoformat(timespec="minutes"),
            "full": full, "descend": sum(r["descend"] for r in rows), "skip": sum(not r["descend"] for r in rows),
            "folders": rows}


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


def drive_doc_id(ref: str) -> str | None:
    """Id do Drive a partir de uma URL (`/d/<id>`, `?id=<id>`) ou do próprio id. None = não parece do Drive."""
    ref = (ref or "").strip()
    m = DRIVE_URL_RE.search(ref)
    if m:
        return m.group(1) or m.group(2)
    return ref if DRIVE_ID_RE.match(ref) else None


def playbook_key(target: str, kind: str = "playbook") -> str:
    return f"{kind}-{target.lower()}"


def check_fields(brain, fields: dict) -> None:
    """Regras das fontes `drive-doc`: `doc` (id do Drive) e `link` (PROC-…/OPP-… que existe no ledger)."""
    if fields.get("kind") != DRIVE_DOC:
        return
    if not fields.get("doc"):
        raise util.BrainError("fonte drive-doc precisa de `doc` (id do doc no Drive)", code=4)
    if not drive_doc_id(str(fields["doc"])):
        raise util.BrainError(f"doc inválido: {fields['doc']!r} (id do Drive)", code=4)
    link = fields.get("link")
    if not link:
        raise util.BrainError("fonte drive-doc precisa de `link` (PROC-#### ou OPP-####)", code=4)
    if link not in brain.state.processes and link not in brain.state.opportunities:
        raise util.BrainError(f"link: {link!r} não existe no ledger (PROC-… ou OPP-…)", code=4)


def broken_links(brain) -> list[str]:
    """Fontes drive-doc cujo `link` não existe (mais) no ledger — para o doctor."""
    out = []
    for s in list_sources(brain.inst):
        if s.get("kind") == DRIVE_DOC:
            try:
                check_fields(brain, s)
            except util.BrainError as e:
                out.append(f"{s.get('key')}: {e}")
    return out


def link_playbook(brain, target: str, ref: str, kind: str = "playbook") -> dict:
    """`doc link --kind playbook|one-pager --watch`: cria (ou atualiza) a fonte drive-doc estável do alvo."""
    doc = drive_doc_id(ref)
    if not doc:
        raise util.BrainError(f"--watch pede um doc do Drive (URL ou id); recebi {ref!r}", code=4)
    key = playbook_key(target, kind)
    fields = {"kind": DRIVE_DOC, "doc": doc, "link": target, "note": f"{kind} de {target}"}
    check_fields(brain, fields)
    if key in {s.get("key") for s in list_sources(brain.inst)}:
        return edit(brain.inst, key, {"doc": doc, "link": target})
    return add(brain.inst, key, fields)


def unlink_playbook(brain, target: str, ref: str) -> bool:
    doc, keys = drive_doc_id(ref), {playbook_key(target, k) for k in ("playbook", "one-pager")}
    src = next((s for s in list_sources(brain.inst) if s.get("key") in keys and s.get("doc") == doc), None)
    if src is None or doc is None:
        return False
    remove(brain.inst, src["key"])
    return True


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
    elif c == "since":
        r = since(brain, args.key)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"since={r['since']} · epoch={r['epoch']} · jql=\"{r['jql']}\" · {r['hours']}h · {r['why']}")
    elif c == "folders":
        raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise util.BrainError(f"entrada não é JSON ({e})", code=2)
        items = data.get("folders", data.get("files")) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise util.BrainError("esperava uma lista JSON de subpastas [{id, name, modifiedTime?}]", code=2)
        r = plan_folders(brain, args.key, items, args.margin, args.full)
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"{r['key']} · desde {r['since'][:16].replace('T', ' ')} (corte {r['cutoff'].replace('T', ' ')}, "
                  f"margem {r['margin']}) · descer {r['descend']} · pular {r['skip']}")
            for x in r["folders"]:
                print(f"{'descer' if x['descend'] else 'pular '}\t{x['id']}\t{x['call_at'] or '—'}\t{x['name']}\t({x['why']})")
    elif c == "add":
        f = {"kind": args.kind, "window": args.window, "note": args.note, **parse_pairs(args.set)}
        check_fields(brain, {k: str(v).strip() for k, v in f.items() if v})
        add(inst, args.key, f)
        print(f"✓ fonte {args.key} adicionada ao watch.toml — o /update passa a puxá-la")
    elif c == "edit":
        f = {"kind": args.kind, "window": args.window, "note": args.note, **parse_pairs(args.set)}
        cur = next((s for s in list_sources(inst) if s.get("key") == args.key), None)
        if cur:
            merged = {**cur, **{k: str(v).strip() for k, v in f.items() if v}}
            for u in args.unset or []:
                merged.pop(u, None)
            check_fields(brain, merged)
        edit(inst, args.key, f, args.unset, args.rename)
        extra = (" · o histórico de pulls fica na key antiga" if args.rename and args.rename != args.key else "")
        print(f"✓ fonte {args.rename or args.key} atualizada{extra}")
    elif c == "remove":
        remove(inst, args.key)
        print(f"✓ fonte {args.key} removida do watch.toml — o /update deixa de puxá-la (snapshots e ledger ficam)")
