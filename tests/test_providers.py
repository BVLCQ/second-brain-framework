"""Provedores da memória (plano memory-providers.md): escolha grava .env + [memory], chave nunca vaza."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BRAIN_NOW", "2026-11-07T10:00:00-03:00")

from brainlib import config, providers, util
from brainlib.core import Brain


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n', encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class ProvidersTests(unittest.TestCase):
    def test_set_fireworks_stack(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp)
            providers.set_slot(b, "embeddings", "fireworks", key="fw-key-1")
            providers.set_slot(b, "reranker", "fireworks", key="fw-key-1")
            providers.set_slot(b, "llm", "anthropic", key="sk-1")
            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL"], "fireworks/qwen3-embedding-8b")
            self.assertEqual(env["HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS"], "1536")
            self.assertEqual(env["HINDSIGHT_API_RERANKER_PROVIDER"], "litellm-sdk")
            self.assertEqual(env["HINDSIGHT_API_RERANKER_LITELLM_SDK_MODEL"],
                             "fireworks_ai/fireworks/qwen3-reranker-8b")
            self.assertEqual(env["HINDSIGHT_API_RERANKER_MAX_CANDIDATES"], "50")
            self.assertEqual(env["HINDSIGHT_API_LLM_PROVIDER"], "anthropic")
            # recomendados por operação (cenário B)
            self.assertEqual(env["HINDSIGHT_API_RETAIN_LLM_MODEL"], "claude-haiku-5-5")
            self.assertEqual(env["HINDSIGHT_API_MENTAL_MODEL_REFRESH_LLM_MODEL"], "claude-sonnet-5-5")
            # escolha no [memory], chave NUNCA
            mem = b.inst.cfg["memory"]
            self.assertEqual(mem["embeddings_provider"], "fireworks")
            self.assertEqual(mem["reranker_provider"], "fireworks")
            self.assertEqual(mem["llm_provider"], "anthropic")
            self.assertTrue(mem["cloud_embeddings"] and mem["cloud_reranker"])
            toml = (tmp / "config" / "brain.toml").read_text(encoding="utf-8")
            self.assertNotIn("fw-key-1", toml)
            self.assertNotIn("sk-1", toml)
            # stack() lê de volta com presença de chave
            st = providers.stack(b)
            self.assertTrue(all(st[s]["key_present"] for s in providers.SLOTS))
            self.assertTrue(all(st[s]["cloud"] for s in providers.SLOTS))

    def test_off_and_local_are_clean(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            r1 = providers.set_slot(b, "reranker", "off")
            r2 = providers.set_slot(b, "embeddings", "local")
            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_RERANKER_PROVIDER"], "rrf")
            self.assertEqual(env["HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL"], "text-embedding-bge-m3")
            self.assertIn("host.docker.internal", env["HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL"])
            self.assertNotIn("HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS", env)
            self.assertFalse(r1["cloud"] and r2["cloud"])
            st = providers.stack(b)
            self.assertEqual(st["reranker"]["provider"], "off")
            self.assertFalse(st["embeddings"]["cloud"])

    def test_rebuild_hint_only_when_switching_with_state(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp)
            (tmp / ".memory-state.json").write_text("{}", encoding="utf-8")
            # mesmo provider+model → sem hint
            self.assertFalse(providers.set_slot(b, "embeddings", "local")["rebuild_needed"])
            # troca de provider com banco já sincronizado → hint
            self.assertTrue(providers.set_slot(b, "embeddings", "fireworks", key="k")["rebuild_needed"])

    def test_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "nope", "local")
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "llm", "nope")
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "llm", "openai")          # sem modelo
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "embeddings", "custom")   # sem model/base_url
            with self.assertRaises(util.BrainError):
                providers._parse_models("retain")               # sem '='

    def test_custom_llm_models_spec(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "fireworks",
                               models={"retain": "m-barato", "consolidation": "m-barato",
                                       "mental_models": "m-grande", "reflect": "m-grande",
                                       "default": "m-barato"})
            env = config.load_env(b.inst)
            self.assertEqual(env["HINDSIGHT_API_LLM_PROVIDER"], "openai")     # wire openai
            self.assertEqual(env["HINDSIGHT_API_LLM_BASE_URL"], "https://api.fireworks.ai/inference/v1")
            self.assertEqual(env["HINDSIGHT_API_RETAIN_LLM_MODEL"], "m-barato")
            self.assertEqual(env["HINDSIGHT_API_REFLECT_LLM_MODEL"], "m-grande")

    def test_cli_show_json_roundtrip(self):
        import argparse, contextlib, io, json
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "embeddings", "fireworks", key="fw-secret-zzz9")
            args = argparse.Namespace(pcmd="", json=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                providers.cli(args, b)
            st = json.loads(buf.getvalue())
            self.assertEqual(st["embeddings"]["provider"], "fireworks")
            self.assertNotIn("fw-secret-zzz9", buf.getvalue())   # chave nunca no output


if __name__ == "__main__":
    unittest.main()
