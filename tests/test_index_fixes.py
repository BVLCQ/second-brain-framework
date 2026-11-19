"""Regressões da projeção SQLite do ledger (#32, #34, #36)."""
from __future__ import annotations

import importlib.util as _ilu
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# sem BRAIN_NOW próprio: o módulo irmão (carregado abaixo) congela o relógio e a gente herda —
# um setdefault com data nova aqui vaza para os outros módulos quando rodam no mesmo processo
_spec = _ilu.spec_from_file_location("test_index", ROOT / "tests" / "test_index.py")
_ti = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_ti)

from brainlib import config, index, search, util                    # noqa: E402
from brainlib.core import Brain                                     # noqa: E402

_inst = _ti._inst
_brain = _ti._brain


def _corpus_brain(tmp: Path, n_events: int = 120, n_docs: int = 30) -> Brain:
    b = Brain(_inst(tmp))
    items = [
        {"type": "person.added", "id": "eu", "by": "owner",
         "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}},
        {"type": "person.added", "id": "marina-demo", "by": "owner",
         "data": {"name": "Marina-demo", "aliases": ["Mari-demo"], "email": "marina-demo@x.com"}},
    ]
    for i in range(n_events):
        items.append({
            "type": "action.opened",
            "by": "agent",
            "date": "2026-10-02",
            "prov": "observado",
            "source": "chat",
            "data": {"title": f"Tarefa sintética {i:03d} massa forno", "owner": "eu"},
        })
    b.record(items)
    docs_dir = b.inst.vault / "RAW" / "2026" / "10" / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    payload = ("Linha de documento sintético para medir indexação incremental.\n" * 80)
    for i in range(n_docs):
        (docs_dir / f"doc-{i:03d}.md").write_text(f"# Doc {i}\n\n{payload}", encoding="utf-8")
    return b


class IncrementalPredicateTests(unittest.TestCase):
    def test_append_avoids_full_rebuild_and_preserves_fts_docs(self):
        with tempfile.TemporaryDirectory() as td:
            b = _corpus_brain(Path(td))
            ledger = b.inst.processed / "_ledger" / "events.jsonl"
            self.assertGreater(ledger.stat().st_size, 8192)     # exercita janela deslizante > 8 KiB

            # 1ª construção (rebuild): fts_docs começa vazio e indexa todo o corpus
            with mock.patch.object(index, "_fts_doc_rows", wraps=index._fts_doc_rows) as spy_docs:
                st0 = index.rebuild(b)
                self.assertEqual(spy_docs.call_args[0][1], {})
            with index.connect(index.db_path(b.inst), ro=True) as con:
                expected_docs = con.execute("SELECT COUNT(*) FROM fts_docs").fetchone()[0]
            self.assertGreater(expected_docs, 30)

            # aquece e mede update estacionário no mesmo corpus sintético
            index.update(b)
            steady_times = []
            for _ in range(3):
                t0 = time.perf_counter()
                index.update(b)
                steady_times.append(time.perf_counter() - t0)
            steady_med = sorted(steady_times)[1]

            # append de novo evento (2ª escrita): não deve disparar full rebuild
            with mock.patch.object(index, "_fts_doc_rows", wraps=index._fts_doc_rows) as spy_docs:
                t0 = time.perf_counter()
                ev = b.record_one({"type": "action.opened", "by": "owner", "date": "2026-10-03",
                                   "data": {"title": "Nova tarefa incremental", "owner": "eu"}})
                append_dur = time.perf_counter() - t0
                passed_docs = spy_docs.call_args[0][1]

            self.assertEqual(len(passed_docs), expected_docs)     # fts_docs preservado (não deletado)
            st1 = index.status(b)
            self.assertTrue(st1["ok"], st1)
            self.assertEqual(st1["events"], st0["events"] + 1)
            self.assertEqual(st1["last_seq"], ev["seq"])
            # 2ª escrita próxima do update estacionário no mesmo corpus (margem para jitter de processo)
            self.assertLess(append_dur, max(steady_med * 5.0, steady_med + 0.15))

    def test_rewrite_same_size_triggers_full_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            ledger = b.inst.processed / "_ledger" / "events.jsonl"
            raw_bytes = ledger.read_bytes()
            old_text = b"Revisar alvenaria"
            new_text = b"Revisar madeiraaa"
            self.assertEqual(len(old_text), len(new_text))
            self.assertIn(old_text, raw_bytes)
            ledger.write_bytes(raw_bytes.replace(old_text, new_text, 1))
            self.assertEqual(ledger.stat().st_size, len(raw_bytes))

            b2 = Brain(config.load(Path(td)))
            with mock.patch.object(index, "_fts_doc_rows", wraps=index._fts_doc_rows) as spy_docs:
                st = index.update(b2)
                self.assertEqual(spy_docs.call_args[0][1], {})    # full rebuild limpou fts_docs
            self.assertTrue(st["ok"], st)
            hits = index.search_index(b2, "madeiraaa")
            self.assertTrue(hits)
            self.assertEqual(hits[0]["id"], b._ids_teste["late"])

    def test_truncate_triggers_full_rebuild(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            ledger = b.inst.processed / "_ledger" / "events.jsonl"
            lines = ledger.read_text(encoding="utf-8").splitlines()
            ledger.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")

            b2 = Brain(config.load(Path(td)))
            st = index.update(b2)
            self.assertEqual(st["events"], 3)
            with index.connect(index.db_path(b2.inst), ro=True) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 0)

    def test_slice_sha_edge_cases(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.jsonl"
            self.assertIsNone(index._ledger_slice_sha(p, 10))
            p.write_bytes(b"abc")
            self.assertEqual(index._ledger_slice_sha(p, 0), util.sha(""))
            self.assertEqual(index._ledger_slice_sha(p, -5), util.sha(""))
            self.assertIsNone(index._ledger_slice_sha(p, 10))
            self.assertEqual(index._ledger_slice_sha(p, 3), util.sha("abc"))

    def test_cas_does_not_overwrite_ledger_meta_when_stale(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            path = index.db_path(b.inst)
            with sqlite3.connect(path) as con:
                con.execute("INSERT OR REPLACE INTO meta VALUES ('last_seq', '999')")
                con.execute("INSERT OR REPLACE INTO meta VALUES ('ledger_size', '123456')")
                con.execute("INSERT OR REPLACE INTO meta VALUES ('ledger_sha_tail', 'vencedor0000')")
                con.commit()

            index.update(b)
            with index.connect(path, ro=True) as con:
                meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}
            self.assertEqual(meta["last_seq"], "999")
            self.assertEqual(meta["ledger_size"], "123456")
            self.assertEqual(meta["ledger_sha_tail"], "vencedor0000")


class Bm25WeightTests(unittest.TestCase):
    def _ranking_brain(self, tmp: Path) -> tuple[Brain, dict[str, str]]:
        b = Brain(_inst(tmp))
        b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                      "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
        b.record_one({"type": "area.added", "id": "operacoes", "by": "owner",
                      "data": {"name": "Operações"}})
        for i in range(12):
            b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                          "prov": "observado", "source": "chat",
                          "data": {"title": f"Item neutro {i}", "owner": "eu"}})
        kind_proc = b.record_one({"type": "process.added", "by": "owner", "date": "2026-10-02",
                                  "data": {"title": "Fornada padrão", "area": "operacoes",
                                           "io": "massa assada"}})
        body_act = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                                 "prov": "observado", "source": "chat",
                                 "data": {"title": "Revisar rotina diária", "owner": "eu",
                                          "origin": "seguir o processo documentado"}})
        title_act = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                                  "prov": "observado", "source": "chat",
                                  "data": {"title": "Revisar processo mensal", "owner": "eu",
                                           "origin": "conferir planilha de rotina"}})
        index.update(b)
        return b, {"kind": kind_proc["id"], "body": body_act["id"], "title": title_act["id"]}

    def test_title_ranks_strictly_above_kind_and_body(self):
        with tempfile.TemporaryDirectory() as td:
            b, ids = self._ranking_brain(Path(td))
            hits = index.search_index(b, "processo")
            by_id = {h["id"]: h for h in hits}
            self.assertIn(ids["title"], by_id)
            self.assertIn(ids["body"], by_id)
            self.assertIn(ids["kind"], by_id)
            self.assertGreater(by_id[ids["title"]]["score"], by_id[ids["body"]]["score"])
            self.assertGreater(by_id[ids["title"]]["score"], by_id[ids["kind"]]["score"])
            self.assertEqual(hits[0]["id"], ids["title"])

    def test_title_ranks_strictly_above_in_or_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            b, ids = self._ranking_brain(Path(td))
            hits = index.search_index(b, "processo inexistentexyz")
            self.assertTrue(hits)
            self.assertTrue(all(h.get("match") == "parcial" for h in hits))
            by_id = {h["id"]: h for h in hits}
            self.assertGreater(by_id[ids["title"]]["score"], by_id[ids["body"]]["score"])
            self.assertGreater(by_id[ids["title"]]["score"], by_id[ids["kind"]]["score"])
            self.assertEqual(hits[0]["id"], ids["title"])


