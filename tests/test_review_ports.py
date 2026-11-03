"""Revisão das portas e do caminho de volta ao framework — gates, varredura do push, caminhos (stdlib, sem rede)."""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import backup, config, demo, focus, mcp_server, outbox, rawsort, runner, snapshot, upstream, util, video  # noqa: E402
from brainlib.gcal import GoogleCalendar  # noqa: E402
from test_brain import _brain  # noqa: E402


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self._night = os.environ.pop("BRAIN_NIGHTLY", None)
        self.addCleanup(lambda: os.environ.__setitem__("BRAIN_NIGHTLY", self._night) if self._night
                        else os.environ.pop("BRAIN_NIGHTLY", None))


# ── outbox ──────────────────────────────────────────────────────────────────
class OutboxGateTests(_Base):
    def _forged_draft(self, b, to="chefe"):
        # rascunho que entrou pelo `brain add` (sem passar por outbox.draft e pela lista [outbound].allow)
        return b.record_one({"type": "message.drafted", "by": "agent", "prov": "sistema", "source": "chat",
                             "data": {"to": to, "text": "oi"}})["id"]

    def test_recipient_outside_allow_cannot_be_approved_or_sent(self):
        b = _brain(self.tmp)
        b.record_one({"type": "person.added", "id": "chefe", "by": "owner", "data": {"name": "Chefe"}})
        mid = self._forged_draft(b)
        with self.assertRaises(util.BrainError) as cm:
            outbox.approve(b, mid, "ok")
        self.assertIn("allow", str(cm.exception))

    def test_recipient_removed_from_allow_after_approval_blocks_send(self):
        b = _brain(self.tmp)
        mid = outbox.draft(b, "marina-demo", "oi", None, None)["id"]
        outbox.approve(b, mid, "enviar 1")
        b.inst.cfg["outbound"]["allow"] = ["#time"]
        with self.assertRaises(util.BrainError):
            outbox.sent(b, mid, "https://x")
        self.assertEqual(b.state.messages[mid].status, "aprovada")

    def test_approval_recorded_after_cancel_does_not_reopen_the_port(self):
        b = _brain(self.tmp)
        mid = outbox.draft(b, "marina-demo", "oi", None, None)["id"]
        b.record_one({"type": "message.cancelled", "id": mid, "by": "owner", "data": {"reason": "x"}})
        b.record_one({"type": "message.approved", "id": mid, "by": "owner",
                      "data": {"quote": "ok", "text_sha": b.state.messages[mid].text_sha}})
        with self.assertRaises(util.BrainError):
            outbox.sent(b, mid, "https://x")

    def test_normal_flow_still_sends(self):
        b = _brain(self.tmp)
        mid = outbox.draft(b, "marina-demo", "oi", None, None)["id"]
        outbox.approve(b, mid, "enviar 1")
        outbox.sent(b, mid, "https://x")
        self.assertEqual(b.state.messages[mid].status, "enviada")


# ── foco / calendário ───────────────────────────────────────────────────────
class _FakeCal:
    def __init__(self, fail_after: int | None = None):
        self.calls, self.fail_after = [], fail_after

    def list_events(self, *_):
        self.calls.append("list")
        return []

    def insert_focus(self, b, *_):
        if self.fail_after is not None and sum(c == "insert" for c in self.calls) >= self.fail_after:
            raise util.BrainError("Google Calendar POST /events → 500: boom", code=2)
        self.calls.append("insert")
        return {"id": f"ev{len(self.calls)}", "htmlLink": "http://x"}

    def delete_guarded(self, *_):
        self.calls.append("delete")
        return True


