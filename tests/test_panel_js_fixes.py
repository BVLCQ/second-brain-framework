"""Testes do Chunk H (#45, #46, #47, #48, #52, #54) no modelo Python e JS compilado."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from brainlib import config, focus, model, render_portfolio  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.demo import cli as demo_cli  # noqa: E402


def _make_inst(root: Path) -> Brain:
    (root / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH", "reports"):
        (root / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (root / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Marina Demo"\n', encoding="utf-8")
    (root / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n"
        "## GOAL-1 — Operação previsível\n"
        "- status: ativo\n"
        "- horizonte: 2026-12-31\n"
        "- por quê: reduzir atrasos\n\n"
        "### PROJ-1 — Projeto Saudável\n"
        "- status: ativo\n"
        "- dono: eu\n"
        "- [ ] PROJ-1.1 Entregável futuro · prazo: 2026-11-30 · peso: 1\n\n"
        "### PROJ-2 — Projeto Crítico\n"
        "- status: ativo\n"
        "- dono: eu\n"
        "- [ ] PROJ-2.1 Entregável atrasado · prazo: 2026-10-01 · peso: 2\n\n"
        "## GOAL-2 — Meta em dia\n"
        "- status: ativo\n"
        "- horizonte: 2026-11-25\n"
        "- por quê: manter ritmo\n\n"
        "### PROJ-3 — Projeto OK\n"
        "- status: ativo\n"
        "- dono: eu\n"
        "- [ ] PROJ-3.1 Entregável em dia · prazo: 2026-11-20 · peso: 1\n",
        encoding="utf-8",
    )
    b = Brain(config.load(root))
    b.record_one({"type": "person.added", "by": "owner", "id": "eu",
                  "data": {"name": "Marina Demo", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "by": "owner", "id": "joao-test",
                  "data": {"name": "João Teste", "aliases": ["Joao"], "relation": "parceiro"}})
    return b


class PanelJsFixesTest(unittest.TestCase):
    NOW = "2026-10-19T10:00:00-03:00"

    def setUp(self):
        self.old_now = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = self.NOW
        self.addCleanup(self._restore_now)

    def _restore_now(self):
        if self.old_now is None:
            os.environ.pop("BRAIN_NOW", None)
        else:
            os.environ["BRAIN_NOW"] = self.old_now

    def test_model_agenda_sort_and_goal_health_from(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_inst(Path(td))
            # Ações em ordem inversa de ID vs horário de foco para provar ordenação por start
            a1 = b.record_one({"type": "action.opened", "by": "owner", "date": "2026-10-19",
                               "data": {"title": "Tarde", "owner": "eu", "due": "2026-10-20", "effort_min": 60, "project": "PROJ-1"}})["id"]
            a2 = b.record_one({"type": "action.opened", "by": "owner", "date": "2026-10-19",
                               "data": {"title": "Manhã", "owner": "eu", "due": "2026-10-20", "effort_min": 60, "project": "PROJ-2"}})["id"]
            b.record_one({"type": "action.opened", "by": "owner", "date": "2026-10-19",
                          "data": {"title": "Ritmo em dia", "owner": "eu", "due": "2026-10-25", "effort_min": 30, "project": "PROJ-3"}})
            b.record_one({
                "type": "focus.planned", "by": "system", "date": "2026-10-19",
                "data": {
                    "plan_file": "FRESH/focus.md",
                    "sha": "deadbeef",
                    "blocks": [
                        {"action": a1, "start": "2026-10-20T15:00:00-03:00", "end": "2026-10-20T16:00:00-03:00"},
                        {"action": a2, "start": "2026-10-20T09:00:00-03:00", "end": "2026-10-20T10:00:00-03:00"},
                    ],
                },
            })
            # Oportunidade para incluir ambos os goals no recorte de portfolio
            b.record_one({"type": "area.added", "id": "ops", "by": "owner",
                          "data": {"name": "Operações", "aliases": []}})
            b.record_one({"type": "opportunity.added", "by": "owner", "date": "2026-10-19",
                          "data": {"title": "Automatizar", "area": "ops", "kind": "melhoria-de-processo"}})
            b.record_one({"type": "opportunity.promoted", "id": "OPP-0001", "by": "owner", "date": "2026-10-19",
                          "data": {"level": "project", "goal": "GOAL-1", "project": "PROJ-2"}})

            m = model.build(b)
            day20 = [it for it in m["agenda"] if it["date"] == "2026-10-20"]
            foco_items = [it for it in day20 if it["kind"] == "foco"]
            self.assertEqual([it["id"] for it in foco_items], [a2, a1])
            self.assertEqual(foco_items[0]["start"], "2026-10-20T09:00:00-03:00")
            self.assertEqual(foco_items[1]["start"], "2026-10-20T15:00:00-03:00")
            # Foco aparece antes das ações do mesmo dia
            kinds = [it["kind"] for it in day20]
            self.assertEqual(kinds[:2], ["foco", "foco"])

            g1 = next(g for g in m["goals"] if g["id"] == "GOAL-1")
            self.assertEqual(g1["health"], "em-risco")
            self.assertEqual(g1["health_from"], "PROJ-2")
            self.assertIn("venceu", g1["health_reason"])

            g2 = next(g for g in m["goals"] if g["id"] == "GOAL-2")
            self.assertEqual(g2["health"], "em-dia")
            self.assertEqual(g2["health_from"], "PROJ-3")

            pf_payload = render_portfolio.html_payload(m)
            pf_g1 = next(g for g in pf_payload["goals"] if g["id"] == "GOAL-1")
            self.assertEqual(pf_g1["health"], "em-risco")
            self.assertEqual(pf_g1["health_from"], "PROJ-2")
            self.assertEqual(pf_g1["health_reason"], g1["health_reason"])
            self.assertTrue(all("owes_me" not in p and "i_owe" not in p and "decisions" not in p for p in pf_payload["people"]))

    def test_single_script_tag_and_asset_hygiene(self):
        for name in ("dashboard.html", "portfolio.html"):
            html = (ROOT / "brainlib" / "assets" / name).read_text(encoding="utf-8")
            self.assertEqual(len(html.split("<script>")), 2, f"{name} deve ter exatamente 1 bloco <script>")
            self.assertEqual(len(html.split("</script>")), 3, f"{name} deve ter exatamente </script> do __DATA__ e do script único")

        extra_src = (ROOT / "brainlib" / "assets" / "src" / "extra.js").read_text(encoding="utf-8")
        for internal in ("goalReasonChip", "normalizeBrain", "fmtDL", "dueTxt", "actionTable"):
            self.assertNotIn(internal, extra_src)

    def test_node_compiled_js_all_fixes(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node ausente no ambiente")

        with tempfile.TemporaryDirectory() as td:
            inst_dir = Path(td) / "demo"
            with contextlib.redirect_stdout(io.StringIO()):
                demo_cli(argparse.Namespace(dir=str(inst_dir), open=False))
            b = Brain(config.load(inst_dir))
            m = model.build(b)
            # Ajusta cenários explícitos no payload mantendo estrutura real do demo
            m["update"] = {"version": "2.0.0", "remote_version": "2.0.0", "behind": 0,
                           "checked": True, "checked_at": "2026-10-19T05:30:00-03:00", "news": ["Nota demo"]}
            m["agenda"] = [
                {"date": m["today"], "kind": "ação", "id": "TASK-0099", "title": "Ação do dia", "project": m["projects"][0]["id"], "overdue_days": 0, "status": "aberta"},
                {"date": m["today"], "kind": "foco", "id": "TASK-0009", "start": m["today"] + "T14:00:00-03:00", "title": "14:00–15:00 · Bloco tarde", "project": None, "overdue_days": 0, "status": "proposto"},
                {"date": m["today"], "kind": "foco", "id": "TASK-0001", "start": m["today"] + "T08:30:00-03:00", "title": "08:30–09:30 · Bloco manhã", "project": None, "overdue_days": 0, "status": "proposto"},
                {"date": m["today"], "kind": "foco", "id": "TASK-0005", "title": "11:00–12:00 · Bloco fallback", "project": None, "overdue_days": 0, "status": "proposto"},
            ]
            m["focus"] = {
                "id": "FOCUS-0001", "status": "proposto", "mode": "ics", "quote": "",
                "blocks": [
                    {"action": m["actions"][0]["id"], "start": m["today"] + "T15:00:00-03:00", "end": m["today"] + "T16:30:00-03:00"},
                    {"action": m["actions"][0]["id"], "start": m["today"] + "T09:00:00-03:00", "end": m["today"] + "T10:00:00-03:00"},
                ],
                "applied": [], "plan_file": "FRESH/focus.md", "at_risk": [], "missing_effort": [], "consumed": [],
                "horizon": {"days": 7}, "busy": [
                    {"start": m["today"] + "T13:00:00-03:00", "end": m["today"] + "T14:00:00-03:00", "title": "Almoço tarde"},
                    {"start": m["today"] + "T08:00:00-03:00", "end": m["today"] + "T08:30:00-03:00", "title": "Standup manhã"},
                ],
                "created": m["today"],
            }
            # Garante ao menos um goal com health != em-dia e health_from e um em-dia
            m["goals"][0]["horizon"] = "2026-12-31"
            m["goals"][0]["health"] = "em-risco"
            m["goals"][0]["health_label"] = "em risco"
            m["goals"][0]["health_from"] = m["goals"][0]["projects"][0]
            m["goals"][0]["health_reason"] = "entregável vencido"
            if len(m["goals"]) > 1:
                m["goals"][1]["health"] = "em-dia"
                m["goals"][1]["health_label"] = "em dia"
                m["goals"][1]["health_from"] = m["goals"][1]["projects"][0] if m["goals"][1]["projects"] else None
                m["goals"][1]["health_reason"] = "tudo ok"

            pf_payload = render_portfolio.html_payload(m)

        dash_html = (ROOT / "brainlib" / "assets" / "dashboard.html").read_text(encoding="utf-8")
        compiled_js = dash_html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        port_html = (ROOT / "brainlib" / "assets" / "portfolio.html").read_text(encoding="utf-8")
        compiled_pf_js = port_html.split("<script>", 1)[1].rsplit("</script>", 1)[0]

        runner = r"""
