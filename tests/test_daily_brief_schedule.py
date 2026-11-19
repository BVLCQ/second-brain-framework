"""Testes da rotina diária padrão 09:00, notes derivadas em FRESH/notes/ e brief pronto (#60)."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, notes, render, runner, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _make_inst(root: Path, extra_toml: str = "") -> config.Instance:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (root / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (root / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (root / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (root / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (root / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (root / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n' + extra_toml,
        encoding="utf-8",
    )
    today_str = util.today().isoformat()
    (root / "vault" / "PLANNING" / "goals.md").write_text(
        f"# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: {today_str}\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        f"- [ ] PROJ-1.1 Entregável · prazo: {today_str} · peso: 1\n",
        encoding="utf-8",
    )
    fake_bin = root / "brain"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    return config.load(root)


def _make_brain(root: Path, extra_toml: str = "") -> Brain:
    b = Brain(_make_inst(root, extra_toml=extra_toml))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class ScheduleDefaultTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env_patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self._td.cleanup()

    def test_launchd_default_0900_explicit_override_and_off(self):
        cmds: list[list[str]] = []

        def fake_run(cmd, **kw):
            cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        inst_default = _make_brain(self.tmp / "inst-default")
        self.assertEqual(inst_default.inst.cfg["runner"]["schedule"], "09:00")

        with mock.patch.object(runner, "_use_launchd", return_value=True):
            with contextlib.redirect_stdout(io.StringIO()):
                runner.schedule_cli(argparse.Namespace(action="install", time=None), inst_default, run=fake_run)
            plist = runner._launchd_plist(inst_default.inst.root)
            self.assertTrue(plist.exists())
            data = plistlib.loads(plist.read_bytes())
            self.assertEqual(data["StartCalendarInterval"], {"Hour": 9, "Minute": 0})
            self.assertTrue(any(c[0] == "launchctl" and "bootstrap" in c for c in cmds))

            # Reagendamento idempotente com --time explícito
            with contextlib.redirect_stdout(io.StringIO()):
                runner.schedule_cli(argparse.Namespace(action="install", time="22:30"), inst_default, run=fake_run)
            data2 = plistlib.loads(plist.read_bytes())
            self.assertEqual(data2["StartCalendarInterval"], {"Hour": 22, "Minute": 30})
            self.assertEqual(len(list(plist.parent.glob("*.plist"))), 1)

            # Instância com schedule = "22:30" explícito no brain.toml preserva 22:30 sem --time
            inst_custom = _make_brain(self.tmp / "inst-custom", '[runner]\nschedule = "22:30"\n')
            with contextlib.redirect_stdout(io.StringIO()):
                runner.schedule_cli(argparse.Namespace(action="install", time=None), inst_custom, run=fake_run)
            plist_custom = runner._launchd_plist(inst_custom.inst.root)
            self.assertEqual(plistlib.loads(plist_custom.read_bytes())["StartCalendarInterval"],
                             {"Hour": 22, "Minute": 30})

            # Instância com schedule = "off" ou "nao-agendar" não instala e remove se existia
            for val in ("off", "nao-agendar"):
                inst_off = _make_brain(self.tmp / f"inst-{val}", f'[runner]\nschedule = "{val}"\n')
                cmds.clear()
                with contextlib.redirect_stdout(io.StringIO()):
                    runner.schedule_cli(argparse.Namespace(action="install", time=None), inst_off, run=fake_run)
                self.assertFalse(runner._launchd_plist(inst_off.inst.root).exists())
                self.assertFalse(runner.scheduled_here(inst_off.inst.root))
                self.assertFalse(any(c[0] == "launchctl" and "bootstrap" in c for c in cmds))

    def test_crontab_default_0900_and_off(self):
        cron_lines: list[str] = []

        def fake_run(cmd, **kw):
            if cmd == ["crontab", "-l"]:
                return subprocess.CompletedProcess(cmd, 0, "\n".join(cron_lines), "")
            if cmd == ["crontab", "-"]:
                cron_lines.clear()
                cron_lines.extend(ln for ln in (kw.get("input") or "").splitlines() if ln.strip())
            return subprocess.CompletedProcess(cmd, 0, "", "")

        b = _make_brain(self.tmp / "inst-cron")
        with mock.patch.object(runner, "_use_launchd", return_value=False), \
             mock.patch.object(runner.shutil, "which", return_value="/usr/bin/crontab"):
            with contextlib.redirect_stdout(io.StringIO()):
                runner.schedule_cli(argparse.Namespace(action="install", time=None), b, run=fake_run)
            self.assertEqual(len(cron_lines), 1)
            self.assertTrue(cron_lines[0].startswith("0 9 * * * "))

            b_off = _make_brain(self.tmp / "inst-cron-off", '[runner]\nschedule = "off"\n')
            with contextlib.redirect_stdout(io.StringIO()):
                runner.schedule_cli(argparse.Namespace(action="install", time=None), b_off, run=fake_run)
            self.assertEqual(len(cron_lines), 1)


class FreshNotesAndBriefTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name).resolve()

    def tearDown(self):
        self._td.cleanup()

    def test_cli_note_write_under_nightly_writes_no_ledger_event(self):
        root = self.tmp / "inst"
        b = _make_brain(root)
        ledger_before = b.ledger_path.read_text(encoding="utf-8")
        env = {**os.environ, "BRAIN_HOME": str(root), "BRAIN_NIGHTLY": "1"}

        r = subprocess.run(
            [sys.executable, str(ROOT / "brain"), "note", "write", "brief", "--text", "Resumo do dia"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        brief_path = root / "vault" / "FRESH" / "notes" / "brief.md"
        self.assertTrue(brief_path.exists())
        parsed = notes.parse_note(brief_path)
        self.assertEqual(parsed["kind"], "brief")
        self.assertEqual(parsed["date"], util.today().isoformat())
        self.assertFalse(parsed["empty"])
        self.assertTrue(parsed["is_today"])
        self.assertEqual(parsed["body"], "Resumo do dia")
        self.assertEqual(b.ledger_path.read_text(encoding="utf-8"), ledger_before)

        # --file - via stdin + --json + --empty
        r_stdin = subprocess.run(
            [sys.executable, str(ROOT / "brain"), "note", "write", "semana",
             "--kind", "week", "--file", "-", "--empty", "--json"],
            input="Sem novidades relevantes.\n", capture_output=True, text=True, env=env,
        )
        self.assertEqual(r_stdin.returncode, 0, r_stdin.stderr)
        payload = json.loads(r_stdin.stdout)
        self.assertEqual(payload["slug"], "semana")
        self.assertEqual(payload["kind"], "week")
        self.assertTrue(payload["empty"])
        self.assertEqual(payload["body"], "Sem novidades relevantes.")

    def test_write_note_rejects_empty_and_traversal_slugs(self):
        b = _make_brain(self.tmp / "inst")
        for bad in ("", "   ", "../evil", "..", "a/b", "a\\b", "---"):
            with self.assertRaises(util.BrainError):
                notes.write_note(b, bad, "texto")

    def test_ensure_daily_brief_preserves_today_and_writes_fallback_when_missing_or_stale(self):
        b = _make_brain(self.tmp / "inst")
        # Ausente -> grava fallback de 1 linha com empty: true
        p = notes.ensure_daily_brief(b)
        self.assertTrue(p.exists())
        info = notes.daily_brief(b.inst.fresh)
        self.assertTrue(info["exists"])
        self.assertTrue(info["is_today"])
        self.assertTrue(info["empty"])
        self.assertEqual(info["text"], "Sem novidades desde a última atualização.")

        # Escrito pelo agente hoje -> preserva
        notes.write_note(b, "brief", "2 ações destravadas hoje.", kind="brief", empty=False)
        notes.ensure_daily_brief(b)
        info2 = notes.daily_brief(b.inst.fresh)
        self.assertFalse(info2["empty"])
        self.assertEqual(info2["text"], "2 ações destravadas hoje.")

        # De ontem -> substitui pelo fallback de hoje
        yesterday = (util.today() - timedelta(days=1)).isoformat()
        notes.write_note(b, "brief", "Brief velho de ontem.", kind="brief", note_date=yesterday, empty=False)
        self.assertFalse(notes.daily_brief(b.inst.fresh)["is_today"])
        notes.ensure_daily_brief(b)
        info3 = notes.daily_brief(b.inst.fresh)
        self.assertTrue(info3["is_today"])
        self.assertTrue(info3["empty"])
        self.assertEqual(info3["text"], "Sem novidades desde a última atualização.")

    def test_runner_nightly_skip_agent_creates_brief_and_render_all_preserves_it(self):
        b = _make_brain(self.tmp / "inst")
        res = runner.nightly(b, skip_agent=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["steps"]["brief"], "sem novidades")
        brief_path = b.inst.fresh / "notes" / "brief.md"
        self.assertTrue(brief_path.exists())

        # Rodar novamente no mesmo dia com brief já pronto retorna "ok" e preserva
        notes.write_note(b, "brief", "Brief gerado pelo agente.", kind="brief", empty=False)
        res2 = runner.nightly(b, skip_agent=True)
        self.assertEqual(res2["steps"]["brief"], "ok")
        self.assertEqual(notes.daily_brief(b.inst.fresh)["text"], "Brief gerado pelo agente.")

    def test_view_model_exposes_daily_brief_and_legacy_notes_compat(self):
        b = _make_brain(self.tmp / "inst")
        m_empty = render.view_model(b)
        self.assertEqual(m_empty["daily_brief"], {
            "exists": False, "is_today": False, "date": None,
            "generated_at": None, "empty": False, "text": "",
        })

        notes.write_note(b, "brief", "Resumo estruturado de hoje.", kind="brief", empty=False)
        legacy_path = b.inst.fresh / "notes" / "semana.md"
        legacy_path.write_text("# Semana\nConteúdo legado sem cabeçalho.\n", encoding="utf-8")

        render.render_all(b)
        self.assertTrue((b.inst.fresh / "notes" / "brief.md").exists())
        self.assertTrue(legacy_path.exists())

        m = render.view_model(b)
        self.assertTrue(m["daily_brief"]["exists"])
        self.assertTrue(m["daily_brief"]["is_today"])
        self.assertEqual(m["daily_brief"]["text"], "Resumo estruturado de hoje.")

        by_name = {n["name"]: n for n in m["notes"]}
        self.assertIn("brief", by_name)
        self.assertEqual(by_name["brief"]["text"], "Resumo estruturado de hoje.")
        self.assertTrue(by_name["brief"]["is_today"])
        self.assertIn("semana", by_name)
        self.assertEqual(by_name["semana"]["text"], "# Semana\nConteúdo legado sem cabeçalho.")
        self.assertIsNone(by_name["semana"]["date"])
        self.assertFalse(by_name["semana"]["is_today"])

    def test_update_skill_documents_daily_brief_step(self):
        skill = (ROOT / "commands" / "update" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("brain note write brief", skill)
        self.assertIn("FRESH/notes/", skill)
        self.assertIn("BRAIN_NIGHTLY=1", skill)


if __name__ == "__main__":
    unittest.main()
