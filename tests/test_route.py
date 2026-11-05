"""Roteador de perguntas + perna ledger do hook (Fases 2 e 4 do plano da memória)."""
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

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, index, route, util                    # noqa: E402
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
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "none"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Abrir o segundo ponto\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n\n"
        "### PROJ-1 — Reforma da galeria\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Mari-demo"]}})
    b.record_one({"type": "decision.made", "id": "DEC-0001", "by": "owner", "date": "2026-10-01",
                  "data": {"title": "Galeria em vez da esquina", "decided_by": ["marina-demo"]}})
    late = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                         "prov": "observado", "source": "chat",
                         "data": {"title": "Revisar orçamento", "owner": "marina-demo", "due": "2026-10-04"}})
    b._ids = {"late": late["id"]}
    index.update(b)
    return b


class ClassifyTests(unittest.TestCase):
    def test_ids_new_and_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            late = b._ids["late"]                      # ex.: TASK-0002 (o CLI numera)
            legacy = f"A-{int(late.split('-')[1])}"    # grafia antiga da MESMA entidade
            self.assertEqual(route.classify(f"como está a {late}?", db)["route"], "ledger")
            self.assertEqual(route.classify(f"o que aconteceu com {legacy}?", db)["ids"], [late])
            self.assertEqual(route.classify("e o G1?", db)["ids"], ["GOAL-1"])   # existe no PLANNING
            # inexistente não vira rota (silêncio — não inventa memória)
            self.assertIsNone(route.classify("como está a TASK-9999?", db)["route"])

    def test_bare_short_id_needs_existence(self):
        """F6: 'P1 é prioridade alta' não roteia; GOAL-1 existente (G1) roteia."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            self.assertIsNone(route.classify("P1 é prioridade alta no Jira", db)["route"])
            self.assertIsNone(route.classify("R2 do plano foi feito?", db)["route"])
            self.assertEqual(route.classify("e o G1?", db)["ids"], ["GOAL-1"])   # existe → roteia

    def test_short_id_only_prompt_reaches_hook(self):
        """'TASK-####?' tem <12 chars — a perna ledger despacha antes do corte."""
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            env = {"BRAIN_RECALL_ROUTE": "ledger", "BRAIN_HOME": td,
                   "BRAIN_NOW": "2026-10-09T10:00:00-03:00", **os.environ}
            r = subprocess.run([sys.executable, str(ROOT / "services" / "hooks" / "recall_context.py")],
                               input=json.dumps({"prompt": f"{b._ids['late']}?"}),
                               capture_output=True, text=True, cwd=ROOT, env=env, timeout=30)
            self.assertIn(f"ledger/{b._ids['late']}", r.stdout)

    def test_state_vocabulary_pt_es(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            for q in ("o que está atrasado com a Marina-demo?",
                      "quais os prazos da semana?",
                      "quem deve o quê a mim?",
                      "qué tareas están vencidas?"):
                self.assertEqual(route.classify(q, db)["route"], "ledger", q)

    def test_project_title_doubled(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            c = route.classify("como anda o projeto de reforma da galeria?", db)
            self.assertEqual(c["route"], "ledger")
            self.assertIn("PROJ-1", c["ids"])

    def test_context_question_is_not_state(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            # pergunta de CONTEXTO (a letra, o porquê) não é estado: silencia
            for q in ("por que escolhemos a galeria?",
                      "o que exatamente foi dito sobre o forno?",
                      "qual a nossa estratégia de cardápio?"):
                self.assertIsNone(route.classify(q, db)["route"], q)


class LedgerLinesTests(unittest.TestCase):
    def test_overdue_lines_with_arrow(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db = index.db_path(b.inst)
            lines = route.ledger_lines("o que está atrasado?", db)
            self.assertTrue(lines)
            self.assertLessEqual(len(lines), 3)
            self.assertIn(f"⟶ ledger/{b._ids['late']}", lines[0])
            self.assertIn("atrasada", lines[0])

    def test_entity_line(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            lines = route.ledger_lines("como está a DEC-0001?", index.db_path(b.inst))
            self.assertTrue(lines)
            self.assertIn("⟶ ledger/DEC-0001", lines[0])

    def test_silence_without_db(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            self.assertEqual(route.ledger_lines("o que está atrasado?", Path(td) / "none.sqlite"), [])

    def test_cap_three_lines(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for i in range(5):
                b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-0" + str(i + 1),
                              "prov": "observado", "source": "chat",
                              "data": {"title": f"atrasada {i}", "owner": "eu", "due": "2026-10-01"}})
            index.update(b)
            self.assertEqual(len(route.ledger_lines("o que está atrasado?", index.db_path(b.inst))), 3)


class HookTests(unittest.TestCase):
    """O hook de verdade, via subprocess (python do sistema, stdlib): ledger leg e silêncio."""

    def _run(self, prompt: str, env_extra: dict) -> str:
        env = {**os.environ, "BRAIN_NOW": "2026-10-09T10:00:00-03:00", **env_extra}
        r = subprocess.run([sys.executable, str(ROOT / "services" / "hooks" / "recall_context.py")],
                           input=json.dumps({"prompt": prompt}), capture_output=True, text=True,
                           cwd=ROOT, env=env, timeout=30)
        return r.stdout.strip()

    def test_ledger_route_outputs_lines(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            out = self._run("o que está atrasado com a Marina-demo?",
                            {"BRAIN_RECALL_ROUTE": "ledger", "BRAIN_HOME": td})
            self.assertIn(f"ledger/{b._ids['late']}", out)
            self.assertIn("additionalContext", out)

    def test_ledger_route_silences_on_context_question(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            out = self._run("por que escolhemos a galeria?",
                            {"BRAIN_RECALL_ROUTE": "ledger", "BRAIN_HOME": td})
            self.assertEqual(out, "")

    def test_ledger_route_silences_without_index(self):
        with tempfile.TemporaryDirectory() as td:
            _inst(Path(td))                                   # sem eventos, sem índice
            out = self._run("o que está atrasado?",
                            {"BRAIN_RECALL_ROUTE": "ledger", "BRAIN_HOME": td})
            self.assertEqual(out, "")

    def test_context_question_silences_when_vector_down(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            out = self._run("por que escolhemos a galeria?",
                            {"BRAIN_HOME": td, "BRAIN_HINDSIGHT_URL": "http://127.0.0.1:59999"})
            self.assertEqual(out, "")                         # contexto + vetor fora: silêncio


# ── Fase 4: sinal literal, expansão por alias e rota embed (default) ──────────
import threading                                                              # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer                    # noqa: E402


class _StubHindsight:
    """Hindsight de mentira em porta efêmera: POST recall → payload fixo."""

    def __init__(self, results):
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
                body = json.dumps({"results": outer.results}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.results = results
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.srv.shutdown()


class LiteralSignalTests(unittest.TestCase):
    def test_literal_pt_es_quotes(self):
        for q in ("o que exatamente foi dito sobre o forno?",
                  "me dá a transcrição da reunião",
                  "o que foi dito sobre o SLA?",
                  'o que ele quis dizer com "rever o contrato de aluguel"?',
                  "qué se dijo literalmente en la reunión?"):
            self.assertTrue(route.literal(q), q)
        for q in ("qual a nossa estratégia de cardápio?",
                  "por que escolhemos a galeria?"):
            self.assertFalse(route.literal(q), q)

    def test_classify_carries_literal_without_ledger_route(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            c = route.classify("o que exatamente foi dito sobre o forno?", index.db_path(b.inst))
            self.assertTrue(c["literal"])
            self.assertIsNone(c["route"])

    def test_person_aliases_for_expansion(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self.assertIn("mari-demo", route.person_aliases("marina-demo", index.db_path(b.inst)))


class EmbedRouteHookTests(unittest.TestCase):
    """Rota embed (default da Fase 4) via subprocess: degrade, corte, teto e abstenção."""

    def _run(self, prompt: str, env_extra: dict) -> str:
        env = {**os.environ, "BRAIN_NOW": "2026-10-09T10:00:00-03:00", **env_extra}
        r = subprocess.run([sys.executable, str(ROOT / "services" / "hooks" / "recall_context.py")],
                           input=json.dumps({"prompt": prompt}), capture_output=True, text=True,
                           cwd=ROOT, env=env, timeout=30)
        return r.stdout.strip()

    @staticmethod
    def _items(out: str) -> list[str]:
        return [ln for ln in json.loads(out)["hookSpecificOutput"]["additionalContext"].splitlines()
                if ln.startswith("- ")]

    def test_state_question_degrades_to_ledger_when_vector_down(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            out = self._run("o que está atrasado?",
                            {"BRAIN_HOME": td, "BRAIN_HINDSIGHT_URL": "http://127.0.0.1:59999"})
            self.assertIn(f"ledger/{b._ids['late']}", out)          # vetor fora → só ledger (4.4)
            self.assertIn("Estado do Segundo Cérebro", out)

    def test_literal_gets_chunks_with_cutoff_and_cap(self):
        stub = _StubHindsight([
            {"text": "Diego disse: congelamos o forno", "document_id": "RAW/x.md",
             "occurred_start": "2026-10-01", "scores": {"semantic": 0.9}},
            {"text": "ruido abaixo do corte", "document_id": "RAW/y.md", "scores": {"semantic": 0.5}},
            {"text": "Ana concordou na integra", "document_id": "RAW/z.md",
             "occurred_start": "2026-10-02", "scores": {"semantic": 0.8}},
        ])
        try:
            with tempfile.TemporaryDirectory() as td:
                _brain(Path(td))
                out = self._run("o que exatamente foi dito sobre o forno?",
                                {"BRAIN_HOME": td, "BRAIN_HINDSIGHT_URL": stub.url})
                items = self._items(out)
                self.assertEqual(len(items), 2)                     # literal: 1–2; o 0.5 caiu
                self.assertIn("RAW/x.md", items[0])
        finally:
            stub.close()

    def test_context_up_to_three_and_abstention_below_cutoff(self):
        def mk(i, s):
            return {"text": f"contexto {i}", "document_id": f"RAW/{i}.md", "scores": {"semantic": s}}
        stub = _StubHindsight([mk(1, 0.9), mk(2, 0.8), mk(3, 0.7), mk(4, 0.3)])
        try:
            with tempfile.TemporaryDirectory() as td:
                _brain(Path(td))
                out = self._run("qual a nossa estratégia de cardápio da padaria?",
                                {"BRAIN_HOME": td, "BRAIN_HINDSIGHT_URL": stub.url})
                self.assertEqual(len(self._items(out)), 3)          # contexto ≤3; o 0.3 caiu
        finally:
            stub.close()
        stub = _StubHindsight([mk(1, 0.3), mk(2, 0.25)])
        try:
            with tempfile.TemporaryDirectory() as td:
                _brain(Path(td))
                out = self._run("qual a nossa estratégia de cardápio da padaria?",
                                {"BRAIN_HOME": td, "BRAIN_HINDSIGHT_URL": stub.url})
                self.assertEqual(out, "")                           # abstenção: nada passa do corte
        finally:
            stub.close()

    def test_person_question_ledger_plus_semantic_cap_five(self):
        stub = _StubHindsight([
            {"text": f"contexto {i}", "document_id": f"RAW/{i}.md", "scores": {"semantic": 0.9}}
            for i in range(10)])
        try:
            with tempfile.TemporaryDirectory() as td:
                b = _brain(Path(td))
                out = self._run("o que está atrasado com a Marina-demo?",
                                {"BRAIN_HOME": td, "BRAIN_HINDSIGHT_URL": stub.url})
                items = self._items(out)
                self.assertLessEqual(len(items), 5)                 # teto da mensagem (4.3)
                self.assertTrue(any(f"ledger/{b._ids['late']}" in ln for ln in items))
                self.assertTrue(any("RAW/" in ln for ln in items))  # ledger + semântico juntos
        finally:
            stub.close()


class RouteCliTests(unittest.TestCase):
    def test_route_json_has_classify_and_lines(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            env = {**os.environ, "BRAIN_HOME": td, "BRAIN_NOW": "2026-10-09T10:00:00-03:00"}
            r = subprocess.run([sys.executable, str(ROOT / "brain"), "route", "como está a DEC-0001?", "--json"],
                               capture_output=True, text=True, cwd=ROOT, env=env, timeout=30)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["route"], "ledger")
            self.assertTrue(any("DEC-0001" in ln for ln in payload["lines"]))


if __name__ == "__main__":
    unittest.main()
