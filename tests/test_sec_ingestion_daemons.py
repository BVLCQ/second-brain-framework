"""Testes de resiliência na ingestão (repos, seed, video) e saneamento no idle_unload."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import repos, seed, util, video, watch  # noqa: E402
from test_brain import _brain  # noqa: E402


def _load_idle_unload():
    spec = importlib.util.spec_from_file_location("idle_unload_sec", ROOT / "services" / "idle_unload.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_docx(path: Path, doc_xml: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)


def _git(repo: Path, *args: str, date: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Marina-demo",
        "GIT_AUTHOR_EMAIL": "marina-demo@x.com",
        "GIT_COMMITTER_NAME": "Marina-demo",
        "GIT_COMMITTER_EMAIL": "marina-demo@x.com",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def _commit(repo: Path, name: str, msg: str, date: str) -> None:
    (repo / name).write_text(msg + "\n", encoding="utf-8")
    _git(repo, "add", name, date=date)
    _git(repo, "commit", "-q", "-m", msg, date=date)


class IdleUnloadSanitizationTests(unittest.TestCase):
    def test_num_rejects_invalid_values(self):
        mod = _load_idle_unload()
        self.assertEqual(mod._num(True, 9.0), 9.0)
        self.assertEqual(mod._num(False, 9.0), 9.0)
        self.assertEqual(mod._num(None, 9.0), 9.0)
        self.assertEqual(mod._num("123", 9.0), 9.0)
        self.assertEqual(mod._num("bad", 9.0), 9.0)
        self.assertEqual(mod._num(float("nan"), 9.0), 9.0)
        self.assertEqual(mod._num(float("inf"), 9.0), 9.0)
        self.assertEqual(mod._num(float("-inf"), 9.0), 9.0)
        self.assertEqual(mod._num(-1, 9.0), 9.0)
        self.assertEqual(mod._num(42, 9.0), 42.0)

    def test_idle_unload_sanitizes_corrupt_state_and_bad_hindsight_counts(self):
        mod = _load_idle_unload()
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state_path = tmp / "idle.json"
            state_path.write_text(
                json.dumps({
                    "models": {
                        "valid-llm": {
                            "timeout_s": "bad",
                            "last_busy": "nope",
                            "unloaded_at": None,
                        },
                        "stale-unloaded": {
                            "timeout_s": 300,
                            "last_busy": 100,
                            "unloaded_at": "bad",
                        },
                        "junk-entry": "not-a-dict",
                    }
                }),
                encoding="utf-8",
            )

            # Hindsight: primeiro banco tem contagem "NaN", segundo banco é válido (0)
            class _FakeResp:
                def __init__(self, raw: bytes):
                    self._raw = raw

                def read(self) -> bytes:
                    return self._raw

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            def fake_urlopen(url, timeout=5):
                if "/bad_bank/" in url:
                    return _FakeResp(json.dumps({"operations_by_status": {"pending": "NaN", "processing": 0}}).encode())
                if "/bool_bank/" in url:
                    return _FakeResp(json.dumps({"operations_by_status": {"pending": True, "processing": 0}}).encode())
                if "/neg_bank/" in url:
                    return _FakeResp(json.dumps({"operations_by_status": {"pending": -2, "processing": 1}}).encode())
                return _FakeResp(json.dumps({"operations_by_status": {"pending": 0, "processing": 0}}).encode())

            models_payload = [
                "bad-non-dict",
                {"identifier": "", "status": "idle"},
                {"identifier": 123, "status": "idle"},
                {
                    "identifier": "valid-llm",
                    "type": "llm",
                    "status": "idle",
                    "lastUsedTime": "not-a-number",
                    "queued": "bad-queue",
                },
            ]

            logs: list[str] = []
            with mock.patch.object(mod, "BANKS", ["bad_bank", "bool_bank", "neg_bank", "ok_bank"]), \
                 mock.patch.object(mod.urllib.request, "urlopen", side_effect=fake_urlopen), \
                 mock.patch.object(mod, "loaded_models", return_value=models_payload), \
                 mock.patch.object(mod, "memory_level", return_value=80), \
                 mock.patch.object(mod, "log", side_effect=logs.append):
                rc = mod.main(["idle_unload.py", str(state_path)])

            self.assertEqual(rc, 0)
            saved = json.loads(state_path.read_text(encoding="utf-8"))["models"]
            self.assertIn("valid-llm", saved)
            self.assertNotIn("junk-entry", saved)
            self.assertNotIn("stale-unloaded", saved)
            self.assertIsInstance(saved["valid-llm"]["timeout_s"], float)
            self.assertIsInstance(saved["valid-llm"]["last_busy"], float)
            self.assertNotIn("unloaded_at", saved["valid-llm"])
            self.assertTrue(any("bad_bank" in ln for ln in logs))

            # Mesmo se ocorrer erro fatal após carregar o estado, finally reescreve estado saneado
            state_path.write_text(
                json.dumps({"models": {"m1": {"timeout_s": "bad", "last_busy": 123.0}, "bad": "x"}}),
                encoding="utf-8",
            )
            with mock.patch.object(mod, "loaded_models", side_effect=RuntimeError("lms falhou")):
                with self.assertRaises(RuntimeError):
                    mod.main(["idle_unload.py", str(state_path)])
            rewritten = json.loads(state_path.read_text(encoding="utf-8"))["models"]
            self.assertEqual(rewritten, {"m1": {"last_busy": 123.0}})

            # Execução via CLI com lms ausente deve sair com código 1 (não 0)
            env = {**os.environ, "BRAIN_LMS": str(tmp / "lms-nao-existe"), "BRAIN_IDLE_UNLOAD_OFF": "0"}
            proc = subprocess.run(
                [sys.executable, str(ROOT / "services" / "idle_unload.py"), str(state_path)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(proc.returncode, 1)


class VideoTimeoutTests(unittest.TestCase):
    def test_video_transcribe_and_frames_enforce_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            media = Path(td) / "reuniao.mp4"
            media.write_bytes(b"fake-video")

            created_procs = []

            class FakeProc:
                def __init__(self, cmd, **_kw):
                    self.cmd = cmd
                    self.returncode = None
                    self.killed = False
                    self.waited = False
                    self.timeouts = []
                    created_procs.append(self)

                def communicate(self, timeout=None):
                    self.timeouts.append(timeout)
                    raise subprocess.TimeoutExpired(self.cmd, timeout)

                def poll(self):
                    return 0 if self.killed else None

                def kill(self):
                    self.killed = True

                def wait(self):
                    self.waited = True
                    return -9

            with mock.patch.object(video, "swift_tool", return_value=["/fake/stt"]):
                with self.assertRaises(util.BrainError) as ctx:
                    video.transcribe(media, locales=["pt-BR", "en-US"], timeout=12, popen=FakeProc)
            self.assertEqual(ctx.exception.code, 3)
            self.assertIn("12s", str(ctx.exception))
            self.assertEqual(len(created_procs), 2)
            # Todos os subprocessos vivos precisam ser finalizados no finally
            self.assertTrue(all(p.killed and p.waited for p in created_procs))
            self.assertTrue(created_procs[0].timeouts[0] is not None and created_procs[0].timeouts[0] <= 12)

            run_calls = []

            def fake_run(args, **kw):
                run_calls.append((args, kw))
                raise subprocess.TimeoutExpired(args, kw.get("timeout"))

            with mock.patch.object(video, "swift_tool", return_value=["/fake/frames"]):
                with self.assertRaises(util.BrainError) as ctx2:
                    video.frames(media, timeout=15, run=fake_run)
            self.assertEqual(ctx2.exception.code, 3)
            self.assertIn("15s", str(ctx2.exception))
            self.assertEqual(run_calls[0][1].get("timeout"), 15)


@unittest.skipUnless(shutil.which("git"), "git ausente")
class ReposBoundsTests(unittest.TestCase):
    def test_repos_first_read_caps_commits_and_batches_diff_tree(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp / "inst")
            github = tmp / "Github"
            repo = github / "app"
            repo.mkdir(parents=True)
            _git(repo, "init", "-q", "-b", "main", date=util.iso_now())
            for i in range(12):
                _commit(repo, f"f{i:02d}.py", f"commit {i:02d}", date=util.iso_now())
            watch.add(b.inst, "github-repos", {"kind": "github", "window": "auto", "path": str(github)})

            orig_git = repos._git
            git_cmds: list[str] = []

            def spy_git(repo_path, *args, **kwargs):
                if args:
                    git_cmds.append(args[0])
                return orig_git(repo_path, *args, **kwargs)

            with mock.patch.object(repos, "MAX_FULL_COMMITS", 5), \
                 mock.patch.object(repos, "_git", side_effect=spy_git):
                r = repos.pull(b, "github-repos")

            self.assertFalse(r["failed"])
            row = r["repos"][0]
            self.assertTrue(row["full"])
            self.assertEqual(row["new"], 5)
            # diff-tree precisa rodar em lote único (1 subprocesso para os 5 commits)
            self.assertEqual(git_cmds.count("diff-tree"), 1)

            snap_text = (b.inst.vault / row["snapshot"]).read_text(encoding="utf-8")
            self.assertIn("- commits: 5 (mostrando os 5 mais recentes; há mais)", snap_text)
            self.assertIn("teto de 5", snap_text)
            hist_text = snap_text.split("## Histórico", 1)[1]
            self.assertIn("commit 11", hist_text)
            self.assertIn("A f11.py", hist_text)
            self.assertNotIn("commit 00", hist_text)


class SeedDocxSecurityTests(unittest.TestCase):
    def test_seed_docx_rejects_oversized_zip_and_entity_xml(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            doctype_docx = tmp / "doctype.docx"
            _make_docx(
                doctype_docx,
                '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe "boom">]>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>",
            )
            with self.assertRaises(util.BrainError) as ctx_dt:
                seed._read_docx(doctype_docx)
            self.assertEqual(ctx_dt.exception.code, 4)

            entity_docx = tmp / "entity.docx"
            _make_docx(
                entity_docx,
                '<?xml version="1.0"?><!ENTITY xxe "boom">'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>oi</w:t></w:r></w:p></w:body></w:document>",
            )
            with self.assertRaises(util.BrainError) as ctx_ent:
                seed._read_docx(entity_docx)
            self.assertEqual(ctx_ent.exception.code, 4)

            big_docx = tmp / "big.docx"
            _make_docx(
                big_docx,
                '<?xml version="1.0"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body><w:p><w:r><w:t>{'A' * 400}</w:t></w:r></w:p></w:body></w:document>",
            )
            with mock.patch.object(seed, "MAX_DOCX_XML_BYTES", 100):
                with self.assertRaises(util.BrainError) as ctx_big:
                    seed._read_docx(big_docx)
            self.assertEqual(ctx_big.exception.code, 4)

            # Simula cabeçalho zip forjado (info.file_size pequeno, fluxo real maior que o teto)
            fake_info = zipfile.ZipInfo("word/document.xml")
            fake_info.file_size = 10

            class _ForgedZip:
                def __init__(self, *_a, **_kw):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_a):
                    return False

                def getinfo(self, _name):
                    return fake_info

                def open(self, _info):
                    return io.BytesIO(b"<w:document>" + b"A" * 150 + b"</w:document>")

            with mock.patch.object(seed, "MAX_DOCX_XML_BYTES", 100), \
                 mock.patch.object(seed.zipfile, "ZipFile", _ForgedZip):
                with self.assertRaises(util.BrainError) as ctx_forged:
                    seed._read_docx(big_docx)
            self.assertEqual(ctx_forged.exception.code, 4)

            bad_xml_docx = tmp / "badxml.docx"
            _make_docx(bad_xml_docx, "<w:document><w:body><unclosed></w:body></w:document>")
            with self.assertRaises(util.BrainError) as ctx_parse:
                seed._read_docx(bad_xml_docx)
            self.assertEqual(ctx_parse.exception.code, 3)

            ok_docx = tmp / "ok.docx"
            _make_docx(
                ok_docx,
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>Parágrafo 1</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Parágrafo 2</w:t></w:r></w:p></w:body></w:document>",
            )
            self.assertEqual(seed._read_docx(ok_docx), "Parágrafo 1\n\nParágrafo 2")


if __name__ == "__main__":
    unittest.main()
