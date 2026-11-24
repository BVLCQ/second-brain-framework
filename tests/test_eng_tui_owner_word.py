""""eu" vale o dono do Brain nas checagens de pessoa dos formulários e no destinatário da TUI.

O CLI já dobrava ("eu" → dono, em `outbox draft` e `_resolve_people`); só as duas checagens da TUI recusavam.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config
from brainlib.core import Brain

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


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


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class OwnerWordInTuiChecks(unittest.IsolatedAsyncioTestCase):
    async def test_people_check_accepts_eu_as_the_owner(self):
        """Antes: `pessoa 'eu' não encontrada` travava o formulário de processo/decisão com "eu" em pessoas."""
        from brainlib.tui.app import BrainApp
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        app = BrainApp(_brain(Path(td.name)).inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.1)
            self.assertEqual(app._people_check("eu, Marina Demo"), "")
            self.assertEqual(app._people_check("EU"), "")
            self.assertIn("pessoa 'Quem Nao Existe' não encontrada", app._people_check("eu, Quem Nao Existe"))

    async def test_recipient_check_folds_eu_to_the_owner_and_keeps_the_allow_gate(self):
        """Antes: `pessoa 'eu' não encontrada` — o CLI (`outbox draft --to eu`) já resolvia o dono."""
        from brainlib.tui.app import BrainApp
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        app = BrainApp(_brain(Path(td.name)).inst)                       # dona-demo está em [outbound].allow
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.1)
            self.assertEqual(app._check_recipient("Eu"), "")
        td2 = tempfile.TemporaryDirectory()
        self.addCleanup(td2.cleanup)
        app2 = BrainApp(_brain(Path(td2.name), allow=("marina-demo", "#time")).inst)   # dono fora da lista
        async with app2.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.1)
            self.assertEqual(app2._check_recipient("eu"),
                             "'dona-demo' não está em [outbound].allow do config/brain.toml")
            self.assertIn("não encontrada", app2._check_recipient("Quem Nao Existe"))

if __name__ == "__main__":
    unittest.main()
