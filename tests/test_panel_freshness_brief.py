"""Testes do Chunk 3 — Pílula e faixa de frescor + cartão 'Seu dia' (#57w2 + #60w2)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, doctor, notes, render, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _make_demo_inst(root: Path) -> Brain:
    (root / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED/_ledger", "FRESH", "logs", "reports"):
        (root / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (root / "config" / "brain.toml").write_text(
        '[owner]\nid = "marina-demo"\nname = "Marina Demo"\n'
        '[owner.extra]\norg = "Padaria Pão Quente"\nemail = "marina-demo@x.com"\n',
        encoding="utf-8",
    )
    (root / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n"
        "## GOAL-1 — Padaria previsível\n"
        "- status: ativo\n"
        "- horizonte: 2026-12-31\n"
        "- por quê: reduzir desperdício de massa\n\n"
        "### PROJ-1 — Fornada da manhã\n"
        "- status: ativo\n"
        "- dono: marina-demo\n"
        "- [ ] PROJ-1.1 Ajustar escala · prazo: 2026-11-15 · peso: 1\n",
        encoding="utf-8",
    )
    (root / "vault" / "PROCESSED" / "_ledger" / "events.jsonl").write_text("", encoding="utf-8")
    b = Brain(config.load(root))
    b.record_one({
        "type": "person.added",
        "id": "marina-demo",
        "by": "owner",
        "data": {"name": "Marina Demo", "email": "marina-demo@x.com", "aliases": ["Marina"], "relation": "dono"},
    })
    return b


def _extract_embedded_model(html: str) -> dict:
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    assert m, "script#data não encontrado no HTML renderizado"
    return json.loads(m.group(1))


class PanelFreshnessBriefTests(unittest.TestCase):
    def setUp(self):
        self.old_now = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = "2026-10-09T10:00:00-03:00"
        self.addCleanup(self._restore_now)

    def _restore_now(self):
        if self.old_now is None:
            os.environ.pop("BRAIN_NOW", None)
        else:
            os.environ["BRAIN_NOW"] = self.old_now

    def test_render_home_embeds_freshness_e_daily_brief_fresco(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_demo_inst(Path(td))
            b.record_one({
                "type": "artifact.added",
                "id": "PROCESSED/2026/10/fornada.md",
                "by": "agent",
                "prov": "observado",
                "source": "RAW/2026/10/notes/fornada.md",
                "data": {"kind": "nota", "title": "Fornada", "raw": "RAW/2026/10/notes/fornada.md"},
            })
            notes.write_note(b, "brief", "Padaria Pão Quente: escala fechada para amanhã.", kind="brief", empty=False)
            render.render_all(b, do_harvest=False)
            # Segundo render reflete o .render-state.json recém-gravado no payload HTML embutido
            render.render_all(b, do_harvest=False)

            m = render.view_model(b)
            self.assertFalse(any(m["freshness"]["stale"].values()), m["freshness"]["stale"])
            self.assertTrue(m["daily_brief"]["exists"])
            self.assertTrue(m["daily_brief"]["is_today"])
            self.assertFalse(m["daily_brief"]["empty"])
            self.assertEqual(m["daily_brief"]["text"], "Padaria Pão Quente: escala fechada para amanhã.")

            html = (b.inst.fresh / "dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="freshbadge"', html)
            embedded = _extract_embedded_model(html)
            self.assertEqual(embedded["freshness"]["stale"], m["freshness"]["stale"])
            self.assertEqual(embedded["daily_brief"], m["daily_brief"])

    def test_render_freshness_envelhecido_ativa_flags_do_payload(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_demo_inst(Path(td))
            base_now = util.now()
            ev = b.record_one({
                "type": "artifact.added",
                "id": "PROCESSED/2026/10/antigo.md",
                "by": "agent",
                "prov": "observado",
                "source": "RAW/2026/10/notes/antigo.md",
                "data": {"kind": "nota", "title": "Nota antiga", "raw": "RAW/2026/10/notes/antigo.md"},
            })
            old_dump_ts = (base_now - timedelta(hours=80)).isoformat(timespec="seconds")
            rows = []
            for ln in b.ledger_path.read_text(encoding="utf-8").splitlines():
                row = json.loads(ln)
                if row.get("seq") == ev["seq"]:
                    row["ts"] = old_dump_ts
                rows.append(json.dumps(row, ensure_ascii=False))
            b.ledger_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            b.reload()

            old_render_ts = (base_now - timedelta(hours=75)).isoformat(timespec="seconds")
            util.write_json(b.inst.fresh / ".render-state.json", {
                "rendered_at": old_render_ts,
                "todo": {},
                "records": {},
            })
            inbox_item = b.inst.inbox / "pedido-farinha.md"
            inbox_item.write_text("Pedido pendente", encoding="utf-8")
            old_mtime = (base_now - timedelta(hours=50)).timestamp()
            os.utime(inbox_item, (old_mtime, old_mtime))

            m = render.view_model(b)
            self.assertTrue(m["freshness"]["stale"]["dump"])
            self.assertTrue(m["freshness"]["stale"]["render"])
            self.assertTrue(m["freshness"]["stale"]["inbox"])
            self.assertEqual(m["freshness"]["thresholds"], doctor.FRESHNESS_THRESHOLDS)
            self.assertAlmostEqual(m["freshness"]["last_dump_age_h"], 80.0, places=1)
            self.assertAlmostEqual(m["freshness"]["last_render_age_h"], 75.0, places=1)

            # Gera o HTML preservando o .render-state.json envelhecido para conferir o payload embutido
            html = render.render_html(m)
            embedded = _extract_embedded_model(html)
            self.assertTrue(embedded["freshness"]["stale"]["render"])
            self.assertTrue(embedded["freshness"]["stale"]["dump"])
            self.assertEqual(embedded["freshness"]["thresholds"], doctor.FRESHNESS_THRESHOLDS)

    def test_normalize_brain_tem_defaults_para_freshness_e_daily_brief(self):
        core_js = (ROOT / "brainlib" / "assets" / "src" / "core.js").read_text(encoding="utf-8")
        m = re.search(r"function normalizeBrain\(m\)\{(.*?)\n\}", core_js, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("m.freshness", body)
        for key in ("last_dump_age_h", "last_render_age_h", "last_memory_sync_age_h", "inbox_backlog", "inbox_oldest_age_h", "stale", "thresholds"):
            self.assertIn(key, body)
        self.assertIn("m.daily_brief", body)
        for key in ("exists", "is_today", "date", "generated_at", "empty", "text"):
            self.assertIn(key, body)

    def test_js_sem_constantes_de_limiar_nem_brain_update_literal(self):
        core_js = (ROOT / "brainlib" / "assets" / "src" / "core.js").read_text(encoding="utf-8")
        extra_js = (ROOT / "brainlib" / "assets" / "src" / "extra.js").read_text(encoding="utf-8")

        self.assertIn("M.freshness", core_js)
        self.assertIn("f.thresholds", core_js)
        self.assertIn("f.stale", core_js)
        self.assertIn('"brain.freshness.dismissed"', core_js)
        self.assertIn('data-brain-update="1"', core_js)
        self.assertIn('go("cfg/saude")', core_js)
        self.assertNotIn("brain update", core_js)
        self.assertNotIn("brain update", extra_js)

        for name in ("dashboard.html", "portfolio.html"):
            built = (ROOT / "brainlib" / "assets" / name).read_text(encoding="utf-8")
            self.assertNotIn("brain update", built, name)

        fn_match = re.search(r"function freshnessSummary\(f\)\{(.*?)\n\}", core_js, re.S)
        self.assertIsNotNone(fn_match)
        fn_body = fn_match.group(1)
        self.assertNotRegex(fn_body, r"\b(26|48)\b", "freshnessSummary não pode hardcodar limiares do doctor")

        for forbidden in ("freshnessSummary", "renderDailyBrief", "renderFreshBanner", "normalizeBrain"):
            self.assertNotIn(forbidden, extra_js)
        self.assertNotRegex(extra_js, r"\b(?:FACES|V\[)")

    @unittest.skipUnless(shutil.which("node"), "node ausente no ambiente")
    def test_core_js_logica_freshness_e_brief_via_node(self):
        node = shutil.which("node")
        with tempfile.TemporaryDirectory() as td:
            b = _make_demo_inst(Path(td) / "inst")
            b.record_one({
                "type": "artifact.added",
                "id": "PROCESSED/2026/10/ok.md",
                "by": "agent",
                "prov": "observado",
                "source": "RAW/2026/10/notes/ok.md",
                "data": {"kind": "nota", "title": "Nota", "raw": "RAW/2026/10/notes/ok.md"},
            })
            notes.write_note(b, "brief", "Foco na fornada.<script>alert(1)</script>", kind="brief", empty=False)
            render.render_all(b, do_harvest=False)
            render.render_all(b, do_harvest=False)
            m = render.view_model(b)
            m["onboarding"] = {"needed": False}

        dash_html = (ROOT / "brainlib" / "assets" / "dashboard.html").read_text(encoding="utf-8")
        compiled_js = dash_html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        port_html = (ROOT / "brainlib" / "assets" / "portfolio.html").read_text(encoding="utf-8")
        compiled_pf_js = port_html.split("<script>", 1)[1].rsplit("</script>", 1)[0]

        script = r"""
