"""Rubric do ICE (brainlib/ice_rubric.py): estrutura, rótulos, genericidade e fonte única."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import ice_rubric  # noqa: E402


class CliAndModelTests(unittest.TestCase):
    """F1: `brain opportunity rubric`, o model carregando o rubric e o score seguindo 1–5."""

    def setUp(self):
        import argparse
        import contextlib
        import io
        import tempfile
        from brainlib import demo as demo_mod
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "inst"
        with contextlib.redirect_stdout(io.StringIO()):
            demo_mod.cli(argparse.Namespace(dir=str(self.root), open=False))

    def _run(self, *argv):
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "brain"), "opportunity", *argv],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_rubric_cli_prints_the_three_tables(self):
        out = self._run("rubric")
        for ax in ice_rubric.AXES:
            self.assertIn(ice_rubric.RUBRIC[ax]["question"], out)
        md = self._run("rubric", "--md")
        self.assertIn("| Nota | Critério |", md)
        self.assertIn(ice_rubric.as_markdown().strip(), md.strip())

    def test_rubric_json_has_fifteen_levels(self):
        import json
        d = json.loads(self._run("rubric", "--json"))
        self.assertEqual(sum(len(v["levels"]) for v in d["axes"].values()), 15)
        self.assertEqual(set(d["axes"]), set(ice_rubric.AXES))

    def test_view_model_carries_the_rubric(self):
        from brainlib import config, model, render_portfolio
        from brainlib.core import Brain
        b = Brain(config.load(self.root))
        m = model.build(b)
        self.assertIn("ice_rubric", m["portfolio"])
        self.assertEqual(list(m["portfolio"]["ice_rubric"]["axes"]), list(ice_rubric.AXES))
        self.assertIn("ice_rubric", render_portfolio.html_payload(m)["portfolio"])   # o mapa também leva

    def test_rendered_panel_payload_carries_rubric(self):
        from brainlib import config, render
        from brainlib.core import Brain
        b = Brain(config.load(self.root))
        report = render.render_all(b, do_harvest=False)
        html = Path(report["dashboard"]).read_text(encoding="utf-8")
        self.assertNotIn("__DATA__", html)
        self.assertIn("ice_rubric", html)                                               # payload embutido
        self.assertIn("iceHelpOverlay", html)                                          # metodologia no JS
        self.assertIn("stackHelp", html)                                               # overlay empilhável
        pf = Path(report["portfolio"]).read_text(encoding="utf-8")                     # o mapa leva o mesmo rubric
        self.assertIn("ice_rubric", pf)

    def test_built_panels_ship_the_methodology(self):
        for name in ("dashboard.html", "portfolio.html"):
            html = (ROOT / "brainlib" / "assets" / name).read_text(encoding="utf-8")
            self.assertIn("iceHelpOverlay", html, name)
            self.assertIn("? orientações", html, name)      # botão de ajuda no diálogo do ICE
            self.assertIn("— escolha —", html, name)        # opção vazia do dropdown
            self.assertIn(".icerub", html, name)            # tabela da metodologia

    def test_score_out_of_scale_error_points_to_rubric(self):
        from brainlib import config, util
        from brainlib.core import Brain
        from brainlib.schema import validate
        b = Brain(config.load(self.root))
        oid = sorted(b.state.opportunities)[0]
        with self.assertRaises(util.BrainError) as ctx:
            validate({"type": "opportunity.scored", "id": oid, "by": "owner", "prov": "declarado",
                      "date": "2026-10-09", "data": {"impact": 9, "confidence": 3, "ease": 3}}, b.state, b.plan)
        self.assertIn("brain opportunity rubric", str(ctx.exception))


class RubricTests(unittest.TestCase):
    def test_three_axes_five_levels_each(self):
        for ax in ice_rubric.AXES:
            r = ice_rubric.RUBRIC[ax]
            self.assertEqual(sorted(r["levels"]), [1, 2, 3, 4, 5], ax)
            for n, lv in r["levels"].items():
                self.assertTrue(lv["criterion"].strip(), f"{ax}.{n} sem critério")
                self.assertTrue(lv["anchor"].strip(), f"{ax}.{n} sem âncora")
                self.assertTrue(lv["link"].strip(), f"{ax}.{n} sem vínculo")
            self.assertTrue(r["question"].endswith("?"), ax)
            self.assertTrue(r["rules"], ax)

    def test_dropdown_labels_unique_and_short(self):
        for ax in ice_rubric.AXES:
            opts = ice_rubric.options(ax)
            self.assertEqual(len(opts), 6, ax)                       # vazia + 5 notas
            self.assertEqual(opts[0], ("", "— escolha —"), ax)
            self.assertEqual([v for v, _ in opts[1:]], ["5", "4", "3", "2", "1"], ax)   # 5 → 1
            labels = [lab for _, lab in opts[1:]]
            self.assertEqual(len(set(labels)), 5, ax)
            for lab in labels:
                self.assertLessEqual(len(lab), 56, f"{ax}: rótulo longo demais ({len(lab)}): {lab}")
                self.assertTrue(lab[0].isdigit() and " · " in lab, f"{ax}: rótulo sem nota: {lab}")

    def test_describe_joins_criterion_and_anchor(self):
        self.assertIn("mais de 40h", ice_rubric.describe("impact", 5))
        self.assertIn("[doc]", ice_rubric.describe("confidence", 5))
        self.assertIn("dias", ice_rubric.describe("ease", 5))
        self.assertEqual(ice_rubric.describe("impact", 9), "")
        with self.assertRaises(KeyError):
            ice_rubric.options("tamanho")

    def test_hint_from_hours_bands(self):
        self.assertEqual(ice_rubric.hint_from_hours(None), None)
        self.assertEqual(ice_rubric.hint_from_hours(41), 5)
        self.assertEqual(ice_rubric.hint_from_hours(40), 4)
        self.assertEqual(ice_rubric.hint_from_hours(20), 4)
        self.assertEqual(ice_rubric.hint_from_hours(19.5), 3)
        self.assertEqual(ice_rubric.hint_from_hours(10), 3)
        self.assertEqual(ice_rubric.hint_from_hours(5), 2)
        self.assertEqual(ice_rubric.hint_from_hours(4.9), 1)
        self.assertEqual(ice_rubric.hint_from_hours(0), 1)

    def test_as_markdown_has_all_levels_no_empty_cells(self):
        md = ice_rubric.as_markdown()
        for ax in ice_rubric.AXES:
            r = ice_rubric.RUBRIC[ax]
            self.assertIn(r["question"], md)
            for n, lv in r["levels"].items():
                self.assertIn(lv["criterion"], md)
                self.assertIn(lv["anchor"], md)
                self.assertIn(lv["link"], md)
        self.assertNotIn("||", md)                                   # célula vazia em tabela
        for k, t in ice_rubric.SUCCESS_MEASURES:
            self.assertIn(f"({k}) {t}", md)

    def test_as_dict_is_jsonable_and_ordered(self):
        import json
        d = json.loads(json.dumps(ice_rubric.as_dict()))
        self.assertEqual(list(d["axes"]), list(ice_rubric.AXES))
        for ax in ice_rubric.AXES:
            self.assertEqual([lv["n"] for lv in d["axes"][ax]["levels"]], [5, 4, 3, 2, 1], ax)
            self.assertEqual(len(d["axes"][ax]["levels"]), 5, ax)

    def test_as_text_mentions_every_axis(self):
        txt = ice_rubric.as_text()
        for ax in ice_rubric.AXES:
            self.assertIn(ice_rubric.RUBRIC[ax]["question"], txt)

    def test_module_has_no_ui_dependencies(self):
        src = (ROOT / "brainlib" / "ice_rubric.py").read_text(encoding="utf-8")
        for forbidden in ("import textual", "from textual", "import rich", "from rich"):
            self.assertNotIn(forbidden, src)

    def test_generic_for_the_public_repo(self):
        """O rubric é do framework público: nada do dono sobe (porta 5)."""
        everything = ice_rubric.as_markdown() + ice_rubric.as_text() + repr(ice_rubric.as_dict())
        forbidden = ["Projeto 2", "CAC", "45 dias", "PROJ-", "OPP-", "TASK-", "DEC-",
                     "marina", "heitor", "sonia", "caio", "voce", "example", "bvlcq", "/Users/"]
        for token in forbidden:
            self.assertNotIn(token, everything, f"token dono no rubric: {token}")


if __name__ == "__main__":
    unittest.main()
