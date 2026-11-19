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
KEY_IDS = ("anthropic", "openai", "fireworks", "zai", "gemini", "custom")


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
            self.assertEqual(mem.get("llm_models", ""), "")

            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_LLM_PROVIDER"], "claude-code")
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

    def test_full_subscription_without_key_is_ok(self):
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
            self.assertEqual(llm_ck["level"], "ok")
            self.assertIn("assinatura", llm_ck["detail"])

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
            self.assertEqual(len(slot_cks), 3)
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


if __name__ == "__main__":
    unittest.main()
