"""Roteador de perguntas + perna ledger do hook (Fase 2 do plano da memória) — sem rede."""
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

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, index, route, util                    # noqa: E402
from brainlib.core import Brain                                     # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "none"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Abrir o segundo ponto\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n\n"
        "### PROJ-1 — Reforma da galeria\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Mari-demo"]}})
    b.record_one({"type": "decision.made", "id": "DEC-0001", "by": "owner", "date": "2026-10-01",
                  "data": {"title": "Galeria em vez da esquina", "decided_by": ["marina-demo"]}})
    late = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                         "prov": "observado", "source": "chat",
                         "data": {"title": "Revisar orçamento", "owner": "marina-demo", "due": "2026-10-04"}})
    b._ids = {"late": late["id"]}
    index.update(b)
    return b


class ClassifyTests(unittest.TestCase):
    def test_ids_new_and_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            self.assertEqual(route.classify("como está a TASK-0146?", db)["route"], "ledger")
            self.assertEqual(route.classify("o que aconteceu com A-146?", db)["ids"], ["TASK-0146"])
            self.assertEqual(route.classify("e o G1?", db)["ids"], ["GOAL-1"])
            self.assertEqual(route.classify("p3.2 está feito?", db)["ids"], ["PROJ-3.2"])

    def test_state_vocabulary_pt_es(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            for q in ("o que está atrasado com a Marina-demo?",
                      "quais os prazos da semana?",
                      "quem deve o quê a mim?",
                      "qué tareas están vencidas?"):
                self.assertEqual(route.classify(q, db)["route"], "ledger", q)

    def test_project_title_doubled(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            c = route.classify("como anda o projeto de reforma da galeria?", db)
            self.assertEqual(c["route"], "ledger")
            self.assertIn("PROJ-1", c["ids"])

    def test_context_question_is_not_state(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            # pergunta de CONTEXTO (a letra, o porquê) não é estado: silencia
            for q in ("por que escolhemos a galeria?",
                      "o que exatamente foi dito sobre o forno?",
                      "qual a nossa estratégia de cardápio?"):
                self.assertIsNone(route.classify(q, db)["route"], q)


class LedgerLinesTests(unittest.TestCase):
    def test_overdue_lines_with_arrow(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            lines = route.ledger_lines("o que está atrasado?", db)
            self.assertTrue(lines)
            self.assertLessEqual(len(lines), 3)
            self.assertIn(f"⟶ ledger/{b._ids['late']}", lines[0])
            self.assertIn("atrasada", lines[0])

    def test_entity_line(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            lines = route.ledger_lines("como está a DEC-0001?", index.db_path(b.inst))
            self.assertTrue(lines)
            self.assertIn("⟶ ledger/DEC-0001", lines[0])

    def test_silence_without_db(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            self.assertEqual(route.ledger_lines("o que está atrasado?", Path(td) / "none.sqlite"), [])

    def test_cap_three_lines(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for i in range(5):
                b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-0" + str(i + 1),
                              "prov": "observado", "source": "chat",
                              "data": {"title": f"atrasada {i}", "owner": "eu", "due": "2026-10-01"}})
            index.update(b)
            self.assertEqual(len(route.ledger_lines("o que está atrasado?", index.db_path(b.inst))), 3)


class HookTests(unittest.TestCase):
    """O hook de verdade, via subprocess (python do sistema, stdlib): ledger leg e silêncio."""

    def _run(self, prompt: str, env_extra: dict) -> str:
        env = {**os.environ, "BRAIN_NOW": "2026-10-09T10:00:00-03:00", **env_extra}
        r = subprocess.run([sys.executable, str(ROOT / "services" / "hooks" / "recall_context.py")],
                           input=json.dumps({"prompt": prompt}), capture_output=True, text=True,
                           cwd=ROOT, env=env, timeout=30)
        return r.stdout.strip()

    def test_ledger_route_outputs_lines(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            out = self._run("o que está atrasado com a Marina-demo?",
                            {"BRAIN_RECALL_ROUTE": "ledger", "BRAIN_HOME": td})
            self.assertIn(f"ledger/{b._ids['late']}", out)
            self.assertIn("additionalContext", out)

    def test_ledger_route_silences_on_context_question(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            out = self._run("por que escolhemos a galeria?",
                            {"BRAIN_RECALL_ROUTE": "ledger", "BRAIN_HOME": td})
            self.assertEqual(out, "")

    def test_ledger_route_silences_without_index(self):
        with tempfile.TemporaryDirectory() as td:
            _inst(Path(td))                                   # sem eventos, sem índice
            out = self._run("o que está atrasado?",
                            {"BRAIN_RECALL_ROUTE": "ledger", "BRAIN_HOME": td})
            self.assertEqual(out, "")

    def test_off_route_keeps_old_behavior_quiet_when_server_down(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            out = self._run("o que está atrasado?",
                            {"BRAIN_HOME": td, "BRAIN_HINDSIGHT_URL": "http://127.0.0.1:59999"})
            self.assertEqual(out, "")                         # sem rota: comportamento atual (banco fora → silêncio)


if __name__ == "__main__":
    unittest.main()
