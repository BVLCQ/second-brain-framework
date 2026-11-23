"""Testes de hardening do runner/perms/bridge/allow-rules (#111, #144.3, #144.4, #144.6)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, perms, runner, util
from brainlib.tui import bridge


class RunnerSandboxSecurityTests(unittest.TestCase):
    def test_preset_argv_has_disallowed_tools_before_allowed_tools(self):
        cfg = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "agent": "claude", "allow": ["mcp__x__ler"]}}
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            argv = runner.preset_argv("claude", cfg, "/update")
            bridge_argv = bridge.agent_argv(cfg, "/update")
        for cmd in (argv, bridge_argv):
            self.assertIsNotNone(cmd)
            dis_idx = cmd.index("--disallowedTools")
            all_idx = cmd.index("--allowedTools")
            self.assertLess(dis_idx, all_idx)
            disallowed = cmd[dis_idx + 1:all_idx]
            for expected in (
                "Read(/config/.env)",
                "Read(**/config/.env)",
                "Read(~/.ssh/**)",
                "Read(~/.aws/**)",
                "Read(~/.config/gh/hosts.yml)",
                "Read(~/.netrc)",
                "Read(~/.gnupg/**)",
                "Bash(*cat *.env*)",
                "Bash(*cat ~/.ssh/*)",
            ):
                self.assertIn(expected, disallowed)
            self.assertFalse(any(".hermes" in x or ".claude" in x for x in disallowed))
            self.assertNotIn("Read(~/.config/**)", disallowed)

    def test_mcp_write_rules_stripped_in_runner_bridge_and_perms(self):
        cfg = {
            **config.DEFAULTS,
            "runner": {
                **config.DEFAULTS["runner"],
                "agent": "claude",
                "allow": [
                    "mcp__slack__list_messages",
                    "mcp__slack__slack_send_message",
                    "mcp__gmail__delete_message",
                    "mcp__gdrive__create_file",
                ],
            },
            "tui": {
                **config.DEFAULTS["tui"],
                "agent_allow": [
                    "mcp__slack__slack_send_message",
                    "mcp__gmail__delete_message",
                    "mcp__x__read_note",
                ],
            },
            "oppdrive": {
                "enabled": True,
                "root": "folder-123",
                "tools": ["mcp__gdrive__create_file"],
            },
        }
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            r_argv = runner.preset_argv("claude", cfg, "/update")
            b_argv = bridge.agent_argv(cfg, "/update", extra_allow=["mcp__gmail__send_message"])

        r_allowed = r_argv[r_argv.index("--allowedTools") + 1:]
        b_allowed = b_argv[b_argv.index("--allowedTools") + 1:]
        p_allowed = perms.mcp_rules(cfg)

        for allowed in (r_allowed, b_allowed, p_allowed):
            self.assertIn("mcp__slack__list_messages", allowed)
            self.assertIn("mcp__gdrive__create_file", allowed)
            self.assertNotIn("mcp__slack__slack_send_message", allowed)
            self.assertNotIn("mcp__gmail__delete_message", allowed)

        self.assertNotIn("mcp__gmail__send_message", b_allowed)
        self.assertIn("mcp__x__read_note", b_allowed)
        self.assertIn("mcp__x__read_note", p_allowed)
        self.assertNotIn("mcp__x__read_note", r_allowed)

        # Quando oppdrive está habilitada com `mcp__gdrive__create_file`, disallowedTools não deve bloqueá-la,
        # mas outras ferramentas de escrita continuam negadas.
        dis = runner.disallowed_tools(cfg)
        self.assertNotIn("mcp__gdrive__*create*", dis)
        self.assertIn("mcp__gdrive__*delete*", dis)
        self.assertIn("mcp__slack__*send*", dis)

        # Quando oppdrive está desligada, `mcp__gdrive__create_file` também é removida.
        cfg_off = {**cfg, "oppdrive": {**cfg["oppdrive"], "enabled": False}}
        self.assertNotIn("mcp__gdrive__create_file", runner.filtered_mcp_allow(cfg_off, include_tui=True))
        self.assertIn("mcp__gdrive__*create*", runner.disallowed_tools(cfg_off))

    def test_static_settings_in_sync_with_dot_claude_file(self):
        committed = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, perms.static_settings())
        deny = committed["permissions"]["deny"]
        for expected in (
            "Read(**/config/.env)",
            "Read(~/.ssh/**)",
            "Read(~/.aws/**)",
            "Read(~/.config/gh/hosts.yml)",
            "Read(~/.netrc)",
            "Read(~/.gnupg/**)",
            "Bash(*cat *.env*)",
            "Bash(*cat ~/.ssh/*)",
        ):
            self.assertIn(expected, deny)
        self.assertFalse(any(".hermes" in x or ".claude" in x for x in deny))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            (root / "config" / "brain.toml").write_text("", encoding="utf-8")
            inst = config.load(root)
            abs_d = perms.abs_denies(inst)
            home = Path.home().resolve()
            self.assertIn(f"Read(/{home / '.ssh'}/**)", abs_d)
            self.assertIn(f"Read(/{home / '.aws'}/**)", abs_d)
            self.assertIn(f"Read(/{home / '.config' / 'gh' / 'hosts.yml'})", abs_d)
            self.assertIn(f"Read(/{home / '.netrc'})", abs_d)
            self.assertIn(f"Read(/{home / '.gnupg'}/**)", abs_d)
            self.assertFalse(any(".hermes" in x or ".claude" in x for x in abs_d))

    def test_check_allow_rule_rejects_wildcard_bash(self):
        for bad in ("Bash(*:*)", "Bash(*)", "Bash(* *)", "Bash(**)", "Bash(sh*:*)", "Bash(git* *:*)", "Bash(:*)", "Bash(   )"):
            with self.assertRaises(util.BrainError, msg=bad) as cm:
                config.check_allow_rule(bad)
            self.assertEqual(cm.exception.code, 4)
        for ok in ("Bash(./brain:*)", "Bash(./brain add:*)", "Bash(git status:*)", "Bash(echo dono)"):
            self.assertEqual(config.check_allow_rule(ok), ok)


if __name__ == "__main__":
    unittest.main()