class FocusPortTests(_Base):
    def _approved_plan(self, b, n_actions=1):
        for i in range(n_actions):
            b.record_one({"type": "action.opened", "by": "owner",
                          "data": {"title": f"Ler {i}", "owner": "eu", "due": "2026-10-16", "effort_min": 60}})
        body = focus.build_plan(b, [])
        fid = b.record_one({"type": "focus.planned", "by": "system", "source": "x",
                            "data": {"plan_file": "FRESH/focus.md", **body}})["id"]
        b.record_one({"type": "focus.approved", "id": fid, "by": "owner", "data": {"quote": "ok", "sha": body["sha"]}})
        return fid

    def test_nightly_apply_google_touches_nothing_in_calendar(self):
        b = _brain(self.tmp)
        fid = self._approved_plan(b)
        cal = _FakeCal()
        os.environ["BRAIN_NIGHTLY"] = "1"
        with self.assertRaises(util.BrainError):
            focus.apply(b, fid, "google", cal=cal)
        self.assertEqual(cal.calls, [])

    def test_partial_failure_records_created_events(self):
        b = _brain(self.tmp)
        fid = self._approved_plan(b, n_actions=2)
        self.assertGreaterEqual(len(b.state.focus_plans[fid].blocks), 2)
        with self.assertRaises(util.BrainError):
            focus.apply(b, fid, "google", cal=_FakeCal(fail_after=1))
        applied = b.state.focus_plans[fid].applied
        self.assertEqual(len(applied), 1)
        self.assertTrue(applied[0]["event_id"])

    def test_delete_guarded_without_id_never_calls_api(self):
        calls = []
        cal = GoogleCalendar(config.load(_brain(self.tmp).inst.root), http=lambda *a: calls.append(a) or (200, {}),
                             token="t")
        self.assertFalse(cal.delete_guarded("", "TASK-0001"))
        self.assertEqual(calls, [])

    def test_event_id_slashes_are_escaped(self):
        urls = []

        def http(method, url, body, headers):
            urls.append(url)
            return 200, {"extendedProperties": {"private": {"brain_focus": "1", "brain_action": "TASK-0001"}}}

        cal = GoogleCalendar(config.load(_brain(self.tmp).inst.root), http=http, token="t")
        cal.delete_guarded("../../users/me/x", "TASK-0001")
        self.assertTrue(all("/events/..%2F..%2Fusers%2Fme%2Fx" in u for u in urls), urls)


# ── backup ──────────────────────────────────────────────────────────────────
class BackupPortTests(_Base):
    def test_rotation_only_deletes_own_zips(self):
        b = _brain(self.tmp)
        b.inst.cfg["backup"]["keep"] = 1
        listing = [{"id": "new", "name": "brain-backup-20261009-1000.zip"},
                   {"id": "doc", "name": "brain-backup-notas.docx"},
                   {"id": "mine", "name": "meu-brain-backup-20260101-0000.zip"},
                   {"id": "old", "name": "brain-backup-20261002-1000.zip"}]
        deleted = []

        def drive(token, method, url, body=None, headers=None):
            if method == "GET":
                self.assertNotIn(" ", url)          # urllib recusa espaço na URL (InvalidURL): a rotação nunca rodava
                return 200, {}, json.dumps({"files": listing}).encode()
            deleted.append(url.rsplit("/", 1)[-1])
            return 204, {}, b""

        with mock.patch.object(backup, "access_token", return_value="t"), \
                mock.patch.object(backup.config, "load_env", return_value={"GOOGLE_BACKUP_FOLDER_ID": "abcDEF123_-"}), \
                mock.patch.object(backup, "upload", return_value="new"), mock.patch.object(backup, "_drive", drive):
            backup.run(b)
        self.assertEqual(deleted, ["old"])

    def test_no_rotation_without_upload_confirmation(self):
        b = _brain(self.tmp)
        b.inst.cfg["backup"]["keep"] = 1
        drive = mock.Mock(return_value=(200, {}, b'{"files": []}'))
        with mock.patch.object(backup, "access_token", return_value="t"), \
                mock.patch.object(backup.config, "load_env", return_value={"GOOGLE_BACKUP_FOLDER_ID": "abcDEF123_-"}), \
                mock.patch.object(backup, "upload", return_value=""), mock.patch.object(backup, "_drive", drive):
            with self.assertRaises(util.BrainError):
                backup.run(b)
        drive.assert_not_called()

    def test_folder_id_cannot_change_the_drive_query(self):
        with self.assertRaises(util.BrainError):
            backup._list("t", "x' or name contains '")

    def test_local_keep_zero_keeps_new_zip_and_ignores_foreign_files(self):
        b = _brain(self.tmp)
        b.inst.cfg["backup"]["keep"] = 0
        dest = self.tmp / "bk"
        dest.mkdir()
        (dest / "brain-backup-notas.zip").write_text("do dono")
        backup.run(b, str(dest))
        names = sorted(p.name for p in dest.iterdir())
        self.assertIn("brain-backup-notas.zip", names)
        self.assertEqual(len([n for n in names if backup._ours(n)]), 1)

    def test_symlink_out_of_vault_is_not_zipped(self):
        b = _brain(self.tmp)
        secret = self.tmp / "segredo.txt"
        secret.write_text("chave")
        os.symlink(secret, b.inst.vault / "PROFILE" / "link.txt")
        zpath, _ = backup.make_zip(b, self.tmp)
        with zipfile.ZipFile(zpath) as z:
            self.assertFalse(any(n.endswith("link.txt") for n in z.namelist()))


