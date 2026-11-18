"""Canal MCP somente-leitura do cérebro nos agentes (`brain harness`) — stdlib unittest, sem rede."""
from __future__ import annotations

import contextlib
import io
import json
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

from brainlib import cli, config, harness, perms                                    # noqa: E402
from brainlib.core import Brain                                                     # noqa: E402


def _brain(tmp: Path) -> Brain:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n", encoding="utf-8")
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class _OkRun:
    """subprocess.run falso: registra argv e sempre sai 0."""

    def __init__(self, rc: int = 0, stdout: str = "", stderr: str = "", side_effect=None):
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.side_effect = side_effect
        self.argvs: list[list[str]] = []

    def __call__(self, cmd, **kw):
        argv = list(cmd)
        self.argvs.append(argv)
        if self.side_effect:
            res = self.side_effect(argv, **kw)
            if res is not None:
                return res
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


class DetectTests(unittest.TestCase):
    def test_detect_via_home_dirs(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td, "PATH": ""}):
            home = Path(td)
            (home / ".claude").mkdir()
            (home / ".cursor").mkdir()
            with mock.patch.object(harness.shutil, "which", return_value=None):
                det = harness.detect(home)
            self.assertTrue(det["claude-code"])
            self.assertTrue(det["cursor-cli"])
            self.assertFalse(det["codex"])
            self.assertFalse(det["hermes"])


class ConnectDisconnectTests(unittest.TestCase):
    def test_connect_claude_code_wires_mcp_and_sets_recall_hook_true(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td, "PATH": ""}):
            home = Path(td)
            b = _brain(home / "inst")
            run = _OkRun()
            with mock.patch.object(harness.shutil, "which", side_effect=lambda x: f"/usr/bin/{x}"):
                res = harness.connect(b, ["claude-code"], home=home, run=run)
            self.assertEqual(res[0]["agent"], "claude-code")
            self.assertTrue(res[0]["mcp"]["ok"])
            self.assertIs(b.inst.cfg["memory"]["recall_hook"], True)
            self.assertTrue(harness._claude_hook_present(b.inst))
            expected_mcp = [
                "claude", "mcp", "add", "--scope", "user", "brain",
                "--env", f"BRAIN_HOME={b.inst.root}",
                "--", str(harness.FRAMEWORK / "brain"), "mcp",
            ]
            self.assertEqual(run.argvs, [expected_mcp])
            self.assertFalse((home / ".hindsight" / "coding-agent.json").exists())

            # Disconnect desliga recall_hook = false e remove MCP
            run_rm = _OkRun()
            with mock.patch.object(harness.shutil, "which", side_effect=lambda x: f"/usr/bin/{x}"):
                rm_res = harness.disconnect(b, ["claude-code"], home=home, run=run_rm)
            self.assertTrue(rm_res[0]["mcp"]["ok"])
            self.assertIs(b.inst.cfg["memory"]["recall_hook"], False)
            self.assertFalse(harness._claude_hook_present(b.inst))
            self.assertEqual(run_rm.argvs, [["claude", "mcp", "remove", "--scope", "user", "brain"]])

    def test_connect_hermes_wires_only_mcp_and_never_touches_hermes_memory(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td, "PATH": ""}):
            home = Path(td)
            b = _brain(home / "inst")
            y = harness.hermes_yaml(home)
            y.parent.mkdir(parents=True, exist_ok=True)
            spec_cmd = str(harness.FRAMEWORK / "brain")

            def _save_yaml(argv, **_kw):
                if argv[:3] == ["hermes", "mcp", "add"]:
                    y.write_text(
                        f"mcp_servers:\n  brain:\n    command: {spec_cmd}\n    args:\n      - mcp\n    enabled: true\n",
                        encoding="utf-8",
                    )
                return None

            run = _OkRun(side_effect=_save_yaml)
            with mock.patch.object(harness.shutil, "which", return_value="/usr/local/bin/hermes"):
                res = harness.connect(b, ["hermes"], home=home, run=run)
            self.assertTrue(res[0]["mcp"]["ok"])
            self.assertFalse((home / ".hermes" / "hindsight" / "config.json").exists())
            self.assertFalse(any("memory.provider" in a for argv in run.argvs for a in argv))

    def test_connect_default_uses_detected_agents(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td, "PATH": ""}):
            home = Path(td)
            (home / ".cursor").mkdir()
            (home / ".codex").mkdir()
            b = _brain(home / "inst")
            with mock.patch.object(harness.shutil, "which", return_value=None):
                res = harness.connect(b, None, home=home, run=_OkRun())
            self.assertEqual([r["agent"] for r in res], ["cursor-cli", "codex"])
            self.assertTrue(all(r["mcp"]["ok"] for r in res))

    def test_format_connect_lines_pt_br(self):
        lines = harness.format_connect_lines([
            {"agent": "cursor-cli", "mcp": {"ok": True, "how": "file", "hint": ""}},
            {"agent": "hermes", "mcp": {"ok": False, "how": "manual", "hint": "CLI do Hermes ausente"}},
        ])
        self.assertTrue(any("✓ cursor-cli" in ln and "MCP" in ln for ln in lines))
        self.assertTrue(any("⚠ hermes" in ln and "CLI do Hermes ausente" in ln for ln in lines))


