"""Formulários: uma especificação (brainlib/forms.py), duas pontas (TUI e painel) — e nada de divergir.

Trava três coisas:
1. **Ninguém escreve campo à mão numa ponta só.** A TUI só abre formulário por `open_form("<id>")` e o painel só por
   `openForm("<id>")`; `Field(`/`FormSpec(` fora do adaptador e `formDialog({… fields: [` no JS são recusados.
2. **Toda especificação tem as duas pontas** (ou está marcada `where="tui"`/`"panel"` com o porquê).
3. **O mesmo valor vira o mesmo comando.** Para cada formulário, com valores de exemplo, o Python (`forms.build`) e o
   JS (`formArgv`, rodado no node) montam a MESMA linha; o mesmo vale para obrigatório/validação (`missing`), dicas,
   valor inicial e listas de escolha. Sem node, a parte 3 é pulada (as outras não).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

from brainlib import config, forms, render  # noqa: E402
from brainlib import demo as demo_mod  # noqa: E402
from brainlib.core import Brain  # noqa: E402

TUI_FILES = ("app.py", "store.py", "portfolio_keys.py", "config_keys.py", "ask_keys.py", "feedback_keys.py")
JS = ROOT / "brainlib" / "assets" / "src"


def _tui_src() -> str:
    return "".join((ROOT / "brainlib" / "tui" / f).read_text(encoding="utf-8") for f in TUI_FILES)


def _js_src() -> str:
    return "".join((JS / f).read_text(encoding="utf-8") for f in ("extra.js", "core.js"))


class SingleSourceTest(unittest.TestCase):
    def test_tui_has_no_hand_written_fields(self):
        """Field(...) só no adaptador `open_form` (app.py) e no próprio modals.py."""
        src = _tui_src()
        calls = [m.start() for m in re.finditer(r"\bField\(", src)]
        self.assertEqual(len(calls), 1, "a TUI declara campo fora do forms.py (use open_form)")
        self.assertEqual(len(re.findall(r"\bFormSpec\(", src)), 1, "FormSpec só no adaptador open_form")

    def test_panel_has_no_hand_written_fields(self):
        src = _js_src()
        self.assertNotRegex(src, r"\bfields:\s*\[", "o painel declara campo fora do forms.py (use openForm)")
        self.assertNotRegex(src, r"formDialog\(\{", "formDialog com campos à mão: use openForm(\"<id>\")")

    def test_every_form_has_both_ends(self):
        tui, js = _tui_src(), _js_src()
        for fid, fm in forms.FORMS.items():
            in_tui = re.search(r'open_form\(\s*["\']' + re.escape(fid) + r'["\']', tui) is not None
            in_js = re.search(r'openForm\(\s*["\']' + re.escape(fid) + r'["\']', js) is not None
            if fm.where == "both":
                self.assertTrue(in_tui and in_js, f"{fid}: TUI={in_tui} painel={in_js} — as duas pontas abrem o formulário")
            else:
                self.assertTrue(fm.why, f"{fid}: só numa ponta precisa do porquê (Form.why)")
                self.assertTrue(in_tui if fm.where == "tui" else in_js, f"{fid}: a ponta {fm.where} não o abre")
                self.assertFalse(in_js if fm.where == "tui" else in_tui, f"{fid}: marcado {fm.where}, mas a outra ponta abre")

    def test_named_rules_exist_on_both_sides_or_are_justified(self):
        """Todo nome de validação/dica/transformação/fonte usado na especificação existe no Python e no JS (ou em PY_ONLY)."""
        js = (JS / "forms.js").read_text(encoding="utf-8")
        used = {"check": set(), "hint": set(), "xf": set(), "source": set(), "pred": set(), "init": set()}
        for fm in forms.FORMS.values():
            for f in fm.fields:
                if f.check:
                    used["check"].add(f.check.split(":")[0])
                if f.hint:
                    used["hint"].add(f.hint)
                if f.xf:
                    used["xf"].add(f.xf)
                for s in (f.choices, f.suggest):
                    if isinstance(s, str):
                        used["source"].add(s.lstrip("@"))
                if isinstance(f.show, str):
                    used["pred"].add(f.show)
                for spec in (f.init, f.base):
                    if spec and not spec.startswith("@") and ":" in spec:
                        used["init"].add(spec.split(":", 1)[1])
            used["pred"] |= {p for p, _ in fm.more}
        py = {"check": set(forms.CHECKS) | {"int"}, "hint": set(forms.HINTS), "xf": set(forms.XF),
              "source": set(forms.SOURCES), "pred": set(forms.PRED), "init": set(forms.INIT) | set(forms.IFMT)}
        for kind, names in used.items():
            for n in sorted(names):
                self.assertIn(n, py[kind], f"{kind} {n!r}: falta no forms.py")
                if f"{kind}:{n}" in forms.PY_ONLY:
                    continue
                if kind == "check" and n == "int":
                    continue
                hit = re.search(r'(?:^|[\s{,])(?:"' + re.escape(n) + r'"|' + re.escape(n) + r')\s*:', js, re.M)
                self.assertIsNotNone(hit, f"{kind} {n!r}: falta no forms.js (ou justifique em forms.PY_ONLY)")

    def test_gates_never_prefill_approval(self):
        """Silêncio não é aprovação: campo de aprovação literal nunca vem preenchido (e é obrigatório)."""
        for fm in forms.FORMS.values():
            for f in fm.fields:
                if f.id == "quote" or f.arg in ("--approval", "--quote"):
                    self.assertTrue(f.req, f"{fm.id}.{f.id}: aprovação obrigatória")
                    self.assertFalse(f.value or f.init, f"{fm.id}.{f.id}: aprovação não vem preenchida")
        js = _js_src()
        self.assertNotRegex(js, r"--approval \"ok\"|--approval ok\b", "o painel não aprova por você")

    def test_dynamic_sources_never_empty(self):
        """Cardápio dinâmico com depends fora da tabela (ex.: modo none) cai no default — o Select
        do FormModal exige opções (regressão 2.20.1: IndexError no compose do memory.mode)."""
        f = forms.F("embeddings", "embeddings", choices="@memory_embs", depends="mode")
        m = {"form_static": forms.static()}
        for mode, first in (("full", "fireworks"), ("embed", "local"), ("none", "local"), ("", "local")):
            opts = forms.options(f, m, {"mode": mode})
            self.assertTrue(opts, f"modo {mode!r}: cardápio vazio")
            self.assertEqual(opts[0][0], first)


def _ctx_for(m: dict) -> dict[str, dict]:
    """Um contexto realista por formulário, tirado do view model da demo (o mesmo que as pontas montam)."""
    act = next(a for a in m["actions"] if a["open"] and a["project"])
    closed = next(a for a in m["actions"] if not a["open"])
    goal, proj = m["goals"][0], next(p for p in m["projects"] if p["deliverables"])
    deliv = proj["deliverables"][0]
    pe = next(p for p in m["people"] if not p["is_owner"])
    pf = m["portfolio"]
    opp, proc, area = pf["opportunities"][0], pf["processes"][0], pf["areas"][0]
    dec = m["decisions"][0] if m["decisions"] else {"id": "DEC-0001", "title": "x"}
    src = next((s for s in m["sources"] if s.get("kind") == "jira"), m["sources"][0])
    return {
        "goal.new": {"nid": "GOAL-9"},
        "project.new": {"nid": "PROJ-9", "goal": goal["id"], "goal_title": goal["title"]},
        "deliverable.new": {"nid": proj["id"] + ".9", "project": proj["id"], "project_title": proj["title"]},
        "goal.edit": {"id": goal["id"], "item": goal},
        "project.edit": {"id": proj["id"], "item": proj},
        "deliverable.edit": {"id": deliv["id"], "item": deliv},
        "deliverable.done": {"id": deliv["id"], "title": deliv["title"], "item": deliv},
        "deliverable.state": {"id": deliv["id"], "title": deliv["title"], "item": deliv},
        "progress.declare": {"id": goal["id"]},
        "share.export": {"kind": "project", "target": proj["id"]},
        "action.new": {"list": "waiting", "owner": "", "project": proj["id"], "item": {"project": proj["id"]}},
        "action.edit": {"id": act["id"], "title": act["title"], "item": act},
        "action.close": {"id": act["id"], "title": act["title"], "item": act},
        "action.due": {"id": act["id"], "title": act["title"], "item": act, "due_sub": "Deixe em branco para remover o prazo."},
        "action.drop": {"id": act["id"], "title": act["title"], "item": act},
        "action.merge": {"id": act["id"], "title": act["title"], "item": act},
        "action.reopen": {"id": closed["id"], "title": closed["title"], "item": closed},
        "note.add": {"link": act["id"], "text": ""},
        "proposal.accept": {"id": "PROP-0001", "summary": "fechar", "kind": "fechar-acao", "target": act["id"], "into": ""},
        "proposal.reject": {"id": "PROP-0001", "summary": "fechar"},
        "ask.answer": {"id": "ASK-0001", "text": "Quem é a Lu?", "item": {"options": ["Lu Martins", "outra"]}},
        "ask.drop": {"id": "ASK-0001", "text": "Quem é a Lu?"},
        "outbox.draft": {"to": pe["id"], "text": "Oi", "ref": act["id"], "why": "prazo"},
        "outbox.approve": {"id": "MSG-0003", "to_name": pe["name"], "n": "3"},
        "outbox.cancel": {"id": "MSG-0003", "text": "Oi"},
        "focus.plan": {"days": "7"}, "focus.approve": {"id": "FOCUS-0001"}, "focus.apply": {"id": "FOCUS-0001", "mode": "google"},
        "publish.approve": {"id": "PUB-0001", "report": "reports/share/x.html", "destination": "slack:#seu-canal"},
        "decision.supersede": {"id": dec["id"], "title": dec["title"]},
        "person.edit": {"id": pe["id"], "item": pe}, "person.alias": {"id": pe["id"]},
        "process.edit": {"id": proc["id"], "item": proc}, "process.retire": {"id": proc["id"], "title": proc["title"]},
        "opportunity.new": {"item": {"area": area["id"], "process": proc["id"]}},
        "opportunity.edit": {"id": opp["id"], "item": opp},
        "opportunity.status": {"id": opp["id"], "title": opp["title"], "item": opp},
        "opportunity.score": {"id": opp["id"], "item": opp, "ice_reason": ""},
        "opportunity.evidence": {"id": opp["id"]},
        "opportunity.promote": {"id": opp["id"], "item": opp},
        "area.edit": {"id": area["id"], "item": area},
        "doc.link": {"target": proc["id"], "target_fixed": True},
        "doc.unlink": {"target": proc["id"], "ref": "https://example.com/x", "doc_title": "x"},
        "watch.add": {},
        "watch.edit": {"key0": src["key"], "item": src},
        "watch.remove": {"key": src["key"]},
        "memory.provider": {"provider": "local"},
    }


SAMPLES = {   # por validação: valores que exercitam o ok, o erro e a transformação
    "date": ["", "amanhã", "sex", "+3d", "20/10", "2026-12-01", "ontem"],
    "duration": ["", "90m", "1h30", "2h", "1d", "abc"], "duration_pos": ["", "45m", "0m", "x"],
    "num": ["", "3", "2,5", "0", "x"], "slug": ["", "growth", "Bad Slug"], "watch_key": ["", "nova-fonte", "Ruim!"],
    "drive": ["", "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit", "1AbCdEfGhIjKlMnOp", "nada"],
    "jira": ["", "OPS-12", "https://acme.atlassian.net/browse/OPS-12", "https://acme.atlassian.net/jira/software/projects/OPS/boards/3", "?"],
    "pairs": ["", "a=1; b=2", "ruim"], "deliv": ["", "1", "99", "PROJ-1.1", "PROJ-77.1"],
    "merge_into": ["", "TASK-0003", "TASK-0001", "TASK-9999"], "proc": ["", "PROC-0001", "PROC-9999"],
    "goal": ["", "GOAL-1", "GOAL-99"], "note_link": ["", "TASK-0002", "goal-1", "PROJ-1.1", "TASK-9999", "lixo"],
    "no_dot": ["", "Bom", "Ruim · título"], "doc_watch": ["não", "sim"], "fb_dup": ["", "Título novo"],
    "opp_status": ["ideia", "em-andamento"],
}
TEXT = ["", "Algo com espaço", "PROJ-1, x"]


def _cases(m: dict, ctxs: dict) -> list[dict]:
    out = []
    for fid, fm in forms.FORMS.items():
        if fm.where == "tui":
            continue
        ctx = ctxs.get(fid, {})
        init = forms.initial(fm, ctx, m)
        out.append({"form": fid, "ctx": ctx, "raw": dict(init)})
        for f in fm.fields:
            if f.choices is not None:
                vals = [o[0] for o in forms.options(f, m, init, ctx)]
            elif f.check:
                vals = SAMPLES.get(f.check.split(":")[0], ["", "1", "0", "200", "x"] if f.check.startswith("int") else TEXT)
            elif f.suggest:
                vals = [""] + [o[0] for o in forms.options(f, m, init, ctx)][:2] + ["eu"]
            else:
                vals = TEXT
            for val in vals:
                out.append({"form": fid, "ctx": ctx, "raw": {**init, f.id: val}})
    # combinações que importam: tipo da fonte × campos do tipo; nível da promoção; lista × dono
    for kind, _ in [tuple(k) for k in m["source_kinds"]]:
        for jscope in ("mine", "epic", "jql"):
            for mode in ("", "state"):
                raw = {**forms.initial(forms.FORMS["watch.add"], {}, m), "key": "k1", "kind": kind, "jscope": jscope,
                       "jref": "https://acme.atlassian.net/browse/OPS-12", "mode": mode, "channel": "#c", "doc": "1AbCdEfGhIjKlMnOp",
                       "folder": "1AbCdEfGhIjKlMnOp", "path": "~/g", "window": "7d", "note": "n", "other": "x=1"}
                out.append({"form": "watch.add", "ctx": {}, "raw": raw})
                ctx = ctxs["watch.edit"]
                out.append({"form": "watch.edit", "ctx": ctx, "raw": {**forms.initial(forms.FORMS["watch.edit"], ctx, m), **raw}})
    for lst in ("mine", "waiting", "watching"):
        for owner in ("", "eu", "marina-demo"):
            for fid in ("action.new", "action.edit"):
                ctx = ctxs[fid]
                out.append({"form": fid, "ctx": ctx, "raw": {**forms.initial(forms.FORMS[fid], ctx, m), "list": lst, "owner": owner,
                                                             "goal": "—", "project": "PROJ-1", "deliv": "1", "due": "sex"}})
    for level in ("project", "deliverable", "goal"):
        ctx = ctxs["opportunity.promote"]
        out.append({"form": "opportunity.promote", "ctx": ctx,
                    "raw": {**forms.initial(forms.FORMS["opportunity.promote"], ctx, m), "level": level, "quote": "ok"}})
    return out


def _py_eval(m: dict, cases: list[dict]) -> list[dict]:
    res = []
    for c in cases:
        fm = forms.FORMS[c["form"]]
        v = forms.values(fm, c["raw"], c["ctx"], m)
        res.append({
            "argv": forms.build(c["form"], c["raw"], c["ctx"], m),
            "missing": forms.missing(c["form"], c["raw"], c["ctx"], m),
            "hidden": sorted(forms.hidden(fm, {k: c["raw"].get(k, "") for k in v}, c["ctx"], m)),
            "hints": {f.id: forms.hint(f.hint, v[f.id], v, c["ctx"], m) for f in fm.fields
                      if f.hint and f"hint:{f.hint}" not in forms.PY_ONLY},
            "checks": {f.id: forms.check(f.check, v[f.id], v, c["ctx"], m) for f in fm.fields
                       if f.check and f"check:{f.check.split(':')[0]}" not in forms.PY_ONLY},
            "options": {f.id: [list(o) for o in forms.options(f, m, v, c["ctx"])] for f in fm.fields},
            "labels": [forms.label(f, m) for f in fm.fields],
            "title": forms.title(c["form"], c["ctx"]), "sub": forms.sub(c["form"], c["ctx"]),
            "initial": forms.initial(fm, c["ctx"], m), "display": forms.display(forms.build(c["form"], c["raw"], c["ctx"], m)),
        })
    return res


NODE_RUNNER = r"""
const F = require(process.argv[2]);
const fs = require("fs");
const {m, cases} = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const PY_ONLY = m.__py_only;
const out = cases.map(c => {
  const fm = m.forms[c.form], v = F.values(fm, c.raw, c.ctx, m), raw = {};
  Object.keys(v).forEach(k => { raw[k] = c.raw[k] === undefined || c.raw[k] === null ? "" : String(c.raw[k]); });
  const hints = {}, checks = {}, options = {};
  fm.fields.forEach(f => {
    if (f.hint && !PY_ONLY.includes("hint:" + f.hint)) hints[f.id] = F.hint(f.hint, v[f.id], v, c.ctx, m);
    if (f.check && !PY_ONLY.includes("check:" + f.check.split(":")[0])) checks[f.id] = F.check(f.check, v[f.id], v, c.ctx, m);
    options[f.id] = F.options(f, m, v, c.ctx);
  });
  const argv = F.formArgv(fm, c.raw, c.ctx, m);
  return {argv, missing: F.missing(fm, c.raw, c.ctx, m), hidden: [...F.hidden(fm, raw, c.ctx, m)].sort(), hints, checks, options,
          labels: fm.fields.map(f => F.label(f, m)), title: F.fmt(fm.title, c.ctx), sub: F.fmt(fm.sub, c.ctx),
          initial: F.initial(fm, c.ctx, m), display: F.display(argv)};
});
process.stdout.write(JSON.stringify(out));
"""


class CrossLanguageParityTest(unittest.TestCase):
    """Python × JS: os mesmos valores dão o mesmo comando, a mesma validação, as mesmas dicas e listas."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node ausente")
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name) / "inst"
        with contextlib.redirect_stdout(io.StringIO()):
            demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
        b = Brain(config.load(root))
        m = render.view_model(b)
        m["sources"] = m["sources"] + [   # fontes de exemplo (a demo não tem watch.toml)
            {"key": "jira-ops", "kind": "jira", "jql": "parent = OPS-1 AND updated >= -1d", "cloud": "acme.atlassian.net",
             "in_watch": True, "window": "7d", "extra_field": "x"},
            {"key": "slack-time", "kind": "slack", "channel": "#time", "in_watch": True, "note": "time"}]
        cls.m = json.loads(json.dumps(m, default=str))
        cls.cases = _cases(cls.m, _ctx_for(cls.m))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_both_panels_carry_the_forms(self):
        """index.html e portfolio.html recebem a especificação; o portfólio (que circula) sem reports/destinos."""
        from brainlib import render_portfolio
        self.assertEqual(set(self.m["forms"]), {k for k, f in forms.FORMS.items() if f.where != "tui"})
        pf = render_portfolio.html_payload(json.loads(json.dumps(self.m)))
        self.assertEqual(pf["forms"], self.m["forms"])
        self.assertNotIn("destinations", pf["form_static"])
        self.assertNotIn("reports", pf["form_static"])
        self.assertIn("re", pf["form_static"])

    def test_python_and_js_agree(self):
        data = Path(self.tmp.name) / "cases.json"
        data.write_text(json.dumps({"m": {**self.m, "__py_only": sorted(forms.PY_ONLY)}, "cases": self.cases},
                                   ensure_ascii=False), encoding="utf-8")
        runner = Path(self.tmp.name) / "run.js"
        runner.write_text(NODE_RUNNER, encoding="utf-8")
        r = subprocess.run([self.node, str(runner), str(JS / "forms.js"), str(data)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        js = json.loads(r.stdout)
        py = json.loads(json.dumps(_py_eval(self.m, self.cases)))
        self.assertEqual(len(js), len(py))
        diffs = []
        for c, a, b in zip(self.cases, py, js):
            for k in a:
                if a[k] != b[k]:
                    diffs.append(f"{c['form']} · {k}\n  raw={json.dumps(c['raw'], ensure_ascii=False)}\n"
                                 f"  py={json.dumps(a[k], ensure_ascii=False)}\n  js={json.dumps(b[k], ensure_ascii=False)}")
        self.assertEqual(diffs[:8], [], f"{len(diffs)} divergência(s) Python × JS em {len(self.cases)} casos")
        self.assertGreater(len(self.cases), 500)


if __name__ == "__main__":
    unittest.main()
