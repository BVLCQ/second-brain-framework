"""Paridade de setup.md com o stack real (container, LMS_GET_FALLBACK, LaunchAgent, sem datas literais)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import setup  # noqa: E402

SETUP_MD = ROOT / "setup.md"


class TestSetupDocAlignment(unittest.TestCase):
    def test_stack_uses_compose_fallback_url_and_launchd(self):
        self.assertTrue(SETUP_MD.is_file(), "setup.md deve existir na raiz")
        text = SETUP_MD.read_text(encoding="utf-8")
        fallback_url = setup.LMS_GET_FALLBACK["text-embedding-bge-m3"]

        for expected in (
            "services/compose.yaml",
            "services/compose.full.yaml",
            "--env-file",
            "./brain memory setup",
            "./brain setup --only memoria",
            "com o container já de pé",             # o CLI direto não sobe o container; só o caminho guiado sobe
            fallback_url,
            f"lms get {fallback_url}",
            "./brain schedule install",
            "./brain schedule status",
            "./brain schedule remove",
            "./brain memory sync",
            "./brain memory recall",
            "LaunchAgent",
            "launchd",
        ):
            self.assertIn(expected, text, f"faltou em setup.md: {expected!r}")

        self.assertRegex(text, r"(?i)recupera\w*.*perdida|perdida.*recupera")

        for forbidden in (
            "lms get bge-m3",
            "o cron é pulado em silêncio",
            "não recupera jobs perdidos",
            "hindsight-embed memory retain",
        ):
            self.assertNotIn(forbidden, text, f"trecho obsoleto ainda presente em setup.md: {forbidden!r}")

        for heading in (
            "## 0. Pre-flight",
            "## 1. Toolchain",
            "## 2. Este repo + smoke test",
            "### 2.1 TUI (opcional)",
            "## 3. LM Studio",
            "## 4. Hindsight",
            "## 5. Ligar a memória no brain",
            "## 6. Noturno",
            "## 7. Claude Code",
            "## 8. Checklist final",
            "## Problemas comuns",
            "## Depois (não é hoje)",
        ):
            self.assertIn(heading, text, f"seção estrutural ausente: {heading!r}")

    def test_legacy_daemon_isolated_and_no_literal_dates(self):
        text = SETUP_MD.read_text(encoding="utf-8")
        lines = text.splitlines()

        legacy_headings = [
            i for i, ln in enumerate(lines)
            if ln.lstrip().startswith("#") and "legad" in ln.lower()
        ]
        self.assertTrue(legacy_headings, "setup.md deve ter cabeçalho explícito para a alternativa legada")
        first_legacy_idx = legacy_headings[0]

        embed_lines = [i for i, ln in enumerate(lines) if "hindsight-embed" in ln]
        self.assertTrue(embed_lines, "setup.md deve manter a alternativa legada hindsight-embed")
        self.assertTrue(
            all(i > first_legacy_idx for i in embed_lines),
            "hindsight-embed só pode aparecer após o cabeçalho marcado como legado",
        )

        # Seção legada (entre o cabeçalho legado e a próxima seção ##) deve avisar sobre conflito na porta 8888
        next_h2 = next(
            (i for i in range(first_legacy_idx + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        legacy_block = "\n".join(lines[first_legacy_idx:next_h2])
        self.assertIn("8888", legacy_block, "seção legada deve avisar sobre conflito na porta 8888")
        # o bloco também traz o curl de health na mesma porta: quem precisa estar lá é o aviso de conflito
        self.assertIn("disputam a porta `8888`", legacy_block, "seção legada deve avisar sobre o conflito na porta 8888")

        literal_dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text)
        self.assertEqual(literal_dates, [], f"setup.md não deve conter datas literais: {literal_dates}")


if __name__ == "__main__":
    unittest.main()
