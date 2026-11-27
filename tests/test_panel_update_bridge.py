"""Ponte CLI `/api/update`, versão no rodapé da barra lateral e modal de novidades (#62)."""
from __future__ import annotations

import contextlib
import io
import json
import os
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, render, serve, upstream  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _make_inst(root: Path) -> config.Instance:
    (root / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED/_ledger", "FRESH", "logs", "reports"):
        (root / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (root / "config" / "brain.toml").write_text(
        '[owner]\nid = "marina-demo"\nname = "Marina Demo"\n'
        '[owner.extra]\norg = "Padaria Pão Quente"\nemail = "marina-demo@x.com"\n',
        encoding="utf-8",
    )
    (root / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    (root / "vault" / "PROCESSED" / "_ledger" / "events.jsonl").write_text("", encoding="utf-8")
    inst = config.load(root)
    b = Brain(inst)
    b.record_one({
        "type": "person.added",
        "id": "marina-demo",
        "by": "owner",
        "data": {"name": "Marina Demo", "email": "marina-demo@x.com", "relation": "dono"},
    })
    return inst


class PanelUpdateBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.inst = _make_inst(Path(cls.td.name) / "inst")
        cls.token = "tok-update-bridge-123456"
        cls.state = serve._State(cls.inst, cls.token)
        serve._Handler.state = cls.state
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.state.port = cls.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        try:
            serve.live_url_file(cls.inst).unlink()
        except FileNotFoundError:
            pass
        cls.td.cleanup()

    def setUp(self):
        serve._Handler.state = self.state
        with self.state.update_lock:
            self.state.update_jobs.clear()
            self.state.update_active = None
        self.state.update_cmd_fn = serve._default_update_cmd
        self.state.restart_fn = lambda: serve._default_restart(self.state)

    def _req(
        self,
        path: str,
        token: str | None = None,
        method: str = "GET",
        body: dict | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict]:
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("Host", f"127.0.0.1:{self.port}")
        if token is not None:
            r.add_header("X-Brain-Token", token)
        if origin is not None:
            r.add_header("Origin", origin)
        if body is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _poll_until_done(self, jid: str, timeout_s: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            code, payload = self._req(f"/api/update/job/{jid}", token=self.token)
            self.assertEqual(code, 200)
            if payload.get("status") != "running":
                return payload
            time.sleep(0.05)
        self.fail(f"job {jid} não terminou em {timeout_s}s")

    def test_update_fora_da_allowlist_api_cmd_403(self):
        for cmd in ("update", "brain update"):
            code, body = self._req("/api/cmd", token=self.token, method="POST", body={"cmd": cmd})
            self.assertEqual(code, 403)
            self.assertFalse(body["ok"])
            self.assertIn("allowlist", body["error"])

    def test_api_update_exige_token_401(self):
        code, _ = self._req("/api/update", method="POST", body={})
        self.assertEqual(code, 401)
        code, _ = self._req("/api/update", token="errado", method="POST", body={})
        self.assertEqual(code, 401)
        code, _ = self._req("/api/update/job/x")
        self.assertEqual(code, 401)
        code, _ = self._req("/api/update/job/x", token="errado")
        self.assertEqual(code, 401)
        code, _ = self._req(
            "/api/update",
            token=self.token,
            method="POST",
            body={},
            origin="http://atacante.invalid",
        )
        self.assertEqual(code, 403)
        code, _ = self._req(
            "/api/update/job/x",
            token=self.token,
            origin="http://atacante.invalid",
        )
        self.assertEqual(code, 403)
        code, body = self._req("/api/update/job/inexistente", token=self.token)
        self.assertEqual(code, 404)
        self.assertFalse(body["ok"])

    def test_api_update_sucesso_stream_e_agendamento_restart(self):
        restarted = threading.Event()
        versions = iter(["2.29.0", "2.30.0"])

        def fake_cmd(_inst, on_line):
            on_line("1 commit(s) trazidos de origin/main:")
            on_line("  semeado no vault a partir de template/")
            on_line("doctor: ✓ ok")
            return 0

        self.state.update_cmd_fn = fake_cmd
        self.state.restart_fn = restarted.set

        with mock.patch.object(upstream, "_version", side_effect=lambda _root: next(versions)):
            code, start_res = self._req("/api/update", token=self.token, method="POST", body={})
            self.assertEqual(code, 200)
            self.assertTrue(start_res["ok"])
            jid = start_res["job"]
            final = self._poll_until_done(jid)

        expected_keys = {
            "ok", "id", "status", "lines", "exit_code",
            "restarting", "diverged", "version_before", "version_after",
        }
        self.assertEqual(set(final.keys()), expected_keys)
        self.assertTrue(final["ok"])
        self.assertEqual(final["id"], jid)
        self.assertEqual(final["status"], "done")
        self.assertEqual(final["exit_code"], 0)
        self.assertTrue(final["restarting"])
        self.assertFalse(final["diverged"])
        self.assertEqual(final["version_before"], "2.29.0")
        self.assertEqual(final["version_after"], "2.30.0")
        self.assertEqual(
            final["lines"],
            [
                "1 commit(s) trazidos de origin/main:",
                "  semeado no vault a partir de template/",
                "doctor: ✓ ok",
            ],
        )
        self.assertTrue(restarted.wait(timeout=3.5), "restart_fn deveria ser chamada após ~1.2s")

    def test_api_update_concorrente_retorna_409(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_cmd(_inst, on_line):
            on_line("puxando commits...")
            started.set()
            release.wait(timeout=5.0)
            return 0

        self.state.update_cmd_fn = blocking_cmd
        self.state.restart_fn = lambda: None

        code1, res1 = self._req("/api/update", token=self.token, method="POST", body={})
        self.assertEqual(code1, 200)
        jid1 = res1["job"]
        self.assertTrue(started.wait(timeout=2.0))

        code2, res2 = self._req("/api/update", token=self.token, method="POST", body={})
        self.assertEqual(code2, 409)
        self.assertFalse(res2["ok"])
        self.assertEqual(res2["job"], jid1)

        release.set()
        final = self._poll_until_done(jid1)
        self.assertEqual(final["status"], "done")

    def test_api_update_divergencia_retorna_texto_verbatim_sem_restart(self):
        restarted = threading.Event()
        verbatim = [
            "divergiu: 1 commit(s) locais ainda não publicados e 2 novo(s) no upstream.",
            "`brain update --rebase` re-aplica os seus por cima; para conflito, `git rebase --abort` desfaz.",
        ]

        def diverged_cmd(_inst, on_line):
            for ln in verbatim:
                on_line(ln)
            return 2

        self.state.update_cmd_fn = diverged_cmd
        self.state.restart_fn = restarted.set

        code, res = self._req("/api/update", token=self.token, method="POST", body={})
        self.assertEqual(code, 200)
        final = self._poll_until_done(res["job"])

        self.assertTrue(final["ok"])
        self.assertEqual(final["status"], "error")
        self.assertEqual(final["exit_code"], 2)
        self.assertTrue(final["diverged"])
        self.assertFalse(final["restarting"])
        self.assertIsNone(final["version_after"])
        self.assertEqual(final["lines"], verbatim)
        self.assertFalse(restarted.wait(timeout=1.5), "não pode agendar restart em erro")

    def test_api_update_bloqueado_com_brain_nightly_403(self):
        called = False

        def fake_cmd(_inst, _on_line):
            nonlocal called
            called = True
            return 0

        self.state.update_cmd_fn = fake_cmd
        self.state.restart_fn = lambda: None

        with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
            code, res = self._req("/api/update", token=self.token, method="POST", body={})
            self.assertEqual(code, 403)
            self.assertFalse(res["ok"])
            self.assertIn("noturno", res["error"])
        self.assertFalse(called)

    def test_serve_preserva_token_via_env_no_reinicio(self):
        preset = "tok-reinicio-preservado-123456"
        prev_state = serve._Handler.state

        def _restore():
            st = serve._Handler.state
            if st is not None and getattr(st, "httpd", None) is not None and st is not self.state:
                st.httpd.shutdown()
            serve._Handler.state = prev_state

        self.addCleanup(_restore)

        with tempfile.TemporaryDirectory() as td:
            inst2 = _make_inst(Path(td) / "inst2")
            buf = io.StringIO()

            def _run():
                with contextlib.redirect_stdout(buf):
                    serve.serve(inst2, port=0, open_browser=False)

            with mock.patch.dict(os.environ, {"BRAIN_SERVE_TOKEN": preset}):
                t = threading.Thread(target=_run, daemon=True)
                t.start()
                deadline = time.monotonic() + 5.0
                live_url = None
                while time.monotonic() < deadline:
                    live_url = serve.live_panel_url(inst2)
                    if live_url and getattr(serve._Handler.state, "httpd", None) is not None:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(live_url)
                self.assertTrue(live_url.endswith(f"/#t={preset}"), f"URL inesperada: {live_url}")
                self.assertNotIn("BRAIN_SERVE_TOKEN", os.environ)

                port2 = serve._Handler.state.port
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port2}/api/data",
                    headers={"Host": f"127.0.0.1:{port2}", "X-Brain-Token": preset},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertTrue(json.loads(resp.read().decode("utf-8"))["ok"])

                serve._Handler.state.httpd.shutdown()
                t.join(timeout=5.0)
                self.assertFalse(t.is_alive())

    def test_assets_sem_gen2_sem_brain_update_literal_e_modal_com_open(self):
        m = render.view_model(Brain(self.inst))
        self.assertEqual(m["update"]["cli_cmd"], "./brain update")

        for name in ("dashboard.html", "portfolio.html"):
            html = (ROOT / "brainlib" / "assets" / name).read_text(encoding="utf-8")
            self.assertIn('id="sb-status"', html, name)
            self.assertIn('id="verbadge"', html, name)
            self.assertIn('id="freshbadge"', html, name)
            self.assertIn('id="newsact"', html, name)
            self.assertIn('id="newslog"', html, name)
            self.assertNotIn('id="gen2"', html, name)
            self.assertNotIn("brain update", html, name)

        core_js = (ROOT / "brainlib" / "assets" / "src" / "core.js").read_text(encoding="utf-8")
        self.assertIn('classList.add("open")', core_js)
        self.assertIn('classList.remove("open")', core_js)

        node = shutil.which("node")
        if not node:
            self.skipTest("node ausente no ambiente")

        m["update"] = {
            "version": "2.29.0",
            "remote_version": "2.30.0",
            "behind": 2,
            "ahead": 0,
            "checked": True,
            "checked_at": "2026-10-09T09:00:00-03:00",
            "news": ["Novidade de teste"],
            "cli_cmd": "./brain update",
        }
        dash_html = (ROOT / "brainlib" / "assets" / "dashboard.html").read_text(encoding="utf-8")
        compiled_js = dash_html.split("<script>", 1)[1].rsplit("</script>", 1)[0]

        script = r"""
const fs = require("fs");
const payload = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const jsSrc = fs.readFileSync(process.argv[3], "utf8");
const els = new Map();
const docListeners = new Map();
const winListeners = new Map();
function makeClassList(el) {
  const set = new Set();
  return {
    add(...xs) { xs.forEach(x => set.add(x)); el.className = Array.from(set).join(" "); },
    remove(...xs) { xs.forEach(x => set.delete(x)); el.className = Array.from(set).join(" "); },
    toggle(x, f) { const on = f !== undefined ? !!f : !set.has(x); if (on) set.add(x); else set.delete(x); el.className = Array.from(set).join(" "); return on; },
    contains(x) { return set.has(x); },
  };
}
function makeEl(id, tag) {
  const el = {
    id: id || "", tagName: (tag || "DIV").toUpperCase(),
    innerHTML: "", textContent: "", value: "", hidden: id === "newsback" || id === "newsact" || id === "newslog",
    style: {}, dataset: {}, children: [], _ev: {},
    addEventListener(ev, fn) { (this._ev[ev] = this._ev[ev] || []).push(fn); },
    removeEventListener() {},
    querySelector() { return makeEl("", "SPAN"); },
    querySelectorAll() { return []; },
    closest(sel) { return sel === "[data-brain-update]" && el.id === "newsact" ? el : null; },
    focus() {}, select() {}, remove() { el.removed = true; },
    appendChild(c) { this.children.push(c); return c; }, prepend() {},
    setAttribute() {}, hasAttribute() { return false; },
  };
  el.classList = makeClassList(el);
  if (id) els.set(id, el);
  return el;
}
["verbadge","newsback","newstitle","newsmeta","newslist","newslog","newshow","newsfb","newsact","newsclose","view","palback","openpal"].forEach(id => makeEl(id, "DIV"));
let copiedText = "";
const doc = {
  getElementById(id) {
    if (id === "data") return { textContent: JSON.stringify(payload) };
    if (els.has(id)) return els.get(id);
    return makeEl(id, "DIV");
  },
  querySelector(sel) {
    if (sel === ".pal-back.open") { const nb = els.get("newsback"); return nb.classList.contains("open") ? nb : null; }
    if (sel === ".dd.open") return null;
    if (sel.startsWith("#")) return doc.getElementById(sel.slice(1));
    return makeEl("", "DIV");
  },
  querySelectorAll() { return []; },
  addEventListener(ev, fn, cap) { (docListeners.get(ev) || docListeners.set(ev, []).get(ev)).push({fn, cap: !!cap}); },
  removeEventListener() {},
  createElement(tag) { return makeEl("", tag); },
  body: { appendChild(c) { return c; }, classList: makeClassList({}) },
  documentElement: { dataset: {} },
  activeElement: { tagName: "BODY" },
};
const win = {
  location: { hash: "#home", protocol: "file:", hostname: "", pathname: "/", search: "" },
  localStorage: { getItem() { return null; }, setItem() {} },
  sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  history: { replaceState() {} },
  matchMedia: () => ({ matches: false }),
  scrollTo() {},
  addEventListener(ev, fn, cap) { (winListeners.get(ev) || winListeners.set(ev, []).get(ev)).push({fn, cap: !!cap}); },
  setTimeout() { return 1; }, clearTimeout() {},
};
const nav = { platform: "Linux x86_64", userAgent: "Linux", clipboard: { writeText(t) { copiedText = t; return Promise.resolve(); } } };
new Function("window","document","location","localStorage","sessionStorage","history","matchMedia","navigator","setTimeout","clearTimeout", jsSrc)(
  win, doc, win.location, win.localStorage, win.sessionStorage, win.history, win.matchMedia, nav, win.setTimeout, win.clearTimeout
);
const vb = els.get("verbadge"), nb = els.get("newsback"), act = els.get("newsact");
vb._ev.click.forEach(fn => fn());
const opened = !nb.hidden && nb.classList.contains("open") && !act.hidden;
(docListeners.get("keydown") || []).forEach(({fn}) => fn({key: "Escape", target: {tagName: "BODY"}, preventDefault(){}}));
const closedEsc = nb.hidden && !nb.classList.contains("open") && !nb.removed;
(docListeners.get("click") || []).forEach(({fn}) => fn({target: act, preventDefault(){}}));
Promise.resolve().then(() => {
  console.log(JSON.stringify({
    badgeText: vb.textContent,
    badgeBehind: vb.classList.contains("behind"),
    opened,
    closedEsc,
    liveAttr: doc.documentElement.dataset.live,
    cliCmd: nb.dataset.cliCmd,
    copiedText,
    fbText: els.get("newsfb").textContent,
  }));
});
"""
        with tempfile.TemporaryDirectory() as td:
            p_m = Path(td) / "m.json"
            p_js = Path(td) / "c.js"
            p_run = Path(td) / "r.js"
            p_m.write_text(json.dumps(m, default=str), encoding="utf-8")
            p_js.write_text(compiled_js, encoding="utf-8")
            p_run.write_text(script, encoding="utf-8")
            proc = subprocess.run([node, str(p_run), str(p_m), str(p_js)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            res = json.loads(proc.stdout)

        self.assertEqual(res["badgeText"], "v2.29.0 → v2.30.0")
        self.assertTrue(res["badgeBehind"])
        self.assertTrue(res["opened"])
        self.assertTrue(res["closedEsc"])
        self.assertEqual(res["liveAttr"], "0")
        self.assertEqual(res["cliCmd"], "./brain update")
        self.assertEqual(res["copiedText"], "./brain update")
        self.assertEqual(res["fbText"], "Comando copiado")


if __name__ == "__main__":
    unittest.main()
