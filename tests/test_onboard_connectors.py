"""Passo de conectores sem Claude Code e rascunho de planejamento agnóstico de agente (#8)."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, onboard, util              # noqa: E402
from brainlib.core import Brain                         # noqa: E402
from brainlib.tui import bridge                         # noqa: E402

TEMPLATE_PROFILE = "# PROFILE\n\n## Papel\n\n(a preencher no /init)\n"


def _inst(tmp: Path) -> config.Instance:
    for d in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH",
              "vault/reports"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dono do cérebro"\n\n[work]\nstart = "09:00"\nend = "18:00"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    (tmp / "vault" / "PROFILE" / "profile.md").write_text(TEMPLATE_PROFILE, encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    return Brain(_inst(tmp))


def _wait_job(job_id: str) -> dict:
    for _ in range(200):
        j = onboard.job(job_id)
        if j and j["status"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} não terminou a tempo")


class OnboardConnectorsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.b = _brain(self.tmp)

    def tearDown(self):
        onboard._MCP_CACHE.update(at=0.0, servers=None, source=None, hint="", job=None)
        self._td.cleanup()

    def test_scan_connectors_without_claude_with_hermes_finishes_ok(self):
        which_map = {"claude": None, "hermes": "/usr/local/bin/hermes"}
        with mock.patch("shutil.which", side_effect=lambda k: which_map.get(k)), \
                mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            r = onboard.scan_connectors(force=True)
            j = _wait_job(r["job"])
        self.assertEqual(j["status"], "done", j["log"])
        self.assertEqual(j["result"]["source"], "none")
        self.assertEqual(j["result"]["servers"], {})
        self.assertIn("Hermes", j["result"]["hint"])
        self.assertIn("brain watch add", j["result"]["hint"])

    def test_scan_connectors_without_claude_and_without_hermes_gives_generic_hint(self):
        with mock.patch("shutil.which", return_value=None), \
                mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            r = onboard.scan_connectors(force=True)
            j = _wait_job(r["job"])
        self.assertEqual(j["status"], "done", j["log"])
        self.assertEqual(j["result"]["source"], "none")
        self.assertEqual(j["result"]["servers"], {})
        self.assertNotIn("Hermes", j["result"]["hint"])
        self.assertIn("Conectores do Claude Code não encontrados nesta máquina", j["result"]["hint"])
        self.assertIn("brain watch add", j["result"]["hint"])

    def test_planning_draft_uses_configured_runner_and_mentions_no_claude_code_on_error(self):
        onboard.save_planning_note(self.b, {"text": "Abrir a 2ª loja da Padaria Pão Quente até março de 2027."})

        async def fake_run_agent(inst, argv, on_line, info):
            self.assertEqual(argv[0], "cursor-agent")
            info.result = '```json\n{"goals": [{"title": "Abrir a 2ª loja", "projects": []}], "summary": "Você quer crescer."}\n```'
            return 0

        with mock.patch("shutil.which", side_effect=lambda k: "/usr/local/bin/cursor-agent" if k == "cursor-agent" else None), \
                mock.patch.object(bridge, "run_agent", side_effect=fake_run_agent), \
                mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            r = onboard.draft_planning(self.b)
            j = _wait_job(r["job"])
        self.assertEqual(j["status"], "done", j["log"])
        self.assertEqual(r.get("agent"), "cursor")
        self.assertEqual(j["result"]["proposal"]["goals"][0]["title"], "Abrir a 2ª loja")

        with mock.patch("shutil.which", return_value=None), \
                mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            with self.assertRaises(util.BrainError) as ctx:
                onboard.draft_planning(self.b)
        self.assertNotIn("Claude Code", str(ctx.exception))
        self.assertIn("nenhum agente headless encontrado (procurei: cursor-agent, claude, codex, agy, gemini)",
                      str(ctx.exception))

    def test_assets_show_hint_when_source_is_none(self):
        for rel in ("brainlib/assets/onboarding.html", "brainlib/assets/dashboard.html"):
            html = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn('src === "none"', html)
            self.assertIn("connectors_hint", html)


if __name__ == "__main__":
    unittest.main()
