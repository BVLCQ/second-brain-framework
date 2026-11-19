"""Testes de recuperação de boot do Hindsight no doctor e watchdog (#27) — stdlib unittest, sem rede."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, doctor, memory, setup, util                     # noqa: E402
from brainlib.core import Brain                                              # noqa: E402

WATCHDOG_SH = ROOT / "services" / "watchdog.sh"
COMPOSE_YAML = ROOT / "services" / "compose.yaml"


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
        '[memory]\nengine = "hindsight"\n\n'
        '[outbound]\nallow = ["marina-demo", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Marina-demo", "Mari-demo"],
                           "email": "marina-demo@x.com"}})
    return b


def _fake_inspect(stdout: str, returncode: int = 0):
    calls: list[list[str]] = []

    def _run(argv, **_kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    _run.calls = calls
    return _run


class DoctorBootTransientTests(unittest.TestCase):
    """Critérios (1)–(4): estado transitório do container Hindsight no brain doctor."""

    def _run_doctor(self, b: Brain, *, docker_probe=None, status_ret=None):
        st = status_ret or {"level": "error", "detail": "Hindsight indisponível em http://localhost:8888 (Connection refused)"}
        with mock.patch.object(memory, "status", return_value=st), \
                mock.patch.object(setup, "brain_command_status", return_value="/usr/local/bin/brain"), \
                mock.patch.object(setup, "FRAMEWORK", Path("/nonexistent-fw")):
            return doctor.checks(b, online=False, docker_probe=docker_probe)

    def test_1_restarting_container_with_lmstudio_unreachable_warns_transient(self):
        """(1) container restarting=true + LM Studio inacessível → warn 'memória' com 'estado transitório'."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            run = _fake_inspect("running|true|1|2026-10-09T12:58:30.123456789Z\n")

            def _unreachable(_url):
                raise OSError("Connection refused")

            probe = lambda cfg: doctor._hindsight_transient(
                cfg,
                which=lambda cmd: "/usr/local/bin/docker" if cmd == "docker" else None,
                run=run,
                http_get=_unreachable,
            )
            cks = self._run_doctor(b, docker_probe=probe)
            mem = next(c for c in cks if c["title"] == "memória")
            self.assertEqual(mem["level"], "warn")
            self.assertIn("estado transitório", mem["detail"])
            self.assertIn("LM Studio", mem["detail"])
            self.assertEqual(len(run.calls), 1)
            self.assertEqual(run.calls[0][0], "/usr/local/bin/docker")

    def test_2_running_container_started_under_180s_ago_with_nanoseconds_warns_transient(self):
        """(2) container running iniciado <180s atrás (StartedAt com 9 dígitos fracionários) → warn transitório."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            # BRAIN_NOW = 2026-10-09T10:00:00-03:00 (= 13:00:00Z). StartedAt = 45s antes, com 9 casas decimais.
            run = _fake_inspect("running|false|0|2026-10-09T12:59:15.987654321Z\n")
            probe = lambda cfg: doctor._hindsight_transient(
                cfg,
                which=lambda cmd: "/usr/local/bin/docker" if cmd == "docker" else None,
                run=run,
                http_get=lambda _url: True,
            )
            cks = self._run_doctor(b, docker_probe=probe)
            mem = next(c for c in cks if c["title"] == "memória")
            self.assertEqual(mem["level"], "warn")
            self.assertIn("estado transitório", mem["detail"])
            self.assertIn("Hindsight inicializando no boot", mem["detail"])

    def test_3_exited_or_old_running_preserves_original_memory_status_error(self):
        """(3) container exited ou running >180s atrás → preserva o erro original de memory.status()."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            orig_err = "Hindsight indisponível em http://localhost:8888 (Connection refused)"
            for inspect_line in (
                "exited|false|137|2026-10-09T12:59:30.123456789Z\n",
                "running|false|0|2026-10-09T12:50:00.123456789Z\n",   # 600s (>180s) atrás
            ):
                run = _fake_inspect(inspect_line)
                probe = lambda cfg, r=run: doctor._hindsight_transient(
                    cfg,
                    which=lambda cmd: "/usr/local/bin/docker" if cmd == "docker" else None,
                    run=r,
                    http_get=lambda _url: False,
                )
                cks = self._run_doctor(b, docker_probe=probe, status_ret={"level": "error", "detail": orig_err})
                mem = next(c for c in cks if c["title"] == "memória")
                self.assertEqual(mem["level"], "error", inspect_line)
                self.assertEqual(mem["detail"], orig_err, inspect_line)

    def test_4_which_docker_none_is_offline_safe_and_spawns_no_subprocess(self):
        """(4) which('docker') -> None → seguro sem Docker (Linux CI / WSL2 / Mac limpo), zero subprocessos."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))

            def _forbidden_run(*_a, **_kw):
                raise AssertionError("nenhum subprocesso deve ser chamado quando docker não existe")

            res = doctor._hindsight_transient(
                b.inst.cfg,
                which=lambda _cmd: None,
                run=_forbidden_run,
            )
            self.assertIsNone(res)

            cks = self._run_doctor(
                b,
                docker_probe=lambda cfg: doctor._hindsight_transient(cfg, which=lambda _c: None, run=_forbidden_run),
            )
            mem = next(c for c in cks if c["title"] == "memória")
            self.assertEqual(mem["level"], "error")

    def test_orbstack_fallback_used_only_when_which_docker_is_none_and_exists(self):
        """Fallback para o binário do OrbStack funciona quando which('docker') é None e o caminho existe."""
        run = _fake_inspect("restarting|true|1|2026-10-09T12:59:50.111222333Z\n")
        res = doctor._hindsight_transient(
            {"memory": {"embeddings_provider": "local"}},
            which=lambda _cmd: None,
            exists=lambda p: p == doctor.ORBSTACK_DOCKER,
            run=run,
            http_get=lambda _url: True,
        )
        self.assertIsNotNone(res)
        self.assertIn("estado transitório", res)
        self.assertEqual(run.calls[0][0], doctor.ORBSTACK_DOCKER)

    def test_ok_status_does_not_run_transient_probe(self):
        """Quando memory.status() retorna level='ok', o probe do container não é chamado."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))

            def _boom(_cfg):
                raise AssertionError("docker_probe não deve rodar quando status['level'] == 'ok'")

            cks = self._run_doctor(b, docker_probe=_boom, status_ret={"level": "ok", "detail": "modo embed · servidor no ar"})
            mem = next(c for c in cks if c["title"] == "memória")
            self.assertEqual(mem["level"], "ok")


