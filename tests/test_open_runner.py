"""Testes da Issue #101: agente headless (noturno e ⚡) sem Bash irrestrito nem bypass total."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, perms, runner  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.tui import bridge  # noqa: E402


def _make_inst(tmp: Path, runner_toml: str = "") -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Marina-demo"\n' + runner_toml,
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Entregável · prazo: 2026-11-01\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _make_brain(tmp: Path, runner_toml: str = "") -> Brain:
    b = Brain(_make_inst(tmp, runner_toml))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Eu"], "relation": "dono"}})
    return b


class _FakeAsyncProc:
    """Subprocesso assíncrono falso para testar bridge.run_agent sem disparar binário real."""

    def __init__(self, lines: list[bytes] | None = None, rc: int = 0):
        self.stdout = self._iter(lines or [])
        self._rc = rc
        self.returncode: int | None = None

    @staticmethod
    async def _iter(items: list[bytes]):
        for it in items:
            yield it

    async def wait(self) -> int:
        self.returncode = self._rc
        return self._rc

    def kill(self) -> None:
        self.returncode = -9


class OpenRunnerTests(unittest.TestCase):
    def _cfg(self, **over) -> dict:
        r_over = over.pop("runner", {})
        t_over = over.pop("tui", {})
        return {
            **config.DEFAULTS,
            **over,
            "runner": {**config.DEFAULTS["runner"], **r_over},
            "tui": {**config.DEFAULTS["tui"], **t_over},
        }

    def test_constants_split_interactive_and_headless(self):
        self.assertEqual(
            runner.HEADLESS_TOOLS,
            ["Read", "Grep", "Glob", "Bash(./brain *)", "Bash(./brain)"],
        )
        self.assertNotIn("Bash", runner.HEADLESS_TOOLS)
        for forbidden in ("Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task"):
            self.assertNotIn(forbidden, runner.HEADLESS_TOOLS)

        # Sessão interativa do dono permanece intacta
        self.assertIn("Bash", runner.CLAUDE_TOOLS)
        self.assertIn("Bash", perms.static_settings()["permissions"]["allow"])

    def test_nightly_claude_argv_restricted_and_env_denies(self):
        cfg = self._cfg(runner={"agent": "claude", "allow": ["mcp__x__ler"]})
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            argv = runner.preset_argv("claude", cfg, "/update", night=True)
            cmd = runner.agent_command(cfg)

        for built in (argv, cmd):
            self.assertIsNotNone(built)
            self.assertNotIn("Bash", built)
            dis_idx = built.index("--disallowedTools")
            all_idx = built.index("--allowedTools")
            self.assertLess(dis_idx, all_idx)

            disallowed = built[dis_idx + 1:all_idx]
            allowed = built[all_idx + 1:]

            for expected in ("Read", "Grep", "Glob", "Bash(./brain *)", "Bash(./brain)", "mcp__x__ler"):
                self.assertIn(expected, allowed)
            for forbidden in ("Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task"):
                self.assertNotIn(forbidden, allowed)
            for env_deny in ("Bash(env *)", "Bash(*env -u*)", "Bash(printenv*)"):
                self.assertIn(env_deny, disallowed)
            self.assertIn("mcp__slack__*send*", disallowed)
            self.assertIn("Read(/config/.env)", disallowed)

    def test_bridge_claude_argv_and_resume_use_headless_tools_and_env_denies(self):
        cfg = self._cfg(
            runner={"agent": "claude", "allow": ["mcp__x__ler"]},
            tui={"agent_allow": ["mcp__x__nota"]},
        )
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            argv = bridge.agent_argv(cfg, "/dump", run_id="run-1")
            resumed = bridge.resume_argv(cfg, "sess-42", "segue", run_id="run-2")

        for built in (argv, resumed):
            self.assertIsNotNone(built)
            self.assertNotIn("Bash", built)
            dis_idx = built.index("--disallowedTools")
            all_idx = built.index("--allowedTools")
            self.assertLess(dis_idx, all_idx)
            disallowed = built[dis_idx + 1:all_idx]
            allowed = built[all_idx + 1:]

            for expected in ("Read", "Grep", "Glob", "Bash(./brain *)", "Bash(./brain)", "mcp__x__ler", "mcp__x__nota"):
                self.assertIn(expected, allowed)
            for forbidden in ("Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task"):
                self.assertNotIn(forbidden, allowed)
            for env_deny in ("Bash(env *)", "Bash(*env -u*)", "Bash(printenv*)"):
                self.assertIn(env_deny, disallowed)
            self.assertIn("mcp__gmail__*send*", disallowed)

    def test_nightly_drops_bypass_flags_for_all_non_claude_presets(self):
        cfg = self._cfg()
        cases = [
            ("agy", "--dangerously-skip-permissions"),
            ("cursor", "--force"),
            ("codex", "--full-auto"),
            ("gemini", "--yolo"),
        ]
        with mock.patch("shutil.which", return_value="/usr/bin/fake"):
            for preset_name, bypass_flag in cases:
                night_argv = runner.preset_argv(preset_name, cfg, "/update", night=True)
                self.assertIsNotNone(night_argv, preset_name)
                self.assertNotIn(bypass_flag, night_argv, preset_name)
                # Ações ⚡ (owner clicked) preservam as flags dos presets não-claude
                tui_argv = bridge.agent_argv(self._cfg(runner={"agent": preset_name}), "/dump")
                self.assertIsNotNone(tui_argv, preset_name)
                self.assertIn(bypass_flag, tui_argv, preset_name)

    def test_nightly_skips_non_claude_presets_and_records_step_failure(self):
        for preset_name, bin_name in (
            ("agy", "agy"),
            ("cursor", "cursor-agent"),
            ("codex", "codex"),
            ("gemini", "gemini"),
        ):
            with self.subTest(preset=preset_name), tempfile.TemporaryDirectory() as td:
                b = _make_brain(Path(td), f'\n[runner]\nagent = "{preset_name}"\nfallback = false\n')
                called: list[list[str]] = []

                def fake_run(cmd, **kw):
                    called.append(list(cmd))
                    return subprocess.CompletedProcess(cmd, 0)

                with mock.patch.object(runner.shutil, "which", side_effect=lambda x: f"/bin/{x}" if x == bin_name else None):
                    res = runner.nightly(b, run=fake_run)

                self.assertEqual(called, [], f"{preset_name} não pode subir no noturno")
                self.assertFalse(res["ok"])
                self.assertIn(
                    f"preset {preset_name} não tem modo restrito — noturno não sobe com bypass",
                    res["steps"]["agente"],
                )

    def test_run_agent_nightly_and_probe_pass_brain_agent_env_to_injectable_run(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td), '\n[runner]\nagent = "claude"\n')
            seen: list[dict] = []

            def fake_run(cmd, **kw):
                seen.append({"cmd": list(cmd), "env": dict(kw["env"])})
                return subprocess.CompletedProcess(cmd, 0, "ok", "")

            with mock.patch.object(runner.shutil, "which", side_effect={"claude": "/bin/claude"}.get):
                out = runner.run_agent(b, run=fake_run)
                pr = runner.probe("claude", b.inst.cfg, cwd=b.inst.root, run=fake_run)

            self.assertEqual(out, "claude ok")
            self.assertTrue(pr["ok"])
            self.assertEqual(len(seen), 2)
            for call in seen:
                self.assertEqual(call["env"].get("BRAIN_AGENT"), "1")
                self.assertEqual(call["env"].get("BRAIN_NIGHTLY"), "1")
                self.assertNotIn("Bash", call["cmd"])
                self.assertIn("Bash(./brain *)", call["cmd"])

    def test_bridge_run_agent_sets_brain_agent_env_for_claude_and_non_claude(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _make_inst(Path(td), '\n[runner]\nagent = "agy"\n')
            # _env (usado por run_brain em cliques diretos do dono no TUI) NÃO injeta BRAIN_AGENT
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("BRAIN_AGENT", None)
                self.assertNotIn("BRAIN_AGENT", bridge._env(inst))

            captured: list[dict] = []

            async def fake_spawn(*argv, **kw):
                captured.append({"argv": list(argv), "env": dict(kw["env"])})
                return _FakeAsyncProc([b"ok\n"], rc=0)

            with mock.patch("shutil.which", return_value="/bin/agy"):
                agy_argv = bridge.agent_argv(inst.cfg, "/dump")
            self.assertIsNotNone(agy_argv)
            self.assertIn("--dangerously-skip-permissions", agy_argv)

            lines: list[str] = []
            rc = asyncio.run(bridge.run_agent(inst, agy_argv, lines.append, run=fake_spawn))
            self.assertEqual(rc, 0)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0]["env"].get("BRAIN_AGENT"), "1")
            self.assertNotIn("BRAIN_NIGHTLY", captured[0]["env"])

            # Também para claude ⚡
            inst_claude = _make_inst(Path(td) / "claude", '\n[runner]\nagent = "claude"\n')
            with mock.patch("shutil.which", return_value="/bin/claude"):
                claude_argv = bridge.agent_argv(inst_claude.cfg, "/dump")
            self.assertIsNotNone(claude_argv)
            self.assertNotIn("Bash", claude_argv)
            rc2 = asyncio.run(bridge.run_agent(inst_claude, claude_argv, lines.append, run=fake_spawn))
            self.assertEqual(rc2, 0)
            self.assertEqual(len(captured), 2)
            self.assertEqual(captured[1]["env"].get("BRAIN_AGENT"), "1")
            self.assertNotIn("BRAIN_NIGHTLY", captured[1]["env"])

    def test_nightly_auto_skips_cursor_bypass_and_runs_claude_with_env(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td), '\n[runner]\nagent = "auto"\n')
            seen: list[dict] = []

            def fake_run(cmd, **kw):
                seen.append({"cmd": list(cmd), "env": dict(kw["env"])})
                return subprocess.CompletedProcess(cmd, 0, "ok", "")

            bins = {"cursor-agent": "/bin/cursor-agent", "claude": "/bin/claude"}
            with mock.patch.object(runner.shutil, "which", side_effect=bins.get):
                res = runner.nightly(b, run=fake_run)

            self.assertTrue(res["ok"])
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]["cmd"][0], "claude")
            self.assertNotIn("Bash", seen[0]["cmd"])
            self.assertEqual(seen[0]["env"].get("BRAIN_AGENT"), "1")
            self.assertEqual(seen[0]["env"].get("BRAIN_NIGHTLY"), "1")
            self.assertIn("preset cursor não tem modo restrito — noturno não sobe com bypass", res["steps"]["agente"])

    def test_write_mcp_in_runner_allow_dropped_unless_oppdrive_door_on_both_consumers(self):
        base_allow = [
            "mcp__slack__list_messages",
            "mcp__slack__slack_send_message",
            "mcp__gdrive__create_file",
            "mcp__gdrive__delete_file",
        ]
        cfg_off = self._cfg(
            runner={"agent": "claude", "allow": base_allow},
            oppdrive={"enabled": False, "root": "folder-1", "tools": ["mcp__gdrive__create_file"]},
        )
        cfg_on = self._cfg(
            runner={"agent": "claude", "allow": base_allow},
            oppdrive={"enabled": True, "root": "folder-1", "tools": ["mcp__gdrive__create_file"]},
        )

        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            night_off = runner.preset_argv("claude", cfg_off, "/update", night=True)
            tui_off = bridge.agent_argv(cfg_off, "/update")
            night_on = runner.preset_argv("claude", cfg_on, "/update", night=True)
            tui_on = bridge.agent_argv(cfg_on, "/update")

        for argv in (night_off, tui_off):
            allowed = argv[argv.index("--allowedTools") + 1:]
            self.assertIn("mcp__slack__list_messages", allowed)
            self.assertNotIn("mcp__slack__slack_send_message", allowed)
            self.assertNotIn("mcp__gdrive__create_file", allowed)
            self.assertNotIn("mcp__gdrive__delete_file", allowed)

        for argv in (night_on, tui_on):
            allowed = argv[argv.index("--allowedTools") + 1:]
            self.assertIn("mcp__slack__list_messages", allowed)
            self.assertIn("mcp__gdrive__create_file", allowed)
            self.assertNotIn("mcp__slack__slack_send_message", allowed)
            self.assertNotIn("mcp__gdrive__delete_file", allowed)


if __name__ == "__main__":
    unittest.main()