# ── snapshot / RAW / MCP ────────────────────────────────────────────────────
class PathTests(_Base):
    def test_snapshot_rejects_ext_with_path(self):
        b = _brain(self.tmp)
        for ext in ("md/../../x", "../x", "", "a b"):
            with self.assertRaises(util.BrainError):
                snapshot.take(b, "slack-time", "conteúdo", ext=ext)
        self.assertTrue(snapshot.take(b, "slack-time", "conteúdo", ext="json")["changed"])

    def test_snapshot_does_not_follow_planted_symlink(self):
        b = _brain(self.tmp)
        target = self.tmp / "fora.txt"
        stamp = util.now().strftime("%Y-%m-%dT%H%M%S")
        os.symlink(target, b.inst.inbox / f"slack-slack-time-{stamp}.md")    # dangling: exists() == False
        res = snapshot.take(b, "slack-time", "conteúdo")
        self.assertFalse(target.exists())
        self.assertTrue(res["path"].name.endswith("-2.md"))

    def test_raw_resolve_rejects_parent_dirs(self):
        b = _brain(self.tmp)
        (self.tmp / "fora.md").write_text("x")
        self.assertIsNone(rawsort.resolve(b.inst, "../fora.md"))
        self.assertIsNone(rawsort.resolve(b.inst, "RAW/../../fora.md"))

    def test_mcp_survives_non_object_requests(self):
        for bad in (5, "x", None, []):
            resp = mcp_server.handle(bad)
            self.assertEqual(resp["error"]["code"], -32600)
        resp = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "brain_read", "arguments": ["a"]}})
        self.assertTrue(resp["result"]["isError"])


# ── demo / vídeo / agendamento ──────────────────────────────────────────────
class MiscTests(_Base):
    def test_demo_refuses_a_real_instance(self):
        b = _brain(self.tmp)
        before = (b.inst.vault / "PLANNING" / "goals.md").read_text(encoding="utf-8")
        with self.assertRaises(util.BrainError):
            demo.build(self.tmp)
        self.assertEqual((b.inst.vault / "PLANNING" / "goals.md").read_text(encoding="utf-8"), before)

    def test_demo_can_be_rebuilt_in_its_own_folder(self):
        d = self.tmp / "demo"
        demo.build(d)
        demo.build(d)
        self.assertIn(demo.DEMO_OWNER_LINE, (d / "config" / "brain.toml").read_text(encoding="utf-8"))

    def test_frames_rejects_non_positive_step(self):
        f = self.tmp / "v.mp4"
        f.write_bytes(b"\0")
        with mock.patch.object(video, "swift_tool", side_effect=AssertionError("não devia compilar")):
            for every in (0, -5):
                with self.assertRaises(util.BrainError):
                    video.frames(f, every=every)

    def test_schedule_time_is_validated_before_touching_the_scheduler(self):
        args = argparse.Namespace(action="install", time="25:00")
        with mock.patch.object(runner, "_use_launchd", side_effect=AssertionError("não devia chegar aqui")):
            with self.assertRaises(util.BrainError):
                runner.schedule_cli(args, None)
        runner._check_time("05:00")


