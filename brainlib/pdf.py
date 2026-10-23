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
from pathlib import Path

from . import util
from .swift import swift_tool as _swift_tool

HINT = ("sem leitor de PDF — instale o poppler (`brew install poppler` · `apt install poppler-utils`) "
        "ou, no macOS, as Command Line Tools (`xcode-select --install`, dá o `swift`)")

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


def text(path: str | Path, pages: list[int] | None = None) -> str:
    """Texto do PDF, com `=== PÁGINA n ===` entre as páginas. Falha com a dica de instalação se nenhum leitor existir."""
    p = _check(Path(path))
    pages = pages or []
    if shutil.which("pdftotext"):
        chunks = []
        if pages:
            for n in pages:
                res = subprocess.run(["pdftotext", "-layout", "-f", str(n), "-l", str(n), p, "-"],
                                     capture_output=True, text=True, check=False)
                if res.returncode == 0:
                    chunks.append(f"=== PÁGINA {n} ===\n{res.stdout.rstrip()}")
        else:
            # Uma chamada só; o pdftotext separa páginas com \f. (Antes: um processo por página e, sem
            # `pdfinfo` no PATH, só a página 1 era lida — em silêncio.)
            res = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                parts = res.stdout.split("\f")
                if len(parts) > 1 and not parts[-1].strip():
                    parts.pop()
                chunks = [f"=== PÁGINA {n} ===\n{t.rstrip()}" for n, t in enumerate(parts, start=1)]
        if chunks:
            return "\n".join(chunks) + "\n"
    tool = _swift_tool(SWIFT_TEXT, "pdftext")
    if tool:
        args = [*tool, p] + ([",".join(map(str, pages))] if pages else [])
        res = subprocess.run(args, capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        raise util.BrainError(HINT, code=3) from None
    reader = PdfReader(p)
    want = pages or list(range(1, len(reader.pages) + 1))
    return "\n".join(f"=== PÁGINA {n} ===\n{reader.pages[n - 1].extract_text() or ''}"
                     for n in want if 1 <= n <= len(reader.pages)) + "\n"


def render(path: str | Path, pages: list[int] | None = None, out: str | Path | None = None, dpi: int = 110) -> list[Path]:
    """PNG de cada página pedida, numa pasta temporária (ou `out`). Para PDF escaneado, onde não há texto."""
    p = _check(Path(path))
    pages = pages or []
    dest = Path(out) if out else Path(tempfile.mkdtemp(prefix="brain-pdf-"))
    dest.mkdir(parents=True, exist_ok=True)
    if shutil.which("pdftoppm"):
        args = ["pdftoppm", "-png", "-r", str(dpi)]
        if pages:
            # Página a página: `-f 1 -l 50` para "1,50" renderizava as 50. Nome igual ao do PDFKit.
            got = []
            for n in pages:
                out_png = dest / f"pagina-{n:03d}"
                res = subprocess.run([*args, "-f", str(n), "-l", str(n), "-singlefile", p, str(out_png)],
                                     capture_output=True, text=True, check=False)
                if res.returncode == 0 and out_png.with_suffix(".png").exists():
                    got.append(out_png.with_suffix(".png"))
            if got:
                return got
        else:
            res = subprocess.run([*args, p, str(dest / "pagina")], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                return sorted(dest.glob("pagina*.png"))
    tool = _swift_tool(SWIFT_RENDER, "pdfrender")
    if not tool:
        raise util.BrainError(HINT, code=3)
    args = [*tool, p, str(dest), str(dpi)] + ([",".join(map(str, pages))] if pages else [])
    res = subprocess.run(args, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise util.BrainError(f"não consegui renderizar o PDF: {res.stderr.strip() or 'erro do PDFKit'}", code=3)
    return [Path(line) for line in res.stdout.splitlines() if line.strip()]


def cli(args, brain) -> None:
    pages = parse_pages(args.pages)
    if args.pcmd == "text":
        sys.stdout.write(text(args.file, pages))
    else:
        for f in render(args.file, pages, args.out, args.dpi):
            print(f)
