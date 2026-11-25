"""Segurança da ponte e shell HTML (#114, #115, #116, #117, #140):
- HTML servido pela ponte sem dados do vault (hidratação autenticada via /api/data e /api/portfolio)
- Token em sessionStorage com TTL de 12h, consumo único de #t= / &t= e limpeza em 401
- CSP em headers do serve e <meta> nos templates HTML
- Polling limitado e expiração 'stale' nos jobs de onboarding
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, demo as demo_mod, onboard, render, serve  # noqa: E402
from brainlib.core import Brain  # noqa: E402

ASSETS = ROOT / "brainlib" / "assets"
DASH_HTML = ASSETS / "dashboard.html"
PF_HTML = ASSETS / "portfolio.html"
OB_HTML = ASSETS / "onboarding.html"


def _demo_inst(td: str) -> config.Instance:
    with contextlib.redirect_stdout(io.StringIO()):
        demo_mod.cli(argparse.Namespace(dir=str(Path(td) / "inst"), open=False))
    return config.load(Path(td) / "inst")


def _extract_bundle_js(html_text: str) -> str:
    # Em dashboard.html e portfolio.html há dois <script>: #data JSON e o bundle único.
    marker = '<script id="data" type="application/json">'
    idx = html_text.index(marker)
    after_data = html_text.index("</script>", idx) + len("</script>")
    start = html_text.index("<script>", after_data) + len("<script>")
    end = html_text.rindex("</script>")
    return html_text[start:end]


def _extract_onboarding_js(html_text: str) -> str:
    start = html_text.rindex("<script>") + len("<script>")
    end = html_text.rindex("</script>")
    return html_text[start:end]


NODE_TOKEN_HARNESS = r"""
"use strict";
const fs = require("fs");
const vm = require("vm");

const mode = process.argv[2];
const htmlPath = process.argv[3];
const html = fs.readFileSync(htmlPath, "utf8");

function extractBundle(text, kind) {
  if (kind === "onboarding") {
    const s = text.lastIndexOf("<script>") + "<script>".length;
    const e = text.lastIndexOf("</script>");
    return text.slice(s, e);
  }
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
    _dump() { return Object.fromEntries(m.entries()); },
  };
}

function makeEl(id, els) {
  const cls = new Set();
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
    classList: {
      add(...xs) { xs.forEach(x => cls.add(x)); },
      remove(...xs) { xs.forEach(x => cls.delete(x)); },
      toggle(x, f) { const on = f === undefined ? !cls.has(x) : !!f; if (on) cls.add(x); else cls.delete(x); return on; },
      contains(x) { return cls.has(x); },
    },
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return makeEl("", els); },
    querySelectorAll() { return []; },
    closest() { return null; },
    appendChild(c) { return c; },
    insertBefore(n) { return n; },
    setAttribute() {},
    remove() {},
    focus() {},
    select() {},
    scrollTop: 0,
    scrollHeight: 0,
  };
  if (id) els.set(id, el);
  return el;
}

