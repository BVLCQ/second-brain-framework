"""Testes de segurança do TUI: edição do goals.md em cópia temporária (#135) e redação de chaves (#138)."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, demo as demo_mod, forms  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.tui import bridge  # noqa: E402

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


def _make_demo(tmp: str) -> config.Instance:
    root = Path(tmp) / "inst"
    with contextlib.redirect_stdout(io.StringIO()):
        demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
    return config.load(root)


class SecretRedactionTest(unittest.TestCase):
    def test_bridge_display_and_modal_preview_redact_secret_flags(self):
        self.assertEqual(forms.secret_flags(), frozenset({"--key", "--emb-key", "--reranker-key"}))
        tok1 = "sk-" + "ant-oat01-demo"
        tok2 = "fw-" + "emb-secret-demo"
        tok3 = "-co-" + "rerank-dash-demo"
        long_tok = "sk-" + ("x" * 350)

        for flag, tok in (("--key", tok1), ("--emb-key", tok2), ("--reranker-key", tok3), ("--key", long_tok)):
            argv_space = ["memory", "providers", "set", "llm", "--provider", "openai", flag, tok]
            argv_eq = ["memory", "providers", "set", "llm", "--provider", "openai", f"{flag}={tok}"]

            # safe_args preserva o valor real para execução
            safe_space = bridge.safe_args(argv_space)
            self.assertTrue(any(tok in a for a in safe_space), f"safe_args perdeu o segredo para {flag}")

            # bridge.display redige tanto `--flag <val>` quanto `--flag=<val>` (inclusive com '-' ou > MAX_ARG)
            for argv in (argv_space, argv_eq):
                disp = bridge.display(argv)
                self.assertNotIn(tok, disp)
                self.assertIn("***", disp)
                self.assertIn(flag, disp)

            # forms.display acompanha a mesma redação
            fdisp = forms.display([argv_space, argv_eq])
            self.assertNotIn(tok, fdisp)
            self.assertIn("***", fdisp)

            if HAVE_TEXTUAL:
                from brainlib.tui import modals
                prev = modals.preview([argv_space, argv_eq]).plain
                self.assertNotIn(tok, prev)
                self.assertIn("***", prev)

        # flags desconhecidas permanecem intactas
        plain = bridge.redact_args(["memory", "providers", "set", "llm", "--provider", "openai"])
        self.assertEqual(plain, ["memory", "providers", "set", "llm", "--provider", "openai"])

    @unittest.skipUnless(shutil.which("node"), "node ausente")
    def test_forms_js_display_redacts_secrets(self):
        tok1 = "sk-" + "ant-oat01-demo"
        tok2 = "fw-" + "emb-secret-demo"
        tok3 = "co-" + "rerank-demo"
        cmds = [
            ["memory", "providers", "set", "llm", "--provider", "openai", "--key", tok1],
            ["memory", "setup", "--mode", "full", "--emb-key", tok2, f"--reranker-key={tok3}"],
        ]
        script = (
            "const F = require(process.argv[1]);\n"
            "const cmds = JSON.parse(process.argv[2]);\n"
            "process.stdout.write(JSON.stringify({display: F.display(cmds), raw: F.shjoin(cmds[0])}));\n"
        )
        r = subprocess.run(
            ["node", "-e", script, str(ROOT / "brainlib" / "assets" / "src" / "forms.js"), json.dumps(cmds)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        for tok in (tok1, tok2, tok3):
            self.assertNotIn(tok, out["display"])
        self.assertIn("--key '***'", out["display"])
        self.assertIn("--emb-key '***'", out["display"])
        self.assertIn("'--reranker-key=***'", out["display"])
        self.assertEqual(out["display"], forms.display(cmds))
        self.assertIn(tok1, out["raw"])


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class TuiSafetyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inst = _make_demo(self.tmp.name)

    async def settle(self, app, pilot, n=80):
        for _ in range(n):
            await pilot.pause(0.1)
            if not app.busy and not app._lock.locked() and len(app.screen_stack) == 1:
                return
        self.fail("o TUI não terminou de executar")

    def log_text(self, app) -> str:
        from textual.widgets import RichLog
        return "\n".join(str(ln.text) for ln in app.query_one("#log", RichLog).lines)

    async def test_edit_plan_uses_temp_copy_and_leaves_real_file_untouched_on_cancel(self):
        from brainlib.tui.app import BrainApp
        goals = self.inst.planning_file
        before = goals.read_bytes()
        seen_paths: list[Path] = []
        addition = "\n## GOAL-9 — Meta temporária\n- status: ativo\n- horizonte: 2027-01-01\n- por quê: teste\n"

        def fake_external(argv: list[str]) -> None:
            target = Path(argv[-1])
            seen_paths.append(target)
            target.write_text(target.read_text(encoding="utf-8") + addition, encoding="utf-8")

        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            with mock.patch.object(app, "external", side_effect=fake_external):
                await pilot.press("3", "E")
                await pilot.pause(0.3)
            self.assertEqual(len(seen_paths), 1)
            edited = seen_paths[0]
            self.assertEqual(edited.name, "goals.md")
            self.assertNotEqual(edited.resolve(), goals.resolve())
            self.assertFalse(edited.parent.exists(), "diretório temporário deve ser limpo após o editor")
            self.assertEqual(type(app.screen).__name__, "FormModal")
            # arquivo real continua byte-idêntico enquanto o modal de gate está aberto
            self.assertEqual(goals.read_bytes(), before)

            await pilot.press("escape")
            await pilot.pause(0.2)
            self.assertEqual(goals.read_bytes(), before)
            self.assertEqual(Brain(self.inst).state.plan_changes, [])

    async def test_edit_plan_writes_only_on_approval_and_detects_external_drift(self):
        from brainlib.tui.app import BrainApp
        goals = self.inst.planning_file
        before = goals.read_text(encoding="utf-8")
        addition = "\n## GOAL-9 — Meta aprovada\n- status: ativo\n- horizonte: 2027-01-01\n- por quê: teste\n"

        def fake_external(argv: list[str]) -> None:
            target = Path(argv[-1])
            target.write_text(target.read_text(encoding="utf-8") + addition, encoding="utf-8")

        # 1) Aprovação: grava goals.md atomicamente e registra plan.changed
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            with mock.patch.object(app, "external", side_effect=fake_external):
                await pilot.press("3", "E")
                await pilot.pause(0.3)
            self.assertEqual(goals.read_text(encoding="utf-8"), before)
            app.screen.query_one("#f_diff").value = "GOAL-9 nasce"
            app.screen.query_one("#f_reason").value = "expansão"
            await pilot.pause(0.1)
            app.screen.action_submit()
            await self.settle(app, pilot)
            self.assertEqual(goals.read_text(encoding="utf-8"), before + addition)
            changes = Brain(self.inst).state.plan_changes
            self.assertEqual(changes[-1]["diff"], "GOAL-9 nasce")

        # 2) Drift externo entre editor e aprovação: recusa sem sobrescrever
        inst2 = _make_demo(self.tmp.name + "-drift")
        goals2 = inst2.planning_file
        before2 = goals2.read_text(encoding="utf-8")
        external_edit = before2 + "\n# edição externa concorrente\n"
        app2 = BrainApp(inst2)
        async with app2.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            with mock.patch.object(app2, "external", side_effect=fake_external):
                await pilot.press("3", "E")
                await pilot.pause(0.3)
            goals2.write_text(external_edit, encoding="utf-8")
            app2.screen.query_one("#f_diff").value = "GOAL-9 nasce"
            app2.screen.query_one("#f_reason").value = "expansão"
            await pilot.pause(0.1)
            app2.screen.action_submit()
            await self.settle(app2, pilot)
            self.assertEqual(goals2.read_text(encoding="utf-8"), external_edit)
            self.assertEqual(Brain(inst2).state.plan_changes, [])
            self.assertIn("mudou fora do TUI", self.log_text(app2))

    async def test_exec_and_form_modal_do_not_log_secret_key(self):
        from brainlib.tui.app import BrainApp
        tok = "sk-" + "ant-oat01-demo"
        app = BrainApp(self.inst)
        seen_argv: list[list[str]] = []

        def fake_run(inst, args, *a, **kw):
            seen_argv.append(list(args))
            return bridge.Result(args, 0, "ok", "")

        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.open_form("memory.provider", {"provider": "openai"}, values={"slot": "llm", "provider": "openai", "key": tok},
                          render=False)
            await pilot.pause(0.3)
            cmdp = str(app.screen.query_one("#cmdp").render())
            self.assertNotIn(tok, cmdp)
            self.assertIn("***", cmdp)
            with mock.patch.object(bridge, "run_brain", fake_run):
                app.screen.action_submit()
                await self.settle(app, pilot)
            self.assertTrue(seen_argv)
            self.assertIn(tok, seen_argv[0])
            self.assertNotIn(tok, self.log_text(app))
            self.assertIn("***", self.log_text(app))


if __name__ == "__main__":
    unittest.main()
