"""Cartão "Seu dia": o brief do agente em Markdown mínimo vira HTML seguro (#160).

O brief é texto do agente — e o agente leu conteúdo da inbox: é entrada NÃO confiável. Este módulo fixa as
duas metades: (1) o que renderiza — seções, ênfases, listas, id com link para a ficha (título e situação lidos
do modelo), título solto e "(noturno)" fora; (2) o que NUNCA entra — HTML cru, <img>, javascript:, atributo
vindo do texto. O modelo sai do pipeline real (eventos → `render.view_model`) e o JS é o do painel compilado,
rodando em node no stub de DOM dos outros testes de painel."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")   # hoje = sexta, 09/10

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "brainlib" / "assets"
sys.path.insert(0, str(ROOT))

from brainlib import config, notes, render  # noqa: E402
from brainlib.core import Brain  # noqa: E402

_TITLE = "# Brief do dia — 09/10/2026 (noturno)\n\n"
_RICH = _TITLE + """## Hoje
- **Fornada**: TASK-0003 vence hoje — confirmar com Caio.
- `brain render` depois de ajustar; TASK-0006 já foi

## Atrasadas
- TASK-0002 (alta) — ligar para o fornecedor; DEC-0001 no caderno

## Aguardando você
- PROP-0001 · ASK-0001 · MSG-0009
- ver GOAL-1 e PROJ-1.1, DEC-0002, WIN-0001
"""
_FOUR = _TITLE + "## A\n- x\n## B\n- y\n## C\n- z\n## D\n- w"


def _demo_brain(root: Path) -> Brain:
    """Instância de demonstração (padaria) com um exemplo de cada entidade que o brief pode citar."""
    (root / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED/_ledger", "FRESH", "logs", "reports"):
        (root / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (root / "config" / "brain.toml").write_text('[owner]\nid = "marina-demo"\nname = "Marina Demo"\n', encoding="utf-8")
    (root / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n"
        "## GOAL-1 — Padaria previsível\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: reduzir desperdício de massa\n\n"
        "### PROJ-1 — Fornada da manhã\n- status: ativo\n- dono: marina-demo\n"
        "- [ ] PROJ-1.1 Ajustar escala · prazo: 2026-11-15 · peso: 1\n",
        encoding="utf-8",
    )
    (root / "vault" / "PROCESSED" / "_ledger" / "events.jsonl").write_text("", encoding="utf-8")
    b = Brain(config.load(root))
    owner = {"by": "owner"}
    b.record_one({"type": "person.added", "id": "marina-demo", **owner,
                  "data": {"name": "Marina Demo", "email": "marina-demo@x.com", "aliases": ["Marina"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "caio-demo", **owner,
                  "data": {"name": "Caio Demo", "email": "caio-demo@x.com", "aliases": ["Caio"], "relation": "fornecedor"}})
    for data in ({"title": "Ajustar escala"},
                 {"title": "Ligar para o fornecedor", "due": "2026-10-06", "priority": "alta"},
                 {"title": "Enviar orçamento", "list": "waiting", "owner": "caio-demo", "due": "2026-10-09"},
                 {"title": 'Revisar "contrato" <rascunho>', "due": "2026-10-12"},
                 {"title": "Comprar farinha"},
                 {"title": "Arquivar nota fiscal"}):
        b.record_one({"type": "action.opened", **owner, "data": data})
    b.record_one({"type": "action.closed", "id": "TASK-0006", **owner, "data": {"how": "feito"}})
    for date, title in (("2026-10-08", "Trocar a farinha"), ("2026-10-09", "Fornada dupla")):
        b.record_one({"type": "decision.made", **owner, "date": date, "source": "chat", "data": {"title": title, "decided_by": ["marina-demo"]}})
    b.record_one({"type": "delivery.recorded", **owner, "date": "2026-10-09", "source": "chat", "data": {"title": "Fornada de sábado", "result": "ok"}})
    b.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "chat",
                  "data": {"kind": "descartar-acao", "summary": "TASK-0001 duplica TASK-0003", "target": "TASK-0001", "into": "TASK-0003"}})
    b.record_one({"type": "question.asked", "by": "agent", "prov": "observado", "source": "chat",
                  "data": {"text": "Qual é o e-mail da Marina?", "options": [], "context": [], "kind": "identidade", "run": "teste"}})
    return b


def _compiled_js(name: str) -> str:
    html = (ASSETS / name).read_text(encoding="utf-8")
    return html.split("<script>", 1)[1].rsplit("</script>", 1)[0]


_NODE = r"""
const fs = require("fs");
const vm = require("vm");
const baseModel = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const compiledJs = fs.readFileSync(process.argv[3], "utf8");
const richText = fs.readFileSync(process.argv[4], "utf8");
const fourText = fs.readFileSync(process.argv[5], "utf8");
const raf = [], clicks = [];

