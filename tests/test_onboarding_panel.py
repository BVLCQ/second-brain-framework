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

from brainlib import config, onboard, serve, setup, watch                 # noqa: E402
from brainlib.core import Brain                                          # noqa: E402
from brainlib import render                                              # noqa: E402

EXTRA = ROOT / "brainlib" / "assets" / "src" / "extra.js"
CORE = ROOT / "brainlib" / "assets" / "src" / "core.js"
CSS = ROOT / "brainlib" / "assets" / "src" / "onboard.css"
OB_HTML = ROOT / "brainlib" / "assets" / "onboarding.html"
BUILT = ROOT / "brainlib" / "assets" / "dashboard.html"


def _steps_literal(text: str, decl: str) -> list[tuple[str, str]]:
    m = re.search(re.escape(decl) + r"\s*=\s*\[(.*?)\];", text, re.S)
    if not m:
        raise AssertionError(f"literal não encontrado: {decl}")
    return re.findall(r'\["([^"]+)",\s*"([^"]+)"\]', m.group(1))


def _src_meta_keys(text: str) -> list[str]:
    """Chaves do `const SRC_META = {…}` — a receita de formulário de cada tipo de fonte."""
    m = re.search(r"const SRC_META = \{(.*?)\n\s*\};", text, re.S)
    if not m:
        raise AssertionError("const SRC_META = {…} não encontrado")
    return [a or b for a, b in re.findall(r'^\s{4}(?:"([^"]+)"|([a-z][\w-]*)):\s*\{', m.group(1), re.M)]


def _squash(css: str) -> str:
    """CSS sem comentários e com um espaço só onde ele separa palavras — para comparar declarações entre a
    página própria, a fonte do painel e o painel construído."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s*([{}:;,>])\s*", r"\1", re.sub(r"\s+", " ", css))
    return css.replace(";}", "}")                                # `;` antes de `}` é ruído entre as duas superfícies


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


class SourceFormTests(unittest.TestCase):
    """Passo Fontes: o Tipo só oferece o que o formulário sabe preencher; seletor e campo são a mesma caixa."""

    @classmethod
    def setUpClass(cls):
        cls.extra = EXTRA.read_text(encoding="utf-8")
        cls.page = OB_HTML.read_text(encoding="utf-8")
        m = re.search(r"<style>(.*?)</style>", cls.page, re.S)
        assert m, "onboarding.html sem <style>"
        cls.css = _squash(CSS.read_text(encoding="utf-8"))
        cls.page_css = _squash(m.group(1))

    def test_tipo_so_oferece_kind_com_receita(self):
        """A lista de kinds do servidor passa pela receita do formulário antes de virar option."""
        for text, state in ((self.extra, "OBS"), (self.page, "S")):
            self.assertIn(f"({state}.watch_kinds || []).filter(([k]) => SRC_META[k])", text)

    def test_receitas_iguais_no_painel_e_na_pagina(self):
        self.assertEqual(_src_meta_keys(self.extra), _src_meta_keys(self.page))

    def test_todo_kind_do_servidor_tem_receita_menos_os_opt_in(self):
        """Kind do servidor sem receita ficava no Tipo com rótulo "undefined" e o parâmetro era descartado no
        envio. Hoje só fica de fora o opt-in avançado (nasce pelo `brain watch add`); kind novo sem receita
        reprova aqui — a decisão de oferecer ou não é tomada de propósito, não por esquecimento."""
        kinds = {k for k, _ in watch.KINDS}
        receitas = set(_src_meta_keys(self.extra))
        self.assertEqual(kinds - receitas, {"slack-dm"})
        self.assertEqual(receitas - kinds, set(), "receita de kind que o servidor não conhece")

    def test_seletor_e_campo_dividem_a_mesma_caixa(self):
        """`<select>` com appearance:auto ficava mais baixo que o campo ao lado (line-height:normal do UA e o
        desenho nativo). Altura única para os campos de uma linha e o seletor; seta desenhada em var(--muted)."""
        arrow = ("{appearance:none;-webkit-appearance:none;line-height:1.5;padding-right:30px;"
                 "text-overflow:ellipsis;")
        self.assertIn(".obw input[type=date],.obw select{height:40px}", self.css)
        self.assertIn(".obw select" + arrow, self.css)
        self.assertIn("input[type=date],select{height:40px}", self.page_css)
        self.assertIn("select" + arrow, self.page_css)
        built = _squash(BUILT.read_text(encoding="utf-8"))          # o painel servido é o construído
        self.assertIn(".obw input[type=date],.obw select{height:40px}", built)
        self.assertIn(".obw select" + arrow, built)

    def test_tipo_tem_a_coluna_mais_larga_e_a_linha_fecha_sem_a_janela(self):
        """O rótulo mais longo do registro cabe inteiro no Tipo; sem a Janela, a linha não fica com um
        buraco à direita."""
        tres = "{grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) minmax(0,.8fr)}"
        duas = ":has(>label.f:nth-child(3).hidden){grid-template-columns:minmax(0,1.3fr) minmax(0,1fr)}"
        for css, sel in ((self.css, ".obw .addform .grid3"), (self.page_css, ".addform .grid3")):
            self.assertIn(sel + tres, css)
            self.assertIn(sel + duas, css)


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
