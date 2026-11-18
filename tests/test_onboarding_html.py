"""Contrato do wizard HTML (`brainlib/assets/onboarding.html`) com o registro de passos e o tema."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import setup  # noqa: E402

HTML_PATH = ROOT / "brainlib" / "assets" / "onboarding.html"


class OnboardingHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_steps_ids_match_setup_web_steps(self):
        m = re.search(r"const\s+STEPS\s*=\s*(\[\[.*?\]\])\s*;", self.html, re.S)
        self.assertIsNotNone(m, "const STEPS = [[...]] não encontrado no onboarding.html")
        steps = json.loads(m.group(1))
        html_ids = [item[0] for item in steps]
        web_ids = [s[0] for s in setup.WEB_STEPS]
        self.assertEqual(html_ids, web_ids)

    def test_required_action_literals_present(self):
        for lit in ("agent_connect", "agent_later", "source_add", "source_remove", "maquina"):
            self.assertIn(lit, self.html)

    def test_old_navy_theme_removed_and_dark_theme_present(self):
        self.assertNotIn("#060a1f", self.html.lower())
        self.assertIn("data-theme=dark", self.html)


if __name__ == "__main__":
    unittest.main()
