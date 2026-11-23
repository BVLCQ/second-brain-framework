"""Leitura de PDF sem dependência obrigatória — o /dump precisa do texto (e, em PDF escaneado, da imagem).

Texto: `pdftotext` (poppler) → PDFKit do macOS (via swift) → `pypdf`, se estiver instalado.
Imagem: `pdftoppm` (poppler) → PDFKit do macOS (via swift).
Nada aqui grava no vault: a saída vai para o stdout ou para uma pasta temporária; quem arquiva é o /dump.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import util
from .swift import swift_tool as _swift_tool

HINT = ("sem leitor de PDF — instale o poppler (`brew install poppler` · `apt install poppler-utils`) "
        "ou, no macOS, as Command Line Tools (`xcode-select --install`, dá o `swift`)")
PDF_TIMEOUT_S = 120
TEMP_MAX_AGE_H = 24.0


def sweep_temp_dirs(
    prefix: str,
    *,
    max_age_hours: float = TEMP_MAX_AGE_H,
    root: Path | None = None,
    now: float | None = None,
    keep: Path | None = None,
) -> int:
    """Remove diretórios temporários antigos com o prefixo dado, preservando `keep` e ignorando symlinks."""
    base = (Path(root) if root is not None else Path(tempfile.gettempdir())).resolve()
    cutoff = (time.time() if now is None else now) - max_age_hours * 3600.0
    keep_res = keep.resolve() if keep is not None else None
    removed = 0
    try:
        entries = list(base.glob(f"{prefix}*"))
    except OSError:
        return 0
    for p in entries:
        try:
            if p.is_symlink() or not p.is_dir():
                continue
            p_res = p.resolve()
            if p_res.parent != base:
                continue
            if keep_res is not None and p_res == keep_res:
                continue
            if p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def _run_pdf(args: list[str], target: str, run=None) -> subprocess.CompletedProcess:
    runner = subprocess.run if run is None else run
    try:
        return runner(args, capture_output=True, text=True, check=False, timeout=PDF_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise util.BrainError(f"tempo esgotado ({PDF_TIMEOUT_S}s) ao rodar {args[0]} em {target}", code=3)


def _err_detail(res: subprocess.CompletedProcess, fallback: str) -> str:
    raw = (res.stderr or "").strip() or (res.stdout or "").strip() or fallback
    msg = " ".join(raw.splitlines()).strip() or fallback
    return msg if len(msg) <= 300 else msg[:299] + "…"


def _warn_missing_pages(missing: list[int]) -> None:
    if missing:
        print(f"⚠ páginas sem saída (fora do documento?): {', '.join(map(str, missing))}", file=sys.stderr)

SWIFT_TEXT = r'''
import PDFKit
import Foundation
let a = CommandLine.arguments
guard a.count >= 2, let doc = PDFDocument(url: URL(fileURLWithPath: a[1])) else { exit(2) }
let wanted: Set<Int> = a.count > 2 ? Set(a[2].split(separator: ",").compactMap { Int($0) }) : []
for i in 0..<doc.pageCount where wanted.isEmpty || wanted.contains(i + 1) {
    print("=== PÁGINA \(i + 1) ===")
    print(doc.page(at: i)?.string ?? "")
}
'''

SWIFT_RENDER = r'''
import PDFKit
import AppKit
import Foundation
let a = CommandLine.arguments
guard a.count >= 4, let doc = PDFDocument(url: URL(fileURLWithPath: a[1])) else { exit(2) }
let out = a[2]
let scale = (Double(a[3]) ?? 110.0) / 72.0
let wanted: Set<Int> = a.count > 4 ? Set(a[4].split(separator: ",").compactMap { Int($0) }) : []
for i in 0..<doc.pageCount where wanted.isEmpty || wanted.contains(i + 1) {
    guard let page = doc.page(at: i) else { continue }
    let box = page.bounds(for: .mediaBox)
    let size = NSSize(width: box.width * scale, height: box.height * scale)
    let img = page.thumbnail(of: size, for: .mediaBox)
    guard let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else { continue }
    let path = out + "/pagina-" + String(format: "%03d", i + 1) + ".png"
    try? png.write(to: URL(fileURLWithPath: path))
    print(path)
}
'''


def parse_pages(spec: str | None) -> list[int]:
    """'1-3,5' → [1, 2, 3, 5]. Vazio = todas (lista vazia)."""
    if not spec:
        return []
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise util.BrainError(f"páginas inválidas: {spec!r} (ex.: 1-3,5)", code=2)
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b < a:
            raise util.BrainError(f"páginas inválidas: {spec!r}", code=2)
        out.extend(range(a, b + 1))
    return sorted(set(out))


def _check(path: Path) -> str:
    if not path.is_file():
        raise util.BrainError(f"arquivo não encontrado: {path}", code=3)
    return str(path.resolve())      # absoluto: um nome como "-foo.pdf" não vira opção do pdftotext/pdftoppm


def text(path: str | Path, pages: list[int] | None = None, run=None) -> str:
    """Texto do PDF, com `=== PÁGINA n ===` entre as páginas. Falha com a dica de instalação se nenhum leitor existir."""
    p = _check(Path(path))
    pages = pages or []
    failures: list[str] = []
    if shutil.which("pdftotext"):
        chunks: list[str] = []
        if pages:
            missing: list[int] = []
            errs: list[str] = []
            for n in pages:
                res = _run_pdf(["pdftotext", "-layout", "-f", str(n), "-l", str(n), p, "-"], p, run=run)
                if res.returncode == 0:
                    chunks.append(f"=== PÁGINA {n} ===\n{res.stdout.rstrip()}")
                else:
                    missing.append(n)
                    errs.append(_err_detail(res, f"código {res.returncode}"))
            if chunks:
                _warn_missing_pages(missing)
                return "\n".join(chunks) + "\n"
            if errs:
                failures.append(f"pdftotext: {errs[0]}")
            else:
                _warn_missing_pages(missing)
                return ""
        else:
            # Uma chamada só; o pdftotext separa páginas com \f. (Antes: um processo por página e, sem
            # `pdfinfo` no PATH, só a página 1 era lida — em silêncio.)
            res = _run_pdf(["pdftotext", "-layout", p, "-"], p, run=run)
            if res.returncode == 0:
                parts = res.stdout.split("\f")
                if len(parts) > 1 and not parts[-1].strip():
                    parts.pop()
                chunks = [f"=== PÁGINA {n} ===\n{t.rstrip()}" for n, t in enumerate(parts, start=1)]
                return ("\n".join(chunks) + "\n") if chunks else ""
            failures.append(f"pdftotext: {_err_detail(res, f'código {res.returncode}')}")
    tool = _swift_tool(SWIFT_TEXT, "pdftext")
    if tool:
        args = [*tool, p] + ([",".join(map(str, pages))] if pages else [])
        res = _run_pdf(args, p, run=run)
        if res.returncode != 0:
            failures.append(f"PDFKit: {_err_detail(res, f'código {res.returncode}')}")
        else:
            if pages:
                found = {int(m) for m in re.findall(r"^=== PÁGINA (\d+) ===$", res.stdout, re.M)}
                _warn_missing_pages([n for n in pages if n not in found])
            if res.stdout.strip():
                return res.stdout
            if pages:
                return ""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        if failures:
            raise util.BrainError(f"falha ao ler PDF ({'; '.join(failures)})", code=3) from None
        raise util.BrainError(HINT, code=3) from None
    try:
        reader = PdfReader(p)
        total = len(reader.pages)
        if pages:
            _warn_missing_pages([n for n in pages if not (1 <= n <= total)])
        want = pages or list(range(1, total + 1))
        out = "\n".join(f"=== PÁGINA {n} ===\n{reader.pages[n - 1].extract_text() or ''}"
                        for n in want if 1 <= n <= total)
        return (out + "\n") if out else ""
    except Exception as e:
        failures.append(f"pypdf: {str(e)[:300]}")
        raise util.BrainError(f"falha ao ler PDF ({'; '.join(failures)})", code=3) from None


def render(path: str | Path, pages: list[int] | None = None, out: str | Path | None = None, dpi: int = 110,
           run=None) -> list[Path]:
    """PNG de cada página pedida, numa pasta temporária (ou `out`). Para PDF escaneado, onde não há texto."""
    p = _check(Path(path))
    pages = pages or []
    if out is None:
        dest = Path(tempfile.mkdtemp(prefix="brain-pdf-"))
        sweep_temp_dirs("brain-pdf-", keep=dest)
    else:
        dest = Path(out)
    dest.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    if shutil.which("pdftoppm"):
        args = ["pdftoppm", "-png", "-r", str(dpi)]
        if pages:
            # Página a página: `-f 1 -l 50` para "1,50" renderizava as 50. Nome igual ao do PDFKit.
            got: list[Path] = []
            missing: list[int] = []
            errs: list[str] = []
            for n in pages:
                out_png = dest / f"pagina-{n:03d}"
                res = _run_pdf([*args, "-f", str(n), "-l", str(n), "-singlefile", p, str(out_png)], p, run=run)
                png = out_png.with_suffix(".png")
                if res.returncode == 0 and png.exists():
                    got.append(png)
                else:
                    missing.append(n)
                    if res.returncode != 0:
                        errs.append(_err_detail(res, f"código {res.returncode}"))
            if got:
                _warn_missing_pages(missing)
                return got
            if errs:
                failures.append(f"pdftoppm: {errs[0]}")
            else:
                _warn_missing_pages(missing)
                return []
        else:
            res = _run_pdf([*args, p, str(dest / "pagina")], p, run=run)
            if res.returncode == 0:
                return sorted(dest.glob("pagina*.png"))
            failures.append(f"pdftoppm: {_err_detail(res, f'código {res.returncode}')}")
    tool = _swift_tool(SWIFT_RENDER, "pdfrender")
    if not tool:
        if failures:
            raise util.BrainError(f"falha ao renderizar PDF ({'; '.join(failures)})", code=3)
        raise util.BrainError(HINT, code=3)
    args = [*tool, p, str(dest), str(dpi)] + ([",".join(map(str, pages))] if pages else [])
    res = _run_pdf(args, p, run=run)
    if res.returncode != 0:
        failures.append(f"PDFKit: {_err_detail(res, 'erro do PDFKit')}")
        raise util.BrainError(f"falha ao renderizar PDF ({'; '.join(failures)})", code=3)
    got = [Path(line) for line in res.stdout.splitlines() if line.strip()]
    if pages:
        found: set[int] = set()
        for path_out in got:
            m = re.search(r"pagina-(\d+)\.png$", path_out.name)
            if m:
                found.add(int(m.group(1)))
        _warn_missing_pages([n for n in pages if n not in found])
    return got


def cli(args, brain) -> None:
    pages = parse_pages(args.pages)
    if args.pcmd == "text":
        sys.stdout.write(text(args.file, pages))
    else:
        for f in render(args.file, pages, args.out, args.dpi):
            print(f)
