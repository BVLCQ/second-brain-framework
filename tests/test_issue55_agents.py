"""Issue #55: exibe sempre os 4 agentes, conecta sem gate de detecção e adiciona 'Outros harnesses'."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, harness, onboard, setup, util  # noqa: E402
from brainlib.core import Brain                            # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    for rel in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH"):
        (tmp / rel).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Marina Demo"\n\n[memory]\nengine = "none"\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _wait_job(jid: str, timeout: float = 5.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = onboard.job(jid)
        if j["status"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError(f"job {jid} não terminou em {timeout}s")


class Issue55AgentsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self._old = {k: os.environ.get(k) for k in ("HOME", "PATH", "BRAIN_NIGHTLY")}
        os.environ["HOME"] = str(self.tmp)
        os.environ["PATH"] = ""
        os.environ.pop("BRAIN_NIGHTLY", None)
        self.b = Brain(_inst(self.tmp))

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._td.cleanup()

    def test_mcp_snippets_returns_valid_json_toml_and_cli(self):
        sn = harness.mcp_snippets(self.b.inst)
        spec = harness.mcp_spec(self.b.inst)
        self.assertEqual(sn["command"], spec["command"])
        self.assertEqual(sn["brain_home"], spec["env"]["BRAIN_HOME"])
        parsed_json = json.loads(sn["json"])
        self.assertEqual(parsed_json, {"mcpServers": {harness.MCP_NAME: spec}})
        parsed_toml = tomllib.loads(sn["toml"])
        srv = parsed_toml["mcp_servers"][harness.MCP_NAME]
        self.assertEqual(srv["command"], spec["command"])
        self.assertEqual(srv["args"], spec["args"])
        self.assertEqual(srv["env"]["BRAIN_HOME"], spec["env"]["BRAIN_HOME"])
        self.assertEqual(sn["cli"], f"BRAIN_HOME={spec['env']['BRAIN_HOME']} {spec['command']} mcp")

    def test_agents_state_lists_all_four_and_checks_mcp_without_detection(self):
        with mock.patch.object(harness.shutil, "which", return_value=None):
            ags = onboard.agents_state(self.b)
            self.assertEqual([a["key"] for a in ags], list(harness._DETECT))
            self.assertTrue(all(not a["detected"] and not a["mcp"] for a in ags))

            # Config MCP manual no ~/.claude.json sem pasta ~/.claude (não detectado, mas mcp=True)
            (self.tmp / ".claude.json").write_text(
                json.dumps({"mcpServers": {harness.MCP_NAME: harness.mcp_spec(self.b.inst)}}),
                encoding="utf-8",
            )
            st = onboard.state(self.b)
            claude = next(a for a in st["agents"] if a["key"] == "claude-code")
            self.assertFalse(claude["detected"])
            self.assertTrue(claude["mcp"])
            self.assertIs(st["setup"]["agente"], True)

    def test_connect_claude_and_codex_work_without_detection(self):
        with mock.patch.object(harness.shutil, "which", return_value=None):
            r_claude = onboard.connect_agent(self.b, {"agent": "claude-code"})
            j_claude = _wait_job(r_claude["job"])
            self.assertEqual(j_claude["status"], "done", j_claude["log"])
            self.assertFalse(j_claude["result"]["mcp"])
            self.assertEqual(j_claude["result"]["how"], "manual")
            self.assertIn("claude mcp add", j_claude["result"]["hint"])
            self.assertTrue((self.tmp / ".claude" / "settings.local.json").exists())

            r_codex = onboard.connect_agent(self.b, {"agent": "codex"})
            j_codex = _wait_job(r_codex["job"])
            self.assertEqual(j_codex["status"], "done", j_codex["log"])
            self.assertTrue(j_codex["result"]["mcp"], j_codex["log"])
            self.assertEqual(j_codex["result"]["how"], "file")
            self.assertEqual(j_codex["result"]["hint"], "")
            cfg = tomllib.loads((self.tmp / "config" / "brain.toml").read_text(encoding="utf-8"))
            self.assertEqual(cfg["runner"]["agent"], "codex")
            codex_toml = tomllib.loads((self.tmp / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(codex_toml["mcp_servers"][harness.MCP_NAME]["command"], str(harness.FRAMEWORK / "brain"))

    def test_other_harness_marks_manual_in_setup_without_new_step(self):
        web_ids = [s[0] for s in setup.WEB_STEPS]
        self.assertNotIn("other", web_ids)
        self.assertEqual(onboard.STEPS, tuple(web_ids))

        res = onboard.connect_agent(self.b, {"agent": "other"})
        self.assertEqual(res, {"mode": "manual"})

        st = onboard.state(self.b)
        self.assertEqual(st["agent_mode"], "manual")
        self.assertEqual(st["setup"]["agente"], "manual")
        self.assertIn("agente", st["progress"].get("done", []))
        self.assertIn("json", st["mcp_snippets"])
        self.assertIn("toml", st["mcp_snippets"])
        self.assertIn("cli", st["mcp_snippets"])

        # Conectar um agente com sucesso limpa agent_mode="manual" e promove setup["agente"] para True
        r_cur = onboard.connect_agent(self.b, {"agent": "cursor-cli"})
        j_cur = _wait_job(r_cur["job"])
        self.assertEqual(j_cur["status"], "done", j_cur["log"])
        self.assertTrue(j_cur["result"]["mcp"])
        st2 = onboard.state(self.b)
        self.assertEqual(st2["agent_mode"], "")
        self.assertIs(st2["setup"]["agente"], True)

    def test_other_harness_refused_in_nightly(self):
        os.environ["BRAIN_NIGHTLY"] = "1"
        with self.assertRaises(util.BrainError):
            onboard.connect_agent(self.b, {"agent": "other"})

    def test_onboarding_html_and_extra_js_render_all_agents_and_other_card(self):
        ob_html = (ROOT / "brainlib" / "assets" / "onboarding.html").read_text(encoding="utf-8")
        self.assertIn('data-ag="other"', ob_html)
        self.assertIn("Outros harnesses", ob_html)
        self.assertIn("S.mcp_snippets", ob_html)
        self.assertIn("detectado", ob_html)
        self.assertIn("não detectado", ob_html)
        self.assertIn("Marcar como configurado manualmente", ob_html)
        self.assertIn("ag-hint", ob_html)
        self.assertNotIn("Nenhum agente foi encontrado nesta máquina", ob_html)
        self.assertNotIn("agentcard dim", ob_html)

        extra = (ROOT / "brainlib" / "assets" / "src" / "extra.js").read_text(encoding="utf-8")
        self.assertIn('const SETUP_STEPS = [["perfil", "Perfil"], ["rotina", "Rotina"], ["agente", "Seu agente"], '
                      '["conectores", "Conectores"], ["memoria", "Memória"], ["integracoes", "Integrações"]];', extra)
        self.assertIn('ok === "manual" ? \'<span class="chip h-info">manual</span>\'', extra)
        self.assertIn('Outro harness (MCP manual)', extra)
        self.assertIn('data-ag="other"', extra)
        self.assertIn("Outros harnesses", extra)
        self.assertIn("SS.mcp_snippets", extra)
        self.assertIn('obAct("agent_connect", {agent: "other"})', extra)
        self.assertIn("detectado", extra)
        self.assertIn("não detectado", extra)
        self.assertNotIn("const detected = (SS.agents || []).filter(a => a.detected);", extra)


if __name__ == "__main__":
    unittest.main()
