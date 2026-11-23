"""Regressões pontuais do TUI (#11, #12, #15, #16, #17) — relógio congelado, sem rede."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, model, util
from brainlib.core import Brain
from brainlib.tui import bridge

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


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


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class TuiFixesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.b = _brain(Path(self.tmp.name))
        self.inst = self.b.inst

    async def test_border_subtitle_align_right(self):
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            for pid in range(1, 7):
                self.assertEqual(app.query_one(f"#p{pid}").styles.border_subtitle_align, "right")

    async def test_fix_doc_sys_selects_real_tab(self):
        from brainlib.tui.app import BrainApp, SYS_TAB
        from brainlib.tui.store import Store
        app = BrainApp(self.inst)
        app.store = Store(self.inst)
        app.face = 2  # Saúde mora na face Configurações
        stub = SimpleNamespace(extra={"fix": {"sys": "sys:render"}})
        with mock.patch.object(app, "cur", return_value=stub):
            app.fix_doc()
        self.assertEqual(app.face, 0)
        self.assertTrue(0 <= app.tab[1] < len(app.panels[1][1]))
        self.assertEqual(app.panels[1][1][app.tab[1]], SYS_TAB)
        self.assertEqual(app.cur().id, "sys:render")

    async def test_dead_panel_help_and_tab_move(self):
        from brainlib.tui.app import BrainApp
        from brainlib.tui.modals import TextModal
        from brainlib.tui.store import FACES
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            while FACES[app.face][0] != "Configurações":
                await pilot.press("tab")
            await pilot.press("3")
            self.assertNotIn(app.p, app.panels)
            for key in ("h", "l", "[", "]"):
                await pilot.press(key)
            await pilot.press("question_mark")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, TextModal)
            for key in ("h", "l", "[", "]"):
                await pilot.press(key)
            self.assertIsInstance(app.screen, TextModal)

    def test_cycle_status_ignores_closed_blocker(self):
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        app.cur = lambda: SimpleNamespace(data={
            "id": "TASK-0002", "status": "aberta",
            "blocked_by": [], "blocked_by_all": ["TASK-0001"],
        })
        app.run_cmds = mock.Mock()
        app.cycle_status()
        self.assertEqual(
            app.run_cmds.call_args[0][0],
            [["action", "update", "TASK-0002", "--status", "fazendo", "--by", "owner"]],
        )
        # Contra-caso: bloqueador ainda aberto em blocked_by impede o avanço
        app.cur = lambda: SimpleNamespace(data={
            "id": "TASK-0002", "status": "aberta",
            "blocked_by": ["TASK-0001"], "blocked_by_all": ["TASK-0001"],
        })
        app.run_cmds = mock.Mock()
        app.cycle_status()
        app.run_cmds.assert_not_called()

    def test_model_blocked_by_open_only(self):
        self.assertTrue(bridge.run_brain(self.inst, ["action", "open", "Bloqueadora", "--by", "owner"]).ok)
        self.assertTrue(bridge.run_brain(self.inst, ["action", "open", "Dependente", "--blocked-by", "TASK-0001", "--by", "owner"]).ok)
        self.assertTrue(bridge.run_brain(self.inst, ["action", "close", "TASK-0001", "--how", "resolvida", "--by", "owner"]).ok)
        self.b.reload()
        row = next(a for a in model.build(self.b)["actions"] if a["id"] == "TASK-0002")
        self.assertEqual(row["blocked_by"], [])
        self.assertEqual(row["blocked_by_all"], ["TASK-0001"])

    async def test_render_failure_logged_as_warning(self):
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            logged: list[tuple[str, str]] = []

            def fake_run(_inst, args, timeout=300):
                if args == ["render"]:
                    return bridge.Result(["render"], 1, "", "Traceback…\nValueError: boom")
                return bridge.Result(args, 0, "ok", "")

            with mock.patch.object(app, "log_line", side_effect=lambda text, style="": logged.append((text, style))), \
                 mock.patch.object(bridge, "run_brain", side_effect=fake_run):
                await app._exec([["status"]], True, None)

            self.assertTrue(any(style == "yellow" for _, style in logged), logged)
            self.assertFalse(any(text.startswith("↻ brain render") for text, _ in logged), logged)

    async def test_log_line_uses_instance_clock(self):
        from textual.widgets import RichLog
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            written = []
            with mock.patch.dict(os.environ, {"BRAIN_NOW": "2026-10-09T03:45:00-03:00"}), \
                 mock.patch.object(RichLog, "write", side_effect=lambda content, *a, **kw: written.append(content)):
                app.log_line("teste de relógio")
                want_prefix = util.now().strftime("%H:%M ")
            self.assertEqual(len(written), 1)
            self.assertTrue(written[0].plain.startswith(want_prefix), written[0].plain)
            self.assertEqual(written[0].plain, f"{want_prefix}teste de relógio")


if __name__ == "__main__":
    unittest.main()
