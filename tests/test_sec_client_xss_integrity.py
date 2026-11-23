"""Segurança do cliente e integridade de URLs, refresh e remoção da inbox (#105, #119, #123, #132)."""
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
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import cli, config, feedback, share, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402

ASSETS = ROOT / "brainlib" / "assets"
DASH_HTML = ASSETS / "dashboard.html"
PF_HTML = ASSETS / "portfolio.html"


def _make_brain(tmp: Path) -> Brain:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED/_ledger", "FRESH", "reports/share", "logs"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "marina-demo"\nname = "Marina Demo"\n'
        '[publish]\ndestinations = ["slack-canvas"]\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    (tmp / "vault" / "PROCESSED" / "_ledger" / "events.jsonl").write_text("", encoding="utf-8")
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina Demo", "email": "marina-demo@x.com", "relation": "dono"}})
    return b


class _FakeResp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._raw


NODE_HARNESS = r"""
"use strict";
const fs = require("fs");
const vm = require("vm");

const mode = process.argv[2];
const htmlPath = process.argv[3];
const html = fs.readFileSync(htmlPath, "utf8");

function extractBundle(text) {
  const marker = '<script id="data" type="application/json">';
  const idx = text.indexOf(marker);
  const after = text.indexOf("</script>", idx) + "</script>".length;
  const s = text.indexOf("<script>", after) + "<script>".length;
  const e = text.lastIndexOf("</script>");
  return text.slice(s, e);
}

function makeStorage() {
  const m = new Map();
  return {
    getItem(k) { return m.has(k) ? m.get(k) : null; },
    setItem(k, v) { m.set(String(k), String(v)); },
    removeItem(k) { m.delete(k); },
  };
}

function makeEl(id, els) {
  const cls = new Set();
  const attrs = {};
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
    children,
    firstChild: null,
    classList: {
      add(...xs) { xs.forEach(x => cls.add(x)); },
      remove(...xs) { xs.forEach(x => cls.delete(x)); },
      toggle(x, f) { const on = f === undefined ? !cls.has(x) : !!f; if (on) cls.add(x); else cls.delete(x); return on; },
      contains(x) { return cls.has(x); },
    },
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    appendChild(c) { children.push(c); el.firstChild = children[0] || null; return c; },
    prepend(c) { children.unshift(c); el.firstChild = children[0] || null; if (c.id) els.set(c.id, c); return c; },
    insertBefore(n) { children.unshift(n); el.firstChild = children[0] || null; if (n.id) els.set(n.id, n); return n; },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] || null; },
    remove() {},
    focus() {},
    select() {},
    scrollTop: 0,
    scrollHeight: 0,
  };
  if (id) els.set(id, el);
  return el;
}

function bootEnv(embeddedData) {
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
  els.get("data").textContent = JSON.stringify(embeddedData || {});
  const localStorage = makeStorage();
  const sessionStorage = makeStorage();
  const loc = {
    protocol: "file:",
    hostname: "",
    pathname: "/tmp/dashboard.html",
    search: "",
    hash: "#home",
    href: "file:///tmp/dashboard.html#home",
    reload() {},
  };
  const doc = {
    documentElement: { dataset: {} },
    body: makeEl("body", els),
    activeElement: { tagName: "BODY" },
    getElementById(id) { return els.get(id) || null; },
    querySelector(sel) { return sel.startsWith("#") ? (els.get(sel.slice(1)) || null) : null; },
    querySelectorAll() { return []; },
    createElement(tag) { const el = makeEl("", els); el.tagName = tag.toUpperCase(); return el; },
    addEventListener() {},
  };
  const sandbox = {
    console,
    Date,
    URL,
    URLSearchParams,
    Uint8Array,
    Promise,
    setTimeout() { return 1; },
    clearTimeout() {},
    matchMedia() { return { matches: false }; },
    navigator: { platform: "MacIntel", userAgent: "Node" },
    location: loc,
    history: { replaceState() {} },
    localStorage,
    sessionStorage,
    document: doc,
    encodeURIComponent,
    decodeURIComponent,
    CustomEvent: function(t, d) { this.type = t; this.detail = d && d.detail; },
  };
  sandbox.window = sandbox;
  sandbox.window.addEventListener = () => {};
  sandbox.window.scrollTo = () => {};
  vm.createContext(sandbox);
  vm.runInContext(extractBundle(html), sandbox);
  return { sandbox, els };
}

(async () => {
  if (mode === "safeurl-and-normalize") {
    const { sandbox, els } = bootEnv({});
    const B = sandbox.window.BRAIN;
    if (!B || typeof B.safeUrl !== "function") throw new Error("BRAIN.safeUrl ausente");

    // 1. safeUrl checks
    const mustAllow = [
      ["https://example.com/1", false, "https://example.com/1"],
      ["http://localhost:8080/a?b=1#c", false, "http://localhost:8080/a?b=1#c"],
      ["  https://github.com/o/r/issues/7  ", false, "https://github.com/o/r/issues/7"],
      ["mailto:marina-demo@x.com", true, "mailto:marina-demo@x.com"],
    ];
    for (const [inp, mailto, exp] of mustAllow) {
      const got = B.safeUrl(inp, mailto);
      if (got !== exp) throw new Error("safeUrl permitiu errado: " + inp + " -> " + got);
    }

    const mustBlock = [
      ["javascript:alert(1)", false],
      ["JaVaScRiPt:alert(1)", false],
      ["  javascript:alert(1)", false],
      ["java\tscript:alert(1)", false],
      ["java\nscript:alert(1)", false],
      ["data:text/html,<script>alert(1)</script>", false],
      ["vbscript:msgbox(1)", false],
      ["mailto:marina-demo@x.com", false],
      ["https://example.com/\nfoo", false],
      ["https://example.com/foo bar", false],
      ["https:///foo", false],
      ["http://", false],
      ["//evil.example/x", false],
      ["https://evil.example\\x", false],
      ["/relative/path", false],
      ["", false],
      [null, false],
      [undefined, false],
      [123, false],
    ];
    for (const [inp, mailto] of mustBlock) {
      const got = B.safeUrl(inp, mailto);
      if (got !== "") throw new Error("safeUrl não bloqueou: " + String(inp) + " -> " + got);
    }

    // docUrl checks
    if (B.docUrl("javascript:alert(1)") !== "") throw new Error("docUrl não bloqueou javascript:");
    if (B.docUrl("https://docs.google.com/document/d/123") !== "https://docs.google.com/document/d/123") {
      throw new Error("docUrl rejeitou https válido");
    }
    if (!B.docUrl("12345678901234567890").startsWith("https://drive.google.com/file/d/")) {
      throw new Error("docUrl não montou link do Drive");
    }

    // 2. normalizeBrain on empty and null-valued payloads
    const emptyNorm = B.normalizeBrain({});
    if (!emptyNorm.owner || emptyNorm.owner.name !== "Dono") throw new Error("default owner ausente");
    if (!Array.isArray(emptyNorm.agenda) || !emptyNorm.wins || !Array.isArray(emptyNorm.wins.weeks)) {
      throw new Error("defaults agenda/wins ausentes");
    }
    if (!emptyNorm.portfolio || !emptyNorm.portfolio.ice_rubric || !emptyNorm.counts || !emptyNorm.review) {
      throw new Error("defaults portfolio/counts/review ausentes");
    }
    const nullNorm = B.normalizeBrain({ owner: null, agenda: null, wins: null, portfolio: null, counts: null, review: null });
    if (!nullNorm.owner || !Array.isArray(nullNorm.agenda) || !Array.isArray(nullNorm.wins.weeks)) {
      throw new Error("normalizeBrain falhou com chaves null");
    }
    // Rendering views on empty model must not throw
    B.V.home();
    B.V.wins();
    B.V["pf/visao"]();

    // 3. Render sinks: V.feedback, V.ask, V["pf/docs"]
    const okRefresh = B.refresh({
      owner: { id: "marina-demo", name: "Marina Demo" },
      today: "2026-10-09",
      actions: [{ id: "TASK-0001", title: "Assar pão", owner: "marina-demo", owner_name: "Marina Demo",
        list: "mine", status: "aberta", open: true, mine: true, blocked_by: [], unblocks: [], people: [], history: [] }],
      feedback: [
        { id: "FB-0001", kind: "bug", title: "XSS 1", status: "retratado", number: 10,
          url: "javascript:alert(1)", reason: "teste", comment_url: "data:text/html,xss" },
        { id: "FB-0002", kind: "sugestao", title: "Link bom", status: "retratado", number: 11,
          url: "https://github.com/o/r/issues/11", reason: "ok",
          comment_url: "https://github.com/o/r/issues/11#issuecomment-2" },
      ],
      publishes: [
        { id: "PUB-0001", title: "Relatório mau", to: "slack-canvas", status: "publicada", link: "javascript:alert(2)" },
        { id: "PUB-0002", title: "Relatório bom", to: "slack-canvas", status: "publicada", link: "https://example.com/pub/2" },
      ],
      portfolio: {
        areas: [], processes: [],
        opportunities: [{ id: "OPP-0001", title: "Forno", area: "ops", kind: "melhoria-de-processo", status: "ideia",
          docs: [{ kind: "one-pager", title: "Doc mau", ref: "javascript:alert(3)", watch: false }], status_history: [], evidence: [] }],
      },
    });
    if (!okRefresh) throw new Error("refresh válido retornou false");

    const fbHtml = B.V.feedback(new URLSearchParams("a=1"));
    if (/href=["']?(?:javascript|data|vbscript):/i.test(fbHtml) || fbHtml.includes("javascript:") || fbHtml.includes("data:text/html")) {
      throw new Error("V.feedback renderizou URL perigosa: " + fbHtml);
    }
    if (!fbHtml.includes('href="https://github.com/o/r/issues/11"') ||
        !fbHtml.includes('href="https://github.com/o/r/issues/11#issuecomment-2"')) {
      throw new Error("V.feedback omitiu URL válida");
    }

    const askHtml = B.V.ask(new URLSearchParams("a=1"));
    if (/href=["']?(?:javascript|data|vbscript):/i.test(askHtml) || askHtml.includes('href="#"')) {
      throw new Error("V.ask renderizou href perigoso ou # fallback: " + askHtml);
    }
    if ((askHtml.match(/<a\b/g) || []).length !== 1 || !askHtml.includes('href="https://example.com/pub/2"')) {
      throw new Error("V.ask não renderizou exatamente 1 link válido: " + askHtml);
    }

    const docsHtml = B.V["pf/docs"]();
    if (docsHtml.includes("javascript:")) {
      throw new Error("V[pf/docs] renderizou javascript: em data-url");
    }

    // 3b. extra.js entEntries() lê window.BRAIN.M após refresh (não D0 congelado)
    const openpal = els.get("openpal");
    if (openpal && typeof openpal.onclick === "function") {
      openpal.onclick();
      const palHtml = els.get("pallist").innerHTML;
      if (!palHtml.includes("TASK-0001") || !palHtml.includes("Assar pão")) {
        throw new Error("paleta (entEntries) não refletiu ação do refresh: " + palHtml);
      }
    }

    // 4. Atomic refresh failure: malformed payload leaves prior M intact + visible error
    const badNull = B.refresh(null);
    const badArrItem = B.refresh({ owner: { id: "evil", name: "Evil" }, actions: [null] });
    if (badNull !== false || badArrItem !== false) throw new Error("refresh malformado não retornou false");
    if (B.M.owner.name !== "Marina Demo" || !B.A["TASK-0001"] || B.M.actions.length !== 1) {
      throw new Error("refresh malformado corrompeu M/A anteriores");
    }
    if (els.get("ownername").textContent !== "Marina Demo") {
      throw new Error("ownername foi alterado após refresh falho");
    }
    if (!els.get("toast").classList.contains("show") || !els.get("refresh-err-banner")) {
      throw new Error("aviso visual de erro no refresh não apareceu");
    }

    console.log("OK_SAFEURL_AND_NORMALIZE");
  } else if (mode === "inbox-bytes") {
    const { sandbox } = bootEnv({});
    const remove = sandbox.window.BRAIN_INBOX && sandbox.window.BRAIN_INBOX.originRemove;
    if (typeof remove !== "function") throw new Error("BRAIN_INBOX.originRemove ausente");

    function makeFile(name, bytes, mtime) {
      const u8 = new Uint8Array(bytes);
      return {
        name,
        size: u8.byteLength,
        lastModified: mtime,
        async arrayBuffer() { return u8.slice().buffer; },
      };
    }

    function makeHandle(dirName, fileObj) {
      const removed = [];
      return {
        name: dirName,
        removed,
        async getDirectoryHandle() { throw new Error("no subdir"); },
        async getFileHandle(n) {
          if (n !== fileObj.name) throw new Error("not found");
          return { async getFile() { return fileObj; } };
        },
        async removeEntry(n) { removed.push(n); },
      };
    }

    // Same name, same size (4 bytes), same mtime, DIFFERENT bytes -> NOT removed
    const uploaded = makeFile("nota.txt", [65, 66, 67, 68], 1700000000);
    const diffHandle = makeHandle("Downloads", makeFile("nota.txt", [65, 66, 67, 88], 1700000000));
    const resDiff = await remove([diffHandle], "nota.txt", uploaded);
    if (resDiff !== null || diffHandle.removed.length !== 0) {
      throw new Error("removeEntry chamado para arquivo com bytes diferentes");
    }

    // Same name, size, mtime, IDENTICAL bytes -> removed
    const sameHandle = makeHandle("Desktop", makeFile("nota.txt", [65, 66, 67, 68], 1700000000));
    const resSame = await remove([diffHandle, sameHandle], "nota.txt", uploaded);
    if (resSame !== "Desktop" || sameHandle.removed.length !== 1 || sameHandle.removed[0] !== "nota.txt") {
      throw new Error("removeEntry não foi chamado para arquivo idêntico");
    }

    console.log("OK_INBOX_BYTES");
  }
})();
"""


class ClientXssAndIntegrityTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.brain = _make_brain(self.tmp)
        self._old_home = os.environ.get("BRAIN_HOME")
        os.environ["BRAIN_HOME"] = str(self.tmp)
        os.environ.pop("BRAIN_NIGHTLY", None)

    def tearDown(self):
        os.environ.pop("BRAIN_NIGHTLY", None)
        if self._old_home is None:
            os.environ.pop("BRAIN_HOME", None)
        else:
            os.environ["BRAIN_HOME"] = self._old_home
        self._td.cleanup()

    def test_publish_done_and_feedback_pushed_reject_javascript_url(self):
        # Preparar publish aprovado
        report = self.brain.inst.reports / "share" / "resumo.md"
        report.write_text("# Resumo\n", encoding="utf-8")
        req_ev = self.brain.record_one({
            "type": "share.requested", "by": "agent", "prov": "sistema", "source": "chat",
            "data": {"report": "reports/share/resumo.md", "destination": "slack-canvas",
                     "content_sha": util.sha(report.read_bytes())},
        })
        pid = req_ev["id"]
        self.brain.record_one({
            "type": "share.approved", "id": pid, "by": "owner",
            "data": {"quote": "ok", "content_sha": util.sha(report.read_bytes())},
        })

        # Preparar feedback pendente
        fb_ev = feedback.add(self.brain, "bug", "Botão não abre", by="owner")
        fid = fb_ev["id"]

        bad_urls = [
            "javascript:alert(1)",
            "data:text/html,<script>1</script>",
            "vbscript:x",
            "ftp://example.com/1",
            "https://",
            "https:///path",
            "https://example.com/a b",
            "https://example.com/\n1",
            "",
        ]
        for bad in bad_urls:
            with self.subTest(bad=bad):
                with self.assertRaises(util.BrainError) as cm_pub:
                    share.cli_publish(argparse.Namespace(pbcmd="done", id=pid, link=bad), self.brain)
                self.assertEqual(cm_pub.exception.code, 4)
                self.assertIn("--link", str(cm_pub.exception))
                if bad and bad not in ("http://", "https://"):
                    self.assertNotIn(bad, str(cm_pub.exception))

                with self.assertRaises(util.BrainError) as cm_fb:
                    feedback.cli(argparse.Namespace(fbcmd="pushed", id=fid, number=7, url=bad), self.brain)
                self.assertEqual(cm_fb.exception.code, 4)
                self.assertIn("--url", str(cm_fb.exception))
                if bad and bad not in ("http://", "https://"):
                    self.assertNotIn(bad, str(cm_fb.exception))

        # URL válida passa nos dois caminhos
        with contextlib.redirect_stdout(io.StringIO()):
            share.cli_publish(
                argparse.Namespace(pbcmd="done", id=pid, link="https://example.com/1"), self.brain
            )
            feedback.cli(
                argparse.Namespace(fbcmd="pushed", id=fid, number=7, url="https://example.com/1"), self.brain
            )
        self.brain.reload()
        self.assertEqual(self.brain.state.shares[pid].status, "publicada")
        self.assertEqual(self.brain.state.shares[pid].link, "https://example.com/1")
        self.assertEqual(self.brain.state.feedbacks[fid].status, "criado")
        self.assertEqual(self.brain.state.feedbacks[fid].url, "https://example.com/1")

    def test_feedback_api_helpers_and_push_validate_returned_urls(self):
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=fake-tok-demo\n", encoding="utf-8")
        fb = feedback.add(self.brain, "sugestao", "Validar URL retornada", by="owner")
        fid = fb["id"]

        # 1. create_issue retornando html_url inválido via HTTP
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResp({"number": 42, "html_url": "javascript:alert(1)", "labels": []})):
            with self.assertRaises(util.BrainError):
                feedback.create_issue(self.brain.inst, "o/r", "t", "b", [])
            # E dentro de push(): NÃO grava feedback.pushed nem feedback.failed; avisa que pode existir + recovery hint
            with self.assertRaises(util.BrainError) as cm:
                feedback.push(self.brain, fid, approval="ok")
            msg = str(cm.exception)
            self.assertIn("pode já existir no GitHub", msg)
            self.assertIn(f"brain feedback pushed {fid} --number 42 --url", msg)
            self.assertNotIn("javascript:", msg)

        self.brain.reload()
        self.assertEqual(self.brain.state.feedbacks[fid].status, "pendente")
        self.assertEqual(len(self.brain.state.feedbacks[fid].history), 1)

        # 2. push() com create_issue mockado devolvendo URL inválida também bloqueia antes de gravar
        with mock.patch.object(feedback, "create_issue",
                               return_value={"number": 99, "url": "data:text/html,evil"}):
            with self.assertRaises(util.BrainError) as cm2:
                feedback.push(self.brain, fid, approval="ok")
            msg2 = str(cm2.exception)
            self.assertIn("pode já existir no GitHub", msg2)
            self.assertIn(f"brain feedback pushed {fid} --number 99 --url", msg2)
            self.assertNotIn("data:text/html", msg2)

        self.brain.reload()
        self.assertEqual(self.brain.state.feedbacks[fid].status, "pendente")

        # 3. add_comment / update_issue: a escrita já foi — link inválido vira vazio (não entra no ledger), não é
        #    erro. Levantar aqui deixaria a retratação sem registro com o comentário já no GitHub.
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResp({"html_url": "javascript:alert(2)"})):
            self.assertEqual(feedback.add_comment(self.brain.inst, "o/r", 1, "texto"), {"html_url": ""})
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResp({"number": 7, "html_url": "vbscript:bad", "state": "closed"})):
            res = feedback.update_issue(self.brain.inst, "o/r", 7, state="closed")
        self.assertEqual((res["number"], res["url"], res["state"]), (7, "", "closed"))

    def test_retract_is_recorded_even_if_the_api_returns_a_bad_comment_url(self):
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=fake-tok-demo\n", encoding="utf-8")
        fid = feedback.add(self.brain, "sugestao", "Retratar com link ruim", by="owner")["id"]
        self.brain.record_one({
            "type": "feedback.pushed", "id": fid, "by": "owner",
            "data": {"number": 84, "url": "https://github.com/BVLCQ/second-brain-framework/issues/84"},
        })
        with mock.patch("urllib.request.urlopen", return_value=_FakeResp({"html_url": "javascript:alert(3)"})):
            ev = feedback.retract(self.brain, fid, mode="withdraw", reason="premissa errada", by="owner")
        self.assertEqual(ev["type"], "feedback.retracted")
        # o ledger derruba valor em branco (core.py: `data` sem ""/None): o link ruim não entra, e a retratação fica
        self.assertFalse(ev["data"].get("comment_url"))
        self.brain.reload()
        self.assertEqual(self.brain.state.feedbacks[fid].status, "retratado")
        self.assertNotIn("javascript:", self.brain.ledger_path.read_text(encoding="utf-8"))

    @unittest.skipUnless(shutil.which("node"), "node ausente")
    def test_safe_url_and_normalize_brain_in_node(self):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "harness.js"
            script.write_text(NODE_HARNESS, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(script), "safeurl-and-normalize", str(DASH_HTML)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("OK_SAFEURL_AND_NORMALIZE", proc.stdout)

    @unittest.skipUnless(shutil.which("node"), "node ausente")
    def test_inbox_origin_remove_verifies_bytes_in_node(self):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "harness.js"
            script.write_text(NODE_HARNESS, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(script), "inbox-bytes", str(DASH_HTML)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")
            self.assertIn("OK_INBOX_BYTES", proc.stdout)

    def test_rebuilt_assets_match_src(self):
        spec = importlib.util.spec_from_file_location("build_assets", ROOT / "scripts" / "build_assets.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(DASH_HTML.read_text(encoding="utf-8"), mod.assemble(False, "Brain"))
        self.assertEqual(PF_HTML.read_text(encoding="utf-8"), mod.assemble(True, "Brain — Portfólio"))


if __name__ == "__main__":
    unittest.main()
