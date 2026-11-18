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
// o ícone do app reaproveita esta aba (util.focus_open_tab) apontando-a para `/#t=<token>`: se a ponte foi reiniciada
// o token mudou — guarda o novo, devolve a URL ao que era (a rota fica) e recarrega; token igual, só devolve a URL
if (SERVE) window.addEventListener("hashchange", e => {
  const m = location.hash.match(/[#&]t=([^&]+)/); if (!m) return;
  const tok = decodeURIComponent(m[1]), back = (e.oldURL || "").split("#").slice(1).join("#");
  try { localStorage.setItem("brain-serve-token", tok); } catch (x) {}
  history.replaceState(null, "", location.pathname + location.search + (back ? "#" + back : ""));
  if (tok !== TOK) location.reload();
});
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
  const mine = MD.actions.filter(a => a.open && a.list === "mine");
  mine.filter(a => a.status === "aberta").forEach(a => out.push({label: "Marcar fazendo · " + a.id + " " + a.title,
    cmd: "brain action update " + a.id + " --status fazendo", mut: m => { m.actions.find(x => x.id === a.id).status = "fazendo"; }}));
  mine.forEach(a => out.push({label: "Fechar · " + a.id + " " + a.title, act: () => closeForm(a)}));
  MD.actions.filter(a => a.open && a.due_suggested).forEach(a => out.push({label: "Confirmar prazo sugerido · " + a.id + " (" + (a.due || "").slice(0, 10) + ")",
    cmd: "brain action update " + a.id + " --confirm-due", mut: m => { m.actions.find(x => x.id === a.id).due_suggested = false; }}));
  if (D0.focus && D0.focus.status === "proposto")
    out.push({label: "Aprovar plano de foco " + D0.focus.id + " (gate)", act: () => focusApproveForm()});
  if (D0.focus && D0.focus.status === "aprovado")
    out.push({label: "Aplicar plano de foco " + D0.focus.id + " no calendário (gate)", act: () => focusApplyForm()});
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
const NEEDS_BY = ["action ", "area ", "decision add", "delivery ", "person ", "process ", "doc ",
  "opportunity add", "opportunity update", "opportunity score", "opportunity status", "opportunity evidence", "plan deliverable"];
function ownerCmd(cmd){
  const bare = cmd.replace(/^brain /, "");
  return NEEDS_BY.some(x => bare.startsWith(x)) && !/^person resolve/.test(bare) && !/\s--by(\s|=)/.test(bare) ? cmd + " --by owner" : cmd;
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
    ["pf/visao", "Portfólio · Visão"], ["pf/opps", "Portfólio · Oportunidades"], ["pf/matrix", "Portfólio · Matriz"], ["pf/procs", "Portfólio · Processos"], ["pf/areas", "Portfólio · Áreas"], ["pf/docs", "Portfólio · Documentos"]]
    : [["face/execucao", "→ face Execução"], ["face/portfolio", "→ face Portfólio"], ["face/configuracoes", "→ face Configurações"],
    ["home", "Início"], ["sources", "Fontes"], ["todo", "TODO"], ["projects", "Projetos"], ["decisions", "Decisões"], ["wins", "Conquistas"],
    ["people", "Pessoas"], ["timeline", "Linha do tempo"], ["focus", "Foco"], ["outbox", "Mensagens"], ["feedback", "Sugestões"],
    ["cfg/inicio", "Configurações · Visão geral"], ["cfg/perfil", "Configurações · Perfil"], ["cfg/rotina", "Configurações · Rotina"],
    ["cfg/conectores", "Configurações · Conectores"], ["cfg/memoria", "Configurações · Memória"], ["cfg/integracoes", "Configurações · Integrações"],
    ["cfg/saude", "Configurações · Saúde"],
    ["pf/visao", "Portfólio · Visão"], ["pf/opps", "Portfólio · Oportunidades"], ["pf/matrix", "Portfólio · Matriz"],
    ["pf/procs", "Portfólio · Processos"], ["pf/areas", "Portfólio · Áreas"], ["pf/docs", "Portfólio · Documentos"]];
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
function focusReserve(){
  const f = window.BRAIN.M.focus;
  const ov = document.createElement("div"); ov.className = "pal-back open";
  ov.innerHTML = '<div class="palette"><div class="pin"><b>Reservar bloco de foco</b><span class="hint">' + esc(f.id) + "</span></div>" +
    '<div class="pal-confirm open" style="display:block;border-top:0;padding:14px 16px">' +
    '<p class="note-s" style="margin:0 0 10px">o CLI aprova e aplica o plano inteiro — evento brain_focus=1 no calendário. Reservar bloco-a-bloco seria extensão nova do CLI.</p>' +
    '<div class="row"><span class="note-s"></span><button class="btn ghost" data-x>cancelar</button><button class="btn primary" data-ok>continuar</button></div></div></div>';
  document.body.appendChild(ov);
  ov.querySelector("[data-x]").onclick = () => ov.remove();
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  ov.querySelector("[data-ok]").onclick = () => {
    ov.remove();
    if (window.BRAIN.M.focus && window.BRAIN.M.focus.status === "aprovado") focusApplyForm();
    else focusApproveForm();
  };
}
function focusApproveForm(){ openForm("focus.approve", {id: window.BRAIN.M.focus.id}); }   // gate: resposta literal, como a TUI
function focusApplyForm(){ const f = window.BRAIN.M.focus; openForm("focus.apply", {id: f.id, mode: f.mode || "google"}); }
function focusPlanForm(){
  const M = window.BRAIN.M;
  openForm("focus.plan", {days: String((M.focus && M.focus.horizon && M.focus.horizon.days) || 7)});
}
function focusSyncForm(){ openForm("focus.sync"); }
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
        if (b.dataset.c === "approve") focusApproveForm(); else focusApplyForm(); });
    }
  }
  document.querySelectorAll("#view .blk.prop").forEach(el => {
    el.classList.add("reservable");
    el.onclick = () => focusReserve();
  });
}


// ── perguntas e propostas (porta do dono: responder, descartar, aceitar, rejeitar) ──
function askAnswer(id, text){                          // botão de opção: a mesma linha do formulário ask.answer
  const M = window.BRAIN.M, q = (M.questions || []).find(x => x.id === id) || {};
  runArgv(window.BRAIN_FORMS.formArgv(M.forms["ask.answer"], {answer: text}, {id: id, text: q.text}, M));
}
function propQuote(id, accept){
  const p = (window.BRAIN.M.proposals || []).find(x => x.id === id) || {id: id};
  if (accept) openForm("proposal.accept", {id: id, summary: p.summary || "", kind: p.kind || "", target: p.target || "", into: p.into || ""});
  else openForm("proposal.reject", {id: id, summary: p.summary || ""});
}
function wireAskPage(){
  document.querySelectorAll("#view [data-ask]").forEach(card => {
    const id = card.dataset.ask;
    card.querySelectorAll("[data-opt]").forEach(b => b.onclick = () => askAnswer(id, b.dataset.opt));
    const send = card.querySelector("[data-send]");
    if (send) send.onclick = () => { const inp = card.querySelector("[data-free]");
      if (inp && inp.value.trim()) askAnswer(id, inp.value.trim()); else inp && inp.focus(); };
    const drop = card.querySelector("[data-drop]");
    if (drop) drop.onclick = () => { const q = (window.BRAIN.M.questions || []).find(x => x.id === id) || {}; openForm("ask.drop", {id: id, text: q.text || ""}); };
  });
  document.querySelectorAll("#view [data-acc], #view [data-rej]").forEach(b => {
    const card = b.closest(".card"); const idEl = card && card.querySelector(".idchip");
    if (!idEl) return;
    const id = idEl.textContent.trim(), accept = b.hasAttribute("data-acc");
    b.onclick = () => propQuote(id, accept);
  });
}


// ── P0: entregável, progresso, rascunho, publicar, criar entidades ───────
function findDelivIn(m, id0){ for (const pr of m.projects) { const d = pr.deliverables.find(x => x.id === id0); if (d) return d; } return null; }
function delivToggle(id0){                             // feito → pede evidência (como a TUI); desfazer é direto
  const d = findDelivIn(window.BRAIN.M, id0); if (!d) return;
  if (d.status === "feito") { runArgv([["plan", "deliverable", id0, "--status", "nao-iniciado", "--by", "owner"]]); return; }
  openForm("deliverable.done", {id: id0, title: d.title, item: d});
}
function delivState(id0){ const d = findDelivIn(window.BRAIN.M, id0); openForm("deliverable.state", {id: id0, title: d.title, item: d}); }
function progressForm(gid){ openForm("progress.declare", {id: gid}); }