const fs = require("fs");
const payload = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const pfPayload = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const compiled = fs.readFileSync(process.argv[4], "utf8");
const compiledPf = fs.readFileSync(process.argv[5], "utf8");

function makeDom(platformStr, initPayload, jsSrc, initHash) {
  const els = new Map();
  const docListeners = new Map();
  const winListeners = new Map();
  let scrolled = [];
  const timers = [];

  function makeClassList(el) {
    const set = new Set();
    return {
      add(...xs) { xs.forEach(x => set.add(x)); el._refreshClass(); },
      remove(...xs) { xs.forEach(x => set.delete(x)); el._refreshClass(); },
      toggle(x, force) {
        const on = force !== undefined ? !!force : !set.has(x);
        if (on) set.add(x); else set.delete(x);
        el._refreshClass();
        return on;
      },
      contains(x) { return set.has(x); },
      _set: set,
    };
  }
  function makeEl(id, tag) {
    const el = {
      id: id || "", tagName: (tag || "DIV").toUpperCase(),
      innerHTML: "", textContent: "", value: "", hidden: false, style: {}, dataset: {},
      children: [],
      _attrs: {},
      _refreshClass() { this.className = Array.from(this.classList._set).join(" "); },
      addEventListener(ev, fn) { (this._ev[ev] = this._ev[ev] || []).push(fn); },
      removeEventListener() {},
      dispatchEvent() {},
      querySelector(sel) {
        if (sel === "b" && this.id === "openpal") return openpalB;
        if (sel === "h2 .count, h3 .count" || sel === "h3 .count") return countEl;
        return makeEl("", "SPAN");
      },
      querySelectorAll() { return []; },
      closest() { return null; },
      focus() {}, select() {}, remove() { el.removed = true; },
      appendChild(c) { this.children.push(c); return c; },
      prepend() {},
      setAttribute(k, v) { this._attrs[k] = String(v); },
      hasAttribute(k) { return k in this._attrs; },
      scrollIntoView(opts) { scrolled.push({id: this.id, opts}); },
      _ev: {},
    };
    el.classList = makeClassList(el);
    if (id) els.set(id, el);
    return el;
  }

  const openpalB = makeEl("", "B");
  openpalB.textContent = "⌘K";
  const openpal = makeEl("openpal", "BUTTON");
  const view = makeEl("view", "DIV");
  const palback = makeEl("palback", "DIV");
  const newsback = makeEl("newsback", "DIV");
  const newsshow = makeEl("newshow", "SPAN");
  const newstitle = makeEl("newstitle", "B");
  const newslist = makeEl("newslist", "DIV");
  const verbadge = makeEl("verbadge", "BUTTON");
  const newsclose = makeEl("newsclose", "BUTTON");
  const countEl = makeEl("", "SPAN");
  countEl.textContent = "3";
  const firstProjId = (initPayload.goals[0] && initPayload.goals[0].projects && initPayload.goals[0].projects[0]) || "PROJ-1";
  const projCardEl = makeEl("proj-" + firstProjId, "SECTION");

  const bodyChildren = [];
  const doc = {
    getElementById(id) {
      if (id === "data") return { textContent: JSON.stringify(initPayload) };
      if (id === "kbar" || id === "lfbar") return els.get(id) || null;
      if (els.has(id)) return els.get(id);
      return makeEl(id, "DIV");
    },
    querySelector(sel) {
      if (sel === "#openpal b") return openpalB;
      if (sel === "#openpal") return openpal;
      if (sel === ".pal-back.open") return null;
      if (sel === ".dd.open") return null;
      if (sel.startsWith("#")) return doc.getElementById(sel.slice(1));
      return makeEl("", "DIV");
    },
    querySelectorAll(sel) {
      if (sel === "#view .col") return [{
        querySelector: s => (s.includes("h2 .count") ? countEl : null),
        querySelectorAll: () => [],
      }];
      return [];
    },
    addEventListener(ev, fn, cap) {
      (docListeners.get(ev) || docListeners.set(ev, []).get(ev)).push({fn, cap: !!cap});
    },
    removeEventListener() {},
    createElement(tag) { return makeEl("", tag); },
    body: {
      appendChild(c) { bodyChildren.push(c); return c; },
      classList: makeClassList({ _refreshClass() {} }),
    },
    documentElement: { dataset: {} },
    activeElement: { tagName: "BODY" },
  };
  const win = {
    location: { hash: initHash || "#home", protocol: "file:", hostname: "", pathname: "/", search: "" },
    localStorage: { _m: {}, getItem(k) { return this._m[k] || null; }, setItem(k, v) { this._m[k] = String(v); } },
    sessionStorage: { _m: {}, getItem(k) { return this._m[k] || null; }, setItem(k, v) { this._m[k] = String(v); }, removeItem(k) { delete this._m[k]; } },
    history: { replaceState() {} },
    matchMedia: () => ({ matches: false }),
    scrollTo() {},
    addEventListener(ev, fn, cap) {
      (winListeners.get(ev) || winListeners.set(ev, []).get(ev)).push({fn, cap: !!cap});
    },
    setTimeout(fn) { timers.push(fn); return timers.length; },
    clearTimeout() {},
  };
  const nav = { platform: platformStr, userAgent: platformStr };

  const fn = new Function(
    "window", "document", "location", "localStorage", "sessionStorage",
    "history", "matchMedia", "navigator", "setTimeout", "clearTimeout",
    jsSrc + "\nreturn window.BRAIN;"
  );
  const BRAIN = fn(win, doc, win.location, win.localStorage, win.sessionStorage, win.history, win.matchMedia, nav, win.setTimeout, win.clearTimeout);
  return {BRAIN, win, flushTimers: () => { while (timers.length) timers.shift()(); }, winListeners, docListeners, els, openpalB, bodyChildren, scrolled, verbadge, newsshow, countEl, projCardEl};
}