const fs = require("fs");
const vm = require("vm");
const baseModel = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const compiledJs = fs.readFileSync(process.argv[3], "utf8");
const compiledPfJs = fs.readFileSync(process.argv[4], "utf8");

function boot(model, jsSrc) {
  const els = new Map();
  const store = {};
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
      innerHTML: "", textContent: "", value: "", hidden: id === "freshbadge" || id === "newsback",
      style: {}, dataset: {}, children: [], _ev: {},
      addEventListener(ev, fn) { (this._ev[ev] = this._ev[ev] || []).push(fn); },
      removeEventListener() {},
      querySelector() { return makeEl("", "SPAN"); },
      querySelectorAll() { return []; },
      closest() { return null; },
      focus() {}, select() {}, remove() { el.removed = true; },
      appendChild(c) { this.children.push(c); return c; }, prepend() {},
      setAttribute() {}, hasAttribute() { return false; },
    };
    el.classList = makeClassList(el);
    if (id) els.set(id, el);
    return el;
  }
  const view = makeEl("view", "DIV");
  const freshbadge = makeEl("freshbadge", "BUTTON");
  const verbadge = makeEl("verbadge", "BUTTON");
  const freshHealthBtn = makeEl("fresh-health-btn", "BUTTON");
  const freshDismissBtn = makeEl("fresh-dismiss-btn", "BUTTON");
  const freshBannerEl = makeEl("freshbanner", "SECTION");
  const timers = [];

  const doc = {
    getElementById(id) {
      if (id === "data") return { textContent: JSON.stringify(model) };
      if (els.has(id)) return els.get(id);
      return makeEl(id, "DIV");
    },
    querySelector(sel) {
      if (sel === "#fresh-health-btn") return freshHealthBtn;
      if (sel === "#fresh-dismiss-btn") return freshDismissBtn;
      if (sel === "#freshbanner") return freshBannerEl;
      if (sel === ".pal-back.open" || sel === ".dd.open") return null;
      if (sel.startsWith("#")) return doc.getElementById(sel.slice(1));
      return makeEl("", "DIV");
    },
    querySelectorAll() { return []; },
    addEventListener() {}, removeEventListener() {},
    createElement(tag) { return makeEl("", tag); },
    body: { appendChild(c) { return c; }, classList: makeClassList({}) },
    documentElement: { dataset: {} },
    activeElement: { tagName: "BODY" },
  };
  const win = {
    document: doc,
    location: { hash: "#home", protocol: "file:", hostname: "", pathname: "/", search: "" },
    localStorage: {
      getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
      setItem(k, v) { store[k] = String(v); },
      removeItem(k) { delete store[k]; },
    },
    sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    history: { replaceState() {} },
    matchMedia: () => ({ matches: false }),
    navigator: { platform: "Linux x86_64", userAgent: "Linux" },
    scrollTo() {},
    addEventListener() {},
    setTimeout(fn) { timers.push(fn); return timers.length; },
    clearTimeout() {},
    URLSearchParams,
    CustomEvent: function(name, opts) { this.type = name; this.detail = opts && opts.detail; },
  };
  win.window = win;
  win.globalThis = win;
  vm.runInNewContext(jsSrc, win);
  const BRAIN = win.BRAIN;
  const flush = () => { while (timers.length) timers.shift()(); };
  return { BRAIN, win, store, view, freshbadge, freshHealthBtn, freshDismissBtn, freshBannerEl, flush };
}

