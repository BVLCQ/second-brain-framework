// ── formulários: o MESMO motor do brainlib/forms.py ──────────────────────
// A especificação (campos, rótulos, obrigatórios, quando aparece, como vira `brain …`) chega pronta no view model
// (M.forms) e as regexes em M.form_static.re: nada de campo escrito à mão aqui. Cada nome de CHECKS/HINTS/XF/INIT/
// IFMT/SOURCES/PRED/FILL espelha o do Python — tests/test_forms.py roda os dois pelo node e compara o comando.
// Carrega no navegador (window.BRAIN_FORMS) e no node (module.exports), sem tocar no DOM.
const BRAIN_FORMS = (function(){
  const ELL = "…", NONE = "—";
  let RE = null;
  function re(M, k){
    if (!RE || RE._m !== M) { RE = {_m: M}; const s = (M.form_static || {}).re || {};
      Object.keys(s).forEach(n => { const [p, fl] = s[n]; RE[n] = (typeof p === "string" && !["jira_mine"].includes(n)) ? new RegExp(p, fl) : p; }); }
    return RE[k];
  }
  const str = x => x === null || x === undefined ? "" : String(x);
  const pyrepr = t => t.includes("'") && !t.includes('"') ? '"' + t + '"' : "'" + t.replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "'";   // repr() do Python
  const fold = t => str(t).normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
  const csvSplit = t => str(t).split(",").map(x => x.trim()).filter(Boolean);
  const short = (t, n) => { n = n || 46; return t.length <= n ? t : t.slice(0, n - 1) + "…"; };
  const active = x => x.status === "ativo" || x.status === "ativa";

  // shlex.join (Python): o preview das duas pontas é a mesma linha
  function shq(s){ s = str(s); if (s === "") return "''"; if (/^[\w@%+=:,./-]+$/.test(s)) return s; return "'" + s.replace(/'/g, "'\"'\"'") + "'"; }
  const shjoin = a => a.map(shq).join(" ");

  // ── datas (brainlib/dates.py) ──
  const WD = {seg: 0, segunda: 0, ter: 1, terca: 1, qua: 2, quarta: 2, qui: 3, quinta: 3, sex: 4, sexta: 4, sab: 5, sabado: 5, dom: 6, domingo: 6};
  const iso = d => d.getUTCFullYear() + "-" + String(d.getUTCMonth() + 1).padStart(2, "0") + "-" + String(d.getUTCDate()).padStart(2, "0");
  const dayOf = s => { const [y, m, d] = s.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const addDays = (d, n) => new Date(d.getTime() + n * 86400000);
  const pyWeekday = d => (d.getUTCDay() + 6) % 7;
  function parseDue(text, today, M){
    const s = fold(text); if (!s) return null;
    const help = (M.form_static || {}).date_help || "";
    const bad = () => { throw new Error("data não reconhecida: " + pyrepr(str(text)) + " (" + help + ")"); };
    let m;
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) { const d = dayOf(s); if (iso(d) !== s) bad(); return d; }
    if (s === "hoje") return today;
    if (s === "amanha") return addDays(today, 1);
    if ((m = s.match(/^\+(\d{1,3})d?$/))) return addDays(today, +m[1]);
    if ((m = s.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{4}))?$/))) {
      const y = +(m[3] || today.getUTCFullYear()), mo = +m[2], d = +m[1], dt = new Date(Date.UTC(y, mo - 1, d));
      if (dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) throw new Error("day is out of range for month");
      return dt; }
    const name = s.replace(/-feira$/, "");
    if (name in WD) { const ahead = (WD[name] - pyWeekday(today) + 7) % 7; return addDays(today, ahead || 7); }
    return bad();
  }
  const todayOf = M => dayOf(M.today);
  function describeDate(text, M){
    let d; try { d = parseDue(text, todayOf(M), M); } catch (e) { return e.message; }
    if (!d) return "";
    const wd = ((M.form_static || {}).weekdays || [])[pyWeekday(d)] || "";
    return "→ " + iso(d) + " (" + wd + " " + String(d.getUTCDate()).padStart(2, "0") + "/" + String(d.getUTCMonth() + 1).padStart(2, "0") + ")";
  }
  // util.parse_duration
  function parseDuration(v, M){
    if (v === null || v === undefined || v === "") return null;
    const s = str(v).trim().toLowerCase().replace(/ /g, ""); let m;
    if ((m = s.match(/^(\d+)h(\d+)$/))) return +m[1] * 60 + +m[2];
    m = s.match(re(M, "dur"));
    if (!m || !(m[1] || m[2] || m[3])) throw new Error("duração inválida: " + pyrepr(str(v)) + " (ex.: 90m, 2h, 1h30, 1d)");
    return (+(m[1] || 0)) * 480 + (+(m[2] || 0)) * 60 + (+(m[3] || 0));
  }
  // ids.normalize
  function normId(ref, M){
    const v = str(ref).trim(), L = re(M, "legacy_long") || {}, LP = re(M, "long_prefixes") || []; let m;
    if ((m = v.match(new RegExp("^([" + Object.keys(L).join("") + "])-(\\d+)$", "i")))) return L[m[1].toUpperCase()] + "-" + String(+m[2]).padStart(4, "0");
    if ((m = v.match(/^G(\d+)$/i))) return "GOAL-" + (+m[1]);
    if ((m = v.match(/^P(\d+)(?:\.(\d+))?$/i))) return "PROJ-" + (+m[1]) + (m[2] !== undefined ? "." + (+m[2]) : "");
    if ((m = v.match(new RegExp("^(" + LP.join("|") + ")-(\\d+)$", "i")))) return m[1].toUpperCase() + "-" + String(+m[2]).padStart(4, "0");
    if ((m = v.match(/^(GOAL|PROJ)-(\d+)(?:\.(\d+))?$/i))) return m[1].toUpperCase() + "-" + (+m[2]) + (m[3] !== undefined ? "." + (+m[3]) : "");
    return ref;
  }
  // watch.py: Drive e Jira
  function driveId(ref, M){ ref = str(ref).trim(); const m = ref.match(re(M, "drive_url")); if (m) return m[1] || m[2];
    return re(M, "drive_id").test(ref) ? ref : null; }
  function jiraCloud(ref, M){ const m = str(ref).trim().match(re(M, "jira_host")); return m ? m[1].toLowerCase() : null; }
  function jiraBase(scope, ref, M){
    ref = str(ref).trim();
    if (scope === "mine") return re(M, "jira_mine");
    if (scope === "jql") { if (!ref) throw new Error("escreva a JQL"); return ref; }
    if (!ref) throw new Error("cole a chave ou a URL");
    if (scope === "epic") { const m = (ref.includes("://") ? ref : ref.toUpperCase()).match(re(M, "jira_issue"));
      if (!m) throw new Error("épico: não achei uma chave como OPS-123 em " + pyrepr(ref)); return "parent = " + m[1]; }
    if (scope === "filter") { const m = ref.match(re(M, "jira_filter")); const fid = m ? (m[1] || m[2]) : (/^\d+$/.test(ref) ? ref : null);
      if (!fid) throw new Error("filtro: cole a URL do filtro ou o id numérico (recebi " + pyrepr(ref) + ")"); return "filter = " + fid; }
    if (scope === "project" || scope === "board") { const m = ref.match(re(M, "jira_project"));
      const key = m ? (m[1] || m[2]) : (/^[A-Za-z][A-Za-z0-9_]+$/.test(ref) ? ref.toUpperCase() : null);
      if (!key) throw new Error(scope + ": " + (scope === "board" ? "cole a URL do board (…/projects/OPS/boards/12) — o id sozinho não diz o projeto"
        : "cole a chave (OPS) ou a URL do projeto"));
      return "project = " + key; }
    throw new Error("escopo do jira desconhecido: " + pyrepr(scope));
  }
  function jiraJql(scope, ref, mode, M){ const b = jiraBase(scope, ref, M); if (scope === "jql") return b;
    return mode === "state" ? b + " AND statusCategory != Done ORDER BY key" : b + " AND updated >= -1d"; }
  const num = x => { if (x === null || x === undefined || x === "") return ""; const t = str(x).trim(), f = Number(t);
    return t === "" || isNaN(f) ? str(x) : String(f); };
  const fmtDur = n => { if (!n) return ""; const h = Math.floor(n / 60), mi = n % 60; return h && mi ? h + "h" + mi + "m" : h ? h + "h" : mi + "m"; };
  const pairs = t => { const o = {}; str(t).split(";").filter(p => p.trim()).forEach(p => { const i = p.indexOf("=");
    const k = (i < 0 ? p : p.slice(0, i)).trim(); o[k] = i < 0 ? "" : p.slice(i + 1).trim(); }); return o; };

  // ── fontes de listas (as mesmas do SOURCES do Python, lidas de M) ──
  const pf = M => M.portfolio || {};
  const goalOf = (item, ctx, M) => { const p = item && item.project; if (!p || p === NONE) return NONE;
    const x = (M.projects || []).find(y => y.id === p); return x ? x.goal : NONE; };
  const allDelivs = M => { const o = {}; (M.projects || []).forEach(p => (p.deliverables || []).forEach(d => { o[d.id] = [p, d]; })); return o; };
  const ice = ax => (M, v, ctx) => { const r = ((pf(M).ice_rubric || {}).axes || {})[ax];
    return [["", "— escolha —"]].concat(((r || {}).levels || []).map(l => [String(l.n), l.label])); };
  const planNodes = M => (M.goals || []).map(g => [g.id, g.id + " · " + short(g.title)]).concat((M.projects || []).map(p => [p.id, p.id + " · " + short(p.title)]));
  const NODE = ["ativo", "congelado", "depois", "finalizado"];
  const OPP_STATUS = ["ideia", "triagem", "priorizada", "em-andamento", "piloto", "validando", "entregue", "em-espera", "descartada"];
  const OPP_LATERAL = ["em-espera", "descartada"];
  const st = M => M.form_static || {};
  const SOURCES = {
    people: M => (M.people || []).map(p => [p.id, p.name]),
    recipients: M => (M.people || []).filter(p => !p.is_owner).map(p => [p.id, p.name]),
    relations: () => [["par", "par"], ["gestor", "gestor"], ["stakeholder", "stakeholder"], ["time", "time"]],
    areas: M => (pf(M).areas || []).map(a => [a.id, a.name]),
    processes: M => (pf(M).processes || []).map(p => [p.id, p.id + " · " + short(p.title)]),
    doc_targets: M => ["processes", "opportunities"].flatMap(k => (pf(M)[k] || []).map(x => [x.id, x.id + " · " + short(x.title)])),
    goals: M => (M.goals || []).map(g => [g.id, g.id + " · " + short(g.title)]),
    goals_active: M => (M.goals || []).filter(active).map(g => [g.id, g.id + " · " + short(g.title)]),
    projects_active: M => (M.projects || []).filter(active).map(p => [p.id, p.id + " · " + short(p.title)]),
    goal_filter: (M, v, ctx) => { const keep = goalOf((ctx && ctx.item) || {project: ctx && ctx.project}, ctx, M);
      return [[NONE, "— (todos os goals)"]].concat((M.goals || []).filter(g => active(g) || g.id === keep).map(g => [g.id, g.id + " · " + short(g.title)])); },
    projects_of_goal: (M, v, ctx) => { const g = (v && v.goal) || NONE; let keep = ((ctx && ctx.item) || {}).project || (ctx && ctx.project) || "";
      const kp = (M.projects || []).find(p => p.id === keep), kg = kp ? kp.goal : NONE; if (!(g === NONE || g === kg)) keep = "";
      return [[NONE, NONE]].concat((M.projects || []).filter(p => (active(p) && (g === NONE || p.goal === g)) || p.id === keep).map(p => [p.id, p.id + " · " + short(p.title)])); },
    plan_nodes: M => planNodes(M),
    link_targets: M => (M.actions || []).filter(a => a.open).map(a => [a.id, a.id + " · " + short(a.title)]).concat(planNodes(M)),
    decisions: M => (M.decisions || []).filter(d => d.status === "ativa").map(d => [d.id, d.id + " · " + short(d.title)]),
    artifacts: M => (M.artifacts || []).map(a => [a.id, short(a.title || a.id)]),
    ask_options: (M, v, ctx) => (((ctx && ctx.item) || {}).options || []).map(o => [o, o]),
    node_status: (M, v, ctx) => { const cur = ((ctx && ctx.item) || {}).status; return NODE.concat(cur && !NODE.includes(cur) ? [cur] : []).map(s => [s, s]); },
    recurrence: M => [[NONE, NONE]].concat((st(M).recurrence || []).map(r => [r, r])),
    opp_kinds: M => (st(M).opp_kinds || []).map(k => [k, k]),
    doc_kinds: M => (M.doc_kinds || []).map(k => [k, k]),
    source_kinds: (M, v, ctx) => { const ks = (M.source_kinds || []).map(k => [k[0], k[1]]), cur = ((ctx && ctx.item) || {}).kind;
      return ks.concat(cur && !ks.some(k => k[0] === cur) ? [[cur, cur]] : []); },
    opp_status: (M, v, ctx) => { const it = (ctx && ctx.item) || {};
      return OPP_STATUS.map(s => [s, s + (s === it.status ? " ← atual" : OPP_LATERAL.includes(s) ? " (pede motivo)"
        : (s === "em-andamento" && !(it.promoted || it.project)) ? " (só promovendo: p)" : "")]); },
    reports: M => (st(M).reports || []).map(r => [r, r]),
    destinations: M => (st(M).destinations || []).map(d => [d, d]),
    providers: (M, v) => (((st(M).providers || {})[(v && v.slot) || "embeddings"]) || []).map(x => [x[0], x[1]]),
    "ice:impact": ice("impact"), "ice:confidence": ice("confidence"), "ice:ease": ice("ease"),
  };
  function options(f, M, v, ctx){
    const src = f.choices !== undefined ? f.choices : f.suggest;
    if (src === undefined || src === null) return [];
    if (typeof src === "string") return SOURCES[src.replace(/^@/, "")](M, v || {}, ctx || {}).map(x => [str(x[0]), str(x[1])]);
    return src.map(x => [str(x[0]), str(x[1])]);
  }
  function label(f, M){
    if (f.label.startsWith("@ice:")) { const ax = ((pf(M).ice_rubric || {}).axes || {})[f.label.slice(5)] || {};
      return ((ax.name || f.label.slice(5)) + " — " + (ax.question || "")).replace(/[ —]+$/, ""); }
    return f.label;
  }

  // ── valor inicial ──
  const INIT = {str: x => str(x), csv: x => (x || []).join(", "), csvc: x => (x || []).join(","), dur: fmtDur, num: num,
    prio: x => x || "normal", jscope: x => x ? "jql" : "mine"};
  const SRC_META = ["key", "kind", "in_watch", "last_ok", "last_error", "failures", "pulls", "last_changed", "window", "note",
    "channel", "user", "query", "folder", "doc", "jql", "cloud", "mode", "path"];
  const IFMT = {
    goal_of: goalOf,
    deliv_short: item => { const d = item.deliverable || "", p = item.project || ""; return p && d.startsWith(p + ".") ? d.split(".").slice(1).join(".") : d; },
    owner_shown: item => (item.mine || item.list === "mine") ? "eu" : (item.owner || ""),
    owner_base: item => item.mine ? "eu" : (item.owner || ""),
    source_other: item => Object.entries(item).filter(([k, x]) => !SRC_META.includes(k) && x !== null && x !== undefined && x !== "").map(([k, x]) => k + "=" + x).join("; "),
    cloud0: (item, ctx, M) => item.cloud || ((M.sources || []).find(s => s.cloud) || {}).cloud || "",
  };
  function initOf(spec, ctx, M){
    if (!spec) return "";
    const item = ctx.item || {};
    if (spec[0] === "@") return str(ctx[spec.slice(1)]);
    const i = spec.indexOf(":"), key = i < 0 ? spec : spec.slice(0, i), fmt = i < 0 ? "" : spec.slice(i + 1);
    if (IFMT[fmt]) return IFMT[fmt](item, ctx, M);
    return INIT[fmt || "str"](item[key]);
  }
  function initial(fm, ctx, M){ const o = {}; fm.fields.forEach(f => { const g = f.init ? initOf(f.init, ctx || {}, M) : ""; o[f.id] = g !== "" ? g : (f.value || ""); }); return o; }
  function baseline(fm, ctx, M){ const o = {}; fm.fields.forEach(f => { o[f.id] = initOf(f.base || f.init, ctx || {}, M); }); return o; }

  // ── visibilidade ──
  const fbDup = (v, ctx, M) => { const key = fold(v.title).split(" ").filter(Boolean).join(" "), kind = v.kind || "sugestao";
    return key ? (M.feedback || []).find(f => f.kind === kind && fold(f.title).split(" ").filter(Boolean).join(" ") === key) : undefined; };
  const PRED = {
    fb_dup: (v, ctx, M) => !!fbDup(v, ctx, M),
    no_target_ctx: (v, ctx) => !ctx.target_fixed,
    prop_close: (v, ctx) => ctx.kind === "fechar-acao" && !!ctx.target,
    prop_effort: (v, ctx) => ctx.kind === "reestimar" && !!ctx.target,
    prop_merge: (v, ctx) => ctx.kind === "unificar-acao" && !!ctx.target && !!ctx.into,
    prop_drop: (v, ctx) => ctx.kind === "descartar-acao" && !!ctx.target && !!ctx.into,
  };
  function cond(c, v, ctx, M){
    if (c === undefined || c === null) return true;
    if (typeof c === "string") return !!PRED[c](v, ctx, M);
    return Object.entries(c).every(([k, vals]) => { const neg = k.endsWith("!"); k = k.replace(/!+$/, "");
      const got = str(k[0] === "@" ? ctx[k.slice(1)] : (v[k] || "")); return vals.includes(got) !== neg; });
  }
  function hidden(fm, raw, ctx, M){ return new Set(fm.fields.filter(f => !cond(f.show, raw, ctx || {}, M)).map(f => f.id)); }
  function values(fm, raw, ctx, M){
    const r = {}; fm.fields.forEach(f => { r[f.id] = str(raw[f.id]).trim(); });
    const h = hidden(fm, r, ctx, M); const o = {}; Object.keys(r).forEach(k => { o[k] = h.has(k) ? "" : r[k]; }); return o;
  }

  // ── validação e dicas ──
  const delivFull = (x, project, M) => { const r = normId(str(x).trim().toUpperCase().replace(/^\.+/, ""), M);
    if (/^\d+$/.test(r)) return project && project !== NONE ? project + "." + (+r) : ""; return r; };
  const ckInt = (lo, hi) => x => { const ok = /^\d+$/.test(x) && (lo === null || +x >= lo) && (hi === null || +x <= hi);
    return ok ? "" : (lo !== null && hi !== null ? "Use um inteiro de " + lo + " a " + hi + "." : "Use um inteiro a partir de " + lo + "."); };
  const ckDur = pos => (x, v, ctx, M) => { let n; try { n = parseDuration(x, M); } catch (e) { return e.message; }
    return pos && !n ? "Use uma duração maior que zero (45m, 1h30m)." : ""; };
  const linkNorm = (x, M) => { const v = str(x).trim().toUpperCase(), m = v.match(/^(?:A|TASK)-?(\d{1,})$/);   // notes.normalize_link
    return m ? "TASK-" + String(+m[1]).padStart(4, "0") : normId(v, M); };
  const CHECKS = {
    date: (x, v, ctx, M) => { try { parseDue(x, todayOf(M), M); return ""; } catch (e) { return e.message; } },
    duration: ckDur(false), duration_pos: ckDur(true),
    num: x => { const t = str(x).replace(",", ".").trim(), f = Number(t); return (t !== "" && !isNaN(f) && f > 0) ? "" : "Use um número maior que zero."; },
    slug: x => /^[a-z0-9]+(-[a-z0-9]+)*$/.test(x) ? "" : "Use minúsculas, números e hífens (ex.: growth).",
    watch_key: (x, v, ctx, M) => { if (!re(M, "key").test(x)) return "key: minúsculas, números, '.', '_' e '-' (ex.: slack-time-dados)";
      return (M.sources || []).some(s => s.in_watch && s.key === x && s.key !== ctx.key0) ? "já existe uma fonte com essa key" : ""; },
    drive: (x, v, ctx, M) => driveId(x, M) ? "" : "cole a URL (ou o id) do Drive",
    jira: (x, v, ctx, M) => { try { jiraBase(v.jscope || "mine", x, M); return ""; } catch (e) { return e.message; } },
    pairs: (x, v, ctx, M) => { for (const part of str(x).split(";").filter(p => p.trim())) { const i = part.indexOf("=");
      if (i < 0 || !re(M, "field").test(part.slice(0, i).trim())) return "use campo=valor separados por ponto e vírgula (recebi " + pyrepr(part.trim()) + ")"; } return ""; },
    deliv: (x, v, ctx, M) => { const full = delivFull(x, v.project || "", M);
      if (!full) return "Só o número precisa do campo projeto: escolha o projeto ou escreva PROJ-#.# por inteiro.";
      if (allDelivs(M)[full]) return ""; const p = full.split(".")[0];
      const nums = (M.projects || []).filter(pr => pr.id === p).flatMap(pr => (pr.deliverables || []).map(d => d.id.split(".")[1]));
      return full + " não existe" + (nums.length ? " (os de " + p + " são " + nums.join(", ") + ")" : ""); },
    merge_into: (x, v, ctx, M) => { const t = (M.actions || []).find(a => a.id === normId(x, M));
      if (!t || t.id === ctx.id) return "informe outra ação existente (TASK-####)"; return t.open ? "" : t.id + " precisa estar aberta"; },
    proc: (x, v, ctx, M) => (pf(M).processes || []).some(p => p.id === x) ? "" : x + " não existe (use PROC-####).",
    goal: (x, v, ctx, M) => (M.goals || []).some(g => g.id === x) ? "" : x + " não existe no PLANNING (use GOAL-#).",
    doc_watch: (x, v, ctx, M) => { if (x !== "sim") return ""; if (v.kind !== "playbook") return "Só playbook é vigiado.";
      return driveId(v.ref || "", M) ? "" : "Vigiar pede um doc do Drive (URL ou id)."; },
    fb_dup: (x, v, ctx, M) => { const f = fbDup(v, ctx, M);
      return f && v.force !== "sim" ? "mesmo título e tipo de " + f.id + " — acrescente detalhe ao existente (`brain feedback show " + f.id + "`) ou marque “criar mesmo assim”" : ""; },
    opp_status: (x, v, ctx) => { const it = ctx.item || {};
      return x === "em-andamento" && x !== it.status && !(it.promoted || it.project) ? (it.id || "") + ": 'em-andamento' só existe depois de promover (tecla p, em qualquer nível)." : ""; },
    note_link: (x, v, ctx, M) => { const l = linkNorm(x, M);         // as mensagens de notes.check_link
      if (!re(M, "link_id").test(l)) return "vínculo inválido: " + pyrepr(l) + " (use TASK-####, GOAL-#, PROJ-# ou PROJ-#.#)";
      if (l.startsWith("TASK-")) return (M.actions || []).some(a => a.id === l) ? "" : l + ": ação não encontrada";
      const plan = new Set((M.goals || []).map(g => g.id).concat((M.projects || []).map(p => p.id), Object.keys(allDelivs(M))));
      return plan.has(l) ? "" : l + ": não existe em PLANNING/goals.md"; },
    no_dot: x => x.includes("·") ? "O título não pode ter “·”." : "",
  };
  function check(name, x, v, ctx, M){
    if (!name || !x) return "";
    const [b, lo, hi] = name.split(":");
    if (b === "int") return ckInt(lo ? +lo : null, hi ? +hi : null)(x);
    return CHECKS[b] ? CHECKS[b](x, v, ctx || {}, M) : "";
  }
  const hIce = ax => (x, v, ctx, M) => { const r = ((pf(M).ice_rubric || {}).axes || {})[ax] || {};
    const lv = (r.levels || []).find(l => String(l.n) === x); return lv ? lv.criterion + " · " + lv.anchor : ""; };
  const hHours = h => h > 40 ? 5 : h >= 20 ? 4 : h >= 10 ? 3 : h >= 5 ? 2 : 1;
  const HINTS = {
    date: (x, v, ctx, M) => describeDate(x, M),
    drive: (x, v, ctx, M) => { const g = driveId(x, M); return g ? "id " + g : "não parece uma URL ou id do Drive"; },
    jira: (x, v, ctx, M) => { try { return "→ " + jiraJql(v.jscope || "mine", x, v.mode || "", M); } catch (e) { return e.message; } },
    deliv: (x, v, ctx, M) => { const full = delivFull(x, v.project || "", M), hit = allDelivs(M)[full]; return hit ? "→ " + full + " · " + hit[1].title : ""; },
    note_link: (x, v, ctx, M) => { const bad = CHECKS.note_link(x, v, ctx, M); if (bad) return bad;
      const l = linkNorm(x, M), a = (M.actions || []).find(y => y.id === l);
      const t = (a && a.title) || ((M.goals || []).concat(M.projects || []).find(n => n.id === l) || {}).title || ((allDelivs(M)[l] || [])[1] || {}).title || "";
      return t ? "→ " + l + " · " + t : ""; },
    "ice:impact": hIce("impact"), "ice:confidence": hIce("confidence"), "ice:ease": hIce("ease"),
    ice_impact: (x, v, ctx, M) => { let out = hIce("impact")(x, v, ctx, M); const h = (ctx.item || {}).hours_saved;
      if (/^\d+$/.test(x) && h) { const hint = hHours(+h); out += "\nhoras declaradas: " + num(+h) + " h/mês → faixa sugerida " + hint;
        if (+x > hint) out += " · ⚠ escopo e horas divergem: vale a menor nota"; } return out; },
  };
  function hint(name, x, v, ctx, M){ return (!name || !x || !HINTS[name]) ? "" : HINTS[name](x, v, ctx || {}, M); }
  const XF = {
    date: (x, v, ctx, M) => { let d; try { d = parseDue(x, todayOf(M), M); } catch (e) { return ""; } return d ? iso(d) : ""; },
    deliv: (x, v, ctx, M) => delivFull(x, v.project || "", M) || x,
    nospace: x => x.replace(/ /g, ""),
    num: x => x ? num(x.replace(",", ".")) : "",
    note_link: (x, v, ctx, M) => x ? linkNorm(x, M) : "",
    lower_eu: x => x.toLowerCase() === "eu" ? "eu" : x,
    jql: (x, v, ctx, M) => { if (!x) return ""; try { return jiraJql(x || "mine", v.jref || "", v.mode || "", M); } catch (e) { return v.jref || ELL; } },
    jira_cloud: (x, v, ctx, M) => x || jiraCloud(v.jref || "", M) || "",
    new_people: (x, v, ctx) => { const had = new Set(((ctx.item || {}).people) || []); return csvSplit(x).filter(p => !had.has(p)).join(","); },
  };
  const FILL = {owner_for_list: v => v.list === "mine" ? "eu" : (str(v.owner).toLowerCase() === "eu" ? "" : undefined)};

  // ── montagem do comando (forms.build) ──
  const xf = (f, x, v, ctx, M) => f.xf ? XF[f.xf](x, v, ctx, M) : x;
  function tok(t, fm, v, ctx, M){
    const byId = {}; fm.fields.forEach(f => { byId[f.id] = f; });
    const m = t.match(/^\{([?*@]?)([\w.]+)\}$/);
    if (!m) return [t.replace(/\{@(\w+)\}/g, (_, k) => str(ctx[k]) || ELL)];
    const [, mode, name] = m;
    if (mode === "@" || !byId[name]) { const val = ctx[name]; return [val === undefined || val === null || val === "" ? ELL : str(val)]; }
    let val = xf(byId[name], v[name] || "", v, ctx, M);
    if (val === "" && ctx[name] !== undefined && ctx[name] !== null && ctx[name] !== "") val = str(ctx[name]);   // escondido/vazio: o ctx fixa
    if (mode === "*") { const p = csvSplit(val); return p.length ? p : [ELL]; }
    if (mode === "?") return val ? [val] : [];
    return [val || ELL];
  }
  function argOf(f, val){
    if (f.flag) return (f.flag[val] || []).slice();
    if (f.set === "*") return Object.entries(pairs(val)).flatMap(([k, x]) => ["--set", k + "=" + x]);
    if (f.set) return ["--set", f.set + "=" + val];
    if (f.many) return csvSplit(val).flatMap(p => [f.arg, p]);
    return f.arg ? [f.arg, val] : [];
  }
  const emits = f => !!(f.arg || f.set || f.flag);
  function formArgv(fm, raw, ctx, M){
    ctx = ctx || {};
    const v = values(fm, raw, ctx, M), byId = {}; fm.fields.forEach(f => { byId[f.id] = f; });
    const placed = new Set(fm.cmd.filter(t => t[0] === "{").map(t => t.replace(/[{}?*@]/g, "")));
    let main = []; fm.cmd.forEach(t => { main = main.concat(tok(t, fm, v, ctx, M)); });
    const base = fm.edit ? baseline(fm, ctx, M) : {};
    const order = (fm.order || []).concat(fm.fields.map(f => f.id).filter(id => !(fm.order || []).includes(id)));
    order.forEach(id => { const f = byId[id]; if (!f || placed.has(id) || !emits(f)) return;
      const val = xf(f, v[id], v, ctx, M);
      if (fm.edit && !f.always) {
        if (f.set === "*") { const old = pairs(base[id] || ""), nw = pairs(val);
          Object.entries(nw).forEach(([k, x]) => { if (old[k] !== x) main.push("--set", k + "=" + x); });
          Object.keys(old).forEach(k => { if (!(k in nw)) main.push("--unset", k); }); return; }
        const was = f.xf !== "new_people" ? xf(f, base[id] || "", v, ctx, M) : (base[id] || "");
        if (val === was) return;
        if (val === "") { main = main.concat(f.clear || []); return; }
      }
      if (val === "" || (f.skip || []).includes(val)) return;
      main = main.concat(argOf(f, val));
    });
    main = main.concat(fm.tail || []);
    const cmds = [main];
    (fm.more || []).forEach(([p, tpl]) => { if (PRED[p](v, ctx, M)) { let c = []; tpl.forEach(t => { c = c.concat(tok(t, fm, v, ctx, M)); }); cmds.push(c); } });
    return cmds;
  }
  function missing(fm, raw, ctx, M){
    ctx = ctx || {};
    const v = values(fm, raw, ctx, M), r = {}; Object.keys(v).forEach(k => { r[k] = str(raw[k]); });
    const h = hidden(fm, r, ctx, M);
    for (const f of fm.fields) { if (h.has(f.id)) continue;
      if (f.req && !v[f.id]) return 'Preencha "' + label(f, M) + '".';
      const msg = check(f.check, v[f.id], v, ctx, M); if (msg) return msg; }
    return "";
  }
  const fmt = (s, ctx) => str(s).replace(/\{(\w+)\}/g, (_, k) => str((ctx || {})[k]));
  const display = cmds => cmds.map(c => "brain " + shjoin(c)).join("\n");
  return {formArgv, missing, initial, baseline, values, hidden, options, label, check, hint, fmt, display, shjoin, cond,
    FILL, SOURCES, INIT, IFMT, PRED, CHECKS, HINTS, XF, parseDue, describeDate, parseDuration, normId};
})();
if (typeof window !== "undefined") window.BRAIN_FORMS = BRAIN_FORMS;
if (typeof module !== "undefined" && module.exports) module.exports = BRAIN_FORMS;
