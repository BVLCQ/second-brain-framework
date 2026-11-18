"""Testes de entrada sem terminal (Abrir o Brain.command)."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CMD_PATH = ROOT / "Abrir o Brain.command"
README_PATH = ROOT / "README.md"


class InstallEntryTests(unittest.TestCase):
    def test_command_file_exists_and_executable(self):
        self.assertTrue(CMD_PATH.is_file(), "Abrir o Brain.command deve existir na raiz")
        self.assertTrue(os.access(CMD_PATH, os.X_OK), "Abrir o Brain.command deve ser executável (X_OK)")
        first_line = CMD_PATH.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first_line, "#!/bin/sh")

    def test_command_file_content_and_zip_branch(self):
        content = CMD_PATH.read_text(encoding="utf-8")
        self.assertIn("install.sh", content, "Deve mencionar install.sh")
        self.assertIn("git init", content, "Deve conter 'git init' para o ramo do ZIP")
        self.assertIn("remote.origin.fetch", content, "Deve configurar 'remote.origin.fetch'")

    def test_readme_mentions_command_and_zip(self):
        self.assertTrue(README_PATH.is_file(), "README.md deve existir na raiz")
        content = README_PATH.read_text(encoding="utf-8")
        self.assertIn("Abrir o Brain.command", content, "README.md deve mencionar Abrir o Brain.command")
        self.assertIn("ZIP", content, "README.md deve mencionar ZIP")

    def test_syntax_sh_n(self):
        res = subprocess.run(["sh", "-n", str(CMD_PATH)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"sh -n falhou: {res.stderr}")


if __name__ == "__main__":
    unittest.main()
