"""Provedores LLM por assinatura, bloqueio de LLM local e doctor slot-aware (#59)."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brainlib import cli, config, doctor, memory, providers, setup, util
from brainlib.core import Brain

SUBSCRIPTION_IDS = ("claude-code", "chatgpt", "cursor", "github-copilot", "xai-oauth", "nous")
KEY_IDS = ("anthropic", "openai", "fireworks", "zai", "gemini", "minimax", "custom")


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n',
        encoding="utf-8",
    )
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


def _run_cli(root: Path, argv: list[str]) -> str:
    parser = cli.build_parser()
    args = parser.parse_args(argv)
    b = Brain(config.load(root))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        args.fn(args, b)
    return buf.getvalue()


class RegistryTests(unittest.TestCase):
    def test_subscription_and_key_families_in_registry(self):
        llm = providers.PROVIDERS["llm"]
        for pid in SUBSCRIPTION_IDS:
            self.assertIn(pid, llm)
            entry = llm[pid]
            self.assertEqual(entry["family"], "subscription")
            self.assertEqual(entry["key_env"], "")
            self.assertEqual(entry["cost_mode"], "subscription")
            self.assertTrue(entry["setup_hint"].strip())
            self.assertTrue(entry["rate_limit_note"].strip())

        for pid in KEY_IDS:
            self.assertIn(pid, llm)
            self.assertEqual(llm[pid]["family"], "key")
            self.assertEqual(llm[pid]["key_env"], "HINDSIGHT_API_LLM_API_KEY")

        for blocked in ("lmstudio", "ollama", "llama.cpp"):
            self.assertNotIn(blocked, llm)
            self.assertIn(blocked, providers.LOCAL_LLM_BLOCKED)

        self.assertIn("local", providers.PROVIDERS["embeddings"])


class SetSlotAndStackTests(unittest.TestCase):
    def test_blocked_local_llms_raise_brain_error(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for blocked in ("lmstudio", "ollama", "llama.cpp"):
                with self.assertRaises(util.BrainError) as ctx:
                    providers.set_slot(b, "llm", blocked)
                self.assertEqual(ctx.exception.code, 4)

    def test_subscription_set_slot_requires_no_key_or_model(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            res = providers.set_slot(b, "llm", "claude-code")
            self.assertEqual(res["provider"], "claude-code")
            self.assertEqual(res["family"], "subscription")
            self.assertTrue(res["setup_hint"])
            self.assertTrue(res["rate_limit_note"])

            mem = b.inst.cfg["memory"]
            self.assertEqual(mem["llm_provider"], "claude-code")
            # tabela Haiku 5.5 por operação (régua do dono) vai ao [memory] e ao .env
            self.assertEqual(mem.get("llm_models", ""),
                             "retain=claude-haiku-5-5,consolidation=claude-haiku-5-5,"
                             "mental_models=claude-haiku-5-5,reflect=claude-haiku-5-5,default=claude-haiku-5-5")

            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_LLM_PROVIDER"], "claude-code")
            self.assertEqual(env["HINDSIGHT_API_LLM_REASONING_EFFORT"], "high")
            self.assertNotIn("HINDSIGHT_API_LLM_API_KEY", env)

            st = providers.stack(b)["llm"]
            self.assertEqual(st["family"], "subscription")
            self.assertEqual(st["cost_mode"], "subscription")
            self.assertFalse(st["legacy_local"])
            self.assertFalse(st["key_required"])

    def test_stack_legacy_lmstudio_does_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {"llm_provider": "lmstudio"})
            b.inst = config.load(b.inst.root)
            st = providers.stack(b)["llm"]
            self.assertEqual(st["provider"], "lmstudio")
            self.assertTrue(st["legacy_local"])
            self.assertFalse(st["key_required"])


class DoctorSlotAwareTests(unittest.TestCase):
    def _checks(self, b: Brain) -> list[dict]:
        with mock.patch.object(setup, "brain_command_status", return_value="/usr/local/bin/brain"), \
                mock.patch.object(setup, "FRAMEWORK", Path("/nonexistent-fw")):
            return doctor.checks(b)

    def test_full_subscription_without_credential_is_error_naming_auth(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": True, "cloud_llm": True,
                "raw_awaiting_dump": "hold", "llm_provider": "claude-code",
                "embeddings_provider": "fireworks",
            })
            b.inst.env_file.write_text("HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=fw-1\n", encoding="utf-8")
            b.inst = config.load(b.inst.root)
            cks = self._checks(b)
            llm_ck = next(c for c in cks if c["title"] == "memória · LLM")
            self.assertEqual(llm_ck["level"], "error")
            self.assertIn("brain memory auth claude-code", llm_ck["detail"])

    def test_full_subscription_with_token_is_ok(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": True, "cloud_llm": True,
                "raw_awaiting_dump": "hold", "llm_provider": "claude-code",
                "embeddings_provider": "fireworks",
            })
            b.inst.env_file.write_text("HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=fw-1\n"
                                       "HINDSIGHT_API_LLM_API_KEY=" + "sk-" + "ant-oat01-demo-token\n",
                                       encoding="utf-8")
            b.inst = config.load(b.inst.root)
            cks = self._checks(b)
            llm_ck = next(c for c in cks if c["title"] == "memória · LLM")
            self.assertEqual(llm_ck["level"], "ok")
            self.assertIn("assinatura", llm_ck["detail"])
            self.assertIn("token", llm_ck["detail"])

    def test_full_anthropic_without_key_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": True, "cloud_llm": True,
                "raw_awaiting_dump": "hold", "llm_provider": "anthropic",
                "embeddings_provider": "fireworks",
            })
            b.inst.env_file.write_text("HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=fw-1\n", encoding="utf-8")
            b.inst = config.load(b.inst.root)
            cks = self._checks(b)
            llm_ck = next(c for c in cks if c["title"] == "memória · LLM")
            self.assertEqual(llm_ck["level"], "error")

    def test_full_legacy_lmstudio_is_error_without_keyerror(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": True, "cloud_llm": True,
                "raw_awaiting_dump": "hold", "llm_provider": "lmstudio",
                "embeddings_provider": "fireworks",
            })
            b.inst.env_file.write_text("HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=fw-1\n", encoding="utf-8")
            b.inst = config.load(b.inst.root)
            cks = self._checks(b)
            llm_ck = next(c for c in cks if c["title"] == "memória · LLM")
            self.assertEqual(llm_ck["level"], "error")

    def test_embed_local_and_reranker_off_without_env_all_valid(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": False, "cloud_llm": False,
                "raw_awaiting_dump": "degraded",
                "embeddings_provider": "local", "reranker_provider": "off",
            })
            b.inst = config.load(b.inst.root)
            cks = self._checks(b)
            slot_cks = [c for c in cks if c["title"].startswith("memória · ")]
            self.assertEqual(len(slot_cks), 4)                # llm · embeddings · reranker · decisão
            self.assertTrue(all(c["level"] == "ok" for c in slot_cks))

    def test_reranker_cohere_without_key_errors_only_on_reranker(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": False, "cloud_llm": False,
                "raw_awaiting_dump": "degraded",
                "embeddings_provider": "local", "reranker_provider": "cohere",
            })
            b.inst = config.load(b.inst.root)
            cks = self._checks(b)
            by_title = {c["title"]: c for c in cks if c["title"].startswith("memória · ")}
            self.assertEqual(by_title["memória · LLM"]["level"], "ok")
            self.assertEqual(by_title["memória · embeddings"]["level"], "ok")
            self.assertEqual(by_title["memória · reranker"]["level"], "error")


class DoctorFullLocalEmbeddingsTests(unittest.TestCase):
    """Full + embeddings `local`: o aviso de \"só-nuvem\" saiu; o estado real do LM Studio decide ok/warn."""

    def _slot(self, b: Brain, state: str) -> dict:
        with mock.patch.object(setup, "brain_command_status", return_value="/usr/local/bin/brain"), \
                mock.patch.object(setup, "FRAMEWORK", Path("/nonexistent-fw")), \
                mock.patch.object(setup, "lmstudio_state", return_value=state):
            cks = doctor.checks(b)
        return {c["title"]: c for c in cks if c["title"].startswith("memória · ")}

    def _full(self, b: Brain, emb: str) -> None:
        config.set_keys(b.inst, "memory", {
            "engine": "hindsight", "extract": True, "cloud_llm": True, "raw_awaiting_dump": "hold",
            "llm_provider": "claude-code", "embeddings_provider": emb,
            "cloud_embeddings": emb != "local", "reranker_provider": "off"})
        b.inst.env_file.write_text("HINDSIGHT_API_LLM_API_KEY=sk-ant-demo\n", encoding="utf-8")
        b.inst = config.load(b.inst.root)

    def test_lmstudio_up_is_ok_and_states_the_egress(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self._full(b, "local")
            emb = self._slot(b, "up")["memória · embeddings"]
            self.assertEqual(emb["level"], "ok")
            self.assertIn("o LLM continua na nuvem", emb["detail"])
            self.assertNotIn("só-nuvem", emb["detail"])

    def test_lmstudio_down_or_missing_warns_with_the_command(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self._full(b, "local")
            for state, why in (("installed", "servidor desligado"), ("missing", "ausente")):
                emb = self._slot(b, state)["memória · embeddings"]
                self.assertEqual(emb["level"], "warn", state)
                self.assertIn(why, emb["detail"])
                self.assertIn("brain setup --only memoria", emb["detail"])

    def test_cloud_embeddings_without_key_is_still_an_error_in_full(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self._full(b, "fireworks")
            emb = self._slot(b, "up")["memória · embeddings"]
            self.assertEqual(emb["level"], "error")
            self.assertIn("sem a chave", emb["detail"])


class CostAndCliTests(unittest.TestCase):
    def test_memory_cost_subscription_text_and_json(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp)
            providers.set_slot(b, "llm", "claude-code")
            config.set_keys(b.inst, "memory", {
                "extract": True, "cloud_llm": True, "raw_awaiting_dump": "hold",
            })
            b.inst = config.load(tmp)

            c = memory.cost(b)
            self.assertEqual(c["billing"], "subscription")
            self.assertEqual(c["billing_note"], "custo incluído no plano, sujeito a limite")
            self.assertIn("custo incluído no plano, sujeito a limite", c["detail"])

            out_txt = _run_cli(tmp, ["memory", "cost"])
            self.assertIn("custo incluído no plano, sujeito a limite", out_txt)

            out_json = _run_cli(tmp, ["memory", "cost", "--json"])
            parsed = json.loads(out_json)
            self.assertEqual(parsed["billing"], "subscription")
            self.assertEqual(parsed["billing_note"], "custo incluído no plano, sujeito a limite")

    def test_cli_memory_providers_lists_families_and_sets_subscription(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _brain(tmp)

            out_list = _run_cli(tmp, ["memory", "providers"])
            self.assertIn("Assinatura (sem chave de API)", out_list)
            self.assertIn("Chave de API", out_list)
            self.assertIn("claude-code", out_list)
            self.assertIn("gemini", out_list)

            out_set = _run_cli(tmp, ["memory", "providers", "set", "llm", "--provider", "cursor"])
            self.assertIn("Cursor (assinatura)", out_set)
            self.assertIn("Custo incluído no plano, sujeito ao limite de taxa da assinatura.", out_set)

            cfg = config.load(tmp).cfg["memory"]
            self.assertEqual(cfg["llm_provider"], "cursor")


class AuthStateTests(unittest.TestCase):
    """providers.auth_state: o que o painel/doctor/noturno leem do provedor de assinatura."""

    def _brain_with(self, tmp: Path, provider: str) -> Brain:
        b = _brain(tmp)
        config.set_keys(b.inst, "memory", {"llm_provider": provider})
        b.inst = config.load(tmp)
        return b

    def test_claude_code_pending_without_token_and_ok_with_it(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = self._brain_with(tmp, "claude-code")
            st = providers.auth_state(b)
            self.assertEqual(st["state"], "pending")
            self.assertEqual(st["fix"], "brain memory auth claude-code")
            self.assertEqual(st["flow"], "claude-token")

            b.inst.env_file.write_text("HINDSIGHT_API_LLM_API_KEY=" + "sk-" + "ant-oat01-demo\n", encoding="utf-8")
            b.inst = config.load(tmp)
            self.assertEqual(providers.auth_state(b)["state"], "ok")

    def test_xai_state_from_container_store_probe(self):
        class _Res:
            def __init__(self, rc): self.returncode = rc

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = self._brain_with(tmp, "xai-oauth")
            providers._AUTH_CACHE.update(at=0.0, value=None)
            st = providers.auth_state(b, run=lambda *a, **k: _Res(0))
            self.assertEqual(st["state"], "ok")
            providers._AUTH_CACHE.update(at=0.0, value=None)
            st = providers.auth_state(b, run=lambda *a, **k: _Res(1))
            self.assertEqual(st["state"], "pending")
            self.assertEqual(st["fix"], "brain memory auth xai-oauth")
            providers._AUTH_CACHE.update(at=0.0, value=None)

            def _boom(*a, **k): raise OSError("docker ausente")
            st = providers.auth_state(b, run=_boom)
            self.assertEqual(st["state"], "unknown")
            providers._AUTH_CACHE.update(at=0.0, value=None)

    def test_key_provider_and_manual_flow_states(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = self._brain_with(tmp, "anthropic")
            self.assertEqual(providers.auth_state(b)["state"], "na")
            config.set_keys(b.inst, "memory", {"llm_provider": "chatgpt"})
            b.inst = config.load(tmp)
            st = providers.auth_state(b)
            self.assertEqual(st["state"], "manual")
            self.assertTrue(st["note"])


class _LogUI:
    interactive = False

    def __init__(self): self.log: list[str] = []

    def say(self, msg): self.log.append(str(msg))


class RunLlmAuthTests(unittest.TestCase):
    """setup.run_llm_auth: fluxo visível do botão Autenticar / `brain memory auth`."""

    def test_non_subscription_refuses_with_the_list(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = _LogUI()
            self.assertFalse(setup.run_llm_auth(b, ui, "anthropic"))
            self.assertTrue(any("assinatura" in ln for ln in ui.log))

    def test_nightly_gate_raises(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with mock.patch.dict("os.environ", {"BRAIN_NIGHTLY": "1"}):
                with self.assertRaises(util.BrainError):
                    setup.run_llm_auth(b, _LogUI(), "claude-code")

    def test_claude_token_flow_without_cli_narrates_install(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = _LogUI()
            with mock.patch.object(setup.shutil, "which", return_value=None):
                self.assertFalse(setup.run_llm_auth(b, ui, "claude-code"))
            self.assertTrue(any("brew install" in ln or "npm install" in ln for ln in ui.log))

    def test_claude_token_flow_captures_token_into_env_and_never_echoes_it(self):
        token = "sk-" + "ant-oat01-" + "x" * 30
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp)
            ui = _LogUI()
            with mock.patch.object(setup.shutil, "which", return_value="/usr/local/bin/claude"), \
                    mock.patch.object(setup, "_run", return_value=(0, f"Long-lived token:\n{token}\n")), \
                    mock.patch.object(memory, "mode", return_value="full"):
                self.assertTrue(setup.run_llm_auth(b, ui, "claude-code"))
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_LLM_API_KEY"), token)
            self.assertFalse(any(token in ln or "x" * 30 in ln for ln in ui.log))
            self.assertTrue(any("config/.env" in ln for ln in ui.log))

    def test_claude_token_flow_failure_redacts_and_narrates_login(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = _LogUI()
            with mock.patch.object(setup.shutil, "which", return_value="/usr/local/bin/claude"), \
                    mock.patch.object(setup, "_run",
                                      return_value=(1, "not logged in — " + "sk-" + "ant-short-abcdef123 run claude first")):
                self.assertFalse(setup.run_llm_auth(b, ui, "claude-code"))
            self.assertTrue(any("falta login" in ln for ln in ui.log))
            self.assertFalse(any("ant-short-abcdef123" in ln for ln in ui.log))

    def test_manual_flow_provider_narrates_hint(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = _LogUI()
            self.assertFalse(setup.run_llm_auth(b, ui, "chatgpt"))
            self.assertTrue(any("sem fluxo automático" in ln for ln in ui.log))

    def test_cli_memory_auth_runs_flow(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _brain(tmp)
            with mock.patch.object(setup.shutil, "which", return_value=None):
                out = _run_cli(tmp, ["memory", "auth", "claude-code"])
            self.assertIn("Claude Code CLI não encontrado", out)

    def test_configure_memory_accepts_subscription_without_key(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {"extract": True, "cloud_llm": True, "raw_awaiting_dump": "hold"})
            b.inst = config.load(b.inst.root)
            with mock.patch.object(setup, "_run_memoria") as run_mem:
                v = setup.configure_memory(b, {
                    "mode": "full", "consent": True,
                    "llm": {"provider": "claude-code"},
                    "embeddings": {"provider": "fireworks", "key": "fw-1"},
                })
                self.assertEqual(v, "full")
                run_mem.assert_called_once()


class ModelDefaultsTests(unittest.TestCase):
    """Vazio = recomendado do provedor: default_model (precedência registro → servidor pinado),
    preenchimento explícito no set_slot e modelo digitado vencendo a tabela por operação."""

    def test_server_defaults_cover_the_llm_menu(self):
        for pid in providers.PROVIDERS["llm"]:
            if pid == "custom":
                continue
            self.assertTrue(providers.default_model(pid), f"{pid} sem default conhecido")

    def test_default_model_precedence(self):
        # cura do registro (pesquisada na leaderboard da Hindsight, 2026-11-19) vence a
        # tabela do servidor pinado em TODOS os curados
        self.assertEqual(providers.default_model("anthropic"),
                         providers.PROVIDERS["llm"]["anthropic"]["models"]["default"])   # haiku-5.5
        self.assertEqual(providers.default_model("fireworks"),
                         providers.PROVIDERS["llm"]["fireworks"]["model"])
        self.assertEqual(providers.default_model("openai"), "gpt-6-luna")
        self.assertEqual(providers.default_model("zai"), "glm-5.3-flash")
        self.assertEqual(providers.default_model("gemini"), "gemini-3.1-flash-lite")
        self.assertEqual(providers.default_model("minimax"), "MiniMax-M3.1-Flash")
        self.assertEqual(providers.default_model("claude-code"), "claude-haiku-5-5")     # régua do dono
        self.assertEqual(providers.default_model("xai-oauth"), "grok-4.7")               # = preço do 4.6
        self.assertEqual(providers.default_model("custom"), "")

    def test_set_slot_blank_model_writes_default_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "openai", key="ok-1")
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_LLM_MODEL"), "gpt-6-luna")

    def test_haiku_effort_high_written_for_both_claude_lanes(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for provider in ("anthropic", "claude-code"):
                providers.set_slot(b, "llm", provider)
                env = config.load_env(b.inst)
                # cada lane pelo caminho que o servidor 1.3.0 aplica: claude-code → --effort (REASONING_EFFORT);
                # API Anthropic → output_config.effort no extra body (o lane ignora REASONING_EFFORT)
                if provider == "claude-code":
                    self.assertEqual(env.get("HINDSIGHT_API_LLM_REASONING_EFFORT"), "high")
                    self.assertNotIn("HINDSIGHT_API_LLM_EXTRA_BODY", env)
                else:
                    self.assertEqual(json.loads(env["HINDSIGHT_API_LLM_EXTRA_BODY"]), {"output_config": {"effort": "high"}})
                    self.assertNotIn("HINDSIGHT_API_LLM_REASONING_EFFORT", env)
                self.assertEqual(env.get("HINDSIGHT_API_RETAIN_LLM_MODEL"), "claude-haiku-5-5")
                self.assertEqual(env.get("HINDSIGHT_API_MENTAL_MODEL_REFRESH_LLM_MODEL"),
                                 "claude-haiku-5-5")   # Sonnet saiu: régua do dono é Haiku em tudo

    def test_set_slot_custom_without_model_still_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "llm", "custom", key="ck-1")

    def test_typed_model_beats_per_operation_table(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = setup.ScriptedMemoriaUI(_LogUI(), {"LLM": "anthropic"}, {"HINDSIGHT_API_LLM_API_KEY": "ak-1"},
                                         "claude-sonnet-5-5", consent=True, models_override=True)
            setup._providers_step(b, ui, ["llm"])
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_LLM_MODEL"), "claude-sonnet-5-5")
            self.assertNotIn("HINDSIGHT_API_RETAIN_LLM_MODEL", env)   # cenário B fora: modelo único

    def test_blank_model_on_anthropic_keeps_per_operation_table(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = setup.ScriptedMemoriaUI(_LogUI(), {"LLM": "anthropic"}, {"HINDSIGHT_API_LLM_API_KEY": "ak-1"},
                                         "", consent=True)
            setup._providers_step(b, ui, ["llm"])
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_RETAIN_LLM_MODEL"), "claude-haiku-5-5")   # tabela por operação
            self.assertEqual(env.get("HINDSIGHT_API_MENTAL_MODEL_REFRESH_LLM_MODEL"), "claude-haiku-5-5")


class DecisionSlotTests(unittest.TestCase):
    """Slot decisão (opcional): off de fábrica, hosted hindsight com chave hsk_, doctor fiscaliza."""

    def test_registry_and_set_slot(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self.assertIn("off", providers.PROVIDERS["decision"])
            self.assertEqual(providers.PROVIDERS["decision"]["hindsight"]["model"], "hs-decide-1-flash")

            providers.set_slot(b, "decision", "off")
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_PROVIDER"), "none")
            self.assertNotIn("HINDSIGHT_API_DECISION_MODEL_API_KEY", env)

            providers.set_slot(b, "decision", "hindsight", key="hsk-demo-1")
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_PROVIDER"), "hindsight")
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_MODEL"), "hs-decide-1-flash")
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_API_KEY"), "hsk-demo-1")
            self.assertEqual(config.load(b.inst.root).cfg["memory"].get("decision_provider"), "hindsight")

            st = providers.stack(b)["decision"]
            self.assertEqual(st["provider"], "hindsight")
            self.assertTrue(st["key_present"])

    def test_doctor_off_ok_and_hindsight_needs_key(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": False, "cloud_llm": False,
                "raw_awaiting_dump": "degraded", "embeddings_provider": "local",
            })
            b.inst = config.load(b.inst.root)
            with mock.patch.object(setup, "brain_command_status", return_value="/usr/local/bin/brain"), \
                    mock.patch.object(setup, "FRAMEWORK", Path("/nonexistent-fw")):
                cks = doctor.checks(b)
            dec = next(c for c in cks if c["title"] == "memória · decisão")
            self.assertEqual(dec["level"], "ok")
            self.assertIn("desligado", dec["detail"])

            config.set_keys(b.inst, "memory", {"decision_provider": "hindsight"})
            b.inst = config.load(b.inst.root)
            with mock.patch.object(setup, "brain_command_status", return_value="/usr/local/bin/brain"), \
                    mock.patch.object(setup, "FRAMEWORK", Path("/nonexistent-fw")):
                cks = doctor.checks(b)
            dec = next(c for c in cks if c["title"] == "memória · decisão")
            self.assertEqual(dec["level"], "error")
            self.assertIn("hsk_", dec["detail"])

            b.inst.env_file.write_text("HINDSIGHT_API_DECISION_MODEL_API_KEY=hsk-demo-2\n", encoding="utf-8")
            b.inst = config.load(b.inst.root)
            with mock.patch.object(setup, "brain_command_status", return_value="/usr/local/bin/brain"), \
                    mock.patch.object(setup, "FRAMEWORK", Path("/nonexistent-fw")):
                cks = doctor.checks(b)
            dec = next(c for c in cks if c["title"] == "memória · decisão")
            self.assertEqual(dec["level"], "ok")

    def test_validate_and_configure_fail_fast_without_key(self):
        v = setup.validate_memory_setup({
            "mode": "full", "consent": True,
            "llm": {"provider": "claude-code"},
            "embeddings": {"provider": "fireworks", "key": "fw-1"},
            "decision": {"provider": "hindsight"},
        })
        self.assertEqual(v["dec"], "hindsight")
        self.assertEqual(v["slots"]["decision"]["provider"], "hindsight")

        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError) as ctx:
                setup.configure_memory(b, {
                    "mode": "full", "consent": True,
                    "llm": {"provider": "claude-code"},
                    "embeddings": {"provider": "fireworks", "key": "fw-1"},
                    "decision": {"provider": "hindsight"},     # sem chave e sem chave no .env
                })
            self.assertIn("HINDSIGHT_API_DECISION_MODEL_API_KEY", str(ctx.exception))

    def test_off_is_the_default_and_skippable(self):
        v = setup.validate_memory_setup({"mode": "full", "consent": True,
                                         "llm": {"provider": "claude-code"},
                                         "embeddings": {"provider": "fireworks", "key": "fw-1"}})
        self.assertEqual(v["dec"], "off")                     # pular = só os tokens do próprio LLM
        self.assertEqual(v["slots"]["decision"]["provider"], "off")


if __name__ == "__main__":
    unittest.main()
