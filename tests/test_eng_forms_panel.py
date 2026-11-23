"""Testes de regressão para o chunk C3: forms-panel (#69, #86, #87, #81)."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import config, forms, providers, render  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.demo import cli as demo_cli  # noqa: E402
from brainlib.tui.config_keys import ConfigKeys  # noqa: E402


class MemoryModeFormTest(unittest.TestCase):
    @staticmethod
    def _flat(slot):
        """Registro inteiro menos `custom`: provedor custom exige model + base_url, que nem o formulário
        nem as flags planas do `memory setup` têm como levar."""
        return [k for k in providers.PROVIDERS[slot] if k != "custom"]

    def test_memory_mode_lists_match_providers_registry(self):
        m = {"form_static": forms.static()}
        fm = forms.FORMS["memory.mode"]
        f_prov = next(f for f in fm.fields if f.id == "provider")
        f_emb = next(f for f in fm.fields if f.id == "embeddings")
        f_rer = next(f for f in fm.fields if f.id == "reranker")

        self.assertEqual([k for k, _ in forms.options(f_prov, m, {}, {})], self._flat("llm"))
        self.assertEqual([k for k, _ in forms.options(f_rer, m, {}, {})], self._flat("reranker"))
        self.assertEqual([k for k, _ in forms.options(f_emb, m, {"mode": "embed"}, {})],
                         self._flat("embeddings"))
        self.assertEqual([k for k, _ in forms.options(f_emb, m, {"mode": "full"}, {})],
                         [k for k in self._flat("embeddings") if k != "local"])

    def test_every_offered_option_is_accepted_by_the_memory_setup_parser(self):
        """Cardápio só vale se o comando que o formulário monta aceitar a opção. O parser do
        `brain memory setup` é quem decide: uma opção oferecida que ele recusa derruba a linha com
        "invalid choice" (rc 2) — foi o que aconteceu com 18 das opções quando o cardápio passou a vir
        do registro e o parser continuou com a lista chumbada."""
        from brainlib import cli
        parser = cli.build_parser()
        m = {"form_static": forms.static()}
        fm = forms.FORMS["memory.mode"]
        seen = 0
        for fid, mode in (("provider", "full"), ("embeddings", "embed"), ("embeddings", "full"),
                          ("reranker", "embed")):
            f = next(x for x in fm.fields if x.id == fid)
            for value, _label in forms.options(f, m, {"mode": mode}, {}):
                vals = {"mode": mode, "embeddings": "fireworks" if mode == "full" else "local",
                        "reranker": "off", "quote": "ok", fid: value}
                argv = forms.build("memory.mode", vals, {}, m)[0]
                self.assertIn(value, argv)
                ns = parser.parse_args(argv)            # SystemExit(2) se o parser recusar a opção
                self.assertEqual(getattr(ns, fid), value)
                seen += 1
        self.assertGreaterEqual(seen, 20)               # 12 LLM + 4 + 3 embeddings + 5 rerankers

    def test_memory_setup_parser_choices_follow_the_registry(self):
        """As flags planas do `memory setup` não espelham provedores à mão: vêm do registro (menos custom)."""
        from brainlib import cli
        parser = cli.build_parser()
        ns = parser.parse_args(["memory", "setup", "--mode", "full", "--provider", "zai",
                                "--embeddings", "cohere", "--reranker", "zeroentropy"])
        self.assertEqual((ns.provider, ns.embeddings, ns.reranker), ("zai", "cohere", "zeroentropy"))
        with contextlib.redirect_stderr(io.StringIO()):
            for flag in ("--provider", "--embeddings", "--reranker"):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["memory", "setup", "--mode", "full", flag, "custom"])
                with self.assertRaises(SystemExit):
                    parser.parse_args(["memory", "setup", "--mode", "full", flag, "nao-existe"])

    def test_current_custom_provider_still_shows_as_atual(self):
        m = {"form_static": forms.static()}
        fm = forms.FORMS["memory.mode"]
        for fid, mode in (("provider", "full"), ("embeddings", "embed"), ("reranker", "embed")):
            f = next(x for x in fm.fields if x.id == fid)
            opts = forms.options(f, m, {"mode": mode}, {"item": {fid: "custom"}})
            self.assertIn(("custom", "custom (atual)"), opts)
            self.assertEqual(opts[0], ("custom", "custom (atual)"))   # só como "(atual)", nunca como opção do registro
            self.assertEqual([k for k, _ in opts].count("custom"), 1)

    def test_unknown_provider_preserved_and_mode_change_does_not_rewrite(self):
        ctx = {"item": {
            "mode": "embed",
            "provider": "provedor-custom",
            "embeddings": "emb-custom",
            "reranker": "rer-custom",
        }}
        m = {"form_static": forms.static()}
        fm = forms.FORMS["memory.mode"]

        for fid, cur in (("provider", "provedor-custom"), ("embeddings", "emb-custom"), ("reranker", "rer-custom")):
            f = next(x for x in fm.fields if x.id == fid)
            opts = forms.options(f, m, {"mode": "full"}, ctx)
            self.assertIn((cur, f"{cur} (atual)"), opts)

        init = forms.initial(fm, ctx, m)
        self.assertEqual(init["mode"], "embed")
        self.assertEqual(init["provider"], "provedor-custom")
        self.assertEqual(init["embeddings"], "emb-custom")
        self.assertEqual(init["reranker"], "rer-custom")

        cmds_full = forms.build("memory.mode", {**init, "mode": "full", "quote": "ok"}, ctx, m)
        self.assertEqual(cmds_full, [["memory", "setup", "--mode", "full", "--approval", "ok"]])

        cmds_none = forms.build("memory.mode", {**init, "mode": "none"}, ctx, m)
        self.assertEqual(cmds_none, [["memory", "setup", "--mode", "none"]])

        cmds_emb = forms.build("memory.mode", {**init, "mode": "full", "embeddings": "fireworks", "quote": "ok"}, ctx, m)
        self.assertEqual(cmds_emb, [["memory", "setup", "--mode", "full", "--embeddings", "fireworks", "--approval", "ok"]])

    def test_config_keys_f_memory_mode_passes_unknown_providers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "inst"
            with contextlib.redirect_stdout(io.StringIO()):
                demo_cli(argparse.Namespace(dir=str(root), open=False))
            inst = config.load(root)
            config.set_keys(inst, "memory", {
                "engine": "hindsight",
                "extract": True,
                "cloud_llm": True,
                "llm_provider": "claude-code",
                "embeddings_provider": "emb-custom",
                "reranker_provider": "rer-custom",
            })
            b = Brain(config.load(root))

            opened = []

            class _Stub(ConfigKeys):
                def __init__(self, brain):
                    self.store = types.SimpleNamespace(brain=brain)

                def open_form(self, form_id, ctx=None, **kw):
                    opened.append((form_id, ctx, kw))

            _Stub(b).f_memory_mode()
            self.assertEqual(len(opened), 1)
            fid, ctx, kw = opened[0]
            self.assertEqual(fid, "memory.mode")
            self.assertEqual(ctx, {"item": {
                "mode": "full",
                "provider": "claude-code",
                "embeddings": "emb-custom",
                "reranker": "rer-custom",
            }})
            self.assertEqual(kw.get("show"), "Provedores")


class HiddenFieldsTest(unittest.TestCase):
    def _watch_ctx(self, **overrides):
        src = {
            "key": "jira-ops",
            "kind": "jira",
            "jql": "parent = OPS-1 AND updated >= -1d",
            "cloud": "acme.atlassian.net",
            "in_watch": True,
            "window": "7d",
            "mode": "",
            "enabled": True,
        }
        src.update(overrides)
        return {"key0": src["key"], "item": src}

    def test_hiding_configured_field_does_not_emit_clear(self):
        fm = forms.FORMS["watch.edit"]
        m = {"form_static": forms.static(), "source_kinds": [("jira", "Jira"), ("slack", "Slack")]}

        # Caso 2: visível na carga (window=7d), oculto após edição (mode=state) → não emite --unset window
        ctx2 = self._watch_ctx(mode="", window="7d")
        init2 = forms.initial(fm, ctx2, m)
        cmd2 = forms.build("watch.edit", {**init2, "mode": "state"}, ctx2, m)[0]
        self.assertNotIn("--unset", cmd2)

        # Trocar kind para slack também oculta jql/cloud sem emitir --unset
        cmd_kind = forms.build("watch.edit", {**init2, "kind": "slack", "channel": "#ops"}, ctx2, m)[0]
        self.assertNotIn("--unset", cmd_kind)

        # Caso 1: já oculto na carga (mode=state com window residual) → não emite --unset window
        ctx1 = self._watch_ctx(mode="state", window="7d")
        init1 = forms.initial(fm, ctx1, m)
        cmd1 = forms.build("watch.edit", {**init1, "mode": "state"}, ctx1, m)[0]
        self.assertNotIn("--unset", cmd1)

        # Caso 3: visível na carga, continua visível e usuário apaga → emite --unset window
        cmd3 = forms.build("watch.edit", {**init2, "mode": "", "window": ""}, ctx2, m)[0]
        self.assertIn("--unset", cmd3)
        idx = cmd3.index("--unset")
        self.assertEqual(cmd3[idx:idx + 2], ["--unset", "window"])

    def test_missing_and_build_agree_on_whitespace_padded_selector(self):
        m = {"form_static": forms.static()}
        fm_mem = forms.FORMS["memory.mode"]

        raw_full = {"mode": " full ", "provider": "anthropic", "embeddings": "fireworks"}
        self.assertEqual(forms.hidden(fm_mem, raw_full, {}, m),
                         forms.hidden(fm_mem, {"mode": "full", "provider": "anthropic", "embeddings": "fireworks"}, {}, m))
        # quote é visível porque mode == "full" (mesmo com espaços) → missing exige quote
        self.assertTrue(forms.missing("memory.mode", raw_full, {}, m, surface="tui"))

        raw_none = {"mode": " none "}
        self.assertEqual(forms.missing("memory.mode", raw_none, {}, m, surface="tui"), "")
        self.assertEqual(forms.build("memory.mode", raw_none, {}, m, surface="tui"),
                         [["memory", "setup", "--mode", "none"]])

        # Com quote preenchido, nenhum campo validado some do comando
        raw_full_ok = {**raw_full, "quote": "ok"}
        self.assertEqual(forms.missing("memory.mode", raw_full_ok, {}, m, surface="tui"), "")
        cmd = forms.build("memory.mode", raw_full_ok, {}, m, surface="tui")[0]
        self.assertIn("--provider", cmd)
        self.assertIn("anthropic", cmd)
        self.assertIn("--approval", cmd)


class FormNumberValidationTest(unittest.TestCase):
    def test_int_rejects_unicode_digits(self):
        self.assertEqual(forms.check("int:1:5", "5", {}, {}, {}), "")
        for bad in ("²", "٣", "१२"):
            msg = forms.check("int:1:5", bad, {}, {}, {})
            self.assertEqual(msg, "Use um inteiro de 1 a 5.")
            msg2 = forms.check("int:1:", bad, {}, {}, {})
            self.assertEqual(msg2, "Use um inteiro a partir de 1.")
        # Dica de impacto com hours_saved e entregável curto não estouram ValueError em "²"
        self.assertIsInstance(forms.hint("ice_impact", "²", {}, {"item": {"hours_saved": 10}}, {}), str)
        self.assertEqual(forms._deliv_full("²", "PROJ-1"), "²")

    def test_comma_number_rules(self):
        for ok in ("12,5", "0,25", "12.5", "3"):
            self.assertEqual(forms.check("num", ok, {}, {}, {}), "", f"falhou em {ok!r}")
        for thousands in ("1,000", "1.000,5", "1,000.5"):
            self.assertEqual(
                forms.check("num", thousands, {}, {}, {}),
                "Use ponto decimal ou vírgula só para decimais (sem separador de milhar).",
                f"milhar {thousands!r}",
            )
        for bad in ("0", "0,0", "-1", "abc", "٣"):
            self.assertEqual(forms.check("num", bad, {}, {}, {}), "Use um número maior que zero.", f"bad {bad!r}")

        self.assertEqual(forms.XF["num"]("12,5", {}, {}, {}), "12.5")
        self.assertEqual(forms.XF["num"]("1,000", {}, {}, {}), "1,000")
        self.assertEqual(forms._num("1,000"), "1,000")


class ActionNewNoForceTest(unittest.TestCase):
    def test_action_new_omits_force_by_default(self):
        cmds = forms.build("action.new", {"title": "Revisar proposta da Padaria Pão Quente"}, {}, {})
        self.assertNotIn("--force", cmds[0])
        self.assertEqual(cmds[0][-2:], ["--by", "owner"])

    @unittest.skipUnless(shutil.which("node"), "node ausente no ambiente")
    def test_panel_extra_js_handles_duplicate_refusal_and_forces(self):
        dash_html = ROOT / "brainlib" / "assets" / "dashboard.html"
        html_text = dash_html.read_text(encoding="utf-8")

        spec = importlib.util.spec_from_file_location("build_assets", ROOT / "scripts" / "build_assets.py")
        assert spec and spec.loader
        build_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_mod)
        self.assertEqual(html_text, build_mod.assemble(False, "Brain"), "dashboard.html em drift com src/")

        with tempfile.TemporaryDirectory() as td:
            inst_dir = Path(td) / "demo"
            with contextlib.redirect_stdout(io.StringIO()):
                demo_cli(argparse.Namespace(dir=str(inst_dir), open=False))
            b = Brain(config.load(inst_dir))
            m = render.view_model(b)

            compiled_js = html_text.split("<script>", 1)[1].rsplit("</script>", 1)[0]
            runner = r"""
