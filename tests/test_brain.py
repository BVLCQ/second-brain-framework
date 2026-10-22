"""Testes do núcleo v2 — stdlib unittest, sem rede, relógio congelado."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, doctor, ids, portfolio as portfolio_mod, notes as notes_mod, focus, harvest, mcp_server, memory, outbox, planning, people, rawsort, render, schema, share, snapshot, upstream, util
from brainlib.core import Brain
from brainlib.gcal import GoogleCalendar
from brainlib import demo as demo_mod


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
        '[outbound]\nallow = ["marina-demo", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n"
        "- [ ] PROJ-1.2 Outro · prazo: 2026-11-01\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Marina-demo", "Mari-demo"], "email": "marina-demo@x.com"}})
    return b


class ConfigTests(unittest.TestCase):
    def test_finds_cwd_instance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _inst(root)
            old = os.getcwd()
            try:
                os.chdir(root)
                os.environ.pop("BRAIN_HOME", None)
                inst = config.load()
                self.assertEqual(inst.root.resolve(), root.resolve())
            finally:
                os.chdir(old)


class UtilTests(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(util.parse_duration("90m"), 90)
        self.assertEqual(util.parse_duration("2h"), 120)
        self.assertEqual(util.parse_duration("1h30"), 90)
        self.assertEqual(util.parse_duration("1d"), 480)

    def test_fold_slug(self):
        self.assertEqual(util.fold("  Marina  demo "), "marina demo")
        self.assertEqual(util.slugify("Marina-demo"), "marina-demo")

    def test_today_frozen(self):
        self.assertEqual(util.today(), date(2026, 10, 9))


class PlanningTests(unittest.TestCase):
    def test_template_has_no_fake_tree(self):
        plan = planning.load(ROOT / "template" / "PLANNING" / "goals.md")
        self.assertEqual(plan.goals, {})
        self.assertFalse(plan.warnings)

    def test_skips_fenced_example(self):
        plan = planning.parse("# x\n\n```\n## GOAL-9 — Exemplo\n- [ ] PROJ-9.1 Foo · prazo: AAAA-MM-DD\n```\n")
        self.assertEqual(plan.goals, {})
        self.assertFalse(plan.warnings)

    def test_parse_and_progress(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(Path(td))
            plan = planning.load(inst.planning_file)
            self.assertEqual(list(plan.goals), ["GOAL-1"])
            self.assertEqual(list(plan.projects), ["PROJ-1"])
            self.assertEqual(plan.deliverables["PROJ-1.1"].weight, 2)
            self.assertFalse(plan.warnings)
            planning.set_deliverable(inst.planning_file, "PROJ-1.1", "feito", date(2026, 10, 8))
            plan = planning.load(inst.planning_file)
            self.assertEqual(plan.deliverables["PROJ-1.1"].status, "feito")
            # peso 2 de 3
            self.assertEqual(plan.progress("PROJ-1")["pct"], 67)
            self.assertEqual(plan.progress("PROJ-1")["done"], 1)
            self.assertEqual(plan.progress("PROJ-1")["weight_done"], 2)
            self.assertIn("peso 2/3", planning.format_progress(plan.progress("PROJ-1")))


class LedgerTests(unittest.TestCase):
    def test_ids_and_close_cascade(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            a1 = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Revisar", "owner": "marina-demo", "list": "waiting"}})
            self.assertEqual(a1["id"], "ACT-0001")
            a2 = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Publicar", "owner": "eu", "due": "2026-10-12",
                                        "effort_min": 60, "project": "PROJ-1", "blocked_by": ["ACT-0001"]}})
            self.assertEqual(a2["id"], "ACT-0002")
            self.assertEqual(b.state.blocked(b.state.actions["ACT-0002"]), ["ACT-0001"])
            b.record_one({"type": "action.closed", "id": "ACT-0001", "by": "owner",
                          "data": {"how": "revisou"}})
            # cascade is CLI-level; ledger just closes
            self.assertFalse(b.state.actions["ACT-0001"].open)
            self.assertEqual(b.state.blocked(b.state.actions["ACT-0002"]), [])
            self.assertEqual(b.validate_all(), [])

    def test_suggested_due_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            a = b.record_one({"type": "action.opened", "by": "agent", "prov": "observado", "source": "chat",
                              "data": {"title": "Sugerida", "owner": "eu", "due": "2026-10-16",
                                       "due_suggested": True, "due_reason": "entregável PROJ-1.1 vence 20/10"}})["id"]
            st = b.state.actions[a]
            self.assertTrue(st.due_suggested)
            self.assertEqual(st.due_reason, "entregável PROJ-1.1 vence 20/10")
            # só o agente sugere; sugestão exige data
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "action.updated", "id": a, "by": "owner",
                              "data": {"due": "2026-10-17", "due_suggested": True}})
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "action.updated", "id": a, "by": "agent", "prov": "observado", "source": "chat",
                              "data": {"due_suggested": True}})
            # o dono aceita como está: mesma data, deixa de ser sugestão
            b.record_one({"type": "action.updated", "id": a, "by": "owner", "data": {"due_confirmed": True}})
            self.assertFalse(b.state.actions[a].due_suggested)
            self.assertEqual(b.state.actions[a].due.isoformat(), "2026-10-16")
            with self.assertRaises(util.BrainError):      # nada pendente para confirmar
                b.record_one({"type": "action.updated", "id": a, "by": "owner", "data": {"due_confirmed": True}})
            # nova sugestão; qualquer data do dono (ou limpar o prazo) a derruba
            sug = {"due": "2026-10-14", "due_suggested": True, "due_reason": "x"}
            b.record_one({"type": "action.updated", "id": a, "by": "agent", "prov": "observado", "source": "chat", "data": sug})
            self.assertTrue(b.state.actions[a].due_suggested)
            b.record_one({"type": "action.updated", "id": a, "by": "owner", "data": {"due": "2026-10-14"}})
            self.assertFalse(b.state.actions[a].due_suggested)
            self.assertEqual(b.state.actions[a].due_reason, "")
            b.record_one({"type": "action.updated", "id": a, "by": "agent", "prov": "observado", "source": "chat", "data": sug})
            b.record_one({"type": "action.updated", "id": a, "by": "owner", "data": {"clear": ["due"]}})
            self.assertFalse(b.state.actions[a].due_suggested)
            self.assertIsNone(b.state.actions[a].due)
            self.assertEqual(b.validate_all(), [])

    def test_decision_supersede(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            d1 = b.record_one({"type": "decision.made", "by": "agent", "prov": "observado",
                               "source": "chat",
                               "data": {"title": "Congelar", "decided_by": ["marina-demo"], "project": "PROJ-1"}})
            b.record_one({"type": "decision.made", "by": "agent", "prov": "doc", "source": "chat",
                          "data": {"title": "Portar", "decided_by": ["marina-demo"], "project": "PROJ-1",
                                   "supersedes": d1["id"]}})
            self.assertEqual(b.state.decisions[d1["id"]].status, "substituida")

    def test_reject_unknown_person(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "action.opened", "by": "owner",
                              "data": {"title": "x", "owner": "ghost"}})

    def test_merge_duplicate_person(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.record_one({"type": "person.added", "id": "lia-demo", "by": "owner",
                          "data": {"name": "Lia-demo", "email": "lia@example.com"}})
            dup = b.record_one({"type": "person.added", "id": "lia-demo", "by": "owner",
                                "data": {"name": "Lia-demo Duplicada", "email": "lia@example.com"}})
            self.assertEqual(dup["id"], "lia-demo-2")
            act = b.record_one({"type": "action.opened", "by": "owner",
                                "data": {"title": "Ler", "owner": "eu", "people": ["lia-demo-2"]}})
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "person.merged", "id": "lia-demo-2", "by": "owner",
                              "data": {"into": "lia-demo-2"}})
            b.record_one({"type": "person.merged", "id": "lia-demo-2", "by": "owner",
                          "data": {"into": "lia-demo"}})
            self.assertNotIn("lia-demo-2", b.state.people)
            self.assertEqual(b.state.actions[act["id"]].people, ["lia-demo"])
            self.assertEqual(people.resolve(b.state, "Lia-demo Duplicada"), ["lia-demo"])
            self.assertEqual(people.alias_collisions(b.state), [])
            self.assertEqual(Brain(b.inst).state.merged_people, {"lia-demo-2": "lia-demo"})

    def test_clear_due(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ev = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Ler", "owner": "eu", "due": "2026-10-15"}})
            b.record_one({"type": "action.updated", "id": ev["id"], "by": "owner",
                          "data": {"clear": ["due"]}})
            self.assertIsNone(b.state.actions[ev["id"]].due)

    def test_agent_needs_source(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "action.opened", "by": "agent", "prov": "observado",
                              "data": {"title": "x", "owner": "eu"}})

    def test_idempotent_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            path = "PROCESSED/2026/10/n.md"
            (b.inst.vault / path).parent.mkdir(parents=True, exist_ok=True)
            (b.inst.vault / path).write_text("# n\n", encoding="utf-8")
            b.record_one({"type": "artifact.added", "id": path, "by": "agent", "prov": "observado",
                          "source": "RAW/2026/10/n.md",
                          "data": {"kind": "nota", "title": "n", "raw": "RAW/2026/10/n.md"}})
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "artifact.added", "id": path, "by": "agent", "prov": "observado",
                              "source": "RAW/2026/10/n.md",
                              "data": {"kind": "nota", "title": "n", "raw": "RAW/2026/10/n.md"}})


class PeopleTests(unittest.TestCase):
    def test_resolve(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self.assertEqual(people.resolve(b.state, "Marina-demo"), ["marina-demo"])
            self.assertEqual(people.resolve(b.state, "marina-demo@x.com"), ["marina-demo"])
            self.assertEqual(people.resolve(b.state, "ninguém"), [])


class HarvestTests(unittest.TestCase):
    def test_todo_checkbox_closes(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ev = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Ler política", "owner": "eu", "due": "2026-10-12",
                                        "effort_min": 30}})
            render.render_all(b, do_harvest=False)
            todo = b.inst.fresh / "todo.md"
            text = todo.read_text(encoding="utf-8")
            text = text.replace(f"- [ ] **{ev['id']}**", f"- [x] **{ev['id']}**", 1)
            todo.write_text(text, encoding="utf-8")
            got = harvest.run(b)
            self.assertEqual(len(got), 1)
            self.assertEqual(got[0]["type"], "action.closed")
            self.assertFalse(b.state.actions[ev["id"]].open)


class FocusTests(unittest.TestCase):
    def test_edf_respects_busy_and_deadline(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.record_one({"type": "action.opened", "by": "owner",
                          "data": {"title": "Urgente", "owner": "eu", "due": "2026-10-10",
                                   "effort_min": 60, "priority": "alta"}})
            b.record_one({"type": "action.opened", "by": "owner",
                          "data": {"title": "Depois", "owner": "eu", "due": "2026-10-20",
                                   "effort_min": 60}})
            busy = [(datetime(2026, 10, 9, 11, 0, tzinfo=util.tz()),
                     datetime(2026, 10, 9, 12, 0, tzinfo=util.tz()))]
            plan = focus.build_plan(b, busy, days=5)
            self.assertTrue(plan["blocks"])
            first = plan["blocks"][0]
            self.assertEqual(first["action"], "ACT-0001")
            # não começa dentro do busy (11-12 + buffer tratado em parse_busy; aqui busy já cortado)
            start = util.parse_dt(first["start"])
            self.assertFalse(datetime(2026, 10, 9, 11, 0, tzinfo=util.tz()) <= start <
                             datetime(2026, 10, 9, 12, 0, tzinfo=util.tz()))

    def test_ics_roundtrip_shape(self):
        ics = focus.to_ics("FOCUS-0001", [{"action": "ACT-0001", "start": "2026-10-09T14:00:00-03:00",
                                       "end": "2026-10-09T15:00:00-03:00", "minutes": 60}],
                           {"ACT-0001": "Ler"}, "Foco")
        self.assertIn("BEGIN:VEVENT", ics)
        self.assertIn("SUMMARY:Foco · ACT-0001 · Ler", ics)

    def test_apply_requires_approval(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            body = focus.build_plan(b, [])
            ev = b.record_one({"type": "focus.planned", "by": "system",
                               "data": {"plan_file": "FRESH/focus.md", **body}})
            with self.assertRaises(util.BrainError):
                focus.apply(b, ev["id"], mode="ics")
            b.record_one({"type": "focus.approved", "id": ev["id"], "by": "owner",
                          "data": {"quote": "ok", "sha": body["sha"]}})
            res = focus.apply(b, ev["id"], mode="ics")
            self.assertEqual(res["mode"], "ics")
            self.assertTrue(Path(res["file"]).exists())


class OutboxTests(unittest.TestCase):
    def test_allowlist_and_hash(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                outbox.draft(b, "ghost", "oi", None, None)
            ev = outbox.draft(b, "marina-demo", "Oi Marina-demo, tudo bem?", None, "teste")
            with self.assertRaises(util.BrainError):
                outbox.sent(b, ev["id"], None)
            outbox.approve(b, ev["id"], "enviar 1")
            outbox.sent(b, ev["id"], "https://slack/xxx")
            self.assertEqual(b.state.messages[ev["id"]].status, "enviada")


class SnapshotTests(unittest.TestCase):
    def test_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            r1 = snapshot.take(b, "gmail-today", "assunto X\n")
            self.assertTrue(r1["changed"])
            r2 = snapshot.take(b, "gmail-today", "assunto X\n")
            self.assertFalse(r2["changed"])
            r3 = snapshot.take(b, "gmail-today", "assunto Y\n")
            self.assertTrue(r3["changed"])

    def test_folder_items_have_their_own_hash(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            a1 = snapshot.take(b, "drive-pasta", "ata A\n", item="idA", rev="t1", name="Ata A")
            b1 = snapshot.take(b, "drive-pasta", "ata B\n", item="idB", rev="t1")
            self.assertTrue(a1["changed"] and b1["changed"])
            self.assertNotEqual(a1["path"], b1["path"])
            # B muda; A continua igual: só B gera arquivo novo
            self.assertFalse(snapshot.take(b, "drive-pasta", "ata A\n", item="idA", rev="t1")["changed"])
            b2 = snapshot.take(b, "drive-pasta", "ata B v2\n", item="idB", rev="t2")
            self.assertTrue(b2["changed"])
            self.assertEqual(len(list(b.inst.inbox.glob("*.md"))), 3)

    def test_rev_skips_reading(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            snapshot.take(b, "drive-pasta", "ata A\n", item="idA", rev="t1")
            self.assertTrue(snapshot.unchanged(b, "drive-pasta", "t1", "idA"))
            self.assertFalse(snapshot.unchanged(b, "drive-pasta", "t2", "idA"))
            r = snapshot.take(b, "drive-pasta", "", item="idA", rev="t1")   # sem conteúdo: nem foi lido
            self.assertEqual((r["changed"], r["failed"], r["why"]), (False, False, "rev"))
            # revisão nova, mesmo texto: sem arquivo novo, e a revisão nova fica guardada
            r = snapshot.take(b, "drive-pasta", "ata A\n", item="idA", rev="t2")
            self.assertFalse(r["changed"])
            self.assertTrue(snapshot.unchanged(b, "drive-pasta", "t2", "idA"))

    def test_same_content_under_another_item_or_key_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            first = snapshot.take(b, "drive-meet-1ab", "mesma ata\n")          # chave antiga, por documento
            self.assertTrue(first["changed"])
            r = snapshot.take(b, "drive-meet", "mesma ata\n", item="1abFULL")  # agora como item da pasta
            self.assertEqual((r["changed"], r["why"]), (False, "alias"))
            shortcut = snapshot.take(b, "drive-meet", "mesma ata\n", item="atalho")
            self.assertFalse(shortcut["changed"])
            self.assertEqual(len(list(b.inst.inbox.glob("*.md"))), 1)
            # chaves sem --item não se fundem: fontes diferentes com texto igual continuam separadas
            self.assertTrue(snapshot.take(b, "gmail-x", "mesma ata\n")["changed"])


class NoteTests(unittest.TestCase):
    def test_names_links_and_collisions(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "x", "owner": "eu"}})
            names = [notes_mod.create(b, "t", link).name for link in ("a-1", "GOAL-1", "PROJ-1", "PROJ-1.2", "", "PROJ-1")]
            self.assertEqual(names, ["ACT-0001-2026-10-09-note.md", "GOAL-1-2026-10-09-note.md", "PROJ-1-2026-10-09-note.md",
                                     "PROJ-1.2-2026-10-09-note.md", "note-2026-10-09-note.md", "PROJ-1-2026-10-09-note-2.md"])
            got = {n.path.split("/")[-1]: n for n in notes_mod.scan(b.inst)}
            n = got["ACT-0001-2026-10-09-note.md"]
            self.assertEqual((n.link, n.kind, n.created, n.text, n.archived), ("ACT-0001", "ação", "2026-10-09 10:00", "t", False))
            self.assertEqual(got["note-2026-10-09-note.md"].link, "")
            self.assertEqual(got["PROJ-1.2-2026-10-09-note.md"].kind, "entregável")

    def test_rejects_unknown_link_empty_text_and_nightly(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for text, link in (("x", "ACT-0009"), ("x", "PROJ-9"), ("x", "../x"), ("  \n", "")):
                with self.assertRaises(util.BrainError):
                    notes_mod.create(b, text, link)
            os.environ["BRAIN_NIGHTLY"] = "1"
            try:
                with self.assertRaises(util.BrainError):
                    notes_mod.create(b, "x", "")
            finally:
                os.environ.pop("BRAIN_NIGHTLY", None)
            self.assertEqual(list(b.inst.inbox.glob("*")), [])

    def test_archived_notes_in_raw_are_still_found_and_searchable(self):
        from brainlib import search
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            src = notes_mod.create(b, "decidimos usar parquet no pipeline", "PROJ-1")
            dest = b.inst.vault / "RAW" / "2026" / "10"
            dest.mkdir(parents=True)
            src.rename(dest / src.name)                       # o que o /dump faz: mover sem renomear
            (n,) = notes_mod.scan(b.inst)
            self.assertTrue(n.archived)
            self.assertEqual((n.link, n.created), ("PROJ-1", "2026-10-09 10:00"))
            hits = search.search(b, "parquet")
            self.assertEqual([(h["kind"], h["id"]) for h in hits], [("nota", "PROJ-1")])

    def test_search_falls_back_to_any_term_when_all_terms_miss(self):
        from brainlib import search
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            notes_mod.create(b, "decidimos usar parquet no pipeline", "PROJ-1")
            exact = search.search(b, "parquet pipeline")
            self.assertTrue(exact and all("match" not in h for h in exact))
            hits = search.search(b, "parquet zzzinexistente")
            self.assertEqual([(h["kind"], h["id"], h["match"]) for h in hits], [("nota", "PROJ-1", "parcial")])
            self.assertEqual(search.search(b, "zzzinexistente qqqinexistente"), [])
            self.assertEqual(search.search(b, "zzzinexistente"), [])

    def test_edit_only_while_in_inbox(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            path = notes_mod.create(b, "antes", "PROJ-1")
            self.assertEqual(notes_mod.editable_today(b.inst, "PROJ-1").path, b.inst.rel(path))
            self.assertIsNone(notes_mod.editable_today(b.inst, ""))
            notes_mod.update(b, b.inst.rel(path), "depois\n\ncom mais")
            (n,) = notes_mod.scan(b.inst)
            self.assertEqual((n.text, n.created, n.edited, n.link), ("depois\n\ncom mais", "2026-10-09 10:00", "2026-10-09 10:00", "PROJ-1"))
            with self.assertRaises(util.BrainError):
                notes_mod.update(b, "PLANNING/goals.md", "x")           # só nota da inbox
            with self.assertRaises(util.BrainError):
                notes_mod.update(b, "RAW/inbox/../../config/brain.toml", "x")
            dest = b.inst.vault / "RAW" / "2026" / "10"
            dest.mkdir(parents=True)
            path.rename(dest / path.name)
            self.assertIsNone(notes_mod.editable_today(b.inst, "PROJ-1"))   # RAW é imutável
            with self.assertRaises(util.BrainError):
                notes_mod.update(b, f"RAW/2026/10/{path.name}", "x")

    def test_cli_add_and_list(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            env = {**os.environ, "BRAIN_HOME": td}
            run = lambda *a: subprocess.run([sys.executable, str(ROOT / "brain"), *a], capture_output=True, text=True, env=env)  # noqa: E731
            r = run("note", "add", "--link", "PROJ-1", "--text", "oi")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("PROJ-1-2026-10-09-note.md", r.stdout)
            self.assertIn("PROJ-1-2026-10-09-note.md", run("note", "list", "--link", "p1").stdout)
            self.assertEqual(run("note", "add", "--link", "GOAL-9", "--text", "x").returncode, 3)


class RawSortTests(unittest.TestCase):
    CASES = {
        "slack-slack-dm-marina-demo-2026-10-14T185117.md": "slack",
        "drive-drive-meet-gravacoes-onboarding-2026-10-19T183016.md": "meetings",
        "drive-drive-meet-gravacoes-pasta-onboarding-2026-10-19T183017.md": "connectors",
        "drive-drive-meet-gravacoes-2026-10-14T185118.md": "connectors",
        "drive-drive-meet-gravacoes-listagem-x-2026-10-20T143119.json": "connectors",
        "jira-jira-me-2026-10-16T183900.json": "connectors",
        "gcal-gcal-primary-2026-10-09T100000.json": "connectors",
        "reuniao.vtt": "meetings",
        "Relatório Final.PDF": "documents",
        "ata.md": "documents",
        "gravacao.mp4": "videos",
        "audio.m4a": "videos",
        "pagina.html": "artifacts",
        "print.png": "images",
        "PROJ-1-2026-10-09-note.md": "notes",
        "note-2026-10-09-note-2.md": "notes",
        "dados.parquet": "misc",
        ".DS_Store": "misc",
    }

    def test_classify(self):
        for name, want in self.CASES.items():
            self.assertEqual(rawsort.classify(name), want, name)

    def test_archive_moves_inbox_into_type_folder_without_overwriting(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(Path(td))
            for name in ("slack-slack-a-2026-10-09T100000.md", "foto.png", ".keep.md"):
                (inst.inbox / name).write_text("x", encoding="utf-8")
            (inst.vault / "RAW" / "2026" / "10" / "images").mkdir(parents=True)
            (inst.vault / "RAW" / "2026" / "10" / "images" / "foto.png").write_text("antigo", encoding="utf-8")
            moved = rawsort.archive(inst)
            self.assertEqual({m["to"] for m in moved}, {"RAW/2026/10/slack/slack-slack-a-2026-10-09T100000.md",
                                                        "RAW/2026/10/images/foto-2.png"})
            self.assertEqual((inst.vault / "RAW/2026/10/images/foto.png").read_text(encoding="utf-8"), "antigo")
            self.assertEqual([p.name for p in inst.inbox.iterdir()], [".keep.md"])

    def test_archive_forced_type_and_bad_args(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(Path(td))
            (inst.inbox / "ata.md").write_text("x", encoding="utf-8")
            (inst.vault / "PLANNING" / "x.md").write_text("x", encoding="utf-8")
            with self.assertRaises(util.BrainError):
                rawsort.archive(inst, ["ata.md"], "inexistente")
            with self.assertRaises(util.BrainError):
                rawsort.archive(inst, ["PLANNING/x.md"])             # só a inbox é origem
            (m,) = rawsort.archive(inst, ["ata.md"], "meetings", "2026-09-30")
            self.assertEqual(m["to"], "RAW/2026/09/meetings/ata.md")

    def test_sort_existing_is_idempotent_and_old_ledger_paths_still_resolve(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(Path(td))
            month = inst.vault / "RAW" / "2026" / "10"
            month.mkdir(parents=True)
            (month / "slack-slack-a-2026-10-09T100000.md").write_text("s", encoding="utf-8")
            (month / "doc.pdf").write_text("d", encoding="utf-8")
            (month / "[Training] Aula 2026_10_09.mp4").write_text("v", encoding="utf-8")   # colchetes não são glob
            (inst.vault / "RAW" / "2026" / "09").mkdir()
            (inst.vault / "RAW" / "2026" / "09" / "doc.pdf").write_text("outro mês", encoding="utf-8")
            plan = rawsort.sort_existing(inst, dry_run=True)
            self.assertEqual(len(plan), 4)
            self.assertTrue((month / "doc.pdf").exists())            # simulação não move
            self.assertEqual(len(rawsort.sort_existing(inst)), 4)
            self.assertEqual(rawsort.sort_existing(inst), [])
            self.assertFalse((month / "doc.pdf").exists())
            self.assertEqual(rawsort.resolve(inst, "RAW/2026/10/doc.pdf"), month / "documents" / "doc.pdf")
            self.assertEqual(rawsort.resolve(inst, "RAW/2026/09/doc.pdf").read_text(encoding="utf-8"), "outro mês")
            self.assertEqual(rawsort.resolve(inst, "RAW/2026/10/[Training] Aula 2026_10_09.mp4"),
                             month / "videos" / "[Training] Aula 2026_10_09.mp4")
            self.assertIsNone(rawsort.resolve(inst, "RAW/2026/10/nao-existe.pdf"))
            self.assertTrue(list(inst.logs.glob("raw-sort-*.jsonl")))

    def test_notes_and_calendar_snapshots_are_found_in_type_folders(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            src = notes_mod.create(b, "nota arquivada por tipo", "PROJ-1")
            rawsort.archive(b.inst)
            (n,) = notes_mod.scan(b.inst)
            self.assertTrue(n.archived)
            self.assertEqual(n.path, f"RAW/2026/10/notes/{src.name}")
            conn = b.inst.vault / "RAW" / "2026" / "10" / "connectors"
            conn.mkdir(parents=True, exist_ok=True)
            (conn / "gcal-gcal-primary-2026-10-09T100000.json").write_text("{}", encoding="utf-8")
            self.assertEqual(focus.latest_calendar_snapshot(b.inst.vault).name, "gcal-gcal-primary-2026-10-09T100000.json")


class PlanAddTests(unittest.TestCase):
    def _run(self, td, *a):
        env = {**os.environ, "BRAIN_HOME": td}
        return subprocess.run([sys.executable, str(ROOT / "brain"), *a], capture_output=True, text=True, env=env)

    def test_ids_placement_and_gate(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            goals = b.inst.planning_file
            self.assertEqual(self._run(td, "plan", "add-project", "GOAL-1", "Sem ok").returncode, 4)   # gate sem aprovação
            self.assertNotIn("Sem ok", goals.read_text(encoding="utf-8"))
            r = self._run(td, "plan", "add-project", "GOAL-1", "Segundo", "--approval", "ok")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self._run(td, "plan", "add-goal", "Outro goal", "--horizon", "2027-01-01", "--approval", "ok")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._run(td, "plan", "add-deliverable", "PROJ-2", "Algo", "--due", "2026-12-01", "--weight", "2").returncode, 0)
            self.assertEqual(self._run(td, "plan", "add-deliverable", "PROJ-1", "Terceiro").returncode, 0)
            self.assertEqual(self._run(td, "plan", "add-deliverable", "PROJ-1", "x · y").returncode, 3)
            self.assertEqual(self._run(td, "plan", "add-project", "GOAL-9", "x", "--approval", "ok").returncode, 3)
            plan = planning.load(goals)
            self.assertEqual(plan.warnings, [])
            self.assertEqual((plan.projects["PROJ-2"].goal_id, plan.deliverables["PROJ-2.1"].weight), ("GOAL-1", 2))
            self.assertEqual(plan.deliverables["PROJ-1.3"].project_id, "PROJ-1")             # entra no fim do PROJ-1, antes do PROJ-2
            self.assertEqual(plan.goals["GOAL-2"].title, "Outro goal")
            self.assertEqual(list(plan.projects), ["PROJ-1", "PROJ-2"])
            self.assertEqual(Brain(b.inst).validate_all(), [])
            log = b.inst.planning_log.read_text(encoding="utf-8")
            self.assertIn('PROJ-2 projeto criado sob GOAL-1', log)
            self.assertIn('aprovado: "ok"', log)
            self.assertEqual(sum(1 for e in Brain(b.inst).read_events() if e["type"] == "plan.changed"), 2)

    def test_edit_gate_and_factual(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            goals = b.inst.planning_file
            before = goals.read_text(encoding="utf-8")
            self.assertEqual(self._run(td, "plan", "edit", "GOAL-1", "--title", "Sem ok").returncode, 4)   # gate sem aprovação
            self.assertEqual(goals.read_text(encoding="utf-8"), before)
            self.assertEqual(self._run(td, "plan", "edit", "GOAL-9", "--title", "x", "--approval", "ok").returncode, 3)
            self.assertEqual(self._run(td, "plan", "edit", "GOAL-1").returncode, 3)                           # nada para mudar
            self.assertEqual(self._run(td, "plan", "edit", "GOAL-1", "--due", "2026-12-01", "--approval", "ok").returncode, 3)  # campo de outro tipo
            r = self._run(td, "plan", "edit", "GOAL-1", "--title", "Goal renomeado", "--horizon", "2027-03-01",
                          "--status", "congelado", "--reason", "pausa", "--approval", "ok")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self._run(td, "plan", "edit", "PROJ-1", "--title", "Projeto renomeado", "--approval", "ok")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self._run(td, "plan", "edit", "PROJ-1.1", "--title", "Entregável novo", "--due", "2026-12-15", "--weight", "3")   # sem gate
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self._run(td, "plan", "edit", "PROJ-1.1", "--title", "a · b").returncode, 3)
            plan = planning.load(goals)
            self.assertEqual(plan.warnings, [])
            self.assertEqual((plan.goals["GOAL-1"].title, plan.goals["GOAL-1"].horizon, plan.goals["GOAL-1"].status),
                             ("Goal renomeado", "2027-03-01", "congelado"))
            d = plan.deliverables["PROJ-1.1"]
            self.assertEqual((plan.projects["PROJ-1"].title, d.title, d.due, d.weight),
                             ("Projeto renomeado", "Entregável novo", date(2026, 12, 15), 3))
            self.assertEqual(Brain(b.inst).validate_all(), [])
            self.assertEqual(sum(1 for e in Brain(b.inst).read_events() if e["type"] == "plan.changed"), 2)
            log = b.inst.planning_log.read_text(encoding="utf-8")
            self.assertIn("GOAL-1 editado", log)
            self.assertIn("PROJ-1.1 entregável editado", log)

    def test_edit_nightly_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            env = {**os.environ, "BRAIN_HOME": td, "BRAIN_NIGHTLY": "1"}
            r = subprocess.run([sys.executable, str(ROOT / "brain"), "plan", "edit", "PROJ-1.1", "--title", "x"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 4)

    def test_nightly_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            env = {**os.environ, "BRAIN_HOME": td, "BRAIN_NIGHTLY": "1"}
            r = subprocess.run([sys.executable, str(ROOT / "brain"), "plan", "add-goal", "x", "--approval", "ok"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 4)


class GcalTests(unittest.TestCase):
    def test_delete_without_mark_refused(self):
        calls = []

        def http(method, url, body, headers):
            calls.append((method, url, body))
            if method == "GET":
                return 200, {"id": "evt1", "extendedProperties": {"private": {}}}
            return 200, {}

        cal = GoogleCalendar(_inst(Path(tempfile.mkdtemp())), http=http, token="t")
        with self.assertRaises(util.BrainError):
            cal.delete_guarded("evt1", "ACT-0001")
        self.assertFalse(any(c[0] == "DELETE" for c in calls))

    def test_insert_falls_back_without_focustime(self):
        n = {"i": 0}

        def http(method, url, body, headers):
            n["i"] += 1
            if n["i"] == 1:
                raise util.BrainError("Google Calendar POST /events → 400: invalid eventType focusTime", code=2)
            self.assertNotIn("eventType", body)
            return 200, {"id": "e2", "htmlLink": "http://x"}

        cal = GoogleCalendar(_inst(Path(tempfile.mkdtemp())), http=http, token="t")
        ev = cal.insert_focus({"action": "A-1", "start": "2026-10-09T14:00:00-03:00",
                               "end": "2026-10-09T15:00:00-03:00"}, "F-1", "Foco", "d", "no")
        self.assertEqual(ev["id"], "e2")


class NightlyGateTests(unittest.TestCase):
    def test_forbids_approval(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ev = outbox.draft(b, "marina-demo", "oi", None, None)
            os.environ["BRAIN_NIGHTLY"] = "1"
            try:
                with self.assertRaises(util.BrainError):
                    outbox.approve(b, ev["id"], "ok")
            finally:
                os.environ.pop("BRAIN_NIGHTLY", None)


class ShareMcpRenderTests(unittest.TestCase):
    def test_share_and_mcp_and_render(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.record_one({"type": "action.opened", "by": "owner",
                          "data": {"title": "Enviar draft", "owner": "eu", "due": "2026-10-11",
                                   "effort_min": 45, "project": "PROJ-1"}})
            b.record_one({"type": "decision.made", "by": "agent", "prov": "observado", "source": "chat",
                          "data": {"title": "Draft sai sem pipeline", "decided_by": ["marina-demo"],
                                   "project": "PROJ-1"}})
            report = render.render_all(b, do_harvest=False)
            self.assertGreater(report["total"], 8)
            self.assertTrue(Path(report["dashboard"]).is_file())
            html = Path(report["dashboard"]).read_text(encoding="utf-8")
            self.assertNotIn("__DATA__", html)
            self.assertIn("Enviar draft", html)

            path = share.export(b, "project", "PROJ-1", "md")
            text = path.read_text(encoding="utf-8")
            self.assertIn("Draft sai sem pipeline", text)
            self.assertIn("Marina-demo", text)
            self.assertIn("peso", text)
            (b.inst.reports / "share").mkdir(parents=True, exist_ok=True)
            outside = b.inst.config_dir / ".env"
            outside.write_text("GOOGLE_CLIENT_SECRET=nope\n", encoding="utf-8")
            with self.assertRaises(util.BrainError):
                share._file_sha(b, "reports/../../config/.env")

            os.environ["BRAIN_HOME"] = str(b.inst.root)
            try:
                ov = mcp_server.call_tool("brain_overview", {})
                self.assertEqual(ov["today"], "2026-10-09")
                self.assertTrue(any(g["id"] == "GOAL-1" for g in ov["goals"]))
            finally:
                os.environ.pop("BRAIN_HOME", None)

            init = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "2025-03-26"}})
            self.assertEqual(init["result"]["serverInfo"]["name"], "segundo-cerebro")
            listed = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            names = {t["name"] for t in listed["result"]["tools"]}
            self.assertIn("brain_overview", names)
            self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in listed["result"]["tools"]))


class DemoTests(unittest.TestCase):
    def test_demo_renders(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "demo"
            demo_mod.build(target)
            b = Brain(config.load(target))
            self.assertGreater(len(b.state.actions), 5)
            self.assertEqual(b.validate_all(), [])
            report = render.render_all(b)
            dash = Path(report["dashboard"]).read_text(encoding="utf-8")
            self.assertIn("Reforma do novo ponto", dash)
            self.assertIn("Marina-demo", dash)
            self.assertTrue((target / "vault" / "FRESH" / "todo.md").exists())
            self.assertTrue((target / "vault" / "FRESH" / "dashboard" / "index.html").exists())
            self.assertFalse((target / "vault" / "FRESH" / "bases").exists())
            st = b.state
            self.assertEqual((len(st.areas), len(st.processes), len(st.opportunities)), (3, 3, 6))
            self.assertEqual(st.opportunities["OPP-0003"].status, "em-andamento")        # uma promovida, ligada a PROJ-3/GOAL-2
            self.assertEqual((st.opportunities["OPP-0003"].project, st.opportunities["OPP-0003"].goal), ("PROJ-3", "GOAL-2"))
            self.assertTrue(st.opportunities["OPP-0002"].ice_suggested)
            self.assertEqual(st.processes["PROC-0001"].hours_month, 21 * 3 * 2)
            self.assertTrue((target / "vault" / "FRESH" / "opportunities.md").exists())
            self.assertIn("Portfólio", dash)
            self.assertTrue((target / "vault" / "FRESH" / "projects" / "PROJ-1.md").exists())




class FakeHindsight(memory.Hindsight):
    """Hindsight em memória: retain assíncrono abre uma operação; o teste decide como ela termina."""

    def __init__(self):
        super().__init__("http://fake")
        self.ops: dict[str, dict] = {}   # op_id → {bank, document_id, status, created_at, updated_at}
        self.sent: list[tuple[str, str]] = []
        self.calls = 0
        self.clock = 0
        self.bank_stats: dict[str, dict] = {}   # bank → campos extras de /stats (pending_consolidation…)

    def _add(self, bank: str, doc: str, status: str = "processing", op_type: str = "retain") -> str:
        self.clock += 1
        op_id = f"op-{len(self.ops) + 1}"
        t = (datetime(2026, 10, 9, 9, 0) + timedelta(minutes=self.clock)).isoformat() + "+00:00"
        self.ops[op_id] = {"id": op_id, "bank": bank, "document_id": doc, "status": status,
                           "operation_type": op_type, "created_at": t, "updated_at": t}
        return op_id

    def health(self):
        return {"status": "healthy"}

    def stats(self, bank):
        return {"bank_id": bank, **self.bank_stats.get(bank, {})}

    def retain(self, bank, items, async_=True):
        self.calls += 1
        self.sent.append((bank, items[0]["document_id"]))
        return {"success": True, "bank_id": bank, "items_count": 1, "async": True,
                "operation_id": self._add(bank, items[0]["document_id"])}

    def operation(self, bank, op_id):
        o = self.ops.get(op_id)
        return {"operation_id": op_id, "status": o["status"]} if o else {"operation_id": op_id, "status": "not_found"}

    def operations(self, bank, status, page=100, max_pages=20):
        return [dict(o) for o in self.ops.values() if o["bank"] == bank and o["status"] == status]

    def finish(self, doc: str, status: str, bank: str = "brain-mem"):
        for o in self.ops.values():
            if o["bank"] == bank and o["document_id"] == doc and o["status"] == "processing":
                o["status"] = status


class MemorySyncTests(unittest.TestCase):
    def _setup(self, td):
        b = _brain(Path(td))
        return b, FakeHindsight()

    def test_setup_keeps_both_banks_llm_free(self):
        class Rec:
            def __init__(self):
                self.cfg = {}

            def put_bank(self, bank, body):
                pass

            def patch_config(self, bank, cfg):
                self.cfg[bank] = cfg

        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            hs = Rec()
            memory.setup(b, hs=hs)
            self.assertEqual(len(hs.cfg), 2)
            for cfg in hs.cfg.values():
                self.assertEqual(cfg, {"retain_extraction_mode": "chunks", "enable_auto_consolidation": False,
                                       "enable_observations": False})
            self.assertEqual(len(hs.cfg), 2)

    def test_sync_records_operation_ids(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            res = memory.sync(b, hs=hs)
            self.assertGreater(res["sent"], 0)
            self.assertEqual(res["remaining"], 0)
            state = util.read_json(memory._state_path(b), {})
            self.assertTrue(state[memory.OPS_KEY]["mem"]["PLANNING/goals.md"]["ids"])

    def test_failed_async_retain_is_resent(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            memory.sync(b, hs=hs)
            hs.finish("PLANNING/goals.md", "failed")
            for o in hs.ops.values():
                if o["status"] == "processing":
                    o["status"] = "completed"
            hs.sent.clear()
            res = memory.sync(b, hs=hs)
            self.assertEqual(res["resent"], ["mem:PLANNING/goals.md"])
            self.assertEqual(hs.sent, [("brain-mem", "PLANNING/goals.md")])
            self.assertEqual(res["remaining"], 0)
            # o reenvio ainda em andamento não dispara novo reenvio
            hs.sent.clear()
            self.assertEqual(memory.sync(b, hs=hs)["resent"], [])
            self.assertEqual(hs.sent, [])

    def test_legacy_state_uses_failed_list(self):
        """Estado de antes do rastreio (sem _ops): a lista status=failed do servidor decide."""
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            memory.sync(b, hs=hs)
            for o in hs.ops.values():
                o["status"] = "completed"
            hs._add("brain-mem", "PLANNING/goals.md", "failed")   # falha mais nova que o retain concluído
            hs._add("brain-mem", "profile-velho.md", "failed")    # documento fora do estado: ignorado
            state = util.read_json(memory._state_path(b), {})
            state.pop(memory.OPS_KEY)
            util.write_json(memory._state_path(b), state)
            hs.sent.clear()
            res = memory.sync(b, hs=hs)
            self.assertEqual(res["resent"], ["mem:PLANNING/goals.md"])
            self.assertEqual(hs.sent, [("brain-mem", "PLANNING/goals.md")])

    def test_old_failure_superseded_by_later_success_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            hs._add("brain-mem", "PLANNING/goals.md", "failed")
            memory.sync(b, hs=hs)
            for o in hs.ops.values():
                o["status"] = "completed" if o["status"] == "processing" else o["status"]
            hs.sent.clear()
            res = memory.sync(b, hs=hs)
            self.assertEqual(res["resent"], [])
            self.assertEqual(memory.op_problems(b, hs)["failed"], [])

    def test_gives_up_after_max_tries(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            memory.sync(b, hs=hs)
            for _ in range(memory.MAX_TRIES):
                hs.finish("PLANNING/goals.md", "failed")
                self.assertEqual(memory.sync(b, hs=hs)["resent"], ["mem:PLANNING/goals.md"])
            hs.finish("PLANNING/goals.md", "failed")
            res = memory.sync(b, hs=hs)
            self.assertEqual(res["resent"], [])
            self.assertEqual(res["gave_up"], ["mem:PLANNING/goals.md"])
            self.assertEqual(memory.op_problems(b)["gave_up"], ["mem:PLANNING/goals.md"])

    def test_dry_run_does_not_touch_server(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            res = memory.sync(b, dry_run=True, hs=hs)
            self.assertTrue(res["would_send"])
            self.assertEqual(hs.calls, 0)

    def test_status_and_doctor_warn_on_failed_and_stuck(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            b.inst.cfg["memory"]["engine"] = "hindsight"
            memory.sync(b, hs=hs)
            for o in hs.ops.values():
                o["status"] = "completed"
            self.assertEqual(memory.status(b, online=True, hs=hs)["level"], "ok")
            # falha no servidor, ainda sem ter passado por um sync
            hs._add("brain-mem", "PLANNING/goals.md", "failed")
            s = memory.status(b, online=True, hs=hs)
            self.assertEqual(s["level"], "warn")
            self.assertIn("mem:PLANNING/goals.md", s["detail"])
            # operação parada em processing há mais de 2h (BRAIN_NOW = 2026-10-09T10:00-03:00 = 13:00Z)
            hs.ops[hs._add("brain-raw", "RAW/x.md", "processing")]["updated_at"] = "2026-10-09T10:30:00+00:00"
            s = memory.status(b, online=True, hs=hs)
            self.assertEqual(len(s["problems"]["stuck"]), 1)
            self.assertIn("processamento há mais de 2h", s["detail"])
            hs.ops[hs._add("brain-raw", "RAW/y.md", "processing")]["updated_at"] = "2026-10-09T12:30:00+00:00"
            self.assertEqual(len(memory.status(b, online=True, hs=hs)["problems"]["stuck"]), 1)

    def test_status_shows_queue(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            b.inst.cfg["memory"]["engine"] = "hindsight"
            memory.sync(b, hs=hs)
            for o in hs.ops.values():
                o["status"] = "completed"
            s = memory.status(b, online=True, hs=hs)
            self.assertIn("fila: vazia — LLM livre", s["queue_text"])
            hs._add("brain-mem", None, "processing", "consolidation")
            hs._add("brain-mem", None, "pending", "consolidation")
            hs._add("brain-raw", "RAW/x.md", "pending")
            hs.bank_stats["brain-mem"] = {"pending_consolidation": 12, "failed_consolidation": 3}
            s = memory.status(b, online=True, hs=hs)
            self.assertEqual(s["queue"]["brain-mem"]["ops"]["consolidation"], {"processing": 1, "pending": 1})
            self.assertIn("fila: ocupada", s["queue_text"])
            self.assertIn("consolidation 1 rodando + 1 na fila", s["queue_text"])
            self.assertIn("12 memórias aguardando consolidação", s["queue_text"])
            self.assertIn("brain-raw: retain 1 na fila", s["queue_text"])
            # consolidação que desistiu vira aviso
            self.assertEqual(s["level"], "warn")
            self.assertIn("brain-mem 3", s["detail"])

    def test_backlog_without_consolidation_op_is_not_busy(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            b.inst.cfg["memory"]["engine"] = "hindsight"
            memory.sync(b, hs=hs)
            for o in hs.ops.values():
                o["status"] = "completed"
            hs.bank_stats["brain-mem"] = {"pending_consolidation": 136}     # consolidação desligada: backlog parado
            s = memory.status(b, online=True, hs=hs)
            self.assertIn("fila: vazia — LLM livre", s["queue_text"])
            self.assertEqual(s["queue"]["brain-mem"]["pending_consolidation"], 0)

    def test_doctor_warns_offline_from_recorded_failures(self):
        with tempfile.TemporaryDirectory() as td:
            b, hs = self._setup(td)
            b.inst.cfg["memory"]["engine"] = "hindsight"
            memory.sync(b, hs=hs)
            hs.finish("PLANNING/goals.md", "failed")
            state = util.read_json(memory._state_path(b), {})
            memory.reconcile(b, hs, state)
            util.write_json(memory._state_path(b), state)
            mem_check = [c for c in doctor.checks(b) if c["title"] == "memória"][0]
            self.assertEqual(mem_check["level"], "warn")
            self.assertIn("retain falho", mem_check["detail"])


class ScanDemoTokenTests(unittest.TestCase):
    def test_demo_suffix_is_not_a_leak(self):
        import re
        res = [("pessoa", re.compile(r"(?<!\w)marina(?!\w)", re.I))]
        self.assertTrue(upstream._scan_line("falei com a Marina ontem", res, ""))
        self.assertFalse(upstream._scan_line("falei com a Marina-demo ontem, id marina-demo", res, ""))
        self.assertFalse(upstream._scan_line("marina-demo@example.com", res, ""))


class UpstreamTests(unittest.TestCase):
    """update/upstream contra repos git locais: um remoto bare, um mantenedor (A) e uma instância (B)."""

    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                                                    "GIT_COMMITTER_EMAIL", "BRAIN_NIGHTLY")}
        os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org",
                          GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")
        os.environ.pop("BRAIN_NIGHTLY", None)
        self._td = tempfile.TemporaryDirectory()
        tmp = Path(self._td.name)
        self.remote, self.a, self.b = tmp / "remote.git", tmp / "a", tmp / "b"
        self._git(tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self._git(tmp, "clone", "-q", str(self.remote), str(self.a))
        (self.a / "brainlib").mkdir()
        (self.a / "brainlib" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
        (self.a / "brain").write_text("print('doctor ok')\n", encoding="utf-8")
        (self.a / "template" / "PROFILE").mkdir(parents=True)
        (self.a / "template" / "PROFILE" / "me.md").write_text("modelo v1\n", encoding="utf-8")
        (self.a / ".gitignore").write_text("/vault/\nconfig/brain.toml\nconfig/.env\n", encoding="utf-8")
        self._commit(self.a, "base")
        self._git(self.a, "push", "-q", "origin", "HEAD:main")
        self._git(tmp, "clone", "-q", str(self.remote), str(self.b))
        (self.b / "config").mkdir()
        (self.b / "config" / "brain.toml").write_text('[owner]\nid = "dona"\nname = "Fulana Quiteria"\n', encoding="utf-8")
        (self.b / "vault" / "PROFILE").mkdir(parents=True)
        (self.b / "vault" / "PROFILE" / "me.md").write_text("meu texto\n", encoding="utf-8")
        self.inst = config.load(self.b)

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._td.cleanup()

    @staticmethod
    def _git(cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout

    def _commit(self, repo, msg):
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", msg)

    def _upstream_release(self):
        (self.a / "template" / "PROFILE" / "me.md").write_text("modelo v2\n", encoding="utf-8")
        (self.a / "template" / "PROFILE" / "novo.md").write_text("novo\n", encoding="utf-8")
        (self.a / "brainlib" / "__init__.py").write_text('__version__ = "1.1.0"\n', encoding="utf-8")
        self._commit(self.a, "v1.1")
        self._git(self.a, "push", "-q", "origin", "HEAD:main")

    def test_update_check_does_nothing_then_apply_seeds_without_overwriting(self):
        self._upstream_release()
        res = upstream.update(self.inst, check=True)
        self.assertEqual((res["behind"], res["updated"]), (1, False))
        self.assertEqual(_read(self.b / "brainlib" / "__init__.py"), '__version__ = "1.0.0"\n')
        res = upstream.update(self.inst)
        self.assertTrue(res["updated"])
        self.assertEqual((res["version_before"], res["version_after"]), ("1.0.0", "1.1.0"))
        self.assertEqual(_read(self.b / "vault" / "PROFILE" / "novo.md"), "novo\n")
        self.assertEqual(_read(self.b / "vault" / "PROFILE" / "me.md"), "meu texto\n")
        self.assertEqual(res["template_diverged"], ["vault/PROFILE/me.md"])
        self.assertTrue(res["doctor_ok"])
        self.assertEqual(upstream.update(self.inst)["behind"], 0)

    def test_update_works_when_clone_has_no_fetch_refspec(self):
        self._git(self.b, "config", "--unset-all", "remote.origin.fetch")
        self._upstream_release()
        self.assertEqual(upstream.update(self.inst, check=True)["behind"], 1)
        self.assertTrue(upstream.update(self.inst)["updated"])
        self.assertEqual(upstream.update(self.inst, check=True)["behind"], 0)

    def test_update_diverged_needs_rebase(self):
        (self.b / "brainlib" / "extra.py").write_text("x = 1\n", encoding="utf-8")
        self._commit(self.b, "local")
        self._upstream_release()
        with self.assertRaises(util.BrainError) as cm:
            upstream.update(self.inst)
        self.assertEqual(cm.exception.code, 2)
        res = upstream.update(self.inst, rebase=True)
        self.assertEqual((res["updated"], res["ahead"]), (True, 1))
        self.assertTrue((self.b / "brainlib" / "extra.py").exists())
        self.assertEqual(upstream.upstream_scan(self.inst)["ahead"], 1)

    def test_update_refuses_when_vault_is_tracked(self):
        self._git(self.b, "add", "-f", "vault/PROFILE/me.md")
        with self.assertRaises(util.BrainError) as cm:
            upstream.update(self.inst, check=True)
        self.assertIn("vault/PROFILE/me.md", str(cm.exception))

    def _leaky_file(self):
        home_path = "/" + "Users" + "/alguem/projeto"
        token = "xox" + "b-" + "1234567890-abcdef"
        (self.b / "brainlib" / "leak.py").write_text(
            f"# feito por Fulana Quiteria\nPATH = '{home_path}'\nTOKEN = '{token}'\n", encoding="utf-8")

    def test_scan_clean_change_has_no_findings(self):
        (self.b / "brainlib" / "feature.py").write_text("x = 1\n", encoding="utf-8")
        st = upstream.upstream_scan(self.inst)
        self.assertEqual((st["findings"], st["new"]), ([], ["brainlib/feature.py"]))

    def test_scan_flags_personal_data_secret_and_machine_path(self):
        self._leaky_file()
        rules = {f["rule"] for f in upstream.upstream_scan(self.inst)["findings"]}
        self.assertEqual(rules, {"dado pessoal (dono)", "caminho da máquina", "token do Slack"})

    def test_scan_ignores_placeholders_and_container_paths(self):
        (self.b / "doc.md").write_text(
            "https://seu-workspace.slack.com/archives/C1\n/home/postgres/data\n/" + "Users" + "/you/x\n", encoding="utf-8")
        self.assertEqual(upstream.upstream_scan(self.inst)["findings"], [])

    def test_scan_covers_commit_messages_and_committed_mode_skips_worktree(self):
        (self.b / "brainlib" / "ok.py").write_text("x = 1\n", encoding="utf-8")
        self._commit(self.b, "ajuste pedido por Fulana Quiteria")
        self._leaky_file()
        self.assertEqual({f["file"] for f in upstream.upstream_scan(self.inst, committed=True)["findings"]},
                         {"(mensagem de commit)"})
        self.assertIn("brainlib/leak.py", {f["file"] for f in upstream.upstream_scan(self.inst)["findings"]})

    def test_committed_scan_sees_leak_even_if_a_later_commit_removes_it(self):
        (self.b / "doc.md").write_text("contato: Fulana Quiteria\n", encoding="utf-8")
        self._commit(self.b, "adiciona")
        (self.b / "doc.md").write_text("contato: alguem\n", encoding="utf-8")
        self._commit(self.b, "limpa")
        self.assertEqual(upstream.upstream_scan(self.inst)["findings"], [])  # diff líquido está limpo
        found = upstream.upstream_scan(self.inst, committed=True)["findings"]
        self.assertEqual(len(found), 1)
        self.assertIn("commit", found[0]["file"])

    def test_hook_blocks_real_git_push_with_leak_and_allows_clean(self):
        self.assertEqual(upstream.hook(self.inst, "install"), "instalado")
        hook = upstream._hook_path(self.b)
        self.assertTrue(os.access(hook, os.X_OK))
        # o hook chama ./brain da instância: aponta para o CLI real deste repo
        (self.b / "brain").write_text(
            f"#!/bin/sh\nBRAIN_HOME={self.b} exec {sys.executable} {ROOT / 'brain'} \"$@\"\n", encoding="utf-8")
        (self.b / "brain").chmod(0o755)
        self._git(self.b, "update-index", "--assume-unchanged", "brain")
        (self.b / "brainlib" / "leak.py").write_text("# Fulana Quiteria\n", encoding="utf-8")
        self._commit(self.b, "vaza")
        bad = subprocess.run(["git", "-C", str(self.b), "push", "origin", "HEAD:main"], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("push bloqueado", bad.stderr)
        self._git(self.b, "reset", "-q", "--hard", "origin/main")
        (self.b / "brainlib" / "feature.py").write_text("x = 1\n", encoding="utf-8")
        self._commit(self.b, "ok")
        good = subprocess.run(["git", "-C", str(self.b), "push", "origin", "HEAD:main"], capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)

    def test_hook_install_respects_foreign_hook_and_remove(self):
        path = upstream._hook_path(self.b)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\necho meu\n", encoding="utf-8")
        self.assertEqual(upstream.hook(self.inst, "install"), "de-outro")
        self.assertIn("echo meu", _read(path))
        path.unlink()
        self.assertEqual(upstream.hook(self.inst, "install"), "instalado")
        self.assertEqual(upstream.hook(self.inst, "remove"), "ausente")

    def test_doctor_reports_pending_and_missing_hook(self):
        (self.b / "brainlib" / "feature.py").write_text("x = 1\n", encoding="utf-8")
        got = {c["title"]: c["level"] for c in upstream.doctor_checks(self.inst)}
        self.assertEqual(got, {"framework": "warn", "hook pre-push": "warn"})
        self._git(self.b, "add", "-A")
        self._git(self.b, "commit", "-q", "-m", "x")
        self._git(self.b, "push", "-q", "origin", "HEAD:main")
        upstream.hook(self.inst, "install")
        self.assertEqual({c["level"] for c in upstream.doctor_checks(self.inst)}, {"ok"})


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class SchemaCoverageTests(unittest.TestCase):
    def test_unknown_type(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "action.exploded", "by": "owner", "data": {}})


class PdfTest(unittest.TestCase):
    @staticmethod
    def _pdf(path: Path, text: str) -> None:
        stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
                b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        out, offs = b"%PDF-1.4\n", []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        out += b"".join(b"%010d 00000 n \n" % o for o in offs)
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
        path.write_bytes(out)

    def test_parse_pages(self):
        from brainlib import pdf
        self.assertEqual(pdf.parse_pages("1-3,5"), [1, 2, 3, 5])
        self.assertEqual(pdf.parse_pages(None), [])
        for bad in ("0", "3-1", "a", "1-"):
            with self.assertRaises(util.BrainError, msg=bad):
                pdf.parse_pages(bad)

    def test_missing_file_and_no_reader_give_clear_errors(self):
        from unittest import mock
        from brainlib import pdf
        with self.assertRaises(util.BrainError) as cm:
            pdf.text("/nao/existe.pdf")
        self.assertEqual(cm.exception.code, 3)
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.pdf"
            self._pdf(f, "Ola")
            with mock.patch("shutil.which", return_value=None), mock.patch.object(pdf, "_swift_tool", return_value=None), \
                 mock.patch.dict(sys.modules, {"pypdf": None}):
                with self.assertRaises(util.BrainError) as cm:
                    pdf.text(f)
            self.assertIn("poppler", str(cm.exception))

    @unittest.skipUnless(sys.platform == "darwin" and __import__("shutil").which("swiftc"), "precisa de macOS com swiftc")
    def test_pdfkit_fallback_reads_text_and_renders_png(self):
        from unittest import mock
        from brainlib import pdf
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / " Glossário teste.pdf"       # espaço no começo e acento: o arquivo do RAW nunca é renomeado
            self._pdf(f, "Glossario Exemplo")
            with mock.patch("shutil.which", side_effect=lambda n: {"swiftc": "/usr/bin/swiftc", "swift": "/usr/bin/swift"}.get(n)):
                self.assertIn("=== PÁGINA 1 ===", pdf.text(f))
                self.assertIn("Glossario Exemplo", pdf.text(f, [1]))
                pngs = pdf.render(f, [1], Path(td) / "out", dpi=40)
            self.assertEqual([p.name for p in pngs], ["pagina-001.png"])
            self.assertTrue(pngs[0].read_bytes().startswith(b"\x89PNG"))


class VideoTest(unittest.TestCase):
    def test_parse_and_merge_pick_the_language_actually_spoken_each_minute(self):
        from brainlib import video
        pt = video.parse("[00:00:05] Oi gente, vocês também estão aqui? Não sei, então vamos começar\n"
                         "[00:01:10] Nosotros vamos a hablar de los datos y de las reglas\n")
        es = video.parse("[00:00:05] Oi gente voces tambien esta aqui no se entonces\n"
                         "[00:01:10] Nosotros vamos a hablar de los datos y de las reglas del negocio y también de usted\n")
        merged = video.merge({"pt-BR": pt, "es-MX": es})
        self.assertEqual([(t, loc) for t, _, loc in merged], [(5, "pt-BR"), (70, "es-MX")])

    def test_missing_file_and_wrong_platform_are_clear_errors(self):
        from unittest import mock
        from brainlib import video
        with self.assertRaises(util.BrainError) as cm:
            video.transcribe("/nao/existe.mp4")
        self.assertEqual(cm.exception.code, 3)
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.mp4"
            f.write_bytes(b"x")
            with mock.patch.object(video, "swift_tool", return_value=None):
                with self.assertRaises(util.BrainError) as cm:
                    video.frames(f)
            self.assertIn("macOS", str(cm.exception))


class SnapshotEmptyTest(unittest.TestCase):
    def test_empty_window_counts_as_a_successful_pull_not_a_failure(self):
        import argparse
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ns = dict(key="slack-x", prefix=None, ext="md", file=None, fail=None, item=None, rev=None, name=None,
                      check=False, empty=True, json=False)
            snapshot.cli(argparse.Namespace(**ns), b)
            c = b.state.connectors["slack-x"]
            self.assertTrue(c.last_ok)
            self.assertEqual(c.consecutive_failures, 0)
            self.assertEqual(list(b.inst.inbox.glob("*slack*")), [])


class RunnerTest(unittest.TestCase):
    def test_nightly_claude_gets_only_runner_allow(self):
        from unittest import mock
        from brainlib import runner
        cfg = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "agent": "claude", "allow": ["mcp__x__ler"]},
                                 "tui": {"agent_allow": ["mcp__x__enviar"]}}
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            argv = runner.agent_command(cfg)
        self.assertEqual(argv[-1], "mcp__x__ler")
        self.assertNotIn("mcp__x__enviar", argv)  # escrita do TUI nunca vai pro noturno

    def test_launchd_plist_runs_nightly_at_requested_time(self):
        import argparse
        import plistlib
        from unittest import mock
        from brainlib import runner
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td) / "i")
            plist = Path(td) / "nightly.plist"
            calls: list[tuple] = []

            def fake_launchctl(*a):
                calls.append(a)
                return subprocess.CompletedProcess(a, 0, "", "")

            with mock.patch.object(runner, "_launchd_plist", return_value=plist), \
                 mock.patch.object(runner, "_launchctl", side_effect=fake_launchctl), \
                 mock.patch.object(runner, "_crontab", return_value=[]):
                runner._schedule_launchd(argparse.Namespace(action="install", time="05:30"), b)
                data = plistlib.loads(plist.read_bytes())
                self.assertEqual(data["StartCalendarInterval"], {"Hour": 5, "Minute": 30})
                self.assertEqual(data["ProgramArguments"][1:], ["nightly"])
                self.assertEqual(calls[-1][0], "bootstrap")
                runner._schedule_launchd(argparse.Namespace(action="remove", time="05:00"), b)
                self.assertFalse(plist.exists())


class PortfolioStateTests(unittest.TestCase):
    """Passo 1 do portfólio: áreas, processos, oportunidades, ICE e documentos no ledger."""

    def _b(self, td):
        b = _brain(Path(td))
        b.record_one({"type": "area.added", "id": "operacoes", "by": "owner", "data": {"name": "Operações"}})
        b.record_one({"type": "area.added", "id": "growth", "by": "owner", "data": {"name": "Growth"}})
        return b

    def _proc(self, b, **data):
        base = {"title": "Fechamento mensal", "area": "operacoes", "owner": "eu"}
        return b.record_one({"type": "process.added", "by": "owner", "data": {**base, **data}})

    def _opp(self, b, **kw):
        ev = {"type": "opportunity.added", "by": "owner",
              "data": {"title": "Automatizar conciliação", "area": "operacoes", **kw.pop("data", {})}}
        ev.update(kw)
        return b.record_one(ev)

    def test_area_and_ids(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._b(td)
            self.assertEqual(list(b.state.areas), ["operacoes", "growth"])
            with self.assertRaises(util.BrainError):                    # área duplicada
                b.record_one({"type": "area.added", "id": "growth", "by": "owner", "data": {"name": "G"}})
            with self.assertRaises(util.BrainError):                    # área inexistente
                self._proc(b, area="nao-existe")
            self.assertEqual(self._proc(b)["id"], "PROC-0001")
            self.assertEqual(self._proc(b, title="Outro")["id"], "PROC-0002")
            self.assertEqual(self._opp(b)["id"], "OPP-0001")
            self.assertEqual(b.state.next_id("ACT"), "ACT-0001")
            self.assertEqual(b.validate_all(), [])

    def test_process_hours_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._b(td)
            pid = self._proc(b, executors=["eu", "marina-demo"], recurrence="semanal", duration="1h30m")["id"]
            p = b.state.processes[pid]
            self.assertEqual(p.duration_min, 90)
            self.assertAlmostEqual(p.hours_month, 4.33 * 1.5 * 2, places=2)
            sob = self._proc(b, title="Sob demanda", recurrence="sob-demanda", per_month=3, duration="45m")["id"]
            self.assertAlmostEqual(b.state.processes[sob].hours_month, 2.25)
            vazio = self._proc(b, title="Sem dados")["id"]
            self.assertIsNone(b.state.processes[vazio].hours_month)
            for bad in ({"recurrence": "anual"}, {"recurrence": "sob-demanda"}, {"maturity": 6},
                        {"duration": "0m"}, {"owner": "ninguem"}, {"executors": ["ninguem"]}):
                with self.assertRaises(util.BrainError, msg=str(bad)):
                    self._proc(b, **bad)
            with self.assertRaises(util.BrainError):                    # agente sem --source
                b.record_one({"type": "process.added", "by": "agent", "prov": "observado",
                              "data": {"title": "X", "area": "growth"}})
            b.record_one({"type": "process.retired", "id": pid, "by": "owner", "data": {"reason": "acabou"}})
            self.assertEqual(b.state.processes[pid].status, "aposentado")
            self.assertEqual(b.validate_all(), [])

    def test_opportunity_score_and_agent_rules(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._b(td)
            ev = b.record_one({"type": "opportunity.added", "by": "agent", "prov": "observado", "source": "chat",
                               "data": {"title": "Ideia do agente", "area": "growth"}})
            oid = ev["id"]
            self.assertEqual(b.state.opportunities[oid].status, "ideia")
            with self.assertRaises(util.BrainError):                    # agente sem --source
                b.record_one({"type": "opportunity.added", "by": "agent", "prov": "observado",
                              "data": {"title": "Sem fonte", "area": "growth"}})
            with self.assertRaises(util.BrainError):                    # agente não move status
                b.record_one({"type": "opportunity.status", "id": oid, "by": "agent", "prov": "observado",
                              "data": {"status": "triagem"}})
            b.record_one({"type": "opportunity.scored", "id": oid, "by": "agent", "prov": "observado",
                          "data": {"impact": 4, "confidence": 3, "ease": 2, "ice_suggested": True, "reason": "x"}})
            o = b.state.opportunities[oid]
            self.assertEqual((o.score, o.ice_suggested), (24, True))
            with self.assertRaises(util.BrainError):                    # dono não marca ice_suggested
                b.record_one({"type": "opportunity.scored", "id": oid, "by": "owner",
                              "data": {"impact": 1, "confidence": 1, "ease": 1, "ice_suggested": True}})
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "opportunity.scored", "id": oid, "by": "owner",
                              "data": {"impact": 6, "confidence": 1, "ease": 1}})
            b.record_one({"type": "opportunity.scored", "id": oid, "by": "owner",
                          "data": {"impact": 5, "confidence": 5, "ease": 5}})
            o = b.state.opportunities[oid]
            self.assertEqual((o.score, o.ice_suggested), (125, False))   # dono limpa a sugestão
            sem_ice = self._opp(b)["id"]
            self.assertIsNone(b.state.opportunities[sem_ice].score)
            self.assertEqual(b.validate_all(), [])

    def test_status_rules_and_history(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._b(td)
            oid = self._opp(b)["id"]
            st = lambda s, **d: b.record_one({"type": "opportunity.status", "id": oid, "by": "owner",  # noqa: E731
                                              "data": {"status": s, **d}})
            st("triagem")
            st("priorizada")
            st("triagem")                                               # vai e volta
            for bad in ("descartada", "em-espera", "em-andamento", "invalido"):
                with self.assertRaises(util.BrainError, msg=bad):
                    st(bad)                                             # laterais sem motivo; em-andamento sem projeto
            st("descartada", reason="duplicada")
            hist = b.state.opportunities[oid].status_history
            self.assertEqual([(h["from"], h["to"]) for h in hist],
                             [("ideia", "triagem"), ("triagem", "priorizada"), ("priorizada", "triagem"),
                              ("triagem", "descartada")])
            self.assertEqual(hist[-1]["reason"], "duplicada")

    def test_promoted_links_goal_and_project(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._b(td)
            oid = self._opp(b)["id"]
            for goal, proj in (("GOAL-9", "PROJ-1"), ("GOAL-1", "PROJ-9")):
                with self.assertRaises(util.BrainError):
                    b.record_one({"type": "opportunity.promoted", "id": oid, "by": "owner",
                                  "data": {"goal": goal, "project": proj}})
            b.record_one({"type": "opportunity.promoted", "id": oid, "by": "owner",
                          "data": {"goal": "GOAL-1", "project": "PROJ-1"}})
            b.record_one({"type": "opportunity.status", "id": oid, "by": "owner", "data": {"status": "em-andamento"}})
            o = b.state.opportunities[oid]
            self.assertEqual((o.project, o.goal, o.status), ("PROJ-1", "GOAL-1", "em-andamento"))
            self.assertEqual(b.validate_all(), [])

    def test_docs_evidence_and_person_merge(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._b(td)
            b.record_one({"type": "person.added", "id": "mari-dup", "by": "owner", "data": {"name": "Mari Dup"}})
            pid = self._proc(b, owner="mari-dup", executors=["mari-dup", "marina-demo"])["id"]
            oid = self._opp(b, data={"people": ["mari-dup"]})["id"]
            b.record_one({"type": "doc.linked", "by": "owner", "data": {
                "target": pid, "kind": "playbook", "ref": "https://example.com/doc", "title": "Playbook"}})
            self.assertEqual(b.state.processes[pid].playbook.ref, "https://example.com/doc")
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "doc.linked", "by": "owner",
                              "data": {"target": pid, "kind": "foo", "ref": "x"}})
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "doc.linked", "by": "owner",
                              "data": {"target": "OPP-9999", "kind": "outro", "ref": "x"}})
            b.record_one({"type": "doc.unlinked", "by": "owner",
                          "data": {"target": pid, "ref": "https://example.com/doc"}})
            self.assertEqual(b.state.processes[pid].docs, [])
            for _ in range(2):
                b.record_one({"type": "opportunity.evidence", "id": oid, "by": "agent", "prov": "observado",
                              "source": "PROCESSED/x.md", "data": {"source": "PROCESSED/x.md"}})
            o = b.state.opportunities[oid]
            self.assertEqual((o.evidence, o.evidence_count), (["PROCESSED/x.md"], 2))
            b.record_one({"type": "person.merged", "id": "mari-dup", "by": "owner", "data": {"into": "marina-demo"}})
            p = b.state.processes[pid]
            self.assertEqual((p.owner, p.executors), ("marina-demo", ["marina-demo"]))
            self.assertEqual(b.state.opportunities[oid].people, ["marina-demo"])
            self.assertEqual(b.validate_all(), [])


class PortfolioCliTests(unittest.TestCase):
    """Passo 2: `brain area|process|opportunity|doc` (sempre com BRAIN_HOME numa pasta temporária)."""

    def _run(self, td, *a):
        env = {**os.environ, "BRAIN_HOME": td}
        return subprocess.run([sys.executable, str(ROOT / "brain"), *a], capture_output=True, text=True, env=env)

    def _ok(self, td, *a):
        r = self._run(td, *a)
        self.assertEqual(r.returncode, 0, f"{a}: {r.stderr}")
        return r.stdout

    def _setup(self, td):
        _brain(Path(td))
        self._ok(td, "area", "add", "operacoes", "--name", "Operações", "--alias", "Ops", "--by", "owner")
        self._ok(td, "area", "add", "growth", "--by", "owner")

    def test_area_process_flow(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            self.assertIn("Operações", self._ok(td, "area", "list"))
            out = self._ok(td, "process", "add", "Fechamento mensal", "--area", "Ops", "--owner", "marina-demo",
                           "--executor", "marina-demo", "--executor", "eu", "--recurrence", "semanal",
                           "--duration", "1h30m", "--tools", "Sheets, Jira", "--pain", "retrabalho",
                           "--maturity", "2", "--by", "owner")
            self.assertIn("PROC-0001", out)
            self.assertIn("12,99 h/mês", out)
            self.assertIn("sem playbook", out)
            self.assertEqual(self._run(td, "process", "add", "X", "--area", "nada", "--by", "owner").returncode, 3)
            self.assertEqual(self._run(td, "process", "add", "Y", "--area", "growth", "--recurrence", "sob-demanda",
                                       "--by", "owner").returncode, 4)           # exige --per-month
            self._ok(td, "process", "update", "PROC-0001", "--recurrence", "sob-demanda", "--per-month", "2",
                     "--by", "owner")
            shown = json.loads(self._ok(td, "process", "show", "PROC-0001", "--json"))
            self.assertEqual((shown["hours_month"], shown["tools"]), (6.0, ["Sheets", "Jira"]))
            self.assertIn("PROC-0001", self._ok(td, "process", "list", "--gaps"))
            self._ok(td, "doc", "link", "PROC-0001", "--kind", "playbook", "--ref", "https://example.com/pb",
                     "--by", "owner")
            self.assertNotIn("PROC-0001", self._ok(td, "process", "list", "--area", "operacoes", "--gaps"))
            self._ok(td, "process", "retire", "PROC-0001", "--reason", "fim", "--by", "owner")
            self.assertEqual(self._ok(td, "process", "list").strip(), "(nenhum processo)")
            self.assertIn("✓", self._ok(td, "validate"))

    def test_opportunity_flow_duplicates_and_agent(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            self._ok(td, "opportunity", "add", "Automatizar conciliação bancária", "--area", "operacoes",
                     "--problem", "conciliação manual consome horas da equipe", "--hours-saved", "10", "--by", "owner")
            dup = self._run(td, "opportunity", "add", "Automatizar a conciliação bancária", "--area", "operacoes",
                            "--problem", "conciliação manual consome horas", "--by", "owner")
            self.assertEqual(dup.returncode, 2)
            self.assertIn("OPP-0001", dup.stderr)
            self._ok(td, "opportunity", "add", "Automatizar a conciliação bancária", "--area", "operacoes",
                     "--by", "owner", "--force")
            self.assertEqual(self._run(td, "opportunity", "add", "Do agente", "--area", "growth").returncode, 4)  # sem fonte
            self._ok(td, "opportunity", "add", "Dashboard de metas", "--area", "growth", "--by", "agent",
                     "--prov", "observado", "--source", "chat")
            self.assertEqual(self._run(td, "opportunity", "status", "OPP-0003", "triagem", "--by", "agent",
                                       "--prov", "observado").returncode, 4)
            self._ok(td, "opportunity", "score", "OPP-0003", "--impact", "4", "--confidence", "3", "--ease", "5",
                     "--suggest", "--reason", "parece simples", "--prov", "observado")
            out = self._ok(td, "opportunity", "show", "OPP-0003")
            self.assertIn("60 (sugerido)", out)
            out = self._ok(td, "opportunity", "score", "OPP-0003", "--impact", "4", "--confidence", "3", "--ease", "5")
            self.assertIn("=60", out)
            self.assertNotIn("sugerido", out)
            self.assertEqual(self._run(td, "opportunity", "status", "OPP-0003", "descartada").returncode, 4)  # sem motivo
            self._ok(td, "opportunity", "status", "OPP-0003", "descartada", "--reason", "fora do foco")
            self._ok(td, "opportunity", "evidence", "OPP-0001", "--source", "PROCESSED/x.md", "--prov", "observado")
            ranked = self._ok(td, "opportunity", "list", "--sort", "score").splitlines()
            self.assertTrue(ranked[0].startswith("OPP-0003"))
            self.assertEqual(len(json.loads(self._ok(td, "opportunity", "list", "--status", "ideia", "--json"))), 2)
            self._ok(td, "doc", "link", "OPP-0001", "--kind", "one-pager", "--ref", "reports/share/x.md", "--by", "owner")
            self._ok(td, "doc", "unlink", "OPP-0001", "--ref", "reports/share/x.md", "--by", "owner")
            self.assertEqual(self._run(td, "doc", "unlink", "OPP-0001", "--ref", "nao-existe").returncode, 4)
            hits = json.loads(self._ok(td, "search", "conciliação", "--json"))
            self.assertIn("OPP-0001", {h["id"] for h in hits})

    def test_promote_is_a_gate(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            self._ok(td, "opportunity", "add", "Playbook de onboarding", "--area", "growth",
                     "--problem", "time novo demora a render", "--by", "owner")
            goals = Path(td) / "vault" / "PLANNING" / "goals.md"
            before = goals.read_text(encoding="utf-8")
            r = self._run(td, "opportunity", "promote", "OPP-0001", "--goal", "GOAL-1")
            self.assertEqual(r.returncode, 4)
            self.assertIn("### PROJ-2 — Playbook de onboarding", r.stdout)
            self.assertIn("- por quê: time novo demora a render", r.stdout)
            self.assertEqual(goals.read_text(encoding="utf-8"), before)           # nada gravado sem "ok"
            self.assertEqual(self._run(td, "opportunity", "promote", "OPP-0001", "--goal", "GOAL-9",
                                       "--approval", "ok").returncode, 3)
            self._ok(td, "opportunity", "promote", "OPP-0001", "--goal", "GOAL-1", "--approval", "ok")
            self.assertIn("### PROJ-2 — Playbook de onboarding", goals.read_text(encoding="utf-8"))
            o = json.loads(self._ok(td, "opportunity", "show", "OPP-0001", "--json"))
            self.assertEqual((o["status"], o["project"], o["goal"]), ("em-andamento", "PROJ-2", "GOAL-1"))
            self.assertIn("promoção de OPP-0001", (Path(td) / "vault" / "PLANNING" / "log.md").read_text(encoding="utf-8"))
            self.assertEqual(self._run(td, "opportunity", "promote", "OPP-0001", "--goal", "GOAL-1",
                                       "--approval", "ok").returncode, 4)          # já promovida
            types = [e["type"] for e in Brain(config.load(Path(td))).read_events()][-3:]
            self.assertEqual(types, ["plan.changed", "opportunity.promoted", "opportunity.status"])
            self.assertIn("✓", self._ok(td, "validate"))
            nightly = {**os.environ, "BRAIN_HOME": td, "BRAIN_NIGHTLY": "1"}
            r = subprocess.run([sys.executable, str(ROOT / "brain"), "opportunity", "promote", "OPP-0001",
                                "--goal", "GOAL-1", "--approval", "ok"], capture_output=True, text=True, env=nightly)
            self.assertEqual(r.returncode, 4)


class PortfolioModelTests(unittest.TestCase):
    """Passo 4: funções determinísticas de `brainlib/portfolio.py` e a seção `portfolio` do model."""

    def _seed(self, td):
        b = _brain(Path(td))
        for slug, name in (("operacoes", "Operações"), ("growth", "Growth"), ("vazia", "Área vazia")):
            b.record_one({"type": "area.added", "id": slug, "by": "owner", "data": {"name": name}})
        p1 = b.record_one({"type": "process.added", "by": "owner", "data": {
            "title": "Fechamento mensal", "area": "operacoes", "owner": "eu", "recurrence": "mensal",
            "duration": "2h"}})["id"]
        b.record_one({"type": "doc.linked", "by": "owner", "data": {
            "target": p1, "kind": "playbook", "ref": "https://example.com/pb"}})
        b.record_one({"type": "process.added", "by": "owner", "data": {"title": "Sem dados", "area": "growth"}})

        def opp(title, area, status=None, ice=None, **data):
            oid = b.record_one({"type": "opportunity.added", "by": "owner", "data": {
                "title": title, "area": area, **data}})["id"]
            if ice:
                b.record_one({"type": "opportunity.scored", "id": oid, "by": "owner",
                              "data": dict(zip(("impact", "confidence", "ease"), ice))})
            if status:
                b.record_one({"type": "opportunity.status", "id": oid, "by": "owner",
                              "data": {"status": status, "reason": "x"}})
            return oid
        ids = {
            "rapido": opp("Ganho rápido", "operacoes", "priorizada", (5, 4, 4), process=p1, hours_saved=8),
            "aposta": opp("Aposta grande", "operacoes", "triagem", (5, 3, 1)),
            "depois": opp("Preencher depois", "growth", None, (2, 5, 5), goal="GOAL-1"),
            "evitar": opp("Evitar", "growth", "descartada", (1, 1, 1)),
            "semice": opp("Sem ICE", "growth"),
        }
        b.record_one({"type": "opportunity.scored", "id": ids["semice"], "by": "agent", "prov": "observado",
                      "data": {"impact": 3, "confidence": 3, "ease": 3, "ice_suggested": True}})
        return b, p1, ids

    def test_tokens_and_duplicates(self):
        self.assertEqual(portfolio_mod.tokens("Automatizar a conciliação, de PAGAMENTOS!"),
                         {"automatizar", "conciliacao", "pagamentos"})
        with tempfile.TemporaryDirectory() as td:
            b, _, ids = self._seed(td)
            opps = b.state.opportunities.values()
            hits = portfolio_mod.duplicates("Ganho rápido!", "", opps)
            self.assertEqual([(o.id, s) for o, s in hits], [(ids["rapido"], 1.0)])
            self.assertEqual(portfolio_mod.duplicates("Totalmente diferente", "outro assunto", opps), [])
            many = portfolio_mod.duplicates("Aposta grande Evitar Sem ICE Preencher", "", opps)
            self.assertLessEqual(len(many), 3)

    def test_quadrants_matrix_funnel_groups(self):
        with tempfile.TemporaryDirectory() as td:
            b, _, ids = self._seed(td)
            o = b.state.opportunities
            self.assertEqual([portfolio_mod.quadrant(o[ids[k]]) for k in ("rapido", "aposta", "depois", "evitar")],
                             ["ganho rápido", "aposta", "preencher depois", "evitar"])
            m = portfolio_mod.matrix(o.values())
            self.assertEqual([x.id for x in m["ganho rápido"]], [ids["rapido"], ids["semice"]])  # score 80 > 27
            self.assertEqual(m["evitar"], [])                                  # descartada sai da matriz
            f = portfolio_mod.funnel(o.values())
            self.assertEqual((f["priorizada"], f["triagem"], f["descartada"], f["ideia"]), (1, 1, 1, 2))
            self.assertEqual(list(portfolio_mod.by_area(o.values())), ["operacoes", "growth"])
            self.assertEqual([x.id for x in portfolio_mod.by_goal(o.values())[""]],
                             [ids["rapido"], ids["aposta"], ids["evitar"], ids["semice"]])
            self.assertEqual(portfolio_mod.gain_hours(o[ids["rapido"]]), 8)
            self.assertIsNone(portfolio_mod.gain_hours(o[ids["aposta"]]))

    def test_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            b, p1, ids = self._seed(td)
            g = portfolio_mod.gaps(b.state, util.today())
            self.assertEqual(g["areas_without_process"], ["vazia"])
            self.assertEqual(g["processes"], [{"id": "PROC-0002", "gaps": [
                "sem playbook", "sem responsável", "sem recorrência/duração"]}])
            self.assertEqual(g["ice_suggested"], [ids["semice"]])
            self.assertEqual(g["no_ice"], [])
            self.assertEqual(g["stale"], [])
            self.assertEqual(g["total"], 3)
            later = util.today() + timedelta(days=45)
            stale = portfolio_mod.gaps(b.state, later)["stale"]
            self.assertEqual({s["id"] for s in stale}, {ids[k] for k in ("rapido", "aposta", "depois", "semice")})
            self.assertEqual(stale[0]["days"], 45)                             # descartada não fica "parada"

    def test_model_section(self):
        with tempfile.TemporaryDirectory() as td:
            b, p1, ids = self._seed(td)
            from brainlib import model
            pf = model.build(b)["portfolio"]
            self.assertEqual(pf["counts"], {"opportunities": 5, "prioritized": 1, "processes": 2, "gaps": 3})
            self.assertEqual(pf["ranking"], [ids["rapido"], ids["depois"], ids["semice"], ids["aposta"]])
            self.assertNotIn(ids["evitar"], pf["ranking"])
            proc = next(p for p in pf["processes"] if p["id"] == p1)
            self.assertEqual((proc["hours_month"], proc["opportunities"], proc["gaps"]), (2.0, [ids["rapido"]], []))
            opp = next(o for o in pf["opportunities"] if o["id"] == ids["semice"])
            self.assertEqual((opp["score"], opp["ice_suggested"], opp["quadrant"]), (27, True, "ganho rápido"))
            self.assertEqual(next(o for o in pf["opportunities"] if o["id"] == ids["depois"])["goal_title"], "Meta")
            self.assertEqual({a["id"]: a["processes"] for a in pf["areas"]},
                             {"operacoes": 1, "growth": 1, "vazia": 0})
            json.dumps(pf)                                                     # serializável


class PortfolioViewsTests(unittest.TestCase):
    """Passo 5: processes.md, opportunities.md, fichas, home, painel e a colheita de `status:` da ficha de OPP."""

    def _render(self, td):
        b, p1, ids = PortfolioModelTests._seed(None, td)
        render.render_all(b, do_harvest=False)
        return b, p1, ids, b.inst.fresh

    def test_pages_and_records(self):
        with tempfile.TemporaryDirectory() as td:
            b, p1, ids, fresh = self._render(td)
            procs = (fresh / "processes.md").read_text(encoding="utf-8")
            self.assertIn("generated-at:", procs)
            self.assertIn("fontes:", procs)
            self.assertIn("## Operações · 1 processos · 2 h/mês", procs)
            self.assertIn("⚠ sem playbook", procs)
            opps = (fresh / "opportunities.md").read_text(encoding="utf-8")
            self.assertIn("generated-at:", opps)
            self.assertIn("5×4×4 = **80**", opps)
            self.assertIn("(sugerido)", opps)                                   # ICE do agente em destaque
            self.assertIn("ganho rápido: [OPP-0001]", opps)
            self.assertIn("preencher depois: [OPP-0003]", opps)
            rec = (fresh / "records" / "opportunities" / f"{ids['rapido']}.md").read_text(encoding="utf-8")
            self.assertIn('status: "priorizada"', rec)
            self.assertIn("## Histórico de status", rec)
            prec = (fresh / "records" / "processes" / f"{p1}.md").read_text(encoding="utf-8")
            self.assertIn("horas_mes: 2.0", prec)
            self.assertIn("[playbook]", prec)
            home = (fresh / "home.md").read_text(encoding="utf-8")
            self.assertIn("Portfólio: **5** oportunidades · **1** priorizadas · **3** lacunas", home)
            dash = (fresh / "dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn('"portfolio"', dash)
            self.assertIn("Aposta grande", dash)

    def test_no_portfolio_no_line_in_home(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            render.render_all(b, do_harvest=False)
            self.assertNotIn("Portfólio:", (b.inst.fresh / "home.md").read_text(encoding="utf-8"))
            self.assertTrue((b.inst.fresh / "processes.md").exists())

    def test_edit_status_in_record_is_harvested(self):
        with tempfile.TemporaryDirectory() as td:
            b, p1, ids, fresh = self._render(td)
            path = fresh / "records" / "opportunities" / f"{ids['aposta']}.md"
            path.write_text(path.read_text(encoding="utf-8").replace('status: "triagem"', 'status: "priorizada"'),
                            encoding="utf-8")
            report = render.render_all(b)
            self.assertIn(f"opportunity.status {ids['aposta']}", report["harvested"])
            ev = [e for e in Brain(b.inst).read_events() if e["type"] == "opportunity.status"][-1]
            self.assertEqual((ev["by"], ev["prov"], ev["data"]["status"]), ("owner", "declarado", "priorizada"))
            self.assertEqual(Brain(b.inst).state.opportunities[ids["aposta"]].status, "priorizada")
            # lateral sem motivo na ficha ganha motivo padrão; não colhe de novo no render seguinte
            path.write_text(path.read_text(encoding="utf-8").replace('status: "priorizada"', 'status: "em-espera"'),
                            encoding="utf-8")
            render.render_all(b)
            o = Brain(b.inst).state.opportunities[ids["aposta"]]
            self.assertEqual((o.status, o.status_history[-1]["reason"]), ("em-espera", "alterado na ficha (status)"))
            self.assertEqual(render.render_all(b)["harvested"], [])

    def test_invalid_status_in_record_warns_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            b, p1, ids, fresh = self._render(td)
            before = len(Brain(b.inst).read_events())
            for bad in ("quase-pronta", "em-andamento"):                        # inexistente · sem projeto vinculado
                path = fresh / "records" / "opportunities" / f"{ids['aposta']}.md"
                path.write_text(path.read_text(encoding="utf-8").replace('status: "triagem"', f'status: "{bad}"'),
                                encoding="utf-8")
                report = render.render_all(b)
                self.assertEqual(report["harvested"], [])
                self.assertTrue(any(w["title"] == "ficha" and ids["aposta"] in w["detail"] for w in report["warnings"]), bad)
                self.assertIn("ficha", render.summary(report))
                self.assertEqual(len(Brain(b.inst).read_events()), before)
                self.assertEqual(Brain(b.inst).state.opportunities[ids["aposta"]].status, "triagem")
                before = len(Brain(b.inst).read_events())

    def test_dashboard_script_is_valid_js(self):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("node ausente")
        with tempfile.TemporaryDirectory() as td:
            b, p1, ids, fresh = self._render(td)
            html = (fresh / "dashboard" / "index.html").read_text(encoding="utf-8")
            script = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
            js = Path(td) / "dash.js"
            js.write_text(script, encoding="utf-8")
            r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


class PortfolioOutputsTests(unittest.TestCase):
    """Passos 8–9: exports (/share portfolio, one-pager), skills e as ferramentas MCP somente-leitura."""

    def test_share_portfolio_and_onepager(self):
        with tempfile.TemporaryDirectory() as td:
            b, p1, ids = PortfolioModelTests._seed(None, td)
            b.record_one({"type": "opportunity.evidence", "id": ids["rapido"], "by": "owner", "data": {"source": "PROCESSED/x.md"}})
            path = share.export(b, "portfolio", None, "md")
            text = path.read_text(encoding="utf-8")
            self.assertIn("# Roadmap de oportunidades", text)
            self.assertIn("Ganho rápido — prioridade 80", text)
            self.assertIn("**ganho rápido:**", text)
            self.assertIn("ganho declarado: 8 h/mês", text)
            body = text.split("**Fontes**")[0]
            self.assertNotIn(ids["rapido"], body)                       # IDs internos só na seção de fontes
            self.assertIn("Sem ICE — prioridade 27 (preliminar)", body)  # sugestão do agente não vira número firme
            only = share.export(b, "portfolio", None, "md", area="Growth").read_text(encoding="utf-8")
            self.assertIn("— Growth", only.splitlines()[0])
            self.assertNotIn("Ganho rápido", only)                      # é da área Operações
            with self.assertRaises(util.BrainError):
                share.export(b, "portfolio", None, "md", area="nao-existe")
            one = share.export(b, "opportunity", ids["rapido"], "html").read_text(encoding="utf-8")
            self.assertIn("Ganho rápido", one)
            self.assertIn("prioridade 80", one)
            self.assertIn("Fechamento mensal", one)                     # processo ligado
            self.assertIn("PROCESSED/x.md", one)
            sug = share.export(b, "opportunity", ids["semice"], "md").read_text(encoding="utf-8")
            self.assertIn("estimativa preliminar", sug)                 # ICE só sugerido não vira firme no documento
            with self.assertRaises(util.BrainError):
                share.export(b, "opportunity", "OPP-9999", "md")

    def test_mcp_portfolio_tools_are_read_only_and_answer(self):
        with tempfile.TemporaryDirectory() as td:
            b, p1, ids = PortfolioModelTests._seed(None, td)
            os.environ["BRAIN_HOME"] = str(b.inst.root)
            try:
                ov = mcp_server.call_tool("portfolio_overview", {})
                self.assertEqual(ov["counts"]["opportunities"], 5)
                self.assertEqual(ov["ranking"][0]["id"], ids["rapido"])
                self.assertEqual(ov["gaps"]["areas_without_process"], ["vazia"])
                self.assertEqual(mcp_server.call_tool("process", {"id": p1.lower()})["hours_month"], 2.0)
                self.assertIn("erro", mcp_server.call_tool("process", {"id": "PROC-9999"}))
                o = mcp_server.call_tool("opportunity", {"id": ids["semice"]})
                self.assertEqual((o["score"], o["ice_suggested"]), (27, True))
                self.assertIn("erro", mcp_server.call_tool("opportunity", {"id": "OPP-9999"}))
                self.assertEqual([x["id"] for x in mcp_server.call_tool("opportunities", {"status": "priorizada"})], [ids["rapido"]])
                growth = mcp_server.call_tool("opportunities", {"area": "growth"})
                self.assertEqual([x["id"] for x in growth][0], ids["depois"])      # maior score primeiro
                self.assertNotIn("status_history", growth[0])
            finally:
                os.environ.pop("BRAIN_HOME", None)
            listed = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
            names = {t["name"] for t in listed}
            self.assertTrue({"portfolio_overview", "process", "opportunity", "opportunities"} <= names)
            self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in listed))

    def test_new_skills_and_constitution(self):
        import re
        for name in ("process", "opportunity"):
            text = (ROOT / "commands" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(re.match(rf'---\nname: {name}\ndescription: ".+"\n---\n', text), name)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for needle in ("`PROC-####`", "`OPP-####`", "commands/process/SKILL.md", "commands/opportunity/SKILL.md",
                       "só cria em `ideia`", "processes.md"):
            self.assertIn(needle, agents.replace("**O agente cria oportunidade sozinho, sempre em `ideia`**", "só cria em `ideia`"))
        self.assertIn("## 13. Face Portfólio", (ROOT / "guides" / "user-guide.md").read_text(encoding="utf-8"))
        self.assertIn("opportunity add", (ROOT / "commands" / "dump" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("share portfolio", (ROOT / "commands" / "share" / "SKILL.md").read_text(encoding="utf-8"))


class IdsTests(unittest.TestCase):
    """Passo 1 da migração de IDs: prefixos declarativos; os nomes antigos continuam valendo na entrada."""

    def test_normalize_translates_legacy_and_keeps_new(self):
        n = ids.normalize
        self.assertEqual([n(x) for x in ("A-0146", "a-146", "D-12", "E-0003", "R-7", "M-2", "S-1", "F-1")],
                         ["ACT-0146", "ACT-0146", "DEC-0012", "WIN-0003", "PROP-0007", "MSG-0002", "PUB-0001", "FOCUS-0001"])
        self.assertEqual([n(x) for x in ("G1", "g01", "P3", "p3.2", "P10.12")],
                         ["GOAL-1", "GOAL-1", "PROJ-3", "PROJ-3.2", "PROJ-10.12"])
        for new in ("ACT-0146", "DEC-0012", "WIN-0003", "PROP-0007", "MSG-0002", "PUB-0001", "FOCUS-0001", "PROC-0003",
                    "OPP-0004", "GOAL-1", "PROJ-3", "PROJ-3.2"):
            self.assertEqual(n(new), new)
        # o que não é ID fica como veio (URL, texto, slug de área ou pessoa, lista com mistura)
        for other in ("https://example.com/P3", "marina-demo", "operacoes", "Reunião P3 de ontem", "", "A-1B"):
            self.assertEqual(n(other), other)
        self.assertEqual(n(["A-1", "G2", "texto"]), ["ACT-0001", "GOAL-2", "texto"])
        self.assertEqual(ids.normalize_csv("A-1, P2.1 ,x"), "ACT-0001,PROJ-2.1,x")
        self.assertEqual((ids.entity_of("A-0001"), ids.entity_of("PROJ-3.2"), ids.entity_of("GOAL-1"), ids.entity_of("x")),
                         ("action", "deliverable", "goal", None))
        self.assertEqual((ids.make("action", 147), ids.make("goal", 4), ids.make("project", 12)), ("ACT-0147", "GOAL-4", "PROJ-12"))

    def test_legacy_input_is_stored_in_the_new_format_and_sequence_continues(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ev = b.record_one({"type": "action.opened", "by": "owner", "data": {
                "title": "Ligada ao plano", "owner": "eu", "project": "P1", "deliverable": "P1.1"}})
            self.assertEqual((ev["id"], ev["data"]["project"], ev["data"]["deliverable"]), ("ACT-0001", "PROJ-1", "PROJ-1.1"))
            b.record_one({"type": "action.opened", "by": "owner", "data": {
                "title": "Bloqueada", "owner": "eu", "blocked_by": ["A-0001"]}})
            self.assertEqual(b.state.actions["ACT-0002"].blocked_by, ["ACT-0001"])
            b.record_one({"type": "action.updated", "id": "A-0002", "by": "owner", "data": {"note": "x"}})   # id antigo na entrada
            b.record_one({"type": "delivery.recorded", "by": "owner", "data": {"title": "Entrega", "ref": "P1.2"}})
            self.assertEqual(b.state.deliveries["WIN-0001"].ref, "PROJ-1.2")
            self.assertEqual(b.state.next_id("ACT"), "ACT-0003")
            lines = b.ledger_path.read_text(encoding="utf-8")
            self.assertNotIn('"A-0', lines)
            self.assertNotIn('"P1', lines)
            self.assertEqual(b.validate_all(), [])

    def test_ledger_still_in_old_names_is_readable_and_continues_in_the_new_ones(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            old = [{"seq": 100 + i, "ts": "2026-10-01T10:00:00-03:00", "type": t, "id": i_, "date": "2026-10-01", "by": "owner",
                    "prov": "declarado", "source": "chat", "data": d} for i, (t, i_, d) in enumerate([
                ("action.opened", "A-0146", {"title": "Antiga", "owner": "eu", "project": "P1"}),
                ("action.opened", "A-0147", {"title": "Outra", "owner": "eu", "blocked_by": ["A-0146"]}),
                ("progress.declared", "G1", {"pct": 40}),
                ("delivery.recorded", "E-0003", {"title": "Entregue", "ref": "A-0146"})])]
            base = b.state.max_seq()
            for i, e in enumerate(old):
                e["seq"] = base + 1 + i
            with open(b.ledger_path, "a", encoding="utf-8") as fh:
                for e in old:
                    fh.write(json.dumps(e) + "\n")
            b2 = Brain(b.inst)
            self.assertEqual(sorted(b2.state.actions), ["ACT-0146", "ACT-0147"])
            self.assertEqual(b2.state.actions["ACT-0147"].blocked_by, ["ACT-0146"])
            self.assertEqual(b2.state.deliveries["WIN-0003"].ref, "ACT-0146")
            self.assertIn("GOAL-1", b2.state.progress)
            self.assertEqual(b2.validate_all(), [])
            self.assertEqual(b2.record_one({"type": "action.opened", "by": "owner", "data": {"title": "Nova", "owner": "eu"}})["id"], "ACT-0148")

    def test_goals_md_reads_both_formats_and_writes_the_new_one(self):
        legacy = ("# PLANNING\n\n## G1 — Meta\n- status: ativo\n\n### P1 — Projeto\n- status: ativo\n"
                  "- [ ] P1.1 Um · prazo: 2026-10-20 · peso: 2\n- [x] P1.2 Dois · feito: 2026-10-01\n")
        new = legacy.replace("G1", "GOAL-1").replace("P1", "PROJ-1")
        a, b_ = planning.parse(legacy), planning.parse(new)
        for plan in (a, b_):
            self.assertEqual(list(plan.goals), ["GOAL-1"])
            self.assertEqual(list(plan.projects), ["PROJ-1"])
            self.assertEqual(list(plan.deliverables), ["PROJ-1.1", "PROJ-1.2"])
            self.assertEqual(plan.progress("P1")["pct"], 33)                # consulta pelo nome antigo também funciona
            self.assertTrue(plan.has("G1") and plan.has("P1.2"))
            self.assertEqual(plan.warnings, [])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "goals.md"
            path.write_text(legacy, encoding="utf-8")
            self.assertEqual(planning.add_project(path, "G1", "Novo"), "PROJ-2")      # sequência e formato novos
            self.assertEqual(planning.add_goal(path, "Outro"), "GOAL-2")
            self.assertEqual(planning.add_deliverable(path, "P2", "Entregável novo"), "PROJ-2.1")
            self.assertTrue(planning.set_deliverable(path, "P1.1", "feito", date(2026, 10, 9)))
            text = path.read_text(encoding="utf-8")
            self.assertIn("### PROJ-2 — Novo", text)
            self.assertIn("- [x] PROJ-1.1 Um", text)                          # a linha tocada passou ao formato novo
            self.assertIn("## G1 — Meta", text)                               # o resto do arquivo só muda quando o cérebro reescreve
            changes = planning.edit_node(path, "G1", title="Meta nova")
            self.assertEqual(changes[0][0], "título")
            self.assertEqual(planning.parse(path.read_text(encoding="utf-8")).warnings, [])

    def test_cli_accepts_old_names_and_prints_new_ones(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            run = lambda *a: subprocess.run([sys.executable, str(ROOT / "brain"), *a], capture_output=True, text=True,   # noqa: E731
                                            env={**os.environ, "BRAIN_HOME": td})
            r = run("action", "open", "Pelo CLI", "--project", "P1", "--deliverable", "P1.2", "--by", "owner")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("ACT-0001", r.stdout)
            self.assertIn("PROJ-1", r.stdout)
            r = run("action", "update", "A-0001", "--note", "x", "--by", "owner")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(run("action", "show", "A-1", "--json").returncode, 0)
            r = run("plan", "deliverable", "P1.1", "--status", "feito", "--by", "owner")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(run("progress", "G1", "50").returncode, 0)
            self.assertIn("GOAL-1", run("plan", "show").stdout)
            r = run("note", "add", "--link", "a-1", "--text", "nota de teste")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(any(p.name.startswith("ACT-0001-") for p in (Path(td) / "vault" / "RAW" / "inbox").glob("*")))
            self.assertIn("✓", run("validate").stdout)

    def test_old_note_names_are_still_read_and_linked_to_the_new_id(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            inbox = b.inst.inbox
            (inbox / "A-0001-2026-10-09-note.md").write_text("---\ntipo: nota\nvinculo: A-0001\ncriada: 2026-10-09 10:00\n---\ncorpo", encoding="utf-8")
            (inbox / "P1-2026-10-09-note.md").write_text("sem frontmatter", encoding="utf-8")
            got = {n.link for n in notes_mod.scan(b.inst)}
            self.assertEqual(got, {"ACT-0001", "PROJ-1"})


if __name__ == "__main__":
    unittest.main()
