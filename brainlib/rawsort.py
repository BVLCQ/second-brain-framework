"""Organização do RAW por tipo: `RAW/<ano>/<mês>/<tipo>/<arquivo>`.

A classificação é determinística (prefixo do snapshot, depois extensão) — o mesmo arquivo cai sempre na mesma
pasta. O `/dump` pode sobrescrever com `--type` quando a leitura do conteúdo mostrar outra coisa (um `.md` solto
que é transcrição de reunião, por exemplo). Mover é a única operação: o conteúdo, e o nome, nunca mudam.

Os caminhos que o ledger já guarda (`RAW/<ano>/<mês>/<arquivo>`) não são reescritos: `resolve()` acha o arquivo
pelo nome dentro do mesmo mês quando o caminho antigo deixou de existir.
"""
from __future__ import annotations

import glob
import json
import re
import shutil
import sys
from pathlib import Path

from . import util

CATEGORIES = ("slack", "meetings", "documents", "videos", "artifacts", "notes", "images", "connectors", "github", "misc")

SNAPSHOT_PREFIXES = {"slack": "slack", "jira": "connectors", "gmail": "connectors", "gcal": "connectors",
                     "drive": "connectors", "databricks": "connectors", "github": "github"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".svg", ".tiff", ".bmp"}
DOC_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".rtf", ".txt", ".md", ".csv", ".key",
           ".pages", ".numbers"}
TRANSCRIPT_EXT = {".vtt", ".srt"}
HTML_EXT = {".html", ".htm"}
# listagem de pasta do Drive/Meet, não transcrição: fica com os conectores
_LISTING = re.compile(r"-(?:pasta|listagem)-|-gravacoes-\d{4}-\d{2}-\d{2}T", re.I)
_NOTE = re.compile(r"-\d{4}-\d{2}-\d{2}-note(?:-\d+)?\.md$")
_MONTH_DIR = re.compile(r"^\d{4}/\d{2}$")

# `--kind` do `brain artifact` → pasta (conector depende do prefixo, por isso não consta)
KIND_FOLDER = {"reuniao": "meetings", "reunião": "meetings", "documento": "documents", "nota": "notes"}


def classify(name: str) -> str:
    low = name.lower()
    if low.startswith("."):
        return "misc"
    ext = Path(low).suffix
    if _NOTE.search(low):
        return "notes"
    prefix = low.split("-", 1)[0]
    if prefix in SNAPSHOT_PREFIXES:
        if prefix == "drive" and "-meet-" in low and ext in {".md", ".txt"} | TRANSCRIPT_EXT and not _LISTING.search(low):
            return "meetings"
        return SNAPSHOT_PREFIXES[prefix]
    if ext in TRANSCRIPT_EXT:
        return "meetings"
    if ext in VIDEO_EXT:
        return "videos"
    if ext in HTML_EXT:
        return "artifacts"
    if ext in IMAGE_EXT:
        return "images"
    if ext in DOC_EXT:
        return "documents"
    return "misc"


def _free(dest_dir: Path, name: str) -> Path:
    path, stem, suffix, n = dest_dir / name, Path(name).stem, Path(name).suffix, 2
    while path.exists():
        path, n = dest_dir / f"{stem}-{n}{suffix}", n + 1
    return path


def _move(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


def archive(inst, names: list[str] | None = None, tipo: str | None = None, day=None) -> list[dict]:
    """Move itens da inbox para `RAW/<ano>/<mês>/<tipo>/`. `names` vazio = tudo que está na inbox."""
    if tipo and tipo not in CATEGORIES:
        raise util.BrainError(f"tipo inválido: {tipo} (use {', '.join(CATEGORIES)})", code=3)
    day = util.parse_date(day) if day else util.today()
    if names:
        paths = []
        for n in names:
            p = Path(n)
            if not p.is_absolute():
                p = inst.inbox / n if len(p.parts) == 1 else inst.vault / n
            if p.resolve().parent != inst.inbox.resolve() or not p.is_file():
                raise util.BrainError(f"{n}: não é um arquivo da inbox", code=3)
            paths.append(p)
    else:
        paths = sorted(p for p in inst.inbox.glob("*") if p.is_file() and not p.name.startswith("."))
    out = []
    for p in paths:
        if p.name == ".keep.md":
            continue
        t = tipo or classify(p.name)
        dest = _free(inst.vault / "RAW" / f"{day:%Y}" / f"{day:%m}" / t, p.name)
        _move(p, dest)
        out.append({"from": inst.rel(p), "to": inst.rel(dest), "type": t})
    return out


def sort_existing(inst, dry_run: bool = False) -> list[dict]:
    """Arruma o que já está solto em `RAW/<ano>/<mês>/` (layout antigo). Idempotente: pastas de tipo não são tocadas."""
    raw, out = inst.vault / "RAW", []
    if not raw.exists():
        return out
    for month in sorted(raw.glob("*/*")):
        if not month.is_dir() or not _MONTH_DIR.match(f"{month.parent.name}/{month.name}"):
            continue
        for p in sorted(month.iterdir()):
            if not p.is_file():
                continue
            t = classify(p.name)
            dest = month / t / p.name
            if dest.exists():
                out.append({"from": inst.rel(p), "to": inst.rel(dest), "type": t, "skipped": "destino já existe"})
                continue
            if not dry_run:
                _move(p, dest)
            out.append({"from": inst.rel(p), "to": inst.rel(dest), "type": t})
    if out and not dry_run:
        inst.logs.mkdir(parents=True, exist_ok=True)
        log = inst.logs / f"raw-sort-{util.now():%Y%m%dT%H%M%S}.jsonl"
        util.atomic_write(log, "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in out))
    return out


def resolve(inst, rel: str) -> Path | None:
    """O arquivo de um caminho `RAW/…` guardado no ledger, mesmo depois de ter ido para a pasta do tipo."""
    parts = Path(rel).parts
    if Path(rel).is_absolute() or ".." in parts:
        return None             # caminho do ledger é relativo ao vault; `../` sairia dele
    path = inst.vault / rel
    if path.is_file():
        return path
    if len(parts) < 2 or parts[0] != "RAW":
        return None
    name, raw = parts[-1], inst.vault / "RAW"
    scope = raw / parts[1] / parts[2] if len(parts) >= 4 and parts[1] != "inbox" else raw
    hits = sorted(scope.rglob(glob.escape(name)))
    return next((h for h in hits if h.is_file() and "inbox" not in h.relative_to(raw).parts), None)


def cli(args, brain) -> None:
    inst = brain.inst
    if args.rcmd == "archive":
        moved = archive(inst, args.files, args.type, args.date)
    elif args.rcmd == "sort":
        moved = sort_existing(inst, args.dry_run)
    else:
        found = resolve(inst, args.path)
        if found is None:
            raise util.BrainError(f"{args.path}: não consta no RAW", code=3)
        print(inst.rel(found))
        return
    if getattr(args, "json", False):
        print(json.dumps(moved, ensure_ascii=False, indent=2))
        return
    dry = getattr(args, "dry_run", False)
    for m in moved:
        mark = "·" if dry else ("!" if m.get("skipped") else "✓")
        print(f"{mark} {m['type']:<10} {m['from']} → {m['to']}" + (f"  ({m['skipped']})" if m.get("skipped") else ""))
    sys.stdout.write(f"{'(simulação) ' if dry else ''}{len(moved)} arquivo(s)\n")