const fs = require("fs");
const payload = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const compiled = fs.readFileSync(process.argv[3], "utf8");

function makeNode(tag) {
  const attrs = {};
  const cls = new Set();
  const evs = {};
  let _html = "";
  const el = {
    id: "",
    tagName: (tag || "DIV").toUpperCase(),
    textContent: "",
    value: "",
    hidden: false,
    disabled: false,
    type: "",
    style: {},
    dataset: {},
    children: [],
    _attrs: attrs,
    _evs: evs,
    onclick: null,
    get className() { return [...cls].join(" "); },
    set className(v) { cls.clear(); String(v || "").split(/\s+/).filter(Boolean).forEach(x => cls.add(x)); },
    classList: {
      add(...xs) { xs.forEach(x => cls.add(x)); },
      remove(...xs) { xs.forEach(x => cls.delete(x)); },
      toggle(x, f) { const on = f === undefined ? !cls.has(x) : !!f; if (on) cls.add(x); else cls.delete(x); return on; },
      contains(x) { return cls.has(x); },
    },
    addEventListener(ev, fn, cap) { (evs[ev] = evs[ev] || []).push({fn, cap: !!cap}); },
    removeEventListener(ev, fn) { if (evs[ev]) evs[ev] = evs[ev].filter(x => x.fn !== fn); },
    dispatch(ev, arg) {
      const a = arg || {target: el, preventDefault(){}, stopPropagation(){}};
      (evs[ev] || []).forEach(({fn}) => fn(a));
      if (ev === "click" && el.onclick) el.onclick(a);
    },
    appendChild(c) { c.parentNode = el; el.children.push(c); return c; },
    prepend(c) { c.parentNode = el; el.children.unshift(c); return c; },
    remove() { el.removed = true; if (el.parentNode) el.parentNode.children = el.parentNode.children.filter(x => x !== el); },
    setAttribute(k, v) { attrs[k] = String(v); if (k.startsWith("data-")) { const dk = k.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase()); el.dataset[dk] = String(v); } },
    getAttribute(k) { return k in attrs ? attrs[k] : null; },
    hasAttribute(k) { return k in attrs; },
    focus() {},
    select() {},
    closest() { return null; },
    querySelector(sel) { return el.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) {
      const res = [];
      const walk = node => {
        for (const ch of (node.children || [])) {
          if (matches(ch, sel)) res.push(ch);
          walk(ch);
        }
      };
      walk(el);
      return res;
    },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return _html; },
    set(v) {
      _html = String(v);
      el.children = [];
      // parser mínimo para o template de openForm: cria nós para data-k, data-dup-box, data-err, data-preview, data-ok, data-x, data-row, data-hint, data-sug
      const reTag = /<(input|select|textarea|button|div|p|span|option)\b([^>]*)>/gi;
      let mm;
      let curSelect = null;
      while ((mm = reTag.exec(_html))) {
        const tagName = mm[1].toUpperCase();
        const attrStr = mm[2];
        if (tagName === "OPTION") {
          if (curSelect) {
            const vm = /\bvalue="([^"]*)"/.exec(attrStr);
            const val = vm ? vm[1] : "";
            if (!curSelect._hasOpt || /\bselected\b/.test(attrStr)) {
              curSelect.value = val;
              curSelect._hasOpt = true;
            }
          }
          continue;
        }
        const child = makeNode(tagName);
        if (tagName === "SELECT") curSelect = child;
        const reAttr = /([\w-]+)(?:="([^"]*)")?/g;
        let am;
        while ((am = reAttr.exec(attrStr))) {
          const k = am[1], av = am[2] !== undefined ? am[2] : "";
          child.setAttribute(k, av);
          if (k === "value") child.value = av;
          if (k === "hidden") child.hidden = true;
          if (k === "class") av.split(/\s+/).filter(Boolean).forEach(c => child.classList.add(c));
        }
        el.appendChild(child);
      }
    },
  });
  return el;
}