// 1. Fresco hoje + brief com XSS escapado
const c1 = boot(baseModel, compiledJs);
const htmlFresh = c1.view.innerHTML;
const badgeFresh = {
  hidden: c1.freshbadge.hidden,
  text: c1.freshbadge.textContent,
  ok: c1.freshbadge.classList.contains("fresh-ok"),
  warn: c1.freshbadge.classList.contains("fresh-warn"),
  title: c1.freshbadge.title,
};

// 2. Refresh com 3 dias de atraso -> atualiza #freshbadge e exibe banner
const m3d = JSON.parse(JSON.stringify(baseModel));
m3d.freshness.last_dump_age_h = 75;
m3d.freshness.last_render_age_h = 10;
m3d.freshness.stale = { dump: true, render: false, memory_sync: false, inbox: false };
c1.BRAIN.refresh(m3d);
c1.flush();
const html3d = c1.view.innerHTML;
const badge3d = {
  hidden: c1.freshbadge.hidden,
  text: c1.freshbadge.textContent,
  ok: c1.freshbadge.classList.contains("fresh-ok"),
  warn: c1.freshbadge.classList.contains("fresh-warn"),
};

// 3. Clique em Dispensar hoje persiste localStorage e suprime banner no mesmo dia
c1.freshDismissBtn.onclick();
const dismissedVal = c1.store["brain.freshness.dismissed"];
const bannerRemoved = !!c1.freshBannerEl.removed;
const htmlAfterDismiss = c1.BRAIN.V.home();
const mNextDay = JSON.parse(JSON.stringify(m3d));
mNextDay.today = "2026-10-10";
c1.BRAIN.refresh(mNextDay);
const htmlNextDay = c1.view.innerHTML;

