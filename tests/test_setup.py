"""Setup assistido (`brain setup`) — stdlib unittest, sem rede, sem docker."""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, memory, setup, util                     # noqa: E402
from brainlib.core import Brain                                      # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[work]\ndays = [1, 2, 3, 4, 5]\nstart = "09:00"\nend = "18:00"\nlunch = "12:00-13:00"\n',
        encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class ScriptedUI(setup.ConsoleUI):
    """UI de teste: respostas enfileiradas; nada lê stdin."""

    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.said: list[str] = []

    def say(self, msg):
        self.said.append(msg)

    def ask(self, prompt, default=""):
        self.said.append(f"ASK {prompt}")
        return self.answers.pop(0) if self.answers else default

    def secret(self, prompt):
        raise AssertionError("segredo não pode ser pedido neste teste")

    def confirm(self, prompt, default=False):
        r = self.ask(prompt, "n")
        return r.lower() in ("s", "sim", "y", "yes")


class SetEnvTests(unittest.TestCase):
    def test_preserves_and_appends_with_0600(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(Path(td))
            (inst.env_file).write_text("# header\nGOOGLE_CLIENT_ID=abc\n", encoding="utf-8")
            changed = setup.set_env(inst, {"GOOGLE_CLIENT_ID": "abc", "GITHUB_TOKEN": "x"})
            self.assertEqual(changed, ["GITHUB_TOKEN"])            # valor igual não regrava
            text = inst.env_file.read_text(encoding="utf-8")
            self.assertIn("# header", text)
            self.assertIn("GOOGLE_CLIENT_ID=abc", text)
            self.assertIn("GITHUB_TOKEN=x", text)
            self.assertEqual(stat.S_IMODE(inst.env_file.stat().st_mode), 0o600)

    def test_updates_existing_value(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(Path(td))
            (inst.env_file).write_text("K=old\n", encoding="utf-8")
            self.assertEqual(setup.set_env(inst, {"K": "new"}), ["K"])
            self.assertIn("K=new", inst.env_file.read_text(encoding="utf-8"))


class BrainCommandTests(unittest.TestCase):
    def test_status_none_when_not_on_path(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(Path(td))
            self.assertIsNone(setup.brain_command_status(inst.root))   # nada chamado brain aí

    def test_install_and_status(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            old_home, old_path = os.environ.get("HOME"), os.environ.get("PATH")
            try:
                os.environ["HOME"] = str(home)
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{(old_path or '')}"
                inst = _inst(Path(td) / "inst")
                fake = inst.root / "brain"
                fake.write_text("#!/bin/sh\n", encoding="utf-8")
                fake.chmod(0o755)                      # shutil.which exige executável
                ui = ScriptedUI([])
                link = setup.install_brain_command(inst.root, ui)
                self.assertEqual(Path(link).parent, bin_dir)
                got = setup.brain_command_status(inst.root)
                self.assertIsNotNone(got)
                self.assertEqual(Path(got).resolve(), (inst.root / "brain").resolve())
            finally:
                os.environ["HOME"] = old_home or ""
                os.environ["PATH"] = old_path or os.defpath


class StepStatusTests(unittest.TestCase):
    def test_statuses_on_fresh_instance(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            real_fw = setup.FRAMEWORK
            setup.FRAMEWORK = Path(td)                 # hermético: .venv-tui da máquina real não vaza
            try:
                st = {s["id"]: s["status"](b) for s in setup.STEPS}
            finally:
                setup.FRAMEWORK = real_fw
            self.assertEqual(st["instancia"], "done")          # zonas + config existem
            self.assertEqual(st["identidade"], "done")         # dono no ledger
            self.assertEqual(st["rotina"], "done")             # [work] no arquivo
            self.assertEqual(st["foco"], "done")               # ics = zero config
            self.assertEqual(st["memoria"], "off")             # engine none
            self.assertEqual(st["tui"], "pending")

    def test_demo_instance_warns(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.inst.cfg["owner"]["name"] = "Ada (demo)"
            self.assertEqual(setup._st_instancia(b), "warn")

    def test_memoria_done_when_hindsight(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {"engine": "hindsight"})
            b.inst = config.load(b.inst.root)
            self.assertEqual(setup._st_memoria(b), "done")


class RunTests(unittest.TestCase):
    def test_unknown_step_refused(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                setup.run(b, only=["nao-existe"], auto=True)

    def test_only_rotina_writes_config(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = ScriptedUI(["America/Sao_Paulo", "08:00", "17:30", ""])
            # roda direto o passo com a UI roteirizada (run() imprime a tabela; o passo é o que importa)
            setup._run_rotina(b, ui)
            b.inst = config.load(b.inst.root)
            self.assertEqual(b.inst.cfg["work"]["start"], "08:00")
            self.assertEqual(b.inst.cfg["work"]["end"], "17:30")
            self.assertEqual(b.inst.cfg["work"]["lunch"], "")

    def test_identidade_registers_owner(self):
        with tempfile.TemporaryDirectory() as td:
            b = Brain(_inst(Path(td)))                          # sem dono no ledger
            ui = ScriptedUI(["Dona Teste"])
            setup._run_identidade(b, ui)
            self.assertIn("eu", b.state.people)
            self.assertEqual(b.state.people["eu"].name, "Dona Teste")

    def test_memoria_full_gate_requires_literal_ok(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = ScriptedUI(["sim"])                            # qualquer coisa ≠ "ok"
            setup._run_memoria(b, ui, mode_hint="full")
            self.assertEqual(memory.mode(b.inst.cfg["memory"]), "none")   # nada gravado

    def test_memoria_none_applies(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {"engine": "hindsight"})
            b.inst = config.load(b.inst.root)
            ui = ScriptedUI([])
            setup._run_memoria(b, ui, mode_hint="none")
            b.inst = config.load(b.inst.root)
            self.assertEqual(memory.mode(b.inst.cfg["memory"]), "none")

    def test_auto_ui_full_gate_refuses(self):
        """--yes + full: o gate literal não vem de default — modo não é gravado."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            (b.inst.config_dir / ".env").write_text("HINDSIGHT_API_LLM_API_KEY=sk-demo\n", encoding="utf-8")
            ui = setup.AutoUI()
            setup._run_memoria(b, ui, mode_hint="full")
            self.assertEqual(memory.mode(b.inst.cfg["memory"]), "none")


class NightlyGuardTests(unittest.TestCase):
    def test_setup_refuses_nightly(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            old = os.environ.get("BRAIN_NIGHTLY")
            os.environ["BRAIN_NIGHTLY"] = "1"
            try:
                with self.assertRaises(util.BrainError):
                    setup.cli(argparse_namespace(), b)
            finally:
                if old is None:
                    os.environ.pop("BRAIN_NIGHTLY", None)
                else:
                    os.environ["BRAIN_NIGHTLY"] = old


def argparse_namespace():
    import argparse
    return argparse.Namespace(only="", yes=False, mode=None)


class DoctorRulerTests(unittest.TestCase):
    """O doctor é a régua da instalação (plano setup-wizard, princípio 7)."""

    def _checks(self, b, path_cmd=None, framework=None):
        from brainlib import doctor
        import unittest.mock as mock
        with mock.patch.object(setup, "brain_command_status", return_value=path_cmd), \
                mock.patch.object(setup, "FRAMEWORK", framework or Path("/nonexistent-fw")):
            return doctor.checks(b)

    def test_full_without_key_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {"engine": "hindsight", "extract": True, "cloud_llm": True,
                                               "raw_awaiting_dump": "hold"})
            b.inst = config.load(b.inst.root)
            got = [c for c in self._checks(b) if c["title"] == "memória"]
            self.assertTrue(any(c["level"] == "error" and "chave de LLM" in c["detail"] for c in got))

    def test_full_with_key_no_error(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            (b.inst.env_file).write_text("HINDSIGHT_API_LLM_API_KEY=sk-demo\n", encoding="utf-8")
            config.set_keys(b.inst, "memory", {"engine": "hindsight", "extract": True, "cloud_llm": True,
                                               "raw_awaiting_dump": "hold"})
            b.inst = config.load(b.inst.root)
            got = [c for c in self._checks(b) if c["title"] == "memória" and "chave de LLM" in c["detail"]]
            self.assertEqual(got, [])

    def test_command_and_tui_ruler(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            checks = self._checks(b, path_cmd="/x/bin/brain", framework=Path(td))
            got = {c["title"]: c for c in checks}
            self.assertEqual(got["comando"]["level"], "ok")
            self.assertEqual(got["tui"]["level"], "warn")     # framework falso não tem .venv-tui
            checks2 = self._checks(b, path_cmd=None, framework=Path(td))
            got2 = {c["title"]: c for c in checks2}
            self.assertEqual(got2["comando"]["level"], "warn")
            self.assertEqual(got2["tui"]["level"], "warn")


if __name__ == "__main__":
    unittest.main()