function matches(node, sel) {
  return sel.split(",").map(s => s.trim()).some(part => {
    if (/^[a-z]+$/i.test(part)) return node.tagName === part.toUpperCase();
    const m = part.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
    if (m) {
      if (!(m[1] in node._attrs)) return false;
      return m[2] === undefined ? true : node._attrs[m[1]] === m[2];
    }
    return false;
  });
}

function runScenario(responses) {
  const els = new Map();
  const docListeners = new Map();
  const body = makeNode("BODY");
  const getOrMake = id => { if (!els.has(id)) { const n = makeNode("DIV"); n.id = id; els.set(id, n); } return els.get(id); };
  getOrMake("data").textContent = JSON.stringify(payload);

  const doc = {
    getElementById(id) {
      if (id === "kbar" || id === "lfbar") return els.get(id) || null;
      return getOrMake(id);
    },
    querySelector(sel) {
      if (sel === ".pal-back.open") return body.children.find(c => c.classList.contains("pal-back") && c.classList.contains("open")) || null;
      if (sel === ".dd.open") return null;
      if (sel.startsWith("#")) return getOrMake(sel.slice(1));
      return makeNode("DIV");
    },
    querySelectorAll() { return []; },
    addEventListener(ev, fn, cap) { (docListeners.get(ev) || docListeners.set(ev, []).get(ev)).push({fn, cap: !!cap}); },
    removeEventListener() {},
    createElement(tag) { return makeNode(tag); },
    body,
    documentElement: { dataset: {} },
    activeElement: { tagName: "BODY" },
  };
  const win = {
    location: { protocol: "http:", hostname: "127.0.0.1", pathname: "/", search: "", hash: "#todo&t=tok-demo", href: "http://127.0.0.1/#todo&t=tok-demo", reload(){} },
    localStorage: { _m: {}, getItem(k){ return this._m[k] || null; }, setItem(k, v){ this._m[k] = String(v); }, removeItem(k){ delete this._m[k]; } },
    sessionStorage: { _m: {}, getItem(k){ return this._m[k] || null; }, setItem(k, v){ this._m[k] = String(v); }, removeItem(k){ delete this._m[k]; } },
    history: { replaceState(){} },
    matchMedia: () => ({ matches: false }),
    scrollTo() {},
    addEventListener() {},
    setTimeout(fn) { return 1; },
    clearTimeout() {},
  };
  const cmdCalls = [];
  let dataCalls = 0;
  const queue = responses.slice();
  const fetch = async (url, opts) => {
    if (url === "/api/cmd") {
      const bodyObj = JSON.parse(opts.body);
      cmdCalls.push(bodyObj.cmd);
      const resp = queue.shift() || {ok: true, rc: 0, out: [], err: ""};
      return { status: 200, ok: true, json: async () => resp };
    }
    if (url === "/api/data") {
      dataCalls++;
      return { status: 200, ok: true, json: async () => ({ok: true, model: payload}) };
    }
    return { status: 404, ok: false, json: async () => ({}) };
  };

  const fn = new Function(
    "window", "document", "location", "localStorage", "sessionStorage",
    "history", "matchMedia", "navigator", "setTimeout", "clearTimeout", "fetch",
    compiled + "\nreturn window.BRAIN;"
  );
  fn(win, doc, win.location, win.localStorage, win.sessionStorage, win.history, win.matchMedia, {platform: "Linux", userAgent: "Linux"}, win.setTimeout, win.clearTimeout, fetch);

  const openModal = () => {
    (docListeners.get("keydown") || []).forEach(({fn: h}) => h({key: "n", target: {tagName: "BODY"}, preventDefault(){}, stopPropagation(){}}));
    return body.children.find(c => c.classList.contains("pal-back"));
  };
  return {openModal, cmdCalls, getDataCalls: () => dataCalls, body};
}

