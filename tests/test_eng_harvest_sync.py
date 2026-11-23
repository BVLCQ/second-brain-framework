"""Regressões de colheita no sync, ordenação de agenda e vagas de notas (#64, #65, #85)."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, focus, harvest, index, notes, render, search, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    hor = (util.today() + timedelta(days=80)).isoformat()
    due1 = (util.today() + timedelta(days=11)).isoformat()
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n'
        '[outbound]\nallow = ["marina-demo"]\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        f"# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: {hor}\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        f"- [ ] PROJ-1.1 Entregável · prazo: {due1} · peso: 1\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "area.added", "id": "operacoes", "by": "owner",
                  "data": {"name": "Operações"}})
    return b


def _open_action(b: Brain, title: str = "Revisar contrato") -> str:
    due = (util.today() + timedelta(days=3)).isoformat()
    ev = b.record_one({
        "type": "action.opened",
        "by": "owner",
        "data": {"title": title, "owner": "eu", "list": "mine", "due": due},
    })
    return ev["id"]


def _set_front_status(path: Path, new_status: str) -> None:
    txt = path.read_text(encoding="utf-8")
    updated, n = re.subn(r'^status:\s*.*$', f'status: "{new_status}"', txt, count=1, flags=re.M)
    assert n == 1, f"frontmatter sem status: em {path}"
    path.write_text(updated, encoding="utf-8")


class TestHarvestSyncRoundTrip(unittest.TestCase):
    def test_todo_checkbox_roundtrip_two_syncs(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)
            st0 = harvest.load_state(b.inst.fresh)
            rendered_at = st0["rendered_at"]
            todo = b.inst.fresh / "todo.md"

            txt = todo.read_text(encoding="utf-8")
            todo.write_text(txt.replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1), encoding="utf-8")
            ev1 = harvest.run(b)
            self.assertEqual([e["type"] for e in ev1], ["action.closed"])
            self.assertFalse(b.state.actions[aid].open)

            # Segunda edição sem render intermediário: desmarcar deve reabrir
            txt2 = todo.read_text(encoding="utf-8")
            todo.write_text(txt2.replace(f"- [x] **{aid}**", f"- [ ] **{aid}**", 1), encoding="utf-8")
            ev2 = harvest.run(b)
            self.assertEqual([e["type"] for e in ev2], ["action.reopened"])
            self.assertTrue(b.state.actions[aid].open)

            # Terceira execução sem edição não grava nada
            self.assertEqual(harvest.run(b), [])
            self.assertEqual(harvest.load_state(b.inst.fresh)["rendered_at"], rendered_at)

    def test_action_record_status_roundtrip_two_syncs(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)
            rec = b.inst.fresh / "records" / "actions" / f"{aid}.md"

            _set_front_status(rec, "feita")
            ev1 = harvest.run(b)
            self.assertEqual([e["type"] for e in ev1], ["action.closed"])
            self.assertFalse(b.state.actions[aid].open)

            _set_front_status(rec, "a fazer")
            ev2 = harvest.run(b)
            self.assertEqual([e["type"] for e in ev2], ["action.reopened", "action.updated"])
            self.assertTrue(b.state.actions[aid].open)

            self.assertEqual(harvest.run(b), [])

    def test_opportunity_record_status_roundtrip_two_syncs(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            oid = b.record_one({
                "type": "opportunity.added",
                "by": "owner",
                "data": {"title": "Padronizar abertura", "area": "operacoes"},
            })["id"]
            render.render_all(b, do_harvest=False)
            rec = b.inst.fresh / "records" / "opportunities" / f"{oid}.md"

            _set_front_status(rec, "triagem")
            ev1 = harvest.run(b)
            self.assertEqual([e["type"] for e in ev1], ["opportunity.status"])
            self.assertEqual(b.state.opportunities[oid].status, "triagem")

            _set_front_status(rec, "ideia")
            ev2 = harvest.run(b)
            self.assertEqual([e["type"] for e in ev2], ["opportunity.status"])
            self.assertEqual(b.state.opportunities[oid].status, "ideia")

            self.assertEqual(harvest.run(b), [])

    def test_failed_record_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)
            todo = b.inst.fresh / "todo.md"
            txt = todo.read_text(encoding="utf-8")
            todo.write_text(txt.replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1), encoding="utf-8")

            with mock.patch.object(b, "record", side_effect=util.BrainError("falha simulada", code=5)):
                with self.assertRaises(util.BrainError):
                    harvest.run(b)

            st = harvest.load_state(b.inst.fresh)
            self.assertIs(st["todo"][aid], False)

    def test_absorbed_edit_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            aid = _open_action(b)
            render.render_all(b, do_harvest=False)
            snap = harvest.begin_agent_window(b.inst, "nightly", strict=True)
            todo = b.inst.fresh / "todo.md"
            txt = todo.read_text(encoding="utf-8")
            todo.write_text(txt.replace(f"- [ ] **{aid}**", f"- [x] **{aid}**", 1), encoding="utf-8")
            win = harvest.end_agent_window(b.inst, snap)

            notices: list[dict] = []
            ev = harvest.run(b, notices=notices, window=win)
            self.assertEqual(ev, [])
            self.assertTrue(any(n["title"] == "colheita" for n in notices))
            self.assertIs(harvest.load_state(b.inst.fresh)["todo"][aid], False)


class TestLatestCalendarSnapshot(unittest.TestCase):
    def test_december_beats_november(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            inbox = vault / "RAW" / "inbox"
            inbox.mkdir(parents=True)
            nov = inbox / "gcal-2026-11-30.json"
            dec = inbox / "gcal-2026-12-01.json"
            nov.write_text("{}", encoding="utf-8")
            dec.write_text("{}", encoding="utf-8")
            os.utime(dec, (1000, 1000))
            os.utime(nov, (2000, 2000))

            got = focus.latest_calendar_snapshot(vault)
            self.assertEqual(got, dec)

    def test_same_day_tiebreak_by_time_then_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            inbox = vault / "RAW" / "inbox"
            arch = vault / "RAW" / "2026" / "12" / "connectors"
            inbox.mkdir(parents=True)
            arch.mkdir(parents=True)
            early = inbox / "gcal-2026-12-01-0830.json"
            late = inbox / "gcal-2026-12-01-1415.json"
            early.write_text("{}", encoding="utf-8")
            late.write_text("{}", encoding="utf-8")
            os.utime(late, (1000, 1000))
            os.utime(early, (3000, 3000))

            self.assertEqual(focus.latest_calendar_snapshot(vault), late)

            early.unlink()
            late.unlink()
            f_arch = arch / "gcal-2026-12-01.json"
            f_inbox = inbox / "gcal-2026-12-01.json"
            f_arch.write_text("{}", encoding="utf-8")
            f_inbox.write_text("{}", encoding="utf-8")
            os.utime(f_arch, (2500, 2500))
            os.utime(f_inbox, (1500, 1500))

            self.assertEqual(focus.latest_calendar_snapshot(vault), f_arch)

    def test_fallback_mtime_when_undated(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            inbox = vault / "RAW" / "inbox"
            inbox.mkdir(parents=True)
            fa = inbox / "gcal-a.json"
            fb = inbox / "gcal-b.json"
            fa.write_text("{}", encoding="utf-8")
            fb.write_text("{}", encoding="utf-8")
            os.utime(fa, (2000, 2000))
            os.utime(fb, (1000, 1000))

            self.assertEqual(focus.latest_calendar_snapshot(vault), fa)

    def test_empty_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            (vault / "RAW" / "inbox").mkdir(parents=True)
            self.assertIsNone(focus.latest_calendar_snapshot(vault))


class TestSearchLiveNotesSeats(unittest.TestCase):
    def test_exact_note_survives_full_index_page(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            notes.create(b, "padaria fermentacao longa e temperatura do forno")
            idx_hits = [
                {"kind": "ação", "id": "TASK-0001", "title": "Item 1", "date": "2026-10-01", "path": None, "score": 10.0},
                {"kind": "ação", "id": "TASK-0002", "title": "Item 2", "date": "2026-10-02", "path": None, "score": 8.0},
                {"kind": "ação", "id": "TASK-0003", "title": "Item 3", "date": "2026-10-03", "path": None, "score": 5.0},
                {"kind": "ação", "id": "TASK-0004", "title": "Item 4", "date": "2026-10-04", "path": None, "score": 1.0},
            ]
            with mock.patch.object(index, "search_index", return_value=idx_hits):
                got = search.search(b, "padaria fermentacao", limit=4)

            self.assertEqual(len(got), 4)
            ids = [h["id"] for h in got]
            self.assertTrue(any(h["kind"] == "nota" for h in got), got)
            self.assertNotIn("TASK-0004", ids)
            for keep in ("TASK-0001", "TASK-0002", "TASK-0003"):
                self.assertIn(keep, ids)

    def test_strong_note_ranks_ahead_of_partial_index_hits(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            notes.create(b, "padaria forno ajustado hoje")
            idx_hits = [
                {"kind": "ação", "id": f"TASK-000{i}", "title": f"Parcial {i}", "date": "2026-10-01",
                 "path": None, "score": float(10 - i), "match": "parcial"}
                for i in range(1, 5)
            ]
            with mock.patch.object(index, "search_index", return_value=idx_hits):
                got = search.search(b, "padaria forno", limit=4)

            self.assertEqual(len(got), 4)
            self.assertEqual(got[0]["kind"], "nota")

    def test_seat_cap_half_limit(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for i in range(5):
                notes.create(b, f"padaria forno lote {i}")
            idx_hits = [
                {"kind": "ação", "id": f"TASK-000{i}", "title": f"Item {i}", "date": "2026-10-01",
                 "path": None, "score": float(100 - i * 10)}
                for i in range(1, 7)
            ]
            with mock.patch.object(index, "search_index", return_value=idx_hits):
                got = search.search(b, "padaria forno", limit=6)

            self.assertEqual(len(got), 6)
            note_hits = [h for h in got if h["kind"] == "nota"]
            idx_kept = [h for h in got if h["kind"] != "nota"]
            self.assertEqual(len(note_hits), 3)
            self.assertEqual([h["id"] for h in idx_kept], ["TASK-0001", "TASK-0002", "TASK-0003"])

    def test_leftover_seats_and_zero_limit(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for i in range(5):
                notes.create(b, f"padaria forno lote {i}")
            idx_hits = [
                {"kind": "ação", "id": "TASK-0001", "title": "Item 1", "date": "2026-10-01", "path": None, "score": 9.0},
            ]
            with mock.patch.object(index, "search_index", return_value=idx_hits):
                got = search.search(b, "padaria forno", limit=6)
                empty = search.search(b, "padaria forno", limit=0)

            self.assertEqual(empty, [])
            self.assertEqual(len(got), 6)
            self.assertEqual(sum(1 for h in got if h["kind"] == "nota"), 5)


if __name__ == "__main__":
    unittest.main()
