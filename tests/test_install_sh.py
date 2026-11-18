"""Testes de install.sh e setup.md — sintaxe shell, posições relativas e guarda de erro."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config                                          # noqa: E402
from brainlib.core import Brain                                      # noqa: E402

INSTALL_SH = ROOT / "install.sh"
SETUP_MD = ROOT / "setup.md"


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n'
        '[outbound]\nallow = ["marina-demo", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n"
        "- [ ] PROJ-1.2 Outro · prazo: 2026-11-01\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Marina-demo", "Mari-demo"], "email": "marina-demo@x.com"}})
    return b


class InstallShTests(unittest.TestCase):
    def test_syntax_sh_n(self):
        """sh -n install.sh deve retornar 0 (sintaxe válida para /bin/sh)."""
        self.assertTrue(INSTALL_SH.is_file(), "install.sh deve existir na raiz")
        res = subprocess.run(["sh", "-n", str(INSTALL_SH)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"sh -n falhou: {res.stderr}")

    def test_line_indices(self):
        """O primeiro 'mise trust' deve vir antes do check 'python3 -c' e antes de './brain init'."""
        lines = INSTALL_SH.read_text(encoding="utf-8").splitlines()

        mise_trust_indices = [i for i, line in enumerate(lines) if "mise trust" in line]
        self.assertTrue(mise_trust_indices, "install.sh deve conter pelo menos uma linha com 'mise trust'")
        first_mise_trust_idx = mise_trust_indices[0]

        python_check_indices = [i for i, line in enumerate(lines) if "python3 -c" in line]
        self.assertTrue(python_check_indices, "install.sh deve conter o check 'python3 -c'")
        first_python_check_idx = python_check_indices[0]

        brain_init_indices = [
            i for i, line in enumerate(lines)
            if "./brain init" in line and not line.strip().startswith("#")
        ]
        self.assertTrue(brain_init_indices, "install.sh deve conter chamada a './brain init'")
        first_brain_init_idx = brain_init_indices[0]

        self.assertLess(
            first_mise_trust_idx,
            first_python_check_idx,
            f"'mise trust' (linha {first_mise_trust_idx + 1}) deve vir antes de 'python3 -c' (linha {first_python_check_idx + 1})",
        )
        self.assertLess(
            first_mise_trust_idx,
            first_brain_init_idx,
            f"'mise trust' (linha {first_mise_trust_idx + 1}) deve vir antes de './brain init' (linha {first_brain_init_idx + 1})",
        )

    def test_brain_init_only_in_if_not(self):
        """'./brain init' como comando executado só pode aparecer em construto 'if !'."""
        lines = INSTALL_SH.read_text(encoding="utf-8").splitlines()
        exec_lines = [
            (i + 1, line.strip())
            for i, line in enumerate(lines)
            if "./brain init" in line
            and not line.strip().startswith("#")
            and not line.strip().startswith("echo")
        ]
        self.assertTrue(exec_lines, "install.sh deve conter execução de './brain init'")
        for lineno, line in exec_lines:
            self.assertTrue(
                line.startswith("if ! ./brain init"),
                f"linha {lineno}: execução de './brain init' deve aparecer dentro de 'if !', mas achou: {line}",
            )

    def test_error_and_warning_messages(self):
        """Mensagens de diagnóstico devem orientar o dono com comandos exatos."""
        content = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn('echo "⚠ não consegui confiar no mise.toml — rode:  mise trust \\"$PWD\\"  e depois  sh install.sh"', content)
        self.assertIn('echo "✗ ./brain init falhou (veja o erro acima)."', content)
        self.assertIn('echo "  com mise:  mise trust \\"$PWD\\" && mise install  — depois:  sh install.sh"', content)

    def test_setup_md_annotation(self):
        """setup.md deve anotar que o install.sh já faz o mise trust sozinho."""
        self.assertTrue(SETUP_MD.is_file(), "setup.md deve existir")
        content = SETUP_MD.read_text(encoding="utf-8")
        trust_lines = [line for line in content.splitlines() if "mise trust" in line]
        self.assertTrue(trust_lines, "setup.md deve conter instrução mise trust")
        self.assertTrue(
            any("o `install.sh` já faz isso sozinho" in l or "o install.sh já faz isso sozinho" in l for l in trust_lines),
            "setup.md deve conter nota 'o install.sh já faz isso sozinho' junto da instrução mise trust",
        )

    def test_optional_shellcheck(self):
        """Roda shellcheck se estiver no PATH, caso contrário pula."""
        shellcheck = shutil.which("shellcheck")
        if shellcheck is None:
            self.skipTest("shellcheck não encontrado no PATH")
        res = subprocess.run([shellcheck, str(INSTALL_SH)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"shellcheck falhou:\n{res.stdout}\n{res.stderr}")


if __name__ == "__main__":
    unittest.main()
