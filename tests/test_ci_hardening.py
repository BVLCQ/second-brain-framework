"""CI com `permissions` mínimo e actions fixadas por SHA (#113)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WorkflowHardeningTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_top_level_permissions_is_read_only(self):
        block = re.search(r"^permissions:\n((?:[ \t]+.*\n)+)", self.text, flags=re.M)
        self.assertIsNotNone(block, "o workflow não declara `permissions:` no topo")
        assert block
        perms = dict(re.findall(r"^[ \t]+(\w+):[ \t]*(\S+)[ \t]*$", block.group(1), flags=re.M))
        self.assertEqual(perms, {"contents": "read"})

    def test_every_action_is_pinned_to_a_sha(self):
        uses = re.findall(r"^[ \t]*-?[ \t]*uses:[ \t]*(\S+)", self.text, flags=re.M)
        self.assertTrue(uses, "nenhuma action encontrada no workflow")
        for used in uses:
            with self.subTest(uses=used):
                self.assertRegex(used, r"^[^@\s]+@[0-9a-f]{40}$", "action fixada em tag móvel — fixe pelo SHA da versão")

    def test_pull_request_trigger_is_not_a_target_fork_event(self):
        self.assertRegex(self.text, r"(?m)^  pull_request:\s*$")
        self.assertNotIn("pull_request_target", self.text)


if __name__ == "__main__":
    unittest.main()
