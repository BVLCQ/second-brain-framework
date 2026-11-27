"""Configurações › Memória: modo e provedores numa tela só.

Antes eram dois blocos: Modo (none · embed · full, com uma parte dos campos de cada slot) e a tabela Provedores, que
abria o formulário `memory.provider` (a linha `memory providers set` — sem recriar o servidor). Agora um editor só,
pré-preenchido com o que está gravado, aplicado pela rota do passo Memória (`/api/onboard/memory` →
`configure_memory` → `set_slot`, que sobe ou recria o servidor). Este módulo fixa:

1. o view model que alimenta a tela sai do registro (operações do LLM, rótulos, padrões) — nada de lista à mão;
2. as funções puras da tela (rascunho, diferença, corpo de cada slot), rodando em node sobre o fonte;
3. a volta completa: o corpo que a tela monta é aceito pela rota e grava o que a tela mostrava;
4. a paridade: todo campo do formulário `memory.provider` (TUI) e toda flag de `memory providers set` tem um controle
   na tela — campo novo lá sem lugar aqui reprova;
5. as correções que a tela tornou visíveis: dimensão e teto de candidatos de um provedor anterior não ficam para trás.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from brainlib import config, forms, memory, onboard, providers, serve, setup  # noqa: E402
from test_eng_setup_headless_slots import _brain  # noqa: E402

EXTRA_JS = ROOT / "brainlib" / "assets" / "src" / "extra.js"
NODE = shutil.which("node")


def _helpers_src() -> str:
    """As funções puras da tela (do `const MEM_MODES` até o `SETUP.memoria`), para rodar em node."""
    src = EXTRA_JS.read_text(encoding="utf-8")
    return src[src.index("const MEM_MODES = "):src.index("SETUP.memoria = box => {")]


def _node(script: str):
    assert NODE, "node ausente"
    proc = subprocess.run([NODE, "-e", "const window = {};\n" + _helpers_src() + "\n" + script],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _no_machine():
    """Tudo que sai da máquina é mockado (docker, servidor de memória, LM Studio, decisor local)."""
    st = contextlib.ExitStack()
    returns: dict[str, object] = {"docker_available": True, "hindsight_health": {"status": "ok"}, "compose_up": True,
                                  "wait_hindsight": True, "lmstudio_up": True, "lmstudio_ensure": True}
    for name, rv in returns.items():
        st.enter_context(mock.patch.object(setup, name, return_value=rv))
    st.enter_context(mock.patch.object(memory, "setup", side_effect=lambda bb: ["brain"]))
    hs = st.enter_context(mock.patch.object(memory, "client"))
    hs.return_value.health_llm.return_value = {}
    return st


class _Job:
    id = "job-de-prova"

    def say(self, *_a, **_k):
        pass


def _apply(b, body: dict) -> dict:
    """A rota do painel (`/api/onboard/memory`) com o job em linha; devolve o stack gravado depois."""
    def _start_sync(_name, run):
        run(_Job())
        return _Job()
    with _no_machine(), mock.patch.object(onboard, "_start", _start_sync):
        onboard.apply_memory(b, body)
    b.inst = config.load(b.inst.root)
    return providers.stack(b)


def _screen_bodies(stack: dict, menus: dict, edits: str = "") -> dict:
    """O que a tela manda ao Aplicar: rascunho de cada slot a partir do gravado, `edits` (JS) mexe no rascunho."""
    return _node(f"""
