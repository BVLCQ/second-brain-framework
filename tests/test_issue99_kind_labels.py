"""Testes do mapa de rótulos do tipo de oportunidade (Issue #99, opção A).

O slug segue como valor no CLI/ledger; o rótulo humano aparece em toda superfície
de exibição: ficha do painel (payload kind_label + fallback), ficha da TUI e
formulários (choices rotuladas, Python e JS).
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib.schema import OPP_KINDS, OPP_KIND_LABELS, opp_kind_label  # noqa: E402


def _load_test_brain():
    spec = importlib.util.spec_from_file_location("tb_harness", ROOT / "tests" / "test_brain.py")
    assert spec is not None and spec.loader is not None
    tb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tb)
    return tb


class OppKindLabelTests(unittest.TestCase):
    def test_todo_kind_tem_rotulo_humano(self):
        for k in OPP_KINDS:
            self.assertIn(k, OPP_KIND_LABELS)
            self.assertNotEqual(opp_kind_label(k), k)

    def test_slug_desconhecido_passa_intacto(self):
        # retrocompatibilidade: instância antiga/tipo novo não quebra a exibição
        self.assertEqual(opp_kind_label("futuro-tipo"), "futuro-tipo")

    def test_payload_do_painel_carrega_kind_label(self):
        tb = _load_test_brain()
        from brainlib import render
        with tempfile.TemporaryDirectory() as td:
            b = tb._brain(Path(td))
            b.record_one({"type": "area.added", "id": "producao", "date": "2026-11-19", "by": "owner",
                          "data": {"name": "Produção"}})
            b.record_one({"type": "opportunity.added", "date": "2026-11-20", "by": "owner",
                          "prov": "observado",
                          "data": {"title": "Fornada medida", "area": "producao",
                                   "kind": "melhoria-de-processo"}})
            opps = render.view_model(b)["portfolio"]["opportunities"]
            self.assertTrue(opps)
            self.assertEqual(opps[0]["kind"], "melhoria-de-processo")
            self.assertEqual(opps[0]["kind_label"], "Melhoria de processo")

    def test_forms_js_espelha_o_mapa_python(self):
        fjs = (ROOT / "brainlib" / "assets" / "src" / "forms.js").read_text(encoding="utf-8")
        for label in OPP_KIND_LABELS.values():
            self.assertIn('"%s"' % label, fjs, "forms.js driftou do mapa em schema.py")

    def test_fontes_e_asset_construido(self):
        core = (ROOT / "brainlib" / "assets" / "src" / "core.js").read_text(encoding="utf-8")
        self.assertIn("o.kind_label || o.kind", core)
        rows = (ROOT / "brainlib" / "tui" / "rows.py").read_text(encoding="utf-8")
        self.assertIn("schema.opp_kind_label(o['kind'])", rows)
        for name in ("dashboard.html", "portfolio.html"):
            html = (ROOT / "brainlib" / "assets" / name).read_text(encoding="utf-8")
            self.assertIn("kind_label", html)


if __name__ == "__main__":
    unittest.main()
