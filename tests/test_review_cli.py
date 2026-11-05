"""Regressões da revisão de cli.py / planning.py / harvest.py / notes.py — stdlib unittest, sem rede."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import harvest, notes as notes_mod, planning, util  # noqa: E402
from test_brain import _brain  # noqa: E402


def _run(td: Path, *args: str, nightly: bool = False, stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "BRAIN_HOME": str(td)}
    env.pop("BRAIN_NIGHTLY", None)
    if nightly:
        env["BRAIN_NIGHTLY"] = "1"
    return subprocess.run([sys.executable, str(ROOT / "brain"), *args], env=env, capture_output=True,
                          text=True, input=stdin)


class PlanDeliverableRollbackTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.b = _brain(self.td)
        self.goals = self.td / "vault" / "PLANNING" / "goals.md"

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _assert_untouched(self, before: str):
        self.assertEqual(self.goals.read_text(encoding="utf-8"), before)
        self.b.reload()
        self.assertEqual([e for e in harvest.collect(self.b) if e["type"] == "deliverable.updated"], [],
                         "checkbox órfão viraria edição do dono na próxima colheita")

    def test_ledger_refusal_restores_goals_md(self):
        before = self.goals.read_text(encoding="utf-8")
        r = _run(self.td, "plan", "deliverable", "PROJ-1.1", "--status", "feito")     # agente sem --prov/--source
        self.assertEqual(r.returncode, 4, r.stderr)
        self._assert_untouched(before)

    def test_nightly_owner_refusal_restores_goals_md(self):
        before = self.goals.read_text(encoding="utf-8")
        r = _run(self.td, "plan", "deliverable", "PROJ-1.1", "--status", "feito", "--by", "owner", nightly=True)
        self.assertEqual(r.returncode, 4, r.stderr)
        self._assert_untouched(before)

    def test_success_still_writes(self):
        r = _run(self.td, "plan", "deliverable", "PROJ-1.1", "--status", "feito", "--by", "owner")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("- [x] PROJ-1.1", self.goals.read_text(encoding="utf-8"))


class AddBatchTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.b = _brain(self.td)

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _check(self, content: str | None, code: int):
        f = self.td / ("lote.json" if content is not None else "nao-existe.json")
        if content is not None:
            f.write_text(content, encoding="utf-8")
        r = _run(self.td, "add", "--file", str(f))
        self.assertEqual(r.returncode, code, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("ERRO:", r.stderr)

    def test_bad_inputs_are_clean_errors(self):
        self._check("{nope", 4)
        self._check("[1, 2]", 4)
        self._check('"texto"', 4)
        self._check(None, 1)                               # arquivo inexistente

    def test_gate_events_refused_even_with_by_owner(self):
        self._check('[{"type": "message.approved", "id": "MSG-0001", "by": "owner", '
                    '"data": {"approval": "enviar 1"}}]', 4)
        self._check('{"type": "plan.changed", "by": "owner", "data": {"diff": "x", "approval": "ok"}}', 4)

    def test_deliverable_updated_refused(self):
        self._check('[{"type": "deliverable.updated", "id": "PROJ-1.1", "prov": "doc", "source": "x.md", '
                    '"data": {"status": "feito"}}]', 4)
        self.b.reload()
        self.assertFalse(self.b.state.deliverable_events.get("PROJ-1.1"))


class PlanLogGateTests(unittest.TestCase):
    def test_blank_approval_refused(self):
        td = Path(tempfile.mkdtemp())
        try:
            _brain(td)
            r = _run(td, "plan", "log", "--diff", "x", "--reason", "y", "--approval", "  ")
            self.assertEqual(r.returncode, 4, r.stderr)
        finally:
            shutil.rmtree(td, ignore_errors=True)


class GoalsRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.g = self.td / "goals.md"

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def test_meta_value_with_backslashes(self):
        self.g.write_text("## GOAL-1 — G\n- status: ativo\n- por quê: velho\n", encoding="utf-8")
        planning.edit_node(self.g, "GOAL-1", why=r"C:\new \1 \g<0>")
        self.assertEqual(planning.load(self.g).goals["GOAL-1"].why, r"C:\new \1 \g<0>")
        self.assertEqual(len(self.g.read_text(encoding="utf-8").splitlines()), 3)

    def test_unicode_line_separators_survive_edit(self):
        text = ("## GOAL-1 — Meta\n- status: ativo\n- por quê: linha\u2028continua\n\n"
                "### PROJ-1 — Proj\x0c x\n- status: ativo\n- [ ] PROJ-1.1 Um · prazo: 2026-10-20\n")
        self.g.write_text(text, encoding="utf-8")
        plan = planning.parse(text)
        self.assertEqual(plan.goals["GOAL-1"].why, "linha\u2028continua")
        self.assertEqual(plan.projects["PROJ-1"].title, "Proj\x0c x")
        planning.edit_node(self.g, "GOAL-1", status="congelado")
        self.assertEqual(self.g.read_text(encoding="utf-8"), text.replace("status: ativo", "status: congelado", 1))
        planning.set_deliverable(self.g, "PROJ-1.1", "feito", None)
        self.assertIn("\u2028", self.g.read_text(encoding="utf-8"))
        self.assertIn("Proj\x0c x", self.g.read_text(encoding="utf-8"))

    def test_status_vocabulario_e_alias_do_antigo(self):
        self.g.write_text("## GOAL-1 — G\n- status: ativo\n\n### PROJ-1 — P\n- status: fechado\n"
                          "- [ ] PROJ-1.1 Um\n", encoding="utf-8")
        plan = planning.load(self.g)
        self.assertEqual(plan.goals["GOAL-1"].status, "ativo")
        self.assertEqual(plan.projects["PROJ-1"].status, "finalizado")          # nome antigo lido como novo
        planning.edit_node(self.g, "GOAL-1", status="depois")
        self.assertIn("- status: depois", self.g.read_text(encoding="utf-8"))
        planning.edit_node(self.g, "PROJ-1", status="congelada")               # feminino do dono vale
        self.assertIn("- status: congelado", self.g.read_text(encoding="utf-8"))
        with self.assertRaises(util.BrainError):
            planning.edit_node(self.g, "GOAL-1", status="arquivado")

    def test_title_edit_without_spaces_around_dash(self):
        self.g.write_text("## GOAL-1—Pré-venda\n- status: ativo\n", encoding="utf-8")
        planning.edit_node(self.g, "GOAL-1", title="Novo")
        self.assertEqual(planning.load(self.g).goals["GOAL-1"].title, "Novo")
        self.assertTrue(self.g.read_text(encoding="utf-8").startswith("## GOAL-1—Novo\n"))

    def test_indented_sub_bullet_is_not_project_meta(self):
        self.g.write_text("## GOAL-1 — G\n- status: ativo\n\n### PROJ-1 — P\n- dono: eu\n- [ ] PROJ-1.1 X\n"
                          "  - status: bloqueado pelo jurídico\n  - dono: marina-demo\n", encoding="utf-8")
        p = planning.load(self.g).projects["PROJ-1"]
        self.assertEqual((p.status, p.owner), ("ativo", "eu"))
        planning.edit_node(self.g, "PROJ-1", owner="ana")
        text = self.g.read_text(encoding="utf-8")
        self.assertIn("- dono: ana\n", text)
        self.assertIn("  - dono: marina-demo\n", text)            # a nota do entregável ficou intacta

    def test_porque_alias_is_edited_not_duplicated(self):
        self.g.write_text("## GOAL-1 — G\n- status: ativo\n- porque: velho\n", encoding="utf-8")
        planning.edit_node(self.g, "GOAL-1", why="")
        self.assertIsNone(planning.load(self.g).goals["GOAL-1"].why)
        self.assertNotIn("porque", self.g.read_text(encoding="utf-8"))

    def test_comment_opened_after_closed_one(self):
        text = ("## GOAL-1 — G\n\n### PROJ-1 — P\n- [ ] PROJ-1.1 X\n<!-- a --> nota <!-- rascunho:\n"
                "- [ ] PROJ-1.2 rascunho comentado\n-->\n")
        self.assertEqual(list(planning.parse(text).deliverables), ["PROJ-1.1"])

    def test_owner_segments_keep_text_and_order(self):
        self.g.write_text("## GOAL-1 — G\n\n### PROJ-1 — P\n"
                          "- [ ] PROJ-1.1 X · Responsável: Ana · prazo: 2026-10-20 · Crítico\n", encoding="utf-8")
        planning.set_deliverable(self.g, "PROJ-1.1", "feito", None)
        self.assertIn("- [x] PROJ-1.1 X · Responsável: Ana · prazo: 2026-10-20 · Crítico · feito: 2026-10-09\n",
                      self.g.read_text(encoding="utf-8"))
        planning.set_deliverable(self.g, "PROJ-1.1", "em-andamento", None)
        planning.edit_node(self.g, "PROJ-1.1", due="2026-11-01", weight=3)
        self.assertIn("- [ ] PROJ-1.1 X · Responsável: Ana · prazo: 2026-11-01 · Crítico · estado: em-andamento"
                      " · peso: 3\n", self.g.read_text(encoding="utf-8"))
        d = planning.load(self.g).deliverables["PROJ-1.1"]
        self.assertEqual((d.status, d.weight, d.due.isoformat()), ("em-andamento", 3, "2026-11-01"))


class InitTests(unittest.TestCase):
    def test_owner_name_with_quotes_and_non_slug_id(self):
        td = Path(tempfile.mkdtemp())
        try:
            (td / "config").mkdir()
            for name in ("brain.toml.example", "watch.toml.example", ".env.example"):
                shutil.copy(ROOT / "config" / name, td / "config" / name)
            shutil.copytree(ROOT / "template", td / "template")
            (td / "vault").mkdir()
            r = _run(td, "init", "--owner-id", "Marína Demo", "--owner-name", 'Ana "Nana" \\ Silva')
            self.assertEqual(r.returncode, 0, r.stderr)
            cfg = tomllib.loads((td / "config" / "brain.toml").read_text(encoding="utf-8"))
            self.assertEqual(cfg["owner"]["id"], "marina-demo")
            self.assertEqual(cfg["owner"]["name"], 'Ana "Nana" \\ Silva')
            self.assertIn("pessoa: marina-demo", r.stdout)
            self.assertEqual(_run(td, "status").returncode, 0)
        finally:
            shutil.rmtree(td, ignore_errors=True)


class NotesArchivedTests(unittest.TestCase):
    def test_inbox_dir_above_vault_does_not_mark_raw_notes_as_inbox(self):
        td = Path(tempfile.mkdtemp())
        try:
            b = _brain(td / "inbox" / "brain")                   # instância dentro de uma pasta chamada "inbox"
            notes_mod.create(b, "na inbox")
            raw = b.inst.vault / "RAW" / "2026" / "10" / "notes"
            raw.mkdir(parents=True)
            (raw / "note-2026-10-01-note.md").write_text("---\ntipo: nota\ncriada: 2026-10-01 09:00\n---\nvelha\n",
                                                        encoding="utf-8")
            by_text = {n.text: n.archived for n in notes_mod.scan(b.inst)}
            self.assertEqual(by_text, {"na inbox": False, "velha": True})
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
