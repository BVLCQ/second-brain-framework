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
            ui = ScriptedUI(["America/Sao_Paulo", "08:00", "17:30"])
            # roda direto o passo com a UI roteirizada (run() imprime a tabela; o passo é o que importa)
            setup._run_rotina(b, ui)
            b.inst = config.load(b.inst.root)
            self.assertEqual(b.inst.cfg["work"]["start"], "08:00")
            self.assertEqual(b.inst.cfg["work"]["end"], "17:30")
            self.assertEqual(b.inst.cfg["work"]["lunch"], "12:00-13:00")   # não se pergunta; default intacto

    def test_identidade_registers_owner(self):
        with tempfile.TemporaryDirectory() as td:
            b = Brain(_inst(Path(td)))                          # sem dono no ledger
            ui = ScriptedUI(["Dona Teste"])
            setup._run_identidade(b, ui)
            self.assertEqual(b.owner, "dona-teste")                 # id gerado do nome, não "eu"
            self.assertIn("dona-teste", b.state.people)
            self.assertEqual(b.state.people["dona-teste"].name, "Dona Teste")
            self.assertEqual(b.inst.cfg["owner"]["id"], "dona-teste")  # e gravado no brain.toml

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

    def test_configure_memory_headless_with_reranker(self):
        """CLI/TUI headless: aceite literal, cardápio do reranker e a conta compartilhada do Fireworks."""
        from unittest import mock
        from brainlib import memory
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):      # full sem aceite
                setup.validate_memory_setup({"mode": "full", "provider": "anthropic", "key": "k"})
            with self.assertRaises(util.BrainError):      # reranker fora do registro
                setup.validate_memory_setup({"mode": "full", "consent": True, "key": "k",
                                             "reranker": "nope"})
            ze = setup.validate_memory_setup({"mode": "full", "consent": True, "key": "k",
                                              "reranker": "zeroentropy", "reranker_key": "ze-1"})
            self.assertEqual(ze["rer"], "zeroentropy")
            self.assertEqual(ze["rer_key"], "ze-1")
            self.assertTrue(setup.validate_memory_setup(
                {"mode": "full", "approval": "OK", "key": "k"})["consent"])   # literal, qualquer caixa
            with mock.patch.object(setup, "docker_available", return_value=True), \
                    mock.patch.object(setup, "hindsight_health", return_value={"status": "ok"}), \
                    mock.patch.object(setup, "compose_up", return_value=True), \
                    mock.patch.object(setup, "wait_hindsight", return_value=True), \
                    mock.patch.object(memory, "setup", side_effect=lambda bb: ["brain"]):
                final = setup.configure_memory(b, {"mode": "full", "provider": "anthropic", "key": "sk-1",
                                                   "emb_key": "fw-1", "reranker": "fireworks", "consent": True})
            self.assertEqual(final, "full")
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_LLM_API_KEY"), "sk-1")
            self.assertEqual(env.get("HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL"), "fireworks/qwen3-embedding-8b")
            self.assertEqual(env.get("HINDSIGHT_API_RERANKER_LITELLM_SDK_MODEL"),
                             "fireworks_ai/fireworks/qwen3-reranker-8b")
            self.assertEqual(env.get("HINDSIGHT_API_RERANKER_LITELLM_SDK_API_KEY"), "fw-1")   # mesma conta

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


