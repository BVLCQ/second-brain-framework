"""Testes de engenharia do onboarding e setup (#75, #77, #78, #81)."""
from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import ask, config, launcher, onboard, render, setup, util  # noqa: E402
from brainlib.core import Brain                                           # noqa: E402

TEMPLATE_PROFILE = "# PROFILE\n\n## Papel\n\n(a preencher no /init)\n"


def _inst(tmp: Path) -> config.Instance:
    for d in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH",
              "vault/reports"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dono do cérebro"\n\n[work]\nstart = "09:00"\nend = "18:00"\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    (tmp / "vault" / "PROFILE" / "profile.md").write_text(TEMPLATE_PROFILE, encoding="utf-8")
    return config.load(tmp)


class TestFinishOrder(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.b = Brain(_inst(self.tmp))

    def test_ledger_failure_keeps_needed_true(self):
        with mock.patch.object(self.b, "record_one", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(util.BrainError) as cm:
                onboard.finish(self.b)
        self.assertEqual(cm.exception.code, 3)
        pg = onboard.progress(self.b.inst)
        self.assertNotIn("finished", pg)
        self.assertNotIn("pronto", pg.get("done", []))
        self.assertTrue(onboard.needed(self.b))

    def test_render_failure_keeps_needed_true(self):
        with mock.patch.object(render, "render_all", side_effect=OSError("disco cheio")):
            with self.assertRaises(util.BrainError) as cm:
                onboard.finish(self.b)
        self.assertEqual(cm.exception.code, 3)
        pg = onboard.progress(self.b.inst)
        self.assertNotIn("finished", pg)
        self.assertNotIn("pronto", pg.get("done", []))
        self.assertEqual([e for e in self.b.read_events() if e["type"] == "onboarding.finished"], [])
        self.assertTrue(onboard.needed(self.b))

    def test_success_marks_finished_after_render(self):
        onboard.save_about(self.b, {"name": "Marina Demo"})
        (self.tmp / "vault" / "PROFILE" / "profile.md").write_text("# PROFILE\n\n## Papel\n\nPadeira.\n",
                                                                   encoding="utf-8")
        order: list[str] = []
        orig_record = self.b.record_one
        orig_ask = ask.add
        orig_render = render.render_all
        orig_save = onboard._save_progress

        def trace_record(ev):
            order.append(f"ledger:{ev['type']}")
            return orig_record(ev)

        def trace_ask(*args, **kwargs):
            order.append("ask")
            return orig_ask(*args, **kwargs)

        def trace_render(*args, **kwargs):
            order.append("render")
            return orig_render(*args, **kwargs)

        def trace_save(inst, **changes):
            for k in changes:
                order.append(f"progress:{k}")
            return orig_save(inst, **changes)

        with mock.patch.object(self.b, "record_one", side_effect=trace_record), \
                mock.patch.object(ask, "add", side_effect=trace_ask), \
                mock.patch.object(render, "render_all", side_effect=trace_render), \
                mock.patch.object(onboard, "_save_progress", side_effect=trace_save):
            res = onboard.finish(self.b)

        self.assertTrue(res["ok"])
        self.assertFalse(onboard.needed(self.b))
        self.assertEqual(order[-1], "progress:finished")
        self.assertLess(order.index("ask"), order.index("render"))
        self.assertLess(order.index("render"), order.index("ledger:onboarding.finished"))
        self.assertLess(order.index("ledger:onboarding.finished"), order.index("progress:finished"))


class TestMemoryLater(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.b = Brain(_inst(self.tmp))

    def test_creates_task_recording_intended_mode(self):
        onboard.save_about(self.b, {"name": "Marina Demo"})
        r_full = onboard.apply_memory(self.b, {"mode": "full", "later": True})
        self.assertTrue(r_full["later"])
        self.assertEqual(r_full["mode"], "full")
        self.assertTrue(r_full["id"].startswith("TASK-"))
        t_full = self.b.state.actions[r_full["id"]]
        self.assertEqual(t_full.owner, self.b.owner)
        self.assertEqual(t_full.list, "mine")
        self.assertIn("full", t_full.title)
        self.assertEqual(onboard.progress(self.b.inst)["memory_later"], "full")
        self.assertIn("memoria", onboard.progress(self.b.inst).get("done", []))

        r_lite = onboard.apply_memory(self.b, {"mode": "lite", "later": True})
        self.assertTrue(r_lite["later"])
        self.assertEqual(r_lite["mode"], "embed")
        self.assertTrue(r_lite["id"].startswith("TASK-"))
        t_lite = self.b.state.actions[r_lite["id"]]
        self.assertEqual(t_lite.owner, self.b.owner)
        self.assertEqual(t_lite.list, "mine")
        self.assertIn("embed", t_lite.title)
        self.assertEqual(onboard.progress(self.b.inst)["memory_later"], "lite")

    def test_requires_owner_and_blocks_nightly(self):
        with self.assertRaises(util.BrainError) as cm_owner:
            onboard.apply_memory(self.b, {"mode": "embed", "later": True})
        self.assertEqual(cm_owner.exception.code, 4)

        onboard.save_about(self.b, {"name": "Marina Demo"})
        with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
            with self.assertRaises(util.BrainError) as cm_nightly:
                onboard.apply_memory(self.b, {"mode": "embed", "later": True})
        self.assertEqual(cm_nightly.exception.code, 4)


class TestJobsPurgeOnRead(unittest.TestCase):
    def test_job_read_evicts_expired_entries(self):
        expired = onboard._Job("expired")
        expired.started = time.time() - (onboard.JOB_TTL_S + 400)
        fresh = onboard._Job("fresh")
        with onboard._JOBS_LOCK:
            onboard._JOBS[expired.id] = expired
            onboard._JOBS[fresh.id] = fresh
        try:
            self.assertIsNone(onboard.job(expired.id))
            with onboard._JOBS_LOCK:
                self.assertNotIn(expired.id, onboard._JOBS)
            got = onboard.job(fresh.id)
            self.assertIsNotNone(got)
            self.assertEqual(got["id"], fresh.id)
        finally:
            with onboard._JOBS_LOCK:
                onboard._JOBS.pop(expired.id, None)
                onboard._JOBS.pop(fresh.id, None)


class TestAtomicUpload(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.b = Brain(_inst(self.tmp))

    def test_save_upload_uses_atomic_replace_and_cleans_on_error(self):
        calls: list[tuple[Path, Path]] = []
        orig_replace = os.replace

        def spy_replace(src, dst):
            calls.append((Path(src), Path(dst)))
            return orig_replace(src, dst)

        with mock.patch("brainlib.onboard.os.replace", side_effect=spy_replace):
            res = onboard.save_upload(self.b, "plano.txt", b"conteudo")

        inbox_calls = [(s, d) for s, d in calls if d.parent.resolve() == self.b.inst.inbox.resolve()]
        self.assertEqual(len(inbox_calls), 1)
        src, dst = inbox_calls[0]
        self.assertEqual(src.parent.resolve(), self.b.inst.inbox.resolve())
        self.assertTrue(src.name.startswith(".upload-"))
        self.assertTrue(src.name.endswith(".tmp"))
        self.assertEqual(dst, self.b.inst.inbox / "plano.txt")
        self.assertEqual(res["name"], "plano.txt")
        self.assertEqual(list(self.b.inst.inbox.glob(".upload-*.tmp")), [])

        with mock.patch("brainlib.onboard.os.replace", side_effect=OSError("falha replace")):
            with self.assertRaises(OSError):
                onboard.save_upload(self.b, "segundo.txt", b"conteudo 2")

        self.assertFalse((self.b.inst.inbox / "segundo.txt").exists())
        self.assertEqual(list(self.b.inst.inbox.glob(".upload-*.tmp")), [])


class TestIconStepByOwner(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.b = Brain(_inst(self.tmp))

    def test_custom_named_app_reports_done(self):
        with mock.patch.object(launcher, "_platform", return_value="darwin"), \
                mock.patch.object(launcher, "find_for_instance",
                                  return_value=[Path("/Applications/Meu Brain.app")]) as find_fn, \
                mock.patch.object(launcher, "pin_status", return_value=True) as pin_fn, \
                mock.patch.object(launcher, "docked_other", return_value=None):
            res = onboard.maquina_state(self.b)

        find_fn.assert_called_once_with(self.b.inst.root, platform="darwin")
        pin_fn.assert_called_once_with(root=self.b.inst.root, platform="darwin")
        self.assertEqual(res["icon"], "done")
        self.assertEqual(res["icon_hint"], "")

    def test_other_instance_docked_stays_pending_with_hint(self):
        with mock.patch.object(launcher, "_platform", return_value="darwin"), \
                mock.patch.object(launcher, "find_for_instance",
                                  return_value=[Path("/Applications/Meu Brain.app")]), \
                mock.patch.object(launcher, "pin_status", return_value=False), \
                mock.patch.object(launcher, "docked_other", return_value="/caminho/da/outra") as other_fn:
            res = onboard.maquina_state(self.b)

        other_fn.assert_called_once_with(self.b.inst.root, platform="darwin")
        self.assertEqual(res["icon"], "pending")
        self.assertIn("/caminho/da/outra", res["icon_hint"])


class TestEnvDuplicates(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.inst = _inst(self.tmp)

    def test_set_env_collapses_duplicate_keys_last_wins(self):
        self.inst.env_file.write_text("# comentario\nFOO=um\nBAR=ok\nFOO=um\n", encoding="utf-8")
        changed = setup.set_env(self.inst, {"FOO": "novo"})
        self.assertEqual(changed, ["FOO"])
        self.assertEqual(config.load_env(self.inst), {"FOO": "novo", "BAR": "ok"})
        text = self.inst.env_file.read_text(encoding="utf-8")
        self.assertEqual(text.count("FOO="), 1)
        self.assertIn("# comentario", text)
        self.assertIn("BAR=ok", text)
        self.assertEqual(stat.S_IMODE(self.inst.env_file.stat().st_mode), 0o600)

        self.inst.env_file.write_text("FOO=um\nFOO=dois\n", encoding="utf-8")
        changed2 = setup.set_env(self.inst, {"FOO": "novo"})
        self.assertEqual(changed2, ["FOO"])
        self.assertEqual(config.load_env(self.inst), {"FOO": "novo"})
        self.assertEqual(self.inst.env_file.read_text(encoding="utf-8").count("FOO="), 1)

    def test_missing_env_file_returns_empty_dict(self):
        self.assertFalse(self.inst.env_file.exists())
        self.assertEqual(config.load_env(self.inst), {})


class TestOAuthPortTaken(unittest.TestCase):
    def test_eaddrinuse_raises_brain_error_without_traceback(self):
        with mock.patch("brainlib.setup.HTTPServer",
                        side_effect=OSError(errno.EADDRINUSE, "Address already in use")):
            with self.assertRaises(util.BrainError) as cm:
                setup.google_refresh_token("cid", "csec", open_browser=False)
        self.assertEqual(cm.exception.code, 3)
        self.assertIn(str(setup.OAUTH_PORT), str(cm.exception))
        self.assertIn("em uso", str(cm.exception))

    def test_other_bind_oserror_raises_brain_error(self):
        with mock.patch("brainlib.setup.HTTPServer",
                        side_effect=OSError(errno.EACCES, "Permission denied")):
            with self.assertRaises(util.BrainError) as cm:
                setup.google_refresh_token("cid", "csec", open_browser=False)
        self.assertEqual(cm.exception.code, 3)


if __name__ == "__main__":
    unittest.main()
