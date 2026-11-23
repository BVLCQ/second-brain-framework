"""`memory setup` headless: um slot mantém tudo que o payload não nomeou.

O wizard e os formulários enviam payload completo; a CLI e o painel podem nomear um slot só. Antes, o
assistente roteirizado rodava sobre TODOS os slots do modo e regravava com o padrão do modo quem não foi
nomeado — reranker e decisão voltavam para `off`, modelo customizado voltava para o recomendado —; uma chave
digitada era ignorada quando já havia uma no .env; e a escolha explícita de `decision` era descartada (o
rótulo do passo diz "decisão", a UI roteirizada só casava "decision").
"""
from __future__ import annotations

import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, memory, onboard, providers, setup, util
from brainlib.core import Brain


def _inst(tmp: Path, *, allow: tuple[str, ...] = ("dona-demo", "marina-demo", "#time")) -> config.Instance:
    """Instância de prova: dono `dona-demo` SEM o alias "eu" — só a dobra de "eu" faz o dono ser achado."""
    for d in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH",
              "vault/reports"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "dona-demo"\nname = "Dona Demo"\n\n'
        '[outbound]\nallow = [' + ", ".join(f'"{x}"' for x in allow) + ']\n\n'
        '[work]\nstart = "09:00"\nend = "18:00"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path, **kw) -> Brain:
    b = Brain(_inst(tmp, **kw))
    b.record_one({"type": "person.added", "id": "dona-demo", "by": "owner",
                  "data": {"name": "Dona Demo", "aliases": ["Dona"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina Demo", "aliases": ["Mari Demo"], "email": "marina-demo@x.com"}})
    return b


class MemorySetupKeepsUnaddressedSlots(unittest.TestCase):
    def test_validate_reports_which_slots_the_payload_addressed(self):
        v = setup.validate_memory_setup({"mode": "full", "consent": True, "provider": "openai", "key": "sk-" + "1"})
        self.assertEqual(v["given"], {"llm": True, "embeddings": False, "reranker": False, "decision": False})
        v = setup.validate_memory_setup({"mode": "embed", "embeddings": "fireworks", "emb_key": "fw-" + "1"})
        self.assertEqual((v["given"]["embeddings"], v["given"]["reranker"]), (True, False))
        v = setup.validate_memory_setup({"mode": "full", "consent": True, "llm": {"provider": "claude-code"},
                                         "reranker_key": "ze-" + "1"})
        self.assertEqual((v["given"]["llm"], v["given"]["reranker"], v["given"]["decision"]), (True, True, False))
        # chave/modelo sem provedor: endereça o slot, mas não nomeia provedor
        v = setup.validate_memory_setup({"mode": "full", "consent": True, "model": "gpt-prova", "key": "sk-" + "1"})
        self.assertEqual((v["given"]["llm"], v["named"]["llm"], v["model_given"]["llm"]), (True, False, True))
        v = setup.validate_memory_setup({"mode": "embed", "emb_key": "fw-" + "1"})
        self.assertEqual((v["given"]["embeddings"], v["named"]["embeddings"], v["model_given"]["embeddings"]),
                         (True, False, False))

    def _configure(self, b: Brain, payload: dict) -> str:
        """O fluxo roteirizado de verdade — sem docker, sem servidor, sem LM Studio: só o que sai da máquina é mockado."""
        with mock.patch.object(setup, "docker_available", return_value=True), \
                mock.patch.object(setup, "hindsight_health", return_value={"status": "ok"}), \
                mock.patch.object(setup, "compose_up", return_value=True), \
                mock.patch.object(setup, "wait_hindsight", return_value=True), \
                mock.patch.object(setup, "lmstudio_up", return_value=True), \
                mock.patch.object(setup, "lmstudio_ensure", return_value=True), \
                mock.patch.object(memory, "setup", side_effect=lambda bb: ["brain"]), \
                mock.patch.object(memory, "client") as hs:
            hs.return_value.health_llm.return_value = {}
            return setup.configure_memory(b, payload, say=lambda *_: None)

    @staticmethod
    def _slot_env(env: dict, needle: str) -> dict:
        return {k: v for k, v in env.items() if needle in k}

    def test_provider_flag_keeps_reranker_and_decision_already_configured(self):
        """Antes: trocar o LLM no full voltava reranker e decisão para `off` (e apagava a chave do .env)."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "reranker", "fireworks", key="fw-" + "1")
            providers.set_slot(b, "decision", "hindsight", key="hs-" + "1")
            before = config.load_env(b.inst)
            final = self._configure(b, {"mode": "full", "consent": True, "provider": "openai", "model": "gpt-prova",
                                        "key": "sk-" + "1", "embeddings": "fireworks", "emb_key": "fw-" + "1"})
            self.assertEqual(final, "full")
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["llm_provider"], mem["embeddings_provider"]), ("openai", "fireworks"))   # endereçados
            self.assertEqual((mem["reranker_provider"], mem["decision_provider"]), ("fireworks", "hindsight"))  # intactos
            after = config.load_env(b.inst)
            self.assertEqual(self._slot_env(after, "RERANK"), self._slot_env(before, "RERANK"))
            self.assertEqual(self._slot_env(after, "DECISION"), self._slot_env(before, "DECISION"))

    def test_embed_setup_keeps_a_configured_reranker(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "reranker", "cohere", key="ck-" + "1")
            final = self._configure(b, {"mode": "embed", "embeddings": "fireworks", "emb_key": "fw-" + "1"})
            self.assertEqual(final, "embed")
            self.assertEqual(config.load(b.inst.root).cfg["memory"]["reranker_provider"], "cohere")

    def test_unaddressed_slot_without_a_valid_choice_still_falls_to_the_mode_default(self):
        """Instância nova indo ao full: embeddings = local (padrão do embed), que o full não aceita → fireworks, como antes."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self._configure(b, {"mode": "full", "consent": True, "provider": "openai", "model": "gpt-prova",
                                "key": "sk-" + "1", "emb_key": "fw-" + "1"})
            self.assertEqual(config.load(b.inst.root).cfg["memory"]["embeddings_provider"], "fireworks")

    def test_addressed_decision_slot_is_applied(self):
        """O rótulo do passo diz "decisão"; a UI roteirizada só casava "decision" — a escolha do payload era ignorada."""
        base = {"mode": "full", "consent": True, "provider": "openai", "model": "gpt-prova", "key": "sk-" + "1",
                "embeddings": "fireworks", "emb_key": "fw-" + "1"}
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self._configure(b, {**base, "decision": {"provider": "hindsight", "key": "hs-" + "1"}})
            self.assertEqual(config.load(b.inst.root).cfg["memory"]["decision_provider"], "hindsight")
            self._configure(b, {**base, "decision": {"provider": "off"}})
            self.assertEqual(config.load(b.inst.root).cfg["memory"]["decision_provider"], "off")

    @staticmethod
    def _slots_view(b: Brain) -> tuple[dict, dict]:
        """O que diz respeito a provedor/modelo/chave de cada slot: a configuração e o .env inteiros."""
        mem = config.load(b.inst.root).cfg["memory"]
        return ({k: v for k, v in mem.items() if any(t in k for t in ("provider", "model", "base_url"))},
                config.load_env(b.inst))

    def test_key_without_provider_rotates_the_key_and_keeps_the_rest(self):
        """Antes: `--key` sozinho trocava o LLM para o padrão do modo (anthropic) e gravava a chave nele."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "openai", model="gpt-prova", key="sk-" + "1")
            providers.set_slot(b, "embeddings", "fireworks", key="fw-" + "1")
            kenv = providers.PROVIDERS["llm"]["openai"]["key_env"]
            self.assertEqual(self._configure(b, {"mode": "full", "consent": True, "key": "sk-" + "2"}), "full")
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["llm_provider"], mem["llm_models"]), ("openai", "gpt-prova"))
            self.assertEqual(config.load_env(b.inst)[kenv], "sk-" + "2")

    def test_typed_key_replaces_the_stored_one(self):
        """Antes: com chave já no .env, a digitada era ignorada — e "vazio = mantém" prometia o contrário."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "openai", model="gpt-prova", key="sk-" + "1")
            providers.set_slot(b, "embeddings", "fireworks", key="fw-" + "1")
            kenv = providers.PROVIDERS["llm"]["openai"]["key_env"]
            self._configure(b, {"mode": "full", "consent": True, "provider": "openai", "model": "gpt-4o",
                                "key": "sk-" + "2"})
            self.assertEqual(config.load_env(b.inst)[kenv], "sk-" + "2")
            self.assertEqual(config.load(b.inst.root).cfg["memory"]["llm_models"], "gpt-4o")     # modelo nomeado: aplica

    def test_omitted_key_keeps_the_stored_one(self):
        """Chave omitida com chave já gravada: o roteiro não pode pedir — e "vazio = mantém" tem que valer para o
        slot endereçado. A 1ª versão lia `replace_key` como método, sem chamar: pedia a chave sempre e falhava com
        "falta a API key" ao trocar só o modelo, ou ao trocar de provedor (todos os LLM por chave dividem a mesma
        variável no .env)."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "openai", model="gpt-prova", key="sk-" + "1")
            providers.set_slot(b, "embeddings", "fireworks", key="fw-" + "1")
            # 1) só o modelo mudou
            self.assertEqual(self._configure(b, {"mode": "full", "consent": True, "model": "gpt-outro"}), "full")
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["llm_provider"], mem["llm_models"]), ("openai", "gpt-outro"))
            # 2) o provedor mudou para um que já tem chave gravada
            providers.set_slot(b, "llm", "zai", key="zk-" + "1")
            before = self._slots_view(b)
            self.assertEqual(self._configure(b, {"mode": "full", "consent": True, "provider": "zai"}), "full")
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual(mem["llm_provider"], "zai")
            self.assertEqual(self._slot_env(config.load_env(b.inst), "API_KEY"), self._slot_env(before[1], "API_KEY"))
            self.assertEqual(config.load_env(b.inst)["HINDSIGHT_API_LLM_API_KEY"], "zk-" + "1")

    def test_going_full_with_local_embeddings_uses_the_stored_cloud_key(self):
        """Embeddings locais (modo embed) indo ao full: o slot não nomeado cai em fireworks e reaproveita a chave que
        já está no .env — a mesma falha da versão anterior, em outro slot."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "openai", model="gpt-prova", key="sk-" + "1")
            providers.set_slot(b, "embeddings", "fireworks", key="fw-" + "1")
            providers.set_slot(b, "embeddings", "local")
            self.assertEqual(self._configure(b, {"mode": "full", "consent": True}), "full")
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual(mem["embeddings_provider"], "fireworks")
            kenv = providers.PROVIDERS["embeddings"]["fireworks"]["key_env"]
            self.assertEqual(config.load_env(b.inst)[kenv], "fw-" + "1")

    def test_missing_key_is_still_refused_before_anything_is_written(self):
        """O outro lado da regra: sem chave no payload e sem chave no .env, o roteiro recusa antes de gravar."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaisesRegex(util.BrainError, "cole a chave de llm"):
                self._configure(b, {"mode": "full", "consent": True, "provider": "openai", "model": "gpt-prova"})
            self.assertEqual(config.load_env(b.inst), {})

    def test_form_payload_with_prefilled_providers_changes_nothing(self):
        """O formulário da TUI reenvia os provedores atuais, sem modelo: editar um slot não pode regravar os outros."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "llm", "openai", model="gpt-prova", key="sk-" + "1")
            providers.set_slot(b, "embeddings", "fireworks", key="fw-" + "1")
            providers.set_slot(b, "reranker", "cohere", key="ck-" + "1")
            providers.set_slot(b, "decision", "hindsight", key="hs-" + "1")
            before = self._slots_view(b)
            self._configure(b, {"mode": "full", "consent": True, "provider": "openai", "embeddings": "fireworks",
                                "reranker": "cohere"})
            self.assertEqual(self._slots_view(b), before)

class MemorySetupAppliesCustomSlotValues(unittest.TestCase):
    """Modelo e endpoint que o payload traz para um slot que não é o LLM (embeddings e reranker `custom`: a página de
    onboarding pede os dois) precisam chegar ao slot. Antes, a UI roteirizada só conhecia o modelo e a base URL do LLM e
    respondia com eles às perguntas de qualquer slot: sem LLM no payload (modo embed) dava "embeddings custom exige
    --model e --base-url" com os dois digitados; com LLM custom no payload (modo full) o slot de embeddings era
    gravado com o modelo e o endpoint DO LLM; no reranker, que não exige nada, os dois eram descartados sem erro."""

    _configure = MemorySetupKeepsUnaddressedSlots._configure

    def test_custom_embeddings_get_the_model_and_base_url_from_the_payload(self):
        """Antes: "embeddings custom exige --model e --base-url" — no modo embed não há LLM de onde emprestar."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self._configure(b, {"mode": "embed", "embeddings": {"provider": "custom", "model": "emb-prova",
                                                                "base_url": "https://emb.example.invalid/v1",
                                                                "key": "sk-" + "1"}})
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["embeddings_provider"], mem["embeddings_model"], mem["embeddings_base_url"]),
                             ("custom", "emb-prova", "https://emb.example.invalid/v1"))

    def test_custom_embeddings_never_borrow_the_llm_model_or_base_url(self):
        """Antes: o slot de embeddings saía com o modelo e o endpoint do LLM — sem erro nenhum."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self._configure(b, {"mode": "full", "consent": True,
                                "llm": {"provider": "custom", "model": "llm-prova",
                                        "base_url": "https://llm.example.invalid/v1", "key": "sk-" + "1"},
                                "embeddings": {"provider": "custom", "model": "emb-prova",
                                               "base_url": "https://emb.example.invalid/v1", "key": "sk-" + "1"}})
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["llm_provider"], mem["llm_models"]), ("custom", "llm-prova"))
            self.assertEqual((mem["embeddings_model"], mem["embeddings_base_url"]),
                             ("emb-prova", "https://emb.example.invalid/v1"),
                             "embeddings herdou o modelo/endpoint do LLM")

    def test_custom_reranker_gets_the_model_and_base_url_from_the_payload(self):
        """Antes: `set_slot` não exige nada do reranker custom — modelo e endpoint digitados eram descartados sem erro."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self._configure(b, {"mode": "embed", "embeddings": "fireworks", "emb_key": "fw-" + "1",
                                "reranker": {"provider": "custom", "model": "rr-prova",
                                             "base_url": "https://rr.example.invalid/v1", "key": "ck-" + "1"}})
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["reranker_provider"], mem["reranker_model"], mem["reranker_base_url"]),
                             ("custom", "rr-prova", "https://rr.example.invalid/v1"))

    def test_model_without_provider_addresses_the_reranker(self):
        """A mesma regra do LLM: modelo/endpoint sem provedor endereça o slot, mas não nomeia provedor."""
        v = setup.validate_memory_setup({"mode": "embed", "embeddings": "fireworks",
                                         "reranker": {"model": "rr-prova", "base_url": "https://rr.example.invalid/v1"}})
        self.assertEqual((v["given"]["reranker"], v["named"]["reranker"], v["model_given"]["reranker"]),
                         (True, False, True))

    def test_key_alone_keeps_the_custom_slot_model_and_base_url(self):
        """O outro lado: chave nova para um embeddings custom já gravado, sem provedor nomeado — provedor, modelo e
        endpoint ficam, só a chave gira (o slot não passa pelo passo de provedores)."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "embeddings", "custom", model="emb-prova",
                               base_url="https://emb.example.invalid/v1", key="sk-" + "1")
            kenv = providers.PROVIDERS["embeddings"]["custom"]["key_env"]
            self._configure(b, {"mode": "embed", "emb_key": "sk-" + "2"})
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["embeddings_provider"], mem["embeddings_model"], mem["embeddings_base_url"]),
                             ("custom", "emb-prova", "https://emb.example.invalid/v1"))
            self.assertEqual(config.load_env(b.inst)[kenv], "sk-" + "2")

    def test_wizard_without_a_script_asks_a_custom_slot_by_its_name(self):
        """Wizard interativo (UI sem roteiro): a pergunta nomeia o slot, o padrão continua o do registro (`custom` não
        tem modelo nem endpoint) e o que o dono digita é o que fica gravado."""
        class _UI:
            interactive = True

            def __init__(self):
                self.asks: list = []

            def say(self, msg):
                pass

            def choice(self, prompt, options, default):
                return "custom"

            def ask(self, prompt, default=""):
                self.asks.append((prompt, default))
                return {"Modelo (embeddings)": "emb-prova",
                        "Base URL (embeddings)": "https://emb.example.invalid/v1"}.get(prompt, default)

            def secret(self, prompt):
                return "sk-" + "1"

            def confirm(self, prompt, default=False):
                return default

        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ui = _UI()
            setup._providers_step(b, ui, ["embeddings"], going_full=False)
            self.assertEqual(ui.asks, [("Modelo (embeddings)", ""), ("Base URL (embeddings)", "")])
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["embeddings_model"], mem["embeddings_base_url"]),
                             ("emb-prova", "https://emb.example.invalid/v1"))

    @staticmethod
    def _no_machine():
        """Tudo que sai da máquina é mockado — o mesmo conjunto do `_configure` da classe de cima."""
        st = contextlib.ExitStack()
        for name, kw in (("docker_available", {"return_value": True}), ("hindsight_health", {"return_value": {"status": "ok"}}),
                         ("compose_up", {"return_value": True}), ("wait_hindsight", {"return_value": True}),
                         ("lmstudio_up", {"return_value": True}), ("lmstudio_ensure", {"return_value": True})):
            st.enter_context(mock.patch.object(setup, name, **kw))
        st.enter_context(mock.patch.object(memory, "setup", side_effect=lambda bb: ["brain"]))
        hs = st.enter_context(mock.patch.object(memory, "client"))
        hs.return_value.health_llm.return_value = {}
        return st

    def test_onboarding_route_carries_a_custom_slot_to_its_slot(self):
        """Pela rota `/api/onboard/memory`, com o corpo que a página de onboarding monta (o job roda em linha, sem
        thread). Antes: no modo embed, "embeddings custom exige --model e --base-url" com os dois digitados."""
        class _Job:
            id = "job-de-prova"

            def say(self, *_a, **_k):
                pass

        def _start_sync(_name, run):
            run(_Job())
            return _Job()

        body = {"mode": "embed",                                       # readSlot("embeddings") / readSlot("reranker")
                "embeddings": {"provider": "custom", "model": "emb-prova",
                               "base_url": "https://emb.example.invalid/v1", "key": "sk-" + "1"},
                "reranker": {"provider": "custom", "model": "rr-prova",
                             "base_url": "https://rr.example.invalid/v1", "key": "ck-" + "1"}}
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self._no_machine(), mock.patch.object(onboard, "_start", _start_sync):
                self.assertEqual(onboard.apply_memory(b, body), {"job": "job-de-prova"})
            mem = config.load(b.inst.root).cfg["memory"]
            self.assertEqual((mem["embeddings_provider"], mem["embeddings_model"], mem["embeddings_base_url"]),
                             ("custom", "emb-prova", "https://emb.example.invalid/v1"))
            self.assertEqual((mem["reranker_provider"], mem["reranker_model"], mem["reranker_base_url"]),
                             ("custom", "rr-prova", "https://rr.example.invalid/v1"))
            self.assertIn("memoria", onboard.progress(b.inst)["done"])        # o passo foi dado

    def test_onboarding_page_sends_the_model_and_base_url_of_a_custom_slot(self):
        """O outro lado da mesma regra, fixado no fonte da página: `custom` está nos menus de embeddings e de
        reranker; um slot custom ganha os campos Modelo e Base URL; cada slot sai com o seu modelo e a sua base
        URL; e é esse corpo que vai para a rota de memória."""
        self.assertIn("custom", providers.PROVIDERS["embeddings"])
        self.assertIn("custom", providers.PROVIDERS["reranker"])
        js = (ROOT / "brainlib" / "assets" / "src" / "extra.js").read_text(encoding="utf-8")
        self.assertRegex(js, r"""\{key: "custom",[^\n]*m\.emb_key\}""")              # menu de embeddings
        self.assertRegex(js, r"""\{key: "custom",[^\n]*m\.rer_key\}""")              # menu de reranker
        self.assertIn('const needModel = slot === "llm" || curKey === "custom";', js)
        self.assertIn("id=\"model-' + slot + '\"", js)
        self.assertRegex(js, r"""curKey === "custom" \? '<label[^>]*><span>Base URL</span><input[^>]*id="url-' \+ slot""")
        self.assertIn("if (mEl && mEl.value.trim()) obj.model = mEl.value.trim();", js)
        self.assertIn("if (uEl && uEl.value.trim()) obj.base_url = uEl.value.trim();", js)
        self.assertIn('body.embeddings = readSlot("embeddings");', js)
        self.assertIn('body.reranker = readSlot("reranker");', js)
        self.assertIn('const r = await obAct("memory", body);', js)


if __name__ == "__main__":
    unittest.main()
