"""Testes das correções e higiene do app da TUI (#67, #68, #87, #81)."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, doctor, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    horizon = (util.today() + timedelta(days=90)).isoformat()
    due1 = (util.today() + timedelta(days=14)).isoformat()
    due2 = (util.today() + timedelta(days=28)).isoformat()
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona Demo"\n\n'
        '[outbound]\nallow = ["marina-demo", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n"
        f"## GOAL-1 — Meta\n- status: ativo\n- horizonte: {horizon}\n- por quê: teste\n\n"
        "### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        f"- [ ] PROJ-1.1 Entregável 1 · prazo: {due1} · peso: 2\n"
        f"- [ ] PROJ-1.2 Entregável 2 · prazo: {due2}\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({
        "type": "person.added",
        "id": "eu",
        "by": "owner",
        "data": {"name": "Dona Demo", "aliases": ["Eu"], "relation": "dono"},
    })
    b.record_one({
        "type": "person.added",
        "id": "marina-demo",
        "by": "owner",
        "data": {"name": "Marina Demo", "aliases": ["Mari Demo"], "email": "marina-demo@example.com"},
    })
    return b


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class PickerUnmountTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.b = _brain(Path(self.tmp.name))
        self.inst = self.b.inst

    async def test_closing_picker_mid_search_does_not_crash_app(self):
        from rich.text import Text
        from brainlib.tui.app import BrainApp
        from brainlib.tui.modals import PickItem, PickerModal

        started = threading.Event()
        release = threading.Event()

        def slow_source(_q: str) -> list[PickItem]:
            started.set()
            release.wait(timeout=2.0)
            return [PickItem(Text("item"), "a")]

        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            modal = PickerModal("Busca", "…", slow_source)
            app.push_screen(modal)
            for _ in range(100):
                if started.is_set():
                    break
                await pilot.pause(0.02)
            self.assertTrue(started.is_set())

            worker = modal._worker
            await pilot.press("escape")
            await pilot.pause(0.05)
            release.set()
            for _ in range(10):
                await pilot.pause(0.05)

            self.assertTrue(app.is_running)
            self.assertEqual(len(app.screen_stack), 1)
            if worker is not None:
                self.assertNotIsInstance(worker.error, Exception)


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class DoctorFixNavigationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.b = _brain(Path(self.tmp.name))
        self.inst = self.b.inst

    async def test_fix_doc_from_config_navigates_to_exec_panel_and_tab(self):
        from brainlib.tui.app import BrainApp
        from brainlib.tui.store import Item

        cases = [
            ("ações sem prazo", (0, 2, 0)),
            ("perguntas", (0, 4, 0)),
            ("propostas", (0, 4, 1)),
            ("mensagens", (0, 4, 2)),
            ("foco", (0, 4, 3)),
        ]
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            orig_cur = app.cur
            for title, (want_face, want_p, want_tab) in cases:
                app.face_to(2)
                app.p = 2
                app.redraw()
                fix = doctor.fix_for({"title": title, "level": "warn", "detail": ""})
                self.assertIsNotNone(fix, title)
                stub = Item("h:0", "doc", {"title": title, "level": "warn", "detail": ""}, extra={"fix": fix})
                once = [stub]
                with mock.patch.object(app, "cur", side_effect=lambda: once.pop(0) if once else orig_cur()):
                    app.fix_doc()
                self.assertEqual(app.face, want_face, title)
                self.assertEqual(app.p, want_p, title)
                self.assertEqual(app.tab[want_p], want_tab, title)
                self.assertIn(want_p, app.panels, title)

            # Destino desconhecido: não troca de face nem aponta para painel fora de self.panels
            app.face_to(2)
            app.p = 2
            tab_before = app.tab[2]
            app.redraw()
            logged: list[tuple[str, str]] = []
            stub_bad = Item("h:0", "doc", {"title": "desconhecido", "level": "warn", "detail": ""},
                            extra={"fix": {"label": "teste", "go": (99, 0)}})
            once_bad = [stub_bad]
            with mock.patch.object(app, "cur", side_effect=lambda: once_bad.pop(0) if once_bad else orig_cur()), \
                 mock.patch.object(app, "log_line", side_effect=lambda msg, style="": logged.append((msg, style))):
                app.fix_doc()
            self.assertEqual(app.face, 2)
            self.assertEqual(app.p, 2)
            self.assertEqual(app.tab[2], tab_before)
            self.assertTrue(any("destino desconhecido" in msg for msg, _ in logged), logged)


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class ActionDuplicateConfirmTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.b = _brain(Path(self.tmp.name))
        self.a1 = self.b.record_one({
            "type": "action.opened",
            "by": "owner",
            "data": {"title": "Fechar contrato da Padaria Pão Quente", "list": "mine"},
        })["id"]
        self.inst = self.b.inst

    async def test_duplicate_action_prompts_confirm_before_forcing(self):
        from brainlib.tui.app import BrainApp
        from brainlib.tui.modals import ConfirmModal

        app = BrainApp(self.inst)
        calls: list[list[list[str]]] = []
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            with mock.patch.object(app, "run_cmds", side_effect=lambda cmds, **kw: calls.append(cmds)):
                await pilot.press("n")
                await pilot.pause(0.2)
                app.screen.query_one("#f_title").value = "Fechar contrato da Padaria Pão Quente"
                await pilot.pause(0.1)
                await pilot.press("ctrl+s")
                await pilot.pause(0.2)

                self.assertEqual(calls, [])
                self.assertIsInstance(app.screen, ConfirmModal)
                self.assertEqual(app.screen.title_, "Possível duplicata")
                self.assertIn(self.a1, app.screen.body)
                self.assertIn("Fechar contrato da Padaria Pão Quente", app.screen.body)

                await pilot.press("escape")
                await pilot.pause(0.15)
                self.assertEqual(calls, [])
                self.assertEqual(len(app.screen_stack), 1)

                await pilot.press("n")
                await pilot.pause(0.2)
                app.screen.query_one("#f_title").value = "Fechar contrato da Padaria Pão Quente"
                await pilot.pause(0.1)
                await pilot.press("ctrl+s")
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, ConfirmModal)

                await pilot.press("enter")
                await pilot.pause(0.2)
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(calls[0]), 1)
                self.assertEqual(calls[0][0].count("--force"), 1)

    async def test_people_eu_counts_as_the_owner_in_the_duplicate_probe(self):
        """"eu" em pessoas vale o dono do Brain (como em cli._resolve_people). Sem esse fold a ficha literal de "eu"
        não bate com o id do dono, o título perde metade da nota e a duplicata é enviada sem confirmação."""
        from brainlib.tui.app import BrainApp
        from brainlib.tui.modals import ConfirmModal

        tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(tmp2.cleanup)
        root = Path(tmp2.name)
        _inst(root)                                    # a mesma instância do harness…
        cfg = root / "config" / "brain.toml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace('id = "eu"', 'id = "dona-demo"'), encoding="utf-8")
        b = Brain(config.load(root))                   # …só que o dono não se chama "eu" nem tem "eu" de alias
        b.record_one({
            "type": "person.added", "id": "dona-demo", "by": "owner",
            "data": {"name": "Dona Demo", "aliases": ["Dona"], "relation": "dono"},
        })
        b.record_one({
            "type": "action.opened", "by": "owner",
            "data": {"title": "Fechar contrato da Padaria Pão Quente", "list": "mine",
                     "owner": "dona-demo", "people": ["dona-demo"]},
        })
        app = BrainApp(b.inst)
        calls: list[list[list[str]]] = []
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            with mock.patch.object(app, "run_cmds", side_effect=lambda cmds, **kw: calls.append(cmds)):
                await pilot.press("n")
                await pilot.pause(0.2)
                app.screen.query_one("#f_title").value = "Fechar contrato da Padaria Pão Quente"
                app.screen.query_one("#f_people").value = "eu"
                await pilot.pause(0.1)
                await pilot.press("ctrl+s")
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, ConfirmModal)
                self.assertIn("TASK-0001", app.screen.body)
                self.assertEqual(calls, [])

    async def test_unique_action_submits_without_duplicate_modal(self):
        from brainlib.tui.app import BrainApp

        app = BrainApp(self.inst)
        calls: list[list[list[str]]] = []
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            with mock.patch.object(app, "run_cmds", side_effect=lambda cmds, **kw: calls.append(cmds)):
                await pilot.press("n")
                await pilot.pause(0.2)
                app.screen.query_one("#f_title").value = "Revisar manual de estoque trimestral"
                await pilot.pause(0.1)
                await pilot.press("ctrl+s")
                await pilot.pause(0.2)

                self.assertEqual(len(app.screen_stack), 1)
                self.assertEqual(len(calls), 1)


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class TuiHygieneTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.b = _brain(Path(self.tmp.name))
        self.b.record_one({"type": "area.added", "id": "operacoes", "by": "owner", "data": {"name": "Operações"}})
        self.opp = self.b.record_one({
            "type": "opportunity.added",
            "by": "owner",
            "data": {"title": "Automatizar conciliação", "area": "operacoes"},
        })["id"]
        self.inst = self.b.inst

    async def test_select_overlay_public_api_without_private_import(self):
        from textual.widgets import Select
        from brainlib.tui import modals
        from brainlib.tui.app import BrainApp
        from brainlib.tui.modals import Field, FormModal, FormSpec, _in_select_overlay

        src = Path(modals.__file__).read_text(encoding="utf-8")
        self.assertNotIn("textual.widgets._select", src)
        self.assertNotIn("SelectOverlay", src)

        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            spec = FormSpec(
                title="Teste Select",
                fields=[
                    Field(id="sel", label="Escolha", choice=[("a", "A"), ("b", "B")], value="a"),
                    Field(id="txt", label="Texto", value=""),
                ],
                build=lambda v: [],
            )
            modal = FormModal(spec)
            app.push_screen(modal)
            await pilot.pause(0.2)

            sel = modal.query_one("#f_sel", Select)
            sel.focus()
            await pilot.pause(0.05)
            await pilot.press("space")
            await pilot.pause(0.1)

            self.assertTrue(sel.expanded)
            self.assertTrue(_in_select_overlay(modal, modal.focused))
            self.assertFalse(modal.check_action("enter_submit", ()))

            await pilot.press("escape")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, FormModal)
            self.assertFalse(_in_select_overlay(modal, modal.focused))

    def test_doc_link_hint_uses_uppercase_L(self):
        from brainlib.tui import rows
        from brainlib.tui.app import CMD_CATALOG
        from brainlib.tui.store import Store

        st = Store(self.inst)
        it = next(i for i in st.items(1, 3, 0) if i.id == self.opp)
        text = rows.detail(st, it).plain
        self.assertIn("L liga um documento", text)
        self.assertNotIn("l liga um documento", text)

        entry = next(go for name, _, go in CMD_CATALOG if name == "Ligar documento")
        self.assertEqual(entry[3], "L")

    async def test_unknown_sys_fix_does_not_raise_value_error(self):
        from brainlib.tui.app import BrainApp
        from brainlib.tui.store import Item

        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            stub = Item("h:0", "doc", {"title": "desconhecido", "level": "warn", "detail": ""},
                        extra={"fix": {"label": "teste", "sys": "sys:inexistente"}})
            with mock.patch.object(app, "cur", return_value=stub):
                app.fix_doc()
            app.run_catalog((0, 1, 0, None, "sem-prefixo"))

    def test_renamed_methods_and_no_builtin_shadows(self):
        from brainlib.tui.app import BrainApp

        self.assertNotIn("exec", BrainApp.__dict__)
        self.assertNotIn("help", BrainApp.__dict__)
        self.assertTrue(callable(BrainApp.run_cmds))
        self.assertTrue(callable(BrainApp.show_help))


if __name__ == "__main__":
    unittest.main()
