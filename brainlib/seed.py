"""Backfill de histórico a partir de uma pasta local para a inbox (com data de captura original)."""
from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

from . import pdf, snapshot, util

SUPPORTED_EXTS = {".md", ".txt", ".docx", ".pdf"}
DEFAULT_LIMIT = 30
KINDS = ("nota", "documento")
MAX_DOCX_XML_BYTES = 10 * 1024 * 1024
_FORBIDDEN_XML_RE = re.compile(rb"<!(?:DOCTYPE|ENTITY)\b", re.I)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("word/document.xml")
        if info.file_size > MAX_DOCX_XML_BYTES:
            raise util.BrainError("word/document.xml excede o limite de 10 MB", code=4)
        with zf.open(info) as member:
            xml_bytes = member.read(MAX_DOCX_XML_BYTES + 1)
    if len(xml_bytes) > MAX_DOCX_XML_BYTES:
        raise util.BrainError("word/document.xml excede o limite de 10 MB", code=4)
    if _FORBIDDEN_XML_RE.search(xml_bytes):
        raise util.BrainError("DOCX contém declarações XML não permitidas (DOCTYPE/ENTITY)", code=4)
    # Nota de auditoria (#81 — registro): `xml.etree.ElementTree.fromstring` lê DOCX local do dono
    # já filtrado por `_FORBIDDEN_XML_RE` (bloqueia `<!DOCTYPE`/`<!ENTITY>`) e pelo teto
    # `MAX_DOCX_XML_BYTES` (10 MB); sem parser XML externo para manter o núcleo stdlib-only.
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise util.BrainError(f"XML inválido em word/document.xml: {e}", code=3) from e
    paras: list[str] = []
    for el in root.iter():
        if _local_tag(el.tag) == "p":
            txt = "".join(t.text or "" for t in el.iter() if _local_tag(t.tag) == "t")
            if txt.strip():
                paras.append(txt.strip())
    return "\n\n".join(paras)


def _read_pdf(path: Path, pdf_extractor=None) -> str:
    extractor = pdf_extractor or pdf.text
    raw = extractor(path) or ""
    meaningful = re.sub(r"^=== PÁGINA \d+ ===$", "", raw, flags=re.MULTILINE).strip()
    if not meaningful:
        raise util.BrainError("PDF sem texto extraível", code=3)
    return raw


def _extract(path: Path, pdf_extractor=None) -> str:
    ext = path.suffix.lower()
    if ext in (".md", ".txt"):
        return _read_text(path)
    if ext == ".docx":
        return _read_docx(path)
    if ext == ".pdf":
        return _read_pdf(path, pdf_extractor=pdf_extractor)
    raise util.BrainError(f"extensão não suportada: {ext}", code=2)


def _collect_files(folder: Path) -> list[tuple[float, str, Path, os.stat_result]]:
    items: list[tuple[float, str, Path, os.stat_result]] = []
    for root, dirs, filenames in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in filenames:
            if name.startswith("."):
                continue
            p = Path(root) / name
            if p.suffix.lower() not in SUPPORTED_EXTS or not p.is_file():
                continue
            rel = p.relative_to(folder)
            if any(part.startswith(".") for part in rel.parts):
                continue
            st = p.stat()
            items.append((st.st_mtime, rel.as_posix(), p, st))
    items.sort(key=lambda it: (it[0], it[1]))
    return items


def seed_folder(brain, folder: Path, *, limit: int = DEFAULT_LIMIT, kind: str = "documento",
                pdf_extractor=None, progress_cb=None) -> dict:
    """Importa arquivos de uma pasta local para `RAW/inbox/` preservando `mtime` e respeitando lote retomável."""
    folder = Path(folder)
    if not folder.exists() or not folder.is_dir():
        raise util.BrainError(f"pasta não encontrada ou não é diretório: {folder}", code=3)
    if kind not in KINDS:
        raise util.BrainError(f"kind inválido: {kind!r} (use {', '.join(KINDS)})", code=2)
    if limit < 0:
        raise util.BrainError(f"--limit deve ser >= 0 (recebido: {limit})", code=2)
    f_res = folder.resolve()
    v_res = brain.inst.vault.resolve()
    if f_res == v_res or f_res.is_relative_to(v_res) or v_res.is_relative_to(f_res):
        raise util.BrainError(
            "pasta não pode coincidir com o vault, ser pai ou subpasta dele (risco de auto-ingestão)",
            code=4,
        )

    candidates = _collect_files(f_res)
    total_found = len(candidates)
    key = f"seed-folder:{util.slugify(f_res.name, 32)}"
    imported = 0
    skipped_unchanged = 0
    remaining = 0
    errors: list[dict[str, str]] = []
    files: list[dict[str, str]] = []

    for idx, (mtime, rel_posix, path, _st) in enumerate(candidates):
        try:
            text = _extract(path, pdf_extractor=pdf_extractor)
        except Exception as e:
            errors.append({"path": rel_posix, "error": str(e)})
            continue

        mtime_dt = datetime.fromtimestamp(mtime, util.tz())
        content = f"_pull: seed-folder · kind={kind} · origem={rel_posix}\n\n{text}"
        try:
            res = snapshot.take(
                brain,
                key=key,
                content=content,
                ext="md",
                item=rel_posix,
                name=path.stem,
                captured_at=mtime_dt,
            )
        except Exception as e:
            errors.append({"path": rel_posix, "error": str(e)})
            continue

        if res.get("changed"):
            imported += 1
            files.append({
                "src": rel_posix,
                "snapshot": brain.inst.rel(res["path"]),
                "captured_at": mtime_dt.isoformat(),
            })
            if progress_cb:
                pool = max(imported, total_found - skipped_unchanged - len(errors))
                target_batch = min(limit, pool) if limit > 0 else pool
                progress_cb(imported, target_batch, rel_posix)
            if limit > 0 and imported >= limit:
                remaining = total_found - (idx + 1)
                break
        elif not res.get("failed"):
            skipped_unchanged += 1
        else:
            err_msg = (res.get("event") or {}).get("data", {}).get("error") or "falha no snapshot"
            errors.append({"path": rel_posix, "error": err_msg})

    return {
        "folder": str(f_res),
        "kind": kind,
        "limit": limit,
        "total_found": total_found,
        "imported": imported,
        "skipped_unchanged": skipped_unchanged,
        "remaining": remaining,
        "errors": errors,
        "files": files,
    }


def cli(args, brain) -> None:
    if args.scmd != "folder":
        raise util.BrainError(f"subcomando desconhecido: {args.scmd}", code=2)
    cb = None
    if not args.json:
        def cb(done: int, total: int, rel_posix: str) -> None:
            print(f"[{done}/{total}] importado: {rel_posix}", flush=True)
    res = seed_folder(brain, Path(args.path), limit=args.limit, kind=args.kind, progress_cb=cb)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    if res["imported"] == 0 and res["remaining"] == 0 and not res["errors"]:
        print("✓ pasta já sincronizada (nada novo)")
        return
    print(
        f"✓ {res['imported']} importado(s), {res['skipped_unchanged']} inalterado(s), "
        f"{res['remaining']} restante(s)"
    )
    for err in res["errors"]:
        print(f"⚠ erro em {err['path']}: {err['error']}", file=sys.stderr)
    if res["remaining"] > 0:
        print(f"→ há {res['remaining']} arquivo(s) restante(s): rode o mesmo comando novamente para continuar")
    if res["imported"] > 0:
        print("→ rode /dump para processar os arquivos na inbox")