const cur = {json.dumps(stack)}, menus = {json.dumps(menus)};
const reg = (s, k) => (menus[s] || []).find(x => x.key === k) || null;
const base = {{}}, draft = {{}};
for (const s of ["llm", "embeddings", "reranker", "decision"]) {{
  base[s] = memDraft(s, cur[s], reg(s, (cur[s] || {{}}).provider));
  draft[s] = memDraft(s, cur[s], reg(s, (cur[s] || {{}}).provider));
}}
const fresh = (s, p) => Object.assign(memDraft(s, {{}}, null), {{provider: p}});
{edits}
const out = {{}};
for (const s of ["llm", "embeddings", "reranker", "decision"]) out[s] = memSlotBody(s, draft[s], base[s]);
process.stdout.write(JSON.stringify(out));
""")


def _menus(b) -> dict:
    """Os cardápios por slot que a tela recebe (onboard.state → memory.providers), sem sondar a máquina."""
    with mock.patch.object(onboard, "_prereqs", return_value={"docker": True, "docker_state": "up", "lmstudio": True,
                                                              "lmstudio_state": "up"}), \
         mock.patch.object(onboard, "_llm_auth_state", return_value={}):
        return onboard.state(b)["memory"]


class ViewModelComesFromTheRegistry(unittest.TestCase):
    def test_memory_state_carries_the_stack_ops_labels_and_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            m = _menus(b)
            self.assertEqual(m["current"], providers.stack(b))                    # o que está gravado, por slot
            self.assertEqual(m["slot_labels"], dict(providers.SLOT_LABELS))
            # uma entrada por operação do LLM (menos a default, que é o campo Modelo), rótulo do registro
            ops = [op for op, _ in providers.LLM_OPS if op != "default"]
            self.assertEqual([op for op, _ in m["llm_ops"]], ops)
            for op, label in m["llm_ops"]:
                self.assertEqual(label, providers.LLM_OP_LABELS[op])
            # padrões do provedor que a tela diz no campo vazio
            fw_emb = next(x for x in m["providers"]["embeddings"] if x["key"] == "fireworks")
            fw_rer = next(x for x in m["providers"]["reranker"] if x["key"] == "fireworks")
            self.assertEqual(fw_emb["dimensions"], providers.PROVIDERS["embeddings"]["fireworks"]["dimensions"])
            self.assertEqual(fw_rer["candidates"], providers.PROVIDERS["reranker"]["fireworks"]["candidates"])

    def test_models_of_reads_the_saved_table_tolerantly(self):
        self.assertEqual(providers.models_of("retain=a,default=b"), {"retain": "a", "default": "b"})
        self.assertEqual(providers.models_of("modelo-solto"), {"default": "modelo-solto"})
        self.assertEqual(providers.models_of("retain=a,inventada=x"), {"retain": "a"})
        self.assertEqual(providers.models_of(""), {})

    def test_panel_no_longer_runs_the_provider_line(self):
        """O painel aplica pela rota do passo Memória; a linha `memory providers set` ficou na TUI e no terminal."""
        self.assertEqual(forms.FORMS["memory.provider"].where, "tui")
        self.assertFalse(serve._allowed_argv(["memory", "providers", "set", "embeddings", "--provider", "local"]))


@unittest.skipUnless(NODE, "node ausente")
class ScreenHelpers(unittest.TestCase):
    def test_slots_follow_the_mode_and_the_recall(self):
        r = _node('process.stdout.write(JSON.stringify([memSlotsFor("none"), memSlotsFor("embed"), '
                  'memSlotsFor("full", false), memSlotsFor("full", true)]))')
        self.assertEqual(r, [[], ["embeddings", "reranker"], ["llm", "embeddings", "reranker", "decision"],
                             ["llm", "embeddings", "decision"]])          # recall ligado: reranker inerte, fora

    def test_untouched_slot_is_only_named_never_rewritten(self):
        """Aplicar sem mexer num slot não o regrava (só nomeia o provedor) — o que está gravado fica."""
        stack = {"llm": {"provider": "anthropic", "ops": {"default": "m1", "retain": "m2"}},
                 "embeddings": {"provider": "fireworks", "model": "fireworks/qwen3-embedding-8b", "dimensions": 768},
                 "reranker": {"provider": "cohere", "model": "rerank-v3.5", "candidates": 30},
                 "decision": {"provider": "hindsight", "recall": True, "candidates": 25}}
        out = _screen_bodies(stack, {})
        self.assertEqual(out, {"llm": {"provider": "anthropic"}, "embeddings": {"provider": "fireworks"},
                               "reranker": {"provider": "cohere"}, "decision": {"provider": "hindsight"}})

    def test_changed_slot_is_rewritten_with_exactly_what_the_screen_shows(self):
        stack = {"llm": {"provider": "anthropic", "ops": {"default": "m1", "retain": "m2"}},
                 "embeddings": {"provider": "local", "model": "text-embedding-bge-m3"},
                 "reranker": {"provider": "off"}, "decision": {"provider": "off"}}
        menus = {"embeddings": [{"key": "local", "model": "text-embedding-bge-m3"}]}   # o modelo gravado é o padrão
        out = _screen_bodies(stack, menus, """
