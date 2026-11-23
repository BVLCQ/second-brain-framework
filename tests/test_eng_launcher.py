"""Testes de proteção multi-instância e superfícies globais do launcher e do comando `brain`."""
from __future__ import annotations

import contextlib
import io
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import launcher, setup, util  # noqa: E402


def _make_inst(root: Path) -> SimpleNamespace:
    root.mkdir(parents=True, exist_ok=True)
    logs = root / "vault" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    brain = root / "brain"
    brain.write_text("#!/bin/sh\n", encoding="utf-8")
    brain.chmod(0o755)
    return SimpleNamespace(root=root, logs=logs)


def _make_fw(tmp: Path) -> Path:
    fw = tmp / "fw"
    fw.mkdir(parents=True, exist_ok=True)
    (fw / "brain").write_text("#!/bin/sh\n", encoding="utf-8")
    return fw


class _CaptureUI(setup.ConsoleUI):
    def __init__(self):
        self.interactive = False
        self.said: list[str] = []

    def say(self, msg: str) -> None:
        self.said.append(msg)


class TestBrainCommandGuard(unittest.TestCase):
    def test_refuses_regular_file_without_deleting(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            home = tmp / "home"
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            existing = bin_dir / "brain"
            original = "#!/bin/sh\necho outro\n"
            existing.write_text(original, encoding="utf-8")
            inst = _make_inst(tmp / "inst")

            with mock.patch.object(Path, "home", return_value=home), \
                 mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}/usr/bin"}):
                ui1 = _CaptureUI()
                res1 = setup.install_brain_command(inst.root, ui1)
                self.assertIsNone(res1)
                self.assertEqual(existing.read_text(encoding="utf-8"), original)
                self.assertFalse(existing.is_symlink())
                self.assertTrue(any("⚠" in m and str(existing) in m and "brain setup --only comando" in m for m in ui1.said))

                ui2 = _CaptureUI()
                res2 = setup.install_brain_command(inst.root, ui2, replace=True)
                self.assertIsNone(res2)
                self.assertEqual(existing.read_text(encoding="utf-8"), original)
                self.assertFalse(existing.is_symlink())
                self.assertTrue(any("⚠" in m and str(existing) in m and "brain setup --only comando" in m for m in ui2.said))

    def test_replaces_broken_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            home = tmp / "home"
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            link = bin_dir / "brain"
            link.symlink_to("/nao/existe/brain")
            self.assertTrue(link.is_symlink())
            self.assertFalse(link.exists())
            inst = _make_inst(tmp / "inst")

            with mock.patch.object(Path, "home", return_value=home), \
                 mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}/usr/bin"}):
                ui = _CaptureUI()
                res = setup.install_brain_command(inst.root, ui)
                self.assertEqual(res, str(link))
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), (inst.root / "brain").resolve())


