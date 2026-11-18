"""Testes da classificação de prefixos no RAW e avisos de snapshot."""
from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, rawsort, snapshot, util
from brainlib.core import Brain


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n'
        '[outbound]\nallow = ["marina-demo", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n"
        "- [ ] PROJ-1.2 Outro · prazo: 2026-11-01\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Marina-demo", "Mari-demo"], "email": "marina-demo@x.com"}})
    return b


class RawSortPrefixTests(unittest.TestCase):
    def test_existing_prefixes_preserved(self):
        """Todos os prefixos pré-existentes mapeiam para suas respectivas pastas."""
        expected = {
            "slack": "slack",
            "jira": "connectors",
            "gmail": "connectors",
            "gcal": "connectors",
            "drive": "connectors",
            "databricks": "connectors",
            "github": "github",
            "granola": "meetings",
        }
        for prefix, target in expected.items():
            self.assertIn(prefix, rawsort.SNAPSHOT_PREFIXES)
            self.assertEqual(rawsort.SNAPSHOT_PREFIXES[prefix], target)
            self.assertTrue(rawsort.known_prefix(prefix))
            self.assertTrue(rawsort.known_prefix(prefix.upper()))

        # Todos os tipos também são prefixos conhecidos
        for t in rawsort.TYPES:
            self.assertIn(t, rawsort.SNAPSHOT_PREFIXES)
            self.assertEqual(rawsort.SNAPSHOT_PREFIXES[t], t)
            self.assertTrue(rawsort.known_prefix(t))

        self.assertFalse(rawsort.known_prefix("foo"))
        self.assertFalse(rawsort.known_prefix("desconhecido"))

    def test_connectors_prefix_archives_to_connectors_folder(self):
        """Arquivo com prefix='connectors' vai para RAW/<ano>/<mês>/connectors/."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            res = snapshot.take(b, "teste", "leitura de conector\n", prefix="connectors")
            self.assertTrue(res["changed"])
            self.assertFalse(res["failed"])
            self.assertNotIn("warning", res)

            snap_path = res["path"]
            self.assertTrue(snap_path.is_file())
            self.assertEqual(snap_path.parent.resolve(), b.inst.inbox.resolve())

            moved = rawsort.archive(b.inst)
            self.assertEqual(len(moved), 1)
            self.assertEqual(moved[0]["type"], "connectors")

            target = b.inst.vault / "RAW" / "2026" / "10" / "connectors" / snap_path.name
            self.assertTrue(target.is_file())
            self.assertFalse(snap_path.exists())

    def test_unknown_prefix_returns_warning_and_lands_in_inbox(self):
        """Prefixo não reconhecido gera chave 'warning' e salva na inbox normalmente."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            res = snapshot.take(b, "teste-foo", "leitura foo\n", prefix="foo")
            self.assertTrue(res["changed"])
            self.assertFalse(res["failed"])
            self.assertIn("warning", res)
            self.assertIn("prefixo 'foo' não classifica no RAW", res["warning"])
            self.assertIn("Prefixos que classificam:", res["warning"])
            self.assertIn("connectors", res["warning"])

            snap_path = res["path"]
            self.assertTrue(snap_path.is_file())
            self.assertEqual(snap_path.parent.resolve(), b.inst.inbox.resolve())

    def test_default_prefix_from_key_has_no_warning(self):
        """Prefixo inferido a partir da chave (sem --prefix explícito) não emite warning."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            res = snapshot.take(b, "email-diario", "leitura diaria\n")
            self.assertTrue(res["changed"])
            self.assertFalse(res["failed"])
            self.assertNotIn("warning", res)
            self.assertTrue(res["path"].is_file())
            self.assertEqual(res["path"].parent.resolve(), b.inst.inbox.resolve())

    def test_cli_prints_warning_to_stderr(self):
        """No handler de CLI, o aviso é impresso em stderr mantendo comportamento normal."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ns = {
                "key": "teste-cli",
                "file": None,
                "prefix": "foo",
                "ext": "md",
                "item": None,
                "rev": None,
                "name": None,
                "check": False,
                "fail": None,
                "empty": False,
            }
            fake_stdin = io.StringIO("conteúdo da CLI\n")
            captured_stdout = io.StringIO()
            captured_stderr = io.StringIO()

            old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
            try:
                sys.stdin, sys.stdout, sys.stderr = fake_stdin, captured_stdout, captured_stderr
                snapshot.cli(argparse.Namespace(**ns), b)
            finally:
                sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr

            stderr_output = captured_stderr.getvalue()
            stdout_output = captured_stdout.getvalue()

            self.assertIn("⚠ prefixo 'foo' não classifica no RAW", stderr_output)
            self.assertIn("✓ teste-cli: novidades →", stdout_output)
