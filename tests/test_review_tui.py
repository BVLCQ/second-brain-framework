"""Regressões da revisão do TUI: argv blindado contra texto com '-', agente não fica órfão, permissões que o TUI não libera,
tecla r nas Propostas, gate do PLANNING que falha, config relida depois de `brain agent allow`.
Os testes de UI rodam só com o Textual instalado (`./brain tui --setup`); usam o demo numa pasta temporária."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, demo as demo_mod  # noqa: E402
from brainlib.tui import bridge  # noqa: E402

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


def make_demo(tmp: str) -> config.Instance:
    root = Path(tmp) / "inst"
    with contextlib.redirect_stdout(io.StringIO()):
        demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
    return config.load(root)


class SafeArgsTest(unittest.TestCase):
    def test_dash_values_become_equals_or_go_after_double_dash(self):
        sa = bridge.safe_args
        self.assertEqual(sa(["note", "add", "--text", "-urgente"]), ["note", "add", "--text=-urgente"])
        self.assertEqual(sa(["action", "close", "TASK-0001", "--how", "--by=agent", "--by", "owner"]),
                         ["action", "close", "TASK-0001", "--how=--by=agent", "--by", "owner"])
        self.assertEqual(sa(["ask", "answer", "ASK-0001", "--no", "--by", "owner"]),
                         ["ask", "answer", "--by", "owner", "--", "ASK-0001", "--no"])
        # sem '-' na frente, a linha não muda (nem a ordem); flags sem valor seguem flags
        plain = ["action", "update", "TASK-0001", "--clear-due", "--by", "owner"]
        self.assertEqual(sa(plain), plain)
        self.assertEqual(sa(["note", "add", "--text", "- item com espaço"]), ["note", "add", "--text=- item com espaço"])
        self.assertEqual(bridge.display(["note", "add", "--text", "-x"]), "brain note add --text=-x")

    def test_cli_accepts_the_hardened_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = make_demo(tmp)
            r = bridge.run_brain(inst, ["action", "open", "-x", "--by", "owner", "--origin", "-urgente"])
            self.assertEqual(r.rc, 0, r.err)
            from brainlib.core import Brain
            a = [x for x in Brain(inst).state.actions.values() if x.title == "-x"]
            self.assertEqual(len(a), 1)


class AgentKillTest(unittest.TestCase):
    def test_cancelled_run_kills_the_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = make_demo(tmp)
            pidf = Path(tmp) / "child.pid"
            script = f"import os, time; open({str(pidf)!r}, 'w').write(str(os.getpid())); print('ok', flush=True); time.sleep(30)"

            async def main():
                t = asyncio.create_task(bridge.run_agent(inst, [sys.executable, "-c", script], lambda _ln: None))
                for _ in range(100):
                    await asyncio.sleep(0.05)
                    if pidf.exists() and pidf.read_text():
                        break
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            asyncio.run(main())
            pid = int(pidf.read_text())
            with self.assertRaises(ProcessLookupError):           # o TUI saiu no meio: o agente não segue rodando sozinho
                os.kill(pid, 0)


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class PermissionRulesTest(unittest.TestCase):
    def q(self, rule, *extra, kind="permissao"):
        return mock.Mock(id="ASK-0001", kind=kind, context=[f"allow:{rule}", *extra])

    def test_rule_for_survives_multiline_quotes(self):
        from brainlib.tui.ask_keys import rule_for
        self.assertEqual(rule_for({"tool_name": "Bash", "tool_input": {"command": './brain note add --text "linha 1\nlinha 2"'}}),
                         "Bash(./brain note:*)")

    def test_safe_rule_refuses_external_wide_and_invalid(self):
        from brainlib.tui.ask_keys import safe_rule
        self.assertEqual(safe_rule("mcp__x__list_files"), "mcp__x__list_files")
        self.assertEqual(safe_rule("Bash(./brain add:*)"), "Bash(./brain add:*)")
        for bad in ("mcp__slack__slack_send_message", "mcp__slack", "mcp__slack__*", "Bash(*)", "rm -rf"):
            self.assertEqual(safe_rule(bad), "", bad)

    def test_typed_allow_on_external_question_allows_nothing(self):
        from brainlib.tui.ask_keys import ALLOW_YES, AskKeys
        k = AskKeys()
        for q in (self.q("mcp__slack__slack_send_message", "externo"), self.q("mcp__slack"), self.q("mcp__slack__*")):
            cmds = k._answer_cmds(q, ALLOW_YES)
            self.assertFalse(any(c[:2] == ["agent", "allow"] for c in cmds), cmds)
            self.assertEqual(cmds[-1][:2], ["ask", "applied"])
        ok = k._answer_cmds(self.q("mcp__x__list_files"), ALLOW_YES)
        self.assertIn(["agent", "allow", "mcp__x__list_files", "--scope", "runner"], ok)

    def test_resume_never_passes_external_write_to_allowed_tools(self):
        from brainlib.tui.ask_keys import ALLOW_YES, AskKeys
        app = AskKeys()
        app.inst = mock.Mock(cfg=config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "agent": "claude"}})
        app.last_run = bridge.RunInfo(id="run-1", session_id="sess-1")
        app.log_line = lambda *a, **k: None
        seen = {}
        app.run_worker = lambda coro, **kw: (seen.setdefault("coro", coro), coro.close())
        app._agent = lambda argv, *a, **kw: seen.setdefault("argv", argv) and _noop()
        answered = [mock.Mock(id="ASK-0001", answer=ALLOW_YES, context=["allow:mcp__slack__slack_send_message", "externo"]),
                    mock.Mock(id="ASK-0002", answer=ALLOW_YES, context=["allow:mcp__x__list_files"])]
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            app.resume_now(answered)
        argv = seen["argv"]
        self.assertIn("mcp__x__list_files", argv)
        self.assertNotIn("mcp__slack__slack_send_message", argv)


async def _noop():
    return None


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class ReviewTuiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inst = make_demo(self.tmp.name)

    async def settle(self, app, pilot, n=80):
        for _ in range(n):
            await pilot.pause(0.1)
            if not app.busy and not app._lock.locked() and len(app.screen_stack) == 1:
                return
        self.fail("o TUI não terminou de executar")

    def app(self):
        from brainlib.tui.app import BrainApp
        return BrainApp(self.inst)

    def state(self):
        from brainlib.core import Brain
        return Brain(self.inst).state

    async def test_r_rejects_the_selected_proposal(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "]")
            rid = app.cur().id
            self.assertNotIn("render", str(app.query_one("#globals").render()))      # o global r não aparece escondido
            app.action_hint("r")                                                       # clicar na dica "r rejeitar"
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertIn(f"Rejeitar {rid}", app.screen.spec.title)
            await pilot.press("escape")
            await pilot.pause(0.1)
            await pilot.press("r")                                                     # e a tecla
            await pilot.pause(0.2)
            self.assertIn(f"Rejeitar {rid}", app.screen.spec.title)
            await pilot.press(*"nao", "enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state().proposals[rid].status, "rejeitada")

    async def test_plan_gate_failure_restores_goals(self):
        goals = self.inst.planning_file
        before = goals.read_text(encoding="utf-8")
        after = before + "\n## GOAL-9 — Meta nova\n- status: ativo\n- horizonte: 2027-01-01\n- por quê: teste\n"
        real = bridge.run_brain

        def failing(inst, args, *a, **kw):
            if args[:2] == ["plan", "log"]:
                return bridge.Result(args, 4, "", "ERRO: ledger recusou")
            return real(inst, args, *a, **kw)

        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            goals.write_text(after, encoding="utf-8")                 # o que o editor deixou
            with mock.patch.object(bridge, "run_brain", failing):
                app.gate_for_plan(before, after)
                await pilot.pause(0.2)
                for k, v in (("diff", "GOAL-9 nasce"), ("reason", "nova meta"), ("quote", "ok")):
                    app.screen.query_one(f"#f_{k}").value = v
                await pilot.pause(0.1)
                app.screen.action_submit()
                await self.settle(app, pilot)
            self.assertEqual(goals.read_text(encoding="utf-8"), before)   # sem o registro do gate, a árvore não muda
            self.assertFalse(any(c.get("diff") == "GOAL-9 nasce" for c in self.state().plan_changes))

    async def test_agent_allow_is_picked_up_without_restarting(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.exec([["agent", "allow", "Bash(./brain note:*)", "--scope", "tui"]], render=False)
            await self.settle(app, pilot)
            self.assertIn("Bash(./brain note:*)", app.inst.cfg["tui"]["agent_allow"])
            cfg = app.inst.cfg | {"runner": {**app.inst.cfg["runner"], "agent": "claude", "command": ""}}
            with mock.patch("shutil.which", return_value="/usr/bin/claude"):
                self.assertIn("Bash(./brain note:*)", bridge.agent_argv(cfg, "/dump"))


if __name__ == "__main__":
    unittest.main()
