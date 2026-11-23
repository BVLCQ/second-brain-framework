"""Testes de desempenho: atalho stat no FTS, cache negativo de contêiner e fila memoizada (#66, #93, #94)."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from brainlib import config, dupes, index, providers, review  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from test_brain import _brain  # noqa: E402


class PerfIndexCacheReviewTests(unittest.TestCase):
    def setUp(self):
        providers.reset_auth_cache()
        dupes.clear_cache()
        review.clear_cache()

    def tearDown(self):
        providers.reset_auth_cache()
        dupes.clear_cache()
        review.clear_cache()

    def test_fts_update_skips_reading_unchanged_raw_files(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp)
            docs_dir = b.inst.vault / "RAW" / "2026" / "10" / "documents"
            docs_dir.mkdir(parents=True, exist_ok=True)
            files = []
            for i in range(5):
                p = docs_dir / f"doc-{i:02d}.md"
                p.write_text(f"# Documento {i}\nConteúdo inicial palavra{i}.\n", encoding="utf-8")
                files.append(p)

            index.rebuild(b)
            with index.connect(index.db_path(b.inst), ro=True) as con:
                row = con.execute("SELECT sha, size, mtime_ns FROM fts_docs WHERE path = ?",
                                  (b.inst.rel(files[0]),)).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[1], files[0].stat().st_size)
                self.assertEqual(row[2], files[0].stat().st_mtime_ns)

            # Novo evento no ledger: index.update(b) não deve reler nenhum arquivo RAW inalterado
            b.record_one({"type": "action.opened", "by": "owner",
                          "data": {"title": "Ação incremental sem tocar RAW", "owner": "eu"}})

            raw_reads: list[Path] = []
            orig_read_text = Path.read_text

            def counting_read_text(self_path: Path, *args, **kwargs):
                if docs_dir in self_path.parents:
                    raw_reads.append(self_path)
                return orig_read_text(self_path, *args, **kwargs)

            with mock.patch.object(Path, "read_text", counting_read_text):
                st = index.update(b)
            self.assertTrue(st["ok"], st)
            self.assertEqual(raw_reads, [])

            # Modifica exatamente 1 arquivo RAW (tamanho + mtime_ns diferentes): exatamente 1 leitura RAW
            target = files[2]
            prev_st = target.stat()
            target.write_text("# Documento 2\nConteúdo alterado termo_unico_c15_xyz.\n", encoding="utf-8")
            os.utime(target, ns=(prev_st.st_atime_ns, prev_st.st_mtime_ns + 1_000_000))

            raw_reads.clear()
            with mock.patch.object(Path, "read_text", counting_read_text):
                index.update(b)
            self.assertEqual(raw_reads, [target])

            hits = index.search_index(b, "termo_unico_c15_xyz")
            self.assertTrue(hits)
            self.assertEqual(hits[0]["path"], b.inst.rel(target))

    def test_fts_upgrades_v1_schema_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp)
            db = index.db_path(b.inst)
            db.parent.mkdir(parents=True, exist_ok=True)
            for p in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
                p.unlink(missing_ok=True)
            # Simula um banco legado v1 onde fts_docs só tem (path, sha)
            con = sqlite3.connect(db)
            try:
                con.executescript(
                    "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
                    "CREATE TABLE fts_docs(path TEXT PRIMARY KEY, sha TEXT);"
                    "INSERT INTO meta VALUES ('schema_version', '1');"
                    "INSERT INTO meta VALUES ('last_seq', '1');"
                )
            finally:
                con.close()
            st = index.update(b)
            self.assertTrue(st["ok"], st)
            with index.connect(db, ro=True) as con:
                cols = {r[1] for r in con.execute("PRAGMA table_info(fts_docs)")}
                self.assertTrue({"path", "sha", "size", "mtime_ns"}.issubset(cols))
                ver = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
                self.assertEqual(ver[0], index.SCHEMA_VERSION)

    def test_container_probe_caches_none_result_for_ttl(self):
        calls = 0

        def fail_probe(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise FileNotFoundError("docker ausente")

        t_now = [1000.0]
        with mock.patch.object(providers.time, "time", side_effect=lambda: t_now[0]):
            res1 = providers._container_store(run=fail_probe)
            res2 = providers._container_store(run=fail_probe)
            self.assertIsNone(res1)
            self.assertIsNone(res2)
            self.assertEqual(calls, 1)

            # Dentro do TTL de 60s mantém o None em cache
            t_now[0] = 1059.0
            self.assertIsNone(providers._container_store(run=fail_probe))
            self.assertEqual(calls, 1)

            # Após 60s re-sonda (inclusive para retorno não-zero -> False)
            t_now[0] = 1061.0

            class _Res:
                def __init__(self, rc: int):
                    self.returncode = rc

            nz_calls = 0

            def nz_probe(*args, **kwargs):
                nonlocal nz_calls
                nz_calls += 1
                return _Res(1)

            self.assertFalse(providers._container_store(run=nz_probe))
            self.assertFalse(providers._container_store(run=nz_probe))
            self.assertEqual(nz_calls, 1)

    def test_review_queue_memoizes_dupes_across_fresh_brain_instances(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            b = _brain(tmp)
            batch = [
                {"type": "action.opened", "by": "owner",
                 "data": {"title": f"Revisar módulo desempenho lote {i}", "owner": "eu", "not_dup": []}}
                for i in range(40)
            ]
            b.record(batch)
            inst_root = b.inst.root

            with mock.patch.object(dupes.Index, "__init__", wraps=dupes.Index.__init__, autospec=True) as spy_idx:
                s1 = review.summary(Brain(config.load(inst_root)))
                s2 = review.summary(Brain(config.load(inst_root)))
                q_filtered = review.queue(Brain(config.load(inst_root)), kind="dupe")
                self.assertEqual(spy_idx.call_count, 1)
                self.assertEqual(s1, s2)
                self.assertEqual(q_filtered["counts"], s1["counts"])

                # Mutação no retorno não pode corromper o cache
                q_filtered["counts"]["dupe"] = -999
                if q_filtered["items"]:
                    q_filtered["items"][0]["why"].append("mutated")
                q_again = review.queue(Brain(config.load(inst_root)), kind="dupe")
                self.assertEqual(q_again["counts"]["dupe"], s1["counts"]["dupe"])
                if q_again["items"]:
                    self.assertNotIn("mutated", q_again["items"][0]["why"])

                # Novo evento invalida o cache e recalcula
                Brain(config.load(inst_root)).record_one(
                    {"type": "action.opened", "by": "owner",
                     "data": {"title": "Nova tarefa após cache", "owner": "eu"}}
                )
                s3 = review.summary(Brain(config.load(inst_root)))
                self.assertEqual(spy_idx.call_count, 2)
                self.assertGreaterEqual(s3["counts"]["dupe"], s1["counts"]["dupe"])

    def test_caches_are_bounded_lru(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for i in range(12):
                dupes.pairs(b.state, cache_key=f"vault-{i}")
                b_fake_root = Path(td) / f"v-{i}"
                b.inst.root = b_fake_root
                review.queue(b)
            self.assertEqual(len(dupes._PAIRS_CACHE), dupes._CACHE_MAX)
            self.assertEqual(len(review._QUEUE_CACHE), review._CACHE_MAX)


if __name__ == "__main__":
    unittest.main()