function boot(model, jsSrc) {
  const els = new Map(), store = {}, timers = [];
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
      innerHTML: "", textContent: "", value: "", hidden: false,
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
  // corpo recolhido: 100px do topo; o rótulo da 4ª seção começa em 420 → o corte fica logo antes dele
  const fitStub = { offsetTop: 100, style: {}, querySelectorAll: () => [{ offsetTop: 120 }, { offsetTop: 200 }, { offsetTop: 300 }, { offsetTop: 420 }] };
  const doc = {
    getElementById(id) {
      if (id === "data") return { textContent: JSON.stringify(model) };
      if (els.has(id)) return els.get(id);
      return makeEl(id, "DIV");
    },
    querySelector(sel) {
      if (sel === "#daily-brief .brief-body.is-clamped:not(.is-open)") return fitStub;
      if (sel === ".pal-back.open" || sel === ".dd.open") return null;
      if (sel.startsWith("#")) return doc.getElementById(sel.slice(1));
      return makeEl("", "DIV");
    },
    querySelectorAll() { return []; },
    addEventListener(type, fn) { if (type === "click") clicks.push(fn); },
    removeEventListener() {},
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
    requestAnimationFrame(fn) { raf.push(fn); return raf.length; },
    URLSearchParams,
    CustomEvent: function(name, opts) { this.type = name; this.detail = opts && opts.detail; },
  };
  win.window = win;
  win.globalThis = win;
  vm.runInNewContext(jsSrc, win);
  const flush = () => { while (timers.length) timers.shift()(); };
  return { BRAIN: win.BRAIN, win, view, fitStub, flush };
}

const c = boot(baseModel, compiledJs);
function card(text, briefOver, modelOver) {
  const m = JSON.parse(JSON.stringify(baseModel));
  Object.assign(m.daily_brief, { exists: true, is_today: true, date: "2026-10-09", generated_at: "2026-10-09T10:00:00-03:00", empty: false, text: text }, briefOver || {});
  // saúde fixa: a que o doctor tira desta máquina (setup, PATH, launchd) não é do renderizador e muda de máquina pra máquina
  Object.assign(m, { health: [{ level: "ok", title: "ledger ok", detail: "", fix: "" }, { level: "warn", title: "goals.md sem entregáveis", detail: "Cadastre o primeiro goal.", fix: "Cadastre o primeiro goal." }] }, modelOver || {});
  c.BRAIN.refresh(m);
  c.flush();
  c.fitStub.style = {};
  raf.length = 0;
  const h = c.BRAIN.V.home();
  while (raf.length) raf.shift()();
  const i = h.indexOf('id="daily-brief"');
  return { html: h.slice(h.lastIndexOf("<section", i), h.indexOf("</section>", i) + 10), fitMax: c.fitStub.style.maxHeight || "", notes: notesIn(h) };
}

