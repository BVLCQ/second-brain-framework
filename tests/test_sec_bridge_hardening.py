"""Testes de endurecimento da ponte HTTP (`serve.py` e `render.ensure_bridge`): #103, #107, #112, #125."""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import __version__, config, render, serve, util  # noqa: E402


def _make_inst(root: Path) -> config.Instance:
    (root / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED/_ledger", "FRESH", "logs", "reports"):
        (root / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (root / "config" / "brain.toml").write_text(
        '[owner]\nid = "marina-demo"\nname = "Marina Demo"\n'
        '[owner.extra]\norg = "Padaria Pão Quente"\nemail = "marina-demo@x.com"\n',
        encoding="utf-8",
    )
    (root / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    (root / "vault" / "PROCESSED" / "_ledger" / "events.jsonl").write_text("", encoding="utf-8")
    return config.load(root)


def _multipart_move(filename: str, file_bytes: bytes, source_path: str) -> tuple[str, bytes]:
    boundary = "----BrainSecHardeningBoundary"
    parts = [
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8") + file_bytes + b"\r\n",
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="mode"\r\n\r\nmove\r\n'.encode("utf-8"),
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="source_path"\r\n\r\n{source_path}\r\n'.encode("utf-8"),
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


class BridgeHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.inst = _make_inst(Path(cls.td.name) / "inst")
        cls.token = "tok-" + "bridge-hardening-demo"
        cls.state = serve._State(cls.inst, cls.token)
        serve._Handler.state = cls.state
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.state.port = cls.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        serve.live_url_file(cls.inst).unlink(missing_ok=True)
        cls.td.cleanup()

    def setUp(self):
        serve._Handler.state = self.state
        serve.live_url_file(self.inst).unlink(missing_ok=True)

    def _req(
        self,
        path: str,
        *,
        token: str | None = None,
        method: str = "GET",
        body: dict | None = None,
    ) -> tuple[int, dict]:
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Host", f"127.0.0.1:{self.port}")
        if token is not None:
            req.add_header("X-Brain-Token", token)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    # ── #103: allowlist estrita por argv ─────────────────────────────────
    def test_doctor_mutating_flags_denied_with_403(self):
        for cmd in (
            "brain doctor --fix --apply",
            "brain doctor --fix",
            "brain doctor --dry-run",
            "brain doctor --apply",
            "brain doctor --online --fix",
            "brain doctor --unknown",
            "brain doctor extra",
        ):
            with self.subTest(cmd=cmd):
                code, payload = self._req("/api/cmd", token=self.token, method="POST", body={"cmd": cmd})
                self.assertEqual(code, 403, payload)
                self.assertFalse(payload["ok"])
                self.assertIn("allowlist", payload["error"])

        self.assertTrue(serve._allowed_argv(["doctor"]))
        self.assertTrue(serve._allowed_argv(["doctor", "--online"]))
        self.assertTrue(serve._allowed_argv(["doctor", "--json"]))
        self.assertTrue(serve._allowed_argv(["doctor", "--online", "--json"]))

        code, payload = self._req("/api/cmd", token=self.token, method="POST", body={"cmd": "brain doctor --json"})
        self.assertEqual(code, 200, payload)

    def test_none_subcommand_routes_validate_flags(self):
        denied_cmds = (
            "brain render --open",
            "brain render --open portfolio",
            "brain render --open=execucao",
            "brain render --unknown",
            "brain render extra",
            "brain share invalid",
            "brain share project PROJ-1 --unknown",
            "brain share status --format html --evil x",
            "brain share portfolio PROJ-1 extra",
            "brain progress GOAL-1",
            "brain progress GOAL-1 45 --unknown",
            "brain progress GOAL-1 45 extra",
            "brain delivery 'Entrega demo' --unknown",
            "brain delivery 'Entrega demo' --actor marina-demo",
            "brain delivery 'Entrega demo' extra",
            "brain search",
            "brain search --json",
            "brain search forno --limit abc",
            "brain search forno --unknown",
            "brain search forno extra",
        )
        for cmd in denied_cmds:
            with self.subTest(cmd=cmd):
                code, payload = self._req("/api/cmd", token=self.token, method="POST", body={"cmd": cmd})
                self.assertEqual(code, 403, f"deveria recusar {cmd}: {payload}")
                self.assertFalse(payload["ok"])

        today = util.today().isoformat()
        allowed_argvs = (
            ["render"],
            ["render", "--no-harvest"],
            ["render", "--json"],
            ["render", "--no-harvest", "--json"],
            ["share", "status"],
            ["share", "project", "PROJ-1", "--format", "md"],
            ["share", "portfolio", "--area", "operacoes", "--json"],
            ["share", "opportunity", "OPP-0001"],
            ["progress", "GOAL-1", "45"],
            ["progress", "GOAL-1", "45", "--note", "cardápio andou", "--json"],
            ["delivery", "Entrega demo"],
            [
                "delivery",
                "Entrega demo",
                "--ref",
                "PROJ-1",
                "--result",
                "reduziu fila",
                "--impact",
                "alto",
                "--evidence",
                "RAW/2026/10/notes/nota.md",
                "--by",
                "owner",
                "--prov",
                "declarado",
                "--source",
                "chat",
                "--date",
                today,
                "--json",
            ],
            ["search", "forno"],
            ["search", "forno", "--limit", "5", "--json"],
        )
        for argv in allowed_argvs:
            with self.subTest(argv=argv):
                self.assertTrue(serve._allowed_argv(argv))

        # Fallback deny para comando None sem regra em ALLOWED_RULES
        with mock.patch.dict(serve.ALLOWED, {"sem_regra": None}):
            self.assertFalse(serve._allowed_argv(["sem_regra"]))
            self.assertFalse(serve._allowed_argv(["sem_regra", "--json"]))

    # ── #112: liveness autenticada via GET /api/ping ─────────────────────
    def test_live_panel_url_rejects_foreign_tcp_listener_and_cleans_stale_file(self):
        # 1. /api/ping exige token válido
        code_no_tok, _ = self._req("/api/ping")
        self.assertEqual(code_no_tok, 401)
        code_bad_tok, _ = self._req("/api/ping", token="errado")
        self.assertEqual(code_bad_tok, 401)
        code_ok, ping_data = self._req("/api/ping", token=self.token)
        self.assertEqual(code_ok, 200)
        self.assertTrue(ping_data["ok"])
        self.assertEqual(ping_data["pid"], os.getpid())
        self.assertEqual(ping_data["version"], __version__)

        # 2. Listener HTTP estranho (não é o Brain) → live_panel_url devolve None e limpa serve.json
        class _ForeignHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = json.dumps({"ok": False, "service": "foreign"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A002
                return

        foreign = ThreadingHTTPServer(("127.0.0.1", 0), _ForeignHandler)
        foreign_port = foreign.server_address[1]
        t_foreign = threading.Thread(target=foreign.serve_forever, daemon=True)
        t_foreign.start()
        self.addCleanup(lambda: (foreign.shutdown(), foreign.server_close()))

        f = serve.live_url_file(self.inst)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            json.dumps({
                "url": f"http://127.0.0.1:{foreign_port}/#t={self.token}",
                "port": foreign_port,
                "pid": os.getpid(),
            }),
            encoding="utf-8",
        )
        self.assertIsNone(serve.live_panel_url(self.inst))
        self.assertFalse(f.exists())

        # 3. Listener TCP cru (aceita conexão e fecha sem HTTP) → também rejeitado e limpo
        raw_sock = socket.socket()
        raw_sock.bind(("127.0.0.1", 0))
        raw_sock.listen(1)
        self.addCleanup(raw_sock.close)
        raw_port = raw_sock.getsockname()[1]

        def _accept_and_drop():
            try:
                conn, _ = raw_sock.accept()
                conn.close()
            except OSError:
                pass

        threading.Thread(target=_accept_and_drop, daemon=True).start()
        f.write_text(
            json.dumps({
                "url": f"http://127.0.0.1:{raw_port}/#t={self.token}",
                "port": raw_port,
                "pid": os.getpid(),
            }),
            encoding="utf-8",
        )
        self.assertIsNone(serve.live_panel_url(self.inst))
        self.assertFalse(f.exists())

        # 4. Ponte real com token válido → devolve URL viva
        expected_url = f"http://127.0.0.1:{self.port}/#t={self.token}"
        f.write_text(
            json.dumps({"url": expected_url, "port": self.port, "pid": os.getpid()}),
            encoding="utf-8",
        )
        self.assertEqual(serve.live_panel_url(self.inst), expected_url)
        self.assertTrue(f.exists())

        # 5. Token errado no serve.json contra ponte real → 401 no ping, limpa serve.json
        f.write_text(
            json.dumps({"url": f"http://127.0.0.1:{self.port}/#t=errado", "port": self.port, "pid": os.getpid()}),
            encoding="utf-8",
        )
        self.assertIsNone(serve.live_panel_url(self.inst))
        self.assertFalse(f.exists())

    def test_ensure_bridge_uses_authenticated_liveness_not_raw_tcp(self):
        # Mesmo se houver um listener TCP na porta, sem /api/ping válido ensure_bridge não retorna URL falsa
        from brainlib.core import Brain

        raw_sock = socket.socket()
        raw_sock.bind(("127.0.0.1", 0))
        raw_sock.listen(1)
        self.addCleanup(raw_sock.close)
        port = raw_sock.getsockname()[1]

        f = serve.live_url_file(self.inst)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            json.dumps({"url": f"http://127.0.0.1:{port}/#t={self.token}", "port": port, "pid": os.getpid()}),
            encoding="utf-8",
        )
        with mock.patch("subprocess.Popen"), \
             mock.patch("time.sleep"):
            got = render.ensure_bridge(Brain(self.inst), port=port, wait_s=0.05)
        self.assertIsNone(got)
        self.assertFalse(f.exists())

    # ── #125: identidade byte a byte no move ─────────────────────────────
    def test_try_move_source_refuses_mismatched_bytes(self):
        with tempfile.TemporaryDirectory() as home_td:
            fake_home = Path(home_td)
            src = fake_home / "Downloads" / "relatorio.txt"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(b"conteudo-original-no-disco")

            with mock.patch("brainlib.serve.Path.home", return_value=fake_home):
                # Conteúdo diferente → recusa e preserva original
                self.assertFalse(serve._try_move_source(str(src), self.inst, b"conteudo-diferente"))
                self.assertTrue(src.exists())
                self.assertEqual(src.read_bytes(), b"conteudo-original-no-disco")

                # Via POST /api/inbox em mode=move com source_path divergente → original preservado
                ct, raw_body = _multipart_move("relatorio.txt", b"outro-arquivo-upload", str(src))
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/inbox",
                    data=raw_body,
                    method="POST",
                    headers={
                        "Host": f"127.0.0.1:{self.port}",
                        "X-Brain-Token": self.token,
                        "Content-Type": ct,
                        "Content-Length": str(len(raw_body)),
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    self.assertEqual(resp.status, 200)
                    res = json.loads(resp.read().decode("utf-8"))
                self.assertFalse(res["moved"])
                self.assertTrue(res["fallback_copy"])
                self.assertTrue(src.exists())

                # Conteúdo idêntico → apaga original e devolve True
                self.assertTrue(serve._try_move_source(str(src), self.inst, b"conteudo-original-no-disco"))
                self.assertFalse(src.exists())


if __name__ == "__main__":
    unittest.main()
