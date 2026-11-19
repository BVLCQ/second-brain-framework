"""Testes de higiene do CSS dos painéis HTML (#53)."""
from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS_SRC = ROOT / "brainlib" / "assets" / "src"
CSS_PATH = ASSETS_SRC / "dashboard.css"

ALLOWED_FONT_SIZES = {"10.5px", "11.5px", "12.5px", "14px", "16px", "20px", "26px"}
LAYOUT_ONLY_TOKENS = {"--r", "--side"}


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _parse_rules(css: str, scope: str = "root") -> tuple[list[tuple[str, str, str]], list[str]]:
    """Extrai (escopo, seletor, corpo) e condições @media preservando a ordem da cascata."""
    text = _strip_comments(css)
    i = 0
    n = len(text)
    rules: list[tuple[str, str, str]] = []
    media_scopes: list[str] = []
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        brace = text.find("{", i)
        if brace == -1:
            break
        sel = " ".join(text[i:brace].split())
        depth = 1
        j = brace + 1
        while j < n and depth > 0:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[brace + 1 : j - 1]
        if sel.startswith("@media"):
            media_scopes.append(sel)
            sub_rules, sub_media = _parse_rules(body, scope=sel)
            rules.extend(sub_rules)
            media_scopes.extend(sub_media)
        else:
            rules.append((scope, sel, body))
        i = j
    return rules, media_scopes


def _parse_declarations(body: str) -> list[tuple[str, str]]:
    decls: list[tuple[str, str]] = []
    for raw in body.split(";"):
        item = raw.strip()
        if not item or ":" not in item:
            continue
        prop, val = item.split(":", 1)
        decls.append((prop.strip(), " ".join(val.split())))
    return decls


def _expand_box(prop: str, val: str) -> dict[str, str]:
    parts = val.split()
    if len(parts) == 1:
        t = r = b = l = parts[0]
    elif len(parts) == 2:
        t = b = parts[0]
        r = l = parts[1]
    elif len(parts) == 3:
        t, r, b, l = parts[0], parts[1], parts[2], parts[1]
    elif len(parts) == 4:
        t, r, b, l = parts[0], parts[1], parts[2], parts[3]
    else:
        return {prop: val}
    if prop == "inset":
        return {"top": t, "right": r, "bottom": b, "left": l}
    return {f"{prop}-top": t, f"{prop}-right": r, f"{prop}-bottom": b, f"{prop}-left": l}


def _expand_declaration(prop: str, val: str) -> dict[str, str]:
    if prop in ("padding", "margin", "inset"):
        return _expand_box(prop, val)
    if prop == "font" and val != "inherit":
        m = re.search(r"(\d+(?:\.\d+)?px)(?:/([^\s]+))?", val)
        out = {"font": val}
        if m:
            out["font-size"] = m.group(1)
            if m.group(2):
                out["line-height"] = m.group(2)
        return out
    return {prop: val}


