"""Abrir o painel (macOS): reaproveita a aba do Brain que já está aberta em vez de abrir outra.

Tudo com mocks: nenhum teste toca no navegador real nem nas abas do dono (o `webbrowser.open` interceptado nunca chega
ao `_MacOpen`, e aqui `subprocess.run` é falso)."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import webbrowser
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import util  # noqa: E402

LIVE = "http://127.0.0.1:8787/#t=novo-token"


def _run(running=True, out="ok", code=0, calls=None):
    def fake(argv, **kw):
        if calls is not None:
            calls.append(argv)
        if argv[0].endswith("pgrep"):
            return subprocess.CompletedProcess(argv, 0 if running else 1, "", "")
        return subprocess.CompletedProcess(argv, code, out, "")
    return fake


class TabPrefixTest(unittest.TestCase):
    def test_only_the_local_bridge_and_files_are_reused(self):
        self.assertEqual(util._tab_prefix("http://127.0.0.1:8787/#t=x"), "http://127.0.0.1:8787/")
        self.assertEqual(util._tab_prefix("http://127.0.0.1:8791/onboarding#t=x"), "http://127.0.0.1:8791/")
        self.assertEqual(util._tab_prefix("file:///v/FRESH/dashboard/index.html#home"), "file:///v/FRESH/dashboard/index.html")
        self.assertIsNone(util._tab_prefix("https://claude.ai/settings/connectors"))
        self.assertIsNone(util._tab_prefix("http://localhost:8787/"))


class FocusOpenTabTest(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(util.sys, "platform", "darwin"),
                  mock.patch.object(util, "_default_browser", return_value=("Safari", "safari"))):
            p.start()
            self.addCleanup(p.stop)

    def test_found_tab_is_focused(self):
        calls: list = []
        with mock.patch("subprocess.run", _run(calls=calls)):
            self.assertTrue(util.focus_open_tab(LIVE))
        osa = next(c for c in calls if c[0].endswith("osascript"))
        self.assertEqual(osa[-2:], ["http://127.0.0.1:8787/", LIVE])           # prefixo da origem + URL de destino
        self.assertIn('tell application "Safari"', osa[2])

    def test_no_tab_found_falls_back(self):
        with mock.patch("subprocess.run", _run(out="")):
            self.assertFalse(util.focus_open_tab(LIVE))

    def test_closed_browser_is_never_launched(self):
        calls: list = []
        with mock.patch("subprocess.run", _run(running=False, calls=calls)):
            self.assertFalse(util.focus_open_tab(LIVE))
        self.assertFalse(any(c[0].endswith("osascript") for c in calls), "osascript abriria o navegador fechado")

    def test_denied_permission_or_timeout_falls_back(self):
        with mock.patch("subprocess.run", _run(code=1, out="")):
            self.assertFalse(util.focus_open_tab(LIVE))
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("osascript", 10)):
            self.assertFalse(util.focus_open_tab(LIVE))

    def test_tab_in_non_default_browser_is_found(self):
        """A razão da varredura: a aba do Brain mora num navegador que NÃO é o padrão.
        Padrão (Safari) sem a aba → a varredura continua e acha no Chrome."""
        calls: list = []

        def fake(argv, **kw):
            calls.append(argv)
            if argv[0].endswith("pgrep"):
                running = argv[2] in ("Safari", "Google Chrome")           # os dois abertos
                return subprocess.CompletedProcess(argv, 0 if running else 1, "", "")
            # osascript: só o Chrome tem a aba do Brain
            found = "Chrome" in argv[2]
            return subprocess.CompletedProcess(argv, 0, "ok" if found else "", "")

        with mock.patch.object(util, "_default_browser", return_value=("Safari", "safari")), \
                mock.patch("subprocess.run", fake):
            self.assertTrue(util.focus_open_tab(LIVE))
        chromes = [c for c in calls if c[0].endswith("osascript") and "Chrome" in c[2]]
        self.assertTrue(chromes, "a varredura precisa ter chegado no Chrome")

    def test_default_browser_is_swept_first(self):
        calls: list = []
        with mock.patch.object(util, "_default_browser", return_value=("Google Chrome", "chromium")), \
                mock.patch("subprocess.run", _run(calls=calls)):
            self.assertTrue(util.focus_open_tab(LIVE))
        first_osa = next(c for c in calls if c[0].endswith("osascript"))
        self.assertIn("Google Chrome", first_osa[2])                      # o padrão vem antes dos demais

    def test_unknown_default_browser_or_foreign_url_is_left_alone(self):
        # padrão desconhecido: varre os navegadores controláveis que existirem (a aba do Brain pode
        # morar num navegador que não é o padrão — ruling "manage the user's browser"), mas nunca
        # ABRE nada: sem navegador rodando, é False na primeira consulta e sem osascript.
        calls: list = []
        with mock.patch.object(util, "_default_browser", return_value=None), \
                mock.patch("subprocess.run", _run(running=False, calls=calls)):
            self.assertFalse(util.focus_open_tab(LIVE))
            self.assertFalse(any(c[0].endswith("osascript") for c in calls))
        with mock.patch("subprocess.run", side_effect=AssertionError("não deveria consultar nada")):
            self.assertFalse(util.focus_open_tab("https://example.com/"))

    def test_chromium_family_uses_its_own_script(self):
        calls: list = []
        with mock.patch.object(util, "_default_browser", return_value=("Google Chrome", "chromium")), \
                mock.patch("subprocess.run", _run(calls=calls)):
            self.assertTrue(util.focus_open_tab(LIVE))
        osa = next(c for c in calls if c[0].endswith("osascript"))
        self.assertIn("active tab index", osa[2])


class MacOpenTest(unittest.TestCase):
    def test_reused_tab_skips_the_new_window(self):
        b = util._MacOpen("/usr/bin/open")
        with mock.patch.object(util, "focus_open_tab", return_value=True), \
                mock.patch.object(webbrowser.BackgroundBrowser, "open", return_value=True) as opened:
            self.assertTrue(b.open(LIVE))
        opened.assert_not_called()

    def test_without_a_tab_it_opens_as_before(self):
        b = util._MacOpen("/usr/bin/open")
        with mock.patch.object(util, "focus_open_tab", return_value=False), \
                mock.patch.object(webbrowser.BackgroundBrowser, "open", return_value=True) as opened:
            self.assertTrue(b.open(LIVE))
        opened.assert_called_once()

    def test_intercepted_webbrowser_never_touches_real_tabs(self):
        with mock.patch.object(util, "focus_open_tab", side_effect=AssertionError("tocou nas abas")), \
                mock.patch("webbrowser.open", return_value=True):
            self.assertTrue(util.open_url(LIVE))


class AppleScriptSyntaxTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("osacompile"), "só no macOS")
    def test_scripts_compile(self):
        for family, app in (("safari", "Safari"), ("chromium", "Google Chrome")):
            if not Path(f"/Applications/{app}.app").exists():
                continue                                    # osacompile precisa do dicionário do app
            with tempfile.TemporaryDirectory() as td:
                src = Path(td) / "a.applescript"
                src.write_text(util._FIND_TAB[family].format(app=app), encoding="utf-8")
                r = subprocess.run(["osacompile", "-o", str(Path(td) / "a.scpt"), str(src)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


class PageTokenHandoffTest(unittest.TestCase):
    def test_page_takes_the_new_token_from_a_reused_tab(self):
        """O painel guarda o token do `#t=` que a aba reaproveitada recebe e devolve a rota (a falta disso = 401 na ponte nova)."""
        js = (ROOT / "brainlib/assets/src/extra.js").read_text(encoding="utf-8")
        self.assertIn('window.addEventListener("hashchange", e => {', js)
        self.assertIn("if (tok !== TOK) location.reload();", js)
        for name in ("dashboard.html", "portfolio.html"):
            self.assertIn("if (tok !== TOK) location.reload();", (ROOT / "brainlib/assets" / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