(async () => {
  // 1) Recusa de duplicata abre caixa segura e "Criar mesmo assim" reenvia com --force
  const dupErr = "ERRO: possível ação duplicada — nada gravado:\n  TASK-0001 (aberta) · Fechar contrato com a Padaria Pão Quente · 1.00 · mesmo título · <img onerror=alert(1)>\nse for a mesma: não crie; acrescente à existente (`brain action update ID --note … --people …`)\nse for outra: repita com --force (CLI) ou data.not_dup = [ids] (brain add)";
  const s1 = runScenario([
    {ok: false, rc: 2, out: [], err: dupErr},
    {ok: true, rc: 0, out: ["✓ TASK-0002 · aberta · Fechar contrato com a Padaria Pão Quente"], err: ""},
  ]);
  const ov1 = s1.openModal();
  const title1 = ov1.querySelector('[data-k="title"]');
  title1.value = "Fechar contrato com a Padaria Pão Quente";
  title1.dispatch("input");
  ov1.querySelector("[data-ok]").dispatch("click");
  await new Promise(r => setTimeout(r, 10));
  const dupBox1 = ov1.querySelector("[data-dup-box]");
  const forceBtn1 = dupBox1.querySelector('[data-force-submit="1"]');
  const afterFirst = {
    cmd0: s1.cmdCalls[0],
    modalStillOpen: !ov1.removed,
    titlePreserved: title1.value,
    dupHidden: dupBox1.hidden,
    dupTexts: [dupBox1.children[0].textContent, ...dupBox1.children[1].children.map(li => li.textContent)],
    dupInnerHtml: dupBox1.innerHTML,
    forceBtnText: forceBtn1 ? forceBtn1.textContent : "",
  };
  forceBtn1.dispatch("click");
  await new Promise(r => setTimeout(r, 10));
  const afterForce = {
    cmd1: s1.cmdCalls[1],
    modalClosed: !!ov1.removed,
    dataRefreshed: s1.getDataCalls(),
  };

  // 2) Editar qualquer campo após recusa limpa a caixa de duplicata e envia sem --force
  const s2 = runScenario([
    {ok: false, rc: 2, out: [], err: dupErr},
    {ok: true, rc: 0, out: ["✓ TASK-0003 · aberta · Novo título revisado"], err: ""},
  ]);
  const ov2 = s2.openModal();
  const title2 = ov2.querySelector('[data-k="title"]');
  title2.value = "Fechar contrato com a Padaria Pão Quente";
  title2.dispatch("input");
  ov2.querySelector("[data-ok]").dispatch("click");
  await new Promise(r => setTimeout(r, 10));
  const dupBox2 = ov2.querySelector("[data-dup-box]");
  const boxVisibleBeforeEdit = !dupBox2.hidden;
  title2.value = "Novo título revisado";
  title2.dispatch("input");
  const boxHiddenAfterEdit = dupBox2.hidden;
  ov2.querySelector("[data-ok]").dispatch("click");
  await new Promise(r => setTimeout(r, 10));
  const editFlow = {boxVisibleBeforeEdit, boxHiddenAfterEdit, cmd1: s2.cmdCalls[1], modalClosed: !!ov2.removed};

  // 2b) Evento "change" em outro campo também limpa a caixa de duplicata
  const s2b = runScenario([
    {ok: false, rc: 2, out: [], err: dupErr},
    {ok: true, rc: 0, out: ["✓ TASK-0004 · aberta · Com prazo"], err: ""},
  ]);
  const ov2b = s2b.openModal();
  ov2b.querySelector('[data-k="title"]').value = "Fechar contrato com a Padaria Pão Quente";
  ov2b.querySelector("[data-ok]").dispatch("click");
  await new Promise(r => setTimeout(r, 10));
  const dupBox2b = ov2b.querySelector("[data-dup-box]");
  const visibleBeforeChange = !dupBox2b.hidden;
  ov2b.querySelector('[data-k="due"]').value = "sex";
  ov2b.querySelector('[data-k="due"]').dispatch("change");
  const hiddenAfterChange = dupBox2b.hidden;

  // 3) Caso negativo A3 #1: outro erro que não é duplicata NÃO abre a caixa
  const s3 = runScenario([{ok: false, rc: 4, out: [], err: "due_none_reason: informe o motivo"}]);
  const ov3 = s3.openModal();
  ov3.querySelector('[data-k="title"]').value = "Ação sem prazo";
  ov3.querySelector("[data-ok]").dispatch("click");
  await new Promise(r => setTimeout(r, 10));
  const negErr = {dupHidden: ov3.querySelector("[data-dup-box]").hidden, modalClosed: !!ov3.removed};

  // 4) Caso negativo A3 #2: ok=true com aviso "↳ parecidas" no stderr NÃO abre a caixa
  const s4 = runScenario([{ok: true, rc: 0, out: ["✓ TASK-0002 · aberta"], err: "↳ parecidas (confira se não é a mesma): TASK-0001 … (0.71)"}]);
  const ov4 = s4.openModal();
  ov4.querySelector('[data-k="title"]').value = "Ação parecida mas permitida";
  ov4.querySelector("[data-ok]").dispatch("click");
  await new Promise(r => setTimeout(r, 10));
  const negWarn = {dupHidden: ov4.querySelector("[data-dup-box]").hidden, modalClosed: !!ov4.removed};

  console.log(JSON.stringify({afterFirst, afterForce, editFlow, changeFlow: {visibleBeforeChange, hiddenAfterChange}, negErr, negWarn}));
})();
"""
            p_data = Path(td) / "model.json"
            p_js = Path(td) / "compiled.js"
            p_run = Path(td) / "run.js"
            p_data.write_text(json.dumps(m, default=str), encoding="utf-8")
            p_js.write_text(compiled_js, encoding="utf-8")
            p_run.write_text(runner, encoding="utf-8")

            proc = subprocess.run([shutil.which("node"), str(p_run), str(p_data), str(p_js)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"Node falhou:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
            res = json.loads(proc.stdout)

        af = res["afterFirst"]
        self.assertNotIn("--force", af["cmd0"])
        self.assertTrue(af["modalStillOpen"])
        self.assertEqual(af["titlePreserved"], "Fechar contrato com a Padaria Pão Quente")
        self.assertFalse(af["dupHidden"])
        self.assertEqual(af["dupTexts"][0], "Possível duplicata")
        self.assertIn("TASK-0001", af["dupTexts"][1])
        self.assertEqual(af["dupInnerHtml"], "")
        self.assertEqual(af["forceBtnText"], "Criar mesmo assim")

        aforce = res["afterForce"]
        self.assertEqual(aforce["cmd1"], af["cmd0"] + " --force")
        self.assertEqual(aforce["cmd1"].count("--force"), 1)
        self.assertTrue(aforce["modalClosed"])
        self.assertGreaterEqual(aforce["dataRefreshed"], 1)

        ef = res["editFlow"]
        self.assertTrue(ef["boxVisibleBeforeEdit"])
        self.assertTrue(ef["boxHiddenAfterEdit"])
        self.assertNotIn("--force", ef["cmd1"])
        self.assertTrue(ef["modalClosed"])

        self.assertTrue(res["changeFlow"]["visibleBeforeChange"])
        self.assertTrue(res["changeFlow"]["hiddenAfterChange"])

        self.assertTrue(res["negErr"]["dupHidden"])
        self.assertTrue(res["negErr"]["modalClosed"])
        self.assertTrue(res["negWarn"]["dupHidden"])
        self.assertTrue(res["negWarn"]["modalClosed"])


if __name__ == "__main__":
    unittest.main()
