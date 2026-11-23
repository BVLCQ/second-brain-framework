"""Testes para Abrir o Brain.command e endurecimento de install.sh (#71, #81)."""
from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CMD_SRC = ROOT / "Abrir o Brain.command"
INSTALL_SRC = ROOT / "install.sh"

_BASE_TOOLS = ("sh", "id", "mktemp", "rm", "tr", "dirname", "grep", "cat", "touch")


def _make_stub(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _populate_base_bin(bin_dir: Path) -> None:
    for tool in _BASE_TOOLS:
        resolved = shutil.which(tool)
        if resolved:
            target = bin_dir / tool
            if not target.exists():
                target.symlink_to(resolved)


class _IsolatedShellTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._root_tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._root_tmp.name)
        self.bin_dir = self.tmp / "bin"
        self.bin_dir.mkdir()
        _populate_base_bin(self.bin_dir)
        self.home_dir = self.tmp / "home"
        self.home_dir.mkdir()
        self.tmpdir = self.tmp / "tmpdir"
        self.tmpdir.mkdir()

    def tearDown(self) -> None:
        self._root_tmp.cleanup()

    def _base_env(self) -> dict[str, str]:
        return {
            "PATH": str(self.bin_dir),
            "HOME": str(self.home_dir),
            "TMPDIR": str(self.tmpdir),
            "USER": "marina-demo",
        }