function runEnv(opts) {
  const srcHtml = opts.htmlPath ? fs.readFileSync(opts.htmlPath, "utf8") : html;
  const els = new Map();
  for (const id of [
    "data", "ownername", "avatar", "view", "tabs", "faces", "side", "openpal",
    "theme", "verbadge", "freshbadge", "clidot", "conmode", "conout", "conx",
    "console", "conbadge", "toast", "palback", "palq", "pallist", "palconfirm",
    "palcmd", "palnote", "palcancel", "palrun", "burger", "newsback", "newslist",
    "newstitle", "newsmeta", "newshow", "newsact", "newslog", "newsfb", "newsclose",
    "app", "fatal", "bar", "steps", "q",
  ]) {
    makeEl(id, els);
  }
  els.get("data").textContent = JSON.stringify(opts.embeddedData || {});
  if (opts.kind === "onboarding") {
    els.get("fatal").classList.add("hidden");
  }

  const localStorage = makeStorage(opts.localInit || {});
  const sessionStorage = makeStorage(opts.sessionInit || {});
  const docListeners = {};
  const winListeners = {};
  const replaceCalls = [];
  let currentHash = opts.hash || "";
  const loc = {
    protocol: opts.protocol || "http:",
    hostname: opts.hostname || "127.0.0.1",
    pathname: "/",
    search: opts.search || "",
    get hash() { return currentHash; },
    set hash(v) { currentHash = String(v).startsWith("#") ? String(v) : ("#" + v); },
    href: "",
    reloadCalled: false,
    reload() { loc.reloadCalled = true; },
  };
  const history = {
    replaceState(_st, _title, url) {
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
    addEventListener(ev, fn) { (docListeners[ev] = docListeners[ev] || []).push(fn); },
  };

  let now = opts.now || 1700000000000;
  const FakeDate = class extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  };

  const sandbox = {
    console,
    Date: FakeDate,
    setTimeout(fn, ms) {
      if (opts.advanceTimeOnTimeout) now += (ms || 0);
      if (opts.runImmediateTimers && (!ms || ms < 50)) fn();
      return 1;
    },
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
  const code = extractBundle(srcHtml, opts.kind);
  vm.runInContext(code, sandbox);
  return {
    sandbox, els, localStorage, sessionStorage, loc, replaceCalls, winListeners,
    setNow(v) { now = v; },
    fireHashChange(newHash, oldHash) {
      currentHash = newHash;
      for (const fn of (winListeners.hashchange || [])) {
        fn({ oldURL: "http://127.0.0.1:8787/" + (oldHash || ""), newURL: "http://127.0.0.1:8787/" + newHash });
      }
    },
  };
}

(async () => {
  if (mode === "token-lifecycle") {
    const fetchCalls = [];
    let statusToReturn = 200;
    const env = runEnv({
      kind: "dashboard",
      hash: "#t=abc123",
      localInit: { "brain-serve-token": "stale-local-tok" },
      fetchImpl: async (url, init) => {
        fetchCalls.push({ url, headers: (init && init.headers) || {} });
        if (statusToReturn === 401) {
          return { ok: false, status: 401, json: async () => ({ ok: false, error: "401" }) };
        }
        return { ok: true, status: 200, json: async () => ({ ok: true, model: { owner: { id: "eu", name: "Você (demo)" }, today: "2026-10-10", counts: { mine_open: 1 }, agenda: [], portfolio: { areas: [], processes: [], opportunities: [], gaps: [] } } }) };
      },
    });
    await new Promise(r => setTimeout(r, 20));

    // 1. sessionStorage stored token+exp, localStorage NOT written and cleaned
    const rawSess = env.sessionStorage.getItem("brain-serve-token");
    if (!rawSess) throw new Error("token ausente no sessionStorage");
    const parsed = JSON.parse(rawSess);
    if (parsed.tok !== "abc123") throw new Error("tok inesperado: " + parsed.tok);
    if (typeof parsed.exp !== "number" || parsed.exp <= 1700000000000) throw new Error("exp inválido");
    if (env.localStorage.getItem("brain-serve-token") !== null) throw new Error("localStorage ainda tem token");

    // 2. #t= stripped cleanly
    if (env.loc.hash !== "") throw new Error("hash deveria estar vazio, veio: " + env.loc.hash);
    if (!env.replaceCalls.includes("/")) throw new Error("replaceState não chamado com /");

    // 3. hashchange com #t= NÃO guarda token nem recarrega; apenas remove t= da URL mantendo outras partes do fragmento
    env.fireHashChange("#t=newtok42", "#inbox");
    const afterHash = JSON.parse(env.sessionStorage.getItem("brain-serve-token"));
    if (afterHash.tok !== "abc123") throw new Error("hashchange guardou token indevidamente: " + afterHash.tok);
    if (env.localStorage.getItem("brain-serve-token") !== null) throw new Error("hashchange escreveu em localStorage");
    if (env.loc.hash !== "") throw new Error("#t= ficou na URL após hashchange: " + env.loc.hash);
    if (env.loc.reloadCalled) throw new Error("hashchange disparou reload");

    env.fireHashChange("#todo&t=evil99", "#home");
    if (JSON.parse(env.sessionStorage.getItem("brain-serve-token")).tok !== "abc123") {
      throw new Error("hashchange #todo&t= alterou token guardado");
    }
    if (env.loc.hash !== "#todo") throw new Error("#todo&t= deveria virar #todo, veio: " + env.loc.hash);
    if (env.loc.reloadCalled) throw new Error("hashchange #todo&t= disparou reload");

    // 3b. navegação completa com ?n=…#t= (aba reaproveitada via util.focus_open_tab) consome no boot e remove só o fragmento
    const reusedEnv = runEnv({
      kind: "dashboard",
      search: "?n=a1b2c3d4",
      hash: "#t=reused99",
      fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, model: { owner: { id: "eu", name: "Você (demo)" }, today: "2026-10-10", counts: { mine_open: 0 }, agenda: [], portfolio: { areas: [], processes: [], opportunities: [], gaps: [] } } }) }),
    });
    await new Promise(r => setTimeout(r, 20));
    if (JSON.parse(reusedEnv.sessionStorage.getItem("brain-serve-token")).tok !== "reused99") {
      throw new Error("boot com ?n=…#t= não guardou o token");
    }
    if (reusedEnv.loc.hash !== "") throw new Error("boot com ?n=…#t= não limpou o hash: " + reusedEnv.loc.hash);
    if (!reusedEnv.replaceCalls.includes("/?n=a1b2c3d4")) {
      throw new Error("replaceState não preservou ?n=: " + JSON.stringify(reusedEnv.replaceCalls));
    }

    // 4. 401 clears token & resets LIVE
    statusToReturn = 401;
    env.els.get("toast").textContent = "";
    const clickUpdate = env.sandbox.document; // trigger api() via /api/cmd or hydrate
    // Chamar hydrate de novo simulando uma resposta 401 em api()
    await env.sandbox.BRAIN_AUTH.hydrate();
    if (env.sessionStorage.getItem("brain-serve-token") !== null) throw new Error("401 não limpou sessionStorage");
    if (env.sandbox.BRAIN_AUTH.isLive()) throw new Error("401 não resetou LIVE");
    if (env.sandbox.document.documentElement.dataset.live !== "0") throw new Error("dataset.live não virou 0");
    if (!env.els.get("view").innerHTML.includes("data-auth-required")) throw new Error("prompt de reautenticação ausente");

    // 5. >12h TTL expired in sessionStorage is purged on boot
    const expiredEnv = runEnv({
      kind: "dashboard",
      hash: "",
      sessionInit: { "brain-serve-token": JSON.stringify({ tok: "old", exp: 1700000000000 - 1000 }) },
      fetchImpl: async () => { throw new Error("não deveria chamar fetch com token expirado"); },
    });
    if (expiredEnv.sessionStorage.getItem("brain-serve-token") !== null) throw new Error("token expirado não foi purgado");
    if (expiredEnv.sandbox.BRAIN_AUTH.isLive()) throw new Error("token expirado marcou LIVE=true");
    if (!expiredEnv.els.get("view").innerHTML.includes("data-auth-required")) throw new Error("tela de auth não apareceu");

    // 6. #onboarding&t=tok preserves #onboarding and strips only t=
    const obHashEnv = runEnv({
      kind: "dashboard",
      hash: "#onboarding&t=obtok77",
      fetchImpl: async () => ({
        ok: true, status: 200,
        json: async () => ({ ok: true, model: { owner: { id: "eu", name: "Você (demo)" }, today: "2026-10-10", counts: { mine_open: 0 }, agenda: [], portfolio: { areas: [], processes: [], opportunities: [], gaps: [] } } }),
      }),
    });
    await new Promise(r => setTimeout(r, 20));
    if (obHashEnv.loc.hash !== "#onboarding") throw new Error("hash #onboarding perdido: " + obHashEnv.loc.hash);
    if (!obHashEnv.replaceCalls.includes("/#onboarding")) throw new Error("replaceState não preservou #onboarding: " + JSON.stringify(obHashEnv.replaceCalls));
    if (JSON.parse(obHashEnv.sessionStorage.getItem("brain-serve-token")).tok !== "obtok77") throw new Error("token do #onboarding&t= não foi salvo");

    // 7. onboarding.html standalone: #onboarding&t=tok, sessionStorage, 401 clear, expired purge
    const obPageEnv = runEnv({
      kind: "onboarding",
      htmlPath: process.argv[4],
      hash: "#onboarding&t=standalone1",
      localInit: { "brain-serve-token": "legacy-tok" },
      fetchImpl: async (url) => {
        if (url === "/api/onboard/state") return { ok: false, status: 401, json: async () => ({ ok: false }) };
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      },
    });
    await new Promise(r => setTimeout(r, 20));
    if (obPageEnv.localStorage.getItem("brain-serve-token") !== null) throw new Error("onboarding deixou token em localStorage");
    if (obPageEnv.loc.hash !== "#onboarding") throw new Error("onboarding perdeu #onboarding: " + obPageEnv.loc.hash);
    if (obPageEnv.sessionStorage.getItem("brain-serve-token") !== null) throw new Error("onboarding não limpou sessionStorage em 401");
    if (obPageEnv.els.get("fatal").classList.contains("hidden")) throw new Error("onboarding não exibiu #fatal em 401");

    console.log("OK_TOKEN_LIFECYCLE");
  } else if (mode === "real-bridge-hydrate") {
    const baseUrl = process.argv[4];
    const token = process.argv[5];
    const hash = process.argv[6] || "";
    const protocol = process.argv[7] || "http:";
    const embedded = process.argv[8] ? JSON.parse(process.argv[8]) : {};
    const fetchCalls = [];
    // A hidratação é assíncrona (pedidos reais à ponte): o harness espera ela assentar em vez de
    // dormir um tempo fixo — um sleep de 80 ms lia o nome do dono antes da resposta chegar num
    // runner carregado. "Assentado" = nenhum pedido à ponte em voo (resposta ou corpo) E DOM
    // estável há 40 ms. `inFlight` sempre volta a zero: cada incremento tem o decremento dele.
    let inFlight = 0;
    let settledAt = 0;
    const env = runEnv({
      kind: "dashboard",
      protocol,
      hostname: protocol === "file:" ? "" : "127.0.0.1",
      hash,
      embeddedData: embedded,
      fetchImpl: async (url, init) => {
        fetchCalls.push(url);
        inFlight += 1;
        let res;
        try {
          res = await globalThis.fetch(baseUrl + url, init);
        } catch (e) {
          inFlight -= 1;
          settledAt = Date.now();
          throw e;
        }
        inFlight -= 1;
        settledAt = Date.now();
        return {
          ok: res.ok,
          status: res.status,
          json: async () => {
            inFlight += 1;
            try {
              return await res.json();
            } finally {
              inFlight -= 1;
              settledAt = Date.now();
            }
          },
        };
      },
    });
    const snap = () => env.els.get("view").innerHTML + "\u0000" + env.els.get("ownername").textContent;
    const t0 = Date.now();
    let prev = snap();
    let stableSince = Date.now();
    while (Date.now() - t0 < 8000) {
      await new Promise(r => setTimeout(r, 10));
      const cur = snap();
      if (cur !== prev) {
        prev = cur;
        stableSince = Date.now();
      }
      if (inFlight === 0 && Date.now() - Math.max(stableSince, settledAt) >= 40) break;
    }
    console.log(JSON.stringify({
      hash: env.loc.hash,
      fetchCalls,
      live: env.sandbox.BRAIN_AUTH.isLive(),
      ownername: env.els.get("ownername").textContent,
      viewHtml: env.els.get("view").innerHTML,
      sessionTok: env.sessionStorage.getItem("brain-serve-token"),
    }));
  } else if (mode === "job-timeout") {
    // Testa o timeout do polling em onboarding.html (waitJob) quando status === "stale" ou >= 15 min
    const htmlOb = fs.readFileSync(process.argv[3], "utf8");
    const envStale = runEnv({
      kind: "onboarding",
      hash: "#t=tokjob",
      fetchImpl: async (url) => {
        if (url === "/api/onboard/state") return { ok: true, status: 200, json: async () => ({ ok: true, state: { owner: {}, routine: {}, profile: {}, setup: {}, connectors: [], memory: {}, keys: {}, agents: [], machine: {}, planning: {}, progress: { done: [] } } }) };
        return { ok: true, status: 200, json: async () => ({ ok: true, job: { status: "stale", result: { error: "tempo esgotado (15 min) — rode `brain doctor --online` no terminal" } } }) };
      },
    });
    await new Promise(r => setTimeout(r, 20));
    let staleErr = "";
    try {
      await envStale.sandbox.waitJob("j1");
    } catch (e) {
      staleErr = e.message;
    }
    if (!staleErr.includes("15 min")) throw new Error("waitJob não rejeitou job stale: " + staleErr);

    // Timeout no cliente (avançando Date.now após 1a poll running)
    let polls = 0;
    let timeBoxErr = "";
    try {
      const envCap = runEnv({
        kind: "onboarding",
        hash: "#t=tokjob",
        fetchImpl: async (url) => {
          if (url === "/api/onboard/state") return { ok: true, status: 200, json: async () => ({ ok: true, state: { owner: {}, routine: {}, profile: {}, setup: {}, connectors: [], memory: {}, keys: {}, agents: [], machine: {}, planning: {}, progress: { done: [] } } }) };
          polls += 1;
          return { ok: true, status: 200, json: async () => ({ ok: true, job: { status: "running", log: [] } }) };
        },
      });
      await new Promise(r => setTimeout(r, 20));
      const p = envCap.sandbox.waitJob("j2");
      envCap.setNow(1700000000000 + 16 * 60 * 1000);
      await p;
    } catch (e) {
      timeBoxErr = e.message;
    }
    if (!timeBoxErr.includes("15 min") || polls !== 1) throw new Error("waitJob não respeitou cap de 15 min: " + timeBoxErr + " polls=" + polls);
    console.log("OK_JOB_TIMEOUT");
  }
})().catch(e => { console.error(e); process.exit(1); });
"""


class BridgeSessionShellSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.inst = _demo_inst(cls.td.name)
        cls.token = "tok-sec-c06-demo"
        serve._Handler.state = serve._State(cls.inst, cls.token)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.td.cleanup()

    def _req(self, path: str, token: str | None = None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if token is not None:
            req.add_header("X-Brain-Token", token)
        req.add_header("Host", "127.0.0.1")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8")

    def test_unauthenticated_html_routes_contain_zero_vault_data(self):
        secret_markers = (
            "Você (demo)",
            "Marina-demo",
            "Reforma do novo ponto",
            "Padaria",
            "TASK-0001",
            "OPP-0001",
            "PROC-0001",
        )
        for route in ("/", "/index.html", "/portfolio.html"):
            with self.subTest(route=route):
                status, _hdrs, html = self._req(route)
                self.assertEqual(status, 200)
                self.assertIn('<script id="data" type="application/json">{}</script>', html)
                for marker in secret_markers:
                    self.assertNotIn(marker, html)

    def test_api_data_and_api_portfolio_require_token_and_return_model(self):
        for route in ("/api/data", "/api/portfolio"):
            with self.subTest(route=route):
                st_no, _, _ = self._req(route)
                self.assertEqual(st_no, 401)
                st_bad, _, _ = self._req(route, token="errado")
                self.assertEqual(st_bad, 401)
                st_ok, _, body = self._req(route, token=self.token)
                self.assertEqual(st_ok, 200)
                payload = json.loads(body)
                self.assertTrue(payload["ok"])
                m = payload["model"]
                self.assertIn("portfolio", m)
                self.assertEqual(m["owner"]["name"], "Você (demo)")

        # /api/portfolio mantém o recorte (não vaza notas/health)
        _, _, pf_body = self._req("/api/portfolio", token=self.token)
        pf_model = json.loads(pf_body)["model"]
        self.assertNotIn("notes", pf_model)
        self.assertNotIn("health", pf_model)

    def test_csp_header_and_meta_present(self):
        for route in ("/", "/portfolio.html", "/api/data", "/api/portfolio"):
            with self.subTest(route=route):
                _, hdrs, _ = self._req(route, token=self.token)
                csp = hdrs.get("Content-Security-Policy") or ""
                for directive in (
                    "default-src 'none'",
                    "script-src 'unsafe-inline'",
                    "style-src 'unsafe-inline'",
                    "connect-src 'self'",
                    "base-uri 'none'",
                    "form-action 'none'",
                    "frame-ancestors 'none'",
                ):
                    self.assertIn(directive, csp)

        for path in (DASH_HTML, PF_HTML, OB_HTML):
            with self.subTest(asset=path.name):
                html = path.read_text(encoding="utf-8")
                m = re.search(r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
                self.assertIsNotNone(m, f"<meta> CSP ausente em {path.name}")
                meta_csp = m.group(1)
                for directive in (
                    "default-src 'none'",
                    "script-src 'unsafe-inline'",
                    "style-src 'unsafe-inline'",
                    "connect-src 'self'",
                    "base-uri 'none'",
                    "form-action 'none'",
                ):
                    self.assertIn(directive, meta_csp)
                self.assertNotIn("frame-ancestors", meta_csp)
                self.assertNotIn('localStorage.setItem("brain-serve-token"', html)
                self.assertIn("sessionStorage", html)

    @unittest.skipUnless(shutil.which("node"), "node ausente")
    def test_token_sessionstorage_ttl_oneshot_and_401_clear_in_node(self):
        spec = importlib.util.spec_from_file_location("build_assets", ROOT / "scripts" / "build_assets.py")
        build_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_mod)
        with tempfile.TemporaryDirectory() as td:
            dash_built = Path(td) / "dashboard.html"
            dash_built.write_text(build_mod.assemble(False, "Brain"), encoding="utf-8")
            harness = Path(td) / "harness.js"
            harness.write_text(NODE_TOKEN_HARNESS, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(harness), "token-lifecycle", str(dash_built), str(OB_HTML)],
                capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("OK_TOKEN_LIFECYCLE", proc.stdout)

    @unittest.skipUnless(shutil.which("node"), "node ausente")
    def test_shell_hydrates_via_real_bridge(self):
        base = f"http://127.0.0.1:{self.port}"
        # Confirma que os HTMLs vindos da ponte são shells sem dados
        for route in ("/", "/portfolio.html"):
            st, _, html = self._req(route)
            self.assertEqual(st, 200)
            self.assertIn('<script id="data" type="application/json">{}</script>', html)

        with tempfile.TemporaryDirectory() as td:
            harness = Path(td) / "harness.js"
            harness.write_text(NODE_TOKEN_HARNESS, encoding="utf-8")
            dash_shell = Path(td) / "dash_shell.html"
            pf_shell = Path(td) / "pf_shell.html"
            _, _, dash_text = self._req("/")
            _, _, pf_text = self._req("/portfolio.html")
            dash_shell.write_text(dash_text, encoding="utf-8")
            pf_shell.write_text(pf_text, encoding="utf-8")

            def run_mode(asset_file: Path, hash_val: str, protocol: str = "http:", embedded: dict | None = None):
                args = ["node", str(harness), "real-bridge-hydrate", str(asset_file), base, self.token, hash_val, protocol]
                if embedded is not None:
                    args.append(json.dumps(embedded))
                proc = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                return json.loads(proc.stdout.strip())

            # 1. Rota #todo&t=<token>: hidrata via /api/data e renderiza a vista #todo (não #home)
            # A pílula de serviços pode pedir /api/services à parte; não entra na hidratação.
            def hydrate(calls):
                return [c for c in calls if c != "/api/services"]

            res_todo = run_mode(dash_shell, f"#todo&t={self.token}")
            self.assertEqual(hydrate(res_todo["fetchCalls"]), ["/api/data"])
            self.assertEqual(res_todo["hash"], "#todo")
            self.assertTrue(res_todo["live"])
            self.assertEqual(res_todo["ownername"], "Você (demo)")
            self.assertIn("A fazer", res_todo["viewHtml"])
            self.assertNotIn("data-auth-required", res_todo["viewHtml"])

            # 2. portfolio.html com #pf/opps&t=<token>: hidrata via /api/portfolio e renderiza Oportunidades
            res_pf = run_mode(pf_shell, f"#pf/opps&t={self.token}")
            self.assertEqual(hydrate(res_pf["fetchCalls"]), ["/api/portfolio"])
            self.assertEqual(res_pf["hash"], "#pf/opps")
            self.assertEqual(res_pf["ownername"], "Você (demo)")
            self.assertIn("Oportunidades", res_pf["viewHtml"])

            # 3. Token inválido -> ponte responde 401 -> limpa sessionStorage e mostra prompt de reautenticação
            res_bad = run_mode(dash_shell, "#t=token-invalido")
            self.assertEqual(hydrate(res_bad["fetchCalls"]), ["/api/data"])
            self.assertFalse(res_bad["live"])
            self.assertIsNone(res_bad["sessionTok"])
            self.assertIn("data-auth-required", res_bad["viewHtml"])
            self.assertIn("render --open", res_bad["viewHtml"])

            # 4. Sem token -> não chama /api/data e exibe prompt de autenticação
            res_notok = run_mode(dash_shell, "")
            self.assertEqual(res_notok["fetchCalls"], [])
            self.assertFalse(res_notok["live"])
            self.assertIn("data-auth-required", res_notok["viewHtml"])

            # 5. file:// mantém dados embutidos e nunca faz fetch
            m_full = render.view_model(Brain(self.inst))
            res_file = run_mode(DASH_HTML, "", protocol="file:", embedded=m_full)
            self.assertEqual(res_file["fetchCalls"], [])
            self.assertFalse(res_file["live"])
            self.assertEqual(res_file["ownername"], "Você (demo)")
            self.assertIn("Você (demo)", res_file["viewHtml"])

    def test_onboard_job_becomes_stale_after_timeout(self):
        j = onboard._start("test-timeout", lambda _job: time.sleep(0.05) or {"ok": True})
        j.started = time.time() - (onboard.JOB_TIMEOUT_S + 5)
        snap = onboard.job(j.id)
        self.assertIsNotNone(snap)
        self.assertEqual(snap["status"], "stale")
        self.assertIn("15 min", snap["result"]["error"])
        self.assertIn("brain doctor --online", snap["result"]["error"])

    @unittest.skipUnless(shutil.which("node"), "node ausente")
    def test_onboard_polling_bounded_in_node(self):
        with tempfile.TemporaryDirectory() as td:
            harness = Path(td) / "harness.js"
            harness.write_text(NODE_TOKEN_HARNESS, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(harness), "job-timeout", str(OB_HTML)],
                capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("OK_JOB_TIMEOUT", proc.stdout)


if __name__ == "__main__":
    unittest.main()
