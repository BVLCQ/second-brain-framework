"""No Windows, abrir arquivo do vault não passa por `cmd /c start`: nomes com `&`, `|`, `^` não viram comando (#130)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import opener, util                                     # noqa: E402

META = "a&b|c^d.md"          # nome que o cmd.exe interpretaria como comandos extras
CFG = {"tui": {"open": {"md": "Cursor"}}}


class _FakeShell32:
    def __init__(self, rc: int = 42):
        self.rc, self.calls = rc, []

    def ShellExecuteW(self, *args):
        self.calls.append(args)
        return self.rc


class WindowsArgvTest(unittest.TestCase):
    def test_argv_for_never_builds_a_cmd_line_on_windows(self):
        for cfg in (CFG, {}):
            for name in ("a.md", META):
                with self.subTest(cfg=cfg, name=name):
                    self.assertEqual(opener.argv_for(cfg, Path("C:/v") / name, "win32"), [])

    def test_shellexecute_passes_the_path_verbatim_without_a_shell(self):
        fake = _FakeShell32()
        path = Path("C:/v") / META
        opener._shellexecute(path, "Cursor", shell32=fake)
        opener._shellexecute(path, "", shell32=fake)
        self.assertEqual(fake.calls, [
            (None, "open", "Cursor", f'"{path}"', None, 1),   # app configurado: o caminho vai como parâmetro, cru
            (None, "open", str(path), None, None, 1),         # sem app: abre o arquivo pelo associador do sistema
        ])
        for call in fake.calls:
            self.assertNotIn("cmd", [a for a in call if isinstance(a, str)])

    def test_shellexecute_treats_small_return_codes_as_failure(self):
        fake = _FakeShell32(rc=31)
        with self.assertRaises(OSError):
            opener._shellexecute(Path("C:/v/a.md"), "Cursor", shell32=fake)
        self.assertEqual(fake.calls and fake.calls[0][3], '"C:/v/a.md"')


class WindowsOpenFileTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        vault = Path(self._td.name)
        (vault / META).write_text("x", encoding="utf-8")
        self.inst = SimpleNamespace(vault=vault, cfg=CFG)
        self.path = opener.resolve(self.inst, META)      # resolvido (o macOS symlinka /var → /private/var)

    def test_open_file_on_windows_never_spawns_a_process(self):
        with mock.patch.object(opener.sys, "platform", "win32"), \
                mock.patch.object(opener, "_shellexecute") as sh, \
                mock.patch.object(opener.subprocess, "Popen") as popen:
            self.assertEqual(opener.open_file(self.inst, META), "Cursor")
        sh.assert_called_once_with(self.path, "Cursor")
        popen.assert_not_called()

    def test_open_file_without_configured_app_uses_the_system_association(self):
        self.inst.cfg = {}
        with mock.patch.object(opener.sys, "platform", "win32"), \
                mock.patch.object(opener, "_shellexecute", side_effect=lambda p, app="": self.assertEqual(app, "")):
            self.assertEqual(opener.open_file(self.inst, META), "padrão do sistema")

    def test_windows_failure_is_a_brain_error(self):
        with mock.patch.object(opener.sys, "platform", "win32"), \
                mock.patch.object(opener, "_shellexecute", side_effect=OSError("ShellExecuteW retornou 5")):
            with self.assertRaises(util.BrainError) as cm:
                opener.open_file(self.inst, META)
        self.assertEqual(cm.exception.code, 4)

    def test_unix_platforms_keep_spawning_argv(self):
        with mock.patch.object(opener.sys, "platform", "darwin"), \
                mock.patch.object(opener, "_shellexecute") as sh, \
                mock.patch.object(opener.subprocess, "Popen") as popen:
            self.assertEqual(opener.open_file(self.inst, META), "Cursor")
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["open", "-a", "Cursor", str(self.path)])
        sh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
