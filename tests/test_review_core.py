"""Revisão do núcleo: gates do dono, noturno, entrada malformada, ledger, fuso, permissões e migração."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, migrate_ids, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from test_brain import _brain  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.b = _brain(Path(self.td.name))

    def refused(self, ev, msg=None):
        with self.assertRaises(util.BrainError, msg=msg or str(ev)):
            self.b.record_one(ev)

    def nightly(self):
        os.environ["BRAIN_NIGHTLY"] = "1"
        self.addCleanup(os.environ.pop, "BRAIN_NIGHTLY", None)


class OwnerGateTests(_Base):
    """by=system (ou agent) não pode gravar o que é do dono: promover, mover status, ICE firme, aprovações."""

    def setUp(self):
        super().setUp()
        self.b.record_one({"type": "area.added", "by": "owner", "data": {"name": "ops"}})
        self.oid = self.b.record_one({"type": "opportunity.added", "by": "owner", "data": {"title": "x", "area": "ops"}})["id"]

    def test_system_cannot_promote_or_move_opportunity(self):
        self.refused({"type": "opportunity.promoted", "id": self.oid, "by": "system",
                      "data": {"project": "PROJ-1", "goal": "GOAL-1"}})
        self.refused({"type": "opportunity.status", "id": self.oid, "by": "system", "data": {"status": "priorizada"}})
        self.refused({"type": "opportunity.scored", "id": self.oid, "by": "system",
                      "data": {"impact": 5, "confidence": 5, "ease": 5}})
        self.b.record_one({"type": "opportunity.status", "id": self.oid, "by": "owner", "data": {"status": "priorizada"}})
        self.assertEqual(self.b.state.opportunities[self.oid].status, "priorizada")

    def test_project_only_via_promotion(self):
        self.refused({"type": "opportunity.updated", "id": self.oid, "by": "agent", "prov": "observado", "source": "x",
                      "data": {"project": "PROJ-1"}})
        self.refused({"type": "opportunity.added", "by": "owner", "data": {"title": "y", "area": "ops", "project": "PROJ-1"}})
        self.b.record_one({"type": "opportunity.updated", "id": self.oid, "by": "owner", "data": {"goal": "GOAL-1"}})

    def test_agent_ice_on_add_is_suggestion_and_must_be_complete(self):
        base = {"type": "opportunity.added", "by": "agent", "prov": "observado", "source": "RAW/x.md"}
        self.refused({**base, "data": {"title": "z", "area": "ops", "impact": 5, "confidence": 5, "ease": 5}})
        self.refused({"type": "opportunity.added", "by": "owner", "data": {"title": "w", "area": "ops", "impact": 3}})
        ev = self.b.record_one({**base, "data": {"title": "z", "area": "ops", "impact": 5, "confidence": 4, "ease": 3,
                                                 "ice_suggested": True, "reason": "palpite"}})
        o = self.b.state.opportunities[ev["id"]]
        self.assertEqual((o.score, o.ice_suggested), (60, True))

    def test_approvals_need_owner(self):
        pid = self.b.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "x",
                                 "data": {"kind": "outro", "summary": "s"}})["id"]
        for by in ("agent", "system"):
            self.refused({"type": "proposal.accepted", "id": pid, "by": by, "prov": "observado", "data": {"quote": "ok"}})
            self.refused({"type": "plan.changed", "by": by, "prov": "observado",
                          "data": {"diff": "x", "reason": "y", "approval": "ok"}})
        self.b.record_one({"type": "proposal.accepted", "id": pid, "by": "owner", "data": {"quote": "ok"}})
        self.assertEqual(self.b.state.proposals[pid].status, "aceita")


class NightlyTests(_Base):
    def test_structural_gates_refused_at_night_whatever_the_by(self):
        pid = self.b.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "x",
                                 "data": {"kind": "outro", "summary": "s"}})["id"]
        self.nightly()
        for ev in ({"type": "plan.changed", "by": "system", "data": {"diff": "x", "reason": "y", "approval": "ok"}},
                   {"type": "proposal.rejected", "id": pid, "by": "system", "data": {"quote": "não"}}):
            with self.assertRaisesRegex(util.BrainError, "noturno"):
                self.b.record_one(ev)
        # o noturno segue podendo registrar fatos do agente
        self.b.record_one({"type": "action.opened", "by": "agent", "prov": "observado", "source": "RAW/x.md",
                           "data": {"title": "t", "owner": "eu"}})


class MalformedInputTests(_Base):
    """`brain add` com JSON torto: BrainError (código 4), nunca traceback, nada gravado."""

    def test_shapes(self):
        n = len(self.b.read_events())
        bad = [
            ["não é objeto"],
            {"type": "action.opened", "by": "owner", "data": "texto"},
            {"type": "action.opened", "by": "owner", "data": {"title": "t", "owner": "eu", "blocked_by": "TASK-0001"}},
            {"type": "action.opened", "by": "owner", "data": {"title": "t", "owner": "eu", "people": "marina-demo"}},
            {"type": "action.opened", "by": "owner", "data": {"title": "t", "owner": "eu", "effort_min": True}},
            {"type": "progress.declared", "id": "GOAL-1", "by": "owner", "data": {"pct": True}},
            {"type": "action.opened", "by": ["owner"], "prov": "declarado", "data": {"title": "t", "owner": "eu"}},
            {"type": "person.updated", "id": ["eu"], "by": "owner", "data": {}},
        ]
        for ev in bad:
            with self.assertRaises(util.BrainError, msg=repr(ev)) as cm:
                self.b.record([ev])
            self.assertEqual(cm.exception.code, 4, repr(ev))
        self.assertEqual(len(self.b.read_events()), n)

    def test_artifact_path_cannot_escape_vault(self):
        base = {"type": "artifact.added", "by": "agent", "prov": "doc", "source": "RAW/a.md"}
        for p in ("../../etc/passwd.md", "PROCESSED/../../x.md", "/etc/hosts"):
            self.refused({**base, "id": p, "data": {"kind": "nota", "title": "t"}}, p)
        self.refused({**base, "id": "PROCESSED/ok.md", "data": {"kind": "nota", "title": "t", "raw": "../fora.md"}})
        ev = self.b.record_one({**base, "id": str(self.b.inst.vault / "PROCESSED" / "ok.md"), "data": {"kind": "nota", "title": "t"}})
        self.assertEqual(ev["id"], "PROCESSED/ok.md")


class LedgerAppendTests(_Base):
    def test_last_line_without_newline_is_not_glued(self):
        text = self.b.ledger_path.read_text(encoding="utf-8")
        self.b.ledger_path.write_text(text.rstrip("\n"), encoding="utf-8")      # salvo num editor que tira o \n final
        self.b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "t", "owner": "eu"}})
        events = Brain(self.b.inst).read_events()
        self.assertEqual([e["seq"] for e in events], [1, 2, 3])
        self.assertEqual(Brain(self.b.inst).validate_all(), [])

    def test_batch_is_one_append(self):
        evs = self.b.record([{"type": "action.opened", "by": "owner", "data": {"title": f"t{i}", "owner": "eu"}}
                             for i in range(3)])
        self.assertEqual([e["id"] for e in evs], ["TASK-0001", "TASK-0002", "TASK-0003"])
        self.assertTrue(self.b.ledger_path.read_text(encoding="utf-8").endswith("\n"))

    def test_unicode_line_separators_in_text_do_not_split_events(self):
        title = "a b c\x85d\x0ce\x1cf"
        self.b.record_one({"type": "action.opened", "by": "owner", "data": {"title": title, "owner": "eu"}})
        self.b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "depois", "owner": "eu"}})
        b2 = Brain(self.b.inst)
        self.assertEqual(b2.state.actions["TASK-0001"].title, title)
        self.assertEqual(b2.validate_all(), [])


class ClockTests(unittest.TestCase):
    def test_brain_now_with_utc_offset_is_converted_to_instance_tz(self):
        old = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = "2026-10-22T01:30:00+00:00"        # 22h30 do dia 21 no fuso da instância (-03:00)
        try:
            util.set_timezone("America/Sao_Paulo")
            self.assertEqual(util.today().isoformat(), "2026-10-21")
            self.assertTrue(util.iso_now().endswith("-03:00"))
        finally:
            os.environ["BRAIN_NOW"] = old if old is not None else ""
            if old is None:
                os.environ.pop("BRAIN_NOW")

    def test_bad_timezone_is_brain_error(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config").mkdir()
            (Path(td) / "config" / "brain.toml").write_text('timezone = "Marte/Olimpo"\n', encoding="utf-8")
            with self.assertRaises(util.BrainError):
                config.load(Path(td))
        util.set_timezone("America/Sao_Paulo")

    def test_atomic_write_leaves_no_temp_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "goals.md"
            p.write_text("antes\n", encoding="utf-8")
            with self.assertRaises(TypeError):
                util.atomic_write(p, 123)                               # type: ignore[arg-type]
            self.assertEqual(sorted(x.name for x in Path(td).iterdir()), ["goals.md"])
            self.assertEqual(p.read_text(encoding="utf-8"), "antes\n")


class AllowRuleTests(unittest.TestCase):
    def test_server_wide_and_wildcard_mcp_rules_are_refused(self):
        for bad in ("mcp__slack", "mcp__slack__*", "mcp__slack__slack_*"):
            self.assertTrue(config.is_external_write(bad), bad)
            with self.assertRaises(util.BrainError, msg=bad):
                config.check_allow_rule(bad)
        self.assertEqual(config.check_allow_rule("mcp__x__list_files"), "mcp__x__list_files")


class MigrationRaceTests(_Base):
    def test_apply_aborts_if_ledger_moved_since_plan(self):
        self.b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "t", "owner": "eu"}})
        lp = self.b.ledger_path
        lp.write_text(lp.read_text(encoding="utf-8").replace('"TASK-0001"', '"A-0001"'), encoding="utf-8")
        b = Brain(self.b.inst)
        mig = migrate_ids.plan_migration(b)
        self.assertIn("A-0001", mig.mapping)
        b.record_one({"type": "action.opened", "by": "owner", "data": {"title": "chegou no meio", "owner": "eu"}})
        before = lp.read_text(encoding="utf-8")
        with self.assertRaisesRegex(util.BrainError, "mudou"):
            migrate_ids.apply(b, mig)
        self.assertEqual(lp.read_text(encoding="utf-8"), before)
        self.assertFalse((b.inst.vault / migrate_ids.MARKER_REL).exists())
        self.assertEqual(list(b.inst.vault.parent.glob("brain-pre-ids-migration-*.zip")), [])
        self.assertIn("chegou no meio", json.dumps(Brain(b.inst).read_events(), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
