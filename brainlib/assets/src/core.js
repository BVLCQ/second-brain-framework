/* núcleo compartilhado das 3 variantes — mesmas views, dados reais do demo.
   Diferenças visuais ficam no CSS de cada variante; extras ficam em scripts por variante. */
(function(){
"use strict";
// normalização: o portfolio.html injeta só o recorte do portfólio — e instâncias antigas podem
// não ter todas as chaves. Nenhuma leitura do painel pode ver undefined (boot OU refresh do serve).
function normalizeBrain(m){
  m.counts = m.counts || {}; m.questions = m.questions || []; m.proposals = m.proposals || [];
  m.outbox = m.outbox || []; m.health = m.health || []; m.deliveries = m.deliveries || [];
  m.actions = m.actions || []; m.publishes = m.publishes || []; m.focus = m.focus || null;
  m.deliverables_done = m.deliverables_done || [];
  m.timeline = m.timeline || {past: [], ahead: []}; m.people = m.people || [];
  m.goals = m.goals || []; m.projects = m.projects || []; m.decisions = m.decisions || [];
  m.artifacts = m.artifacts || []; m.shares = m.shares || []; m.notes = m.notes || [];
  // publicações (porta 3) vêm dos shares reais do ledger (Share: solicitada|aprovada|publicada|cancelada)
  if (!m.publishes.length && m.shares.length)
    m.publishes = m.shares.map(x => ({id: x.id, title: String(x.report || "").split("/").pop() || x.id,
      to: x.destination || "—", status: x.status, date: x.date, link: x.link || null}));
  return m;
}
const M = normalizeBrain(JSON.parse(document.getElementById("data").textContent));
const idx = (arr, k) => { k = k || "id"; return Object.assign(Object.create(null), Object.fromEntries(arr.map(x => [x[k], x]))); };
var A = idx(M.actions), D = idx(M.decisions), P = idx(M.projects), G = idx(M.goals), PE = idx(M.people), ART = idx(M.artifacts);
var DL = idx(M.deliveries), DD = idx(M.deliverables_done);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const WD = ["dom","seg","ter","qua","qui","sex","sáb"];
const fmtD = iso => { if (!iso) return "—"; const p = iso.slice(0,10).split("-"); return p[2] + "/" + p[1]; };
const fmtDL = iso => { if (!iso) return "—"; const p = iso.slice(0,10).split("-"); return p[2] + "/" + p[1] + "/" + p[0]; };
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
const chip = (level, label) => '<span class="chip h-' + esc(level) + '">' + esc(label) + "</span>";
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
  if (a.due_suggested) return '<span class="dsug" title="' + esc(a.due_reason || "prazo sugerido pelo agente") + '">' + (a.overdue_days ? "⚠ " : "") + fmtDW(a.due) + ' <em>sugerido</em>' +
    (a.overdue_days ? " · " + a.overdue_days + "d atrasada" : a.due_in != null && a.due_in <= 7 ? " · " + (a.due_in ? "em " + a.due_in + "d" : "hoje") : "") + "</span>";
  if (a.overdue_days) return '<span class="late">⚠ ' + fmtDW(a.due) + " · " + a.overdue_days + "d atrasada</span>";
  if (a.due_in != null && a.due_in <= 7) return '<span class="soon">' + fmtDW(a.due) + " · " + (a.due_in ? "em " + a.due_in + "d" : "hoje") + "</span>";
  return fmtDW(a.due);
}

// ── cartão de ação (kanban) ─────────────────────────────────────────────
function card(a){
  return '<article class="card' + (a.overdue_days ? " is-late" : "") + (a.status === "bloqueada" ? " is-blocked" : "") + '">' +
    '<header><span class="ids">' + aL(a.id) + "</span>" +
    (a.priority === "alta" ? " " + chip("em-risco", "alta") : "") +
    (a.list !== "mine" ? " " + chip("info", a.owner_name) : "") + "</header>" +
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

// ── views ───────────────────────────────────────────────────────────────
const V = Object.create(null);
V.home = () => {
  const c = M.counts;
  let h = '<div class="pagehead"><div><h1>☀ ' + fmtDW(M.today) + "</h1>" +
    '<p class="sub">' + esc(M.owner.name) + " · " + c.mine_open + " ações abertas" + (c.mine_overdue ? ' · <b class="late">' + c.mine_overdue + " atrasadas</b>" : "") + "</p></div></div>";
  h += '<div class="kpis">' + [
    ["Minhas abertas", c.mine_open, ""], ["Atrasadas", c.mine_overdue, c.mine_overdue ? "risk" : "ok"],
    ["Vencem em 7 dias", c.mine_due_7d, ""], ["Bloqueadas", c.mine_blocked, c.mine_blocked ? "risk" : ""],
    ["Aguardando outros", c.waiting_open, ""], ["Conquistas 30d", c.wins_30d, "ok"], ["Decisões 30d", c.decisions_30d, ""]]
    .map(k => '<div class="kpi ' + k[2] + '"><span>' + k[0] + "</span><b>" + k[1] + "</b></div>").join("") + "</div>";
  const needs = [];
  (M.questions || []).filter(q => q.status === "aberta").forEach(q => needs.push('<li class="info">' + chip("info", q.id) + " " + esc(q.text.slice(0, 100)) + '… — <a href="#ask">responder</a></li>'));
  M.proposals.forEach(p => needs.push('<li class="warn">' + chip("atencao", "proposta " + p.id) + " " + esc(p.summary) + (p.target ? " · alvo " + (A[p.target] ? aL(p.target) : esc(p.target)) : "") + ' — <a href="#ask">decidir</a></li>'));
  if (M.focus && M.focus.status === "proposto") needs.push('<li class="info">' + chip("info", "foco " + M.focus.id) + " plano com " + M.focus.blocks.length + ' blocos aguardando seu "ok" — <a href="#focus">ver</a></li>');
  M.outbox.filter(m => m.status === "rascunho").forEach(m => needs.push('<li class="info">' + chip("info", "rascunho " + m.id) + " para " + esc(m.to_name) + ': "' + esc(m.text.slice(0, 90)) + '" — <a href="#outbox">revisar</a></li>'));
  const pl = (n, s, p) => n === 1 ? s : p;
  if (c.mine_no_due) needs.push('<li class="warn">' + chip("atencao", "prazo") + " " + c.mine_no_due + " " + pl(c.mine_no_due, "ação sua sem prazo", "ações suas sem prazo") + " — o foco não consegue agendá-las</li>");
  if (c.mine_no_effort) needs.push('<li class="warn">' + chip("atencao", "esforço") + " " + c.mine_no_effort + " " + pl(c.mine_no_effort, "ação sua sem estimativa", "ações suas sem estimativa") + " de esforço</li>");
  if (needs.length) h += panel("Precisa de você", '<ul class="feed">' + needs.join("") + "</ul>", ' data-priority');
  h += "<h2 class=\"sec\">Goals</h2>";
  if (!M.goals.length) h += empty("Nenhum goal no PLANNING ainda — rode /init ou /goal.");
  h += '<div class="grid g2">' + M.goals.map(g => '<section class="panel goal"><div class="goal-head">' + donut(g.progress.pct, 48) +
    '<div><b class="goal-title">' + g.id + " — " + esc(g.title) + "</b>" + chip(g.health, g.health_label) +
    '<div class="muted small">' + (g.horizon ? "horizonte " + esc(g.horizon) + " · " : "") + progTxt(g.progress) + ' · <button class="btn ghost tiny" data-progress="' + esc(g.id) + '">⛏ declarar %</button>' +
    (g.declared ? " · declarado " + g.declared.pct + "% em " + fmtD(g.declared.date) : "") + "</div></div></div>" +
    g.projects.map(pid => { const p = P[pid]; return '<div class="proj"><div class="t">' + pL(pid, true) + "<small>" + esc(p.health.reason) +
      (p.next_due ? " · próximo: " + p.next_due.id + " " + fmtD(p.next_due.date) : "") + "</small></div>" + bar(p.progress.pct) + chip(p.health.level, p.health.label) + "</div>"; }).join("") +
    "</section>").join("") + "</div>";
  h += '<div class="grid g2" style="margin-top:14px">';
  const days = {};
  M.agenda.forEach(it => (days[it.date] = days[it.date] || []).push(it));
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
  (M.notes || []).forEach(n => { h += '<details class="panel note"><summary><b>Nota do agente · ' + esc(n.name) + '</b> <span class="muted">(FRESH/notes/' + esc(n.name) + ".md)</span></summary><div class=\"msg\">" + esc(n.text) + "</div></details>"; });
  return h;
};
V.todo = (q) => {
  const proj = q.get("p") || "", showWatch = q.get("w") === "1";
  const mine = M.actions.filter(a => a.list === "mine" && a.mine && (!proj || a.project === proj));
  const recent = new Date(M.today + "T12:00:00"); recent.setDate(recent.getDate() - 14);
  const cols = [["A fazer", a => a.open && a.status === "aberta", "aberta"],
    ["Fazendo", a => a.open && a.status === "fazendo", "fazendo"],
    ["Bloqueada / aguardando", a => a.open && (a.status === "bloqueada" || a.status === "aguardando"), "aguardando"],
    ["Feita (14 dias)", a => a.status === "fechada" && a.closed && new Date(a.closed + "T12:00:00") >= recent, "fechada"]];
  const sortA = l => l.sort((x, y) => (x.due || "9999").localeCompare(y.due || "9999") || (x.priority === "alta" ? -1 : 0));
  let h = '<div class="pagehead"><div><h1>TODO</h1><p class="sub">Suas ações em quadro. Feche pelo chat (/done), marcando em FRESH/todo.md — ou pelo painel, se a ponte CLI estiver ligada.</p></div></div>' +
    '<div class="filters">' + dd("fp", M.projects.map(p => [p.id, p.id + " " + p.title]), proj, "todos os projetos") +
    '<label class="chk"><input type="checkbox" id="fw"' + (showWatch ? " checked" : "") + "> mostrar observando</label></div>";
  h += '<div class="kanban">' + cols.map(([t, f, key]) => { const l = sortA(mine.filter(f)); return '<div class="col" data-col="' + key + '"><h3>' + t + ' <span class="count">' + l.length + "</span></h3>" + (l.map(card).join("") || empty("—")) + "</div>"; }).join("") + "</div>";
  const waiting = M.actions.filter(a => a.open && a.list === "waiting" && (!proj || a.project === proj));
  h += panel("Aguardando de outros · " + waiting.length, actionTable(sortA(waiting).map(a => a.id), ["owner", "age", "project"]), ' style="margin-top:16px"');
  if (showWatch) {
    const w = M.actions.filter(a => a.open && a.list === "watching" && (!proj || a.project === proj));
    h += panel("Observando — contexto, não cobra · " + w.length, actionTable(w.map(a => a.id), ["owner", "project"]), ' style="margin-top:14px"');
  }
  setTimeout(() => {
    const b = document.querySelector('[data-dd="fp"] .dd-btn');
    if (b) b.addEventListener("ddchange", e => go("todo", {p: e.detail.value, w: showWatch ? "1" : ""}));
    const c = document.querySelector("#fw");
    if (c) c.onchange = e => go("todo", {p: proj, w: e.target.checked ? "1" : ""});
  });
  return h;
};
V.projects = () => {
  let h = '<div class="pagehead"><div><h1>Projetos</h1><p class="sub">A árvore de PLANNING, por goal.</p></div></div>';
  if (!M.projects.length) return h + empty("Nenhum projeto no PLANNING.");
  M.goals.forEach(g => {
    h += '<h2 class="sec">' + g.id + " — " + esc(g.title) + " " + chip(g.health, g.health_label) + '</h2><div class="grid g3">' + g.projects.map(pid => { const p = P[pid];
      return '<section class="panel projcard"><div class="projcard-head">' + donut(p.progress.pct, 44) + '<div><b>' + pL(pid, true) + "</b>" + chip(p.health.level, p.health.label) +
        '<div class="muted small">' + progTxt(p.progress) + "</div></div></div>" +
        '<div class="muted small">' + esc(p.health.reason) + "</div>" +
        '<div class="foot small">' + p.actions.mine.length + " minhas · " + p.actions.waiting.length + " aguardando · " + p.decisions.length + " decisões" +
        (p.next_due ? " · próximo " + p.next_due.id + " " + fmtD(p.next_due.date) : "") + "</div></section>"; }).join("") + "</div>";
  });
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
  return h;
};
V.decisions = (q) => {
  const proj = q.get("p") || "", who = q.get("who") || "", st = q.get("s") || "";
  const list = M.decisions.filter(d => (!proj || d.project === proj) && (!who || d.decided_by.includes(who)) && (!st || d.status === st));
  let h = '<div class="pagehead"><div><h1>Decisões</h1><p class="sub">Quem decidiu o quê, quando — e de onde veio. Substituídas ficam riscadas, nunca apagadas.</p></div></div>';
  h += '<div class="filters">' +
    dd("dp", M.projects.map(p => [p.id, p.id + " " + p.title]), proj, "todos os projetos") +
    dd("dw", M.people.filter(p => p.decisions.length).map(p => [p.id, p.name]), who, "qualquer pessoa") +
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
    const items = [...k.deliveries.map(id => { const e = DL[id]; return "<li>✓ <b>" + esc(e.title) + '</b> <span class="muted">' + fmtD(e.date) + "</span> — " + esc(e.result) + (e.impact ? " · impacto: " + esc(e.impact) : "") + (e.project ? " · " + pL(e.project) : "") + ' <span class="muted">[' + esc(e.prov) + "]</span></li>"; }),
      ...k.deliverables.map(id => { const x = DD[id]; return "<li>✓ entregável <b>" + id + "</b> " + esc(x.title) + ' <span class="muted">' + fmtD(x.date) + "</span> · " + pL(x.project) + "</li>"; })];
    h += '<h2 class="sec">' + esc(k.label) + ' <span class="muted">· ' + (k.deliveries.length + k.deliverables.length) + " entregas · " + k.closed.length + " ações fechadas · " + k.decisions.length + " decisões</span></h2>" +
      panel("", (items.length ? '<ul class="feed">' + items.join("") + "</ul>" : "") + (k.closed.length ? '<p class="muted small">Ações fechadas: ' + k.closed.map(id => aL(id) + " " + esc(A[id].title)).join(" · ") + "</p>" : "") +
      (!items.length && !k.closed.length ? empty("nada registrado") : ""));
  });
  return h;
};
V.people = () => '<div class="pagehead"><div><h1>Pessoas</h1><p class="sub">Uma ficha por pessoa — nunca duas.</p></div></div>' +
  panel("", '<div class="twrap"><table><tr><th>Pessoa</th><th>Papel</th><th>Última interação</th><th>Me deve</th><th>Devo</th><th>Decisões</th></tr>' +
  M.people.map(p => "<tr><td>" + peL(p.id) + (p.is_owner ? " " + chip("info", "você") : "") + "</td><td>" + esc(p.role || "—") + '</td><td class="muted">' + (p.last_interaction ? fmtD(p.last_interaction.date) + " " + esc(p.last_interaction.title) : "—") +
    '</td><td class="num">' + p.owes_me.length + '</td><td class="num">' + p.i_owe.length + '</td><td class="num">' + p.decisions.length + "</td></tr>").join("") + "</table></div>");
