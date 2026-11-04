"""Projeção SQLite do ledger (Fase 1 do plano da memória) — stdlib unittest, sem rede."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, index, search, util                    # noqa: E402
from brainlib.core import Brain                                     # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[outbound]\nallow = ["marina-demo"]\n\n'
        '[memory]\nengine = "none"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: teste\n\n"
        "### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Mari-demo"], "email": "marina-demo@x.com"}})
    b.record_one({"type": "decision.made", "id": "DEC-0001", "by": "owner", "date": "2026-10-01",
                  "data": {"title": "Decisão da alvenaria", "decided_by": ["marina-demo"],
                           "rationale": "parede de tijolos"}})
    late = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                         "prov": "observado", "source": "chat",
                         "data": {"title": "Revisar alvenaria", "owner": "marina-demo", "due": "2026-10-04",
                                  "project": "PROJ-1"}})
    nolater = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                            "prov": "observado", "source": "chat",
                            "data": {"title": "Tarefa sem prazo", "owner": "eu"}})
    fb = b.record_one({"type": "feedback.added", "by": "agent", "date": "2026-10-03",
                       "prov": "observado", "source": "chat",
                       "data": {"kind": "sugestao", "title": "zzquuxtoken no painel", "body": "corpo"}})
    prop = b.record_one({"type": "proposal.opened", "by": "agent", "date": "2026-10-03",
                         "prov": "observado", "source": "chat",
                         "data": {"kind": "atualizar-acao", "summary": "dar prazo à tarefa",
                                  "target": nolater["id"]}})
    b.record_one({"type": "area.added", "id": "producao", "by": "owner",
                  "data": {"name": "Produção"}})
    proc = b.record_one({"type": "process.added", "by": "owner", "date": "2026-10-01",
                         "data": {"title": "Fornada", "area": "producao", "io": "massa → pão"}})
    b.record_one({"type": "process.updated", "id": proc["id"], "by": "owner", "date": "2026-10-02",
                  "data": {"note": "notazzz do processo"}})
    msg = b.record_one({"type": "message.drafted", "by": "agent", "date": "2026-10-03",
                        "prov": "observado", "source": "chat",
                        "data": {"to": "marina-demo", "text": "rascunho zzmsgtoken", "channel": "slack"}})
    b._ids_teste = {"late": late["id"], "nolater": nolater["id"], "fb": fb["id"],
                    "prop": prop["id"], "proc": proc["id"], "msg": msg["id"]}
    return b


class UpdateTests(unittest.TestCase):
    def test_rebuild_equals_incremental_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            st = index.update(b)
            self.assertTrue(st["ok"])
            self.assertEqual(st["events"], len(b.state.events))
            self.assertEqual(index.update(b)["last_seq"], st["last_seq"])   # no-op não muda nada
            st2 = index.rebuild(b)
            self.assertEqual(st2["events"], st["events"])
            self.assertEqual(st2["last_seq"], st["last_seq"])

    def test_record_hook_updates_index(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            n0 = index.status(b)["events"]
            b.record_one({"type": "action.opened", "by": "owner", "date": "2026-10-03",
                          "data": {"title": "via hook", "owner": "eu"}})
            st = index.status(b)                                    # SEM update() explícito: o hook do record fez
            self.assertTrue(st["ok"], st)
            self.assertEqual(st["events"], n0 + 1)

    def test_shrunk_ledger_triggers_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            # simula edição manual: trunca o ledger e regrava menor
            ledger = b.inst.processed / "_ledger" / "events.jsonl"
            lines = ledger.read_text(encoding="utf-8").splitlines()
            ledger.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
            b2 = Brain(config.load(Path(td)))
            st = index.update(b2)
            self.assertEqual(st["events"], 2)                        # refaz tudo, não fica lixo


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.b = _brain(Path(self.td.name))
        index.update(self.b)

    def tearDown(self):
        self.td.cleanup()

    def _con(self):
        return index.connect(index.db_path(self.b.inst), ro=True)

    def test_overdue_and_open_filters(self):
        with self._con() as con:
            open_ids = [a["id"] for a in index.query_actions(con, open=True)]
            self.assertEqual(open_ids, [self.b._ids_teste["late"], self.b._ids_teste["nolater"]])
            # due 2026-10-04 venceu nos DOIS relógios (BRAIN_NOW 2026-10-09 e date('now') real < 2030)
            late = [a["id"] for a in index.query_actions(con, open=True, overdue=True)]
            self.assertEqual(late, [self.b._ids_teste["late"]])
            mine = [a["id"] for a in index.query_actions(con, open=True, person="eu")]
            self.assertEqual(mine, [self.b._ids_teste["nolater"]])

    def test_person_by_alias(self):
        with self._con() as con:
            p = index.query_person(con, "Mari-demo")
            self.assertEqual(p["id"], "marina-demo")
            self.assertEqual(p["actions_open"], 1)
            self.assertIsNone(index.query_person(con, "ninguem-assim"))

    def test_entity_and_planning(self):
        with self._con() as con:
            d = index.query_entity(con, "DEC-0001")
            self.assertTrue(d["found"])
            self.assertEqual(d["title"], "Decisão da alvenaria")
            self.assertFalse(index.query_entity(con, "TASK-9999")["found"])
            pr = index.query_entity(con, "PROJ-1")
            self.assertEqual(pr["kind"], "project")
            g = index.query_entity(con, "GOAL-1")
            self.assertEqual(g["kind"], "goal")

    def test_sql_refuses_writes(self):
        with self._con() as con:
            for bad in ("DELETE FROM events", "INSERT INTO meta VALUES ('x','y')", "ATTACH DATABASE 'x' AS y",
                        "SELECT 1; SELECT 2"):
                with self.assertRaises(util.BrainError):
                    index.query_sql(con, bad)
            self.assertEqual(index.query_sql(con, "SELECT COUNT(*) n FROM actions")[0]["n"], 2)

    def test_event_classes(self):
        with self._con() as con:
            rows = {r["class"]: r["n"] for r in
                    index.query_sql(con, "SELECT class, COUNT(*) n FROM events GROUP BY class")}
            self.assertEqual(rows.get("dono"), 6)          # 2 person + decision + area + process added/updated
            self.assertEqual(rows.get("fato"), 5)          # 2 action + fb + prop + msg, by agent


class FtsTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.b = _brain(Path(self.td.name))
        index.update(self.b)

    def tearDown(self):
        self.td.cleanup()

    def test_terms_sanitized(self):
        self.assertEqual(index.fts_terms("forno lenha"), '"forno" "lenha"*')   # frase-prefixo FTS5
        self.assertEqual(index.fts_terms('aspas "x"'), '"aspas" """x"""*')  # aspas internas dobradas

    def test_case_and_accent_insensitive(self):
        hits = index.search_index(self.b, "ALVENARIA")
        self.assertTrue(any(h["id"] == self.b._ids_teste["late"] for h in hits))

    def test_and_then_or_partial(self):
        hits = index.search_index(self.b, "alvenaria inexistente")
        self.assertTrue(hits)
        self.assertTrue(all(h.get("match") == "parcial" for h in hits))

    def test_partial_id_prefix(self):
        eid = self.b._ids_teste["late"]                   # ex.: TASK-0001 — prefixo deve achar (semântica R2)
        hits = index.search_index(self.b, eid[:-1])
        self.assertTrue(any(h["id"] == eid for h in hits))

    def test_no_hit_returns_empty(self):
        self.assertEqual(index.search_index(self.b, "zzzqqqxxx"), [])

    def test_search_falls_back_without_index(self):
        import shutil
        shutil.rmtree(self.b.inst.fresh / index.DIR_NAME)
        self.assertIsNone(index.search_index(self.b, "alvenaria"))
        hits = search.search(self.b, "alvenaria")          # caminho antigo (refold) continua valendo
        self.assertTrue(any(h["id"] == self.b._ids_teste["late"] for h in hits))


class ReviewFixTests(unittest.TestCase):
    """Regressões do revisor independente (F1-F6)."""

    def test_fb_and_prop_entities_found(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            with index.connect(index.db_path(b.inst), ro=True) as con:
                fb = index.query_entity(con, b._ids_teste["fb"])
                self.assertTrue(fb["found"], fb)
                self.assertEqual(fb["title"], "zzquuxtoken no painel")
                pr = index.query_entity(con, b._ids_teste["prop"])
                self.assertTrue(pr["found"])
                self.assertEqual(pr["kind"], "atualizar-acao")

    def test_entity_without_table_falls_back_to_event(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            with index.connect(index.db_path(b.inst), ro=True) as con:
                m = index.query_entity(con, b._ids_teste["msg"])
                self.assertTrue(m["found"])
                self.assertEqual(m["type"], "message.drafted")

    def test_wal_enabled(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            with index.connect(index.db_path(b.inst), ro=True) as con:
                mode = con.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")

    def test_search_parity_process_notes(self):
        """F3: campo que o search antigo cobria continua achável COM índice."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            hits = search.search(b, "notazzz")
            self.assertTrue(any(h["id"] == b._ids_teste["proc"] for h in hits),
                            f"nota de processo perdida com índice: {hits}")

    def test_title_weighted_above_body(self):
        """F5: bm25 3× no TÍTULO — hit de título ranqueia acima de hit só-no-corpo."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            hits = index.search_index(b, "alvenaria")
            self.assertTrue(hits)
            by_title = [h for h in hits if "alvenaria" in util.fold(h["title"])]
            by_body = [h for h in hits if "alvenaria" not in util.fold(h["title"])]
            if by_title and by_body:
                self.assertLessEqual(by_title[0]["score"], by_body[0]["score"])  # score negativo = melhor


class ConcurrencyTests(unittest.TestCase):
    def test_two_processes_no_stale_no_corruption(self):
        """R1: dois `brain index update` em paralelo → last_seq = máximo, zero stale (flock + CAS)."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            env = {**os.environ, "BRAIN_HOME": td}
            script = ("import sys; sys.path.insert(0, %r); "
                      "from brainlib import config, index, core; "
                      "b = core.Brain(config.load()); index.update(b)" % str(ROOT))
            procs = [subprocess.Popen([sys.executable, "-c", script], cwd=ROOT, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
            for p in procs:
                _, err = p.communicate(timeout=120)
                self.assertEqual(p.returncode, 0, err.decode()[:400])
            st = index.status(b)
            self.assertTrue(st["ok"], st)
            self.assertEqual(st["last_seq"], b.state.max_seq())


if __name__ == "__main__":
    unittest.main()
