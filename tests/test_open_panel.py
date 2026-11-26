"""Regressão #164 e #114:
- #164: ao sair do onboarding com sucesso (exitOnboarding), a hash vira #home via replaceState ANTES do
  BRAIN.refresh, evitando que route() reentre em enterOnboarding() no último passo.
- #114: #t= só é aceito em consumeBootToken (carregamento completo); hashchange com t= não guarda token nem
  recarrega e apenas remove t= do fragmento; focus_open_tab força recarga via query ?n=<nonce>; serve aceita GET /?n=…
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, demo as demo_mod, serve, util  # noqa: E402


def _assemble_dashboard_html() -> str:
    spec = importlib.util.spec_from_file_location("build_assets", ROOT / "scripts" / "build_assets.py")
    build_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_mod)
    return build_mod.assemble(False, "Brain")


NODE_RUNNER = r"""
"use strict";
const fs = require("fs");
const vm = require("vm");

const mode = process.argv[2];
const html = fs.readFileSync(process.argv[3], "utf8");

function extractBundle(text) {
  const marker = '<script id="data" type="application/json">';
  const idx = text.indexOf(marker);
  const after = text.indexOf("</script>", idx) + "</script>".length;
  const s = text.indexOf("<script>", after) + "<script>".length;
  const e = text.lastIndexOf("</script>");
  return text.slice(s, e);
}

function makeStorage(init) {
  const m = new Map(Object.entries(init || {}));
  return {
    getItem(k) { return m.has(k) ? m.get(k) : null; },
    setItem(k, v) { m.set(String(k), String(v)); },
    removeItem(k) { m.delete(k); },
  };
}

function makeEl(id, els) {
  const cls = new Set();
  const children = [];
  const el = {
    id: id || "",
    tagName: "DIV",
    innerHTML: "",
    textContent: "",
    value: "",
    title: "",
    hidden: false,
    disabled: false,
    dataset: {},
    style: {},
    firstChild: null,
    classList: {
      add(...xs) { xs.forEach(x => cls.add(x)); },
      remove(...xs) { xs.forEach(x => cls.delete(x)); },
      toggle(x, f) { const on = f === undefined ? !cls.has(x) : !!f; if (on) cls.add(x); else cls.delete(x); return on; },
      contains(x) { return cls.has(x); },
    },
    addEventListener() {},
    removeEventListener() {},
    querySelector(sel) {
      if (sel && sel.startsWith("#")) return els.get(sel.slice(1)) || null;
      return makeEl("", els);
    },
    querySelectorAll() { return []; },
    closest() { return null; },
    appendChild(c) { children.push(c); return c; },
    insertBefore(n) { children.unshift(n); if (n && n.id) els.set(n.id, n); return n; },
    prepend() {},
    setAttribute() {},
    remove() { if (el.id) els.delete(el.id); },
    focus() {},
    select() {},
    scrollTop: 0,
    scrollHeight: 0,
  };
  if (id) els.set(id, el);
  return el;
}

