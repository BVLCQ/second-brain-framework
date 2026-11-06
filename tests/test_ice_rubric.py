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
