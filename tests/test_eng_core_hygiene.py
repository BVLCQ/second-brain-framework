"""Testes de higiene do núcleo (#92, #81): strip_tag, serve._running_max_age, opener, providers, ice_rubric, ids e memory."""
from __future__ import annotations

import argparse
import contextlib
import io
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import (  # noqa: E402
    config,
    feedback,
    ice_rubric,
    ids,
    issues,
    memory,
    opener,
    providers,
    serve,
    util,
)
from brainlib.core import Brain  # noqa: E402


def _inst(tmp: Path, *, full_mem: bool = False) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    mem_block = '[memory]\nengine = "hindsight"\n'
    if full_mem:
        mem_block += 'extract = true\ncloud_llm = true\nraw_awaiting_dump = "hold"\n'
    (tmp / "config" / "brain.toml").write_text(
        f'[owner]\nid = "eu"\nname = "Dona-demo"\n\n{mem_block}',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path, *, full_mem: bool = False) -> Brain:
    b = Brain(_inst(tmp, full_mem=full_mem))
    b.record_one({
        "type": "person.added",
        "id": "eu",
        "by": "owner",
        "data": {"name": "Dona-demo", "aliases": ["Eu"], "relation": "dono"},
    })
    return b


class TestStripTag(unittest.TestCase):
    def test_arbitrary_prefixes_preserved_and_local_fb_stripped(self):
        self.assertEqual(issues.strip_tag("FASE-3 corrigir cache"), "FASE-3 corrigir cache")
        self.assertEqual(issues.strip_tag("FASE2-3 corrigir cache"), "FASE2-3 corrigir cache")
        self.assertEqual(issues.strip_tag("M4-2 migrar"), "M4-2 migrar")
        self.assertEqual(issues.strip_tag("API-2 erro 500"), "API-2 erro 500")
        self.assertEqual(issues.strip_tag("RFC: novo fluxo"), "RFC: novo fluxo")
        self.assertEqual(issues.strip_tag("UX — ajuste fino"), "UX — ajuste fino")

        self.assertEqual(issues.strip_tag("[Bug] título"), "título")
        self.assertEqual(issues.strip_tag("FB-0003: título"), "título")
        self.assertEqual(issues.strip_tag("fb-0003: título"), "título")
        self.assertEqual(issues.strip_tag("F-0003 - título"), "título")
        self.assertEqual(issues.strip_tag("[Sugestão] FB-0012: FASE-3 ajuste"), "FASE-3 ajuste")

        fb_item = SimpleNamespace(kind="sugestao", proposal="", title="[Sugestão] FB-0012: FASE-3 ajuste")
        self.assertEqual(feedback.issue_title(fb_item), "[Sugestão] FASE-3 ajuste")

        fb_plain = SimpleNamespace(kind="bug", proposal="", title="API-2 erro 500")
        self.assertEqual(feedback.issue_title(fb_plain), "[Bug] API-2 erro 500")


class TestRunnerTimeoutUnified(unittest.TestCase):
    def test_serve_running_max_age_matches_config_default(self):
        default_min = config.DEFAULTS["runner"]["timeout_min"]
        expected_default = max(600, default_min * 60 + 300)
        self.assertEqual(serve._running_max_age({}), expected_default)
        self.assertEqual(serve._running_max_age(None), expected_default)
        self.assertEqual(serve._running_max_age({"timeout_min": "x"}), expected_default)
        self.assertEqual(serve._running_max_age({"timeout_min": None}), expected_default)
        self.assertEqual(serve._running_max_age({"timeout_min": 5}), 600)
        self.assertEqual(serve._running_max_age({"timeout_min": 45}), 3000)