function bootPanel(opts) {
  const els = new Map();
  for (const id of [
    "data", "ownername", "avatar", "view", "tabs", "faces", "side", "openpal",
    "theme", "verbadge", "freshbadge", "clidot", "conmode", "conout", "conx",
    "console", "conbadge", "toast", "palback", "palq", "pallist", "palconfirm",
    "palcmd", "palnote", "palcancel", "palrun", "burger", "newsback", "newslist",
    "newstitle", "newsmeta", "newshow", "newsact", "newslog", "newsfb", "newsclose",
    "q",
  ]) {
    makeEl(id, els);
  }
  els.get("data").textContent = JSON.stringify(opts.embeddedData || {});
  const localStorage = makeStorage(opts.localInit || {});
  const sessionStorage = makeStorage(opts.sessionInit || {});
  const winListeners = {};
  const replaceCalls = [];
  let hashChangeCount = 0;
  let currentHash = opts.hash || "";

  const loc = {
    protocol: "http:",
    hostname: "127.0.0.1",
    pathname: "/",
    search: opts.search || "",
    get hash() { return currentHash; },
    set hash(v) {
      const next = String(v).startsWith("#") ? String(v) : ("#" + v);
      const oldURL = "http://127.0.0.1:8787" + loc.pathname + loc.search + currentHash;
      currentHash = next;
      hashChangeCount += 1;
      for (const fn of (winListeners.hashchange || [])) {
        fn({ oldURL, newURL: "http://127.0.0.1:8787" + loc.pathname + loc.search + currentHash });
      }
    },
    reloadCalled: false,
    reload() { loc.reloadCalled = true; },
  };
  const history = {
    replaceState(_st, _t, url) {
      replaceCalls.push(url);
      const i = url.indexOf("#");
      currentHash = i >= 0 ? url.slice(i) : "";
    },
  };
  const doc = {
    documentElement: { dataset: {} },
    body: makeEl("body", els),
    activeElement: { tagName: "BODY" },
    getElementById(id) { return els.get(id) || null; },
    querySelector(sel) {
      if (sel.startsWith("#")) return els.get(sel.slice(1)) || null;
      return null;
    },
    querySelectorAll() { return []; },
    createElement(tag) { const el = makeEl("", els); el.tagName = tag.toUpperCase(); return el; },
    addEventListener() {},
  };

  const sandbox = {
    console,
    Date,
    setTimeout(fn) { return 1; },
    clearTimeout() {},
    matchMedia() { return { matches: false }; },
    navigator: { platform: "MacIntel", userAgent: "Node" },
    location: loc,
    history,
    localStorage,
    sessionStorage,
    document: doc,
    fetch: opts.fetchImpl,
    encodeURIComponent,
    decodeURIComponent,
    URLSearchParams,
    CustomEvent: function(t, d) { this.type = t; this.detail = d && d.detail; },
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = (ev, fn) => {
    (winListeners[ev] = winListeners[ev] || []).push(fn);
  };
  sandbox.window.scrollTo = () => {};
  vm.createContext(sandbox);
  vm.runInContext(extractBundle(html), sandbox);

  const settle = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
  return {
    sandbox, els, doc, loc, sessionStorage, replaceCalls, winListeners, settle,
    getHashChangeCount: () => hashChangeCount,
    fireHashChange(newHash, oldHash) {
      currentHash = newHash;
      hashChangeCount += 1;
      for (const fn of (winListeners.hashchange || [])) {
        fn({
          oldURL: "http://127.0.0.1:8787" + loc.pathname + loc.search + (oldHash || ""),
          newURL: "http://127.0.0.1:8787" + loc.pathname + loc.search + newHash,
        });
      }
    },
  };
}

function demoModel(onboardingNeeded) {
  return {
    owner: { id: "eu", name: "Dona Demo" },
    today: "2026-11-24",
    onboarding: { needed: !!onboardingNeeded },
    counts: { mine_open: 0 },
    agenda: [],
    actions: [],
    decisions: [],
    projects: [],
    goals: [],
    people: [],
    portfolio: { areas: [], processes: [], opportunities: [], gaps: [] },
  };
}

function onboardState() {
  return {
    owner: { id: "eu", name: "Dona Demo" },
    routine: {},
    profile: {},
    setup: {},
    connectors: [],
    watch_kinds: [],
    sources: [],
    memory: { mode: "none" },
    keys: {},
    agents: [],
    maquina: {},
    planning: { goals: 0 },
    progress: { done: [] },
    inbox: 0,
  };
}

(async () => {
  if (mode === "exit-onboarding-success") {
    const env = bootPanel({
      hash: "#onboarding&t=tok-ob-1",
      fetchImpl: async (url) => {
        if (url === "/api/data") return { ok: true, status: 200, json: async () => ({ ok: true, model: demoModel(true) }) };
        if (url === "/api/onboard/state") return { ok: true, status: 200, json: async () => ({ ok: true, state: onboardState() }) };
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      },
    });
    await env.settle();
    if (!env.doc.body.classList.contains("obmode")) throw new Error("não entrou em obmode no boot");
    if (env.loc.hash !== "#onboarding") throw new Error("hash inicial inesperada: " + env.loc.hash);

    let hashDuringRefresh = null;
    let obmodeDuringRefresh = null;
    let enterCallsAfterExit = 0;
    const origEnter = env.sandbox.enterOnboarding;
    env.sandbox.enterOnboarding = async function() {
      enterCallsAfterExit += 1;
      return origEnter.apply(this, arguments);
    };
    const origRefresh = env.sandbox.BRAIN.refresh;
    env.sandbox.BRAIN.refresh = function(m) {
      hashDuringRefresh = env.loc.hash;
      obmodeDuringRefresh = env.doc.body.classList.contains("obmode");
      return origRefresh.call(this, m);
    };
    const hcBefore = env.getHashChangeCount();

    await env.sandbox.exitOnboarding();
    await env.settle();

    if (hashDuringRefresh !== "#home") {
      throw new Error("refresh viu hash != #home: " + hashDuringRefresh);
    }
    if (obmodeDuringRefresh !== false) {
      throw new Error("obmode ainda estava ativo durante refresh");
    }
    if (env.getHashChangeCount() !== hcBefore) {
      throw new Error("exitOnboarding sucesso disparou hashchange via location.hash em vez de replaceState");
    }
    if (!env.sandbox.__obDone) throw new Error("__obDone não ficou true");
    if (enterCallsAfterExit !== 0) {
      throw new Error("enterOnboarding foi chamada novamente após sair: " + enterCallsAfterExit);
    }
    if (env.doc.body.classList.contains("obmode")) throw new Error("body ainda tem obmode");
    if (env.loc.hash !== "#home") throw new Error("hash final != #home: " + env.loc.hash);
    console.log("OK_EXIT_SUCCESS");
  } else if (mode === "exit-onboarding-failure") {
    let failData = false;
    const env = bootPanel({
      hash: "#onboarding&t=tok-ob-2",
      fetchImpl: async (url) => {
        if (url === "/api/data") {
          if (failData) throw new Error("ponte caiu");
          return { ok: true, status: 200, json: async () => ({ ok: true, model: demoModel(false) }) };
        }
        if (url === "/api/onboard/state") return { ok: true, status: 200, json: async () => ({ ok: true, state: onboardState() }) };
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      },
    });
    await env.settle();
    failData = true;
    const hcBefore = env.getHashChangeCount();
    await env.sandbox.exitOnboarding();
    await env.settle();
    if (env.doc.body.classList.contains("obmode")) throw new Error("obmode não saiu na falha");
    if (env.loc.hash !== "#home") throw new Error("falha não foi para #home: " + env.loc.hash);
    if (env.getHashChangeCount() !== hcBefore + 1) throw new Error("caminho de falha não usou location.hash");
    console.log("OK_EXIT_FAILURE");
  } else if (mode === "hashchange-ignores-token") {
    const env = bootPanel({
      hash: "#t=boot-tok-1",
      fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, model: demoModel(false) }) }),
    });
    await env.settle();
    env.fireHashChange("#t=rogue-tok-2", "#home");
    const rec1 = JSON.parse(env.sessionStorage.getItem("brain-serve-token"));
    if (rec1.tok !== "boot-tok-1") throw new Error("hashchange guardou token: " + rec1.tok);
    if (env.loc.reloadCalled) throw new Error("hashchange chamou location.reload");
    if (env.loc.hash !== "") throw new Error("hashchange não removeu #t=: " + env.loc.hash);

    env.fireHashChange("#tasks&t=rogue-tok-3", "#home");
    const rec2 = JSON.parse(env.sessionStorage.getItem("brain-serve-token"));
    if (rec2.tok !== "boot-tok-1") throw new Error("hashchange #tasks&t= guardou token: " + rec2.tok);
    if (env.loc.reloadCalled) throw new Error("hashchange #tasks&t= chamou reload");
    if (env.loc.hash !== "#tasks") throw new Error("hashchange #tasks&t= não manteve #tasks: " + env.loc.hash);

    // Full load com ?n=<nonce>#t=<token> deve consumir no boot
    const seenTokens = [];
    const envReload = bootPanel({
      search: "?n=deadbeef",
      hash: "#t=reused-tok-9",
      fetchImpl: async (_url, init) => {
        seenTokens.push((init && init.headers && init.headers["X-Brain-Token"]) || null);
        return { ok: true, status: 200, json: async () => ({ ok: true, model: demoModel(false) }) };
      },
    });
    await envReload.settle();
    const rec3 = JSON.parse(envReload.sessionStorage.getItem("brain-serve-token"));
    if (rec3.tok !== "reused-tok-9") throw new Error("boot com ?n=…#t= não guardou token: " + rec3.tok);
    if (envReload.loc.hash !== "") throw new Error("boot não limpou fragmento: " + envReload.loc.hash);
    if (!envReload.replaceCalls.includes("/?n=deadbeef")) {
      throw new Error("replaceState não preservou ?n=deadbeef: " + JSON.stringify(envReload.replaceCalls));
    }
    if (seenTokens[0] !== "reused-tok-9") throw new Error("fetch não usou token do boot: " + seenTokens[0]);
    console.log("OK_HASHCHANGE_TOKEN");
  }
})().catch(e => { console.error(e); process.exit(1); });
"""


class OpenPanelRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.dash_path = Path(cls.td.name) / "dashboard.html"
        cls.dash_path.write_text(_assemble_dashboard_html(), encoding="utf-8")
        cls.runner_path = Path(cls.td.name) / "runner.js"
        cls.runner_path.write_text(NODE_RUNNER, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def _run_node(self, mode: str) -> str:
        node = shutil.which("node")
        if not node:
            self.skipTest("node ausente no ambiente")
        proc = subprocess.run(
            [node, str(self.runner_path), mode, str(self.dash_path)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def test_exit_onboarding_success_replaces_hash_before_refresh_and_does_not_reenter(self):
        out = self._run_node("exit-onboarding-success")
        self.assertIn("OK_EXIT_SUCCESS", out)

    def test_exit_onboarding_failure_falls_back_to_home_hash(self):
        out = self._run_node("exit-onboarding-failure")
        self.assertIn("OK_EXIT_FAILURE", out)

    def test_hashchange_does_not_store_or_reload_and_boot_accepts_query_nonce(self):
        out = self._run_node("hashchange-ignores-token")
        self.assertIn("OK_HASHCHANGE_TOKEN", out)


class TabReuseNonceAndServeQueryTests(unittest.TestCase):
    def test_focus_open_tab_adds_changing_query_nonce_for_bridge_urls(self):
        calls: list[list[str]] = []

        def fake_run(argv, **kw):
            calls.append(argv)
            if argv[0].endswith("pgrep"):
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 0, "ok", "")

        with mock.patch.object(util.sys, "platform", "darwin"), \
                mock.patch.object(util, "_default_browser", return_value=("Safari", "safari")), \
                mock.patch("subprocess.run", fake_run):
            self.assertTrue(util.focus_open_tab("http://127.0.0.1:8787/#t=tok1"))
            self.assertTrue(util.focus_open_tab("http://127.0.0.1:8787/#t=tok1"))
            self.assertTrue(util.focus_open_tab("http://127.0.0.1:8787/#onboarding&t=tok1"))
            self.assertTrue(util.focus_open_tab("file:///tmp/dashboard.html#home"))

        osas = [c for c in calls if c[0].endswith("osascript")]
        self.assertEqual(len(osas), 4)
        self.assertEqual(osas[0][-2], "http://127.0.0.1:8787/")
        self.assertRegex(osas[0][-1], r"^http://127\.0\.0\.1:8787/\?n=[0-9a-f]+#t=tok1$")
        self.assertRegex(osas[1][-1], r"^http://127\.0\.0\.1:8787/\?n=[0-9a-f]+#t=tok1$")
        self.assertNotEqual(osas[0][-1], osas[1][-1])
        self.assertRegex(osas[2][-1], r"^http://127\.0\.0\.1:8787/\?n=[0-9a-f]+#onboarding&t=tok1$")
        self.assertEqual(osas[3][-1], "file:///tmp/dashboard.html#home")

    def test_focus_only_does_not_write_a_url(self):
        calls: list[list[str]] = []

        def fake_run(argv, **kw):
            calls.append(argv)
            if argv[0].endswith("pgrep"):
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 0, "ok", "")

        with mock.patch.object(util.sys, "platform", "darwin"), \
                mock.patch.object(util, "_default_browser", return_value=("Safari", "safari")), \
                mock.patch("subprocess.run", fake_run):
            self.assertTrue(util.focus_open_tab("http://127.0.0.1:8787/#t=tok1", focus_only=True))
        osa = next(c for c in calls if c[0].endswith("osascript"))
        self.assertIn('set brainMode to "focus"', osa[2])
        self.assertEqual(len([c for c in calls if c[0].endswith("osascript")]), 1)

    def test_keep_route_puts_the_page_before_the_new_token(self):
        calls: list[list[str]] = []

        def fake_run(argv, **kw):
            calls.append(argv)
            if argv[0].endswith("pgrep"):
                return subprocess.CompletedProcess(argv, 0, "", "")
            mode = "read" if 'set brainMode to "read"' in argv[2] else "set"
            out = "http://127.0.0.1:8787/#todo" if mode == "read" else "ok"
            return subprocess.CompletedProcess(argv, 0, out, "")

        with mock.patch.object(util.sys, "platform", "darwin"), \
                mock.patch.object(util, "_default_browser", return_value=("Safari", "safari")), \
                mock.patch("subprocess.run", fake_run):
            self.assertTrue(util.focus_open_tab("http://127.0.0.1:8787/#t=novo", keep_route=True))
        osas = [c for c in calls if c[0].endswith("osascript")]
        self.assertEqual(len(osas), 2)
        self.assertRegex(osas[1][-1], r"^http://127\.0\.0\.1:8787/\?n=[0-9a-f]+#todo&t=novo$")

    def test_page_hash_drops_the_token_and_keeps_the_route(self):
        self.assertEqual(util._page_hash("http://127.0.0.1:8787/#todo&t=velho"), "todo")
        self.assertEqual(util._page_hash("http://127.0.0.1:8787/#t=velho"), "")
        self.assertEqual(util._page_hash("http://127.0.0.1:8787/"), "")

    def test_serve_accepts_root_and_portfolio_with_query_nonce(self):
        with tempfile.TemporaryDirectory() as td:
            with contextlib.redirect_stdout(io.StringIO()):
                demo_mod.cli(argparse.Namespace(dir=str(Path(td) / "inst"), open=False))
            inst = config.load(Path(td) / "inst")
            serve._Handler.state = serve._State(inst, "tok-open-panel")
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
            httpd.daemon_threads = True
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                for path in ("/?n=deadbeef", "/portfolio.html?n=deadbeef"):
                    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
                    req.add_header("Host", "127.0.0.1")
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        self.assertEqual(resp.status, 200)
                        body = resp.read().decode("utf-8")
                        self.assertIn('<script id="data" type="application/json">{}</script>', body)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