function draftForm(prefill){ const p = prefill || {}; openForm("outbox.draft", {to: p.to || "", text: p.text || "", ref: p.ref || "", why: p.why || ""}); }
function chaseDraft(a){                                // o mesmo texto de partida da TUI (m cobrar)
  draftForm({to: a.owner, ref: a.id, why: a.overdue_days ? "prazo venceu" : "acompanhamento",
    text: "Oi " + String(a.owner_name || a.owner || "").split(" ")[0] + ', como está "' + a.title + '"?'});
}
function closeForm(a){ openForm("action.close", {id: a.id, title: a.title, item: a}); }
function reopenForm(a){ openForm("action.reopen", {id: a.id, title: a.title, item: a}); }
function approveMsgForm(m0){                           // porta 2: texto exato + resposta literal, como a TUI
  const n = (m0.id.split("-")[1] || "0").replace(/^0+/, "") || "0";
  openForm("outbox.approve", {id: m0.id, to_name: m0.to_name || m0.to || "?", n: n, text: m0.text},
    {extra: '<p class="note-s" style="margin:0 0 10px;white-space:pre-wrap">▌ ' + esc(m0.text) + "</p>"});
}
function cancelMsgForm(m0){ openForm("outbox.cancel", {id: m0.id, text: m0.text}); }
function feedbackForm(){ openForm("feedback.new"); }
function pubAction(act, id0){
  const s = (window.BRAIN.M.shares || []).find(y => y.id === id0) || {};
  if (act === "cancel") { runArgv([["publish", "cancel", id0]]); return; }          // como a TUI: cancelar é direto
  if (act === "approve") { openForm("publish.approve", {id: id0, report: s.report || "", destination: s.destination || ""}); return; }
  if (act === "done") { toast("(agente) publicar é porta do agente — publish done " + id0 + " registra o link ao postar"); return; }
}
function pubRequestForm(){
  const st = window.BRAIN.M.form_static || {};
  if (!(st.destinations || []).length) { toast("Nenhum destino em [publish].destinations (config/brain.toml). A porta está fechada."); return; }
  openForm("publish.request", {report: (st.reports || [])[0] || ""});
}
function nbForm(kind){
  if (kind === "note") return noteForm();
  if (kind === "newaction") return newAction();
  if (kind === "planform") return planNew();
  if (kind === "outbox") return draftForm();
  if (kind === "feedback") return feedbackForm();
  if (kind === "pub") return pubRequestForm();
  if (kind === "decision") return openForm("decision.new");
  if (kind === "delivery") return openForm("delivery.new");
  if (kind === "person") return openForm("person.new");
  if (kind === "process") return needArea() && openForm("process.new");
  if (kind === "area") return openForm("area.new");
}
function needArea(){                                   // processo e oportunidade pedem área (como a TUI): sem nenhuma, cadastra
  if ((window.BRAIN.M.portfolio || {}).areas && window.BRAIN.M.portfolio.areas.length) return true;
  toast("Cadastre uma área primeiro (Portfólio › Áreas, tecla n)."); openForm("area.new"); return false;
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
function noteForm(){                                   // vínculo: o item aberto ou selecionado (ação, goal, projeto, entregável)
  const h = decodeURIComponent(location.hash.slice(1).split("?")[0]), sel = selId() || "";
  const page = (h.match(/^(?:action|project|goal)\/(.+)$/) || [])[1] || "";
  const link = [page, sel].find(x => /^(TASK-\d{4,}|GOAL-\d+|PROJ-\d+(\.\d+)?)$/.test(x)) || "";
  openForm("note.add", {text: "", link: link});
}
function shareForm(){                                  // mesmo formulário da TUI (S exportar na árvore)
  const id = selId() || "", kind = id.startsWith("GOAL-") ? "goal" : /^PROJ-\d+$/.test(id) ? "project" : "status";
  openForm("share.export", {kind: kind, target: kind === "status" ? "" : id});
}
function planNew(){                                    // n na árvore: o que nasce depende do item (como a TUI)
  const M = window.BRAIN.M, id = selId() || "";
  const nextN = (ids, re) => Math.max(0, ...ids.map(x => (x.match(re) || [])[1]).filter(Boolean).map(Number)) + 1;
  const goal = M.goals.find(g => g.id === id), proj = M.projects.find(p => p.id === id);
  if (goal) return openForm("project.new", {nid: "PROJ-" + nextN(M.projects.map(p => p.id), /^PROJ-(\d+)$/), goal: goal.id, goal_title: goal.title});
  if (proj) return openForm("deliverable.new", {nid: proj.id + "." + nextN((proj.deliverables || []).map(d => d.id), /\.(\d+)$/),
    project: proj.id, project_title: proj.title});
  const dv = selEl() && selEl().dataset.deliv;
  if (dv) { const pr = M.projects.find(p => (p.deliverables || []).some(d => d.id === dv));
    return newAction({project: pr ? pr.id : "—", deliv: dv}); }
  return planGoal();
}
function planGoal(){ const M = window.BRAIN.M;
  const n = Math.max(0, ...M.goals.map(g => +(g.id.match(/^GOAL-(\d+)$/) || [0, 0])[1])) + 1;
  openForm("goal.new", {nid: "GOAL-" + n}); }
function mergeForm(a){ openForm("action.merge", {id: a.id, title: a.title, item: a}); }

// ── kanban de oportunidades: arrastar = brain opportunity status (laterais pedem motivo) ──
const OPP_LAT = ["em-espera", "descartada"];
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
      if (stage === "em-andamento" && !(o.promoted || o.project)) { toast(id + ": 'em-andamento' só existe depois de promover (tecla p, em qualquer nível)."); return; }
      if (OPP_LAT.includes(stage)) { statusPicker(o, stage); return; }      // laterais pedem motivo: o formulário da TUI
      runArgv([["opportunity", "status", id, stage, "--by", "owner"]]);
    });
  });
}

// ── kanban: botões rápidos + arrastar e soltar (ponte CLI) ──────────────
function colOf(a){ if (!a.open) return "fechada"; return ((a.blocked_by && a.blocked_by.length) || a.status === "bloqueada" || a.status === "aguardando") ? "aguardando" : a.status; }
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

// ── face Configurações: os passos da configuração guiada, revisitáveis ───────────────────────────
// Mesmos endpoints do /onboarding (/api/onboard/*): uma regra, duas portas de entrada. "feito" vem do
// estado real (state.setup), não da lista de passos vistos — pular não conta como feito.
const SETUP_STEPS = [["perfil", "Perfil"], ["rotina", "Rotina"], ["conectores", "Conectores"], ["memoria", "Memória"], ["integracoes", "Integrações"]];
const MEM_LABEL = {none: "nenhuma", lite: "embed", embed: "embed", full: "full"};   // a API ainda diz "lite"; a tela diz o nome da CLI
let SS = null, profileDraftCfg = null;
async function obApi(path, body){
  const o = {headers: {"X-Brain-Token": TOK}};
  if (body !== undefined) { o.method = "POST"; o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  const r = await fetch(path, o);
  let j = {};
  try { j = await r.json(); } catch (e) {}
  if (!r.ok || j.ok === false) throw new Error(j.error || ("erro " + r.status));
  return j;
}
const obAct = (name, body) => obApi("/api/onboard/" + name, body || {});
async function obJob(id, onTick){
  for (;;) {
    const j = (await obApi("/api/onboard/job/" + id)).job;
    if (onTick) onTick(j);
    if (j.status !== "running") return j;
    await new Promise(r => setTimeout(r, 1500));
  }
}
function stMsg(el, kind, text){ if (el) { el.className = "stmsg " + kind; el.textContent = text; } }
async function stBusy(btn, label, fn){
  const was = btn.innerHTML; btn.disabled = true; btn.textContent = label || "salvando…";
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = was; }
}
const stStatus = ok => ok ? '<span class="chip h-em-dia">feito</span>' : '<span class="stlater">depois</span>';
const fld = (label, input, hint) => '<label class="fld"><span>' + label + "</span>" + input + (hint ? "<small>" + hint + "</small>" : "") + "</label>";
const sec = (title, body, right) => '<section class="panel stsec"><div class="sthead"><h2>' + title + "</h2>" + (right || "") + "</div>" + body + "</section>";

async function wireSetup(step){
  const box = document.getElementById("setup");
  if (!box) return;
  if (!LIVE) {
    box.innerHTML = step === "memoria" ? "" : '<section class="panel"><p>Este painel foi aberto como arquivo (retrato). Para ver e mudar a configuração, abra o <b>Brain</b> pelo app — Aplicativos, Launchpad ou Spotlight.</p></section>';
    return;
  }
  try { await obState(); }
  catch (e) { box.innerHTML = '<section class="panel"><p class="late">Não consegui ler a configuração: ' + esc(e.message) + "</p></section>"; return; }
  if (!document.getElementById("setup") || document.getElementById("setup").dataset.step !== step) return;   // trocou de aba enquanto lia
  (SETUP[step] || (() => {}))(document.getElementById("setup"));
}
async function obState(){ SS = (await obApi("/api/onboard/state")).state; return SS; }
const redo = step => { const b = document.getElementById("setup"); if (b && b.dataset.step === step) SETUP[step](b); };

