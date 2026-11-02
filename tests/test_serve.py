"""Ponte CLI do painel (./brain serve): token, host, allowlist e execução real."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, serve                              # noqa: E402
from brainlib.core import Brain                                 # noqa: E402
from brainlib import demo as demo_mod                           # noqa: E402


def _BrainAt(root):
    from brainlib.core import Brain
    return Brain(config.load(Path(root)))


def _demo_inst(td: str) -> config.Instance:
    import argparse, contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        demo_mod.cli(argparse.Namespace(dir=str(Path(td) / "inst"), open=False))
    return config.load(Path(td) / "inst")


class ServeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.inst = _demo_inst(cls.td.name)
        cls.token = "tok-teste-123"
        serve._Handler.state = serve._State(cls.inst, cls.token)
        from http.server import ThreadingHTTPServer
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        # como serve() faz: anota a URL viva p/ o render --open achar o painel vivo
        import os as _os
        from brainlib import serve as _serve
        f = _serve.live_url_file(cls.inst)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"url": f"http://127.0.0.1:{cls.port}/#t={cls.token}",
                                 "port": cls.port, "pid": _os.getpid()}), encoding="utf-8")
        _os.chmod(f, 0o600)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        from brainlib import serve as _serve
        try:
            _serve.live_url_file(cls.inst).unlink()
        except FileNotFoundError:
            pass
        cls.td.cleanup()

    def _req(self, path: str, token: str | None = None, host: str = "127.0.0.1", method="GET", body=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        if token:
            r.add_header("X-Brain-Token", token)
        r.add_header("Host", host if ":" not in host else host)   # rebinding: host controlado
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    # ── guards ───────────────────────────────────────────────────────────
    def test_sem_token_401(self):
        code, body = self._req("/api/data")
        self.assertEqual(code, 401)
        self.assertIn("token", body)

    def test_token_errado_401(self):
        code, _ = self._req("/api/data", token="errado")
        self.assertEqual(code, 401)

    def test_host_de_rebinding_403(self):
        code, body = self._req("/api/data", token=self.token, host="atacante.invalid")
        self.assertEqual(code, 403)
        self.assertIn("127.0.0.1", body)

    def test_rota_desconhecida_404(self):
        code, _ = self._req("/api/nope", token=self.token)
        self.assertEqual(code, 404)

    # ── leitura ──────────────────────────────────────────────────────────
    def test_data_e_painel_renderizado(self):
        code, body = self._req("/api/data", token=self.token)
        self.assertEqual(code, 200)
        m = json.loads(body)["model"]
        self.assertIn("actions", m)
        self.assertIn("portfolio", m)
        code, html = self._req("/", token=self.token)
        self.assertEqual(code, 200)
        self.assertNotIn("__DATA__", html)                        # view model injetado, não o placeholder
        self.assertIn("application/json", html)

    # ── allowlist ────────────────────────────────────────────────────────
    def _cmd(self, cmd: str, expect_code: int):
        code, body = self._req("/api/cmd", token=self.token, method="POST", body={"cmd": cmd})
        self.assertEqual(code, expect_code, f"{cmd}: {body[:200]}")
        return body

    def test_fora_da_allowlist_403(self):
        for cmd in ("brain update", "brain serve", "brain migrate ids --apply", "brain init",
                    "brain upstream push", "rm -rf /", "brain backup"):
            body = self._cmd(cmd, 403)
            self.assertIn("allowlist", json.loads(body)["error"])

    def test_comando_inexistente_dentro_da_allowlist_retorna_falso(self):
        body = self._cmd('brain action update TASK-9999 --status fazendo', 200)
        j = json.loads(body)
        self.assertFalse(j["ok"])                                 # o CLI recusou — e a ponte relatou
        self.assertTrue(j["err"] or j["out"])

    def test_comando_real_escreve_no_ledger_e_o_data_reflete(self):
        _, body0 = self._req("/api/data", token=self.token)
        bid = next(a["id"] for a in json.loads(body0)["model"]["actions"]
                   if a["open"] and a["status"] != "bloqueada")   # bloqueada é derivada de blocked_by — não muda com update
        body = self._cmd(f"brain action update {bid} --status fazendo --by owner", 200)
        j = json.loads(body)
        self.assertTrue(j["ok"], j)
        evs = Brain(self.inst).read_events()
        self.assertTrue(any(e["type"] == "action.updated" and e["id"] == bid for e in evs))
        _, body2 = self._req("/api/data", token=self.token)
        st = next(a["status"] for a in json.loads(body2)["model"]["actions"] if a["id"] == bid)
        self.assertEqual(st, "fazendo")

    def test_gate_do_cli_continua_valeando(self):
        """focus apply exige aprovação prévia — a ponte não contorna gates do CLI."""
        body = self._cmd("brain focus apply FOCUS-9999 --mode ics", 200)
        j = json.loads(body)
        self.assertFalse(j["ok"])

    def test_feedback_pela_ponte_registra_e_o_data_reflete(self):
        """Porta 7 no painel: add registra (sem token fica pendente), push recusado no pré-checagem."""
        body = self._cmd('brain feedback add "Painel pelo serve" --kind sugestao --by owner', 200)
        j = json.loads(body)
        self.assertTrue(j["ok"], j)
        f = next(x for x in Brain(self.inst).state.feedbacks.values() if x.title == "Painel pelo serve")
        self.assertEqual(f.status, "pendente")
        _, body2 = self._req("/api/data", token=self.token)
        self.assertTrue(any(x["id"] == f.id for x in json.loads(body2)["model"]["feedback"]))
        body3 = self._cmd(f"brain feedback push {f.id}", 200)                 # sem GITHUB_TOKEN: o CLI recusa
        self.assertFalse(json.loads(body3)["ok"])

    def test_feedback_pela_ponte_leva_contexto_e_o_payload_mostra(self):
        """Paridade de campos no painel: --context passa pela ponte e volta no /api/data."""
        body = self._cmd('brain feedback add "Contexto pelo serve" --kind bug '
                         '--context "TASK-0001, PROC-0002" --no-push --by owner', 200)
        self.assertTrue(json.loads(body)["ok"], body)
        f = next(x for x in Brain(self.inst).state.feedbacks.values() if x.title == "Contexto pelo serve")
        self.assertEqual(f.context, ["TASK-0001", "PROC-0002"])
        self.assertEqual(f.status, "pendente")                              # --no-push: só registrou
        _, body2 = self._req("/api/data", token=self.token)
        row = next(x for x in json.loads(body2)["model"]["feedback"] if x["id"] == f.id)
        self.assertEqual(row["context"], ["TASK-0001", "PROC-0002"])

    # ── headers de segurança / framing / origem ───────────────────────────
    def test_painel_nao_e_embebivel(self):
        """Clickjacking: um site qualquer não pode iframar o painel vivo e clicar por você."""
        import urllib.request
        for path in ("/", "/api/data"):
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
            req.add_header("X-Brain-Token", self.token)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    xfo, csp = resp.headers.get("X-Frame-Options"), resp.headers.get("Content-Security-Policy")
            except urllib.error.HTTPError as e:
                xfo, csp = e.headers.get("X-Frame-Options"), e.headers.get("Content-Security-Policy")
            self.assertEqual(xfo, "DENY", path)
            self.assertIn("frame-ancestors 'none'", csp or "", path)

    def test_api_rejeita_origin_de_fora(self):
        code, _ = self._req("/api/data", token=self.token)  # sanidade: sem Origin, passa
        self.assertEqual(code, 200)
        url = f"http://127.0.0.1:{self.port}/api/data"
        for evil in ("http://atacante.invalid", "http://127.0.0.1.atacante.invalid", "null"):
            r = urllib.request.Request(url, headers={"X-Brain-Token": self.token, "Origin": evil})
            try:
                with urllib.request.urlopen(r, timeout=10) as resp:
                    code = resp.status
            except urllib.error.HTTPError as e:
                code = e.code
            self.assertEqual(code, 403, evil)

    # ── parsing hostil ────────────────────────────────────────────────────
    def test_content_length_malicioso_nao_trava(self):
        import http.client
        for cl in ("-1", "abc"):
            with self.subTest(cl=cl):
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
                conn.putrequest("POST", "/api/cmd")
                conn.putheader("Host", f"127.0.0.1:{self.port}")
                conn.putheader("X-Brain-Token", self.token)
                conn.putheader("Content-Length", cl)
                conn.endheaders()
                resp = conn.getresponse()
                self.assertIn(resp.status, (400, 413))
                conn.close()

    def test_chunked_e_rejeitado_com_411(self):
        """Sem Content-Length o corpo seria lido como vazio — melhor recusar com 411 claro."""
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/api/cmd")
        conn.putheader("Host", f"127.0.0.1:{self.port}")
        conn.putheader("X-Brain-Token", self.token)
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 411)
        conn.close()

    def test_api_data_tem_health_e_notes(self):
        """O serve devolve o MESMO view model do render (saúde + notas não somem no refresh)."""
        _, body = self._req("/api/data", token=self.token)
        m = json.loads(body)["model"]
        self.assertIn("health", m)
        self.assertIn("notes", m)

    # ── painel vivo: serve.json + render --open prefere a ponte ──────────
    def test_servejson_registra_e_some(self):
        from brainlib import serve as _serve
        f = _serve.live_url_file(self.inst)
        self.assertTrue(f.exists())                              # no ar: URL+porta anotadas (0600)
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        self.assertTrue(_serve.live_panel_url(self.inst).startswith("http://127.0.0.1:"))

    def test_render_open_prefere_o_painel_vivo(self):
        """Com a ponte no ar, `brain render --open` abre o painel VIVO, não o file://."""
        import brainlib.render as _r
        from brainlib import serve as _serve
        opened = {}
        _r.webbrowser.open = lambda url: opened.setdefault("url", url)
        with tempfile.TemporaryDirectory() as td:
            import argparse, contextlib, io as _io
            with contextlib.redirect_stdout(_io.StringIO()):
                demo_mod.cli(argparse.Namespace(dir=str(Path(td) / "d2"), open=False))
            dead = _r.open_dashboard.__globals__["Brain"](config.load(Path(td) / "d2")) if False else None
            # sem ponte (spawn=False: teste não sobe daemon): abre file:// e avisa
            _r.open_dashboard(_BrainAt(Path(td) / "d2"), spawn=False)
            self.assertEqual(opened.get("url", "file://").startswith("file://"), True)
            # com ponte (a nossa, de classe): abre a URL viva com o token
            _r.open_dashboard(_BrainAt(self.inst.root))
            self.assertTrue(opened["url"].startswith("http://127.0.0.1:"))
            self.assertIn("#t=", opened["url"])

    # ── noturno ──────────────────────────────────────────────────────────
    def test_noturno_nao_serve(self):
        old = os.environ.get("BRAIN_NIGHTLY")
        os.environ["BRAIN_NIGHTLY"] = "1"
        try:
            with self.assertRaises(Exception):
                serve.serve(self.inst, port=0)
        finally:
            if old is None:
                os.environ.pop("BRAIN_NIGHTLY", None)
            else:
                os.environ["BRAIN_NIGHTLY"] = old


if __name__ == "__main__":
    unittest.main()