def _dedupe_rules(rules: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Funde seletores repetidos no mesmo escopo preservando o último valor da cascata."""
    merged: dict[tuple[str, str], dict[str, str]] = {}
    order: list[tuple[str, str]] = []
    for scope, sel, body in rules:
        key = (scope, sel)
        if key not in merged:
            merged[key] = {}
            order.append(key)
        props = merged[key]
        for prop, val in _parse_declarations(body):
            # Reinsere a chave no fim para preservar ordem de declaração (ex.: padding antes de padding-bottom)
            if prop in props:
                del props[prop]
            props[prop] = val
    return [
        (scope, sel, ";".join(f"{k}:{v}" for k, v in merged[(scope, sel)].items()))
        for scope, sel in order
    ]


def _selector_specificity(sel: str) -> tuple[int, int, int]:
    """Calcula a especificidade CSS (id, class/attr/pseudo-class, tag/pseudo-el)."""
    s = re.sub(r"\[[^\]]*\]", " .attr ", sel)
    ids = len(re.findall(r"#[a-zA-Z0-9_-]+", s))
    s = re.sub(r"#[a-zA-Z0-9_-]+", " ", s)
    pseudo_els = len(re.findall(r"::[a-zA-Z0-9_-]+|(?<!:):(?:before|after)\b", s))
    s = re.sub(r"::[a-zA-Z0-9_-]+|(?<!:):(?:before|after)\b", " ", s)
    classes = len(re.findall(r"\.[a-zA-Z0-9_-]+", s))
    s = re.sub(r"\.[a-zA-Z0-9_-]+", " ", s)
    pseudo_cls = len(re.findall(r":[a-zA-Z0-9_-]+(?:\([^)]*\))?", s))
    s = re.sub(r":[a-zA-Z0-9_-]+(?:\([^)]*\))?", " ", s)
    tags = len(re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]*\b", s))
    return (ids, classes + pseudo_cls, tags + pseudo_els)


def _computed_for_selectors(
    rules: list[tuple[str, str, str]],
    matching_selectors: set[str],
    active_scopes: tuple[str, ...],
) -> dict[str, str]:
    """Avalia propriedades computadas expandidas por especificidade e ordem de cascata."""
    matched: list[tuple[tuple[int, int, int], int, str]] = []
    for idx, (scope, sel, body) in enumerate(rules):
        if scope not in active_scopes:
            continue
        parts = [" ".join(p.split()) for p in sel.split(",")]
        specs = [_selector_specificity(p) for p in parts if p in matching_selectors]
        if specs:
            matched.append((max(specs), idx, body))
    matched.sort(key=lambda item: (item[0], item[1]))
    computed: dict[str, str] = {}
    for _, _, body in matched:
        for prop, val in _parse_declarations(body):
            computed.update(_expand_declaration(prop, val))
    return computed


class CssHygieneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.rules, cls.media_scopes = _parse_rules(cls.css)

    def test_no_duplicate_selectors_per_scope(self):
        """1. Zero seletores duplicados no mesmo escopo raiz/@media e zero @media repetidos."""
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for scope, sel, _ in self.rules:
            counts[(scope, sel)] += 1
        dups = {k: v for k, v in counts.items() if v > 1}
        self.assertEqual(dups, {}, f"Seletores duplicados encontrados: {dups}")

        media_counts = {m: self.media_scopes.count(m) for m in set(self.media_scopes) if self.media_scopes.count(m) > 1}
        self.assertEqual(media_counts, {}, f"Blocos @media duplicados encontrados: {media_counts}")

    def test_no_literal_colors_outside_theme_blocks(self):
        """2. Zero literais #hex ou rgb/rgba fora de :root e html[data-theme=dark]."""
        offenders = []
        for scope, sel, body in self.rules:
            if sel in (":root", "html[data-theme=dark]"):
                continue
            hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
            rgbs = re.findall(r"rgba?\([^)]+\)", body)
            if hexes or rgbs:
                offenders.append((scope, sel, hexes, rgbs))
        self.assertEqual(offenders, [], f"Cores literais fora dos blocos de tema: {offenders}")

        # Verifica uso explícito dos tokens esperados
        by_sel = {(scope, sel): body for scope, sel, body in self.rules}
        self.assertIn("color:var(--accent-ink)", by_sel[("root", ".brand .mark")])
        self.assertIn("color:var(--accent-ink)", by_sel[("root", ".clidot .conbadge")])
        self.assertIn("background:var(--dsug)", by_sel[("root", ".tl .k-decisão:before")])
        self.assertIn("background:var(--backdrop)", by_sel[("root", ".pal-back")])
        self.assertIn("box-shadow:var(--console-shadow)", by_sel[("root", ".console")])

    def test_no_dead_tokens_and_theme_parity(self):
        """3. Zero tokens --* não referenciados nos assets (CSS/JS/HTML) e paridade claro/escuro."""
        by_sel = {sel: body for scope, sel, body in self.rules if scope == "root"}
        root_tokens = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", by_sel[":root"]))
        dark_tokens = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", by_sel["html[data-theme=dark]"]))

        self.assertEqual(set(dark_tokens) - set(root_tokens), set())
        self.assertEqual(set(root_tokens) - set(dark_tokens) - LAYOUT_ONLY_TOKENS, set())

        referenced: set[str] = set()
        for name in ("dashboard.css", "core.js", "extra.js", "forms.js", "shell.html"):
            content = (ASSETS_SRC / name).read_text(encoding="utf-8")
            referenced.update(re.findall(r"var\(\s*(--[a-z0-9-]+)", content))

        declared = set(root_tokens) | set(dark_tokens)
        dead = sorted(declared - referenced)
        self.assertEqual(dead, [], f"Tokens CSS mortos: {dead}")

    def test_closed_typographic_scale(self):
        """4. 100% dos font-size (incluindo shorthand font:) pertencem à escala fechada."""
        out_of_scale = []
        seen_sizes: set[str] = set()
        for scope, sel, body in self.rules:
            for prop, val in _parse_declarations(body):
                if prop == "font-size":
                    seen_sizes.add(val)
                    if val not in ALLOWED_FONT_SIZES:
                        out_of_scale.append((scope, sel, prop, val))
                elif prop == "font":
                    if val == "inherit":
                        continue
                    m = re.search(r"(\d+(?:\.\d+)?px)", val)
                    if not m:
                        out_of_scale.append((scope, sel, prop, val))
                    else:
                        seen_sizes.add(m.group(1))
                        if m.group(1) not in ALLOWED_FONT_SIZES:
                            out_of_scale.append((scope, sel, prop, val))

        self.assertEqual(out_of_scale, [], f"Tamanhos fora da escala fechada: {out_of_scale}")
        self.assertTrue(seen_sizes.issubset(ALLOWED_FONT_SIZES))

        # Hierarquia esperada: h1 (20) < .kpi b (26); h2/h2.sec (16) > body (14) > meta (12.5/11.5)
        h1_style = _computed_for_selectors(self.rules, {"h1"}, ("root",))
        kpi_style = _computed_for_selectors(self.rules, {".kpi b"}, ("root",))
        h2_style = _computed_for_selectors(self.rules, {"h2"}, ("root",))
        body_style = _computed_for_selectors(self.rules, {"body"}, ("root",))
        self.assertEqual(h1_style["font-size"], "20px")
        self.assertEqual(kpi_style["font-size"], "26px")
        self.assertEqual(h2_style["font-size"], "16px")
        self.assertEqual(body_style["font-size"], "14px")

    def test_computed_styles_preserved_after_dedupe(self):
        """5. Estilos computados preservados após dedupe, incluindo ::after e alvos >= 24px."""
        # Simula estado pré-dedupe (main.col dividido + @media 900px dividido) e verifica equivalência
        synthetic_pre = [
            ("root", "main.col", "min-width:0;padding:22px 28px 80px"),
            ("root", ".panel,.grid>*,.projcard,.col", "min-width:0"),
            ("root", ".toprow", "display:flex;justify-content:flex-end;align-items:center;padding:10px 14px 0;gap:10px"),
            ("@media (max-width:900px)", ".toprow", "justify-content:space-between"),
            ("root", "main.col", "padding-bottom:120px"),
            ("@media (max-width:900px)", "main.col", "padding:16px 14px 120px"),
        ]
        synthetic_post = _dedupe_rules(synthetic_pre)

        for scopes in (("root",), ("root", "@media (max-width:900px)")):
            for match in ({"main.col", ".col"}, {".toprow"}):
                self.assertEqual(
                    _computed_for_selectors(synthetic_pre, match, scopes),
                    _computed_for_selectors(synthetic_post, match, scopes),
                )

        # Confirma na stylesheet real: main.col desktop e mobile, .toprow, #person::after e alvos >=24px
        col_desktop = _computed_for_selectors(self.rules, {"main.col", ".col"}, ("root",))
        self.assertEqual(col_desktop["padding-top"], "22px")
        self.assertEqual(col_desktop["padding-right"], "28px")
        self.assertEqual(col_desktop["padding-bottom"], "120px")
        self.assertEqual(col_desktop["padding-left"], "28px")
        self.assertEqual(col_desktop["min-width"], "0")

        col_mobile = _computed_for_selectors(self.rules, {"main.col", ".col"}, ("root", "@media (max-width:900px)"))
        self.assertEqual(col_mobile["padding-top"], "16px")
        self.assertEqual(col_mobile["padding-right"], "14px")
        self.assertEqual(col_mobile["padding-bottom"], "120px")
        self.assertEqual(col_mobile["padding-left"], "14px")

        toprow_mobile = _computed_for_selectors(self.rules, {".toprow"}, ("root", "@media (max-width:900px)"))
        self.assertEqual(toprow_mobile["justify-content"], "space-between")

        person_after = _computed_for_selectors(self.rules, {'a[href^="#person/"]::after'}, ("root",))
        self.assertEqual(person_after["content"], '""')
        self.assertEqual(person_after["position"], "absolute")
        self.assertEqual(person_after["top"], "-6px")
        self.assertEqual(person_after["right"], "-2px")
        self.assertEqual(person_after["bottom"], "-6px")
        self.assertEqual(person_after["left"], "-2px")

        btn_tiny = _computed_for_selectors(self.rules, {".btn", ".btn.tiny"}, ("root",))
        self.assertGreaterEqual(float(btn_tiny["min-height"].removesuffix("px")), 24.0)

        con_close = _computed_for_selectors(self.rules, {".console header .x"}, ("root",))
        self.assertGreaterEqual(float(con_close["min-width"].removesuffix("px")), 24.0)
        self.assertGreaterEqual(float(con_close["min-height"].removesuffix("px")), 24.0)


if __name__ == "__main__":
    unittest.main()
