"""Regressões da segunda rodada de correções do TUI (#39, #40, #41, #42)."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, dupes  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.tui import bridge, rows  # noqa: E402
from brainlib.tui.store import Item, Store  # noqa: E402

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


def _inst(tmp: Path, *, goals_md: str | None = None) -> config.Instance:
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
        '[publish]\ndestinations = ["slack:#time"]\n',
        encoding="utf-8",
    )
    default_goals = (
        "# PLANNING\n\n"
        "## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: teste\n\n"
        "### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n"
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(goals_md or default_goals, encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path, *, goals_md: str | None = None) -> Brain:
    b = Brain(_inst(tmp, goals_md=goals_md))
    b.record_one({
        "type": "person.added",
        "id": "eu",
        "by": "owner",
        "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"},
    })
    b.record_one({
        "type": "person.added",
        "id": "marina-demo",
        "by": "owner",
        "data": {"name": "Marina-demo", "aliases": ["Marina-demo"], "email": "marina-demo@x.com"},
    })
    return b


class StoreAndRowsFixesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_focus_tab_omits_fwarn_when_no_at_risk_and_shows_when_present(self):
        b = _brain(self.root)
        b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Ação sem risco", "list": "mine"}})
        b.record_one({
            "type": "focus.planned",
            "by": "owner",
            "data": {"plan_file": "vault/FRESH/focus.md", "sha": "abc123",
                     "blocks": [{"action": "TASK-0001", "start": "2026-10-09T10:00:00", "end": "2026-10-09T11:00:00"}],
                     "at_risk": []},
        })
        st = Store(b.inst)
        focus_items = st.items(0, 4, 3)
        self.assertFalse(any(it.id == "f:warn" for it in focus_items))

        # Com at_risk presente, f:warn aparece
        b.record_one({
            "type": "focus.planned",
            "by": "owner",
            "data": {"plan_file": "vault/FRESH/focus.md", "sha": "def456",
                     "blocks": [], "at_risk": [{"action": "TASK-0001", "shortfall_min": 45, "due": "2026-10-10"}]},
        })
        st.load()
        focus_items = st.items(0, 4, 3)
        warns = [it for it in focus_items if it.id == "f:warn"]
        self.assertEqual(len(warns), 1)
        rendered = rows.row(st, warns[0], 80).plain
        self.assertIn("não cabe: 1", rendered)
        # Chamada direta a rows.row com at_risk=[] também permanece coerente
        self.assertIn("não cabe: 0", rows.row(st, Item("f:warn", "fwarn", {"at_risk": []}), 80).plain)

    def test_d_action_shows_multiple_open_blockers(self):
        b = _brain(self.root)
        b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Primeiro bloqueador", "list": "mine"}})
        b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Segundo bloqueador", "list": "mine"}})
        b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Bloqueador já fechado", "list": "mine"}})
        b.record_one({"type": "action.closed", "id": "TASK-0003", "by": "owner", "data": {"how": "feito"}})
        b.record_one({
            "type": "action.opened",
            "by": "owner",
            "data": {"title": "Ação bloqueada", "list": "mine", "blocked_by": ["TASK-0001", "TASK-0002", "TASK-0003"]},
        })
        st = Store(b.inst)
        it = next(i for i in st.items(0, 2, 0) if i.id == "TASK-0004")
        doc = rows.d_action(st, it)
        kv_lines = [line.plain for line in doc.lines if "bloqueada por" in line.plain]
        self.assertEqual(len(kv_lines), 1)
        self.assertIn("TASK-0001", kv_lines[0])
        self.assertIn("TASK-0002", kv_lines[0])
        self.assertNotIn("TASK-0003", kv_lines[0])

    def test_portfolio_by_goal_pct_none_has_no_percent_sign(self):
        goals = "# PLANNING\n\n## GOAL-1 — Meta sem entregáveis\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: teste\n"
        b = _brain(self.root, goals_md=goals)
        b.record_one({"type": "area.added", "id": "operacoes", "by": "owner", "data": {"name": "Operações"}})
        b.record_one({
            "type": "opportunity.added",
            "by": "owner",
            "data": {"title": "Oportunidade ligada", "area": "operacoes"},
        })
        st = Store(b.inst)
        items = st.items(1, 1, 2)
        goal_hdr = next(i for i in items if i.kind == "pgrp" and i.id == "grp:GOAL-1")
        self.assertEqual(goal_hdr.data["sub"], "—")
        self.assertNotIn("%", goal_hdr.data["sub"])


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class TuiFixes2Test(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.b = _brain(Path(self.tmp.name))
        self.inst = self.b.inst

    def app(self):
        from brainlib.tui.app import BrainApp
        return BrainApp(self.inst)

    async def test_palette_saude_online_and_wizmem_run_sys_directly(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.3)
            with mock.patch("brainlib.tui.bridge.run_brain",
                            return_value=bridge.Result(args=["doctor", "--online"], rc=0, out="ok ledger", err="")) as m_brain:
                app.run_catalog((2, 2, 0, "enter", "sys:doctor"))
                for _ in range(40):
                    await pilot.pause(0.05)
                    if type(app.screen).__name__ == "TextModal":
                        break
                self.assertEqual(app.face, 2)
                self.assertEqual(app.p, 2)
                self.assertFalse(app.zoom)
                self.assertEqual(type(app.screen).__name__, "TextModal")
                self.assertTrue(any(call.args[1] == ["doctor", "--online"] for call in m_brain.call_args_list))
            await pilot.press("escape")
            await pilot.pause(0.1)

            with mock.patch.object(app, "external") as m_ext:
                app.run_catalog((2, 1, 0, "w", "sys:wizmem"))
                await pilot.pause(0.1)
                self.assertEqual(app.face, 2)
                self.assertEqual(app.p, 1)
                m_ext.assert_called_once()
                self.assertEqual(m_ext.call_args.args[0][-3:], ["setup", "--only", "memoria"])

    async def test_typing_title_debounces_dupes_similar_and_caches_index(self):
        from textual.widgets import Input

        self.b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Revisar contrato anual", "list": "mine"}})
        self.b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Fechar orçamento mensal", "list": "mine"}})
        app = self.app()
        real_similar = dupes.similar
        real_index = dupes.Index

        with mock.patch("brainlib.dupes.similar", side_effect=real_similar) as m_sim, \
             mock.patch("brainlib.dupes.Index", side_effect=real_index) as m_idx:
            async with app.run_test(size=(140, 44)) as pilot:
                await pilot.pause(0.3)
                await pilot.press("n")
                await pilot.pause(0.2)
                self.assertEqual(type(app.screen).__name__, "FormModal")
                self.assertEqual(m_sim.call_count, 0)

                inp = app.screen.query_one("#f_title", Input)
                text = "Revisar contrato anual"
                for i in range(1, len(text) + 1):
                    inp.value = text[:i]
                await pilot.pause(0.02)
                # Imediatamente após digitar N teclas, o debounce ainda não disparou
                self.assertEqual(m_sim.call_count, 0)
                await pilot.pause(0.25)
                self.assertEqual(m_sim.call_count, 1)
                self.assertEqual(m_idx.call_count, 1)

                # Mais teclas reaproveitam o Index em cache no Store
                for suffix in (" n", " no", " nov", " novo"):
                    inp.value = text + suffix
                await pilot.pause(0.25)
                self.assertEqual(m_sim.call_count, 2)
                self.assertEqual(m_idx.call_count, 1)

                # Cancelar enquanto há timer pendente não levanta NoMatches no unmount
                inp.value = text + " novo x"
                await pilot.pause(0.01)
                await pilot.press("escape")
                await pilot.pause(0.2)
                self.assertEqual(len(app.screen_stack), 1)

                # Store.load() invalida o índice em cache
                app.store.load()
                app.store.dup_index()
                self.assertEqual(m_idx.call_count, 2)

    async def test_escape_does_not_clear_filter_of_another_tab(self):
        self.b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Ação filtrada", "list": "mine"}})
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.3)
            app.p = 2
            app.tab[2] = 0
            app.filt = (2, 0, "filtrada")
            app.redraw()

            # Em outra aba do mesmo painel, esc não limpa o filtro da aba 0
            app.tab[2] = 1
            app.redraw()
            await pilot.press("escape")
            await pilot.pause(0.1)
            self.assertEqual(app.filt, (2, 0, "filtrada"))

            # Em outro painel, esc também não limpa o filtro de (2, 0)
            app.p = 3
            app.redraw()
            await pilot.press("escape")
            await pilot.pause(0.1)
            self.assertEqual(app.filt, (2, 0, "filtrada"))

            # De volta à aba onde o filtro mora, esc limpa
            app.p = 2
            app.tab[2] = 0
            app.redraw()
            await pilot.press("escape")
            await pilot.pause(0.1)
            self.assertIsNone(app.filt)

    async def test_watch_skips_reload_if_signature_matches_inside_lock(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.3)
            current_sig = app.store.sig
            with mock.patch.object(app.store, "signature", side_effect=[("changed",), current_sig]), \
                 mock.patch.object(app, "_reload", new=mock.AsyncMock()) as m_reload, \
                 mock.patch.object(app, "log_line") as m_log:
                await app._watch()
                m_reload.assert_not_awaited()
                self.assertFalse(any("releitura feita" in str(c.args[0]) for c in m_log.call_args_list))

    async def test_form_modal_raw_treats_select_null_as_empty(self):
        from types import SimpleNamespace
        from textual.widgets import Select
        from brainlib.tui.modals import Field, FormModal, FormSpec

        spec = FormSpec(
            title="Teste Select NULL",
            fields=[Field(id="opt", label="Opção", options=lambda v: [])],
            build=lambda v: [],
        )
        modal = FormModal(spec)
        null = getattr(Select, "NULL", Select.BLANK)
        with mock.patch.object(modal, "query_one", return_value=SimpleNamespace(value=null)):
            self.assertEqual(modal._raw()["opt"], "")


if __name__ == "__main__":
    unittest.main()
