#!/usr/bin/env python3
"""Monta os painéis HTML (FRESH/dashboard/index.html e portfolio.html) a partir das fontes em
brainlib/assets/src/. O resultado é auto-contido (CSS+JS embutidos) e mantém o placeholder
__DATA__, que o render.py substitui pelo view model (render_html) em cada `brain render`.

Rodar depois de editar as fontes:
    python3 scripts/build_assets.py
"""
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "brainlib" / "assets" / "src"
OUT = ROOT / "brainlib" / "assets"
MARK = OUT / "icon" / "brain-mark.svg"            # marca ≤ 32 px: barra lateral + favicon (embutida: o painel abre offline)


def mark_svg() -> bytes:
    """A marca recortada no ladrilho: o arquivo guarda a margem da grade de ícones da Apple (vale para o .icns),
    mas na barra lateral essa margem só encolhia o desenho."""
    svg = MARK.read_text(encoding="utf-8")
    cropped = svg.replace('viewBox="0 0 1024 1024"', 'viewBox="96 112 832 832"', 1)
    if cropped == svg:
        raise SystemExit("brain-mark.svg sem o viewBox 1024 esperado")
    return cropped.encode("utf-8")


def assemble(pf_only: bool, title: str) -> str:
    shell = (SRC / "shell.html").read_text(encoding="utf-8")
    css = (SRC / "dashboard.css").read_text(encoding="utf-8")
    core = (SRC / "core.js").read_text(encoding="utf-8")
    extra = (SRC / "extra.js").read_text(encoding="utf-8")
    forms = (SRC / "forms.js").read_text(encoding="utf-8")       # motor dos formulários (o mesmo do brainlib/forms.py)
    html = shell.replace("<title>Brain</title>", f"<title>{title}</title>", 1)
    html = html.replace("__CSS__", css, 1)
    html = html.replace("__MARK__", "data:image/svg+xml;base64," + base64.b64encode(mark_svg()).decode("ascii"))
    # um ÚNICO bloco <script> (os testes extraem o JS com split("<script>")/rsplit("</script>"))
    # na ordem do mockup: extras primeiro, core depois; a flag da variante vem antes de tudo (e o motor dos formulários)
    js = f'window.PF_ONLY = {"true" if pf_only else "false"};\n' + forms + "\n" + extra + "\n" + core
    html = html.replace('<script>__EXTRA__</script>\n<script>__CORE__</script>', "<script>" + js + "</script>", 1)
    if "__EXTRA__" in html or "__CORE__" in html:
        raise SystemExit("placeholders de script não substituídos (shell mudou?)")
    if "__DATA__" not in html:
        raise SystemExit("placeholder __DATA__ sumiu — o render.py precisa dele")
    for ph in set(re.findall(r"__[A-Z]+__", html)):
        if ph != "__DATA__":
            raise SystemExit(f"placeholder não substituído: {ph}")
    assert all("</script" not in x for x in (core, extra, forms)), "script não pode conter </script>"
    return html


def main() -> int:
    (OUT / "dashboard.html").write_text(assemble(False, "Brain"), encoding="utf-8")
    (OUT / "portfolio.html").write_text(assemble(True, "Brain — Portfólio"), encoding="utf-8")
    for f in sorted(OUT.glob("*.html")):
        print(f"{f.name}: {f.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
