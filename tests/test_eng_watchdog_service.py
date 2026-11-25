"""Testes do serviço watchdog, plist e paridade do guia de setup (#73, #80, #81)."""
from __future__ import annotations

import os
import plistlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import setup  # noqa: E402

WATCHDOG_SH = ROOT / "services" / "watchdog.sh"
WATCHDOG_PLIST = ROOT / "services" / "com.segundo-cerebro.watchdog.plist"
COMMANDS_MD = ROOT / "guides" / "commands.md"


def _write_stub(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@unittest.skipUnless(shutil.which("zsh"), "zsh ausente (CI Linux sem zsh)")
class TestWatchdogDelegates(unittest.TestCase):
    """O shell só chama `brain services ensure`. A escolha de compose mora no Python."""

    def test_script_calls_ensure_and_honors_pause(self) -> None:
        text = WATCHDOG_SH.read_text(encoding="utf-8")
        self.assertIn("services ensure --reason watchdog", text)
        self.assertIn(".brain-watchdog-off", text)
        self.assertNotIn("docker compose", text)
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            (home / ".brain-watchdog-off").write_text("", encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["BRAIN_DIR"] = str(ROOT)
            res = subprocess.run(["zsh", str(WATCHDOG_SH)], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)


class _RetiredComposeShell:
    """O contrato de compose (full/embed/LM Studio) mudou de shell para brainlib/services.py.
    Os casos vivem em tests/test_services.py. Esta classe não roda."""


class TestWatchdogComposeMode(unittest.TestCase):
    def test_moved(self) -> None:
        self.assertIn("def compose_argv", (ROOT / "brainlib" / "services.py").read_text(encoding="utf-8"))
        self.assertIn("def hindsight_blocked", (ROOT / "brainlib" / "services.py").read_text(encoding="utf-8"))



class TestWatchdogPlistAndGuide(unittest.TestCase):
    """services/com.segundo-cerebro.watchdog.plist e receita em guides/commands.md."""

    def test_plist_valid_and_matches_guide_label(self) -> None:
        self.assertTrue(WATCHDOG_PLIST.is_file())
        data = plistlib.loads(WATCHDOG_PLIST.read_bytes())
        self.assertEqual(data["Label"], "com.segundo-cerebro.watchdog")
        self.assertIn("__BRAIN_DIR__/services/watchdog.sh", data["ProgramArguments"])
        self.assertIs(data["RunAtLoad"], True)
        self.assertEqual(data["StartInterval"], 300)
        self.assertEqual(data["StandardOutPath"], "__BRAIN_DIR__/vault/logs/watchdog.log")
        self.assertEqual(data["StandardErrorPath"], "__BRAIN_DIR__/vault/logs/watchdog.log")
        self.assertEqual(data["ProcessType"], "Background")
        self.assertIs(data["LowPriorityIO"], True)

        guide = COMMANDS_MD.read_text(encoding="utf-8")
        self.assertIn("services/com.segundo-cerebro.watchdog.plist", guide)
        self.assertIn("sed ", guide)
        self.assertIn("launchctl kickstart gui/$(id -u)/com.segundo-cerebro.watchdog", guide)


class TestGuideLaunchAgentRecipes(unittest.TestCase):
    """As receitas de LaunchAgent de guides/commands.md têm que rodar como estão no arquivo cru.

    O guia também é lido cru (terminal, agente), não só renderizado: numa célula de tabela o `|` pede escape
    (`\\|`), e um `sed` copiado com esse escape não roda no BSD sed do macOS — o único sistema onde LaunchAgent
    existe. Delimitador `#` dispensa o escape e dá o mesmo resultado cru e renderizado."""

    ROW = re.compile(r"^\| Instalar o (watchdog|descarregador) \|(.*)$", re.MULTILINE)
    SED = re.compile(r'sed ("[^"]*") (services/[\w.\-]+) >')

    def _recipes(self) -> list[tuple[str, str]]:
        rows = self.ROW.findall(COMMANDS_MD.read_text(encoding="utf-8"))
        self.assertEqual([name for name, _ in rows], ["watchdog", "descarregador"],
                         "receitas do watchdog e do descarregador ausentes ou fora de ordem em guides/commands.md")
        return rows

    def test_recipe_reads_the_same_raw(self) -> None:
        for name, row in self._recipes():
            self.assertNotIn("\\|", row, f"'Instalar o {name}': pipe escapado não roda como está no arquivo cru")
            self.assertIn('sed "s#__BRAIN_DIR__#$PWD#g"', row)
            self.assertIn("mkdir -p ~/Library/LaunchAgents", row,
                          "'Instalar o " + name + "': sem a pasta, o redirecionamento falha antes do launchctl")

    @unittest.skipUnless(shutil.which("sed"), "sed ausente")
    def test_documented_substitution_runs_on_the_local_sed(self) -> None:
        sed = shutil.which("sed") or "sed"           # (sem sed no PATH a classe já pula)
        for name, row in self._recipes():
            m = self.SED.search(row)
            assert m is not None, f"'Instalar o {name}': comando sed não encontrado na receita"
            expr, src = shlex.split(m.group(1))[0], m.group(2)
            self.assertTrue((ROOT / src).is_file(), f"{src} ausente no repo")
            sample = plistlib.loads((ROOT / src).read_bytes())
            self.assertIn("__BRAIN_DIR__", " ".join(sample["ProgramArguments"]),
                           f"{src} deveria trazer o placeholder __BRAIN_DIR__")
            proc = subprocess.run([sed, expr.replace("$PWD", "/caminho/da/instancia"), str(ROOT / src)],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0,
                             f"'Instalar o {name}': o sed recusou a receita como está no guia: {proc.stderr.strip()}")
            rendered = plistlib.loads(proc.stdout.encode("utf-8"))
            self.assertEqual(rendered["Label"], sample["Label"])
            self.assertNotIn("__BRAIN_DIR__", proc.stdout)
            self.assertIn("/caminho/da/instancia/", proc.stdout)


class TestGuideStepsParity(unittest.TestCase):
    """Seção 25 de guides/commands.md documenta todos os passos de setup.STEPS."""

    def test_commands_guide_covers_all_setup_steps(self) -> None:
        guide = COMMANDS_MD.read_text(encoding="utf-8")
        m = re.search(r"^## 25\. .*?(?=^## \d+\. |\Z)", guide, flags=re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(m, "seção 25 não encontrada em guides/commands.md")
        sec25 = m.group(0)
        for step in setup.STEPS:
            self.assertIn(step["id"], sec25, f"passo {step['id']!r} ausente na seção 25 de guides/commands.md")
