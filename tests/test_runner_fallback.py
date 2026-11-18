"""Testes do runner: candidatos, fallback noturno, sonda de login, aviso de MCP e doctor."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, doctor, runner, setup, watch  # noqa: E402
from brainlib.core import Brain  # noqa: E402


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


class StubUI(setup.ConsoleUI):
    """UI de teste que registra as opções de choice e controla interatividade."""

    def __init__(self, choice_ans: str | None = None, confirm_ans: bool = False, interactive: bool = True):
        self.interactive = interactive
        self.choice_ans = choice_ans
        self.confirm_ans = confirm_ans
        self.choices_seen: list[list[str]] = []
        self.said: list[str] = []

    def say(self, msg: str) -> None:
        self.said.append(msg)

    def choice(self, prompt: str, options: list[str], default: str) -> str:
        self.choices_seen.append(list(options))
        return self.choice_ans if self.choice_ans is not None else default

    def confirm(self, prompt: str, default: bool = False) -> bool:
        return self.confirm_ans


class RunnerFallbackTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._env = mock.patch.dict(os.environ, {"HOME": str(self.tmp)})
        self._env.start()
        self._ni = mock.patch.object(setup, "nightly_installed", return_value=False)
        self._ni.start()

    def tearDown(self):
        self._ni.stop()
        self._env.stop()
        self._td.cleanup()

    def _cfg(self, **runner_over) -> dict:
        return {**config.DEFAULTS, "runner": {**config.DEFAULTS["runner"], **runner_over}}

    def test_candidates_order_and_modes(self):
        bins = {"claude": "/bin/claude", "codex": "/bin/codex"}
        with mock.patch.object(runner.shutil, "which", side_effect=bins.get):
            c_auto = runner.agent_candidates(self._cfg(agent="auto"))
            self.assertEqual([n for n, _ in c_auto], ["claude", "codex"])

            c_explicit = runner.agent_candidates(self._cfg(agent="codex", fallback=True))
            self.assertEqual([n for n, _ in c_explicit], ["codex", "claude"])

            c_no_fb = runner.agent_candidates(self._cfg(agent="codex", fallback=False))
            self.assertEqual([n for n, _ in c_no_fb], ["codex"])

            c_cmd = runner.agent_candidates(self._cfg(command="meu-bin --flag {prompt}"))
            self.assertEqual(len(c_cmd), 1)
            self.assertEqual(c_cmd[0][0], "command")
            self.assertEqual(c_cmd[0][1][:2], ["meu-bin", "--flag"])

            c_none = runner.agent_candidates(self._cfg(agent="none"))
            self.assertEqual(c_none, [])

            claude_argv = dict(c_auto)["claude"]
            m_idx = claude_argv.index("--model")
            a_idx = claude_argv.index("--allowedTools")
            self.assertEqual(claude_argv[m_idx + 1], "claude-haiku-5-5")
            self.assertLess(m_idx, a_idx)

    def test_nightly_fallback_on_early_auth_error(self):
        b = _brain(self.tmp / "inst")
        bins = {"claude": "/bin/claude", "codex": "/bin/codex"}
        calls: list[list[str]] = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            if len(calls) == 1:
                kw["stdout"].write("Error: Authentication required\n")
                kw["stdout"].flush()
                return subprocess.CompletedProcess(cmd, 1)
            return subprocess.CompletedProcess(cmd, 0)

        with mock.patch.object(runner.shutil, "which", side_effect=bins.get), \
             mock.patch.object(runner.subprocess, "run", side_effect=fake_run):
            res = runner.nightly(b)

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "claude")
        self.assertEqual(calls[1][0], "codex")
        self.assertTrue(res["steps"]["agente"].startswith("codex ok"))
        self.assertIn("Authentication required", res["steps"]["agente"])
        self.assertTrue(res["ok"])
        self.assertTrue(b.state.runs["nightly"]["ok"])

    def test_no_fallback_after_footprint(self):
        b = _brain(self.tmp / "inst")
        bins = {"claude": "/bin/claude", "codex": "/bin/codex"}
        calls: list[list[str]] = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            (b.inst.inbox / "x.md").write_text("parcial", encoding="utf-8")
            kw["stdout"].write("boom depois de escrever\n")
            kw["stdout"].flush()
            return subprocess.CompletedProcess(cmd, 1)

        with mock.patch.object(runner.shutil, "which", side_effect=bins.get), \
             mock.patch.object(runner.subprocess, "run", side_effect=fake_run):
            res = runner.nightly(b)

        self.assertEqual(len(calls), 1)
        self.assertTrue(res["steps"]["agente"].startswith("falhou:"))
        self.assertFalse(res["ok"])
        self.assertFalse(b.state.runs["nightly"]["ok"])

    def test_timeout_does_not_fallback(self):
        b = _brain(self.tmp / "inst")
        bins = {"claude": "/bin/claude", "codex": "/bin/codex"}
        calls: list[list[str]] = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            raise subprocess.TimeoutExpired(cmd, 2700)

        with mock.patch.object(runner.shutil, "which", side_effect=bins.get), \
             mock.patch.object(runner.subprocess, "run", side_effect=fake_run):
            res = runner.nightly(b)

        self.assertEqual(len(calls), 1)
        self.assertTrue(res["steps"]["agente"].startswith("falhou:"))
        self.assertFalse(res["ok"])

    def test_all_candidates_fail_lists_both(self):
        b = _brain(self.tmp / "inst")
        bins = {"claude": "/bin/claude", "codex": "/bin/codex"}

        def fake_run(cmd, **kw):
            kw["stdout"].write(f"{cmd[0]}: not logged in\n")
            kw["stdout"].flush()
            return subprocess.CompletedProcess(cmd, 1)

        with mock.patch.object(runner.shutil, "which", side_effect=bins.get), \
             mock.patch.object(runner.subprocess, "run", side_effect=fake_run):
            res = runner.nightly(b)

        self.assertFalse(res["ok"])
        self.assertIn("claude", res["steps"]["agente"])
        self.assertIn("codex", res["steps"]["agente"])

    def test_doctor_detail_for_failed_and_fallback_runs(self):
        b = _brain(self.tmp / "inst")
        b.record_one({
            "type": "run.completed",
            "id": "nightly",
            "by": "system",
            "data": {
                "ok": False,
                "steps": {"agente": "falhou: claude saiu com código 1 — Authentication required (vault/logs/nightly-agent.log)"},
            },
        })
        c_fail = next(c for c in doctor.checks(b) if c["title"] == "noturno")
        self.assertEqual(c_fail["level"], "warn")
        self.assertIn("agente:", c_fail["detail"])
        self.assertIn("Authentication required", c_fail["detail"])
        self.assertIsNone(doctor.fix_for(c_fail))

        b.record_one({
            "type": "run.completed",
            "id": "nightly",
            "by": "system",
            "data": {
                "ok": True,
                "steps": {"agente": "codex ok (fallback: claude — Authentication required)"},
            },
        })
        c_fb = next(c for c in doctor.checks(b) if c["title"] == "noturno")
        self.assertEqual(c_fb["level"], "warn")
        self.assertIn("fallback", c_fb["detail"])
        self.assertIsNone(doctor.fix_for(c_fb))

        c_never = {"level": "warn", "title": "noturno", "detail": "nunca rodou — `brain setup --only noturno`"}
        self.assertEqual(doctor.fix_for(c_never), {"label": "agendar o noturno", "sys": "sys:schedule"})

    def test_mcp_gap_check_and_claude_silence(self):
        b = _brain(self.tmp / "inst")
        watch.add(b.inst, "gmail-today", {"kind": "gmail", "window": "auto"})
        config.set_keys(b.inst, "runner", {"agent": "cursor"})
        b.inst = config.load(b.inst.root)

        with mock.patch.object(runner.shutil, "which", side_effect={"cursor-agent": "/bin/cursor-agent"}.get):
            checks = doctor.checks(b)
        r_checks = [c for c in checks if c["title"] == "runner"]
        self.assertEqual(len(r_checks), 1)
        self.assertEqual(r_checks[0]["level"], "warn")
        self.assertIn("cursor", r_checks[0]["detail"])

        config.set_keys(b.inst, "runner", {"agent": "claude"})
        b.inst = config.load(b.inst.root)
        with mock.patch.object(runner.shutil, "which", side_effect={"claude": "/bin/claude"}.get):
            checks_claude = doctor.checks(b)
        self.assertEqual([c for c in checks_claude if c["title"] == "runner"], [])

    def test_probe_responses(self):
        cfg = self._cfg(agent="claude")
        with mock.patch.object(runner.shutil, "which", side_effect={"claude": "/bin/claude"}.get):
            r_auth = runner.probe("claude", cfg,
                                  run=lambda a, **k: subprocess.CompletedProcess(a, 1, "Not logged in", ""))
            self.assertFalse(r_auth["ok"])
            self.assertTrue(r_auth["auth"])
            self.assertIn("Not logged in", r_auth["reason"])

            r_ok = runner.probe("claude", cfg,
                                run=lambda a, **k: subprocess.CompletedProcess(a, 0, "ok", ""))
            self.assertTrue(r_ok["ok"])
            self.assertFalse(r_ok["auth"])
            self.assertEqual(r_ok["reason"], "")

            def raise_to(a, **k):
                raise subprocess.TimeoutExpired(a, 60)

            r_to = runner.probe("claude", cfg, run=raise_to)
            self.assertFalse(r_to["ok"])
            self.assertFalse(r_to["auth"])
            self.assertIn("60", r_to["reason"])

    def test_setup_runner_options_noninteractive_and_auth_fail(self):
        b = _brain(self.tmp / "inst")
        with mock.patch.object(runner.shutil, "which", return_value="/bin/claude"), \
             mock.patch.object(runner, "probe") as m_probe:
            ui_non = StubUI(choice_ans="claude", interactive=False)
            setup._run_runner(b, ui_non)
            self.assertIn("gemini", ui_non.choices_seen[0])
            m_probe.assert_not_called()
            self.assertEqual(b.inst.cfg["runner"]["agent"], "claude")

        config.set_keys(b.inst, "runner", {"agent": "auto"})
        b.inst = config.load(b.inst.root)
        with mock.patch.object(runner.shutil, "which", return_value="/bin/codex"), \
             mock.patch.object(runner, "probe", return_value={"name": "codex", "ok": False, "auth": True, "reason": "Not logged in"}):
            ui_int = StubUI(choice_ans="codex", confirm_ans=False, interactive=True)
            setup._run_runner(b, ui_int)
            self.assertEqual(b.inst.cfg["runner"]["agent"], "auto")

    def test_doctor_default_never_calls_probe(self):
        b = _brain(self.tmp / "inst")
        with mock.patch.object(runner.shutil, "which", side_effect={"claude": "/bin/claude"}.get), \
             mock.patch.object(runner, "probe", side_effect=AssertionError("probe não deve rodar sem probe_agent")):
            doctor.checks(b)


if __name__ == "__main__":
    unittest.main()