// 4. Clique no badge e no #fresh-health-btn navegam para #cfg/saude
c1.win.location.hash = "#home";
c1.freshbadge._ev.click.forEach(fn => fn());
const hashAfterBadge = c1.win.location.hash;
c1.win.location.hash = "#home";
c1.flush();
c1.freshHealthBtn.onclick();
const hashAfterBtn = c1.win.location.hash;

// 5. Demais faixas: ontem, <24h stale, apenas inbox stale, e estados de daily_brief
delete c1.store["brain.freshness.dismissed"];
const mOntem = JSON.parse(JSON.stringify(baseModel));
mOntem.freshness.last_dump_age_h = 30;
mOntem.freshness.stale = { dump: false, render: true, memory_sync: false, inbox: false };
mOntem.daily_brief = { exists: true, is_today: true, date: "2026-10-09", generated_at: null, empty: true, text: "Sem novidades desde a última atualização." };
c1.BRAIN.refresh(mOntem);
const badgeOntem = c1.freshbadge.textContent;
const htmlBriefQuietToday = c1.view.innerHTML;

const m20h = JSON.parse(JSON.stringify(baseModel));
m20h.freshness.last_dump_age_h = 5;
m20h.freshness.last_render_age_h = 20;
m20h.freshness.stale = { dump: false, render: true, memory_sync: false, inbox: false };
m20h.daily_brief = { exists: true, is_today: false, date: "2026-10-08", generated_at: null, empty: false, text: "Ontem" };
c1.BRAIN.refresh(m20h);
const badge20h = c1.freshbadge.textContent;
const htmlBriefStaleDate = c1.view.innerHTML;

const mInboxOnly = JSON.parse(JSON.stringify(baseModel));
mInboxOnly.freshness.last_dump_age_h = 2;
mInboxOnly.freshness.last_render_age_h = 1;
mInboxOnly.freshness.inbox_backlog = 3;
mInboxOnly.freshness.inbox_oldest_age_h = 60;
mInboxOnly.freshness.stale = { dump: false, render: false, memory_sync: false, inbox: true };
mInboxOnly.daily_brief = { exists: false, is_today: false, date: null, generated_at: null, empty: false, text: "" };
c1.BRAIN.refresh(mInboxOnly);
const badgeInboxOnly = c1.freshbadge.textContent;
const htmlBriefMissing = c1.view.innerHTML;

// 6. Portfolio standalone (PF_ONLY=true) sem freshness/daily_brief
const pfMin = { generated_at: baseModel.generated_at, today: baseModel.today, owner: baseModel.owner,
  portfolio: baseModel.portfolio, people: [], goals: [], projects: [], actions: [], decisions: [], artifacts: [] };
const cPf = boot(pfMin, compiledPfJs);

