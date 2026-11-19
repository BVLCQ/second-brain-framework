"""Testes do recall temporal, contradições sem LLM, supersessão explícita e formato as-of (#58)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, memory, recall_rank, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _brain(tmp: Path, mem_toml: str = 'engine = "hindsight"\n') -> Brain:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH", "reports"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        f'[owner]\nid = "eu"\nname = "Marina-demo"\n\n[memory]\n{mem_toml}',
        encoding="utf-8",
    )
    horizon = (date.today() + timedelta(days=90)).isoformat()
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        f"# PLANNING\n\n## GOAL-1 — Abrir segundo ponto\n- status: ativo\n- horizonte: {horizon}\n- por quê: t\n",
        encoding="utf-8",
    )
    return Brain(config.load(tmp))


class _MockRecallServer:
    """Servidor HTTP local efêmero imitando `/v1/default/banks/<bank>/memories/recall` e `/memories`."""

    def __init__(self, results: list[dict], extra_top: dict | None = None):
        outer = self
        self.results = results
        self.extra_top = extra_top or {}
        self.requests: list[tuple[str, dict]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                outer.requests.append((self.path, json.loads(raw)))
                if self.path.endswith("/memories"):
                    payload = {"success": True, "async": True, "operation_id": "op-corr-1"}
                else:
                    payload = {**outer.extra_top, "results": outer.results}
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


class SelectiveDecayTests(unittest.TestCase):
    def test_estado_decays_while_perennial_classes_keep_full_weight(self):
        today = date.today()
        d90 = (today - timedelta(days=90)).isoformat()
        d5 = (today - timedelta(days=5)).isoformat()
        d365 = (today - timedelta(days=365)).isoformat()

        items = [
            {
                "id": "old-estado",
                "text": "Forno em manutenção na unidade centro",
                "document_id": "RAW/2026/08/notes/n1.md",
                "occurred_start": d90,
                "scores": {"semantic": 0.90},
                "metadata": {"fact_class": "estado"},
            },
            {
                "id": "recent-estado",
                "text": "Forno operando normalmente hoje",
                "document_id": "RAW/2026/11/notes/n2.md",
                "occurred_start": d5,
                "scores": {"semantic": 0.60},
                "metadata": {"fact_class": "estado"},
            },
            {
                "id": "old-decisao",
                "text": "Decidimos usar fermentação natural",
                "document_id": "ledger/DEC-0001",
                "occurred_start": d365,
                "scores": {"semantic": 0.80},
            },
            {
                "id": "old-identidade",
                "text": "Dono da Padaria Pão Quente",
                "document_id": "PROFILE/owner.md",
                "occurred_start": d365,
                "scores": {"semantic": 0.75},
            },
            {
                "id": "old-preferencia",
                "text": "Prefere comunicação direta e objetiva",
                "document_id": "PROFILE/preferences.md",
                "occurred_start": d365,
                "scores": {"semantic": 0.70},
            },
        ]

        ranked = recall_rank.rerank(items, half_life_days=45, today=today)
        by_id = {it["id"]: it for it in ranked}

        self.assertAlmostEqual(by_id["old-estado"]["decay_factor"], 0.25, places=6)
        self.assertAlmostEqual(by_id["old-estado"]["score_adjusted"], 0.225, places=6)
        self.assertGreater(by_id["recent-estado"]["score_adjusted"], by_id["old-estado"]["score_adjusted"])
        order = [it["id"] for it in ranked]
        self.assertLess(order.index("recent-estado"), order.index("old-estado"))

        for pid in ("old-decisao", "old-identidade", "old-preferencia"):
            self.assertEqual(by_id[pid]["decay_factor"], 1.0)
        self.assertEqual(by_id["old-decisao"]["fact_class"], "decisao")
        self.assertEqual(by_id["old-identidade"]["fact_class"], "identidade")
        self.assertEqual(by_id["old-preferencia"]["fact_class"], "preferencia")

    def test_half_life_zero_disables_decay(self):
        today = date.today()
        d90 = (today - timedelta(days=90)).isoformat()
        self.assertEqual(recall_rank.decay_factor("estado", d90, 0, today), 1.0)
        self.assertEqual(recall_rank.decay_factor("estado", d90, -10, today), 1.0)

    def test_classify_fact_by_document_id_and_config_default(self):
        self.assertEqual(recall_rank.classify_fact({"document_id": "ledger/TASK-0001"}), "compromisso")
        self.assertEqual(recall_rank.classify_fact({"document_id": "ledger/FOCUS-0002"}), "compromisso")
        self.assertEqual(recall_rank.classify_fact({"document_id": "config/brain.toml"}), "config")
        self.assertEqual(recall_rank.classify_fact({"document_id": "RAW/misc/nota.md", "text": "x"}), "estado")
        self.assertEqual(config.DEFAULTS["memory"]["recall_half_life_days"], 45)


class ContradictionTests(unittest.TestCase):
    def test_temporal_conflict_pairs_preserve_both_and_mark_status(self):
        today = date.today()
        d30 = (today - timedelta(days=30)).isoformat()
        d3 = (today - timedelta(days=3)).isoformat()
        d10_ago = (today - timedelta(days=10)).isoformat()
        d5_ahead = (today + timedelta(days=5)).isoformat()

        items = [
            {
                "id": "loc-old",
                "text": "PROJ-1 local: loja da esquina",
                "document_id": "RAW/2026/10/meetings/ata-1.md",
                "occurred_start": d30,
                "scores": {"semantic": 0.95},
            },
            {
                "id": "loc-new",
                "text": "PROJ-1 local: espaço da galeria",
                "document_id": "RAW/2026/11/meetings/ata-2.md",
                "occurred_start": d3,
                "scores": {"semantic": 0.85},
            },
            {
                "id": "due-old",
                "text": f"TASK-0002 prazo: {d10_ago}",
                "document_id": "RAW/2026/10/notes/n1.md",
                "occurred_start": d30,
                "scores": {"semantic": 0.80},
            },
            {
                "id": "due-new",
                "text": f"TASK-0002 prazo: {d5_ahead}",
                "document_id": "RAW/2026/11/notes/n2.md",
                "occurred_start": d3,
                "scores": {"semantic": 0.78},
            },
            {
                "id": "clean-fact",
                "text": "GOAL-1 status: ativo",
                "document_id": "PLANNING/goals.md",
                "occurred_start": d3,
                "scores": {"semantic": 0.88},
            },
        ]

        ranked = recall_rank.rerank(items, half_life_days=45, today=today)
        self.assertEqual(len(ranked), 5)  # nunca apaga nenhum item
        by_id = {it["id"]: it for it in ranked}

        self.assertEqual(by_id["loc-new"]["conflict_status"], "vale")
        self.assertIsNone(by_id["loc-new"]["superseded_by"])
        self.assertEqual(by_id["loc-old"]["conflict_status"], "supercedado")
        self.assertEqual(by_id["loc-old"]["superseded_by"], "loc-new")
        self.assertEqual(by_id["loc-old"]["conflict_key"], "proj-1:local")

        self.assertEqual(by_id["due-new"]["conflict_status"], "vale")
        self.assertEqual(by_id["due-old"]["conflict_status"], "supercedado")
        self.assertEqual(by_id["due-old"]["superseded_by"], "due-new")

        self.assertIsNone(by_id["clean-fact"]["conflict_status"])
        self.assertIsNone(by_id["clean-fact"]["superseded_by"])

        # Fatos ativos ("vale") ranqueiam acima dos supercedados mesmo com score semântico menor
        ids = [it["id"] for it in ranked]
        self.assertLess(ids.index("loc-new"), ids.index("loc-old"))
        self.assertLess(ids.index("due-new"), ids.index("due-old"))

    def test_spv_avoids_false_positives_on_ambiguous_prose(self):
        d_target = (date.today() + timedelta(days=14)).isoformat()
        self.assertEqual(recall_rank.extract_spv({"text": "Precisamos definir um prazo logo"}), ("", "", ""))
        self.assertEqual(recall_rank.extract_spv({"text": "PROJ-1 precisa de um novo local"}), ("", "", ""))
        self.assertEqual(
            recall_rank.extract_spv({"text": f"O prazo da TASK-0002 mudou para {d_target}"}),
            ("task-0002", "prazo", d_target),
        )


class ExplicitSupersedeTests(unittest.TestCase):
    def test_metadata_supersedes_and_local_store_mark_unrelated_texts(self):
        today = date.today()
        d20 = (today - timedelta(days=20)).isoformat()
        d1 = (today - timedelta(days=1)).isoformat()

        # 1) metadata.supersedes sem regex em comum
        items_meta = [
            {
                "id": "fact-old",
                "text": "Vamos abrir de segunda a sexta",
                "document_id": "RAW/2026/10/notes/horario.md",
                "occurred_start": d20,
                "scores": {"semantic": 0.95},
            },
            {
                "id": "fact-new",
                "text": "Atendimento agora inclui sábados de manhã",
                "document_id": "RAW/2026/11/notes/ajuste.md",
                "occurred_start": d1,
                "scores": {"semantic": 0.70},
                "metadata": {"supersedes": "fact-old"},
            },
        ]
        ranked_meta = recall_rank.rerank(items_meta, today=today)
        by_id = {it["id"]: it for it in ranked_meta}
        self.assertEqual(by_id["fact-old"]["conflict_status"], "supercedado")
        self.assertEqual(by_id["fact-old"]["superseded_by"], "fact-new")
        self.assertEqual(by_id["fact-new"]["conflict_status"], "vale")

        # 2) record_supersede + retain_correction persistidos em .memory-supersedes.json
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            memory.record_supersede(b, "RAW/2026/11/notes/novo.md", "RAW/2026/10/notes/antigo.md", reason="atualizado")
            loaded = memory._load_supersedes(b.inst)
            self.assertEqual(loaded["RAW/2026/10/notes/antigo.md"], "RAW/2026/11/notes/novo.md")

            srv = _MockRecallServer([
                {
                    "text": "Texto antigo sem estrutura",
                    "document_id": "RAW/2026/10/notes/antigo.md",
                    "occurred_start": d20,
                    "scores": {"semantic": 0.95},
                },
                {
                    "text": "Texto novo corrigido",
                    "document_id": "RAW/2026/11/notes/novo.md",
                    "occurred_start": d1,
                    "scores": {"semantic": 0.70},
                },
            ])
            try:
                config.set_keys(b.inst, "memory", {"url": srv.url})
                b.inst = config.load(b.inst.root)
                res = memory.recall(b, "horário")
                docs = {r["document_id"]: r for r in res["results"]}
                self.assertEqual(docs["RAW/2026/10/notes/antigo.md"]["conflict_status"], "supercedado")
                self.assertEqual(docs["RAW/2026/10/notes/antigo.md"]["superseded_by"], "RAW/2026/11/notes/novo.md")
                self.assertEqual(docs["RAW/2026/11/notes/novo.md"]["conflict_status"], "vale")

                # retain_correction envia metadata.supersedes e grava link local
                corr = memory.retain_correction(b, "Correção confirmada", supersedes="RAW/2026/11/notes/novo.md")
                self.assertTrue(corr["retained"])
                self.assertIn(corr["document_id"], memory._load_supersedes(b.inst).values())
                retain_body = srv.requests[-1][1]
                self.assertEqual(retain_body["items"][0]["metadata"]["supersedes"], "RAW/2026/11/notes/novo.md")
            finally:
                srv.close()

    def test_cli_memory_supersede(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td), mem_toml='engine = "none"\n')
            env = {**os.environ, "BRAIN_HOME": td}
            r = subprocess.run(
                [sys.executable, str(ROOT / "brain"), "memory", "supersede", "doc-novo", "doc-velho", "--reason", "ajuste", "--json"],
                capture_output=True, text=True, cwd=ROOT, env=env, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["old"], "doc-velho")
            self.assertEqual(out["new"], "doc-novo")
            self.assertTrue((Path(td) / ".memory-supersedes.json").exists())


class AnchorProvenanceAndFormatTests(unittest.TestCase):
    def test_ungrounded_item_is_pista_and_ranked_below_grounded(self):
        today = date.today()
        d2 = (today - timedelta(days=2)).isoformat()
        items = [
            {"id": "unanchored", "text": "Pista solta sem documento", "scores": {"semantic": 0.99}},
            {
                "id": "anchored",
                "text": "Fato ancorado na reunião",
                "document_id": "RAW/2026/11/meetings/ata.md",
                "occurred_start": d2,
                "scores": {"semantic": 0.50},
            },
        ]
        ranked = recall_rank.rerank(items, today=today)
        self.assertEqual([r["id"] for r in ranked], ["anchored", "unanchored"])
        self.assertFalse(ranked[1]["grounded"])
        self.assertEqual(ranked[1]["prov"], "sem-fonte")
        self.assertEqual(recall_rank.format_line(ranked[1]), "[pista · sem âncora] Pista solta sem documento")

    def test_extract_anchor_from_nested_metadata_chunk_and_stamp(self):
        today = date.today()
        stamp = (today - timedelta(days=4)).isoformat()
        meta_doc = recall_rank.extract_anchor_and_meta({
            "text": "x",
            "metadata": {"document_id": f"RAW/2026/11/documents/contrato-{stamp}.md"},
        })
        self.assertTrue(meta_doc["grounded"])
        self.assertEqual(meta_doc["fact_date"], stamp)
        self.assertEqual(meta_doc["prov"], "doc")

        chunk_doc = recall_rank.extract_anchor_and_meta({
            "text": "y",
            "chunk": {"document_id": "RAW/2026/11/slack/canal.md"},
        })
        self.assertTrue(chunk_doc["grounded"])
        self.assertEqual(chunk_doc["prov"], "observado")

    def test_hook_format_line_exact_templates(self):
        d = (date.today() - timedelta(days=1)).isoformat()
        base = {
            "text": "Forno aprovado",
            "grounded": True,
            "fact_date": d,
            "prov": "observado",
            "conflict_status": None,
        }
        self.assertEqual(recall_rank.format_line(base), f"[memória · as of {d} · observado] Forno aprovado")
        self.assertEqual(
            recall_rank.format_line({**base, "conflict_status": "vale"}),
            f"[memória · as of {d} · observado · vale] Forno aprovado",
        )
        self.assertEqual(
            recall_rank.format_line({**base, "conflict_status": "supercedado"}),
            f"[memória · as of {d} · observado · supercedado] Forno aprovado",
        )
        self.assertEqual(
            recall_rank.format_line({**base, "fact_date": None, "prov": "doc"}),
            "[memória · as of sem-data · doc] Forno aprovado",
        )


class MemoryRecallIntegrationTests(unittest.TestCase):
    def test_memory_recall_preserves_original_fields_and_formats_cli(self):
        today = date.today()
        d_old = (today - timedelta(days=25)).isoformat()
        d_new = (today - timedelta(days=2)).isoformat()
        raw_results = [
            {
                "id": "r1",
                "text": "PROJ-1 local: loja da esquina",
                "document_id": "RAW/2026/10/meetings/ata-1.md",
                "occurred_start": d_old,
                "scores": {"semantic": 0.91},
                "custom_server_field": "preserve-me",
            },
            {
                "id": "r2",
                "text": "PROJ-1 local: espaço da galeria",
                "document_id": "RAW/2026/11/meetings/ata-2.md",
                "occurred_start": d_new,
                "scores": {"semantic": 0.84},
                "extra_nested": {"k": 42},
            },
            {
                "id": "r3",
                "text": "Comentário sem arquivo",
                "scores": {"semantic": 0.99},
            },
        ]
        srv = _MockRecallServer(raw_results, extra_top={"bank_id": "brain", "server_meta": "ok"})
        try:
            with tempfile.TemporaryDirectory() as td:
                b = _brain(Path(td), mem_toml=f'engine = "hindsight"\nurl = "{srv.url}"\n')
                res = memory.recall(b, "onde fica o PROJ-1?", today=today)
                self.assertEqual(res["bank_id"], "brain")
                self.assertEqual(res["server_meta"], "ok")
                self.assertEqual(len(res["results"]), 3)

                by_id = {r["id"]: r for r in res["results"]}
                self.assertEqual(by_id["r1"]["custom_server_field"], "preserve-me")
                self.assertEqual(by_id["r2"]["extra_nested"], {"k": 42})
                self.assertEqual(by_id["r2"]["conflict_status"], "vale")
                self.assertEqual(by_id["r1"]["conflict_status"], "supercedado")
                self.assertFalse(by_id["r3"]["grounded"])
                self.assertEqual([r["id"] for r in res["results"]], ["r2", "r1", "r3"])

                # CLI `brain memory recall` com --json e texto
                env = {**os.environ, "BRAIN_HOME": td}
                rj = subprocess.run(
                    [sys.executable, str(ROOT / "brain"), "memory", "recall", "local PROJ-1", "--json"],
                    capture_output=True, text=True, cwd=ROOT, env=env, timeout=30,
                )
                self.assertEqual(rj.returncode, 0, rj.stderr)
                jdata = json.loads(rj.stdout)
                self.assertEqual(jdata["results"][0]["id"], "r2")
                self.assertEqual(jdata["results"][0]["conflict_status"], "vale")

                rt = subprocess.run(
                    [sys.executable, str(ROOT / "brain"), "memory", "recall", "local PROJ-1"],
                    capture_output=True, text=True, cwd=ROOT, env=env, timeout=30,
                )
                self.assertEqual(rt.returncode, 0, rt.stderr)
                self.assertIn(f"[memória · as of {d_new} · observado · vale]", rt.stdout)
                self.assertIn(f"[memória · as of {d_old} · observado · supercedado]", rt.stdout)
                self.assertIn("[pista · sem âncora] Comentário sem arquivo", rt.stdout)
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
