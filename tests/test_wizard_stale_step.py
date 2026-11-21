"""Wizard (modo primeira vez): continuação async de um passo não pode pintar em DOM de outro passo.

Defeito real (relato do dono, 2026-11-21): a varredura automática de conectores
(OBV.conectores → scan) terminava DEPOIS de o dono avançar para o passo de
planejamento — drawConns() caía num #conns que não existe mais e o catch do scan
pintava o erro vermelho no #m do passo ATUAL, lido como "criar entregável quebrou".

O teste avalia o extra.js real num stub de DOM onde ids de views substituídas
resolvem para null (a semântica do browser para innerHTML trocado) e dirige o
fluxo: entra no wizard em "conectores", navega para "planejamento" com o job da
varredura ainda rodando, e só então conclui o job.

- cenário "stale": nenhum crash, nenhum erro pintado no #m do planejamento.
- cenário "happy": a varredura que termina com o dono ainda no passo continua
  pintando #conns com o status pós-scan (o guard não mata o caminho bom).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRA = ROOT / "brainlib" / "assets" / "src" / "extra.js"

# Nota de segurança: o runner abaixo usa `new Function` + `innerHTML` no stub de
# DOM — o mesmo padrão do harness da casa (tests/test_panel_js_fixes.py). O único
# código avaliado é o extra.js DO REPO (caminho fixo, lido do disco), nunca input
# de usuário; o innerHTML do stub é uma string em memória, sem parser de HTML.

RUNNER = r"""
"use strict";
const fs = require("fs");
const SRC = fs.readFileSync(process.argv[2], "utf8");
const STEPS = process.argv[3].split(",");

let jobDone = false;
const state = () => ({
  claude_installed: true,
  connectors: [{key: "slack", label: "Slack", what: "leitura de canais",
                status: jobDone ? "connected" : "missing", enabled: false}],
  connectors_scanned: jobDone,
  connectors_source: "claude",
  connectors_hint: "",
  sources: [],
  watch_kinds: [["slack", "Slack"]],
  planning: {proposal: null, goals: 0},
  agent: false,
  progress: {done: []},
});
function resp(j) { return {ok: true, status: 200, json: async () => j}; }
async function fetchStub(path) {
  const u = String(path);
  if (u === "/api/onboard/state") return resp({ok: true, state: state()});
  if (u === "/api/onboard/connectors_scan") return resp({ok: true, job: "job-1"});
  if (u === "/api/onboard/job/job-1")
    return resp({ok: true, job: jobDone
      ? {status: "done", result: {source: "claude", hint: ""}}
      : {status: "running", log: ["procurando conectores…"]}});
  return resp({ok: true});
}

