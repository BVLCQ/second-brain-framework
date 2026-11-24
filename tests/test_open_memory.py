"""Testes para #159 (esforço high), #158 (assinaturas sem login guiado no Docker) e #163 (decisor no recall e local)."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brainlib import cli, config, doctor, forms, onboard, providers, setup, util
from brainlib.core import Brain


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    for zone in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH", "reports"):
        (tmp / "vault" / zone).mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


def _checks(b: Brain, **kwargs) -> list[dict]:
    with mock.patch.object(setup, "brain_command_status", return_value="/usr/local/bin/brain"), \
            mock.patch.object(setup, "FRAMEWORK", Path("/nonexistent-fw")):
        return doctor.checks(b, **kwargs)


class _LogUI:
    interactive = False

    def __init__(self):
        self.log: list[str] = []

    def say(self, msg: str) -> None:
        self.log.append(str(msg))


class EffortDefaultHighTests(unittest.TestCase):
    """#159 — HINDSIGHT_API_LLM_REASONING_EFFORT padrão high; max existente preservado com warn."""

    def test_effort_high_emitted_for_blank_setup_and_unset_for_other_providers(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for pid in ("claude-code", "anthropic"):
                providers.set_slot(b, "llm", pid, key="sk-ant-1" if pid == "anthropic" else None)
                env = config.load_env(b.inst)
                self.assertEqual(env.get("HINDSIGHT_API_LLM_REASONING_EFFORT"), "high")

        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for pid in ("openai", "fireworks", "xai-oauth"):
                providers.set_slot(b, "llm", pid, key="k-1" if pid != "xai-oauth" else None)
                env = config.load_env(b.inst)
                self.assertNotIn("HINDSIGHT_API_LLM_REASONING_EFFORT", env)

    def test_existing_max_not_rewritten_and_doctor_warns(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.inst.env_file.write_text(
                "HINDSIGHT_API_LLM_REASONING_EFFORT=max\n"
                "HINDSIGHT_API_LLM_API_KEY=sk-ant-1\n"
                "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=fw-1\n",
                encoding="utf-8",
            )
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": True, "cloud_llm": True,
                "raw_awaiting_dump": "hold", "embeddings_provider": "fireworks",
            })
            b.inst = config.load(b.inst.root)

            providers.set_slot(b, "llm", "anthropic", key="sk-ant-1")
            env_after = config.load_env(b.inst)
            self.assertEqual(env_after.get("HINDSIGHT_API_LLM_REASONING_EFFORT"), "max")

            raw_before_doctor = b.inst.env_file.read_text(encoding="utf-8")
            cks = _checks(b)
            self.assertEqual(b.inst.env_file.read_text(encoding="utf-8"), raw_before_doctor)

            llm_ck = next(c for c in cks if c["title"] == "memória · LLM")
            self.assertEqual(llm_ck["level"], "warn")
            self.assertIn("diferente do padrão", llm_ck["detail"])
            self.assertIn("high", llm_ck["detail"])


