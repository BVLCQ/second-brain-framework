"""Testes de imposição de timeouts e conversão de TimeoutExpired em subprocessos."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import pdf, setup, util  # noqa: E402
from brainlib import tui  # noqa: E402


class TestPdfTimeouts(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.pdf_path = Path(self.td.name) / "doc.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 dummy")

    def test_pdf_text_pdftotext_passes_timeout(self):
        calls = []

        def fake_run(argv, **kw):
            if argv[0] == "pdftotext":
                calls.append((argv, kw))
                return subprocess.CompletedProcess(argv, 0, "Texto página 1\fTexto página 2\f", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/pdftotext" if cmd == "pdftotext" else None), \
             mock.patch("subprocess.run", side_effect=fake_run):
            # Sem páginas especificadas: 1 chamada com timeout=PDF_TIMEOUT_S
            out = pdf.text(self.pdf_path)
            self.assertIn("=== PÁGINA 1 ===", out)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1].get("timeout"), pdf.PDF_TIMEOUT_S)

            # Com páginas: 1 chamada por página com timeout=PDF_TIMEOUT_S
            calls.clear()
            out_pages = pdf.text(self.pdf_path, pages=[1, 2])
            self.assertEqual(len(calls), 2)
            for _, kw in calls:
                self.assertEqual(kw.get("timeout"), pdf.PDF_TIMEOUT_S)

    def test_pdf_text_swift_passes_timeout(self):
        calls = []

        def fake_run(argv, **kw):
            if argv[0] == "swift":
                calls.append((argv, kw))
                return subprocess.CompletedProcess(argv, 0, "=== PÁGINA 1 ===\nTexto swift", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("shutil.which", return_value=None), \
             mock.patch("brainlib.pdf._swift_tool", return_value=["swift", "/tmp/tool"]), \
             mock.patch("subprocess.run", side_effect=fake_run):
            out = pdf.text(self.pdf_path)
            self.assertIn("=== PÁGINA 1 ===", out)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1].get("timeout"), pdf.PDF_TIMEOUT_S)

    def test_pdf_text_timeout_expired_raises_brain_error(self):
        def fake_run(argv, **kw):
            if argv[0] == "pdftotext":
                raise subprocess.TimeoutExpired(argv[0], pdf.PDF_TIMEOUT_S)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/pdftotext" if cmd == "pdftotext" else None), \
             mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(util.BrainError) as ctx:
                pdf.text(self.pdf_path)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("tempo esgotado", str(ctx.exception))
            self.assertIn("pdftotext", str(ctx.exception))
            self.assertIn(f"{pdf.PDF_TIMEOUT_S}s", str(ctx.exception))

    def test_pdf_text_swift_timeout_expired_raises_brain_error(self):
        def fake_run(argv, **kw):
            if argv[0] == "swift":
                raise subprocess.TimeoutExpired(argv[0], pdf.PDF_TIMEOUT_S)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("shutil.which", return_value=None), \
             mock.patch("brainlib.pdf._swift_tool", return_value=["swift", "/tmp/tool"]), \
             mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(util.BrainError) as ctx:
                pdf.text(self.pdf_path)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("tempo esgotado", str(ctx.exception))
            self.assertIn("swift", str(ctx.exception))

    def test_pdf_render_pdftoppm_passes_timeout(self):
        calls = []

        def fake_run(argv, **kw):
            if argv[0] == "pdftoppm":
                calls.append((argv, kw))
                # Cria arquivo de saída fake para render() encontrar
                if "-singlefile" in argv:
                    out_prefix = argv[-1]
                    Path(f"{out_prefix}.png").write_bytes(b"png")
                else:
                    dest_prefix = Path(argv[-1])
                    (dest_prefix.parent / "pagina-001.png").write_bytes(b"png")
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/pdftoppm" if cmd == "pdftoppm" else None), \
             mock.patch("subprocess.run", side_effect=fake_run):
            out_dir = Path(self.td.name) / "rendered"
            # Sem páginas
            res = pdf.render(self.pdf_path, out=out_dir)
            self.assertTrue(len(res) > 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1].get("timeout"), pdf.PDF_TIMEOUT_S)

            # Com páginas
            calls.clear()
            res_pages = pdf.render(self.pdf_path, pages=[1], out=out_dir)
            self.assertTrue(len(res_pages) > 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1].get("timeout"), pdf.PDF_TIMEOUT_S)

    def test_pdf_render_swift_passes_timeout(self):
        calls = []

        def fake_run(argv, **kw):
            if argv[0] == "swift":
                calls.append((argv, kw))
                return subprocess.CompletedProcess(argv, 0, "/tmp/out/pagina-001.png\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("shutil.which", return_value=None), \
             mock.patch("brainlib.pdf._swift_tool", return_value=["swift", "/tmp/tool"]), \
             mock.patch("subprocess.run", side_effect=fake_run):
            res = pdf.render(self.pdf_path)
            self.assertEqual(len(res), 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1].get("timeout"), pdf.PDF_TIMEOUT_S)

    def test_pdf_render_timeout_expired_raises_brain_error(self):
        def fake_run(argv, **kw):
            if argv[0] == "pdftoppm":
                raise subprocess.TimeoutExpired(argv[0], pdf.PDF_TIMEOUT_S)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/pdftoppm" if cmd == "pdftoppm" else None), \
             mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(util.BrainError) as ctx:
                pdf.render(self.pdf_path)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("tempo esgotado", str(ctx.exception))
            self.assertIn("pdftoppm", str(ctx.exception))
            self.assertIn(f"{pdf.PDF_TIMEOUT_S}s", str(ctx.exception))

    def test_pdf_render_swift_timeout_expired_raises_brain_error(self):
        def fake_run(argv, **kw):
            if argv[0] == "swift":
                raise subprocess.TimeoutExpired(argv[0], pdf.PDF_TIMEOUT_S)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("shutil.which", return_value=None), \
             mock.patch("brainlib.pdf._swift_tool", return_value=["swift", "/tmp/tool"]), \
             mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(util.BrainError) as ctx:
                pdf.render(self.pdf_path)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("tempo esgotado", str(ctx.exception))
            self.assertIn("swift", str(ctx.exception))


class TestTuiSetupTimeouts(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        (self.root / tui.REQS).write_text("textual==0.1.0\n", encoding="utf-8")

    def test_tui_setup_passes_timeout(self):
        calls = []

        def fake_run(argv, **kw):
            calls.append((argv, kw))
            # Cria executável python falso na venv para que o setup continue até o pip
            py_bin = self.root / tui.VENV / "bin" / "python"
            py_bin.parent.mkdir(parents=True, exist_ok=True)
            py_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("subprocess.run", side_effect=fake_run), \
             mock.patch("sys.stdout", io.StringIO()):
            tui.setup(self.root)

        self.assertEqual(len(calls), 2)
        # Primeira chamada: criação do venv
        argv_venv, kw_venv = calls[0]
        self.assertEqual(argv_venv[0], sys.executable)
        self.assertEqual(argv_venv[1:3], ["-m", "venv"])
        self.assertEqual(kw_venv.get("timeout"), tui.VENV_TIMEOUT_S)

        # Segunda chamada: pip install
        argv_pip, kw_pip = calls[1]
        self.assertEqual(argv_pip[1:3], ["-m", "pip"])
        self.assertEqual(kw_pip.get("timeout"), tui.PIP_TIMEOUT_S)

    def test_tui_setup_venv_timeout_raises_brain_error(self):
        def fake_run(argv, **kw):
            if "-m" in argv and "venv" in argv:
                raise subprocess.TimeoutExpired(argv[0], tui.VENV_TIMEOUT_S)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("subprocess.run", side_effect=fake_run), \
             mock.patch("sys.stdout", io.StringIO()):
            with self.assertRaises(util.BrainError) as ctx:
                tui.setup(self.root)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("tempo esgotado", str(ctx.exception))
            self.assertIn("venv", str(ctx.exception))
            self.assertIn(f"{tui.VENV_TIMEOUT_S}s", str(ctx.exception))

    def test_tui_setup_pip_timeout_raises_brain_error(self):
        def fake_run(argv, **kw):
            if "-m" in argv and "venv" in argv:
                py_bin = self.root / tui.VENV / "bin" / "python"
                py_bin.parent.mkdir(parents=True, exist_ok=True)
                py_bin.write_text("#!/bin/sh\n", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "", "")
            if "-m" in argv and "pip" in argv:
                raise subprocess.TimeoutExpired(argv[0], tui.PIP_TIMEOUT_S)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("subprocess.run", side_effect=fake_run), \
             mock.patch("sys.stdout", io.StringIO()):
            with self.assertRaises(util.BrainError) as ctx:
                tui.setup(self.root)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("tempo esgotado", str(ctx.exception))
            self.assertIn("pip", str(ctx.exception))
            self.assertIn(f"{tui.PIP_TIMEOUT_S}s", str(ctx.exception))


class TestSetupOAuthTimeouts(unittest.TestCase):
    def _run_oauth(self, run_side_effect=None):
        calls = []

        def default_run(argv, **kw):
            calls.append((argv, kw))
            if run_side_effect:
                return run_side_effect(argv, **kw)
            return subprocess.CompletedProcess(argv, 0, "", "")

        class FakeServer:
            def __init__(self, addr, handler_cls):
                self.addr = addr
                self.handler_cls = handler_cls
                self.timeout = None
                handler_cls.code = "test-auth-code"

            def handle_request(self):
                pass

            def server_close(self):
                pass

        class FakeHTTPResponse:
            def __init__(self, data: dict):
                self.raw = json.dumps(data).encode("utf-8")

            def read(self):
                return self.raw

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with mock.patch("shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}" if cmd in ("xdg-open", "open") else None), \
             mock.patch("brainlib.setup.HTTPServer", FakeServer), \
             mock.patch("urllib.request.urlopen", return_value=FakeHTTPResponse({"refresh_token": "rt-demo-123"})), \
             mock.patch("subprocess.run", side_effect=default_run):
            token = setup.google_refresh_token("client_id", "client_secret", open_browser=True, say=lambda *a: None)
            return token, calls

    def test_setup_google_refresh_token_passes_timeout(self):
        token, calls = self._run_oauth()
        self.assertEqual(token, "rt-demo-123")
        self.assertEqual(len(calls), 1)
        argv, kw = calls[0]
        self.assertEqual(argv[0], "/usr/bin/xdg-open")
        self.assertEqual(kw.get("timeout"), 15)

    def test_setup_google_refresh_token_opener_timeout_does_not_break(self):
        def timeout_side_effect(argv, **kw):
            if argv[0] == "/usr/bin/xdg-open":
                raise subprocess.TimeoutExpired(argv[0], 15)
            return subprocess.CompletedProcess(argv, 0, "", "")

        token, calls = self._run_oauth(run_side_effect=timeout_side_effect)
        self.assertEqual(token, "rt-demo-123")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].get("timeout"), 15)

    def test_setup_google_refresh_token_opener_oserror_does_not_break(self):
        def oserror_side_effect(argv, **kw):
            if argv[0] == "/usr/bin/xdg-open":
                raise OSError("exec format error")
            return subprocess.CompletedProcess(argv, 0, "", "")

        token, calls = self._run_oauth(run_side_effect=oserror_side_effect)
        self.assertEqual(token, "rt-demo-123")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].get("timeout"), 15)


if __name__ == "__main__":
    unittest.main()