draft.llm.ops.retain = "";                                  // apagou o modelo do retain: volta ao Modelo
draft.llm.ops.reflect = "m3";
draft.reranker = fresh("reranker", "cohere"); draft.reranker.candidates = "40"; draft.reranker.key = "ck-x";
draft.decision = fresh("decision", "hindsight"); draft.decision.recall = "on"; draft.decision.rcands = "25";
draft.embeddings.dimensions = "512";
""")
        self.assertEqual(out["llm"], {"provider": "anthropic", "reconfigure": True, "model": "m1",
                                      "models": {"reflect": "m3"}})
        self.assertEqual(out["reranker"], {"provider": "cohere", "key": "ck-x", "reconfigure": True, "candidates": 40})
        self.assertEqual(out["decision"], {"provider": "hindsight", "reconfigure": True, "recall": "on", "candidates": 25})
        self.assertEqual(out["embeddings"], {"provider": "local", "reconfigure": True, "dimensions": 512})

    def test_local_decider_sends_a_url_only_from_the_advanced_box(self):
        stack = {"decision": {"provider": "off"}}
        out = _screen_bodies(stack, {}, """
draft.decision = fresh("decision", "local");
draft.decision.base_url = "http://exemplo.invalid:8000";   // digitada, mas o avançado está desmarcado
""")
        self.assertEqual(out["decision"], {"provider": "local", "reconfigure": True})   # o Brain instala
        out = _screen_bodies(stack, {}, """
draft.decision = fresh("decision", "local"); draft.decision.url_on = true;
draft.decision.base_url = "http://exemplo.invalid:8000";
""")
        self.assertEqual(out["decision"]["base_url"], "http://exemplo.invalid:8000")

    def test_defaults_are_not_prefilled_so_the_placeholder_tells_the_truth(self):
        """Teto e dimensão iguais ao padrão do provedor ficam vazios (o placeholder diz o padrão); diferentes, aparecem."""
        menus = {"reranker": [{"key": "fireworks", "candidates": 50}], "embeddings": [{"key": "fireworks", "dimensions": 1536}]}
        r = _node(f"""const m = {json.dumps(menus)};
