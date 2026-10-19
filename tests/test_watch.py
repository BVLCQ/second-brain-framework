"""`brain watch` — edição segura do config/watch.toml (stdlib, sem rede)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, util, watch

EXAMPLE = (ROOT / "config" / "watch.toml.example").read_text(encoding="utf-8")


class _WatchBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "vault").mkdir()
        (self.root / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
        self.inst = config.load(self.root)
        self.file = watch.path(self.inst)

    def seed(self, text: str = EXAMPLE) -> None:
        self.file.write_text(text, encoding="utf-8")

    def keys(self) -> list[str]:
        return [s["key"] for s in watch.list_sources(self.inst)]


class WatchTest(_WatchBase):

    def test_add_creates_the_file_with_the_header(self):
        self.assertEqual(watch.list_sources(self.inst), [])
        watch.add(self.inst, "slack-dados", {"kind": "slack", "window": "1d", "channel": "#dados"})
        text = self.file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Universo observável"))
        self.assertEqual(watch.list_sources(self.inst), [{"key": "slack-dados", "kind": "slack", "window": "1d", "channel": "#dados"}])

    def test_add_keeps_comments_and_examples(self):
        self.seed()
        watch.add(self.inst, "gmail-hoje", {"kind": "gmail", "window": "1d", "note": "digest do dia"})
        text = self.file.read_text(encoding="utf-8")
        self.assertIn('# key = "gcal-primary"', text)             # exemplos comentados continuam
        self.assertEqual(self.keys(), ["gmail-hoje"])             # e não viram fonte

    def test_validation(self):
        self.seed()
        with self.assertRaises(util.BrainError) as e:
            watch.add(self.inst, "Slack Dados", {"kind": "slack"})
        self.assertEqual(e.exception.code, 4)
        with self.assertRaises(util.BrainError):
            watch.add(self.inst, "ok", {})                         # sem kind
        watch.add(self.inst, "a", {"kind": "slack"})
        with self.assertRaises(util.BrainError):
            watch.add(self.inst, "a", {"kind": "gmail"})           # key repetida
        with self.assertRaises(util.BrainError):
            watch.add(self.inst, "b", {"kind": "slack", "Campo Ruim": "x"})
        self.assertEqual(self.keys(), ["a"])

    def test_edit_changes_values_and_keeps_the_rest(self):
        self.seed("# meu arquivo\n\n[[source]]\nkey = \"a\"\nkind = \"slack\"\nwindow = \"1d\"  # só ontem\nnote = \"x\"\n\n"
                  "[[source]]\nkey = \"b\"\nkind = \"gmail\"\n")
        watch.edit(self.inst, "a", {"window": "7d", "channel": '#dados "novo"'}, unset=["note"])
        text = self.file.read_text(encoding="utf-8")
        self.assertIn('window = "7d"  # só ontem', text)           # comentário na mesma linha sobrevive
        self.assertIn("# meu arquivo", text)
        src = {s["key"]: s for s in watch.list_sources(self.inst)}
        self.assertEqual(src["a"], {"key": "a", "kind": "slack", "window": "7d", "channel": '#dados "novo"'})
        self.assertEqual(src["b"], {"key": "b", "kind": "gmail"})   # o outro bloco não mudou

    def test_edit_rename_and_protected_fields(self):
        self.seed("[[source]]\nkey = \"a\"\nkind = \"slack\"\n\n[[source]]\nkey = \"b\"\nkind = \"gmail\"\n")
        watch.edit(self.inst, "a", rename="a2")
        self.assertEqual(self.keys(), ["a2", "b"])
        with self.assertRaises(util.BrainError):
            watch.edit(self.inst, "a2", rename="b")                # colide
        with self.assertRaises(util.BrainError):
            watch.edit(self.inst, "a2", unset=["kind"])
        with self.assertRaises(util.BrainError) as e:
            watch.edit(self.inst, "nao-existe", {"window": "1d"})
        self.assertEqual(e.exception.code, 3)

    def test_remove_only_that_block(self):
        self.seed(EXAMPLE)
        for k in ("a", "b", "c"):
            watch.add(self.inst, k, {"kind": "slack"})
        watch.remove(self.inst, "b")
        self.assertEqual(self.keys(), ["a", "c"])
        self.assertIn('# key = "jira-me"', self.file.read_text(encoding="utf-8"))
        watch.remove(self.inst, "c")
        watch.remove(self.inst, "a")
        self.assertEqual(self.keys(), [])
        self.assertTrue(self.file.read_text(encoding="utf-8").endswith("\n"))

    def test_invalid_file_is_never_overwritten(self):
        bad = "[[source]]\nkey = \"a\"\nkind = \n"
        self.seed(bad)
        with self.assertRaises(util.BrainError):
            watch.add(self.inst, "b", {"kind": "slack"})
        self.assertEqual(self.file.read_text(encoding="utf-8"), bad)

    def test_file_mode_is_preserved(self):
        self.seed()
        os.chmod(self.file, 0o640)
        watch.add(self.inst, "a", {"kind": "slack"})
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o640)

    def test_cli_roundtrip(self):
        env = {**os.environ, "BRAIN_HOME": str(self.root)}
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "brain"), "watch", *a], capture_output=True, text=True, env=env)  # noqa: E731
        self.assertEqual(run("add", "slack-dados", "--kind", "slack", "--window", "1d", "--set", "channel=#dados").returncode, 0)
        r = run("list", "--json")
        self.assertEqual(json.loads(r.stdout)[0]["channel"], "#dados")
        self.assertEqual(run("edit", "slack-dados", "--window", "7d", "--unset", "channel").returncode, 0)
        self.assertEqual(json.loads(run("list", "--json").stdout), [{"key": "slack-dados", "kind": "slack", "window": "7d"}])
        bad = run("add", "slack-dados", "--kind", "slack")
        self.assertEqual((bad.returncode, "já existe" in bad.stderr), (4, True))
        self.assertEqual(run("remove", "slack-dados").returncode, 0)
        self.assertEqual(run("remove", "slack-dados").returncode, 3)


class WatchSinceTest(_WatchBase):
    """`brain watch since`: o início da janela é do cérebro, não do LLM."""
    NOW = "2026-10-19T10:00:00-03:00"

    def brain(self, last_ok: str = ""):
        from types import SimpleNamespace
        from brainlib import state
        conns = {"slack-x": state.Connector("slack-x", last_ok=last_ok)} if last_ok else {}
        return SimpleNamespace(inst=self.inst, state=SimpleNamespace(connectors=conns))

    def since(self, window: str, last_ok: str = "") -> dict:
        watch.add(self.inst, "slack-x", {"kind": "slack", "window": window})
        old = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = self.NOW
        try:
            return watch.since(self.brain(last_ok), "slack-x")
        finally:
            os.environ.pop("BRAIN_NOW") if old is None else os.environ.__setitem__("BRAIN_NOW", old)

    def test_fixed_window_counts_back_from_now(self):
        r = self.since("1d")
        self.assertEqual((r["hours"], r["since"]), (24.0, "2026-10-18T10:00:00-03:00"))

    def test_auto_first_pull_looks_back_seven_days(self):
        self.assertEqual(self.since("auto")["hours"], 7 * 24.0)

    def test_auto_starts_at_last_ok_minus_overlap(self):
        r = self.since("auto", last_ok="2026-10-19T07:00:00-03:00")
        self.assertEqual(r["since"], "2026-10-19T05:00:00-03:00")
        self.assertEqual(r["hours"], 5.0)

    def test_auto_is_capped_after_a_long_gap(self):
        self.assertEqual(self.since("auto", last_ok="2026-08-01T07:00:00-03:00")["hours"], 14 * 24.0)

    def test_invalid_window_is_refused(self):
        for bad in ("2 dias", "0d", "d", "1m"):
            with self.assertRaises(util.BrainError, msg=bad):
                watch.add(self.inst, "slack-y", {"kind": "slack", "window": bad})
        self.assertNotIn("slack-y", self.keys())


if __name__ == "__main__":
    unittest.main()
