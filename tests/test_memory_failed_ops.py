"""Operações falhas do servidor no status/doctor (#26): o contador de failed_operations
do Hindsight aparece mesmo quando o rastreador local (op_problems) não tem o documento —
o doctor não pode mostrar tudo verde com retains morrendo no servidor."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# sem BRAIN_NOW próprio: o módulo irmão (carregado abaixo) congela o relógio e a gente herda —
# um setdefault com data nova aqui vaza para os outros módulos quando rodam no mesmo processo

from brainlib import memory                                                       # noqa: E402

# mesmo padrão de tests/test_memory_modes.py: carrega o módulo irmão e reusa o harness + o fake
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("test_memory_modes", ROOT / "tests" / "test_memory_modes.py")
_tm = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_tm)
_make = _tm._brain
FakeHindsight = _tm.FakeHindsight


class FailedOperationsTests(unittest.TestCase):
    def _hs_with_failures(self, n: int, error: str = "") -> FakeHindsight:
        hs = FakeHindsight()
        hs.bank_stats["brain"] = {"failed_operations": n}
        if error:
            t = (datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc) + timedelta(minutes=1)).isoformat()
            hs.ops["op-f1"] = {"id": "op-f1", "bank": "brain", "document_id": "doc-x",
                               "status": "failed", "operation_type": "retain",
                               "created_at": t, "updated_at": t, "error": error}
        return hs

    def test_failed_operations_warn_even_without_tracked_docs(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make(Path(td))
            hs = self._hs_with_failures(848)
            s = memory.status(b, online=True, hs=hs)
            self.assertEqual(s["level"], "warn")                     # nunca verde com falhas no servidor
            self.assertIn("848", s["detail"])
            self.assertIn("operações falhas", s["detail"])
            self.assertIn("docker logs hindsight", s["detail"])      # causa genérica sem detalhe do erro

    def test_no_models_loaded_hint_names_the_fix(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make(Path(td), mem_extra="[memory]\nextract = true\ncloud_llm = true\nraw_awaiting_dump = \"hold\"")
            hs = self._hs_with_failures(12, error="RuntimeError: Fact extraction failed: HTTP 400: No models loaded.")
            s = memory.status(b, online=True, hs=hs)
            self.assertEqual(s["level"], "warn")
            self.assertIn("No models loaded", s["detail"])
            self.assertIn("brain memory providers set llm", s["detail"])

    def test_zero_failed_operations_keeps_level(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make(Path(td))
            hs = FakeHindsight()
            hs.bank_stats["brain"] = {"failed_operations": 0}
            s = memory.status(b, online=True, hs=hs)
            self.assertEqual(s["level"], "ok")
            self.assertNotIn("operações falhas", s["detail"])

    def test_queue_carries_the_counter(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make(Path(td))
            hs = self._hs_with_failures(7)
            q = memory.queue(b, hs)
            self.assertEqual(q["brain"]["failed_operations"], 7)
            self.assertIn("7 operações falhas", memory._queue_text(q))


if __name__ == "__main__":
    unittest.main()