// 1. Execução no Mac
const mac = makeDom("MacIntel", payload, compiled, "#home");
const homeHtml = mac.BRAIN.V.home();
const focusHtml = mac.BRAIN.V.focus();
const projectsHtml = mac.BRAIN.V.projects(new URLSearchParams("focus=" + payload.goals[0].projects[0]));
mac.flushTimers();
const peopleFullHtml = mac.BRAIN.V.people();

// Clique em a[data-proj-jump] já estando em #projects
mac.win.location.hash = "#projects";
const jumpLink = { dataset: { projJump: payload.goals[0].projects[0] } };
let jumpPrevented = false;
(mac.docListeners.get("click") || []).forEach(({fn}) => fn({
  target: { closest: sel => sel === "a[data-proj-jump]" ? jumpLink : null },
  preventDefault() { jumpPrevented = true; },
}));

// Dispara verbadge click para testar fmtDL(u.checked_at)
mac.verbadge._ev.click.forEach(fn => fn());

// Simula clique em ? para inspecionar helpOverlay
const kbar = mac.bodyChildren.find(c => c.id === "kbar");
const helpBtnTitle = kbar.innerHTML.match(/data-g="g" title="([^"]+)"/)[1];
const helpClicks = mac.docListeners.get("keydown") || [];
// Dispara key '?' para abrir helpOverlay
helpClicks.forEach(({fn}) => fn({key: "?", target: {tagName: "BODY"}, preventDefault(){}}));
const helpOv = mac.bodyChildren.find(c => (c.innerHTML || "").includes("Teclas — as mesmas da TUI"));