const notesIn = h => Array.from(h.matchAll(/<details class="panel note"><summary><b>Nota do agente · ([^<]+)<\/b>[^<]*<span[^>]*>[^<]*<\/span><\/summary><div class="msg"><div class="brief-body">([\s\S]*?)<\/div><\/div><\/details>/g)).map(m => ({ name: m[1], body: m[2] }));
const out = {};
out.rich = card(richText);
out.many = card("## A\n- TASK-0001, TASK-0005 e TASK-0002").html;
out.uniform = card("## A\n- TASK-0001 e TASK-0005").html;
out.nonUniform = card("## A\n- TASK-0001 e TASK-0002").html;
out.refs = card("## A\n- Avançou TASK-0004 (ver TASK-0001), TASK-0042 não consta. `TASK-0002` segue.\n- revisar (TASK-0001) hoje").html;
out.xss = card('<script>alert(1)</script>\n\n- [x](javascript:alert(1)) e ![i](https://evil.invalid/x.png)\n- <a href="x" onmouseover="y">z</a> · [t](data:text/html,1) · <img src=x onerror=1>\n- https://evil.invalid/a"onmouseover="b e [ok](https://ok.invalid/p?q=1).\n- TASK-0001"onmouseover="x').html;
out.md = card("### B\n1. um\n2. dois\n- **n** e *i* e _u_\n> cita\n---\nfim\nparágrafo\nlinha 2").html;
out.nested = card("## A\n- pai\n  - filho 1\n  - filho 2\n  1. passo\n- irmão\n- último").html;
out.clamp4 = card(fourText);
out.clamp3 = card("## A\n- x\n## B\n- y\n## C\n- z");
out.titleOnly = card("# Brief do dia — 09/10/2026 (noturno)\n\n");
out.emptySection = card("## A\n\n## B\n- x\n## C\n\n## D\n## E\n- y");
out.stale = card("", { is_today: false, exists: true });
out.weekNote = card("## A\n- x", null, { notes: [{ name: "semana", text: "## Destaques\n- Fechada TASK-0006; decisão DEC-0001\n<script>1</script>", kind: "week" }] }).notes;
out.healthOne = card("## A\n- x").html;
out.healthNone = card("## A\n- x", null, { health: [{ level: "ok", title: "ledger ok", detail: "", fix: "" }] }).html;
out.healthDup = card("## A\n- x", null, { health: [{ level: "warn", title: "mesmo aviso", detail: "1", fix: "" }, { level: "error", title: "mesmo aviso", detail: "2", fix: "" }] }).html;
out.healthTwo = card("## A\n- x", null, { health: [{ level: "warn", title: "aviso um", detail: "", fix: "" }, { level: "warn", title: "aviso dois", detail: "", fix: "" }] }).html;
out.whenDate = card("## A\n- x", { generated_at: "" }).html;

// "Mostrar tudo": abre, fecha (re-corta na 4ª seção) e o brief que o dono abriu continua aberto no re-render
const body = { offsetTop: 100, style: {}, classList: { n: 0, toggle() { this.n++; return this.n % 2 === 1; } },
  querySelectorAll: () => [{ offsetTop: 120 }, { offsetTop: 200 }, { offsetTop: 300 }, { offsetTop: 420 }] };
const btn = { attrs: { "data-n": "4", "data-key": "2026-10-09T10:00:00-03:00" }, parts: [],
  parentNode: { querySelector: () => body }, getAttribute(k) { return this.attrs[k]; }, setAttribute(k, v) { this.attrs[k] = v; },
  append(...xs) { this.parts.push(...xs); } };
