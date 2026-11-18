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


if __name__ == "__main__":
    unittest.main()