class ProviderRegistryTests(unittest.TestCase):
    """Registro completo de provedores na porta roteada (plano onboarding-unification F5)."""

    def test_nested_zai_with_model_validates(self):
        v = setup.validate_memory_setup({
            "mode": "full", "consent": True,
            "llm": {"provider": "zai", "model": "glm-5", "key": "zk-1"},
            "embeddings": {"provider": "fireworks", "key": "fw-1"},
            "reranker": {"provider": "zeroentropy", "key": "ze-1"},
        })
        self.assertEqual(v["provider"], "zai")
        self.assertEqual(v["model"], "glm-5")
        self.assertEqual(v["slots"]["llm"]["provider"], "zai")
        self.assertEqual(v["slots"]["llm"]["model"], "glm-5")
        self.assertEqual(v["slots"]["llm"]["key"], "zk-1")
        self.assertTrue(v["slots"]["llm"]["base_url"].startswith("https://api.z.ai/"))
        self.assertEqual(v["slots"]["reranker"], {"provider": "zeroentropy", "key": "ze-1"})

    def test_zai_without_model_fills_server_default(self):
        v = setup.validate_memory_setup({
            "mode": "full", "consent": True,
            "llm": {"provider": "zai", "key": "zk-1"},
            "embeddings": {"provider": "fireworks", "key": "fw-1"},
        })
        self.assertEqual(v["provider"], "zai")
        self.assertEqual(v["model"], "glm-5.3-flash")   # cura do registro prefills o recomendado
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            from brainlib import providers
            res = providers.set_slot(b, "llm", "zai", key="zk-1")
            self.assertEqual(res["provider"], "zai")
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_LLM_MODEL"), "glm-5.3-flash")

    def test_custom_without_base_url_refuses(self):
        with self.assertRaises(util.BrainError):
            setup.validate_memory_setup({
                "mode": "full", "consent": True,
                "llm": {"provider": "custom", "model": "meu-llm", "key": "ck-1"},
                "embeddings": {"provider": "fireworks", "key": "fw-1"},
            })
        with self.assertRaises(util.BrainError):
            setup.validate_memory_setup({
                "mode": "embed",
                "embeddings": {"provider": "custom", "model": "meu-emb", "key": "ck-1"},
            })

    def test_full_with_local_embeddings_refuses(self):
        with self.assertRaises(util.BrainError):
            setup.validate_memory_setup({
                "mode": "full", "consent": True,
                "llm": {"provider": "anthropic", "key": "sk-1"},
                "embeddings": {"provider": "local"},
            })

    def test_legacy_return_coherent_for_flat_payload(self):
        v_emb = setup.validate_memory_setup({"mode": "lite", "embeddings": "fireworks", "key": "fw-1"})
        self.assertEqual(v_emb["mode"], "embed")
        self.assertEqual(v_emb["emb"], "fireworks")
        self.assertEqual(v_emb["key"], "fw-1")
        self.assertEqual(v_emb["emb_key"], "fw-1")
        self.assertNotIn("llm", v_emb["slots"])
        self.assertEqual(v_emb["slots"]["embeddings"]["key"], "fw-1")

        v_full = setup.validate_memory_setup({
            "mode": "full", "provider": "openai", "model": "gpt-5-mini",
            "key": "sk-oa", "embeddings": "cohere", "emb_key": "ck-1",
            "reranker": "openrouter", "reranker_key": "or-1", "consent": True,
        })
        self.assertEqual((v_full["provider"], v_full["emb"], v_full["rer"]), ("openai", "cohere", "openrouter"))
        self.assertEqual((v_full["key"], v_full["emb_key"], v_full["rer_key"]), ("sk-oa", "ck-1", "or-1"))
        self.assertEqual(v_full["slots"]["llm"]["model"], "gpt-5-mini")

    def test_configure_memory_fail_fast_without_key_and_without_env(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with mock.patch.object(setup, "_run_memoria") as run_mem:
                with self.assertRaises(util.BrainError) as ctx:
                    setup.configure_memory(b, {
                        "mode": "full", "consent": True,
                        "llm": {"provider": "anthropic", "key": ""},
                        "embeddings": {"provider": "fireworks", "key": "fw-1"},
                    })
                self.assertIn("HINDSIGHT_API_LLM_API_KEY", str(ctx.exception))
                run_mem.assert_not_called()


class _PainelUI:
    """UI roteirizada pro passo painel: confirm responde o que o teste quer, say acumula."""

    def __init__(self, answers: list[bool]):
        self.answers = list(answers)
        self.log: list[str] = []
        self.interactive = True

    def confirm(self, prompt: str, default: bool = False) -> bool:
        return self.answers.pop(0) if self.answers else default

    def say(self, msg: str) -> None:
        self.log.append(msg)


class PainelPinTests(unittest.TestCase):
    """O passo painel do terminal não pode divergir do wizard: instala o app E prega o atalho."""

    def setUp(self):
        from unittest import mock
        from brainlib import launcher
        self.mock = mock
        self.launcher = launcher
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.b = Brain(_inst(self.tmp))

    def tearDown(self):
        self._td.cleanup()

    def test_install_then_pin_with_same_money_as_the_wizard(self):
        with self.mock.patch.object(self.launcher, "is_installed", return_value=False), \
             self.mock.patch.object(self.launcher, "other_owner", return_value=None), \
             self.mock.patch.object(self.launcher, "install", return_value="/Applications/Brain.app"), \
             self.mock.patch.object(self.launcher, "pin_shortcut", return_value="✓ Brain pregado no Dock") as pin:
            ui = _PainelUI([True])
            setup._run_painel(self.b, ui)
        pin.assert_called_once()
        self.assertTrue(any("ícone criado" in m for m in ui.log))
        self.assertTrue(any("pregado no Dock" in m for m in ui.log))

    def test_pin_failure_never_kills_the_step(self):
        with self.mock.patch.object(self.launcher, "is_installed", return_value=False), \
             self.mock.patch.object(self.launcher, "other_owner", return_value=None), \
             self.mock.patch.object(self.launcher, "install", return_value="/Applications/Brain.app"), \
             self.mock.patch.object(self.launcher, "pin_shortcut", side_effect=OSError("dock travado")):
            ui = _PainelUI([True])
            setup._run_painel(self.b, ui)
        self.assertTrue(any("ícone criado" in m for m in ui.log))     # o passo seguiu
        self.assertTrue(any("atalho de um clique" in m for m in ui.log))


class LmStudioTests(unittest.TestCase):
    """Probe granular + lmstudio_ensure: o Brain instala, sobe e configura o LM Studio sozinho
    (ruling 2026-11-19 — instalado nunca mais vira "falta — baixar")."""

    def test_state_distingue_up_instalado_e_ausente(self):
        from unittest import mock
        app = Path("/Applications/LM Studio.app")
        self.assertEqual(setup.lmstudio_state(up=True), "up")
        self.assertEqual(setup.lmstudio_state(up=False, which=lambda c: None,
                                              exists=lambda p: p == app), "installed")
        self.assertEqual(setup.lmstudio_state(up=False, which=lambda c: "/usr/local/bin/lms",
                                              exists=lambda p: False), "installed")
        with tempfile.TemporaryDirectory() as td:                    # sem lms no PATH, sem app
            with mock.patch.dict(os.environ, {"HOME": td}), \
                    mock.patch.object(setup, "_LMS_APP_DIRS", ()):
                self.assertEqual(setup.lmstudio_state(up=False, which=lambda c: None), "missing")

    def _nua(self, home: Path):
        """run fake da máquina nua: bash install.sh cria o lms; lms responde por subcomando."""
        disk: list[str] = []

        def fake_run(cmd, cwd=None, timeout=120):
            if cmd[0] == "bash":
                b = home / ".lmstudio" / "bin"
                b.mkdir(parents=True, exist_ok=True)
                f = b / "lms"
                f.write_text("#!/bin/sh\n", encoding="utf-8")
                f.chmod(0o755)                                        # `which` exige executável
                return 0, "installed"
            a = cmd[1:]
            if a[:1] == ["ls"]:
                return 0, " \n".join(disk) or "(vazio)"
            if a[:2] == ["server", "start"]:
                return 0, "started"
            if a[:1] == ["get"]:
                disk.append("text-embedding-bge-m3")
                return 0, "downloaded"
            if a[:1] == ["load"]:
                return 0, "loaded"
            return 1, f"? {cmd}"

        return fake_run, disk

    def test_ensure_na_maquina_nua_instala_sobe_baixa_e_carrega(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            fake_run, _ = self._nua(home)
            with mock.patch.dict(os.environ, {"HOME": td}), \
                    mock.patch.object(setup, "_LMS_APP_DIRS", ()), \
                    mock.patch.object(setup, "_fetch",
                                      side_effect=lambda url, dest, timeout=120:
                                      (dest.write_text("#!/bin/sh\n", encoding="utf-8"), None)[1]):
                # 1ª leitura (antes do server start) falsa, demais verdadeiras:
                ups = iter([False, True, True, True])
                with mock.patch.object(setup, "lmstudio_up", side_effect=lambda: next(ups, True)):
                    ui = ScriptedUI([])
                    ok = setup.lmstudio_ensure(ui, run=fake_run, which=lambda c: None)
            self.assertTrue(ok, ui.said)
            self.assertTrue(any("LM Studio instalado" in s for s in ui.said))
            self.assertTrue(any("servidor do LM Studio no ar" in s for s in ui.said))
            self.assertTrue(any("modelo text-embedding-bge-m3 no disco" in s for s in ui.said))
            self.assertTrue(any("modelo text-embedding-bge-m3 carregado" in s for s in ui.said))

    def test_ensure_com_modelo_ausente_baixa(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            fake_run, _ = self._nua(home)
            lms = home / ".lmstudio" / "bin" / "lms"                  # já instalado, sem app
            lms.parent.mkdir(parents=True, exist_ok=True)
            lms.write_text("#!/bin/sh\n", encoding="utf-8")
            lms.chmod(0o755)
            got: list[list[str]] = []
            orig = fake_run

            def run_rec(cmd, cwd=None, timeout=120):
                if cmd[:1] == [str(lms)] and cmd[1:2] == ["get"]:
                    got.append(cmd[1:])
                return orig(cmd, cwd=cwd, timeout=timeout)

            with mock.patch.dict(os.environ, {"HOME": td}), \
                    mock.patch.object(setup, "_LMS_APP_DIRS", ()):
                # 1ª leitura (antes do server start) falsa, demais verdadeiras:
                ups = iter([False, True, True])
                with mock.patch.object(setup, "lmstudio_up", side_effect=lambda: next(ups, True)):
                    ui = ScriptedUI([])
                    ok = setup.lmstudio_ensure(ui, run=run_rec, which=lambda c: str(lms) if c == "lms" else None)
            self.assertTrue(ok, ui.said)
            self.assertEqual(got, [["get", "text-embedding-bge-m3", "-y"]])

    def test_ensure_no_wsl_nao_instala_e_explica(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:                    # sem lms na máquina isolada
            with mock.patch.dict(os.environ, {"HOME": td}), \
                    mock.patch.object(util, "in_wsl", return_value=True), \
                    mock.patch.object(setup, "_LMS_APP_DIRS", ()):
                calls: list = []

                def no_run(cmd, cwd=None, timeout=120):
                    calls.append(cmd)
                    return 0, ""

                ui = ScriptedUI([])
                ok = setup.lmstudio_ensure(ui, run=no_run, which=lambda c: None)
        self.assertFalse(ok)
        self.assertEqual(calls, [])                                   # nada executa
        self.assertTrue(any("host Windows" in s for s in ui.said))

    def test_ensure_tudo_pronto_apenas_carrega(self):
        from unittest import mock
        calls: list = []

        def fake_run(cmd, cwd=None, timeout=120):
            calls.append(cmd[1:2])
            return (0, "text-embedding-bge-m3") if cmd[1:2] == ["ls"] else (0, "ok")

        with mock.patch.object(setup, "lmstudio_up", return_value=True):
            ui = ScriptedUI([])
            ok = setup.lmstudio_ensure(ui, run=fake_run, which=lambda c: "/opt/lms")
        self.assertTrue(ok, ui.said)
        self.assertEqual(calls, [["ls"], ["load"]])                   # nada de bash/server/get
        self.assertTrue(any("carregado" in s for s in ui.said))

    def test_ensure_fallback_do_get_quando_staff_picks_nao_resolve(self):
        from unittest import mock
        gets: list[str] = []
        disk: list[str] = []

        def fake_run(cmd, cwd=None, timeout=120):
            a = cmd[1:]
            if a[:1] == ["ls"]:
                return 0, " ".join(disk)
            if a[:1] == ["get"]:
                gets.append(a[1])
                if a[1].startswith("https://"):        # só a URL do HF resolve
                    disk.append("text-embedding-bge-m3")
                    return 0, "downloaded"
                return 1, "No staff picks found"
            return 0, "ok"

        with mock.patch.object(setup, "lmstudio_up", return_value=True):
            ui = ScriptedUI([])
            ok = setup.lmstudio_ensure(ui, run=fake_run, which=lambda c: "/opt/lms")
        self.assertTrue(ok, ui.said)
        self.assertEqual(gets, ["text-embedding-bge-m3",
                                setup.LMS_GET_FALLBACK["text-embedding-bge-m3"]])

    def test_run_memoria_garante_lmstudio_antes_do_compose(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            order: list = []

            def up() -> bool:
                return "ensure" in order                              # o ensure resolve; depois é True

            with mock.patch.object(setup, "docker_available", return_value=True), \
                    mock.patch.object(setup, "hindsight_health", return_value=None), \
                    mock.patch.object(setup, "compose_up",
                                      side_effect=lambda *a, **k: order.append("compose") or True), \
                    mock.patch.object(setup, "wait_hindsight", return_value=True), \
                    mock.patch.object(setup, "lmstudio_up", side_effect=up), \
                    mock.patch.object(setup, "lmstudio_ensure",
                                      side_effect=lambda ui_, model="": order.append("ensure") or True), \
                    mock.patch.object(setup, "_run", return_value=(0, "sync ok")), \
                    mock.patch.object(memory, "setup", side_effect=lambda bb: ["brain"]):
                ui = ScriptedUI([])
                setup._run_memoria(b, ui, mode_hint="embed")
            self.assertEqual(order[:2], ["ensure", "compose"])        # boot do Hindsight exige embeddings antes
            self.assertTrue(any("LM Studio pronto para o Brain" in s for s in ui.said))


if __name__ == "__main__":
    unittest.main()
