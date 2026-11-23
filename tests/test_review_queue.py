"""Testes da fila de revisão derivada, bloqueio de portas, aceite em lote e CLI (#61)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import render, review, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from test_brain import _brain  # noqa: E402


def _run(td: Path, *args: str, nightly: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "BRAIN_HOME": str(td)}
    env.pop("BRAIN_NIGHTLY", None)
    if nightly:
        env["BRAIN_NIGHTLY"] = "1"
    return subprocess.run([sys.executable, str(ROOT / "brain"), *args], env=env, capture_output=True, text=True)


def _seed_action(b: Brain, title: str, *, link: str = "") -> str:
    data = {"title": title, "owner": "eu"}
    if link:
        data["link"] = link
    return b.record_one({"type": "action.opened", "by": "owner", "data": data})["id"]


def _seed_proposal(b: Brain, kind: str, summary: str, *, target: str = "", into: str = "") -> str:
    data: dict = {"kind": kind, "summary": summary}
    if target:
        data["target"] = target
    if into:
        data["into"] = into
    return b.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado",
                         "source": "RAW/2026/10/notes/nota.md", "data": data})["id"]


def _seed_outbox(b: Brain, text: str = "Oi Marina-demo, tudo bem?") -> str:
    return b.record_one({"type": "message.drafted", "by": "agent", "prov": "observado",
                         "source": "RAW/2026/10/notes/nota.md",
                         "data": {"to": "marina-demo", "text": text, "why": "acompanhamento"}})["id"]


def _seed_publish(b: Brain) -> str:
    return b.record_one({"type": "share.requested", "by": "agent", "prov": "sistema",
                         "source": "chat",
                         "data": {"report": "reports/share/semanal.html",
                                  "destination": "slack:#time",
                                  "content_sha": util.sha("semanal")}})["id"]


def _seed_ask(b: Brain) -> str:
    return b.record_one({"type": "question.asked", "by": "agent", "prov": "observado",
                         "source": "RAW/2026/10/notes/nota.md",
                         "data": {"text": "Qual prioridade usar?", "options": ["alta", "media"]}})["id"]


def _seed_focus(b: Brain) -> str:
    return b.record_one({"type": "focus.planned", "by": "agent", "prov": "sistema",
                         "source": "chat",
                         "data": {"plan_file": "FRESH/focus.md", "sha": util.sha("focus"),
                                  "blocks": [{"action": "TASK-0001", "start": "09:00", "end": "10:00"}]}})["id"]


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.b = _brain(self.root)

    def test_queue_aggregates_all_six_sources_and_filters(self):
        t1 = _seed_action(self.b, "Revisar contrato do fornecedor BigQuery", link="https://example.com/1")
        t2 = _seed_action(self.b, "Revisar acesso ao BigQuery", link="https://example.com/2")
        # Par parecido para entrar em dupes.pairs (t3 e t4 sem not_dup)
        _seed_action(self.b, "Enviar planilha mensal de custos para diretoria")
        self.b.record_one({"type": "action.opened", "by": "owner",
                           "data": {"title": "Enviar planilha mensal de custos diretoria", "owner": "eu",
                                    "not_dup": []}})
        # Como --force / not_dup vazio deixa par aberto: garante ao menos 1 par em dupes.pairs
        pid = _seed_proposal(self.b, "fechar-acao", "Concluída em reunião", target=t1)
        mid = _seed_outbox(self.b)
        sid = _seed_publish(self.b)
        qid = _seed_ask(self.b)
        fid = _seed_focus(self.b)
        # Item já resolvido não deve aparecer na fila
        p_closed = _seed_proposal(self.b, "outro", "Já resolvida", target=t2)
        self.b.record_one({"type": "proposal.rejected", "id": p_closed, "by": "owner", "data": {"quote": "não"}})

        q = review.queue(self.b)
        self.assertEqual(q["counts"]["proposal"], 1)
        self.assertEqual(q["counts"]["outbox"], 1)
        self.assertEqual(q["counts"]["publish"], 1)
        self.assertEqual(q["counts"]["ask"], 1)
        self.assertEqual(q["counts"]["focus"], 1)
        self.assertGreaterEqual(q["counts"]["dupe"], 1)
        self.assertEqual(q["total"], sum(q["counts"].values()))
        self.assertEqual(q["batch_acceptable"], 1)
        self.assertEqual(q["ports"], 3)

        by_id = {it["id"]: it for it in q["items"]}
        self.assertIn(pid, by_id)
        self.assertNotIn(p_closed, by_id)
        self.assertFalse(by_id[pid]["is_port"])
        self.assertTrue(by_id[pid]["batch_acceptable"])
        self.assertEqual(by_id[pid]["prov"], "observado")
        self.assertIn("RAW/2026/10/notes/nota.md", by_id[pid]["source"])
        self.assertTrue(by_id[pid]["diff"])

        for port_id in (mid, sid, fid):
            self.assertTrue(by_id[port_id]["is_port"])
            self.assertFalse(by_id[port_id]["batch_acceptable"])

        self.assertFalse(by_id[qid]["is_port"])
        self.assertFalse(by_id[qid]["batch_acceptable"])

        dupe_items = [it for it in q["items"] if it["kind"] == "dupe"]
        self.assertTrue(dupe_items[0]["id"].startswith("DUPE:"))
        self.assertFalse(dupe_items[0]["is_port"])
        self.assertFalse(dupe_items[0]["batch_acceptable"])

        # Filtro --kind mantém counts totais para o badge
        only_ports = review.queue(self.b, kind="outbox")
        self.assertEqual([it["id"] for it in only_ports["items"]], [mid])
        self.assertEqual(only_ports["counts"], q["counts"])
        self.assertEqual(only_ports["total"], q["total"])

        with self.assertRaises(util.BrainError) as ctx:
            review.queue(self.b, kind="desconhecido")
        self.assertEqual(ctx.exception.code, 4)

    def test_accept_batch_records_individual_events_and_applies_effects(self):
        t1 = _seed_action(self.b, "Fechar pendência de acesso")
        t2 = _seed_action(self.b, "Pendência duplicada", link="https://example.com/a")
        t3 = _seed_action(self.b, "Pendência principal", link="https://example.com/b")
        p1 = _seed_proposal(self.b, "fechar-acao", "Feita pelo time", target=t1)
        p2 = _seed_proposal(self.b, "descartar-acao", "Duplicada de " + t3, target=t2, into=t3)

        before = len(self.b.read_events())
        res = review.accept_batch(self.b, [p1, "R-1", p2], quote="aprovo")

        self.assertEqual(res["summary"], {"requested": 2, "accepted": 2, "failed": 0})
        self.assertEqual([x["id"] for x in res["accepted"]], [p1, p2])
        self.assertEqual(res["failed"], [])

        new_events = self.b.read_events()[before:]
        prop_events = [e for e in new_events if e["type"] == "proposal.accepted"]
        self.assertEqual([e["id"] for e in prop_events], [p1, p2])
        self.assertNotEqual(prop_events[0]["seq"], prop_events[1]["seq"])
        self.assertEqual(prop_events[0]["data"]["quote"], "aprovo")

        st = self.b.state
        self.assertEqual(st.proposals[p1].status, "aceita")
        self.assertEqual(st.proposals[p2].status, "aceita")
        self.assertEqual(st.actions[t1].status, "fechada")
        self.assertEqual(st.actions[t2].status, "descartada")
        self.assertEqual(st.actions[t2].duplicate_of, t3)

    def test_accept_batch_blocks_ports_and_individual_items(self):
        t1 = _seed_action(self.b, "Ação para fechar")
        p1 = _seed_proposal(self.b, "fechar-acao", "Concluída", target=t1)
        mid = _seed_outbox(self.b)
        sid = _seed_publish(self.b)
        fid = _seed_focus(self.b)
        qid = _seed_ask(self.b)

        res = review.accept_batch(self.b, [p1, mid, sid, fid, qid, "DUPE:TASK-0001:TASK-0002"], quote="ok")
        self.assertEqual([x["id"] for x in res["accepted"]], [p1])
        failed = {x["id"]: x for x in res["failed"]}
        self.assertEqual(failed[mid]["status"], "rejected_port")
        self.assertEqual(failed[sid]["status"], "rejected_port")
        self.assertEqual(failed[fid]["status"], "rejected_port")
        self.assertEqual(failed[qid]["status"], "rejected_kind")
        self.assertEqual(failed["DUPE:TASK-0001:TASK-0002"]["status"], "rejected_kind")

        st = self.b.state
        self.assertEqual(st.messages[mid].status, "rascunho")
        self.assertEqual(st.shares[sid].status, "solicitada")
        self.assertEqual(st.focus_plans[fid].status, "proposto")
        self.assertEqual(st.questions[qid].status, "aberta")

        # Prefixos legados das portas (M-1, S-1, F-1) também são barrados antes de qualquer mutação
        leg = review.accept_batch(self.b, ["M-1", "S-1", "F-1"], quote="ok")
        self.assertEqual(leg["accepted"], [])
        self.assertTrue(all(x["status"] == "rejected_port" for x in leg["failed"]))

    def test_accept_batch_is_resilient_per_item(self):
        t1 = _seed_action(self.b, "Primeira ação")
        t2 = _seed_action(self.b, "Segunda ação já fechada")
        t3 = _seed_action(self.b, "Terceira ação")
        p1 = _seed_proposal(self.b, "fechar-acao", "Feita 1", target=t1)
        p_closed_tgt = _seed_proposal(self.b, "fechar-acao", "Feita 2", target=t2)
        p3 = _seed_proposal(self.b, "fechar-acao", "Feita 3", target=t3)
        # Fecha t2 por fora (sem sweep): mesmo antes do sweep, p_closed_tgt falha sem travar o lote
        self.b.record([{"type": "action.closed", "id": t2, "by": "owner", "data": {"how": "manual"}}], sweep=False)

        res = review.accept_batch(self.b, [p_closed_tgt, p1, "PROP-9999", p3], quote="ok")
        self.assertEqual([x["id"] for x in res["accepted"]], [p1, p3])
        failed = {x["id"]: x for x in res["failed"]}
        self.assertEqual(set(failed), {"PROP-9999", p_closed_tgt})
        self.assertEqual(failed["PROP-9999"]["status"], "error")
        self.assertEqual(failed[p_closed_tgt]["status"], "error")

        st = self.b.state
        self.assertEqual(st.actions[t1].status, "fechada")
        self.assertEqual(st.actions[t3].status, "fechada")
        accepted_ids = {e["id"] for e in self.b.read_events() if e["type"] == "proposal.accepted"}
        self.assertEqual(accepted_ids, {p1, p3})

    def test_nightly_refuses_batch_accept_without_recording(self):
        t1 = _seed_action(self.b, "Ação noturna")
        p1 = _seed_proposal(self.b, "fechar-acao", "Feita", target=t1)
        before = len(self.b.read_events())

        old_nightly = os.environ.get("BRAIN_NIGHTLY")
        os.environ["BRAIN_NIGHTLY"] = "1"
        try:
            res = review.accept_batch(self.b, [p1], quote="ok")
        finally:
            if old_nightly is None:
                os.environ.pop("BRAIN_NIGHTLY", None)
            else:
                os.environ["BRAIN_NIGHTLY"] = old_nightly

        self.assertEqual(res["accepted"], [])
        self.assertEqual(len(res["failed"]), 1)
        self.assertIn("noturno", res["failed"][0]["error"])
        self.assertEqual(len(self.b.read_events()), before)
        self.assertEqual(self.b.state.proposals[p1].status, "aberta")

        r = _run(self.root, "review", "accept", p1, "--quote", "ok", "--json", nightly=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.b.read_events()), before)

    def test_cli_json_and_view_model_badge(self):
        t1 = _seed_action(self.b, "Ação via CLI 1")
        t2 = _seed_action(self.b, "Ação via CLI 2")
        p1 = _seed_proposal(self.b, "fechar-acao", "Feita", target=t1)
        p2 = _seed_proposal(self.b, "outro", "Confirmar nota", target=t2)
        mid = _seed_outbox(self.b)

        vm = render.view_model(self.b)
        q = review.queue(self.b)
        self.assertEqual(vm["review"], review.summary(self.b))
        self.assertEqual(vm["review"]["total"], q["total"])
        self.assertEqual(vm["review"]["batch_acceptable"], 2)
        self.assertEqual(vm["review"]["ports"], 1)

        r_list = _run(self.root, "review", "list", "--json")
        self.assertEqual(r_list.returncode, 0, r_list.stderr)
        payload = json.loads(r_list.stdout)
        self.assertEqual(payload["total"], q["total"])
        self.assertEqual(payload["counts"]["proposal"], 2)
        self.assertEqual(payload["counts"]["outbox"], 1)

        r_part = _run(self.root, "review", "accept", p1, mid, "--quote", "painel", "--json")
        self.assertEqual(r_part.returncode, 2)
        part = json.loads(r_part.stdout)
        self.assertEqual([x["id"] for x in part["accepted"]], [p1])
        self.assertEqual(part["failed"][0]["status"], "rejected_port")

        r_ok = _run(self.root, "review", "accept", p2, "--quote", "painel", "--json")
        self.assertEqual(r_ok.returncode, 0, r_ok.stderr)
        ok_data = json.loads(r_ok.stdout)
        self.assertEqual(ok_data["summary"], {"requested": 1, "accepted": 1, "failed": 0})

        # Quote vazio na CLI é recusado com erro de validação (4)
        r_empty = _run(self.root, "review", "accept", p2, "--quote", "   ")
        self.assertEqual(r_empty.returncode, 4)


if __name__ == "__main__":
    unittest.main()
