"""Testes de falha fechada do `doctor` (#126, #127, #128)."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, demo as demo_mod, doctor, runner, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _make_brain(tmp: Path, *, focus_mode: str = "ics") -> Brain:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "logs").mkdir(parents=True, exist_ok=True)
    today_iso = util.today().isoformat()
    horizon_iso = (util.today() + timedelta(days=30)).isoformat()
    due_iso = (util.today() + timedelta(days=7)).isoformat()
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Marina Demo"\n\n'
        '[memory]\nengine = "none"\n\n'
        f'[focus]\nmode = "{focus_mode}"\n\n'
        '[outbound]\nallow = ["marina-demo", "#seu-canal"]\n\n'
        '[publish]\ndestinations = ["slack:#seu-canal"]\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta de teste\n- status: ativo\n"
        f"- horizonte: {horizon_iso}\n- por quê: validar doctor ({today_iso})\n\n"
        "### PROJ-1 — Projeto de teste\n- status: ativo\n- dono: eu\n"
        f"- [ ] PROJ-1.1 Entregável 1 · prazo: {due_iso} · peso: 2\n",
        encoding="utf-8",
    )
    b = Brain(config.load(tmp))
    b.record_one({
        "type": "person.added",
        "id": "eu",
        "by": "owner",
        "data": {"name": "Marina Demo", "aliases": ["Eu"], "relation": "dono"},
    })
    return b


class DoctorFailClosedTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_fix_apply_exits_nonzero_when_error_findings_remain(self):
        b = _make_brain(self.td, focus_mode="google")
        args = argparse.Namespace(
            fix=True, apply=True, dry_run=False, json=False, online=False,
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                doctor.cli(args, b)
        self.assertEqual(ctx.exception.code, 1)

        args_json = argparse.Namespace(
            fix=True, apply=True, dry_run=False, json=True, online=False,
        )
        jbuf = io.StringIO()
        with contextlib.redirect_stdout(jbuf):
            with self.assertRaises(SystemExit) as ctx_json:
                doctor.cli(args_json, b)
        self.assertEqual(ctx_json.exception.code, 1)
        payload = json.loads(jbuf.getvalue())
        self.assertGreaterEqual(payload["remaining_errors"], 1)

    def test_checks_emits_views_warn_when_render_state_missing_or_corrupt(self):
        b = _make_brain(self.td)
        rs_path = b.inst.fresh / ".render-state.json"

        # 1. Ausente
        rs_path.unlink(missing_ok=True)
        views_missing = [c for c in doctor.checks(b) if c["title"] == "views"]
        self.assertEqual(len(views_missing), 1)
        self.assertEqual(views_missing[0]["level"], "warn")
        self.assertIn("ausente", views_missing[0]["detail"])

        # 2. JSON malformado
        rs_path.write_text("{broken", encoding="utf-8")
        views_broken = [c for c in doctor.checks(b) if c["title"] == "views"]
        self.assertEqual(len(views_broken), 1)
        self.assertEqual(views_broken[0]["level"], "warn")
        self.assertIn("corrompido", views_broken[0]["detail"])

        # 3. Tipo não-dict ou rendered_at inválido
        rs_path.write_text("[]", encoding="utf-8")
        views_list = [c for c in doctor.checks(b) if c["title"] == "views"]
        self.assertEqual(len(views_list), 1)
        self.assertEqual(views_list[0]["level"], "warn")

        rs_path.write_text(json.dumps({"rendered_at": "invalido"}), encoding="utf-8")
        views_bad_dt = [c for c in doctor.checks(b) if c["title"] == "views"]
        self.assertEqual(len(views_bad_dt), 1)
        self.assertEqual(views_bad_dt[0]["level"], "warn")

        # 4. Válido e recente → ok
        rs_path.write_text(json.dumps({"rendered_at": util.iso_now()}), encoding="utf-8")
        views_ok = [c for c in doctor.checks(b) if c["title"] == "views"]
        self.assertEqual(len(views_ok), 1)
        self.assertEqual(views_ok[0]["level"], "ok")

    def test_freshness_dump_fails_closed_when_never_dumped_or_ledger_corrupt(self):
        b = _make_brain(self.td)
        base_now = util.now()

        # 1. Ledger vazio (sem artifact.added) -> stale["dump"] = True, dump_reason = "nunca dumpado"
        f_empty = doctor.freshness(b, now=base_now)
        self.assertTrue(f_empty["stale"]["dump"])
        self.assertEqual(f_empty["dump_reason"], "nunca dumpado")
        self.assertIsNone(f_empty["last_dump_at"])
        self.assertIsNone(f_empty["last_dump_age_h"])

        # 2. Ledger corrompido -> stale["dump"] = True, dump_reason = "ledger ilegível"
        b_bad = _make_brain(self.td / "bad")
        b_bad.ledger_path.write_text("{corrupt-jsonl\n", encoding="utf-8")
        b_bad.reload()
        f_bad = doctor.freshness(b_bad, now=base_now)
        self.assertTrue(f_bad["stale"]["dump"])
        self.assertEqual(f_bad["dump_reason"], "ledger ilegível")
        self.assertIsNone(f_bad["last_dump_at"])
        self.assertIsNone(f_bad["last_dump_age_h"])

        # 3. Com artifact.added fresco -> stale["dump"] = False, dump_reason = None
        b.record_one({
            "type": "artifact.added",
            "id": "PROCESSED/nota.md",
            "by": "agent",
            "prov": "observado",
            "source": "RAW/nota.md",
            "data": {"kind": "nota", "title": "Nota", "raw": "RAW/nota.md"},
        })
        f_fresh = doctor.freshness(b, now=base_now)
        self.assertFalse(f_fresh["stale"]["dump"])
        self.assertIsNone(f_fresh["dump_reason"])
        self.assertIsNotNone(f_fresh["last_dump_at"])
        self.assertIsNotNone(f_fresh["last_dump_age_h"])

    def test_doctor_online_exits_zero_on_demo_vault(self):
        demo_dir = self.td / "demo"
        with contextlib.redirect_stdout(io.StringIO()):
            demo_mod.cli(argparse.Namespace(dir=str(demo_dir), open=False))
        b_demo = Brain(config.load(demo_dir))
        args = argparse.Namespace(
            fix=False, apply=False, dry_run=False, json=False, online=True,
        )
        buf = io.StringIO()
        with mock.patch.object(runner, "agent_candidates", return_value=[]):
            with contextlib.redirect_stdout(buf):
                doctor.cli(args, b_demo)
        self.assertIn("views:", buf.getvalue())

        # Mesmo sem .render-state.json (vault recém-inicializado), views é warn e não quebra exit 0
        (b_demo.inst.fresh / ".render-state.json").unlink(missing_ok=True)
        buf2 = io.StringIO()
        with mock.patch.object(runner, "agent_candidates", return_value=[]):
            with contextlib.redirect_stdout(buf2):
                doctor.cli(args, b_demo)
        self.assertIn("⚠ views:", buf2.getvalue())
