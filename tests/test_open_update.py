"""Testes da issue #107: proteção do `brain update` contra execução não assistida e commit inesperado."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, perms, serve, upstream, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _make_inst(root: Path, *, with_git_dir: bool = True) -> config.Instance:
    (root / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED/_ledger", "FRESH", "logs", "reports"):
        (root / "vault" / sub).mkdir(parents=True, exist_ok=True)
    if with_git_dir:
        (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "brainlib").mkdir(parents=True, exist_ok=True)
    (root / "brainlib" / "__init__.py").write_text('__version__ = "2.1.0"\n', encoding="utf-8")
    (root / "config" / "brain.toml").write_text(
        '[owner]\nid = "marina-demo"\nname = "Marina Demo"\n',
        encoding="utf-8",
    )
    (root / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    (root / "vault" / "PROCESSED" / "_ledger" / "events.jsonl").write_text("", encoding="utf-8")
    inst = config.load(root)
    Brain(inst).record_one({
        "type": "person.added",
        "id": "marina-demo",
        "by": "owner",
        "data": {"name": "Marina Demo", "relation": "dono"},
    })
    return inst


class _FakeGit:
    """Stub injetável para `_git` em `upstream.update`/`check_update` sem invocar git real."""

    def __init__(
        self,
        *,
        expected_sha: str = "a" * 40,
        post_pull_head: str | None = None,
        initial_head: str = "0" * 40,
        ahead: int = 0,
        behind: int = 1,
        is_ancestor: bool = True,
    ):
        self.expected_sha = expected_sha
        self.post_pull_head = expected_sha if post_pull_head is None else post_pull_head
        self.initial_head = initial_head
        self.ahead = ahead
        self.behind = behind
        self.is_ancestor = is_ancestor
        self.pulled = False
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        self.calls.append(args)
        cmd = ("git", "-C", str(root), *args)
        if args == ("remote",):
            return subprocess.CompletedProcess(cmd, 0, "origin\n", "")
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return subprocess.CompletedProcess(cmd, 0, "main\n", "")
        if args == ("ls-files",):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if args[:2] == ("ls-files", "--others"):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if args and args[0] == "fetch":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if args[:3] == ("rev-parse", "--verify", "--quiet"):
            return subprocess.CompletedProcess(cmd, 0, self.expected_sha + "\n", "")
        if args[:3] == ("rev-list", "--left-right", "--count"):
            return subprocess.CompletedProcess(cmd, 0, f"{self.ahead} {self.behind}\n", "")
        if args[:2] == ("diff", "--name-only"):
            return subprocess.CompletedProcess(cmd, 0, "brainlib/upstream.py\n", "")
        if args[:2] == ("log", "--format=%h %s"):
            return subprocess.CompletedProcess(cmd, 0, "abc1234 ajuste\n", "")
        if args == ("rev-parse", "origin/main"):
            return subprocess.CompletedProcess(cmd, 0, self.expected_sha + ("\n" if self.expected_sha else ""), "")
        if args and args[0] == "pull":
            self.pulled = True
            return subprocess.CompletedProcess(cmd, 0, "Updating...\n", "")
        if args == ("rev-parse", "HEAD"):
            head = self.post_pull_head if self.pulled else self.initial_head
            return subprocess.CompletedProcess(cmd, 0, head + ("\n" if head else ""), "")
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(cmd, 0 if self.is_ancestor else 1, "", "")
        if args[:2] == ("rev-parse", "--git-path"):
            return subprocess.CompletedProcess(cmd, 0, f".git/{args[2]}\n", "")
        if args and args[0] == "show":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"chamada git inesperada no stub: {args!r}")


class UpdateNightlyAndAgentGateTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = {k: os.environ.get(k) for k in ("BRAIN_NIGHTLY", "BRAIN_AGENT")}
        os.environ.pop("BRAIN_NIGHTLY", None)
        os.environ.pop("BRAIN_AGENT", None)
        self._td = tempfile.TemporaryDirectory()
        self.inst = _make_inst(Path(self._td.name) / "inst")

    def tearDown(self):
        for k, v in self._env_backup.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._td.cleanup()

    def test_nightly_refuses_apply_with_code_4(self):
        for val in ("1", "true", "yes", "on"):
            with self.subTest(BRAIN_NIGHTLY=val), mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": val}):
                git = _FakeGit()
                doctor_calls: list[list[str]] = []

                def fake_run(argv, **_kw):
                    doctor_calls.append(list(argv))
                    return subprocess.CompletedProcess(argv, 0, "ok\n", "")

                with self.assertRaises(util.BrainError) as cm:
                    upstream.update(self.inst, git=git, run=fake_run)
                self.assertEqual(cm.exception.code, 4)
                self.assertIn("checar", str(cm.exception).lower())
                self.assertEqual(git.calls, [])
                self.assertEqual(doctor_calls, [])
                self.assertFalse((self.inst.root / ".git" / "hooks" / "pre-push").exists())

    def test_agent_refuses_apply_with_code_4(self):
        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "1"}):
            git = _FakeGit()
            doctor_calls: list[list[str]] = []

            def fake_run(argv, **_kw):
                doctor_calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "ok\n", "")

            with self.assertRaises(util.BrainError) as cm:
                upstream.update(self.inst, git=git, run=fake_run)
            self.assertEqual(cm.exception.code, 4)
            self.assertIn("agente", str(cm.exception).lower())
            self.assertEqual(git.calls, [])
            self.assertEqual(doctor_calls, [])
            self.assertFalse((self.inst.root / ".git" / "hooks" / "pre-push").exists())

    def test_cli_update_refuses_nightly_and_agent_without_syncing_perms(self):
        args = argparse.Namespace(check=False, rebase=False, remote=None, branch=None, json=False)
        for env in ({"BRAIN_NIGHTLY": "1"}, {"BRAIN_AGENT": "1"}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env), \
                 mock.patch.object(config, "load", return_value=self.inst), \
                 mock.patch.object(perms, "try_sync") as sync_mock:
                with self.assertRaises(util.BrainError) as cm:
                    upstream.cli_update(args, None)
                self.assertEqual(cm.exception.code, 4)
                sync_mock.assert_not_called()

    def test_check_still_works_in_nightly_and_agent(self):
        for env in ({"BRAIN_NIGHTLY": "1"}, {"BRAIN_AGENT": "1"}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env):
                git = _FakeGit(behind=2)
                doctor_calls: list[list[str]] = []

                def fake_run(argv, **_kw):
                    doctor_calls.append(list(argv))
                    return subprocess.CompletedProcess(argv, 0, "ok\n", "")

                res = upstream.update(self.inst, check=True, git=git, run=fake_run)
                self.assertTrue(res["checked_only"])
                self.assertFalse(res["updated"])
                self.assertEqual(res["behind"], 2)
                self.assertFalse(git.pulled)
                self.assertEqual(doctor_calls, [])
                self.assertFalse((self.inst.root / ".git" / "hooks" / "pre-push").exists())

    def test_nightly_check_update_cache_step_still_works(self):
        with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
            git = _FakeGit(behind=1)
            c = upstream.check_update(self.inst, force=True, git=git)
            self.assertEqual(c["behind"], 1)
            self.assertEqual(c["error"], "")
            self.assertFalse(git.pulled)


class PostPullShaCheckTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = {k: os.environ.get(k) for k in ("BRAIN_NIGHTLY", "BRAIN_AGENT")}
        os.environ.pop("BRAIN_NIGHTLY", None)
        os.environ.pop("BRAIN_AGENT", None)
        self._td = tempfile.TemporaryDirectory()
        self.inst = _make_inst(Path(self._td.name) / "inst")

    def tearDown(self):
        for k, v in self._env_backup.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._td.cleanup()

    def test_refuses_doctor_and_hook_when_head_differs_from_expected_sha(self):
        git = _FakeGit(expected_sha="1" * 40, post_pull_head="2" * 40)
        doctor_calls: list[list[str]] = []

        def fake_run(argv, **_kw):
            doctor_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")

        with self.assertRaises(util.BrainError) as cm:
            upstream.update(self.inst, git=git, run=fake_run)
        self.assertEqual(cm.exception.code, 4)
        self.assertTrue(git.pulled)
        self.assertEqual(doctor_calls, [])
        self.assertFalse((self.inst.root / ".git" / "hooks" / "pre-push").exists())

    def test_refuses_doctor_and_hook_when_expected_sha_is_empty(self):
        git = _FakeGit(expected_sha="", post_pull_head="2" * 40)
        doctor_calls: list[list[str]] = []

        def fake_run(argv, **_kw):
            doctor_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")

        with self.assertRaises(util.BrainError) as cm:
            upstream.update(self.inst, git=git, run=fake_run)
        self.assertEqual(cm.exception.code, 4)
        self.assertFalse(git.pulled)
        self.assertEqual(doctor_calls, [])
        self.assertFalse((self.inst.root / ".git" / "hooks" / "pre-push").exists())

    def test_refuses_doctor_and_hook_when_rebase_misses_expected_sha(self):
        git = _FakeGit(expected_sha="1" * 40, post_pull_head="3" * 40, ahead=1, behind=1, is_ancestor=False)
        doctor_calls: list[list[str]] = []

        def fake_run(argv, **_kw):
            doctor_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")

        with self.assertRaises(util.BrainError) as cm:
            upstream.update(self.inst, rebase=True, git=git, run=fake_run)
        self.assertEqual(cm.exception.code, 4)
        self.assertTrue(git.pulled)
        self.assertEqual(doctor_calls, [])
        self.assertFalse((self.inst.root / ".git" / "hooks" / "pre-push").exists())

    def test_runs_doctor_and_hook_when_head_matches_expected_sha(self):
        sha = "a1b2c3d4" * 5
        git = _FakeGit(expected_sha=sha, post_pull_head=sha)
        doctor_calls: list[list[str]] = []

        def fake_run(argv, **_kw):
            doctor_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "✓ tudo certo\n", "")

        res = upstream.update(self.inst, git=git, run=fake_run)
        self.assertTrue(res["updated"])
        self.assertTrue(res["doctor_ok"])
        self.assertEqual(res["hook"], "instalado")
        self.assertEqual(len(doctor_calls), 1)
        self.assertEqual(doctor_calls[0][1:], [str(self.inst.root / "brain"), "doctor"])
        self.assertTrue((self.inst.root / ".git" / "hooks" / "pre-push").exists())


class ServeUpdateNightlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._prev_handler_state = serve._Handler.state
        cls.td = tempfile.TemporaryDirectory()
        cls.inst = _make_inst(Path(cls.td.name) / "inst", with_git_dir=False)
        cls.token = "tok-open-update-123456"
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
        serve._Handler.state = cls._prev_handler_state
        try:
            serve.live_url_file(cls.inst).unlink()
        except FileNotFoundError:
            pass
        cls.td.cleanup()

    def setUp(self):
        serve._Handler.state = self.state
        with self.state.update_lock:
            self.state.update_jobs.clear()
            self.state.update_active = None
        self.state.update_cmd_fn = serve._default_update_cmd
        self.state.restart_fn = lambda: None

    def _req(self, path: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Host", f"127.0.0.1:{self.port}")
        r.add_header("X-Brain-Token", self.token)
        if body is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_post_update_returns_403_when_nightly(self):
        called = False
        restarted = False

        def fake_cmd(_inst, _on_line):
            nonlocal called
            called = True
            return 0

        def fake_restart():
            nonlocal restarted
            restarted = True

        self.state.update_cmd_fn = fake_cmd
        self.state.restart_fn = fake_restart

        for val in ("1", "true"):
            with self.subTest(BRAIN_NIGHTLY=val), mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": val}):
                code, payload = self._req("/api/update", method="POST", body={})
                self.assertEqual(code, 403)
                self.assertFalse(payload["ok"])
                self.assertIn("noturno", payload["error"])
        self.assertFalse(called)
        self.assertFalse(restarted)

    def test_post_update_owner_present_still_applies(self):
        ran = threading.Event()

        def fake_cmd(_inst, on_line):
            on_line("✓ atualizado")
            ran.set()
            return 0

        self.state.update_cmd_fn = fake_cmd
        self.state.restart_fn = lambda: None

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAIN_NIGHTLY", None)
            code, start_res = self._req("/api/update", method="POST", body={})
            self.assertEqual(code, 200)
            self.assertTrue(start_res["ok"])
            self.assertTrue(ran.wait(timeout=3.0))
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                jc, j = self._req(f"/api/update/job/{start_res['job']}")
                self.assertEqual(jc, 200)
                if j["status"] != "running":
                    self.assertEqual(j["status"], "done")
                    return
                time.sleep(0.02)
            self.fail("job /api/update não terminou a tempo")


if __name__ == "__main__":
    unittest.main()