class FreshnessTests(unittest.TestCase):
    def test_stale_index_returns_none_and_search_falls_back_to_refold(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            # grava evento no ledger sem atualizar o índice SQLite
            with mock.patch.object(Brain, "_index_update"):
                ev = b.record_one({"type": "action.opened", "by": "owner", "date": "2026-10-04",
                                   "data": {"title": "Comprar forno zzfreshtoken", "owner": "eu"}})

            self.assertIsNone(index.search_index(b, "zzfreshtoken"))
            self.assertIsNone(index.search_index(b, "alvenaria"))
            hits = search.search(b, "zzfreshtoken")
            self.assertTrue(any(h["id"] == ev["id"] for h in hits), hits)

    def test_missing_last_seq_or_sqlite_error_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            index.update(b)
            db = index.db_path(b.inst)
            with sqlite3.connect(db) as con:
                con.execute("DELETE FROM meta WHERE key = 'last_seq'")
                con.commit()
            self.assertIsNone(index.search_index(b, "alvenaria"))

            db.write_bytes(b"arquivo corrompido nao e sqlite")
            self.assertIsNone(index.search_index(b, "alvenaria"))
            hits = search.search(b, "alvenaria")
            self.assertTrue(any(h["id"] == b._ids_teste["late"] for h in hits))


if __name__ == "__main__":
    unittest.main()
