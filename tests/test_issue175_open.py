"""[open] vence [tui.open]; mode e ide não são extensão."""
from __future__ import annotations

import unittest

from brainlib import opener


class OpenMapTests(unittest.TestCase):
    def test_open_vence_o_sinonimo_antigo(self):
        cfg = {"tui": {"open": {"md": "Cursor"}}, "open": {"mode": "auto", "ide": "Zed", "md": "VS Code"}}
        self.assertEqual(opener.app_for(cfg, "nota.md"), "VS Code")
        self.assertEqual(opener.app_for(cfg, "clip.mp4"), "")

    def test_sinonimo_antigo_segue_valendo(self):
        cfg = {"tui": {"open": {"md": "Cursor"}}}
        self.assertEqual(opener.app_for(cfg, "nota.md"), "Cursor")

    def test_modo_brain_abre_o_leitor(self):
        self.assertTrue(opener.prefer_reader({"open": {"mode": "brain"}}))
        self.assertFalse(opener.prefer_reader({"open": {"mode": "ide"}}))
        self.assertFalse(opener.prefer_reader({"open": {"mode": "auto", "ide": "Cursor"}}, which=lambda n: None))
        self.assertTrue(opener.prefer_reader({"open": {"mode": "auto"}}, which=lambda n: None))

    def test_set_prefs_grava_o_modo(self):
        import tempfile
        from pathlib import Path
        from brainlib import config
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            (root / "config" / "brain.toml").write_text("[owner]\nid = \"eu\"\n", encoding="utf-8")
            inst = config.load(root)
            changed = opener.set_prefs(inst, "brain", "Zed")
            self.assertEqual(changed, ["mode", "ide"])
            again = config.load(root)
            self.assertEqual(again.cfg["open"]["mode"], "brain")
            self.assertEqual(again.cfg["open"]["ide"], "Zed")


class LinkedFileTests(unittest.TestCase):
    def test_origem_em_arquivo_entra_na_lista_ligada(self):
        import os
        import tempfile
        from pathlib import Path
        from brainlib import config, model
        from brainlib.core import Brain
        os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            (root / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
            for sub in ("PLANNING", "RAW/inbox", "PROCESSED", "FRESH"):
                (root / "vault" / sub).mkdir(parents=True)
            (root / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
            rel = "RAW/inbox/reuniao-demo.md"
            (root / "vault" / rel).write_text("# Fornada\n", encoding="utf-8")
            b = Brain(config.load(root))
            b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                          "data": {"name": "Dona", "relation": "dono"}})
            b.record_one({"type": "action.opened", "by": "owner", "source": rel,
                          "data": {"title": "Enviar a receita", "owner": "eu"}})
            m = model.build(b)
            rels = [f["rel"] for f in m["actions"][0]["files"]]
            self.assertIn(rel, rels)

    def test_pergunta_com_fonte_em_arquivo_entra_na_lista(self):
        import os
        import tempfile
        from pathlib import Path
        from brainlib import config, model
        from brainlib.core import Brain
        os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            (root / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
            for sub in ("PLANNING", "RAW/inbox", "PROCESSED", "FRESH"):
                (root / "vault" / sub).mkdir(parents=True)
            (root / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
            rel = "RAW/inbox/reuniao-demo.md"
            (root / "vault" / rel).write_text("# Fornada\n", encoding="utf-8")
            b = Brain(config.load(root))
            b.record_one({"type": "question.asked", "by": "agent", "source": rel, "prov": "observado",
                          "data": {"text": "Qual receita enviar?", "context": [rel]}})
            files = model.build(b)["questions"][0]["files"]
            self.assertIn(rel, [f["rel"] for f in files])

    def test_fichas_do_painel_ligam_os_arquivos(self):
        from pathlib import Path
        src = Path("brainlib/assets/src/core.js").read_text(encoding="utf-8")
        for fid in ("V.action", "V.decision", "V.project", "V.person"):
            start = src.index(fid + " = ")
            body = src[start:src.index("\n};", start)]
            self.assertIn("filesBlock(", body, fid)
        self.assertIn("function docName", src)
        self.assertIn("data-read", src[src.index("function docName"):src.index("function docName") + 400])
        self.assertIn("data-opentoggle", src)
        self.assertIn("data-openall", src)
        for needle in ("filesBlock(f.files)", "filesBlock(q.files)", "filesBlock(g.files)", "filesBlock(x.files)"):
            self.assertIn(needle, src, needle)