class TestLauncherCleanup(unittest.TestCase):
    def test_skips_other_instance_copy_with_warning(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_a = _make_inst(tmp / "inst-a")
            inst_b = _make_inst(tmp / "inst-b")
            dest_main = tmp / "Applications"
            dest_alt = tmp / "UserApplications"

            app_a = launcher.install(inst_a, dest=dest_alt, framework=fw, platform="darwin")
            buf = io.StringIO()
            with mock.patch.object(launcher, "default_dest", return_value=dest_main), \
                 mock.patch.object(launcher, "_search_dests", return_value=[dest_main, dest_alt]), \
                 contextlib.redirect_stdout(buf):
                app_b = launcher.install(inst_b, dest=None, framework=fw, platform="darwin")

            self.assertTrue(app_a.exists())
            self.assertEqual(launcher.owner_of(app_a), str(inst_a.root))
            self.assertTrue(app_b.exists())
            self.assertEqual(app_b.parent.resolve(), dest_main.resolve())
            self.assertEqual(launcher.owner_of(app_b), str(inst_b.root))
            out = buf.getvalue()
            self.assertIn("⚠", out)
            self.assertIn(str(inst_a.root), out)

    def test_removes_own_old_copy_in_alt_dest(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_b = _make_inst(tmp / "inst-b")
            dest_main = tmp / "Applications"
            dest_alt = tmp / "UserApplications"

            old_alt = launcher.install(inst_b, dest=dest_alt, framework=fw, platform="darwin")
            old_legacy = launcher.install(inst_b, dest=dest_main, name="Segundo Cérebro", framework=fw, platform="darwin")
            with mock.patch.object(launcher, "default_dest", return_value=dest_main), \
                 mock.patch.object(launcher, "_search_dests", return_value=[dest_main, dest_alt]):
                new_app = launcher.install(inst_b, dest=None, framework=fw, platform="darwin")

            self.assertTrue(new_app.exists())
            self.assertFalse(old_alt.exists())
            self.assertFalse(old_legacy.exists())

    def test_never_touches_unknown_owner_copy(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_b = _make_inst(tmp / "inst-b")
            dest_main = tmp / "Applications"
            dest_alt = tmp / "UserApplications"
            unknown = dest_alt / "Brain.app"
            (unknown / "Contents").mkdir(parents=True)
            (unknown / "Contents" / "Info.plist").write_bytes(
                plistlib.dumps({"CFBundleIdentifier": launcher.BUNDLE_ID})
            )
            self.assertEqual(launcher.owner_of(unknown), "")

            with mock.patch.object(launcher, "default_dest", return_value=dest_main), \
                 mock.patch.object(launcher, "_search_dests", return_value=[dest_main, dest_alt]):
                app_b = launcher.install(inst_b, dest=None, framework=fw, platform="darwin")

            self.assertTrue(app_b.exists())
            self.assertTrue(unknown.exists())


class TestDockPinByOwner(unittest.TestCase):
    def test_dock_tile_of_other_instance_is_not_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_a = _make_inst(tmp / "inst-a")
            inst_b = _make_inst(tmp / "inst-b")
            dir_a = tmp / "apps-a"
            dir_b = tmp / "apps-b"
            app_a = launcher.install(inst_a, dest=dir_a, framework=fw, platform="darwin")
            launcher.install(inst_b, dest=dir_b, name="Brain B", framework=fw, platform="darwin")

            tiles = [{"tile-type": "file-tile", "tile-data": {"file-data": {"_CFURLString": f"file://{app_a}/"}}}]
            with mock.patch.object(launcher, "_dock_tiles", return_value=tiles):
                self.assertFalse(launcher.pin_status(root=inst_b.root, platform="darwin"))
                self.assertEqual(launcher.docked_other(inst_b.root, platform="darwin"), str(inst_a.root))

    def test_pins_our_app_when_other_instance_docked(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_a = _make_inst(tmp / "inst-a")
            inst_b = _make_inst(tmp / "inst-b")
            dir_a = tmp / "apps-a"
            dir_b = tmp / "apps-b"
            app_a = launcher.install(inst_a, dest=dir_a, framework=fw, platform="darwin")
            app_b = launcher.install(inst_b, dest=dir_b, name="Brain B", framework=fw, platform="darwin")

            tiles = [{"tile-type": "file-tile", "tile-data": {"file-data": {"_CFURLString": f"file://{app_a}/"}}}]
            calls: list[list[str]] = []

            def fake_run(argv, **kw):
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "", "")

            with mock.patch.object(launcher, "_dock_tiles", return_value=tiles), \
                 mock.patch.object(launcher, "_search_dests", return_value=[dir_b]):
                msg = launcher.pin_shortcut(root=inst_b.root, platform="darwin", run=fake_run)

            self.assertIn("Brain B", msg)
            defaults_calls = [c for c in calls if c[0].endswith("defaults")]
            self.assertEqual(len(defaults_calls), 1)
            self.assertIn(str(app_b), defaults_calls[0][-1])
            self.assertNotIn(str(app_a), defaults_calls[0][-1])

    def test_percent_encoded_file_url_matches_owner(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_b = _make_inst(tmp / "inst-b")
            dest = tmp / "apps"
            app = launcher.install(inst_b, dest=dest, name="Meu Brain", framework=fw, platform="darwin")
            encoded = str(app).replace(" ", "%20")
            tiles = [{"tile-type": "file-tile", "tile-data": {"file-data": {"_CFURLString": f"file://{encoded}/"}}}]

            with mock.patch.object(launcher, "_dock_tiles", return_value=tiles):
                self.assertTrue(launcher.pin_status(root=inst_b.root, platform="darwin"))

    def test_missing_dock_tile_app_does_not_count_as_other_or_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            inst_b = _make_inst(tmp / "inst-b")
            tiles = [{"tile-type": "file-tile", "tile-data": {"file-data": {"_CFURLString": f"file://{tmp / 'Ghost.app'}/"}}}]
            with mock.patch.object(launcher, "_dock_tiles", return_value=tiles):
                self.assertFalse(launcher.pin_status(root=inst_b.root, platform="darwin"))
                self.assertIsNone(launcher.docked_other(inst_b.root, platform="darwin"))

    def test_pin_shortcut_raises_when_only_other_instance_in_dock(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_a = _make_inst(tmp / "inst-a")
            inst_b = _make_inst(tmp / "inst-b")
            dir_a = tmp / "apps-a"
            dir_b = tmp / "apps-b"
            dir_b.mkdir()
            app_a = launcher.install(inst_a, dest=dir_a, framework=fw, platform="darwin")
            tiles = [{"tile-type": "file-tile", "tile-data": {"file-data": {"_CFURLString": f"file://{app_a}/"}}}]

            with mock.patch.object(launcher, "_dock_tiles", return_value=tiles), \
                 mock.patch.object(launcher, "_search_dests", return_value=[dir_b]):
                def _no_subprocess(*args, **kwargs):
                    self.fail("pin_shortcut chamou subprocess com o Dock de outra instância no caminho")
                with self.assertRaises(util.BrainError) as ctx:
                    launcher.pin_shortcut(root=inst_b.root, platform="darwin", run=_no_subprocess)
                self.assertIn(str(inst_a.root), str(ctx.exception))

    def test_linux_desktop_pin_by_owner(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            home = tmp / "home"
            desktop = home / "Desktop"
            apps = home / ".local" / "share" / "applications"
            desktop.mkdir(parents=True)
            inst_a = _make_inst(tmp / "inst-a")
            inst_b = _make_inst(tmp / "inst-b")
            entry_a = launcher.install(inst_a, dest=apps, name="Brain A", framework=fw, platform="linux")
            entry_b = launcher.install(inst_b, dest=apps, name="Meu Brain", framework=fw, platform="linux")
            (desktop / entry_a.name).write_text(entry_a.read_text(encoding="utf-8"), encoding="utf-8")

            calls: list[list[str]] = []

            def fake_run(argv, **kw):
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "", "")

            with mock.patch.object(Path, "home", return_value=home), \
                 mock.patch.object(launcher, "_search_dests", return_value=[apps]):
                self.assertFalse(launcher.pin_status(root=inst_b.root, platform="linux"))
                self.assertEqual(launcher.docked_other(inst_b.root, platform="linux"), str(inst_a.root))
                msg = launcher.pin_shortcut(root=inst_b.root, platform="linux", run=fake_run)
                self.assertIn("meu-brain", msg)
                self.assertTrue((desktop / entry_b.name).exists())
                self.assertTrue(launcher.pin_status(root=inst_b.root, platform="linux"))


class TestSessionEnvOmit(unittest.TestCase):
    def test_warns_and_omits_brain_vault_and_config(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst = _make_inst(tmp / "inst")
            dest = tmp / "apps"
            buf = io.StringIO()

            with mock.patch.dict(os.environ, {
                "BRAIN_VAULT": "/tmp/desvio/v",
                "BRAIN_CONFIG": "/tmp/desvio/c",
            }), contextlib.redirect_stdout(buf):
                app = launcher.install(inst, dest=dest, framework=fw, platform="darwin")

            body = (app / "Contents" / "MacOS" / "launcher").read_text(encoding="utf-8")
            self.assertNotIn("BRAIN_VAULT", body)
            self.assertNotIn("BRAIN_CONFIG", body)
            self.assertNotIn("/tmp/desvio/", body)
            self.assertIn(f"BRAIN_HOME={inst.root}", body)
            out = buf.getvalue()
            lines = out.splitlines()
            self.assertTrue(any("⚠" in ln and "BRAIN_VAULT" in ln for ln in lines))
            self.assertTrue(any("⚠" in ln and "BRAIN_CONFIG" in ln for ln in lines))


class TestFindForInstance(unittest.TestCase):
    def test_finds_custom_named_app_by_owner(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_a = _make_inst(tmp / "inst-a")
            inst_b = _make_inst(tmp / "inst-b")

            dest_mac = tmp / "apps-mac"
            launcher.install(inst_a, dest=dest_mac, name="Outro", framework=fw, platform="darwin")
            app_b = launcher.install(inst_b, dest=dest_mac, name="Meu Brain", framework=fw, platform="darwin")
            with mock.patch.object(launcher, "_search_dests", return_value=[dest_mac]):
                self.assertEqual(launcher.find_for_instance(inst_b.root, platform="darwin"), [app_b])

            dest_lin = tmp / "apps-lin" / "applications"
            launcher.install(inst_a, dest=dest_lin, name="Outro", framework=fw, platform="linux")
            entry_b = launcher.install(inst_b, dest=dest_lin, name="Meu Brain", framework=fw, platform="linux")
            with mock.patch.object(launcher, "_search_dests", return_value=[dest_lin]):
                self.assertEqual(launcher.find_for_instance(inst_b.root, platform="linux"), [entry_b])

    def test_find_for_instance_orders_default_first_then_lex(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst = _make_inst(tmp / "inst")
            dest = tmp / "apps"
            app_z = launcher.install(inst, dest=dest, name="Zeta", framework=fw, platform="darwin")
            app_a = launcher.install(inst, dest=dest, name="Alpha", framework=fw, platform="darwin")
            app_def = launcher.install(inst, dest=dest, name=launcher.DEFAULT_NAME, framework=fw, platform="darwin")
            with mock.patch.object(launcher, "_search_dests", return_value=[dest]):
                self.assertEqual(
                    launcher.find_for_instance(inst.root, platform="darwin"),
                    [app_def, app_a, app_z],
                )

    def test_is_installed_finds_our_app_in_alt_dest_even_when_main_has_other_instance(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td).resolve()
            fw = _make_fw(tmp)
            inst_a = _make_inst(tmp / "inst-a")
            inst_b = _make_inst(tmp / "inst-b")
            dest_main = tmp / "Applications"
            dest_alt = tmp / "UserApplications"
            launcher.install(inst_a, dest=dest_main, framework=fw, platform="darwin")
            launcher.install(inst_b, dest=dest_alt, framework=fw, platform="darwin")

            with mock.patch.object(launcher, "_platform", return_value="darwin"), \
                 mock.patch.object(launcher, "_search_dests", return_value=[dest_main, dest_alt]):
                self.assertTrue(launcher.is_installed(inst_b.root))
                self.assertTrue(launcher.is_installed(inst_a.root))


if __name__ == "__main__":
    unittest.main()
