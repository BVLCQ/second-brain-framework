"""Testes de guarda de atribuição na colheita pós-agente (#106) — stdlib unittest, sem rede."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, harvest, planning, render, runner, serve, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.tui import bridge  # noqa: E402

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


def _make_brain(tmp: Path) -> Brain:
    today = util.today()
    due1 = (today + timedelta(days=11)).isoformat()
    due2 = (today + timedelta(days=23)).isoformat()
    hor = (today + timedelta(days=80)).isoformat()
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n'
        '[runner]\nagent = "none"\ntimeout_min = 45\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        f"# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: {hor}\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        f"- [ ] PROJ-1.1 Um entregável · prazo: {due1} · peso: 2\n"
        f"- [ ] PROJ-1.2 Outro · prazo: {due2}\n",
        encoding="utf-8",
    )
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


def _open_action(b: Brain, title: str = "Revisar contrato") -> str:
    due = (util.today() + timedelta(days=3)).isoformat()
    ev = b.record_one({
        "type": "action.opened",
        "by": "owner",
        "data": {"title": title, "owner": "eu", "due": due, "effort_min": 30},
    })
    return ev["id"]


def _gated_close(b: Brain, did: str) -> None:
    """Os dois passos de `brain plan deliverable` (cli.py): reescreve a linha no goals.md e registra o evento."""
    planning.set_deliverable(b.inst.planning_file, did, "feito", util.today())
    b.reload()
    b.record_one({"type": "deliverable.updated", "id": did, "by": "agent", "prov": "observado",
                  "source": "chat", "data": {"status": "feito", "evidence": "teste"}})


class HarvestGuardTests(unittest.TestCase):
    def test_agent_planted_todo_checkbox_absorbed_not_owner(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)
            before_events = len(b.read_events())

            def fake_agent(brain, ran=None):
                todo = brain.inst.fresh / "todo.md"
                txt = todo.read_text(encoding="utf-8")
                todo.write_text(txt.replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1), encoding="utf-8")
                return "fake ok"

            with mock.patch.object(runner, "run_agent", side_effect=fake_agent):
                res = runner.nightly(b)

            self.assertTrue(res["ok"])
            self.assertIn("colheita", res["steps"])
            b.reload()
            self.assertTrue(b.state.actions[aid].open)
            owner_closes = [
                e for e in b.read_events()[before_events:]
                if e.get("by") == "owner" and e.get("type") == "action.closed"
            ]
            self.assertEqual(owner_closes, [])
            todo_txt = (b.inst.fresh / "todo.md").read_text(encoding="utf-8")
            self.assertIn(f"- [ ] **{aid}**", todo_txt)
            self.assertNotIn(f"- [x] **{aid}**", todo_txt)
            nlog = (b.inst.logs / "nightly.log").read_text(encoding="utf-8")
            self.assertIn("FRESH/todo.md", nlog)
            self.assertIn(aid, nlog)

    def test_absorbed_goals_tick_is_undone_in_file_and_progress(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file
            orig_lines = planning._lines(goals_path.read_text(encoding="utf-8"))
            orig_deliv = next(ln for ln in orig_lines if "PROJ-1.1" in ln)
            before_progress = planning.load(goals_path).progress("PROJ-1")

            def fake_agent(brain, ran=None):
                txt = goals_path.read_text(encoding="utf-8")
                goals_path.write_text(txt.replace("- [ ] PROJ-1.1", "- [x] PROJ-1.1", 1), encoding="utf-8")
                return "fake ok"

            with mock.patch.object(runner, "run_agent", side_effect=fake_agent):
                res = runner.nightly(b)

            self.assertTrue(res["ok"])
            self.assertIn("colheita", res["steps"])
            b.reload()
            deliv_evs = [e for e in b.read_events() if e["type"] == "deliverable.updated"]
            self.assertEqual(deliv_evs, [])
            restored_lines = planning._lines(goals_path.read_text(encoding="utf-8"))
            self.assertIn(orig_deliv, restored_lines)
            self.assertEqual(planning.load(goals_path).progress("PROJ-1"), before_progress)
            nlog = (b.inst.logs / "nightly.log").read_text(encoding="utf-8")
            self.assertIn("PLANNING/goals.md", nlog)
            self.assertIn("PROJ-1.1", nlog)

            # Segundo render comum também não emite nada
            rep2 = render.render_all(b)
            self.assertEqual(rep2["harvested"], [])
            self.assertEqual([e for e in b.read_events() if e["type"] == "deliverable.updated"], [])

    def test_planted_tick_with_future_mtime_is_still_absorbed_nightly(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)

            def fake_agent(brain, ran=None):
                todo = brain.inst.fresh / "todo.md"
                todo.write_text(
                    todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                    encoding="utf-8",
                )
                future = time.time() + 86400
                os.utime(todo, (future, future))
                return "fake ok"

            with mock.patch.object(runner, "run_agent", side_effect=fake_agent):
                res = runner.nightly(b)

            self.assertTrue(res["ok"])
            b.reload()
            self.assertTrue(b.state.actions[aid].open)
            self.assertIn("colheita", res["steps"])

    def test_owner_edit_before_agent_is_still_harvested(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)

            todo = b.inst.fresh / "todo.md"
            todo.write_text(
                todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                encoding="utf-8",
            )

            with mock.patch.object(runner, "run_agent", return_value="fake ok"):
                res = runner.nightly(b)

            self.assertTrue(res["ok"])
            self.assertNotIn("colheita", res["steps"])
            b.reload()
            self.assertFalse(b.state.actions[aid].open)
            closes = [e for e in b.read_events() if e["type"] == "action.closed" and e["id"] == aid]
            self.assertEqual(len(closes), 1)
            self.assertEqual(closes[0]["by"], "owner")

    def test_owner_edit_after_agent_end_is_harvested_in_untrusted_window(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)

            snap = harvest.begin_agent_window(b.inst, "tui", strict=False)
            win = harvest.end_agent_window(b.inst, snap)

            todo = b.inst.fresh / "todo.md"
            todo.write_text(
                todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                encoding="utf-8",
            )
            after_ns = win["ended_ns"] + 5_000_000_000
            os.utime(todo, ns=(after_ns, after_ns))

            rep = render.render_all(b)
            self.assertIn(f"action.closed {aid}", rep["harvested"])
            b.reload()
            self.assertFalse(b.state.actions[aid].open)

    def test_owner_edit_during_window_to_a_non_deliverable_line_is_kept(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file

            def fake_agent(brain, ran=None):
                txt = goals_path.read_text(encoding="utf-8")
                txt = txt.replace("- por quê: teste", "- por quê: motivo editado pelo dono", 1)
                txt = txt.replace("- [ ] PROJ-1.1", "- [x] PROJ-1.1", 1)
                goals_path.write_text(txt, encoding="utf-8")
                return "fake ok"

            with mock.patch.object(runner, "run_agent", side_effect=fake_agent):
                runner.nightly(b)

            final_txt = goals_path.read_text(encoding="utf-8")
            self.assertIn("- por quê: motivo editado pelo dono", final_txt)
            self.assertIn("- [ ] PROJ-1.1", final_txt)
            self.assertNotIn("- [x] PROJ-1.1", final_txt)

    def test_window_file_deleted_by_agent_still_guards_nightly(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)

            def fake_agent(brain, ran=None):
                guard = brain.inst.logs / harvest.HARVEST_GUARD_FILE
                self.assertTrue(guard.exists())
                self.assertEqual(stat.S_IMODE(guard.stat().st_mode), 0o600)
                guard.unlink()
                todo = brain.inst.fresh / "todo.md"
                todo.write_text(
                    todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                    encoding="utf-8",
                )
                return "fake ok"

            with mock.patch.object(runner, "run_agent", side_effect=fake_agent):
                res = runner.nightly(b)

            self.assertTrue(res["ok"])
            self.assertIn("colheita", res["steps"])
            b.reload()
            self.assertTrue(b.state.actions[aid].open)

    def test_stale_crash_marker_does_not_absorb_late_owner_edit(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)

            old_start = time.time_ns() - 4 * 3600 * 1_000_000_000
            old_deadline = old_start + 55 * 60 * 1_000_000_000
            stale = {
                "label": "tui",
                "strict": False,
                "started_ns": old_start,
                "deadline_ns": old_deadline,
                "files": harvest.snapshot_inputs(b.inst),
            }
            harvest._write_guard(b.inst.logs / harvest.HARVEST_GUARD_FILE, stale)

            todo = b.inst.fresh / "todo.md"
            todo.write_text(
                todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                encoding="utf-8",
            )
            now_ns = time.time_ns()
            os.utime(todo, ns=(now_ns, now_ns))

            rep = render.render_all(b)
            self.assertIn(f"action.closed {aid}", rep["harvested"])
            self.assertFalse((b.inst.logs / harvest.HARVEST_GUARD_FILE).exists())

    def test_stale_strict_nightly_window_does_not_absorb_late_owner_edit(self):
        # Noturno morto entre o fim do agente e o render final (máquina dormiu, desligou): fica a janela ESTRITA no
        # disco até o primeiro render do dono. O que ele marcou depois disso tem mtime E ctime posteriores ao fim e
        # precisa ser colhido; só o que mudou até o fim é do agente.
        for closed in (True, False):
            with self.subTest(fechada=closed), tempfile.TemporaryDirectory() as td:
                b = _make_brain(Path(td))
                aid = _open_action(b)
                render.render_all(b, do_harvest=False)
                old_start = time.time_ns() - 4 * 3600 * 1_000_000_000
                stale = {
                    "label": "nightly",
                    "strict": True,
                    "started_ns": old_start,
                    "deadline_ns": old_start + 55 * 60 * 1_000_000_000,
                    "files": harvest.snapshot_inputs(b.inst),
                }
                if closed:
                    stale["ended_ns"] = old_start + 20 * 60 * 1_000_000_000
                harvest._write_guard(b.inst.logs / harvest.HARVEST_GUARD_FILE, stale)

                todo = b.inst.fresh / "todo.md"
                todo.write_text(
                    todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                    encoding="utf-8",
                )

                rep = render.render_all(b)
                self.assertIn(f"action.closed {aid}", rep["harvested"])
                b.reload()
                self.assertFalse(b.state.actions[aid].open)

    def test_forged_future_mtime_inside_strict_window_is_still_absorbed(self):
        # O contrário do de cima, direto na regra: plantação FEITA dentro da janela com mtime forjado para o futuro
        # tem ctime dentro da janela — continua sendo do agente.
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)
            files = harvest.snapshot_inputs(b.inst)
            todo = b.inst.fresh / "todo.md"
            todo.write_text(
                todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                encoding="utf-8",
            )
            future = time.time() + 86400
            os.utime(todo, (future, future))
            win = {"label": "nightly", "strict": True, "files": files, "ended_ns": time.time_ns()}

            rep = render.render_all(b, window=win)
            self.assertEqual(rep["harvested"], [])
            b.reload()
            self.assertTrue(b.state.actions[aid].open)

    def test_window_left_by_agent_job_is_consumed_by_next_render(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)

            snap = harvest.begin_agent_window(b.inst, "panel:dump", strict=False)
            todo = b.inst.fresh / "todo.md"
            todo.write_text(
                todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                encoding="utf-8",
            )
            harvest.end_agent_window(b.inst, snap)
            self.assertTrue((b.inst.logs / harvest.HARVEST_GUARD_FILE).exists())

            rep = render.render_all(b)
            self.assertEqual(rep["harvested"], [])
            self.assertTrue(any(w["title"] == "colheita" and aid in w["detail"] for w in rep["warnings"]))
            self.assertFalse((b.inst.logs / harvest.HARVEST_GUARD_FILE).exists())
            b.reload()
            self.assertTrue(b.state.actions[aid].open)

    def _plant(self, b: Brain, edit, strict: bool = True) -> dict:
        """Abre a janela, aplica `edit(text) -> text` no goals.md, fecha e devolve a janela."""
        snap = harvest.begin_agent_window(b.inst, "nightly" if strict else "tui", strict=strict)
        goals_path = b.inst.planning_file
        goals_path.write_text(edit(goals_path.read_text(encoding="utf-8")), encoding="utf-8")
        return harvest.end_agent_window(b.inst, snap)

    def _colheita(self, rep: dict, needle: str) -> bool:
        return any(w["title"] == "colheita" and needle in w["detail"] for w in rep["warnings"])

    def _deliverable_events(self, b: Brain, did: str) -> list[dict]:
        return [e for e in b.read_events() if e["type"] == "deliverable.updated" and e["id"] == did]

    def test_new_ticked_deliverable_planted_in_window_is_removed_and_never_attributed(self):
        # Linha de entregável NOA, já marcada, sem evento no ledger: é plantação. Se ficasse no arquivo, o render
        # seguinte (sem janela) leria o `[x]` como edição manual do dono — a atribuição só seria adiada.
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file
            new_line = "- [x] PROJ-1.3 Entregável plantado · peso: 3"

            win = self._plant(b, lambda txt: txt + new_line + "\n")
            rep = render.render_all(b, window=win)
            self.assertEqual(rep["harvested"], [])
            self.assertNotIn("PROJ-1.3", goals_path.read_text(encoding="utf-8"))
            self.assertTrue(self._colheita(rep, "PROJ-1.3"), rep["warnings"])

            rep2 = render.render_all(b)
            self.assertEqual(rep2["harvested"], [])
            self.assertEqual(self._deliverable_events(b, "PROJ-1.3"), [])
            self.assertNotIn("PROJ-1.3", planning.load(goals_path).deliverables)

    def test_new_unticked_deliverable_added_in_window_is_kept(self):
        # Cadastro com gate (`brain plan add`) feito durante a janela: linha `[ ]` confere com o ledger — fica.
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file
            new_line = "- [ ] PROJ-1.3 Novo entregável · peso: 1"

            win = self._plant(b, lambda txt: txt + new_line + "\n")
            rep = render.render_all(b, window=win)
            self.assertEqual(rep["harvested"], [])
            self.assertIn(new_line, goals_path.read_text(encoding="utf-8"))
            self.assertFalse(self._colheita(rep, "PROJ-1.3"), rep["warnings"])
            self.assertEqual(self._deliverable_events(b, "PROJ-1.3"), [])
            self.assertEqual(render.render_all(b)["harvested"], [])

    def test_gated_deliverable_close_during_agent_window_survives(self):
        # `brain plan deliverable` é a via legítima de o agente fechar um entregável: reescreve a linha E registra
        # `deliverable.updated`. A guarda desfaz edição SEM evento; essa tem — precisa ficar no arquivo.
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file

            def fake_agent(brain, ran=None):
                _gated_close(brain, "PROJ-1.1")
                return "fake ok"

            with mock.patch.object(runner, "run_agent", side_effect=fake_agent):
                res = runner.nightly(b)

            self.assertTrue(res["ok"])
            self.assertIn("- [x] PROJ-1.1", goals_path.read_text(encoding="utf-8"))
            b.reload()
            self.assertEqual(b.plan.deliverables["PROJ-1.1"].status, "feito")
            self.assertEqual([(e["by"], e["data"]["status"]) for e in self._deliverable_events(b, "PROJ-1.1")],
                             [("agent", "feito")])

            # O render comum seguinte não pode "desfazer" o fechamento em nome do dono
            self.assertEqual(render.render_all(b)["harvested"], [])
            self.assertEqual(len(self._deliverable_events(b, "PROJ-1.1")), 1)
            self.assertIn("- [x] PROJ-1.1", goals_path.read_text(encoding="utf-8"))

    def test_back_to_back_agent_jobs_without_render_keep_the_first_window(self):
        # Painel: dois jobs ⚡ seguidos sem "regenerar views" no meio, e o segundo NÃO mexe no mesmo arquivo. A segunda
        # janela não pode adotar a edição do primeiro agente como estado de antes — senão o render a colhe como do dono.
        # (Quando o segundo job mexe no mesmo arquivo, ele é absorvido inteiro e o buraco não aparece.)
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            a1 = _open_action(b, "Primeira")
            a2 = _open_action(b, "Segunda")
            render.render_all(b, do_harvest=False)
            todo = b.inst.fresh / "todo.md"
            rec2 = b.inst.fresh / "records" / "actions" / f"{a2}.md"

            snap = harvest.begin_agent_window(b.inst, "panel:dump", strict=False)
            todo.write_text(
                todo.read_text(encoding="utf-8").replace(f"- [ ] **{a1}**", f"- [x] **{a1}**", 1),
                encoding="utf-8",
            )
            harvest.end_agent_window(b.inst, snap)

            snap = harvest.begin_agent_window(b.inst, "panel:update", strict=False)  # sobrescreve o guard
            rec2.write_text(
                rec2.read_text(encoding="utf-8").replace('status: "a fazer"', 'status: "feita"', 1),
                encoding="utf-8",
            )
            harvest.end_agent_window(b.inst, snap)

            rep = render.render_all(b)
            self.assertEqual(rep["harvested"], [])
            b.reload()
            self.assertTrue(b.state.actions[a1].open)
            self.assertTrue(b.state.actions[a2].open)
            self.assertFalse([e for e in b.read_events() if e["type"] == "action.closed"])

    def test_owner_edit_between_back_to_back_jobs_is_still_harvested(self):
        # Contraprova da juntura de janelas: edição do dono DEPOIS do fim do primeiro job não vira "do agente".
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)
            todo = b.inst.fresh / "todo.md"

            snap = harvest.begin_agent_window(b.inst, "panel:dump", strict=False)
            harvest.end_agent_window(b.inst, snap)
            todo.write_text(
                todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                encoding="utf-8",
            )
            after_ns = snap["ended_ns"] + 5_000_000_000
            os.utime(todo, ns=(after_ns, after_ns))
            snap = harvest.begin_agent_window(b.inst, "panel:update", strict=False)
            harvest.end_agent_window(b.inst, snap)

            rep = render.render_all(b)
            self.assertIn(f"action.closed {aid}", rep["harvested"])
            b.reload()
            self.assertFalse(b.state.actions[aid].open)

    def test_deleted_deliverables_return_to_the_project_block_next_to_a_new_one(self):
        # Sem vizinha conhecida para se apoiar (o agente apagou as duas e cadastrou uma nova em `[ ]`): as apagadas
        # voltam para o bloco de entregáveis do projeto, na ordem antiga entre si.
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file
            orig_lines = planning._lines(goals_path.read_text(encoding="utf-8"))
            l1 = next(ln for ln in orig_lines if "PROJ-1.1" in ln)
            l2 = next(ln for ln in orig_lines if "PROJ-1.2" in ln)
            new_line = "- [ ] PROJ-1.3 Novo entregável · peso: 1"

            def edit(txt: str) -> str:
                return txt.replace(l1 + "\n", "", 1).replace(l2 + "\n", "", 1) + new_line + "\n"

            win = self._plant(b, edit)
            rep = render.render_all(b, window=win)
            self.assertEqual(rep["harvested"], [])
            after = planning._lines(goals_path.read_text(encoding="utf-8"))
            self.assertEqual([ln for ln in after if "PROJ-1." in ln], [new_line, l1, l2])
            self.assertTrue(self._colheita(rep, "PROJ-1.1") and self._colheita(rep, "PROJ-1.2"), rep["warnings"])
            self.assertEqual(render.render_all(b)["harvested"], [])

    def test_agent_deleted_deliverable_line_in_window_is_restored(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file
            orig = goals_path.read_text(encoding="utf-8")
            gone = next(ln for ln in planning._lines(orig) if "PROJ-1.2" in ln)

            win = self._plant(b, lambda txt: txt.replace(gone + "\n", "", 1))
            rep = render.render_all(b, window=win)
            self.assertEqual(rep["harvested"], [])
            self.assertEqual(goals_path.read_text(encoding="utf-8"), orig)
            self.assertTrue(self._colheita(rep, "PROJ-1.2"), rep["warnings"])
            self.assertEqual(render.render_all(b)["harvested"], [])

    def test_owner_tick_before_window_on_a_line_the_agent_touched_is_still_harvested(self):
        # O dono marcou PROJ-1.1 à mão (ainda não colhido); o agente mexeu na mesma linha. A linha do dono volta
        # e o checkbox dele é colhido no MESMO render — não some nem espera outro render.
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file
            goals_path.write_text(
                goals_path.read_text(encoding="utf-8").replace("- [ ] PROJ-1.1", "- [x] PROJ-1.1", 1),
                encoding="utf-8",
            )

            win = self._plant(
                b,
                lambda txt: txt.replace("- [x] PROJ-1.1 Um entregável", "- [ ] PROJ-1.1 Entregável renomeado", 1),
            )
            rep = render.render_all(b, window=win)
            self.assertEqual(rep["harvested"], ["deliverable.updated PROJ-1.1"])  # o tick do dono, e só ele
            self.assertIn("- [x] PROJ-1.1 Um entregável", goals_path.read_text(encoding="utf-8"))
            evs = self._deliverable_events(b, "PROJ-1.1")
            self.assertEqual([(e["by"], e["data"]["status"]) for e in evs], [("owner", "feito")])
            self.assertEqual(render.render_all(b)["harvested"], [])

    def test_non_deliverable_edit_in_window_is_kept_and_reported(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            render.render_all(b, do_harvest=False)
            goals_path = b.inst.planning_file

            win = self._plant(
                b,
                lambda txt: txt.replace("- por quê: teste", "- por quê: motivo editado na janela", 1),
            )
            rep = render.render_all(b, window=win)
            self.assertEqual(rep["harvested"], [])
            self.assertIn("- por quê: motivo editado na janela", goals_path.read_text(encoding="utf-8"))
            self.assertTrue(self._colheita(rep, "fora de entregáveis"), rep["warnings"])

    def test_agent_side_render_mid_nightly_absorbs_and_does_not_fail(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)

            def fake_agent(brain, ran=None):
                todo = brain.inst.fresh / "todo.md"
                todo.write_text(
                    todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                    encoding="utf-8",
                )
                with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
                    mid = render.render_all(Brain(brain.inst))
                    self.assertEqual(mid["harvested"], [])
                return "fake ok"

            with mock.patch.object(runner, "run_agent", side_effect=fake_agent):
                res = runner.nightly(b)

            self.assertTrue(res["ok"])
            b.reload()
            self.assertTrue(b.state.actions[aid].open)

    def test_record_status_edits_for_action_and_opportunity_are_absorbed(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            b.record_one({"type": "area.added", "by": "owner", "data": {"name": "ops"}})
            oid = b.record_one({"type": "opportunity.added", "by": "owner",
                                "data": {"title": "Melhorar fluxo", "area": "ops"}})["id"]
            render.render_all(b, do_harvest=False)

            snap = harvest.begin_agent_window(b.inst, "nightly", strict=True)
            ap = b.inst.fresh / "records" / "actions" / f"{aid}.md"
            op = b.inst.fresh / "records" / "opportunities" / f"{oid}.md"
            ap.write_text(ap.read_text(encoding="utf-8").replace('status: "a fazer"', 'status: "feita"'), encoding="utf-8")
            op.write_text(op.read_text(encoding="utf-8").replace('status: "ideia"', 'status: "priorizada"'), encoding="utf-8")
            win = harvest.end_agent_window(b.inst, snap)

            rep = render.render_all(b, window=win)
            self.assertEqual(rep["harvested"], [])
            b.reload()
            self.assertTrue(b.state.actions[aid].open)
            self.assertEqual(b.state.opportunities[oid].status, "ideia")
            self.assertTrue(any(w["title"] == "colheita" and aid in w["detail"] for w in rep["warnings"]))
            self.assertTrue(any(w["title"] == "colheita" and oid in w["detail"] for w in rep["warnings"]))

    def test_tui_and_bridge_agent_window_guard(self):
        with tempfile.TemporaryDirectory() as td:
            b = _make_brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)

            if HAVE_TEXTUAL:
                from brainlib.tui.app import BrainApp
                app = BrainApp(b.inst)
                logged: list[tuple[str, str]] = []
                app.log_line = lambda text, style="": logged.append((text, style))
                app._detail_subtitle = lambda: ""
                app.query_one = lambda *a, **kw: mock.MagicMock()
                app.redraw = lambda: None
                app.report_run = lambda info: None
                app._reload = mock.AsyncMock()

                async def fake_bridge_agent(inst, argv, on_line, info=None):
                    guard = inst.logs / harvest.HARVEST_GUARD_FILE
                    self.assertTrue(guard.exists())
                    todo = inst.fresh / "todo.md"
                    todo.write_text(
                        todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                        encoding="utf-8",
                    )
                    return 0

                async def run_tui_agent():
                    app._lock = asyncio.Lock()
                    await app._agent(["fake"], "/dump")

                with mock.patch.object(bridge, "run_agent", side_effect=fake_bridge_agent), \
                     mock.patch.object(bridge, "record_run"):
                    asyncio.run(run_tui_agent())

                self.assertFalse((b.inst.logs / harvest.HARVEST_GUARD_FILE).exists())
                b.reload()
                self.assertTrue(b.state.actions[aid].open)
                yellow_logs = [txt for txt, style in logged if style == "yellow"]
                self.assertTrue(any("colheita:" in txt and aid in txt for txt in yellow_logs), logged)

            # Caminho do painel (`serve._agent_post` -> `_worker`)
            config.set_keys(b.inst, "runner", {"command": f"{sys.executable} -c pass {{prompt}}"})
            serve._Handler.state = serve._State(b.inst, "tok-harvest-test")
            handler = object.__new__(serve._Handler)
            handler.state = serve._Handler.state
            handler.path = "/api/agent"
            handler._read_json_body = lambda: {"action": "dump"}
            sent_resp: list[tuple[int, dict]] = []
            handler._json = lambda code, body: sent_resp.append((code, body))
            handler._deny = lambda code, msg: sent_resp.append((code, {"ok": False, "error": msg}))

            async def fake_panel_agent(inst, argv, on_line, info=None):
                self.assertTrue((inst.logs / harvest.HARVEST_GUARD_FILE).exists())
                todo = inst.fresh / "todo.md"
                todo.write_text(
                    todo.read_text(encoding="utf-8").replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1),
                    encoding="utf-8",
                )
                return 0

            with mock.patch.object(bridge, "run_agent", side_effect=fake_panel_agent), \
                 mock.patch.object(bridge, "record_run"):
                handler._agent_post()
                self.assertEqual(sent_resp[0][0], 200)
                job_id = sent_resp[0][1]["id"]
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    with serve._Handler.state.agent_lock:
                        job = dict(serve._Handler.state.agent_jobs[job_id])
                    if job["status"] != "running":
                        break
                    time.sleep(0.02)

            self.assertEqual(job["status"], "done")
            self.assertTrue(any("janela da colheita fechada" in ln for ln in job["lines"]))
            self.assertTrue((b.inst.logs / harvest.HARVEST_GUARD_FILE).exists())
            rep = render.render_all(b)
            self.assertEqual(rep["harvested"], [])
            b.reload()
            self.assertTrue(b.state.actions[aid].open)


if __name__ == "__main__":
    unittest.main()