process.stdout.write(JSON.stringify([
  memDraft("reranker", {{provider: "fireworks", candidates: 50}}, m.reranker[0]).candidates,
  memDraft("reranker", {{provider: "fireworks", candidates: 30}}, m.reranker[0]).candidates,
  memDraft("embeddings", {{provider: "fireworks", dimensions: 1536}}, m.embeddings[0]).dimensions,
  memDraft("embeddings", {{provider: "fireworks", dimensions: 768}}, m.embeddings[0]).dimensions]))""")
        self.assertEqual(r, ["", "30", "", "768"])


@unittest.skipUnless(NODE, "node ausente")
class ScreenBodyRoundTrip(unittest.TestCase):
    """O corpo que a tela monta passa pela rota do painel e grava o que a tela mostrava."""
    FULL = {"mode": "full", "consent": True,
            "llm": {"provider": "anthropic", "key": "sk-" + "1"},
            "embeddings": {"provider": "fireworks", "key": "fw-" + "1"},
            "reranker": {"provider": "off"}, "decision": {"provider": "off"}}

    def _full(self, td):
        b = _brain(Path(td))
        _apply(b, self.FULL)
        return b

    def _screen(self, b, edits: str) -> dict:
        st, m = providers.stack(b), _menus(b)
        body = {"mode": "full", "consent": True, **_screen_bodies(st, m["providers"], edits)}
        return _apply(b, body)

    def test_llm_model_per_operation_and_back_to_the_recommended(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._full(td)
            st = self._screen(b, 'draft.llm.model = "modelo-base"; draft.llm.ops.retain = "modelo-barato";')
            self.assertEqual(st["llm"]["ops"], {"default": "modelo-base", "retain": "modelo-barato"})
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_RETAIN_LLM_MODEL"), "modelo-barato")
            # apagou o modelo do retain: a variável sai do .env (antes ficava a da escolha anterior)
            st = self._screen(b, 'draft.llm.ops.retain = "";')
            self.assertNotIn("retain", st["llm"]["ops"])
            self.assertNotIn("HINDSIGHT_API_RETAIN_LLM_MODEL", config.load_env(b.inst))
            self.assertEqual(st["llm"]["ops"].get("default"), "modelo-base")

    def test_reranker_ceiling_and_embeddings_dimensions(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._full(td)
            st = self._screen(b, 'draft.embeddings.dimensions = "1024"; draft.reranker = fresh("reranker", "fireworks"); '
                                 'draft.reranker.candidates = "30"; draft.reranker.key = "fw-" + "1";')
            self.assertEqual((st["embeddings"]["dimensions"], st["reranker"]["candidates"]), (1024, 30))
            env = config.load_env(b.inst)
            self.assertEqual(env.get("HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS"), "1024")
            self.assertEqual(env.get("HINDSIGHT_API_RERANKER_MAX_CANDIDATES"), "30")
            # campos apagados: voltam ao padrão do provedor (Fireworks: 1536 dimensões, teto 50)
            st = self._screen(b, 'draft.embeddings.dimensions = ""; draft.reranker.candidates = "";')
            self.assertEqual((st["embeddings"]["dimensions"], st["reranker"]["candidates"]), (1536, 50))

    def test_local_decider_without_url_is_installed_by_the_brain(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._full(td)
            prepared = {"container_url": "http://host.docker.internal:8000", "local_key": "bdk_" + "prova"}
            with mock.patch("brainlib.decider.prepare", return_value=prepared) as prep:
                st = self._screen(b, 'draft.decision = fresh("decision", "local");')
            prep.assert_called_once()
            self.assertEqual((st["decision"]["provider"], st["decision"]["base_url"]),
                             ("local", "http://host.docker.internal:8000"))


class StaleValuesDoNotSurviveAProviderSwitch(unittest.TestCase):
    """Dimensão e teto de um provedor anterior não ficam para trás (bug anterior à tela, que ela deixou à vista)."""

    def test_embeddings_dimensions_leave_with_the_provider(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "embeddings", "fireworks", key="fw-" + "1")
            self.assertEqual(config.load_env(b.inst).get("HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS"), "1536")
            providers.set_slot(b, "embeddings", "local")              # bge-m3 tem 1024: pedir 1536 quebrava
            self.assertFalse([k for k in config.load_env(b.inst) if k.endswith("_DIMENSIONS")])
            self.assertEqual(providers.stack(b)["embeddings"]["dimensions"], 0)

    def test_reranker_ceiling_leaves_with_the_provider(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "reranker", "fireworks", key="fw-" + "1")
            providers.set_slot(b, "reranker", "cohere", key="ck-" + "1")
            self.assertNotIn("HINDSIGHT_API_RERANKER_MAX_CANDIDATES", config.load_env(b.inst))
            self.assertEqual(providers.stack(b)["reranker"]["candidates"], 0)

    def test_the_recall_keeps_its_ceiling(self):
        """Com o decisor no recall, a variável do teto é do recall: regravar o reranker não a apaga."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "reranker", "cohere", key="ck-" + "1")
            providers.set_slot(b, "decision", "hindsight", key="hs-" + "1", recall="on", candidates=25)
            providers.set_slot(b, "reranker", "cohere", key="ck-" + "1")
            self.assertEqual(config.load_env(b.inst).get("HINDSIGHT_API_RERANKER_MAX_CANDIDATES"), "25")

    def test_a_dimensions_change_asks_for_the_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "embeddings", "fireworks", key="fw-" + "1")
            config.set_keys(b.inst, "memory", {"engine": "hindsight"})
            b.inst = config.load(b.inst.root)
            (b.inst.root / ".memory-state.json").write_text("{}", encoding="utf-8")   # banco já sincronizado
            model = providers.PROVIDERS["embeddings"]["fireworks"]["model"]
            self.assertFalse(providers.embeddings_change_pending(b, "fireworks", model, 1536))
            self.assertTrue(providers.embeddings_change_pending(b, "fireworks", model, 768))
            self.assertFalse(providers.embeddings_change_pending(b, "fireworks", model))   # quem não diz, não muda


