"""Contrato do wizard como modo primeira vez do painel (F8 — guides/plans/onboarding-unification.md):
mesmo HTML do painel, transição sem recarregar, rota antiga virando atalho."""
from __future__ import annotations

import http.client
import json
import re
import subprocess
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


ONBOARD_CSS = ROOT / "brainlib" / "assets" / "src" / "onboard.css"

_RENDER_STUB = """
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const chosen = {llm: "x", embeddings: "y", reranker: "z", decision: "off"};
const listFor = slot => [{key: chosen[slot], label: "L-" + slot, recommended: true, cloud: true, model: "m"}];
const getProv = (slot, key) => listFor(slot).find(p => p.key === key) || null;
"""


def _slice(text: str, start: str, end: str) -> str:
    a = text.index(start)
    b = text.index(end, a) + len(end)
    return text[a:b]


def _line(text: str, start: str) -> str:
    a = text.index(start)
    return text[a:text.index("\n", a)]


def _render_header(text: str) -> dict:
    """Roda o `renderSlot` REAL da cópia (painel ou página própria) no node, com o mínimo de stubs."""
    harness = (_RENDER_STUB + _slice(text, "const LLM_OPS = [", "];\n") + "\n"
               + _line(text, "const opTerm = ") + "\n"
               + _slice(text, "const renderSlot = (slot, title, ops) => {", "\n  };\n") + "\n"
               'process.stdout.write(JSON.stringify({llm: renderSlot("llm", "LLM", LLM_OPS),'
               ' emb: renderSlot("embeddings", "Embeddings")}));')
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


class LlmSlotHeaderTests(unittest.TestCase):
    """O slot LLM do wizard nomeia as operações e explica cada uma no tooltip — o header dizia só "extração de fatos".
    As DUAS cópias do JS (painel e página própria) carregam a mesma lista de `providers.LLM_OPS_INFO`."""

    @classmethod
    def setUpClass(cls):
        from brainlib import providers
        cls.ops = list(providers.LLM_OPS_INFO.values())
        cls.sources = {"painel": EXTRA.read_text(encoding="utf-8"), "página": OB_HTML.read_text(encoding="utf-8")}

    def test_as_operacoes_sao_as_mesmas_nas_duas_copias_e_no_registro(self):
        from brainlib import providers
        self.assertEqual(set(providers.LLM_OPS_INFO), {"retain", "consolidation", "reflect"})
        self.assertLessEqual(set(providers.LLM_OPS_INFO), {op for op, _ in providers.LLM_OPS})   # só operação que o servidor tem
        for onde, texto in self.sources.items():
            with self.subTest(onde=onde):
                self.assertEqual(_steps_literal(texto, "const LLM_OPS"), self.ops)
                self.assertNotIn("LLM — extração de fatos", texto)
        for nome, tip in self.ops:                                                # prosa: `brain <cmd>` no JS do painel
            self.assertNotRegex(tip, r"\bbrain \w")                               # conta como gesto emitido (allowlist)

    def test_rotulo_do_slot_sai_da_lista(self):
        from brainlib import providers
        self.assertEqual(providers.SLOT_LABELS["llm"], "LLM (Retain · Consolidação · Reflexão)")
        self.assertEqual(providers.SLOT_LABELS["llm"],
                         "LLM (" + " · ".join(n for n, _ in providers.LLM_OPS_INFO.values()) + ")")

    def test_cada_operacao_vira_um_termo_com_tooltip(self):
        esperado = "LLM — " + "&nbsp;· ".join(                                    # &nbsp: na quebra de linha o "·" fica no fim, não no começo
            f'<span class="op" tabindex="0" title="{tip}">{nome}</span>' for nome, tip in self.ops)
        for onde, texto in self.sources.items():
            with self.subTest(onde=onde):
                r = _render_header(texto)
            self.assertIn('<div class="sh"><span>' + esperado + "</span>", r["llm"])
            self.assertIn('class="pill rec"', r["llm"])
            self.assertIn('<div class="sh"><span>Embeddings</span>', r["emb"])       # slot sem operações: header intacto
            self.assertNotIn('class="op"', r["emb"])

    def test_afordancia_de_hover_existe_nas_duas_casas_de_css(self):
        css = ONBOARD_CSS.read_text(encoding="utf-8")
        self.assertRegex(css, re.compile(r"\.obw \.sh \.op \{[^}]*text-decoration: underline dotted[^}]*cursor: help; \}"))
        self.assertRegex(self.sources["página"], re.compile(r"\.sh \.op\{[^}]*text-decoration:underline dotted[^}]*cursor:help\}"))
        built = BUILT.read_text(encoding="utf-8")                                   # o painel construído carrega os dois
        self.assertIn(".obw .sh .op {", built)
        self.assertIn("const LLM_OPS", built)


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