class WatchdogShTests(unittest.TestCase):
    """Critério (5): sintaxe zsh -n e verificação das ramificações de log e guarda [[ -x "$LMS" ]]."""

    @unittest.skipUnless(shutil.which("zsh"), "zsh ausente (CI roda em Ubuntu sem zsh) — checagem de sintaxe é local/macOS")
    def test_5_watchdog_zsh_syntax_and_honest_logging_branches(self):
        self.assertTrue(WATCHDOG_SH.is_file(), "services/watchdog.sh deve existir")
        res = subprocess.run(["zsh", "-n", str(WATCHDOG_SH)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"zsh -n services/watchdog.sh falhou: {res.stderr}")

        content = WATCHDOG_SH.read_text(encoding="utf-8")
        # Passo 1: guarda [[ -x "$LMS" ]] e espera pelo endpoint :1234/v1/models
        self.assertIn('[[ -x "$LMS" ]]', content)
        self.assertIn("http://127.0.0.1:1234/v1/models", content)

        # Passo 3: inspeciona estado do container antes do compose up -d e registra saída real
        self.assertIn("inspect -f '{{.State.Status}}|{{.State.Restarting}}' hindsight", content)
        self.assertIn("subido/recriado", content)
        self.assertIn("Container hindsight Running", content)
        self.assertIn("compose up -d não alterou (Container hindsight Running)", content)

        # compose.yaml mantém restart: unless-stopped e start_period: 120s
        compose = COMPOSE_YAML.read_text(encoding="utf-8")
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("start_period: 120s", compose)


if __name__ == "__main__":
    unittest.main()