class StatusTests(unittest.TestCase):
    def test_status_reports_detected_and_mcp_per_agent(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td, "PATH": ""}):
            home = Path(td)
            (home / ".cursor").mkdir()
            b = _brain(home / "inst")
            harness.wire_mcp(b.inst, "cursor-cli", home=home)
            with mock.patch.object(harness.shutil, "which", return_value=None):
                st = harness.status(b, home=home)
            self.assertEqual(set(st.keys()), {"claude-code", "cursor-cli", "codex", "hermes"})
            self.assertEqual(st["cursor-cli"], {"detected": True, "mcp": True})
            self.assertEqual(st["claude-code"], {"detected": False, "mcp": False})
            self.assertEqual(st["codex"], {"detected": False, "mcp": False})
            self.assertEqual(st["hermes"], {"detected": False, "mcp": False})


class HarnessCliTests(unittest.TestCase):
    def test_cli_status_human_and_json(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td, "PATH": ""}):
            home = Path(td)
            (home / ".codex").mkdir()
            b = _brain(home / "inst")
            harness.wire_mcp(b.inst, "codex", home=home)
            p = cli.build_parser()

            buf = io.StringIO()
            with mock.patch.object(harness.shutil, "which", return_value=None), \
                 contextlib.redirect_stdout(buf):
                cli.cmd_harness(p.parse_args(["harness", "status"]), b)
            self.assertIn("✓ codex: detectado · MCP registrado", buf.getvalue())

            buf_json = io.StringIO()
            with mock.patch.object(harness.shutil, "which", return_value=None), \
                 contextlib.redirect_stdout(buf_json):
                cli.cmd_harness(p.parse_args(["harness", "status", "--json"]), b)
            data = json.loads(buf_json.getvalue())
            self.assertEqual(data["codex"], {"detected": True, "mcp": True})

    def test_cli_connect_and_disconnect(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td, "PATH": ""}):
            home = Path(td)
            b = _brain(home / "inst")
            p = cli.build_parser()

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cli.cmd_harness(p.parse_args(["harness", "connect", "cursor-cli"]), b)
            self.assertIn("✓ cursor-cli", buf.getvalue())
            self.assertTrue(harness.mcp_present(b.inst, "cursor-cli", home=home))

            buf_rm = io.StringIO()
            with contextlib.redirect_stdout(buf_rm):
                cli.cmd_harness(p.parse_args(["harness", "disconnect", "cursor-cli"]), b)
            self.assertIn("✓ cursor-cli", buf_rm.getvalue())
            self.assertFalse(harness.mcp_present(b.inst, "cursor-cli", home=home))


if __name__ == "__main__":
    unittest.main()