class IdleUnloadTests(_Base):
    def test_truncated_state_entry_does_not_break_every_run(self):
        mod = _load_script("idle_unload_t", ROOT / "services" / "idle_unload.py")
        state = self.tmp / "idle.json"
        state.write_text(json.dumps({"models": {"m1": {}, "m2": "lixo"}}))
        unloaded = []
        with mock.patch.object(mod, "loaded_models", return_value=[{"identifier": "m1", "status": "idle"}]), \
                mock.patch.object(mod, "hindsight_busy", return_value={}), \
                mock.patch.object(mod, "memory_level", return_value=80), \
                mock.patch.object(mod.subprocess, "run", side_effect=lambda *a, **k: unloaded.append(a) or
                                  subprocess.CompletedProcess(a, 0, "", "")):
            self.assertEqual(mod.main(["x", str(state)]), 0)
        self.assertIn("m1", json.loads(state.read_text())["models"])


class GoogleAuthStateTests(_Base):
    def test_callback_without_matching_state_is_ignored(self):
        from brainlib import setup as setup_mod          # fluxo absorvido do script (que agora é casca)
        h = setup_mod._OAuthHandler
        h.code, h.denied, h.expected_state = None, None, "s3cr3t"
        server = HTTPServer(("127.0.0.1", 0), h)
        self.addCleanup(server.server_close)
        port = server.server_address[1]
        t = threading.Thread(target=setup_mod._pump, args=(server, 5), daemon=True)
        t.start()
        for q in ("code=ATACANTE", "code=ATACANTE&state=errado", "x=1"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/?{q}", timeout=5)
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 400)
        self.assertIsNone(h.code)
        urllib.request.urlopen(f"http://127.0.0.1:{port}/?code=BOM&state=s3cr3t", timeout=5).read()
        t.join(5)
        self.assertEqual(h.code, "BOM")


