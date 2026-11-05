"""Eval de memória (Fase 0) — parser do gold e métricas com cliente falso, sem rede."""
from __future__ import annotations

import importlib.util as _ilu
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, index, memory_eval, util                   # noqa: E402
from brainlib.core import Brain                                         # noqa: E402

_spec = _ilu.spec_from_file_location("test_brain", ROOT / "tests" / "test_brain.py")
_tb = _ilu.module_from_spec(_spec)
spec_ok = _spec.loader.exec_module(_tb) or True
FakeHindsight = _tb.FakeHindsight


def _brain(tmp: Path) -> Brain:
    (tmp / "config").mkdir(parents=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH", "reports"):
        (tmp / "vault" / sub).mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n", encoding="utf-8")
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Mari-demo"]}})
    late = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                         "prov": "observado", "source": "chat",
                         "data": {"title": "Revisar orçamento", "owner": "marina-demo", "due": "2026-10-04"}})
    b.record_one({"type": "decision.made", "by": "owner", "date": "2026-10-01", "source": "chat",
                  "data": {"title": "Galeria em vez da esquina", "decided_by": ["marina-demo"]}})
    index.update(b)
    b._late = late["id"]
    return b


class _VecHS(FakeHindsight):
    """Recall determinístico por consulta — para recall@k/MRR/citação."""

    def __init__(self, by_query: dict):
        super().__init__()
        self.by_query = by_query

    def recall(self, bank, query, tags=None, budget="mid"):
        super().recall(bank, query, tags, budget)
        return {"results": self.by_query.get(query, [])}


class GoldParserTests(unittest.TestCase):
    def test_skips_comments_and_validates(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "g.jsonl"
            p.write_text("# comentário\n\n"
                         '{"id":"q1","q":"a?","type":"estado","expect_ids":["TASK-0001"]}\n'
                         '{"id":"q2","q":"b?","type":"nada"}\n', encoding="utf-8")
            gold = memory_eval.load_gold(p)
            self.assertEqual([g["id"] for g in gold], ["q1", "q2"])
            self.assertEqual(gold[1]["expect_docs"], [])
            with self.assertRaises(util.BrainError):
                memory_eval.load_gold(Path(td) / "nope.jsonl")

    def test_bad_type_and_dupe_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "g.jsonl"
            p.write_text('{"id":"q1","q":"a?","type":"chute"}\n', encoding="utf-8")
            with self.assertRaises(util.BrainError):
                memory_eval.load_gold(p)
            p.write_text('{"id":"q1","q":"a?","type":"nada"}\n{"id":"q1","q":"b?","type":"nada"}\n',
                         encoding="utf-8")
            with self.assertRaises(util.BrainError):
                memory_eval.load_gold(p)


class EvalRunTests(unittest.TestCase):
    def test_state_hits_ledger_and_nada_abstains(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            gold = [
                {"id": "q1", "q": "o que está atrasado com a Marina-demo?", "type": "estado",
                 "expect_ids": [b._late]},
                {"id": "q2", "q": "o que decidimos sobre o franqueamento?", "type": "nada"},
            ]
            res = memory_eval.run(b, gold, hs=_VecHS({}), route_on=True, k=5)
            self.assertTrue(res["rows"][0]["hit"])
            self.assertEqual(res["by_type"]["estado"]["recall_at_k"], 1.0)
            self.assertEqual(res["by_type"]["nada"]["abstention"], 1.0)     # nada injetou zero

    def test_vector_hit_rank_and_citation(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            q = "o que sabemos sobre a padaria-demo?"
            hs = _VecHS({q: [
                {"document_id": "RAW/outro.md", "text": "x"},
                {"document_id": "RAW/2026/10/meetings/ata.md", "text": "y"},
            ]})
            gold = [{"id": "q1", "q": q, "type": "contexto", "expect_docs": ["RAW/2026/10/meetings/ata.md"]}]
            res = memory_eval.run(b, gold, hs=hs, route_on=True, k=5)
            self.assertTrue(res["rows"][0]["hit"])
            self.assertEqual(res["rows"][0]["rank"], 2)                      # 1º o doc errado, 2º o esperado
            self.assertEqual(res["rows"][0]["recalled_doc"], "RAW/2026/10/meetings/ata.md")

    def test_conclusao_accepts_mental_model_doc(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            q = "por que achamos que o segundo ponto importa?"
            hs = _VecHS({q: [{"document_id": "mm-goal-1", "text": "síntese"}]})
            gold = [{"id": "q1", "q": q, "type": "conclusao", "expect_docs": []}]
            res = memory_eval.run(b, gold, hs=hs, route_on=True, k=5)
            self.assertTrue(res["rows"][0]["hit"])                          # página do model conta (variante full)

    def test_route_off_disables_ledger_leg(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            gold = [{"id": "q1", "q": "o que está atrasado?", "type": "estado",
                     "expect_ids": [b._late]}]
            res = memory_eval.run(b, gold, hs=_VecHS({}), route_on=False, k=5)
            self.assertFalse(res["rows"][0]["hit"])


if __name__ == "__main__":
    unittest.main()
