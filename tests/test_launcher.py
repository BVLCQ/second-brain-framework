"""Ícone clicável do painel (`brain app install`) — stdlib unittest, sem rede. Hermético: tudo em tmp."""
from __future__ import annotations

import os
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import cli, config, launcher, setup, util              # noqa: E402


def _inst(tmp: Path):
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "logs").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
    return config.load(tmp)


def _fake_framework(tmp: Path) -> Path:
    fw = tmp / "fw"
    fw.mkdir()
    (fw / "brain").write_text(
        "import os, sys\n"
        "open(os.environ['STUB_OUT'], 'w').write(repr((sys.argv[1:], os.environ.get('BRAIN_HOME'), os.getcwd())))\n"
        "sys.exit(int(os.environ.get('STUB_RC', '0')))\n", encoding="utf-8")
    return fw


class IconTests(unittest.TestCase):
    def test_icon_assets_exist_and_are_clean(self):
        png = launcher.icon_png()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (512, 512))         # IHDR: 512×512
        for f in (launcher.ICON_SVG, launcher.ICON_MARK, launcher.ICON_HERO):
            svg = f.read_text(encoding="utf-8")
            self.assertTrue(svg.lstrip().startswith("<svg"), f.name)
            for bad in ("<script", "onload=", "<image", "href=\"http"):           # SVG versionado: sem script nem rede
                self.assertNotIn(bad, svg, f.name)

    def test_dashboard_brand_uses_the_mark_and_no_demo_tag(self):
        import base64
        from brainlib import render
        html = render.ASSET.read_text(encoding="utf-8")
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_assets", Path(launcher.__file__).parent.parent / "scripts" / "build_assets.py")
        ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)
        mark = "data:image/svg+xml;base64," + base64.b64encode(ba.mark_svg()).decode("ascii")
        self.assertIn(f'class="mark" src="{mark}"', html)                        # embutida: o painel abre offline
        self.assertNotIn('id="gen"', html)                                       # o "demo" ao lado do nome saiu

    def test_icns_container(self):
        png = launcher.icon_png()
        icns = launcher.build_icns({128: png, 256: png, 512: png})               # tamanho do PNG não importa p/ o contêiner
        self.assertEqual(icns[:4], b"icns")
        self.assertEqual(struct.unpack(">I", icns[4:8])[0], len(icns))
        pos, tags = 8, []
        while pos < len(icns):
            tag, n = struct.unpack(">4sI", icns[pos:pos + 8])
            self.assertEqual(icns[pos + 8:pos + 16], b"\x89PNG\r\n\x1a\n")
            tags.append(tag)
            pos += n
        self.assertEqual(pos, len(icns))
        self.assertEqual(tags, [t for t, _s in launcher.ICNS_TYPES])
        self.assertEqual(launcher.build_icns({512: png})[8:12], b"ic09")       # reserva sem sips: só o 512

    def test_icon_icns_falls_back_without_system_tools(self):
        with mock.patch.object(launcher.shutil, "which", return_value=None):
            icns = launcher.icon_icns()
        self.assertEqual(icns[:4], b"icns")
        self.assertEqual(icns[8:12], b"ic09")


class InstallTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.inst = _inst(self.tmp / "home")
        self.fw = _fake_framework(self.tmp)
        self.dest = self.tmp / "Applications"

    def tearDown(self):
        self._td.cleanup()

    def _install(self, **kw):
        return launcher.install(self.inst, self.dest, framework=self.fw, platform="darwin", **kw)

    def test_macos_bundle_layout(self):
        app = self._install()
        self.assertEqual(app.name, "Brain.app")
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        self.assertEqual(info["CFBundleExecutable"], "launcher")
        self.assertEqual(info["CFBundleIdentifier"], launcher.BUNDLE_ID)
        self.assertEqual(info["SegundoCerebroHome"], str(self.inst.root))
        exe = app / "Contents" / "MacOS" / "launcher"
        self.assertTrue(os.access(exe, os.X_OK))
        self.assertEqual((app / "Contents" / "Resources" / "AppIcon.icns").read_bytes()[:4], b"icns")
        self.assertEqual(subprocess.run(["sh", "-n", str(exe)]).returncode, 0)    # sintaxe do script
        self.assertEqual(list(self.dest.glob(".*.tmp")), [])                       # sem sobra do build

    def test_launcher_runs_brain_open_in_the_instance(self):
        exe = self._install() / "Contents" / "MacOS" / "launcher"
        out = self.tmp / "ran.txt"
        env = {**os.environ, "STUB_OUT": str(out), "HOME": str(self.tmp)}
        env.pop("BRAIN_HOME", None)
        r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        args, home, cwd = eval(out.read_text(encoding="utf-8"))
        self.assertEqual(args, ["open"])                                   # onboarding na 1ª vez, depois o painel
        self.assertEqual(home, str(self.inst.root))
        self.assertEqual(Path(cwd).resolve(), self.inst.root.resolve())

    def test_launcher_failure_is_logged_and_nonzero(self):
        exe = self._install(python=sys.executable) / "Contents" / "MacOS" / "launcher"
        body = exe.read_text(encoding="utf-8")
        # sem GUI nos testes: troca só o bloco do diálogo por um marcador, mantendo o fluxo de falha
        body = body[:body.index("osascript -")] + "echo FALHOU-NOTIFICADO >&2\nexit 1\n"
        exe.write_text(body, encoding="utf-8")
        env = {**os.environ, "STUB_OUT": str(self.tmp / "ran.txt"), "STUB_RC": "3"}
        r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FALHOU-NOTIFICADO", r.stderr)
        self.assertTrue((self.inst.logs / "app.log").exists())

    def test_reinstall_replaces_and_updates_home(self):
        app = self._install()
        (app / "Contents" / "stale.txt").write_text("x", encoding="utf-8")
        other = _inst(self.tmp / "other")
        again = launcher.install(other, self.dest, framework=self.fw, platform="darwin", replace_other=True)
        self.assertEqual(again, app)
        self.assertFalse((app / "Contents" / "stale.txt").exists())
        self.assertEqual(launcher.owner_of(app), str(other.root))

    def test_refuses_to_overwrite_foreign_app(self):
        foreign = self.dest / "Brain.app"
        (foreign / "Contents").mkdir(parents=True)
        (foreign / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.outro.app"}))
        with self.assertRaises(util.BrainError):
            self._install()
        with self.assertRaises(util.BrainError):
            launcher.uninstall(self.dest, platform="darwin")
        self.assertTrue(foreign.exists())                             # intocado

    def test_uninstall(self):
        app = self._install()
        self.assertEqual(launcher.uninstall(self.dest, platform="darwin"), app)
        self.assertFalse(app.exists())
        self.assertIsNone(launcher.uninstall(self.dest, platform="darwin"))

    def test_custom_name_and_name_validation(self):
        self.assertEqual(self._install(name="Meu Cérebro").name, "Meu Cérebro.app")
        for bad in ("", "../x", "a/b", ".oculto"):
            with self.assertRaises(util.BrainError):
                self._install(name=bad)

    def test_linux_desktop_entry(self):
        dest = self.tmp / "share" / "applications"
        entry = launcher.install(self.inst, dest, framework=self.fw, platform="linux")
        self.assertEqual(entry.name, "brain.desktop")
        text = entry.read_text(encoding="utf-8")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Terminal=false", text)
        script = self.tmp / "share" / "segundo-cerebro" / "launcher.sh"
        self.assertIn(f'Exec="{script}"', text)
        self.assertTrue(os.access(script, os.X_OK))
        self.assertEqual((self.tmp / "share" / "segundo-cerebro" / "icon.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(launcher.owner_of(entry), str(self.inst.root))
        self.assertEqual(launcher.uninstall(dest, platform="linux"), entry)
        self.assertFalse(script.exists())

    def test_vault_and_config_overrides_are_baked(self):
        os.environ["BRAIN_VAULT"] = str(self.tmp / "outro vault")
        try:
            body = (self._install() / "Contents" / "MacOS" / "launcher").read_text(encoding="utf-8")
        finally:
            del os.environ["BRAIN_VAULT"]
        self.assertIn("export BRAIN_VAULT='" + str(self.tmp / "outro vault") + "'", body)

    def test_is_installed_matches_instance(self):
        self._install()
        orig = launcher.default_dest
        launcher.default_dest = lambda platform=None: self.dest
        try:
            if sys.platform in launcher.SUPPORTED:
                # só macOS tem o nome .app; no Linux o nome do arquivo difere — conferimos o caminho do macOS
                if sys.platform == "darwin":
                    self.assertTrue(launcher.is_installed(self.inst.root))
                    self.assertFalse(launcher.is_installed(self.tmp / "outra"))
        finally:
            launcher.default_dest = orig


class CliAndSetupTests(unittest.TestCase):
    def test_cli_install_and_uninstall(self):
        if sys.platform not in launcher.SUPPORTED:
            self.skipTest("plataforma sem ícone")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            inst = _inst(tmp / "home")
            dest = tmp / "dest"
            old = os.environ.get("BRAIN_HOME")
            os.environ["BRAIN_HOME"] = str(inst.root)
            try:
                self.assertEqual(cli.main(["app", "install", "--dest", str(dest)]), 0)
                self.assertEqual(len(list(dest.iterdir())), 1)
                self.assertEqual(cli.main(["app", "uninstall", "--dest", str(dest)]), 0)
                self.assertEqual(list(dest.iterdir()), [])
            finally:
                if old is None:
                    os.environ.pop("BRAIN_HOME", None)
                else:
                    os.environ["BRAIN_HOME"] = old

    def test_setup_step_installs_in_auto_mode_and_is_idempotent(self):
        if sys.platform not in launcher.SUPPORTED:
            self.skipTest("plataforma sem ícone")
        step = next(s for s in setup.STEPS if s["id"] == "painel")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            inst = _inst(tmp / "home")
            said, calls = [], []

            class _UI(setup.AutoUI):
                def say(self, msg):
                    said.append(msg)

            class _B:
                pass
            _B.inst = inst
            orig_default, orig_install = launcher.default_dest, launcher.install
            launcher.default_dest = lambda platform=None: tmp / "apps"          # nada na máquina real
            launcher.install = lambda i, *a, **k: calls.append(1) or orig_install(i, tmp / "apps", **k)
            try:
                self.assertEqual(step["status"](_B), "pending")
                step["run"](_B, _UI())                                          # --yes: cria
                self.assertEqual(calls, [1])
                self.assertEqual(step["status"](_B), "done")
                step["run"](_B, _UI())                                          # de novo: não recria
                self.assertEqual(calls, [1])
                self.assertIn("já instalado", said[-1])
            finally:
                launcher.default_dest, launcher.install = orig_default, orig_install


class PinShortcutTests(unittest.TestCase):
    """Atalho de um clique: Dock no macOS, .desktop na área de trabalho no Linux. Idempotente e honesto."""

    def test_dock_tile_fragment_is_a_well_formed_plist(self):
        """O fragmento tem que PARSEAR — tile-type dentro do tile. Um fragmento malformado já escapou
        da suíte uma vez (defaults grava amputado e o pill mentia 'pronto'); nunca de novo."""
        frag = launcher._DOCK_TILE.format(app="/Applications/Brain.app")
        tile = plistlib.loads(f"<plist><array>{frag}</array></plist>".encode())[0]
        self.assertEqual(tile["tile-type"], "file-tile")
        self.assertEqual(tile["tile-data"]["file-data"]["_CFURLString"], "/Applications/Brain.app")

    def test_macos_pins_installed_app_once(self):
        tiles: list[dict] = []

        def fake_tiles():
            return list(tiles)

        def fake_write(argv, **kw):
            if not argv[0].endswith("defaults"):                      # killall Dock: só sucesso
                return subprocess.CompletedProcess(argv, 0, "", "")
            tiles.append(plistlib.loads(f"<plist><array>{argv[-1]}</array></plist>".encode())[0])

        with mock.patch.object(launcher, "_find_ours", return_value=[Path("/Applications/Brain.app")]), \
             mock.patch.object(launcher, "_platform", return_value="darwin"), \
             mock.patch.object(launcher, "_dock_tiles", side_effect=fake_tiles), \
             mock.patch("subprocess.run", side_effect=fake_write) as run:
            self.assertIn("pregado no Dock", launcher.pin_shortcut())
            self.assertIn("já está no Dock", launcher.pin_shortcut())       # idempotente: segunda vez não escreve
            self.assertEqual(run.call_count, 2)                             # write + killall, uma vez só

    def test_macos_typeless_tile_from_old_bug_does_not_count_and_is_healed(self):
        """Tile nosso sem tile-type (fragmento bugado do a272072) NÃO é 'já está' — o pin reescreve."""
        wounded = {"tile-data": {"file-data": {"_CFURLString": "/Applications/Brain.app",
                                               "_CFURLStringType": 0}}}     # sem tile-type
        written: list[dict] = []

        def fake_write(argv, **kw):
            if not argv[0].endswith("defaults"):                      # killall Dock: só sucesso
                return subprocess.CompletedProcess(argv, 0, "", "")
            written.append(plistlib.loads(f"<plist><array>{argv[-1]}</array></plist>".encode())[0])

        with mock.patch.object(launcher, "_find_ours", return_value=[Path("/Applications/Brain.app")]), \
             mock.patch.object(launcher, "_platform", return_value="darwin"), \
             mock.patch.object(launcher, "_dock_tiles", return_value=[wounded]), \
             mock.patch("subprocess.run", side_effect=fake_write):
            self.assertIn("pregado no Dock", launcher.pin_shortcut())      # cura, não "já está"
            self.assertEqual(written[0]["tile-type"], "file-tile")

    def test_macos_without_app_refuses(self):
        with mock.patch.object(launcher, "_find_ours", return_value=[]), \
             mock.patch.object(launcher, "_platform", return_value="darwin"):
            with self.assertRaises(util.BrainError):
                launcher.pin_shortcut()

    def test_linux_copies_desktop_entry(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "Desktop").mkdir()
            src = home / ".local/share/applications/brain.desktop"
            src.parent.mkdir(parents=True)
            src.write_text("[Desktop Entry]\nName=Brain\n", encoding="utf-8")
            with mock.patch.object(launcher, "_find_ours", return_value=[src]), \
                 mock.patch.object(launcher, "_platform", return_value="linux"), \
                 mock.patch.object(Path, "home", return_value=home):
                self.assertIn("área de trabalho", launcher.pin_shortcut())
            dst = home / "Desktop" / "brain.desktop"
            self.assertTrue(dst.exists())
            self.assertEqual(dst.stat().st_mode & 0o111, 0o111)             # executável

    def test_linux_pin_marks_the_desktop_entry_trusted_for_gnome(self):
        calls: list = []
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "Desktop").mkdir()
            src = home / ".local/share/applications/brain.desktop"
            src.parent.mkdir(parents=True)
            src.write_text("[Desktop Entry]\nName=Brain\n", encoding="utf-8")
            with mock.patch.object(launcher, "_find_ours", return_value=[src]), \
                 mock.patch.object(launcher, "_platform", return_value="linux"), \
                 mock.patch.object(Path, "home", return_value=home), \
                 mock.patch.object(launcher.shutil, "which", return_value="/usr/bin/gio"), \
                 mock.patch("subprocess.run") as run:
                launcher.pin_shortcut()
            gio = [c for c in run.call_args_list if "gio" in str(c.args[0][0])]
            self.assertTrue(gio, "precisa marcar metadata::trusted pro GNOME")
            self.assertIn("metadata::trusted", " ".join(gio[0].args[0]))

    def test_pin_status_requires_a_well_formed_tile(self):
        good = {"tile-type": "file-tile", "tile-data": {"file-data": {"_CFURLString": "/Applications/Brain.app"}}}
        # forma que o próprio Dock normaliza depois de um reload (vista na máquina real):
        docked = {"tile-type": "file-tile",
                  "tile-data": {"file-data": {"_CFURLString": "file:///Applications/Brain.app/", "_CFURLStringType": 15}}}
        wounded = {"tile-data": {"file-data": {"_CFURLString": "/Applications/Brain.app"}}}
        with mock.patch.object(launcher, "_platform", return_value="darwin"):
            for tiles in ([good], [docked]):
                with mock.patch.object(launcher, "_dock_tiles", return_value=tiles):
                    self.assertTrue(launcher.pin_status())
            with mock.patch.object(launcher, "_dock_tiles", return_value=[wounded]):
                self.assertFalse(launcher.pin_status())
            with mock.patch.object(launcher, "_dock_tiles", return_value=[]):
                self.assertFalse(launcher.pin_status())


if __name__ == "__main__":
    unittest.main()