class EveryProviderSettingHasAControl(unittest.TestCase):
    """O pedido: modo e provedores numa tela só, sem perder configuração. Todo campo do formulário da TUI e toda flag
    da CLI de provedores têm um controle na tela — campo novo lá, sem lugar aqui, reprova este teste. A exceção é
    decisão do dono e fica escrita aqui: no painel a Decisão é só local ou desligada, então o decisor de nuvem e o
    recall dele (que só existe com ele) ficam na CLI e na TUI — e a tela não pode voltar a oferecê-los."""
    # controle = o trecho do fonte que cria o campo (id montado no HTML ou passado ao `inp`)
    FORM_FIELD_CONTROL = {      # campo do formulário memory.provider → controle da tela
        "slot": 'data-mslot="',                                 # uma linha por slot, na pilha
        "provider": 'id="m-prov-',
        "model": 'inp("m-model-"',
        "advanced": 'id="m-urlon-decision"',
        "base_url": 'inp("m-url-"',
        "key": 'id="m-key-',
        "models": 'inp("m-op-"',
        "candidates": 'inp("m-cands-reranker"',
    }
    CLI_FLAG_CONTROL = {
        "--provider": 'id="m-prov-', "--model": 'inp("m-model-"', "--models": 'inp("m-op-"',
        "--base-url": 'inp("m-url-"', "--dimensions": 'inp("m-dims-embeddings"', "--candidates": 'inp("m-cands-reranker"',
        "--key": 'id="m-key-',
    }
    NOT_ON_THE_PANEL = {        # decisão do dono: Decisão do painel = local ou desligada
        "recall": "o recall é do decisor de nuvem, que o painel não oferece",
        "--recall": "o recall é do decisor de nuvem, que o painel não oferece",
    }

    def _screen_src(self) -> str:
        src = EXTRA_JS.read_text(encoding="utf-8")
        return src[src.index("const MEM_MODES = "):src.index("SETUP.agente = box => {")]

    def test_every_tui_form_field_has_a_control(self):
        fm = forms.FORMS["memory.provider"]
        self.assertEqual({f.id for f in fm.fields}, set(self.FORM_FIELD_CONTROL) | (set(self.NOT_ON_THE_PANEL) & {f.id for f in fm.fields}),
                         "campo novo no formulário memory.provider: dê a ele um controle na tela Memória")
        src = self._screen_src()
        for name, control in self.FORM_FIELD_CONTROL.items():
            self.assertIn(control, src, f"campo {name} sem controle na tela Memória")

    def test_every_cli_flag_has_a_control(self):
        from brainlib import cli

        def child(parser, name):
            sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
            return getattr(sub, "choices")[name]
        pv = child(child(child(cli.build_parser(), "memory"), "providers"), "set")
        flags = {o for a in pv._actions for o in a.option_strings if o.startswith("--") and o != "--help"}
        self.assertEqual(flags, set(self.CLI_FLAG_CONTROL) | {f for f in self.NOT_ON_THE_PANEL if f.startswith("--")},
                         "flag nova em `memory providers set`: dê a ela um controle na tela Memória")
        src = self._screen_src()
        for flag, control in self.CLI_FLAG_CONTROL.items():
            self.assertIn(control, src, f"{flag} sem controle na tela Memória")

    def test_the_panel_offers_no_cloud_decider_and_no_recall(self):
        src = self._screen_src()
        editor = src[src.index("SETUP.memoria = box => {"):]
        for gone in ('id="m-recall"', '"m-rcands"', 'data-mdec="hindsight"'):
            self.assertNotIn(gone, editor)
        self.assertIn("x.legacy", editor)            # o de nuvem só aparece como o gravado de uma instância antiga

    def test_the_three_modes_and_the_cloud_consent_are_on_the_same_screen(self):
        src = self._screen_src()
        for mode in ("none", "embed", "full"):
            self.assertIn(f'["{mode}", ', src)
        self.assertIn('id="m-consent"', src)
        self.assertIn('obAct("memory", body)', src)        # a rota do passo Memória (o job sobe/recria o servidor)


