"""Sessão interativa do Claude Code pré-autorizada: o cérebro não pede licença para ls, cat, pastas ou MCP de leitura."""
import json
import tempfile
import unittest
from pathlib import Path

from brainlib import config, perms, runner

ROOT = Path(__file__).resolve().parent.parent


def _inst(tmp: str, toml: str = "") -> config.Instance:
    root = Path(tmp)
    (root / "config").mkdir()
    (root / "config" / "brain.toml").write_text(toml, encoding="utf-8")
    return config.load(root)


class StaticSettingsTest(unittest.TestCase):
    def test_committed_settings_match_the_module(self):
        committed = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, perms.static_settings())     # `python3 -c "…"` regenera: ver perms.static_settings()

    def test_every_headless_native_tool_is_allowed_interactively(self):
        committed = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertTrue(set(runner.CLAUDE_TOOLS) <= set(committed["permissions"]["allow"]))

    def test_bash_is_unrestricted_and_constitution_limits_are_denied(self):
        allow = perms.static_settings()["permissions"]["allow"]
        self.assertIn("Bash", allow)
        deny = perms.static_settings()["permissions"]["deny"]
        self.assertIn("Edit(/vault/PROCESSED/_ledger/**)", deny)
        self.assertIn("Bash(*--no-verify*)", deny)
        self.assertIn("Read(/config/.env)", deny)

    def test_local_settings_file_is_gitignored(self):
        self.assertIn(".claude/settings.local.json", (ROOT / ".gitignore").read_text(encoding="utf-8"))


class LocalSettingsTest(unittest.TestCase):
    def test_sync_writes_mcp_read_tools_and_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = _inst(tmp, '[runner]\nallow = ["mcp__x__ler"]\n')
            res = perms.sync(inst)
            self.assertTrue(res["changed"])
            data = json.loads(perms.local_path(inst).read_text(encoding="utf-8"))
            self.assertIn("mcp__x__ler", data["permissions"]["allow"])
            self.assertIn(str(Path(tmp).resolve()), data["permissions"]["additionalDirectories"])
            self.assertFalse(perms.sync(inst)["changed"])         # idempotente
            self.assertEqual(perms.status(inst)["local"], "ok")

    def test_external_write_tool_never_reaches_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = _inst(tmp, '[runner]\nallow = ["mcp__slack__slack_send_message", "mcp__x__ler"]\n')
            perms.sync(inst)
            allow = json.loads(perms.local_path(inst).read_text(encoding="utf-8"))["permissions"]["allow"]
            self.assertEqual(allow, ["mcp__x__ler"])

    def test_owner_edits_survive_and_removed_rules_leave(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = _inst(tmp, '[runner]\nallow = ["mcp__x__ler"]\n')
            perms.sync(inst)
            f = perms.local_path(inst)
            data = json.loads(f.read_text(encoding="utf-8"))
            data["permissions"]["allow"].append("Bash(echo dono)")
            data["model"] = "haiku"
            f.write_text(json.dumps(data), encoding="utf-8")
            (Path(tmp) / "config" / "brain.toml").write_text('[runner]\nallow = ["mcp__x__outra"]\n', encoding="utf-8")
            perms.sync(config.load(Path(tmp)))
            out = json.loads(f.read_text(encoding="utf-8"))
            self.assertEqual(out["model"], "haiku")
            self.assertIn("Bash(echo dono)", out["permissions"]["allow"])
            self.assertIn("mcp__x__outra", out["permissions"]["allow"])
            self.assertNotIn("mcp__x__ler", out["permissions"]["allow"])

    def test_absolute_denies_protect_the_real_env_and_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = _inst(tmp)
            perms.sync(inst)
            deny = json.loads(perms.local_path(inst).read_text(encoding="utf-8"))["permissions"]["deny"]
            root = Path(tmp).resolve()
            self.assertIn(f"Read(/{root}/config/.env)", deny)           # `//abs` = caminho absoluto no Claude Code
            self.assertIn(f"Edit(/{root}/vault/PROCESSED/_ledger/**)", deny)

    def test_worktrees_of_the_instance_get_their_own_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = _inst(tmp, '[runner]\nallow = ["mcp__x__ler"]\n')
            wt = Path(tmp) / ".claude" / "worktrees" / "feature"
            wt.mkdir(parents=True)
            res = perms.sync(inst)
            self.assertEqual(res["roots"], 2)
            data = json.loads((wt / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            self.assertIn("mcp__x__ler", data["permissions"]["allow"])
            self.assertIn(str(Path(tmp).resolve()), data["permissions"]["additionalDirectories"])

    def test_session_start_hook_regenerates_the_local_file(self):
        hook = perms.static_settings()["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn("brain agent permissions", hook)
        self.assertTrue(hook.rstrip().endswith("|| true"))             # nunca trava a abertura da sessão

    def test_status_flags_missing_and_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = _inst(tmp, '[runner]\nallow = ["mcp__x__ler"]\n')
            self.assertEqual(perms.status(inst)["local"], "missing")
            perms.sync(inst)
            (Path(tmp) / "config" / "brain.toml").write_text('[runner]\nallow = ["mcp__x__ler", "mcp__x__mais"]\n', encoding="utf-8")
            st = perms.status(config.load(Path(tmp)))
            self.assertEqual(st["local"], "stale")
            self.assertIn("mcp__x__mais", st["missing"])


if __name__ == "__main__":
    unittest.main()
