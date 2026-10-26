"""`brain oppdrive` — porta das pastas de oportunidade no Drive (só contabilidade; quem escreve no Drive é o agente)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from brainlib import runner                     # noqa: E402
from test_brain import _brain                   # noqa: E402

RAIZ, PASTA, DOC, OUTRA = "1RaizRaizRaizRaiz", "1PastaPastaPasta", "1DocDocDocDocDoc", "1OutraOutraOutra"
TOOLS = ["mcp__drive__create_file", "mcp__docs__update_doc"]


class OppDriveTests(unittest.TestCase):
    def _run(self, td, *a):
        env = {**os.environ, "BRAIN_HOME": td}
        env.pop("BRAIN_NIGHTLY", None)
        return subprocess.run([sys.executable, str(ROOT / "brain"), *a], capture_output=True, text=True, env=env)

    def _ok(self, td, *a):
        r = self._run(td, *a)
        self.assertEqual(r.returncode, 0, f"{a}: {r.stderr}")
        return r.stdout

    def _setup(self, td, enabled=True):
        _brain(Path(td))
        cfg = Path(td) / "config" / "brain.toml"
        cfg.write_text(cfg.read_text() + f'\n[oppdrive]\nenabled = {"true" if enabled else "false"}\n'
                       f'root = "https://drive.google.com/drive/u/0/folders/{RAIZ}"\ntools = {json.dumps(TOOLS)}\n')
        self._ok(td, "area", "add", "operacoes", "--by", "owner")
        self._ok(td, "opportunity", "add", "Roteamento de tickets", "--area", "operacoes",
                 "--problem", "triagem manual", "--by", "owner")

    def _status(self, td):
        return json.loads(self._ok(td, "oppdrive", "status", "--json"))["opportunities"][0]

    def test_disabled_door_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td, enabled=False)
            self.assertEqual(self._run(td, "oppdrive", "status").returncode, 4)

    def test_folder_onepager_and_suggestion_flow(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            st = self._status(td)
            self.assertEqual((st["todo"], st["folder_title"]), (["pasta", "one-pager"], "OPP-0001: Roteamento de tickets"))
            md = self._ok(td, "oppdrive", "onepager", "OPP-0001")
            self.assertIn("# OPP-0001: Roteamento de tickets", md)
            self.assertIn("triagem manual", md)
            self.assertIn("## Arquivos relacionados", md)
            # pasta fora da raiz: recusada, nada gravado
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--folder", PASTA, "--parent", OUTRA).returncode, 4)
            # one-pager antes da pasta: recusado
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--onepager", DOC, "--parent", PASTA).returncode, 4)
            self.assertIn("fonte oppdrive", self._ok(td, "oppdrive", "record", "OPP-0001", "--folder", PASTA, "--parent", RAIZ))
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--onepager", DOC, "--parent", OUTRA).returncode, 4)
            out = self._ok(td, "oppdrive", "record", "OPP-0001", "--onepager",
                           f"https://docs.google.com/document/d/{DOC}/edit", "--parent", PASTA)
            self.assertIn("one-pager-opp-0001", out)                        # vigiado pelo watch
            watch = json.loads(self._ok(td, "watch", "list", "--json"))
            self.assertIn({"key": "oppdrive", "doc": None}, [{"key": w["key"], "doc": w.get("doc")} for w in watch])
            self.assertIn({"key": "one-pager-opp-0001", "doc": DOC}, [{"key": w["key"], "doc": w.get("doc")} for w in watch])
            # cria uma vez só
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--onepager", OUTRA, "--parent", PASTA).returncode, 4)
            self.assertEqual(self._status(td)["todo"], [])
            # arquivo de outra pessoa ligado → pendente até virar sugestão no one-pager
            url = "https://docs.google.com/spreadsheets/d/1PlanilhaPlanilha/edit"
            self._ok(td, "doc", "link", "OPP-0001", "--kind", "planilha", "--ref", url, "--title", "Base de tickets",
                     "--prov", "observado", "--source", "RAW/inbox/x.md")
            self.assertIn("OPP-0001", self._ok(td, "oppdrive", "status", "--pending"))
            self.assertEqual(self._run(td, "oppdrive", "suggested", "OPP-0001", "--doc", OUTRA, "--what", "x").returncode, 4)
            self._ok(td, "oppdrive", "suggested", "OPP-0001", "--doc", DOC, "--what", f"Arquivos relacionados: {url}")
            self.assertTrue(self._status(td)["related"][0]["in_onepager"])
            self.assertIn("nada pendente", self._ok(td, "oppdrive", "status", "--pending"))
            self.assertIn("✓", self._ok(td, "validate"))

    def test_door_tools_only_when_enabled(self):
        cfg = {"runner": {"allow": []}, "oppdrive": {"enabled": True, "root": RAIZ, "tools": TOOLS}}
        self.assertEqual(runner.door_allow(cfg), TOOLS)
        self.assertEqual(runner.door_allow({**cfg, "oppdrive": {**cfg["oppdrive"], "enabled": False}}), [])
        self.assertEqual(runner.door_allow({**cfg, "oppdrive": {**cfg["oppdrive"], "root": ""}}), [])


if __name__ == "__main__":
    unittest.main()