function makeWorld() {
  const els = new Map();
  let viewIds = new Set();
  const deadIds = new Set();
  const timers = [];

  function classList(el) {
    const set = new Set();
    const sync = () => { el.className = Array.from(set).join(" "); };
    return {
      add(...xs) { xs.forEach(x => set.add(x)); sync(); },
      remove(...xs) { xs.forEach(x => set.delete(x)); sync(); },
      toggle(x, f) { const on = f === undefined ? !set.has(x) : !!f; if (on) set.add(x); else set.delete(x); sync(); return on; },
      contains(x) { return set.has(x); },
    };
  }
  function makeEl(id, tag) {
    const el = {
      tagName: (tag || "DIV").toUpperCase(),
      innerHTML: "", textContent: "", value: "", hidden: false, disabled: false,
      checked: false, style: {}, dataset: {}, children: [], className: "",
      addEventListener() {}, removeEventListener() {},
      querySelector() { return makeEl("", "SPAN"); }, querySelectorAll() { return []; },
      closest() { return makeEl("", "DIV"); },
      focus() {}, select() {}, remove() {}, appendChild(c) { return c; }, insertBefore(n) { return n; },
      setAttribute() {}, hasAttribute() { return false; },
      onclick: null, onchange: null, isConnected: true,
    };
    let _id = id || "";
    Object.defineProperty(el, "id", {get: () => _id, set: v => { _id = v; if (v) els.set(v, el); }});
    el.classList = classList(el);
    if (id) els.set(id, el);
    return el;
  }

  // #view é o coração do stub: trocar innerHTML destrói os ids do passo anterior
  // (passam a resolver null, como no browser) e publica os ids do passo novo.
  const view = makeEl("view", "DIV");
  let viewHtml = "";
  Object.defineProperty(view, "innerHTML", {
    get: () => viewHtml,
    set: h => {
      viewHtml = String(h);
      for (const old of viewIds) { deadIds.add(old); els.delete(old); }
      viewIds = new Set(Array.from(viewHtml.matchAll(/id="([^"]+)"/g), m => m[1]));
    },
  });

  function resolveEl(id) {
    if (id === "view") return view;
    if (els.has(id)) return els.get(id);
    if (viewIds.has(id)) return makeEl(id, "DIV");
    if (deadIds.has(id)) return null;          // id de um passo substituído: não existe mais
    return makeEl(id, "DIV");                  // shell/criação preguiçosa (kbar, side, …)
  }

  const stepLis = STEPS.map(k => ({dataset: {k}, onclick: null, className: ""}));

  const PAYLOAD = JSON.stringify({owner: {name: "Dona Demo", id: "eu"}, today: "2026-11-21"});

  const doc = {
    getElementById: id => (id === "data" ? {textContent: PAYLOAD} : resolveEl(id)),
    querySelector(sel) { return sel[0] === "#" ? resolveEl(sel.slice(1)) : makeEl("", "DIV"); },
    querySelectorAll(sel) { return sel === "#ob-steps li" ? stepLis : []; },
    createElement: tag => makeEl("", tag),
    addEventListener() {}, removeEventListener() {},
    body: makeEl("", "BODY"),
    documentElement: {dataset: {}},
    activeElement: null,
  };
  const win = {
    location: {protocol: "http:", hostname: "127.0.0.1", hash: "#t=tok1", pathname: "/", search: "",
               href: "http://127.0.0.1:8787/#t=tok1"},
    localStorage: {_m: {"brain-onboarding-step": "conectores"},
                   getItem(k) { return k in this._m ? this._m[k] : null; },
                   setItem(k, v) { this._m[k] = String(v); }},
    sessionStorage: {_m: {}, getItem() { return null; }, setItem() {}, removeItem() {}},
    history: {replaceState() {}},
    matchMedia: () => ({matches: false}),
    scrollTo() {},
    addEventListener() {}, removeEventListener() {},
    setTimeout(fn) { timers.push(fn); return timers.length; },
    clearTimeout() {},
  };

  new Function(
    "window", "document", "location", "localStorage", "sessionStorage", "history",
    "matchMedia", "navigator", "setTimeout", "clearTimeout", "fetch",
    SRC + "\n"
  )(win, doc, win.location, win.localStorage, win.sessionStorage, win.history,
    win.matchMedia, {platform: "MacIntel", userAgent: "node"},
    win.setTimeout, win.clearTimeout, fetchStub);

  const settle = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
  const flushTimers = () => { let guard = 0; while (timers.length && guard++ < 200) timers.shift()(); };
  return {win, doc, els, stepLis, settle, flushTimers};
}

async function staleScenario() {
  jobDone = false;
  const w = makeWorld();
  try {
    await w.win.enterOnboarding();
    await w.settle();                                  // varredura auto: poll 1 (running) → dorme num timer
    const connsEl = w.doc.querySelector("#conns");
    const before = connsEl.innerHTML;
    const li = w.stepLis.find(l => l.dataset.k === "planejamento");
    li.onclick();                                      // dono avança ANTES do job terminar
    const mEl = w.doc.querySelector("#m");             // #m do passo ATUAL (planejamento)
    jobDone = true;
    w.flushTimers();                                   // o job conclui depois da navegação
    await w.settle(); await w.settle();
    return {crashed: null,
            mClass: mEl.className, mText: mEl.textContent,
            connsUntouched: connsEl.innerHTML === before};
  } catch (e) { return {crashed: String((e && e.stack) || e), mClass: "?", mText: "?", connsUntouched: false}; }
}

async function happyScenario() {
  jobDone = false;
  const w = makeWorld();
  try {
    await w.win.enterOnboarding();
    await w.settle();
    jobDone = true;                                    // dono continua em "conectores"
    w.flushTimers();
    await w.settle(); await w.settle();
    const connsEl = w.doc.querySelector("#conns");
    const mEl = w.doc.querySelector("#m");
    return {crashed: null,
            connsPainted: /class="conn"/.test(connsEl.innerHTML),
            saysConnected: connsEl.innerHTML.indexOf("Conectado") >= 0,
            mClass: mEl.className};
  } catch (e) { return {crashed: String((e && e.stack) || e), connsPainted: false, saysConnected: false, mClass: "?"}; }
}

(async () => {
  console.log("WIZTEST " + JSON.stringify({stale: await staleScenario(), happy: await happyScenario()}));
})().catch(e => { console.log("WIZTEST " + JSON.stringify({fatal: String((e && e.stack) || e)})); });
"""


def _wizard_steps() -> list[str]:
    src = EXTRA.read_text(encoding="utf-8")
    m = re.search(r"const OB_STEPS = \[(.*?)\];", src, re.S)
    if not m:
        raise AssertionError("literal OB_STEPS não encontrado em extra.js")
    return re.findall(r'\["([a-z]+)",', m.group(1))


class WizardStaleStepTests(unittest.TestCase):
    """A continuação async de um passo do wizard não pinta nem navega depois de trocar de passo."""

    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node ausente no ambiente")
        cls.steps = _wizard_steps()
        for needed in ("conectores", "planejamento"):
            if needed not in cls.steps:
                raise AssertionError(f"passo {needed!r} sumiu do OB_STEPS — revisar o teste")
        cls.td = tempfile.TemporaryDirectory()
        runner = Path(cls.td.name) / "runner.js"
        runner.write_text(RUNNER, encoding="utf-8")
        out = subprocess.run([node, str(runner), str(EXTRA), ",".join(cls.steps)],
                             capture_output=True, text=True, timeout=120)
        line = next((l for l in out.stdout.splitlines() if l.startswith("WIZTEST ")), None)
        if line is None:
            raise AssertionError(f"runner não respondeu\nstdout:\n{out.stdout}\nstderr:\n{out.stderr}")
        cls.result = json.loads(line[len("WIZTEST "):])

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_runner_sem_fatal(self):
        self.assertNotIn("fatal", self.result)

    def test_scan_que_termina_depois_de_avancar_nao_crasha_nem_pinta_erro(self):
        r = self.result["stale"]
        self.assertIsNone(r["crashed"], f"continuação do scan explodiu: {r['crashed']}")
        self.assertNotIn("err", (r["mClass"] or "").split(), "erro pintado no #m do planejamento")
        self.assertEqual(r["mText"], "", "mensagem de outro passo vazou para o planejamento")
        self.assertTrue(r["connsUntouched"], "repintura em DOM de passo morto")

    def test_scan_que_termina_no_passo_continua_pintando(self):
        r = self.result["happy"]
        self.assertIsNone(r["crashed"], f"happy path quebrou: {r['crashed']}")
        self.assertTrue(r["connsPainted"], "#conns não pintou após o scan")
        self.assertTrue(r["saysConnected"], "status pós-scan não chegou ao #conns")
        self.assertNotIn("err", (r["mClass"] or "").split())


if __name__ == "__main__":
    unittest.main()
