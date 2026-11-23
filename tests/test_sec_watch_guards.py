"""Guardas de segurança em `brainlib/watch.py`: gate noturno (#118) e tolerância a `modifiedTime` inválido (#122)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, state, util, watch  # noqa: E402


@contextmanager
def _env(key: str, value: str | None):
    old = os.environ.get(key)
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


class WatchSecurityGuardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "vault").mkdir()
        (self.root / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
        self.inst = config.load(self.root)
        self.file = watch.path(self.inst)

    def test_watch_add_edit_remove_refused_in_nightly(self):
        watch.add(self.inst, "slack-dados", {"kind": "slack", "window": "1d", "channel": "#dados"})
        before = self.file.read_text(encoding="utf-8")

        for flag in ("1", "true"):
            with self.subTest(BRAIN_NIGHTLY=flag), _env("BRAIN_NIGHTLY", flag):
                with self.assertRaises(util.BrainError) as cm_add:
                    watch.add(self.inst, "nova-fonte", {"kind": "gmail", "window": "1d"})
                self.assertEqual(cm_add.exception.code, 4)
                self.assertIn("noturno", str(cm_add.exception))

                with self.assertRaises(util.BrainError) as cm_edit:
                    watch.edit(self.inst, "slack-dados", {"window": "7d"})
                self.assertEqual(cm_edit.exception.code, 4)
                self.assertIn("noturno", str(cm_edit.exception))

                with self.assertRaises(util.BrainError) as cm_rm:
                    watch.remove(self.inst, "slack-dados")
                self.assertEqual(cm_rm.exception.code, 4)
                self.assertIn("noturno", str(cm_rm.exception))

                self.assertEqual(self.file.read_text(encoding="utf-8"), before)

    def test_plan_folders_survives_malformed_modified_time(self):
        watch.add(self.inst, "drive-reunioes", {"kind": "drive", "window": "auto"})
        now = util.now()
        last_ok = (now - timedelta(hours=3)).isoformat(timespec="seconds")
        old_call_day = (now - timedelta(days=18)).strftime("%Y/%m/%d")
        old_mod_iso = (now - timedelta(days=15)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fresh_mod_iso = (now - timedelta(minutes=30)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        brain = SimpleNamespace(
            inst=self.inst,
            state=SimpleNamespace(connectors={"drive-reunioes": state.Connector("drive-reunioes", last_ok=last_ok)}),
        )

        folders = [
            {"id": "f-none", "name": f"Retro - {old_call_day} 09:00", "modifiedTime": None},
            {"id": "f-int", "name": f"Retro - {old_call_day} 09:00", "modifiedTime": 12345},
            {"id": "f-bad", "name": f"Retro - {old_call_day} 09:00", "modifiedTime": "not-a-date"},
            {"id": "f-dict", "name": f"Retro - {old_call_day} 09:00", "modifiedTime": {}},
            {"id": "f-blank", "name": f"Retro - {old_call_day} 09:00", "modifiedTime": "   "},
            {"id": "f-old-valid", "name": f"Retro - {old_call_day} 09:00", "modifiedTime": old_mod_iso},
            {"id": "f-fresh-valid", "name": f"Retro - {old_call_day} 09:00", "modifiedTime": fresh_mod_iso},
        ]

        r = watch.plan_folders(brain, "drive-reunioes", folders)
        by_id = {row["id"]: row for row in r["folders"]}

        for bad_id in ("f-int", "f-bad", "f-dict", "f-blank"):
            self.assertTrue(by_id[bad_id]["descend"], bad_id)
            self.assertIn("modifiedTime inválido", by_id[bad_id]["why"], bad_id)

        self.assertFalse(by_id["f-none"]["descend"])
        self.assertFalse(by_id["f-old-valid"]["descend"])
        self.assertTrue(by_id["f-fresh-valid"]["descend"])
        self.assertEqual((r["descend"], r["skip"]), (5, 2))
        self.assertEqual(len(r["warnings"]), 4)
        for bad_id in ("f-int", "f-bad", "f-dict", "f-blank"):
            self.assertTrue(any(bad_id in w for w in r["warnings"]), bad_id)


if __name__ == "__main__":
    unittest.main()
