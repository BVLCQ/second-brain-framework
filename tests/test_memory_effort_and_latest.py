"""Memória: decisor de nuvem (Hindsight · OpenAI · Typesafe), esforço do LLM por modelo e o padrão que acompanha o
modelo mais novo da linha.

Fixa:
1. o catálogo — linha e versão de cada id (Claude, GPT, Grok, Gemini), o mais novo da linha e os níveis de esforço de
   cada modelo (regras dos fornecedores; versão nova herda; a API da Anthropic, quando lida, vence a regra);
2. o esforço chega ao servidor pelo caminho que o lane aplica (Hindsight 1.3.0): REASONING_EFFORT no Claude Code /
   OpenAI / ChatGPT / xAI, `output_config.effort` no extra body da API Anthropic, `thinking_config` no Gemini — e o
   resto do extra body do dono fica;
3. campo vazio = o mais novo da linha; digitado = fixo; a checagem diária move só o que segue o padrão, recria o
   servidor e, se o LLM não responder, volta ao modelo de antes;
4. cada decisor de nuvem guarda a sua chave: a variável que o servidor lê é sempre a do ativo;
5. o painel manda esforço e recall de nuvem pela rota do passo Memória.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from brainlib import config, models_catalog as mc, onboard, providers, setup, util  # noqa: E402
from test_eng_setup_headless_slots import _brain  # noqa: E402

L5 = ["low", "medium", "high", "xhigh", "max"]


def _full(b) -> None:
    config.set_keys(b.inst, "memory", {"engine": "hindsight", "extract": True, "cloud_llm": True})
    b.inst = config.load(b.inst.root)


def _seed_catalog(b, provider: str, ids: list[str], at: float = 1e12) -> None:
    models = []
    for i in ids:
        p = mc.parse(i)
        models.append({"id": p["id"], "line": p["line"], "version": list(p["version"])})
    data = mc.load_cache(b)
    data.setdefault("providers", {})[provider] = {"source": "openrouter", "at": at, "error": "", "models": models}
    mc._save_cache(b, data)


def _openrouter(ids: list[str]):
    def http(url, headers):
        if "openrouter" not in url:
            raise urllib.error.URLError("sem rede no teste")
        return {"data": [{"id": i, "created": 1} for i in ids]}
    return http


class CatalogParsing(unittest.TestCase):
    def test_lines_and_versions(self):
        self.assertEqual(mc.parse("claude-haiku-5-5")["line"], "claude-haiku")
        self.assertEqual(mc.parse("claude-haiku-5.6")["id"], "claude-haiku-5-6")          # forma do OpenRouter
        self.assertEqual(mc.parse("claude-opus-5")["version"], (5, 0))
        self.assertEqual(mc.parse("gpt-6.1-terra")["line"], "gpt-terra")
        self.assertEqual(mc.parse("gpt-6.1-terra")["version"], (6, 1))
        self.assertEqual(mc.parse("gpt-5-nano")["line"], "gpt-nano")
        self.assertEqual(mc.parse("grok-4.7")["line"], "grok")
        self.assertEqual(mc.parse("gemini-3.5-flash-lite")["line"], "gemini-flash-lite")
        self.assertEqual(mc.parse("gemini-4-hydrogen")["line"], "gemini-hydrogen")
        for snapshot in ("claude-sonnet-4-5-20250929", "gemini-3-flash-preview", "gpt-6-luna-2026-09-22", "o3"):
            self.assertIsNone(mc.parse(snapshot), snapshot)

    def test_newest_of_the_line(self):
        cat = [{"id": i, "line": mc.parse(i)["line"], "version": list(mc.parse(i)["version"])}
               for i in ("claude-haiku-5-5", "claude-haiku-5-6", "claude-sonnet-6", "claude-haiku-4-5")]
        self.assertEqual(mc.newest("claude-haiku-5-5", cat), "claude-haiku-5-6")       # Haiku 5.6 move o padrão
        self.assertEqual(mc.newest("claude-haiku-5-6", cat), "claude-haiku-5-6")
        self.assertEqual(mc.newest("custom-model", cat), "custom-model")              # fora das regras: a semente
        self.assertEqual(mc.newest("claude-haiku-5-5", []), "claude-haiku-5-5")       # sem catálogo: a semente


class EffortLevels(unittest.TestCase):
    def test_vendor_levels_per_model(self):
        e = mc.efforts("claude-code", "claude-haiku-5-5")
        self.assertEqual((e["levels"], e["default"], e["inferred"]), (L5, "medium", False))
        self.assertEqual(mc.efforts("anthropic", "claude-opus-4-6")["levels"], ["low", "medium", "high", "max"])
        self.assertEqual(mc.efforts("anthropic", "claude-haiku-4-5")["levels"], [])    # Haiku 4.5: sem esforço
        self.assertEqual(mc.efforts("chatgpt", "gpt-6-luna")["levels"], ["none"] + L5)
        self.assertNotIn("max", mc.efforts("openai", "gpt-6-luna")["levels"])         # `max` só na Responses API
        self.assertNotIn("none", mc.efforts("chatgpt", "gpt-6.2-astra")["levels"])
        self.assertEqual(mc.efforts("xai-oauth", "grok-4.7")["levels"], ["low", "medium", "high", "xhigh"])
        self.assertEqual(mc.efforts("gemini", "gemini-4-carbon")["levels"], ["low", "medium", "high"])
        self.assertEqual(mc.efforts("gemini", "gemini-4-neon")["levels"], ["low", "medium", "high", "xhigh"])

    def test_new_version_inherits_and_unknown_is_not_invented(self):
        self.assertTrue(mc.efforts("anthropic", "claude-haiku-5-6")["inferred"])
        self.assertEqual(mc.efforts("anthropic", "claude-haiku-5-6")["levels"], L5)
        unk = mc.efforts("custom", "meu-modelo")
        self.assertEqual((unk["known"], unk["levels"]), (False, []))
        self.assertEqual(mc.efforts("fireworks", "accounts/fireworks/models/deepseek-v4p1-flash")["lane"], "")

    def test_anthropic_api_capabilities_beat_the_rule(self):
        ent = {"id": "claude-haiku-5-5", "levels": ["low", "high"], "levels_source": "api"}
        self.assertEqual(mc.efforts("anthropic", "claude-haiku-5-5", ent)["levels"], ["low", "high"])

    def test_check_refuses_levels_the_model_lacks(self):
        with self.assertRaises(util.BrainError):
            mc.check_effort("openai", "gpt-6-luna", "max")
        with self.assertRaises(util.BrainError):
            mc.check_effort("anthropic", "claude-haiku-5-5", "minimal")
        self.assertIn("não constam", mc.check_effort("custom", "meu-modelo", "high"))


class EffortReachesTheServer(unittest.TestCase):
    def test_claude_code_uses_reasoning_effort_per_operation(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "claude-code", efforts={"retain": "low"})
            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_LLM_REASONING_EFFORT"], "high")              # o padrão do Brain
            self.assertEqual(env["HINDSIGHT_API_RETAIN_LLM_REASONING_EFFORT"], "low")
            self.assertNotIn("HINDSIGHT_API_REFLECT_LLM_REASONING_EFFORT", env)             # herda o global
            self.assertEqual(b.inst.cfg["memory"]["llm_effort"], "retain=low")

    def test_anthropic_api_goes_through_the_extra_body_and_keeps_the_owners_keys(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.inst.env_file.write_text('HINDSIGHT_API_LLM_EXTRA_BODY={"temperature":0.2}\n', encoding="utf-8")
            providers.set_slot(b, "llm", "anthropic", key="ak-1", effort="medium", efforts={"reflect": "xhigh"})
            env = config.load_env(b.inst)
            self.assertEqual(json.loads(env["HINDSIGHT_API_LLM_EXTRA_BODY"]),
                             {"temperature": 0.2, "output_config": {"effort": "medium"}})
            self.assertEqual(json.loads(env["HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY"]), {"output_config": {"effort": "xhigh"}})
            self.assertNotIn("HINDSIGHT_API_LLM_REASONING_EFFORT", env)
            # troca para um lane de REASONING_EFFORT: o nível sai do extra body, a temperatura do dono fica
            providers.set_slot(b, "llm", "openai", key="ok-1", effort="low")
            env = config.load_env(b.inst)
            self.assertEqual(json.loads(env["HINDSIGHT_API_LLM_EXTRA_BODY"]), {"temperature": 0.2})
            self.assertNotIn("HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY", env)
            self.assertEqual(env["HINDSIGHT_API_LLM_REASONING_EFFORT"], "low")

    def test_gemini_uses_thinking_level(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "gemini", key="gk-1", model="gemini-4-hydrogen", effort="xhigh")
            env = config.load_env(b.inst)
            self.assertEqual(json.loads(env["HINDSIGHT_API_LLM_EXTRA_BODY"]),
                             {"thinking_config": {"thinking_level": "XHIGH"}})

    def test_invalid_level_and_provider_without_effort_are_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "llm", "anthropic", key="ak-1", effort="minimal")
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "llm", "fireworks", key="fk-1", effort="high")
            self.assertNotIn("HINDSIGHT_API_LLM_PROVIDER", config.load_env(b.inst))

    def test_stack_reads_back_the_effective_levels(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "anthropic", key="ak-1", efforts={"retain": "low"})
            llm = providers.stack(b)["llm"]
            self.assertEqual(llm["effort_lane"], "anthropic")
            self.assertEqual(llm["efforts"]["default"], "high")
            self.assertEqual(llm["efforts"]["retain"], "low")
            self.assertEqual(llm["efforts"]["reflect"], "high")
            self.assertEqual(llm["levels"]["claude-haiku-5-5"]["levels"], L5)


class DefaultsFollowTheNewestModel(unittest.TestCase):
    def test_blank_resolves_to_the_newest_of_the_line_and_typed_is_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            _seed_catalog(b, "anthropic", ["claude-haiku-5-5", "claude-haiku-5-6", "claude-sonnet-5-5"])
            providers.set_slot(b, "llm", "anthropic", key="ak-1")
            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_LLM_MODEL"], "claude-haiku-5-6")
            self.assertEqual(env["HINDSIGHT_API_RETAIN_LLM_MODEL"], "claude-haiku-5-6")
            self.assertEqual(providers.pinned_ops(b), [])
            providers.set_slot(b, "llm", "anthropic", models={"reflect": "claude-sonnet-5-5"})
            self.assertEqual(providers.pinned_ops(b), ["reflect"])
            self.assertEqual(config.load_env(b.inst)["HINDSIGHT_API_REFLECT_LLM_MODEL"], "claude-sonnet-5-5")

    def test_instance_from_before_follows_unless_it_changed_the_default(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {"llm_provider": "anthropic", "llm_models":
                            "retain=claude-haiku-5-5,consolidation=claude-haiku-5-5,reflect=claude-sonnet-5-5,"
                            "default=claude-haiku-5-5"})
            b.inst = config.load(b.inst.root)
            self.assertEqual(providers.pinned_ops(b), ["reflect"])

    def test_daily_follow_moves_recreates_and_records(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            _full(b)
            providers.set_slot(b, "llm", "anthropic", key="ak-1", models={"reflect": "claude-sonnet-5-5"})
            seen = []
            res = providers.follow_latest(
                b, http=_openrouter(["anthropic/claude-haiku-5.5", "anthropic/claude-haiku-5.6",
                                     "anthropic/claude-sonnet-5.5", "anthropic/claude-haiku-5.6:batch"]),
                now=2e9, recreate=lambda brain, say: (seen.append(1) or (True, "")))
            self.assertTrue(res["applied"])
            self.assertEqual(seen, [1])
            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_RETAIN_LLM_MODEL"], "claude-haiku-5-6")
            self.assertEqual(env["HINDSIGHT_API_REFLECT_LLM_MODEL"], "claude-sonnet-5-5")     # fixo: não move
            self.assertEqual(env["HINDSIGHT_API_LLM_API_KEY"], "ak-1")
            self.assertTrue(mc.moves(b)[0]["ok"])
            # no mesmo dia, nada (uma vez por dia)
            again = providers.follow_latest(b, http=_openrouter([]), now=2e9 + 60)
            self.assertIn("24 h", again["reason"])

    def test_failed_health_check_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            _full(b)
            providers.set_slot(b, "llm", "anthropic", key="ak-1")
            before = config.load_env(b.inst)
            calls = []
            res = providers.follow_latest(
                b, http=_openrouter(["anthropic/claude-haiku-5.6"]), now=2e9,
                recreate=lambda brain, say: (calls.append(1), (len(calls) > 1, "health/llm falhou: 404"))[1])
            self.assertFalse(res["applied"])
            self.assertEqual(len(calls), 2)                                  # tentou e recriou de volta
            after = config.load_env(b.inst)
            self.assertEqual(after["HINDSIGHT_API_LLM_MODEL"], before["HINDSIGHT_API_LLM_MODEL"])
            self.assertEqual(b.inst.cfg["memory"]["llm_models"], config.load(b.inst.root).cfg["memory"]["llm_models"])
            self.assertIn("claude-haiku-5-5", config.load(b.inst.root).cfg["memory"]["llm_models"])
            self.assertFalse(mc.moves(b)[0]["ok"])

    def test_follow_skips_outside_full_and_for_providers_without_a_live_list(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "anthropic", key="ak-1")
            self.assertIn("full", providers.follow_latest(b, http=_openrouter([]), now=2e9)["reason"])
            _full(b)
            providers.set_slot(b, "llm", "fireworks", key="fk-1")
            self.assertIn("laboratório", providers.follow_latest(b, http=_openrouter([]), now=2e9)["reason"])

    def test_vendor_api_with_the_key_then_openrouter_without(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "anthropic", key="ak-1")
            calls = []

            def http(url, headers):
                calls.append((url.split("?")[0], sorted(headers)))
                return {"data": [{"id": "claude-haiku-5-6", "capabilities": {"effort": {
                    "supported": True, "low": {"supported": True}, "medium": {"supported": True},
                    "high": {"supported": True}, "max": {"supported": False}}}}], "has_more": False}
            cat = mc.catalog(b, "anthropic", refresh=True, http=http, now=2e9)
            self.assertEqual(cat["source"], "anthropic")
            self.assertEqual(calls[0][0], "https://api.anthropic.com/v1/models")
            self.assertIn("x-api-key", calls[0][1])
            self.assertEqual(mc.efforts("anthropic", "claude-haiku-5-6", mc.entry(cat, "claude-haiku-5-6"))["levels"],
                             ["low", "medium", "high"])
            # provedor sem chave no .env (xAI por assinatura): catálogo público
            cat2 = mc.catalog(b, "xai-oauth", refresh=True, http=_openrouter(["x-ai/grok-4.7", "x-ai/grok-5"]), now=2e9)
            self.assertEqual((cat2["source"], mc.newest("grok-4.7", cat2["models"])), ("openrouter", "grok-5"))

    def test_network_failure_keeps_the_cache(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            _seed_catalog(b, "openai", ["gpt-6-luna"], at=1)

            def down(url, headers):
                raise urllib.error.URLError("offline")
            cat = mc.catalog(b, "openai", refresh=True, http=down, now=2e9)
            self.assertEqual([m["id"] for m in cat["models"]], ["gpt-6-luna"])
            self.assertTrue(cat["error"])


class CloudDecisionKeys(unittest.TestCase):
    W = providers.DECISION_WIRE_KEY

    def test_each_provider_keeps_its_key_and_the_server_reads_the_active_one(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "decision", "hindsight", key="hs-1")
            providers.set_slot(b, "decision", "openai", key="op-1", recall="on", candidates=40)
            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_DECISION_MODEL_PROVIDER"], "openai")
            self.assertEqual(env["HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER"], "openai")
            self.assertEqual(env["HINDSIGHT_API_DECISION_MODEL_MODEL"], "gpt-6-luna")
            self.assertEqual((env[self.W], env["BRAIN_DECISION_OPENAI_API_KEY"]), ("op-1", "op-1"))
            self.assertEqual(env["HINDSIGHT_API_DECISION_CLOUD_API_KEY"], "hs-1")          # a do Hindsight no cofre
            self.assertTrue(b.inst.cfg["memory"]["cloud_decision"])
            providers.set_slot(b, "decision", "hindsight")                                # volta sem colar de novo
            env = config.load_env(b.inst)
            self.assertEqual(env[self.W], "hs-1")
            self.assertEqual(env["HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER"], "none")
            providers.set_slot(b, "decision", "typesafe", key="ts-1")
            self.assertEqual(config.load_env(b.inst)["HINDSIGHT_API_DECISION_MODEL_PROVIDER"], "typesafe")
            providers.set_slot(b, "decision", "openai")                                   # a própria, guardada
            self.assertEqual(config.load_env(b.inst)[self.W], "op-1")

    def test_cloud_decider_without_any_key_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for p in ("typesafe", "openai", "hindsight"):
                with self.assertRaises(util.BrainError, msg=p):
                    providers.set_slot(b, "decision", p)
            self.assertEqual(b.inst.cfg["memory"]["decision_provider"], "off")

    def test_openai_decider_reuses_the_openai_llm_key(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "openai", key="sk-llm-1")
            providers.set_slot(b, "decision", "openai")
            self.assertEqual(config.load_env(b.inst)[self.W], "sk-llm-1")
            self.assertTrue(providers.stack(b)["decision"]["key_present"])

    def test_recall_needs_a_cloud_decider(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                providers.slot_env("decision", "local", recall="on", candidates=10)
            env = providers.slot_env("decision", "typesafe", key="ts-1", recall="on", candidates=10)
            self.assertEqual(env["HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER"], "typesafe")
            del b


class PanelRoute(unittest.TestCase):
    def test_validate_accepts_effort_and_cloud_recall(self):
        v = setup.validate_memory_setup({
            "mode": "full", "consent": True,
            "llm": {"provider": "anthropic", "key": "ak-1", "effort": "medium", "efforts": {"retain": "low"},
                    "reconfigure": True},
            "decision": {"provider": "openai", "key": "op-1", "recall": "on", "candidates": 30}})
        self.assertEqual((v["slots"]["llm"]["effort"], v["slots"]["llm"]["efforts"]), ("medium", {"retain": "low"}))
        self.assertTrue(v["dec_recall"])
        with self.assertRaises(util.BrainError):
            setup.validate_memory_setup({"mode": "full", "consent": True, "llm": {"provider": "anthropic",
                                         "effort": "turbo"}})
        with self.assertRaises(util.BrainError):
            setup.validate_memory_setup({"mode": "full", "consent": True, "llm": {"provider": "anthropic"},
                                         "decision": {"provider": "local", "recall": "on", "candidates": 5}})

    def test_the_providers_step_writes_effort_from_the_panel(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = setup.ScriptedMemoriaUI(setup._SayOnly(lambda *_a: None), {"LLM": "claude-code"}, {}, "", consent=True,
                                         slot_models={"llm": {"model": "", "effort": "low",
                                                              "efforts": {"reflect": "xhigh"}}})
            setup._providers_step(b, ui, ["llm"])
            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_LLM_REASONING_EFFORT"], "low")
            self.assertEqual(env["HINDSIGHT_API_REFLECT_LLM_REASONING_EFFORT"], "xhigh")
            self.assertEqual(providers.pinned_ops(b), [])                     # recomendados = seguem o mais novo

    def test_models_action_refreshes_and_returns_levels(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with mock.patch.object(mc, "_http_json", _openrouter(["google/gemini-4-neon", "google/gemini-3.5-flash-lite"])):
                r = onboard.run_action(b, "memory_models", {"provider": "gemini", "refresh": True})
            self.assertEqual(r["lane"], "gemini")
            self.assertEqual(r["latest"]["default"], "gemini-3.5-flash-lite")      # semente 3.1-flash-lite → 3.5
            self.assertEqual(r["models"][0]["id"], "gemini-4-neon")              # a sugestão abre no mais novo
            neon = next(x for x in r["models"] if x["id"] == "gemini-4-neon")
            self.assertEqual(neon["levels"], ["low", "medium", "high", "xhigh"])
            with self.assertRaises(util.BrainError):
                onboard.run_action(b, "memory_models", {"provider": "nada"})


OLD_IMAGE = "ghcr.io/vectorize-io/hindsight@sha256:" + "c7d4" + "0" * 60


class ServerFollowsTheUpdate(unittest.TestCase):
    """`brain update` traz o código; o servidor de memória do dono acompanha: .env no formato novo e a imagem pinada,
    conferidos — e, se a imagem nova não subir, volta à anterior. Roda no ensure (watchdog/abertura), com o código
    novo, qualquer que seja o código que fez o pull."""

    def setUp(self):
        env = mock.patch.dict("os.environ", {})
        env.start()
        self.addCleanup(env.stop)
        import os
        os.environ.pop("BRAIN_SERVICES_NO_KICK", None)          # a suíte local costuma rodar com ele ligado

    VOL = "segundo-cerebro_hindsight-data"

    def _run(self, image: str | None, compose_code: int = 0, fail: tuple = ()):
        """Docker de mentira. `fail`: passos que devolvem erro — "pull", "backup" (cópia vol → bak), "restore"."""
        calls = []

        def run(argv, timeout=60):
            calls.append(list(argv))
            if "inspect" in argv:
                if not image:
                    return 1, "Error: No such object: hindsight"
                return (0, self.VOL + "\n") if any(".pg0" in a for a in argv) else (0, image + "\n")
            if "pull" in argv:
                return (1, "net down") if "pull" in fail else (0, "pulled")
            if "run" in argv and "--rm" in argv:
                restore = any(a.endswith("-pre-upgrade:/from:ro") for a in argv)
                step = "restore" if restore else "backup"
                return (1, "cp: no space") if step in fail else (0, "")
            if "compose" in argv and argv[0] != "env":
                return compose_code, "ok"
            return 0, "ok"
        return run, calls

    @staticmethod
    def _step(c: list) -> str:
        if c[0] == "env":
            return "compose-old"
        for k in ("inspect", "pull", "stop", "start", "compose"):
            if k in c:
                return k
        if "volume" in c:
            return "volume-" + c[c.index("volume") + 1]
        if "run" in c:
            return "restore" if any(a.endswith("-pre-upgrade:/from:ro") for a in c) else "backup"
        return c[0]

    def _inst(self, td, **mem):
        b = _brain(Path(td))
        config.set_keys(b.inst, "memory", {"engine": "hindsight", **mem})
        return config.load(b.inst.root)

    def test_the_pin_is_the_1_3_0_slim_digest(self):
        from brainlib import services
        self.assertEqual(services.pinned_image(),
                         "ghcr.io/vectorize-io/hindsight@sha256:d311bdee313f4be08d7f33ab7070ace35ebdec27985a6678acfc6ad186515b44")

    def test_old_image_is_recreated_with_the_pinned_one(self):
        from brainlib import services
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td)
            run, calls = self._run(OLD_IMAGE)
            res = services.sync_server(inst, run=run, probes={"hindsight": lambda: True, "lmstudio": lambda: True},
                                       sleep=lambda s: None)
            self.assertEqual(res["state"], "ready")
            self.assertIn(f"{self.VOL}-pre-upgrade", res["detail"])
            steps = [self._step(c) for c in calls if self._step(c) != "inspect"]
            # baixa antes de parar; copia o banco antes de subir a imagem nova; nada de volta
            self.assertEqual(steps, ["pull", "stop", "volume-rm", "volume-create", "backup", "compose"])
            backup = next(c for c in calls if self._step(c) == "backup")
            self.assertIn("--user", backup)                                      # sem root a cópia sai vazia
            self.assertIn(f"{self.VOL}:/from:ro", backup)
            self.assertIn(f"{self.VOL}-pre-upgrade:/to", backup)
            self.assertEqual(backup[backup.index("--entrypoint") + 2], OLD_IMAGE)
            self.assertFalse((Path(inst.logs) / "server-sync.lock").exists())

    def test_failed_download_or_backup_changes_nothing(self):
        from brainlib import services
        probes = {"hindsight": lambda: True, "lmstudio": lambda: True}
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td)
            run, calls = self._run(OLD_IMAGE, fail=("pull",))
            res = services.sync_server(inst, run=run, probes=probes, sleep=lambda s: None)
            self.assertEqual(res["state"], "failed")
            self.assertIn("nada foi mudado", res["detail"])
            self.assertEqual([self._step(c) for c in calls if self._step(c) != "inspect"], ["pull"])   # nem parou
            run, calls = self._run(OLD_IMAGE, fail=("backup",))
            res = services.sync_server(inst, run=run, probes=probes, sleep=lambda s: None)
            self.assertIn("nada foi mudado", res["detail"])
            steps = [self._step(c) for c in calls if self._step(c) != "inspect"]
            self.assertEqual(steps[-2:], ["backup", "start"])                     # religa o de antes
            self.assertNotIn("compose", steps)

    def test_no_data_volume_no_upgrade(self):
        from brainlib import services
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td)
            run, calls = self._run(OLD_IMAGE)
            self.VOL = ""
            res = services.sync_server(inst, run=run, probes={"hindsight": lambda: True, "lmstudio": lambda: True},
                                       sleep=lambda s: None)
            self.assertIn("volume de dados", res["detail"])
            self.assertFalse(any(self._step(c) in ("pull", "stop", "compose") for c in calls))

    def test_nothing_to_do_when_image_and_env_are_current(self):
        from brainlib import services
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td)
            run, calls = self._run(services.pinned_image())
            self.assertIsNone(services.sync_server(inst, run=run, probes={"hindsight": lambda: True}))
            self.assertFalse(any("compose" in c for c in calls))
            run, calls = self._run(None)                                   # sem contêiner: o ensure/setup cria
            self.assertIsNone(services.sync_server(inst, run=run, probes={"hindsight": lambda: True}))

    def test_old_env_is_migrated_and_the_server_recreated(self):
        from brainlib import services
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td, extract=True, cloud_llm=True, llm_provider="anthropic",
                              llm_models="retain=claude-haiku-5-5,reflect=claude-sonnet-5-5,default=claude-haiku-5-5")
            inst.env_file.write_text("HINDSIGHT_API_LLM_PROVIDER=anthropic\nHINDSIGHT_API_LLM_API_KEY=ak-1\n"
                                     "HINDSIGHT_API_LLM_REASONING_EFFORT=high\nHINDSIGHT_API_LLM_MODEL=claude-haiku-5-5\n",
                                     encoding="utf-8")
            run, calls = self._run(services.pinned_image())
            verified = []
            res = services.sync_server(inst, run=run, probes={"hindsight": lambda: True, "lmstudio": lambda: True},
                                       sleep=lambda s: None, verify_llm=lambda i: verified.append(1))
            self.assertEqual(res["state"], "ready")
            env = config.load_env(inst)
            self.assertNotIn("HINDSIGHT_API_LLM_REASONING_EFFORT", env)    # o lane Anthropic ignorava
            self.assertEqual(json.loads(env["HINDSIGHT_API_LLM_EXTRA_BODY"]), {"output_config": {"effort": "high"}})
            self.assertEqual(env["HINDSIGHT_API_REFLECT_LLM_MODEL"], "claude-sonnet-5-5")   # escolha do dono fica
            self.assertEqual(env["HINDSIGHT_API_LLM_API_KEY"], "ak-1")
            mem = config.load(inst.root).cfg["memory"]
            self.assertEqual((mem["llm_follow_v"], mem["llm_pinned"]), (1, "reflect"))
            self.assertEqual(verified, [1])                                 # full: o LLM conferido
            self.assertEqual(sum("compose" in c for c in calls), 1)
            # de novo: nada (migração feita, imagem certa)
            run2, calls2 = self._run(services.pinned_image())
            self.assertIsNone(services.sync_server(config.load(inst.root), run=run2, probes={"hindsight": lambda: True}))

    def test_new_image_that_does_not_come_up_rolls_back(self):
        from brainlib import services
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td, extract=True, cloud_llm=True)
            run, calls = self._run(OLD_IMAGE)

            def fail(_inst):
                raise util.BrainError("health/llm 500")
            res = services.sync_server(inst, run=run, probes={"hindsight": lambda: True, "lmstudio": lambda: True},
                                       sleep=lambda s: None, verify_llm=fail)
            self.assertEqual(res["state"], "failed")
            self.assertIn("restaurou o banco de antes", res["detail"])
            steps = [self._step(c) for c in calls if self._step(c) != "inspect"]
            # a imagem nova já migrou o banco: a volta restaura a cópia ANTES de subir a imagem de antes
            self.assertEqual(steps[-4:], ["compose", "stop", "restore", "compose-old"])
            restore = next(c for c in calls if self._step(c) == "restore")
            self.assertIn(f"{self.VOL}:/to", restore)
            self.assertIn("find /to -mindepth 1 -delete", restore[-1])
            back = [c for c in calls if c[0] == "env"]
            self.assertEqual(back[0][1], f"BRAIN_HINDSIGHT_IMAGE={OLD_IMAGE}")

    def test_failed_restore_stops_and_points_to_the_backup(self):
        from brainlib import services
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td)
            run, calls = self._run(OLD_IMAGE, compose_code=1, fail=("restore",))
            res = services.sync_server(inst, run=run, probes={"hindsight": lambda: True, "lmstudio": lambda: True},
                                       sleep=lambda s: None)
            self.assertIn(f"{self.VOL}-pre-upgrade", res["detail"])
            self.assertIn("Não rode `memory rebuild`", res["detail"])
            self.assertFalse(any(c[0] == "env" for c in calls))      # não sobe a versão de antes num banco pela metade

    def test_a_sync_already_running_is_not_doubled(self):
        from brainlib import services
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td)
            lock = Path(inst.logs) / "server-sync.lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text("1", encoding="utf-8")
            run, calls = self._run(OLD_IMAGE)
            self.assertIsNone(services.sync_server(inst, run=run, probes={"hindsight": lambda: True}))
            self.assertEqual(calls, [])

    def test_ensure_runs_the_sync_after_the_dependencies(self):
        from brainlib import services
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td, embeddings_provider="fireworks")
            run, calls = self._run(OLD_IMAGE)
            probes = {"hindsight": lambda: True, "docker": lambda: True, "lmstudio": lambda: True}
            with mock.patch.object(services, "PAUSE", Path(td) / "nope"):
                row = services.ensure(inst, reason="watchdog", run=run, probes=probes, sleep=lambda s: None)
            self.assertEqual(row["deps"]["hindsight"]["detail"][:30], "servidor de memória atualizado")
            self.assertEqual(sum("compose" in c for c in calls), 1)


class ComposeFilesAreValid(unittest.TestCase):
    """Volume nomeado montado num serviço precisa estar declarado no topo: o Compose v5 recusa o arquivo inteiro
    ("refers to undefined volume") — e aí nenhum recreate do Brain sobe (Aplicar, troca de provedor, update)."""

    def test_every_named_volume_is_declared(self):
        import re
        for name in ("compose.yaml", "compose.full.yaml"):
            txt = (ROOT / "services" / name).read_text(encoding="utf-8")
            used = set(re.findall(r"^\s+-\s+([A-Za-z][\w-]*):/", txt, re.M))
            top = re.search(r"^volumes:\n((?:[ \t]+.*\n?|\n)*)", txt, re.M)
            declared = set(re.findall(r"^  ([A-Za-z][\w-]*):", top.group(1), re.M)) if top else set()
            self.assertEqual(used - declared, set(), name)


if __name__ == "__main__":
    unittest.main()
