"""Cache por assinatura de memory.documents(), NO_LLM_CONFIG único e exclusão de connectors-* fora da pasta (#10 #12 #18)."""
from __future__ import annotations

import contextlib
import importlib.util as _ilu
import inspect
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

from brainlib import cli, config, memory  # noqa: E402
from brainlib.core import Brain  # noqa: E402

_spec = _ilu.spec_from_file_location("test_brain", ROOT / "tests" / "test_brain.py")
_tb = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_tb)
FakeHindsight = _tb.FakeHindsight


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
        '[memory]\nengine = "hindsight"\ndegraded_after_days = 0\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n\n"
        "### PROJ-1 — Pagamentos demo\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-11-20 · peso: 2\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "decision.made", "by": "owner", "date": "2026-11-01", "source": "chat",
                  "data": {"title": "Congelar o forno-demo", "decided_by": ["eu"], "project": "PROJ-1"}})
    return b


def _raw(b: Brain, rel: str, text: str = "nota sobre o forno-demo") -> Path:
    p = b.inst.vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class MemoryDocsCacheTests(unittest.TestCase):
    def test_documents_built_once_per_signature(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = _brain(root)
            with mock.patch.object(memory, "_build_documents", wraps=memory._build_documents) as m:
                memory.documents(b)
                memory.documents(b)
                self.assertEqual(m.call_count, 1)

                _raw(b, "RAW/2026/11/notes/x.md")
                memory.documents(b)
                self.assertEqual(m.call_count, 2)

                with mock.patch.dict(os.environ, {"BRAIN_HOME": str(root)}), \
                        contextlib.redirect_stdout(io.StringIO()):
                    rc = cli.main(["decision", "add", "Segunda decisão", "--decided-by", "eu", "--by", "owner"])
                self.assertEqual(rc, 0)
                memory.documents(b)
                self.assertEqual(m.call_count, 3)

    def test_status_reads_raw_once(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            _raw(b, "RAW/2026/11/notes/x.md")
            hs = FakeHindsight()
            with mock.patch.object(memory, "_build_documents", wraps=memory._build_documents) as m:
                memory.status(b, online=True, hs=hs)
                self.assertEqual(m.call_count, 1)
                memory.cost(b, hs=hs)
                self.assertEqual(m.call_count, 1)

    def test_returned_dicts_are_copies(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            first = memory.documents(b)
            orig_id = first[0]["id"]
            first[0]["id"] = "mutado"
            second = memory.documents(b)
            self.assertEqual(second[0]["id"], orig_id)

    def test_connector_prefix_in_documents_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            _raw(b, "RAW/2026/11/documents/connectors-teste-20261118.md")
            _raw(b, "RAW/2026/11/documents/nota-20261118.md")
            ids = {d["id"] for d in memory.documents(b)}
            self.assertNotIn("RAW/2026/11/documents/connectors-teste-20261118.md", ids)
            self.assertIn("RAW/2026/11/documents/nota-20261118.md", ids)

    def test_single_no_llm_config(self):
        self.assertEqual(inspect.getsource(memory).count("NO_LLM_CONFIG = "), 1)


if __name__ == "__main__":
    unittest.main()
