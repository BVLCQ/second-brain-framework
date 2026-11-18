"""Multi-instância na mesma máquina: agendamento por instância (launchd/cron), symlink `brain` e app Brain (#9)."""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, doctor, launcher, runner, setup  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n'
        '[outbound]\nallow = ["marina-demo", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n"
        "- [ ] PROJ-1.2 Outro · prazo: 2026-11-01\n", encoding="utf-8")
    fake = tmp / "brain"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class _UI(setup.ConsoleUI):
    def __init__(self, *, interactive: bool, confirm_ans: bool = False):
        self.interactive = interactive
        self.confirm_ans = confirm_ans
        self.said: list[str] = []

    def say(self, msg: str) -> None:
        self.said.append(msg)

    def confirm(self, prompt: str, default: bool = False) -> bool:
        return self.confirm_ans


class MultiInstanceTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.root_a = self.tmp / "inst-a"
        self.root_b = self.tmp / "inst-b"
        self.brain_a = _brain(self.root_a)
        self.brain_b = _brain(self.root_b)
        self.calls: list[tuple[str, ...]] = []

        def fake_launchctl(*a, **kw):
            self.calls.append(tuple(a))
            return subprocess.CompletedProcess(["launchctl", *a], 0, "", "")

        self._p_env = mock.patch.dict(os.environ, {"HOME": str(self.home), "BRAIN_NOW": "2026-10-09T10:00:00-03:00"})
        self._p_ld = mock.patch.object(runner, "_use_launchd", return_value=True)
        self._p_ctl = mock.patch.object(runner, "_launchctl", side_effect=fake_launchctl)
        self._p_cron = mock.patch.object(runner, "_crontab", return_value=[])
        self._p_env.start()
        self._p_ld.start()
        self._p_ctl.start()
        self._p_cron.start()

    def tearDown(self):
        self._p_cron.stop()
        self._p_ctl.stop()
        self._p_ld.stop()
        self._p_env.stop()
        self._td.cleanup()

    def test_launchd_per_instance_plists_and_scheduled_here(self):
        self.assertFalse(runner.scheduled_here(self.root_a))
        self.assertFalse(runner.scheduled_here(self.root_b))

        with contextlib.redirect_stdout(io.StringIO()):
            runner.schedule_cli(argparse.Namespace(action="install", time="05:00"), self.brain_a)
        plist_a = runner._launchd_plist(self.root_a)
        self.assertTrue(plist_a.exists())
        data_a = plistlib.loads(plist_a.read_bytes())
        self.assertEqual(data_a["Label"], runner.launchd_label(self.root_a))
        self.assertTrue(runner.scheduled_here(self.root_a))
        self.assertFalse(runner.scheduled_here(self.root_b))
        self.assertTrue(setup.nightly_installed(self.root_a))
        self.assertFalse(setup.nightly_installed(self.root_b))

        with contextlib.redirect_stdout(io.StringIO()):
            runner.schedule_cli(argparse.Namespace(action="install", time="06:00"), self.brain_b)
        plist_b = runner._launchd_plist(self.root_b)
        self.assertTrue(plist_a.exists())
        self.assertTrue(plist_b.exists())
        self.assertNotEqual(plist_a, plist_b)
        self.assertTrue(runner.scheduled_here(self.root_a))
        self.assertTrue(runner.scheduled_here(self.root_b))

    def test_legacy_plist_detection_and_migration_only_by_owner(self):
        legacy = runner._launchd_plist(None)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(plistlib.dumps({
            "Label": runner.LAUNCHD_LABEL,
            "ProgramArguments": [str(self.root_a / "brain"), "nightly"],
        }))

        self.assertTrue(runner.scheduled_here(self.root_a))
        self.assertFalse(runner.scheduled_here(self.root_b))
        self.assertIsNone(runner.foreign_schedule(self.root_a))
        self.assertEqual(runner.foreign_schedule(self.root_b), self.root_a)

        # Instalar B mantém o plist legado de A intocado
        self.calls.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            runner.schedule_cli(argparse.Namespace(action="install", time="06:00"), self.brain_b)
        self.assertTrue(legacy.exists())
        self.assertFalse(any(c[0] == "bootout" and runner.LAUNCHD_LABEL in c[1]
                             and not c[1].endswith(runner.launchd_label(self.root_b)) for c in self.calls))

        # Instalar A migra e remove o plist legado, registrando o bootout
        self.calls.clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            runner.schedule_cli(argparse.Namespace(action="install", time="05:30"), self.brain_a)
        self.assertFalse(legacy.exists())
        self.assertTrue(runner._launchd_plist(self.root_a).exists())
        self.assertIn(("bootout", f"gui/{os.getuid()}/{runner.LAUNCHD_LABEL}"), self.calls)
        self.assertIn("migrado", buf.getvalue())

    def test_cron_branch_keeps_other_instance_lines(self):
        cron_lines: list[str] = []

        def fake_run(cmd, **kw):
            if cmd == ["crontab", "-"]:
                cron_lines.clear()
                cron_lines.extend(ln for ln in (kw.get("input") or "").splitlines() if ln.strip())
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(runner, "_use_launchd", return_value=False), \
                mock.patch.object(runner, "_crontab", side_effect=lambda: list(cron_lines)), \
                mock.patch.object(runner.shutil, "which", return_value="/usr/bin/crontab"):
            with contextlib.redirect_stdout(io.StringIO()):
                runner.schedule_cli(argparse.Namespace(action="install", time="05:00"), self.brain_a, run=fake_run)
            self.assertEqual(len(cron_lines), 1)
            line_a = cron_lines[0]
            self.assertTrue(runner.scheduled_here(self.root_a))
            self.assertFalse(runner.scheduled_here(self.root_b))

            with contextlib.redirect_stdout(io.StringIO()):
                runner.schedule_cli(argparse.Namespace(action="install", time="06:15"), self.brain_b, run=fake_run)
            self.assertEqual(len(cron_lines), 2)
            self.assertIn(line_a, cron_lines)
            self.assertTrue(runner.scheduled_here(self.root_a))
            self.assertTrue(runner.scheduled_here(self.root_b))

            with contextlib.redirect_stdout(io.StringIO()):
                runner.schedule_cli(argparse.Namespace(action="remove", time="05:00"), self.brain_b, run=fake_run)
            self.assertEqual(cron_lines, [line_a])
            self.assertTrue(runner.scheduled_here(self.root_a))
            self.assertFalse(runner.scheduled_here(self.root_b))

    def test_symlink_does_not_repoint_without_confirmation_except_dangling(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        link = bin_dir / "brain"
        link.symlink_to(self.root_a / "brain")
        with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}):
            self.assertEqual(setup._st_comando(self.brain_a), "done")
            self.assertEqual(setup._st_comando(self.brain_b), "warn")

            # Não-interativo: mantém apontando para A e avisa com ⚠
            ui_non = _UI(interactive=False, confirm_ans=True)
            setup._run_comando(self.brain_b, ui_non)
            self.assertEqual(link.resolve(), (self.root_a / "brain").resolve())
            self.assertTrue(any("⚠" in s and str(self.root_a) in s for s in ui_non.said))

            # Interativo com confirm=True: troca para B
            ui_yes = _UI(interactive=True, confirm_ans=True)
            setup._run_comando(self.brain_b, ui_yes)
            self.assertEqual(link.resolve(), (self.root_b / "brain").resolve())
            self.assertEqual(setup._st_comando(self.brain_b), "done")

            # Link quebrado (dangling): re-aponta sem perguntar
            link.unlink()
            link.symlink_to(self.tmp / "sumiu" / "brain")
            self.assertTrue(link.is_symlink())
            self.assertFalse(link.exists())
            ui_dangling = _UI(interactive=False, confirm_ans=False)
            setup._run_comando(self.brain_a, ui_dangling)
            self.assertEqual(link.resolve(), (self.root_a / "brain").resolve())
            self.assertTrue(any("✓" in s for s in ui_dangling.said))

    def test_doctor_in_b_reports_foreign_legacy_plist_from_a(self):
        legacy = runner._launchd_plist(None)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(plistlib.dumps({
            "Label": runner.LAUNCHD_LABEL,
            "ProgramArguments": [str(self.root_a / "brain"), "nightly"],
        }))
        checks = doctor.checks(self.brain_b)
        noturno = next(c for c in checks if c["title"] == "noturno")
        self.assertEqual(noturno["level"], "warn")
        self.assertIn(str(self.root_a), noturno["detail"])
        self.assertIn("não tem noturno", noturno["detail"])
        self.assertEqual(doctor.fix_for(noturno), {"label": "agendar o noturno", "sys": "sys:schedule"})

    def test_app_install_does_not_touch_target_owned_by_other_instance(self):
        dest = self.tmp / "Applications"
        fw = self.tmp / "fw"
        fw.mkdir()
        (fw / "brain").write_text("#!/bin/sh\n", encoding="utf-8")
        app = launcher.install(self.brain_a.inst, dest, framework=fw, platform="darwin")
        marker = app / "Contents" / "marker.txt"
        marker.write_text("da-instancia-a", encoding="utf-8")

        with mock.patch.object(launcher, "owner_of", return_value=str(self.root_a)):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                launcher.install(self.brain_b.inst, dest, framework=fw, platform="darwin", replace_other=None)
        self.assertTrue(marker.exists())
        self.assertIn("⚠", buf.getvalue())
        self.assertEqual(launcher.owner_of(app), str(self.root_a))


if __name__ == "__main__":
    unittest.main()
