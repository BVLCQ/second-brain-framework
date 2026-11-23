"""Testes do serviço watchdog, plist e paridade do guia de setup (#73, #80, #81)."""
from __future__ import annotations

import os
import plistlib
import re
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
class TestWatchdogComposeMode(unittest.TestCase):
    """services/watchdog.sh deriva docker compose do modo em config/brain.toml."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.brain_dir = self.root / "inst"
        (self.brain_dir / "config").mkdir(parents=True)
        (self.brain_dir / "vault" / "logs").mkdir(parents=True)
        self.stubs = self.root / "bin"
        self.stubs.mkdir()
        self.docker_args_file = self.root / "docker_args.txt"
        self.log_file = self.brain_dir / "vault" / "logs" / "watchdog.log"

        self.curl_stub = _write_stub(
            self.stubs / "curl",
            'case "$*" in\n'
            '  *:1234/v1/models*) exit 0 ;;\n'
            '  *:8888/health*) exit 1 ;;\n'
            '  *) exit 1 ;;\n'
            'esac',
        )
        self.orbctl_stub = _write_stub(self.stubs / "orbctl", 'echo "Running"')
        self.docker_stub = _write_stub(
            self.stubs / "docker",
            f'if [ "$1" = "inspect" ]; then\n'
            f'  echo "exited|false"\n'
            f'  exit 0\n'
            f'fi\n'
            f'printf "%s\\n" "$@" > "{self.docker_args_file}"\n'
            f'echo "Container hindsight Recreated"\n'
            f'exit 0',
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_watchdog(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update({
            "HOME": str(self.root / "home"),
            "PATH": f"{self.stubs}:{env.get('PATH', '')}",
            "BRAIN_DIR": str(self.brain_dir),
            "WATCHDOG_LOG": str(self.log_file),
            "LMS": str(self.root / "no-lms"),
            "CURL": str(self.curl_stub),
            "ORBCTL": str(self.orbctl_stub),
            "DOCKER": str(self.docker_stub),
            "WATCHDOG_LMS_TRIES": "1",
            "WATCHDOG_LMS_SLEEP": "0",
            "WATCHDOG_HEALTH_TRIES": "1",
            "WATCHDOG_SLEEP": "0",
        })
        (self.root / "home").mkdir(exist_ok=True)
        return subprocess.run(
            ["zsh", str(WATCHDOG_SH)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_full_mode_uses_full_compose_and_env_file(self) -> None:
        (self.brain_dir / "config" / "brain.toml").write_text(
            '[memory]\n'
            'engine = "hindsight"\n'
            'extract = true  # nuvem\n'
            'cloud_llm = true\n',
            encoding="utf-8",
        )
        env_file = self.brain_dir / "config" / ".env"
        env_file.write_text("HINDSIGHT_API_LLM_PROVIDER=openai\n", encoding="utf-8")

        res = self._run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        args = self.docker_args_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(args[0], "compose")
        self.assertIn("--env-file", args)
        env_idx = args.index("--env-file")
        self.assertEqual(args[env_idx + 1], str(env_file))
        self.assertIn(str(ROOT / "services" / "compose.yaml"), args)
        self.assertIn(str(ROOT / "services" / "compose.full.yaml"), args)
        self.assertEqual(args[-2:], ["up", "-d"])

        log = self.log_file.read_text(encoding="utf-8")
        self.assertIn("modo: full", log)
        self.assertIn("subido/recriado", log)

    def test_embed_mode_uses_base_compose_only(self) -> None:
        (self.brain_dir / "config" / "brain.toml").write_text(
            '[memory]\n'
            'engine = "hindsight"\n'
            'extract = false\n',
            encoding="utf-8",
        )
        (self.brain_dir / "config" / ".env").write_text("DUMMY=1\n", encoding="utf-8")

        res = self._run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        args = self.docker_args_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            args,
            ["compose", "-f", str(ROOT / "services" / "compose.yaml"), "up", "-d"],
        )
        self.assertNotIn("--env-file", args)
        self.assertNotIn(str(ROOT / "services" / "compose.full.yaml"), args)

    def test_embed_mode_with_quoted_false_extract_does_not_enable_full(self) -> None:
        (self.brain_dir / "config" / "brain.toml").write_text(
            '[memory]\n'
            'engine = "hindsight"\n'
            'extract = "false"  # explícito como string\n',
            encoding="utf-8",
        )

        res = self._run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        args = self.docker_args_file.read_text(encoding="utf-8").splitlines()
        self.assertNotIn(str(ROOT / "services" / "compose.full.yaml"), args)
        log = self.log_file.read_text(encoding="utf-8")
        self.assertIn("modo: embed", log)

    def test_missing_config_defaults_to_embed(self) -> None:
        res = self._run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        args = self.docker_args_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            args,
            ["compose", "-f", str(ROOT / "services" / "compose.yaml"), "up", "-d"],
        )
        self.assertNotIn(str(ROOT / "services" / "compose.full.yaml"), args)

    def test_none_mode_skips_recreate(self) -> None:
        (self.brain_dir / "config" / "brain.toml").write_text(
            '[memory]\n'
            'engine = "none"\n',
            encoding="utf-8",
        )

        res = self._run_watchdog()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(self.docker_args_file.exists())
        log = self.log_file.read_text(encoding="utf-8")
        self.assertIn("modo none", log)


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


class TestGuideStepsParity(unittest.TestCase):
    """Seção 25 de guides/commands.md documenta todos os passos de setup.STEPS."""

    def test_commands_guide_covers_all_setup_steps(self) -> None:
        guide = COMMANDS_MD.read_text(encoding="utf-8")
        m = re.search(r"^## 25\. .*?(?=^## \d+\. |\Z)", guide, flags=re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(m, "seção 25 não encontrada em guides/commands.md")
        sec25 = m.group(0)
        for step in setup.STEPS:
            self.assertIn(step["id"], sec25, f"passo {step['id']!r} ausente na seção 25 de guides/commands.md")