# ── upstream: o hook pre-push ───────────────────────────────────────────────
class PrePushTests(_Base):
    def setUp(self):
        super().setUp()
        self._env = {k: os.environ.get(k) for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                                                    "GIT_COMMITTER_EMAIL")}
        os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org",
                          GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in self._env.items()])
        self.remote, self.b = self.tmp / "remote.git", self.tmp / "b"
        self._git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self._git(self.tmp, "clone", "-q", str(self.remote), str(self.b))
        (self.b / "brainlib").mkdir()
        (self.b / "brainlib" / "__init__.py").write_text('__version__ = "1"\n', encoding="utf-8")
        (self.b / ".gitignore").write_text("/vault/\nconfig/brain.toml\n/brain\n", encoding="utf-8")
        self._commit("base")
        self._git(self.b, "push", "-q", "origin", "HEAD:main")
        (self.b / "config").mkdir()
        (self.b / "config" / "brain.toml").write_text('[owner]\nid = "dona"\nname = "Fulana Quiteria"\n', encoding="utf-8")
        (self.b / "vault" / "PROFILE").mkdir(parents=True)
        (self.b / "brain").write_text(f"#!/bin/sh\nBRAIN_HOME={self.b} exec {sys.executable} {ROOT / 'brain'} \"$@\"\n",
                                      encoding="utf-8")
        (self.b / "brain").chmod(0o755)
        self.inst = config.load(self.b)
        self.assertEqual(upstream.hook(self.inst, "install"), "instalado")

    @staticmethod
    def _git(cwd, *args, check=True):
        return subprocess.run(["git", "-C", str(cwd), *args], check=check, capture_output=True, text=True)

    def _commit(self, msg):
        self._git(self.b, "add", "-A")
        self._git(self.b, "commit", "-q", "-m", msg)

    def _push(self, *refspec):
        return self._git(self.b, "push", "origin", *refspec, check=False)

    def assertBlocked(self, r):
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertIn("push bloqueado", r.stderr)

    def test_leak_on_branch_other_than_head_is_blocked(self):
        self._git(self.b, "checkout", "-qb", "feat")
        (self.b / "doc.md").write_text("Fulana Quiteria\n", encoding="utf-8")
        self._commit("x")
        self._git(self.b, "checkout", "-q", "main")
        self.assertBlocked(self._push("feat"))

    def test_detached_head_push_is_scanned_not_waved_through(self):
        (self.b / "doc.md").write_text("Fulana Quiteria\n", encoding="utf-8")
        self._commit("x")
        self._git(self.b, "checkout", "-q", "--detach")
        self.assertBlocked(self._push("HEAD:refs/heads/outra"))

    def test_evil_merge_content_is_scanned(self):
        self._git(self.b, "checkout", "-qb", "side")
        (self.b / "a.md").write_text("a\n", encoding="utf-8")
        self._commit("side")
        self._git(self.b, "checkout", "-q", "main")
        (self.b / "c.md").write_text("c\n", encoding="utf-8")
        self._commit("main2")
        self._git(self.b, "merge", "-q", "--no-commit", "side")
        (self.b / "c.md").write_text("c\nFulana Quiteria\n", encoding="utf-8")
        self._commit("merge")
        self.assertBlocked(self._push("main"))

    def test_binary_non_ascii_name_and_header_lookalike_are_scanned(self):
        token = "xox" + "b-" + "1234567890-abcdef"
        cases = [("bin.dat", b"\0\x01PNG\0" + token.encode() + b"\0\0"),
                 ("decisões.md", "Fulana Quiteria\n".encode()),
                 ("tricky.md", "++ /dev/null\nFulana Quiteria\n".encode()),
                 ("notas de Fulana Quiteria.md", b"ok\n")]
        for name, data in cases:
            with self.subTest(name=name):
                self._git(self.b, "reset", "-q", "--hard", "origin/main")
                (self.b / name).write_bytes(data)
                self._commit("x")
                self.assertBlocked(self._push("HEAD:main"))

    def test_scan_failure_blocks_instead_of_allowing(self):
        (self.b / "doc.md").write_text("ok\n", encoding="utf-8")
        self._commit("x")
        (self.b / "config" / "brain.toml").write_text("isto não é toml [[[", encoding="utf-8")
        self.assertBlocked(self._push("HEAD:main"))

    def test_clean_new_branch_and_branch_delete_pass(self):
        self._git(self.b, "checkout", "-qb", "feat")
        (self.b / "brainlib" / "x.py").write_text("x = 1\n", encoding="utf-8")
        self._commit("ok")
        r = self._push("feat")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._push("--delete", "feat")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_push_revsets_shapes(self):
        head = self._git(self.b, "rev-parse", "HEAD").stdout.strip()
        zero = "0" * 40
        sets = upstream.push_revsets(self.inst, "origin",
                                     f"refs/heads/a {head} refs/heads/a {zero}\n"
                                     f"refs/heads/b {zero} refs/heads/b {head}\n"
                                     f"refs/heads/c {head} refs/heads/c {head}\n")
        self.assertEqual(sets, [[head, "--not", "--remotes=origin"], [head, f"^{head}"]])


if __name__ == "__main__":
    unittest.main()