btn.textContent = "Mostrar tudo";
out.toggle = [];
const click = () => { btn.parts = []; clicks.forEach(fn => fn({ target: { closest: sel => (sel === ".bd-more" ? btn : null) } })); };   // textContent = "" esvazia o botão real
click();
out.toggle.push({ max: body.style.maxHeight, aria: btn.attrs["aria-expanded"], parts: btn.parts.map(p => (typeof p === "string" ? p : p.className + ":" + p.textContent)) });
click();
out.toggle.push({ max: body.style.maxHeight, aria: btn.attrs["aria-expanded"], parts: btn.parts.map(p => (typeof p === "string" ? p : p.className + ":" + p.textContent)) });
click();
out.persist = card(fourText).html;
console.log(JSON.stringify(out));
"""


class PanelBriefRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node ausente no ambiente")
        with tempfile.TemporaryDirectory() as td:
            b = _demo_brain(Path(td) / "inst")
            notes.write_note(b, "brief", _RICH, kind="brief", empty=False)
            render.render_all(b, do_harvest=False)
            render.render_all(b, do_harvest=False)
            model = render.view_model(b)
            model["onboarding"] = {"needed": False}
            paths = [Path(td) / n for n in ("m.json", "panel.js", "run.js", "rich.md", "four.md")]
            paths[0].write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
            paths[1].write_text(_compiled_js("dashboard.html"), encoding="utf-8")
            paths[2].write_text(_NODE, encoding="utf-8")
            paths[3].write_text(_RICH, encoding="utf-8")
            paths[4].write_text(_FOUR, encoding="utf-8")
            proc = subprocess.run([node, str(paths[2]), str(paths[0]), str(paths[1]), str(paths[3]), str(paths[4])],
                                  capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise AssertionError("node falhou:\n" + proc.stderr[-2000:])
        cls.o = json.loads(proc.stdout.strip().splitlines()[-1])

    # ── o que renderiza ──────────────────────────────────────────────────────────
    def test_secoes_enfases_codigo_e_lista(self):
        h = self.o["md"]
        self.assertIn('<div class="bd-h4">B</div><ol class="bd-ol"><li class="bd-li">um</li><li class="bd-li">dois</li></ol>'
                      '<ul class="bd-ul"><li class="bd-li"><strong>n</strong> e <em>i</em> e <em>u</em></li></ul>'
                      '<blockquote class="bd-quote">cita</blockquote><hr class="bd-hr"><p>fim<br>parágrafo<br>linha 2</p>', h)
        text = re.sub(r"<[^>]+>", "", h)                                           # o que o dono lê: sem sintaxe sobrando
        for raw in ("###", "**", "_u_", "&lt;", "> cita"):
            self.assertNotIn(raw, text)
        n = self.o["nested"]                                                       # sublista nasce dentro do item pai; voltar um nível fecha a sublista, não o pai
        self.assertIn('<ul class="bd-ul"><li class="bd-li">pai<ul class="bd-ul bd-sub"><li class="bd-li">filho 1</li><li class="bd-li">filho 2</li>'
                      '</ul><ol class="bd-ol bd-sub"><li class="bd-li">passo</li></ol></li><li class="bd-li">irmão</li><li class="bd-li">último</li></ul>', n)

    def test_html_do_cartao_e_balanceado(self):
        for name, html in self._cards().items():
            with self.subTest(card=name):
                stack, void = (["div"] if ":nota:" in name else []), {"br", "hr"}   # corpo de nota é fragmento: mora dentro do <div class="brief-body">
                for tag in re.findall(r"<(/?)([a-z0-9]+)\b[^>]*>", html):
                    closing, el = tag[0] == "/", tag[1]
                    if el in void:
                        continue
                    parent = stack[-1] if stack else None
                    if closing:
                        self.assertTrue(stack and stack[-1] == el, f"</{el}> sem abertura correspondente em {name} (pilha {stack})")
                        stack.pop()
                    else:
                        self.assertFalse(el == "li" and parent not in ("ul", "ol"), f"<li> solto dentro de <{parent}> em {name}")
                        self.assertFalse(el in ("ul", "ol") and parent not in ("li", "div"), f"<{el}> dentro de <{parent}> em {name}")
                        stack.append(el)
                self.assertEqual(stack, ["div"] if ":nota:" in name else [], f"tags abertas em {name}: {stack}")

    def test_notas_do_agente_mesmo_renderizador_e_brief_sem_duplicata(self):
        self.assertEqual(self.o["rich"]["notes"], [])                      # o brief de hoje mora no cartão "Seu dia": não repete logo abaixo
        stale = self.o["stale"]["notes"]                                   # brief de outro dia: o cartão fica quieto, então ele continua legível aqui — formatado
        self.assertEqual([n["name"] for n in stale], ["brief"])
        self.assertIn('<div class="bd-h">Hoje</div>', stale[0]["body"])
        self.assertNotIn("Brief do dia", stale[0]["body"])
        week = self.o["weekNote"]                                          # qualquer nota do agente (/week) passa pelo mesmo caminho seguro
        self.assertEqual([n["name"] for n in week], ["semana"])
        self.assertIn('<div class="bd-h">Destaques</div><ul class="bd-ul"><li class="bd-li">Fechada <span class="bd-nb"><a class="bd-tag bd-tag-m is-done" href="#action/TASK-0006"', week[0]["body"])
        self.assertRegex(week[0]["body"], r'<a class="bd-tag[^"]*" href="#decision/DEC-0001"')
        self.assertIn("&lt;script&gt;1&lt;/script&gt;", week[0]["body"])
        self.assertNotIn("<script", week[0]["body"])

    def _cards(self) -> dict:
        """Todo fragmento que sai do renderizador do brief: cartões e corpos de nota (o teste de equilíbrio passa por todos)."""
        out = {}
        for k, v in self.o.items():
            if isinstance(v, str):
                out[k] = v
            elif isinstance(v, dict) and "html" in v:
                out[k] = v["html"]
                out.update({f"{k}:nota:{n['name']}": n["body"] for n in v.get("notes", [])})
        return out

    def test_secao_vazia_nao_aparece_nem_conta_para_recolher(self):
        c = self.o["emptySection"]
        self.assertIn('<div class="bd-h">B</div><ul class="bd-ul"><li class="bd-li">x</li></ul><div class="bd-h">E</div><ul class="bd-ul"><li class="bd-li">y</li></ul></div>', c["html"])
        for gone in (">A</div>", ">C</div>", ">D</div>"):
            self.assertNotIn(gone, c["html"])
        self.assertNotIn("bd-more", c["html"])                               # 2 seções de verdade: não recolhe
        self.assertEqual(c["fitMax"], "")

    def test_titulo_solto_e_noturno_nao_aparecem(self):
        h = self.o["rich"]["html"]
        self.assertNotIn("Brief do dia", h)
        self.assertNotIn("noturno", h)
        self.assertIn('<div class="bd-h">Hoje</div>', h)
        self.assertIn("atualizado 10:00", h)

    def test_acao_vira_etiqueta_com_titulo_e_situacao_do_modelo(self):
        h = self.o["rich"]["html"]
        self.assertRegex(h, r'<a class="bd-tag is-soon" href="#action/TASK-0003" title="[^"]*Enviar orçamento[^"]*"><code class="idchip">TASK-0003</code>'
                         r'<span class="bd-tag-t">Enviar orçamento</span><span class="chip bd-tag-s h-atencao">vence hoje · com Caio Demo</span></a>')
        self.assertIn('<a class="bd-tag bd-tag-m is-late" href="#action/TASK-0002" title="Ligar para o fornecedor · alta · atrasada 3d">', h)
        self.assertIn('<span class="chip bd-tag-s h-em-risco">alta · atrasada 3d</span>', h)
        self.assertIn('<code class="bd-code">brain render</code>', h)
        self.assertIn('<a href="#person/caio-demo">Caio</a>', h)                    # pessoa do painel: link para a ficha
        self.assertRegex(h, r'<a class="bd-tag is-done" href="#action/TASK-0006"[^>]*>.*?<span class="chip bd-tag-s h-concluido">fechada</span></a>')

    def test_demais_entidades(self):
        h = self.o["rich"]["html"]
        self.assertIn('<a class="bd-tag bd-tag-m" href="#decision/DEC-0001" title="Trocar a farinha"><code class="idchip">DEC-0001</code>'
                      '<span class="bd-tag-t">Trocar a farinha</span></a>', h)
        self.assertIn('<a class="bd-tag bd-tag-m" href="#decision/DEC-0002" title="Fornada dupla"><code class="idchip">DEC-0002</code>'
                      '<span class="bd-tag-t">Fornada dupla</span></a>', h)
        self.assertIn('<a class="bd-tag bd-tag-m is-prop" href="#ask" title="TASK-0001 duplica TASK-0003"><code class="idchip">PROP-0001</code>'
                      '<span class="bd-tag-t">proposta · descartar ação</span><span class="chip bd-tag-s h-atencao">aguarda decisão</span></a>', h)
        self.assertIn('<a class="bd-tag bd-tag-m is-ask" href="#ask" title="Qual é o e-mail da Marina?"><code class="idchip">ASK-0001</code>'
                      '<span class="bd-tag-t">pergunta</span><span class="chip bd-tag-s h-info">aberta</span></a>', h)
        self.assertIn('href="#projects?focus=GOAL-1"', h)
        self.assertIn('<span class="bd-tag-t">Padaria previsível</span>', h)
        self.assertRegex(h, r'href="#project/PROJ-1"[^>]*><code class="idchip">PROJ-1\.1</code><span class="bd-tag-t">Ajustar escala</span><span class="chip bd-tag-s">[a-z]{3} 15/11</span>')
        self.assertIn('href="#wins"', h)
        self.assertIn('<code class="idchip">MSG-0009</code>', h)                     # o painel não conhece: chip comum, sem link
        self.assertNotIn('href="#outbox"', h)

    def test_varias_entidades_duas_por_linha_e_virgula_orfa_some(self):
        h = self.o["many"]
        self.assertIn('</a></span> <span class="bd-nb"><a class="bd-tag bd-tag-m" href="#action/TASK-0005"', h)
        self.assertIn('</a></span> e <span class="bd-nb"><a class="bd-tag bd-tag-m is-late" href="#action/TASK-0002"', h)
        self.assertNotIn("</a></span>,", h)

    def test_situacao_igual_em_todas_nao_repete(self):
        self.assertIn('<a class="bd-tag bd-tag-m" href="#action/TASK-0001" title="Ajustar escala · sem prazo"><code class="idchip">TASK-0001</code><span class="bd-tag-t">Ajustar escala</span></a>', self.o["uniform"])
        self.assertNotIn("bd-tag-s", self.o["uniform"])
        self.assertIn('<span class="chip bd-tag-s">sem prazo</span>', self.o["nonUniform"])

    def test_referencia_entre_parenteses_e_chip_curto(self):
        h = self.o["refs"]
        self.assertIn('<span class="bd-nb"><a class="bd-id" href="#action/TASK-0001" title="Ajustar escala · sem prazo"><code class="idchip">TASK-0001</code></a>),</span>', h)
        self.assertIn('revisar <span class="bd-nb">(<a class="bd-id" href="#action/TASK-0001"', h)
        self.assertIn("</a>)</span> hoje", h)
        self.assertIn('<span class="bd-nb"><code class="idchip">TASK-0042</code></span>', h)
        self.assertIn('<span class="bd-nb"><a class="bd-tag bd-tag-m is-late" href="#action/TASK-0002"', h)   # id entre crases continua sendo etiqueta

    def test_brief_longo_abre_recolhido_e_o_corte_cai_na_4a_secao(self):
        four, three = self.o["clamp4"], self.o["clamp3"]
        self.assertIn('brief-body is-clamped">', four["html"])
        self.assertIn('aria-expanded="false" data-n="4"', four["html"])
        self.assertIn("Mostrar tudo<span class=\"bd-more-n\">4 seções</span> ▾", four["html"])
        self.assertEqual(four["fitMax"], "313px")                                   # 420 (4º rótulo) − 100 (corpo) − 7
        self.assertNotIn("is-clamped", three["html"])
        self.assertNotIn("bd-more", three["html"])
        self.assertEqual(three["fitMax"], "")

    def test_mostrar_tudo_abre_fecha_e_persiste_no_re_render(self):
        opened, closed = self.o["toggle"]
        self.assertEqual((opened["max"], opened["aria"], opened["parts"]), ("none", "true", ["Mostrar menos"]))
        self.assertEqual((closed["max"], closed["aria"]), ("313px", "false"))
        self.assertEqual(closed["parts"], ["Mostrar tudo", "bd-more-n:4 seções", " ▾"])
        self.assertIn('brief-body is-clamped is-open">', self.o["persist"])
        self.assertIn('aria-expanded="true"', self.o["persist"])
        self.assertIn(">Mostrar menos</button>", self.o["persist"])

    def test_estados_sem_brief(self):
        t = self.o["titleOnly"]["html"]
        self.assertIn("is-quiet", t)
        self.assertIn('<p class="brief-quiet">Sem novidades desde a última atualização.</p>', t)
        s = self.o["stale"]["html"]
        self.assertIn("Sem novidades ainda hoje — o resumo do dia aparece após a rotina. Último resumo: ", s)
        self.assertNotIn('brief-when">atualizado', s)

    def test_avisos_de_saude_vem_do_modelo_e_vao_para_a_pagina_de_saude(self):
        self.assertIn('<a class="bd-hl" href="#cfg/saude" title="goals.md sem entregáveis: Cadastre o primeiro goal.">⚠ 1 aviso de saúde</a>', self.o["healthOne"])
        self.assertNotIn("bd-hl", self.o["healthNone"])
        self.assertIn("⚠ 1 aviso de saúde", self.o["healthDup"])
        self.assertIn("⚠ 2 avisos de saúde", self.o["healthTwo"])
        self.assertIn('brief-when', self.o["whenDate"])
        self.assertIn("09/10", self.o["whenDate"])
        self.assertNotIn("atualizado", self.o["whenDate"])                          # sem hora: só a data do brief

    # ── o que NUNCA entra ────────────────────────────────────────────────────────
    def test_brief_e_texto_nao_confiavel(self):
        h = self.o["xss"]
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", h)
        self.assertIn("&lt;a href=&quot;x&quot; onmouseover=&quot;y&quot;&gt;z&lt;/a&gt;", h)
        self.assertIn("&lt;img src=x onerror=1&gt;", h)                           # tag do texto vira texto visível, nunca elemento
        for forbidden in ("<script", "<img", 'href="javascript:', 'href="data:', "<a href=\"x"):
            self.assertNotIn(forbidden, h)                                         # "href=…" só existe em tag do renderizador
        for tag in re.findall(r"<[^>]+>", h):                                      # nenhuma tag carrega atributo vindo do texto
            self.assertNotRegex(tag, r"\son[a-z]+=", tag)
            self.assertNotIn("src=", tag)
            self.assertNotIn("javascript:", tag)
        self.assertIn('href="https://ok.invalid/p?q=1" target="_blank" rel="noopener noreferrer">ok</a>.', h)
        self.assertIn('href="https://evil.invalid/a" target="_blank" rel="noopener noreferrer">https://evil.invalid/a</a>&quot;onmouseover=&quot;b', h)
        self.assertIn("&quot;onmouseover=&quot;x", h)                              # id citado + atributo colado: o que sobra é texto

    def test_atributo_do_modelo_e_escapado(self):
        self.assertIn('title="Revisar &quot;contrato&quot; &lt;rascunho&gt; · em 3d"', self.o["refs"])      # aspas e < > do título não viram atributo/tag

    # ── fonte e asset compilado ──────────────────────────────────────────────────
    def test_css_do_brief_e_structura_nao_pre_wrap(self):
        css = (ROOT / "brainlib/assets/src/dashboard.css").read_text(encoding="utf-8")
        self.assertNotIn(".brief-body{white-space:pre-wrap", css)
        for rule in (".bd-tag{", "a.bd-id{", ".bd-tag-m{", ".brief-when{", "a.bd-hl{", ".brief-body.is-clamped{", ".bd-more{", ".bd-h{", ".bd-code{"):
            self.assertIn(rule, css)
        mobile = css.split("@media (max-width:640px){", 1)[1].split("\n}", 1)[0]
        self.assertIn(".bd-tag-m{max-width:100%}", mobile)

    def test_assets_compilados_contem_o_renderizador(self):
        for name in ("dashboard.html", "portfolio.html"):
            js = _compiled_js(name)
            self.assertIn("function briefHtml(", js)
            self.assertIn("bd-tag-m", js)
            self.assertIn("function renderDailyBrief(", js)

    def test_skills_definem_o_formato_do_brief(self):
        brief = (ROOT / "commands/brief/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("note write brief --file", brief)
        self.assertIn("sem linha de título", brief)
        self.assertIn("noturno", brief)
        update = (ROOT / "commands/update/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("commands/brief/SKILL.md", update)
        self.assertIn("note write brief --file", update)


if __name__ == "__main__":
    unittest.main()