class TestOpenerReap(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        vault = Path(self._td.name)
        (vault / "nota.md").write_text("oi", encoding="utf-8")
        self.inst = SimpleNamespace(vault=vault, cfg={"tui": {"open": {"md": "Cursor"}}})
        self.path = opener.resolve(self.inst, "nota.md")

    def test_spawn_reaps_child_in_daemon_thread(self):
        reaped = threading.Event()
        calls: list = []
        created_threads: list[threading.Thread] = []
        orig_thread = threading.Thread

        class _FakeProc:
            def wait(self):
                calls.append("wait")
                reaped.set()
                return 0

        def fake_popen(argv, **kw):
            calls.append(("popen", argv, kw))
            return _FakeProc()

        def spy_thread(*args, **kwargs):
            t = orig_thread(*args, **kwargs)
            created_threads.append(t)
            return t

        with mock.patch.object(opener.threading, "Thread", side_effect=spy_thread):
            opener._spawn(["open", str(self.path)], popen=fake_popen)

        self.assertTrue(reaped.wait(timeout=2.0), "thread de colheita não chamou proc.wait()")
        self.assertIn("wait", calls)
        self.assertTrue(created_threads and created_threads[0].daemon)

    def test_open_file_non_blocking_when_wait_blocks_forever(self):
        gate = threading.Event()
        self.addCleanup(gate.set)

        class _BlockingProc:
            def wait(self):
                gate.wait(timeout=5.0)
                return 0

        t0 = time.monotonic()
        with mock.patch.object(opener.sys, "platform", "darwin"), \
                mock.patch.object(opener.subprocess, "Popen", return_value=_BlockingProc()):
            app = opener.open_file(self.inst, "nota.md")
        elapsed = time.monotonic() - t0
        self.assertEqual(app, "Cursor")
        self.assertLess(elapsed, 1.0)

    def test_open_file_passes_exact_argv_and_devnull(self):
        seen: list = []

        class _DoneProc:
            def wait(self):
                return 0

        def fake_popen(argv, **kw):
            seen.append((argv, kw))
            return _DoneProc()

        with mock.patch.object(opener.sys, "platform", "darwin"), \
                mock.patch.object(opener.subprocess, "Popen", side_effect=fake_popen):
            opener.open_file(self.inst, "nota.md")

        self.assertEqual(len(seen), 1)
        argv, kw = seen[0]
        self.assertEqual(argv, opener.argv_for(self.inst.cfg, self.path, "darwin"))
        self.assertTrue(kw.get("start_new_session"))
        self.assertIs(kw.get("stdin"), subprocess.DEVNULL)
        self.assertIs(kw.get("stdout"), subprocess.DEVNULL)
        self.assertIs(kw.get("stderr"), subprocess.DEVNULL)


class TestProvidersHygiene(unittest.TestCase):
    def test_refuses_key_for_local_provider_and_empty_value(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            fake_secret = "sk-" + "demo" + "01"
            with self.assertRaises(util.BrainError) as cm_local:
                providers.set_slot(b, "embeddings", "local", key=fake_secret)
            self.assertEqual(cm_local.exception.code, 4)

            with self.assertRaises(util.BrainError) as cm_local_empty:
                providers.set_slot(b, "embeddings", "local", key="")
            self.assertEqual(cm_local_empty.exception.code, 4)

            for empty_val in ("", "   "):
                with self.assertRaises(util.BrainError) as cm_empty:
                    providers.set_slot(b, "embeddings", "fireworks", key=empty_val)
                self.assertEqual(cm_empty.exception.code, 4)

            with self.assertRaises(util.BrainError) as cm_slot_env:
                providers.slot_env("embeddings", "local", key=fake_secret)
            self.assertEqual(cm_slot_env.exception.code, 4)

            with self.assertRaises(util.BrainError) as cm_guard_name:
                providers._guard_env_updates({"": "val"})
            self.assertEqual(cm_guard_name.exception.code, 4)

            with self.assertRaises(util.BrainError) as cm_guard_val:
                providers._guard_env_updates({"HINDSIGHT_API_LLM_API_KEY": ""})
            self.assertEqual(cm_guard_val.exception.code, 4)

            self.assertFalse(b.inst.env_file.exists())

            res = providers.set_slot(b, "embeddings", "local")
            self.assertEqual(res["provider"], "local")
            raw_env = b.inst.env_file.read_text(encoding="utf-8")
            for ln in raw_env.splitlines():
                self.assertFalse(ln.startswith("="), ln)
                self.assertNotIn("API_KEY=", ln)

            # CLI sem --key (args.key = None) funciona em embeddings local
            args_ok = argparse.Namespace(
                pcmd="set", slot="embeddings", provider="local",
                model="", models="", base_url="", dimensions=0, candidates=0, key=None,
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                providers.cli(args_ok, b)
            self.assertIn("embeddings", buf.getvalue())

    def test_rebuild_notice_spelling(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp)
            (tmp / ".memory-state.json").write_text("{}", encoding="utf-8")
            fake_secret = "fw-" + "demo" + "01"
            args = argparse.Namespace(
                pcmd="set", slot="embeddings", provider="fireworks",
                model="", models="", base_url="", dimensions=0, candidates=0, key=fake_secret,
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                providers.cli(args, b)
            out = buf.getvalue()
            self.assertIn("vetores antigos", out)
            self.assertNotIn("antios", out)


class TestRubricAndIdsGuards(unittest.TestCase):
    def test_ice_rubric_describe_guards(self):
        for bad in (None, "", "   ", "abc", "٥", True, False, 3.5):
            with self.subTest(bad=bad):
                with self.assertRaises(util.BrainError) as cm:
                    ice_rubric.describe("impact", bad)
                self.assertEqual(cm.exception.code, 2)

        self.assertIn("Cosmético", ice_rubric.describe("impact", 1))
        self.assertIn("Muda um resultado", ice_rubric.describe("impact", "5"))
        self.assertEqual(ice_rubric.describe("impact", 9), "")
        self.assertEqual(ice_rubric.describe("impact", 0), "")

    def test_ids_number_guards(self):
        for bad in (None, "", "SEMNUMERO", "TASK-٠١٢"):
            with self.subTest(bad=bad):
                with self.assertRaises(util.BrainError) as cm:
                    ids.number(bad)
                self.assertEqual(cm.exception.code, 2)

        self.assertEqual(ids.number("TASK-0146"), 146)
        self.assertEqual(ids.number("PROJ-3"), 3)
        self.assertEqual(ids.number("PROJ-3.2"), 3)


class TestMemoryDecimalFormat(unittest.TestCase):
    def test_cost_detail_and_text_use_comma_decimal(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td), full_mem=True)
            month = util.now().strftime("%Y-%m")

            class _FakeHs:
                def __init__(self, payload):
                    self._payload = payload

                def llm_stats(self, _bank):
                    return self._payload

            c_used = memory.cost(b, _FakeHs({"requests": [{
                "operation": "retain",
                "model": "haiku",
                "created_at": f"{month}-05T10:00:00+00:00",
                "requests": 3,
                "input_tokens": 12500,
                "output_tokens": 3400,
                "cost_usd": 1.25,
            }]}))
            self.assertIn("US$ 1,25", c_used["detail"])
            txt = memory._cost_text(c_used)
            self.assertIn("12.500 in/3.400 out tokens · US$ 1,25", txt)

            c_zero = memory.cost(b, _FakeHs({"requests": []}))
            self.assertIn("US$ 0,00", c_zero["detail"])
            self.assertEqual(memory._fmt_dec_br(1234.5), "1.234,50")


if __name__ == "__main__":
    unittest.main()
