"""Testes do núcleo v2 — stdlib unittest, sem rede, relógio congelado."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, extract as extract_mod, focus, harvest, mcp_server, outbox, planning, people, render, schema, share, snapshot, util
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
        '[outbound]\nallow = ["ana", "#time"]\n\n'
        '[publish]\ndestinations = ["slack:#time"]\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## G1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### P1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] P1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n"
        "- [ ] P1.2 Outro · prazo: 2026-11-01\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "ana", "by": "owner",
                  "data": {"name": "Ana Ribeiro", "aliases": ["Ana", "Bia"], "email": "ana@x.com"}})
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
        self.assertEqual(util.fold("  Ana  Ribeiro "), "ana ribeiro")
        self.assertEqual(util.slugify("Ana Ribeiro"), "ana-ribeiro")

    def test_today_frozen(self):
        self.assertEqual(util.today(), date(2026, 10, 9))


class PlanningTests(unittest.TestCase):
    def test_template_has_no_fake_tree(self):
        plan = planning.load(ROOT / "template" / "PLANNING" / "goals.md")
        self.assertEqual(plan.goals, {})
        self.assertFalse(plan.warnings)

    def test_skips_fenced_example(self):
        plan = planning.parse("# x\n\n```\n## G9 — Exemplo\n- [ ] P9.1 Foo · prazo: AAAA-MM-DD\n```\n")
        self.assertEqual(plan.goals, {})
        self.assertFalse(plan.warnings)

    def test_parse_and_progress(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(Path(td))
            plan = planning.load(inst.planning_file)
            self.assertEqual(list(plan.goals), ["G1"])
            self.assertEqual(list(plan.projects), ["P1"])
            self.assertEqual(plan.deliverables["P1.1"].weight, 2)
            self.assertFalse(plan.warnings)
            planning.set_deliverable(inst.planning_file, "P1.1", "feito", date(2026, 10, 8))
            plan = planning.load(inst.planning_file)
            self.assertEqual(plan.deliverables["P1.1"].status, "feito")
            # peso 2 de 3
            self.assertEqual(plan.progress("P1")["pct"], 67)
            self.assertEqual(plan.progress("P1")["done"], 1)
            self.assertEqual(plan.progress("P1")["weight_done"], 2)
            self.assertIn("peso 2/3", planning.format_progress(plan.progress("P1")))


class LedgerTests(unittest.TestCase):
    def test_ids_and_close_cascade(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            a1 = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Revisar", "owner": "ana", "list": "waiting"}})
            self.assertEqual(a1["id"], "A-0001")
            a2 = b.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Publicar", "owner": "eu", "due": "2026-10-12",
                                        "effort_min": 60, "project": "P1", "blocked_by": ["A-0001"]}})
            self.assertEqual(a2["id"], "A-0002")
            self.assertEqual(b.state.blocked(b.state.actions["A-0002"]), ["A-0001"])
            b.record_one({"type": "action.closed", "id": "A-0001", "by": "owner",
                          "data": {"how": "revisou"}})
            # cascade is CLI-level; ledger just closes
            self.assertFalse(b.state.actions["A-0001"].open)
            self.assertEqual(b.state.blocked(b.state.actions["A-0002"]), [])
            self.assertEqual(b.validate_all(), [])

    def test_decision_supersede(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            d1 = b.record_one({"type": "decision.made", "by": "agent", "prov": "observado",
                               "source": "chat",
                               "data": {"title": "Congelar", "decided_by": ["ana"], "project": "P1"}})
            b.record_one({"type": "decision.made", "by": "agent", "prov": "doc", "source": "chat",
                          "data": {"title": "Portar", "decided_by": ["ana"], "project": "P1",
                                   "supersedes": d1["id"]}})
            self.assertEqual(b.state.decisions[d1["id"]].status, "substituida")

    def test_reject_unknown_person(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "action.opened", "by": "owner",
                              "data": {"title": "x", "owner": "ghost"}})

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
            self.assertEqual(people.resolve(b.state, "Ana"), ["ana"])
            self.assertEqual(people.resolve(b.state, "ana@x.com"), ["ana"])
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
            self.assertEqual(first["action"], "A-0001")
            # não começa dentro do busy (11-12 + buffer tratado em parse_busy; aqui busy já cortado)
            start = util.parse_dt(first["start"])
            self.assertFalse(datetime(2026, 10, 9, 11, 0, tzinfo=util.tz()) <= start <
                             datetime(2026, 10, 9, 12, 0, tzinfo=util.tz()))

    def test_ics_roundtrip_shape(self):
        ics = focus.to_ics("F-0001", [{"action": "A-0001", "start": "2026-10-09T14:00:00-03:00",
                                       "end": "2026-10-09T15:00:00-03:00", "minutes": 60}],
                           {"A-0001": "Ler"}, "Foco")
        self.assertIn("BEGIN:VEVENT", ics)
        self.assertIn("SUMMARY:Foco · A-0001 · Ler", ics)

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
            ev = outbox.draft(b, "ana", "Oi Ana, tudo bem?", None, "teste")
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
            cal.delete_guarded("evt1", "A-0001")
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
            ev = outbox.draft(b, "ana", "oi", None, None)
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
                                   "effort_min": 45, "project": "P1"}})
            b.record_one({"type": "decision.made", "by": "agent", "prov": "observado", "source": "chat",
                          "data": {"title": "Draft sai sem pipeline", "decided_by": ["ana"],
                                   "project": "P1"}})
            report = render.render_all(b, do_harvest=False)
            self.assertGreater(report["total"], 8)
            self.assertTrue(Path(report["dashboard"]).is_file())
            html = Path(report["dashboard"]).read_text(encoding="utf-8")
            self.assertNotIn("__DATA__", html)
            self.assertIn("Enviar draft", html)

            path = share.export(b, "project", "P1", "md")
            text = path.read_text(encoding="utf-8")
            self.assertIn("Draft sai sem pipeline", text)
            self.assertIn("Ana Ribeiro", text)
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
                self.assertTrue(any(g["id"] == "G1" for g in ov["goals"]))
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
            self.assertIn("Padronização de métricas", dash)
            self.assertIn("Ana Ribeiro", dash)
            self.assertTrue((target / "vault" / "FRESH" / "todo.md").exists())
            self.assertTrue((target / "vault" / "FRESH" / "dashboard" / "index.html").exists())
            self.assertFalse((target / "vault" / "FRESH" / "bases").exists())
            self.assertTrue((target / "vault" / "FRESH" / "projects" / "P1.md").exists())




class ExtractTests(unittest.TestCase):
    """Funil do extrator sem rede: parse, refinamento e dry-run."""

    def test_parse_json_fences_and_prose(self):
        self.assertEqual(extract_mod.parse_json('```json\n[{"type":"action.opened"}]\n```'),
                         [{"type": "action.opened"}])
        self.assertEqual(extract_mod.parse_json('Aqui vai:\n[{"a":1}]\nobrigado'),
                         [{"a": 1}])
        self.assertEqual(extract_mod.parse_json('{"type":"decision.made"}'),
                         [{"type": "decision.made"}])
        with self.assertRaises(util.BrainError):
            extract_mod.parse_json("sem json aqui")

    def test_guess_kind(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = {
                "slack-time-dados.md": "conector",
                "ata-reuniao-x.md": "reuniao",
                "lembrete-rapido.md": "nota",
            }
            for name, want in cases.items():
                f = root / name
                f.write_text("conteúdo qualquer " * 3, encoding="utf-8")
                self.assertEqual(extract_mod.guess_kind(f), want, name)
            big = root / "politica-gigante.md"
            big.write_text("x" * 8000, encoding="utf-8")
            self.assertEqual(extract_mod.guess_kind(big), "documento")

    def test_refine_and_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            raw_items = [
                {"type": "action.opened", "id": "A-9999", "data": {"title": "Ler política",
                 "owner": "Ana", "list": "mine", "due": "2026-10-15", "effort_min": 30}},
                {"type": "decision.made", "data": {"title": "Congelar pipeline",
                 "decided_by": "Ana Ribeiro", "project": "P1"}},
                {"type": "action.closed", "data": {"id": "A-0001"}},   # fora do escopo
            ]
            items, dropped = extract_mod.refine(b, raw_items, "RAW/2026/10/x.md")
            self.assertEqual(len(items), 2)
            self.assertEqual(dropped, ["tipo fora do escopo do extrator: 'action.closed'"])
            # alias Ana → ana resolvido deterministicamente; id inventado ignorado
            self.assertEqual(items[0]["data"]["owner"], "ana")
            # "eu" do modelo mapeia para o dono real da instância, seja qual for o id
            items_eu, _ = extract_mod.refine(b, [{"type": "action.opened",
                "data": {"title": "x", "owner": "Eu"}}], "RAW/x.md")
            self.assertEqual(items_eu[0]["data"]["owner"], "eu")
            self.assertEqual(items[1]["data"]["decided_by"], ["ana"])
            self.assertNotIn("id", items[0])
            self.assertEqual(items[0]["prov"], "observado")
            self.assertEqual(items[0]["source"], "RAW/2026/10/x.md")
            ok, errs = extract_mod.dry_run(b, items)
            self.assertEqual(len(ok), 2)
            self.assertEqual(errs, [])
            # pessoa desconhecida: o dry-run recusa (validação do ledger)
            bad = [{"type": "action.opened", "by": "agent", "prov": "observado",
                    "source": "RAW/x.md", "data": {"title": "x", "owner": "fantasma"}}]
            ok2, errs2 = extract_mod.dry_run(b, bad)
            self.assertEqual(ok2, [])
            self.assertIn("fantasma", errs2[0])

    def test_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            f = Path(td) / "vault" / "RAW" / "inbox" / "n.md"
            f.write_text("texto", encoding="utf-8")
            with self.assertRaises(util.BrainError):
                extract_mod.extract(b, f)

    def test_outside_vault_refused(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            outside = Path(td) / "fora.md"
            outside.write_text("x", encoding="utf-8")
            b.inst.cfg["extractor"]["enabled"] = True
            b.inst.cfg["extractor"]["model"] = "m"
            with self.assertRaises(util.BrainError):
                extract_mod.extract(b, outside)


class SchemaCoverageTests(unittest.TestCase):
    def test_unknown_type(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError):
                b.record_one({"type": "action.exploded", "by": "owner", "data": {}})


if __name__ == "__main__":
    unittest.main()