class DecisionMenuIsLocalOnlyOnThePanel(unittest.TestCase):
    """View model: a Decisão do painel oferece Desligado e Local; o decisor de nuvem só volta, marcado `legacy`, para a
    instância que já o tem gravado — abrir a tela e aplicar nunca o troca em silêncio."""

    def test_fresh_instance_sees_off_and_local(self):
        with tempfile.TemporaryDirectory() as td:
            dec = _menus(_brain(Path(td)))["providers"]["decision"]
            self.assertEqual([x["key"] for x in dec], ["off", "local"])
            self.assertFalse(any(x["legacy"] for x in dec))

    def test_saved_cloud_decider_stays_visible_as_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "decision", "hindsight", key="hs-" + "1")
            b.inst = config.load(b.inst.root)
            dec = {x["key"]: x for x in _menus(b)["providers"]["decision"]}
            self.assertEqual(set(dec), {"off", "local", "hindsight"})
            self.assertTrue(dec["hindsight"]["legacy"])
            self.assertFalse(dec["local"]["legacy"])

    def test_the_screen_knows_whether_the_local_decider_can_run_here(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            from brainlib import decider
            with mock.patch.object(decider, "platform_kind", return_value=None):
                self.assertEqual(_menus(b)["decider"], {"platform": "", "installed": False})
            with mock.patch.object(decider, "platform_kind", return_value="mlx"):
                self.assertEqual(_menus(b)["decider"]["platform"], "mlx")


@unittest.skipUnless(NODE, "node ausente")
class WiringPlanMirrorsTheJob(unittest.TestCase):
    """O que a tela diz que o Brain liga sozinho, antes do Aplicar — cada passo é um passo real do `configure_memory`."""
    MENUS = {"llm": [{"key": "claude-code", "subscription": True, "flow": "claude-token", "label": "Claude Code (assinatura)"},
                     {"key": "anthropic", "key_required": True, "label": "Anthropic"}],
             "embeddings": [{"key": "local", "local": True, "model": "text-embedding-bge-m3"},
                            {"key": "fireworks", "key_required": True, "model": "fireworks/qwen3-embedding-8b", "dimensions": 1536}],
             "decision": [{"key": "off"}, {"key": "local", "local": True, "managed": True}]}

    def _plan(self, sel, cur_mode, draft, base, machine):
        m = dict(machine, providers=self.MENUS)
        return _node(f"""
const blank = s => memDraft(s, {{}}, null);
const mk = o => {{ const d = {{}}; for (const s of ["llm", "embeddings", "reranker", "decision"]) d[s] = Object.assign(blank(s), (o || {{}})[s] || {{}}); return d; }};
const out = memPlan({{sel: {json.dumps(sel)}, curMode: {json.dumps(cur_mode)}, draft: mk({json.dumps(draft)}), base: mk({json.dumps(base)}), m: {json.dumps(m)}}});
process.stdout.write(JSON.stringify(out.map(x => x.id + ":" + x.st)));""")

    NEW_MACHINE = {"docker_state": "missing", "lmstudio_state": "missing", "decider": {"platform": "mlx", "installed": False},
                   "llm_auth": {"provider": "", "state": "unknown"}}
    READY = {"docker_state": "up", "lmstudio_state": "up", "decider": {"platform": "mlx", "installed": True},
             "dec_local_key": True, "llm_auth": {"provider": "claude-code", "state": "ok"}}
    LOCAL_FULL = {"llm": {"provider": "claude-code"}, "embeddings": {"provider": "local"}, "reranker": {"provider": "off"},
                  "decision": {"provider": "local"}}

    def test_new_machine_choosing_local_lists_every_install_step(self):
        steps = self._plan("full", "none", self.LOCAL_FULL, {}, self.NEW_MACHINE)
        self.assertEqual(steps, ["docker-inst:todo", "lms-inst:todo", "lms-srv:todo", "lms-model:todo", "dec-inst:todo",
                                 "dec-up:todo", "auth:you", "write:todo", "hs:todo", "verify:todo"])

    def test_ready_machine_only_writes_and_recreates(self):
        steps = self._plan("full", "full", dict(self.LOCAL_FULL, llm={"provider": "claude-code", "model": "outro"}),
                           self.LOCAL_FULL, self.READY)
        self.assertEqual(steps, ["docker:ok", "lms:ok", "dec:ok", "auth:ok", "write:todo", "hs:todo", "verify:todo"])

    def test_saved_decider_without_its_key_is_reinstalled(self):
        """Mesmo sem mudar a escolha: sem a chave do decisor no .env o job não mantém o slot — o plano diz isso."""
        steps = self._plan("full", "full", self.LOCAL_FULL, self.LOCAL_FULL, dict(self.READY, dec_local_key=False))
        self.assertIn("dec:todo", steps)
        steps = self._plan("full", "full", self.LOCAL_FULL, self.LOCAL_FULL, dict(self.READY, decider={"platform": "mlx", "installed": False}))
        self.assertIn("dec-inst:todo", steps)

    def test_installed_decider_is_only_rechecked(self):
        steps = self._plan("full", "embed", self.LOCAL_FULL, dict(self.LOCAL_FULL, decision={"provider": "off"}), self.READY)
        self.assertIn("dec:todo", steps)
        self.assertNotIn("dec-inst:todo", steps)

    def test_cloud_choices_install_nothing_local(self):
        steps = self._plan("full", "none", {"llm": {"provider": "anthropic"}, "embeddings": {"provider": "fireworks"},
                                            "decision": {"provider": "off"}}, {}, self.NEW_MACHINE)
        self.assertFalse([x for x in steps if x.startswith(("lms", "dec", "auth"))])
        self.assertEqual(steps[0], "docker-inst:todo")

    def test_own_decider_url_installs_nothing(self):
        steps = self._plan("full", "none", dict(self.LOCAL_FULL, decision={"provider": "local", "url_on": True,
                                                                           "base_url": "http://exemplo.invalid:8000"}),
                           {}, self.NEW_MACHINE)
        self.assertFalse([x for x in steps if x.startswith("dec")])

    def test_embeddings_switch_leaves_the_rebuild_for_later(self):
        steps = self._plan("embed", "embed", {"embeddings": {"provider": "fireworks"}}, {"embeddings": {"provider": "local"}}, self.READY)
        self.assertEqual(steps[-1], "rebuild:later")
        self.assertIn("verify:todo", steps)

    def test_turning_memory_off_is_one_step(self):
        self.assertEqual(self._plan("none", "embed", {}, {}, self.READY), ["off:todo"])
        self.assertEqual(self._plan("none", "none", {}, {}, self.READY), [])


if __name__ == "__main__":
    unittest.main()