// Simula filtro "/" (lfApply deve encontrar h2 .count)
mac.win.location.hash = "#todo";
helpClicks.forEach(({fn}) => fn({key: "/", target: {tagName: "BODY"}, preventDefault(){}}));
const todoCountAfterFilter = mac.countEl.textContent;

// Simula capture Ctrl/Meta+K (mesmo em input focado)
const capKey = (mac.winListeners.get("keydown") || []).filter(x => x.cap);
let prevented = 0, stopped = 0;
const ev1 = {metaKey: true, ctrlKey: false, altKey: false, key: "k", code: "KeyK", target: {tagName: "INPUT"}, preventDefault(){prevented++;}, stopPropagation(){stopped++;}};
capKey.forEach(({fn}) => fn(ev1));
const openAfterFirst = mac.els.get("palback").classList.contains("open");
const ev2 = {metaKey: true, ctrlKey: false, altKey: false, key: "k", code: "KeyK", target: {tagName: "INPUT"}, preventDefault(){prevented++;}, stopPropagation(){stopped++;}};
capKey.forEach(({fn}) => fn(ev2));
const openAfterSecond = mac.els.get("palback").classList.contains("open");
const evAlt = {metaKey: false, ctrlKey: true, altKey: true, key: "k", code: "KeyK", target: {tagName: "BODY"}, preventDefault(){prevented++;}, stopPropagation(){stopped++;}};
capKey.forEach(({fn}) => fn(evAlt));
const openAfterAlt = mac.els.get("palback").classList.contains("open");

