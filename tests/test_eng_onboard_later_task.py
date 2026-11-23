"""A tarefa "fazer depois" do onboarding é idempotente: clique duplo, retry ou segunda aba não cunham duas.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, onboard, util
from brainlib.core import Brain


def _inst(tmp: Path, *, allow: tuple[str, ...] = ("dona-demo", "marina-demo", "#time")) -> config.Instance:
    """Instância de prova: dono `dona-demo` SEM o alias "eu" — só a dobra de "eu" faz o dono ser achado."""
    for d in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH",
              "vault/reports"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "dona-demo"\nname = "Dona Demo"\n\n'
        '[outbound]\nallow = [' + ", ".join(f'"{x}"' for x in allow) + ']\n\n'
        '[work]\nstart = "09:00"\nend = "18:00"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path, **kw) -> Brain:
    b = Brain(_inst(tmp, **kw))
    b.record_one({"type": "person.added", "id": "dona-demo", "by": "owner",
                  "data": {"name": "Dona Demo", "aliases": ["Dona"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina Demo", "aliases": ["Mari Demo"], "email": "marina-demo@x.com"}})
    return b


class LaterTaskIsIdempotent(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.b = _brain(Path(self._td.name))

    def _open(self) -> list[str]:
        return sorted(a.id for a in self.b.state.actions.values() if a.open)

    def test_double_click_on_later_coins_one_task(self):
        r1 = onboard.agent_later(self.b, {"agent": "hermes"})
        r2 = onboard.agent_later(self.b, {"agent": "hermes"})
        self.assertEqual(r2["id"], r1["id"])
        self.assertEqual(self._open(), [r1["id"]])

    def test_another_agent_or_mode_reuses_the_open_task(self):
        """É a mesma coisa a fazer: fica UMA tarefa — com o título da ÚLTIMA escolha, que é o que o dono vai fazer."""
        r1 = onboard.agent_later(self.b, {"agent": "hermes"})
        r2 = onboard.agent_later(self.b, {"agent": "claude-code"})
        self.assertEqual(r2["id"], r1["id"])
        self.assertIn(onboard._agent_label("claude-code"), self.b.state.actions[r1["id"]].title)
        self.assertNotIn("Hermes", self.b.state.actions[r1["id"]].title)
        r3 = onboard.apply_memory(self.b, {"mode": "embed", "later": True})
        r4 = onboard.apply_memory(self.b, {"mode": "full", "later": True})
        self.assertEqual((r4["id"], r4["later"]), (r3["id"], True))
        self.assertIn("no modo full", self.b.state.actions[r3["id"]].title)
        self.assertEqual(self._open(), sorted([r1["id"], r3["id"]]))

    def test_reused_task_keeps_the_earlier_title_in_the_ledger(self):
        """O título novo é um evento a mais (`action.updated`): o primeiro continua legível no histórico."""
        r1 = onboard.apply_memory(self.b, {"mode": "embed", "later": True})
        r2 = onboard.apply_memory(self.b, {"mode": "full", "later": True})
        self.assertEqual(r2["id"], r1["id"])
        a = self.b.state.actions[r1["id"]]
        self.assertEqual([h["type"] for h in a.history], ["action.opened", "action.updated"])
        self.assertIn("no modo embed", a.history[0]["data"]["title"])
        self.assertIn("no modo full", a.title)

    def test_closed_task_does_not_block_a_new_later(self):
        r1 = onboard.agent_later(self.b, {"agent": "hermes"})
        self.b.record_one({"type": "action.closed", "id": r1["id"], "by": "owner", "data": {"how": "feito"}})
        r2 = onboard.agent_later(self.b, {"agent": "hermes"})
        self.assertNotEqual(r2["id"], r1["id"])
        self.assertEqual(self._open(), [r2["id"]])

    def test_nightly_refuses_before_reusing_or_creating(self):
        """Sem dono presente não há "depois eu faço": nem cunha nem reaproveita. Antes só o caminho de criar batia
        na recusa do ledger (`by: owner`); reaproveitar devolvia o id em silêncio."""
        r1 = onboard.agent_later(self.b, {"agent": "hermes"})
        with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
            with self.assertRaisesRegex(util.BrainError, "noturno"):
                onboard.agent_later(self.b, {"agent": "hermes"})       # já existe: também recusa
            with self.assertRaisesRegex(util.BrainError, "noturno"):
                onboard.agent_later(self.b, {"agent": "cursor"})       # título novo: mesma recusa, mesma mensagem
        self.assertEqual(self._open(), [r1["id"]])
        self.assertEqual([h["type"] for h in self.b.state.actions[r1["id"]].history], ["action.opened"])
    def test_nightly_refuses_the_memory_step_before_reusing_or_creating(self):
        """O mesmo, pelo passo de memória: `apply_memory(later=True)` recusa antes de reaproveitar ou criar — e não
        grava a escolha "depois" no progresso. Sem a guarda, o mesmo modo devolvia o id em silêncio."""
        r1 = onboard.apply_memory(self.b, {"mode": "embed", "later": True})
        before = onboard.progress(self.b.inst)
        with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
            with self.assertRaisesRegex(util.BrainError, "noturno"):
                onboard.apply_memory(self.b, {"mode": "embed", "later": True})     # já existe: também recusa
            with self.assertRaisesRegex(util.BrainError, "noturno"):
                onboard.apply_memory(self.b, {"mode": "full", "later": True})      # título novo: mesma recusa
        self.assertEqual(onboard.progress(self.b.inst), before)
        self.assertEqual([h["type"] for h in self.b.state.actions[r1["id"]].history], ["action.opened"])


if __name__ == "__main__":
    unittest.main()
