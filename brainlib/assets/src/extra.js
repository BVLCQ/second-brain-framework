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
D0.owner = D0.owner || {name: ""};
D0.agent_ok = !!D0.agent_ok;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm = s => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || "");
const KMOD = IS_MAC ? "⌘K" : "Ctrl K";

// ── sidebar: dono ───────────────────────────────────────────────────────
const ownBootName = (D0.owner && D0.owner.name) || "—";
$("#ownername").textContent = ownBootName;
$("#avatar").textContent = ownBootName.trim().slice(0, 1).toUpperCase() || "B";

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
function toast(msg, ms){ const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTmr); toastTmr = setTimeout(() => t.classList.remove("show"), ms || 2800); }
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
const TOK_KEY = "brain-serve-token";
const TOK_TTL_MS = 12 * 3600 * 1000;
let tokConsumed = false;
function readStoredToken(){
  try { localStorage.removeItem(TOK_KEY); } catch (e) {}
  try {
    const raw = sessionStorage.getItem(TOK_KEY);
    if (!raw) return null;
    const rec = JSON.parse(raw);
    if (!rec || typeof rec.tok !== "string" || !rec.tok || typeof rec.exp !== "number" || Date.now() > rec.exp) {
      sessionStorage.removeItem(TOK_KEY);
      return null;
    }
    return rec.tok;
  } catch (e) {
    try { sessionStorage.removeItem(TOK_KEY); } catch (x) {}
    return null;
  }
}
function storeToken(tok){
  try { localStorage.removeItem(TOK_KEY); } catch (e) {}
  try { sessionStorage.setItem(TOK_KEY, JSON.stringify({tok: tok, exp: Date.now() + TOK_TTL_MS})); } catch (e) {}
}
function consumeBootToken(){
  if (!SERVE || tokConsumed) return null;
  tokConsumed = true;
  const rawHash = location.hash || "";
  if (!rawHash.startsWith("#")) return null;
  const parts = rawHash.slice(1).split("&");
  let foundTok = null;
  const kept = [];
  for (const p of parts) {
    if (foundTok === null && p.startsWith("t=")) {
      const val = p.slice(2);
      if (val) {
        try { foundTok = decodeURIComponent(val); } catch (e) { foundTok = val; }
      }
    } else if (p !== "") {
      kept.push(p);
    }
  }
  if (!foundTok) return null;
  storeToken(foundTok);
  const nextHash = kept.length ? "#" + kept.join("&") : "";
  history.replaceState(null, "", location.pathname + location.search + nextHash);
  return foundTok;
}
let TOK = null;
if (SERVE) {
  TOK = consumeBootToken() || readStoredToken();
}
// aba reaproveitada (util.focus_open_tab): a nova URL traz `#t=<token>` e só muda o fragmento — a página não recarrega
// sozinha, e o boot de cima já rodou. Guarda o token novo (com validade), devolve a rota ao que era e recarrega; token
// igual, só devolve a URL. Sem isto a aba reaproveitada fica com o token antigo e a ponte nova responde 401.
if (SERVE) window.addEventListener("hashchange", e => {
  const m = location.hash.match(/[#&]t=([^&]+)/); if (!m) return;
  let tok = m[1]; try { tok = decodeURIComponent(tok); } catch (x) {}
  const back = (e.oldURL || "").split("#").slice(1).join("#");
  storeToken(tok);
  history.replaceState(null, "", location.pathname + location.search + (back ? "#" + back : ""));
  if (tok !== TOK) location.reload();
});
let LIVE = SERVE && !!TOK;
document.documentElement.dataset.live = LIVE ? "1" : "0";
function paintLiveStatus(){
  document.documentElement.dataset.live = LIVE ? "1" : "0";
  const cm = document.querySelector("#conmode");
  const ci = document.querySelector("#clidot");
  if (LIVE) {
    if (cm) cm.textContent = "vivo — comandos executam";
    document.body.classList.add("bridge-live");
    if (ci) { ci.classList.add("live"); ci.title = "ponte CLI conectada — comandos executam (clique/` para o console)"; }
  } else {
    if (cm) cm.textContent = "retrato — comandos só copiam";
    document.body.classList.remove("bridge-live");
    if (ci) { ci.classList.remove("live"); ci.title = "ponte CLI offline — retrato: comandos são copiados (clique/` para o console)"; }
  }
}
function handle401(silent){
  TOK = null;
  LIVE = false;
  try { localStorage.removeItem(TOK_KEY); } catch (e) {}
  try { sessionStorage.removeItem(TOK_KEY); } catch (e) {}
  paintLiveStatus();
  if (!silent) toast("sessão expirada — reabra via ./brain render --open ou pelo app Brain");
}
function renderAuthRequired(detail){
  const v = document.getElementById("view");
  if (!v) return;
  const msg = detail || "Esta página precisa do token temporário da ponte local.";
  v.innerHTML = '<section class="panel" data-auth-required="1"><h2>Sessão não autenticada</h2>' +
    '<p>' + esc(msg) + '</p>' +
    '<p class="muted">Reabra o painel pelo aplicativo <b>Brain</b> (Brain.app) ou rode <code>./brain render --open</code> no terminal.</p></section>';
}
async function hydrateShell(){
  try {
    const endpoint = window.PF_ONLY ? "/api/portfolio" : "/api/data";
    const d = await api(endpoint);
    if (d && d.model && window.BRAIN && window.BRAIN.refresh) {
      window.BRAIN.refresh(d.model);
      return;
    }
    renderAuthRequired("Resposta inesperada da ponte — reabra via ./brain render --open ou pelo app Brain.");
  } catch (e) {
    renderAuthRequired(e && e.message === "401"
      ? "Token inválido ou expirado — reabra via ./brain render --open ou pelo app Brain."
      : "Não foi possível conectar à ponte local — rode ./brain render --open ou abra pelo app Brain.");
  }
}
window.BRAIN_AUTH = { isLive: () => LIVE, hydrate: hydrateShell, showAuthRequired: renderAuthRequired };
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
paintLiveStatus();

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
  if (MD.focus && MD.focus.status === "proposto")
    out.push({label: "Aprovar plano de foco " + MD.focus.id + " (gate)", act: () => focusApproveForm()});
  if (MD.focus && MD.focus.status === "aprovado")
    out.push({label: "Aplicar plano de foco " + MD.focus.id + " no calendário (gate)", act: () => focusApplyForm()});
  MD.outbox.filter(m0 => m0.status === "rascunho").forEach(m0 => out.push({label: "Aprovar mensagem " + m0.id + " para " + m0.to_name,
    act: () => approveMsgForm(m0)}));
  MD.proposals.forEach(p => {
    out.push({label: "Aceitar proposta " + p.id + " · " + p.summary.slice(0, 60) + "…",
      cmd: 'brain proposal accept ' + p.id + ' --quote "ok"', mut: m => { m.proposals = m.proposals.filter(x => x.id !== p.id); }});
    out.push({label: "Rejeitar proposta " + p.id,
      cmd: 'brain proposal reject ' + p.id + ' --quote "não"', mut: m => { m.proposals = m.proposals.filter(x => x.id !== p.id); }});
  });
  out.push({label: "Regenerar views (render)", cmd: "brain render"});
  if (!window.PF_ONLY) {
    [
      ["Atualizar tudo (/update)", () => runAgent("update", "", "atualizar tudo", "/update")],
      ["Processar a inbox (/dump)", () => runAgent("dump", "", "processar a inbox", "/dump")],
      ["Puxar uma fonte (/connect)", () => {
        if (!LIVE || !isAgentOk()) runAgent("connect", "", "puxar uma fonte", "/connect <fonte>");
        else pickSourceAgent();
      }],
      ["Brief do dia (/brief)", () => runAgent("brief", "", "brief do dia", "/brief")],
      ["Cockpit da semana (/week)", () => runAgent("week", "", "cockpit da semana", "/week")],
      ["Ler emails (/gmail)", () => agentArgPrompt("gmail", "Ler emails (/gmail)", "filtro ou janela", "da marina-demo · assunto X · 3d (vazio = hoje)", false)],
      ["Ler Slack (/slack)", () => agentArgPrompt("slack", "Ler Slack (/slack)", "canal ou pessoa", "#canal @user 7d", true)],
      ["Ler doc do Drive (/drive)", () => agentArgPrompt("drive", "Ler doc do Drive (/drive)", "termo ou id", "nome do doc ou id do arquivo", true)],
      ["Ler a agenda (/calendar)", () => agentArgPrompt("calendar", "Ler a agenda (/calendar)", "janela", "14d (vazio = padrão)", false)],
      ["Recap (/recap)", () => agentArgPrompt("recap", "Recap (/recap)", "alvo", "GOAL-1 · PROJ-2 · 2025-01-01:2025-03-31", true)],
      ["Reconciliar o framework (/upgrade)", () => runAgent("upgrade", "", "reconciliar o framework", "/upgrade")],
      ["Primeira entrevista (/init)", () => runAgent("init", "", "primeira entrevista", "/init")],
    ].forEach(([label, act]) => out.push({label: "⚡ " + label, act: act}));
  }
  return out;
}

async function api(path, opts){
  const headers = Object.assign({"X-Brain-Token": TOK || ""}, (opts && opts.headers) || {});
  const r = await fetch(path, Object.assign({}, opts, {headers}));
  if (r.status === 401) { handle401(); throw new Error("401"); }
  return r.json();
}
async function serveRun(cmd, onResp){
  conOpen();
  conLine('<span class="dim">$</span> ' + esc(cmd));
  let j;
  try {
    j = await api("/api/cmd", {method: "POST", headers: {"Content-Type": "application/json"},
                              body: JSON.stringify({cmd: cmd})});
  } catch (e) { conLine('<span class="late">ponte fora do ar — ./brain serve</span>'); if (onResp) onResp(null); return false; }
  if (onResp) onResp(j);
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
    ["pf/visao", "Portfólio · Visão"], ["pf/opps", "Portfólio · Oportunidades"], ["pf/matrix", "Portfólio · Matriz"], ["pf/procs", "Portfólio · Processos"], ["pf/areas", "Portfólio · Áreas"], ["pf/docs", "Portfólio · Documentos"],
    ["people", "Portfólio · Pessoas"]]
    : [["face/execucao", "→ face Execução"], ["face/portfolio", "→ face Portfólio"], ["face/configuracoes", "→ face Configurações"],
    ["home", "Início"], ["sources", "Fontes"], ["todo", "TODO"], ["projects", "Projetos"], ["decisions", "Decisões"], ["wins", "Conquistas"],
    ["timeline", "Linha do tempo"], ["focus", "Foco"], ["outbox", "Mensagens"], ["feedback", "Sugestões"],
    ["cfg/inicio", "Configurações · Visão geral"], ["cfg/perfil", "Configurações · Perfil"], ["cfg/rotina", "Configurações · Rotina"],
    ["cfg/conectores", "Configurações · Conectores"], ["cfg/agente", "Configurações · Seu agente"], ["cfg/memoria", "Configurações · Memória"], ["cfg/integracoes", "Configurações · Integrações"],
    ["cfg/saude", "Configurações · Saúde"],
    ["pf/visao", "Portfólio · Visão"], ["pf/opps", "Portfólio · Oportunidades"], ["pf/matrix", "Portfólio · Matriz"],
    ["pf/procs", "Portfólio · Processos"], ["pf/areas", "Portfólio · Áreas"], ["pf/docs", "Portfólio · Documentos"],
    ["people", "Portfólio · Pessoas"]];
  return tabs.map(t => ({group: t[0].startsWith("face/") ? "faces" : "ir para", label: t[1], view: t[0]}));
}
function entEntries(){
  const out = [];
  const MD = (window.BRAIN && window.BRAIN.M) || D0;
  (MD.actions || []).filter(a => a.open).forEach(a => out.push({group: "ações abertas", label: a.title, ent: a.id, view: "action/" + a.id}));
  (MD.decisions || []).slice(0, 8).forEach(d => out.push({group: "decisões", label: d.title, ent: d.id, view: "decision/" + d.id}));
  (MD.projects || []).forEach(p => out.push({group: "projetos", label: p.id + " " + p.title, ent: p.id, view: "project/" + p.id}));
  (MD.people || []).forEach(p => out.push({group: "pessoas", label: p.name, ent: p.id, view: "person/" + encodeURIComponent(p.id)}));
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
function feedbackWithdrawForm(fb){ openForm("feedback.withdraw", {id: fb.id, title: fb.title, item: fb}); }
function feedbackRetractForm(fb){ openForm("feedback.retract", {id: fb.id, title: fb.title, item: fb}); }
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
    runCommand("brain feedback push " + id0 + " --approval painel"); }});   // gate: resposta do dono (a mesma convenção da TUI)
  document.querySelectorAll("#view [data-fbwithdraw]").forEach(b => { const id0 = b.dataset.fbwithdraw; b.onclick = () => {
    const fb = (window.BRAIN.M.feedback || []).find(x => x.id === id0); if (fb) feedbackWithdrawForm(fb); }; });
  document.querySelectorAll("#view [data-fbretract]").forEach(b => { const id0 = b.dataset.fbretract; b.onclick = () => {
    const fb = (window.BRAIN.M.feedback || []).find(x => x.id === id0); if (fb) feedbackRetractForm(fb); }; });
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
const SETUP_STEPS = [["perfil", "Perfil"], ["rotina", "Rotina"], ["agente", "Seu agente"], ["conectores", "Conectores"], ["memoria", "Memória"], ["integracoes", "Integrações"]];
const MEM_LABEL = {none: "nenhuma", lite: "embed", embed: "embed", full: "full"};   // a API ainda diz "lite"; a tela diz o nome da CLI
let SS = null, profileDraftCfg = null;
const OB_JOB_TIMEOUT_MS = 15 * 60 * 1000;
async function obApi(path, body){
  const o = {headers: {"X-Brain-Token": TOK || ""}};
  if (body !== undefined) { o.method = "POST"; o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  const r = await fetch(path, o);
  if (r.status === 401) { handle401(); throw new Error("sessão expirada — reabra via ./brain render --open ou pelo app Brain"); }
  let j = {};
  try { j = await r.json(); } catch (e) {}
  if (!r.ok || j.ok === false) throw new Error(j.error || ("erro " + r.status));
  return j;
}
const obAct = (name, body) => obApi("/api/onboard/" + name, body || {});
async function obJob(id, onTick){
  const started = Date.now();
  for (;;) {
    const j = (await obApi("/api/onboard/job/" + id)).job;
    if (onTick) onTick(j);
    if (j.status === "stale") throw new Error((j.result && j.result.error) || "tempo esgotado (15 min) — rode `brain doctor --online` no terminal");
    if (j.status !== "running") return j;
    if (Date.now() - started >= OB_JOB_TIMEOUT_MS) throw new Error("tempo esgotado (15 min) — rode `brain doctor --online` no terminal");
    await new Promise(r => setTimeout(r, 1500));
  }
}
function stMsg(el, kind, text){ if (el) { el.className = "stmsg " + kind; el.textContent = text; } }
async function stBusy(btn, label, fn){
  const was = btn.innerHTML; btn.disabled = true; btn.textContent = label || "salvando…";
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = was; }
}
const stStatus = ok => ok === "manual" ? '<span class="chip h-info">manual</span>' : (ok ? '<span class="chip h-em-dia">feito</span>' : '<span class="stlater">depois</span>');
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
    agente: st.agente === "manual" ? "Outro harness (MCP manual)"
      : (((SS.agents || []).filter(a => a.mcp || a.selected).map(a => a.label).join(", "))
        || ((SS.agents || []).map(a => a.label).join(" · ")) || "Outros harnesses"),
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
    location.hash = "onboarding";   // F8: o wizard mora no painel — mesma página, sem recarregar
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
let connScanRes = null;
const CONN_ST = {connected: ["h-em-dia", "conectado"], auth: ["h-atencao", "precisa autorizar"], missing: ["", "não adicionado"], error: ["h-em-risco", "com erro"], unknown: ["", "não verificado"]};
SETUP.conectores = box => {
  const perm = SS.permissions.ok;
  const src = (connScanRes && connScanRes.source) || SS.connectors_source;
  const hint = (connScanRes && connScanRes.hint) || SS.connectors_hint;
  const noConn = src === "none";
  const rows = noConn
    ? '<p class="muted">' + esc(hint) + "</p>"
    : SS.connectors.map(c => {
        const [cls, label] = CONN_ST[SS.connectors_scanned ? c.status : "unknown"] || CONN_ST.unknown;
        const can = c.status === "connected" || c.enabled;
        return '<div class="stconn"><div><b>' + esc(c.label) + '</b><span class="muted small">' + esc(c.what) + '</span></div><span class="chip ' + cls + '">' + label + "</span>" +
          '<label class="chk" title="o Brain pode ler"><input type="checkbox" data-c="' + esc(c.key) + '"' + (c.enabled || c.status === "connected" ? " checked" : "") + (can ? "" : " disabled") + "> ler</label></div>";
      }).join("");
  box.innerHTML = sec("Seus conectores", rows +
      '<div class="stgrid" id="s-extra"' + (noConn ? " hidden" : "") + ">" + fld("Canais do Slack para acompanhar", '<input type="text" id="s-slack" placeholder="#meu-time, #projeto-x">', "Separados por vírgula: entram como fontes novas.") +
      fld("Pasta do Drive (link)", '<input type="text" id="s-drive" placeholder="https://drive.google.com/drive/folders/…">', "Opcional.") + "</div>" +
      (noConn ? "" : '<p class="muted small">Desligar um conector aqui faz o Brain parar de lê-lo. Conecte novos em <a href="https://claude.ai/settings/connectors" target="_blank" rel="noopener">claude.ai → Configurações → Conectores</a> e clique em verificar.</p>') +
      '<div class="stactions"><span class="stmsg" id="s-m"></span><button class="btn" id="s-scan">↻ verificar conexões</button><button class="btn primary" id="s-save"' + (noConn ? " hidden" : "") + '>Salvar</button></div>') +
    sec("Permissões no computador", '<p>Pré-autoriza o Claude a ler esta pasta e usar as ferramentas de <b>leitura</b> dos conectores ligados. Segredos, livro-razão e envios continuam bloqueados.</p>' +
      '<div class="stactions"><span class="stmsg" id="s-mp"></span>' + (perm ? "" : '<button class="btn primary" id="s-perm">Liberar</button>') + "</div>",
      perm ? '<span class="chip h-em-dia">liberado</span>' : '<span class="chip h-atencao">pendente</span>');
  const q = s => box.querySelector(s);
  const extra = () => { const on = k => !!box.querySelector('[data-c="' + k + '"]:checked'); q("#s-slack").closest(".fld").hidden = !on("slack"); q("#s-drive").closest(".fld").hidden = !on("drive"); };
  box.querySelectorAll("[data-c]").forEach(i => i.onchange = extra); extra();
  q("#s-scan").onclick = e => stBusy(e.currentTarget, "verificando…", async () => {
    try { const r = await obAct("connectors_scan", {force: true});
          if (r.job) { const j = await obJob(r.job); if (j.status === "error") stMsg(q("#s-m"), "late", (j.result && j.result.error) || "não consegui verificar"); connScanRes = j.result || null; }
          else { connScanRes = r; }
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
  const rerOpts = [["off", "Desligado — fusão RRF"], ["fireworks", "Fireworks — Qwen3-Reranker-8B"], ["cohere", "Cohere — rerank-v3.5"]];
  const curRer = () => rerOpts.some(o => o[0] === m.rer_provider) ? m.rer_provider : "off";
  const selHTML = (list, curv, id) => '<select id="' + id + '">' + list.map(o => '<option value="' + o[0] + '"' + (o[0] === curv ? " selected" : "") + ">" + esc(o[1]) + "</option>").join("") + "</select>";
  const keyChip = ok => ok ? ' <span class="chip h-em-dia">já salva</span>' : "";
  const keyInp = id => '<input type="password" id="' + id + '" autocomplete="off" placeholder="cole a chave">';
  const draw = () => {
    box.innerHTML = sec("Modo", '<div class="stopts">' + opts.map(([k, t, d]) => '<button class="stopt' + (k === sel ? " sel" : "") + '" data-m="' + k + '"><b>' + t + (k === cur ? ' <span class="chip h-info">atual</span>' : "") + "</b><span>" + d + "</span></button>").join("") + "</div>" +
      (sel !== "none" ? '<p class="small">' + (() => {
          const dst = m.docker_state || (m.docker ? "up" : "missing");
          if (dst === "up") return '<span class="ok">✓</span> OrbStack (o banco da memória) pronto';
          return dst === "installed"
            ? '<span class="late">⚠</span> OrbStack instalado, parado — ativar sobe'
            : '<span class="late">✗</span> OrbStack ausente — o Brain instala ao ativar';
        })() +
        '<span id="s-lms"' + (sel === "embed" ? "" : " hidden") + '> · ' + (() => {
          const lst = m.lmstudio_state || (m.lmstudio ? "up" : "missing");
          if (lst === "up") return '<span class="ok">✓</span> LM Studio com <code>text-embedding-bge-m3</code> pronto';
          return lst === "installed"
            ? '<span class="late">⚠</span> LM Studio instalado, servidor desligado — ativar sobe e configura'
            : '<span class="late">✗</span> LM Studio ausente — o Brain instala e configura ao ativar';
        })() + " (só no embeddings local)</span></p>" : "") +
      (sel === "embed" ? '<div class="stgrid">' + fld("Embeddings", selHTML(embOpts(false), curEmb(false), "s-emb")) +
        '<div id="s-ekey-wrap"' + (curEmb(false) === "local" ? " hidden" : "") + ">" + fld("API key do embeddings" + keyChip(m.emb_key), keyInp("s-ekey"), "Fireworks ou OpenAI, conforme o escolhido.") + "</div></div>" +
        '<p class="small" id="s-egress"' + (curEmb(false) === "local" ? " hidden" : "") + '>☁ com provedor de nuvem, o texto do vault vai à API para virar vetores.</p>' : "") +
      (sel === "full" ?
        '<div class="stgrid">' +
        fld("LLM", '<select id="s-prov"><option value="anthropic"' + (m.llm_provider === "openai" ? "" : " selected") + '>Anthropic (Claude) — Haiku/Sonnet por operação</option><option value="openai"' + (m.llm_provider === "openai" ? " selected" : "") + '>OpenAI</option><option value="claude-code"' + (m.llm_provider === "claude-code" ? " selected" : "") + '>Claude Code (assinatura Pro/Max)</option><option value="xai-oauth"' + (m.llm_provider === "xai-oauth" ? " selected" : "") + ">xAI / SuperGrok (assinatura)</option></select>") +
        '<div id="s-key-wrap">' + fld("API key (LLM)" + keyChip(m.llm_key), keyInp("s-key")) + "</div>" +
        '<div id="s-auth-wrap" hidden>' + fld("Assinatura — sem chave de API" + ((m.llm_auth || {}).state === "ok" ? ' <span class="chip h-em-dia">autenticado</span>' : ((m.llm_auth || {}).state === "pending" ? ' <span class="chip h-late">autenticar</span>' : "")),
          '<button class="btn" type="button" id="s-auth">' + ((m.llm_auth || {}).state === "ok" ? "Reautenticar" : "Autenticar") + "</button>",
          "A credencial nasce aqui mesmo (job narrado) — nunca passa pela tela.") + "</div></div>" +
        '<div class="stgrid" id="s-model-wrap">' + fld("Modelo do LLM", '<input type="text" id="s-model" placeholder="vazio = recomendado do provedor">') + "</div>" +
        '<div class="stgrid">' + fld("Embeddings", selHTML(embOpts(true), curEmb(true), "s-emb")) +
        '<div id="s-ekey-wrap">' + fld("API key do embeddings" + keyChip(m.emb_key), keyInp("s-ekey"), "Fireworks ou OpenAI — conta própria do embeddings.") + "</div></div>" +
        '<div class="stgrid">' + fld("Reranking", selHTML(rerOpts, curRer(), "s-rer")) +
        '<div id="s-rkey-wrap">' + fld("API key do reranker" + keyChip(m.rer_key), keyInp("s-rkey"), "Fireworks ou Cohere.") + "</div></div>" +
        '<div class="stgrid">' + fld("Decisão (opcional)", selHTML([["off", "Desligado — só os tokens do LLM (padrão)"],
                                                                        ["hindsight", "Hindsight — hs-decide-1-flash · US$ 0,02/1M"]], (m.dec_provider || "off"), "s-dec")) +
        '<div id="s-dkey-wrap" hidden>' + fld("Chave hsk_ (decisão)" + keyChip(m.dec_key), keyInp("s-dkey"),
          "inference.hindsight.vectorize.io — por uso, sem assinatura. Pular = cada um paga só os tokens do próprio LLM.") + "</div></div>" +
        '<p class="small" id="s-samekey" hidden>LLM e embeddings no OpenAI: a mesma chave serve nos dois.</p>' +
        '<p class="small" id="s-rsame" hidden>Fireworks no embeddings e no reranker: a mesma chave serve nos dois.</p>' +
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
        const subscr = q("#s-prov") && ["claude-code", "xai-oauth"].includes(q("#s-prov").value);
        if (q("#s-model-wrap")) q("#s-model-wrap").hidden = false;
        if (q("#s-model")) {
          const pk = q("#s-prov") ? q("#s-prov").value : "";
          const pe = (m.providers && m.providers.llm || []).find(x => x.key === pk);
          q("#s-model").placeholder = "vazio = " + ((pe && pe.model) || "padrão do provedor");
        }
        if (q("#s-key-wrap")) q("#s-key-wrap").hidden = !!subscr;
        if (q("#s-auth-wrap")) q("#s-auth-wrap").hidden = !subscr;
        const same = openai && q("#s-emb").value === "openai";
        if (q("#s-ekey-wrap")) q("#s-ekey-wrap").hidden = same;
        if (q("#s-samekey")) q("#s-samekey").hidden = !same;
        const rer = q("#s-rer") ? q("#s-rer").value : "off";
        const rsame = rer === "fireworks" && q("#s-emb").value === "fireworks";
        if (q("#s-rkey-wrap")) q("#s-rkey-wrap").hidden = rer === "off" || rsame;
        if (q("#s-rsame")) q("#s-rsame").hidden = !rsame;
        if (q("#s-dkey-wrap")) q("#s-dkey-wrap").hidden = !q("#s-dec") || q("#s-dec").value !== "hindsight";
      }
    };
    if (q("#s-emb")) q("#s-emb").onchange = sync;
    if (q("#s-prov")) q("#s-prov").onchange = sync;
    if (q("#s-rer")) q("#s-rer").onchange = sync;
    if (q("#s-dec")) q("#s-dec").onchange = sync;
    sync();
    q("#s-apply").onclick = e => stBusy(e.currentTarget, "aplicando…", async () => {
      const body = {mode: sel};
      if (sel === "embed") {
        body.embeddings = q("#s-emb").value; body.key = q("#s-ekey") ? q("#s-ekey").value : "";
        if (body.embeddings !== "local" && !body.key && !m.emb_key) return stMsg(q("#s-m"), "late", "cole a API key do embeddings");
      } else if (sel === "full") {
        body.provider = q("#s-prov").value; body.model = q("#s-model") ? q("#s-model").value.trim() : "";
        body.embeddings = q("#s-emb").value; body.key = q("#s-key").value;
        body.emb_key = q("#s-ekey") ? q("#s-ekey").value : "";
        body.reranker = q("#s-rer") ? q("#s-rer").value : "off";
        body.reranker_key = q("#s-rkey") ? q("#s-rkey").value : "";
        body.decision = q("#s-dec")
          ? {provider: q("#s-dec").value, key: q("#s-dkey") ? q("#s-dkey").value : ""}
          : {provider: "off"};
        body.consent = q("#s-consent").checked;
        if (!body.consent) return stMsg(q("#s-m"), "late", "marque o aceite de envio à API");
        if (body.decision.provider === "hindsight" && !body.decision.key && !m.dec_key)
          return stMsg(q("#s-m"), "late", "cole a chave hsk_ da decisão — ou deixe Desligado (padrão)");
        const subscr = ["claude-code", "xai-oauth"].includes(body.provider);
        if (!subscr && !body.key && !m.llm_key) return stMsg(q("#s-m"), "late", "cole a API key do LLM");
        if (subscr && (m.llm_auth || {}).state === "pending" && (m.llm_auth || {}).provider === body.provider)
          return stMsg(q("#s-m"), "late", "autentique a assinatura primeiro (botão Autenticar ao lado)");
        const sameAcct = body.provider === "openai" && body.embeddings === "openai";
        if (!sameAcct && !body.emb_key && !m.emb_key) return stMsg(q("#s-m"), "late", "cole a API key do embeddings (" + (body.embeddings === "fireworks" ? "Fireworks" : "OpenAI") + ")");
        const rsame = body.reranker === "fireworks" && body.embeddings === "fireworks";
        if (rsame && !body.emb_key && !m.emb_key && !body.reranker_key)
          return stMsg(q("#s-m"), "late", "cole a API key do Fireworks (embeddings e reranker usam a mesma conta)");
        if (body.reranker !== "off" && !rsame && !body.reranker_key && !m.rer_key)
          return stMsg(q("#s-m"), "late", "cole a API key do reranker (" + (body.reranker === "fireworks" ? "Fireworks" : "Cohere") + ")");
      }
      try {
        const r = await obAct("memory", body);
        if (q("#s-key")) q("#s-key").value = "";
        if (q("#s-ekey")) q("#s-ekey").value = "";
        if (q("#s-rkey")) q("#s-rkey").value = "";
        if (r.job) { const log = q("#s-log"); log.hidden = false;
          const j = await obJob(r.job, jj => { log.textContent = (jj.log || []).join("\n"); log.scrollTop = 1e9; });
          if (j.status === "error") return stMsg(q("#s-m"), "late", (j.result && j.result.error) || "não consegui mudar a memória"); }
        await obState(); toast("memória: modo " + (MEM_LABEL[SS.memory.mode] || SS.memory.mode)); SETUP.memoria(box);
      } catch (err) { stMsg(q("#s-m"), "late", err.message); }
    });
    const authBtn = q("#s-auth");
    if (authBtn) authBtn.onclick = e => stBusy(e.currentTarget, "autenticando…", async () => {
      try {
        const r = await obAct("memory_auth", {provider: q("#s-prov").value});
        if (r.job) { const log = q("#s-log"); log.hidden = false;
          const j = await obJob(r.job, jj => { log.textContent = (jj.log || []).join("\n"); log.scrollTop = 1e9; });
          if (j.status === "error") return stMsg(q("#s-m"), "late", (j.result && j.result.error) || "não consegui autenticar");
          stMsg(q("#s-m"), (j.result && j.result.ok === false) ? "late" : "ok",
                (j.result && j.result.ok === false) ? "autenticação não completou — o log acima diz o que faltou" : "✓ autenticado");
        }
        await obState(); SETUP.memoria(box);
      } catch (err) { stMsg(q("#s-m"), "late", err.message); }
    });
  };
  draw();
};
SETUP.agente = box => {
  const agents = SS.agents || [];
  const sn = SS.mcp_snippets || {};
  let picked = (agents.find(a => a.selected) || agents.find(a => a.mcp)
    || (SS.agent_mode === "manual" ? {key: "other"} : null)
    || agents.find(a => a.detected) || agents[0] || {key: "other"}).key;
  let manualHint = "";
  const extractCmd = h => { const m = String(h || "").match(/`([^`]+)`/); return m ? m[1] : String(h || ""); };
  const draw = () => {
    const isOther = picked === "other";
    const stAg = (SS.setup && "agente" in SS.setup) ? SS.setup.agente : agents.some(a => a.mcp);
    const cards = agents.map(a =>
      '<button class="stopt' + (a.key === picked ? " sel" : "") + '" data-ag="' + esc(a.key) + '"><b>' + esc(a.label) +
      (a.detected ? ' <span class="chip h-em-dia">detectado</span>' : ' <span class="chip">não detectado</span>') +
      (a.mcp ? ' <span class="chip h-em-dia">conectado</span>' : "") + (a.selected ? ' <span class="chip h-info">ativo</span>' : "") +
      '</b><span>' + (a.detected ? (a.runner ? "instalado · runner: " + esc(a.runner) : "instalado · chat e canais") : "não encontrado no PATH") + "</span></button>"
    ).join("") +
      '<button class="stopt' + (isOther ? " sel" : "") + '" data-ag="other"><b>Outros harnesses' +
      (SS.agent_mode === "manual" ? ' <span class="chip h-info">manual</span>' : "") +
      '</b><span>Qualquer cliente MCP (stdio): JSON, TOML ou CLI</span></button>';
    const bodyOther =
      '<p class="small">Cole um dos snippets abaixo na configuração MCP do seu harness e marque como configurado manualmente.</p>' +
      '<div><b>JSON (mcpServers)</b> <button class="btn" type="button" data-copy="json">Copiar</button><pre>' + esc(sn.json || "") + "</pre></div>" +
      '<div><b>TOML ([mcp_servers.brain])</b> <button class="btn" type="button" data-copy="toml">Copiar</button><pre>' + esc(sn.toml || "") + "</pre></div>" +
      '<div><b>Linha de comando (stdio)</b> <button class="btn" type="button" data-copy="cli">Copiar</button><pre>' + esc(sn.cli || "") + "</pre></div>" +
      '<div class="stactions"><span class="stmsg" id="ag-m"></span><button class="btn primary" id="ag-manual">Marcar como configurado manualmente</button></div>';
    const bodyAgent =
      (manualHint ? '<div id="ag-hint"><b>Receita manual para concluir</b> <button class="btn" type="button" id="ag-copy-hint">Copiar comando</button><pre>' + esc(manualHint) + "</pre></div>" : "") +
      '<pre class="stlog" id="ag-log" hidden></pre>' +
      '<div class="stactions"><span class="stmsg" id="ag-m"></span><button class="btn primary" id="ag-go">Conectar o canal de leitura</button></div>';
    box.innerHTML = sec("Seu agente de IA",
      '<p class="small">O cérebro funciona com um agente para ler suas fontes e ajudar nas rotinas. Conectar cria o canal de leitura (MCP somente-leitura) — o agente consulta, nunca escreve.</p>' +
      '<div class="stopts">' + cards + "</div>" + (isOther ? bodyOther : bodyAgent),
      stStatus(stAg).replace("feito", "conectado"));
    const q = s => box.querySelector(s);
    box.querySelectorAll("[data-ag]").forEach(b => b.onclick = () => { picked = b.dataset.ag; manualHint = ""; draw(); });
    box.querySelectorAll("[data-copy]").forEach(b => b.onclick = () => { copyCmd(sn[b.dataset.copy] || ""); toast("snippet copiado"); });
    if (q("#ag-copy-hint")) q("#ag-copy-hint").onclick = () => { copyCmd(extractCmd(manualHint)); toast("comando copiado"); };
    const manualBtn = q("#ag-manual");
    if (manualBtn) manualBtn.onclick = e => stBusy(e.currentTarget, "salvando…", async () => {
      try {
        await obAct("agent_connect", {agent: "other"});
        await obState(); toast("agente marcado como manual"); SETUP.agente(box);
      } catch (err) { stMsg(q("#ag-m"), "late", err.message); }
    });
    const goBtn = q("#ag-go");
    if (goBtn) goBtn.onclick = e => stBusy(e.currentTarget, "conectando…", async () => {
      if (!picked || picked === "other") return stMsg(q("#ag-m"), "late", "escolha um agente acima");
      try {
        const r = await obAct("agent_connect", {agent: picked});
        let res = r;
        if (r.job) { const log = q("#ag-log"); log.hidden = false;
          const j = await obJob(r.job, jj => { log.textContent = (jj.log || []).join("\n"); log.scrollTop = 1e9; });
          if (j.status === "error") return stMsg(q("#ag-m"), "late", (j.result && j.result.error) || "não consegui conectar");
          res = j.result || {}; }
        await obState();
        if (!res.mcp && res.hint) {
          manualHint = res.hint;
          draw();
          stMsg(q("#ag-m"), "late", "MCP não registrado automaticamente — siga a receita acima.");
          return;
        }
        toast("canal de leitura conectado"); SETUP.agente(box);
      } catch (err) { stMsg(q("#ag-m"), "late", err.message); }
    });
  };
  draw();
};
SETUP.integracoes = box => {
  const gh = SS.keys.GITHUB_TOKEN || {};
  const gk = SS.keys || {};
  const gset = k => gk[k] && gk[k].set;
  box.innerHTML = sec("Sugestões e bugs do Brain", '<p>Com um token do GitHub, as sugestões que você manda pelo Brain viram issues públicas no repo do framework. <a href="https://github.com/settings/tokens/new?scopes=public_repo&description=Brain%20%E2%80%94%20sugest%C3%B5es%20e%20bugs" target="_blank" rel="noopener">Criar token →</a> (escopo <code>public_repo</code> já marcado, sem validade)</p>' +
      fld("Token do GitHub", '<input type="password" id="s-gh" autocomplete="off" placeholder="' + (gh.set ? "vazio mantém o atual" : "ghp_…") + '">') +
      '<div class="stactions"><span class="stmsg" id="s-m"></span><button class="btn primary" id="s-save">Salvar</button></div>', stStatus(gh.set).replace("feito", "configurado")) +
    sec("Google — foco na agenda e backup no Drive" + (gset("GOOGLE_REFRESH_TOKEN") ? ' <span class="chip h-em-dia">conectado</span>' : ""),
      '<p class="small">Blocos de foco aprovados entram direto no Google Calendar, e o backup semanal sobe pro Drive. Escopo mínimo: só eventos que o Brain cria + os próprios zips de backup.</p>' +
      '<div class="stgrid">' +
      fld("Client ID" + (gset("GOOGLE_CLIENT_ID") ? ' <span class="chip h-em-dia">já salvo</span>' : ""),
          '<input type="text" id="s-gcid" autocomplete="off" placeholder="' + (gset("GOOGLE_CLIENT_ID") ? "vazio mantém o atual" : "…apps.googleusercontent.com") + '">') +
      fld("Client Secret" + (gset("GOOGLE_CLIENT_SECRET") ? ' <span class="chip h-em-dia">já salvo</span>' : ""),
          '<input type="password" id="s-gsec" autocomplete="off" placeholder="' + (gset("GOOGLE_CLIENT_SECRET") ? "vazio mantém o atual" : "GOCSPX-…") + '">') +
      "</div>" +
      '<p class="small">Crie em <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">Google Cloud Console</a> → Credenciais → ID do cliente OAuth (app Desktop).</p>' +
      '<pre class="stlog" id="s-glog" hidden></pre>' +
      '<div class="stactions"><button class="btn primary" id="s-gcon">Conectar Google</button><span class="stmsg" id="s-gm"></span></div>');
  const q = s => box.querySelector(s);
  q("#s-save").onclick = e => stBusy(e.currentTarget, "salvando…", async () => {
    const v = q("#s-gh").value.trim();
    if (!v) return stMsg(q("#s-m"), "late", "cole o token");
    try { await obAct("keys", {GITHUB_TOKEN: v}); q("#s-gh").value = ""; await obState(); redo("integracoes"); toast("token salvo no config/.env"); }
    catch (err) { stMsg(q("#s-m"), "late", err.message); }
  });
  q("#s-gcon").onclick = e => stBusy(e.currentTarget, "conectando…", async () => {
    try {
      const r = await obAct("foco_google", {client_id: q("#s-gcid").value, client_secret: q("#s-gsec").value});
      if (r.job) { const log = q("#s-glog"); log.hidden = false;
        const j = await obJob(r.job, jj => { log.textContent = (jj.log || []).join("\n"); log.scrollTop = 1e9; });
        if (j.status === "error") return stMsg(q("#s-gm"), "late", (j.result && j.result.error) || "não consegui conectar o Google"); }
      q("#s-gsec").value = "";
      await obState(); redo("integracoes"); toast("Google conectado — foco na agenda e backup ativos");
    } catch (err) { stMsg(q("#s-gm"), "late", err.message); }
  });
};

// ── face Configurações: troca de provedor da memória (mesma linha do CLI; sem campos condicionais:
//    um select por slot, "manter" nos que não mudam — o preview monta só a linha do slot escolhido) ──
function wireCfgMemoria(){
  const b = document.querySelector("[data-provform]");
  if (b) b.onclick = () => provForm();
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
const kbtn = $("#openpal b"); if (kbtn) kbtn.textContent = KMOD;
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
    const n = col.querySelector("h2 .count, h3 .count"); if (!n) return;
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
    if (el.dataset.url) {
      const u = window.BRAIN && window.BRAIN.safeUrl ? window.BRAIN.safeUrl(el.dataset.url) : "";
      if (u) window.open(u, "_blank", "noopener"); else toast("URL inválida para este documento");
    } else toast("documento do vault: " + (el.children[2] ? el.children[2].textContent : ""));
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
  const rows = fm.fields.filter(f => f.auto !== "surface").map(f => {
    const lab = esc(F.label(f, M)) + (f.req ? ' <span class="req">*</span>' : ""), ph = F.fmt(f.ph || "", ctx), val = init[f.id] || "";
    const ctl = f.choices !== undefined ? '<select data-k="' + f.id + '">' + optHTML(f, init, val) + "</select>"
      : f.multi ? '<textarea data-k="' + f.id + '" rows="5"' + (ph ? ' placeholder="' + esc(ph) + '"' : "") + ">" + esc(val) + "</textarea>"
      : '<input data-k="' + f.id + '" type="' + (f.secret ? "password" : "text") + '" value="' + esc(val) + '"' +
        (ph ? ' placeholder="' + esc(ph) + '"' : "") + (f.suggest ? ' autocomplete="off" data-suggest="' + esc(f.suggest) + '"' : "") + ">";
    const sug = f.suggest ? '<div class="fsug" data-sug="' + f.id + '" hidden></div>' : "";
    return '<div data-row="' + f.id + '"><div class="frow"><label>' + lab + "</label>" + ctl + "</div>" + sug +
      '<div class="note-s fhint" data-hint="' + f.id + '" style="margin:-4px 0 8px 130px"></div></div>'; }).join("");
  const title = F.fmt(fm.title, ctx), sub = F.fmt(fm.sub || "", ctx);
  const ov = document.createElement("div"); ov.className = "pal-back open";
  ov.innerHTML = '<div class="palette"><div class="pin"><b>' + esc(title) + "</b>" + (fm.gate ? ' <span class="gatebadge">gate — confirmar aprova</span>' : "") + "</div>" +
    '<div class="pal-confirm open" style="display:block;border-top:0;padding:14px 16px;max-height:70vh;overflow:auto">' +
    (sub ? '<p class="note-s" style="margin:0 0 10px">' + esc(sub) + "</p>" : "") + (opts.extra || "") + rows +
    '<div class="cline" data-preview style="min-height:34px;white-space:pre"></div>' +
    '<div class="dup-box" data-dup-box hidden style="margin:8px 0;padding:10px 12px;border:1px solid var(--warn, #b45309);border-radius:8px;background:rgba(180,83,9,.08)"></div>' +
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
    fm.fields.filter(f => f.auto !== "surface").forEach(f => { const row = ov.querySelector('[data-row="' + f.id + '"]'); if (row) row.hidden = hid.has(f.id);
      const h = ov.querySelector('[data-hint="' + f.id + '"]'); if (h) h.textContent = f.hint && w[f.id] ? F.hint(f.hint, w[f.id], w, ctx, M) : ""; });
    ov.querySelector("[data-preview]").textContent = "$ " + F.display(F.formArgv(fm, v, ctx, M)).replace(/\n/g, "\n$ ");
    ov.querySelector("[data-err]").textContent = "";
  };
  const sugState = {};
  const sugTok = val => val.includes(",") ? val.split(",").pop().trim() : val.trim();
  const closeSug = id0 => {
    (id0 ? [id0] : Object.keys(sugState)).forEach(k => {
      const st = sugState[k]; if (!st) return;
      st.open = false; st.nav = false;
      if (st.box) { st.box.hidden = true; st.box.innerHTML = ""; }
    });
  };
  const renderSug = f => {
    const st = sugState[f.id]; if (!st || !st.box) return;
    if (!st.open || !st.items.length) { st.box.hidden = true; st.box.innerHTML = ""; return; }
    st.box.hidden = false;
    st.box.innerHTML = st.items.map((it, i) =>
      '<div class="fsug-item' + (i === st.sel ? " sel" : "") + '" data-i="' + i + '" data-id="' + esc(it.id) + '">' +
      '<span class="ent">' + esc(it.id) + "</span>" +
      (it.label && it.label !== it.id ? "<span>" + esc(it.label) + "</span>" : "") + "</div>"
    ).join("");
    st.box.querySelectorAll(".fsug-item").forEach(row => {
      row.onmouseenter = () => { st.sel = +row.dataset.i; renderSug(f); };
      row.onmousedown = ev => { ev.preventDefault(); applySug(f, st.items[+row.dataset.i]); };
      row.onclick = ev => { ev.preventDefault(); applySug(f, st.items[+row.dataset.i]); };
    });
  };
  const refreshSug = (f, forceOpen) => {
    const inp = el(f.id), st = sugState[f.id]; if (!inp || !st) return;
    const tok = sugTok(inp.value);
    if (!tok && !forceOpen) { closeSug(f.id); return; }
    Object.keys(sugState).forEach(k => { if (k !== f.id) closeSug(k); });
    st.items = F.filterOptions(opt(f, vals()), tok);
    st.sel = 0; st.open = st.items.length > 0;
    renderSug(f);
  };
  const applySug = (f, chosen) => {
    const inp = el(f.id); if (!inp || !chosen) return;
    const cur = inp.value;
    inp.value = cur.includes(",") ? cur.slice(0, cur.lastIndexOf(",")).trimEnd() + ", " + chosen.id : chosen.id;
    closeSug(f.id);
    changed(f.id);
    inp.focus();
  };
  const dupBox = ov.querySelector("[data-dup-box]");
  const clearDup = () => {
    if (!dupBox) return;
    dupBox.hidden = true;
    dupBox.textContent = "";
  };
  const parseDupCandidates = errTxt => {
    const lines = String(errTxt || "").split(/\r?\n/);
    const idx = lines.findIndex(l => /possível ação duplicada — nada gravado/.test(l));
    if (idx >= 0) {
      const cands = [];
      for (let i = idx + 1; i < lines.length; i++) {
        const t = lines[i].trim();
        if (!t) continue;
        if (/^se for a mesma\b/i.test(t) || /^se for outra\b/i.test(t)) break;
        cands.push(t);
      }
      if (cands.length) return cands;
    }
    const trimmed = String(errTxt || "").trim();
    return trimmed ? [trimmed] : [];
  };
  let submitting = false;
  const showDup = (cands, pendingCmds) => {
    if (!dupBox) return;
    dupBox.textContent = "";
    dupBox.hidden = false;
    const hd = document.createElement("div");
    hd.style.fontWeight = "600";
    hd.style.marginBottom = "4px";
    hd.textContent = "Possível duplicata";
    dupBox.appendChild(hd);
    const ul = document.createElement("ul");
    ul.style.margin = "4px 0 8px 18px";
    ul.style.padding = "0";
    cands.forEach(line => {
      const li = document.createElement("li");
      li.textContent = line;
      ul.appendChild(li);
    });
    dupBox.appendChild(ul);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn primary";
    btn.setAttribute("data-force-submit", "1");
    btn.textContent = "Criar mesmo assim";
    btn.onclick = () => sendCmds(pendingCmds.map((c, idx) => idx === 0 && !c.includes("--force") ? c.concat(["--force"]) : c), true);
    dupBox.appendChild(btn);
  };
  const sendCmds = async (cmds, forced) => {
    if (submitting) return;
    if (!LIVE || id !== "action.new") {
      close();
      runArgv(cmds, m => opts.run && opts.run(F.values(fm, vals(), ctx, M), m));
      return;
    }
    submitting = true;
    const okBtn = ov.querySelector("[data-ok]");
    const forceBtn = dupBox && dupBox.querySelector("[data-force-submit]");
    if (okBtn) okBtn.disabled = true;
    if (forceBtn) forceBtn.disabled = true;
    let lastResp = null;
    let ok = false;
    try {
      ok = await runArgv(cmds, m => opts.run && opts.run(F.values(fm, vals(), ctx, M), m), r => { lastResp = r; });
    } finally {
      submitting = false;
      if (okBtn) okBtn.disabled = false;
      if (forceBtn) forceBtn.disabled = false;
    }
    if (ok) {
      close();
      return;
    }
    const errTxt = (lastResp && lastResp.err) || "";
    if (!forced && lastResp && !lastResp.ok && /possível ação duplicada — nada gravado/.test(errTxt)) {
      showDup(parseDupCandidates(errTxt), cmds);
      return;
    }
    close();
  };
  const changed = id0 => {
    clearDup();
    fm.fields.filter(f => f.depends === id0 && f.choices !== undefined).forEach(f => { const e = el(f.id); e.innerHTML = optHTML(f, vals(), e.value); });
    fm.fields.filter(f => f.fill && f.fill[0] === id0).forEach(f => { const nv = F.FILL[f.fill[1]](vals()), e = el(f.id);
      if (nv !== undefined && e) { e.value = nv; closeSug(f.id); } });
    paint();
  };
  const submit = () => {
    const v = vals(), msg = F.missing(fm, v, ctx, M);
    if (msg) { ov.querySelector("[data-err]").textContent = msg; const p = ov.querySelector("[data-preview]");
      p.classList.add("miss"); setTimeout(() => p.classList.remove("miss"), 600); return; }
    let cmds = F.formArgv(fm, v, ctx, M); if (opts.wrap) cmds = opts.wrap(cmds, F.values(fm, v, ctx, M));
    sendCmds(cmds, false);
  };
  fm.fields.filter(f => f.auto !== "surface" && f.suggest).forEach(f => {
    sugState[f.id] = {items: [], sel: 0, open: false, nav: false, box: ov.querySelector('[data-sug="' + f.id + '"]')};
  });
  ov.querySelectorAll("[data-k]").forEach(e => {
    const f = fm.fields.find(x => x.id === e.dataset.k), st = f && sugState[f.id];
    e.addEventListener("input", () => { if (st) { st.nav = false; refreshSug(f, false); } changed(e.dataset.k); });
    if (e.tagName === "SELECT") e.addEventListener("change", () => changed(e.dataset.k));
    else e.addEventListener("change", clearDup);
    if (st) e.addEventListener("focus", () => Object.keys(sugState).forEach(k => { if (k !== f.id) closeSug(k); }));
    e.addEventListener("keydown", ev => {
      if (st) {
        if (ev.key === "ArrowDown") {
          ev.preventDefault();
          if (!st.open) { st.nav = true; refreshSug(f, true); }
          else if (st.items.length) { st.nav = true; st.sel = Math.min(st.items.length - 1, st.sel + 1); renderSug(f); }
          return;
        }
        if (ev.key === "ArrowUp" && st.open) {
          ev.preventDefault(); st.nav = true; st.sel = Math.max(0, st.sel - 1); renderSug(f); return;
        }
        if (ev.key === "Escape" && st.open) {
          ev.preventDefault(); ev.stopPropagation(); closeSug(f.id); return;
        }
        if (ev.key === "Enter" && st.open && st.items[st.sel]) {
          const chosen = st.items[st.sel], tok = sugTok(e.value);
          if (tok !== chosen.id || st.nav) {
            ev.preventDefault(); ev.stopPropagation(); applySug(f, chosen); return;
          }
          closeSug(f.id);
        }
      }
      if (ev.key === "Enter" && (e.tagName !== "TEXTAREA" || ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); submit(); }
    });
  });
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
async function runArgv(cmds, mut, onResp){
  const lines = cmds.map(c => "brain " + window.BRAIN_FORMS.shjoin(c));
  if (!LIVE) { offlineCmd(lines.join(" && ")); return true; }
  for (const ln of lines) { if (!(await serveRun(ln, onResp))) return false; }
  return true;
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
function isAgentOk(){
  return !!(window.BRAIN && window.BRAIN.M ? window.BRAIN.M.agent_ok : D0.agent_ok);
}
function agentToast(what, how, why){
  toast("(agente) " + what + " — rode " + how + " no chat" + (why ? " (" + why + ")" : "; o painel não roda o agente"));
}
async function runAgent(action, arg, what, how){
  if (!LIVE) { agentToast(what, how, "ponte serve desligada"); return false; }
  if (!isAgentOk()) { agentToast(what, how, "runner não configurado"); return false; }
  conToggle(true);
  conLine('<span class="dim">⚡</span> ' + esc(how || ("/" + action + (arg ? " " + arg : ""))));
  let res;
  try {
    res = await api("/api/agent", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action: action, arg: arg || ""}),
    });
  } catch (e) {
    conLine('<span class="late">ponte fora do ar — ./brain serve</span>');
    return false;
  }
  if (!res.ok) {
    const msg = res.error || "falha ao iniciar ação do agente";
    conLine('<span class="late">' + esc(msg) + "</span>");
    toast(msg);
    return false;
  }
  toast("⚡ " + what + " — executando…");
  let seen = 0, job = null;
  while (true) {
    await new Promise(r => setTimeout(r, 800));
    let jr;
    try {
      jr = await api("/api/agent/job/" + encodeURIComponent(res.id));
    } catch (e) {
      conLine('<span class="late">perdeu contato com a ponte durante a execução</span>');
      toast("perdeu contato com a ponte");
      return false;
    }
    if (!jr.ok || !jr.job) {
      conLine('<span class="late">execução do agente não encontrada</span>');
      return false;
    }
    job = jr.job;
    const lines = job.lines || [];
    for (; seen < lines.length; seen++) {
      const ln = lines[seen];
      conLine('<span class="' + (ln.startsWith("✓") ? "ok" : "dim") + '">' + esc(ln) + "</span>");
    }
    if (job.status !== "running") break;
  }
  const ok = job.status === "done" && job.rc === 0;
  if (ok) {
    conLine('<span class="ok">✓ ' + esc(what) + " concluído</span>");
    toast("✓ " + what + " concluído");
  } else {
    const errMsg = "✗ " + what + " falhou (código " + job.rc + ")";
    conLine('<span class="late">' + esc(errMsg) + "</span>");
    toast(errMsg);
  }
  try {
    const d = await api("/api/data");
    if (window.BRAIN && window.BRAIN.refresh) window.BRAIN.refresh(d.model);
  } catch (e) { /* views regeneram no próximo render */ }
  return ok;
}
function pickSourceAgent(){
  const srcs = (window.BRAIN && window.BRAIN.M && window.BRAIN.M.sources) || [];
  if (!srcs.length) { toast("Nenhuma fonte conhecida. Cadastre em Fontes (tecla n)."); return; }
  const ov = document.createElement("div"); ov.className = "pal-back open";
  ov.innerHTML = '<div class="palette"><div class="pin"><b>Puxar qual fonte? (/connect)</b><span class="hint">esc fecha</span></div>' +
    '<div class="pal-list">' + srcs.map(s =>
      '<div class="pal-item" data-src="' + esc(s.key) + '"><span class="ent">' + esc(s.kind || "avulsa") + "</span>" +
      "<span>" + esc(s.key) + "</span>" + (s.in_watch ? "" : '<span class="cmd">fora do watch</span>') + "</div>"
    ).join("") + "</div></div>";
  document.body.appendChild(ov);
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  ov.querySelectorAll("[data-src]").forEach(el => {
    el.onclick = () => { const k = el.dataset.src; ov.remove(); runAgent("connect", k, "puxar " + k, "/connect " + k); };
  });
}
function agentArgPrompt(action, title, argLabel, argPh, required){
  if (!LIVE || !isAgentOk()) { runAgent(action, "", title, "/" + action); return; }
  const ov = document.createElement("div"); ov.className = "pal-back open";
  ov.innerHTML = '<div class="palette"><div class="pin"><b>' + esc(title) + '</b><span class="hint">esc fecha</span></div>' +
    '<div class="pal-confirm open" style="display:block;border-top:0;padding:14px 16px">' +
    '<div class="frow"><label>' + esc(argLabel) + (required ? ' <span class="req">*</span>' : "") + '</label>' +
    '<input type="text" data-arg placeholder="' + esc(argPh || "") + '"></div>' +
    '<div class="note-s" data-err style="margin:0 0 6px;color:var(--risk)"></div>' +
    '<div class="row"><span class="note-s">enter confirma · esc cancela</span>' +
    '<button class="btn ghost" data-x>cancelar</button><button class="btn primary" data-ok>executar</button></div></div></div>';
  document.body.appendChild(ov);
  const inp = ov.querySelector("[data-arg]"), err = ov.querySelector("[data-err]");
  const submit = () => {
    const val = (inp.value || "").trim();
    if (required && !val) { err.textContent = "preencha: " + argLabel; inp.focus(); return; }
    ov.remove();
    runAgent(action, val, title, "/" + action + (val ? " " + val : ""));
  };
  ov.querySelector("[data-x]").onclick = () => ov.remove();
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  ov.querySelector("[data-ok]").onclick = submit;
  inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
  inp.focus();
}
function healthFix(fix){
  if (fix.agent === "dump") runAgent("dump", "", "processar a inbox", "/dump");
  else if (fix.agent === "connect") runAgent("connect", fix.key, "puxar " + fix.key, "/connect " + fix.key);
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
    const AG = {u: ["update", "atualizar tudo", "/update"], d: ["dump", "processar a inbox", "/dump"],
      b: ["brief", "brief do dia", "/brief"], w: ["week", "cockpit da semana", "/week"],
      i: ["init", "primeira entrevista", "/init"]};
    if (AG[k]) { runAgent(AG[k][0], "", AG[k][1], AG[k][2]); return true; }
    if (k === "c") {
      if (!LIVE || !isAgentOk()) { runAgent("connect", "", "puxar uma fonte", "/connect <fonte>"); return true; }
      pickSourceAgent(); return true;
    }
    return false; }
  if (h.startsWith("#sources")) {
    if (k === "n") { srcAddForm(); return true; }
    const sid = selId() || "", src = sid.startsWith("src:") ? (M.sources || []).find(x => x.key === sid.slice(4)) : null;
    if (k === "u") { runAgent("update", "", "atualizar tudo", "/update"); return true; }
    if (!["e", "d", "w", "c"].includes(k)) return false;
    if (!src) { needSel(); return true; }
    if (k === "e") { if (src.in_watch) srcEditForm(src); else toast(src.key + " é pull avulso — w inclui no watch.toml"); return true; }
    if (k === "d") { if (src.in_watch) srcRemoveForm(src); else toast(src.key + " não está no watch.toml"); return true; }
    if (k === "w") { if (!src.in_watch) srcAddForm({key: src.key}); else toast(src.key + " já está no watch.toml"); return true; }
    runAgent("connect", src.key, "puxar " + src.key, "/connect " + src.key); return true; }
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
    const fid = selId() || "";
    const fb = fid.startsWith("FB-") ? M.feedback.find(x => x.id === fid) : null;
    if (k === "p") {
      if (fb && (fb.status === "pendente" || fb.status === "falhou")) runCommand("brain feedback push " + fb.id + " --approval painel");
      else if (!fb) needSel();
      else toast(fb.id + " está " + fb.status + " — publicar vale para pendente ou falhou");
      return true; }
    if (k === "d") {
      if (fb && (fb.status === "pendente" || fb.status === "falhou")) feedbackWithdrawForm(fb);
      else if (!fb) needSel();
      else toast(fb.id + " está " + fb.status + " — retirar vale para rascunho pendente ou falhou");
      return true; }
    if (k === "r") {
      if (fb && fb.status === "criado") feedbackRetractForm(fb);
      else if (!fb) needSel();
      else toast(fb.id + " está " + fb.status + " — retratar vale para issue publicada");
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
    ["g : " + KMOD, "busca e comandos (paleta)"],
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
    ["Sugestões", ""], ["n", "nova"], ["p", "publicar"], ["d", "retirar rascunho"], ["r", "retratar issue"], ["s", "sincronizar issues"],
    ["Portfólio · Oportunidades", ""], ["n", "nova"], ["s", "status"], ["i", "ICE"], ["c", "confirmar ICE sugerido"],
    ["e", "editar"], ["d", "descartar"], ["p", "promover (gate)"], ["O", "one-pager (agente)"], ["L", "ligar documento"], ["v", "evidência"],
    ["Portfólio · Processos", ""], ["n", "novo"], ["e", "editar"], ["a", "nova oportunidade daqui"], ["d", "aposentar"], ["L", "ligar documento"], ["o", "abrir playbook"],
    ["Portfólio · Matriz", ""], ["s", "status"], ["i", "ICE"],
    ["Portfólio · Documentos", ""], ["L", "ligar"], ["d", "desligar"], ["enter", "abrir"],
    ["Configurações · Memória", ""], ["s", "trocar provedor"],
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

// handler único de teclado: captura global para Ctrl/⌘K, depois paleta e teclas de página
window.addEventListener("keydown", e => {
  if (document.body.classList.contains("obmode")) return;   // wizard (F8): sem paleta na configuração
  if ((e.metaKey || e.ctrlKey) && !e.altKey && ((e.key && ["k", "p"].includes(e.key.toLowerCase())) || e.code === "KeyK")) {
    e.preventDefault(); e.stopPropagation(); pal.open ? closePal() : openPal();
  }
}, true);
document.addEventListener("keydown", e => {
  if (pal.open) {
    if (e.key === "Escape") closePal();
    if (e.key === "ArrowDown") { e.preventDefault(); pal.sel = Math.min(pal.items.length - 1, pal.sel + 1); renderPal(); }
    if (e.key === "ArrowUp") { e.preventDefault(); pal.sel = Math.max(0, pal.sel - 1); renderPal(); }
    if (e.key === "Enter") { e.preventDefault(); if ($("#palconfirm").classList.contains("open")) $("#palrun").click(); else pick(pal.sel); }
    return;
  }
  const openOv = document.querySelector(".pal-back.open");             // form/dialog aberto: só Esc fecha
  if (openOv) {
    if (e.key === "Escape") {
      if (openOv.id === "newsback") { openOv.classList.remove("open"); openOv.hidden = true; }
      else openOv.remove();
    }
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
    add("n", "sugerir/corrigir");
    add("p", "publicar", !(fb && (fb.status === "pendente" || fb.status === "falhou")));
    add("d", "retirar", !(fb && (fb.status === "pendente" || fb.status === "falhou")));
    add("r", "retratar", !(fb && fb.status === "criado"));
    add("s", "sincronizar"); add("T", hashAll() ? "só pendentes" : "todas");
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
  else if (h.startsWith("#cfg/memoria")) { add("s", "provedor"); }
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
    '" data-k="' + esc(x.k) + '" title="' + (x.gate ? "gate — confirmar aprova · " : "") + "tecla " + esc(x.k) + '">' +
    "<kbd>" + esc(x.k) + "</kbd>" + esc(x.label) + "</button>").join("");
  bar.innerHTML = '<div class="kctx">' + (ctx || '<span class="knone">sem teclas de contexto nesta página — j/k navega, enter abre</span>') + "</div>" +
    '<div class="kglobal">' + (lfLevels().length ? '<button class="kkey lfon" data-g="esc" title="tira o último filtro da lista"><kbd>esc</kbd>tira filtro (' + lfLevels().length + ')</button>' : "") +
    '<button class="kkey" data-g="/" title="filtrar a lista desta página; de novo refina o filtro"><kbd>/</kbd>' + (lfLevels().length ? "refinar" : "filtrar") + '</button>' +
    '<button class="kkey" data-g="g" title="paleta de busca e comandos (' + KMOD + ')"><kbd>g</kbd>busca</button>' +
    '<button class="kkey" data-g="tab" title="trocar de face"><kbd>tab</kbd>face</button>' +
    '<button class="kkey" data-g="?" title="mapa de teclas"><kbd>?</kbd>ajuda</button></div>';
  bar.querySelectorAll("[data-k]").forEach(b => b.onclick = () => ctxKeys(b.dataset.k));
  bar.querySelectorAll("[data-g]").forEach(b => b.onclick = () => {
    if (b.dataset.g === "/") lfOpen();
    else if (b.dataset.g === "g") openPal();
    else if (b.dataset.g === "esc") lfPop();
    else if (b.dataset.g === "?") helpOverlay();
    else location.hash = "#face/" + ((faceCur === "portfolio" || location.hash.startsWith("#pf/") || location.hash === "#people" || location.hash.startsWith("#person/")) ? "execucao" : "portfolio");
  });
}

// ── arrastar arquivo ou pasta para a inbox (ponte ./brain serve) ─────────
const INBOX_OFFLINE_MSG = "Ponte CLI inativa — rode ./brain serve para arrastar arquivos para o painel, ou salve direto em vault/RAW/inbox/.";
const INBOX_SKIP = new Set([".DS_Store", ".keep.md"]);
let inboxDragDepth = 0;

// Pasta de origem (File System Access API): o navegador não entrega o caminho de um arquivo
// arrastado. A ponte já procura o original no disco e apaga (byte a byte conferido); as pastas
// concedidas aqui são o COMPLEMENTO — cobrem pastas fora de HOME ou instâncias com a busca
// desligada ([serve].move_search = false). Várias pastas; lembradas no IndexedDB (porta fixa).
let inboxOrigins = null;                   // [{handle,name}] | null (ainda não carregado)
const INBOX_ORIGIN_DB = "brain-panel", INBOX_ORIGIN_STORE = "handles",
      INBOX_ORIGIN_KEY = "inbox-origins", INBOX_ORIGIN_LEGACY = "inbox-origin";
function inboxIdb(){
  return new Promise((res, rej) => {
    const q = indexedDB.open(INBOX_ORIGIN_DB, 1);
    q.onupgradeneeded = () => { q.result.createObjectStore(INBOX_ORIGIN_STORE); };
    q.onsuccess = () => res(q.result);
    q.onerror = () => rej(q.error);
  });
}
function inboxIdbGet(key){
  return new Promise(async (res, rej) => {
    try {
      const db = await inboxIdb();
      const rq = db.transaction(INBOX_ORIGIN_STORE, "readonly").objectStore(INBOX_ORIGIN_STORE).get(key);
      rq.onsuccess = () => res(rq.result || null);
      rq.onerror = () => rej(rq.error);
    } catch (e) { res(null); }
  });
}
function inboxIdbPut(key, val){
  return new Promise(async (res, rej) => {
    try {
      const db = await inboxIdb();
      const tx = db.transaction(INBOX_ORIGIN_STORE, "readwrite");
      if (val === null) tx.objectStore(INBOX_ORIGIN_STORE).delete(key);
      else tx.objectStore(INBOX_ORIGIN_STORE).put(val, key);
      tx.oncomplete = () => res();
      tx.onerror = () => rej(tx.error);
    } catch (e) { res(); }
  });
}
async function inboxOriginsLoad(){
  if (!("indexedDB" in window)) { inboxOrigins = []; return inboxOrigins; }
  let list = await inboxIdbGet(INBOX_ORIGIN_KEY);
  if (!list) {                                     // migração: chave única da 1ª versão
    const single = await inboxIdbGet(INBOX_ORIGIN_LEGACY);
    list = single && single.kind === "directory" ? [single] : [];
    if (list.length) { await inboxIdbPut(INBOX_ORIGIN_KEY, list); await inboxIdbPut(INBOX_ORIGIN_LEGACY, null); }
  }
  inboxOrigins = Array.isArray(list) ? list.filter(h => h && h.kind === "directory").map(h => ({handle: h, name: h.name})) : [];
  updateInboxDropHint();
  return inboxOrigins;
}
async function inboxOriginsSave(list){
  inboxOrigins = list.slice();
  await inboxIdbPut(INBOX_ORIGIN_KEY, list.map(o => o.handle));
  updateInboxDropHint();
}
async function inboxOriginsWritable(){
  // Chamada no instante do drop: requestPermission({mode:"readwrite"}) exige ativação de
  // usuário fresca — nunca depois dos envios, que podem demorar mais que a janela de ativação.
  if (!inboxOrigins) await inboxOriginsLoad();
  const out = [];
  for (const o of inboxOrigins) {
    try {
      if (await o.handle.queryPermission({mode: "readwrite"}) === "granted") { out.push(o.handle); continue; }
      if (await o.handle.requestPermission({mode: "readwrite"}) === "granted") out.push(o.handle);
    } catch (e) { /* sem ativação ou negado: fica para a busca da ponte */ }
  }
  return out;
}
async function inboxOriginRemove(handles, relPath, file){
  // Apaga APENAS sob nome+tamanho+horário+bytes idênticos ao que caiu — nunca por nome puro:
  // homônimo na pasta concedida com outro conteúdo é cópia mantida, não original apagado.
  for (const handle of handles) {
    try {
      const parts = relPath.split("/").filter(Boolean), name = parts.pop();
      if (!name) continue;
      let dir = handle;
      for (const seg of parts) dir = await dir.getDirectoryHandle(seg);
      const g = await (await dir.getFileHandle(name)).getFile();
      if (g.size !== file.size || g.lastModified !== file.lastModified) continue;
      const [aBuf, bBuf] = await Promise.all([file.arrayBuffer(), g.arrayBuffer()]);
      if (aBuf.byteLength !== bBuf.byteLength) continue;
      const aBytes = new Uint8Array(aBuf), bBytes = new Uint8Array(bBuf);
      let same = true;
      for (let i = 0; i < aBytes.length; i++) {
        if (aBytes[i] !== bBytes[i]) { same = false; break; }
      }
      if (!same) continue;
      await dir.removeEntry(name);
      return handle.name;
    } catch (e) { /* tenta a próxima pasta */ }
  }
  return null;
}
window.BRAIN_INBOX = { originRemove: inboxOriginRemove };
if (LIVE) inboxOriginsLoad();

function isFileDrag(e){
  if (dragId) return false;
  const dt = e && e.dataTransfer;
  if (!dt || !dt.types) return false;
  return Array.from(dt.types).includes("Files");
}
function ensureInboxDropOverlay(){
  let ov = document.getElementById("inbox-drop-ov");
  if (ov) return ov;
  ov = document.createElement("div");
  ov.id = "inbox-drop-ov";
  ov.className = "inbox-drop-ov";
  ov.hidden = true;
  if (LIVE) {
    ov.innerHTML =
      '<div class="inbox-drop-zone" data-drop-mode="move"><div class="inbox-drop-card">' +
      "<strong>Mover arquivo para a inbox</strong>" +
      '<span id="inbox-origin-hint">o original é apagado quando você define a pasta de origem</span></div></div>' +
      '<div class="inbox-drop-zone" data-drop-mode="copy"><div class="inbox-drop-card">' +
      "<strong>Copiar arquivo para a inbox</strong>" +
      "<span>mantém o original</span></div></div>";
    updateInboxDropHint();
  } else {
    ov.innerHTML =
      '<div class="inbox-drop-offline" role="status">' +
      "<strong>Ponte CLI inativa</strong>" +
      "<span>" + esc(INBOX_OFFLINE_MSG) + "</span></div>";
  }
  document.body.appendChild(ov);
  return ov;
}
function hideInboxDropOverlay(){
  inboxDragDepth = 0;
  const ov = document.getElementById("inbox-drop-ov");
  if (!ov) return;
  ov.hidden = true;
  ov.querySelectorAll(".active").forEach(el => el.classList.remove("active"));
}
function updateInboxDropHint(){
  // Estado vivo da zona Mover ANTES do dono soltar: a busca da ponte cobre o disco;
  // pastas concedidas somam (fora de HOME ou busca desligada).
  const el = document.getElementById("inbox-origin-hint");
  if (!el) return;
  const names = (inboxOrigins || []).map(o => o.name);
  const extra = names.length > 2 ? " +" + (names.length - 2) : "";
  el.textContent = names.length
    ? "apaga o original após enviar · busca no disco + pastas: " + names.slice(0, 2).join(", ") + extra
    : "apaga o original após enviar — a ponte acha o arquivo no disco (duplicado, ela pergunta)";
}
function inboxDropModeAt(e, ov){
  const r = ov.getBoundingClientRect();
  const mid = r.height ? r.top + r.height / 2 : window.innerHeight / 2;
  return e.clientY < mid ? "move" : "copy";
}
function paintInboxDropZone(mode){
  const ov = document.getElementById("inbox-drop-ov");
  if (!ov) return;
  ov.querySelectorAll("[data-drop-mode]").forEach(z => z.classList.toggle("active", z.dataset.dropMode === mode));
}
async function readAllDirEntries(reader){
  const all = [];
  for (;;) {
    const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch || !batch.length) break;
    all.push(...batch);
  }
  return all;
}
async function collectEntryFiles(entry, collected, rejected){
  if (!entry) return;
  if (INBOX_SKIP.has(entry.name)) { rejected.push(entry.name); return; }
  if (entry.isFile) {
    try {
      const f = await new Promise((resolve, reject) => entry.file(resolve, reject));
      if (INBOX_SKIP.has(f.name)) rejected.push(f.name);
      else collected.push({file: f, sourcePath: f.path || "", relPath: (entry.fullPath || "/" + f.name).replace(/^\/+/, "")});
    } catch (err) {
      rejected.push(entry.name || "arquivo ilegível");
    }
    return;
  }
  if (entry.isDirectory) {
    try {
      const children = await readAllDirEntries(entry.createReader());
      for (const ch of children) await collectEntryFiles(ch, collected, rejected);
    } catch (err) {
      rejected.push(entry.name || "pasta ilegível");
    }
    return;
  }
  rejected.push(entry.name || "item ignorado");
}
async function handleInboxDrop(mode, entries, fallbackFiles, rejected){
  const collected = [];
  if (entries.length) {
    for (const entry of entries) await collectEntryFiles(entry, collected, rejected);
  } else {
    for (const f of fallbackFiles) {
      if (INBOX_SKIP.has(f.name)) rejected.push(f.name);
      else collected.push({file: f, sourcePath: f.path || "", relPath: f.name});
    }
  }
  if (!collected.length) {
    conOpen();
    const emptyMsg = "Nenhum arquivo válido para enviar à inbox" +
      (rejected.length ? " (ignorados: " + rejected.join(", ") + ")" : "") + ".";
    conLine('<span class="dim">' + esc(emptyMsg) + "</span>");
    toast(emptyMsg, 4000);
    return;
  }
  conOpen();
  conLine('<span class="dim">$</span> inbox (' + esc(mode) + ") · " + collected.length + " arquivo(s)");
  // Permissão das pastas concedidas ANTES dos envios: requestPermission quer ativação fresca do drop.
  const originHandles = mode === "move" ? await inboxOriginsWritable() : [];
  const uploaded = [], failed = [], stillFallback = [], dupeGroups = [];
  let searchIncomplete = false, searchRan = false;
  for (const item of collected) {
    const fd = new FormData();
    fd.append("mode", mode);
    if (item.sourcePath) fd.append("source_path", item.sourcePath);
    fd.append("file", item.file, item.file.name);
    let r, j = null;
    try {
      r = await fetch("/api/inbox", {method: "POST", headers: {"X-Brain-Token": TOK || ""}, body: fd});
      if (r.status === 401) {
        handle401();
        conLine('<span class="late">✗ sessão expirada — reabra via ./brain render --open</span>');
        return;
      }
      try { j = await r.json(); } catch (e) {}
    } catch (err) {
      failed.push(item.file.name);
      conLine('<span class="late">✗ ' + esc(item.file.name) + ": ponte fora do ar — ./brain serve</span>");
      continue;
    }
    if (r.ok && j && j.ok) {
      uploaded.push(j);
      if (j.search) searchRan = true;
      if (j.search && !j.search_complete) searchIncomplete = true;
      let movedNote = j.moved ? " (original removido: " + (j.moved_from || "") + ")" : "";
      if (j.candidates && j.candidates.length) {
        movedNote = " (" + j.candidates.length + " cópias idênticas no disco — escolha quais apagar)";
        dupeGroups.push({file: item.file, inboxName: j.name, candidates: j.candidates});
      } else if (j.fallback_copy && originHandles.length) {
        // a busca da ponte não achou (arquivo fora de HOME ou busca desligada):
        // as pastas concedidas no navegador cobrem o resto, nome+tamanho+horário conferidos
        const originName = await inboxOriginRemove(originHandles, item.relPath, item.file);
        if (originName) movedNote = " (original removido de " + originName + ")";
        else stillFallback.push(item);
      } else if (j.fallback_copy) stillFallback.push(item);
      const renamed = j.name !== j.original ? " → " + j.name : "";
      conLine('<span class="ok">✓ ' + esc(j.original) + esc(renamed) + esc(movedNote) + "</span>");
    } else {
      const errMsg = (j && j.error) || ("erro " + r.status);
      failed.push(item.file.name);
      conLine('<span class="late">✗ ' + esc(item.file.name) + ": " + esc(errMsg) + "</span>");
    }
  }
  const summary = uploaded.length + " item(ns) enviado(s) para a inbox" +
    (rejected.length ? " · ignorados: " + rejected.join(", ") : "") +
    (failed.length ? " · falhas: " + failed.join(", ") : "");
  conLine('<span class="' + (uploaded.length ? "ok" : "late") + '">' + esc(summary) + "</span>");
  if (searchIncomplete)
    conLine('<span class="dim">busca no disco incompleta (muitos arquivos) — conferia e apagava só o que achou</span>');
  if (mode === "move" && stillFallback.length && uploaded.length) {
    const note = searchRan
      ? "Original(is) não achado(s) no disco (nome ou conteúdo não batem) — ficaram onde estão."
      : "Sem busca no disco nem pasta concedida, o navegador só deixa copiar — " +
        stillFallback.length + " original(is) ficaram onde estão.";
    conLine('<span class="dim">' + esc(note) + "</span>");
    toast(summary + " — " + note, 5500);
    // pastas concedidas cobrem o que a busca não alcança (fora de HOME, busca desligada);
    // não empilha sobre o diálogo de duplicatas — o dono já está respondendo uma pergunta
    if (!dupeGroups.length) inboxOriginDialog(stillFallback);
  } else if (dupeGroups.length) {
    toast(summary + " — originais duplicados: escolha quais apagar", 4500);
  } else {
    toast(summary, 3800);
  }
  if (dupeGroups.length) inboxDupesDialog(dupeGroups);
  if (uploaded.length) {
    try {
      const d = await api("/api/data");
      if (window.BRAIN && window.BRAIN.refresh) window.BRAIN.refresh(d.model);
    } catch (e) { /* views regeneram no próximo brain render */ }
  }
}

function inboxOriginDialog(pending){
  // Gestão das pastas concedidas (complemento da busca da ponte: cobre pastas fora de HOME
  // ou instâncias com a busca desligada). Abre sozinho 1× por sessão quando um Mover
  // virou cópia SEM busca no disco; cancelar o seletor do sistema libera a pergunta de novo.
  if (document.getElementById("inbox-origin-dlg")) return;
  try { if (sessionStorage.getItem("inboxOriginAsked")) return; } catch (e) {}
  try { sessionStorage.setItem("inboxOriginAsked", "1"); } catch (e) {}
  const supported = typeof window.showDirectoryPicker === "function";
  const ov = document.createElement("div");
  ov.className = "pal-back open";
  ov.id = "inbox-origin-dlg";
  const originsHTML = () => (inboxOrigins || []).map((o, i) =>
    '<p class="note-s"><b>' + esc(o.name) + '</b> <button class="btn tiny" data-inbox-origin-del="' + i + '">remover</button></p>'
  ).join("");
  const render = () => {
    ov.innerHTML = '<div class="palette"><div class="pin"><b>Pastas concedidas</b><span class="hint">Esc fecha</span></div>' +
      '<div class="pal-scroll">' +
      '<p class="note-s">A ponte já <b>procura o original no disco</b> e apaga após a cópia (conteúdo idêntico, byte a byte; duplicata, ela pergunta). Conceder pastas aqui é para o resto: arquivos <b>fora da sua pasta pessoal</b> ou instâncias com a busca desligada — aí o Mover apaga direto na pasta concedida, conferindo nome+tamanho+horário.</p>' +
      (originsHTML() || '<p class="note-s dim">nenhuma pasta concedida</p>') +
      (supported ? "" : '<p class="note-s"><b>Este navegador não suporta conceder pastas</b> (File System Access) — a busca no disco segue cobrindo sua pasta pessoal.</p>') +
      '</div><div class="pal-foot">' +
      (supported ? '<button class="btn" data-inbox-origin-pick>+ Adicionar pasta</button>' : "") +
      '<button class="btn ghost" data-inbox-origin-close>Pronto</button></div></div>';
    ov.querySelectorAll("[data-inbox-origin-del]").forEach(b => b.addEventListener("click", async () => {
      const idx = +b.dataset.inboxOriginDel;
      const list = (inboxOrigins || []).slice();
      list.splice(idx, 1);
      await inboxOriginsSave(list);
      render();
    }));
    const pick = ov.querySelector("[data-inbox-origin-pick]");
    if (pick) pick.addEventListener("click", async () => {
      let dir = null;
      try {
        dir = await window.showDirectoryPicker({mode: "readwrite", id: "brain-inbox-origin"});
      } catch (err) { return; }                     // cancelou o seletor: segue no diálogo
      const list = (inboxOrigins || []).filter(o => o.name !== dir.name);
      list.push({handle: dir, name: dir.name});
      await inboxOriginsSave(list);
      render();
      if (pending && pending.length) {              // tenta mover na hora o que caiu
        conOpen();
        for (const it of pending) {
          const from = await inboxOriginRemove([dir], it.relPath, it.file);
          conLine(from
            ? '<span class="ok">✓ original removido: ' + esc(it.file.name) + " (" + esc(from) + ")</span>"
            : '<span class="late">✗ ' + esc(it.file.name) + " não achado em " + esc(dir.name) + "</span>");
        }
      }
    });
    ov.querySelector("[data-inbox-origin-close]").addEventListener("click", close);
  };
  const close = () => { ov.remove(); document.removeEventListener("keydown", onKey, true); };
  const onKey = ev => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  ov.addEventListener("click", e => { if (e.target === ov) close(); });
  document.body.appendChild(ov);
  render();
}

function fmtSize(n){
  if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " KB";
  return n + " B";
}
function inboxDupesDialog(groups){
  // A busca da ponte achou o MESMO arquivo em mais de um lugar: nada foi apagado —
  // o dono escolhe (checkboxes) quais cópias sumem. A ponte revalida byte a byte na hora.
  if (document.getElementById("inbox-dupes-dlg")) return;
  const ov = document.createElement("div");
  ov.className = "pal-back open";
  ov.id = "inbox-dupes-dlg";
  const body = groups.map((g, gi) =>
    '<h3 style="margin:12px 0 4px">' + esc(g.file.name) + '</h3>' +
    g.candidates.map((c, ci) =>
      '<label class="duprow"><input type="checkbox" checked data-dup="' + gi + ":" + ci + '">' +
      '<span class="duppath">' + esc(c.path) + "</span>" +
      '<span class="dupmeta">' + esc(new Date(c.mtime * 1000).toLocaleString("pt-BR")) + " · " + fmtSize(c.size) + "</span></label>"
    ).join("")
  ).join("");
  ov.innerHTML = '<div class="palette"><div class="pin"><b>Achei cópias idênticas</b><span class="hint">Esc fecha</span></div>' +
    '<div class="pal-scroll"><p class="note-s">O arquivo já está na inbox. Essas cópias no disco são idênticas byte a byte — marque as que devem sumir (a ponte confere de novo antes de apagar).</p>' +
    body + "</div>" +
    '<div class="pal-foot"><button class="btn" data-dupes-apply disabled>Apagar selecionado(s)</button>' +
    '<button class="btn ghost" data-dupes-close>Manter todas</button></div></div>';
  document.body.appendChild(ov);
  const apply = ov.querySelector("[data-dupes-apply]");
  const close = () => { ov.remove(); document.removeEventListener("keydown", onKey, true); };
  const onKey = ev => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  const recount = () => {
    const n = ov.querySelectorAll("input[data-dup]:checked").length;
    apply.disabled = !n;
    apply.textContent = "Apagar " + n + " selecionado(s)";
  };
  ov.querySelectorAll("input[data-dup]").forEach(cb => cb.addEventListener("change", recount));
  recount();
  ov.addEventListener("click", e => {
    if (e.target === ov || e.target.closest("[data-dupes-close]")) close();
  });
  apply.addEventListener("click", async () => {
    apply.disabled = true;
    const picked = {};
    ov.querySelectorAll("input[data-dup]:checked").forEach(cb => {
      const [gi, ci] = cb.dataset.dup.split(":").map(Number);
      (picked[gi] = picked[gi] || []).push(groups[gi].candidates[ci].path);
    });
    conOpen();
    let removedN = 0;
    for (const gi of Object.keys(picked)) {
      const g = groups[+gi];
      let r, j = null;
      try {
        r = await fetch("/api/inbox/remove", {method: "POST", headers: {"X-Brain-Token": TOK || "", "Content-Type": "application/json"},
          body: JSON.stringify({inbox_name: g.inboxName, paths: picked[gi]})});
        if (r.status === 401) {
          handle401();
          conLine('<span class="late">✗ sessão expirada — reabra via ./brain render --open</span>');
          close();
          return;
        }
        try { j = await r.json(); } catch (e) {}
      } catch (err) { conLine('<span class="late">✗ ' + esc(g.file.name) + ": ponte fora do ar</span>"); continue; }
      if (r.ok && j && j.ok) {
        (j.removed || []).forEach(p => { removedN++; conLine('<span class="ok">✓ apagado: ' + esc(p) + "</span>"); });
        (j.refused || []).forEach(x => conLine('<span class="late">✗ ' + esc(x.path) + ": " + esc(x.reason) + "</span>"));
      } else {
        conLine('<span class="late">✗ ' + esc(g.file.name) + ": " + esc((j && j.error) || ("erro " + r.status)) + "</span>");
      }
    }
    toast(removedN ? removedN + " original(is) apagado(s) do disco" : "nada apagado — cópias mantidas", 4200);
    close();
  });
}

document.addEventListener("dragenter", e => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  inboxDragDepth++;
  const ov = ensureInboxDropOverlay();
  ov.hidden = false;
  if (LIVE) paintInboxDropZone(inboxDropModeAt(e, ov));
  else if (inboxDragDepth === 1) toast(INBOX_OFFLINE_MSG, 4500);
});
document.addEventListener("dragover", e => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  const ov = ensureInboxDropOverlay();
  if (e.dataTransfer) e.dataTransfer.dropEffect = (LIVE && inboxDropModeAt(e, ov) === "move") ? "move" : "copy";
  ov.hidden = false;
  if (LIVE) paintInboxDropZone(inboxDropModeAt(e, ov));
});
document.addEventListener("dragleave", e => {
  if (!isFileDrag(e)) return;
  inboxDragDepth = Math.max(0, inboxDragDepth - 1);
  if (inboxDragDepth === 0) hideInboxDropOverlay();
});
document.addEventListener("drop", e => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  const ov = ensureInboxDropOverlay();
  const mode = LIVE ? inboxDropModeAt(e, ov) : "copy";
  hideInboxDropOverlay();
  if (!LIVE) {
    toast(INBOX_OFFLINE_MSG, 5000);
    return;
  }
  const dt = e.dataTransfer;
  const entries = [], fallbackFiles = [], rejected = [];
  if (dt && dt.items && dt.items.length) {
    for (const item of Array.from(dt.items)) {
      if (item.kind !== "file") continue;
      if (typeof item.webkitGetAsEntry === "function") {
        const entry = item.webkitGetAsEntry();
        if (entry) entries.push(entry);
        else {
          // webkitGetAsEntry existe mas devolve null (DataTransfer sintético, ou navegador
          // sem entries): cai no arquivo plano — perder o item aqui seria drop silencioso
          const f = typeof item.getAsFile === "function" ? item.getAsFile() : null;
          if (f) fallbackFiles.push(f);
        }
      } else if (typeof item.getAsFile === "function") {
        const f = item.getAsFile();
        if (f) fallbackFiles.push(f);
      }
    }
  } else if (dt && dt.files) {
    fallbackFiles.push(...Array.from(dt.files));
  }
  handleInboxDrop(mode, entries, fallbackFiles, rejected);
});
window.addEventListener("blur", hideInboxDropOverlay);

// ── wizard de configuração — modo primeira vez do painel (F8) ──────────────
// Portado do onboarding.html (que segue no repo como rollback da rota /onboarding).
// Fala com os MESMOS /api/onboard/* do hub "Seu Brain" (uma regra, duas portas),
// renderiza na shell do painel — marca, tema e barra lateral; sem faces/⌘K —
// e "Abrir meu Brain" volta às faces SEM recarregar a página.
const OB_STEPS = [["inicio","Boas-vindas"],["voce","Você e sua rotina"],["sobre","Sobre você"],["agente","Seu agente"],["conectores","Conectores e fontes"],["memoria","Memória"],["chaves","Chaves e portas"],["maquina","A máquina"],["planejamento","Goals e projetos"],["conversa","A conversa"],["pronto","Pronto"]];
const OB_STEP_GROUPS = {
  inicio: "Você", voce: "Você", sobre: "Você",
  agente: "Conexões", conectores: "Conexões", memoria: "Conexões", chaves: "Conexões",
  maquina: "O cérebro",
  planejamento: "Começando", conversa: "Começando", pronto: "Começando",
};
let OBS = null, obCur = "inicio", obStepGen = 0;   // geração de navegação — quem capturou e viu mudar, o passo já não é o seu
let obPickedAgent = null;    // destaque (sugestão de detecção conta)
let obAgentChosen = false;   // mas só o clique do dono é escolha — é o que nomeia a TASK do "Fazer depois"
let obAgentHint = null;      // receita manual quando wire_mcp devolve mcp=false + hint
let obProfileDraft = null, obPlan = {goals: []}, obPlanTab = "escrever", obUploads = [];
let OB_ACTIVE = false;
try { obCur = localStorage.getItem("brain-onboarding-step") || "inicio"; } catch (e) {}
if (!OB_STEPS.some(s => s[0] === obCur)) obCur = "inicio";

const obAll = (s, r) => Array.from((r || document).querySelectorAll(s));
async function obRefresh() { OBS = (await obApi("/api/onboard/state")).state; }
function obDoneSet() { return new Set((OBS && OBS.progress && OBS.progress.done) || []); }
function obSet(html) { $("#view").innerHTML = '<div class="obw"><div class="bar"><i id="ob-bar"></i></div><div class="obcontent">' + html + "</div></div>"; }
function obGo(step) {
  obCur = step;
  obStepGen++;            // invalida as continuações async do passo anterior (scan, jobs): nada de pintar nem navegar por ele
  try { localStorage.setItem("brain-onboarding-step", step); } catch (e) {}
  obRender();
  window.scrollTo({top: 0, behavior: "smooth"});
}
function obNext() { const i = OB_STEPS.findIndex(s => s[0] === obCur); obGo(OB_STEPS[Math.min(i + 1, OB_STEPS.length - 1)][0]); }
function obBack() { const i = OB_STEPS.findIndex(s => s[0] === obCur); obGo(OB_STEPS[Math.max(i - 1, 0)][0]); }
async function obSkip(step) { try { await obAct("skip", {step}); await obRefresh(); } catch (e) {} obNext(); }
function obMsg(el, kind, text) { if (el) { el.className = "msg show " + kind; el.textContent = text; } }
function obBusy(btn, on, label) {
  if (!btn) return;
  if (on) { btn.dataset.obl = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<i class="spin"></i> ' + esc(label || "Salvando…"); }
  else { btn.disabled = false; if (btn.dataset.obl) btn.innerHTML = btn.dataset.obl; }
}
function obTickLog(logEl, j) {
  if (!logEl) return;
  logEl.classList.add("show");
  logEl.textContent = (j && j.log && j.log.length) ? j.log.join("\n") : "executando…";
  logEl.scrollTop = logEl.scrollHeight;
}
function obStillOn(gen) { return gen === obStepGen; }   // false = o dono trocou de passo; a continuação async não pinta nem navega
function obRenderSteps() {
  const list = $("#ob-steps"); if (!list) return;
  const done = obDoneSet();
  let lastGrp = "", html = "";
  OB_STEPS.forEach(([k, t], i) => {
    const grp = OB_STEP_GROUPS[k] || "";
    if (grp !== lastGrp) { html += '<div class="grp">' + esc(grp) + "</div>"; lastGrp = grp; }
    html += '<li data-k="' + k + '" class="' + (k === obCur ? "cur" : "") + " " + (done.has(k) ? "done" : "") + '"><span class="dot">' + (done.has(k) ? "✓" : i) + '</span><span class="t">' + esc(t) + "</span></li>";
  });
  list.innerHTML = html;
  obAll("#ob-steps li").forEach(li => li.onclick = () => obGo(li.dataset.k));
  const i = OB_STEPS.findIndex(s => s[0] === obCur);
  const bar = $("#ob-bar");
  if (bar) bar.style.width = Math.round(i / (OB_STEPS.length - 1) * 100) + "%";
}
function obNav(opts) {
  opts = opts || {};
  return '<div class="actions" id="nav">' +
    (obCur !== "inicio" ? '<button class="btn ghost" type="button" data-a="back">← Voltar</button>' : "") +
    '<span class="spacer"></span>' +
    (opts.skip ? '<button class="btn ghost" type="button" data-a="skip">' + esc(opts.skip) + "</button>" : "") +
    (opts.hideMain ? "" : '<button class="btn pri" type="button" data-a="main">' + esc(opts.main || "Continuar") + " →</button>") +
    "</div>";
}
function obBindNav(main, onSkip) {
  const b = $('[data-a="back"]'); if (b) b.onclick = obBack;
  const k = $('[data-a="skip"]'); if (k) k.onclick = () => (onSkip ? onSkip(k) : obSkip(obCur));
  const m = $('[data-a="main"]'); if (m && main) m.onclick = () => main(m);
}
function obHead(kicker, title, lead) {
  return '<div class="kicker">' + esc(kicker) + "</div><h1>" + esc(title) + "</h1>" + (lead ? '<p class="lead">' + lead + "</p>" : "");
}
function obMd(text) {
  return text.split("\n").filter(l => l !== "# PROFILE" && !/^_.*|.*_$/.test(l)).map(l => {
    if (l.startsWith("# ")) return "<h1>" + esc(l.slice(2)) + "</h1>";
    if (l.startsWith("## ")) return "<h2>" + esc(l.slice(3)) + "</h2>";
    if (!l.trim()) return "";
    const t = esc(l), it = /^_/.test(l) || /_$/.test(l);
    return it ? "<p><em>" + t.replace(/^_|_$/g, "") + "</em></p>" : "<p>" + t + "</p>";
  }).join("");
}
function obCopyText(text, btn) {
  const done = () => {
    if (!btn) return;
    const old = btn.textContent;
    btn.textContent = "✓ Copiado";
    setTimeout(() => { if (btn.isConnected) btn.textContent = old; }, 1400);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => {});
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) {}
  ta.remove();
}
function obExtractCmd(hint) {
  const m = String(hint || "").match(/`([^`]+)`/);
  return m ? m[1] : String(hint || "");
}

const OBV = {};

// 1. Boas-vindas
OBV.inicio = () => {
  obSet('<div class="welcome"><div>' +
    obHead("Segundo Cérebro · local e só seu", "Vamos montar o seu Brain", "O Brain organiza sua vida profissional: reuniões, decisões, tarefas, objetivos e as pessoas com quem você trabalha — num lugar só, no seu computador.") +
    '<div class="feat">' +
      "<div><b>Leva uns 10 minutos</b>Você pode pular qualquer passo e voltar depois.</div>" +
      "<div><b>Seus dados são seus</b>Tudo fica nesta máquina. Nada é enviado sem você aprovar.</div>" +
      '<div><b>Ele observa, você decide</b>O Brain sugere; enviar, publicar e mudar objetivos é sempre com o seu "ok".</div>' +
    "</div></div>" + markTag() + "</div>" + obNav({main: "Começar"}));
  obBindNav(() => obNext());
};
function markTag() {
  const src = (document.querySelector(".brand .mark") || {}).src || "/brain.svg";
  return '<div class="app-tile"><img src="' + src + '" alt="Ícone do app Brain"><small>o app que acaba de entrar nos seus Aplicativos</small></div>';
}

// 2. Você e sua rotina
OBV.voce = () => {
  const o = OBS.owner || {}, r = OBS.routine || {};
  const guess = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const curTz = r.timezone || guess;
  const zones = Array.from(new Set([r.timezone, guess, "America/Sao_Paulo", "America/Argentina/Buenos_Aires",
    "America/Mexico_City", "America/Bogota", "America/Santiago", "America/Lima", "America/New_York",
    "Europe/Lisbon", "Europe/Madrid", "UTC"].filter(Boolean)));
  obSet(obHead("Você", "Você e sua rotina", "Assim o Brain reconhece você nas reuniões, nos e-mails e no Slack, e usa seus horários para calcular prazos e sugerir blocos de foco.") +
    '<div class="card">' +
      "<h2>Identidade</h2>" +
      '<label class="f"><span>Nome completo <span class="req">*</span></span><input type="text" id="name" value="' + esc(o.name || o.suggested_name) + '" autocomplete="name"></label>' +
      '<div class="grid2">' +
        '<label class="f"><span>Apelido</span><input type="text" id="nick" value="' + esc(o.nickname) + '" placeholder="como as pessoas te chamam"><small>O nome curto que aparece nas reuniões e no Slack. Ajuda a te achar nas transcrições.</small></label>' +
        '<label class="f"><span>Cargo</span><input type="text" id="role" value="' + esc(o.role) + '" placeholder="ex.: Gerente de Produto"></label>' +
      "</div>" +
      '<label class="f" style="margin-bottom:0"><span>E-mail de trabalho</span><input type="email" id="email" value="' + esc(o.email) + '" placeholder="voce@empresa.com" autocomplete="email"><small>Opcional. Usado para reconhecer convites e e-mails seus.</small></label>' +
    "</div>" +
    '<div class="card">' +
      "<h2>Sua rotina</h2>" +
      '<label class="f"><span>Fuso horário</span><select id="tz">' + zones.map(z => '<option ' + (z === curTz ? "selected" : "") + ">" + esc(z) + "</option>").join("") + "</select></label>" +
      '<div class="grid2">' +
        '<label class="f"><span>Começo do expediente</span><input type="time" id="st" value="' + esc(r.start || "09:00") + '"></label>' +
        '<label class="f" style="margin-bottom:0"><span>Fim do expediente</span><input type="time" id="en" value="' + esc(r.end || "18:00") + '"></label>' +
      "</div>" +
      '<small>O planejador de foco desvia do almoço (12:00–13:00 por padrão). Detalhes finos ficam em <span class="kbd">config/brain.toml</span> seção <span class="kbd">[work]</span>.</small>' +
    "</div>" +
    '<div class="msg" id="m"></div>' + obNav());
  $("#name").focus();
  obBindNav(async btn => {
    const aboutBody = {name: $("#name").value, nickname: $("#nick").value, role: $("#role").value, email: $("#email").value};
    if (!aboutBody.name.trim()) return obMsg($("#m"), "err", "Preencha o seu nome completo.");
    const routineBody = {
      timezone: $("#tz").value,
      start: $("#st").value,
      end: $("#en").value,
      lunch: r.lunch || "",      // não se pergunta (ruling do dono): o que já está gravado atravessa
    };
    obBusy(btn, true);
    try {
      await obAct("about", aboutBody);
      await obAct("routine", routineBody);
      await obRefresh();
      obNext();
    } catch (e) { obMsg($("#m"), "err", e.message); } finally { obBusy(btn, false); }
  });
};

// 3. Sobre você
OBV.sobre = () => {
  const tpl = OBS.profile.template;
  obSet(obHead("Você", "Conte um pouco sobre você", "Isto vira o seu perfil — o contexto que o Brain usa para entender o que é importante para você. Escreva como se estivesse explicando para um colega novo.") +
    (!tpl ? '<div class="msg info show" style="margin:0 0 14px">Você já tem um perfil salvo. Se escrever aqui, o novo texto substitui o atual (você vê a prévia antes).</div>' : "") +
    '<div class="card" id="form">' +
      '<label class="f"><span>Sobre você</span><textarea id="about" placeholder="Seu papel, seu time, pelo que você responde, há quanto tempo está na empresa…"></textarea></label>' +
      '<label class="f"><span>Como você trabalha</span><textarea id="how" placeholder="Rituais da semana, reuniões fixas, como prefere receber informação, horários de foco…"></textarea></label>' +
      '<label class="f" style="margin-bottom:0"><span>O que importa agora</span><textarea id="focus" placeholder="As 2–3 coisas que mais pesam neste trimestre."></textarea></label>' +
      '<div class="msg" id="m"></div>' +
    "</div>" +
    '<div class="card hidden" id="prev"><h2>Prévia do seu perfil</h2><p class="sub">É isto que será salvo. Confira e confirme.</p><div class="preview" id="pv"></div>' +
      '<div class="actions" style="margin-top:16px"><button class="btn" type="button" id="edit">Editar texto</button><span class="spacer"></span><button class="btn pri" type="button" id="save">Salvar perfil →</button></div><div class="msg" id="m2"></div></div>' +
    obNav({main: "Ver prévia", skip: "Pular por agora"}));
  if (obProfileDraft) { $("#about").value = obProfileDraft.about; $("#how").value = obProfileDraft.how; $("#focus").value = obProfileDraft.focus; }
  obBindNav(async btn => {
    obProfileDraft = {about: $("#about").value, how: $("#how").value, focus: $("#focus").value};
    if (!(obProfileDraft.about + obProfileDraft.how + obProfileDraft.focus).trim()) return obMsg($("#m"), "err", "Escreva pelo menos um dos campos — ou pule este passo.");
    const gen = obStepGen;
    obBusy(btn, true, "Montando…");
    try {
      const r = await obAct("profile_preview", obProfileDraft);
      if (!obStillOn(gen)) return;
      $("#pv").innerHTML = obMd(r.markdown); $("#pv").dataset.md = r.markdown;
      $("#form").classList.add("hidden"); $("#prev").classList.remove("hidden"); $("#nav").classList.add("hidden");
    } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { obBusy(btn, false); }
  });
  $("#edit").onclick = () => { $("#prev").classList.add("hidden"); $("#form").classList.remove("hidden"); $("#nav").classList.remove("hidden"); };
  $("#save").onclick = async () => {
    const b = $("#save"), gen = obStepGen; obBusy(b, true);
    try { await obAct("profile_save", {markdown: $("#pv").dataset.md, overwrite: !tpl}); await obRefresh(); if (obStillOn(gen)) obNext(); }
    catch (e) { if (obStillOn(gen)) obMsg($("#m2"), "err", e.message); } finally { obBusy(b, false); }
  };
};

// 4. Seu agente
const OB_AGENT_URLS = {
  "claude-code": "https://claude.ai/claude-code",
  "hermes": "https://hermes.nousresearch.com",
  "cursor-cli": "https://cursor.com",
  "codex": "https://openai.com/codex",
};
const OB_AGENT_ICONS = {"claude-code": "⌘", "hermes": "✳", "cursor-cli": "▷", "codex": "◇"};
OBV.agente = () => {
  const agents = OBS.agents || [];
  const sn = OBS.mcp_snippets || {};
  if (!obPickedAgent || (obPickedAgent !== "other" && !agents.some(a => a.key === obPickedAgent))) {
    const pre = agents.find(a => a.selected) || agents.find(a => a.mcp)
      || (OBS.agent_mode === "manual" ? {key: "other"} : null)
      || agents.find(a => a.detected) || agents[0];
    obPickedAgent = pre ? pre.key : "other";
    obAgentChosen = false;               // destaque é sugestão; escolha é clique (ruling)
  }
  const isOther = obPickedAgent === "other";
  const currentObj = () => agents.find(a => a.key === obPickedAgent) || null;
  const anyConnected = agents.some(a => a.mcp || a.selected) || OBS.agent_mode === "manual" || Boolean(obAgentHint);
  const preStyle = "margin:0;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;word-break:break-all;overflow-x:auto";
  obSet(obHead("Conexões · primeiro o agente", "Seu agente", "O cérebro funciona com um agente de IA para ler suas fontes e ajudar nas rotinas. Escolha o seu agente principal ou configure outro cliente MCP manualmente.") +
    '<div class="card">' +
      '<div id="ag-list">' + agents.map(a => {
        const url = OB_AGENT_URLS[a.key] || "#";
        const ic = OB_AGENT_ICONS[a.key] || "✦";
        const badges = [
          a.detected ? '<span class="pill ok">detectado</span>' : '<span class="pill muted">não detectado</span>',
          a.mcp ? '<span class="pill ok">MCP conectado</span>' : "",
          a.selected ? '<span class="pill info">ativo</span>' : "",
        ].filter(Boolean).join(" ");
        const desc = a.detected
          ? esc(a.runner ? "instalado · runner: " + a.runner : "instalado · chat e canais")
          : 'não encontrado no PATH — <a href="' + esc(url) + '" target="_blank" rel="noopener">como instalar</a>';
        return '<div class="agentcard ' + (a.key === obPickedAgent ? "sel" : "") + '" data-ag="' + esc(a.key) + '">' +
          '<div class="ai-ic">' + ic + "</div>" +
          '<div class="meta"><b>' + esc(a.label) + "</b> " + badges + '<div class="d">' + desc + "</div></div>" +
          '<span class="radio"></span>' +
          "</div>";
      }).join("") +
      '<div class="agentcard ' + (isOther ? "sel" : "") + '" data-ag="other">' +
        '<div class="ai-ic">✦</div>' +
        '<div class="meta"><b>Outros harnesses</b> ' + (OBS.agent_mode === "manual" ? '<span class="pill info">manual</span>' : "") + '<div class="d">Qualquer cliente MCP (stdio) — copie os snippets JSON, TOML ou CLI</div></div>' +
        '<span class="radio"></span>' +
      "</div></div>" +
      (isOther ? '<div id="ag-other" style="margin-top:12px">' +
        '<p class="sub" style="margin-bottom:8px">Cole um dos blocos abaixo na configuração MCP do seu agente e marque como configurado manualmente.</p>' +
        '<div class="slot"><div class="sh"><span>JSON (mcpServers)</span><span class="spacer"></span><button class="btn sm" type="button" data-copy="json">Copiar</button></div><pre style="' + preStyle + '">' + esc(sn.json || "") + "</pre></div>" +
        '<div class="slot"><div class="sh"><span>TOML ([mcp_servers.brain])</span><span class="spacer"></span><button class="btn sm" type="button" data-copy="toml">Copiar</button></div><pre style="' + preStyle + '">' + esc(sn.toml || "") + "</pre></div>" +
        '<div class="slot"><div class="sh"><span>Linha de comando (stdio)</span><span class="spacer"></span><button class="btn sm" type="button" data-copy="cli">Copiar</button></div><pre style="' + preStyle + '">' + esc(sn.cli || "") + "</pre></div>" +
      "</div>" : "") +
      '<div class="slot ' + (obAgentHint ? "" : "hidden") + '" id="ag-hint">' +
        '<div class="sh"><span>Receita manual para concluir</span><span class="spacer"></span><button class="btn sm" type="button" id="ag-copy-hint">Copiar comando</button></div>' +
        '<pre id="ag-hint-txt" style="' + preStyle + '">' + esc(obAgentHint || "") + "</pre>" +
      "</div>" +
      '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:12px">' +
        (isOther
          ? '<button class="btn pri" type="button" id="ag-manual">Marcar como configurado manualmente</button>'
          : '<button class="btn pri" type="button" id="ag-connect">Conectar o Brain ao ' + esc((currentObj() || {}).label || "agente") + "</button>") +
        '<button class="btn" type="button" id="ag-later">Fazer depois</button>' +
      "</div>" +
      '<div class="log" id="ag-log"></div>' +
      '<div class="msg" id="m"></div>' +
    "</div>" +
    obNav({main: anyConnected ? "Continuar" : "Seguir sem conectar", hideMain: !anyConnected}));

  obAll("#ag-list .agentcard[data-ag]").forEach(card => {
    card.onclick = e => {
      if (e.target && e.target.closest && e.target.closest("a")) return;
      obPickedAgent = card.dataset.ag;
      obAgentChosen = true;
      obAgentHint = null;
      OBV.agente();
    };
  });

  obAll("#ag-other [data-copy]").forEach(b => {
    b.onclick = () => obCopyText(sn[b.dataset.copy] || "", b);
  });

  if ($("#ag-copy-hint")) {
    $("#ag-copy-hint").onclick = () => obCopyText(obExtractCmd(obAgentHint), $("#ag-copy-hint"));
  }

  const doLater = async btn => {
    const gen = obStepGen;
    obBusy(btn, true, "Criando tarefa…");
    try {
      const r = await obAct("agent_later", obAgentChosen && obPickedAgent !== "other" ? {agent: obPickedAgent} : {});
      await obRefresh();
      if (!obStillOn(gen)) return;
      obMsg($("#m"), "ok", "✓ Tarefa " + r.id + " criada — ficou no seu TODO.");
      setTimeout(() => { if (obStillOn(gen)) obNext(); }, 1100);
    } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { if (btn.isConnected) obBusy(btn, false); }
  };
  $("#ag-later").onclick = () => doLater($("#ag-later"));

  if ($("#ag-manual")) {
    $("#ag-manual").onclick = async () => {
      const btn = $("#ag-manual"), gen = obStepGen;
      obBusy(btn, true, "Salvando…");
      try {
        await obAct("agent_connect", {agent: "other"});
        await obRefresh();
        obRenderSteps();
        if (!obStillOn(gen)) return;
        OBV.agente();
        obMsg($("#m"), "ok", "✓ Marcado como configurado manualmente.");
      } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { if (btn.isConnected) obBusy(btn, false); }
    };
  }

  if ($("#ag-connect")) {
    $("#ag-connect").onclick = async () => {
      const obj = currentObj();
      if (!obj) return;
      obAgentChosen = true;               // o botão nomeia o agente: conectar é escolher
      obAgentHint = null;
      const btn = $("#ag-connect"), log = $("#ag-log"), gen = obStepGen;
      obBusy(btn, true, "Conectando…");
      try {
        const r = await obAct("agent_connect", {agent: obj.key});
        let res = r;
        if (r.job) {
          const j = await obJob(r.job, jj => { if (obStillOn(gen)) obTickLog(log, jj); });
          if (j.status === "error") {
            if (obStillOn(gen)) obMsg($("#m"), "err", (j.result && j.result.error) || "não consegui conectar o agente");
            return;
          }
          res = j.result || {};
        }
        await obRefresh();
        obRenderSteps();
        if (!obStillOn(gen)) return;
        if (!res.mcp && res.hint) {
          obAgentHint = res.hint;
          OBV.agente();
          obMsg($("#m"), "warn", "Configuração automática indisponível — copie a receita acima para concluir no terminal.");
          return;
        }
        btn.textContent = "✓ " + obj.label + " conectado";
        obMsg($("#m"), "ok", "✓ " + obj.label + " conectado.");
        setTimeout(() => { if (obStillOn(gen)) obNext(); }, 700);
      } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { if (btn.isConnected) obBusy(btn, false); }
    };
  }
  obBindNav(() => obNext());
};

// 5. Conectores e fontes
const OB_ST_LABEL = {connected: ["ok", "Conectado"], auth: ["warn", "Precisa autorizar"], missing: ["muted", "Não adicionado"], error: ["bad", "Com erro"], unknown: ["muted", "Verificando…"]};
OBV.conectores = () => {
  const noClaude = !OBS.claude_installed;
  let scanRes = null;
  obSet(obHead("Conexões", "Conectores e fontes", "Conector é o aplicativo (Slack, Gmail…). Fonte é o recorte que o Brain observa no <span class=\"kbd\">watch.toml</span> — só para <b>leitura</b>.") +
    (noClaude ? "" : '<div class="card soft"><h2>Como conectar (uma vez só)</h2>' +
      '<ol class="howto">' +
        '<li>Abra <a href="https://claude.ai/settings/connectors" target="_blank" rel="noopener">claude.ai → Configurações → Conectores</a>.</li>' +
        "<li>Adicione os que você usa: <b>Slack</b>, <b>Gmail</b>, <b>Google Calendar</b>, <b>Google Drive</b>, <b>Granola</b>, <b>Atlassian</b>.</li>" +
        "<li>Clique em <b>Conectar</b> em cada um e autorize com a sua conta de trabalho.</li>" +
        "<li>Volte aqui e clique em <b>Verificar de novo</b>.</li>" +
      "</ol></div>") +
    '<div class="card">' +
      '<div style="display:flex;align-items:center;gap:12px;margin-bottom:4px"><h2 style="margin:0">Aplicativos</h2><span class="spacer"></span><button class="btn sm" type="button" id="scan">↻ Verificar de novo</button></div>' +
      '<div id="conns"></div>' +
      '<div class="log" id="scanlog"></div>' +
      '<div id="extra" class="hidden" style="margin-top:14px">' +
        '<div class="grid2">' +
          '<label class="f" id="fslack" style="margin-bottom:0"><span>Canais do Slack para acompanhar</span><input type="text" id="slack" placeholder="#meu-time, #projeto-x"><small>Separados por vírgula. Dá para mudar depois.</small></label>' +
          '<label class="f" id="fdrive" style="margin-bottom:0"><span>Pasta do Drive (link)</span><input type="text" id="drive" placeholder="https://drive.google.com/drive/folders/…"><small>Opcional: o Brain acompanha os documentos dela.</small></label>' +
        "</div>" +
      "</div>" +
      '<div class="msg" id="m"></div>' +
    "</div>" +
    '<div class="card">' +
      '<div style="display:flex;align-items:center;gap:12px;margin-bottom:4px">' +
        '<div><h2 style="margin:0">Fontes observadas</h2><p class="sub" style="margin:2px 0 0">Fonte fora desta lista não é puxada — regra do <span class="kbd">watch.toml</span>.</p></div>' +
        '<span class="spacer"></span>' +
        '<button class="btn sm" type="button" id="show-add">+ Adicionar fonte</button>' +
      "</div>" +
      '<div class="twrap"><table class="src" id="srctable"></table></div>' +
      '<div class="addform hidden" id="addform">' +
        '<div class="grid3">' +
          '<label class="f"><span>Tipo</span><select id="src-kind"></select></label>' +
          '<label class="f"><span>Key (nome único)</span><input type="text" id="src-key" placeholder="ex.: slack-time"></label>' +
          '<label class="f"><span>Janela</span><select id="src-win"><option value="1d">1d</option><option value="7d">7d</option><option value="14d" selected>14d</option><option value="auto">auto</option></select></label>' +
        "</div>" +
        '<label class="f" id="src-param-f"><span id="src-param-l">Parâmetro</span><input type="text" id="src-param" placeholder=""></label>' +
        '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">' +
          '<button class="btn pri sm" type="button" id="src-add">Adicionar</button>' +
          '<button class="btn ghost sm" type="button" id="src-cancel">Fechar</button>' +
          '<span style="font-size:12px;color:var(--muted)">Valida o <span class="kbd">watch.toml</span> na hora.</span>' +
        "</div>" +
      "</div>" +
      '<div class="msg" id="srcmsg"></div>' +
    "</div>" +
    obNav({main: "Salvar e continuar", skip: "Fazer depois"}));

  const drawConns = () => {
    const box = $("#conns");
    if (!box) return;                 // o passo saiu de cena — nunca pintar em DOM de outro passo
    const src = (scanRes && scanRes.source) || OBS.connectors_source;
    const hint = (scanRes && scanRes.hint) || OBS.connectors_hint;
    if (src === "none") {
      box.innerHTML = '<p style="color:var(--muted);margin:10px 0 0">' + esc(hint) + "</p>";
      $("#extra").classList.add("hidden");
      return;
    }
    box.innerHTML = OBS.connectors.map(c => {
      const pair = OB_ST_LABEL[OBS.connectors_scanned ? c.status : "unknown"] || OB_ST_LABEL.unknown;
      const can = c.status === "connected" || c.enabled;
      return '<div class="conn"><div class="info"><b>' + esc(c.label) + "</b><p>" + esc(c.what) + '</p></div>' +
        '<div class="right"><span class="pill ' + pair[0] + '">' + pair[1] + "</span>" +
        '<label class="toggle" title="O Brain pode ler"><input type="checkbox" data-c="' + c.key + '" ' + (c.enabled || c.status === "connected" ? "checked" : "") + " " + (can ? "" : "disabled") + '><span></span></label></div></div>';
    }).join("");
    const sel = () => obAll("#conns input:checked").map(i => i.dataset.c);
    const ex = () => {
      const s = sel();
      $("#extra").classList.toggle("hidden", !s.includes("slack") && !s.includes("drive"));
      $("#fslack").classList.toggle("hidden", !s.includes("slack"));
      $("#fdrive").classList.toggle("hidden", !s.includes("drive"));
    };
    obAll("#conns input").forEach(i => i.onchange = ex); ex();
  };

  const drawSources = () => {
    const tbl = $("#srctable");
    if (!tbl) return;                 // idem: passo trocado, DOM morto
    const list = OBS.sources || [];
    if (!list.length) {
      tbl.innerHTML = '<tr><td colspan="5" style="color:var(--muted);padding:12px 4px">Nenhuma fonte cadastrada ainda.</td></tr>';
      return;
    }
    const detailOf = s => [
      s.channel,
      s.folder ? "pasta " + s.folder : "",
      s.doc ? "doc " + s.doc : "",
      s.jql,
      s.path,
      s.query,
      s.note,
    ].filter(Boolean).join(" · ") || "—";
    tbl.innerHTML = "<thead><tr><th>key</th><th>tipo</th><th>janela</th><th>detalhe</th><th></th></tr></thead><tbody>" +
      list.map(s => "<tr>" +
        '<td><span class="kbd">' + esc(s.key) + "</span></td>" +
        "<td>" + esc(s.kind) + "</td>" +
        "<td>" + esc(s.window || "auto") + "</td>" +
        '<td><span class="d">' + esc(detailOf(s)) + "</span></td>" +
        '<td style="text-align:right"><button class="x" type="button" data-rm-src="' + esc(s.key) + '" title="Remover fonte">×</button></td>' +
      "</tr>").join("") + "</tbody>";
    obAll("#srctable [data-rm-src]").forEach(btn => {
      btn.onclick = async () => {
        const key = btn.dataset.rmSrc;
        btn.disabled = true;
        try {
          await obAct("source_remove", {key});
          await obRefresh();
          drawSources();
          obMsg($("#srcmsg"), "ok", '✓ Fonte "' + key + '" removida.');
        } catch (e) { obMsg($("#srcmsg"), "err", e.message); btn.disabled = false; }
      };
    });
  };

  const kinds = OBS.watch_kinds || [];
  $("#src-kind").innerHTML = kinds.map(([k, l]) => '<option value="' + esc(k) + '">' + esc(l) + "</option>").join("");

  const SRC_META = {
    gmail:       {key: "gmail-hoje",      param: null},
    gcal:        {key: "gcal-agenda",     param: null},
    granola:     {key: "granola-reunioes", param: null},
    slack:       {key: "slack-time",      field: "channel", label: "Canal ou pessoa",  ph: "#meu-time — ou @pessoa para DM", req: true},
    drive:       {key: "drive-pasta",     field: "folder",  label: "Pasta do Drive",   ph: "cole a URL da pasta — o id é extraído na hora", req: true},
    "drive-doc": {key: "drive-okr",       field: "doc",     label: "Documento do Drive", ph: "cole a URL do doc, planilha ou slides", req: true, noWindow: true},
    jira:        {key: "jira-meus",       field: "jql",     label: "JQL",              ph: "assignee = currentUser() — os seus cards", req: true},
    github:      {key: "github-repo",     field: "path",    label: "Caminho do clone local", ph: "~/projetos/meu-repo", req: true, noWindow: true},
  };
  const syncSrcForm = () => {
    const m = SRC_META[$("#src-kind").value] || {};
    $("#src-key").placeholder = "ex.: " + (m.key || "minha-fonte");
    const f = $("#src-param-f");
    if (m.param === null) { f.classList.add("hidden"); $("#src-param").value = ""; }
    else {
      f.classList.remove("hidden");
      $("#src-param-l").textContent = m.label + (m.req ? " *" : "");
      $("#src-param").placeholder = m.ph || "";
    }
    $("#src-win").closest("label").classList.toggle("hidden", !!m.noWindow);
  };
  $("#src-kind").onchange = syncSrcForm; syncSrcForm();
  $("#show-add").onclick = () => $("#addform").classList.toggle("hidden");
  $("#src-cancel").onclick = () => $("#addform").classList.add("hidden");
  $("#src-add").onclick = async () => {
    const b = $("#src-add");
    const kind = $("#src-kind").value;
    const meta = SRC_META[kind] || {};
    const key = $("#src-key").value.trim();
    const win = $("#src-win").value;
    const param = $("#src-param").value.trim();
    if (meta.req && !param)
      return obMsg($("#srcmsg"), "err", 'Preencha o campo "' + meta.label + '" — ele diz ao Brain o que observar.');
    const payload = {key, kind};
    if (!meta.noWindow) payload.window = win;
    if (param && meta.field) payload[meta.field] = param;
    obBusy(b, true, "Adicionando…");
    try {
      await obAct("source_add", payload);
      $("#src-key").value = "";
      $("#src-param").value = "";
      await obRefresh();
      drawSources();
      obMsg($("#srcmsg"), "ok", '✓ Fonte "' + key + '" adicionada.');
    } catch (e) { obMsg($("#srcmsg"), "err", e.message); } finally { obBusy(b, false); }
  };

  drawConns();
  drawSources();

  const scan = async force => {
    const b = $("#scan"), log = $("#scanlog"), gen = obStepGen;
    const here = () => obStillOn(gen);   // o dono trocou de passo? a varredura segue no servidor; a tela, não
    obBusy(b, true, "Verificando…");
    try {
      const r = await obAct("connectors_scan", {force});
      if (r.job) {
        const j = await obJob(r.job, jj => { if (here()) obTickLog(log, jj); });
        if (j.status === "error") {
          if (here()) obMsg($("#m"), "err", (j.result && j.result.error) || "não consegui verificar");
          return;
        }
        scanRes = j.result || null;
      } else {
        scanRes = r;
      }
      await obRefresh();
      if (here()) drawConns();
    } catch (e) { if (here()) obMsg($("#m"), "err", e.message); } finally { obBusy(b, false); }
  };
  $("#scan").onclick = () => scan(true);
  if (!OBS.connectors_scanned) scan(false);
  obBindNav(async btn => {
    const keys = obAll("#conns input:checked").map(i => i.dataset.c);
    if (!keys.length) return obSkip(obCur);
    const gen = obStepGen;
    obBusy(btn, true);
    try {
      await obAct("connectors_enable", {
        connectors: keys,
        slack_channels: $("#slack") ? $("#slack").value : "",
        drive_folder: $("#drive") ? $("#drive").value : "",
      });
      await obRefresh(); if (obStillOn(gen)) obNext();
    } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { obBusy(btn, false); }
  });
};

// O que o LLM faz no modo full — nome e tooltip de cada operação. É a MESMA lista de providers.LLM_OPS_INFO
// (tests/test_onboarding_panel.py confere as duas cópias): o header do slot nomeia as três, a explicação
// fica no hover (title) — no header, só a extração vendia o slot curto.
const LLM_OPS = [
  ["Retain", "Quando um documento entra no vault, o LLM lê o texto e extrai os fatos duráveis: decisões e quem decidiu, compromissos com dono e prazo, entregas e números."],
  ["Consolidação", "Em segundo plano, o LLM revisa os fatos já retidos e forma observações — padrões e preferências estáveis sobre pessoas e projetos. Se mental models estiver ligado, também os atualiza quando você pede."],
  ["Reflexão", "Na hora da pergunta: em vez de devolver só trechos, o LLM raciocina sobre as memórias recuperadas e redige a resposta."],
];
const opTerm = ([name, tip]) => '<span class="op" tabindex="0" title="' + esc(tip) + '">' + esc(name) + "</span>";

// 6. Memória
OBV.memoria = () => {
  const m = OBS.memory || {};
  const normMode = m.mode === "lite" ? "embed" : (m.mode || "none");
  let sel = normMode === "full" ? "full" : "embed";

  const providers = (m.providers && (m.providers.llm || m.providers.embeddings || m.providers.reranker))
    ? m.providers
    : {
        llm: [
          {key: "claude-code", label: "Claude Code (assinatura Claude Pro/Max)", recommended: false, cloud: true, model: "claude-haiku-5-5", subscription: true, flow: "claude-token", key_set: false},
          {key: "chatgpt", label: "ChatGPT (sign-in / assinatura Plus/Pro)", recommended: false, cloud: true, model: "gpt-6-luna", subscription: true, key_set: false},
          {key: "cursor", label: "Cursor (assinatura)", recommended: false, cloud: true, model: "auto", subscription: true, key_set: false},
          {key: "github-copilot", label: "GitHub Copilot (assinatura)", recommended: false, cloud: true, model: "gpt-5.6-terra", subscription: true, key_set: false},
          {key: "xai-oauth", label: "xAI / SuperGrok (sign-in)", recommended: false, cloud: true, model: "grok-4.7", subscription: true, flow: "xai-device", key_set: false},
          {key: "nous", label: "Nous Portal (assinatura)", recommended: false, cloud: true, model: "deepseek/deepseek-v4-flash", subscription: true, key_set: false},
          {key: "anthropic", label: "Anthropic", recommended: true, cloud: true, model: "claude-haiku-5-5", key_set: !!m.llm_key},
          {key: "fireworks", label: "Fireworks — DeepSeek v4.1-Flash", recommended: false, cloud: true, model: "accounts/fireworks/models/deepseek-v4p1-flash", key_set: !!m.llm_key},
          {key: "openai", label: "OpenAI", recommended: false, cloud: true, model: "gpt-6-luna", key_set: !!m.llm_key},
          {key: "zai", label: "Z.ai (GLM, plano coding)", recommended: false, cloud: true, model: "glm-5.3-flash", key_set: !!m.llm_key},
          {key: "gemini", label: "Google Gemini (chave do AI Studio)", recommended: false, cloud: true, model: "gemini-3.1-flash-lite", key_set: !!m.llm_key},
          {key: "minimax", label: "MiniMax — M3.1-Flash (campeão de extração)", recommended: false, cloud: true, model: "MiniMax-M3.1-Flash", key_set: !!m.llm_key},
          {key: "custom", label: "Outro (OpenAI-compatível)", recommended: false, cloud: true, key_set: !!m.llm_key},
        ],
        embeddings: [
          {key: "local", label: "Local — LM Studio bge-m3 (zero egress)", recommended: true, cloud: false, key_set: false},
          {key: "fireworks", label: "Fireworks — Qwen3-Embedding-8B", recommended: false, cloud: true, key_set: !!m.emb_key},
          {key: "openai", label: "OpenAI — text-embedding-3-small", recommended: false, cloud: true, key_set: !!m.emb_key},
          {key: "cohere", label: "Cohere — embed-multilingual-v3.0", recommended: false, cloud: true, key_set: !!m.emb_key},
          {key: "custom", label: "Outro (OpenAI-compatível)", recommended: false, cloud: true, key_set: !!m.emb_key},
        ],
        reranker: [
          {key: "off", label: "Desligado — fusão RRF", recommended: true, cloud: false, key_set: false},
          {key: "fireworks", label: "Fireworks — Qwen3-Reranker-8B", recommended: false, cloud: true, key_set: !!m.rer_key},
          {key: "cohere", label: "Cohere — rerank-v3.5", recommended: false, cloud: true, key_set: !!m.rer_key},
          {key: "zeroentropy", label: "ZeroEntropy — zerank-2", recommended: false, cloud: true, key_set: !!m.rer_key},
          {key: "openrouter", label: "OpenRouter — rerank-v3.5", recommended: false, cloud: true, key_set: !!m.rer_key},
          {key: "custom", label: "Outro (compatível com /rerank)", recommended: false, cloud: true, key_set: !!m.rer_key},
        ],
        decision: [
          {key: "off", label: "Desligado — só os tokens do próprio LLM (padrão)", recommended: true, cloud: false, key_set: false},
          {key: "hindsight", label: "Hindsight — hs-decide-1-flash · US$ 0,02/1M de entrada (corta ~40% das chamadas do LLM)", recommended: false, cloud: true, key_set: !!m.dec_key},
        ],
      };

  const stack = m.stack || {};
  const stackDefault = slot => {
    const raw = stack[slot];
    if (raw && typeof raw === "object") return raw.provider || "";
    if (typeof raw === "string" && raw) return raw;
    if (slot === "llm") return m.llm_provider || "";
    if (slot === "embeddings") return m.emb_provider || "";
    if (slot === "reranker") return m.rer_provider || "";
    if (slot === "decision") return m.dec_provider || "off";
    return "";
  };
  const listFor = slot => providers[slot] || [];
  const chosen = {llm: "", embeddings: "", reranker: "", decision: ""};
  ["llm", "embeddings", "reranker", "decision"].forEach(slot => {
    const list = listFor(slot);
    const curVal = stackDefault(slot);
    const found = list.find(p => p.key === curVal) || list.find(p => p.recommended) || list[0];
    chosen[slot] = found ? found.key : "";
  });
  const getProv = (slot, key) => listFor(slot).find(p => p.key === key) || null;

  const pre = (on, t, link, midNote) => {
    const mid = on === "installed";
    const safeLink = (window.BRAIN && window.BRAIN.safeUrl) ? window.BRAIN.safeUrl(link) : "";
    return '<div style="display:flex;align-items:center;gap:8px;margin-top:4px">' +
      (mid ? '<span class="pill info">instalado</span>' : on ? '<span class="pill ok">pronto</span>' : '<span class="pill warn">falta</span>') +
      " <span>" + t +
      (!on && !mid && safeLink ? ' — <a href="' + esc(safeLink) + '" target="_blank" rel="noopener">baixar</a>' : "") +
      (mid ? " — " + (midNote || "o Brain sobe e configura ao ativar") : "") + "</span></div>";
  };

  obSet(obHead("Conexões · memória de IA", "Memória", "A memória deixa o Brain responder perguntas pelo <b>significado</b>. Sem ela, o Brain continua funcionando inteiro com busca por palavras.") +
    '<div class="grid3">' +
      '<div class="opt" data-m="none"><span class="pill off">Sem servidor · grátis</span><h3>Apenas livro-razão</h3><p>O cérebro funciona inteiro; ligar depois é 2 min e vira tarefa no seu TODO.</p></div>' +
      '<div class="opt" data-m="embed"><span class="pill rec">✓ recomendado pra começar</span><h3>Embed</h3><p>Busca por significado, 100% local e grátis. Chunks do vault, zero LLM, nada sai da máquina.</p></div>' +
      '<div class="opt" data-m="full"><span class="pill warn">Usa a sua chave · custo por uso</span><h3>Full</h3><p>Extrai fatos e liga assuntos entre reuniões. O texto vai para a IA com a sua chave.</p></div>' +
    "</div>" +
    '<div class="card" id="det" style="margin-top:14px"></div>' +
    '<div class="log" id="log"></div>' +
    '<div class="msg" id="m"></div>' +
    obNav({main: "Ativar", skip: "Fazer depois"}));

  const authChip = key => {
    const a = m.llm_auth || {};
    if (a.provider !== key) return "";
    if (a.state === "ok") return '<span class="pill ok" style="margin-left:6px">autenticado</span>';
    if (a.state === "pending") return '<span class="pill warn" style="margin-left:6px">autenticar</span>';
    return "";
  };
  const renderSlot = (slot, title, ops) => {
    const list = listFor(slot);
    const curKey = chosen[slot];
    const p = getProv(slot, curKey) || {};
    const needModel = slot === "llm" || curKey === "custom";
    const needModelUrl = needModel;
    const modelPh = slot === "llm" && p.model ? "vazio = " + p.model : "ex.: gpt-4o-mini";
    return '<div class="slot" data-slot="' + slot + '">' +
      '<div class="sh"><span>' + esc(title) + (ops ? " — " + ops.map(opTerm).join("&nbsp;· ") : "") + "</span>" +
        (p.recommended ? '<span class="pill rec">✓ recomendado</span>' : "") + "</div>" +
      '<select id="prov-' + slot + '">' +
        list.map(it => '<option value="' + esc(it.key) + '" ' + (it.key === curKey ? "selected" : "") + ">" + esc(it.label) + (it.recommended ? " — ✓ recomendado" : "") + "</option>").join("") +
      "</select>" +
      (p.subscription ? '<label class="f" style="margin-top:10px;margin-bottom:0">' +
        "<span>Assinatura — sem chave de API" + authChip(curKey) + "</span>" +
        '<small>' + esc(p.hint || "Autentique pelo botão abaixo; a credencial nunca passa pela tela.") + "</small>" +
        (p.flow ? '<div style="margin-top:8px"><button class="btn sm" type="button" id="auth-llm">' +
          (m.llm_auth && m.llm_auth.state === "ok" && m.llm_auth.provider === curKey ? "Reautenticar" : "Autenticar") +
          "</button></div>" : "") +
      "</label>" : p.cloud ? '<div style="margin-top:10px">' +
        '<label class="f" style="margin-bottom:' + (needModelUrl ? "10px" : "0") + '">' +
          "<span>API key " + (p.key_set ? '<span class="pill ok" style="margin-left:6px">chave já salva</span>' : "") + "</span>" +
          '<input type="password" id="key-' + slot + '" placeholder="' + (p.key_set ? "deixe vazio para manter a atual" : "cole a chave aqui") + '" autocomplete="off">' +
          '<small>Vai direto para <span class="kbd">config/.env</span> (0600) e nunca volta para a tela.</small>' +
        "</label>" +
      "</div>" : "") +
      (needModel ? '<div class="grid2" style="margin-top:8px">' +
        '<label class="f" style="margin-bottom:0"><span>Modelo</span><input type="text" id="model-' + slot + '" placeholder="' + esc(modelPh) + '"></label>' +
        (curKey === "custom" ? '<label class="f" style="margin-bottom:0"><span>Base URL</span><input type="text" id="url-' + slot + '" placeholder="https://…/v1"></label>' : "<div></div>") +
      "</div>" : "") +
    "</div>";
  };

  const drawDetails = () => {
    obAll("#view .opt").forEach(o => o.classList.toggle("sel", o.dataset.m === sel));
    if (sel === "none") {
      $("#det").innerHTML = '<h2>Apenas livro-razão</h2><p class="sub" style="margin:0">O Brain usa o índice local de palavras. Você pode ativar o Embed ou o Full depois (a tarefa fica registrada se escolher "Fazer depois").</p>';
      return;
    }
    const visibleSlots = sel === "full" ? ["llm", "embeddings", "reranker", "decision"] : ["embeddings", "reranker"];
    const anyCloud = visibleSlots.some(sl => (getProv(sl, chosen[sl]) || {}).cloud);
    const usesLocal = visibleSlots.some(sl => ["local", "lmstudio"].includes((getProv(sl, chosen[sl]) || {}).key));
    const prereqs = '<div class="rowline" style="margin-top:12px;padding-bottom:0;border-top:1px solid var(--line2)">' +
      '<div class="info"><b>Servidor e modelos locais</b>' +
        pre(m.docker_state || m.docker, "<b>OrbStack</b> — roda o servidor de memória (o Brain instala e sobe ao ativar)",
            "https://orbstack.dev", "o Brain sobe ao ativar") +
        (usesLocal ? pre(m.lmstudio_state || m.lmstudio,
                         "<b>LM Studio</b> — embeddings locais (o Brain instala e configura ao ativar)",
                         "https://lmstudio.ai") : "") +
      "</div></div>";
    $("#det").innerHTML = "<h2>Motores</h2>" +
      '<p class="sub">Escolha os provedores por slot — os itens recomendados já vêm selecionados.</p>' +
      (sel === "full" ? renderSlot("llm", "LLM", LLM_OPS) : "") +
      renderSlot("embeddings", "Embeddings") +
      renderSlot("reranker", "Reranker") +
      (sel === "full" ? renderSlot("decision", "Decisão — juiz rápido (opcional)") : "") +
      (anyCloud ? '<div class="egress">⚠ Provedor em nuvem: texto do vault sai da máquina — o doctor narra enquanto estiver ativo.</div>' : "") +
      prereqs +
      (sel === "full" ? '<label class="check"><input type="checkbox" id="consent"> Entendo que trechos das minhas reuniões, mensagens e documentos serão enviados à API do provedor, com a minha chave, e que isso tem custo por uso.</label>' : "");

    visibleSlots.forEach(slot => {
      const sEl = $("#prov-" + slot);
      if (sEl) sEl.onchange = () => { chosen[slot] = sEl.value; drawDetails(); };
    });
    const aBtn = $("#auth-llm");
    if (aBtn) aBtn.onclick = async () => {
      const gen = obStepGen;
      obBusy(aBtn, true, "Autenticando…");
      const log = $("#log");
      try {
        const r = await obAct("memory_auth", {provider: chosen.llm});
        if (r.job) {
          const j = await obJob(r.job, jj => { if (obStillOn(gen)) obTickLog(log, jj); });
          if (!obStillOn(gen)) return;
          if (j.status === "error") return obMsg($("#m"), "err", (j.result && j.result.error) || "não consegui autenticar");
          if (j.result && j.result.ok === false)
            obMsg($("#m"), "late", "Autenticação não completou — o log acima diz o que faltou.");
          else obMsg($("#m"), "ok", "✓ Autenticado.");
        }
        await obRefresh();
        if (!obStillOn(gen)) return;
        Object.assign(m, OBS.memory || {});
        drawDetails();
      } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { obBusy(aBtn, false); }
    };
  };

  obAll("#view .opt").forEach(o => o.onclick = () => { sel = o.dataset.m; drawDetails(); });
  drawDetails();

  const readSlot = slot => {
    const sEl = $("#prov-" + slot);
    if (!sEl) return undefined;
    const obj = {provider: sEl.value};
    const kEl = $("#key-" + slot), mEl = $("#model-" + slot), uEl = $("#url-" + slot);
    if (kEl && kEl.value.trim()) obj.key = kEl.value.trim();
    if (mEl && mEl.value.trim()) obj.model = mEl.value.trim();
    if (uEl && uEl.value.trim()) obj.base_url = uEl.value.trim();
    return obj;
  };

  obBindNav(async btn => {
    const body = {mode: sel};
    if (sel === "embed" || sel === "full") {
      body.embeddings = readSlot("embeddings");
      body.reranker = readSlot("reranker");
    }
    if (sel === "full") {
      body.llm = readSlot("llm");
      body.decision = readSlot("decision");
      body.consent = !!($("#consent") && $("#consent").checked);
      if (!body.consent) return obMsg($("#m"), "err", "Para o modo Full, marque o aceite de envio à API.");
    }
    const checkSlots = sel === "full" ? [["llm", "LLM"], ["embeddings", "Embeddings"], ["reranker", "Reranker"], ["decision", "Decisão"]]
      : (sel === "embed" ? [["embeddings", "Embeddings"], ["reranker", "Reranker"]] : []);
    for (const pair of checkSlots) {
      const p = getProv(pair[0], body[pair[0]].provider);
      if (p && p.cloud && !p.subscription && !p.key_set && !body[pair[0]].key) {
        return obMsg($("#m"), "err", 'Cole a API key de ' + pair[1] + " (" + p.label + ') — ou escolha "Fazer depois".');
      }
    }
    obBusy(btn, true, "Ativando…");
    const log = $("#log"), gen = obStepGen;
    try {
      const r = await obAct("memory", body);
      obAll("#det input[type=password]").forEach(i => { i.value = ""; });
      if (r.job) {
        const j = await obJob(r.job, jj => { if (obStillOn(gen)) obTickLog(log, jj); });
        if (j.status === "error") {
          if (obStillOn(gen)) obMsg($("#m"), "err", (j.result && j.result.error) || "não consegui ligar a memória");
          return;
        }
      }
      await obRefresh();
      if (!obStillOn(gen)) return;
      obMsg($("#m"), "ok", "✓ Memória configurada.");
      setTimeout(() => { if (obStillOn(gen)) obNext(); }, 700);
    } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { obBusy(btn, false); }
  }, async skipBtn => {
    const gen = obStepGen;
    obBusy(skipBtn, true, "Salvando…");
    try { await obAct("memory", {mode: sel, later: true}); await obRefresh(); if (obStillOn(gen)) obNext(); }
    catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { obBusy(skipBtn, false); }
  });
};

// 7. Chaves e portas
OBV.chaves = () => {
  const k = OBS.keys || {GITHUB_TOKEN: {set: false}};
  obSet(obHead("Conexões", "Chaves e portas", "Nada aqui é obrigatório. As chaves ficam só no seu computador e nunca aparecem de novo na tela.") +
    '<div class="card">' +
      "<h2>Sugestões e bugs do Brain " + (k.GITHUB_TOKEN.set ? '<span class="pill ok" style="margin-left:6px">configurado</span>' : "") + "</h2>" +
      '<p class="sub">Com um token do GitHub, as sugestões que você mandar pelo Brain viram issues públicas no repositório do projeto.</p>' +
      '<ol class="howto" style="margin:4px 0 12px;padding-left:20px;color:var(--muted)">' +
        '<li>Abra <a href="https://github.com/settings/tokens/new?scopes=public_repo&description=Brain%20%E2%80%94%20sugest%C3%B5es%20e%20bugs" target="_blank" rel="noopener">a página de criação do GitHub</a> — o escopo <b>public_repo</b> já vem marcado (é o único necessário: este token só abre e lê issues em repositórios públicos).</li>' +
        "<li>Em <b>Expiration</b>, escolha <b>No expiration</b> — sem validade, pra não parar de funcionar num mês (o risco é mínimo: issues em repos públicos, nada mais).</li>" +
        "<li>Role até o fim e clique em <b>Generate token</b>; depois cole o valor abaixo.</li>" +
      "</ol>" +
      '<label class="f" style="margin:0"><span>Token do GitHub (GITHUB_TOKEN)</span><input type="password" id="gh" placeholder="' + (k.GITHUB_TOKEN.set ? "deixe vazio para manter o atual" : "ghp_… (clássico, escopo public_repo)") + '" autocomplete="off"></label>' +
    "</div>" +
    '<div class="card">' +
      "<h2>Google — foco na agenda e backup no Drive " + ((k.GOOGLE_REFRESH_TOKEN && k.GOOGLE_REFRESH_TOKEN.set) ? '<span class="pill ok" style="margin-left:6px">conectado</span>' : "") + "</h2>" +
      '<p class="sub">Blocos de foco aprovados entram direto no Google Calendar, e o backup semanal sobe pro Drive. Escopo mínimo: só eventos que o Brain cria + os próprios zips de backup.</p>' +
      '<ol class="howto" style="margin:4px 0 12px;padding-left:20px;color:var(--muted)">' +
        '<li>No <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">Google Cloud Console</a>, crie um <b>ID do cliente OAuth</b> do tipo <b>App desktop</b> (ative a Calendar API e a Drive API se o console pedir).</li>' +
        "<li>Copie o <b>Client ID</b> e o <b>Client Secret</b> para os campos abaixo.</li>" +
        "<li>Clique em <b>Conectar Google</b> — o navegador abre na autorização; aceite e volte.</li>" +
      "</ol>" +
      '<div class="grid2">' +
        '<label class="f"><span>Client ID ' + (k.GOOGLE_CLIENT_ID && k.GOOGLE_CLIENT_ID.set ? '<span class="pill ok">já salvo</span>' : "") + '</span><input type="text" id="gcid" placeholder="' + (k.GOOGLE_CLIENT_ID && k.GOOGLE_CLIENT_ID.set ? "deixe vazio para manter o atual" : "…apps.googleusercontent.com") + '" autocomplete="off"></label>' +
        '<label class="f" style="margin-bottom:0"><span>Client Secret ' + (k.GOOGLE_CLIENT_SECRET && k.GOOGLE_CLIENT_SECRET.set ? '<span class="pill ok">já salvo</span>' : "") + '</span><input type="password" id="gsec" placeholder="' + (k.GOOGLE_CLIENT_SECRET && k.GOOGLE_CLIENT_SECRET.set ? "deixe vazio para manter o atual" : "GOCSPX-…") + '" autocomplete="off"></label>' +
      "</div>" +
      '<div class="actions" style="margin-top:14px"><button class="btn pri sm" type="button" id="gcon">Conectar Google</button>' +
        '<span style="font-size:12px;color:var(--muted)">O navegador vai abrir pra você autorizar — o token fica no seu computador.</span></div>' +
      '<div class="log" id="glog"></div>' +
    "</div>" +
    '<div class="msg" id="m"></div>' +
    obNav({skip: "Pular"}));
  obBindNav(async btn => {
    const v = $("#gh").value.trim();
    if (!v) { await obSkip(obCur); return; }
    obBusy(btn, true);
    try { await obAct("keys", {GITHUB_TOKEN: v}); $("#gh").value = ""; await obRefresh(); obNext(); }
    catch (e) { obMsg($("#m"), "err", e.message); } finally { obBusy(btn, false); }
  });

  $("#gcon").onclick = async () => {
    const b = $("#gcon"), log = $("#glog");
    obBusy(b, true, "Conectando…");
    try {
      const r = await obAct("foco_google", {client_id: $("#gcid").value, client_secret: $("#gsec").value});
      if (r.job) {
        log.classList.add("show");
        const j = await obJob(r.job, jj => { log.textContent = (jj.log || []).join("\n"); log.scrollTop = 1e9; });
        if (j.status === "error") throw new Error((j.result && j.result.error) || "não consegui conectar o Google");
      }
      $("#gsec").value = "";
      await obRefresh();
      obMsg($("#m"), "ok", "✓ Google conectado — foco na agenda e backup no Drive ativos.");
    } catch (e) { obMsg($("#m"), "err", e.message); } finally { obBusy(b, false); }
  };
};

// 8. A máquina
const OB_MQ_PILL = {done: ["ok", "✓ pronto"], pending: ["warn", "pendente"], warn: ["warn", "atenção"], off: ["off", "desligado"]};
OBV.maquina = () => {
  const mq = OBS.maquina || {};
  const pill = st => {
    const pair = OB_MQ_PILL[st] || OB_MQ_PILL.pending;
    return '<span class="pill ' + pair[0] + '">' + pair[1] + "</span>";
  };
  obSet(obHead("O cérebro", "A máquina", "Cinco ajustes para o Brain rodar sozinho no seu computador, com defaults prontos. Confira e clique em Configurar.") +
    '<div class="card">' +
      '<div class="rowline">' +
        '<div class="info"><b>Sincronização automática</b><p>O "noturno": reler fontes, renderizar o painel, sincronizar memória e backup semanal — sem você fazer nada.</p></div>' +
        '<div class="right">' + pill(mq.noturno) +
          '<label class="toggle" title="Agendar sincronização"><input type="checkbox" id="mq-agendar" checked><span></span></label>' +
          '<input type="time" id="mq-time" value="05:00" style="width:104px" title="Horário da sincronização (HH:MM)">' +
        "</div>" +
      "</div>" +
      '<div class="rowline">' +
        '<div class="info"><b>Comando <span class="kbd">brain</span> no PATH</b><p>Usar o cérebro de qualquer pasta no terminal.</p></div>' +
        '<div class="right">' + pill(mq.comando) +
          '<label class="toggle" title="Instalar comando brain no PATH"><input type="checkbox" id="mq-comando" checked><span></span></label>' +
        "</div>" +
      "</div>" +
      '<div class="rowline">' +
        '<div class="info"><b>' + (mq.platform === "darwin" ? "Ícone no Dock" : "Atalho na área de trabalho") + "</b><p>O Brain a um clique, como qualquer app — e a aba do painel se reaproveita em vez de abrir nova toda hora.</p></div>" +
        '<div class="right">' + pill(mq.icon) +
          '<label class="toggle" title="Pregar o atalho do Brain"><input type="checkbox" id="mq-icon" checked><span></span></label>' +
        "</div>" +
      "</div>" +
      '<div class="rowline">' +
        '<div class="info"><b>TUI</b><p>Cockpit de terminal (opcional, ~40 MB): Execução · Portfólio · Configurações.</p></div>' +
        '<div class="right">' + pill(mq.tui) +
          '<label class="toggle" title="Instalar TUI"><input type="checkbox" id="mq-tui" checked><span></span></label>' +
        "</div>" +
      "</div>" +
      '<div class="rowline">' +
        '<div class="info"><b>Agenda — Google Calendar</b><p>Blocos de foco aprovados entram direto na sua agenda (e o backup semanal vai pro Drive).</p></div>' +
        '<div class="right">' + ((OBS.keys && OBS.keys.GOOGLE_REFRESH_TOKEN && OBS.keys.GOOGLE_REFRESH_TOKEN.set)
          ? '<span class="pill ok">✓ Google conectado</span>'
          : '<span class="pill warn">conectar em Chaves e portas</span> <button class="btn sm" type="button" id="mq-goto-keys">ir lá</button>') + "</div>" +
      "</div>" +
      '<div class="rowline">' +
        '<div class="info"><b>Atualização do framework</b><p>Novidades do projeto chegam até você: o comando <span class="kbd">update</span> busca as melhorias mais recentes e aplica no seu Brain.</p></div>' +
        '<div class="right">' + pill(mq.framework) +
          '<label class="toggle" title="Configurar atualização do framework"><input type="checkbox" id="mq-framework" checked><span></span></label>' +
        "</div>" +
      "</div>" +
      '<div class="log" id="log"></div>' +
      '<div class="msg" id="m"></div>' +
    "</div>" +
    obNav({main: "Configurar", skip: "Fazer depois"}));

  const gk = $("#mq-goto-keys");
  if (gk) gk.onclick = () => obGo("chaves");

  obBindNav(async btn => {
    const payload = {
      noturno: $("#mq-agendar").checked ? $("#mq-time").value : "",
      comando: $("#mq-comando").checked,
      icon: $("#mq-icon").checked,
      tui: $("#mq-tui").checked,
      framework: $("#mq-framework").checked,
    };
    const log = $("#log"), gen = obStepGen;
    obBusy(btn, true, "Configurando…");
    try {
      const r = await obAct("maquina", payload);
      if (r.job) {
        const j = await obJob(r.job, jj => { if (obStillOn(gen)) obTickLog(log, jj); });
        if (j.status === "error") {
          if (obStillOn(gen)) obMsg($("#m"), "err", (j.result && j.result.error) || "não consegui configurar a máquina");
          return;
        }
      }
      await obRefresh();
      if (!obStillOn(gen)) return;
      obMsg($("#m"), "ok", "✓ Máquina configurada.");
      setTimeout(() => { if (obStillOn(gen)) obNext(); }, 700);
    } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { obBusy(btn, false); }
  });
};

// 9. Goals e projetos
const obEmptyGoal = () => ({title: "", horizon: "", why: "", projects: [{title: "", deliverables: [{title: "", due: ""}]}]});
OBV.planejamento = () => {
  if (OBS.planning.proposal && !obPlan.goals.length) { obPlan = JSON.parse(JSON.stringify(OBS.planning.proposal)); obPlanTab = "revisar"; }
  const hasGoals = OBS.planning.goals > 0;
  obSet(obHead("Começando", "Goals e projetos", "É o mapa do que você quer alcançar. O Brain liga cada tarefa e decisão a um projeto, e mostra o progresso.") +
    '<div class="hier"><span class="g">Goal — objetivo grande</span>→<span class="p">Projeto — como chegar lá</span>→<span>Entregável — o que sai pronto</span></div>' +
    (hasGoals ? '<div class="msg info show">Você já tem ' + OBS.planning.goals + " goal(s). O que criar aqui é somado a eles.</div>" : "") +
    '<div style="margin-top:16px" class="tabs"><button type="button" data-t="escrever">Escrever ou enviar documento</button><button type="button" data-t="revisar">Revisar e montar</button></div>' +
    '<div id="tab"></div><div class="msg" id="m"></div>' +
    obNav({main: "Aprovar e criar", skip: "Fazer depois"}));
  obAll("#view .tabs button").forEach(b => { b.classList.toggle("on", b.dataset.t === obPlanTab); b.onclick = () => { obPlanTab = b.dataset.t; OBV.planejamento(); }; });
  const mainBtn = $('[data-a="main"]');
  if (obPlanTab === "escrever") {
    mainBtn.classList.add("hidden");
    $("#tab").innerHTML = '<div class="card">' +
      '<label class="f"><span>Explique com as suas palavras</span><textarea id="ptext" style="min-height:150px" placeholder="Ex.: Neste semestre quero lançar o novo app de pagamentos até junho. Para isso, preciso fechar a pesquisa com clientes em março e o MVP em maio. Também quero estruturar o time de dados…"></textarea></label>' +
      '<div class="drop" id="drop"><b>Arraste documentos aqui</b> ou clique para escolher<br><small style="color:var(--muted)">Planejamento, OKRs, apresentação… (PDF, Word, PowerPoint, texto — até 25 MB)</small><input type="file" id="file" multiple class="hidden"></div>' +
      '<ul class="files" id="files">' + obUploads.map(u => "<li><span>" + esc(u.name) + "</span><span>✓ recebido</span></li>").join("") + "</ul>" +
      '<div class="actions" style="margin-top:16px"><span class="spacer"></span><button class="btn" type="button" id="manual">Montar à mão</button><button class="btn pri" type="button" id="ob-gen" ' + (OBS.agent ? "" : "disabled") + '>✦ Gerar proposta com IA</button></div>' +
      (OBS.agent ? "" : '<p style="color:var(--muted);font-size:12.5px;margin:10px 0 0">A proposta automática precisa de um agente headless instalado ou configurado em [runner]. Você pode montar à mão.</p>') +
      '<div class="log" id="log"></div></div>';
    const drop = $("#drop"), file = $("#file");
    drop.onclick = () => file.click();
    drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); send(e.dataTransfer.files); };
    file.onchange = () => send(file.files);
    async function send(list) {
      for (const f of Array.from(list)) {
        const li = document.createElement("li"); li.innerHTML = "<span>" + esc(f.name) + "</span><span><i class='spin'></i></span>"; $("#files").appendChild(li);
        try {
          const r = await fetch("/api/onboard/upload", {method: "POST", headers: {"X-Brain-Token": TOK || "", "X-File-Name": encodeURIComponent(f.name)}, body: f});
          if (r.status === 401) { handle401(); throw new Error("sessão expirada — reabra via ./brain render --open"); }
          const j = await r.json(); if (!r.ok || !j.ok) throw new Error(j.error || "falhou");
          obUploads.push({name: j.name}); li.lastChild.textContent = "✓ recebido";
        } catch (e) { li.lastChild.textContent = "✗ " + e.message; }
      }
    }
    $("#manual").onclick = () => { if (!obPlan.goals.length) obPlan.goals.push(obEmptyGoal()); obPlanTab = "revisar"; OBV.planejamento(); };
    $("#ob-gen").onclick = async () => {
      const b = $("#ob-gen"), log = $("#log"), gen = obStepGen;
      const t = $("#ptext").value.trim();
      if (!t && !obUploads.length) return obMsg($("#m"), "err", "Escreva algo ou envie um documento primeiro.");
      obBusy(b, true, "Lendo…");
      try {
        if (t) await obAct("planning_note", {text: t});
        const r = await obAct("planning_draft");
        log.classList.add("show"); log.textContent = "O Brain está lendo o que você mandou. Isso leva de 1 a 3 minutos…";
        const j = await obJob(r.job, jj => { if (jj.log && jj.log.length && obStillOn(gen)) obTickLog(log, jj); });
        if (j.status === "error") throw new Error((j.result && j.result.error) || "não consegui gerar a proposta");
        obPlan = j.result.proposal; obPlanTab = "revisar"; await obRefresh();
        if (obStillOn(gen)) OBV.planejamento();   // dono saiu do passo? a proposta fica em obPlan e aparece quando ele voltar
      } catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { obBusy(b, false); }
    };
  } else {
    obDrawTree();
  }
  obBindNav(async btn => {
    obCollectTree();
    const goals = obPlan.goals.filter(g => g.title.trim());
    if (!goals.length) return obMsg($("#m"), "err", 'Adicione pelo menos um goal — ou escolha "Fazer depois".');
    if (!$("#approve").checked) return obMsg($("#m"), "err", "Marque a confirmação para criar os goals.");
    const gen = obStepGen;
    obBusy(btn, true, "Criando…");
    try { await obAct("planning_apply", {proposal: {goals}, approved: true}); obPlan = {goals: []}; await obRefresh(); if (obStillOn(gen)) obNext(); }
    catch (e) { if (obStillOn(gen)) obMsg($("#m"), "err", e.message); } finally { obBusy(btn, false); }
  });
};
function obDrawTree() {
  if (!obPlan.goals.length) obPlan.goals.push(obEmptyGoal());
  $("#tab").innerHTML = (obPlan.summary ? '<div class="msg info show" style="margin:0 0 14px">✦ ' + esc(obPlan.summary) + "</div>" : "") +
    '<div class="tree" id="tree">' + obPlan.goals.map((g, gi) => '<div class="goal" data-g="' + gi + '">' +
      '<div class="row"><span class="lvl g">Goal</span><input type="text" data-f="title" value="' + esc(g.title) + '" placeholder="Ex.: Lançar o app de pagamentos"><button class="x" type="button" data-rm="g" title="Remover">×</button></div>' +
      '<div class="row"><span class="lvl d">Por quê</span><input type="text" data-f="why" value="' + esc(g.why) + '" placeholder="o que isto destrava (opcional)"><input type="date" data-f="horizon" value="' + esc(g.horizon) + '" style="max-width:170px" title="Prazo do goal"></div>' +
      g.projects.map((p, pi) => '<div class="proj" data-p="' + pi + '">' +
        '<div class="row"><span class="lvl p">Projeto</span><input type="text" data-f="title" value="' + esc(p.title) + '" placeholder="Ex.: Pesquisa com clientes"><button class="x" type="button" data-rm="p">×</button></div>' +
        p.deliverables.map((d, di) => '<div class="row del" data-d="' + di + '"><span class="lvl d">Entregável</span><input type="text" data-f="title" value="' + esc(d.title) + '" placeholder="Ex.: Relatório de entrevistas"><input type="date" data-f="due" value="' + esc(d.due) + '" style="max-width:170px" title="Prazo"><button class="x" type="button" data-rm="d">×</button></div>').join("") +
        '<button class="add del" type="button" data-add="d">+ entregável</button></div>').join("") +
      '<button class="add" type="button" data-add="p" style="margin-left:18px">+ projeto</button></div>').join("") + "</div>" +
    '<button class="btn sm" type="button" data-add="g">+ goal</button>' +
    '<label class="check" style="margin-top:16px"><input type="checkbox" id="approve"> Aprovo: pode criar estes goals, projetos e entregáveis no meu Brain.</label>';
  obAll("#tab [data-add]").forEach(b => b.onclick = () => {
    obCollectTree();
    const gEl = b.closest("[data-g]"), pEl = b.closest("[data-p]");
    if (b.dataset.add === "g") obPlan.goals.push(obEmptyGoal());
    if (b.dataset.add === "p") obPlan.goals[+gEl.dataset.g].projects.push({title: "", deliverables: [{title: "", due: ""}]});
    if (b.dataset.add === "d") obPlan.goals[+gEl.dataset.g].projects[+pEl.dataset.p].deliverables.push({title: "", due: ""});
    obDrawTree();
  });
  obAll("#tab [data-rm]").forEach(b => b.onclick = () => {
    obCollectTree();
    const gi = +b.closest("[data-g]").dataset.g, pEl = b.closest("[data-p]"), dEl = b.closest("[data-d]");
    if (b.dataset.rm === "g") obPlan.goals.splice(gi, 1);
    if (b.dataset.rm === "p") obPlan.goals[gi].projects.splice(+pEl.dataset.p, 1);
    if (b.dataset.rm === "d") obPlan.goals[gi].projects[+pEl.dataset.p].deliverables.splice(+dEl.dataset.d, 1);
    obDrawTree();
  });
}
function obCollectTree() {
  if (!$("#tree")) return;
  const val = (el, f) => { const x = el.querySelector(":scope > .row [data-f=\"" + f + "\"]"); return x ? x.value.trim() : ""; };
  obPlan.goals = obAll("#tree .goal").map(gEl => ({
    title: val(gEl, "title"), why: val(gEl, "why"), horizon: val(gEl, "horizon"),
    projects: obAll(":scope > .proj", gEl).map(pEl => ({
      title: val(pEl, "title"),
      deliverables: obAll(":scope > .del[data-d]", pEl).map(dEl => ({
        title: (dEl.querySelector("[data-f=\"title\"]") || {value: ""}).value.trim(),
        due: (dEl.querySelector("[data-f=\"due\"]") || {value: ""}).value || "",
      })).filter(d => d.title),
    })).filter(p => p.title),
  }));
}

// 10. A conversa
OBV.conversa = () => {
  obSet(obHead("Começando", "A conversa", "O formulário acabou; a entrevista não. Responda aqui mesmo — ou pule e o Brain anota no seu TODO.") +
    '<div class="card">' +
      "<h2>Uma pergunta aberta para o agente</h2>" +
      '<p class="sub">O que o Brain ainda quer saber para fechar o seu mapa:</p>' +
      '<div class="msgline"><b>Pessoas recorrentes</b> — quem mais aparece no seu dia, para criar fichas sem duplicar ninguém.</div>' +
      '<div class="msgline"><b>Fontes que valem observar</b> — canais, pastas ou projetos que faltaram nas conexões.</div>' +
      '<label class="f"><span>Pessoas recorrentes <i style="font-weight:400">(uma por linha: Nome — apelido, e-mail)</i></span>' +
        '<textarea id="cv-people" rows="4" placeholder="Marina Silva — Mari, marina@exemplo.com&#10;Heitor Costa"></textarea></label>' +
      '<label class="f"><span>Fontes que valem observar <i style="font-weight:400">(uma por linha: canal, pasta, projeto)</i></span>' +
        '<textarea id="cv-sources" rows="3" placeholder="#time-dados&#10;pasta do Drive &quot;Clientes&quot;"></textarea></label>' +
      '<p class="sub" style="margin:2px 0 0">As pessoas viram fichas agora; as fontes entram como proposta para você aprovar depois.</p>' +
    "</div>" +
    '<div class="card soft">' +
      '<div class="rowline" style="padding:0">' +
        '<div class="info"><b>Se preferir conversar depois</b><p>Pule — o Brain cria uma tarefa no seu TODO e retoma a pergunta quando você abrir o chat (ou o <span class="kbd">⚡</span> na TUI).</p></div>' +
        '<span class="pill ok">não se perde</span>' +
      "</div>" +
    "</div>" +
    obNav({main: "Enviar respostas", skip: "Pular"}));
  obBindNav(async btn => {
    obBusy(btn, true);
    try { await obAct("entrevista", {people: $("#cv-people").value, sources: $("#cv-sources").value}); obNext(); }
    catch (e) { obMsg($("#m"), "err", e.message); } finally { obBusy(btn, false); }
  });
};

// 11. Pronto
OBV.pronto = () => {
  const d = obDoneSet();
  const agents = OBS.agents || [];
  const connAg = agents.find(a => a.detected && (a.mcp || a.selected)) || agents.find(a => a.mcp || a.selected);
  const agLabel = connAg ? connAg.label : (OBS.agent || "");
  const agDetail = connAg ? [connAg.mcp ? "MCP" : "", connAg.selected ? "selecionado" : ""].filter(Boolean).join(" · ") : "";

  const enabledConns = (OBS.connectors || []).filter(c => c.enabled).map(c => c.label);
  const nSources = (OBS.sources || []).length;
  const connExtra = [enabledConns.join(", "), nSources ? nSources + " fonte(s)" : ""].filter(Boolean).join(" · ");

  const memLabel = {none: "apenas livro-razão", lite: "embed", embed: "embed", full: "full"}[(OBS.memory || {}).mode] || "apenas livro-razão";

  const mq = OBS.maquina || {};
  const mqFmt = (name, st) => name + ": " + ({done: "pronto", pending: "pendente", warn: "atenção", off: "desligado"}[st] || st || "—");
  const mqExtra = [mqFmt("sincronização", mq.noturno), mqFmt("comando", mq.comando), mqFmt("TUI", mq.tui)].join(" · ");
  const mqDone = mq.noturno === "done" && mq.comando === "done";

  const nGoals = (OBS.planning || {}).goals || 0;
  const row = (ok, title, extra) => "<li>" + (ok ? '<span class="pill ok">pronto</span>' : '<span class="pill off">depois</span>') + " <b>" + esc(title) + "</b>" + (extra ? '<span class="extra">— ' + esc(extra) + "</span>" : "") + "</li>";

  obSet(obHead("Começando", "Pronto — seu Brain está de pé", "Daqui para frente, abra o Brain pelo ícone e comece o dia por ele.") +
    '<div class="card"><ul class="summary">' +
      row(!!connAg, "Agente", agLabel ? (agDetail ? agLabel + " (" + agDetail + ")" : agLabel) : "nenhum conectado") +
      row(enabledConns.length > 0 || nSources > 0, "Conectores e fontes", connExtra || "nenhum") +
      row((OBS.memory || {}).mode && OBS.memory.mode !== "none", "Memória", memLabel) +
      row(mqDone || d.has("maquina"), "Máquina", mqExtra) +
      row(nGoals > 0, "Goals e projetos", nGoals ? nGoals + " goal(s)" : "nenhum ainda") +
    "</ul></div>" +
    '<div class="msg info show" style="margin:0 0 14px">O que ficou pra depois virou tarefa com nome no seu TODO.</div>' +
    '<div class="card soft"><h2>Primeiros passos</h2><ol class="howto">' +
      "<li>No chat com o seu agente, nesta pasta, digite <b>/brief</b> para ver o seu dia.</li>" +
      "<li>Jogue arquivos (atas, PDFs, prints) na caixa de entrada do Brain e digite <b>/dump</b> — ele organiza tudo.</li>" +
      "<li>Para puxar as novidades do Slack, Gmail e agenda: <b>/update</b>.</li></ol>" +
      (OBS.inbox ? '<p style="color:var(--muted);margin:10px 0 0;font-size:13px">Você tem ' + OBS.inbox + " item(ns) na caixa de entrada esperando um <b>/dump</b>.</p>" : "") + "</div>" +
    '<div class="msg" id="m"></div>' +
    obNav({main: "Abrir meu Brain"}));
  obBindNav(async btn => {
    obBusy(btn, true, "Preparando o painel…");
    try {
      await obAct("finish");
      try { localStorage.removeItem("brain-onboarding-step"); } catch (e) {}
      obBusy(btn, false);
      await exitOnboarding();          // F8: mesma página — o painel aparece sem recarregar
    }
    catch (e) { obMsg($("#m"), "err", e.message); obBusy(btn, false); }
  });
};

function obRender() { obRenderSteps(); (OBV[obCur] || OBV.inicio)(); }

async function enterOnboarding() {
  if (OB_ACTIVE) return;
  OB_ACTIVE = true;
  document.body.classList.add("obmode");
  if (!LIVE) {
    obSet('<section class="card"><h2>A configuração guiada precisa do app</h2><p class="sub">Este painel foi aberto como arquivo (retrato). Abra o <b>Brain</b> pelos Aplicativos, Launchpad ou Spotlight — enquanto a configuração não termina, o app abre aqui sozinho.</p></section>');
    return;
  }
  obSet('<section class="card"><p class="sub">carregando a configuração…</p></section>');
  try { await obRefresh(); }
  catch (e) { obSet('<section class="card"><p class="late">Não consegui falar com o Brain: ' + esc(e.message) + "</p></section>"); return; }
  const side = document.getElementById("side");
  if (side && !document.getElementById("obnav")) {
    const nav = document.createElement("div");
    nav.className = "obnav"; nav.id = "obnav";
    nav.innerHTML = '<ol class="steps" id="ob-steps"></ol><p class="obnote">Tudo fica no seu computador. Você pode voltar a qualquer passo e mudar depois.</p>';
    side.insertBefore(nav, document.getElementById("tabs"));
  }
  obRender();
}
async function exitOnboarding() {
  OB_ACTIVE = false; window.__obDone = true;
  const teardown = () => {
    document.body.classList.remove("obmode");
    const n = document.getElementById("obnav"); if (n) n.remove();
  };
  try {
    const d = await api("/api/data");
    if (d && d.model && window.BRAIN && window.BRAIN.refresh) { teardown(); window.BRAIN.refresh(d.model); return; }
  } catch (e) { /* views regeneram no próximo brain render */ }
  teardown();
  location.hash = "home";
}
window.enterOnboarding = enterOnboarding;
window.exitOnboarding = exitOnboarding;

// ── atualização via ponte (/api/update) + cópia no retrato ──────────────
(function(){
  let updatePoll = null;
  function setUpdateTriggersDisabled(disabled){
    document.querySelectorAll("[data-brain-update]").forEach(el => { el.disabled = !!disabled; });
  }
  function renderUpdateLog(lines, status, diverged){
    const log = document.getElementById("newslog");
    if (!log) return;
    log.hidden = false;
    const rows = (lines || []).map(ln => {
      const cls = ln.startsWith("✓") ? "ok" : (ln.startsWith("✗") || ln.startsWith("⚠") ? "err" : "dim");
      const pref = (ln.startsWith("✓") || ln.startsWith("✗") || ln.startsWith("⚠"))
        ? ""
        : (status === "error" ? "✗ " : (status === "done" ? "✓ " : "… "));
      return '<div class="news-log-line ' + cls + '">' + esc(pref + ln) + "</div>";
    });
    if (status === "error" && diverged) {
      rows.push('<div class="news-log-line err">✗ Dica: rode o comando `update --rebase` no terminal.</div>');
    }
    log.innerHTML = rows.join("");
    log.scrollTop = log.scrollHeight;
  }
  function copyUpdateCmd(){
    const back = document.getElementById("newsback");
    const cmd = (back && back.dataset.cliCmd) || "";
    const fb = document.getElementById("newsfb");
    const done = () => {
      if (fb) fb.textContent = "Comando copiado";
      toast("Comando copiado");
    };
    if (!cmd) return;
    if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      navigator.clipboard.writeText(cmd).then(done, () => { copyCmd(cmd); done(); });
    } else {
      copyCmd(cmd);
      done();
    }
  }
  function waitBridgeAndReload(){
    const log = document.getElementById("newslog");
    if (log) {
      log.innerHTML += '<div class="news-log-line dim">… Reiniciando ponte…</div>';
      log.scrollTop = log.scrollHeight;
    }
    const started = Date.now();
    let delay = 500;
    const step = async () => {
      if (Date.now() - started > 20000) {
        setUpdateTriggersDisabled(false);
        const fb = document.getElementById("newsfb");
        if (fb) fb.textContent = "Ponte demorou para voltar — recarregue a página.";
        return;
      }
      try {
        const r = await fetch("/api/data", {headers: {"X-Brain-Token": TOK || ""}});
        if (r.status === 401) { handle401(); setUpdateTriggersDisabled(false); return; }
        if (r.ok) { location.reload(); return; }
      } catch (e) {}
      delay = Math.min(2000, Math.round(delay * 1.4));
      setTimeout(step, delay);
    };
    setTimeout(step, delay);
  }
  function pollUpdateJob(jid){
    if (updatePoll) { clearTimeout(updatePoll); updatePoll = null; }
    const tick = async () => {
      let jr;
      try {
        jr = await api("/api/update/job/" + encodeURIComponent(jid));
      } catch (e) {
        renderUpdateLog(["perdeu contato com a ponte durante a atualização"], "error", false);
        setUpdateTriggersDisabled(false);
        return;
      }
      const j = (jr && jr.job) ? jr.job : jr;
      if (!j || (jr && jr.ok === false)) {
        renderUpdateLog(["execução de atualização não encontrada"], "error", false);
        setUpdateTriggersDisabled(false);
        return;
      }
      renderUpdateLog(j.lines || [], j.status, !!j.diverged);
      if (j.status === "running") {
        updatePoll = setTimeout(tick, 500);
        return;
      }
      if (j.status === "done" && j.restarting) {
        waitBridgeAndReload();
        return;
      }
      setUpdateTriggersDisabled(false);
    };
    updatePoll = setTimeout(tick, 500);
  }
  document.addEventListener("click", async e => {
    const trg = e.target.closest("[data-brain-update]");
    if (!trg) return;
    e.preventDefault();
    if (!LIVE) {
      copyUpdateCmd();
      return;
    }
    const back = document.getElementById("newsback");
    if (back) {
      back.hidden = false;
      back.classList.add("open");
    }
    const fb = document.getElementById("newsfb");
    if (fb) fb.textContent = "";
    const log = document.getElementById("newslog");
    if (log) { log.innerHTML = ""; log.hidden = false; }
    setUpdateTriggersDisabled(true);
    let res = null;
    try {
      const r = await fetch("/api/update", {
        method: "POST",
        headers: {"X-Brain-Token": TOK || "", "Content-Type": "application/json"},
        body: "{}",
      });
      if (r.status === 401) {
        handle401();
        setUpdateTriggersDisabled(false);
        return;
      }
      try { res = await r.json(); } catch (err) {}
      if (r.status === 409 && res && res.job) {
        pollUpdateJob(res.job);
        return;
      }
      if (!r.ok || !res || !res.ok || !res.job) {
        renderUpdateLog([(res && res.error) || ("erro " + r.status)], "error", false);
        setUpdateTriggersDisabled(false);
        return;
      }
      pollUpdateJob(res.job);
    } catch (err) {
      renderUpdateLog(["ponte fora do ar"], "error", false);
      setUpdateTriggersDisabled(false);
    }
  });
})();

})();
