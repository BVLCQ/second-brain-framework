"""Autocompletar campos de formulário que referenciam entidades (#31) — mesclagem de ações e pessoas."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, forms, model  # noqa: E402
from brainlib.core import Brain  # noqa: E402

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None
JS_FORMS = ROOT / "brainlib" / "assets" / "src" / "forms.js"
JS_EXTRA = ROOT / "brainlib" / "assets" / "src" / "extra.js"


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n'
        '[outbound]\nallow = ["marina-demo", "sonia-demo", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Padaria\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Rotina da manhã\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Forno · prazo: 2026-10-20 · peso: 2\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Mari-demo"], "email": "marina-demo@x.com"}})
    b.record_one({"type": "person.added", "id": "sonia-demo", "by": "owner",
                  "data": {"name": "Sônia-demo", "aliases": ["Sonia-demo"], "email": "marina-demo@x.com"}})
    return b


class FilterOptionsTest(unittest.TestCase):
    ITEMS = [
        ("TASK-0001", "Assar a fornada"),
        ("TASK-0002", "Anotar encomendas da Sônia-demo"),
        ("TASK-0003", "Conferir estoque de farinha"),
        ("OUTRO-0010", "Task de revisão geral"),
    ]

    def test_match_by_id_prefix_and_numeric_suffix(self):
        self.assertEqual(
            forms.filter_options(self.ITEMS, "TASK-0002"),
            [{"id": "TASK-0002", "label": "Anotar encomendas da Sônia-demo"}],
        )
        self.assertEqual(
            forms.filter_options(self.ITEMS, "0003"),
            [{"id": "TASK-0003", "label": "Conferir estoque de farinha"}],
        )
        self.assertEqual(
            forms.filter_options(self.ITEMS, "1"),
            [
                {"id": "TASK-0001", "label": "Assar a fornada"},
                {"id": "OUTRO-0010", "label": "Task de revisão geral"},
            ],
        )

    def test_match_by_folded_title_and_name_words(self):
        self.assertEqual(
            forms.filter_options(self.ITEMS, "fornada"),
            [{"id": "TASK-0001", "label": "Assar a fornada"}],
        )
        self.assertEqual(
            forms.filter_options(self.ITEMS, "Sônia"),
            [{"id": "TASK-0002", "label": "Anotar encomendas da Sônia-demo"}],
        )
        self.assertEqual(
            forms.filter_options(self.ITEMS, "sonia"),
            [{"id": "TASK-0002", "label": "Anotar encomendas da Sônia-demo"}],
        )
        self.assertEqual(
            forms.filter_options(self.ITEMS, "assar fornada"),
            [{"id": "TASK-0001", "label": "Assar a fornada"}],
        )

    def test_ordering_exact_id_prefix_first_then_by_label(self):
        res = forms.filter_options(self.ITEMS, "task")
        # TASK-0001..0003 casam por prefixo exato do ID e vêm antes de OUTRO-0010 (que só tem "Task" no título);
        # dentro do mesmo grupo, ordena pelo rótulo dobrado ("Anotar..." < "Assar..." < "Conferir...").
        self.assertEqual(
            [x["id"] for x in res],
            ["TASK-0002", "TASK-0001", "TASK-0003", "OUTRO-0010"],
        )

    def test_cap_limit(self):
        many = [(f"TASK-{i:04d}", f"Item {i:02d}") for i in range(1, 25)]
        self.assertEqual(len(forms.filter_options(many, "")), forms.SUGGEST_LIMIT)
        self.assertEqual(len(forms.filter_options(many, "task", limit=5)), 5)

    def test_normalizes_prefixed_labels_and_dict_inputs(self):
        raw = [
            ("PROC-0001", "PROC-0001 · Fechamento mensal"),
            {"id": "PROC-0002", "title": "Abertura da loja"},
        ]
        self.assertEqual(
            forms.filter_options(raw, ""),
            [
                {"id": "PROC-0002", "label": "Abertura da loja"},
                {"id": "PROC-0001", "label": "Fechamento mensal"},
            ],
        )


class FormAutocompleteSpecTest(unittest.TestCase):
    def test_forms_export_carries_suggest_for_merge_and_person_fields(self):
        exported = forms.export()
        merge_into = next(f for f in forms.FORMS["action.merge"].fields if f.id == "into")
        self.assertEqual(merge_into.suggest, "@actions")
        exp_into = next(f for f in exported["action.merge"]["fields"] if f["id"] == "into")
        self.assertEqual(exp_into.get("suggest"), "@actions")

        person_fields = [
            ("action.new", "owner", "@people"),
            ("action.new", "people", "@people"),
            ("action.edit", "owner", "@people"),
            ("action.edit", "people", "@people"),
            ("project.new", "owner", "@people"),
            ("project.edit", "owner", "@people"),
            ("decision.new", "by", "@people"),
            ("process.new", "owner", "@people"),
            ("process.new", "executors", "@people"),
            ("process.edit", "owner", "@people"),
            ("process.edit", "executors", "@people"),
            ("opportunity.new", "people", "@people"),
            ("opportunity.edit", "people", "@people"),
            ("outbox.draft", "to", "@recipients"),
        ]
        for fid, field_id, expected_src in person_fields:
            f = next(x for x in forms.FORMS[fid].fields if x.id == field_id)
            self.assertEqual(f.suggest, expected_src, f"{fid}.{field_id}")
            exp_f = next(x for x in exported[fid]["fields"] if x["id"] == field_id)
            self.assertEqual(exp_f.get("suggest"), expected_src, f"export {fid}.{field_id}")

    def test_actions_source_excludes_current_and_closed_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = _brain(Path(tmp))
            a1 = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Assar a fornada", "owner": "eu"}})["id"]
            a2 = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Anotar encomendas da sonia-demo", "owner": "eu"}})["id"]
            a3 = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Limpar bancada", "owner": "eu"}})["id"]
            b.record_one({"type": "action.closed", "id": a3, "by": "owner", "data": {"how": "feito"}})
            m = model.build(b)
            into_field = next(f for f in forms.FORMS["action.merge"].fields if f.id == "into")
            # Com contexto da ação sendo mesclada (a2), oferece apenas as OUTRAS ações abertas (a1)
            opts_with_ctx = forms.options(into_field, m, {}, {"id": a2})
            self.assertEqual(opts_with_ctx, [(a1, "Assar a fornada")])
            # Sem contexto, oferece todas as ações abertas (a1 e a2), excluindo a fechada (a3)
            opts_no_ctx = forms.options(into_field, m, {}, {})
            self.assertEqual(opts_no_ctx, [(a1, "Assar a fornada"), (a2, "Anotar encomendas da sonia-demo")])

    def test_python_and_js_filter_options_parity(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node ausente")
        items = [
            ["TASK-0001", "Assar a fornada"],
            ["TASK-0002", "Anotar encomendas da Sônia-demo"],
            ["TASK-0003", "Conferir estoque de farinha"],
            ["OUTRO-0010", "Task de revisão geral"],
            ["marina-demo", "Marina-demo"],
            ["sonia-demo", "Sônia-demo"],
        ]
        queries = ["", "fornada", "Sônia", "sonia", "task", "TASK-0002", "2", "marina", "assar fornada", "inexistente"]
        script = (
            "const F = require(process.argv[1]);\n"
            "const {items, queries} = JSON.parse(process.argv[2]);\n"
            "const out = queries.map(q => F.filterOptions(items, q));\n"
            "process.stdout.write(JSON.stringify(out));\n"
        )
        r = subprocess.run([node, "-e", script, str(JS_FORMS), json.dumps({"items": items, "queries": queries})],
                           capture_output=True, text=True, check=True)
        js_out = json.loads(r.stdout)
        py_out = [forms.filter_options(items, q) for q in queries]
        self.assertEqual(py_out, js_out)

    def test_panel_wires_custom_suggest_dropdown(self):
        src = JS_EXTRA.read_text(encoding="utf-8")
        self.assertIn("F.filterOptions(", src)
        self.assertIn('class="fsug"', src)
        self.assertNotIn("<datalist", src)


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class TuiFormAutocompleteTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.b = _brain(Path(self.tmp.name))
        self.a1 = self.b.record_one({"type": "action.opened", "by": "owner",
                                     "data": {"title": "Assar a fornada", "owner": "eu"}})["id"]
        self.a2 = self.b.record_one({"type": "action.opened", "by": "owner",
                                     "data": {"title": "Anotar encomendas da sonia-demo", "owner": "eu"}})["id"]
        self.inst = self.b.inst

    async def test_merge_form_type_title_fragment_and_confirm_fills_right_id(self):
        from textual.widgets import Input, OptionList
        from brainlib.tui.app import BrainApp

        app = BrainApp(self.inst)
        executed: list[list[list[str]]] = []
        app.run_cmds = lambda cmds, **kw: executed.append(cmds)

        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.3)
            # Seleciona TASK-0002 ("Anotar encomendas da sonia-demo") e abre o formulário de mesclagem (M)
            ids = [i.id for i in app.items(2)]
            app.set_sel(2, ids.index(self.a2))
            app.redraw()
            await pilot.press("M")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")

            inp = app.screen.query_one("#f_into", Input)
            ol = app.screen.query_one("#s_into", OptionList)
            self.assertFalse(ol.display)

            # Digita "fornada" (fragmento do título de TASK-0001)
            for ch in "fornada":
                await pilot.press(ch)
            await pilot.pause(0.1)

            self.assertTrue(ol.display)
            self.assertEqual(ol.option_count, 1)
            self.assertIn(self.a1, str(ol.get_option_at_index(0).prompt))
            self.assertIn("Assar a fornada", str(ol.get_option_at_index(0).prompt))

            # Confirmar a sugestão com Enter preenche o campo com TASK-0001 e fecha a lista de sugestões
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(inp.value, self.a1)
            self.assertFalse(ol.display)
            self.assertEqual(
                app.screen.spec.build(app.screen.vals()),
                [["action", "merge", self.a2, "--into", self.a1, "--by", "owner"]],
            )

            # Confirmar o formulário dispara o comando com o ID certo
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(executed, [[["action", "merge", self.a2, "--into", self.a1, "--by", "owner"]]])

    async def test_person_field_autocomplete_arrows_and_escape_dismiss(self):
        from textual.widgets import Input, OptionList
        from brainlib.tui.app import BrainApp

        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.3)
            app.open_form("project.new", {"nid": "PROJ-2", "goal": "GOAL-1", "goal_title": "Padaria"})
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")

            owner_inp = app.screen.query_one("#f_owner", Input)
            owner_ol = app.screen.query_one("#s_owner", OptionList)
            owner_inp.focus()
            await pilot.pause(0.1)

            # Seta para baixo abre a lista; Esc fecha apenas a lista de sugestões sem fechar o FormModal
            await pilot.press("down")
            await pilot.pause(0.1)
            self.assertTrue(owner_ol.display)
            await pilot.press("escape")
            await pilot.pause(0.1)
            self.assertFalse(owner_ol.display)
            self.assertEqual(type(app.screen).__name__, "FormModal")

            # Digitar "sonia" sem acento filtra "Sônia-demo" e Enter preenche "sonia-demo"
            for ch in "sonia":
                await pilot.press(ch)
            await pilot.pause(0.1)
            self.assertTrue(owner_ol.display)
            self.assertEqual(owner_ol.option_count, 1)
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(owner_inp.value, "sonia-demo")
            self.assertFalse(owner_ol.display)

    async def test_comma_separated_people_field_autocompletes_last_token(self):
        from textual.widgets import Input, OptionList
        from brainlib.tui.app import BrainApp

        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.3)
            app.open_form("decision.new")
            await pilot.pause(0.2)
            by_inp = app.screen.query_one("#f_by", Input)
            by_ol = app.screen.query_one("#s_by", OptionList)
            by_inp.focus()
            await pilot.pause(0.1)

            by_inp.value = "marina-demo, son"
            await pilot.pause(0.1)
            self.assertTrue(by_ol.display)
            self.assertEqual(by_ol.option_count, 1)
            await pilot.press("enter")
            await pilot.pause(0.1)
            self.assertEqual(by_inp.value, "marina-demo, sonia-demo")
            self.assertFalse(by_ol.display)


if __name__ == "__main__":
    unittest.main()