// Sweep de todas as views (heading order + "undefined")
const viewCalls = [
  ["home", []],
  ["todo", [new URLSearchParams("")]],
  ["projects", [new URLSearchParams("")]],
  ["project", [new URLSearchParams(""), payload.projects[0].id]],
  ["decisions", [new URLSearchParams("")]],
  ["wins", []],
  ["people", []],
  ["person", [new URLSearchParams(""), payload.people[0].id]],
  ["timeline", []],
  ["focus", []],
  ["outbox", [new URLSearchParams("")]],
  ["feedback", [new URLSearchParams("")]],
  ["health", []],
  ["cfg/saude", []],
  ["cfg/inicio", []],
  ["cfg/memoria", []],
  ["action", [new URLSearchParams(""), payload.actions[0].id]],
  ["decision", [new URLSearchParams(""), payload.decisions[0].id]],
  ["search", [new URLSearchParams("q=teste")]],
  ["sources", []],
  ["pf/visao", []],
  ["pf/opps", [new URLSearchParams("")]],
  ["pf/matrix", []],
  ["pf/procs", [new URLSearchParams("")]],
  ["pf/areas", []],
  ["pf/area", [new URLSearchParams(""), payload.portfolio.areas[0].id]],
  ["pf/opp", [new URLSearchParams(""), payload.portfolio.opportunities[0].id]],
  ["pf/docs", []],
  ["ask", [new URLSearchParams("")]],
];
const sweep = {};
for (const [name, args] of viewCalls) {
  const html = mac.BRAIN.V[name](...args);
  const headings = [...html.matchAll(/<h([1-6])\b/g)].map(m => +m[1]);
  sweep[name] = {
    hasUndefined: /\bundefined\b/.test(html),
    headings,
  };
}

