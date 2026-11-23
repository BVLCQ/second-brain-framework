"""Testes do pipeline de mídia: timeout escalado de vídeo (#88), erros de PDF (#89) e varredura temp (#81)."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import pdf, util, video  # noqa: E402


class TestVideoScaledTimeout(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.media = Path(self.td.name) / "reuniao.mp4"
        self.media.write_bytes(b"fake-video")

    def _fake_popen_factory(self, captured: list[float | None]):
        class FakeProc:
            def __init__(self, cmd, **_kw):
                self.cmd = cmd
                self.returncode = 0

            def communicate(self, timeout=None):
                captured.append(timeout)
                return "[00:00:01] Oi gente\n", ""

            def poll(self):
                return self.returncode

            def kill(self):
                pass

            def wait(self):
                return 0

        return FakeProc

    def test_transcribe_scales_by_length_and_locales(self):
        captured: list[float | None] = []
        probe_calls: list[Path] = []

        def fail_probe(p):
            probe_calls.append(p)
            raise AssertionError("não devia sondar com length explícito")

        with mock.patch.object(video, "swift_tool", return_value=["/fake/stt"]):
            # 20 min × 1 idioma → 1200 s
            video.transcribe(
                self.media,
                locales=["pt-BR"],
                length=1200,
                popen=self._fake_popen_factory(captured),
                probe=fail_probe,
            )
            self.assertEqual(len(captured), 1)
            self.assertAlmostEqual(captured[0], 1200.0, delta=5.0)

            # 60 min × 2 idiomas → teto VIDEO_MAX_TIMEOUT_S (7200 s)
            captured.clear()
            video.transcribe(
                self.media,
                locales=["pt-BR", "en-US"],
                length=3600,
                popen=self._fake_popen_factory(captured),
                probe=fail_probe,
            )
            self.assertEqual(len(captured), 2)
            self.assertAlmostEqual(captured[0], video.VIDEO_MAX_TIMEOUT_S, delta=5.0)
            self.assertEqual(probe_calls, [])

    def test_transcribe_uses_injected_probe(self):
        captured: list[float | None] = []

        with mock.patch.object(video, "swift_tool", return_value=["/fake/stt"]):
            # 20 min via probe, 1 idioma → 1200 s
            video.transcribe(
                self.media,
                locales=["pt-BR"],
                length=0,
                popen=self._fake_popen_factory(captured),
                probe=lambda _p: 1200.0,
            )
            self.assertAlmostEqual(captured[-1], 1200.0, delta=5.0)

            # 2 h via probe, 1 idioma → 7200 s (teto)
            captured.clear()
            video.transcribe(
                self.media,
                locales=["pt-BR"],
                length=0,
                popen=self._fake_popen_factory(captured),
                probe=lambda _p: 7200.0,
            )
            self.assertAlmostEqual(captured[-1], video.VIDEO_MAX_TIMEOUT_S, delta=5.0)

            # probe retorna None → piso VIDEO_TIMEOUT_S (600 s)
            captured.clear()
            video.transcribe(
                self.media,
                locales=["pt-BR"],
                length=0,
                popen=self._fake_popen_factory(captured),
                probe=lambda _p: None,
            )
            self.assertAlmostEqual(captured[-1], video.VIDEO_TIMEOUT_S, delta=5.0)

            # timeout explícito vence e não chama probe
            captured.clear()
            video.transcribe(
                self.media,
                locales=["pt-BR"],
                length=0,
                timeout=42,
                popen=self._fake_popen_factory(captured),
                probe=lambda _p: (_ for _ in ()).throw(AssertionError("não devia sondar")),
            )
            self.assertAlmostEqual(captured[-1], 42.0, delta=5.0)

    def test_frames_scales_by_frame_count_and_caps(self):
        timeouts: list[int | None] = []
        out_dir = Path(self.td.name) / "frames-out"

        def fake_run(args, **kw):
            timeouts.append(kw.get("timeout"))
            return subprocess.CompletedProcess(args, 0, str(out_dir / "frame-00000.png") + "\n", "")

        with mock.patch.object(video, "swift_tool", return_value=["/fake/frames"]):
            # 3600 s / every=10 → 360 quadros × 5 s = 1800 s
            video.frames(self.media, every=10, out=out_dir, run=fake_run, probe=lambda _p: 3600.0)
            self.assertEqual(timeouts[-1], 1800)

            # 72000 s / every=5 → teto VIDEO_MAX_TIMEOUT_S (7200 s)
            video.frames(self.media, every=5, out=out_dir, run=fake_run, probe=lambda _p: 72000.0)
            self.assertEqual(timeouts[-1], video.VIDEO_MAX_TIMEOUT_S)

            # probe None → piso 600 s
            video.frames(self.media, every=10, out=out_dir, run=fake_run, probe=lambda _p: None)
            self.assertEqual(timeouts[-1], video.VIDEO_TIMEOUT_S)

            # timeout explícito pula probe
            video.frames(
                self.media,
                every=10,
                out=out_dir,
                timeout=33,
                run=fake_run,
                probe=lambda _p: (_ for _ in ()).throw(AssertionError("não devia sondar")),
            )
            self.assertEqual(timeouts[-1], 33)

            # start > 0 desconta da duração sondada
            video.frames(self.media, every=10, start=1800, out=out_dir, run=fake_run, probe=lambda _p: 3600.0)
            self.assertEqual(timeouts[-1], 900)

            # end > start usa janela (end - start) sem sondar
            video.frames(
                self.media,
                every=10,
                start=100,
                end=1900,
                out=out_dir,
                run=fake_run,
                probe=lambda _p: (_ for _ in ()).throw(AssertionError("não devia sondar com end > start")),
            )
            self.assertEqual(timeouts[-1], 900)

    def test_probe_duration_parses_mdls_and_handles_errors(self):
        def ok_run(args, **kw):
            self.assertEqual(args[0], "/usr/bin/mdls")
            self.assertEqual(kw.get("timeout"), video.MDLS_TIMEOUT_S)
            return subprocess.CompletedProcess(args, 0, "123.45\n", "")

        self.assertEqual(video.probe_duration(self.media, run=ok_run), 123.45)

        null_run = lambda args, **kw: subprocess.CompletedProcess(args, 0, "(null)\n", "")
        self.assertIsNone(video.probe_duration(self.media, run=null_run))

        def timeout_run(args, **kw):
            raise subprocess.TimeoutExpired(args, video.MDLS_TIMEOUT_S)

        self.assertIsNone(video.probe_duration(self.media, run=timeout_run))

        err_run = lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "mdls failed")
        self.assertIsNone(video.probe_duration(self.media, run=err_run))

        # Sem /usr/bin/mdls no sistema: retorna None sem chamar subprocess.run
        with mock.patch.object(Path, "is_file", return_value=False), \
             mock.patch("subprocess.run", side_effect=AssertionError("não devia chamar mdls")):
            self.assertIsNone(video.probe_duration(self.media))


class TestPdfReaderErrors(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.pdf_path = Path(self.td.name) / "doc.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4 dummy")
        self.out_dir = Path(self.td.name) / "rendered"

    def test_installed_reader_failure_reports_real_error(self):
        def fail_run(argv, **kw):
            return subprocess.CompletedProcess(argv, 1, "", "Syntax Error: PDF corrompido\ndetalhe extra")

        with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/" + cmd if cmd in ("pdftotext", "pdftoppm") else None), \
             mock.patch.object(pdf, "_swift_tool", return_value=None), \
             mock.patch.dict(sys.modules, {"pypdf": None}):
            with self.assertRaises(util.BrainError) as ctx:
                pdf.text(self.pdf_path, run=fail_run)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("PDF corrompido", str(ctx.exception))
            self.assertNotIn("instale o poppler", str(ctx.exception))

            with self.assertRaises(util.BrainError) as ctx_r:
                pdf.render(self.pdf_path, out=self.out_dir, run=fail_run)
            self.assertEqual(ctx_r.exception.code, 3)
            self.assertIn("PDF corrompido", str(ctx_r.exception))
            self.assertNotIn("instale o poppler", str(ctx_r.exception))

    def test_missing_readers_still_raise_install_hint(self):
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(pdf, "_swift_tool", return_value=None), \
             mock.patch.dict(sys.modules, {"pypdf": None}):
            with self.assertRaises(util.BrainError) as ctx:
                pdf.text(self.pdf_path)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn(pdf.HINT, str(ctx.exception))

            with self.assertRaises(util.BrainError) as ctx_r:
                pdf.render(self.pdf_path, out=self.out_dir)
            self.assertEqual(ctx_r.exception.code, 3)
            self.assertIn(pdf.HINT, str(ctx_r.exception))

    def test_out_of_range_pages_warn_stderr(self):
        def partial_text_run(argv, **kw):
            page = argv[argv.index("-f") + 1]
            if page == "1":
                return subprocess.CompletedProcess(argv, 0, "Conteúdo p1", "")
            return subprocess.CompletedProcess(argv, 1, "", "Error: Wrong page range")

        err_buf = io.StringIO()
        with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/pdftotext" if cmd == "pdftotext" else None), \
             mock.patch.object(pdf, "_swift_tool", return_value=None), \
             contextlib.redirect_stderr(err_buf):
            out = pdf.text(self.pdf_path, pages=[1, 99], run=partial_text_run)
        self.assertIn("=== PÁGINA 1 ===\nConteúdo p1", out)
        self.assertIn("99", err_buf.getvalue())
        self.assertIn("⚠", err_buf.getvalue())

        def partial_render_run(argv, **kw):
            page = argv[argv.index("-f") + 1]
            if page == "1":
                Path(argv[-1] + ".png").write_bytes(b"png")
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 1, "", "Error: Wrong page range")

        err_buf_r = io.StringIO()
        with mock.patch("shutil.which", side_effect=lambda cmd: "/usr/bin/pdftoppm" if cmd == "pdftoppm" else None), \
             mock.patch.object(pdf, "_swift_tool", return_value=None), \
             contextlib.redirect_stderr(err_buf_r):
            imgs = pdf.render(self.pdf_path, pages=[1, 99], out=self.out_dir, run=partial_render_run)
        self.assertEqual([p.name for p in imgs], ["pagina-001.png"])
        self.assertIn("99", err_buf_r.getvalue())
        self.assertIn("⚠", err_buf_r.getvalue())

    def test_swift_and_pypdf_failures_and_truncation(self):
        long_err = ("linha 1\n" + "x" * 400).strip()

        def fail_swift(argv, **kw):
            return subprocess.CompletedProcess(argv, 2, "", long_err)

        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(pdf, "_swift_tool", return_value=["/fake/pdftext"]), \
             mock.patch.dict(sys.modules, {"pypdf": None}):
            with self.assertRaises(util.BrainError) as ctx:
                pdf.text(self.pdf_path, run=fail_swift)
            msg = str(ctx.exception)
            self.assertIn("PDFKit:", msg)
            self.assertNotIn("\n", msg)
            self.assertTrue(msg.endswith("…)"))
            detail = msg.split("PDFKit: ", 1)[1].removesuffix(")")
            self.assertLessEqual(len(detail), 300)

        class FakeBrokenPdfReader:
            def __init__(self, _path):
                raise RuntimeError("arquivo truncado no xref")

        fake_pypdf = type(sys)("pypdf")
        fake_pypdf.PdfReader = FakeBrokenPdfReader
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(pdf, "_swift_tool", return_value=None), \
             mock.patch.dict(sys.modules, {"pypdf": fake_pypdf}):
            with self.assertRaises(util.BrainError) as ctx_py:
                pdf.text(self.pdf_path)
            self.assertIn("pypdf: arquivo truncado no xref", str(ctx_py.exception))
            self.assertNotIn("instale o poppler", str(ctx_py.exception))

    def test_swift_and_pypdf_out_of_range_pages_warn_stderr(self):
        def swift_partial_text(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, "=== PÁGINA 1 ===\nTexto swift\n", "")

        err_buf = io.StringIO()
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(pdf, "_swift_tool", return_value=["/fake/pdftext"]), \
             contextlib.redirect_stderr(err_buf):
            out = pdf.text(self.pdf_path, pages=[1, 99], run=swift_partial_text)
        self.assertIn("Texto swift", out)
        self.assertIn("99", err_buf.getvalue())

        def swift_partial_render(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, f"{self.out_dir}/pagina-001.png\n", "")

        err_buf_r = io.StringIO()
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(pdf, "_swift_tool", return_value=["/fake/pdfrender"]), \
             contextlib.redirect_stderr(err_buf_r):
            imgs = pdf.render(self.pdf_path, pages=[1, 99], out=self.out_dir, run=swift_partial_render)
        self.assertEqual([p.name for p in imgs], ["pagina-001.png"])
        self.assertIn("99", err_buf_r.getvalue())

        class FakePage:
            def extract_text(self):
                return "Texto pypdf"

        class FakeOkPdfReader:
            def __init__(self, _path):
                self.pages = [FakePage()]

        fake_pypdf = type(sys)("pypdf")
        fake_pypdf.PdfReader = FakeOkPdfReader
        err_buf_py = io.StringIO()
        with mock.patch("shutil.which", return_value=None), \
             mock.patch.object(pdf, "_swift_tool", return_value=None), \
             mock.patch.dict(sys.modules, {"pypdf": fake_pypdf}), \
             contextlib.redirect_stderr(err_buf_py):
            out_py = pdf.text(self.pdf_path, pages=[1, 99])
        self.assertIn("Texto pypdf", out_py)
        self.assertIn("99", err_buf_py.getvalue())


class TestTempDirSweep(unittest.TestCase):
    def test_sweep_removes_stale_and_keeps_fresh_and_current(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            now = time.time()

            old_dir = root / "brain-pdf-old"
            fresh_dir = root / "brain-pdf-fresh"
            current_dir = root / "brain-pdf-current"
            other_dir = root / "other-dir"
            target_dir = root / "target-outside"
            for d in (old_dir, fresh_dir, current_dir, other_dir, target_dir):
                d.mkdir()
                (d / "sample.txt").write_text("x", encoding="utf-8")

            link_dir = root / "brain-pdf-link"
            link_dir.symlink_to(target_dir)

            os.utime(old_dir, (now - 25 * 3600, now - 25 * 3600))
            os.utime(fresh_dir, (now - 2 * 3600, now - 2 * 3600))
            os.utime(current_dir, (now - 48 * 3600, now - 48 * 3600))
            os.utime(other_dir, (now - 48 * 3600, now - 48 * 3600))
            os.utime(target_dir, (now - 48 * 3600, now - 48 * 3600))

            removed = pdf.sweep_temp_dirs("brain-pdf-", root=root, now=now, keep=current_dir)
            self.assertEqual(removed, 1)
            self.assertFalse(old_dir.exists())
            self.assertTrue(fresh_dir.exists())
            self.assertTrue(current_dir.exists())
            self.assertTrue(other_dir.exists())
            self.assertTrue(link_dir.is_symlink())
            self.assertTrue(target_dir.exists())

    def test_render_and_frames_trigger_sweep_when_out_is_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pdf_file = root / "a.pdf"
            pdf_file.write_bytes(b"%PDF-1.4")
            vid_file = root / "v.mp4"
            vid_file.write_bytes(b"mp4")
            pdf_dest = root / "brain-pdf-new"
            vid_dest = root / "brain-video-new"
            pdf_dest.mkdir()
            vid_dest.mkdir()

            def ok_pdf_run(argv, **kw):
                (pdf_dest / "pagina-001.png").write_bytes(b"png")
                return subprocess.CompletedProcess(argv, 0, "", "")

            with mock.patch("tempfile.mkdtemp", return_value=str(pdf_dest)), \
                 mock.patch.object(pdf, "sweep_temp_dirs") as sweep_pdf, \
                 mock.patch("shutil.which", side_effect=lambda c: "/usr/bin/pdftoppm" if c == "pdftoppm" else None):
                pdf.render(pdf_file, out=None, run=ok_pdf_run)
            sweep_pdf.assert_called_once_with("brain-pdf-", keep=pdf_dest)

            def ok_vid_run(argv, **kw):
                return subprocess.CompletedProcess(argv, 0, str(vid_dest / "frame-00000.png") + "\n", "")

            with mock.patch("tempfile.mkdtemp", return_value=str(vid_dest)), \
                 mock.patch.object(video, "sweep_temp_dirs") as sweep_vid, \
                 mock.patch.object(video, "swift_tool", return_value=["/fake/frames"]):
                video.frames(vid_file, out=None, run=ok_vid_run, probe=lambda _p: 60.0)
            sweep_vid.assert_called_once_with("brain-video-", keep=vid_dest)


if __name__ == "__main__":
    unittest.main()
