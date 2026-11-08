/* VARIANTE B extras — paleta ⌘K + ponte CLI simulada (mesmos comandos que o TUI dispara). */
(function(){
"use strict";
let faceList = [], faceCur = "execucao";   // carrossel de faces: alimentado pelo renderFaces (o core passa a lista)
const D0 = JSON.parse(document.getElementById("data").textContent);
D0.counts = D0.counts || {}; D0.questions = D0.questions || []; D0.proposals = D0.proposals || [];
D0.outbox = D0.outbox || []; D0.health = D0.health || []; D0.deliveries = D0.deliveries || [];
D0.feedback = D0.feedback || [];
D0.actions = D0.actions || []; D0.shares = D0.shares || []; D0.people = D0.people || [];
D0.projects = D0.projects || []; D0.goals = D0.goals || []; D0.decisions = D0.decisions || [];
D0.portfolio = D0.portfolio || {areas: [], processes: [], opportunities: [], gaps: []};
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm = s => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");

// ── sidebar: dono + data ────────────────────────────────────────────────
$("#ownername").textContent = D0.owner.name;
$("#avatar").textContent = D0.owner.name.trim().slice(0, 1).toUpperCase();
$("#gen2").textContent = "gerado " + D0.generated_at.slice(0, 10);

window.renderTabs = function(view, TABS, PARENT){
  document.getElementById("tabs").innerHTML = TABS.map(function(t){
    const n = t[2] ? t[2]() : 0;
    return '<a href="#' + t[0] + '" class="' + ((view === t[0] || PARENT[view] === t[0]) ? "on" : "") + '">' + t[1] +
      (n ? '<span class="badge">' + n + "</span>" : "") + "</a>";
  }).join("");
};
window.renderFaces = function(face, F){   // F vem por parâmetro (padrão da casa: o core é um IIFE, nada vaza pro escopo global)
  faceList = (F && F.length ? F : faceList);   // carrossel do Tab usa a lista que o core passa
  faceCur = face;
  const n = faceList.length, i = Math.max(0, faceList.findIndex(f => f[0] === face));
  const cur = faceList[i] || ["", "—"];
  const prev = n > 1 ? faceList[(i + n - 1) % n] : null;   // ‹ face atual ›: tamanho constante, por mais faces que entrem
  const next = n > 1 ? faceList[(i + 1) % n] : null;
  document.getElementById("faces").innerHTML =
    (prev ? '<button class="fnav" data-f="' + prev[0] + '" title="Face anterior · ' + prev[1] + ' (Shift+Tab)">‹</button>' : "") +
    '<button class="fcur" data-f="' + (next ? next[0] : cur[0]) + '" title="Próxima face — Tab">' + cur[1] + "</button>" +
    (next ? '<button class="fnav" data-f="' + next[0] + '" title="Próxima face · ' + next[1] + ' (Tab)">›</button>' : "");
  document.querySelectorAll("#faces button").forEach(b => b.onclick = () => { location.hash = "#face/" + b.dataset.f; });
};

// ── toast + console ─────────────────────────────────────────────────────
let toastTmr;
function toast(msg){ const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTmr); toastTmr = setTimeout(() => t.classList.remove("show"), 2800); }
let conAuto = sessionStorage.getItem("con-fechado") !== "1";   // quem fechou, ficou fechado
let conUnread = 0;
function conToggle(force){
  const el = $("#console"), open = el.classList.contains("open");
  const on = force !== undefined ? force : !open;
  el.classList.toggle("open", on);
  document.body.classList.toggle("con-open", on);
  conAuto = on;                                              // abrir de novo reativa o auto-open
  if (on) { conUnread = 0; const b = $("#conbadge"); if (b) { b.textContent = ""; b.classList.remove("on"); }
            sessionStorage.removeItem("con-fechado"); $("#conout").scrollTop = 1e6; }
  else sessionStorage.setItem("con-fechado", "1");
}
function conOpen(){ if (conAuto) $("#console").classList.add("open"); }
function conLine(html){
  const out = $("#conout");
  out.innerHTML += html + "\n";
  const lines = out.innerHTML.split("\n");                   // buffer limitado: as últimas 300 linhas
  if (lines.length > 300) out.innerHTML = lines.slice(-300).join("\n");
  out.scrollTop = 1e6;
  if (!$("#console").classList.contains("open")) {            // fechado: conta não-lidas na pílula
    conUnread++; const b = $("#conbadge"); if (b) { b.textContent = conUnread > 50 ? "50+" : conUnread; b.classList.add("on"); } }
}
$("#conx").onclick = () => conToggle(false);
(function(){ const ci = document.querySelector("#clidot");   // ponto CLI no canto direito do topo
  if (ci) ci.onclick = () => conToggle(); })();

// ── ponte CLI: ./brain serve (127.0.0.1 + token). file:// continua sendo retrato somente-leitura ──
const SERVE = location.protocol === "http:" && location.hostname === "127.0.0.1";
let TOK = null;
if (SERVE) {
  const m = location.hash.match(/[#&]t=([^&]+)/);
  if (m) { TOK = decodeURIComponent(m[1]); try { localStorage.setItem("brain-serve-token", TOK); } catch (e) {}
           history.replaceState(null, "", location.pathname + location.search); }
  else { try { TOK = localStorage.getItem("brain-serve-token"); } catch (e) {} }
}
let LIVE = SERVE && !!TOK;
function copyCmd(cmd){
  const t = document.createElement("textarea");
  t.value = cmd; t.style.position = "fixed"; t.style.opacity = "0";
  document.body.appendChild(t); t.select();
  try { document.execCommand("copy"); } catch (e) {}
  t.remove();
}
function offlineCmd(cmd){
  copyCmd(cmd);
  conOpen();
  conLine('<span class="dim">$</span> ' + esc(cmd));
  conLine('<span class="ok">copiado</span> <span class="dim">— rode no terminal (mesma linha que o TUI dispara) · views: brain render</span>');
  toast("comando copiado — rode no terminal");
}
if (LIVE) {
  const cm = document.querySelector("#conmode");
  if (cm) cm.textContent = "vivo — comandos executam";
  document.body.classList.add("bridge-live");
  const ci = document.querySelector("#clidot");
  if (ci) { ci.classList.add("live"); ci.title = "ponte CLI conectada — comandos executam (clique/\` para o console)"; }
} else {
  const ci = document.querySelector("#clidot");
  if (ci) ci.title = "ponte CLI offline — retrato: comandos são copiados (clique/\` para o console)";
}

// ── comandos (mesmas linhas que o TUI roda) ────────────────────────────
function commands(){
  const out = [];
  const MD = (window.BRAIN && window.BRAIN.M) || D0;   // model vivo: o que já rodou sai da paleta
  const mine = MD.actions.filter(a => a.open && a.mine && a.list === "mine");
  mine.filter(a => a.status === "aberta").forEach(a => out.push({label: "Marcar fazendo · " + a.id + " " + a.title,
    cmd: "brain action update " + a.id + " --status fazendo", mut: m => { m.actions.find(x => x.id === a.id).status = "fazendo"; }}));
  mine.forEach(a => out.push({label: "Fechar · " + a.id + " " + a.title, act: () => closeForm(a)}));
  MD.actions.filter(a => a.open && a.due_suggested).forEach(a => out.push({label: "Confirmar prazo sugerido · " + a.id + " (" + (a.due || "").slice(0, 10) + ")",
    cmd: "brain action update " + a.id + " --confirm-due", mut: m => { m.actions.find(x => x.id === a.id).due_suggested = false; }}));
  if (D0.focus && D0.focus.status === "proposto") {
    out.push({label: "Aprovar plano de foco " + D0.focus.id + ' (quote "ok")',
      cmd: 'brain focus approve ' + D0.focus.id + ' --quote "ok"', mut: m => { m.focus.status = "aprovado"; m.focus.quote = "ok"; }});
    out.push({label: "Aprovar e aplicar " + D0.focus.id + " no Google Calendar",
      cmd: "brain focus apply " + D0.focus.id + " --mode google",
      mut: m => { m.focus.status = "aplicado"; m.focus.applied = m.focus.blocks; m.focus.mode = "google"; }});
  }
  MD.outbox.filter(m0 => m0.status === "rascunho").forEach(m0 => out.push({label: "Aprovar mensagem " + m0.id + " para " + m0.to_name,
    act: () => approveMsgForm(m0)}));
  MD.proposals.forEach(p => {
    out.push({label: "Aceitar proposta " + p.id + " · " + p.summary.slice(0, 60) + "…",
      cmd: 'brain proposal accept ' + p.id + ' --quote "ok"', mut: m => { m.proposals = m.proposals.filter(x => x.id !== p.id); }});
    out.push({label: "Rejeitar proposta " + p.id,
      cmd: 'brain proposal reject ' + p.id + ' --quote "não"', mut: m => { m.proposals = m.proposals.filter(x => x.id !== p.id); }});
  });
  out.push({label: "Regenerar views (render)", cmd: "brain render"});
  return out;
}

async function api(path, opts){
  const headers = Object.assign({"X-Brain-Token": TOK}, (opts && opts.headers) || {});
  const r = await fetch(path, Object.assign({}, opts, {headers}));
  if (r.status === 401) { toast("token inválido — rode ./brain serve e abra a URL impressa"); throw new Error("401"); }
  return r.json();
}
async function serveRun(cmd){
  conOpen();
  conLine('<span class="dim">$</span> ' + esc(cmd));
  let j;
  try {
    j = await api("/api/cmd", {method: "POST", headers: {"Content-Type": "application/json"},
                              body: JSON.stringify({cmd: cmd})});
  } catch (e) { conLine('<span class="late">ponte fora do ar — ./brain serve</span>'); return false; }
  (j.out || []).forEach(l => conLine('<span class="' + (l.startsWith("✓") ? "ok" : "dim") + '">' + esc(l) + "</span>"));
  if (j.err) conLine('<span class="late">' + esc(j.err.split("\n")[0]) + "</span>");
  if (j.error) conLine('<span class="late">' + esc(j.error) + "</span>");
  if (!j.ok) { toast("comando recusado — saída no console"); return false; }
  try {
    const d = await api("/api/data");
    if (window.BRAIN && window.BRAIN.refresh) window.BRAIN.refresh(d.model);
  } catch (e) { /* views regeneram no próximo brain render */ }
  return true;
}
// fatos do dono levam --by owner — a mesma convenção das linhas que o TUI dispara
const NEEDS_BY = ["action ", "area ", "decision add", "delivery ", "person ", "process ",
  "opportunity add", "opportunity update", "opportunity score", "opportunity status", "plan deliverable"];
function ownerCmd(cmd){
  const bare = cmd.replace(/^brain /, "");
  return NEEDS_BY.some(x => bare.startsWith(x)) && !/\s--by(\s|=)/.test(bare) ? cmd + " --by owner" : cmd;
}
function runCommand(cmd, mut){
  cmd = ownerCmd(cmd);
  if (LIVE) { serveRun(cmd); return; }
  { offlineCmd(cmd); return; }
}

// ── paleta ⌘K ───────────────────────────────────────────────────────────
const pal = {open: false, sel: 0, items: [], confirmCmd: null, confirmMut: null};
function navEntries(){
  const pfOnly = !!window.PF_ONLY;                     // portfolio.html: só a face Portfólio existe
  const tabs = pfOnly ? [["face/portfolio", "→ face Portfólio"],
    ["pf/visao", "Portfólio · Visão"], ["pf/opps", "Portfólio · Oportunidades"], ["pf/matrix", "Portfólio · Matriz"], ["pf/procs", "Portfólio · Processos"], ["pf/areas", "Portfólio · Áreas"]]
    : [["face/execucao", "→ face Execução"], ["face/portfolio", "→ face Portfólio"], ["face/configuracoes", "→ face Configurações"],
    ["home", "Início"], ["todo", "TODO"], ["projects", "Projetos"], ["decisions", "Decisões"], ["wins", "Conquistas"],
    ["people", "Pessoas"], ["timeline", "Linha do tempo"], ["focus", "Foco"], ["outbox", "Mensagens"], ["feedback", "Sugestões"],
    ["cfg/memoria", "Configurações · Memória"], ["cfg/saude", "Configurações · Saúde"],
    ["pf/visao", "Portfólio · Visão"], ["pf/opps", "Portfólio · Oportunidades"], ["pf/matrix", "Portfólio · Matriz"],
    ["pf/procs", "Portfólio · Processos"], ["pf/areas", "Portfólio · Áreas"]];
  return tabs.map(t => ({group: t[0].startsWith("face/") ? "faces" : "ir para", label: t[1], view: t[0]}));
}
function entEntries(){
  const out = [];
  D0.actions.filter(a => a.open).forEach(a => out.push({group: "ações abertas", label: a.title, ent: a.id, view: "action/" + a.id}));
  D0.decisions.slice(0, 8).forEach(d => out.push({group: "decisões", label: d.title, ent: d.id, view: "decision/" + d.id}));
  D0.projects.forEach(p => out.push({group: "projetos", label: p.id + " " + p.title, ent: p.id, view: "project/" + p.id}));
  D0.people.forEach(p => out.push({group: "pessoas", label: p.name, ent: p.id, view: "person/" + encodeURIComponent(p.id)}));
  return out;
}
function buildItems(q){
  const nq = norm(q);
  const free = /^brain\s/.test(q) ? [{group: "linha livre", label: "executar: " + q, cmd: q, mut: null}] : [];
  const helps = [{group: "ajuda", label: "Metodologia ICE (rubric de pontuação)", act: iceHelpOverlay}];
  const all = [...navEntries(), ...entEntries(), ...helps, ...commands().map(c => ({group: "comando", label: c.label, cmd: c.cmd, mut: c.mut || null, act: c.act || null}))];
  const f = nq ? all.filter(it => norm(it.label + " " + (it.ent || "") + " " + (it.cmd || "") + " " + it.group).includes(nq)) : all;
  return [...free, ...f.slice(0, 30)];
}
function renderPal(){
  const list = $("#pallist");
  if (!pal.items.length) { list.innerHTML = '<div class="pal-empty">nada encontrado — "não consta"</div>'; return; }
  let last = "", h = "";
  pal.items.forEach((it, i) => {
    if (it.group !== last) { h += '<div class="pal-group">' + esc(it.group) + "</div>"; last = it.group; }
    h += '<div class="pal-item' + (i === pal.sel ? " sel" : "") +  '" data-i="' + i + '">' +
      (it.ent ? '<span class="ent">' + esc(it.ent) + "</span>" : "") + "<span>" + esc(it.label) + "</span>" +
      (it.cmd ? '<span class="cmd">' + esc(it.cmd) + "</span>" : "") + "</div>";
  });
  list.innerHTML = h;
  list.querySelectorAll(".pal-item").forEach(el => {
    el.onmouseenter = () => { pal.sel = +el.dataset.i; renderPal(); };
    el.onclick = () => pick(+el.dataset.i);
  });
}
function pick(i){
  const it = pal.items[i]; if (!it) return;
  if (it.act) { closePal(); it.act(); return; }
  if (it.view) { closePal(); location.hash = it.view; return; }
  if (it.cmd) {
    pal.confirmCmd = it.cmd; pal.confirmMut = it.mut;
    $("#palcmd").textContent = "$ " + it.cmd;
    $("#palnote").textContent = LIVE
      ? "mesma linha que o TUI roda — gates e ledger valem igual"
      : "retrato: o comando é copiado para o terminal";
    $("#palrun").textContent = LIVE ? "executar" : "copiar";
    $("#palconfirm").classList.add("open");
  }
}
function openPal(){ pal.open = true; pal.sel = 0; $("#palback").classList.add("open");
  $("#palconfirm").classList.remove("open"); const q = $("#palq"); q.value = ""; q.focus(); pal.items = buildItems(""); renderPal(); }
function closePal(){ pal.open = false; $("#palback").classList.remove("open"); }
$("#palback").onclick = e => { if (e.target === $("#palback")) closePal(); };
$("#palcancel").onclick = closePal;
$("#palrun").onclick = () => { const c = pal.confirmCmd, m0 = pal.confirmMut; closePal(); runCommand(c, m0); };
$("#palq").addEventListener("input", e => { pal.sel = 0; pal.items = buildItems(e.target.value); renderPal(); });

// ── foco: reservar bloco (aprova + aplica o plano — as portas reais do CLI) ──
function focusMut(status){
  return m => {
    m.focus.status = status;
    if (status === "aprovado") m.focus.quote = "ok";
    if (status === "aplicado") { m.focus.applied = m.focus.blocks; m.focus.mode = "google"; }
  };
}
function focusReserve(){
  const f = window.BRAIN.M.focus;
  const ov = document.createElement("div"); ov.className = "pal-back open";
  ov.innerHTML = '<div class="palette"><div class="pin"><b>Reservar bloco de foco</b><span class="hint">' + esc(f.id) + "</span></div>" +
    '<div class="pal-confirm open" style="display:block;border-top:0;padding:14px 16px">' +
    '<div class="cline">$ brain focus approve ' + esc(f.id) + ' --quote "ok"</div>' +
    '<div class="cline">$ brain focus apply ' + esc(f.id) + " --mode google</div>" +
    '<p class="note-s" style="margin:0 0 10px">o CLI aprova e aplica o plano inteiro — evento brain_focus=1 no calendário. Reservar bloco-a-bloco seria extensão nova do CLI.</p>' +
    '<div class="row"><span class="note-s"></span><button class="btn ghost" data-x>cancelar</button><button class="btn primary" data-ok>reservar</button></div></div></div>';
  document.body.appendChild(ov);
  ov.querySelector("[data-x]").onclick = () => ov.remove();
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  ov.querySelector("[data-ok]").onclick = () => {
    ov.remove();
    if (!LIVE) { offlineCmd('brain focus approve ' + f.id + ' --quote "ok"'); return; }
    serveRun('brain focus approve ' + f.id + ' --quote "ok"').then(ok => {
      if (ok && window.BRAIN.M.focus && window.BRAIN.M.focus.status === "aprovado")
        serveRun("brain focus apply " + f.id + " --mode google");
    });
  };
}
function wireFocus(){
  const f = window.BRAIN.M.focus; if (!f) return;
  const head = document.querySelector("#view .pagehead");
  if (head && !head.querySelector(".planbtns")) {
    const row = document.createElement("div"); row.className = "planbtns";
    if (f.status === "proposto") row.innerHTML = '<button class="btn primary" data-c="approve">✓ aprovar plano</button>';
    if (f.status === "aprovado") row.innerHTML = '<button class="btn primary" data-c="apply">→ aplicar no calendário</button>';
    if (row.innerHTML) {
      head.appendChild(row);
      row.querySelectorAll("button").forEach(b => b.onclick = () => {
        if (b.dataset.c === "approve") {
          if (!LIVE) { offlineCmd('brain focus approve ' + f.id + ' --quote "ok"'); return; }
          runCommand('brain focus approve ' + f.id + ' --quote "ok"', focusMut("aprovado"));
        } else {
          if (!LIVE) { offlineCmd("brain focus apply " + f.id + " --mode google"); return; }
          runCommand("brain focus apply " + f.id + " --mode google", focusMut("aplicado"));
        }
      });
    }
  }
  document.querySelectorAll("#view .blk.prop").forEach(el => {
    el.classList.add("reservable");
    el.onclick = () => focusReserve();
  });
}


// ── perguntas e propostas (porta do dono: responder, descartar, aceitar, rejeitar) ──
function askAnswer(id, text){
  runCommand('brain ask answer ' + id + ' "' + text.replace(/"/g, "'") + '"',
    m => { const q = m.questions.find(x => x.id === id); if (q) { q.status = "respondida"; q.answer = text; } });
}
function propQuote(id, accept){
  formDialog({title: (accept ? "Aceitar " : "Rejeitar ") + id, gate: accept,
    sub: "o gate quer a sua resposta literal",
    fields: [{k: "quote", label: "Resposta literal", value: accept ? "ok" : "não"}],
    preview: v => v.quote ? "brain proposal " + (accept ? "accept" : "reject") + " " + id + ' --quote "' + v.quote.replace(/"/g, "'") + '"' : null,
    run: (v, m) => { m.proposals = m.proposals.filter(x => x.id !== id); }});
}
function wireAskPage(){
  document.querySelectorAll("#view [data-ask]").forEach(card => {
    const id = card.dataset.ask;
    card.querySelectorAll("[data-opt]").forEach(b => b.onclick = () => askAnswer(id, b.dataset.opt));
    const send = card.querySelector("[data-send]");
    if (send) send.onclick = () => { const inp = card.querySelector("[data-free]");
      if (inp && inp.value.trim()) askAnswer(id, inp.value.trim()); else inp && inp.focus(); };
    const drop = card.querySelector("[data-drop]");
    if (drop) drop.onclick = () => formDialog({title: "Descartar " + id, fields: [{k: "reason", label: "Motivo", value: ""}],
      preview: v => v.reason ? "brain ask drop " + id + ' --reason "' + v.reason.replace(/"/g, "'") + '"' : null,
      run: (v, m) => { const q = m.questions.find(x => x.id === id); if (q) q.status = "descartada"; }});
  });
  document.querySelectorAll("#view [data-acc], #view [data-rej]").forEach(b => {
    const card = b.closest(".card"); const idEl = card && card.querySelector(".idchip");
    if (!idEl) return;
    const id = idEl.textContent.trim(), accept = b.hasAttribute("data-acc");
    b.onclick = () => propQuote(id, accept);
  });
}

function peopleOpts(extra){ return (extra || [["", "—"]]).concat(window.BRAIN.M.people.map(x => [x.id, x.name])); }
function projectOpts(){ return [["", "—"]].concat(window.BRAIN.M.projects.map(x => [x.id, x.id + " " + x.title])); }
function goalOpts(){ return [["", "—"]].concat(window.BRAIN.M.goals.map(g => [g.id, g.id + " " + g.title])); }
function areaOpts(){ return window.BRAIN.M.portfolio.areas.map(a => [a.id, a.name]); }
function procOpts(){ return [["", "—"]].concat(window.BRAIN.M.portfolio.processes.map(x => [x.id, x.id + " " + x.title])); }
function q(t){ return '"' + String(t || "").replace(/"/g, "'") + '"'; }

// ── P0: entregável, progresso, rascunho, publicar, criar entidades ───────
function findDelivIn(m, id0){ for (const pr of m.projects) { const d = pr.deliverables.find(x => x.id === id0); if (d) return d; } return null; }
function mutDeliv(id0, st){ return m => { const d = findDelivIn(m, id0); if (d) { d.status = st; d.done_date = st === "feito" ? m.today : null; } }; }
function delivToggle(id0){
  const d = findDelivIn(window.BRAIN.M, id0); if (!d) return;
  const st = d.status === "feito" ? "nao-iniciado" : "feito";
  runCommand("brain plan deliverable " + id0 + " --status " + st, mutDeliv(id0, st));
}
function delivState(id0){
  formDialog({title: "Estado · " + id0, fields: [{k: "status", label: "Estado",
      options: [["nao-iniciado", "não iniciado"], ["em-andamento", "em andamento"], ["feito", "feito"], ["cancelado", "cancelado"]],
      value: findDelivIn(window.BRAIN.M, id0).status}],
    preview: v => "brain plan deliverable " + id0 + " --status " + v.status,
    run: (v, m) => mutDeliv(id0, v.status)(m)});
}
function progressForm(gid){
  formDialog({title: "Declarar progresso · " + gid, sub: "percentual seu, ao lado do cálculo por peso",
    fields: [{k: "pct", label: "%", type: "number", value: ""}, {k: "note", label: "Nota", value: ""}],
    preview: v => (v.pct !== "" && v.pct >= 0 && v.pct <= 100) ? "brain progress " + gid + " " + v.pct + (v.note ? ' --note "' + v.note.replace(/"/g, "'") + '"' : "") : null,
    run: (v, m) => { const g = m.goals.find(x => x.id === gid); if (g) g.declared = {pct: +v.pct, date: m.today, note: v.note}; }});
}

function draftForm(prefill){
  const pref = prefill || {};
  const people = window.BRAIN.M.people.filter(x => !x.is_owner);
  formDialog({title: "Rascunhar mensagem", sub: "nada sai sem aprovação do texto exato — porta 2",
    fields: [
      {k: "to", label: "Para", options: people.map(x => [x.id, x.name]), value: pref.to || (people[0] && people[0].id)},
      {k: "text", label: "Texto", value: pref.text || ""},
      {k: "ref", label: "Ref", value: pref.ref || "", ph: "TASK-####"},
      {k: "why", label: "Por quê", value: pref.why || ""},
      {k: "channel", label: "Canal", options: [["slack", "slack"], ["email", "email"]], value: "slack"}],
    preview: v => v.text ? "brain outbox draft --to " + v.to + " --text " + q(v.text) +
      (v.ref ? " --ref " + v.ref : "") + (v.why ? " --why " + q(v.why) : "") +
      (v.channel !== "slack" ? " --channel " + v.channel : "") : null,
    run: (v, m) => { const n = Math.max(0, ...m.outbox.map(x => +x.id.slice(4))) + 1;
      m.outbox.unshift({id: "MSG-" + String(n).padStart(4, "0"), to: v.to, to_name: (m.people.find(x => x.id === v.to) || {name: v.to}).name,
        text: v.text, status: "rascunho", ref: v.ref || null, why: v.why || null, drafted: m.today, sent: null, link: null}); }});
}
function chaseDraft(a){
  draftForm({to: a.owner, ref: a.id, why: "cobrança pelo painel",
    text: 'Oi! Atualização sobre "' + a.title + '"? ' + (a.due ? "Era pra " + a.due.slice(8, 10) + "/" + a.due.slice(5, 7) + ". " : "") + "Consegue me dar um status?"});
}
function closeForm(a){                                 // como a TUI: como foi + resultado (vira WIN)
  formDialog({title: "Fechar " + a.id, sub: a.title,
    fields: [{k: "how", label: "Como foi", value: "", ph: "enviei o draft, confirmação chegou"},
             {k: "outcome", label: "Resultado (vira entrega WIN)", value: "", ph: "opcional"}],
    preview: v => v.how ? "brain action close " + a.id + " --how " + q(v.how) +
      (v.outcome ? " --outcome " + q(v.outcome) : "") : null,
    run: (v, m) => { const x = m.actions.find(y => y.id === a.id); x.open = false; x.status = "fechada"; x.closed = m.today; }});
}
function reopenForm(a){
  formDialog({title: "Reabrir " + a.id, sub: a.title, fields: [{k: "reason", label: "Motivo", value: "", ph: "voltou ao radar"}],
    preview: v => v.reason ? "brain action reopen " + a.id + " --reason " + q(v.reason) : null,
    run: (v, m) => { const x = m.actions.find(y => y.id === a.id); x.open = true; x.status = "aberta"; x.closed = null; }});
}
function approveMsgForm(m0){                            // porta 2: texto exato + resposta literal, como a TUI
  const n = (m0.id.split("-")[1] || "0").replace(/^0+/, "") || "0";
  formDialog({title: "Aprovar " + m0.id + " → " + (m0.to_name || m0.to || "?"), gate: true,
    sub: q(m0.text) + " — você aprova este texto exato; se mudar uma palavra, a aprovação cai.",
    fields: [{k: "quote", label: "Sua aprovação", value: "", ph: "enviar " + n}],
    preview: v => v.quote ? "brain outbox approve " + m0.id + " --quote " + q(v.quote) : null,
    run: (v, m) => { m.outbox.find(x => x.id === m0.id).status = "aprovada"; }});
}
function cancelMsgForm(m0){
  formDialog({title: "Cancelar " + m0.id, sub: m0.text, fields: [{k: "reason", label: "Motivo", value: "", ph: "opcional"}],
    preview: v => "brain outbox cancel " + m0.id + (v.reason ? " --reason " + q(v.reason) : ""),
    run: (v, m) => { m.outbox.find(x => x.id === m0.id).status = "cancelada"; }});
}
function feedbackForm(){
  formDialog({title: "Sugestão ou bug", sub: "porta 7 — vira issue pública no repo do framework · sem dados pessoais",
    fields: [
      {k: "kind", label: "Tipo", options: [["sugestao", "💡 sugestão"], ["bug", "🐞 bug"]], value: "sugestao"},
      {k: "title", label: "Título", value: "", ph: "curto e claro"},
      {k: "body", label: "Descrição", value: "", ta: true, rows: 5, ph: "o que, onde, como reproduzir"},
      {k: "pub", label: "Publicar", options: [["agora", "agora — cria a issue já"], ["depois", "depois — só registra (p publica)"]], value: "agora"},
      {k: "force", label: "Título repetido — criar mesmo assim", options: [["nao", "não"], ["sim", "sim (--force)"]], value: "nao"}],
    note: v => { const f = (window.BRAIN.M.feedback || []).find(x => x.kind === v.kind &&
        x.title.trim().toLowerCase() === v.title.trim().toLowerCase());
      return (f && v.force !== "sim") ? "⚠ mesmo título e tipo de " + f.id + " — acrescente detalhe ao existente ou marque “criar mesmo assim”" : ""; },
    preview: v => v.title ? "brain feedback add " + q(v.title) + " --kind " + v.kind +
      (v.body ? " --body " + q(v.body) : "") +
      (v.pub === "depois" ? " --no-push" : "") + (v.force === "sim" ? " --force" : "") + " --by owner" : null,
    run: (v, m) => { const n = Math.max(0, ...(m.feedback || []).map(x => +x.id.slice(3))) + 1;
      (m.feedback = m.feedback || []).unshift({id: "FB-" + String(n).padStart(4, "0"), kind: v.kind,
        title: v.title, body: v.body || null,
        status: "pendente", number: null, url: null, error: null, added: m.today}); }});
}
function pubAction(act, id0){
  if (act === "cancel") { formDialog({title: "Cancelar " + id0, fields: [{k: "reason", label: "Motivo", value: ""}],
    preview: () => "brain publish cancel " + id0,
    run: (v, m) => { const x = m.publishes.find(y => y.id === id0); if (x) x.status = "cancelada"; }}); return; }
  if (act === "approve") { formDialog({title: "Aprovar " + id0, gate: true, sub: "porta 3 — resposta literal",
    fields: [{k: "quote", label: "Resposta literal", value: "ok"}],
    preview: v => "brain publish approve " + id0 + ' --quote "' + (v.quote || "").replace(/"/g, "'") + '"',
    run: (v, m) => { const x = m.publishes.find(y => y.id === id0); if (x) x.status = "aprovada"; }}); return; }
  if (act === "done") { toast("(agente) publicar é porta do agente — publish done " + id0 + " registra o link ao postar"); return; }
}
function pubRequestForm(){
  const M = window.BRAIN.M;
  formDialog({title: "Pedir publicação", sub: "o export sai de brain share; a publicação é a porta 3",
    fields: [
      {k: "report", label: "Relatório (caminho do share)", value: "reports/share/", ph: "reports/share/…html"},
      {k: "to", label: "Destino", value: "", ph: "slack:#seu-canal"}],
    preview: v => (v.report.length > 14 && v.to) ? "brain publish request " + v.report + " --to " + v.to
      : "brain share status   # 1º exporta · depois: publish request <caminho> --to <destino>",
    run: (v, m) => { const n = Math.max(0, ...(m.publishes || []).map(x => +x.id.slice(4))) + 1;
      (m.publishes = m.publishes || []).unshift({id: "PUB-" + String(n).padStart(4, "0"),
        title: v.title || v.report, to: v.to, status: "solicitada", date: m.today, link: null}); }});
}
function nbForm(kind){
  const M = window.BRAIN.M;
  if (kind === "note") return noteForm();
  if (kind === "newaction") return newAction();
  if (kind === "planform") return planForm();
  if (kind === "outbox") return draftForm();
  if (kind === "feedback") return feedbackForm();
  if (kind === "pub") return pubRequestForm();
  if (kind === "decision") return formDialog({title: "Nova decisão", fields: [
      {k: "title", label: "Decisão", ph: "o que passa a valer"},
      {k: "by", label: "Quem decidiu", value: M.owner.id, ph: "ids por vírgula"},
      {k: "project", label: "Projeto", options: projectOpts()},
      {k: "context", label: "Contexto", ph: "com base em quê"},
      {k: "rationale", label: "Por quê", value: ""}],
    preview: v => v.title ? 'brain decision add "' + v.title.replace(/"/g, "'") + '" --decided-by ' + v.by.split(",").map(x => x.trim()).join(" --decided-by ") +
      (v.project ? " --project " + v.project : "") + (v.context ? " --context " + q(v.context) : "") +
      (v.rationale ? " --rationale " + q(v.rationale) : "") : null,
    run: (v, m) => { const n = Math.max(...m.decisions.map(x => +x.id.slice(4))) + 1;
      m.decisions.unshift({id: "DEC-" + String(n).padStart(4, "0"), title: v.title, date: m.today,
        decided_by: String(v.by || m.owner.id).split(",").map(x => x.trim()),
        decided_by_names: String(v.by || m.owner.id).split(",").map(x => (m.people.find(y => y.id === x.trim()) || {name: x}).name),
        project: v.project || null, context: null, rationale: v.rationale || null, status: "ativa",
        supersedes: null, superseded_by: null, source_label: "declarado no painel", prov: "declarado"}); }});
  if (kind === "delivery") return formDialog({title: "Nova entrega", fields: [
      {k: "title", label: "Título", ph: "o que saiu"},
      {k: "ref", label: "Ref", value: "", ph: "TASK/PROJ/GOAL"},
      {k: "result", label: "Resultado", value: ""},
      {k: "impact", label: "Impacto", value: ""}],
    preview: v => v.title ? 'brain delivery "' + v.title.replace(/"/g, "'") + '"' + (v.ref ? " --ref " + v.ref : "") +
      (v.result ? ' --result "' + v.result.replace(/"/g, "'") + '"' : "") + (v.impact ? ' --impact "' + v.impact.replace(/"/g, "'") + '"' : "") : null,
    run: (v, m) => { m.deliveries.unshift({id: "W" + Date.now(), title: v.title, date: m.today, ref: v.ref || null,
      project: v.ref && v.ref.startsWith("PROJ") ? v.ref : null, result: v.result || "resultado não declarado",
      impact: v.impact || null, prov: "declarado", source_label: "declarado no painel"}); }});
  if (kind === "person") return formDialog({title: "Nova pessoa", fields: [
      {k: "name", label: "Nome", ph: "Nome Sobrenome"},
      {k: "role", label: "Papel", value: ""},
      {k: "relation", label: "Relação", value: ""},
      {k: "email", label: "E-mail", value: ""},
      {k: "alias", label: "Alias", value: "", ph: "apelido"}],
    preview: v => v.name ? "brain person add " + q(v.name) + " --role " + q(v.role || "—") + " --relation " + q(v.relation || "—") +
      (v.email ? " --email " + q(v.email) : "") + (v.alias ? " --alias " + v.alias : "") : null,
    run: (v, m) => { const id0 = norm(v.name).replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "");
      m.people.push({id: id0, name: v.name, aliases: v.alias ? [v.alias] : [], role: v.role || null, relation: v.relation || null,
        email: null, is_owner: false, last_interaction: null, owes_me: [], i_owe: [], decisions: [], artifacts: [], projects: [], mentions: 0}); }});
  if (kind === "process") return formDialog({title: "Novo processo", fields: [
      {k: "title", label: "Título", ph: "o processo"},
      {k: "area", label: "Área", options: areaOpts()},
      {k: "owner", label: "Responsável", options: peopleOpts()},
      {k: "executors", label: "Executores", ph: "ids por vírgula"},
      {k: "recurrence", label: "Recorrência", options: [["diaria", "diária"], ["semanal", "semanal"], ["mensal", "mensal"], ["trimestral", "trimestral"]]},
      {k: "perMonth", label: "Execuções/mês", type: "number"},
      {k: "duration", label: "Duração", ph: "90m · 2h"},
      {k: "maturity", label: "Maturidade (1-5)", options: [["", "—"], ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"], ["5", "5"]]},
      {k: "tools", label: "Ferramentas", ph: "por vírgula"},
      {k: "io", label: "Entrada → saída"},
      {k: "pains", label: "Dores", ph: "por vírgula"},
      {k: "note", label: "Nota"}],
    preview: v => {
      if (!v.title) return null;
      let c = "brain process add " + q(v.title) + " --area " + v.area + " --owner " + v.owner;
      if (v.recurrence) c += " --recurrence " + v.recurrence;
      if (v.executors) c += " --executor " + v.executors.replace(/\s/g, "");
      if (v.perMonth) c += " --per-month " + v.perMonth;
      if (v.duration) c += " --duration " + v.duration;
      if (v.maturity) c += " --maturity " + v.maturity;
      if (v.tools) c += " --tools " + q(v.tools);
      if (v.io) c += " --io " + q(v.io);
      if (v.pains) c += " --pain " + q(v.pains);
      if (v.note) c += " --note " + q(v.note);
      return c;
    },
    run: (v, m) => { const n = Math.max(0, ...m.portfolio.processes.map(x => +x.id.slice(5))) + 1;
      m.portfolio.processes.push({id: "PROC-" + String(n).padStart(4, "0"), title: v.title, area: v.area,
        owner: v.owner, owner_name: (m.people.find(x => x.id === v.owner) || {name: v.owner}).name, executors: [],
        recurrence: v.recurrence, hours_month: null, tools: [], io: null, pains: [], maturity: null,
        status: "ativo", opportunities: [], gaps: [], docs: []}); }});
  if (kind === "area") return formDialog({title: "Nova área", fields: [
      {k: "slug", label: "Slug", ph: "producao"},
      {k: "name", label: "Nome", ph: "Produção"},
      {k: "alias", label: "Também chamada", ph: "Cozinha"},
      {k: "note", label: "Nota"}],
    preview: v => (v.slug && v.name) ? "brain area add " + v.slug + " --name " + q(v.name) +
      (v.alias ? " --alias " + q(v.alias) : "") + (v.note ? " --note " + q(v.note) : "") : null,
    run: (v, m) => { m.portfolio.areas.push({id: v.slug, name: v.name, aliases: [], note: null}); }});
}
function wireP0(){
  document.querySelectorAll("#view [data-deliv] .dmark").forEach(b => b.onclick = () => delivToggle(b.closest("li").dataset.deliv));
  document.querySelectorAll("#view [data-progress]").forEach(b => b.onclick = () => progressForm(b.dataset.progress));
  document.querySelectorAll("#view [data-pub]").forEach(b => { const parts = b.dataset.pub.split(":"); b.onclick = () => pubAction(parts[0], parts[1]); });
  document.querySelectorAll("#view [data-fb]").forEach(b => { const id0 = b.dataset.fb; b.onclick = () => {
    runCommand("brain feedback push " + id0); }});
  document.querySelectorAll("#view [data-fbsync]").forEach(b => { b.onclick = () => {
    runCommand("brain feedback sync"); }});
  const head = document.querySelector("#view .pagehead");
  if (head && !head.querySelector(".planbtns")) {
    const map = {"#home": ["note", "n nota"], "#projects": ["planform", "n estrutura"], "#todo": ["newaction", "n nova ação"],
      "#outbox": ["outbox", "n rascunhar"], "#decisions": ["decision", "n nova decisão"],
      "#feedback": ["feedback", "n sugerir/corrigir"],
      "#wins": ["delivery", "n nova entrega"], "#people": ["person", "n nova pessoa"],
      "#pf/procs": ["process", "n novo processo"], "#pf/areas": ["area", "n nova área"], "#ask": ["pub", "n pedir publicação"]};
    const spec = map[location.hash.split("?")[0]];
    if (spec) { const row = document.createElement("div"); row.className = "planbtns";
      const btn = document.createElement("button"); btn.className = "btn"; btn.textContent = spec[1];
      btn.onclick = () => nbForm(spec[0]); row.appendChild(btn); head.appendChild(row); }
  }
  // ficha de ação: mesclar duplicada + editar/fechar/reabrir por clique (fora do if do planbtns:
  // a ficha de ação tem pagehead próprio e nunca ganha planbtns — mas não pode depender disso)
  document.querySelectorAll('#view [data-act]').forEach(b => {
    const a0 = window.BRAIN.A[b.dataset.id]; if (!a0) return;
    b.onclick = () => {
      if (b.dataset.act === "merge") return mergeForm(a0);
      if (b.dataset.act === "edit") return editAction(a0);
      if (b.dataset.act === "close") return closeForm(a0);
      if (b.dataset.act === "reopen") return reopenForm(a0);
    };
  });
}

// ── nota, estrutura do plano, mesclar ação ───────────────────────────────
function noteForm(){
  const M = window.BRAIN.M;
  const links = [["", "— sem vínculo —"],
    ...M.actions.filter(a => a.open).slice(0, 30).map(a => [a.id, a.id + " " + a.title]),
    ...M.goals.map(g => [g.id, g.id + " " + g.title]),
    ...M.projects.map(x => [x.id, x.id + " " + x.title])];
  formDialog({title: "Nota rápida", sub: "vai para a inbox — o /dump arquiva e vincula",
    fields: [{k: "text", label: "Texto", value: "", ta: true, rows: 5},
      {k: "link", label: "Vínculo", options: links}],
    preview: v => v.text ? "brain note add --text \"" + v.text.replace(/"/g, "'") + "\"" +
      (v.link ? " --link " + v.link : "") : null,
    run: (v, m) => { toast(LIVE ? "nota na inbox — o /dump arquiva" : "retrato — comando copiado"); }});
}
function planForm(){
  const M = window.BRAIN.M;
  formDialog({title: "Estrutura do plano", sub: "goal e projeto são gate estrutural (aprovação literal); entregável não",
    fields: [
      {k: "kind", label: "Criar", options: [["goal", "goal"], ["projeto", "projeto"], ["deliverable", "entregável"]]},
      {k: "title", label: "Título", value: ""},
      {k: "goal", label: "Goal (projeto/entregável)", options: M.goals.map(g => [g.id, g.id + " — " + g.title])},
      {k: "project", label: "Projeto (entregável)", options: M.projects.map(x => [x.id, x.id + " — " + x.title])},
      {k: "owner", label: "Dono (projeto)", options: M.people.map(x => [x.id, x.name])},
      {k: "horizon", label: "Horizonte (goal)", value: "", ph: "AAAA-MM-DD"},
      {k: "why", label: "Por quê (goal)", value: ""},
      {k: "due", label: "Prazo (entregável)", value: "", ph: "AAAA-MM-DD"},
      {k: "weight", label: "Peso (entregável)", type: "number", value: "1"},
      {k: "approval", label: "Aprovação literal", value: "ok"}],
    preview: v => {
      if (!v.title) return null;
      const q = t => '"' + t.replace(/"/g, "'") + '"';
      if (v.kind === "goal") return 'brain plan add-goal ' + q(v.title) +
        (v.horizon ? " --horizon " + v.horizon : "") + (v.why ? " --why " + q(v.why) : "") +
        ' --approval "' + (v.approval || "").replace(/"/g, "'") + '"';
      if (v.kind === "projeto") return 'brain plan add-project ' + v.goal + " " + q(v.title) +
        (v.owner ? " --owner " + v.owner : "") + ' --approval "' + (v.approval || "").replace(/"/g, "'") + '"';
      return 'brain plan add-deliverable ' + v.project + " " + q(v.title) +
        (v.due ? " --due " + v.due : "") + (v.weight ? " --weight " + v.weight : "");
    },
    run: (v, m) => {}});
}
function mergeForm(a){
  formDialog({title: "Mesclar " + a.id, sub: '"' + a.title + '" é duplicada — o que ela tem passa para a que fica',
    fields: [{k: "into", label: "Mesclar em (TASK)", value: "", ph: "TASK-####"},
      {k: "reason", label: "Motivo", value: ""}],
    preview: v => v.into ? "brain action merge " + a.id + " --into " + v.into +
      (v.reason ? ' --reason "' + v.reason.replace(/"/g, "'") + '"' : "") : null,
    run: (v, m) => {}});
}

// ── kanban de oportunidades: arrastar = brain opportunity status (laterais pedem motivo) ──
const OPP_LAT = ["em-espera", "descartada"];
function oppMut(id, stage, reason){
  return m => {
    const x = m.portfolio.opportunities.find(y => y.id === id);
    x.status_history.unshift({date: m.today, from: x.status, to: stage, reason: reason || null});
    x.status = stage;
  };
}
function oppReasonDialog(id, stage){
  const ov = document.createElement("div"); ov.className = "pal-back open";
  ov.innerHTML = '<div class="palette"><div class="pin"><b>' + esc(id) + " → " + esc(stage) + '</b><span class="hint">lateral</span></div>' +
    '<div class="pal-confirm open" style="display:block;border-top:0;padding:14px 16px">' +
    '<p class="note-s" style="margin:0 0 8px">Estágio lateral exige motivo (fica no histórico do ledger):</p>' +
    '<input class="rin" id="rin" value="" placeholder="por quê? (fica no histórico do ledger)" spellcheck="false">' +
    '<div class="cline" id="rin-cmd"></div>' +
    '<div class="row"><span class="note-s"></span><button class="btn ghost" data-x>cancelar</button><button class="btn primary" data-ok>mover</button></div></div></div>';
  document.body.appendChild(ov);
  const cmdOf = r => "$ brain opportunity status " + id + " " + stage + ' --reason "' + r.replace(/"/g, "'") + '"';
  ov.querySelector("#rin-cmd").textContent = cmdOf(ov.querySelector("#rin").value);
  ov.querySelector("#rin").addEventListener("input", e => { ov.querySelector("#rin-cmd").textContent = cmdOf(e.target.value); });
  ov.querySelector("[data-x]").onclick = () => ov.remove();
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  ov.querySelector("[data-ok]").onclick = () => {
    const reason = ov.querySelector("#rin").value.trim();
    if (!reason) { toast("estágio lateral exige motivo — o CLI recusa sem --reason"); return; }
    const cmd = "brain opportunity status " + id + " " + stage + ' --reason "' + reason.replace(/"/g, "'") + '"';
    ov.remove();
    runCommand(cmd, oppMut(id, stage, reason));
  };
}
function wireOppKanban(){
  let dragOpp = null;
  document.querySelectorAll("#view .pf-card").forEach(el => {
    el.addEventListener("dragstart", e => {
      dragOpp = el.dataset.opp;
      e.dataTransfer.setData("text/plain", dragOpp); e.dataTransfer.effectAllowed = "move";
      setTimeout(() => el.classList.add("dragging"), 0);
    });
    el.addEventListener("dragend", () => { el.classList.remove("dragging"); dragOpp = null;
      document.querySelectorAll(".pf-col.drop-hint").forEach(c => c.classList.remove("drop-hint")); });
  });
  document.querySelectorAll("#view .pf-col[data-stage]").forEach(col => {
    col.addEventListener("dragover", e => {
      if (!dragOpp) return;
      e.preventDefault(); e.dataTransfer.dropEffect = "move"; col.classList.add("drop-hint");
    });
    col.addEventListener("dragleave", () => col.classList.remove("drop-hint"));
    col.addEventListener("drop", e => {
      e.preventDefault(); col.classList.remove("drop-hint");
      const id = dragOpp || e.dataTransfer.getData("text/plain"); dragOpp = null;
      const stage = col.dataset.stage;
      const o = window.BRAIN.M.portfolio.opportunities.find(x => x.id === id);
      if (!o || o.status === stage) return;
      if (OPP_LAT.includes(stage)) { oppReasonDialog(id, stage); return; }
      runCommand("brain opportunity status " + id + " " + stage, oppMut(id, stage));
    });
  });
}

// ── kanban: botões rápidos + arrastar e soltar (ponte CLI) ──────────────
function colOf(a){ if (!a.open) return "fechada"; return (a.status === "bloqueada" || a.status === "aguardando") ? "aguardando" : a.status; }
function dropPlan(a, target){                    // → {cmd, mut, dialog?, deny?}
  const from = colOf(a);
  if (from === target) return null;
  if (target === "fechada")
    return {dialog: () => closeForm(a)};          // como foi + resultado opcional (WIN)
  if (!a.open)
    return {dialog: () => reopenForm(a)};         // motivo, como a TUI pede
  if (a.blocked_by.length && target !== "aguardando")
    return {deny: a.id + " segue bloqueada por " + a.blocked_by.join(", ") + " — resolva o bloqueio para movê-la"};
  return {cmd: "brain action update " + a.id + " --status " + (target === "aguardando" ? "aguardando" : target),
    mut: m => { m.actions.find(y => y.id === a.id).status = target === "aguardando" ? "aguardando" : target; }};
}
let dragId = null, lastMoved = null;

// ── face Configurações: troca de provedor da memória (mesma linha do CLI; sem campos condicionais:
//    um select por slot, "manter" nos que não mudam — o preview monta só a linha do slot escolhido) ──
function wireCfgMemoria(){
  const b = document.querySelector("[data-provform]");
  if (b) b.onclick = () => formDialog(provFormSpec());
  document.querySelectorAll("#view [data-hw]").forEach(btn => {
    btn.onclick = () => runCommand("brain memory harness install " + btn.dataset.hw, m => {
      const x = (m.harnesses || []).find(y => y.name === btn.dataset.hw);
      if (x) x.wired = true;                       // otimista: o refresh da ponta confirma
    });
  });
  const v = document.querySelector("[data-hwverify]");
  if (v) v.onclick = () => runCommand("brain memory harness verify", () => {});
}

function provFormSpec(){
  return {
    title: "Trocar provedor da memória",
    sub: "A escolha vai ao config/.env (chave nunca volta em output) e ao [memory]. Recrie o container depois para aplicar.",
    fields: [
      {k: "llm", label: "LLM (só modo full)", options: [["", "manter"], ["anthropic", "Anthropic (Haiku/Sonnet cenário B)"],
        ["openai", "OpenAI"], ["fireworks", "Fireworks"], ["zai", "Z.ai (GLM)"], ["lmstudio", "LM Studio (local)"], ["custom", "custom"]], value: ""},
      {k: "embeddings", label: "Embeddings", options: [["", "manter"], ["local", "Local — LM Studio bge-m3 (zero egress)"],
        ["fireworks", "Fireworks — Qwen3-Embedding-8B"], ["openai", "OpenAI"], ["cohere", "Cohere"], ["custom", "custom"]], value: ""},
      {k: "reranker", label: "Reranker", options: [["", "manter"], ["off", "off — fusão RRF (recomendado)"],
        ["fireworks", "Fireworks — Qwen3-Reranker-8B"], ["cohere", "Cohere"], ["zeroentropy", "ZeroEntropy"],
        ["openrouter", "OpenRouter"], ["custom", "custom"]], value: ""},
      {k: "model", label: "modelo", ph: "vazio = recomendado do provedor"},
      {k: "base_url", label: "base URL", ph: "custom / openai-wire"},
      {k: "key", label: "API key", type: "password", ph: "vazio = mantém a do config/.env"},
      {k: "models", label: "modelos por operação (LLM)", ph: "retain=…,consolidation=… (vazio = recomendados)"},
      {k: "candidates", label: "top-N candidatos (reranker)", ph: "vazio = default do provedor"}
    ],
    preview(v){
      const slot = ["llm", "embeddings", "reranker"].find(s => v[s]);
      if (!slot) return null;
      let c = "brain memory providers set " + slot + " --provider " + v[slot];
      if (v.model) c += " --model " + v.model;
      if (v.base_url) c += " --base-url " + v.base_url;
      if (v.key) c += " --key " + v.key;
      if (slot === "llm" && v.models) c += " --models " + v.models;
      if (slot === "reranker" && v.candidates) c += " --candidates " + v.candidates;
      return c;
    },
    note(v){
      const slot = ["llm", "embeddings", "reranker"].find(s => v[s]);
      if (slot && v[slot] !== "local" && v[slot] !== "off") return "☁ nuvem: texto do vault vai à API do provedor (mesmo gate de egress do plano).";
      if (slot === "embeddings") return "trocar embeddings pede o rebuild da memória: vetores antigos ficam incompatíveis.";
      return "";
    },
    run: () => {}
  };
}

window.afterRoute = function(view){
  if (location.hash.startsWith("#focus")) wireFocus();
  if (location.hash.startsWith("#pf/opps")) wireOppKanban();
  if (location.hash.startsWith("#ask")) wireAskPage();
  if (location.hash.startsWith("#cfg/memoria")) wireCfgMemoria();
  wireP0();
  collectSel();
  document.querySelectorAll("#view .card").forEach(el => {
    if (el.querySelector(".qa")) return;
    const idEl = el.querySelector(".idchip"); if (!idEl) return;
    const id = idEl.textContent.trim();
    const a = (window.BRAIN ? window.BRAIN.M : D0).actions.find(x => x.id === id); if (!a) return;
    if (a.open) {
      el.setAttribute("draggable", "true");
      el.addEventListener("dragstart", e => {
        dragId = id; lastMoved = null;
        e.dataTransfer.setData("text/plain", id); e.dataTransfer.effectAllowed = "move";
        setTimeout(() => el.classList.add("dragging"), 0);
      });
      el.addEventListener("dragend", () => { el.classList.remove("dragging"); dragId = null;
        document.querySelectorAll(".col.drop-hint").forEach(c => c.classList.remove("drop-hint")); });
    }
    const qa = document.createElement("div"); qa.className = "qa";
    if (a.open && a.status === "aberta") qa.innerHTML = '<button class="btn" data-c="fazendo">▶ fazendo</button>';
    if (a.open) qa.innerHTML += '<button class="btn" data-c="fechar">✓ fechar</button>';
    if (qa.innerHTML) el.appendChild(qa);
    qa.querySelectorAll("button").forEach(b => b.onclick = ev => {
      ev.preventDefault(); ev.stopPropagation();
      if (b.dataset.c === "fechar")
        runCommand('brain action close ' + id + ' --how "feito pelo painel"', m => {
          const x = m.actions.find(y => y.id === id); x.open = false; x.status = "fechada"; x.closed = m.today; lastMoved = id; });
      else
        runCommand("brain action update " + id + " --status fazendo", m => { m.actions.find(x => x.id === id).status = "fazendo"; lastMoved = id; });
    });
  });
  // zonas de solta: as colunas do kanban
  document.querySelectorAll("#view .kanban .col").forEach(col => {
    col.addEventListener("dragover", e => {
      if (!dragId) return;
      e.preventDefault(); e.dataTransfer.dropEffect = "move";
      col.classList.add("drop-hint");
    });
    col.addEventListener("dragleave", () => col.classList.remove("drop-hint"));
    col.addEventListener("drop", e => {
      e.preventDefault(); col.classList.remove("drop-hint");
      const id = dragId || e.dataTransfer.getData("text/plain"); dragId = null;
      const a = window.BRAIN.M.actions.find(x => x.id === id); if (!a) return;
      const plan = dropPlan(a, col.dataset.col); if (!plan) return;
      if (plan.deny) { toast(plan.deny); return; }
      lastMoved = id;
      if (plan.dialog) { plan.dialog(); return; }         // fechar/reabrir pedem os campos, como a TUI
      runCommand(plan.cmd, plan.mut);
    });
  });
  // flash do cartão que acabou de se mover (o "live" do arrasto)
  if (lastMoved) {
    const el = [...document.querySelectorAll("#view .card")].find(c => {
      const i = c.querySelector(".idchip"); return i && i.textContent.trim() === lastMoved; });
    if (el) { el.classList.add("just-moved"); setTimeout(() => el.classList.remove("just-moved"), 1200); }
    lastMoved = null;
  }
};

// ── teclado: mesmas teclas da TUI, nos mesmos contextos ─────────────────
// hardening do botão ⌘K (mouse e teclado) + burger (janela estreita)
$("#openpal").addEventListener("click", () => openPal());
const burger = $("#burger");
if (burger) burger.onclick = () => { burger.classList.toggle("open"); $("#side").classList.toggle("open"); };

const SEL = {items: [], i: -1};
function collectSel(){
  SEL.items = [...document.querySelectorAll(
    "#view .kanban .card, #view .pf-kanban .pf-card, #view table tbody tr, #view .blk.prop, #view .msgrow, #view ul.feed li, #view li[data-deliv]"
  )].filter(el => el.querySelector('a[href^="#"]') || el.classList.contains("blk") || el.classList.contains("pf-card") || el.hasAttribute("data-deliv"));
  SEL.i = -1; paintSel();
  SEL.items.forEach(el => el.addEventListener("mouseenter", () => { const n = SEL.items.indexOf(el); if (n >= 0) { SEL.i = n; paintSel(); } }));
}
function paintSel(){ SEL.items.forEach((el, i) => el.classList.toggle("kbd-sel", i === SEL.i)); if (typeof renderKeyBar === "function") renderKeyBar(); }
function selEl(){ return SEL.items[SEL.i] || null; }
function selMove(d){ if (!SEL.items.length) return; SEL.i = (SEL.i + d + SEL.items.length) % SEL.items.length; paintSel(); selEl().scrollIntoView({block: "nearest"}); }
function selOpen(){
  const el = selEl(); if (!el) return;
  if (el.classList.contains("blk")) { el.click(); return; }
  const a = el.querySelector('a[href^="#"]'); if (a) location.hash = a.getAttribute("href");
}
function selId(){
  const el = selEl(); if (!el) return null;
  if (el.dataset.opp) return el.dataset.opp;
  const i = el.querySelector(".idchip");
  return i ? i.textContent.trim() : null;
}
function navStep(dir){
  const links = [...document.querySelectorAll("#tabs a")];
  if (!links.length) return;
  let on = links.findIndex(a => a.classList.contains("on"));
  if (on < 0) on = 0;
  const next = links[(on + dir + links.length) % links.length];
  location.hash = next.getAttribute("href").slice(1);
}

// ── genérico: dialog de formulário → linha brain … (preview vivo) ───────
let dlgOpen = false;
function formDialog(o){          // {title, sub, fields[{k,label,type,value,options,note(v)}], gate, note(v), help()→html, preview(v)→cmd, run(cmd,v)}
  const ov = document.createElement("div"); ov.className = "pal-back open";
  const f = o.fields.map(x => '<div class="frow"><label>' + esc(x.label) + "</label>" +
    (x.options ? '<select data-k="' + x.k + '">' + x.options.map(op => '<option value="' + esc(op[0]) + '"' + (op[0] === x.value ? " selected" : "") + ">" + esc(op[1] || op[0]) + "</option>").join("") + "</select>"
      : x.ta ? '<textarea data-k="' + x.k + '" rows="' + (x.rows || 4) + '"' + (x.ph ? ' placeholder="' + esc(x.ph) + '"' : "") + ">" + esc(x.value ?? "") + "</textarea>"
      : '<input data-k="' + x.k + '" type="' + (x.type || "text") + '" value="' + esc(x.value ?? "") + '"' + (x.ph ? ' placeholder="' + esc(x.ph) + '"' : "") + ">") + "</div>" +
      (x.note ? '<div class="note-s fhint" data-hint="' + esc(x.k) + '" style="margin:-4px 0 8px 130px"></div>' : "")).join("");
  ov.innerHTML = '<div class="palette"><div class="pin"><b>' + esc(o.title) + "</b>" + (o.gate ? ' <span class="gatebadge">gate — precisa do seu ok literal</span>' : "") + '</div>' +
    '<div class="pal-confirm open" style="display:block;border-top:0;padding:14px 16px;max-height:70vh;overflow:auto">' +
    (o.sub ? '<p class="note-s" style="margin:0 0 10px">' + esc(o.sub) + "</p>" : "") + f +
    '<div class="note-s" data-note style="margin:0 0 6px;white-space:pre-line"></div>' +
    '<div class="cline" data-preview style="min-height:34px"></div>' +
    '<div class="row"><span class="note-s">mesma linha que a TUI roda</span>' +
    (o.help ? '<button class="btn ghost" data-help> ? orientações</button>' : "") +
    '<button class="btn ghost" data-x>cancelar</button><button class="btn primary" data-ok>' + (o.gate ? "aprovar (ok)" : "executar") + "</button></div></div></div>";
  document.body.appendChild(ov); dlgOpen = true;
  const close = () => { ov.remove(); dlgOpen = false; if (h2) document.removeEventListener("keydown", h2, true); };
  const vals = () => { const v = {}; ov.querySelectorAll("[data-k]").forEach(el => v[el.dataset.k] = el.value); return v; };
  const paint = () => { const p = ov.querySelector("[data-preview]"); const c = o.preview(vals()); p.textContent = c ? "$ " + c : "$ (preencha os campos)";
    const n = ov.querySelector("[data-note]"); if (n) n.textContent = o.note ? (o.note(vals()) || "") : "";
    ov.querySelectorAll("[data-hint]").forEach(el => { const x = o.fields.find(y => y.k === el.dataset.hint);
      el.textContent = x && x.note ? (x.note(vals()[x.k]) || "") : ""; }); };
  ov.querySelectorAll("[data-k]").forEach(el => el.addEventListener("input", paint));
  ov.querySelectorAll("select[data-k]").forEach(el => el.addEventListener("change", paint));
  paint();
  // ? abre as orientações (o.help) mesmo com o foco num select — antes do handler global, que ignora teclas com dialog aberto
  let h2 = null;
  if (o.help) {
    h2 = ev => { if (ev.key !== "?" || document.querySelector(".help-stack")) return;
      ev.preventDefault(); ev.stopPropagation(); stackHelp("Metodologia · ICE", o.help()); };
    document.addEventListener("keydown", h2, true);
    ov.querySelector("[data-help]").onclick = () => stackHelp("Metodologia · ICE", o.help());
  }
  ov.querySelector("[data-x]").onclick = close;
  ov.onclick = e => { if (e.target === ov) close(); };
  ov.querySelector("[data-ok]").onclick = () => {
    const v = vals(), cmd = o.preview(v);
    if (!cmd) { ov.querySelector("[data-preview]").classList.add("miss"); setTimeout(() => ov.querySelector("[data-preview]").classList.remove("miss"), 600); return; }
    close();
    runCommand(cmd, m => o.run && o.run(v, m));   // runCommand aplica ownerCmd (--by owner) nos dois modos
  };
  const first = ov.querySelector("input,select,textarea"); if (first) first.focus();
}
// overlay de orientações empilhável por cima do formulário aberto: Esc/? fecham SÓ a ajuda (capture, antes do global)
function stackHelp(title, html){
  const ov = document.createElement("div"); ov.className = "pal-back open help-stack";
  ov.innerHTML = '<div class="palette"><div class="pin"><b>' + esc(title) + '</b><span class="hint">? fecha</span></div>' +
    '<div class="pal-scroll">' + html + "</div></div>";
  document.body.appendChild(ov);
  const close = () => { ov.remove(); document.removeEventListener("keydown", h, true); };
  const h = ev => { if (ev.key === "Escape" || ev.key === "?") { ev.preventDefault(); ev.stopPropagation(); close(); } };
  document.addEventListener("keydown", h, true);
  ov.onclick = e => { if (e.target === ov) close(); };
}
function needSel(){ toast("selecione um item primeiro (j/k ou passe o mouse) e tente de novo"); }

// ── editar entidades (tecla e nas fichas, como a TUI) ───────────────────
const A_OF = id => window.BRAIN.M.actions.find(x => x.id === id);
function editAction(a){
  const M = window.BRAIN.M;
  const eff0 = a.effort_min >= 60 ? (a.effort_min % 60 ? Math.floor(a.effort_min / 60) + "h" + (a.effort_min % 60) + "m" : Math.floor(a.effort_min / 60) + "h") : (a.effort_min ? a.effort_min + "m" : "");
  formDialog({title: "Editar " + a.id, sub: a.title, fields: [
      {k: "title", label: "Título", value: a.title},
      {k: "due", label: "Prazo (vazio remove)", type: "date", value: a.due || ""},
      {k: "effort", label: "Esforço", value: eff0},
      {k: "priority", label: "Prioridade", options: [["normal", "normal"], ["alta", "alta"], ["baixa", "baixa"]], value: a.priority || "normal"},
      {k: "project", label: "Projeto", options: projectOpts(), value: a.project || ""},
      {k: "deliverable", label: "Entregável", ph: "PROJ-#.#", value: a.deliverable || ""},
      {k: "blocked", label: "Bloqueada por", ph: "TASK-#### (a CLI não remove bloqueio)", value: (a.blocked_by || []).join(",")},
      {k: "people", label: "Pessoas (+)", ph: "adiciona: ids por vírgula"},
      {k: "list", label: "Lista", options: [["mine", "minhas"], ["waiting", "aguardando outro"], ["watching", "observando"]], value: a.list},
      {k: "owner", label: "Dono", options: peopleOpts(), value: a.owner},
      {k: "note", label: "Nota (histórico)", ph: "vai para o histórico da ação"}],
    preview: v => {
      let c = "brain action update " + a.id;
      if (v.title && v.title !== a.title) c += " --title " + q(v.title);
      if (v.due !== (a.due || "")) c += v.due ? " --due " + v.due : " --clear-due";
      if (v.effort && v.effort !== eff0) c += " --effort " + v.effort;
      if (v.priority !== (a.priority || "normal")) c += " --priority " + v.priority;
      if (v.project !== (a.project || "")) c += " --project " + v.project;
      if (v.deliverable && v.deliverable !== (a.deliverable || "")) c += " --deliverable " + v.deliverable;
      if (v.blocked && v.blocked.replace(/\s/g, "") !== (a.blocked_by || []).join(",")) c += " --blocked-by " + v.blocked.replace(/\s/g, "");
      const novos = v.people.split(",").map(x => x.trim()).filter(x => x && !(a.people || []).includes(x));
      if (novos.length) c += " --people " + novos.join(",");
      if (v.list !== a.list) c += " --list " + v.list;
      if (v.owner && v.owner !== a.owner) c += " --owner " + v.owner;
      if (v.note) c += " --note " + q(v.note);
      return c === "brain action update " + a.id ? null : c;
    },
    run: (v, m) => { const x = m.actions.find(y => y.id === a.id);
      if (v.title) x.title = v.title; if (v.due) x.due = v.due; if (v.priority) x.priority = v.priority; }});
}
function newAction(){
  const M = window.BRAIN.M;
  const ficha = M.people.find(x => x.id === M.owner.id);
  formDialog({title: "Nova ação",
    sub: ficha ? undefined : "⚠ a ficha do dono (" + M.owner.id + ") não existe — o CLI vai recusar até registrar",
    fields: [
      {k: "title", label: "Título", ph: "o que precisa ser feito"},
      {k: "list", label: "Lista", options: [["mine", "minhas"], ["waiting", "aguardando outro"], ["watching", "observando"]], value: "mine"},
      {k: "owner", label: "Dono", options: peopleOpts(), value: M.owner.id},
      {k: "due", label: "Prazo", type: "date", value: ""},
      {k: "effort", label: "Esforço", ph: "90m · 2h · 1h30"},
      {k: "priority", label: "Prioridade", options: [["normal", "normal"], ["alta", "alta"], ["baixa", "baixa"]], value: "normal"},
      {k: "project", label: "Projeto", options: projectOpts()},
      {k: "deliverable", label: "Entregável", ph: "PROJ-#.# do projeto escolhido"},
      {k: "people", label: "Pessoas", ph: "adiciona: marina-demo, heitor-demo"},
      {k: "blocked", label: "Bloqueada por", ph: "TASK-####"},
      {k: "unblocks", label: "Destrava", ph: "TASK-####"},
      {k: "link", label: "Origem (link)", ph: "URL ou arquivo"}],
    preview: v => {
      if (!v.title) return null;
      let c = "brain action open " + q(v.title) + " --force";
      if (v.list !== "mine") c += " --list " + v.list;
      if (v.owner && v.owner !== M.owner.id) c += " --owner " + v.owner;
      if (v.due) c += " --due " + v.due;
      if (v.effort) c += " --effort " + v.effort;
      if (v.project) c += " --project " + v.project;
      if (v.priority !== "normal") c += " --priority " + v.priority;
      if (v.deliverable) c += " --deliverable " + v.deliverable;
      if (v.people) c += " --people " + v.people.replace(/\s/g, "");
      if (v.blocked) c += " --blocked-by " + v.blocked.replace(/\s/g, "");
      if (v.unblocks) c += " --unblocks " + v.unblocks.replace(/\s/g, "");
      if (v.link) c += " --link " + q(v.link);
      return c;
    },
    run: (v, m) => {}});
}
function editPerson(pe){
  formDialog({title: "Editar " + pe.name, fields: [
      {k: "name", label: "Nome", value: pe.name},
      {k: "role", label: "Papel", value: pe.role || ""},
      {k: "relation", label: "Relação", value: pe.relation || ""},
      {k: "email", label: "E-mail", value: pe.email || ""}],
    preview: v => {
      const parts = [];
      if (v.name && v.name !== pe.name) parts.push("--name " + q(v.name));
      if (v.role !== (pe.role || "")) parts.push("--role " + q(v.role));
      if (v.relation !== (pe.relation || "")) parts.push("--relation " + q(v.relation));
      if (v.email !== (pe.email || "")) parts.push("--email " + q(v.email));
      return parts.length ? "brain person update " + pe.id + " " + parts.join(" ") : null;
    },
    run: (v, m) => { const x = m.people.find(y => y.id === pe.id);
      if (v.name) x.name = v.name; if (v.role) x.role = v.role; if (v.relation) x.relation = v.relation; }});
}
function editOpp(o){
  formDialog({title: "Editar " + o.id, sub: o.title, fields: [
      {k: "title", label: "Título", value: o.title},
      {k: "kind", label: "Tipo", options: [["", "—"], ["melhoria-de-processo", "melhoria de processo"], ["novo-processo", "novo processo"], ["estruturante", "estruturante"]], value: o.kind || ""},
      {k: "area", label: "Área", options: areaOpts(), value: o.area || ""},
      {k: "process", label: "Processo", options: procOpts(), value: o.process || ""},
      {k: "goal", label: "Goal", options: goalOpts(), value: o.goal || ""},
      {k: "problem", label: "Problema", value: o.problem || ""},
      {k: "suggestion", label: "Sugestão", value: o.suggestion || ""},
      {k: "gain", label: "Ganho esperado", value: o.gain || ""},
      {k: "hours", label: "Horas/mês economizadas", type: "number", value: o.hours_saved || ""},
      {k: "person", label: "Pessoa ligada", options: peopleOpts(), value: ""},
      {k: "note", label: "Nota"}],
    preview: v => {
      const parts = [];
      if (v.title && v.title !== o.title) parts.push("--title " + q(v.title));
      if (v.kind && v.kind !== o.kind) parts.push("--kind " + v.kind);
      if (v.area && v.area !== o.area) parts.push("--area " + v.area);
      if (v.process && v.process !== (o.process || "")) parts.push("--process " + v.process);
      if (v.goal && v.goal !== (o.goal || "")) parts.push("--goal " + v.goal);
      if (v.problem && v.problem !== (o.problem || "")) parts.push("--problem " + q(v.problem));
      if (v.suggestion && v.suggestion !== (o.suggestion || "")) parts.push("--suggestion " + q(v.suggestion));
      if (v.gain && v.gain !== (o.gain || "")) parts.push("--gain " + q(v.gain));
      if (v.hours) parts.push("--hours-saved " + v.hours);
      if (v.person) parts.push("--person " + v.person);
      if (v.note) parts.push("--note " + q(v.note));
      return parts.length ? "brain opportunity update " + o.id + " " + parts.join(" ") : null;
    },
    run: (v, m) => { const x = m.portfolio.opportunities.find(y => y.id === o.id);
      if (v.title) x.title = v.title; if (v.problem) x.problem = v.problem; }});
}
// ── ICE: dropdowns do rubric (fonte única: portfolio.ice_rubric do view model) ──
function iceAxes(){ const pf = window.BRAIN.M.portfolio || {}; return (pf.ice_rubric && pf.ice_rubric.axes) || {}; }
function iceOpts(ax){
  const a = iceAxes()[ax], out = [["", "— escolha —"]];
  if (a) a.levels.forEach(l => out.push([String(l.n), l.label]));
  return out;
}
function iceQ(ax){ const a = iceAxes()[ax]; return a ? a.name + " — " + a.question : ax; }
function iceNote(ax, v){
  const a = iceAxes()[ax]; if (!a || !v) return "";
  const lv = a.levels.find(l => String(l.n) === String(v));
  return lv ? lv.criterion + " · " + lv.anchor : "";
}
function iceHint(h){ return h == null ? null : h > 40 ? 5 : h >= 20 ? 4 : h >= 10 ? 3 : h >= 5 ? 2 : 1; }
function iceForm(o){
  formDialog({title: "ICE · " + o.id, sub: "impacto × confiança × facilidade (1–5) — o CLI calcula o score · ? traz a metodologia", fields: [
      {k: "impact", label: iceQ("impact"), options: iceOpts("impact"), value: o.impact == null ? "" : String(o.impact),
        note: v => { const base = iceNote("impact", v); if (!o.hours_saved || !v) return base;
          const hint = iceHint(o.hours_saved);
          let t = (base ? base + "\n" : "") + "horas declaradas: " + o.hours_saved + "h/mês → faixa sugerida " + hint;
          if (+v > hint) t += " · ⚠ escopo e horas divergem: vale a menor nota";
          return t; }},
      {k: "confidence", label: iceQ("confidence"), options: iceOpts("confidence"), value: o.confidence == null ? "" : String(o.confidence), note: v => iceNote("confidence", v)},
      {k: "ease", label: iceQ("ease"), options: iceOpts("ease"), value: o.ease == null ? "" : String(o.ease), note: v => iceNote("ease", v)}],
    help: () => iceHelpHTML(),
    preview: v => (v.impact && v.confidence && v.ease)
      ? "brain opportunity score " + o.id + " --impact " + v.impact + " --confidence " + v.confidence + " --ease " + v.ease
      : null,
    run: (v, m) => { const x = m.portfolio.opportunities.find(y => y.id === o.id);
      x.impact = +v.impact; x.confidence = +v.confidence; x.ease = +v.ease; x.score = x.impact * x.confidence * x.ease; x.ice_suggested = false; }});
}
// metodologia: as 3 tabelas + medidas de sucesso + regras, do portfolio.ice_rubric (nada de texto no JS)
function iceHelpHTML(){
  const r = (window.BRAIN.M.portfolio || {}).ice_rubric || {};
  const axes = r.axes || {};
  let h = '<p class="note-s" style="margin:0 0 10px">Score = impacto × confiança × facilidade · 1–5 por eixo · o CLI calcula (1–125).</p>';
  if (r.success_measures && r.success_measures.length)
    h += '<p class="note-s">Medidas de sucesso: ' + r.success_measures.map(x => "(" + esc(x[0]) + ") " + esc(x[1])).join(" · ") + "</p>";
  if (r.principles && r.principles.length)
    h += '<p class="note-s">Princípios: ' + r.principles.map(esc).join(" · ") + "</p>";
  ["impact", "confidence", "ease"].forEach(ax => { const a = axes[ax]; if (!a) return;
    h += "<h3>" + esc(a.name) + " — " + esc(a.question) + "</h3>" +
      '<table class="icerub"><tr><th>Nota</th><th>Critério</th><th>' + esc(a.extra_col) + "</th><th>" + esc(a.links_col) + "</th></tr>" +
      a.levels.map(l => "<tr><td>" + esc(l.n) + "</td><td>" + esc(l.criterion) + "</td><td>" + esc(l.anchor) + "</td><td>" + esc(l.link) + "</td></tr>").join("") +
      "</table>" + '<p class="note-s">Regras: ' + a.rules.map(esc).join(" · ") + "</p>"; });
  return h;
}
function iceHelpOverlay(){ stackHelp("Metodologia · ICE", iceHelpHTML()); }
window.iceHelp = iceHelpOverlay;
document.addEventListener("click", e => { if (e.target.closest("[data-icehelp]")) { e.preventDefault(); iceHelpOverlay(); } });
function editProc(pc){
  formDialog({title: "Editar " + pc.id, sub: pc.title, fields: [
      {k: "title", label: "Título", value: pc.title},
      {k: "area", label: "Área", options: areaOpts(), value: pc.area},
      {k: "owner", label: "Responsável", options: peopleOpts(), value: pc.owner},
      {k: "executors", label: "Executores (+)", ph: "ids por vírgula", value: (pc.executors || []).join(",")},
      {k: "recurrence", label: "Recorrência", options: [["", "—"], ["diaria", "diária"], ["semanal", "semanal"], ["mensal", "mensal"], ["trimestral", "trimestral"]], value: pc.recurrence || ""},
      {k: "perMonth", label: "Execuções/mês", type: "number", value: pc.per_month || ""},
      {k: "duration", label: "Duração", ph: "90m · 2h", value: pc.duration_min ? (pc.duration_min >= 60 ? Math.floor(pc.duration_min / 60) + "h" + (pc.duration_min % 60 ? (pc.duration_min % 60) + "m" : "") : pc.duration_min + "m") : ""},
      {k: "maturity", label: "Maturidade (1-5)", options: [["", "—"], ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"], ["5", "5"]], value: pc.maturity ? String(pc.maturity) : ""},
      {k: "tools", label: "Ferramentas", ph: "por vírgula", value: (pc.tools || []).join(",")},
      {k: "io", label: "Entrada → saída", value: pc.io || ""},
      {k: "pains", label: "Dores (+)", ph: "por vírgula"},
      {k: "note", label: "Nota"}],
    preview: v => {
      const parts = [];
      if (v.title && v.title !== pc.title) parts.push("--title " + q(v.title));
      if (v.area && v.area !== pc.area) parts.push("--area " + v.area);
      if (v.owner && v.owner !== pc.owner) parts.push("--owner " + v.owner);
      if (v.executors) parts.push("--executor " + v.executors.replace(/\s/g, ""));
      if (v.recurrence) parts.push("--recurrence " + v.recurrence);
      if (v.perMonth) parts.push("--per-month " + v.perMonth);
      if (v.duration) parts.push("--duration " + v.duration);
      if (v.maturity) parts.push("--maturity " + v.maturity);
      if (v.tools) parts.push("--tools " + q(v.tools));
      if (v.io) parts.push("--io " + q(v.io));
      if (v.pains) parts.push("--pain " + q(v.pains));
      if (v.note) parts.push("--note " + q(v.note));
      return parts.length ? "brain process update " + pc.id + " " + parts.join(" ") : null;
    },
    run: (v, m) => { const x = m.portfolio.processes.find(y => y.id === pc.id);
      if (v.title) x.title = v.title; if (v.area) x.area = v.area; }});
}
function editPlanNode(kind, id, node){        // goal/projeto: gate estrutural · entregável: sem gate
  const isGoal = kind === "goal", isDeliv = id.includes(".");
  const M = window.BRAIN.M;
  const fields = [{k: "title", label: "Título", value: node.title}];
  if (isDeliv) {
    fields.push({k: "due", label: "Prazo", type: "date", value: node.due || ""});
    fields.push({k: "weight", label: "Peso", type: "number", value: String(node.weight || 1)});
  } else {
    fields.push({k: "status", label: "Status", value: node.status || "ativo",
      options: [["ativo", "ativo"], ["congelado", "congelado"], ["depois", "depois"], ["finalizado", "finalizado"]]});
    if (isGoal) {
      fields.push({k: "horizon", label: "Horizonte", type: "date", value: node.horizon || ""});
      fields.push({k: "why", label: "Por quê", value: node.why || ""});
    } else {
      fields.push({k: "owner", label: "Dono", options: peopleOpts(), value: node.owner || ""});
    }
    fields.push({k: "approval", label: "Aprovação literal", value: "ok"});
  }
  formDialog({title: "Editar " + id, sub: node.title + (isDeliv ? "" : " — mudança estrutural"), gate: !isDeliv, fields: fields,
    preview: v => {
      const parts = [];
      if (v.title && v.title !== node.title) parts.push("--title " + q(v.title));
      if (isDeliv) {
        if (v.due !== (node.due || "")) parts.push(v.due ? "--due " + v.due : "--due ");
        if (v.weight && +v.weight !== (node.weight || 1)) parts.push("--weight " + v.weight);
        return parts.length ? "brain plan edit " + id + " " + parts.join(" ") : null;
      }
      if (v.status && v.status !== (node.status || "ativo")) parts.push("--status " + v.status);
      if (isGoal) {
        if (v.horizon !== (node.horizon || "")) parts.push("--horizon " + (v.horizon || "\"\""));
        if (v.why !== (node.why || "")) parts.push("--why " + q(v.why));
      } else if (v.owner && v.owner !== node.owner) parts.push("--owner " + v.owner);
      parts.push('--approval "' + (v.approval || "").replace(/"/g, "'") + '"');
      return "brain plan edit " + id + " " + parts.join(" ");
    },
    run: (v, m) => { if (v.title) node.title = v.title; if (v.status) node.status = v.status; }});
}
function promoteDialog(o){
  const G = window.BRAIN.M.goals, P = window.BRAIN.M.projects;
  formDialog({title: "Promover " + o.id, sub: o.title + " — vira nó do PLANNING no nível escolhido (gate estrutural)", gate: true, fields: [
      {k: "level", label: "Nível", options: [["project", "projeto — num goal"], ["deliverable", "entregável — num projeto"], ["goal", "goal novo"]], value: "project"},
      {k: "goal", label: "Goal (nível projeto)", options: G.map(g => [g.id, g.id + " — " + g.title]), value: G[0] && G[0].id},
      {k: "project", label: "Projeto (nível entregável)", options: P.map(p => [p.id, p.id + " — " + p.title]), value: P[0] && P[0].id}],
    note: v => v.level === "project" ? "cria um PROJ-# novo dentro do goal escolhido"
      : v.level === "deliverable" ? "cria um PROJ-#.N novo (entregável) dentro do projeto escolhido"
      : "cria um GOAL-# novo no topo da árvore",
    preview: v => "brain opportunity promote " + o.id + " --level " + v.level +
      (v.level === "project" ? " --goal " + v.goal : v.level === "deliverable" ? " --project " + v.project : "") +
      ' --approval "ok"',
    run: (v, m) => { const x = m.portfolio.opportunities.find(y => y.id === o.id); x.status = "em-andamento"; x.promoted = v.level;
      if (v.level === "project") x.goal = v.goal;
      if (v.level === "deliverable") { x.project = v.project; x.goal = ((m.goals.find(g => g.projects.includes(v.project)) || {}).id) || x.goal; }
      if (!LIVE) toast("retrato — no live o CLI cria o nó no goals.md e o refresh traz"); }});
}
function statusPicker(o){
  const stages = ["ideia", "triagem", "priorizada", "em-andamento", "piloto", "validando", "entregue", "em-espera", "descartada"];
  const blocked = (o.project || o.promoted) ? "" : "em-andamento";   // em-andamento só nasce da promoção (gate)
  formDialog({title: "Status · " + o.id, sub: o.title, fields: [
      {k: "status", label: "Estágio", options: stages.map(s => [s, s + (s === o.status ? " (atual)" : "") +
        (s === blocked ? " — exige promoção (gate)" : "")]), value: o.status},
      {k: "reason", label: "Motivo (exigido p/ em-espera e descartada)", value: ""}],
    preview: v => {
      if (v.status === o.status || v.status === blocked) return null;
      const lateral = ["em-espera", "descartada"].includes(v.status);
      if (lateral && !v.reason.trim()) return null;               // estágio lateral sem motivo não vira comando
      return "brain opportunity status " + o.id + " " + v.status +
        (lateral ? ' --reason "' + v.reason.replace(/"/g, "'") + '"' : "");
    },
    run: (v, m) => { if (v.status === o.status || v.status === blocked) return; const x = m.portfolio.opportunities.find(y => y.id === o.id);
      x.status_history.unshift({date: m.today, from: x.status, to: v.status, reason: v.reason || null}); x.status = v.status; }});
}
function supersedeForm(d){
  formDialog({title: "Superar " + d.id, sub: "decisões são imutáveis — o caminho é uma nova que substitui", fields: [
      {k: "title", label: "Nova decisão", ph: "o que passa a valer"},
      {k: "by", label: "Quem decidiu", value: window.BRAIN.M.owner.id, ph: "ids por vírgula"},
      {k: "rationale", label: "Por quê", value: ""}],
    preview: v => v.title ? 'brain decision add "' + v.title.replace(/"/g, "'") + '" --decided-by ' + (v.by || window.BRAIN.M.owner.id) + ' --supersedes ' + d.id + (v.rationale ? ' --rationale "' + v.rationale.replace(/"/g, "'") + '"' : "") : null,
    run: (v, m) => { const n = Math.max(...m.decisions.map(x => +x.id.slice(4))) + 1;
      m.decisions.unshift({id: "DEC-" + String(n).padStart(4, "0"), title: v.title, date: m.today, decided_by: [String(v.by || m.owner.id).trim()], decided_by_names: [m.owner.name],
        project: d.project, context: "supera " + d.id, rationale: v.rationale || null, status: "ativa",
        supersedes: d.id, superseded_by: null, source_label: "declarado no painel", prov: "declarado"}); }});
}

// ── mapa de teclas por contexto (espelha ctx_keys da TUI) ───────────────
function ctxKeys(k){
  const h = location.hash, M = window.BRAIN.M;
  const selTask = () => { const id = selId(); const a = id && id.startsWith("TASK-") ? A_OF(id) : null; if (!a) needSel(); return a; };
  const selOpp = () => { const id = selId(); const o = id && id.startsWith("OPP-") ? M.portfolio.opportunities.find(x => x.id === id) : null; if (!o) needSel(); return o; };
  const selDec = () => { const id = selId(); const d = id && id.startsWith("DEC-") ? M.decisions.find(x => x.id === id) : null; if (!d) needSel(); return d; };
  const goOrSel = (hash, fn) => { const el = selEl(); if (el && (fn || true) && SEL.i >= 0 && fn) fn(); else location.hash = hash; };

  if (h.startsWith("#home")) { if (k === "n") { noteForm(); return true; } return false; }
  if (h.startsWith("#projects")) { if (k === "n") { planForm(); return true; } return false; }
  if (h.startsWith("#todo") || h.startsWith("#action/")) {
    const a = h.startsWith("#action/") ? A_OF(decodeURIComponent(h.slice(8))) : null;
    if (k === "n" && h.startsWith("#todo")) { newAction(); return true; }
    const t = a || selTask(); if (!t) return k === "n";
    const mut = ["e", "c", "s", "t", "D", "z"];          // como o TUI: mutação só em ação aberta
    if (mut.includes(k) && !t.open) { toast(t.id + " está " + (t.status === "descartada" ? "descartada" : "fechada") + " — reabra com o antes"); return true; }
    if (k === "e") { editAction(t); return true; }
    if (k === "m" && h.startsWith("#action/")) { mergeForm(t); return true; }
    if (k === "c") { closeForm(t); return true; }
    if (k === "s") {
      if (t.blocked_by && t.blocked_by.length) { toast(t.id + " segue bloqueada por " + t.blocked_by.join(", ")); return true; }
      const next = {aberta: "fazendo", fazendo: "aguardando", aguardando: "aberta"}[t.status] || "aberta";
      runCommand("brain action update " + t.id + " --status " + next, m => { A_OF(t.id).status = next; }); return true; }
    if (k === "t") { formDialog({title: "Prazo · " + t.id, sub: t.title, fields: [{k: "due", label: "Prazo", type: "date", value: t.due || ""}],
      preview: v => v.due ? "brain action update " + t.id + " --due " + v.due : null,
      run: (v, m) => { A_OF(t.id).due = v.due; }}); return true; }
    if (k === "D") { formDialog({title: "Descartar " + t.id, fields: [{k: "reason", label: "Motivo", value: ""}],
      preview: v => v.reason ? "brain action drop " + t.id + ' --reason "' + v.reason.replace(/"/g, "'") + '"' : null,
      run: (v, m) => { const x = A_OF(t.id); x.open = false; x.status = "descartada"; }}); return true; }
    if (k === "z") { const park = !t.parked;
      runCommand("brain action update " + t.id + (park ? " --park" : " --unpark"), m => { A_OF(t.id).parked = park; }); return true; }
    if (k === "o" && !t.open) { reopenForm(t); return true; }
    if (k === "m") { const w = (t.open && t.list === "waiting") ? t : null;
      if (w) chaseDraft(w); else toast("m cobrar: selecione uma ação aguardando outra pessoa (waiting)"); return true; }
    return mut.includes(k) || k === "o";
  }
  if (h.startsWith("#project/")) { const p = window.BRAIN.P[decodeURIComponent(h.slice(9))];
    if (k === "e" && p) { editPlanNode("project", p.id, p); return true; }
    const dv = selEl() && selEl().dataset.deliv ? selEl().dataset.deliv : null;
    if (k === " " && dv) { delivToggle(dv); return true; }
    if (k === "s" && dv) { delivState(dv); return true; }
    return false; }
  if (h.startsWith("#people")) { if (k === "n") { nbForm("person"); return true; } return false; }
  if (h.startsWith("#wins")) { if (k === "n") { nbForm("delivery"); return true; } return false; }
  if (h.startsWith("#person/")) { const pe = window.BRAIN.PE[decodeURIComponent(h.slice(8))];
    if ((k === "u" || k === "e") && pe) { editPerson(pe); return true; }
    if (k === "a" && pe) { formDialog({title: "Alias · " + pe.name, fields: [{k: "alias", label: "Novo alias", ph: "apelido"}],
      preview: v => v.alias ? "brain person alias " + pe.id + " " + v.alias : null,
      run: (v, m) => { m.people.find(x => x.id === pe.id).aliases.push(v.alias); }}); return true; } return false; }
  if (h.startsWith("#ask")) {
    if (k === "n") { pubRequestForm(); return true; }
    const id = selId() || "";
    const q = id.startsWith("ASK-") ? M.questions.find(x => x.id === id) : null;
    const pr = id.startsWith("PROP-") ? M.proposals.find(x => x.id === id) : null;
    if (!q && !pr) { if (k === "a" || k === "x" || k === "r" || k === "A") needSel(); return k === "R"; }
    if (k === "a" && q) { if (q.status !== "aberta") { toast(q.id + " já está " + q.status); return true; }
      formDialog({title: "Responder " + q.id, sub: q.text,
      fields: [{k: "answer", label: "Resposta", value: (q.options && q.options[0]) || ""}],
      preview: v => v.answer ? "brain ask answer " + q.id + ' "' + v.answer.replace(/"/g, "'") + '"' : null,
      run: (v, m) => { const x = m.questions.find(y => y.id === q.id); x.status = "respondida"; x.answer = v.answer; }}); return true; }
    if (k === "a" && pr) { if (pr.status !== "aberta") { toast(pr.id + " já está " + pr.status); return true; } propQuote(pr.id, true); return true; }
    if (k === "r" && pr) { if (pr.status !== "aberta") { toast(pr.id + " já está " + pr.status); return true; } propQuote(pr.id, false); return true; }
    if (k === "x" && q) { if (q.status !== "aberta") { toast(q.id + " já está " + q.status); return true; }
      const el = selEl(); const d = el && el.querySelector("[data-drop]"); if (d) d.click(); return true; }
    if (k === "R") { toast("(agente) retoma a sessão com as respostas aplicadas — claude -p --resume"); return true; }
    return false;
  }
  if (h.startsWith("#focus")) {
    const f = M.focus;
    if (k === "A" && f && f.status === "proposto") { $("#view .planbtns [data-c=approve]") ? $("#view .planbtns [data-c=approve]").click() : focusApproveKey(); return true; }
    if (k === "a" && f && f.status === "aprovado") { const b = $("#view .planbtns [data-c=apply]"); if (b) b.click(); return true; }
    if (k === "s") { runCommand("brain focus sync --dry-run"); toast("--dry-run: conferir o diff antes de aplicar"); return true; }
    if (k === "p") { toast("(agente) /focus: o agente lê a agenda e propõe o plano — brain focus plan"); return true; }
    return false; }
  if (h.startsWith("#outbox")) {
    if (k === "n") { draftForm(); return true; }
    const mid = selId() || "";
    const m0 = mid.startsWith("MSG-") ? M.outbox.find(x => x.id === mid) : null;
    if (k === "A") {
      if (m0 && m0.status === "rascunho") approveMsgForm(m0);
      else if (!m0) needSel();
      else toast(m0.id + " está " + m0.status + " — aprovar vale para rascunho");
      return true; }
    if (k === "S") { toast("(agente) envio pelo MCP do Slack como o dono — porta 2, após aprovação do texto exato"); return true; }
    if (k === "x") {
      if (m0 && (m0.status === "rascunho" || m0.status === "aprovada")) cancelMsgForm(m0);
      else if (!m0) needSel();
      else toast(m0.id + " está " + m0.status + " — cancelar vale para rascunho ou aprovada");
      return true; }
    return false; }
  if (h.startsWith("#feedback")) {
    if (k === "n") { feedbackForm(); return true; }
    if (k === "s") { runCommand("brain feedback sync"); return true; }
    if (k === "p") { const fid = selId() || "";
      const fb = fid.startsWith("FB-") ? M.feedback.find(x => x.id === fid) : null;
      if (fb && (fb.status === "pendente" || fb.status === "falhou")) runCommand("brain feedback push " + fb.id);
      else if (!fb) needSel();
      else toast(fb.id + " está " + fb.status + " — publicar vale para pendente ou falhou");
      return true; }
    return false; }
  if (h.startsWith("#decisions")) {
    if (k === "n") { nbForm("decision"); return true; }
    if (k === "S") { const d = selDec(); if (d) supersedeForm(d); return true; } return false; }
  if (h.startsWith("#pf/opps")) {
    if (k === "n") { formDialog({title: "Nova oportunidade", fields: [
        {k: "title", label: "Título", ph: "o que vale melhorar"},
        {k: "area", label: "Área", options: areaOpts(), value: M.portfolio.areas[0] && M.portfolio.areas[0].id},
        {k: "kind", label: "Tipo", options: [["melhoria-de-processo", "melhoria-de-processo"], ["novo-processo", "novo-processo"], ["estruturante", "estruturante"]]},
        {k: "process", label: "Processo", options: procOpts()},
        {k: "problem", label: "Problema", ph: "o que dói hoje"},
        {k: "suggestion", label: "Sugestão", ph: "como resolver"},
        {k: "gain", label: "Ganho esperado"},
        {k: "hours", label: "Horas/mês economizadas", type: "number"},
        {k: "person", label: "Pessoa ligada", options: peopleOpts()},
        {k: "goal", label: "Goal", options: goalOpts()}],
      preview: v => {
        if (!v.title) return null;
        let c = "brain opportunity add " + q(v.title) + " --area " + v.area + " --kind " + v.kind;
        if (v.process) c += " --process " + v.process;
        if (v.problem) c += " --problem " + q(v.problem);
        if (v.suggestion) c += " --suggestion " + q(v.suggestion);
        if (v.gain) c += " --gain " + q(v.gain);
        if (v.hours) c += " --hours-saved " + v.hours;
        if (v.person) c += " --person " + v.person;
        if (v.goal) c += " --goal " + v.goal;
        return c;
      },
      run: (v, m) => { const n = Math.max(...m.portfolio.opportunities.map(x => +x.id.slice(4))) + 1;
        m.portfolio.opportunities.push({id: "OPP-" + String(n).padStart(4, "0"), title: v.title, area: v.area, kind: v.kind,
          status: "ideia", status_history: [], score: null, ice_suggested: false, docs: [], evidence: [], people: []}); }}); return true; }
    const o = selOpp(); if (!o) return k === "n";
    if (k === "s") { statusPicker(o); return true; }
    if (k === "i") { iceForm(o); return true; }
    if (k === "c" && o.ice_suggested) {
      runCommand("brain opportunity score " + o.id + " --impact " + o.impact + " --confidence " + o.confidence + " --ease " + o.ease,
        m => { const x = m.portfolio.opportunities.find(y => y.id === o.id); x.ice_suggested = false; }); return true; }
    if (k === "e") { editOpp(o); return true; }
    if (k === "x") { if (["descartada", "entregue"].includes(o.status)) { toast(o.id + " está " + o.status); return true; }
      oppReasonDialog(o.id, "descartada"); return true; }
    if (k === "p" && !(o.project || o.promoted)) { promoteDialog(o); return true; }
    if (k === "O") { toast("(agente) one-pager: brain share opportunity → publica na porta 6"); return true; }
    return ["s", "i", "c", "x", "p", "O"].includes(k); }
  if (h.startsWith("#pf/opp/")) { const o = window.BRAIN.OPP[decodeURIComponent(h.slice(8))];
    if (k === "e" && o) { editOpp(o); return true; }
    if (k === "s" && o) { statusPicker(o); return true; }
    if (k === "i" && o) { iceForm(o); return true; } return false; }
  if (h.startsWith("#pf/procs")) {
    if (k === "n") { nbForm("process"); return true; }
    const id = selId(); const pc = id && id.startsWith("PROC-") ? M.portfolio.processes.find(x => x.id === id) : null;
    if (k === "e" && pc) { editProc(pc); return true; }
    if (k === "x" && pc) { formDialog({title: "Aposentar " + pc.id, fields: [{k: "reason", label: "Motivo", value: ""}],
      preview: v => v.reason ? "brain process retire " + pc.id + ' --reason "' + v.reason.replace(/"/g, "'") + '"' : null,
      run: (v, m) => { m.portfolio.processes.find(x => x.id === pc.id).status = "aposentado"; }}); return true; }
    return false; }
  if (h.startsWith("#pf/areas") || h.startsWith("#pf/area/")) {
    if (k === "n" && h.startsWith("#pf/areas")) { nbForm("area"); return true; }
    let a = null;
    if (h.startsWith("#pf/area/")) a = M.portfolio.areas.find(x => x.id === decodeURIComponent(h.slice(9)));
    else { const name = selEl() && selEl().querySelector("b") ? selEl().querySelector("b").textContent : null;
      a = name && M.portfolio.areas.find(x => x.name === name); }
    if (k === "e" && a) { formDialog({title: "Editar área " + a.name, fields: [{k: "name", label: "Nome", value: a.name}, {k: "alias", label: "Novo alias", value: ""}, {k: "note", label: "Nota", value: a.note || ""}],
      preview: v => { const parts = []; if (v.name && v.name !== a.name) parts.push("--name " + q(v.name)); if (v.alias) parts.push("--alias " + q(v.alias));
        if (v.note && v.note !== (a.note || "")) parts.push("--note " + q(v.note));
        return parts.length ? "brain area update " + a.id + " " + parts.join(" ") : null; },
      run: (v, m) => { const x = m.portfolio.areas.find(y => y.id === a.id); if (v.name) x.name = v.name; if (v.alias) x.aliases.push(v.alias); }}); return true; }
    return false; }
  return false;
}
function focusApproveKey(){ runCommand('brain focus approve ' + window.BRAIN.M.focus.id + ' --quote "ok"', focusMut("aprovado")); }

function helpOverlay(){
  const ov = document.createElement("div"); ov.className = "pal-back open";
  const rows = [
    ["globais", ""],
    ["tab / shift+tab", "próxima / anterior face (Execução · Portfólio)"],
    ["/", "busca e comandos (paleta)"],
    ["j k ↑ ↓", "mover na lista · enter abre a ficha"],
    ["[ ] ← → (h l)", "aba anterior / próxima"],
    ["`", "console da ponte (abre/fecha)"],
    ["?", "esta ajuda"],
    ["? (dentro do ICE)", "metodologia de pontuação — as notas com critério e regras"],
    ["TODO (com cartão selecionado)", ""],
    ["n", "nova ação"], ["e", "editar"], ["c", "fechar"], ["s", "status (ciclo)"], ["t", "prazo"],
    ["D", "descartar"], ["z", "não agora / voltar"], ["o", "reabrir"], ["m", "cobrar (agente)"],
    ["Foco", ""], ["A", "aprovar plano (gate)"], ["a", "aplicar no calendário (gate)"], ["s", "sync"], ["p", "planejar (agente)"],
    ["Mensagens", ""], ["A", "aprovar rascunho (gate)"], ["S", "enviar (agente)"], ["x", "cancelar"],
    ["Decisões", ""], ["S", "superar (nova decisão)"],
    ["Perguntas e propostas", ""], ["a", "responder pergunta / aceitar proposta (gate)"],
    ["r", "rejeitar proposta"], ["x", "descartar pergunta"], ["R", "retomar o agente"],
    ["Portfólio · Oportunidades", ""], ["n", "nova"], ["s", "status"], ["i", "ICE"], ["c", "confirmar ICE sugerido"],
    ["e", "editar"], ["x", "descartar"], ["p", "promover (gate)"], ["O", "one-pager (agente)"],
    ["Portfólio · Processos", ""], ["n", "novo"], ["e", "editar"], ["x", "aposentar"],
    ["Ficha de projeto", ""], ["space", "entregável feito"], ["s", "estado do entregável"],
    ["Publicar (porta 3)", ""], ["n", "pedir publicação"],
    ["Outros n", ""], ["n", "nota (Início) · estrutura do plano (Projetos) · rascunhar msg · nova decisão · nova entrega · nova pessoa · novo processo · nova área"],
    ["Ficha de ação", ""], ["m", "mesclar duplicada"],
    ["Pessoas / fichas", ""], ["u ou e", "editar pessoa"], ["a", "alias"],
    ["Projetos / Goals", ""], ["e", "editar (gate estrutural: brain plan log)"],
  ];
  ov.innerHTML = '<div class="palette"><div class="pin"><b>Teclas — as mesmas da TUI</b><span class="hint">? fecha</span></div>' +
    '<div style="padding:10px 16px 14px;max-height:70vh;overflow:auto"><table class="khelp">' +
    rows.map(r => r[1] ? "<tr><td>" + esc(r[0]) + "</td><td>" + esc(r[1]) + "</td></tr>" : '<tr class="grp"><td colspan="2">' + esc(r[0]) + "</td></tr>").join("") +
    "</table></div></div>";
  document.body.appendChild(ov);
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  document.addEventListener("keydown", function h(ev){ if (ev.key === "Escape" || ev.key === "?") { ov.remove(); document.removeEventListener("keydown", h); } });
}

// handler único de teclado: paleta primeiro, depois teclas de página
document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); pal.open ? closePal() : openPal(); return; }
  if (pal.open) {
    if (e.key === "Escape") closePal();
    if (e.key === "ArrowDown") { e.preventDefault(); pal.sel = Math.min(pal.items.length - 1, pal.sel + 1); renderPal(); }
    if (e.key === "ArrowUp") { e.preventDefault(); pal.sel = Math.max(0, pal.sel - 1); renderPal(); }
    if (e.key === "Enter") { e.preventDefault(); if ($("#palconfirm").classList.contains("open")) $("#palrun").click(); else pick(pal.sel); }
    return;
  }
  const openOv = document.querySelector(".pal-back.open");             // form/dialog aberto: só Esc fecha
  if (openOv) {
    if (e.key === "Escape") openOv.remove();
    return;
  }
  if (document.querySelector(".dd.open")) return;                      // dropdown de filtro cuida de si
  if (/input|textarea|select/i.test(e.target.tagName || "") || e.target.isContentEditable) return;
  const k = e.key;
  if (k === "`") { e.preventDefault(); conToggle(); return; }
  if (k === "Tab") {                                            // carrossel: Tab avança, Shift+Tab volta, wrap nas pontas
    e.preventDefault();
    if (faceList.length > 1) {
      const i = Math.max(0, faceList.findIndex(f => f[0] === faceCur));
      const step = e.shiftKey ? faceList.length - 1 : 1;
      location.hash = "#face/" + faceList[(i + step) % faceList.length][0];
    }
    return;
  }
  if (k === "/") { e.preventDefault(); openPal(); return; }
  if (k === "?") { e.preventDefault(); helpOverlay(); return; }
  if (k === "j" || k === "ArrowDown") { e.preventDefault(); selMove(1); return; }
  if (k === "k" || k === "ArrowUp") { e.preventDefault(); selMove(-1); return; }
  if (k === "Enter" && SEL.i >= 0) { e.preventDefault(); selOpen(); return; }
  if (["[", "ArrowLeft", "h", "]", "ArrowRight", "l"].includes(k)) {
    e.preventDefault(); navStep(["[", "ArrowLeft", "h"].includes(k) ? -1 : 1); return; }
  if (ctxKeys(k)) e.preventDefault();
});


// ── barra de teclas no rodapé (como a TUI: teclas do contexto, clicáveis) ──
function keyLegend(){
  const h = location.hash, M = window.BRAIN.M;
  const id = SEL.i >= 0 ? (selId() || "") : "";
  const sel = SEL.i >= 0 && !!selEl();
  const t = id.startsWith("TASK-") ? A_OF(id) : null;
  const o = id.startsWith("OPP-") ? M.portfolio.opportunities.find(x => x.id === id) : null;
  const out = [];
  const add = (k, label, dim, gate) => out.push({k: k, label: label, dim: !!dim, gate: !!gate});
  if (h.startsWith("#todo")) {
    add("n", "nova");
    add("e", "editar", !t || !t.open); add("c", "fechar", !t || !t.open); add("s", "status", !t || !t.open);
    add("t", "prazo", !t || !t.open); add("D", "descartar", !t || !t.open); add("z", t && t.parked ? "voltar" : "não agora", !t || !t.open);
    add("o", "reabrir", !(t && !t.open)); add("m", "cobrar", !(t && t.open && t.list === "waiting"));
  } else if (h.startsWith("#action/")) { add("e", "editar"); add("c", "fechar"); add("m", "mesclar"); }
  else if (h.startsWith("#home")) add("n", "nota");
  else if (h.startsWith("#projects")) add("n", "estrutura");
  else if (h.startsWith("#project/")) { add("e", "editar (gate)");
    add("space", "marcar feito", !(selEl() && selEl().dataset.deliv)); add("s", "estado", !(selEl() && selEl().dataset.deliv)); }
  else if (h.startsWith("#person/")) { add("u", "editar"); add("a", "alias"); }
  else if (h.startsWith("#ask")) {
    const id = SEL.i >= 0 ? (selId() || "") : "";
    const qs = id.startsWith("ASK-") ? (M.questions || []).find(x => x.id === id) : null;
    const ps = id.startsWith("PROP-") ? (M.proposals || []).find(x => x.id === id) : null;
    add("n", "pedir publicação");
    add("a", id.startsWith("PROP-") ? "aceitar (gate)" : "responder", !(qs ? qs.status === "aberta" : ps ? ps.status === "aberta" : false));
    add("r", "rejeitar proposta", !(ps && ps.status === "aberta"));
    add("x", "descartar pergunta", !(qs && qs.status === "aberta"));
    add("R", "retomar o agente");
  }
  else if (h.startsWith("#focus")) {
    const f = M.focus;
    if (f && f.status === "proposto") add("A", "aprovar", false, true);
    if (f && f.status === "aprovado") add("a", "aplicar", false, true);
    add("s", "sync"); add("p", "planejar");
  } else if (h.startsWith("#outbox")) {
    const mid = SEL.i >= 0 ? (selId() || "") : "";
    const m0 = mid.startsWith("MSG-") ? M.outbox.find(x => x.id === mid) : null;
    add("n", "rascunhar");
    add("A", "aprovar", !(m0 && m0.status === "rascunho"), true);
    add("S", "enviar", !(m0 && m0.status === "aprovada"));
    add("x", "cancelar", !(m0 && (m0.status === "rascunho" || m0.status === "aprovada")));
  } else if (h.startsWith("#feedback")) {
    const fid = SEL.i >= 0 ? (selId() || "") : "";
    const fb = fid.startsWith("FB-") ? (M.feedback || []).find(x => x.id === fid) : null;
    add("n", "sugerir/corrigir"); add("p", "publicar", !(fb && (fb.status === "pendente" || fb.status === "falhou"))); add("s", "sincronizar");
  } else if (h.startsWith("#decisions")) { add("n", "nova"); add("S", "superar", !id.startsWith("DEC-")); }
  else if (h.startsWith("#pf/opps")) {
    add("n", "nova");
    add("s", "status", !o); add("i", "ICE", !o); add("c", "confirmar ICE", !(o && o.ice_suggested));
    add("e", "editar", !o); add("x", "descartar", !o);
    add("p", "promover", !(o && !(o.project || o.promoted)), true); add("O", "one-pager", !o);
  } else if (h.startsWith("#pf/opp/")) { add("e", "editar"); add("s", "status"); add("i", "ICE"); }
  else if (h.startsWith("#pf/procs")) { add("n", "novo"); add("e", "editar", !id.startsWith("PROC-")); add("x", "aposentar", !id.startsWith("PROC-")); }
  else if (h.startsWith("#pf/areas")) { add("n", "nova"); add("e", "editar", !sel); }
  else if (h.startsWith("#wins")) add("n", "nova entrega");
  else if (h.startsWith("#people")) add("n", "nova pessoa");
  else if (h.startsWith("#pf/area/")) add("e", "editar");
  return out;
}
function renderKeyBar(){
  let bar = document.getElementById("kbar");
  if (!bar) { bar = document.createElement("div"); bar.id = "kbar"; bar.className = "kbd-bar"; document.body.appendChild(bar); }
  const ctx = keyLegend().map(x => '<button class="kkey' + (x.dim ? " dim" : "") + (x.gate ? " gate" : "") +
    '" data-k="' + esc(x.k) + '" title="' + (x.gate ? "gate — precisa do seu ok literal · " : "") + "tecla " + esc(x.k) + '">' +
    "<kbd>" + esc(x.k) + "</kbd>" + esc(x.label) + "</button>").join("");
  bar.innerHTML = '<div class="kctx">' + (ctx || '<span class="knone">sem teclas de contexto nesta página — j/k navega, enter abre</span>') + "</div>" +
    '<div class="kglobal"><button class="kkey" data-g="/" title="paleta de busca e comandos"><kbd>/</kbd>busca</button>' +
    '<button class="kkey" data-g="tab" title="trocar de face"><kbd>tab</kbd>face</button>' +
    '<button class="kkey" data-g="?" title="mapa de teclas"><kbd>?</kbd>ajuda</button></div>';
  bar.querySelectorAll("[data-k]").forEach(b => b.onclick = () => ctxKeys(b.dataset.k));
  bar.querySelectorAll("[data-g]").forEach(b => b.onclick = () => {
    if (b.dataset.g === "/") openPal();
    else if (b.dataset.g === "?") helpOverlay();
    else location.hash = "#face/" + (location.hash.startsWith("#pf/") ? "execucao" : "portfolio");
  });
}

})();
