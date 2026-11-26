/* núcleo compartilhado das 3 variantes — mesmas views, dados reais do demo.
   Diferenças visuais ficam no CSS de cada variante; extras ficam em scripts por variante. */
(function(){
"use strict";
// normalização: o portfolio.html injeta só o recorte do portfólio — e instâncias antigas podem
// não ter todas as chaves. Nenhuma leitura do painel pode ver undefined (boot OU refresh do serve).
const RAW_DATA = JSON.parse(document.getElementById("data").textContent);
const SERVE_ORIGIN = location.protocol === "http:" && location.hostname === "127.0.0.1";
const IS_SHELL = SERVE_ORIGIN && Object.keys(RAW_DATA).length === 0;
let HYDRATED = !IS_SHELL;
function normalizeBrain(m){
  m.owner = m.owner || {};
  m.owner = Object.assign({id: "eu", name: "Dono"}, m.owner);
  m.today = m.today || "";
  m.agenda = m.agenda || [];
  if (!Array.isArray(m.agenda)) m.agenda = [];
  m.wins = m.wins || {};
  m.wins = Object.assign({weeks: [], last_30d: 0, closed_30d: 0}, m.wins);
  if (!Array.isArray(m.wins.weeks)) m.wins.weeks = [];
  m.portfolio = m.portfolio || {};
  m.portfolio = Object.assign({
    areas: [], processes: [], opportunities: [], ranking: [],
    matrix: {}, funnel: {}, by_goal: {}, counts: {}, gaps: {}, ice_rubric: {},
  }, m.portfolio);
  if (!Array.isArray(m.portfolio.areas)) m.portfolio.areas = [];
  if (!Array.isArray(m.portfolio.processes)) m.portfolio.processes = [];
  if (!Array.isArray(m.portfolio.opportunities)) m.portfolio.opportunities = [];
  if (!Array.isArray(m.portfolio.ranking)) m.portfolio.ranking = [];
  m.portfolio.matrix = Object.assign({"ganho rápido": [], "aposta": [], "preencher depois": [], "evitar": []}, m.portfolio.matrix || {});
  m.portfolio.funnel = m.portfolio.funnel || {};
  m.portfolio.by_goal = m.portfolio.by_goal || {};
  m.portfolio.counts = Object.assign({opportunities: 0, prioritized: 0, processes: 0}, m.portfolio.counts || {});
  m.portfolio.gaps = Object.assign({total: 0, areas_without_process: [], processes: [], no_ice: [], ice_suggested: [], stale: []}, m.portfolio.gaps || {});
  m.portfolio.ice_rubric = Object.assign({success_measures: [], principles: [], axes: {}}, m.portfolio.ice_rubric || {});
  m.update = m.update || {}; m.update = Object.assign({version:"?", news:[], cli_cmd:"", checked_at:"", behind:0, ahead:0, remote_version:""}, m.update);
  m.open = Object.assign({mode: "auto", ide: "", reader: false}, m.open || {});
  m.freshness = m.freshness || {};
  m.freshness = Object.assign({
    last_dump_at: null, last_dump_age_h: null,
    last_render_at: null, last_render_age_h: null,
    last_memory_sync_at: null, last_memory_sync_age_h: null,
    inbox_backlog: 0, inbox_oldest_age_h: null,
    stale: {}, thresholds: {},
  }, m.freshness);
  m.freshness.stale = Object.assign({dump: false, render: false, memory_sync: false, inbox: false}, m.freshness.stale || {});
  m.freshness.thresholds = Object.assign({}, m.freshness.thresholds || {});
  m.daily_brief = m.daily_brief || {};
  m.daily_brief = Object.assign({
    exists: false, is_today: false, date: null, generated_at: null, empty: false, text: "",
  }, m.daily_brief);
  m.counts = m.counts || {};
  m.counts = Object.assign({
    mine_open: 0, mine_overdue: 0, mine_due_7d: 0, mine_blocked: 0,
    waiting_open: 0, wins_30d: 0, decisions_30d: 0, outbox_pending: 0,
  }, m.counts);
  m.review = m.review || {};
  m.review = Object.assign({total: 0, counts: {}, batch_acceptable: 0, ports: 0}, m.review);
  m.questions = m.questions || []; if (!Array.isArray(m.questions)) m.questions = [];
  m.proposals = m.proposals || []; if (!Array.isArray(m.proposals)) m.proposals = [];
  m.outbox = m.outbox || []; if (!Array.isArray(m.outbox)) m.outbox = [];
  m.health = m.health || []; if (!Array.isArray(m.health)) m.health = [];
  m.deliveries = m.deliveries || []; if (!Array.isArray(m.deliveries)) m.deliveries = [];
  m.feedback = m.feedback || []; if (!Array.isArray(m.feedback)) m.feedback = [];
  m.sources = m.sources || []; if (!Array.isArray(m.sources)) m.sources = [];
  m.source_kinds = m.source_kinds || []; if (!Array.isArray(m.source_kinds)) m.source_kinds = [];
  m.doc_kinds = m.doc_kinds || []; if (!Array.isArray(m.doc_kinds)) m.doc_kinds = [];   // Fontes e Documentos (ausentes em instância antiga)
  m.providers = m.providers || {};   // face Configurações (ausente em instância antiga)
  m.actions = m.actions || []; if (!Array.isArray(m.actions)) m.actions = [];
  m.publishes = m.publishes || []; if (!Array.isArray(m.publishes)) m.publishes = [];
  m.focus = m.focus || null;
  m.deliverables_done = m.deliverables_done || []; if (!Array.isArray(m.deliverables_done)) m.deliverables_done = [];
  m.timeline = m.timeline || {};
  m.timeline = Object.assign({past: [], future: [], back: "", ahead: ""}, m.timeline);
  if (!Array.isArray(m.timeline.past)) m.timeline.past = [];
  if (!Array.isArray(m.timeline.future)) m.timeline.future = [];
  m.people = m.people || []; if (!Array.isArray(m.people)) m.people = [];
  m.people = m.people.map(p => Object.assign({aliases: []}, p));
  m.goals = m.goals || []; if (!Array.isArray(m.goals)) m.goals = [];
  m.goals = m.goals.map(g => Object.assign({health_from: null, health_reason: "", projects: [], progress: {pct: null, done: 0, total: 0}}, g));
  m.projects = m.projects || []; if (!Array.isArray(m.projects)) m.projects = [];
  m.decisions = m.decisions || []; if (!Array.isArray(m.decisions)) m.decisions = [];
  m.artifacts = m.artifacts || []; if (!Array.isArray(m.artifacts)) m.artifacts = [];
  m.shares = m.shares || []; if (!Array.isArray(m.shares)) m.shares = [];
  m.notes = m.notes || []; if (!Array.isArray(m.notes)) m.notes = [];
  m.agent_ok = !!m.agent_ok;
  m.onboarding = m.onboarding || {needed: false};   // F8: primeira vez entra no wizard da própria página
  // publicações (porta 3) vêm dos shares reais do ledger (Share: solicitada|aprovada|publicada|cancelada)
  if (!m.publishes.length && m.shares.length)
    m.publishes = m.shares.map(x => ({id: x.id, title: String(x.report || "").split("/").pop() || x.id,
      to: x.destination || "—", status: x.status, date: x.date, link: x.link || null, report: x.report || "", files: x.files || []}));
  return m;
}
const M = normalizeBrain(RAW_DATA);
const idx = (arr, k) => { k = k || "id"; return Object.assign(Object.create(null), Object.fromEntries(arr.map(x => [x[k], x]))); };
var A = idx(M.actions), D = idx(M.decisions), P = idx(M.projects), G = idx(M.goals), PE = idx(M.people), ART = idx(M.artifacts);
var DL = idx(M.deliveries), DD = idx(M.deliverables_done);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const WD = ["dom","seg","ter","qua","qui","sex","sáb"];
const fmtD = iso => { if (!iso) return "—"; const p = iso.slice(0,10).split("-"); return p[2] + "/" + p[1]; };
const fmtDL = iso => { if (!iso) return "—"; const p = String(iso).slice(0,10).split("-"); return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : esc(iso); };
const fmtDW = iso => { if (!iso) return "—"; const d = new Date(iso.slice(0,10) + "T12:00:00"); return WD[d.getDay()] + " " + fmtD(iso); };
const dur = m => !m ? "—" : (Math.floor(m/60) ? Math.floor(m/60) + "h" + (m%60 ? String(m%60).padStart(2,"0") : "") : m + "min");
const progTxt = p => {
  if (p.pct == null) return "sem entregáveis";
  let s = p.pct + "% · " + p.done + "/" + p.total + " entregáveis";
  if (p.weight_total != null && (p.weight_done !== p.done || p.weight_total !== p.total))
    s += " · peso " + p.weight_done + "/" + p.weight_total;
  return s;
};
const bar = (pct, big) => pct == null ? '<span class="muted">sem entregáveis</span>' :
  '<span class="bar' + (big ? " big" : "") + '"><span style="width:' + pct + '%"></span></span>' + (big ? "" : " <b>" + pct + "%</b>");
const donut = (pct, size) => { size = size || 44; const r = (size - 6) / 2, c = 2 * Math.PI * r;
  return '<svg class="donut" width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + " " + size + '">' +
    '<circle cx="' + size/2 + '" cy="' + size/2 + '" r="' + r + '" fill="none" stroke="var(--chip2)" stroke-width="5"/>' +
    '<circle cx="' + size/2 + '" cy="' + size/2 + '" r="' + r + '" fill="none" stroke="var(--accent)" stroke-width="5" stroke-linecap="round" stroke-dasharray="' +
    (c * (pct || 0) / 100).toFixed(1) + " " + c.toFixed(1) + '" transform="rotate(-90 ' + size/2 + " " + size/2 + ')"/>' +
    '<text x="50%" y="50%" dominant-baseline="central" text-anchor="middle">' + (pct == null ? "—" : pct) + "</text></svg>"; };
// #100: modificador vazio não gera mais "chip h-" morto (chip neutro segue válido);
// nível fora do vocabulário avisa no console em vez de cair no estilo base em silêncio.
// (CHIP_LEVELS é construído junto de STAGES, mais abaixo — chip() só lê na hora do render.)
const chip = (level, label) => {
  if (level && !CHIP_LEVELS.has(level)) console.warn("[chip] modificador sem estilo mapeado:", level);
  return '<span class="chip' + (level ? " h-" + esc(level) : "") + '">' + esc(label) + "</span>";
};
const goalReasonChip = g => (g.health_from && g.health !== "em-dia" && g.health !== "concluido")
  ? '<a class="chip h-reason" href="#projects?focus=' + esc(g.health_from) + '" data-proj-jump="' + esc(g.health_from) + '" title="' + esc(g.health_reason || g.health_from) + '">↳ ' + esc(g.health_from) + (g.health_reason ? " · " + esc(g.health_reason) : "") + "</a>"
  : "";
const idc = id => '<code class="idchip">' + esc(id) + "</code>";
const aL = id => A[id] ? '<a href="#action/' + id + '">' + idc(id) + "</a>" : idc(id);
const dL = id => D[id] ? '<a href="#decision/' + id + '">' + idc(id) + "</a>" : idc(id);
const pL = (id, long) => P[id] ? '<a href="#project/' + id + '">' + idc(id) + (long ? " " + esc(P[id].title) : "") + "</a>" : esc(id || "—");
const peL = id => PE[id] ? '<a href="#person/' + encodeURIComponent(id) + '">' + esc(PE[id].name) + "</a>" : esc(id);
const empty = t => '<div class="empty">' + esc(t) + "</div>";
const panel = (title, body, extra) => '<section class="panel"' + (extra || "") + ">" + (title ? "<h2>" + title + "</h2>" : "") + body + "</section>";


// ── dropdown de filtro (pill + popup, teclado incluso) ─────────────────
function ddVal(id0){ const el = document.querySelector('[data-dd="' + id0 + '"]'); return el ? (el.dataset.v || "") : ""; }
function dd(id0, opts, sel, ph){
  const cur = opts.find(o => o[0] === sel);
  return '<div class="dd" data-dd="' + esc(id0) + '" data-v="' + esc(sel || "") + '">' +
    '<button type="button" class="dd-btn" aria-haspopup="listbox" aria-expanded="false"><span>' +
    esc(cur ? cur[1] : ph) + '</span><i class="dd-chev"></i></button>' +
    '<div class="dd-pop" role="listbox">' +
    (ph ? '<div class="dd-opt' + (!sel ? " on" : "") + '" role="option" data-v="">' + esc(ph) + "</div>" : "") +
    opts.map(o => '<div class="dd-opt' + (o[0] === sel ? " on" : "") + '" role="option" data-v="' + esc(o[0]) + '">' + esc(o[1]) + "</div>").join("") +
    "</div></div>";
}
document.addEventListener("click", e => {
  const pj = e.target.closest("a[data-proj-jump]");
  if (pj && (location.hash.slice(1).split("?")[0] || "home") === "projects") {
    const el = document.getElementById("proj-" + pj.dataset.projJump);
    if (el) {
      e.preventDefault();
      if (typeof el.scrollIntoView === "function") el.scrollIntoView({behavior: "smooth", block: "center"});
      el.classList.add("just-moved");
      setTimeout(() => el.classList.remove("just-moved"), 1400);
    }
    return;
  }
  const sortBtn = e.target.closest("[data-src-sort]");
  if (sortBtn) {
    e.preventDefault();
    S_SORT = S_SORT === "desc" ? "asc" : "desc";
    route();
    return;
  }
  const toggleBtn = e.target.closest("[data-src-toggle]");
  if (toggleBtn && e.target === toggleBtn) {
    e.stopPropagation();
    const key = toggleBtn.dataset.srcToggle;
    const s = (M.sources || []).find(x => x.key === key);
    if (s) {
      runCommand('brain watch edit ' + qArg(s.key) + ' --set enabled=' + (s.enabled === false ? 'true' : 'false'));
    }
    return;
  }
  const btn = e.target.closest(".dd-btn");
  if (btn) { const box = btn.closest(".dd"); const was = box.classList.contains("open");
    document.querySelectorAll(".dd.open").forEach(x => x.classList.remove("open"));
    if (!was) { box.classList.add("open"); btn.setAttribute("aria-expanded", "true"); }
    else btn.setAttribute("aria-expanded", "false");
    return; }
  const opt = e.target.closest(".dd-opt");
  if (opt) { const box = opt.closest(".dd"); box.classList.remove("open"); box.dataset.v = opt.dataset.v;
    box.querySelector(".dd-btn span").textContent = opt.textContent;
    box.querySelectorAll(".dd-opt").forEach(x => x.classList.toggle("on", x === opt));
    box.querySelector(".dd-btn").dispatchEvent(new CustomEvent("ddchange", {bubbles: true, detail: {value: opt.dataset.v}}));
    return; }
  document.querySelectorAll(".dd.open").forEach(x => x.classList.remove("open"));
});
document.addEventListener("keydown", e => {
  const box = document.querySelector(".dd.open"); if (!box) return;
  const opts = [...box.querySelectorAll(".dd-opt")];
  if (e.key === "Escape") { box.classList.remove("open"); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault();
    let i = opts.findIndex(o => o.classList.contains("hover"));
    opts.forEach(o => o.classList.remove("hover"));
    i = e.key === "ArrowDown" ? Math.min(opts.length - 1, i + 1) : Math.max(0, i < 0 ? opts.length - 1 : i - 1);
    opts[i].classList.add("hover"); opts[i].scrollIntoView({block: "nearest"}); return; }
  if (e.key === "Enter") { e.preventDefault();
    (box.querySelector(".dd-opt.hover") || box.querySelector(".dd-opt.on")).click(); return; }
});

// ── prazo ───────────────────────────────────────────────────────────────
function dueTxt(a){
  if (!a.open) return '<span class="muted">' + (a.status === "fechada" ? "✓ feita " : "× descartada ") + fmtD(a.closed) + "</span>";
  if (!a.due) return '<span class="muted">sem prazo</span>';
  if (a.parked) return '<span class="muted" title="adiada de propósito — não conta como atrasada">' + fmtDW(a.due) + (a.due_suggested ? " <em>sugerido</em>" : "") + "</span>";
  if (a.due_suggested) return '<span class="dsug" title="' + esc(a.due_reason || "prazo sugerido pelo agente") + '">' + (a.overdue_days ? "⚠ " : "") + fmtDW(a.due) + ' <em>sugerido</em>' +
    (a.overdue_days ? " · " + a.overdue_days + "d atrasada" : a.due_in != null && a.due_in <= 7 ? " · " + (a.due_in ? "em " + a.due_in + "d" : "hoje") : "") + "</span>";
  if (a.overdue_days) return '<span class="late">⚠ ' + fmtDW(a.due) + " · " + a.overdue_days + "d atrasada</span>";
  if (a.due_in != null && a.due_in <= 7) return '<span class="soon">' + fmtDW(a.due) + " · " + (a.due_in ? "em " + a.due_in + "d" : "hoje") + "</span>";
  return fmtDW(a.due);
}

// ── cartão de ação (kanban) ─────────────────────────────────────────────
function card(a){
  return '<article class="card' + (a.overdue_days && !a.parked ? " is-late" : "") + (a.parked ? " is-parked" : "") + (a.status === "bloqueada" ? " is-blocked" : "") + '">' +
    '<header><span class="ids">' + aL(a.id) + "</span>" +
    (a.priority === "alta" ? " " + chip("em-risco", "alta") : "") +
    (a.list !== "mine" || !a.mine ? " " + chip("info", a.owner_name) : "") + "</header>" +
    '<h3 class="card-title">' + esc(a.title) + "</h3>" +
    '<p class="card-meta">' + dueTxt(a) + (a.effort_min ? " · " + dur(a.effort_min) : "") + (a.project ? " · " + pL(a.project) : "") + "</p>" +
    (a.blocked_by.length ? '<p class="card-block">⛔ ' + a.blocked_by.map(b => aL(b) + " (" + esc((A[b] || {}).owner_name || "") + ")").join(", ") + "</p>" : "") +
    "</article>";
}
function actionTable(ids, cols){
  if (!ids.length) return empty("—");
  const rows = ids.map(id => A[id]).filter(Boolean).map(a => "<tr><td>" + aL(a.id) + "</td>" +
    (cols.includes("owner") ? "<td>" + peL(a.owner) + "</td>" : "") + "<td>" + esc(a.title) + "</td><td>" + dueTxt(a) + "</td>" +
    (cols.includes("status") ? "<td>" + chip(a.status === "bloqueada" ? "em-risco" : "info", a.status) + "</td>" : "") +
    (cols.includes("age") ? '<td class="num">' + (a.aging_days ?? "—") + "d</td>" : "") +
    (cols.includes("project") ? "<td>" + pL(a.project) + "</td>" : "") + "</tr>").join("");
  const head = "<tr><th>ID</th>" + (cols.includes("owner") ? "<th>Quem</th>" : "") + "<th>O quê</th><th>Prazo</th>" +
    (cols.includes("status") ? "<th>Estado</th>" : "") + (cols.includes("age") ? "<th>Idade</th>" : "") + (cols.includes("project") ? "<th>Projeto</th>" : "") + "</tr>";
  return '<div class="twrap"><table>' + head + rows + "</table></div>";
}
function decisionTable(list){
  if (!list.length) return empty("Nenhuma decisão registrada.");
  return '<div class="twrap"><table><tr><th>Data</th><th>ID</th><th>Decisão</th><th>Quem decidiu</th><th>Projeto</th><th>Fonte</th></tr>' +
    list.map(d => '<tr class="' + (d.status === "substituida" ? "sup" : "") + '"><td class="num">' + fmtD(d.date) + "</td><td>" + dL(d.id) + "</td><td>" + esc(d.title) +
      (d.superseded_by ? ' <span class="muted">→ ' + dL(d.superseded_by) + "</span>" : "") + "</td><td>" + d.decided_by.map(peL).join(", ") +
      '</td><td>' + pL(d.project) + '</td><td class="muted">' + esc(d.source_label) + " [" + esc(d.prov) + "]</td></tr>").join("") + "</table></div>";
}
function timelineList(items, limit){
  if (!items.length) return empty("Sem eventos registrados.");
  return '<div class="tl">' + items.slice(0, limit || 60).map(it => '<div class="it k-' + esc(it.kind) + '"><span class="muted">' + fmtD(it.date) + "</span> · " +
    esc(it.kind) + " · " + (it.id.startsWith("TASK-") ? aL(it.id) + " " : it.id.startsWith("DEC-") ? dL(it.id) + " " : it.id.includes("/") ? "" : esc(it.id) + " ") + esc(it.title) +
    (it.who ? ' <span class="muted">(' + esc(it.who) + ")</span>" : "") + (it.project && P[it.project] ? " · " + pL(it.project) : "") + "</div>").join("") + "</div>";
}

// ── frescor e resumo do dia (#57w2 + #60w2) ─────────────────────────────
const FRESH_DISMISS_KEY = "brain.freshness.dismissed";
function isFreshDismissed(todayStr){
  if (!todayStr) return false;
  try { return localStorage.getItem(FRESH_DISMISS_KEY) === String(todayStr); }
  catch (e) { return false; }
}
function dismissFreshToday(todayStr){
  if (!todayStr) return;
  try { localStorage.setItem(FRESH_DISMISS_KEY, String(todayStr)); }
  catch (e) {}
}
function freshnessSummary(f){
  f = f || {};
  const stale = f.stale || {};
  const th = f.thresholds || {};
  const anyStale = !!(stale.dump || stale.render || stale.memory_sync || stale.inbox);
  const onlyInboxStale = !!stale.inbox && !stale.dump && !stale.render && !stale.memory_sync;
  const ages = [f.last_dump_age_h, f.last_render_age_h].filter(x => typeof x === "number" && isFinite(x));
  const ageH = ages.length ? Math.max(...ages) : null;
  const ageDays = ageH == null ? null : Math.floor(ageH / 24);
  let label;
  if (onlyInboxStale) label = "dados desatualizados";
  else if (ageH == null) label = anyStale ? "dados desatualizados" : "dados de hoje";
  else if (ageH < 24) label = anyStale ? ("há " + Math.max(1, Math.floor(ageH)) + "h") : "dados de hoje";
  else if (ageDays < 2) label = "dados de ontem";
  else label = "há " + ageDays + " dias";

  const tone = anyStale ? "fresh-warn" : "fresh-ok";
  const fmtAge = h => h == null ? "sem registro" : (h < 24 ? Math.round(h) + "h" : Math.floor(h / 24) + "d");
  const parts = [
    "dump: " + fmtAge(f.last_dump_age_h) + (th.dump_warn_h != null ? " (limite " + th.dump_warn_h + "h)" : ""),
    "render: " + fmtAge(f.last_render_age_h) + (th.render_warn_h != null ? " (limite " + th.render_warn_h + "h)" : ""),
  ];
  if (f.last_memory_sync_age_h != null || stale.memory_sync) {
    parts.push("memória: " + fmtAge(f.last_memory_sync_age_h) + (th.memory_sync_warn_h != null ? " (limite " + th.memory_sync_warn_h + "h)" : ""));
  }
  if (f.inbox_backlog || stale.inbox) {
    const cntLim = th.inbox_warn_count != null ? "≥" + th.inbox_warn_count : "";
    const ageLim = th.inbox_oldest_warn_h != null ? th.inbox_oldest_warn_h + "h" : "";
    const lim = [cntLim, ageLim].filter(Boolean).join(" / ");
    parts.push("inbox: " + (f.inbox_backlog || 0) + (f.inbox_oldest_age_h != null ? " (" + fmtAge(f.inbox_oldest_age_h) + ")" : "") + (lim ? " (limite " + lim + ")" : ""));
  }
  const banner = (ageDays != null && ageDays >= 2 && !onlyInboxStale)
    ? "Última atualização há " + ageDays + " dias — 'não consta' pode ser falso negativo."
    : "Dados desatualizados — 'não consta' pode ser falso negativo.";
  return {anyStale, onlyInboxStale, ageH, ageDays, label, tone, tooltip: parts.join(" · "), banner};
}
function renderFreshBanner(f, sum){
  const stale = (f && f.stale) || {};
  const reasons = [];
  if (stale.dump) reasons.push("dump");
  if (stale.render) reasons.push("render");
  if (stale.memory_sync) reasons.push("memória");
  if (stale.inbox) reasons.push("inbox (" + (f.inbox_backlog || 0) + ")");
  const detail = reasons.length ? "Pendente: " + reasons.join(", ") + "." : "";
  return '<section class="fresh-banner" id="freshbanner" role="status">' +
    '<div class="fresh-banner-text"><strong>⚠ ' + esc(sum.banner) + "</strong>" +
    (detail ? '<span class="muted small">' + esc(detail) + "</span>" : "") + "</div>" +
    '<div class="fresh-banner-actions">' +
    '<button type="button" class="btn primary" data-brain-update="1"><span class="only-live">Atualizar agora</span><span class="only-portrait">Copiar comando</span></button>' +
    '<button type="button" class="btn" id="fresh-health-btn">Ver saúde</button>' +
    '<button type="button" class="btn ghost" id="fresh-dismiss-btn" aria-label="Dispensar por hoje">Dispensar hoje</button>' +
    "</div></section>";
}
// ── Seu dia: o brief do agente em Markdown mínimo → HTML seguro (#160) ──────────────
// O brief é texto do agente — e o agente leu conteúdo da inbox: é entrada NÃO confiável.
// Segurança por construção: (1) o texto vira blocos, (2) cada pedaço de TEXTO passa por esc()
// ANTES de qualquer marcação, (3) só entra sem escapar o que este código gerou — tags próprias,
// rotas "#..." internas e URLs http(s) já validadas. Sem HTML cru, sem <img>, sem tabela, sem
// atributo vindo do texto. Entidade que o painel conhece (TASK-####, PROP-####, GOAL-#…) vira
// etiqueta com link para a ficha; atraso, prazo e status são LIDOS do modelo (quem calcula é o ./brain).
// O formato que o agente escreve está em commands/brief/SKILL.md (seção ##, lista -, id cru).
const BD_MAX_SECTIONS = 3;   // além disso o brief abre recolhido, com "Mostrar tudo": é um resumo, não a página
const BD_ENT_SRC = "\\b(?:TASK|DEC|WIN|PROP|MSG|PUB|FOCUS|PROC|OPP|ASK|FB)-\\d{2,5}\\b|\\b(?:PROJ|GOAL)-\\d{1,3}(?:\\.\\d{1,3})?\\b";   // sem grupos capturando (entra num alternation maior)
const BD_ENT = new RegExp(BD_ENT_SRC, "i");
const BD_PROP_KIND = {"atualizar-acao":"atualizar ação","fechar-acao":"fechar ação","descartar-acao":"descartar ação",
  "unificar-acao":"unificar ação","add-project":"criar projeto","add-goal":"criar goal","add-deliverable":"criar entregável"};
const BD_SIT_LEVEL = {late:"em-risco", block:"travado", soon:"atencao", done:"concluido", ask:"info", prop:"atencao"};   // tom → classe de chip que o painel já tem
function bdClamp(s, n){ s = String(s || ""); return s.length > n ? s.slice(0, n - 1).replace(/\s+$/, "") + "…" : s; }
// O que o painel sabe sobre a entidade citada: rota, título e situação — tudo lido do modelo.
function bdEnt(id){
  if (!BD_ENT.test(id)) return null;
  var up = id.toUpperCase(), k = /^[A-Z]+/.exec(up)[0], sub = /\.\d+$/.test(up);   // sub: entregável (PROJ-#.#)
  var e = {id: up, kind: k, href: "", title: "", sit: "", tone: "", tip: ""}, a, p, g, x, s;
  if (k === "TASK" && (a = A[up])) {
    e.href = "#action/" + up; e.title = a.title; s = [];
    if (!a.open) { s.push(a.status || "feita"); e.tone = "done"; }
    else if (a.status === "bloqueada") { s.push("bloqueada"); e.tone = "block"; }
    else if (a.overdue_days) { s.push("atrasada " + a.overdue_days + "d"); e.tone = "late"; }
    else if (a.due_in === 0) { s.push("vence hoje"); e.tone = "soon"; }
    else if (a.due_in > 0 && a.due_in <= 7) { s.push("em " + a.due_in + "d"); e.tone = "soon"; }
    else if (a.due) s.push(fmtDW(a.due));
    else s.push("sem prazo");
    if (a.list === "waiting" && a.owner_name) s.push("com " + a.owner_name);
    if (a.priority === "alta" && a.open) s.unshift("alta");
    e.sit = s.join(" · ");
  } else if (k === "DEC" && (x = D[up])) {
    e.href = "#decision/" + up; e.title = x.title; e.sit = x.status && x.status !== "ativa" ? x.status : "";
  } else if (k === "PROJ" || k === "GOAL") {
    var pid = up.split(".")[0];
    if (k === "GOAL" && (g = G[pid])) {
      e.href = "#projects?focus=" + pid; e.title = g.title; e.sit = g.health_label || g.status || "";
    } else if (k === "PROJ" && (p = P[pid])) {
      e.href = "#project/" + pid;
      if (sub) {
        var dv = (p.deliverables || []).find(v => v.id === up);
        if (!dv) return null;
        e.title = dv.title;
        e.sit = dv.status === "feito" || dv.status === "cancelado" ? dv.status :
                dv.overdue_days ? "atrasada " + dv.overdue_days + "d" : dv.due ? fmtDW(dv.due) : "sem prazo";
        e.tone = dv.status === "feito" || dv.status === "cancelado" ? "done" : dv.overdue_days ? "late" : "";
      } else { e.title = p.title; e.sit = p.progress && p.progress.pct != null ? p.progress.pct + "%" : ""; }
    } else return null;
  } else if (k === "PROP" && (x = M.proposals.find(q => q.id === up))) {
    e.href = "#ask"; e.title = "proposta · " + (BD_PROP_KIND[x.kind] || "proposta");
    e.sit = !x.status || x.status === "pendente" ? "aguarda decisão" : x.status; e.tone = "prop"; e.tip = x.summary;
  } else if (k === "ASK" && (x = M.questions.find(q => q.id === up))) {
    e.href = "#ask"; e.title = "pergunta";
    e.sit = x.status === "aberta" ? (x.options && x.options.length ? x.options.length + " opções · aberta" : "aberta") : (x.status || "");
    e.tone = x.status === "aberta" ? "ask" : "done"; e.tip = x.text;
  } else if (k === "MSG" && (x = (M.outbox || []).find(q => q.id === up))) {
    e.href = "#outbox"; e.title = "rascunho para " + (x.to_name || x.to || "—");
    e.sit = x.status || ""; e.tone = x.status === "rascunho" ? "ask" : "done"; e.tip = x.text;
  } else if (k === "FOCUS" && M.focus && M.focus.id === up) {
    e.href = "#focus"; e.title = "plano de foco · " + (M.focus.blocks || []).length + " blocos";
    e.sit = M.focus.status === "proposto" ? "aguarda ok" : (M.focus.status || "");
    e.tone = M.focus.status === "proposto" ? "ask" : "";
  } else if (k === "OPP" && OPP[up]) {
    e.href = "#pf/opp/" + encodeURIComponent(up); e.title = OPP[up].title; e.sit = OPP[up].status || "";
  } else if (k === "PROC" && PROC[up]) {
    e.href = "#pf/procs"; e.title = PROC[up].title;
  } else if (k === "WIN" && DL[up]) {
    e.href = "#wins"; e.title = DL[up].title;
  } else if (k === "FB" && (x = (M.feedback || []).find(q => q.id === up))) {
    e.href = "#feedback"; e.title = x.title || "";
  } else return null;
  return e;
}
var BD_PE_SRC;                                                              // pessoas que deram origem ao regex (trocou → refaz)
function bdPeople(){
  if (BD_PE_SRC === M.people) return;                                       // também cobre BRAIN.refresh: índice novo, regex novo
  BD_PE_SRC = M.people; BD_PE_MAP = Object.create(null); BD_RE = null;
  var alts = [], ownerId = (M.owner && M.owner.id) || "";
  (M.people || []).forEach(p => {
    if (p.id === ownerId || p.is_owner) return;                             // o dono aparece como texto comum
    [p.name].concat(p.aliases || []).forEach(n => {
      n = String(n || "").trim();
      if (n.length < 3 || /[()@/\\[\]`*_<>"'#]/.test(n) || !/[A-Za-zÀ-ÿ]/.test(n)) return;
      if (BD_PE_MAP[n.toLowerCase()]) return;
      BD_PE_MAP[n.toLowerCase()] = p.id;
      alts.push(n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    });
  });
  BD_PE_RE = alts.length ? alts.sort((a, b) => b.length - a.length).join("|") : "(?!)";
}
var BD_PE_RE = null, BD_PE_MAP = null;
function bdPersonLink(text, noLink){
  bdPeople();
  var pid = BD_PE_MAP[String(text).toLowerCase()];
  return pid && !noLink ? '<a href="#person/' + encodeURIComponent(pid) + '">' + esc(text) + "</a>" : esc(text);
}
function bdCode(c, plain){                                                  // `código`: literal, escapado
  var t = c.trim();
  if (BD_ENT.test(t)) return bdEntChip(t, plain);                           // id entre crases continua sendo link para a ficha
  return '<code class="bd-code">' + esc(c) + "</code>";
}
function bdUrl(u, noLink){
  var tail = "";
  while (/[.,;:!?]$/.test(u)) { tail = u.slice(-1) + tail; u = u.slice(0, -1); }   // pontuação colada no fim é da frase, não do link
  return (noLink ? esc(u) : '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + esc(u) + "</a>") + tail;
}
function bdLink(label, url, noLink){                                        // [rótulo](url): só http(s), mailto: e rota "#..." da página
  var ok = /^(https?:\/\/|mailto:)/i.test(url) || /^#[a-z][\w/.-]*$/i.test(url);
  if (noLink || !ok) return "[" + bdInline(label, true) + "](" + esc(url) + ")";
  return '<a href="' + esc(url) + '"' + (url.charAt(0) === "#" ? "" : ' target="_blank" rel="noopener noreferrer"') + ">" +
    bdInline(label, true) + "</a>";
}
// Do bloco em renderização: BD_MANY = várias entidades são o assunto (etiquetas compactas, duas por linha);
// BD_UNIFORM = todas na mesma situação (o rótulo do item já diz — não repetir em cada etiqueta).
var BD_MANY = false, BD_UNIFORM = false;
function bdEntChip(id, plain){
  var e = bdEnt(id), inner = idc(e ? e.id : id), tip = e ? esc(e.tip || [e.title, e.sit].filter(Boolean).join(" · ")) : "";
  if (!e || !e.href) return inner;                                          // o painel não conhece: chip comum, sem link
  if (plain) return '<a class="bd-id" href="' + e.href + '" title="' + tip + '">' + inner + "</a>";
  return '<a class="bd-tag' + (BD_MANY ? " bd-tag-m" : "") + (e.tone ? " is-" + e.tone : "") + '" href="' + e.href + '" title="' + tip + '">' + inner +
    (e.title ? '<span class="bd-tag-t">' + esc(bdClamp(e.title, BD_MANY ? 90 : 46)) + "</span>" : "") +
    (e.sit && !BD_UNIFORM ? '<span class="chip bd-tag-s' + (BD_SIT_LEVEL[e.tone] ? " h-" + BD_SIT_LEVEL[e.tone] : "") + '">' + esc(e.sit) + "</span>" : "") + "</a>";
}
var BD_RE = null;
function bdRe(){
  bdPeople();
  if (BD_RE) return BD_RE;
  BD_RE = new RegExp(
    "(`+)([^`\\n]+?)\\1(?!`)" +                                     // 1,2  `código`
    "|\\[([^\\]\\n]+)\\]\\(([^)\\s]+)\\)" +                          // 3,4  [rótulo](url)
    "|\\*\\*(?=\\S)([^\\n]*?\\S)\\*\\*" +                            // 5    **negrito**
    "|(?<![\\w*])\\*(?!\\s)([^*\\n]+?)(?<!\\s)\\*(?![\\w*])" +        // 6    *itálico*
    "|(?<![\\w_])_(?!\\s)([^_\\n]+?)(?<!\\s)_(?![\\w_])" +            // 7    _itálico_
    "|https?://[^\\s<>\"'`\\])}]+" +                                  // —    url solta (sem grupo: reconhecida pelo texto)
    "|(?:" + BD_ENT_SRC + ")" +                                    // —    entidade (idem)
    "|(?<![\\w@./-])(" + BD_PE_RE + ")(?![\\w@-])",                  // 8    pessoa
    "gi");
  return BD_RE;
}
// id entre parênteses é referência ao que a linha já está dizendo, não o assunto dela: vira chip curto em vez de etiqueta
var BD_SRC = "";                                                    // texto-fonte do bloco em renderização (para a conta de parênteses)
function bdRef(at){
  var t = BD_SRC.slice(0, at);
  return (t.match(/\(/g) || []).length > (t.match(/\)/g) || []).length;
}
function bdInline(raw, noLink, base){
  raw = String(raw || ""), base = base || 0;
  var re = bdRe(), out = "", last = 0, m;
  re.lastIndex = 0;
  // o regex é compartilhado com as chamadas recursivas: a posição é religada a cada volta
  while (re.lastIndex = last, (m = re.exec(raw))) {
    out += esc(raw.slice(last, m.index)); last = re.lastIndex;
    var piece;
    if (m[1] != null) piece = bdCode(m[2], noLink || bdRef(base + m.index));
    else if (m[3] != null) { out += bdLink(m[3], m[4], noLink); continue; }
    else if (m[5] != null) { out += "<strong>" + bdInline(m[5], noLink, base + m.index + 2) + "</strong>"; continue; }
    else if (m[6] != null) { out += "<em>" + bdInline(m[6], noLink, base + m.index + 1) + "</em>"; continue; }
    else if (m[7] != null) { out += "<em>" + bdInline(m[7], noLink, base + m.index + 1) + "</em>"; continue; }
    else if (/^https?:/i.test(m[0])) { out += bdUrl(m[0], noLink); continue; }
    else if (/^[A-Z]+-\d/i.test(m[0])) piece = bdEntChip(m[0], noLink || bdRef(base + m.index));
    else { out += bdPersonLink(m[0], noLink); continue; }
    // chip e pontuação vizinha ficam grudados: "(TASK-0003)," nunca deixa vírgula ou parêntese órfão no fim da linha
    var open = raw.charAt(m.index - 1) === "(" && out.slice(-1) === "(";
    if (open) out = out.slice(0, -1);
    var punct = (raw.slice(last).match(/^[\)\]]+[.,;:!?]?|^[.,;:!?]/) || [""])[0];
    // lista de entidades no formato etiqueta: a vírgula entre duas etiquetas é só separador — sai,
    // para não sobrar uma vírgula órfã no fim da linha que quebrou
    var sep = punct === "," && /^<a class="bd-tag/.test(piece) && /^(?:\s|`)*[A-Z]+-\d/i.test(raw.slice(last + 1));
    last += punct.length;
    out += '<span class="bd-nb">' + (open ? "(" : "") + piece + (sep ? "" : punct) + "</span>";
  }
  return out + esc(raw.slice(last));
}
function bdGroup(text, canUniform){                                // assunto do bloco = entidades fora de parênteses que o painel conhece
  var re = new RegExp(BD_ENT_SRC, "gi"), m, ents = [];
  BD_SRC = text;
  while ((m = re.exec(text))) if (!bdRef(m.index)) { var e = bdEnt(m[0]); if (e && e.href) ents.push(e); }
  BD_MANY = ents.length >= 2;
  BD_UNIFORM = !!canUniform && BD_MANY && ents.every(x => x.sit && x.sit === ents[0].sit);
}
function bdItem(text){ bdGroup(text, true); return '<li class="bd-li">' + bdInline(text); }   // quem fecha o item é quem abre o próximo (liOpen)
function briefHtml(txt){
  var lines = String(txt || "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "").replace(/\r\n?/g, "\n").split("\n"), h = "", stack = [], para = [], quote = [], liOpen = false, head = "", m, i, line;
  function flushHead(){ if (head) { h += head; head = ""; } }                       // rótulo de seção só entra com conteúdo: seção vazia não aparece
  function flushPara(){ if (para.length) { flushHead(); h += "<p>" + para.map(t => (bdGroup(t, false), bdInline(t))).join("<br>") + "</p>"; para = []; } }
  function flushQuote(){ if (quote.length) { flushHead(); h += '<blockquote class="bd-quote">' + quote.map(t => (bdGroup(t, false), bdInline(t))).join("<br>") + "</blockquote>"; quote = []; } }
  function closeAll(){ if (liOpen) { h += "</li>"; liOpen = false; } while (stack.length) h += "</" + stack.pop() + ">"; }
  var ITEM = /^(\s*)(?:([-*+])|(\d{1,3})[.)])[ \t]+(.*)$/, HR = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
  for (i = 0; i < lines.length; i++) {
    line = lines[i];
    if (!line.trim()) { closeAll(); flushPara(); flushQuote(); continue; }
    if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) {
      closeAll(); flushPara(); flushQuote();
      bdGroup(m[2], false);
      head = m[1].length <= 2 ? '<div class="bd-h">' + bdInline(m[2]) + "</div>" : '<div class="bd-h4">' + bdInline(m[2]) + "</div>";
      continue;
    }
    if (HR.test(line)) { closeAll(); flushPara(); flushQuote(); flushHead(); h += '<hr class="bd-hr">'; continue; }
    if (/^ {0,3}>/.test(line)) { closeAll(); flushPara(); quote.push(line.replace(/^ {0,3}> ?/, "")); continue; }   // citação: bloco próprio, mesmo colada numa lista
    if (liOpen && !ITEM.test(line)) { bdGroup(line.trim(), false); h += "<br>" + bdInline(line.trim()); continue; }     // continuação do item aberto
    if ((m = ITEM.exec(line))) {
      var lvl = Math.min(2, Math.floor(m[1].replace(/\t/g, "  ").length / 2)), tag = m[2] ? "ul" : "ol", deeper = false;
      flushQuote(); flushHead();
      if (!stack.length) { stack.push(tag); h += "<" + tag + ' class="bd-' + tag + '">'; }
      else {
        while (stack.length - 1 > lvl) { if (liOpen) { h += "</li>"; liOpen = false; } h += "</" + stack.pop() + ">"; liOpen = true; }
        if (stack.length - 1 < lvl && liOpen) { stack.push(tag); h += "<" + tag + ' class="bd-' + tag + ' bd-sub">'; deeper = true; }   // sublista nasce dentro do item aberto
        else if (stack[stack.length - 1] !== tag) {
          if (liOpen) { h += "</li>"; liOpen = false; }
          h += "</" + stack.pop() + ">"; stack.push(tag); h += "<" + tag + ' class="bd-' + tag + (lvl ? " bd-sub" : "") + '">';
        }
      }
      if (liOpen && !deeper) h += "</li>";
      h += bdItem(m[4]); liOpen = true; continue;
    }
    para.push(line.trim());
  }
  closeAll(); flushPara(); flushQuote();
  return h;
}
// Avisos do doctor: vêm de M.health, nunca do texto do brief — atalho no cabeçalho, sem ocupar linha
function bdBad(){
  var bad = (M.health || []).filter(x => x.level === "warn" || x.level === "error"), seen = Object.create(null), out = [];
  bad.forEach(x => { if (x.title && !seen[x.title]) { seen[x.title] = 1; out.push(x); } });
  return out;
}
function bdHealthLink(){
  var bad = bdBad(), n = bad.length;
  return n ? '<a class="bd-hl" href="#cfg/saude" title="' + esc(bad.map(x => x.title + (x.detail ? ": " + x.detail : "")).join("\n")) + '">⚠ ' + n +
    (n === 1 ? " aviso de saúde" : " avisos de saúde") + "</a>" : "";
}
function bdWhen(br){
  if (!br.is_today) return "";
  if (br.generated_at) return "atualizado " + esc(String(br.generated_at).slice(11, 16));
  return br.date ? esc(fmtD(br.date)) : "";
}
// "Mostrar tudo" do brief recolhido: um listener só, delegado no documento (o cartão é re-renderizado a cada render)
var BD_MORE_BOUND = false, BD_OPEN_KEY = "";                // brief que o dono abriu: continua aberto enquanto for o mesmo
// o corte do brief recolhido cai na fronteira de seção (antes do 4º rótulo), nunca no meio de uma linha
function bdFitClamp(body){
  body = body || document.querySelector("#daily-brief .brief-body.is-clamped:not(.is-open)");
  if (!body) return;
  var hs = body.querySelectorAll(".bd-h, .bd-h4"), h4 = hs[BD_MAX_SECTIONS];
  if (!h4) return;
  body.style.maxHeight = Math.max(120, Math.floor(h4.offsetTop - body.offsetTop - 7)) + "px";
}
function bdBindMore(){
  if (BD_MORE_BOUND) return;
  BD_MORE_BOUND = true;
  document.addEventListener("click", ev => {
    var b = ev.target.closest && ev.target.closest(".bd-more");
    if (!b) return;
    var body = b.parentNode.querySelector(".brief-body"), open = body.classList.toggle("is-open");
    BD_OPEN_KEY = open ? (b.getAttribute("data-key") || "") : "";
    b.setAttribute("aria-expanded", open ? "true" : "false");
    body.style.maxHeight = open ? "none" : "";                 // a altura ajustada (inline) valia só para o estado recolhido
    if (!open) bdFitClamp(body);
    // texto do controle por DOM (nada de innerHTML): "N seções" é número contado do brief, mas passa por textContent
    b.textContent = "";
    b.append(open ? "Mostrar menos" : "Mostrar tudo");
    if (!open) { var n = document.createElement("span"); n.className = "bd-more-n"; n.textContent = b.getAttribute("data-n") + " seções"; b.append(n, " ▾"); }
  });
}
function bdTitle(txt){ return String(txt || "").replace(/^#[ \t]+\S[^\n]*\n*/, "").trim(); }   // "# título" solto na primeira linha não aparece: o cartão já tem título (vale até se for só ele)
function renderDailyBrief(br){
  br = br || {};
  var txt = String(br.text || "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "").trim();
  txt = bdTitle(txt);
  const isToday = !!br.is_today;
  let body;
  if (isToday && !br.empty && txt) {
    const inner = briefHtml(txt), sections = (inner.match(/class="bd-h"/g) || []).length, clamp = sections > BD_MAX_SECTIONS;   // conta a seção que renderizou: vazia não dobra o brief
    const key = br.generated_at || br.date || "", open = clamp && !!key && BD_OPEN_KEY === key;
    if (clamp && document.addEventListener) {
      bdBindMore();
      if (!open && typeof requestAnimationFrame === "function") requestAnimationFrame(() => bdFitClamp());
    }
    body = '<div class="brief-body' + (clamp ? " is-clamped" : "") + (open ? " is-open" : "") + '">' + inner + "</div>" +
      (clamp ? '<button class="bd-more" type="button" aria-expanded="' + (open ? "true" : "false") + '" data-n="' + sections + '" data-key="' + esc(key) + '">' +
        (open ? "Mostrar menos" : "Mostrar tudo<span class=\"bd-more-n\">" + sections + " seções</span> ▾") + "</button>" : "");
  } else if (isToday) {
    body = '<p class="brief-quiet">' + esc(txt || "Sem novidades desde a última atualização.") + "</p>";
  } else {
    const last = br.exists && br.date ? " Último resumo: " + fmtDL(br.date) + "." : "";
    body = '<p class="brief-quiet">' + esc("Sem novidades ainda hoje — o resumo do dia aparece após a rotina." + last) + "</p>";
  }
  return '<section class="card brief-card' + (isToday && !br.empty && txt ? "" : " is-quiet") + '" id="daily-brief">' +
    '<header class="brief-head"><h2>Seu dia</h2><span class="brief-when">' + bdHealthLink() + bdWhen(br) + "</span></header>" + body + "</section>";
}
function syncFreshBadge(){
  const b = document.getElementById("freshbadge");
  if (!b) return;
  if (window.PF_ONLY) { b.hidden = true; return; }
  const sum = freshnessSummary(M.freshness);
  b.hidden = false;
  b.textContent = sum.label;
  b.classList.remove("fresh-ok", "fresh-warn");
  b.classList.add(sum.tone);
  b.title = sum.tooltip + " — clique para abrir Saúde";
}

// ── views ───────────────────────────────────────────────────────────────
const V = Object.create(null);
V.home = () => {
  const c = M.counts;
  const freshSum = freshnessSummary(M.freshness);
  let h = '<div class="pagehead"><div><h1>☀ ' + fmtDW(M.today) + "</h1>" +
    '<p class="sub">' + esc(M.owner.name) + " · " + c.mine_open + " ações abertas" + (c.mine_overdue ? ' · <b class="late">' + c.mine_overdue + " atrasadas</b>" : "") + "</p></div></div>";
  if (freshSum.anyStale && !isFreshDismissed(M.today)) h += renderFreshBanner(M.freshness, freshSum);
  h += renderDailyBrief(M.daily_brief);
  h += '<div class="kpis">' + [
    ["Minhas abertas", c.mine_open, ""], ["Atrasadas", c.mine_overdue, c.mine_overdue ? "risk" : "ok"],
    ["Vencem em 7 dias", c.mine_due_7d, ""], ["Bloqueadas", c.mine_blocked, c.mine_blocked ? "risk" : ""],
    ["Aguardando outros", c.waiting_open, ""], ["Conquistas 30d", c.wins_30d, "ok"], ["Decisões 30d", c.decisions_30d, ""]]
    .map(k => '<div class="kpi ' + k[2] + '"><span>' + k[0] + "</span><b>" + k[1] + "</b></div>").join("") + "</div>";
  const needs = [];
  (M.questions || []).filter(q => q.status === "aberta").forEach(q => needs.push('<li class="info">' + chip("info", q.id) + " " + esc(q.text.slice(0, 100)) + '… — <a class="feed-act" href="#ask">responder</a></li>'));
  M.proposals.forEach(p => needs.push('<li class="warn">' + chip("atencao", "proposta " + p.id) + " " + esc(p.summary) + (p.target ? " · alvo " + (A[p.target] ? aL(p.target) : esc(p.target)) : "") + ' — <a class="feed-act" href="#ask">decidir</a></li>'));
  if (M.focus && M.focus.status === "proposto") needs.push('<li class="info">' + chip("info", "foco " + M.focus.id) + " plano com " + M.focus.blocks.length + ' blocos aguardando seu "ok" — <a class="feed-act" href="#focus">ver</a></li>');
  M.outbox.filter(m => m.status === "rascunho").forEach(m => needs.push('<li class="info">' + chip("info", "rascunho " + m.id) + " para " + esc(m.to_name) + ': "' + esc(m.text.slice(0, 90)) + '" — <a class="feed-act" href="#outbox">revisar</a></li>'));
  const pl = (n, s, p) => n === 1 ? s : p;
  if (c.mine_no_due) needs.push('<li class="warn">' + chip("atencao", "prazo") + " " + c.mine_no_due + " " + pl(c.mine_no_due, "ação sua sem prazo", "ações suas sem prazo") + " — o foco não consegue agendá-las</li>");
  if (c.mine_no_effort) needs.push('<li class="warn">' + chip("atencao", "esforço") + " " + c.mine_no_effort + " " + pl(c.mine_no_effort, "ação sua sem estimativa", "ações suas sem estimativa") + " de esforço</li>");
  if (needs.length) h += panel("Precisa de você", '<ul class="feed">' + needs.join("") + "</ul>", ' data-priority');
  h += "<h2 class=\"sec\">Goals</h2>";
  if (!M.goals.length) h += empty("Nenhum goal no PLANNING ainda — rode /init ou /goal.");
  h += '<div class="grid g2">' + M.goals.map(g => '<section class="panel goal"><div class="goal-head">' + donut(g.progress.pct, 48) +
    '<div><b class="goal-title">' + g.id + " — " + esc(g.title) + "</b>" + chip(g.health, g.health_label) + goalReasonChip(g) +
    '<div class="muted small">' + (g.horizon ? "horizonte " + fmtDL(g.horizon) + " · " : "") + progTxt(g.progress) + ' · <button class="btn ghost tiny" data-progress="' + esc(g.id) + '">⛏ declarar %</button>' +
    (g.declared ? " · declarado " + g.declared.pct + "% em " + fmtD(g.declared.date) : "") + "</div></div></div>" +
    g.projects.map(pid => { const p = P[pid]; return '<div class="proj"><div class="t">' + pL(pid, true) + "<small>" + esc(p.health.reason) +
      (p.next_due ? " · próximo: " + p.next_due.id + " " + fmtD(p.next_due.date) : "") + "</small></div>" + bar(p.progress.pct) + chip(p.health.level, p.health.label) + "</div>"; }).join("") +
    filesBlock(g.files) +
    "</section>").join("") + "</div>";
  h += '<div class="grid g2" style="margin-top:14px">';
  const days = {};
  M.agenda.forEach(it => (days[it.date] = days[it.date] || []).push(it));
  const fKey = x => { const s = x.start || x.title || ""; const i = s.indexOf("T"); return i > 0 ? s.slice(i + 1) : s; };
  Object.values(days).forEach(arr => arr.sort((a, b) =>
    (a.kind !== "foco") - (b.kind !== "foco") ||
    (a.kind === "foco" ? fKey(a).localeCompare(fKey(b)) : 0) ||
    (a.id || "").localeCompare(b.id || "")
  ));
  h += panel("Hoje e próximos 7 dias", (Object.keys(days).length ? Object.keys(days).sort().map(d => "<h3 class=\"day\">" + fmtDW(d) + (d < M.today ? ' <span class="late">atrasado</span>' : d === M.today ? " · hoje" : "") + "</h3>" +
    '<ul class="feed">' + days[d].map(it => "<li>" + chip(it.kind === "foco" ? "info" : it.overdue_days ? "em-risco" : "atencao", it.kind) + " " +
      (it.id.startsWith("TASK-") ? aL(it.id) : "<b>" + esc(it.id) + "</b>") + " " + esc(it.title) + (it.project ? " · " + pL(it.project) : "") + "</li>").join("") + "</ul>").join("") : empty("Nada com data nos próximos 7 dias.")));
  const wins = [...M.deliveries.map(e => ({date: e.date, html: "✓ <b>" + esc(e.title) + "</b> — " + esc(e.result) + (e.project ? " · " + pL(e.project) : "")})),
    ...M.deliverables_done.map(x => ({date: x.date, html: "✓ entregável <b>" + x.id + "</b> " + esc(x.title) + " · " + pL(x.project)}))]
    .sort((a, b) => (b.date || "").localeCompare(a.date || "")).slice(0, 7);
  h += panel("Conquistas recentes", (wins.length ? '<ul class="feed">' + wins.map(w => '<li><span class="muted">' + fmtD(w.date) + "</span> · " + w.html + "</li>").join("") + "</ul>" :
    empty("Nenhuma entrega registrada ainda — declare no /week ou com /done.")) + '<p class="more"><a href="#wins">todas as conquistas →</a></p>');
  h += panel("Decisões recentes", (M.decisions.length ? '<ul class="feed">' + M.decisions.slice(0, 7).map(d => '<li><span class="muted">' + fmtD(d.date) + "</span> · " + dL(d.id) + " " + esc(d.title) +
    ' <span class="muted">— ' + d.decided_by_names.map(esc).join(", ") + "</span>" + (d.project ? " · " + pL(d.project) : "") + "</li>").join("") + "</ul>" : empty("Nenhuma decisão registrada.")));
  const waiting = M.actions.filter(a => a.open && a.list === "waiting"), by = {};
  waiting.forEach(a => (by[a.owner] = by[a.owner] || []).push(a));
  h += panel("Aguardando de outros", (waiting.length ? '<ul class="feed">' + Object.entries(by).sort((x, y) => y[1].length - x[1].length).map(([o, l]) => "<li><b>" + peL(o) + "</b> · " +
    l.map(a => aL(a.id) + " " + esc(a.title) + ' <span class="muted">(' + a.aging_days + "d)</span>").join("; ") + "</li>").join("") + "</ul>" : empty("Ninguém te devendo nada registrado.")));
  h += "</div>";
  // brief de hoje já tem o cartão "Seu dia"; aqui só aparece o de outro dia (o cartão, nesse caso, mostra o estado quieto)
  (M.notes || []).filter(n => n.name !== "brief" || !((M.daily_brief || {}).is_today)).forEach(n => { h += '<details class="panel note"><summary><b>Nota do agente · ' + esc(n.name) + '</b> <span class="muted">(FRESH/notes/' + esc(n.name) + ".md)</span></summary><div class=\"msg\"><div class=\"brief-body\">" + briefHtml(n.name === "brief" ? bdTitle(n.text) : n.text || "") + "</div></div></details>"; });
  setTimeout(() => {
    const hb = $("#fresh-health-btn");
    if (hb) hb.onclick = () => go("cfg/saude");
    const db = $("#fresh-dismiss-btn");
    if (db) db.onclick = () => {
      dismissFreshToday(M.today);
      const b = $("#freshbanner");
      if (b) b.remove();
    };
  });
  return h;
};
// ── visão geral do quadro (TODO): recolhível; aberta = cartões, recolhida = uma linha ──
// Os cartões também filtram o quadro (união). A contagem usa o mesmo predicado do filtro.
const TODO_KPI_KEY = "brain.todo.overview";
const TODO_KPI_ORDER = ["abertas", "atrasadas", "vencem", "fazendo", "bloqueadas", "depois", "outros", "feitas"];
function todoKpisOpen(){ try { return localStorage.getItem(TODO_KPI_KEY) !== "0"; } catch (e) { return true; } }
function setTodoKpisOpen(v){ try { localStorage.setItem(TODO_KPI_KEY, v ? "1" : "0"); } catch (e) {} }
function todoRecent(today){
  const recent = new Date((today || M.today) + "T12:00:00");
  recent.setDate(recent.getDate() - 14);
  return recent;
}
function todoIsBlk(a){
  return !!((a.blocked_by && a.blocked_by.length) || a.status === "bloqueada" || a.status === "aguardando");
}
function todoKpiHit(a, key, recent){
  const mine = a.list === "mine", open = !!a.open, parked = !!a.parked, act = open && !parked;
  if (key === "abertas") return mine && act;
  if (key === "atrasadas") return mine && act && !!a.overdue_days;
  if (key === "vencem") return mine && act && !a.overdue_days && a.due_in != null && a.due_in >= 0 && a.due_in <= 7;
  if (key === "fazendo") return mine && act && a.status === "fazendo";
  if (key === "bloqueadas") return mine && act && todoIsBlk(a);
  if (key === "depois") return mine && open && parked;
  if (key === "outros") return a.list === "waiting" && open;
  if (key === "feitas") return mine && a.status === "fechada" && !!a.closed && new Date(a.closed + "T12:00:00") >= recent;
  return false;
}
function todoKpiSelected(q){
  const raw = String((q && q.get("k")) || "").split(",").filter(Boolean);
  return TODO_KPI_ORDER.filter(k => raw.indexOf(k) >= 0);
}
function todoOverview(list, waitingN, selected){
  const recent = todoRecent(M.today);
  selected = selected || [];
  const labels = {abertas: "Abertas", atrasadas: "Atrasadas", vencem: "Vencem em 7 dias", fazendo: "Fazendo",
    bloqueadas: "Bloqueadas / aguardando", depois: "Depois", outros: "Aguardando outros", feitas: "Feitas 14d"};
  const n = {};
  TODO_KPI_ORDER.forEach(k => { n[k] = k === "outros" ? waitingN : list.filter(a => todoKpiHit(a, k, recent)).length; });
  const tone = {abertas: "", atrasadas: n.atrasadas ? "risk" : "ok", vencem: "", fazendo: "",
    bloqueadas: n.bloqueadas ? "risk" : "", depois: "later", outros: "", feitas: "ok"};
  const filtering = selected.length > 0;
  const pressed = key => selected.indexOf(key) >= 0;
  const chip = key => '<button type="button" class="ovp ' + (tone[key] || "") + (pressed(key) ? " is-on" : "") +
    '" data-kpi="' + key + '" aria-pressed="' + (pressed(key) ? "true" : "false") + '">' +
    esc(labels[key].toLowerCase()) + " <b>" + esc(n[key]) + "</b></button>";
  const card = key => '<button type="button" class="kpi ' + (tone[key] || "") +
    (pressed(key) ? " is-on" : (filtering ? " is-off" : "")) + '" data-kpi="' + key +
    '" aria-pressed="' + (pressed(key) ? "true" : "false") + '"><span>' + esc(labels[key]) +
    "</span><b>" + esc(n[key]) + "</b></button>";
  const on = todoKpisOpen();
  const clear = filtering ? '<button type="button" class="btn" id="kpiclear">limpar filtros</button>' : "";
  return '<div id="todo-ov" class="todo-ov' + (on ? " is-open" : "") + (filtering ? " is-filtering" : "") + '">' +
    '<div class="todo-ov-bar"><button class="btn ovtoggle" id="kpitoggle" aria-expanded="' + (on ? "true" : "false") +
    '" aria-controls="todo-ov-cards">' + (on ? "▾" : "▸") + " visão geral</button>" + clear +
    '<span class="todo-ov-line">' + TODO_KPI_ORDER.map(chip).join("") + "</span></div>" +
    '<div class="kpis" id="todo-ov-cards">' + TODO_KPI_ORDER.map(card).join("") + "</div></div>";
}
V.todo = (q) => {
  const proj = q.get("p") || "", showWatch = q.get("w") === "1";
  const view = q.get("v") || "todas", sortK = q.get("o") || "prazo", showAll = q.get("a") === "1";
  const selected = todoKpiSelected(q);
  const end = new Date(M.today + "T12:00:00"); { const d = end.getDay(); end.setDate(end.getDate() + (d === 0 ? 0 : 7 - d)); }
  const endS = end.toISOString().slice(0, 10);
  let mine = M.actions.filter(a => a.list === "mine" && (!proj || a.project === proj));      // a lista mine é a sua; o dono não filtra
  const all = mine;                                                                           // a visão geral segue o projeto, não a vista
  if (view === "semana") mine = mine.filter(a => a.open && !a.parked && ((a.due && a.due <= endS) || a.status === "fazendo"));
  else if (view === "adiante") mine = mine.filter(a => a.open && !a.parked && !((a.due && a.due <= endS) || a.status === "fazendo"));
  const recent = todoRecent(M.today);
  if (selected.length) mine = mine.filter(a => selected.some(k => k !== "outros" && todoKpiHit(a, k, recent)));
  // "Depois": adiada de propósito (parked, só o dono) — à esquerda, fora do atraso; arrastar para lá/de lá = --park/--unpark
  const isBlk = a => (a.blocked_by && a.blocked_by.length) || a.status === "bloqueada" || a.status === "aguardando";
  const cols = [["Depois", a => a.open && a.parked, "depois"],
    ["A fazer", a => a.open && !a.parked && !isBlk(a) && a.status === "aberta", "aberta"],
    ["Fazendo", a => a.open && !a.parked && !isBlk(a) && a.status === "fazendo", "fazendo"],
    ["Bloqueada / aguardando", a => a.open && !a.parked && isBlk(a), "aguardando"],
    ["Feita" + (showAll ? "" : " (14 dias)"), a => a.status === "fechada" && a.closed && (showAll || new Date(a.closed + "T12:00:00") >= recent), "fechada"]];
  const sortA = l => l.sort((x, y) => sortK === "id" ? x.id.localeCompare(y.id)
    : ((x.due || "9999").localeCompare(y.due || "9999") || (x.priority === "alta" ? -1 : 0)));
  const VIEWS = [["todas", "todas"], ["semana", "esta semana"], ["adiante", "mais adiante"]];
  let h = '<div class="pagehead"><div><h1>TODO</h1><p class="sub">Suas ações em quadro. Feche pelo chat (/done), marcando em FRESH/todo.md — ou pelo painel, se a ponte CLI estiver ligada. Arraste para Depois o que você adiou de propósito: lá não conta como atrasada.</p></div></div>' +
    todoOverview(all, (M.actions || []).filter(a => a.open && a.list === "waiting" && (!proj || a.project === proj)).length, selected) +
    '<div class="filters">' + dd("fp", M.projects.map(p => [p.id, p.id + " " + p.title]), proj, "todos os projetos") +
    dd("fv", VIEWS, view, "todas as vistas") + dd("fo", [["prazo", "por prazo"], ["id", "por id"]], sortK, "por prazo") +
    '<label class="chk"><input type="checkbox" id="fa"' + (showAll ? " checked" : "") + "> todas (fechadas além de 14d)</label>" +
    '<label class="chk"><input type="checkbox" id="fw"' + (showWatch ? " checked" : "") + "> mostrar observando</label></div>";
  h += '<div class="kanban">' + cols.map(([t, f, key]) => { const l = sortA(mine.filter(f)); return '<div class="col' + (key === "depois" ? " col-later" : "") + '" data-col="' + key + '"><h2>' + t + ' <span class="count">' + l.length + "</span></h2>" + (l.map(card).join("") || empty("—")) + "</div>"; }).join("") + "</div>";
  const waiting = M.actions.filter(a => a.open && a.list === "waiting" && (!proj || a.project === proj));
  if (!selected.length || selected.indexOf("outros") >= 0)
    h += panel("Aguardando de outros · " + waiting.length, actionTable(sortA(waiting).map(a => a.id), ["owner", "age", "project"]), ' style="margin-top:16px"');
  if (showWatch) {
    const w = M.actions.filter(a => a.open && a.list === "watching" && (!proj || a.project === proj));
    h += panel("Observando — contexto, não cobra · " + w.length, actionTable(w.map(a => a.id), ["owner", "project"]), ' style="margin-top:14px"');
  }
  setTimeout(() => {
    const kt = document.querySelector("#kpitoggle");
    if (kt) kt.onclick = () => { const open = !todoKpisOpen(); setTodoKpisOpen(open);
      const ov = document.querySelector("#todo-ov"); if (ov) ov.classList.toggle("is-open", open);
      kt.setAttribute("aria-expanded", open ? "true" : "false"); kt.textContent = open ? "▾ visão geral" : "▸ visão geral"; };
    const todoQ = extra => ({p: proj, w: showWatch ? "1" : "", v: view !== "todas" ? view : "",
      o: sortK !== "prazo" ? sortK : "", a: showAll ? "1" : "", k: selected.join(","), ...extra});
    document.querySelectorAll("#todo-ov [data-kpi]").forEach(el => {
      el.addEventListener("click", () => {
        const key = el.getAttribute("data-kpi");
        const next = selected.indexOf(key) >= 0 ? selected.filter(k => k !== key) : selected.concat(key);
        go("todo", todoQ({k: next.join(",")}));
      });
    });
    const clear = document.querySelector("#kpiclear");
    if (clear) clear.onclick = () => go("todo", todoQ({k: ""}));
    [["fp", "p"], ["fv", "v"], ["fo", "o"]].forEach(([id0, key]) => {
      const b = document.querySelector('[data-dd="' + id0 + '"] .dd-btn');
      if (b) b.addEventListener("ddchange", e => go("todo", todoQ({[key]: e.detail.value})));});
    const fa = document.querySelector("#fa");
    if (fa) fa.onchange = e => go("todo", todoQ({a: e.target.checked ? "1" : ""}));
    const c = document.querySelector("#fw");
    if (c) c.onchange = e => go("todo", todoQ({w: e.target.checked ? "1" : ""}));
  });
  return h;
};
V.projects = (q) => {
  let h = '<div class="pagehead"><div><h1>Projetos</h1><p class="sub">A árvore de PLANNING, por goal.</p></div></div>';
  if (!M.projects.length) return h + empty("Nenhum projeto no PLANNING.");
  M.goals.forEach(g => {
    h += '<h2 class="sec">' + g.id + " — " + esc(g.title) + " " + chip(g.health, g.health_label) + goalReasonChip(g) + '</h2><div class="grid g3">' + g.projects.map(pid => { const p = P[pid];
      return '<section class="panel projcard" id="proj-' + esc(p.id) + '"><div class="projcard-head">' + donut(p.progress.pct, 44) + '<div><b>' + pL(pid, true) + "</b>" + chip(p.health.level, p.health.label) +
        '<div class="muted small">' + progTxt(p.progress) + "</div></div></div>" +
        '<div class="muted small">' + esc(p.health.reason) + "</div>" +
        '<div class="foot small">' + p.actions.mine.length + " minhas · " + p.actions.waiting.length + " aguardando · " + p.decisions.length + " decisões" +
        (p.next_due ? " · próximo " + p.next_due.id + " " + fmtD(p.next_due.date) : "") + "</div></section>"; }).join("") + "</div>";
  });
  const focusId = q && q.get("focus");
  if (focusId) {
    setTimeout(() => {
      const el = document.getElementById("proj-" + focusId);
      if (el) {
        if (typeof el.scrollIntoView === "function") el.scrollIntoView({behavior: "smooth", block: "center"});
        el.classList.add("just-moved");
        setTimeout(() => el.classList.remove("just-moved"), 1400);
      }
    });
  }
  return h;
};
V.project = (q, id) => {
  const p = P[id]; if (!p) return empty("Projeto não encontrado: " + id);
  let h = '<p class="crumb muted"><a href="#projects">← projetos</a> · ' + p.goal + " " + esc(p.goal_title) + "</p>" +
    '<div class="pagehead"><div><h1>' + p.id + " — " + esc(p.title) + "</h1>" +
    '<div class="sub">' + chip(p.health.level, p.health.label) + "<span>" + esc(p.health.reason) + "</span>" + bar(p.progress.pct) +
    "<span>" + progTxt(p.progress) + "</span>" + (p.owner && PE[p.owner] ? "<span>dono: " + peL(p.owner) + "</span>" : "") +
    (p.declared ? "<span>declarado " + p.declared.pct + "% em " + fmtD(p.declared.date) + "</span>" : "") + "</div></div></div>";
  h += '<div class="grid g2">' + panel("Entregáveis", (p.deliverables.length ? '<ul class="feed">' + p.deliverables.map(d => '<li data-deliv="' + esc(d.id) + '" data-dstatus="' + esc(d.status) + '" title="space marca feito · s muda estado">' +
    '<button class="dmark ' + (d.status === "feito" ? "is-done" : d.status === "cancelado" ? "is-cancel" : d.status === "em-andamento" ? "is-doing" : "") + '">' +
    (d.status === "feito" ? "✓" : d.status === "cancelado" ? "×" : d.status === "em-andamento" ? "◐" : "○") + "</button> <b>" + d.id + "</b> " + esc(d.title) + ' <span class="muted">· ' +
    (d.done_date ? "feito " + fmtD(d.done_date) : d.due ? "prazo " + fmtDW(d.due) : "sem prazo") + "</span>" + (d.overdue_days ? ' <span class="late">⚠ venceu há ' + d.overdue_days + "d</span>" : "") +
    "</li>").join("") + "</ul>" : empty("Sem entregáveis — progresso não calculável.")));
  h += panel("Pessoas", (p.people.length ? '<ul class="feed">' + p.people.map(x => "<li>" + peL(x.id) + ' <span class="muted">— ' + x.roles.map(esc).join(", ") + " (" + x.count + ")</span></li>").join("") + "</ul>" : empty("—"))) + "</div>";
  h += panel("Decisões — quem decidiu o quê, quando", decisionTable(p.decisions.map(d => D[d])), ' style="margin-top:14px"');
  h += '<div class="grid g2" style="margin-top:14px">' + panel("Minhas ações · " + p.actions.mine.length, actionTable(p.actions.mine, ["status", "age"]) +
    "<h2>Aguardando de outros · " + p.actions.waiting.length + "</h2>" + actionTable(p.actions.waiting, ["owner", "age"]) +
    (p.actions.watching.length ? "<h2>Observando · " + p.actions.watching.length + "</h2>" + actionTable(p.actions.watching, ["owner"]) : "") +
    (p.actions.closed.length ? "<h2>Fechadas recentemente</h2><ul class=\"feed\">" + p.actions.closed.map(aid => { const a = A[aid]; return '<li><span class="muted">' + fmtD(a.closed) + "</span> · " + aL(aid) + " " + esc(a.title) + ' <span class="muted">(' + esc(a.owner_name) + ") — " + esc(a.how) + "</span></li>"; }).join("") + "</ul>" : ""));
  h += panel("Linha do tempo", timelineList(p.timeline, 80)) + "</div>";
  h += filesBlock(p.files);
  return h;
};
V.decisions = (q) => {
  const proj = q.get("p") || "", who = q.get("who") || "", st = q.get("s") || "";
  const list = M.decisions.filter(d => (!proj || d.project === proj) && (!who || d.decided_by.includes(who)) && (!st || d.status === st));
  let h = '<div class="pagehead"><div><h1>Decisões</h1><p class="sub">Quem decidiu o quê, quando — e de onde veio. Substituídas ficam riscadas, nunca apagadas.</p></div></div>';
  h += '<div class="filters">' +
    dd("dp", M.projects.map(p => [p.id, p.id + " " + p.title]), proj, "todos os projetos") +
    dd("dw", M.people.filter(p => (p.decisions || []).length).map(p => [p.id, p.name]), who, "qualquer pessoa") +
    dd("ds", [["ativa", "ativas"], ["substituida", "substituídas"]], st, "qualquer estado") + "</div>";
  h += panel("", decisionTable(list));
  setTimeout(() => { const f = () => go("decisions", {p: ddVal("dp"), who: ddVal("dw"), s: ddVal("ds")});
    ["dp", "dw", "ds"].forEach(i => { const b = document.querySelector('[data-dd="' + i + '"] .dd-btn'); if (b) b.addEventListener("ddchange", f); }); });
  return h;
};
V.wins = () => {
  const w = M.wins, weeks = [...w.weeks].reverse();
  const vals = weeks.map(k => ({d: k.deliveries.length + k.deliverables.length, c: k.closed.length}));
  const max = Math.max(1, ...vals.map(v => v.d + v.c)), W = 640, H = 150, bw = W / Math.max(1, weeks.length);
  let svg = '<svg viewBox="0 0 ' + W + " " + (H + 24) + '" width="100%" style="max-width:720px">';
  weeks.forEach((k, i) => { const v = vals[i], hd = v.d / max * H, hc = v.c / max * H, x = i * bw + 6;
    svg += '<rect x="' + x + '" y="' + (H - hd - hc) + '" width="' + (bw - 12) + '" height="' + hc + '" rx="4" fill="var(--chart-b)"><title>' + v.c + " ações fechadas</title></rect>";
    svg += '<rect x="' + x + '" y="' + (H - hd) + '" width="' + (bw - 12) + '" height="' + hd + '" rx="4" fill="var(--chart-a)"><title>' + v.d + " entregas</title></rect>";
    svg += '<text x="' + (x + (bw - 12) / 2) + '" y="' + (H + 16) + '" text-anchor="middle">S' + k.key.split("-W")[1] + "</text>"; });
  svg += "</svg>";
  let h = '<div class="pagehead"><div><h1>Conquistas</h1><p class="sub">O que saiu — entregas, entregáveis e ações fechadas.</p></div></div>' +
    '<div class="kpis"><div class="kpi ok"><span>entregas + entregáveis (30d)</span><b>' + w.last_30d + "</b></div>" +
    '<div class="kpi"><span>ações suas fechadas (30d)</span><b>' + w.closed_30d + "</b></div></div>";
  h += panel("", '<div class="legend"><span><i style="background:var(--chart-a)"></i>entregas e entregáveis</span><span><i style="background:var(--chart-b)"></i>ações fechadas</span></div>' + svg);
  w.weeks.forEach(k => {
    const items = [...k.deliveries.map(id => { const e = DL[id]; return "<li>✓ <b>" + esc(e.title) + '</b> <span class="muted">' + fmtD(e.date) + "</span> — " + esc(e.result) + (e.impact ? " · impacto: " + esc(e.impact) : "") + (e.project ? " · " + pL(e.project) : "") + ' <span class="muted">[' + esc(e.prov) + "]</span>" + ((e.files || []).map(f => ' <button type="button" class="btn tiny" data-read="' + esc(f.rel) + '">' + esc(f.name) + "</button>").join("")) + "</li>"; }),
      ...k.deliverables.map(id => { const x = DD[id]; return "<li>✓ entregável <b>" + id + "</b> " + esc(x.title) + ' <span class="muted">' + fmtD(x.date) + "</span> · " + pL(x.project) + "</li>"; })];
    h += '<h2 class="sec">' + esc(k.label) + ' <span class="muted">· ' + (k.deliveries.length + k.deliverables.length) + " entregas · " + k.closed.length + " ações fechadas · " + k.decisions.length + " decisões</span></h2>" +
      panel("", (items.length ? '<ul class="feed">' + items.join("") + "</ul>" : "") + (k.closed.length ? '<p class="muted small">Ações fechadas: ' + k.closed.map(id => aL(id) + " " + esc(A[id].title)).join(" · ") + "</p>" : "") +
      (!items.length && !k.closed.length ? empty("nada registrado") : ""));
  });
  return h;
};
V.people = () => {
  const cnt = v => Array.isArray(v) ? v.length : "—";
  return '<div class="pagehead"><div><h1>Pessoas</h1><p class="sub">Uma ficha por pessoa — nunca duas.</p></div></div>' +
    panel("", '<div class="twrap"><table><tr><th>Pessoa</th><th>Papel</th><th>Última interação</th><th>Me deve</th><th>Devo</th><th>Decisões</th></tr>' +
    (M.people || []).map(p => "<tr><td>" + peL(p.id) + (p.is_owner ? " " + chip("info", "você") : "") + "</td><td>" + esc(p.role || "—") + '</td><td class="muted">' + (p.last_interaction ? fmtD(p.last_interaction.date) + " " + esc(p.last_interaction.title) : "—") +
      '</td><td class="num">' + cnt(p.owes_me) + '</td><td class="num">' + cnt(p.i_owe) + '</td><td class="num">' + cnt(p.decisions) + "</td></tr>").join("") + "</table></div>");
};
V.person = (q, id) => {
  const p = PE[decodeURIComponent(id)]; if (!p) return empty("Pessoa não encontrada");
  let h = '<p class="crumb muted"><a href="#people">← pessoas</a></p><div class="pagehead"><div><h1>' + esc(p.name) + "</h1>" +
    '<p class="sub">' + esc(p.role || "papel não registrado") + " · relação: " + esc(p.relation || "—") +
    " · aliases: " + ((p.aliases || []).map(esc).join(", ") || "—") + "</p></div></div>";
  h += "<p><b>Última interação:</b> " + (p.last_interaction ? fmtDL(p.last_interaction.date) + " — " + esc(p.last_interaction.title) : "não consta") + "</p>";
  h += '<div class="grid g2">' + panel("O que me deve", actionTable(p.owes_me || [], ["age", "project"]) + "<h2>O que eu devo</h2>" + actionTable(p.i_owe || [], ["project"]));
  h += panel("Decisões que tomou", ((p.decisions || []).length ? '<ul class="feed">' + (p.decisions || []).map(d => '<li><span class="muted">' + fmtD(D[d] ? D[d].date : "") + "</span> · " + dL(d) + " " + esc(D[d] ? D[d].title : d) + "</li>").join("") + "</ul>" : empty("nenhuma registrada")) +
    "<h2>Projetos</h2>" + ((p.projects || []).map(x => pL(x, true)).join(" · ") || empty("—")) +    '<h2>Menções recentes</h2><ul class="feed">' + (p.artifacts || []).filter(a => ART[a]).map(a => '<li><span class="muted">' + fmtD(ART[a].date) + "</span> · " + esc(ART[a].title) + (ART[a].raw ? " · " + pathLink(ART[a].raw) : "") + "</li>").join("") + "</ul>") + "</div>";
  h += filesBlock(p.files);
  return h;
};
V.timeline = () => {
  const tl = M.timeline, t0 = new Date(M.today + "T00:00:00"), t1 = new Date(tl.ahead + "T00:00:00"), span = Math.max(1, (t1 - t0) / 864e5);
  const rows = {}; tl.future.forEach(it => (rows[it.project || "—"] = rows[it.project || "—"] || []).push(it));
  const keys = Object.keys(rows), W = 980, L = 220, rh = 34, H = keys.length * rh + 30;
  let svg = '<svg viewBox="0 0 ' + W + " " + H + '" width="100%">';
  for (let d = 0; d <= span; d += 7) { const x = L + d / span * (W - L - 10), dt = new Date(t0.getTime() + d * 864e5);
    svg += '<line x1="' + x + '" y1="18" x2="' + x + '" y2="' + H + '" stroke="currentColor" opacity=".12"/><text x="' + x + '" y="12" text-anchor="middle">' + String(dt.getDate()).padStart(2, "0") + "/" + String(dt.getMonth() + 1).padStart(2, "0") + "</text>"; }
  svg += '<line x1="' + L + '" y1="16" x2="' + L + '" y2="' + H + '" stroke="var(--risk)" stroke-width="2"/>';
  keys.forEach((k, i) => { const y = 30 + i * rh;
    svg += '<text x="4" y="' + (y + 4) + '">' + esc((P[k] ? k + " " + P[k].title : "sem projeto").slice(0, 30)) + "</text>";
    rows[k].forEach(it => { const dd = Math.max(0, (new Date(it.date + "T00:00:00") - t0) / 864e5), x = L + dd / span * (W - L - 10);
      const col = it.overdue ? "var(--risk)" : it.kind === "entregável" ? "#7048e8" : "var(--info)";
      svg += '<path d="M' + x + " " + (y - 7) + " l7 7 l-7 7 l-7 -7z" + '" fill="' + col + '"><title>' + esc(it.id + " " + it.title + " · " + fmtD(it.date)) + "</title></path>"; }); });
  svg += "</svg>";
  let h = '<div class="pagehead"><div><h1>Linha do tempo</h1><p class="sub">Prazos à frente e o que aconteceu.</p></div></div>' +
    panel("Próximos prazos", '<div class="legend"><span><i style="background:#7048e8"></i>entregável</span><span><i style="background:var(--info)"></i>ação sua</span><span><i style="background:var(--risk)"></i>atrasado / hoje</span></div>' +
    (tl.future.length ? '<div class="twrap">' + svg + "</div>" + '<ul class="feed">' + tl.future.map(it => "<li>" + fmtDW(it.date) + " · " + esc(it.kind) + " " + (it.id.startsWith("TASK-") ? aL(it.id) : "<b>" + esc(it.id) + "</b>") + " " + esc(it.title) + (it.project ? " · " + pL(it.project) : "") + (it.overdue ? ' <span class="late">atrasado</span>' : "") + "</li>").join("") + "</ul>" :
      empty("Nenhum prazo à frente — itens sem data não aparecem aqui.")));
  h += panel("O que aconteceu · desde " + fmtD(tl.back), timelineList(tl.past, 200), ' style="margin-top:14px"');
  return h;
};
V.focus = () => {
  const f = M.focus;
  if (!f) return '<div class="pagehead"><div><h1>Foco</h1></div></div>' + empty('Nenhum plano ainda. Peça /focus no chat: o agente lê sua agenda e propõe os blocos da semana.');
  const st = {proposto: ["atencao", 'aguardando seu "ok" — nada foi para o calendário'], aprovado: ["info", "aprovado — falta aplicar"], aplicado: ["em-dia", "aplicado (" + f.mode + ")"], substituido: ["", "substituído"]}[f.status];
  const blocks = f.status === "aplicado" ? f.applied : f.blocks;
  const busy = f.busy || [];
  const days = [...new Set([...blocks.map(b => b.start.slice(0, 10)), ...busy.map(e => e.start.slice(0, 10))])].sort();
  const toMin = s => +s.slice(11, 13) * 60 + +s.slice(14, 16);
  const all = [...blocks.map(b => [toMin(b.start), toMin(b.end)]), ...busy.map(e => [toMin(e.start), toMin(e.end)])];
  const minS = Math.min(9 * 60, ...all.map(x => x[0])), maxE = Math.max(18 * 60, ...all.map(x => x[1]));
  const span = Math.max(60, maxE - minS);
  const clash = b => busy.some(e => e.start.slice(0, 10) === b.start.slice(0, 10) &&
    toMin(b.start) < toMin(e.end) && toMin(b.end) > toMin(e.start));
  const hours = [];
  for (let t = Math.ceil(minS / 60) * 60; t <= maxE; t += 60) hours.push(t);
  const hourMark = t => { const pc = (t - minS) / span * 100;
    let s = "top:" + pc + "%";
    if (pc <= 0.5) s = "top:0;transform:none";                       // primeira hora: não vazar acima do eixo
    else if (pc >= 99.5) s = "top:auto;bottom:0;transform:none";     // última hora: não vazar abaixo
    return '<span class="hourmark" style="' + s + '">' + String(Math.floor(t / 60)).padStart(2, "0") + "</span>"; };
  const stepPct = 100 / (span / 60);
  const gridBg = 'background-image:repeating-linear-gradient(to bottom,transparent 0,transparent calc(' + stepPct + '% - 1px),var(--line2) calc(' + stepPct + '% - 1px),var(--line2) ' + stepPct + '%)';
  let h = '<div class="pagehead"><div><h1>Foco</h1><div class="sub">' + chip(st[0], "plano " + f.id) + "<span>" + st[1] + "</span>" +
    (f.quote ? '<span class="muted">aprovação: "' + esc(f.quote) + '"</span>' : "") + "</div></div></div>";
  h += '<div class="legend"><span><i style="background:var(--info)"></i>bloco de foco' + (f.status === "aplicado" ? "" : " (proposto)") + '</span>' +
    '<span><i style="background:var(--muted)"></i>calendário (ocupado)</span>' +
    '<span><i style="background:var(--risk)"></i>conflito com o calendário</span></div>';
  h += '<div class="week" style="grid-template-columns:34px repeat(' + Math.max(1, days.length) + ',minmax(108px,1fr))">' +
    '<div class="hcol"><div class="wslot" style="' + gridBg + '">' +
    hours.map(hourMark).join("") +
    "</div></div>" + days.map(d => '<div class="wday"><h2>' + fmtDW(d) + '</h2><div class="wslot" style="' + gridBg + '">' +
    busy.filter(e => e.start.startsWith(d)).sort((a, b) => (a.start || "").localeCompare(b.start || "")).map(e => { const top = (toMin(e.start) - minS) / span * 100, hgt = (toMin(e.end) - toMin(e.start)) / span * 100;
      return '<div class="blk busy' + (hgt < 4.5 ? " tiny" : "") + '" style="top:' + top + "%;height:" + hgt + '%"><b>' + e.start.slice(11, 16) + "–" + e.end.slice(11, 16) + "</b> " + esc(e.title || "ocupado") + "</div>"; }).join("") +
    blocks.filter(b => b.start.startsWith(d)).sort((a, b) => (a.start || "").localeCompare(b.start || "")).map(b => { const top = (toMin(b.start) - minS) / span * 100, hgt = (toMin(b.end) - toMin(b.start)) / span * 100, a = A[b.action];
      const conflict = f.status !== "aplicado" && clash(b);
      const mins = toMin(b.end) - toMin(b.start);
      return '<div class="blk' + (f.status === "aplicado" || b.applied ? "" : " prop") + (conflict ? " conflict" : "") + (hgt < 4.5 ? " tiny" : "") +
        '" style="top:' + top + "%;height:" + hgt + '%" data-action="' + esc(b.action) + '"' +
        ' title="' + esc((a ? a.title : "") + (conflict ? " — conflita com evento do calendário" : "")) + '">' +
        '<b>' + b.start.slice(11, 16) + "–" + b.end.slice(11, 16) + "</b> " + aL(b.action) + (mins >= 90 ? "<br>" + esc(a ? a.title : "") : "") +
        (conflict ? ' <b class="late">⚠</b>' : "") + "</div>"; }).join("") +
    "</div></div>").join("") + "</div>";
  if (f.status === "proposto") h += '<p class="muted small" style="margin:8px 2px 0">Clique num bloco proposto para reservá-lo (aprova e aplica o plano no calendário).</p>';
  if (f.at_risk.length) h += panel("⚠ Não cabe antes do prazo", '<ul class="feed">' + f.at_risk.map(r => "<li>" + aL(r.action) + " " + esc((A[r.action] || {}).title || "") + " · prazo " + fmtDW(r.due) + " · faltam <b>" + dur(r.shortfall_min) + "</b> de " + dur(r.needed_min) + "</li>").join("") + "</ul>", ' data-priority');
  if (f.missing_effort.length) h += panel("Sem estimativa de esforço (usei o padrão)", f.missing_effort.map(aL).join(", "));
  if (f.consumed.length) h += panel("Esforço consumido e ainda aberta — reestimar?", f.consumed.map(aL).join(", "));
  h += filesBlock(f.files);
  return h;
};
V.outbox = (q) => {
  const all = !!(q && q.get("a") === "1");                      // T: só pendentes (padrão, como o TUI) ↔ todas
  const groups = [["Aguardando sua aprovação", ["rascunho"]], ["Aprovadas, não enviadas", ["aprovada"]], ["Enviadas", ["enviada"]], ["Falhas / canceladas", ["falhou", "cancelada"]]]
    .filter((g, i) => all || i < 2);
  let h = '<div class="pagehead"><div><h1>Mensagens</h1><p class="sub">Nada é enviado sem sua aprovação do texto exato. Todo envio fica registrado.</p></div></div>';
  return h + groups.map(([t, s]) => {
    const l = M.outbox.filter(m => s.includes(m.status));
    return panel(t + " · " + l.length, (l.map(m => {
      const perm = safeUrl(m.link);
      return "<div class=\"msgrow\"><header><b>" + m.id + "</b> → " + esc(m.to_name) + (m.ref ? " · ref " + (A[m.ref] ? aL(m.ref) : esc(m.ref)) : "") + (m.why ? ' <span class="muted">· ' + esc(m.why) + "</span>" : "") +
      (m.sent ? ' <span class="muted">· enviada ' + fmtD(m.sent) + "</span>" : "") +
      (perm ? ' · <a href="' + esc(perm) + '" target="_blank" rel="noopener">permalink</a>' : "") +
      "</header>" + '<div class="msg">' + esc(m.text) + "</div></div>";
    }).join("") || empty("—")), ' style="margin-top:14px"');
  }).join("");
};
V.feedback = (q) => {
  const all = !!(q && q.get("a") === "1");                      // T: só pendentes (padrão, como o TUI) ↔ todas
  const glyph = {sugestao: "💡", bug: "🐞"};
  const issueChip = f => {
    if (f.status !== "criado" && f.status !== "retratado") return "";
    if (f.issue_state === "open") return " " + chip("info", "issue aberta");
    if (f.issue_state === "gone") return " " + chip("em-risco", "issue apagada");
    if (f.issue_state === "closed") {
      const why = f.issue_reason === "not_planned" ? " · não será feita" : f.issue_reason === "completed" ? " · concluída" : "";
      return " " + chip("em-dia", "issue fechada" + why);
    }
    return f.status === "retratado" ? "" : ' <span class="muted small">issue ? — s sincroniza</span>';
  };
  const statusChip = s => chip(s === "criado" ? "em-dia" : s === "falhou" ? "em-risco" : s === "retratado" ? "atencao" : "info", s);
  const row = f => {
    const issueUrl = safeUrl(f.url);
    const commentUrl = safeUrl(f.comment_url);
    return "<div class=\"msgrow\" data-sel=\"" + esc(f.id) + "\"><header><b>" + f.id + "</b> " + glyph[f.kind] + " " + esc(f.title) + " " +
      statusChip(f.status) +
      (f.number && issueUrl ? ' · <a href="' + esc(issueUrl) + '" target="_blank" rel="noopener">issue #' + esc(f.number) + "</a>" : "") +
      issueChip(f) +
      (f.added ? ' <span class="muted">· ' + fmtD(f.added) + "</span>" : "") +
      (f.status === "pendente" || f.status === "falhou"
        ? ' · <button class="btn tiny" data-fb="' + esc(f.id) + '" title="criar a issue no GitHub">p publicar</button>' +
          ' <button class="btn tiny" data-fbwithdraw="' + esc(f.id) + '" title="retirar rascunho antes de publicar">d retirar</button>'
        : "") +
      (f.status === "criado"
        ? ' · <button class="btn tiny" data-fbretract="' + esc(f.id) + '" title="retratar issue publicada (fechar ou corrigir texto)">r retratar</button>'
        : "") +
      "</header>" + (f.issue_diverged ? '<p class="late">O texto no GitHub divergiu do que foi enviado.</p>' : "") + ((f.issue_body || f.body) ? '<div class="msg">' + esc(f.issue_title || "") + "\n\n" + esc(f.issue_body || f.body) + "</div>" : "") +
      ((f.status === "retirado" || f.status === "retratado") && f.reason
        ? '<div class="msg muted"><b>Motivo' + (f.retract_mode ? " (" + esc(f.retract_mode) + ")" : "") + ":</b> " + esc(f.reason) +
          (commentUrl ? ' · <a href="' + esc(commentUrl) + '" target="_blank" rel="noopener">comentário</a>' : "") + "</div>"
        : "") +
      ((f.status === "falhou" || (f.status === "criado" && f.error)) && f.error ? '<div class="msg muted">' + esc(f.error) + "</div>" : "") + "</div>";
  };
  const pend = M.feedback.filter(f => f.status === "pendente" || f.status === "falhou");
  const done = M.feedback.filter(f => f.status !== "pendente" && f.status !== "falhou");
  const doneTitle = 'Já no GitHub / encerradas · ' + done.length + ' <button class="btn tiny" data-fbsync title="relê o estado dos issues no GitHub">s sincronizar</button>';
  return '<div class="pagehead"><div><h1>Sugestões e bugs</h1><p class="sub">Porta 7 — cada registro vira uma issue pública no repo do framework. O texto não carrega nada seu: nomes, e-mails e caminhos ficam fora.</p></div></div>' +
    panel("Pendente de publicar · " + pend.length, pend.map(row).join("") || empty("nada pendente — n para sugerir ou reportar"), ' style="margin-top:14px"') +
    (all ? panel(doneTitle, done.map(row).join("") || empty("—"), ' style="margin-top:14px"') : "");
};
V.health = () => '<div class="pagehead"><div><h1>Saúde</h1><p class="sub">Checagens do brain doctor.</p></div></div>' +
  panel("", '<ul class="feed health">' + (M.health || []).map((c, i) => '<li class="' + c.level + '" data-sel="health:' + i + '"><span class="hicon">' + ({ok: "✓", warn: "⚠", error: "✗"}[c.level]) + "</span> <b>" + esc(c.title) + "</b> — " + esc(c.detail) + (c.fix ? ' <span class="muted small">· f ' + esc(c.fix.label) + "</span>" : "") + "</li>").join("") + "</ul>");
V["cfg/saude"] = V.health;                      // face Configurações: a mesma régua do doctor
// os passos da configuração guiada moram aqui: a view só monta o esqueleto, o extra.js preenche pela ponte
// (/api/onboard/*, os mesmos endpoints do /onboarding). Painel aberto como arquivo: só o aviso de abrir pelo app.
const setupView = (step, title, lead) => () => '<div class="pagehead"><div>' + (step === "inicio" ? '<p class="kicker">Configuração guiada</p>' : "") +
  "<h1>" + title + '</h1><p class="sub">' + lead + '</p></div></div><div id="setup" data-step="' + step + '"><p class="muted">carregando…</p></div>';
V["cfg/inicio"] = setupView("inicio", "Seu Brain", "Volte a qualquer passo quando quiser. Passo pulado fica como \"depois\" e não vira pendência.");
V["cfg/perfil"] = setupView("perfil", "Perfil", "Quem você é e o contexto que o Brain usa para entender o que importa para você.");
V["cfg/rotina"] = setupView("rotina", "Rotina", "Fuso e expediente: o Brain calcula prazos e blocos de foco a partir daqui.");
V["cfg/agente"] = setupView("agente", "Seu agente", "O agente de IA que lê suas fontes e ajuda nas rotinas. Conectar cria o canal de leitura (MCP somente-leitura).");
V["cfg/conectores"] = setupView("conectores", "Conectores", "O que o Brain pode ler, sempre só leitura. Nada é enviado sem você aprovar o texto exato.");
V["cfg/integracoes"] = setupView("integracoes", "Integrações", "Opcionais. As chaves ficam só no seu computador e nunca aparecem de novo na tela.");
V["cfg/memoria"] = () => {
  const rows = [["llm", "LLM"], ["embeddings", "Embeddings"], ["reranker", "Reranker"], ["decision", "Decisão"]].map(([k, icon]) => {
    const p = M.providers[k] || {};
    const egress = p.cloud ? '<span class="late">☁ egress</span>' : (p.local ? '<span class="dim">local</span>' : "");
    const key = p.key_env ? (p.key_present ? '<span class="ok">chave ok</span>' : '<span class="late">sem chave</span>') : "";
    const rec = k === "decision" && p.recall ? ' <span class="late">· recall (top-' + esc(String(p.candidates || "?")) + ")</span>" : "";
    const inert = k === "reranker" && p.inert ? ' <span class="dim">· inerte (decisor no recall)</span>' : "";
    return "<tr><td><b>" + icon + "</b></td><td>" + esc(p.label || "—") + rec + inert + "</td><td>" + esc(p.model || "—") + "</td><td>" + egress + " " + key + "</td></tr>";
  }).join("");
  return '<div class="pagehead"><div><h1>Memória</h1><p class="sub">O modo e os provedores (LLM · embeddings · reranker · decisão) — configuração viva: mude quando quiser.</p></div></div>' +
    '<div id="setup" data-step="memoria"></div>' +
    panel("Provedores", '<div class="twrap"><table><tr><th>Slot</th><th>Provedor</th><th>Modelo</th><th></th></tr>' + rows + "</table></div>" +
      '<p class="note-s" style="margin:10px 2px">A chave mora no config/.env e nunca aparece aqui. Trocou embeddings? O comando rebuild da memória re-deriva os vetores do vault. Depois de trocar, recrie o container (compose com o env-file da config).</p>' +
      '<button class="btn primary" data-provform>Trocar provedor</button>');
};
function filesBlock(files) {
  if (!files || !files.length) return "";
  const reader = !!(window.BRAIN && window.BRAIN.M && window.BRAIN.M.open && window.BRAIN.M.open.reader);
  const rows = files.map(f =>
    '<li><button type="button" class="btn tiny" data-open="' + esc(f.rel) + '">Abrir</button> ' +
    '<button type="button" class="btn tiny" data-read="' + esc(f.rel) + '">Ver</button> ' +
    esc(f.kind) + " · " + esc(f.name) +
    ' <span class="muted">→ ' + esc(f.app || "padrão do sistema") + "</span></li>").join("");
  return panel("Arquivos linkados", '<p class="muted small"><button type="button" class="btn tiny" data-openform="open.set">Como abrir</button> ' +
    '<button type="button" class="btn tiny" data-opentoggle>' + (reader ? "Abrir no editor" : "Ver no Brain") + '</button> ' +
    '<button type="button" class="btn tiny" data-openall>abrir tudo</button></p><ul class="feed">' + rows + "</ul>");
}
V.action = (q, id) => {
  const a = A[id]; if (!a) return empty("Ação não encontrada");
  return '<p class="crumb muted"><a href="#todo">← TODO</a></p><div class="pagehead"><div><h1>' + a.id + " · " + esc(a.title) + '</h1>' +
    '<div class="sub">' + chip(a.status === "bloqueada" ? "em-risco" : a.open ? "info" : "em-dia", a.status) +
    "<span>dono: " + peL(a.owner) + "</span><span>" + dueTxt(a) + "</span>" + (a.effort_min ? "<span>esforço " + dur(a.effort_min) + "</span>" : "") + (a.project ? "<span>" + pL(a.project, true) + "</span>" : "") + "</div></div>" +
    '<div class="ask-opts"><button class="btn" data-act="edit" data-id="' + esc(a.id) + '">e editar</button>' +
    (a.open ? '<button class="btn primary" data-act="close" data-id="' + esc(a.id) + '">c fechar</button>' : '<button class="btn" data-act="reopen" data-id="' + esc(a.id) + '">o reabrir</button>') +
    '<button class="btn" data-act="merge" data-id="' + esc(a.id) + '">m mesclar duplicada</button></div></div>' +
    panel("", (a.blocked_by.length ? "<p>⛔ bloqueada por " + a.blocked_by.map(aL).join(", ") + "</p>" : "") + (a.unblocks.length ? "<p>destrava: " + a.unblocks.map(u => A[u] ? aL(u) : esc(u)).join(", ") + "</p>" : "") +
    (a.people.length ? "<p>envolvidos: " + a.people.map(peL).join(", ") + "</p>" : "") + '<p class="muted small">origem: ' + esc(a.source_label) + (a.source && a.source.indexOf("/") >= 0 ? " (" + pathLink(a.source) + ")" : "") + " [" + esc(a.prov) + "]</p>" + filesBlock(a.files) + (a.outcome ? "<p><b>Resultado:</b> " + esc(a.outcome) + "</p>" : "") +
    "<h2>Histórico</h2>" + '<ul class="feed">' + a.history.map(x => '<li><span class="muted">' + fmtD(x.date) + "</span> · " + esc(x.type) + " · " + esc(x.note) + ' <span class="muted">(' + esc(x.by) + ")</span></li>").join("") + "</ul>");
};
V.decision = (q, id) => {
  const d = D[id]; if (!d) return empty("Decisão não encontrada");
  return '<p class="crumb muted"><a href="#decisions">← decisões</a></p><div class="pagehead"><div><h1>' + d.id + " · " + esc(d.title) + "</h1></div></div>" +
    panel("", "<p>Decidido por " + d.decided_by.map(peL).join(", ") + " em <b>" + fmtDL(d.date) + "</b>" + (d.project ? " · " + pL(d.project, true) : "") + "</p>" +
    (d.context ? "<p><b>Contexto:</b> " + esc(d.context) + "</p>" : "") + (d.rationale ? "<p><b>Por quê:</b> " + esc(d.rationale) + "</p>" : "") +
    '<p class="muted small">Fonte: ' + esc(d.source_label) + " (" + pathLink(d.source) + ") [" + esc(d.prov) + "]</p>" + filesBlock(d.files) + (d.supersedes ? "<p>Substitui " + dL(d.supersedes) + "</p>" : "") + (d.superseded_by ? '<p class="late">Substituída por ' + dL(d.superseded_by) + "</p>" : ""));
};
V.search = (q) => {
  const terms = (q.get("q") || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").split(/\s+/).filter(t => t.length > 1);
  const norm = s => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const hit = s => terms.length && terms.every(t => norm(s).includes(t));
  const res = [];
  M.actions.forEach(a => hit(a.id + " " + a.title + " " + a.owner_name + " " + (a.project_title || "") + " " + a.how) && res.push(["ação", aL(a.id) + " " + esc(a.title) + ' <span class="muted">' + esc(a.owner_name) + " · " + a.status + "</span>"]));
  M.decisions.forEach(d => hit(d.id + " " + d.title + " " + d.decided_by_names.join(" ") + " " + d.context) && res.push(["decisão", dL(d.id) + " " + esc(d.title) + ' <span class="muted">' + fmtD(d.date) + " · " + d.decided_by_names.map(esc).join(", ") + "</span>"]));
  M.projects.forEach(p => hit(p.id + " " + p.title + " " + p.deliverables.map(x => x.title).join(" ")) && res.push(["projeto", pL(p.id, true)]));
  M.people.forEach(p => hit(p.name + " " + p.aliases.join(" ") + " " + p.role) && res.push(["pessoa", peL(p.id) + ' <span class="muted">' + esc(p.role) + "</span>"]));
  M.deliveries.forEach(e => hit(e.title + " " + e.result) && res.push(["entrega", esc(e.title) + ' <span class="muted">' + fmtD(e.date) + "</span>"]));
  M.artifacts.forEach(x => hit(x.title + " " + x.summary) && res.push(["artefato", esc(x.title) + ' <span class="muted">' + fmtD(x.date) + " · " + esc(x.id) + "</span>"]));
  return '<div class="pagehead"><div><h1>Busca: ' + esc(q.get("q")) + "</h1></div></div>" +
    panel("", res.length ? '<ul class="feed">' + res.map(r => "<li>" + chip("info", r[0]) + " " + r[1] + "</li>").join("") + "</ul>" : empty("não consta"));
};

// ── portfólio (dentro do painel de execução) ───────────────────────────
var PF = M.portfolio, AREA = idx(PF.areas), OPP = idx(PF.opportunities), PROC = idx(PF.processes);
const hrs = v => v == null ? "—" : String(v).replace(".", ",") + " h/mês";
const iceTip = o => { const ax = (PF.ice_rubric || {}).axes;
  if (!ax || o.score == null) return esc(o.ice_reason || "");
  const lab = k => { const v = o[k], a = ax[k]; const lv = a && a.levels.find(l => l.n === v); return a.name + " " + v + ": " + (lv ? lv.label : ""); };
  return esc(["impact", "confidence", "ease"].map(lab).join("\n") + (o.ice_reason ? "\n" + o.ice_reason : "")); };
const iceTxt = o => o.score == null ? '<span class="muted">sem ICE</span>' : '<span class="' + (o.ice_suggested ? "sug" : "") + '" title="' + iceTip(o) + '">' +
  o.impact + "×" + o.confidence + "×" + o.ease + " = <b>" + o.score + "</b>" + (o.ice_suggested ? " · sugerido" : "") + "</span>";
const areaName = a => AREA[a] ? AREA[a].name : a;
function pathLink(ref) {
  if (!ref) return "";
  const u = docUrl(ref);
  if (u) return '<a href="' + esc(u) + '" target="_blank" rel="noopener">' + esc(ref) + "</a>";
  if (ref.indexOf("/") >= 0 && !/^[A-Za-z][A-Za-z0-9+.-]*:/.test(ref))
    return '<button type="button" class="btn tiny" data-read="' + esc(ref) + '">' + esc(ref) + "</button>";
  return esc(ref);
}
function oppRow(o, i){
  return "<tr><td>" + (i != null ? i + "</td><td>" : "") + "<b>" + esc(o.id) + "</b></td><td><details><summary>" + esc(o.title) + "</summary>" +
    "<p><b>Problema:</b> " + esc(o.problem || "não consta") + "</p><p><b>Sugestão:</b> " + esc(o.suggestion || "não consta") + "</p>" +
    (o.evidence_count ? '<p class="muted small">' + o.evidence_count + " evidência(s): " + o.evidence.map(pathLink).join(", ") + "</p>" : "") +
    (o.docs.length ? "<p>" + o.docs.map(d => chip("info", d.kind) + " " + docName(d)).join(" · ") + "</p>" : "") +
    (o.status_history.length ? '<p class="muted small">' + o.status_history.map(h => fmtD(h.date) + " " + esc(h.from) + "→" + esc(h.to) + (h.reason ? " (" + esc(h.reason) + ")" : "")).join(" · ") + "</p>" : "") +
    "</details></td><td>" + esc(areaName(o.area)) + "</td><td>" + iceTxt(o) + "</td><td>" + chip("info", o.status) + "</td><td>" + esc(o.quadrant || "—") +
    "</td><td>" + (o.deliverable ? "<b>" + esc(o.deliverable) + "</b> · " + pL(o.project, true)
      : o.project ? pL(o.project, true) + " · " + esc(o.goal)
      : o.promoted === "goal" ? esc(o.goal) + ' <span class="muted">(goal)</span>'
      : '<span class="muted">—</span>') + '</td><td class="num">' + hrs(o.hours_saved) + "</td></tr>";
}
// ── Fontes (watch.toml) — a aba Fontes do TUI ──
var S_SORT = "desc";
const qArg = s => {
  s = String(s ?? "");
  if (/^[\w@%+=:,./-]+$/.test(s)) return s;
  return "'" + s.replace(/'/g, "'\"'\"'") + "'";
};

V.sources = () => {
  const S = M.sources || [], when = x => x ? esc(x.slice(0, 16).replace("T", " ")) : '<span class="muted">nunca</span>';
  if (!S.length) {
    return '<div class="pagehead"><div><h1>Fontes</h1><p class="sub">O universo observável: fonte que não está no watch.toml não é puxada pelo /update nem pelo noturno.</p></div></div>' +
      panel("", empty("Nenhuma fonte no watch.toml — n adiciona."));
  }

  const kindMap = Object.fromEntries(M.source_kinds || []);
  const groupsMap = new Map();
  S.forEach(s => {
    const k = s.kind || "avulsas";
    if (!groupsMap.has(k)) {
      const label = kindMap[k] || (k === "avulsas" ? "avulsas" : k);
      groupsMap.set(k, {kind: k, label: label, rows: []});
    }
    groupsMap.get(k).rows.push(s);
  });

  const groups = Array.from(groupsMap.values());

  // Ordenação de grupos: grupos com pelo menos uma fonte com problem primeiro; resto alfabético por label
  groups.sort((a, b) => {
    const pA = a.rows.some(x => !!x.problem) ? 0 : 1;
    const pB = b.rows.some(x => !!x.problem) ? 0 : 1;
    if (pA !== pB) return pA - pB;
    return a.label.localeCompare(b.label, "pt-BR");
  });

  // Baldes por linha:
  // 1. problem === true sempre primeiro (em asc e desc)
  // 2. saudáveis habilitadas (enabled !== false && !problem)
  // 3. desligadas (enabled === false) por último
  const bucket = s => {
    if (s.problem) return 0;
    if (s.enabled === false) return 2;
    return 1;
  };

  groups.forEach(g => {
    g.rows.sort((a, b) => {
      const bA = bucket(a);
      const bB = bucket(b);
      if (bA !== bB) return bA - bB;
      const cmp = S_SORT === "asc"
        ? (a.last_ok || "").localeCompare(b.last_ok || "")
        : (b.last_ok || "").localeCompare(a.last_ok || "");
      if (cmp !== 0) return cmp;
      return (a.key || "").localeCompare(b.key || "");
    });
  });

  const sortArrow = S_SORT === "desc" ? "↓" : "↑";
  let tableHtml = '<div class="twrap"><table class="src-table"><thead><tr>' +
    '<th class="src-th-toggle"></th>' +
    '<th>Key</th><th>Tipo</th><th>Janela</th>' +
    '<th data-src-sort class="src-sort-hdr" title="Alternar ordenação">Último pull ' + sortArrow + '</th>' +
    '<th>Estado</th></tr></thead><tbody>';

  groups.forEach(g => {
    const probCount = g.rows.filter(x => !!x.problem).length;
    const badge = probCount ? ' ' + chip("atencao", "⚠ " + probCount + " com problema") : "";
    tableHtml += '<tr class="src-group-hdr"><td colspan="6"><div class="src-group-title">' +
      '<span class="src-group-name">▾ ' + esc(g.label) + '</span>' +
      ' <span class="src-group-count">(' + g.rows.length + ')</span>' +
      badge + '</div></td></tr>';

    g.rows.forEach(s => {
      const isProblem = !!s.problem;
      const isDisabled = s.enabled === false;
      let trAttrs = 'data-sel="src:' + esc(s.key) + '"';
      if (isProblem) trAttrs += ' class="src-problem"';
      else if (isDisabled) trAttrs += ' class="src-disabled muted"';

      const toggleCell = s.in_watch
        ? '<td class="src-td-toggle"><input type="checkbox" class="src-toggle" data-src-toggle="' + esc(s.key) + '" aria-label="Ligar/desligar fonte"' + (s.enabled !== false ? ' checked' : '') + '></td>'
        : '<td class="src-td-toggle"><span class="muted">—</span></td>';

      let stateHtml = "";
      if (isDisabled) {
        stateHtml = '<span class="chip h-muted">desligada</span>';
      } else if (isProblem) {
        stateHtml = '<span class="chip h-em-risco late">⚠ ' + esc(s.problem_reason || "problema") + '</span>' +
          (s.last_error ? ' <span class="late small">· ' + esc(s.last_error.slice(0, 80)) + '</span>' : '');
      } else if (!s.in_watch) {
        stateHtml = chip("atencao", "fora do watch") + ' <span class="muted small">w inclui</span>';
      } else {
        stateHtml = '<span class="ok">✓</span>';
      }

      tableHtml += '<tr ' + trAttrs + '>' +
        toggleCell +
        '<td><b>' + esc(s.key) + '</b></td>' +
        '<td>' + esc(s.kind || "—") + '</td>' +
        '<td>' + esc(s.window || "—") + '</td>' +
        '<td>' + when(s.last_ok) + '</td>' +
        '<td>' + stateHtml + '</td>' +
        '</tr>';
    });
  });

  tableHtml += '</tbody></table></div>';

  setTimeout(() => {
    document.querySelectorAll("#view [data-src-sort]").forEach(el => {
      el.onclick = e => {
        e.preventDefault();
        S_SORT = S_SORT === "desc" ? "asc" : "desc";
        route();
      };
    });
    document.querySelectorAll("#view [data-src-toggle]").forEach(el => {
      el.onclick = e => {
        e.stopPropagation();
        const key = el.dataset.srcToggle;
        const s = (M.sources || []).find(x => x.key === key);
        if (s) {
          runCommand('brain watch edit ' + qArg(s.key) + ' --set enabled=' + (s.enabled === false ? 'true' : 'false'));
        }
      };
    });
  });

  return '<div class="pagehead"><div><h1>Fontes</h1><p class="sub">O universo observável: fonte que não está no watch.toml não é puxada pelo /update nem pelo noturno.</p></div></div>' +
    panel("", tableHtml);
};
function docName(d) {
  const label = esc(d.title || d.ref || "");
  const u = docUrl(d.ref);
  if (u) return '<a href="' + esc(u) + '" target="_blank" rel="noopener">' + label + "</a>";
  if (d.ref && !/^[A-Za-z][A-Za-z0-9+.-]*:/.test(d.ref))
    return '<button type="button" class="btn tiny" data-read="' + esc(d.ref) + '">' + label + "</button>";
  return label;
}
V["pf/docs"] = () => {
  const rows = [];
  PF.processes.forEach(p => p.docs.forEach((d, n) => rows.push({t: p.id, title: p.title, d, n})));
  PF.opportunities.forEach(o => o.docs.forEach((d, n) => rows.push({t: o.id, title: o.title, d, n})));
  return '<div class="pagehead"><div><h1>Documentos</h1><p class="sub">Playbooks, one-pagers e planilhas ligados a processos e oportunidades.</p></div></div>' +
    panel("", rows.length ? '<div class="twrap"><table><tr><th>Ligado a</th><th>Tipo</th><th>Documento</th><th>Vigiado</th></tr>' +
      rows.map(r => '<tr data-sel="doc:' + esc(r.t) + ":" + r.n + '" data-url="' + esc(docUrl(r.d.ref)) + '"><td>' + idc(r.t) + " " + esc(r.title) + "</td><td>" + chip("info", r.d.kind) + "</td><td>" +
        docName(r.d) + "</td><td>" + (r.d.watch ? "sim" : "—") + "</td></tr>").join("") + "</table></div>"
      : empty("Nenhum documento ligado — L liga a um processo ou oportunidade."));
};
function safeUrl(u, allowMailto){
  if (typeof u !== "string") return "";
  const s = u.trim();
  if (!s) return "";
  if (/[\x00-\x1f\x7f\s]/.test(s)) return "";
  if (s.startsWith("//") || s.includes("\\")) return "";
  let parsed;
  try {
    parsed = new URL(s, "https://invalid.local");
  } catch (e) {
    return "";
  }
  const proto = parsed.protocol.toLowerCase();
  if (proto === "http:" || proto === "https:") {
    if (!/^https?:\/\/[^/?#]/i.test(s)) return "";
    if (!parsed.hostname) return "";
    return s;
  }
  if (allowMailto && proto === "mailto:") {
    if (!/^mailto:[^/?#]/i.test(s)) return "";
    return s;
  }
  return "";
}
function docUrl(ref){                                 // URL do doc: http direto (validado); id cru do Drive vira o link genérico; caminho do vault não tem URL
  const u = safeUrl(ref);
  if (u) return u;
  if (typeof ref === "string" && /^[A-Za-z0-9_-]{20,}$/.test(ref))
    return safeUrl("https://drive.google.com/file/d/" + ref + "/view");
  return "";
}

// ── face Portfólio: pf/visao · pf/opps (kanban) · pf/matrix · pf/procs · pf/areas ──
const STAGES_PIPE = ["ideia", "triagem", "priorizada", "em-andamento", "piloto", "validando", "entregue"];
const STAGES_LAT = ["em-espera", "descartada"];
const CHIP_LEVELS = new Set(["em-risco","travado","atencao","em-dia","concluido","congelado","depois","fechado","info","reason",
  ...STAGES_PIPE, ...STAGES_LAT, ...STAGES_PIPE.map(s => "s-" + s), ...STAGES_LAT.map(s => "s-" + s)]);
const enc = encodeURIComponent;
const oL = (id, long) => '<a href="#pf/opp/' + enc(id) + '">' + idc(id) + (long ? " " + esc(OPP[id].title) : "") + "</a>";
const stChip = s => chip("s-" + s, s);
function gapsList(){
  const g = PF.gaps, out = [];
  g.areas_without_process.forEach(a => out.push("área sem processo: " + esc(areaName(a))));
  g.processes.forEach(p => out.push(esc(p.id) + ': <span class="late">' + esc(p.gaps.join("; ")) + "</span>"));
  if (g.no_ice.length) out.push("sem ICE: " + g.no_ice.map(esc).join(", "));
  if (g.ice_suggested.length) out.push('ICE só sugerido (<span class="sug">a confirmar</span>): ' + g.ice_suggested.map(esc).join(", "));
  g.stale.forEach(s => out.push(esc(s.id) + " parada há " + s.days + " dias"));
  return out.length ? '<ul class="feed">' + out.map(x => "<li>" + x + "</li>").join("") + "</ul>" : empty("nenhuma lacuna");
}
V["pf/visao"] = () => {
  if (!PF.areas.length && !PF.processes.length && !PF.opportunities.length)
    return '<div class="pagehead"><div><h1>Portfólio</h1></div></div>' + empty("Nada cadastrado — `brain area add` e `brain process add` (ou deixe o /dump extrair).");
  const active = PF.processes.filter(p => p.status === "ativo");
  const mapped = active.reduce((t, p) => t + (p.hours_month || 0), 0);
  const gain = PF.opportunities.filter(o => o.status !== "descartada").reduce((t, o) => t + (o.hours_saved || 0), 0);
  let h = '<div class="pagehead"><div><h1>Portfólio</h1><p class="sub">Processos que existem e o que vale melhorar neles. ICE = impacto × confiança × facilidade (1–5) · <a href="#" data-icehelp>metodologia</a>.</p></div></div>' +
    '<div class="kpis"><div class="kpi"><span>oportunidades</span><b>' + PF.counts.opportunities + "</b></div>" +
    '<div class="kpi"><span>priorizadas</span><b>' + PF.counts.prioritized + "</b></div>" +
    '<div class="kpi"><span>processos ativos</span><b>' + PF.counts.processes + "</b></div>" +
    '<div class="kpi"><span>h/mês mapeados</span><b>' + hrs(mapped).replace(" h/mês", "") + "</b></div>" +
    '<div class="kpi ok"><span>h/mês de ganho declarado</span><b>' + hrs(gain).replace(" h/mês", "") + "</b></div>" +
    '<div class="kpi ' + (PF.gaps.total ? "risk" : "ok") + '"><span>lacunas</span><b>' + PF.gaps.total + "</b></div></div>";
  h += panel("Funil", '<div class="funnelchips">' + Object.entries(PF.funnel).filter(([, n]) => n).map(([s, n]) =>
    '<a href="#pf/opps">' + stChip(s) + " <b>" + n + "</b></a>").join(" ") + "</div>", ' style="margin-top:14px"');
  h += panel("Por área", '<div class="grid g3">' + PF.areas.map(a => {
    const procs = active.filter(p => p.area === a.id), opps = PF.opportunities.filter(o => o.area === a.id);
    return '<a class="card area-card" href="#pf/area/' + encodeURIComponent(a.id) + '"><div class="card-title">' + esc(a.name) + "</div>" +
      '<p class="card-meta">' + procs.length + " processos · " + hrs(procs.reduce((t, p) => t + (p.hours_month || 0), 0)) + " · " + opps.length + " oportunidades</p>" +
      '<p class="card-meta">' + STAGES_PIPE.filter(s => opps.some(o => o.status === s)).map(s => stChip(s) + " " + opps.filter(o => o.status === s).length).join(" ") + "</p></a>";
  }).join("") + "</div>", ' style="margin-top:14px"');
  const goals = Object.entries(PF.by_goal || {});
  if (goals.length) {
    const items = goals.slice().sort((x, y) => (x[0] ? 0 : 1) - (y[0] ? 0 : 1) || x[0].localeCompare(y[0]))
      .map(([g, ids]) => {
        if (!g) return '<li><span class="muted">sem goal ainda: ' + ids.length + " — ganham goal ao serem promovidas a projeto</span></li>";
        return "<li><b>" + esc(g) + "</b> " + esc(G[g] ? G[g].title : "") + " — " + ids.map(i => oL(i)).join(", ") + "</li>";
      }).join("");
    h += panel("Por goal", '<ul class="feed">' + items + "</ul>", ' style="margin-top:14px"');
  }
  h += panel("Lacunas", gapsList(), ' style="margin-top:14px"');
  return h;
};
V["pf/opps"] = (q) => {
  const fa = q.get("area") || "";
  const rows = PF.opportunities.filter(o => !fa || o.area === fa);
  let h = '<div class="pagehead"><div><h1>Oportunidades</h1><p class="sub">Arraste o cartão para mudar o estágio — é o comando <code>brain opportunity status</code> (laterais pedem motivo).</p></div></div>' +
    '<div class="filters">' + dd("ofa", PF.areas.map(a => [a.id, a.name]), fa, "todas as áreas") + "</div>";
  const cardOf = o => '<article class="card pf-card' + (o.ice_suggested ? " is-sug" : "") + '" draggable="true" data-opp="' + esc(o.id) + '">' +
    '<header><span class="ids">' + oL(o.id) + "</span>" + (o.priority ? " " + chip("em-risco", o.priority) : "") + "</header>" +
    '<h3 class="card-title">' + esc(o.title) + "</h3>" +
    '<p class="card-meta">' + iceTxt(o) + " · " + esc(areaName(o.area)) + (o.quadrant ? " · " + esc(o.quadrant) : "") + (o.hours_saved ? " · " + hrs(o.hours_saved) : "") + "</p></article>";
  const colOf = s => { const l = rows.filter(o => o.status === s);
    return '<div class="col pf-col' + (STAGES_LAT.includes(s) ? " lat" : "") + '" data-stage="' + s + '"><h2>' + s + ' <span class="count">' + l.length + "</span></h2>" +
      (l.map(cardOf).join("") || empty("—")) + "</div>"; };
  h += '<div class="pf-kanban">' + STAGES_PIPE.map(colOf).join("") + "</div>";
  h += '<div class="pf-kanban lat-row">' + STAGES_LAT.map(colOf).join("") + "</div>";
  setTimeout(() => {
    const ba = document.querySelector('[data-dd="ofa"] .dd-btn');
    if (ba) ba.addEventListener("ddchange", e => go("pf/opps", {area: e.detail.value}));
  });
  return h;
};
V["pf/matrix"] = () => {
  const QUADS = [["ganho rápido", "impacto alto · facilidade alta"], ["aposta", "impacto alto · facilidade baixa"],
    ["preencher depois", "impacto baixo · facilidade alta"], ["evitar", "impacto baixo · facilidade baixa"]];
  return '<div class="pagehead"><div><h1>Matriz impacto × facilidade</h1><p class="sub">Notas ≥ 3 contam como altas. Fora da matriz: sem ICE.</p></div></div>' +
    panel("", '<div class="grid mx">' + QUADS.map(([qn, d]) => '<div class="col"><h2>' + qn + ' <span class="muted">· ' + d + "</span></h2>" +
      ((PF.matrix[qn] || []).map(i => OPP[i]).filter(Boolean).sort((a, b) => (b.score ?? -1) - (a.score ?? -1)).map(o =>
        '<a class="card mini" href="#pf/opp/' + encodeURIComponent(o.id) + '"><span class="ids">' + esc(o.id) + '</span><div class="card-title">' + esc(o.title) + '</div><p class="card-meta">' +
        iceTxt(o) + " · " + esc(o.status) + " · " + esc(areaName(o.area)) + "</p></a>").join("") || empty("—")) + "</div>").join("") + "</div>");
};
V["pf/procs"] = (q) => {
  const fa = (q && q.get("area")) || "";
  let h = '<div class="pagehead"><div><h1>Processos</h1><p class="sub">Horas/mês = execuções × duração × executores (cálculo do CLI).</p></div></div>' +
    '<div class="filters">' + dd("pfa", PF.areas.map(a => [a.id, a.name]), fa, "todas as áreas") + "</div>";
  setTimeout(() => { const b = document.querySelector('[data-dd="pfa"] .dd-btn'); if (b) b.addEventListener("ddchange", e => go("pf/procs", {area: e.detail.value})); });
  const areas = fa ? PF.areas.filter(a => a.id === fa) : PF.areas;
  return h + areas.map(a => {
    const rows = PF.processes.filter(p => p.area === a.id);
    return rows.length ? panel(esc(a.name) + ' <span class="muted">· ' + rows.length + " · " + hrs(rows.filter(p => p.status === "ativo").reduce((t, p) => t + (p.hours_month || 0), 0)) + "</span>",
      '<div class="twrap"><table><tr><th>ID</th><th>Processo</th><th>Responsável</th><th>Recorrência</th><th>Horas/mês</th><th>Oport.</th><th>Lacunas</th></tr>' +
      rows.map(p => "<tr><td><a href=\"#pf/proc/" + enc(p.id) + "\">" + idc(p.id) + "</a></td><td>" + esc(p.title) + (p.status !== "ativo" ? " " + chip("s-descartada", "aposentado") : "") + "</td><td>" + (p.owner ? peL(p.owner) : "—") +
        "</td><td>" + esc(p.recurrence || "—") + '</td><td class="num">' + hrs(p.hours_month) + '</td><td class="num">' + p.opportunities.length + "</td><td>" +
        (p.gaps.length ? '<span class="late">⚠ ' + p.gaps.map(esc).join("; ") + "</span>" : '<span class="ok">✓</span>') + "</td></tr>").join("") + "</table></div>",
      ' style="margin-top:14px"') : "";
  }).join("") || empty("nenhum processo");
};
V["pf/proc"] = (q, id) => {
  const p = PROC[id]; if (!p) return empty("Processo não encontrado");
  let h = '<p class="crumb muted"><a href="#pf/procs">← processos</a></p><div class="pagehead"><div><h1>' + esc(p.id) + " · " + esc(p.title) + "</h1>" +
    '<div class="sub">' + chip("", p.status || "") + "<span>" + esc(areaName(p.area)) + "</span>" +
    (p.owner ? "<span>responsável: " + peL(p.owner) + "</span>" : "") +
    "<span>" + hrs(p.hours_month) + "</span></div></div></div>";
  h += filesBlock(p.files);
  if (p.docs && p.docs.length) h += panel("Documentos", '<ul class="feed">' + p.docs.map(d => "<li>" + chip("info", d.kind) + " " + docName(d) + "</li>").join("") + "</ul>", ' style="margin-top:14px"');
  return h;
};
V["pf/areas"] = () => '<div class="pagehead"><div><h1>Áreas</h1></div></div>' + panel("", '<div class="twrap"><table><tr><th>Área</th><th>Também chamada</th><th>Processos</th><th>Horas/mês</th><th>Oportunidades</th><th>Priorizadas</th></tr>' +
  PF.areas.map(a => { const procs = PF.processes.filter(p => p.area === a.id && p.status === "ativo"), opps = PF.opportunities.filter(o => o.area === a.id);
    return '<tr><td><b><a href="#pf/area/' + enc(a.id) + '">' + esc(a.name) + "</a></b></td>" + '<td class="muted">' + a.aliases.map(esc).join(", ") + '</td><td class="num">' + procs.length + '</td><td class="num">' +
      hrs(procs.reduce((t, p) => t + (p.hours_month || 0), 0)) + '</td><td class="num">' + opps.length + '</td><td class="num">' + opps.filter(o => o.status === "priorizada").length + "</td></tr>"; }).join("") + "</table></div>");

V["pf/area"] = (q, id) => {
  const a = AREA[decodeURIComponent(id || "")]; if (!a) return empty("Área não encontrada");
  const procs = PF.processes.filter(x => x.area === a.id);
  const active = procs.filter(x => x.status === "ativo");
  const opps = PF.opportunities.filter(o => o.area === a.id).sort((x, y) => (y.score || 0) - (x.score || 0) || x.id.localeCompare(y.id));
  const ppl = [...new Set([...active.flatMap(x => [x.owner, ...(x.executors || [])]), ...opps.flatMap(o => o.people || [])])].filter(Boolean);
  let h = '<p class="crumb muted"><a href="#pf/areas">← áreas</a></p>' +
    '<div class="pagehead"><div><h1>' + esc(a.name) + "</h1>" +
    '<div class="sub">' + (a.aliases.length ? "<span>também: " + a.aliases.map(esc).join(", ") + "</span>" : "") +
    "<span>" + active.length + " " + (active.length === 1 ? "processo ativo" : "processos ativos") + "</span><span>" + hrs(active.reduce((t, x) => t + (x.hours_month || 0), 0)) + "</span>" +
    "<span>" + opps.length + " " + (opps.length === 1 ? "oportunidade" : "oportunidades") + "</span>" + (a.note ? "<span>" + esc(a.note) + "</span>" : "") + "</div></div></div>";
  h += '<div class="grid g2">' +
    panel("Processos · " + procs.length, '<div class="twrap"><table><tr><th>ID</th><th>Processo</th><th>Responsável</th><th>Recorrência</th><th>Horas/mês</th><th>Lacunas</th></tr>' +
      (procs.length ? procs.map(x => "<tr><td><a href=\"#pf/proc/" + enc(x.id) + "\">" + idc(x.id) + "</a></td><td>" + esc(x.title) + (x.status !== "ativo" ? " " + chip("s-descartada", "aposentado") : "") + "</td><td>" +
        (x.owner ? peL(x.owner) : "—") + "</td><td>" + esc(x.recurrence || "—") + '</td><td class="num">' + hrs(x.hours_month) + "</td><td>" +
        (x.gaps.length ? '<span class="late">⚠ ' + x.gaps.map(esc).join("; ") + "</span>" : '<span class="ok">✓</span>') + "</td></tr>").join("")
      : "<tr><td colspan=6>" + empty("—") + "</td></tr>") + '</table></div><p class="more"><a href="#pf/procs?area=' + enc(a.id) + '">lista de processos filtrada →</a></p>') +
    panel("Oportunidades · " + opps.length, '<div class="twrap"><table><tr><th>ID</th><th>Oportunidade</th><th>ICE</th><th>Status</th><th>Ganho</th></tr>' +
      (opps.length ? opps.map(o => "<tr><td>" + oL(o.id) + "</td><td>" + esc(o.title) + '</td><td class="td-ice">' + iceTxt(o) + "</td><td>" + stChip(o.status) +
        '</td><td class="num">' + hrs(o.hours_saved) + "</td></tr>").join("")
      : "<tr><td colspan=5>" + empty("—") + "</td></tr>") + "</table></div>") + "</div>";
  h += panel("Pessoas · " + ppl.length, ppl.length ? ppl.map(x => peL(x) + ' <span class="muted small">' + esc((PE[x] || {}).role || "") + "</span>").join(" · ")
    : empty("ninguém ligado a esta área ainda"), ' style="margin-top:14px"');
  return h;
};
V["pf/opp"] = (q, id) => {
  const o = OPP[id]; if (!o) return empty("Oportunidade não encontrada");
  const proc = PROC[o.process];
  let h = '<p class="crumb muted"><a href="#pf/opps">← oportunidades</a></p><div class="pagehead"><div><h1>' + esc(o.id) + " · " + esc(o.title) + "</h1>" +
    '<div class="sub">' + stChip(o.status) + chip("", o.kind_label || o.kind) + "<span>" + esc(areaName(o.area)) + "</span>" + (o.quadrant ? chip("", o.quadrant) : "") +
    "<span>ICE " + iceTxt(o) + "</span></div></div></div>";
  h += '<div class="grid g2">' + panel("Resumo", '<ul class="feed"><li><b>Ganho esperado:</b> ' + esc(o.gain || "não consta") + (o.hours_saved ? " · " + hrs(o.hours_saved) : "") + "</li>" +
    (o.score != null ? ["impact", "confidence", "ease"].map(k => {       // leitura do ICE: rótulo de cada eixo (rubric)
        const ax = ((PF.ice_rubric || {}).axes || {})[k], lv = ax && ax.levels.find(l => l.n === o[k]);
        return "<li><b>" + esc(ax ? ax.name : k) + " " + o[k] + ":</b> " + esc(lv ? lv.label : "") + "</li>"; }).join("") : "") +
    "<li><b>Processo:</b> " + (o.process ? idc(o.process) + " " + esc(proc ? proc.title : "") : "—") + "</li>" +
    "<li><b>Goal:</b> " + (o.goal ? esc(o.goal) + " " + esc(o.goal_title || "") : "—") + "</li>" +
    "<li><b>Projeto:</b> " + (o.project ? pL(o.project, true) : "—") + "</li>" +
    (o.deliverable ? "<li><b>Entregável:</b> " + esc(o.deliverable) + " " + esc(o.deliverable_title || "") + "</li>" : "") +
    '<li><b>Registrada:</b> ' + fmtD(o.added) + " · por " + esc(o.by === "owner" ? "dono" : "agente") + " [" + esc(o.prov) + "]</li></ul>");
  h += panel("Problema → Sugestão", '<div class="msg">' + esc(o.problem || "não consta") + '</div><div class="msg">' + esc(o.suggestion || "não consta") + "</div>") + "</div>";
  if (o.docs.length) h += panel("Documentos", '<ul class="feed">' + o.docs.map(d => "<li>" + chip("info", d.kind) + " " + esc(d.title || d.ref) + "</li>").join("") + "</ul>", ' style="margin-top:14px"');
  h += filesBlock(o.files);
  h += panel("Histórico de status", o.status_history.length ? '<ul class="feed">' + o.status_history.map(x => "<li><span class=\"muted\">" + fmtD(x.date) + "</span> · " + stChip(x.from) + " → " + stChip(x.to) +
    (x.reason ? ' <span class="muted">(' + esc(x.reason) + ")</span>" : "") + "</li>").join("") + "</ul>" : empty("criada em " + fmtD(o.added) + " como " + o.status), ' style="margin-top:14px"');
  return h;
};
V.portfolio = () => { location.hash = "#pf/visao"; return ""; };   // compat: link antigo


// ── perguntas do agente (ASK-####) e propostas (PROP-####) ──────────────
V.ask = (q) => {
  const all = !!(q && q.get("a") === "1");                      // T: só abertas (padrão, como o TUI) ↔ todas
  const qs = M.questions || [], abertas = qs.filter(q => q.status === "aberta"), feitas = qs.filter(q => q.status !== "aberta");
  let h = '<div class="pagehead"><div><h1>Perguntas e propostas</h1><p class="sub">O agente pergunta (ASK-####) — só o dono responde. Propostas PROP-#### o dono aceita/rejeita com a resposta literal.</p></div></div>';
  h += panel("Perguntas abertas · " + abertas.length, abertas.length ? abertas.map(q =>
    '<div class="card" data-ask="' + esc(q.id) + '" style="margin:0 0 10px">' +
    '<header><span class="ids">' + idc(q.id) + "</span>" + chip("info", q.kind) +
    (q.run ? ' <span class="muted small">rodada ' + esc(q.run) + "</span>" : "") + "</header>" +
    '<h3 class="card-title">' + esc(q.text) + "</h3>" +
    (q.options && q.options.length ? '<div class="ask-opts">' + q.options.map(o => '<button class="btn" data-opt="' + esc(o) + '">' + esc(o) + "</button>").join("") + "</div>" : "") +
    '<div class="ask-free"><input class="rin" data-free placeholder="ou responda com texto livre…"><button class="btn" data-send>responder</button>' +
    '<button class="btn ghost" data-drop title="brain ask drop --reason">descartar</button></div>' +
    (q.context ? '<p class="muted small">contexto: ' + (Array.isArray(q.context) ? q.context.map(pathLink).join(", ") : pathLink(String(q.context))) + "</p>" : "") +
    filesBlock(q.files) +
    "</div>").join("") : empty("nenhuma pergunta aberta"));
  h += panel("Propostas abertas · " + M.proposals.length, M.proposals.length ? M.proposals.map(pr =>
    '<div class="card" style="margin:0 0 10px"><header><span class="ids">' + idc(pr.id) + "</span>" + chip("atencao", pr.kind) + "</header>" +
    '<h3 class="card-title">' + esc(pr.summary) + "</h3>" +
    '<p class="muted small">' + (pr.target ? "alvo " + esc(pr.target) + " · " : "") + (pr.into ? "em " + esc(pr.into) + " · " : "") +
    "evidência: " + (pr.evidence ? pathLink(pr.evidence) : "—") + "</p>" +
    '<div class="ask-opts"><button class="btn primary" data-acc>aceitar (gate)</button><button class="btn" data-rej>rejeitar</button></div></div>').join("")
    : empty("nenhuma proposta aberta"), ' style="margin-top:14px"');
  const pubs = (M.publishes || []).filter(x => all || x.status !== "publicada");
  if (pubs.length) h += panel("Publicar (porta 3) · " + pubs.filter(x => x.status !== "publicada").length + " aguardando",
    pubs.map(x => {
      const pubUrl = safeUrl(x.link);
      return '<div class="card" style="margin:0 0 10px"><header><span class="ids">' + idc(x.id) + "</span>" +
        chip(x.status === "solicitada" ? "atencao" : x.status === "publicada" ? "em-dia" : "info", x.status) +
        ' <span class="muted small">→ ' + esc(x.to) + "</span></header>" +
        '<h3 class="card-title">' + esc(x.title) + "</h3>" +
        (x.link ? '<p class="muted small">' + esc(x.link) + "</p>" : "") +
        filesBlock(x.files) +
        '<div class="ask-opts">' +
        (x.status === "solicitada" ? '<button class="btn primary" data-pub="approve:' + esc(x.id) + '">aprovar (gate)</button><button class="btn" data-pub="cancel:' + esc(x.id) + '">cancelar</button>' : "") +
        (x.status === "aprovada" ? '<button class="btn primary" data-pub="done:' + esc(x.id) + '">publicar (agente)</button><button class="btn" data-pub="cancel:' + esc(x.id) + '">cancelar</button>' : "") +
        (x.status === "publicada" && pubUrl ? '<a class="btn" href="' + esc(pubUrl) + '" target="_blank" rel="noopener">abrir ↗</a>' : "") +
        "</div></div>";
    }).join("") + '<p class="muted small">pedir nova: tecla n · o export sai de brain share; o agente posta na porta 3</p>', ' style="margin-top:14px"');
  if (all && feitas.length) h += panel("Respondidas", '<ul class="feed">' + feitas.map(q =>
    "<li>" + idc(q.id) + ' <span class="muted">' + esc(q.text.slice(0, 90)) + "…</span> → <b>" + esc(q.answer || "") + "</b></li>").join("") + "</ul>", ' style="margin-top:14px"');
  return h;
};

// ── router + faces (mesma lógica da TUI: Execução | Portfólio, cada face lembra onde estava) ──
const TABS_EXEC = [["home", "Início"], ["sources", "Fontes", () => (M.sources || []).filter(s => s.failures).length || 0], ["todo", "TODO", () => M.counts.mine_overdue], ["projects", "Projetos"], ["decisions", "Decisões"], ["ask", "Perguntas", () => ((M.questions || []).filter(q => q.status === "aberta").length + M.proposals.length) || 0], ["wins", "Conquistas"],
  ["timeline", "Linha do tempo"], ["focus", "Foco", () => M.focus && M.focus.status === "proposto" ? 1 : 0],
  ["outbox", "Mensagens", () => M.counts.outbox_pending], ["feedback", "Sugestões", () => (M.feedback || []).filter(f => f.status !== "criado" && f.status !== "retirado" && f.status !== "retratado").length || 0]];
  // (Saúde saiu daqui com a face Configurações — mesma decisão da TUI: mora só lá, com o badge de avisos)
const TABS_PF = [["pf/visao", "Visão geral"], ["pf/opps", "Oportunidades", () => PF.opportunities.filter(o => o.status !== "descartada").length],
  ["pf/matrix", "Matriz"], ["pf/procs", "Processos", () => PF.processes.filter(p => p.status === "ativo").length], ["pf/areas", "Áreas", () => PF.areas.length],
  ["pf/docs", "Documentos", () => PF.processes.concat(PF.opportunities).reduce((n, x) => n + x.docs.length, 0)],
  ["people", "Pessoas"]];
const TABS_CFG = [["cfg/inicio", "Visão geral"], ["cfg/perfil", "Perfil"], ["cfg/rotina", "Rotina"], ["cfg/agente", "Seu agente"], ["cfg/conectores", "Conectores"],
  ["cfg/memoria", "Memória"], ["cfg/integracoes", "Integrações"],
  ["cfg/saude", "Saúde", () => (M.health || []).filter(c => c.level !== "ok").length]];   // o único contador da face: passo pulado não vira pendência
const FACES = [["execucao", "Execução", TABS_EXEC], ["portfolio", "Portfólio", TABS_PF], ["configuracoes", "Configurações", TABS_CFG]];
if (window.PF_ONLY) { FACES.length = 0; FACES.push(["portfolio", "Portfólio", TABS_PF]); }
const faceOf = v => (v.indexOf("pf/") === 0 || v === "people" || v === "person") ? "portfolio" : (v.indexOf("cfg/") === 0 ? "configuracoes" : "execucao");
const PARENT = {project: "projects", person: "people", action: "todo", decision: "decisions", "pf/opp": "pf/opps", "pf/proc": "pf/procs", "pf/area": "pf/areas"};
function go(view, params){ const q = new URLSearchParams(Object.entries(params || {}).filter(([, v]) => v)).toString(); location.hash = view + (q ? "?" + q : ""); }
function route(){
  if (IS_SHELL && !HYDRATED) {
    if (window.BRAIN_AUTH && !window.BRAIN_AUTH.isLive()) window.BRAIN_AUTH.showAuthRequired();
    return;
  }
  const raw = location.hash.slice(1) || "home", parts = raw.split("?"), path = parts[0], qs = parts[1] || "";
  let seg = path.split("/");
  if (seg[0] === "face") {                       // trocar de face: volta pra onde a face estava
    const f = FACES.some(x => x[0] === seg[1]) ? seg[1] : "execucao";
    const last = localStorage.getItem("mock-face-" + f);
    const entry = FACES.find(x => x[0] === f) || FACES[0];
    location.hash = last || entry[2][0][0];      // default = primeira aba da própria face (carrossel: toda face é alcançável)
    return;
  }
  if (path === "onboarding") {                   // F8: o wizard é um modo do painel, não uma página
    if (!(document.body && document.body.classList.contains("obmode")) && typeof window.enterOnboarding === "function") window.enterOnboarding();
    return;
  }
  if ((path === "home" || path === "") && M.onboarding && M.onboarding.needed && !window.__obDone
      && typeof window.enterOnboarding === "function" && !(document.body && document.body.classList.contains("obmode"))) {
    location.hash = "onboarding";                // primeira vez: o painel abre na configuração sozinho
    return;
  }
  if (seg[0] === "portfolio") seg = ["pf", "visao"];          // link antigo
  if (seg[0] === "health") seg = ["cfg", "saude"];            // Saúde mora só na Configurações (link antigo)
  const pf = seg[0] === "pf";
  let view = pf ? "pf/" + (seg[1] || "visao") : (seg[0] === "cfg" ? "cfg/" + (seg[1] || "inicio") : seg[0]);
  const arg = pf ? seg.slice(2).join("/") : (seg[0] === "cfg" ? seg.slice(2).join("/") : seg.slice(1).join("/"));
  const q = new URLSearchParams(qs);
  if (!V[view]) view = "home";
  if (window.PF_ONLY && faceOf(view) === "execucao") { location.hash = "#pf/visao"; return; }
  localStorage.setItem("mock-face-" + faceOf(view), raw);
  if (typeof window.renderTabs === "function")
    window.renderTabs(view, (FACES.find(f => f[0] === faceOf(view)) || FACES[0])[2], PARENT);
  if (typeof window.renderFaces === "function") window.renderFaces(faceOf(view), FACES);
  $("#view").innerHTML = V[view](q, arg && decodeURIComponent(arg));
  if (typeof window.afterRoute === "function") window.afterRoute(view, q, arg);
  window.scrollTo(0, 0);
}
window.BRAIN = {M, A, D, P, G, PE, OPP, PROC, AREA, docUrl, safeUrl, normalizeBrain, go, route, chip, aL, dL, pL, peL, fmtD, fmtDW, donut, bar, esc,
  qArg, V, get S_SORT(){ return S_SORT; }, set S_SORT(v){ S_SORT = v; },
  refresh: function(nm){                       // ponte CLI (./brain serve): novo view model → índices + views (troca atômica)
    let nextM, nA, nD, nP, nG, nPE, nART, nDL, nDD, nPF, nAREA, nOPP, nPROC;
    try {
      if (!nm || typeof nm !== "object" || Array.isArray(nm)) throw new Error("view model inválido");
      nextM = normalizeBrain(Object.assign({}, nm));
      nA = idx(nextM.actions); nD = idx(nextM.decisions); nP = idx(nextM.projects); nG = idx(nextM.goals);
      nPE = idx(nextM.people); nART = idx(nextM.artifacts); nDL = idx(nextM.deliveries); nDD = idx(nextM.deliverables_done);
      nPF = nextM.portfolio; nAREA = idx(nPF.areas); nOPP = idx(nPF.opportunities); nPROC = idx(nPF.processes);
    } catch (err) {
      const msg = "Falha ao atualizar dados do painel — mantendo estado anterior.";
      const t = document.getElementById("toast");
      if (t) { t.textContent = msg; t.classList.add("show"); }
      const view = document.getElementById("view");
      if (view && !document.getElementById("refresh-err-banner")) {
        const b = document.createElement("div");
        b.id = "refresh-err-banner";
        b.className = "fresh-banner";
        b.setAttribute("role", "alert");
        b.innerHTML = '<div class="fresh-banner-text"><strong>⚠ ' + esc(msg) + "</strong></div>";
        if (typeof view.prepend === "function") view.prepend(b);
        else if (typeof view.insertBefore === "function") view.insertBefore(b, view.firstChild || null);
      }
      return false;
    }
    for (const k of Object.keys(M)) delete M[k];
    Object.assign(M, nextM);
    HYDRATED = true;
    A = nA; D = nD; P = nP; G = nG; PE = nPE; ART = nART; DL = nDL; DD = nDD;
    PF = nPF; AREA = nAREA; OPP = nOPP; PROC = nPROC;
    BRAIN.A = A; BRAIN.D = D; BRAIN.P = P; BRAIN.G = G; BRAIN.PE = PE;   // re-exporta: quem lê
    BRAIN.OPP = OPP; BRAIN.PROC = PROC; BRAIN.AREA = AREA;              // window.BRAIN não pode ficar congelado no boot
    const ownName = (M.owner && M.owner.name) || "—";
    const onEl = document.getElementById("ownername"); if (onEl) onEl.textContent = ownName;
    const avEl = document.getElementById("avatar"); if (avEl) avEl.textContent = ownName.trim().slice(0, 1).toUpperCase() || "B";
    syncVerBadge();
    syncFreshBadge();
    route();
    return true;
  }};

// tema (claro/escuro manual + automático)
const themeBtn = $("#theme");
function applyTheme(t){ document.documentElement.dataset.theme = t; if (themeBtn) { themeBtn.textContent = "☀"; themeBtn.title = t === "dark" ? "tema escuro — clique p/ claro" : "tema claro — clique p/ escuro"; themeBtn.classList.toggle("is-dark", t === "dark"); } }
let theme = localStorage.getItem("mock-theme") ||
  (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
applyTheme(theme);
if (themeBtn) themeBtn.onclick = () => { theme = theme === "dark" ? "light" : "dark"; localStorage.setItem("mock-theme", theme); applyTheme(theme); };

// busca
const qi = $("#q");
if (qi) {
  let tmr;
  qi.addEventListener("input", e => { clearTimeout(tmr); const v = e.target.value.trim(); tmr = setTimeout(() => v.length > 1 ? go("search", {q: v}) : go("home"), 250); });
  document.addEventListener("keydown", e => {
    if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); qi.focus(); }
    if (e.key === "Escape" && document.activeElement === qi) { qi.value = ""; go("home"); qi.blur(); }
  });
}
window.addEventListener("hashchange", route);
if (IS_SHELL) {
  if (window.BRAIN_AUTH && window.BRAIN_AUTH.isLive()) {
    $("#view").innerHTML = '<div class="pagehead"><div><h1>Carregando…</h1><p class="sub">conectando à ponte local…</p></div></div>';
    window.BRAIN_AUTH.hydrate();
  } else if (window.BRAIN_AUTH) {
    window.BRAIN_AUTH.showAuthRequired();
  } else {
    $("#view").innerHTML = '<section class="panel" data-auth-required="1"><h2>Sessão não autenticada</h2><p>Reabra via <code>./brain render --open</code> ou pelo app <b>Brain</b>.</p></section>';
  }
} else {
  route();
}


// ── versão + atualização (rodapé da barra lateral; dados vêm do cache do render) ──
// (dentro do MESMO IIFE do core: o M e o $ daqui não existem fora dele)
function syncVerBadge(){
  const u = M.update || {};
  const b = document.getElementById("verbadge");
  if (!b) return;
  const back = document.getElementById("newsback");
  const behind = (u.behind || 0) > 0;
  const commitsTxt = u.behind + (u.behind === 1 ? " commit atrás" : " commits atrás");
  const verTxt = "v" + (u.version || "?");
  const transTxt = verTxt + " → v" + (u.remote_version || "?");
  if (back) {
    back.dataset.behind = String(u.behind || 0);
    back.dataset.ahead = String(u.ahead || 0);
    back.dataset.version = u.version || "";
    back.dataset.remoteVersion = u.remote_version || "";
    back.dataset.cliCmd = u.cli_cmd || "";
  }
  b.textContent = behind
    ? transTxt + " · " + commitsTxt
    : (u.checked ? verTxt + (u.stale ? " · sem verificar" : " · em dia") : verTxt);
  b.classList.toggle("behind", behind);
  b.title = behind ? "atualização disponível (" + commitsTxt + ") — comando `update`"
                   : "Segundo Cérebro " + verTxt + (u.checked ? (u.stale ? " — verificação desatualizada" + (u.checked_at ? " (" + fmtDL(u.checked_at) + ")" : "") : " — em dia") : "");
}
(function(){
  const b = document.getElementById("verbadge");
  if (!b) return;
  const back = document.getElementById("newsback");
  const meta = document.getElementById("newsmeta");
  const act = document.getElementById("newsact");
  const log = document.getElementById("newslog");
  const fb = document.getElementById("newsfb");
  const semNovidade = u => u.checked
    ? (u.stale
        ? ["Não conseguimos confirmar se há atualização: a última verificação está velha" + (u.error ? " ou falhou" : "") + ". Rode `update --check`."]
        : ["Tudo em dia por aqui. A lista completa mora no CHANGELOG.md do repositório."])
    : ["Ainda não verificamos se há atualizações — o noturno ou o comando `update --check` fazem isso."];
  const openNews = () => {
    const u = M.update || {};
    const behind = (u.behind || 0) > 0;
    const commitsTxt = u.behind + (u.behind === 1 ? " commit atrás" : " commits atrás");
    const verTxt = "v" + (u.version || "?");
    const transTxt = verTxt + " → v" + (u.remote_version || "?");
    const news = (u.news && u.news.length) ? u.news : semNovidade(u);
    document.getElementById("newslist").innerHTML =
      news.map(n => '<div class="ni">' + esc(n) + "</div>").join("");
    document.getElementById("newstitle").textContent = behind ? "Atualização disponível" : "Novidades da versão";
    if (meta) {
      meta.textContent = behind
        ? transTxt + " · " + commitsTxt + (u.checked_at ? " · verificado " + fmtDL(u.checked_at) : "")
        : verTxt + (u.checked ? (u.stale ? " · sem verificar" : " · em dia") : "") + (u.checked_at ? " · verificado " + fmtDL(u.checked_at) : "");
    }
    document.getElementById("newshow").textContent = behind
      ? "No terminal, use o comando `update`."
      : (u.stale ? "Verificação desatualizada." : "Instalação em dia.") + (u.checked_at ? " · verificado " + fmtDL(u.checked_at) : "");
    if (act) act.hidden = !behind;
    if (log && !log.textContent) log.hidden = true;
    if (fb) fb.textContent = "";
    if (back) {
      back.hidden = false;
      back.classList.add("open");
    }
  };
  const closeNews = () => {
    if (!back) return;
    back.classList.remove("open");
    back.hidden = true;
  };
  if (!IS_SHELL) syncVerBadge();
  b.addEventListener("click", openNews);
  const closeBtn = document.getElementById("newsclose");
  if (closeBtn) closeBtn.addEventListener("click", closeNews);
  if (back) back.addEventListener("click", e => { if (e.target === back) closeNews(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && back && back.classList.contains("open")) closeNews(); });
})();

(function(){
  const b = document.getElementById("freshbadge");
  if (!b) return;
  if (!IS_SHELL) syncFreshBadge();
  b.addEventListener("click", () => go("cfg/saude"));
})();
})();
