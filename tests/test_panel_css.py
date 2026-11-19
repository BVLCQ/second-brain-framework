"""Testes do CSS dos painéis HTML (#43, #44, #48, #49, #50, #51)."""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "brainlib" / "assets" / "src" / "dashboard.css"


def _parse_hex(color: str) -> tuple[int, int, int]:
    h = color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        raise ValueError(f"cor hex inválida: {color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rel_luminance(color: str) -> float:
    def _lin(ch: int) -> float:
        c = ch / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _parse_hex(color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(c1: str, c2: str) -> float:
    l1, l2 = _rel_luminance(c1), _rel_luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _mix_srgb(fg: str, bg: str, alpha: float) -> str:
    fr, fg_c, fb = _parse_hex(fg)
    br, bg_c, bb = _parse_hex(bg)
    r = round(fr * alpha + br * (1.0 - alpha))
    g = round(fg_c * alpha + bg_c * (1.0 - alpha))
    b = round(fb * alpha + bb * (1.0 - alpha))
    return f"#{r:02x}{g:02x}{b:02x}"


def _extract_root_tokens(css: str) -> dict[str, str]:
    m = re.search(r":root\s*\{([^}]+)\}", css)
    assert m, "bloco :root não encontrado"
    return {name: val.strip() for name, val in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", m.group(1))}


def _extract_rule(css: str, selector_regex: str) -> str:
    m = re.search(rf"{selector_regex}\s*\{{([^}}]+)\}}", css)
    assert m, f"regra não encontrada: {selector_regex}"
    return m.group(1)


class PanelCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.tokens = _extract_root_tokens(cls.css)

    def test_wcag_aa_contrast_all_light_root_pairs(self):
        """#44: todos os tokens de texto do :root claro atingem WCAG >= 4.5:1 sobre todos os fundos."""
        fg_tokens = ["--ink", "--muted", "--accent", "--ok", "--warn", "--risk", "--info", "--sug", "--dsug"]
        bg_tokens = ["--bg", "--panel", "--chip", "--chip2", "--okbg", "--warnbg", "--riskbg", "--infobg"]

        for fg in fg_tokens:
            self.assertIn(fg, self.tokens)
        for bg in bg_tokens:
            self.assertIn(bg, self.tokens)

        failures = []
        for fg in fg_tokens:
            for bg in bg_tokens:
                ratio = _contrast_ratio(self.tokens[fg], self.tokens[bg])
                if ratio < 4.5:
                    failures.append(f"{fg} ({self.tokens[fg]}) sobre {bg} ({self.tokens[bg]}) = {ratio:.2f}:1")

        # Contraste do texto invertido sobre --accent e do --accent sobre fundos com tint (nav ativa / hover)
        accent_ink_ratio = _contrast_ratio(self.tokens["--accent-ink"], self.tokens["--accent"])
        if accent_ink_ratio < 4.5:
            failures.append(f"--accent-ink sobre --accent = {accent_ink_ratio:.2f}:1")

        for bg in ("--bg", "--panel"):
            tinted10 = _mix_srgb(self.tokens["--accent"], self.tokens[bg], 0.10)
            r10 = _contrast_ratio(self.tokens["--accent"], tinted10)
            if r10 < 4.5:
                failures.append(f"--accent sobre tint 10% de {bg} ({tinted10}) = {r10:.2f}:1")

        tinted12 = _mix_srgb(self.tokens["--accent"], self.tokens["--panel"], 0.12)
        r12 = _contrast_ratio(self.tokens["--accent"], tinted12)
        if r12 < 4.5:
            failures.append(f"--accent sobre tint 12% de --panel ({tinted12}) = {r12:.2f}:1")

        self.assertEqual(failures, [], "Pares abaixo de WCAG 4.5:1:\n" + "\n".join(failures))

    def test_face_pill_uses_accent_ink_and_larger_font(self):
        """#43: .faces .fcur usa var(--accent-ink) e font-size 12.5px."""
        rule = _extract_rule(self.css, r"\.faces\s+\.fcur")
        self.assertIn("font-size:12.5px", rule)
        self.assertIn("color:var(--accent-ink)", rule)
        self.assertNotIn("color:#fff", rule)

    def test_project_summary_two_line_clamp(self):
        """#49: .goal .proj .t small usa clamp de 2 linhas em vez de nowrap."""
        rule = _extract_rule(self.css, r"\.goal\s+\.proj\s+\.t\s+small")
        self.assertIn("display:-webkit-box", rule)
        self.assertIn("-webkit-box-orient:vertical", rule)
        self.assertIn("-webkit-line-clamp:2", rule)
        self.assertIn("white-space:normal", rule)
        self.assertIn("overflow:hidden", rule)
        self.assertNotIn("white-space:nowrap", rule)
        self.assertNotIn("text-overflow:ellipsis", rule)

    def test_narrow_viewport_overflow_guards(self):
        """#50: grades, inputs, foco e media queries protegem 500px contra overflow horizontal."""
        g2 = _extract_rule(self.css, r"\.g2")
        g3 = _extract_rule(self.css, r"\.g3")
        mx = _extract_rule(self.css, r"\.mx")
        self.assertIn("minmax(min(400px,100%),1fr)", g2)
        self.assertIn("minmax(min(280px,100%),1fr)", g3)
        self.assertIn("repeat(2,minmax(0,1fr))", mx)

        grid_items = _extract_rule(self.css, r"\.panel,\.grid>\*,\.projcard,\.col")
        self.assertIn("min-width:0", grid_items)

        wrap_rule = _extract_rule(self.css, r"\.card-title,ul\.feed\s+li")
        self.assertIn("overflow-wrap:anywhere", wrap_rule)

        goal_head = _extract_rule(self.css, r"\.goal-head")
        self.assertIn("flex-wrap:wrap", goal_head)
        goal_div = _extract_rule(self.css, r"\.goal-head>div")
        self.assertIn("min-width:0", goal_div)
        self.assertIn("flex:1", goal_div)

        self.assertIn("min-width:min(220px,100%)", _extract_rule(self.css, r"\.ask-free\s+\.rin"))
        self.assertIn("min-width:min(190px,100%)", _extract_rule(self.css, r"\.lfbar\s+input"))

        week = _extract_rule(self.css, r"\.week")
        self.assertIn("overflow-x:auto", week)
        self.assertIn("max-width:100%", week)

        m900 = re.search(r"@media\s*\(max-width:900px\)\s*\{\n(.+?)\n\}", self.css, re.S)
        self.assertIsNotNone(m900)
        self.assertIn(".kbd-bar{left:0;flex-wrap:wrap;gap:4px 8px}", m900.group(1))

        m640 = re.search(r"@media\s*\(max-width:640px\)\s*\{\n(.+?)\n\}", self.css, re.S)
        self.assertIsNotNone(m640)
        self.assertIn(".kanban{grid-template-columns:minmax(0,1fr)}", m640.group(1))
        self.assertIn(".mx{grid-template-columns:minmax(0,1fr)}", m640.group(1))

    def test_touch_targets_at_least_24px(self):
        """#51: botões pequenos têm alvo visível >= 24px e links de pessoa expandem com ::after."""
        for sel in (r"\.console\s+header\s+\.x", r"\.lfchip\s+button"):
            rule = _extract_rule(self.css, sel)
            mh = re.search(r"min-height:\s*(\d+(?:\.\d+)?)px", rule)
            mw = re.search(r"min-width:\s*(\d+(?:\.\d+)?)px", rule)
            self.assertIsNotNone(mh, sel)
            self.assertIsNotNone(mw, sel)
            self.assertGreaterEqual(float(mh.group(1)), 24.0, sel)
            self.assertGreaterEqual(float(mw.group(1)), 24.0, sel)

        btn_tiny = _extract_rule(self.css, r"\.btn\.tiny")
        mh_tiny = re.search(r"min-height:\s*(\d+(?:\.\d+)?)px", btn_tiny)
        self.assertIsNotNone(mh_tiny)
        self.assertGreaterEqual(float(mh_tiny.group(1)), 24.0)

        person_link = _extract_rule(self.css, r'a\[href\^="#person/"\]')
        self.assertIn("position:relative", person_link)
        self.assertIn("display:inline-block", person_link)

        person_after = _extract_rule(self.css, r'a\[href\^="#person/"\]::after')
        self.assertIn('content:""', person_after)
        self.assertIn("position:absolute", person_after)
        self.assertIn("inset:-6px -2px", person_after)

    def test_h2_preparatory_selectors_for_issue48(self):
        """#48: seletores preparatórios de h2 preservam escopo sem alterar visual."""
        self.assertIn(".panel > h2:first-child{margin-top:0}", self.css)
        self.assertNotIn(".panel h2:first-child{margin-top:0}", self.css)
        self.assertIn(".col h2, .col h3{", self.css)
        self.assertIn(".pf-col.lat h2, .pf-col.lat h3{color:var(--muted)}", self.css)
        self.assertIn(".wday h2, .wday h3{", self.css)

    def test_built_html_assets_match_build_assets(self):
        """dashboard.html e portfolio.html estão sincronizados com dashboard.css via build_assets.py."""
        spec = importlib.util.spec_from_file_location("build_assets", ROOT / "scripts" / "build_assets.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        self.assertEqual(
            (ROOT / "brainlib" / "assets" / "dashboard.html").read_text(encoding="utf-8"),
            mod.assemble(False, "Brain"),
        )
        self.assertEqual(
            (ROOT / "brainlib" / "assets" / "portfolio.html").read_text(encoding="utf-8"),
            mod.assemble(True, "Brain — Portfólio"),
        )


if __name__ == "__main__":
    unittest.main()
