"""Security tests for upstream leak scanner redaction (#133) and fail-closed ledger reads (#144.5)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from brainlib import config, publicguard, upstream, util


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init_repo_inst(tmp: Path) -> config.Instance:
    remote = tmp / "remote.git"
    repo = tmp / "inst"
    _git(tmp, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(tmp, "clone", "-q", str(remote), str(repo))
    _git(repo, "config", "user.name", "Marina Demo")
    _git(repo, "config", "user.email", "marina-demo@example.com")
    (repo / "brainlib").mkdir()
    (repo / "brainlib" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (repo / ".gitignore").write_text("/vault/\nconfig/brain.toml\nconfig/.env\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "push", "-q", "origin", "HEAD:main")
    (repo / "config").mkdir()
    (repo / "config" / "brain.toml").write_text(
        '[owner]\nid = "dona"\nname = "Fulana Quiteria"\n',
        encoding="utf-8",
    )
    for sub in ("PLANNING", "RAW/inbox", "PROCESSED/_ledger", "FRESH"):
        (repo / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (repo / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(repo)


class UpstreamScannerRedactionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.inst = _init_repo_inst(Path(self._td.name))

    def test_upstream_scan_never_echoes_secret_in_json_or_stdout(self):
        secret = "sk-" + "ant-oat01-demo1234567890"
        personal = "Fulana Quiteria"
        (self.inst.root / "brainlib" / "leak.py").write_text(
            f'TOKEN = "{secret}"\nOWNER = "{personal}"\n',
            encoding="utf-8",
        )
        st = upstream.upstream_scan(self.inst)
        findings = st["findings"]
        self.assertEqual(len(findings), 2)
        for f in findings:
            self.assertNotIn("text", f)
            self.assertIn("fingerprint", f)
            self.assertIn("length", f)
            self.assertEqual(len(f["fingerprint"]), 12)

        as_json = json.dumps(st, ensure_ascii=False)
        self.assertNotIn(secret, as_json)
        self.assertNotIn(personal, as_json)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            upstream._print_scan(st)
        out = buf.getvalue()
        self.assertNotIn(secret, out)
        self.assertNotIn(personal, out)
        self.assertIn("sha:", out)

    def test_pre_push_scan_and_history_policy_use_hint_without_text(self):
        secret = "ghp_" + "AbCdEfGhIjKlMnOpQrStUvWxYz123456"
        env_file = self.inst.root / "config" / ".env"
        env_file.write_text(f"GITHUB_TOKEN={secret}\n", encoding="utf-8")
        _git(self.inst.root, "add", "-f", "config/.env")
        _git(self.inst.root, "commit", "-q", "-m", "acidente")
        head_sha = _git(self.inst.root, "rev-parse", "HEAD").strip()
        origin_sha = _git(self.inst.root, "rev-parse", "origin/main").strip()

        st = upstream.pre_push_scan(
            self.inst,
            "origin",
            f"refs/heads/main {head_sha} refs/heads/main {origin_sha}\n",
        )
        self.assertTrue(st["findings"])
        for f in st["findings"]:
            self.assertNotIn("text", f)
        self.assertTrue(any(f.get("hint") for f in st["findings"]))

        as_json = json.dumps(st, ensure_ascii=False)
        self.assertNotIn(secret, as_json)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            upstream._print_findings(st["findings"])
        out = buf.getvalue()
        self.assertNotIn(secret, out)
        self.assertIn("git rm --cached", out)


class LeakTermsFailClosedTests(unittest.TestCase):
    def test_leak_terms_fails_closed_on_corrupt_ledger_and_allows_missing_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _init_repo_inst(Path(td))
            ledger = inst.vault / "PROCESSED" / "_ledger" / "events.jsonl"
            self.assertFalse(ledger.exists())

            # Fresh instance with missing ledger file stays tolerated
            terms = upstream._leak_terms(inst)
            self.assertIn(("fulana quiteria", "dono"), terms)

            # Corrupt JSON in existing ledger fails closed
            ledger.write_text("{not-valid-json\n", encoding="utf-8")
            with self.assertRaises(util.BrainError):
                upstream._leak_terms(inst)
            with self.assertRaises(util.BrainError):
                upstream.scan(inst, "HEAD")
            with self.assertRaises(util.BrainError):
                publicguard.guard(inst, "Titulo", "Corpo limpo")

            # Non-UTF8 corrupt bytes in existing ledger also fail closed
            ledger.write_bytes(b"\xff\xfe\xfd\n")
            with self.assertRaises(util.BrainError):
                upstream._leak_terms(inst)


if __name__ == "__main__":
    unittest.main()