console.log(JSON.stringify({
  htmlFresh, badgeFresh,
  html3d, badge3d,
  dismissedVal, bannerRemoved, htmlAfterDismiss, htmlNextDay,
  hashAfterBadge, hashAfterBtn,
  badgeOntem, htmlBriefQuietToday,
  badge20h, htmlBriefStaleDate,
  badgeInboxOnly, htmlBriefMissing,
  pfBadgeHidden: cPf.freshbadge.hidden,
}));
"""
        with tempfile.TemporaryDirectory() as td:
            p_m = Path(td) / "m.json"
            p_js = Path(td) / "c.js"
            p_pf = Path(td) / "pf.js"
            p_run = Path(td) / "r.js"
            p_m.write_text(json.dumps(m, default=str), encoding="utf-8")
            p_js.write_text(compiled_js, encoding="utf-8")
            p_pf.write_text(compiled_pf_js, encoding="utf-8")
            p_run.write_text(script, encoding="utf-8")
            proc = subprocess.run([node, str(p_run), str(p_m), str(p_js), str(p_pf)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"Node falhou:\n{proc.stderr}")
            res = json.loads(proc.stdout)

        # 1. Fresco hoje + brief escapado
        self.assertFalse(res["badgeFresh"]["hidden"])
        self.assertEqual(res["badgeFresh"]["text"], "dados de hoje")
        self.assertTrue(res["badgeFresh"]["ok"])
        self.assertFalse(res["badgeFresh"]["warn"])
        self.assertIn("48h", res["badgeFresh"]["title"])
        self.assertIn("26h", res["badgeFresh"]["title"])
        self.assertNotIn('id="freshbanner"', res["htmlFresh"])
        self.assertIn('id="daily-brief"', res["htmlFresh"])
        self.assertIn("Seu dia", res["htmlFresh"])
        self.assertIn("Foco na fornada.&lt;script&gt;alert(1)&lt;/script&gt;", res["htmlFresh"])
        self.assertNotIn("<script>alert(1)</script>", res["htmlFresh"])

        # 2. 3 dias desatualizado via BRAIN.refresh
        self.assertFalse(res["badge3d"]["hidden"])
        self.assertEqual(res["badge3d"]["text"], "há 3 dias")
        self.assertFalse(res["badge3d"]["ok"])
        self.assertTrue(res["badge3d"]["warn"])
        self.assertIn('id="freshbanner"', res["html3d"])
        self.assertIn("Última atualização há 3 dias — &#39;não consta&#39; pode ser falso negativo.", res["html3d"])
        self.assertIn('data-brain-update="1"', res["html3d"])
        self.assertIn('<span class="only-live">Atualizar agora</span>', res["html3d"])
        self.assertIn('<span class="only-portrait">Copiar comando</span>', res["html3d"])
        self.assertIn('id="fresh-health-btn"', res["html3d"])
        self.assertIn('id="fresh-dismiss-btn"', res["html3d"])

        # 3. Dispensar hoje
        self.assertEqual(res["dismissedVal"], "2026-10-09")
        self.assertTrue(res["bannerRemoved"])
        self.assertNotIn('id="freshbanner"', res["htmlAfterDismiss"])
        self.assertIn('id="freshbanner"', res["htmlNextDay"])

        # 4. Navegação para Saúde
        self.assertEqual(res["hashAfterBadge"], "cfg/saude")
        self.assertEqual(res["hashAfterBtn"], "cfg/saude")

        # 5. Demais faixas e estados do brief
        self.assertEqual(res["badgeOntem"], "dados de ontem")
        self.assertIn("Sem novidades desde a última atualização.", res["htmlBriefQuietToday"])
        self.assertEqual(res["badge20h"], "há 20h")
        self.assertIn("Dados desatualizados — &#39;não consta&#39; pode ser falso negativo.", res["htmlBriefStaleDate"])
        self.assertIn("Sem novidades ainda hoje — o resumo do dia aparece após a rotina. Último resumo: 08/10/2026.", res["htmlBriefStaleDate"])
        self.assertEqual(res["badgeInboxOnly"], "dados desatualizados")
        self.assertIn("Sem novidades ainda hoje — o resumo do dia aparece após a rotina.", res["htmlBriefMissing"])
        self.assertNotIn("Último resumo:", res["htmlBriefMissing"])

        # 6. Portfolio standalone mantém pílula oculta
        self.assertTrue(res["pfBadgeHidden"])


if __name__ == "__main__":
    unittest.main()
