"""Testes de higiene e abas dinâmicas de oportunidades em brainlib.tui.store."""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, demo as demo_mod, schema
from brainlib.tui import store


class OppTabsTest(unittest.TestCase):
    """OPP_TABS cobre todo o schema.OPP_STATUS sem sobreposição e absorve novos status na última aba."""

    def test_default_opp_tabs_covers_entire_schema_without_overlap(self):
        tabs = store.build_opp_tabs()
        self.assertEqual(len(tabs), 4)
        covered: set[str] = set()
        for grp in tabs:
            grp_set = set(grp)
            self.assertEqual(covered & grp_set, set())
            covered |= grp_set
        self.assertEqual(covered, schema.OPP_STATUS)
        self.assertEqual(set(tabs[-1]), {"entregue", "em-espera", "descartada"})

    def test_new_schema_status_lands_in_last_tab(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "inst"
            with contextlib.redirect_stdout(io.StringIO()):
                demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
            st = store.Store(config.load(root))
            opp_id = "OPP-9999"
            opp = {
                "id": opp_id,
                "title": "Oportunidade em revisão",
                "status": "em-revisao-ficticia",
                "area": "operacoes",
                "problem": "fluxo em revisão",
                "score": 10,
            }
            st.m["portfolio"]["opportunities"].append(opp)
            st.by_opp[opp_id] = opp

            with mock.patch.object(schema, "OPP_STATUS", schema.OPP_STATUS | {"em-revisao-ficticia"}):
                tabs = store.build_opp_tabs()
                with mock.patch.object(store, "OPP_TABS", tabs):
                    self.assertIn("em-revisao-ficticia", tabs[-1])
                    self.assertEqual(st.locate(opp_id), (1, 3, 3))
                    self.assertIn(opp_id, [it.id for it in st.items(1, 3, 3)])


class StoreHygieneTest(unittest.TestCase):
    """Higiene do módulo store: remoção do alias obsoleto PANELS."""

    def test_panels_compat_alias_removed(self):
        self.assertFalse(hasattr(store, "PANELS"))
        self.assertIs(store.FACES[0][1], store.PANELS_EXEC)


if __name__ == "__main__":
    unittest.main()