const SETUP = {};
SETUP.inicio = box => {
  const st = SS.setup || {}, n = SETUP_STEPS.filter(([k]) => st[k]).length;
  const conns = SS.connectors.filter(c => c.enabled).map(c => c.label);
  const detail = {
    perfil: [SS.owner.name, SS.owner.nickname].filter(Boolean).join(" · ") || "nome, apelido, sobre você",
    rotina: SS.routine.start && SS.routine.end ? SS.routine.start + "–" + SS.routine.end + " · " + SS.routine.timezone : "fuso e expediente",
    conectores: conns.length ? conns.join(", ") : "Slack, Gmail, Agenda…",
    memoria: st.memoria ? MEM_LABEL[SS.memory.mode] || SS.memory.mode : "nenhuma · embed · full",
    integracoes: SS.keys.GITHUB_TOKEN && SS.keys.GITHUB_TOKEN.set ? "GitHub configurado" : "token do GitHub",
  };
  box.innerHTML = '<div class="stbar"><span style="width:' + Math.round(n / SETUP_STEPS.length * 100) + '%"></span></div>' +
    '<section class="panel stlist">' + SETUP_STEPS.map(([k, t]) =>
      '<a class="strow" href="#cfg/' + k + '">' + stStatus(st[k]) + "<b>" + t + '</b><span class="muted">' + esc(detail[k]) + '</span><span class="stgo">›</span></a>').join("") + "</section>" +
    '<div class="stactions"><button class="btn" data-welcome>Rever boas-vindas</button><a class="btn" href="#projects">Goals e projetos em Execução</a></div>';
  box.querySelector("[data-welcome]").onclick = () => {
    try { localStorage.setItem("brain-onboarding-step", "inicio"); } catch (e) {}
    location.href = "/onboarding";
  };
};
SETUP.perfil = box => {
  const o = SS.owner, tpl = SS.profile.template;
  box.innerHTML = sec("Você", '<div class="stgrid">' +
      fld('Nome completo <span class="late">*</span>', '<input type="text" id="s-name" value="' + esc(o.name || o.suggested_name) + '" autocomplete="name">') +
      fld("Apelido", '<input type="text" id="s-nick" value="' + esc(o.nickname) + '" placeholder="como as pessoas te chamam">', "Ajuda a te achar nas transcrições.") +
      fld("Cargo", '<input type="text" id="s-role" value="' + esc(o.role) + '">') +
      fld("E-mail de trabalho", '<input type="email" id="s-email" value="' + esc(o.email) + '" autocomplete="email">', "Opcional: reconhece convites e e-mails seus.") +
      '</div><div class="stactions"><span class="stmsg" id="s-m1"></span><button class="btn primary" id="s-about">Salvar</button></div>') +
    sec("Sobre você", (tpl ? '<p class="muted">Ainda não há perfil. Escreva como se explicasse para um colega novo.</p>'
        : '<details class="stprof"><summary>Perfil atual</summary><pre>' + esc(SS.profile.text) + "</pre></details>" +
          '<p class="muted small">Escrever aqui gera um perfil novo, que substitui o atual. Você vê a prévia antes de salvar.</p>') +
      '<div id="s-form">' + fld("Sobre você", '<textarea id="s-ab" placeholder="Seu papel, seu time, pelo que você responde…"></textarea>') +
      fld("Como você trabalha", '<textarea id="s-how" placeholder="Rituais, reuniões fixas, como prefere receber informação…"></textarea>') +
      fld("O que importa agora", '<textarea id="s-foc" placeholder="As 2–3 coisas que mais pesam neste trimestre."></textarea>') +
      '<div class="stactions"><span class="stmsg" id="s-m2"></span><button class="btn" id="s-prev">Ver prévia</button></div></div>' +
      '<div id="s-pv" hidden><pre id="s-pvt"></pre><div class="stactions"><button class="btn" id="s-edit">Editar texto</button><span class="stmsg" id="s-m3"></span><button class="btn primary" id="s-save">Salvar perfil</button></div></div>');
  if (profileDraftCfg) { box.querySelector("#s-ab").value = profileDraftCfg.about; box.querySelector("#s-how").value = profileDraftCfg.how; box.querySelector("#s-foc").value = profileDraftCfg.focus; }
  const q = s => box.querySelector(s);
  q("#s-about").onclick = e => stBusy(e.currentTarget, "salvando…", async () => {
    const body = {name: q("#s-name").value, nickname: q("#s-nick").value, role: q("#s-role").value, email: q("#s-email").value};
    if (!body.name.trim()) return stMsg(q("#s-m1"), "late", "preencha o nome completo");
    try { await obAct("about", body); await obState(); stMsg(q("#s-m1"), "ok", "✓ salvo"); } catch (err) { stMsg(q("#s-m1"), "late", err.message); }
  });
  q("#s-prev").onclick = e => stBusy(e.currentTarget, "montando…", async () => {
    profileDraftCfg = {about: q("#s-ab").value, how: q("#s-how").value, focus: q("#s-foc").value};
    if (!(profileDraftCfg.about + profileDraftCfg.how + profileDraftCfg.focus).trim()) return stMsg(q("#s-m2"), "late", "escreva pelo menos um dos campos");
    try { const r = await obAct("profile_preview", profileDraftCfg); q("#s-pvt").textContent = r.markdown; q("#s-pv").dataset.md = r.markdown; q("#s-form").hidden = true; q("#s-pv").hidden = false; }
    catch (err) { stMsg(q("#s-m2"), "late", err.message); }
  });
  q("#s-edit").onclick = () => { q("#s-pv").hidden = true; q("#s-form").hidden = false; };
  q("#s-save").onclick = e => stBusy(e.currentTarget, "salvando…", async () => {
    try { await obAct("profile_save", {markdown: q("#s-pv").dataset.md, overwrite: !tpl}); profileDraftCfg = null; await obState(); redo("perfil"); toast("perfil salvo"); }
    catch (err) { stMsg(q("#s-m3"), "late", err.message); }
  });
};
SETUP.rotina = box => {
  const r = SS.routine, guess = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zones = Array.from(new Set([r.timezone, guess, "America/Sao_Paulo", "America/Argentina/Buenos_Aires", "America/Mexico_City", "America/Bogota",
    "America/Santiago", "America/Lima", "America/New_York", "Europe/Lisbon", "Europe/Madrid", "UTC"].filter(Boolean)));
  const lunch = (r.lunch || "12:00-13:00").split("-");
  box.innerHTML = sec("Expediente", fld("Fuso horário", '<select id="s-tz">' + zones.map(z => "<option" + (z === (r.timezone || guess) ? " selected" : "") + ">" + esc(z) + "</option>").join("") + "</select>") +
    '<div class="stgrid">' + fld("Começo", '<input type="time" id="s-st" value="' + esc(r.start) + '">') + fld("Fim", '<input type="time" id="s-en" value="' + esc(r.end) + '">') + "</div>" +
    '<label class="chk"><input type="checkbox" id="s-lon"' + (r.lunch !== "" ? " checked" : "") + "> Reservar horário de almoço</label>" +
    '<div class="stgrid" id="s-lunch">' + fld("Almoço — início", '<input type="time" id="s-ls" value="' + esc(lunch[0]) + '">') + fld("Almoço — fim", '<input type="time" id="s-le" value="' + esc(lunch[1] || "13:00") + '">') + "</div>" +
    '<div class="stactions"><span class="stmsg" id="s-m"></span><button class="btn primary" id="s-save">Salvar</button></div>');
  const q = s => box.querySelector(s), sync = () => { q("#s-lunch").hidden = !q("#s-lon").checked; };
  q("#s-lon").onchange = sync; sync();
  q("#s-save").onclick = e => stBusy(e.currentTarget, "salvando…", async () => {
    try { await obAct("routine", {timezone: q("#s-tz").value, start: q("#s-st").value, end: q("#s-en").value, lunch: q("#s-lon").checked ? q("#s-ls").value + "-" + q("#s-le").value : ""});
          await obState(); stMsg(q("#s-m"), "ok", "✓ salvo"); } catch (err) { stMsg(q("#s-m"), "late", err.message); }
  });
};
const CONN_ST = {connected: ["h-em-dia", "conectado"], auth: ["h-atencao", "precisa autorizar"], missing: ["", "não adicionado"], error: ["h-em-risco", "com erro"], unknown: ["", "não verificado"]};
SETUP.conectores = box => {
  const noClaude = !SS.claude_installed, perm = SS.permissions.ok;
  const rows = SS.connectors.map(c => {
    const [cls, label] = CONN_ST[SS.connectors_scanned ? c.status : "unknown"] || CONN_ST.unknown;
    const can = c.status === "connected" || c.enabled;
    return '<div class="stconn"><div><b>' + esc(c.label) + '</b><span class="muted small">' + esc(c.what) + '</span></div><span class="chip ' + cls + '">' + label + "</span>" +
      '<label class="chk" title="o Brain pode ler"><input type="checkbox" data-c="' + esc(c.key) + '"' + (c.enabled || c.status === "connected" ? " checked" : "") + (can ? "" : " disabled") + "> ler</label></div>";
  }).join("");
  box.innerHTML = sec("Seus conectores", (noClaude ? '<p class="late">O Claude Code não está instalado: é ele que lê as ferramentas para o Brain.</p>' : "") + rows +
      '<div class="stgrid" id="s-extra">' + fld("Canais do Slack para acompanhar", '<input type="text" id="s-slack" placeholder="#meu-time, #projeto-x">', "Separados por vírgula: entram como fontes novas.") +
      fld("Pasta do Drive (link)", '<input type="text" id="s-drive" placeholder="https://drive.google.com/drive/folders/…">', "Opcional.") + "</div>" +
      '<p class="muted small">Desligar um conector aqui faz o Brain parar de lê-lo. Conecte novos em <a href="https://claude.ai/settings/connectors" target="_blank" rel="noopener">claude.ai → Configurações → Conectores</a> e clique em verificar.</p>' +
      '<div class="stactions"><span class="stmsg" id="s-m"></span><button class="btn" id="s-scan"' + (noClaude ? " disabled" : "") + '>↻ verificar conexões</button><button class="btn primary" id="s-save">Salvar</button></div>') +
    sec("Permissões no computador", '<p>Pré-autoriza o Claude a ler esta pasta e usar as ferramentas de <b>leitura</b> dos conectores ligados. Segredos, livro-razão e envios continuam bloqueados.</p>' +
      '<div class="stactions"><span class="stmsg" id="s-mp"></span>' + (perm ? "" : '<button class="btn primary" id="s-perm">Liberar</button>') + "</div>",
      perm ? '<span class="chip h-em-dia">liberado</span>' : '<span class="chip h-atencao">pendente</span>');
  const q = s => box.querySelector(s);
  const extra = () => { const on = k => !!box.querySelector('[data-c="' + k + '"]:checked'); q("#s-slack").closest(".fld").hidden = !on("slack"); q("#s-drive").closest(".fld").hidden = !on("drive"); };
  box.querySelectorAll("[data-c]").forEach(i => i.onchange = extra); extra();
  q("#s-scan").onclick = e => stBusy(e.currentTarget, "verificando…", async () => {
    try { const r = await obAct("connectors_scan", {force: true});
          if (r.job) { const j = await obJob(r.job); if (j.status === "error") stMsg(q("#s-m"), "late", (j.result && j.result.error) || "não consegui verificar"); }
          await obState(); redo("conectores"); } catch (err) { stMsg(q("#s-m"), "late", err.message); }
  });
  q("#s-save").onclick = e => stBusy(e.currentTarget, "salvando…", async () => {
    const keys = Array.from(box.querySelectorAll("[data-c]:checked")).map(i => i.dataset.c);
    try { await obAct("connectors_enable", {connectors: keys, slack_channels: q("#s-slack").value, drive_folder: q("#s-drive").value});
          await obState(); redo("conectores"); toast("conectores salvos — o próximo /update já lê a lista nova"); } catch (err) { stMsg(q("#s-m"), "late", err.message); }
  });
  if (q("#s-perm")) q("#s-perm").onclick = e => stBusy(e.currentTarget, "liberando…", async () => {
    try { await obAct("permissions"); await obState(); redo("conectores"); } catch (err) { stMsg(q("#s-mp"), "late", err.message); }
  });
};
SETUP.memoria = box => {
  const m = SS.memory, cur = m.mode === "lite" ? "embed" : m.mode;
  let sel = cur;
  const opts = [["none", "Nenhuma", "Busca por palavras. Nada a instalar."], ["embed", "Embed", "Busca por significado — local (bge-m3) ou provedor de nuvem."],
    ["full", "Full", "Também extrai fatos e liga assuntos. Só-nuvem: LLM e embeddings de provedor, com as suas chaves e custo por uso."]];
  const embOpts = full => full ? [["fireworks", "Fireworks — Qwen3-Embedding-8B"], ["openai", "OpenAI — text-embedding-3-small"]]
    : [["local", "Local — LM Studio bge-m3 (nada sai)"], ["fireworks", "Fireworks — Qwen3-Embedding-8B"], ["openai", "OpenAI — text-embedding-3-small"]];
  const curEmb = full => embOpts(full).some(o => o[0] === m.emb_provider) ? m.emb_provider : (full ? "fireworks" : "local");
  const selHTML = (list, curv, id) => '<select id="' + id + '">' + list.map(o => '<option value="' + o[0] + '"' + (o[0] === curv ? " selected" : "") + ">" + esc(o[1]) + "</option>").join("") + "</select>";
  const keyChip = ok => ok ? ' <span class="chip h-em-dia">já salva</span>' : "";
  const keyInp = id => '<input type="password" id="' + id + '" autocomplete="off" placeholder="cole a chave">';
  const draw = () => {
    box.innerHTML = sec("Modo", '<div class="stopts">' + opts.map(([k, t, d]) => '<button class="stopt' + (k === sel ? " sel" : "") + '" data-m="' + k + '"><b>' + t + (k === cur ? ' <span class="chip h-info">atual</span>' : "") + "</b><span>" + d + "</span></button>").join("") + "</div>" +
      (sel !== "none" ? '<p class="small">' + (m.docker ? '<span class="ok">✓</span>' : '<span class="late">✗</span>') + " OrbStack (o banco da memória)" +
        '<span id="s-lms"' + (sel === "embed" ? "" : " hidden") + '> · ' + (m.lmstudio ? '<span class="ok">✓</span>' : '<span class="late">✗</span>') + " LM Studio com <code>text-embedding-bge-m3</code> (só no embeddings local)</span></p>" : "") +
      (sel === "embed" ? '<div class="stgrid">' + fld("Embeddings", selHTML(embOpts(false), curEmb(false), "s-emb")) +
        '<div id="s-ekey-wrap"' + (curEmb(false) === "local" ? " hidden" : "") + ">" + fld("API key do embeddings" + keyChip(m.emb_key), keyInp("s-ekey"), "Fireworks ou OpenAI, conforme o escolhido.") + "</div></div>" +
        '<p class="small" id="s-egress"' + (curEmb(false) === "local" ? " hidden" : "") + '>☁ com provedor de nuvem, o texto do vault vai à API para virar vetores.</p>' : "") +
      (sel === "full" ? '<div class="stgrid">' +
        fld("LLM", '<select id="s-prov"><option value="anthropic"' + (m.llm_provider === "openai" ? "" : " selected") + '>Anthropic (Claude) — Haiku/Sonnet por operação</option><option value="openai"' + (m.llm_provider === "openai" ? " selected" : "") + ">OpenAI</option></select>") +
        '<div id="s-model-wrap"' + (m.llm_provider === "openai" ? "" : " hidden") + ">" + fld("Modelo do LLM", '<input type="text" id="s-model" placeholder="gpt-… (exigido no OpenAI)">') + "</div>" +
        fld("Embeddings", selHTML(embOpts(true), curEmb(true), "s-emb")) +
        fld("API key (LLM)" + keyChip(m.llm_key), keyInp("s-key")) +
        '<div id="s-ekey-wrap">' + fld("API key do embeddings" + keyChip(m.emb_key), keyInp("s-ekey"), "Fireworks ou OpenAI — conta própria do embeddings.") + "</div></div>" +
        '<p class="small" id="s-samekey" hidden>LLM e embeddings no OpenAI: a mesma chave serve nos dois.</p>' +
        '<label class="chk"><input type="checkbox" id="s-consent"> Entendo que trechos do vault vão à API dos provedores, com as minhas chaves, e que isso tem custo por uso.</label>' : "") +
      '<pre class="stlog" id="s-log" hidden></pre><div class="stactions"><span class="stmsg" id="s-m"></span><button class="btn primary" id="s-apply"' + (sel === cur && sel !== "full" ? " disabled" : "") + ">Aplicar</button></div>");
    const q = s => box.querySelector(s);
    box.querySelectorAll("[data-m]").forEach(b => b.onclick = () => { sel = b.dataset.m; draw(); });
    const sync = () => {
      if (sel === "embed" && q("#s-emb")) {
        const cloud = q("#s-emb").value !== "local";
        if (q("#s-ekey-wrap")) q("#s-ekey-wrap").hidden = !cloud;
        if (q("#s-egress")) q("#s-egress").hidden = !cloud;
        if (q("#s-lms")) q("#s-lms").hidden = !q("#s-emb") || q("#s-emb").value !== "local";
      } else if (sel === "full" && q("#s-emb")) {
        const openai = q("#s-prov") && q("#s-prov").value === "openai";
        if (q("#s-model-wrap")) q("#s-model-wrap").hidden = !openai;
        const same = openai && q("#s-emb").value === "openai";
        if (q("#s-ekey-wrap")) q("#s-ekey-wrap").hidden = same;
        if (q("#s-samekey")) q("#s-samekey").hidden = !same;
      }
    };
    if (q("#s-emb")) q("#s-emb").onchange = sync;
    if (q("#s-prov")) q("#s-prov").onchange = sync;
    sync();
    q("#s-apply").onclick = e => stBusy(e.currentTarget, "aplicando…", async () => {
      const body = {mode: sel};
      if (sel === "embed") {
        body.embeddings = q("#s-emb").value; body.key = q("#s-ekey") ? q("#s-ekey").value : "";
        if (body.embeddings !== "local" && !body.key && !m.emb_key) return stMsg(q("#s-m"), "late", "cole a API key do embeddings");
      } else if (sel === "full") {
        body.provider = q("#s-prov").value; body.model = q("#s-model") ? q("#s-model").value.trim() : "";
        body.embeddings = q("#s-emb").value; body.key = q("#s-key").value;
        body.emb_key = q("#s-ekey") ? q("#s-ekey").value : ""; body.consent = q("#s-consent").checked;
        if (!body.consent) return stMsg(q("#s-m"), "late", "marque o aceite de envio à API");
        if (!body.key && !m.llm_key) return stMsg(q("#s-m"), "late", "cole a API key do LLM");
        if (body.provider === "openai" && !body.model) return stMsg(q("#s-m"), "late", "digite o modelo do OpenAI");
        const sameAcct = body.provider === "openai" && body.embeddings === "openai";
        if (!sameAcct && !body.emb_key && !m.emb_key) return stMsg(q("#s-m"), "late", "cole a API key do embeddings (" + (body.embeddings === "fireworks" ? "Fireworks" : "OpenAI") + ")");
      }
      try {
        const r = await obAct("memory", body);
        if (q("#s-key")) q("#s-key").value = "";
        if (q("#s-ekey")) q("#s-ekey").value = "";
        if (r.job) { const log = q("#s-log"); log.hidden = false;
          const j = await obJob(r.job, jj => { log.textContent = (jj.log || []).join("\n"); log.scrollTop = 1e9; });
          if (j.status === "error") return stMsg(q("#s-m"), "late", (j.result && j.result.error) || "não consegui mudar a memória"); }
        await obState(); toast("memória: modo " + (MEM_LABEL[SS.memory.mode] || SS.memory.mode)); SETUP.memoria(box);
      } catch (err) { stMsg(q("#s-m"), "late", err.message); }
    });
  };
  draw();
};
SETUP.integracoes = box => {
  const gh = SS.keys.GITHUB_TOKEN || {};
  box.innerHTML = sec("Sugestões e bugs do Brain", '<p>Com um token do GitHub, as sugestões que você manda pelo Brain viram issues públicas no repo do framework. <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">Criar token →</a></p>' +
      fld("Token do GitHub", '<input type="password" id="s-gh" autocomplete="off" placeholder="' + (gh.set ? "vazio mantém o atual" : "github_pat_…") + '">') +
      '<div class="stactions"><span class="stmsg" id="s-m"></span><button class="btn primary" id="s-save">Salvar</button></div>', stStatus(gh.set).replace("feito", "configurado")) +
    sec("Blocos de foco no Google Calendar", '<p>Por padrão o Brain gera um arquivo de calendário (.ics) que você importa com um clique. A escrita direta na agenda pede uma autorização separada do Google: peça ao Brain no chat, "configurar foco no Google".</p>');
  const q = s => box.querySelector(s);
  q("#s-save").onclick = e => stBusy(e.currentTarget, "salvando…", async () => {
    const v = q("#s-gh").value.trim();
    if (!v) return stMsg(q("#s-m"), "late", "cole o token");
    try { await obAct("keys", {GITHUB_TOKEN: v}); q("#s-gh").value = ""; await obState(); redo("integracoes"); toast("token salvo no config/.env"); }
    catch (err) { stMsg(q("#s-m"), "late", err.message); }
  });
};

