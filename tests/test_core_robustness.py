"""Robustez do núcleo: semeadura externa no init, erro no índice SQLite e dobra quebrada (#33, #36, #37)."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import cli, config, index, upstream, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _make_inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Entregável · prazo: 2026-10-20\n", encoding="utf-8")
    return config.load(tmp)


def _make_brain(tmp: Path) -> Brain:
    b = Brain(_make_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class InitExternalHomeTests(unittest.TestCase):
    """`brain init` fora do clone semeia template/ e config/*.example do framework e avisa se faltarem."""

    def test_cmd_init_outside_clone_seeds_template_and_config(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, {"BRAIN_HOME": str(home)}), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(["init", "--owner-name", "Marina Demo", "--email", "marina-demo@x.com"])
            self.assertEqual(rc, 0)
            self.assertTrue((home / "vault" / "PLANNING" / "goals.md").is_file())
            self.assertTrue((home / "vault" / "PROFILE" / "profile.md").is_file())
            self.assertTrue((home / "vault" / "RAW" / "inbox" / ".keep.md").is_file())
            self.assertTrue((home / "config" / "brain.toml").is_file())
            self.assertTrue((home / "config" / "watch.toml").is_file())
            self.assertTrue((home / "config" / ".env").is_file())
            cfg = config.load(home)
            self.assertEqual(cfg.owner_id, "marina-demo")
            self.assertEqual(err.getvalue(), "")
            self.assertIn("instância pronta", out.getvalue())

    def test_cli_subprocess_init_with_brain_home_outside_clone(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            env = {**os.environ, "BRAIN_HOME": str(home)}
            env.pop("BRAIN_VAULT", None)
            env.pop("BRAIN_CONFIG", None)
            r = subprocess.run([sys.executable, str(ROOT / "brain"), "init"],
                               cwd=str(home), env=env, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((home / "vault" / "PLANNING" / "goals.md").is_file())
            self.assertTrue((home / "config" / "brain.toml").is_file())

    def test_cmd_init_warns_when_template_and_config_missing(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as fw_td:
            home = Path(td)
            empty_fw = Path(fw_td)
            inst = config.load(home)
            out, err = io.StringIO(), io.StringIO()
            args = argparse.Namespace(owner_id=None, owner_name=None, alias=None, email=None)
            with mock.patch.object(upstream, "FRAMEWORK", empty_fw), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                cli.cmd_init(args, Brain(inst))
            self.assertNotIn("nada a criar", out.getvalue())
            msg = err.getvalue()
            self.assertIn(str(empty_fw / "template"), msg)
            self.assertIn(str(empty_fw / "config"), msg)


class IndexUpdateFailureTests(unittest.TestCase):
    """Falha em `_index_update` preserva escrita no ledger e registra log + stderr (nunca stdout)."""

    def test_record_one_succeeds_and_logs_on_index_error(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(index, "update", side_effect=RuntimeError("sqlite bloqueado")), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                ev = b.record_one({"type": "action.opened", "by": "owner",
                                   "data": {"title": "Ação resiliente", "owner": "eu"}})
            self.assertEqual(ev["id"], "TASK-0001")
            self.assertEqual(Brain(b.inst).state.actions["TASK-0001"].title, "Ação resiliente")
            self.assertEqual(out.getvalue(), "")
            self.assertIn("aviso: índice SQLite não atualizado (sqlite bloqueado) — rode ./brain index update",
                          err.getvalue())
            log_file = b.inst.logs / "index-errors.log"
            self.assertTrue(log_file.is_file())
            lines = log_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("RuntimeError: sqlite bloqueado", lines[0])

    def test_record_one_survives_unwritable_logs_dir(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            b.inst.logs.parent.mkdir(parents=True, exist_ok=True)
            b.inst.logs.write_text("não é diretório", encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(index, "update", side_effect=OSError("disco cheio")), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                ev = b.record_one({"type": "action.opened", "by": "owner",
                                   "data": {"title": "Ainda grava", "owner": "eu"}})
            self.assertEqual(ev["id"], "TASK-0001")
            self.assertEqual(out.getvalue(), "")
            self.assertIn("aviso: índice SQLite não atualizado (disco cheio)", err.getvalue())


class BrokenLedgerFoldTests(unittest.TestCase):
    """Referência quebrada/evento inválido na dobra levanta BrainError orientativo e `validate` sai com 4."""

    def test_state_raises_brain_error_with_context_on_broken_reference(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            broken = {"seq": 2, "ts": "2026-10-09T10:01:00-03:00", "type": "action.closed",
                      "id": "TASK-9999", "date": "2026-10-09", "by": "owner", "prov": "declarado",
                      "source": "chat", "data": {"how": "feito"}}
            with open(b.ledger_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(broken, ensure_ascii=False) + "\n")
            b2 = Brain(b.inst)
            with self.assertRaises(util.BrainError) as cm:
                _ = b2.state
            self.assertEqual(cm.exception.code, 5)
            msg = str(cm.exception)
            self.assertIn("seq 2", msg)
            self.assertIn("action.closed", msg)
            self.assertIn("TASK-9999", msg)
            self.assertIn("brain validate", msg)
            problems = b2.validate_all()
            self.assertTrue(any("referência quebrada" in p for p in problems), problems)

    def test_state_raises_brain_error_on_type_error_in_event(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            bad = {"seq": 2, "ts": "2026-10-09T10:01:00-03:00", "type": "action.opened",
                   "id": "TASK-0001", "date": "2026-10-09", "by": "owner", "prov": "declarado",
                   "source": "chat", "data": None}
            with open(b.ledger_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(bad, ensure_ascii=False) + "\n")
            with self.assertRaises(util.BrainError) as cm:
                _ = Brain(b.inst).state
            self.assertEqual(cm.exception.code, 5)
            msg = str(cm.exception)
            self.assertIn("seq 2", msg)
            self.assertIn("action.opened", msg)
            self.assertIn("TASK-0001", msg)
            self.assertIn("brain validate", msg)

    def test_cmd_validate_reports_broken_ref_and_exits_4_without_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            b = _make_brain(home)
            broken = {"seq": 2, "ts": "2026-10-09T10:01:00-03:00", "type": "action.closed",
                      "id": "TASK-9999", "date": "2026-10-09", "by": "owner", "prov": "declarado",
                      "source": "chat", "data": {"how": "feito"}}
            with open(b.ledger_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(broken, ensure_ascii=False) + "\n")

            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, {"BRAIN_HOME": str(home)}), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as cm:
                    cli.main(["validate"])
            self.assertEqual(cm.exception.code, 4)
            self.assertIn("✗ ", out.getvalue())
            self.assertIn("referência quebrada", out.getvalue())
            self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