class SubscriptionDockerAuthTests(unittest.TestCase):
    """#158 — provedores de assinatura sem login guiado no Docker."""

    def test_registry_docker_auth_and_derived_label_suffixes(self):
        llm = providers.PROVIDERS["llm"]
        self.assertEqual(llm["claude-code"]["docker_auth"], "guided")
        self.assertEqual(llm["xai-oauth"]["docker_auth"], "guided")
        self.assertEqual(llm["chatgpt"]["docker_auth"], "manual")
        self.assertEqual(llm["nous"]["docker_auth"], "manual")
        self.assertEqual(llm["github-copilot"]["docker_auth"], "manual")
        self.assertEqual(llm["cursor"]["docker_auth"], "unavailable")

        for pid in ("chatgpt", "nous", "github-copilot"):
            self.assertIn("login manual no servidor", llm[pid]["label"])
            self.assertTrue(llm[pid].get("auth_command", "").strip())
        self.assertIn("modelo padrão fraco para memória", llm["github-copilot"]["label"])
        self.assertIn("indisponível no Docker", llm["cursor"]["label"])
        self.assertIn("claude-code", llm["github-copilot"]["setup_hint"])

    def test_cursor_absent_from_wizard_and_panel_lists_and_manual_last(self):
        menu_ids = [pid for pid, _ in providers.menu_providers("llm")]
        self.assertNotIn("cursor", menu_ids)
        form_ids = [pid for pid, _ in forms.memory_provider_options("llm", "full")]
        self.assertNotIn("cursor", form_ids)
        static_ids = [pid for pid, _ in forms.static()["providers"]["llm"]]
        self.assertNotIn("cursor", static_ids)

        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ob_ids = [p["key"] for p in onboard.state(b)["memory"]["providers"]["llm"]]
            self.assertNotIn("cursor", ob_ids)

        # Guiados e chave de API vêm antes dos manuais
        llm = providers.PROVIDERS["llm"]
        flags = [llm[pid].get("docker_auth") == "manual" for pid in menu_ids]
        self.assertEqual(flags, sorted(flags))
        self.assertTrue(any(flags))

        # Fallbacks do wizard em extra.js e onboarding.html também não listam cursor no slot llm
        root = Path(__file__).resolve().parent.parent
        for rel in ("brainlib/assets/src/extra.js", "brainlib/assets/onboarding.html"):
            txt = (root / rel).read_text(encoding="utf-8")
            self.assertNotIn('{key: "cursor"', txt, f"{rel} ainda expõe cursor no fallback do wizard")
            self.assertIn("login manual no servidor", txt)
            self.assertIn("modelo padrão fraco para memória", txt)

    def test_manual_provider_in_wizard_prints_setup_hint_and_auth_command(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            log_ui = _LogUI()
            ui = setup.ScriptedMemoriaUI(log_ui, {"LLM": "chatgpt"}, {}, "", consent=True)
            setup._providers_step(b, ui, ["llm"])
            joined = "\n".join(log_ui.log)
            self.assertIn(providers.PROVIDERS["llm"]["chatgpt"]["setup_hint"], joined)
            self.assertIn(providers.PROVIDERS["llm"]["chatgpt"]["auth_command"], joined)

    def test_doctor_warns_for_cursor_and_manual_subscriptions_without_false_error_on_guided(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {
                "engine": "hindsight", "extract": True, "cloud_llm": True,
                "raw_awaiting_dump": "hold", "embeddings_provider": "fireworks",
                "llm_provider": "cursor",
            })
            b.inst.env_file.write_text("HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=fw-1\n", encoding="utf-8")
            b.inst = config.load(b.inst.root)
            llm_ck = next(c for c in _checks(b) if c["title"] == "memória · LLM")
            self.assertEqual(llm_ck["level"], "warn")
            self.assertIn("indisponível no Docker", llm_ck["detail"])

            for manual_pid in ("chatgpt", "nous", "github-copilot"):
                config.set_keys(b.inst, "memory", {"llm_provider": manual_pid})
                b.inst = config.load(b.inst.root)
                llm_ck = next(c for c in _checks(b) if c["title"] == "memória · LLM")
                self.assertEqual(llm_ck["level"], "warn")
                self.assertIn("login no servidor não verificado", llm_ck["detail"])

            # Com probe injetado confirmando login no servidor, fica ok
            llm_ck_ok = next(c for c in _checks(b, auth_probe=lambda _p: True) if c["title"] == "memória · LLM")
            self.assertEqual(llm_ck_ok["level"], "ok")

            # Provedor guiado já autenticado continua ok (sem falso erro)
            providers.reset_auth_cache()
            config.set_keys(b.inst, "memory", {"llm_provider": "xai-oauth"})
            b.inst = config.load(b.inst.root)
            llm_ck_xai = next(c for c in _checks(b, auth_probe=lambda *a, **k: True) if c["title"] == "memória · LLM")
            self.assertEqual(llm_ck_xai["level"], "ok")
            providers.reset_auth_cache()


class DecisionRecallAndLocalTests(unittest.TestCase):
    """#163 — decisor no recall e decisor local (/v1/systemone)."""

    def test_recall_env_hindsight_and_explicit_none_and_requires_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            # Sem --candidates, ligar recall é recusado
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "decision", "hindsight", key="hsk-1", recall="on")
            with self.assertRaises(util.BrainError):
                providers.slot_env("decision", "hindsight", key="hsk-1", recall="on", candidates=0)

            # Com --candidates explícito, grava hindsight e decision_recall=True
            providers.set_slot(b, "decision", "hindsight", key="hsk-1", recall="on", candidates=25)
            env = config.load_env(b.inst)
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_PROVIDER"), "hindsight")
            self.assertEqual(env.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER"), "hindsight")
            self.assertEqual(env.get("HINDSIGHT_API_RERANKER_MAX_CANDIDATES"), "25")
            self.assertTrue(mem.get("decision_recall"))
            self.assertEqual(mem.get("decision_max_candidates"), 25)
            self.assertTrue(mem.get("cloud_decision"))

            # Desligar recall grava none explícito e limpa MAX_CANDIDATES do recall
            providers.set_slot(b, "decision", "hindsight", recall="off")
            env_off = config.load_env(b.inst)
            mem_off = config.load(b.inst.root).cfg["memory"]
            self.assertEqual(env_off.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER"), "none")
            self.assertNotIn("HINDSIGHT_API_RECALL_DECISION_MODEL_MAX_CANDIDATES", env_off)
            self.assertNotIn("HINDSIGHT_API_RERANKER_MAX_CANDIDATES", env_off)
            self.assertFalse(mem_off.get("decision_recall"))

    def test_recall_on_preserves_existing_reranker_env(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "reranker", "cohere", key="coh-1")
            env_before = config.load_env(b.inst)
            self.assertEqual(env_before.get("HINDSIGHT_API_RERANKER_PROVIDER"), "cohere")

            with mock.patch.object(setup, "docker_available", return_value=True), \
                    mock.patch.object(setup, "hindsight_health", return_value={"status": "ok"}), \
                    mock.patch.object(setup, "compose_up", return_value=True), \
                    mock.patch.object(setup, "wait_hindsight", return_value=True), \
                    mock.patch("brainlib.memory.setup", return_value=["brain"]), \
                    mock.patch("brainlib.memory.client"):
                setup.configure_memory(b, {
                    "mode": "full",
                    "consent": True,
                    "llm": {"provider": "claude-code"},
                    "embeddings": {"provider": "fireworks", "key": "fw-1"},
                    "reranker": {"provider": "off"},
                    "decision": {"provider": "hindsight", "key": "hsk-1", "recall": "on", "candidates": 30},
                }, say=lambda _m: None)

            env_after = config.load_env(b.inst)
            # Reranker existente no .env é preservado, não apagado nem sobrescrito por rrf
            self.assertEqual(env_after.get("HINDSIGHT_API_RERANKER_PROVIDER"), "cohere")
            self.assertEqual(env_after.get("HINDSIGHT_API_RERANKER_COHERE_API_KEY"), "coh-1")
            self.assertEqual(env_after.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER"), "hindsight")
            self.assertTrue(providers.stack(b)["reranker"]["inert"])

    def test_local_emits_max_concurrent_1_and_base_url_and_switching_off_removes_base_url(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            res = providers.set_slot(
                b, "decision", "local",
                base_url="http://host.docker.internal:8090",
                key="local-secret-1",
            )
            self.assertFalse(res["cloud"])
            env = config.load_env(b.inst)
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_PROVIDER"), "hindsight")
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_MODEL"), "hs-decide-1-flash")
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_BASE_URL"), "http://host.docker.internal:8090")
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_MAX_CONCURRENT"), "1")
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_API_KEY"), "local-secret-1")
            self.assertEqual(env.get("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER"), "none")
            self.assertFalse(mem.get("cloud_decision"))

            # Trocar de local para hindsight ou off remove HINDSIGHT_API_DECISION_MODEL_BASE_URL do .env
            providers.set_slot(b, "decision", "hindsight", key="hsk-cloud-1")
            env_cloud = config.load_env(b.inst)
            mem_cloud = config.load(b.inst.root).cfg["memory"]
            self.assertNotIn("HINDSIGHT_API_DECISION_MODEL_BASE_URL", env_cloud)
            self.assertNotIn("HINDSIGHT_API_DECISION_MODEL_MAX_CONCURRENT", env_cloud)
            self.assertTrue(mem_cloud.get("cloud_decision"))

            providers.set_slot(b, "decision", "local", key="local-secret-1")
            self.assertIn("HINDSIGHT_API_DECISION_MODEL_BASE_URL", config.load_env(b.inst))
            providers.set_slot(b, "decision", "off")
            self.assertNotIn("HINDSIGHT_API_DECISION_MODEL_BASE_URL", config.load_env(b.inst))

    def test_local_recall_flag_refused_and_local_llm_still_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                providers.slot_env("decision", "local", key="k-1", recall="on", candidates=20)
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "decision", "local", key="k-1", recall="on", candidates=20)
            with self.assertRaises(util.BrainError):
                setup.validate_memory_setup({
                    "mode": "full", "consent": True,
                    "llm": {"provider": "claude-code"},
                    "embeddings": {"provider": "fireworks", "key": "fw-1"},
                    "decision": {"provider": "local", "key": "k-1", "recall": "on", "candidates": 20},
                })
            # Embed continua sem decisor
            with self.assertRaises(util.BrainError):
                setup.validate_memory_setup({
                    "mode": "embed",
                    "embeddings": {"provider": "local"},
                    "decision": {"provider": "local", "key": "k-1"},
                })
            # Slot LLM continua bloqueando modelo local
            with self.assertRaises(util.BrainError):
                providers.set_slot(b, "llm", "local")

    def test_doctor_host_rewrite_and_recall_warnings(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(
                b, "decision", "local",
                base_url="http://host.docker.internal:8090/v1/systemone",
                key="local-k-1",
            )
            probed: list[str] = []

            class _Resp:
                status = 200

            def _fake_http(url: str):
                probed.append(url)
                return _Resp()

            cks = _checks(b, http_get=_fake_http)
            self.assertEqual(probed, ["http://localhost:8090/v1/systemone"])
            dec_ck = next(c for c in cks if c["title"] == "memória · decisão")
            self.assertEqual(dec_ck["level"], "ok")
            self.assertIn("http://localhost:8090/v1/systemone", dec_ck["detail"])

            # Recall ligado: doctor avisa sobre requisição por candidato, sem fallback e falha fechada
            providers.set_slot(b, "decision", "hindsight", key="hsk-1", recall="on", candidates=20)
            dec_rec = next(c for c in _checks(b) if c["title"] == "memória · decisão")
            self.assertEqual(dec_rec["level"], "warn")
            self.assertIn("cada candidato", dec_rec["detail"])
            self.assertIn("não há fallback", dec_rec["detail"])
            self.assertIn("falha fechado", dec_rec["detail"])

            # Recall ligado com chave ausente: WARN
            b.inst.env_file.write_text("HINDSIGHT_API_RECALL_DECISION_MODEL_PROVIDER=hindsight\n", encoding="utf-8")
            b.inst = config.load(b.inst.root)
            dec_missing = next(c for c in _checks(b) if c["title"] == "memória · decisão")
            self.assertEqual(dec_missing["level"], "warn")


class FormsAndParserParityTests(unittest.TestCase):
    """Toda opção exposta pelo wizard e formulários é não-vazia e aceita pelo parser da CLI."""

    def test_forms_options_non_empty_and_accepted_by_cli_parser(self):
        parser = cli.build_parser()
        m = {"form_static": forms.static()}

        # 1. memory.mode
        fm_mode = forms.FORMS["memory.mode"]
        for fid, mode in (("provider", "full"), ("embeddings", "embed"), ("embeddings", "full"), ("reranker", "embed")):
            f = next(x for x in fm_mode.fields if x.id == fid)
            opts = forms.options(f, m, {"mode": mode}, {})
            self.assertTrue(opts, f"memory.mode.{fid} ({mode}) vazio")
            for val, lab in opts:
                self.assertTrue(val and lab)
                raw = {"mode": mode, "embeddings": "fireworks" if mode == "full" else "local",
                       "reranker": "off", "quote": "ok", fid: val}
                argv = forms.build("memory.mode", raw, {}, m)[0]
                ns = parser.parse_args(argv)
                self.assertEqual(getattr(ns, fid), val)

        # 2. memory.provider (todos os 4 slots, inclusive decision com local e hindsight --recall)
        fm_prov = forms.FORMS["memory.provider"]
        f_prov = next(x for x in fm_prov.fields if x.id == "provider")
        for slot in providers.SLOTS:
            opts = forms.options(f_prov, m, {"slot": slot}, {})
            self.assertTrue(opts, f"memory.provider ({slot}) vazio")
            for val, lab in opts:
                self.assertTrue(val and lab)
                raw = {"slot": slot, "provider": val}
                if slot == "decision" and val == "hindsight":
                    for rec_val, cands in (("off", ""), ("on", "25")):
                        argv = forms.build("memory.provider", {**raw, "recall": rec_val, "candidates": cands}, {}, m)[0]
                        ns = parser.parse_args(argv)
                        self.assertEqual((ns.slot, ns.provider, ns.recall), (slot, val, rec_val))
                else:
                    argv = forms.build("memory.provider", raw, {}, m)[0]
                    ns = parser.parse_args(argv)
                    self.assertEqual((ns.slot, ns.provider), (slot, val))

        # 3. Opções do wizard (onboard.state) aceitas pelo parser de `memory providers set`
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ob_provs = onboard.state(b)["memory"]["providers"]
            for slot, entries in ob_provs.items():
                self.assertTrue(entries, f"onboard.state providers[{slot}] vazio")
                for entry in entries:
                    ns = parser.parse_args(["memory", "providers", "set", slot, "--provider", entry["key"]])
                    self.assertEqual((ns.slot, ns.provider), (slot, entry["key"]))


if __name__ == "__main__":
    unittest.main()