class TestCommandEntry(_IsolatedShellTestCase):
    def test_sh_syntax_both_scripts(self) -> None:
        for script in (CMD_SRC, INSTALL_SRC):
            res = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"sh -n falhou em {script.name}: {res.stderr}")

    def test_stub_git_skips_init_and_delegates_to_install_sh(self) -> None:
        work = self.tmp / "zip-extract"
        work.mkdir()
        cmd_copy = work / "Abrir o Brain.command"
        shutil.copy2(CMD_SRC, cmd_copy)

        marker = work / "install_called.txt"
        init_forbidden = work / "git_init_called.txt"
        _make_stub(
            work,
            "install.sh",
            f'echo "fake-installer-ran" > {shlex.quote(str(marker))}\nexit 0',
        )
        _make_stub(
            self.bin_dir,
            "git",
            'case "$1" in\n'
            '  --version)\n'
            '    echo "xcode-select: note: no developer tools were found" >&2\n'
            '    exit 1\n'
            '    ;;\n'
            '  init)\n'
            f'    echo "forbidden" > {shlex.quote(str(init_forbidden))}\n'
            '    exit 99\n'
            '    ;;\n'
            '  *)\n'
            '    exit 1\n'
            '    ;;\n'
            'esac',
        )

        res = subprocess.run(
            ["sh", str(cmd_copy)],
            cwd=work,
            env=self._base_env(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"stdout={res.stdout}\nstderr={res.stderr}")
        self.assertTrue(marker.is_file(), "install.sh deveria ter sido chamado")
        self.assertFalse(init_forbidden.exists(), "git init não deve rodar sem git funcional")
        self.assertFalse((work / ".git").exists(), ".git não deve ser criado sem git funcional")
        self.assertIn("instalador", res.stdout)


class TestInstallShHardening(_IsolatedShellTestCase):
    def test_trap_cleans_tmpscript_on_early_exit(self) -> None:
        _make_stub(self.bin_dir, "uname", 'echo "Linux"')
        _make_stub(self.bin_dir, "git", "exit 1")

        before = set(os.listdir(self.tmpdir))
        res = subprocess.run(
            ["sh", str(INSTALL_SRC)],
            cwd=self.tmp,
            env=self._base_env(),
            capture_output=True,
            text=True,
        )
        after = set(os.listdir(self.tmpdir))

        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(after - before, set(), f"temporário vazou em TMPDIR: {after - before}")

    def test_existing_git_with_foreign_origin_aborts(self) -> None:
        dest = self.tmp / "existing-dest"
        (dest / ".git").mkdir(parents=True)
        outside = self.tmp / "outside"
        outside.mkdir()

        _make_stub(self.bin_dir, "uname", 'echo "Linux"')
        _make_stub(
            self.bin_dir,
            "git",
            'case "$1" in\n'
            '  --version) exit 0 ;;\n'
            '  -C)\n'
            '    shift 2\n'
            '    if [ "$1" = "remote" ] && [ "$2" = "get-url" ]; then\n'
            '      echo "https://github.com/outro/repo.git"\n'
            '      exit 0\n'
            '    fi\n'
            '    exit 1 ;;\n'
            '  *) exit 1 ;;\n'
            'esac',
        )

        res = subprocess.run(
            ["sh", str(INSTALL_SRC), str(dest)],
            cwd=outside,
            env=self._base_env(),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("⚠", res.stdout)
        self.assertIn("outro/repo.git", res.stdout)
        self.assertIn("Escolha outra pasta", res.stdout)

    def test_existing_git_with_ssh_origin_is_accepted(self) -> None:
        dest = self.tmp / "existing-brain"
        (dest / ".git").mkdir(parents=True)
        (dest / "brainlib").mkdir()
        brain_log = self.tmp / "brain_calls.log"
        _make_stub(
            dest,
            "brain",
            f'echo "$*" >> {shlex.quote(str(brain_log))}\nexit 0',
        )
        outside = self.tmp / "outside"
        outside.mkdir()

        _make_stub(self.bin_dir, "uname", 'echo "Linux"')
        _make_stub(self.bin_dir, "python3", f'exec {shlex.quote(sys.executable)} "$@"')
        _make_stub(self.bin_dir, "mise", "exit 0")
        _make_stub(self.bin_dir, "docker", "exit 0")
        _make_stub(
            self.bin_dir,
            "git",
            'case "$1" in\n'
            '  --version) exit 0 ;;\n'
            '  -C)\n'
            '    shift 2\n'
            '    if [ "$1" = "remote" ] && [ "$2" = "get-url" ]; then\n'
            '      echo "git@github.com:BVLCQ/second-brain-framework.git"\n'
            '      exit 0\n'
            '    fi\n'
            '    exit 1 ;;\n'
            '  *) exit 1 ;;\n'
            'esac',
        )

        res = subprocess.run(
            ["sh", str(INSTALL_SRC), str(dest)],
            cwd=outside,
            env=self._base_env(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"stdout={res.stdout}\nstderr={res.stderr}")
        self.assertIn("✓ repo já existe", res.stdout)
        calls = brain_log.read_text(encoding="utf-8").splitlines()
        self.assertIn("open --setup", calls)

    def test_clone_failure_prints_warning_and_exits(self) -> None:
        dest = self.tmp / "clone-target"
        outside = self.tmp / "outside"
        outside.mkdir()

        _make_stub(self.bin_dir, "uname", 'echo "Linux"')
        _make_stub(
            self.bin_dir,
            "git",
            'case "$1" in\n'
            '  --version) exit 0 ;;\n'
            '  clone) exit 1 ;;\n'
            '  *) exit 1 ;;\n'
            'esac',
        )

        res = subprocess.run(
            ["sh", str(INSTALL_SRC), str(dest)],
            cwd=outside,
            env=self._base_env(),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("⚠ não consegui clonar", res.stdout)

    def test_optional_mise_failure_continues_with_system_python(self) -> None:
        repo = self.tmp / "fake-repo"
        repo.mkdir()
        (repo / "brainlib").mkdir()
        brain_log = self.tmp / "brain_calls.log"
        _make_stub(
            repo,
            "brain",
            f'echo "$*" >> {shlex.quote(str(brain_log))}\nexit 0',
        )

        _make_stub(self.bin_dir, "uname", 'echo "Linux"')
        _make_stub(self.bin_dir, "git", "exit 0")
        _make_stub(self.bin_dir, "curl", "exit 1")
        _make_stub(self.bin_dir, "brew", "exit 1")
        _make_stub(self.bin_dir, "python3", f'exec {shlex.quote(sys.executable)} "$@"')

        res = subprocess.run(
            ["sh", str(INSTALL_SRC)],
            cwd=repo,
            env=self._base_env(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"stdout={res.stdout}\nstderr={res.stderr}")
        self.assertIn("⚠ mise não instalado", res.stdout)
        self.assertIn("⚠ Docker não instalado", res.stdout)
        calls = brain_log.read_text(encoding="utf-8").splitlines()
        self.assertIn("init", calls)
        self.assertIn("app install", calls)
        self.assertIn("open --setup", calls)


if __name__ == "__main__":
    unittest.main()
