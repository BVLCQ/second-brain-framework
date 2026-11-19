"""Contrato do wizard como modo primeira vez do painel (F8 — guides/plans/onboarding-unification.md):
mesmo HTML do painel, transição sem recarregar, rota antiga virando atalho."""
from __future__ import annotations

import http.client
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, onboard, serve, setup                       # noqa: E402
from brainlib.core import Brain                                          # noqa: E402
from brainlib import render                                              # noqa: E402

EXTRA = ROOT / "brainlib" / "assets" / "src" / "extra.js"
CORE = ROOT / "brainlib" / "assets" / "src" / "core.js"
OB_HTML = ROOT / "brainlib" / "assets" / "onboarding.html"
BUILT = ROOT / "brainlib" / "assets" / "dashboard.html"


def _steps_literal(text: str, decl: str) -> list[tuple[str, str]]:
    m = re.search(re.escape(decl) + r"\s*=\s*\[(.*?)\];", text, re.S)
    if not m:
        raise AssertionError(f"literal não encontrado: {decl}")
    return re.findall(r'\["([^"]+)",\s*"([^"]+)"\]', m.group(1))


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    for zone in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH", "reports"):
        (tmp / "vault" / zone).mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "none"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(tmp)


class WizardPanelParityTests(unittest.TestCase):
    """Os TRÊS registros de passos falam a mesma língua: painel · página própria · setup.WEB_STEPS."""

    def test_steps_iguais_no_painel_na_pagina_e_no_registro(self):
        extra = _steps_literal(EXTRA.read_text(encoding="utf-8"), "const OB_STEPS")
        page = _steps_literal(OB_HTML.read_text(encoding="utf-8"), "const STEPS")
        self.assertEqual(extra, page)
        self.assertEqual([s[0] for s in extra], [s[0] for s in setup.WEB_STEPS])

    def test_painel_construido_carrega_o_wizard(self):
        html = BUILT.read_text(encoding="utf-8")
        for needle in ("enterOnboarding", "exitOnboarding", "obmode", "ob-steps", "obw"):
            self.assertIn(needle, html)

    def test_core_roteia_o_modo_e_da_default_ao_flag(self):
        core = CORE.read_text(encoding="utf-8")
        self.assertIn("m.onboarding = m.onboarding || {needed: false}", core)
        self.assertIn('path === "onboarding"', core)

    def test_hub_reconfigura_sem_recarregar(self):
        extra = EXTRA.read_text(encoding="utf-8")
        self.assertNotIn('location.href = "/onboarding"', extra)
        self.assertIn('location.hash = "onboarding"', extra)


class ViewModelFlagTests(unittest.TestCase):
    """O view model carrega `onboarding.needed`; o finish apaga."""

    def test_needed_no_model_e_apos_finish(self):
        with tempfile.TemporaryDirectory() as td:
            b = Brain(_inst(Path(td)))
            self.assertTrue(render.view_model(b)["onboarding"]["needed"])
            onboard.finish(b)
            self.assertFalse(render.view_model(b)["onboarding"]["needed"])


class OnboardingRedirectTests(unittest.TestCase):
    """A rota /onboarding antiga vira 302 para o modo primeira vez do próprio painel."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.inst = _inst(Path(cls.td.name) / "inst")
        serve._Handler.state = serve._State(cls.inst, "tok-f8")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        serve._Handler.state.port = cls.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.td.cleanup()

    def test_onboarding_redireciona_para_o_painel(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/onboarding", headers={"Host": f"127.0.0.1:{self.port}"})
        resp = conn.getresponse()
        resp.read()
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "/#onboarding")
        conn.close()


if __name__ == "__main__":
    unittest.main()