// ── face Configurações: troca de provedor da memória (mesma linha do CLI; sem campos condicionais:
//    um select por slot, "manter" nos que não mudam — o preview monta só a linha do slot escolhido) ──
function wireCfgMemoria(){
  const b = document.querySelector("[data-provform]");
  if (b) b.onclick = () => provForm();
  document.querySelectorAll("#view [data-hw]").forEach(btn => {
    btn.onclick = () => runCommand("brain memory harness install " + btn.dataset.hw, m => {
      const x = (m.harnesses || []).find(y => y.name === btn.dataset.hw);
      if (x) x.wired = true;                       // otimista: o refresh da ponta confirma
    });
  });
  const v = document.querySelector("[data-hwverify]");
  if (v) v.onclick = () => runCommand("brain memory harness verify", () => {});
}

function provForm(){
  const cur = ((window.BRAIN.M.providers || {}).embeddings || {}).provider || "local";
  openForm("memory.provider", {provider: cur});
}

window.afterRoute = function(view){
  if (location.hash.startsWith("#focus")) wireFocus();
  if (location.hash.startsWith("#pf/opps")) wireOppKanban();
  if (location.hash.startsWith("#ask")) wireAskPage();
  if (location.hash.startsWith("#cfg/memoria")) wireCfgMemoria();
  if (document.getElementById("setup")) wireSetup(document.getElementById("setup").dataset.step);
  if (location.hash.startsWith("#cfg/saude")) {
    const head = document.querySelector("#view .pagehead");
    if (head && !head.querySelector(".planbtns")) { const row = document.createElement("div"); row.className = "planbtns";
      const b = document.createElement("button"); b.className = "btn"; b.textContent = "↻ testar online";
      b.onclick = () => runCommand("brain doctor --online"); row.appendChild(b); head.appendChild(row); }
  }
  wireP0();
  if (LF.key !== lfKey()) { LF.key = lfKey(); LF.draft = null; }   // outra página: o campo aberto não vai junto; os filtros aplicados de cada página ficam
  collectSel();
  if (lfLevels().length || LF.draft !== null) lfApply();           // re-render da mesma página (ponte): reaplica sem perder o que se digitava
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
        closeForm(a);                                    // diálogo com "como foi" + resultado, como a TUI
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
const SEL_QUERY = "#view .kanban .card, #view .pf-kanban .pf-card, #view table tbody tr, #view .blk.prop, #view .msgrow, #view ul.feed li, #view li[data-deliv]";
const selable = el => el.querySelector('a[href^="#"]') || el.classList.contains("blk") || el.classList.contains("pf-card") || el.hasAttribute("data-deliv") || el.hasAttribute("data-sel");
function collectSel(){
  SEL.items = [...document.querySelectorAll(SEL_QUERY)].filter(selable).filter(el => !el.classList.contains("flt-off"));   // filtrado some da navegação j/k
  SEL.i = -1; paintSel();
  SEL.items.forEach(el => { if (el._selWired) return; el._selWired = true;                      // o filtro recoleta a cada tecla: ligar o mouse uma vez só
    el.addEventListener("mouseenter", () => { const n = SEL.items.indexOf(el); if (n >= 0) { SEL.i = n; paintSel(); } }); });
}

// ── filtro de lista em cascata ("/", como a TUI) ────────────────────────
// "/" abre um filtro sobre a lista da página; "/" de novo abre OUTRO, que refina o que sobrou do primeiro.
// Esc dentro do campo desfaz só aquele filtro; Esc na página tira o último aplicado, um por vez.
// Cada página lembra os seus (como a TUI lembra por aba); a barra no topo mostra a corrente inteira.
const LF = {map: {}, draft: null};
const lfKey = () => location.hash.slice(1).split("?")[0] || "home";
const lfLevels = () => LF.map[lfKey()] || (LF.map[lfKey()] = []);
const lfCands = () => [...document.querySelectorAll(SEL_QUERY)].filter(selable);
function lfText(el){
  if (el._lft == null) {
    const c = el.cloneNode(true);
    c.querySelectorAll(".qa, button, script, style").forEach(x => x.remove());                  // rótulos de botão não são conteúdo da linha
    el._lft = norm(c.textContent);
  }
  return el._lft;
}
function lfApply(){
  const all = [...lfLevels(), ...(LF.draft ? [LF.draft] : [])].map(norm).filter(Boolean);
  const cands = lfCands();
  cands.forEach(el => el.classList.toggle("flt-off", !all.every(f => lfText(el).includes(f))));
  document.querySelectorAll("#view .col").forEach(col => {                                      // contador da coluna acompanha o corte
    const n = col.querySelector("h3 .count"); if (!n) return;
    if (n.dataset.n0 == null) n.dataset.n0 = n.textContent;
    n.textContent = all.length ? col.querySelectorAll(".card:not(.flt-off)").length : n.dataset.n0;
  });
  collectSel();
  lfRender(cands.length, cands.filter(el => !el.classList.contains("flt-off")).length);
}
function lfRender(total, shown){
  let bar = document.getElementById("lfbar");
  const levels = lfLevels(), editing = LF.draft !== null;
  if (!levels.length && !editing) { if (bar) bar.remove(); renderKeyBar(); return; }
  const view = document.getElementById("view");
  if (!bar) { bar = document.createElement("div"); bar.id = "lfbar"; bar.className = "lfbar"; view.prepend(bar); }
  if (total == null) { const c = lfCands(); total = c.length; shown = c.filter(el => !el.classList.contains("flt-off")).length; }
  const chips = levels.map((f, i) => '<span class="lfchip" title="tirar este filtro"><b>' + esc(f) + '</b><button data-x="' + i + '" aria-label="tirar o filtro ' + esc(f) + '">×</button></span>');
  const typing = editing ? '<input id="lfin" type="text" autocomplete="off" spellcheck="false" placeholder="' +
    (levels.length ? "refinar o que sobrou…" : "texto, id ou projeto") + '" value="' + esc(LF.draft) + '">' : "";
  bar.innerHTML = '<span class="lflab">⌕ filtro' + (levels.length > 1 ? "s" : "") + '</span>' + chips.concat(typing ? [typing] : []).join('<span class="lfsep">›</span>') +
    '<span class="lfcount' + (shown ? "" : " none") + '">' + (shown ? shown + " de " + total : "nada encontrado — “não consta”") + '</span>' +
    '<span class="lfhint">' + (editing ? "enter mantém · esc desfaz só este filtro" : "esc tira o último · / refina") + "</span>";
  bar.querySelectorAll("[data-x]").forEach(b => b.onclick = () => { lfLevels().splice(+b.dataset.x, 1); lfApply(); });
  const inp = bar.querySelector("#lfin");
  if (inp) {
    if (document.activeElement !== inp) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
    inp.oninput = () => { LF.draft = inp.value; lfApply(); };
    inp.onkeydown = ev => {
      if (ev.key === "Enter" || ev.key === "Escape") {
        ev.preventDefault(); ev.stopPropagation();
        const v = ev.key === "Enter" ? inp.value.trim() : "";
        LF.draft = null; if (v) lfLevels().push(v);
        inp.blur(); lfApply();
      }
    };
  }
  renderKeyBar();
}
function lfOpen(){
  if (!lfCands().length && !lfLevels().length) { toast("nada para filtrar nesta página"); return; }
  LF.draft = ""; lfApply();
}
function lfPop(){                                   // esc na página: tira o último filtro aplicado (ou fecha o campo que ficou aberto)
  if (LF.draft !== null) { LF.draft = null; lfApply(); return true; }
  const l = lfLevels(); if (!l.length) return false;
  l.pop(); lfApply(); return true;
}
function paintSel(){ SEL.items.forEach((el, i) => el.classList.toggle("kbd-sel", i === SEL.i)); if (typeof renderKeyBar === "function") renderKeyBar(); }
function selEl(){ return SEL.items[SEL.i] || null; }
function selMove(d){ if (!SEL.items.length) return; SEL.i = (SEL.i + d + SEL.items.length) % SEL.items.length; paintSel(); selEl().scrollIntoView({block: "nearest"}); }
function selOpen(){
  const el = selEl(); if (!el) return;
  if (el.classList.contains("blk")) { el.click(); return; }
  if (el.dataset.sel && el.dataset.sel.startsWith("doc:")) {          // Documentos: enter abre o link (ou diz onde está no vault)
    if (el.dataset.url) window.open(el.dataset.url, "_blank", "noopener"); else toast("documento do vault: " + (el.children[2] ? el.children[2].textContent : ""));
    return; }
  const a = el.querySelector('a[href^="#"]'); if (a) location.hash = a.getAttribute("href");
}
function selId(){
  const el = selEl(); if (!el) return null;
  if (el.dataset.opp) return el.dataset.opp;
  if (el.dataset.sel) return el.dataset.sel;
  const i = el.querySelector(".idchip");
  if (i) return i.textContent.trim();
  const pa = el.querySelector('a[href^="#person/"]');              // lista de Pessoas: a linha não tem chip de id, o link tem
  return pa ? decodeURIComponent(pa.getAttribute("href").slice(8)) : null;
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
// openForm: o formulário <id> de brainlib/forms.py (M.forms) — campos, rótulos, obrigatórios, quando cada um aparece,
// validação, dicas e a linha `brain …` saem da MESMA especificação da TUI (forms.js). Aqui só se desenha.
// opts: {values: valor inicial por cima do da especificação, extra: html fixo acima dos campos, help()→html,
//        wrap(cmds, v)→cmds (passos só do painel), run(v, m): mutação otimista do modo retrato}
function openForm(id, ctx, opts){
  opts = opts || {}; ctx = ctx || {};
  const M = window.BRAIN.M, F = window.BRAIN_FORMS, fm = (M.forms || {})[id];
  if (!fm) { toast("formulário " + id + " indisponível nesta página"); return; }
  const init = Object.assign(F.initial(fm, ctx, M), opts.values || {});
  const opt = (f, v) => F.options(f, M, v, ctx);
  const optHTML = (f, v, cur) => { const ops = opt(f, v), val = ops.some(o => o[0] === cur) ? cur : (ops[0] ? ops[0][0] : "");
    return ops.map(o => '<option value="' + esc(o[0]) + '"' + (o[0] === val ? " selected" : "") + ">" + esc(o[1]) + "</option>").join(""); };
  const rows = fm.fields.map(f => {
    const lab = esc(F.label(f, M)) + (f.req ? ' <span class="req">*</span>' : ""), ph = F.fmt(f.ph || "", ctx), val = init[f.id] || "";
    const ctl = f.choices !== undefined ? '<select data-k="' + f.id + '">' + optHTML(f, init, val) + "</select>"
      : f.multi ? '<textarea data-k="' + f.id + '" rows="5"' + (ph ? ' placeholder="' + esc(ph) + '"' : "") + ">" + esc(val) + "</textarea>"
      : '<input data-k="' + f.id + '" type="' + (f.secret ? "password" : "text") + '" value="' + esc(val) + '"' +
        (ph ? ' placeholder="' + esc(ph) + '"' : "") + (f.suggest ? ' list="dl_' + f.id + '"' : "") + ">" +
        (f.suggest ? '<datalist id="dl_' + f.id + '">' + opt(f, init).map(o => '<option value="' + esc(o[0]) + '">' + esc(o[1]) + "</option>").join("") + "</datalist>" : "");
    return '<div data-row="' + f.id + '"><div class="frow"><label>' + lab + "</label>" + ctl + "</div>" +
      '<div class="note-s fhint" data-hint="' + f.id + '" style="margin:-4px 0 8px 130px"></div></div>'; }).join("");
  const title = F.fmt(fm.title, ctx), sub = F.fmt(fm.sub || "", ctx);
  const ov = document.createElement("div"); ov.className = "pal-back open";
  ov.innerHTML = '<div class="palette"><div class="pin"><b>' + esc(title) + "</b>" + (fm.gate ? ' <span class="gatebadge">gate — precisa do seu ok literal</span>' : "") + "</div>" +
    '<div class="pal-confirm open" style="display:block;border-top:0;padding:14px 16px;max-height:70vh;overflow:auto">' +
    (sub ? '<p class="note-s" style="margin:0 0 10px">' + esc(sub) + "</p>" : "") + (opts.extra || "") + rows +
    '<div class="cline" data-preview style="min-height:34px;white-space:pre"></div>' +
    '<div class="note-s" data-err style="margin:0 0 6px;color:var(--risk)"></div>' +
    '<div class="row"><span class="note-s">mesma linha que a TUI roda · ' + (fm.fields.some(f => f.multi) ? "ctrl+enter" : "enter") + " confirma · esc cancela</span>" +
    (opts.help ? '<button class="btn ghost" data-help>? orientações</button>' : "") +
    '<button class="btn ghost" data-x>cancelar</button><button class="btn primary" data-ok>' + (fm.gate ? "aprovar" : fm.fields.length ? "executar" : "confirmar") + "</button></div></div></div>";
  document.body.appendChild(ov); dlgOpen = true;
  let h2 = null;
  const close = () => { ov.remove(); dlgOpen = false; if (h2) document.removeEventListener("keydown", h2, true); };
  const el = k => ov.querySelector('[data-k="' + k + '"]');
  const vals = () => { const v = {}; fm.fields.forEach(f => { const e = el(f.id); v[f.id] = e ? e.value : ""; }); return v; };
  const paint = () => {
    const v = vals(), hid = F.hidden(fm, v, ctx, M), w = F.values(fm, v, ctx, M);
    fm.fields.forEach(f => { const row = ov.querySelector('[data-row="' + f.id + '"]'); row.hidden = hid.has(f.id);
      const h = ov.querySelector('[data-hint="' + f.id + '"]'); h.textContent = f.hint && w[f.id] ? F.hint(f.hint, w[f.id], w, ctx, M) : ""; });
    ov.querySelector("[data-preview]").textContent = "$ " + F.display(F.formArgv(fm, v, ctx, M)).replace(/\n/g, "\n$ ");
    ov.querySelector("[data-err]").textContent = "";
  };
  const changed = id0 => {
    fm.fields.filter(f => f.depends === id0 && f.choices !== undefined).forEach(f => { const e = el(f.id); e.innerHTML = optHTML(f, vals(), e.value); });
    fm.fields.filter(f => f.fill && f.fill[0] === id0).forEach(f => { const nv = F.FILL[f.fill[1]](vals()), e = el(f.id);
      if (nv !== undefined && e) e.value = nv; });
    paint();
  };
  const submit = () => {
    const v = vals(), msg = F.missing(fm, v, ctx, M);
    if (msg) { ov.querySelector("[data-err]").textContent = msg; const p = ov.querySelector("[data-preview]");
      p.classList.add("miss"); setTimeout(() => p.classList.remove("miss"), 600); return; }
    let cmds = F.formArgv(fm, v, ctx, M); if (opts.wrap) cmds = opts.wrap(cmds, F.values(fm, v, ctx, M));
    close();
    runArgv(cmds, m => opts.run && opts.run(F.values(fm, v, ctx, M), m));
  };
  ov.querySelectorAll("[data-k]").forEach(e => { e.addEventListener("input", () => changed(e.dataset.k));
    if (e.tagName === "SELECT") e.addEventListener("change", () => changed(e.dataset.k));
    e.addEventListener("keydown", ev => { if (ev.key === "Enter" && (e.tagName !== "TEXTAREA" || ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); submit(); } }); });
  paint();
  if (opts.help) {                       // ? abre as orientações mesmo com o foco num select
    h2 = ev => { if (ev.key !== "?" || document.querySelector(".help-stack") || /input|textarea/i.test(ev.target.tagName || "")) return;
      ev.preventDefault(); ev.stopPropagation(); stackHelp("Metodologia · ICE", opts.help()); };
    document.addEventListener("keydown", h2, true);
    ov.querySelector("[data-help]").onclick = () => stackHelp("Metodologia · ICE", opts.help());
  }
  ov.querySelector("[data-x]").onclick = close;
  ov.onclick = e => { if (e.target === ov) close(); };
  ov.querySelector("[data-ok]").onclick = submit;
  const first = ov.querySelector("input,select,textarea"); if (first) first.focus(); else ov.querySelector("[data-ok]").focus();
}
// comandos da especificação: em sequência no modo vivo (para no primeiro que falhar); no retrato, a linha vai copiada
async function runArgv(cmds, mut){
  const lines = cmds.map(c => "brain " + window.BRAIN_FORMS.shjoin(c));
  if (!LIVE) { offlineCmd(lines.join(" && ")); return; }
  for (const ln of lines) { if (!(await serveRun(ln))) return; }
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

// lista mine é sempre do dono do Brain: escolher mine preenche o dono com você; sair de mine limpa só o que era você

// ── editar entidades (tecla e nas fichas, como a TUI) ───────────────────
const A_OF = id => window.BRAIN.M.actions.find(x => x.id === id);
function editAction(a){ openForm("action.edit", {id: a.id, title: a.title, item: a}); }
function newAction(pre){
  pre = pre || {};
  const M = window.BRAIN.M, ficha = M.people.find(x => x.id === M.owner.id);
  const lst = (new URLSearchParams(location.hash.split("?")[1] || "").get("l")) || "mine";
  const deliv = pre.deliv || "", proj = pre.project || "—";
  openForm("action.new", {list: lst, owner: lst === "mine" ? "eu" : "", deliv: deliv, project: proj, item: {project: proj},
    in_deliv: deliv ? " em " + deliv : ""},
    {extra: ficha ? "" : '<p class="note-s late">⚠ a ficha do dono (' + esc(M.owner.id) + ") não existe — o CLI vai recusar até registrar</p>"});
}
function personAliasForm(pe){ openForm("person.alias", {id: pe.id}); }
function editPerson(pe){ openForm("person.edit", {id: pe.id, item: pe}); }
function editOpp(o){ openForm("opportunity.edit", {id: o.id, item: o}); }
// ── ICE: dropdowns do rubric (fonte única: portfolio.ice_rubric do view model) ──
function oppAddForm(pref){                            // pré-fill: {area, process} p/ "nova opp a partir do processo"
  if (!needArea()) return;
  openForm("opportunity.new", {item: Object.assign({}, pref || {})});
}
function confirmIce(o){                              // ICE sugerido vira firme com as notas sugeridas
  runCommand("brain opportunity score " + o.id + " --impact " + o.impact + " --confidence " + o.confidence + " --ease " + o.ease,
    m => { const x = m.portfolio.opportunities.find(y => y.id === o.id); x.ice_suggested = false; });
}
function iceForm(o){
  openForm("opportunity.score", {id: o.id, item: o, ice_reason: o.ice_suggested && o.ice_reason ? " Sugestão do agente: " + o.ice_reason : ""},
    {help: () => iceHelpHTML()});
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
function editProc(pc){ openForm("process.edit", {id: pc.id, item: pc}); }
function editPlanNode(kind, id, node){                 // goal/projeto: gate estrutural · entregável: sem gate
  const ctx = {id: id, item: node};
  if (id.includes(".")) openForm("deliverable.edit", ctx);
  else if (kind === "goal") openForm("goal.edit", ctx);
  else openForm("project.edit", ctx);
}
function promoteDialog(o){ openForm("opportunity.promote", {id: o.id, item: o}); }
function statusPicker(o, status){ openForm("opportunity.status", {id: o.id, title: o.title, item: o}, status ? {values: {status: status}} : {}); }
function supersedeForm(d){ openForm("decision.supersede", {id: d.id, title: d.title}); }

// ── lacunas de paridade com a TUI: documentos, evidência, quem é…?, fontes, correção de saúde ──
function docLinkForm(target){ openForm("doc.link", target ? {target: target, target_fixed: true} : {target: ""}); }
function docUnlinkForm(target, n){
  const x = window.BRAIN.PROC[target] || window.BRAIN.OPP[target]; const d = x && x.docs[n]; if (!d) { needSel(); return; }
  openForm("doc.unlink", {target: target, ref: d.ref, doc_title: d.title || d.ref});
}
function evidenceForm(o){ openForm("opportunity.evidence", {id: o.id}); }
function resolveForm(){ openForm("person.resolve"); }
function srcAddForm(pre){ openForm("watch.add", {item: pre || {}}); }
function srcEditForm(old){ openForm("watch.edit", {key0: old.key, item: old}); }
function srcRemoveForm(s){ openForm("watch.remove", {key: s.key}); }
function agentToast(what, how){ toast("(agente) " + what + " — rode " + how + " no chat; o painel não roda o agente"); }
function healthFix(fix){
  if (fix.agent === "dump") agentToast("processar a inbox", "/dump");
  else if (fix.agent === "connect") agentToast("puxar " + fix.key, "/connect " + fix.key);
  else if (fix.sys) toast("agendar o noturno: no terminal, “schedule install --time 05:00” (pelo ./brain)");
  else if (fix.page) location.hash = "#" + fix.page;
}
function toggleAllParam(){
  const parts = location.hash.slice(1).split("?"), qs = new URLSearchParams(parts[1] || "");
  qs.get("a") === "1" ? qs.delete("a") : qs.set("a", "1");
  location.hash = parts[0] + (qs.toString() ? "?" + qs.toString() : "");
}
const docUrl = r => window.BRAIN.docUrl(r);
const hashAll = () => new URLSearchParams((location.hash.split("?")[1]) || "").get("a") === "1";

// ── mapa de teclas por contexto (espelha ctx_keys da TUI) ───────────────
function ctxKeys(k){
  const h = location.hash, M = window.BRAIN.M;
  const selTask = () => { const id = selId(); const a = id && id.startsWith("TASK-") ? A_OF(id) : null; if (!a) needSel(); return a; };
  const selOpp = () => { const id = selId(); const o = id && id.startsWith("OPP-") ? M.portfolio.opportunities.find(x => x.id === id) : null; if (!o) needSel(); return o; };
  const selDec = () => { const id = selId(); const d = id && id.startsWith("DEC-") ? M.decisions.find(x => x.id === id) : null; if (!d) needSel(); return d; };
  const goOrSel = (hash, fn) => { const el = selEl(); if (el && (fn || true) && SEL.i >= 0 && fn) fn(); else location.hash = hash; };

  if (k === "T" && /^#(ask|outbox|feedback)/.test(h)) { toggleAllParam(); return true; }     // só abertas ↔ todas
  if (h.startsWith("#home")) {
    if (k === "n") { noteForm(); return true; }
    const AG = {u: ["atualizar tudo", "/update"], d: ["processar a inbox", "/dump"], b: ["brief do dia", "/brief"], c: ["puxar uma fonte", "/connect <fonte>"], i: ["primeira entrevista", "/init"]};
    if (AG[k]) { agentToast(AG[k][0], AG[k][1]); return true; }
    return false; }
  if (h.startsWith("#sources")) {
    if (k === "n") { srcAddForm(); return true; }
    const sid = selId() || "", src = sid.startsWith("src:") ? (M.sources || []).find(x => x.key === sid.slice(4)) : null;
    if (k === "u") { agentToast("atualizar tudo", "/update"); return true; }
    if (!["e", "d", "w", "c"].includes(k)) return false;
    if (!src) { needSel(); return true; }
    if (k === "e") { if (src.in_watch) srcEditForm(src); else toast(src.key + " é pull avulso — w inclui no watch.toml"); return true; }
    if (k === "d") { if (src.in_watch) srcRemoveForm(src); else toast(src.key + " não está no watch.toml"); return true; }
    if (k === "w") { if (!src.in_watch) srcAddForm({key: src.key}); else toast(src.key + " já está no watch.toml"); return true; }
    agentToast("puxar " + src.key, "/connect " + src.key); return true; }
  if (h.startsWith("#projects")) {
    if (k === "n") { planNew(); return true; }
    if (k === "G") { planGoal(); return true; }
    if (k === "E") { toast("mudança livre no goals.md: E na TUI abre o editor e mostra o diff (gate) — aqui, n cria e e edita o item"); return true; }   // E = mudar árvore: o gate estrutural mora no formulário   // G = novo goal: o gate estrutural mora no formulário
    if (k === "P") { const id = selId() || "";
      if (id.startsWith("GOAL-")) progressForm(id);
      else if (id) toast("P declara progresso de goal — selecione um goal");
      else needSel();
      return true; }
    if (k === "S") { shareForm(); return true; }
    return false; }
  if (h.startsWith("#todo") || h.startsWith("#action/")) {
    const a = h.startsWith("#action/") ? A_OF(decodeURIComponent(h.slice(8))) : null;
    if (k === "D") k = "d";                                // teclas antigas (2.10): ainda valem, escondidas
    if (k === "a" && h.startsWith("#todo")) k = "T";
    if (k === "n" && h.startsWith("#todo")) { newAction(); return true; }
    if (["v", "O", "T"].includes(k) && h.startsWith("#todo")) {        // vista · ordem · todas: da página, não do cartão
      const qs = new URLSearchParams((location.hash.split("?")[1]) || "");
      if (k === "v") { const order = ["todas", "semana", "depois", "nao-agora"];
        const cur = qs.get("v") || "todas"; qs.set("v", order[(order.indexOf(cur) + 1) % order.length]); }
      if (k === "O") qs.set("o", (qs.get("o") || "prazo") === "prazo" ? "id" : "prazo");
      if (k === "T") qs.get("a") === "1" ? qs.delete("a") : qs.set("a", "1");
      location.hash = "todo" + (qs.toString() ? "?" + qs.toString() : "");
      return true; }
    const t = a || selTask(); if (!t) return k === "n";
    const mut = ["e", "c", "s", "t", "d", "z"];          // como o TUI: mutação só em ação aberta
    if (mut.includes(k) && !t.open) { toast(t.id + " está " + (t.status === "descartada" ? "descartada" : "fechada") + " — reabra com o antes"); return true; }
    if (k === "e") { editAction(t); return true; }
    if (k === "M") { mergeForm(t); return true; }
    if (k === "c") { closeForm(t); return true; }
    if (k === "s") {
      if (t.blocked_by && t.blocked_by.length) { toast(t.id + " segue bloqueada por " + t.blocked_by.join(", ")); return true; }
      const next = {aberta: "fazendo", fazendo: "aguardando", aguardando: "aberta"}[t.status] || "aberta";
      runCommand("brain action update " + t.id + " --status " + next, m => { A_OF(t.id).status = next; }); return true; }
    if (k === "t") { openForm("action.due", {id: t.id, title: t.title, item: t, due_sub: t.due_suggested
      ? "Prazo sugerido pelo agente (roxo): salve com a mesma data para confirmar, ou digite outra." : "Deixe em branco para remover o prazo."}); return true; }
    if (k === "d") { openForm("action.drop", {id: t.id, title: t.title, item: t}); return true; }
    if (k === "z") { const park = !t.parked;
      runCommand("brain action update " + t.id + (park ? " --park" : " --unpark"), m => { A_OF(t.id).parked = park; }); return true; }
    if (k === "o" && !t.open) { reopenForm(t); return true; }
    if (k === "m") { const w = (t.open && t.list === "waiting") ? t : null;
      if (w) chaseDraft(w); else toast("m cobrar: selecione uma ação aguardando outra pessoa (waiting)"); return true; }
    return mut.includes(k) || k === "o" || k === "M";
  }
  if (h.startsWith("#project/")) { const p = window.BRAIN.P[decodeURIComponent(h.slice(9))];
    if (k === "e" && p) { editPlanNode("project", p.id, p); return true; }
    const dv = selEl() && selEl().dataset.deliv ? selEl().dataset.deliv : null;
    if (k === " " && dv) { delivToggle(dv); return true; }
    if (k === "s" && dv) { delivState(dv); return true; }
    return false; }
  if (h.startsWith("#people")) {
    if (k === "n") { nbForm("person"); return true; }
    if (k === "R") { resolveForm(); return true; }
    const id = selId() || ""; const pe = id && window.BRAIN.PE[id] ? window.BRAIN.PE[id] : null;
    if ((k === "u" || k === "e") && pe) { editPerson(pe); return true; }
    if (k === "a" && pe) { personAliasForm(pe); return true; }
    if (k === "u" || k === "e" || k === "a") needSel();
    return false; }
  if (h.startsWith("#wins")) { if (k === "n") { nbForm("delivery"); return true; } return false; }
  if (h.startsWith("#person/")) { const pe = window.BRAIN.PE[decodeURIComponent(h.slice(8))];
    if ((k === "u" || k === "e") && pe) { editPerson(pe); return true; }
    if (k === "a" && pe) { personAliasForm(pe); return true; } return false; }
  if (h.startsWith("#ask")) {
    if (k === "n") { pubRequestForm(); return true; }
    const id = selId() || "";
    const q = id.startsWith("ASK-") ? M.questions.find(x => x.id === id) : null;
    const pr = id.startsWith("PROP-") ? M.proposals.find(x => x.id === id) : null;
    const pu = id.startsWith("PUB-") ? (M.publishes || []).find(x => x.id === id) : null;
    if (!q && !pr && !pu) { if (k === "a" || k === "d" || k === "A") needSel(); return k === "R"; }
    if (k === "A" && pu) { if (pu.status === "solicitada") pubAction("approve", pu.id); else toast(pu.id + " está " + pu.status); return true; }
    if (k === "d" && pu) { if (pu.status === "solicitada" || pu.status === "aprovada") pubAction("cancel", pu.id); else toast(pu.id + " está " + pu.status); return true; }
    if (k === "a" && q) { if (q.status !== "aberta") { toast(q.id + " já está " + q.status); return true; }
      openForm("ask.answer", {id: q.id, text: q.text, item: {options: q.options || []}}); return true; }
    if (k === "a" && pr) { if (pr.status !== "aberta") { toast(pr.id + " já está " + pr.status); return true; } propQuote(pr.id, true); return true; }
    if (k === "d" && pr) { if (pr.status !== "aberta") { toast(pr.id + " já está " + pr.status); return true; } propQuote(pr.id, false); return true; }
    if (k === "d" && q) { if (q.status !== "aberta") { toast(q.id + " já está " + q.status); return true; }
      const el = selEl(); const d = el && el.querySelector("[data-drop]"); if (d) d.click(); return true; }
    if (k === "R") { toast("(agente) retoma a sessão com as respostas aplicadas — claude -p --resume"); return true; }
    return false;
  }
  if (h.startsWith("#focus")) {
    const f = M.focus;
    if (k === "A" && f && f.status === "proposto") { focusApproveForm(); return true; }
    if (k === "a" && f && f.status === "aprovado") { focusApplyForm(); return true; }
    if (k === "s") { focusSyncForm(); return true; }
    if (k === "p") { focusPlanForm(); return true; }
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
    if (k === "d") {
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
  if (h.startsWith("#pf/matrix")) {
    const o = selOpp(); if (!o) return false;
    if (k === "s") { statusPicker(o); return true; }
    if (k === "i") { iceForm(o); return true; }
    return false; }
  if (h.startsWith("#pf/opps")) {
    if (k === "n") { oppAddForm(); return true; }
    const o = selOpp(); if (!o) return k === "n";
    if (k === "s") { statusPicker(o); return true; }
    if (k === "i") { iceForm(o); return true; }
    if (k === "c" && o.ice_suggested) { confirmIce(o); return true; }
    if (k === "e") { editOpp(o); return true; }
    if (k === "d") { if (["descartada", "entregue"].includes(o.status)) { toast(o.id + " está " + o.status); return true; }
      statusPicker(o, "descartada"); return true; }
    if (k === "p" && !(o.project || o.promoted)) { promoteDialog(o); return true; }
    if (k === "L") { docLinkForm(o.id); return true; }
    if (k === "v") { evidenceForm(o); return true; }
    if (k === "O") { toast("(agente) one-pager: brain share opportunity → publica na porta 6"); return true; }
    return ["s", "i", "c", "d", "p", "O", "L", "v"].includes(k); }
  if (h.startsWith("#pf/opp/")) { const o = window.BRAIN.OPP[decodeURIComponent(h.slice(8))];
    if (k === "e" && o) { editOpp(o); return true; }
    if (k === "s" && o) { statusPicker(o); return true; }
    if (k === "i" && o) { iceForm(o); return true; }
    if (k === "c" && o && o.ice_suggested) { confirmIce(o); return true; }
    if (k === "d" && o && !["descartada", "entregue"].includes(o.status)) { statusPicker(o, "descartada"); return true; }
    if (k === "p" && o && !(o.project || o.promoted)) { promoteDialog(o); return true; }
    if (k === "L" && o) { docLinkForm(o.id); return true; }
    if (k === "v" && o) { evidenceForm(o); return true; }
    return false; }
  if (h.startsWith("#pf/docs")) {
    if (k === "L") { docLinkForm(""); return true; }
    if (k === "d") { const id = selId() || ""; if (!id.startsWith("doc:")) { needSel(); return true; }
      const parts = id.split(":"); docUnlinkForm(parts[1], +parts[2]); return true; }
    return false; }
  if (h.startsWith("#pf/procs")) {
    if (k === "n") { nbForm("process"); return true; }
    const id = selId(); const pc = id && id.startsWith("PROC-") ? M.portfolio.processes.find(x => x.id === id) : null;
    if (k === "e" && pc) { editProc(pc); return true; }
    if (k === "a" && pc) { oppAddForm({process: pc.id}); return true; }
    if (k === "L" && pc) { docLinkForm(pc.id); return true; }
    if (k === "o" && pc) { const pb = pc.playbook, url = pb ? docUrl(pb.ref) : "";
      if (!pb) toast(pc.id + " não tem playbook ligado (L, tipo playbook)");
      else if (url) window.open(url, "_blank", "noopener"); else toast("playbook no vault: " + pb.ref);
      return true; }
    if ((k === "L" || k === "o") && !pc) { needSel(); return true; }
    if (k === "d" && pc) { openForm("process.retire", {id: pc.id, title: pc.title}); return true; }
    return false; }
  if (h.startsWith("#cfg/memoria")) {
    if (k === "s") { const b = document.querySelector("[data-provform]"); if (b) b.click(); else provForm(); return true; }
    if (k === "v") { runCommand("brain memory harness verify", () => {}); return true; }
    if (k === "i") { const id = selId() || ""; const hw = (window.BRAIN.M.harnesses || []).find(x => (x.name || x.id) === id);
      if (hw) runCommand("brain memory harness install " + (hw.name || hw.id), m => {
        const x = (m.harnesses || []).find(y => (y.name || y.id) === (hw.name || hw.id)); if (x) x.wired = true; });
      else needSel();
      return true; }
    return false; }
  if (h.startsWith("#cfg/saude")) {
    if (k === "o") { runCommand("brain doctor --online"); return true; }   // re-check ao vivo; a régua da página é do render
    if (k === "f") { const id = selId() || ""; const c = id.startsWith("health:") ? (M.health || [])[+id.slice(7)] : null;
      if (!c) needSel(); else if (!c.fix) toast("sem correção automática para este aviso"); else healthFix(c.fix);
      return true; }
    return false; }
  if (h.startsWith("#pf/areas") || h.startsWith("#pf/area/")) {
    if (k === "n" && h.startsWith("#pf/areas")) { nbForm("area"); return true; }
    let a = null;
    if (h.startsWith("#pf/area/")) a = M.portfolio.areas.find(x => x.id === decodeURIComponent(h.slice(9)));
    else { const name = selEl() && selEl().querySelector("b") ? selEl().querySelector("b").textContent : null;
      a = name && M.portfolio.areas.find(x => x.name === name); }
    if (k === "e" && a) { openForm("area.edit", {id: a.id, item: a}); return true; }
    return false; }
  return false;
}
function focusApproveKey(){ focusApproveForm(); }      // compat: tecla A e botões usam o mesmo gate

function helpOverlay(){
  const ov = document.createElement("div"); ov.className = "pal-back open";
  const rows = [
    ["globais", ""],
    ["tab / shift+tab", "próxima / anterior face (Execução · Portfólio · Configurações)"],
    ["/", "filtrar a lista da página — de novo: refina o que sobrou (cascata)"],
    ["esc", "tira o último filtro, um por vez (dentro do campo: desfaz só aquele)"],
    ["g : ctrl+k", "busca e comandos (paleta)"],
    ["N", "nota rápida na inbox"],
    ["j k ↑ ↓", "mover na lista · enter abre a ficha"],
    ["[ ] ← → (h l)", "aba anterior / próxima"],
    ["T", "alterna só abertas ↔ todas (TODO, Perguntas, Mensagens, Sugestões)"],
    ["`", "console da ponte (abre/fecha)"],
    ["?", "esta ajuda"],
    ["? (dentro do ICE)", "metodologia de pontuação — as notas com critério e regras"],
    ["padrão em todas as telas", ""],
    ["n", "novo"], ["e", "editar"], ["d", "descartar · remover · cancelar · aposentar · desligar · rejeitar"],
    ["s", "status / estado"], ["A", "aprovar (gate)"],
    ["Início", ""], ["n", "nota"], ["u d b c", "(agente) atualizar tudo · processar inbox · brief · puxar fonte"],
    ["Fontes", ""], ["n", "adicionar"], ["e", "editar"], ["d", "remover"], ["w", "incluir no watch"], ["c u", "(agente) puxar · atualizar tudo"],
    ["TODO (com cartão selecionado)", ""],
    ["n", "nova ação"], ["e", "editar"], ["c", "fechar"], ["s", "status (ciclo)"], ["t", "prazo"],
    ["d", "descartar"], ["z", "não agora / voltar"], ["o", "reabrir"], ["m", "cobrar (rascunho de msg)"], ["M", "mesclar duplicada"],
    ["v / O / T", "vista · ordem · todas (como o TUI)"],
    ["Foco", ""], ["A", "aprovar plano (gate)"], ["a", "aplicar no calendário (gate · ics ou google)"], ["s", "sync (dry-run ou aplicar)"], ["p", "planejar (focus plan --days)"],
    ["Mensagens", ""], ["A", "aprovar rascunho (gate)"], ["S", "enviar (agente)"], ["d", "cancelar"],
    ["Decisões", ""], ["S", "superar (nova decisão)"],
    ["Perguntas e propostas", ""], ["a", "responder pergunta / aceitar proposta (gate)"],
    ["d", "descartar pergunta · rejeitar proposta · cancelar publicação"], ["R", "retomar o agente"],
    ["Publicar (porta 3)", ""], ["n", "pedir publicação"], ["A", "aprovar (gate)"],
    ["Sugestões", ""], ["n", "nova"], ["p", "publicar"], ["s", "sincronizar issues"],
    ["Portfólio · Oportunidades", ""], ["n", "nova"], ["s", "status"], ["i", "ICE"], ["c", "confirmar ICE sugerido"],
    ["e", "editar"], ["d", "descartar"], ["p", "promover (gate)"], ["O", "one-pager (agente)"], ["L", "ligar documento"], ["v", "evidência"],
    ["Portfólio · Processos", ""], ["n", "novo"], ["e", "editar"], ["a", "nova oportunidade daqui"], ["d", "aposentar"], ["L", "ligar documento"], ["o", "abrir playbook"],
    ["Portfólio · Matriz", ""], ["s", "status"], ["i", "ICE"],
    ["Portfólio · Documentos", ""], ["L", "ligar"], ["d", "desligar"], ["enter", "abrir"],
    ["Configurações · Memória", ""], ["s", "trocar provedor"], ["v", "verificar harnesses"], ["i", "conectar selecionado"],
    ["Configurações · Saúde", ""], ["f", "corrigir o aviso selecionado"], ["o", "testar online (doctor --online)"],
    ["Ficha de projeto", ""], ["space", "entregável feito"], ["s", "estado do entregável"],
    ["Outros n", ""], ["n", "nota (Início) · estrutura do plano (Projetos) · rascunhar msg · nova decisão · nova entrega · nova pessoa · novo processo · nova área"],
    ["Pessoas / fichas", ""], ["e", "editar pessoa"], ["a", "alias"], ["R", "quem é…?"],
    ["Projetos / Goals", ""], ["e", "editar (gate estrutural: brain plan log)"], ["G", "novo goal (gate)"], ["E", "mudar árvore (gate)"],
    ["P", "declarar progresso do goal"], ["S", "exportar (share)"],
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
  if ((e.metaKey || e.ctrlKey) && ["k", "p"].includes(e.key.toLowerCase())) { e.preventDefault(); pal.open ? closePal() : openPal(); return; }
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
  if (k === "/") { e.preventDefault(); lfOpen(); return; }
  if (k === "g" || k === ":") { e.preventDefault(); openPal(); return; }      // busca/paleta: g e : (como a TUI)
  if (k === "Escape" && lfPop()) { e.preventDefault(); return; }
  if (k === "N") { e.preventDefault(); noteForm(); return; }                  // nota rápida em qualquer página
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
    add("t", "prazo", !t || !t.open); add("d", "descartar", !t || !t.open); add("z", t && t.parked ? "voltar" : "não agora", !t || !t.open);
    add("o", "reabrir", !(t && !t.open)); add("m", "cobrar", !(t && t.open && t.list === "waiting"));
    const qs0 = new URLSearchParams((location.hash.split("?")[1]) || "");
    const vl = {todas: "todas", semana: "esta semana", depois: "depois", "nao-agora": "não agora"}[qs0.get("v") || "todas"];
    add("v", "vista: " + vl); add("O", "ordem: " + ((qs0.get("o") || "prazo") === "prazo" ? "prazo" : "id"));
    add("T", qs0.get("a") === "1" ? "só recentes" : "todas");
  } else if (h.startsWith("#action/")) { add("e", "editar"); add("c", "fechar"); add("d", "descartar"); add("M", "mesclar"); }
  else if (h.startsWith("#home")) { add("n", "nota"); add("u", "⚡ atualizar tudo"); add("d", "⚡ processar inbox"); add("b", "⚡ brief"); add("c", "⚡ puxar fonte"); }
  else if (h.startsWith("#sources")) {
    const sid = SEL.i >= 0 ? (selId() || "") : "", src = sid.startsWith("src:") ? (M.sources || []).find(x => x.key === sid.slice(4)) : null;
    add("n", "adicionar"); add("e", "editar", !(src && src.in_watch)); add("d", "remover", !(src && src.in_watch));
    add("w", "incluir no watch", !(src && !src.in_watch)); add("c", "⚡ puxar", !src); add("u", "⚡ atualizar tudo"); }
  else if (h.startsWith("#projects")) { add("n", "estrutura"); add("G", "novo goal (gate)"); add("E", "mudar árvore (gate)");
    add("P", "progresso do goal", !id.startsWith("GOAL-")); add("S", "exportar"); }
  else if (h.startsWith("#project/")) { add("e", "editar (gate)");
    add("space", "marcar feito", !(selEl() && selEl().dataset.deliv)); add("s", "estado", !(selEl() && selEl().dataset.deliv)); }
  else if (h.startsWith("#person/")) { add("e", "editar"); add("a", "alias"); }
  else if (h.startsWith("#ask")) {
    const id = SEL.i >= 0 ? (selId() || "") : "";
    const qs = id.startsWith("ASK-") ? (M.questions || []).find(x => x.id === id) : null;
    const ps = id.startsWith("PROP-") ? (M.proposals || []).find(x => x.id === id) : null;
    add("n", "pedir publicação");
    const pu = id.startsWith("PUB-") ? (M.publishes || []).find(x => x.id === id) : null;
    add("A", "aprovar publicação (gate)", !(pu && pu.status === "solicitada"), true);
    add("a", id.startsWith("PROP-") ? "aceitar (gate)" : "responder", !(qs ? qs.status === "aberta" : ps ? ps.status === "aberta" : false));
    add("d", pu ? "cancelar publicação" : ps ? "rejeitar proposta" : "descartar pergunta",
      pu ? !(pu.status === "solicitada" || pu.status === "aprovada") : ps ? ps.status !== "aberta" : !(qs && qs.status === "aberta"));
    add("R", "retomar o agente"); add("T", hashAll() ? "só abertas" : "todas");
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
    add("S", "enviar", !(m0 && m0.status === "aprovada")); add("T", hashAll() ? "só pendentes" : "todas");
    add("d", "cancelar", !(m0 && (m0.status === "rascunho" || m0.status === "aprovada")));
  } else if (h.startsWith("#feedback")) {
    const fid = SEL.i >= 0 ? (selId() || "") : "";
    const fb = fid.startsWith("FB-") ? (M.feedback || []).find(x => x.id === fid) : null;
    add("n", "sugerir/corrigir"); add("p", "publicar", !(fb && (fb.status === "pendente" || fb.status === "falhou"))); add("s", "sincronizar"); add("T", hashAll() ? "só pendentes" : "todas");
  } else if (h.startsWith("#decisions")) { add("n", "nova"); add("S", "superar", !id.startsWith("DEC-")); }
  else if (h.startsWith("#pf/matrix")) { add("s", "status", !o); add("i", "ICE", !o); }
  else if (h.startsWith("#pf/opps")) {
    add("n", "nova");
    add("s", "status", !o); add("i", "ICE", !o); add("c", "confirmar ICE", !(o && o.ice_suggested));
    add("e", "editar", !o); add("d", "descartar", !o);
    add("p", "promover", !(o && !(o.project || o.promoted)), true); add("O", "one-pager", !o); add("L", "ligar doc", !o); add("v", "evidência", !o);
  } else if (h.startsWith("#pf/opp/")) { add("e", "editar"); add("s", "status"); add("i", "ICE");
    add("c", "confirmar ICE", !(o && o.ice_suggested)); add("p", "promover (gate)", !!(o && (o.project || o.promoted)), true);
    add("d", "descartar", !o || ["descartada", "entregue"].includes(o.status)); add("L", "ligar doc"); add("v", "evidência"); }
  else if (h.startsWith("#pf/procs")) { add("n", "novo"); add("e", "editar", !id.startsWith("PROC-"));
    add("a", "nova oportunidade daqui", !id.startsWith("PROC-")); add("d", "aposentar", !id.startsWith("PROC-")); add("L", "ligar doc", !id.startsWith("PROC-")); add("o", "abrir playbook", !id.startsWith("PROC-")); }
  else if (h.startsWith("#pf/docs")) { add("L", "ligar"); add("d", "desligar", !id.startsWith("doc:")); add("enter", "abrir", !id.startsWith("doc:")); }
  else if (h.startsWith("#cfg/memoria")) { add("s", "provedor"); add("v", "verificar harnesses"); add("i", "conectar", !id); }
  else if (h.startsWith("#cfg/saude")) { const hc = id.startsWith("health:") ? (M.health || [])[+id.slice(7)] : null;
    add("f", "corrigir", !(hc && hc.fix)); add("o", "testar online"); }
  else if (h.startsWith("#pf/areas")) { add("n", "nova"); add("e", "editar", !sel); }
  else if (h.startsWith("#wins")) add("n", "nova entrega");
  else if (h.startsWith("#people")) { add("n", "nova pessoa"); add("e", "editar", !id); add("a", "alias", !id); add("R", "quem é…?"); }
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
    '<div class="kglobal">' + (lfLevels().length ? '<button class="kkey lfon" data-g="esc" title="tira o último filtro da lista"><kbd>esc</kbd>tira filtro (' + lfLevels().length + ')</button>' : "") +
    '<button class="kkey" data-g="/" title="filtrar a lista desta página; de novo refina o filtro"><kbd>/</kbd>' + (lfLevels().length ? "refinar" : "filtrar") + '</button>' +
    '<button class="kkey" data-g="g" title="paleta de busca e comandos (⌘K)"><kbd>g</kbd>busca</button>' +
    '<button class="kkey" data-g="tab" title="trocar de face"><kbd>tab</kbd>face</button>' +
    '<button class="kkey" data-g="?" title="mapa de teclas"><kbd>?</kbd>ajuda</button></div>';
  bar.querySelectorAll("[data-k]").forEach(b => b.onclick = () => ctxKeys(b.dataset.k));
  bar.querySelectorAll("[data-g]").forEach(b => b.onclick = () => {
    if (b.dataset.g === "/") lfOpen();
    else if (b.dataset.g === "g") openPal();
    else if (b.dataset.g === "esc") lfPop();
    else if (b.dataset.g === "?") helpOverlay();
    else location.hash = "#face/" + (location.hash.startsWith("#pf/") ? "execucao" : "portfolio");
  });
}

})();