// 2. Execução no Linux (rótulo Ctrl K) + payload standalone de portfolio (Pessoas com travessão)
const lin = makeDom("Linux x86_64", pfPayload, compiledPf, "#people");
const linKbar = lin.bodyChildren.find(c => c.id === "kbar");
const linHelpBtnTitle = linKbar.innerHTML.match(/data-g="g" title="([^"]+)"/)[1];
(lin.docListeners.get("keydown") || []).forEach(({fn}) => fn({key: "?", target: {tagName: "BODY"}, preventDefault(){}}));
const linHelpOv = lin.bodyChildren.find(c => (c.innerHTML || "").includes("Teclas — as mesmas da TUI"));
const peoplePfHtml = lin.BRAIN.V.people();
const decisionsPfHtml = lin.BRAIN.V.decisions(new URLSearchParams(""));
const personPfHtml = lin.BRAIN.V.person(new URLSearchParams(""), pfPayload.people[0].id);

console.log(JSON.stringify({
  macKbtn: mac.openpalB.textContent,
  macKeybarTitle: helpBtnTitle,
  macHelpHasKmod: (helpOv.innerHTML || "").includes("g : ⌘K"),
  linKbtn: lin.openpalB.textContent,
  linKeybarTitle: linHelpBtnTitle,
  linHelpHasKmod: (linHelpOv.innerHTML || "").includes("g : Ctrl K"),
  capListenersCount: capKey.length,
  prevented, stopped, openAfterFirst, openAfterSecond, openAfterAlt,
  homeHtml, focusHtml, projectsHtml,
  scrolled: mac.scrolled,
  jumpPrevented,
  todoCountAfterFilter,
  projCardJustMoved: mac.projCardEl.classList.contains("just-moved"),
  newsshow: mac.newsshow.textContent,
  peopleFullHtml, peoplePfHtml, decisionsPfHtml, personPfHtml,
  sweep,
}));
"""

        with tempfile.TemporaryDirectory() as td:
            p_full = Path(td) / "full.json"
            p_pf = Path(td) / "pf.json"
            p_js = Path(td) / "compiled.js"
            p_pfjs = Path(td) / "compiled_pf.js"
            p_run = Path(td) / "run.js"
            p_full.write_text(json.dumps(m, default=str), encoding="utf-8")
            p_pf.write_text(json.dumps(pf_payload, default=str), encoding="utf-8")
            p_js.write_text(compiled_js, encoding="utf-8")
            p_pfjs.write_text(compiled_pf_js, encoding="utf-8")
            p_run.write_text(runner, encoding="utf-8")

            proc = subprocess.run([node, str(p_run), str(p_full), str(p_pf), str(p_js), str(p_pfjs)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"Node falhou:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
            res = json.loads(proc.stdout)

        # #47: rótulos e capture handler
        self.assertEqual(res["macKbtn"], "⌘K")
        self.assertEqual(res["macKeybarTitle"], "paleta de busca e comandos (⌘K)")
        self.assertTrue(res["macHelpHasKmod"])
        self.assertEqual(res["linKbtn"], "Ctrl K")
        self.assertEqual(res["linKeybarTitle"], "paleta de busca e comandos (Ctrl K)")
        self.assertTrue(res["linHelpHasKmod"])
        self.assertEqual(res["capListenersCount"], 1)
        self.assertEqual(res["prevented"], 2)
        self.assertEqual(res["stopped"], 2)
        self.assertTrue(res["openAfterFirst"])
        self.assertFalse(res["openAfterSecond"])
        self.assertFalse(res["openAfterAlt"])

        # #46: datas dd/mm/aaaa
        self.assertIn("horizonte 31/12/2026", res["homeHtml"])
        self.assertNotIn("horizonte 2026-12-31", res["homeHtml"])
        self.assertIn("verificado 19/10/2026", res["newsshow"])
        self.assertNotIn("verificado 2026-10-19", res["newsshow"])

        # #45: ordem cronológica dos blocos na home e no focus + minmax(108px,1fr)
        home = res["homeHtml"]
        idx_m = home.find("08:30–09:30")
        idx_f = home.find("11:00–12:00")
        idx_t = home.find("14:00–15:00")
        idx_a = home.find("Ação do dia")
        self.assertTrue(0 <= idx_m < idx_f < idx_t < idx_a, f"ordem home inválida: {idx_m}, {idx_f}, {idx_t}, {idx_a}")

        foc = res["focusHtml"]
        self.assertIn("minmax(108px,1fr)", foc)
        self.assertLess(foc.find("08:00–08:30"), foc.find("13:00–14:00"))
        self.assertLess(foc.find("09:00–10:00"), foc.find("15:00–16:30"))

        # #54: mini-chip âncora no goal e jump em #projects
        self.assertIn('class="chip h-reason"', home)
        self.assertIn('href="#projects?focus=' + m["goals"][0]["projects"][0] + '"', home)
        self.assertIn("↳ " + m["goals"][0]["projects"][0] + " · entregável vencido", home)
        if len(m["goals"]) > 1:
            self.assertNotIn("tudo ok", home)
        self.assertIn('id="proj-' + m["goals"][0]["projects"][0] + '"', res["projectsHtml"])
        self.assertIn('class="chip h-reason"', res["projectsHtml"])
        self.assertEqual(len(res["scrolled"]), 2)
        self.assertEqual(res["scrolled"][0]["id"], "proj-" + m["goals"][0]["projects"][0])
        self.assertEqual(res["scrolled"][1]["id"], "proj-" + m["goals"][0]["projects"][0])
        self.assertTrue(res["jumpPrevented"])
        self.assertEqual(res["todoCountAfterFilter"], "3")
        self.assertTrue(res["projCardJustMoved"])

        # #52: Pessoas com 0 no completo e "—" no standalone portfolio
        self.assertIn('<td class="num">0</td>', res["peopleFullHtml"])
        self.assertNotIn('<td class="num">—</td>', res["peopleFullHtml"])
        self.assertIn('<td class="num">—</td>', res["peoplePfHtml"])
        self.assertNotIn('<td class="num">0</td>', res["peoplePfHtml"])
        self.assertNotIn("undefined", res["decisionsPfHtml"])
        self.assertNotIn("undefined", res["personPfHtml"])

        # #48: sweep de headings e "undefined" em todas as views
        for vname, info in res["sweep"].items():
            self.assertFalse(info["hasUndefined"], f"view {vname} contém 'undefined'")
            hs = info["headings"]
            self.assertTrue(hs and hs[0] == 1, f"view {vname} deve iniciar com h1: {hs}")
            for i in range(1, len(hs)):
                self.assertLessEqual(hs[i], hs[i - 1] + 1, f"view {vname} pulou nível de heading: {hs}")
        for h2_view in ("todo", "focus", "pf/opps", "pf/matrix"):
            hs = res["sweep"][h2_view]["headings"]
            self.assertEqual(hs[1], 2, f"view {h2_view} deve ter h2 logo após h1: {hs}")


if __name__ == "__main__":
    unittest.main()
