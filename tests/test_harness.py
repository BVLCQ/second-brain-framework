"""Harnesses de código no servidor do cérebro (plano memory-harness-wizard.md) — stdlib unittest, sem rede."""
from __future__ import annotations

import importlib.util as _ilu
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, harness, memory, util                                   # noqa: E402
from brainlib.core import Brain                                                    # noqa: E402

_spec = _ilu.spec_from_file_location("test_brain", ROOT / "tests" / "test_brain.py")
_tb = _ilu.module_from_spec(_spec)
spec_ok = _spec.loader.exec_module(_tb) or True
FakeHindsight = _tb.FakeHindsight


def _brain(tmp: Path) -> Brain:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n", encoding="utf-8")
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class _OkRun:
    """subprocess.run falso: registra argv e sempre sai 0."""

    def __init__(self):
        self.argvs: list[list[str]] = []

    def __call__(self, cmd, **kw):
        self.argvs.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")


class MergeConfigTests(unittest.TestCase):
    def test_fresh_write_sets_shared_bank_with_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".hindsight" / "coding-agent.json"
            cfg = harness.merge_coding_agent(p, "http://localhost:8888", "hermes")
            self.assertEqual(cfg["serverMode"], "self-hosted")
            self.assertEqual(cfg["apiUrl"], "http://localhost:8888")
            self.assertEqual(cfg["bankId"], "hermes")
            self.assertEqual(cfg["retainTags"], ["project:{gitProject}", "harness:{harness}"])
            self.assertEqual(json.loads(p.read_text())["bankId"], "hermes")

    def test_unknown_owner_keys_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".hindsight" / "coding-agent.json"
            p.parent.mkdir(parents=True)
            p.write_text('{"autoUpdate": false, "myKey": 1}', encoding="utf-8")
            cfg = harness.merge_coding_agent(p, "http://localhost:8888", "hermes")
            self.assertFalse(cfg["autoUpdate"])
            self.assertEqual(cfg["myKey"], 1)


class InstallTests(unittest.TestCase):
    def test_installer_runs_self_hosted_and_records(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            b = _brain(home / "inst")
            run = _OkRun()
            res = harness.install(b, ["claude-code"], home=home, run=run)
            self.assertTrue(res[0]["ok"])
            argv = run.argvs[0]
            self.assertIn("install", argv)
            self.assertIn("claude-code", argv)
            self.assertIn("--server", argv)
            self.assertIn("self-hosted", argv)
            self.assertIn("http://localhost:8888", argv)
            self.assertEqual(b.inst.cfg["memory"]["harnesses"], ["claude-code"])
            self.assertTrue(harness.coding_agent_config(home).exists())

    def test_without_npx_returns_recipe_and_records_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            b = _brain(home / "inst")
            with mock.patch.object(harness.shutil, "which", return_value=None):
                res = harness.install(b, ["codex"], home=home, run=_OkRun())
            self.assertFalse(res[0]["ok"])
            self.assertIn("node/npm ausentes", res[0]["hint"])
            self.assertEqual(b.inst.cfg["memory"]["harnesses"], [])
            self.assertFalse(harness.coding_agent_config(home).exists())


class WireHermesTests(unittest.TestCase):
    def test_writes_local_external_and_preserves_owner_keys(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            p = harness.hermes_config(home)
            p.parent.mkdir(parents=True)
            p.write_text('{"recall_budget": "mid", "timeout": 30}', encoding="utf-8")
            b = _brain(home / "inst")
            out = harness.wire_hermes(b, home=home, run=_OkRun(), which=lambda _b: None)
            cfg = json.loads(p.read_text())
            self.assertEqual(cfg["mode"], "local_external")
            self.assertEqual(cfg["api_url"], "http://localhost:8888")
            self.assertEqual(cfg["bank_id"], "hermes")
            self.assertEqual(cfg["recall_budget"], "mid")            # do dono, preservado
            self.assertFalse(out["cli"])                              # sem CLI no PATH: receita
            self.assertEqual(b.inst.cfg["memory"]["harnesses"], ["hermes"])


class VerifyTests(unittest.TestCase):
    def test_bank_present_and_ping(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            b = _brain(home / "inst")
            hs = FakeHindsight()
            hs.put_bank("hermes", {"name": "agentes"})
            v = harness.verify(b, hs, home=home)
            self.assertTrue(v["bank_exists"])
            self.assertTrue(v["ping"])
            self.assertIn(("hermes", mock.ANY), [(bank, q) for bank, q in hs.recall_calls])

    def test_bank_missing_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td) / "inst")
            v = harness.verify(b, FakeHindsight(), home=Path(td))
            self.assertFalse(v["bank_exists"])
            self.assertFalse(v["ping"])


class DetectTests(unittest.TestCase):
    def test_detect_via_home_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / ".claude").mkdir()
            (home / ".cursor").mkdir()
            with mock.patch.object(harness.shutil, "which", return_value=None):
                det = harness.detect(home)
            self.assertTrue(det["claude-code"])
            self.assertTrue(det["cursor-cli"])
            self.assertFalse(det["codex"])
            self.assertFalse(det["hermes"])


if __name__ == "__main__":
    unittest.main()