V.person = (q, id) => {
  const p = PE[decodeURIComponent(id)]; if (!p) return empty("Pessoa não encontrada");
  let h = '<p class="crumb muted"><a href="#people">← pessoas</a></p><div class="pagehead"><div><h1>' + esc(p.name) + "</h1>" +
    '<p class="sub">' + esc(p.role || "papel não registrado") + " · relação: " + esc(p.relation || "—") +
    " · aliases: " + (p.aliases.map(esc).join(", ") || "—") + "</p></div></div>";
  h += "<p><b>Última interação:</b> " + (p.last_interaction ? fmtDL(p.last_interaction.date) + " — " + esc(p.last_interaction.title) : "não consta") + "</p>";
  h += '<div class="grid g2">' + panel("O que me deve", actionTable(p.owes_me, ["age", "project"]) + "<h2>O que eu devo</h2>" + actionTable(p.i_owe, ["project"]));
  h += panel("Decisões que tomou", (p.decisions.length ? '<ul class="feed">' + p.decisions.map(d => '<li><span class="muted">' + fmtD(D[d].date) + "</span> · " + dL(d) + " " + esc(D[d].title) + "</li>").join("") + "</ul>" : empty("nenhuma registrada")) +
    "<h2>Projetos</h2>" + (p.projects.map(x => pL(x, true)).join(" · ") || empty("—")) + '<h2>Menções recentes</h2><ul class="feed">' + p.artifacts.filter(a => ART[a]).map(a => '<li><span class="muted">' + fmtD(ART[a].date) + "</span> · " + esc(ART[a].title) + "</li>").join("") + "</ul>") + "</div>";
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
  h += '<div class="week" style="grid-template-columns:34px repeat(' + Math.max(1, days.length) + ',1fr)">' +
    '<div class="hcol"><div class="wslot" style="' + gridBg + '">' +
    hours.map(hourMark).join("") +
    "</div></div>" + days.map(d => '<div class="wday"><h3>' + fmtDW(d) + '</h3><div class="wslot" style="' + gridBg + '">' +
    busy.filter(e => e.start.startsWith(d)).map(e => { const top = (toMin(e.start) - minS) / span * 100, hgt = (toMin(e.end) - toMin(e.start)) / span * 100;
      return '<div class="blk busy' + (hgt < 4.5 ? " tiny" : "") + '" style="top:' + top + "%;height:" + hgt + '%"><b>' + e.start.slice(11, 16) + "–" + e.end.slice(11, 16) + "</b> " + esc(e.title || "ocupado") + "</div>"; }).join("") +
    blocks.filter(b => b.start.startsWith(d)).map(b => { const top = (toMin(b.start) - minS) / span * 100, hgt = (toMin(b.end) - toMin(b.start)) / span * 100, a = A[b.action];
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
  return h;
};
V.outbox = () => {
  const groups = [["Aguardando sua aprovação", ["rascunho"]], ["Aprovadas, não enviadas", ["aprovada"]], ["Enviadas", ["enviada"]], ["Falhas / canceladas", ["falhou", "cancelada"]]];
  let h = '<div class="pagehead"><div><h1>Mensagens</h1><p class="sub">Nada é enviado sem sua aprovação do texto exato. Todo envio fica registrado.</p></div></div>';
  return h + groups.map(([t, s]) => {
    const l = M.outbox.filter(m => s.includes(m.status));
    return panel(t + " · " + l.length, (l.map(m => "<div class=\"msgrow\"><header><b>" + m.id + "</b> → " + esc(m.to_name) + (m.ref ? " · ref " + (A[m.ref] ? aL(m.ref) : esc(m.ref)) : "") + (m.why ? ' <span class="muted">· ' + esc(m.why) + "</span>" : "") +
      (m.sent ? ' <span class="muted">· enviada ' + fmtD(m.sent) + "</span>" : "") + "</header>" + '<div class="msg">' + esc(m.text) + "</div></div>").join("") || empty("—")), ' style="margin-top:14px"');
  }).join("");
};
V.health = () => '<div class="pagehead"><div><h1>Saúde</h1><p class="sub">Checagens do brain doctor.</p></div></div>' +
  panel("", '<ul class="feed health">' + (M.health || []).map(c => '<li class="' + c.level + '"><span class="hicon">' + ({ok: "✓", warn: "⚠", error: "✗"}[c.level]) + "</span> <b>" + esc(c.title) + "</b> — " + esc(c.detail) + "</li>").join("") + "</ul>");
V.action = (q, id) => {
  const a = A[id]; if (!a) return empty("Ação não encontrada");
  return '<p class="crumb muted"><a href="#todo">← TODO</a></p><div class="pagehead"><div><h1>' + a.id + " · " + esc(a.title) + '</h1>' +
    '<div class="sub">' + chip(a.status === "bloqueada" ? "em-risco" : a.open ? "info" : "em-dia", a.status) +
    "<span>dono: " + peL(a.owner) + "</span><span>" + dueTxt(a) + "</span>" + (a.effort_min ? "<span>esforço " + dur(a.effort_min) + "</span>" : "") + (a.project ? "<span>" + pL(a.project, true) + "</span>" : "") + "</div></div>" +
    '<div class="ask-opts"><button class="btn" data-act="edit" data-id="' + esc(a.id) + '">e editar</button>' +
    (a.open ? '<button class="btn primary" data-act="close" data-id="' + esc(a.id) + '">c fechar</button>' : '<button class="btn" data-act="reopen" data-id="' + esc(a.id) + '">o reabrir</button>') +
    '<button class="btn" data-act="merge" data-id="' + esc(a.id) + '">m mesclar duplicada</button></div></div>' +
    panel("", (a.blocked_by.length ? "<p>⛔ bloqueada por " + a.blocked_by.map(aL).join(", ") + "</p>" : "") + (a.unblocks.length ? "<p>destrava: " + a.unblocks.map(u => A[u] ? aL(u) : esc(u)).join(", ") + "</p>" : "") +
    (a.people.length ? "<p>envolvidos: " + a.people.map(peL).join(", ") + "</p>" : "") + '<p class="muted small">origem: ' + esc(a.source_label) + " [" + esc(a.prov) + "]</p>" + (a.outcome ? "<p><b>Resultado:</b> " + esc(a.outcome) + "</p>" : "") +
    "<h2>Histórico</h2>" + '<ul class="feed">' + a.history.map(x => '<li><span class="muted">' + fmtD(x.date) + "</span> · " + esc(x.type) + " · " + esc(x.note) + ' <span class="muted">(' + esc(x.by) + ")</span></li>").join("") + "</ul>");
};
V.decision = (q, id) => {
  const d = D[id]; if (!d) return empty("Decisão não encontrada");
  return '<p class="crumb muted"><a href="#decisions">← decisões</a></p><div class="pagehead"><div><h1>' + d.id + " · " + esc(d.title) + "</h1></div></div>" +
    panel("", "<p>Decidido por " + d.decided_by.map(peL).join(", ") + " em <b>" + fmtDL(d.date) + "</b>" + (d.project ? " · " + pL(d.project, true) : "") + "</p>" +
    (d.context ? "<p><b>Contexto:</b> " + esc(d.context) + "</p>" : "") + (d.rationale ? "<p><b>Por quê:</b> " + esc(d.rationale) + "</p>" : "") +
    '<p class="muted small">Fonte: ' + esc(d.source_label) + " (" + esc(d.source) + ") [" + esc(d.prov) + "]</p>" + (d.supersedes ? "<p>Substitui " + dL(d.supersedes) + "</p>" : "") + (d.superseded_by ? '<p class="late">Substituída por ' + dL(d.superseded_by) + "</p>" : ""));
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
const iceTxt = o => o.score == null ? '<span class="muted">sem ICE</span>' : '<span class="' + (o.ice_suggested ? "sug" : "") + '" title="' + esc(o.ice_reason || "") + '">' +
  o.impact + "×" + o.confidence + "×" + o.ease + " = <b>" + o.score + "</b>" + (o.ice_suggested ? " · sugerido" : "") + "</span>";
const areaName = a => AREA[a] ? AREA[a].name : a;
function oppRow(o, i){
  return "<tr><td>" + (i != null ? i + "</td><td>" : "") + "<b>" + esc(o.id) + "</b></td><td><details><summary>" + esc(o.title) + "</summary>" +
    "<p><b>Problema:</b> " + esc(o.problem || "não consta") + "</p><p><b>Sugestão:</b> " + esc(o.suggestion || "não consta") + "</p>" +
    (o.evidence_count ? '<p class="muted small">' + o.evidence_count + " evidência(s): " + o.evidence.map(esc).join(", ") + "</p>" : "") +
    (o.docs.length ? "<p>" + o.docs.map(d => chip("info", d.kind) + " " + esc(d.title || d.ref)).join(" · ") + "</p>" : "") +
    (o.status_history.length ? '<p class="muted small">' + o.status_history.map(h => fmtD(h.date) + " " + esc(h.from) + "→" + esc(h.to) + (h.reason ? " (" + esc(h.reason) + ")" : "")).join(" · ") + "</p>" : "") +
    "</details></td><td>" + esc(areaName(o.area)) + "</td><td>" + iceTxt(o) + "</td><td>" + chip("info", o.status) + "</td><td>" + esc(o.quadrant || "—") +
    "</td><td>" + (o.project ? pL(o.project, true) + " · " + esc(o.goal) : '<span class="muted">—</span>') + '</td><td class="num">' + hrs(o.hours_saved) + "</td></tr>";
}
// ── face Portfólio: pf/visao · pf/opps (kanban) · pf/matrix · pf/procs · pf/areas ──
const STAGES_PIPE = ["ideia", "triagem", "priorizada", "em-andamento", "piloto", "validando", "entregue"];
const STAGES_LAT = ["em-espera", "descartada"];
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
  let h = '<div class="pagehead"><div><h1>Portfólio</h1><p class="sub">Processos que existem e o que vale melhorar neles. ICE = impacto × confiança × facilidade (1–5).</p></div></div>' +
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
    return '<div class="col pf-col' + (STAGES_LAT.includes(s) ? " lat" : "") + '" data-stage="' + s + '"><h3>' + s + ' <span class="count">' + l.length + "</span></h3>" +
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
    panel("", '<div class="grid mx">' + QUADS.map(([qn, d]) => '<div class="col"><h3>' + qn + ' <span class="muted">· ' + d + "</span></h3>" +
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
      rows.map(p => "<tr><td>" + idc(p.id) + "</td><td>" + esc(p.title) + (p.status !== "ativo" ? " " + chip("s-descartada", "aposentado") : "") + "</td><td>" + (p.owner ? peL(p.owner) : "—") +
        "</td><td>" + esc(p.recurrence || "—") + '</td><td class="num">' + hrs(p.hours_month) + '</td><td class="num">' + p.opportunities.length + "</td><td>" +
        (p.gaps.length ? '<span class="late">⚠ ' + p.gaps.map(esc).join("; ") + "</span>" : '<span class="ok">✓</span>') + "</td></tr>").join("") + "</table></div>",
      ' style="margin-top:14px"') : "";
  }).join("") || empty("nenhum processo");
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
      (procs.length ? procs.map(x => "<tr><td>" + idc(x.id) + "</td><td>" + esc(x.title) + (x.status !== "ativo" ? " " + chip("s-descartada", "aposentado") : "") + "</td><td>" +
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
    '<div class="sub">' + stChip(o.status) + chip("", o.kind) + "<span>" + esc(areaName(o.area)) + "</span>" + (o.quadrant ? chip("", o.quadrant) : "") +
    "<span>ICE " + iceTxt(o) + "</span></div></div></div>";
  h += '<div class="grid g2">' + panel("Resumo", '<ul class="feed"><li><b>Ganho esperado:</b> ' + esc(o.gain || "não consta") + (o.hours_saved ? " · " + hrs(o.hours_saved) : "") + "</li>" +
    "<li><b>Processo:</b> " + (o.process ? idc(o.process) + " " + esc(proc ? proc.title : "") : "—") + "</li>" +
    "<li><b>Goal:</b> " + (o.goal ? esc(o.goal) + " " + esc(o.goal_title || "") : "—") + "</li>" +
    "<li><b>Projeto:</b> " + (o.project ? pL(o.project, true) : "—") + "</li>" +
    '<li><b>Registrada:</b> ' + fmtD(o.added) + " · por " + esc(o.by === "owner" ? "dono" : "agente") + " [" + esc(o.prov) + "]</li></ul>");
  h += panel("Problema → Sugestão", '<div class="msg">' + esc(o.problem || "não consta") + '</div><div class="msg">' + esc(o.suggestion || "não consta") + "</div>") + "</div>";
  if (o.docs.length) h += panel("Documentos", '<ul class="feed">' + o.docs.map(d => "<li>" + chip("info", d.kind) + " " + esc(d.title || d.ref) + "</li>").join("") + "</ul>", ' style="margin-top:14px"');
  h += panel("Histórico de status", o.status_history.length ? '<ul class="feed">' + o.status_history.map(x => "<li><span class=\"muted\">" + fmtD(x.date) + "</span> · " + stChip(x.from) + " → " + stChip(x.to) +
    (x.reason ? ' <span class="muted">(' + esc(x.reason) + ")</span>" : "") + "</li>").join("") + "</ul>" : empty("criada em " + fmtD(o.added) + " como " + o.status), ' style="margin-top:14px"');
  return h;
};
V.portfolio = () => { location.hash = "#pf/visao"; return ""; };   // compat: link antigo


// ── perguntas do agente (ASK-####) e propostas (PROP-####) ──────────────
V.ask = () => {
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
    (q.context ? '<p class="muted small">contexto: ' + esc(q.context) + "</p>" : "") +
    "</div>").join("") : empty("nenhuma pergunta aberta"));
  h += panel("Propostas abertas · " + M.proposals.length, M.proposals.length ? M.proposals.map(pr =>
    '<div class="card" style="margin:0 0 10px"><header><span class="ids">' + idc(pr.id) + "</span>" + chip("atencao", pr.kind) + "</header>" +
    '<h3 class="card-title">' + esc(pr.summary) + "</h3>" +
    '<p class="muted small">' + (pr.target ? "alvo " + esc(pr.target) + " · " : "") + (pr.into ? "em " + esc(pr.into) + " · " : "") +
    "evidência: " + esc(pr.evidence || "—") + "</p>" +
    '<div class="ask-opts"><button class="btn primary" data-acc>aceitar (gate)</button><button class="btn" data-rej>rejeitar</button></div></div>').join("")
    : empty("nenhuma proposta aberta"), ' style="margin-top:14px"');
  const pubs = M.publishes || [];
  if (pubs.length) h += panel("Publicar (porta 3) · " + pubs.filter(x => x.status !== "publicada").length + " aguardando",
    pubs.map(x => '<div class="card" style="margin:0 0 10px"><header><span class="ids">' + idc(x.id) + "</span>" +
      chip(x.status === "solicitada" ? "atencao" : x.status === "publicada" ? "em-dia" : "info", x.status) +
      ' <span class="muted small">→ ' + esc(x.to) + "</span></header>" +
      '<h3 class="card-title">' + esc(x.title) + "</h3>" +
      (x.link ? '<p class="muted small">' + esc(x.link) + "</p>" : "") +
      '<div class="ask-opts">' +
      (x.status === "solicitada" ? '<button class="btn primary" data-pub="approve:' + esc(x.id) + '">aprovar (gate)</button><button class="btn" data-pub="cancel:' + esc(x.id) + '">cancelar</button>' : "") +
      (x.status === "aprovada" ? '<button class="btn primary" data-pub="done:' + esc(x.id) + '">publicar (agente)</button><button class="btn" data-pub="cancel:' + esc(x.id) + '">cancelar</button>' : "") +
      (x.status === "publicada" ? '<a class="btn" href="' + esc(x.link || "#") + '">abrir ↗</a>' : "") +
      "</div></div>").join("") + '<p class="muted small">pedir nova: tecla n · o export sai de brain share; o agente posta na porta 3</p>', ' style="margin-top:14px"');
  if (feitas.length) h += panel("Respondidas", '<ul class="feed">' + feitas.map(q =>
    "<li>" + idc(q.id) + ' <span class="muted">' + esc(q.text.slice(0, 90)) + "…</span> → <b>" + esc(q.answer || "") + "</b></li>").join("") + "</ul>", ' style="margin-top:14px"');
  return h;
};

// ── router + faces (mesma lógica da TUI: Execução | Portfólio, cada face lembra onde estava) ──
const TABS_EXEC = [["home", "Início"], ["todo", "TODO", () => M.counts.mine_overdue], ["projects", "Projetos"], ["decisions", "Decisões"], ["ask", "Perguntas", () => ((M.questions || []).filter(q => q.status === "aberta").length + M.proposals.length) || 0], ["wins", "Conquistas"],
  ["people", "Pessoas"], ["timeline", "Linha do tempo"], ["focus", "Foco", () => M.focus && M.focus.status === "proposto" ? 1 : 0],
  ["outbox", "Mensagens", () => M.counts.outbox_pending], ["health", "Saúde", () => (M.health || []).filter(c => c.level !== "ok").length]];
const TABS_PF = [["pf/visao", "Visão geral"], ["pf/opps", "Oportunidades", () => PF.opportunities.filter(o => o.status !== "descartada").length],
  ["pf/matrix", "Matriz"], ["pf/procs", "Processos", () => PF.processes.filter(p => p.status === "ativo").length], ["pf/areas", "Áreas", () => PF.areas.length]];
const FACES = [["execucao", "Execução", TABS_EXEC], ["portfolio", "Portfólio", TABS_PF]];
if (window.PF_ONLY) { FACES.length = 0; FACES.push(["portfolio", "Portfólio", TABS_PF]); }
const faceOf = v => v.indexOf("pf/") === 0 ? "portfolio" : "execucao";
const PARENT = {project: "projects", person: "people", action: "todo", decision: "decisions", "pf/opp": "pf/opps", "pf/area": "pf/areas"};
function go(view, params){ const q = new URLSearchParams(Object.entries(params || {}).filter(([, v]) => v)).toString(); location.hash = view + (q ? "?" + q : ""); }
function route(){
  const raw = location.hash.slice(1) || "home", parts = raw.split("?"), path = parts[0], qs = parts[1] || "";
  let seg = path.split("/");
  if (seg[0] === "face") {                       // trocar de face: volta pra onde a face estava
    const f = FACES.some(x => x[0] === seg[1]) ? seg[1] : "execucao";
    const last = localStorage.getItem("mock-face-" + f);
    location.hash = last || (f === "portfolio" ? "pf/visao" : "home");
    return;
  }
  if (seg[0] === "portfolio") seg = ["pf", "visao"];          // link antigo
  const pf = seg[0] === "pf";
  let view = pf ? "pf/" + (seg[1] || "visao") : seg[0];
  const arg = pf ? seg.slice(2).join("/") : seg.slice(1).join("/");
  const q = new URLSearchParams(qs);
  if (!V[view]) view = "home";
  if (window.PF_ONLY && faceOf(view) === "execucao") { location.hash = "#pf/visao"; return; }
  localStorage.setItem("mock-face-" + faceOf(view), raw);
  if (typeof window.renderTabs === "function")
    window.renderTabs(view, (FACES.find(f => f[0] === faceOf(view)) || FACES[0])[2], PARENT);
  if (typeof window.renderFaces === "function") window.renderFaces(faceOf(view));
  $("#view").innerHTML = V[view](q, arg && decodeURIComponent(arg));
  if (typeof window.afterRoute === "function") window.afterRoute(view, q, arg);
  window.scrollTo(0, 0);
}
window.BRAIN = {M, A, D, P, G, PE, OPP, PROC, AREA, go, route, chip, aL, dL, pL, peL, fmtD, fmtDW, donut, bar, esc,
  refresh: function(nm){                       // ponte CLI (./brain serve): novo view model → índices + views
    normalizeBrain(nm);
    for (const k of Object.keys(M)) delete M[k];
    Object.assign(M, nm);
    A = idx(M.actions); D = idx(M.decisions); P = idx(M.projects); G = idx(M.goals);
    PE = idx(M.people); ART = idx(M.artifacts); DL = idx(M.deliveries); DD = idx(M.deliverables_done);
    PF = M.portfolio; AREA = idx(PF.areas); OPP = idx(PF.opportunities); PROC = idx(PF.processes);
    BRAIN.A = A; BRAIN.D = D; BRAIN.P = P; BRAIN.G = G; BRAIN.PE = PE;   // re-exporta: quem lê
    BRAIN.OPP = OPP; BRAIN.PROC = PROC; BRAIN.AREA = AREA;              // window.BRAIN não pode ficar congelado no boot
    route();
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
route();
})();
