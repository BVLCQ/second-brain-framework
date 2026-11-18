"""Testes do FormModal com Selects sem opções / dependências vazias (#14)."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


def _inst(tmp: Path):
    from brainlib import config
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
        "# PLANNING\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path):
    from brainlib.core import Brain
    return Brain(_inst(tmp))


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class TuiModalEmptyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inst = _inst(self.root)

    def app(self):
        from brainlib.tui.app import BrainApp
        return BrainApp(self.inst)

    async def test_compose_empty_dynamic_select(self):
        """Select dinâmico vazio monta com valor "" e prompt "— escolha —", e submit é barrado pelo req."""
        from textual.widgets import Select, Static
        from brainlib.tui.modals import Field, FormModal, FormSpec

        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            spec = FormSpec(
                title="Teste Select Vazio",
                fields=[Field(id="goal", label="Goal", options=lambda v: [], req=True)],
                build=lambda v: [["echo", v["goal"]]],
            )
            app.push_screen(FormModal(spec))
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")

            sel = app.screen.query_one("#f_goal", Select)
            self.assertEqual(sel.value, "")

            # Submit é recusado: modal continua aberta e mensagem de erro é exibida
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            err = app.screen.query_one("#err", Static)
            self.assertIn('Preencha "Goal".', str(err.render()))

    async def test_refresh_dependent_empties_child(self):
        """Ao recalcular campo dependente que fica sem opções, o Select não levanta exceção e zera o valor."""
        from textual.widgets import Select
        from brainlib.tui.modals import Field, FormModal, FormSpec

        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            spec = FormSpec(
                title="Teste Dependent",
                fields=[
                    Field(id="goal", label="Goal", choice=[("GOAL-1", "GOAL-1"), ("GOAL-2", "GOAL-2")]),
                    Field(id="proj", label="Projeto", options=lambda v: [], depends="goal"),
                ],
                build=lambda v: [],
            )
            app.push_screen(FormModal(spec))
            await pilot.pause(0.2)

            sel_goal = app.screen.query_one("#f_goal", Select)
            sel_proj = app.screen.query_one("#f_proj", Select)
            self.assertEqual(sel_proj.value, "")

            # Altera o pai para disparar _refresh_options no filho
            sel_goal.value = "GOAL-2"
            await pilot.pause(0.2)
            self.assertEqual(sel_proj.value, "")

    async def test_promote_form_without_active_goals(self):
        """Fluxo real: abrir opportunity.promote sem goals ativos monta o modal sem exceção."""
        from brainlib.core import Brain

        # Adiciona área e oportunidade
        b = Brain(self.inst)
        b.record_one({"type": "area.added", "id": "operacoes", "by": "owner", "data": {"name": "Operações"}})
        b.record_one({"type": "opportunity.added", "by": "owner",
                      "data": {"title": "Automatizar conciliação", "area": "operacoes"}})

        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            ctx = {"id": "OPP-0001", "item": {"id": "OPP-0001", "title": "Automatizar conciliação", "status": "ideia"}}
            app.open_form("opportunity.promote", ctx)
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
