"""Testes da porta de feedback (FB-#### → issue no GitHub): stdlib unittest, sem rede.

A rede nunca é tocada: create_issue é substituído nos fluxos e os erros do cliente são testados
com um urlopen falso. BRAIN_NOW congela o relógio; BRAIN_HOME aponta cada teste para um vault novo.
"""
from __future__ import annotations

import io
import contextlib
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, feedback, ids, state, util
from brainlib.core import Brain


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "RAW/inbox", "PROCESSED", "FRESH"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner", "data": {"name": "Dona", "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "email": "marina-demo@x.com"}})
    return b


class FeedbackFlowTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.brain = _brain(self.tmp)
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("BRAIN_NIGHTLY", None)
        self._old_home = os.environ.get("BRAIN_HOME")
        os.environ["BRAIN_HOME"] = str(self.tmp)

    def tearDown(self):
        os.environ.pop("BRAIN_HOME", None)
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("BRAIN_NIGHTLY", None)
        if self._old_home:
            os.environ["BRAIN_HOME"] = self._old_home
        self._td.cleanup()

    # ── add / list / show ───────────────────────────────────────────────────
    def test_add_pendente_e_list(self):
        ev = feedback.add(self.brain, "bug", "Painel demora a abrir", "Abre em 2s")
        self.assertEqual(ev["id"], "FB-0001")
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual((f.kind, f.status, f.title), ("bug", "pendente", "Painel demora a abrir"))
        self.assertIn("FB-0001 · pendente · [bug] Painel demora a abrir", feedback.line(f))

    def test_add_dupe_recusado_force_passa(self):
        feedback.add(self.brain, "sugestao", "Exportar para PDF")
        with self.assertRaises(util.BrainError) as cm:
            feedback.add(self.brain, "sugestao", "exportar  para   PDF")
        self.assertIn("FB-0001", str(cm.exception))
        ev = feedback.add(self.brain, "sugestao", "Exportar para PDF", force=True)
        self.assertEqual(ev["id"], "FB-0002")

    def test_kind_invalid_recusado(self):
        with self.assertRaises(util.BrainError):
            feedback.add(self.brain, "reclamacao", "Título")

    def test_agente_com_proveniencia_e_source_chat(self):
        # convenção do ask: source do agente pode ser o chat onde ele observou; proveniência é obrigatória
        ev = feedback.add(self.brain, "bug", "Bug visto no /dump", by="agent", prov="observado")
        self.assertEqual(ev["source"], "chat")
        with self.assertRaises(util.BrainError):
            feedback.add(self.brain, "bug", "Sem prov", by="agent", prov="")

    # ── push ────────────────────────────────────────────────────────────────
    def test_push_sem_token_fica_pendente_sem_evento_de_falha(self):
        feedback.add(self.brain, "bug", "Painel demora")
        with self.assertRaises(util.BrainError) as cm:
            feedback.push(self.brain, "FB-0001")
        self.assertIn("GITHUB_TOKEN", str(cm.exception))
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual(f.status, "pendente")           # pré-checagem: nada foi tentado na rede
        self.assertEqual(len(f.history), 1)              # só o feedback.added

    def _fake_env(self):
        # create_issue é substituído nestes testes; o token falso só deixa a pré-checagem passar
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=fake-token-teste\n", encoding="utf-8")

    def test_push_cria_issue_e_registra(self):
        feedback.add(self.brain, "sugestao", "Modo escuro no painel", "Hoje só há claro")
        self._fake_env()
        calls = []

        def fake(inst, repo, title, body, labels):
            calls.append((repo, title, body, labels))
            return {"number": 7, "url": "https://github.com/BVLCQ/second-brain-framework/issues/7"}

        orig = feedback.create_issue
        feedback.create_issue = fake
        try:
            ev = feedback.push(self.brain, "FB-0001")
        finally:
            feedback.create_issue = orig
        self.assertEqual(ev["type"], "feedback.pushed")
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual((f.status, f.number, f.url),
                         ("criado", 7, "https://github.com/BVLCQ/second-brain-framework/issues/7"))
        repo, title, body, labels = calls[0]
        self.assertEqual(repo, "BVLCQ/second-brain-framework")
        self.assertEqual(title, "[sugestão] Modo escuro no painel")
        self.assertEqual(labels, ["sugestão"])
        self.assertIn("`FB-0001`", body)
        with self.assertRaises(util.BrainError):          # issue já criada: não empurra duas vezes
            feedback.push(self.brain, "FB-0001")

    def test_push_falha_de_api_registra_failed_e_retry(self):
        feedback.add(self.brain, "bug", "Erro 500 no GitHub")
        self._fake_env()
        orig = feedback.create_issue
        try:
            feedback.create_issue = lambda *a, **k: (_ for _ in ()).throw(util.BrainError("GitHub recusou o issue (502)"))
            with self.assertRaises(util.BrainError) as cm:
                feedback.push(self.brain, "FB-0001")
            self.assertIn("de novo", str(cm.exception))
            self.assertEqual(self.brain.state.feedbacks["FB-0001"].status, "falhou")
            feedback.create_issue = lambda *a, **k: {"number": 9, "url": "https://github.com/x/issues/9"}
            feedback.push(self.brain, "FB-0001")
        finally:
            feedback.create_issue = orig
        self.assertEqual(self.brain.state.feedbacks["FB-0001"].status, "criado")

    def test_push_recusa_dado_do_dono_no_texto(self):
        feedback.add(self.brain, "bug", "Erro no modulo da Dona")
        self._fake_env()
        orig = feedback.create_issue
        boom = RuntimeError("create_issue não deveria ser chamado")
        feedback.create_issue = lambda *a, **k: (_ for _ in ()).throw(boom)
        try:
            with self.assertRaises(util.BrainError) as cm:
                feedback.push(self.brain, "FB-0001")
        finally:
            feedback.create_issue = orig
        self.assertIn("público", str(cm.exception))
        self.assertEqual(self.brain.state.feedbacks["FB-0001"].status, "pendente")

    def test_noturno_nao_publica(self):
        feedback.add(self.brain, "sugestao", "Ideia vista de madrugada")
        self._fake_env()
        os.environ["BRAIN_NIGHTLY"] = "1"
        called = []
        orig = feedback.create_issue
        feedback.create_issue = lambda *a, **k: called.append(1) or {"number": 1, "url": "u"}
        try:
            with self.assertRaises(util.BrainError) as cm:
                feedback.push(self.brain, "FB-0001")
            # e o ledger também recusa o evento direto
            with self.assertRaises(util.BrainError):
                self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "system",
                                       "data": {"number": 1, "url": "u"}})
        finally:
            feedback.create_issue = orig
            os.environ.pop("BRAIN_NIGHTLY", None)
        self.assertEqual(called, [])                       # nenhuma chamada na rede
        self.assertIn("noturno", str(cm.exception))
        self.assertEqual(self.brain.state.feedbacks["FB-0001"].status, "pendente")

    def test_pushed_manual(self):
        feedback.add(self.brain, "bug", "Issue criada na mão por gh")
        self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "system",
                               "data": {"number": 12, "url": "https://github.com/x/issues/12"}})
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual((f.status, f.number), ("criado", 12))
        with self.assertRaises(util.BrainError):           # failed em item já criado não grava
            self.brain.record_one({"type": "feedback.failed", "id": "FB-0001", "by": "system",
                                   "data": {"error": "x"}})

    def test_number_precisa_ser_inteiro_positivo(self):
        feedback.add(self.brain, "bug", "Nº estranho")
        with self.assertRaises(util.BrainError):
            self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "system",
                                   "data": {"number": "12", "url": "u"}})

    # ── render do issue + dobra do estado ──────────────────────────────────
    def test_issue_render(self):
        feedback.add(self.brain, "bug", "Dashboard quebra", "StackTrace tal")
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual(feedback.issue_title(f), "[bug] Dashboard quebra")
        body = feedback.issue_body(f)
        self.assertIn("🐞 bug", body)
        self.assertIn("## Descrição\nStackTrace tal", body)
        self.assertIn("`FB-0001`", body)

    def test_issue_nao_carrega_refs_do_vault_nem_de_evento_antigo(self):
        """O issue é público: refs de contexto (TASK/PROC/OPP) nunca saem — nem de evento antigo que
        ainda traga `context` no data (o campo não existe mais; o dado fica no ledger, não no issue)."""
        self.brain.record_one({"type": "feedback.added", "by": "owner",
                               "data": {"kind": "bug", "title": "Antigo com refs",
                                        "body": "b", "context": ["TASK-0001", "OPP-0002"]}})
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertFalse(hasattr(f, "context"))
        body = feedback.issue_body(f)
        self.assertNotIn("TASK-", body)
        self.assertNotIn("OPP-", body)
        self.assertNotIn("## Contexto", body)

    def test_estado_reconstroi_do_ledger(self):
        feedback.add(self.brain, "sugestao", "Primeira")
        feedback.add(self.brain, "bug", "Segunda")
        events = self.brain.read_events()
        st = state.build(json.loads(json.dumps(events)))
        self.assertEqual({f.status for f in st.feedbacks.values()}, {"pendente"})
        self.assertIn("FB-0001", st.collection("feedback"))

    def test_sync_registra_mudanca_e_e_idempotente(self):
        feedback.add(self.brain, "sugestao", "Modo escuro", force=True)
        self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "system",
                               "data": {"number": 3, "url": "https://github.com/x/issues/3"}})
        self._fake_env()
        orig = feedback.issue_state
        calls = []

        def fake(inst, repo, number):
            calls.append(number)
            return {"state": "closed", "reason": "completed"}

        feedback.issue_state = fake
        try:
            events, notes = feedback.sync(self.brain)
        finally:
            feedback.issue_state = orig
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"], {"state": "closed", "reason": "completed"})
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual((f.issue_state, f.issue_reason, f.synced is not None), ("closed", "completed", True))
        self.assertTrue(any("fechada" in n for n in notes))
        feedback.issue_state = fake
        try:
            events2, _ = feedback.sync(self.brain)          # mesma leitura: nada novo no ledger
        finally:
            feedback.issue_state = orig
        self.assertEqual(events2, [])

    def test_sync_sem_token_pula_sem_erro(self):
        feedback.add(self.brain, "sugestao", "Sem token")
        events, notes = feedback.sync(self.brain)
        self.assertEqual(events, [])
        self.assertTrue(any("GITHUB_TOKEN" in n for n in notes))

    def test_sync_erro_por_item_continua_os_demais(self):
        for i, t in enumerate(("Primeira", "Segunda"), 1):
            feedback.add(self.brain, "sugestao", t)
            self.brain.record_one({"type": "feedback.pushed", "id": f"FB-000{i:04d}", "by": "system",
                                   "data": {"number": i, "url": f"https://github.com/x/issues/{i}"}})
        self._fake_env()
        orig = feedback.issue_state
        feedback.issue_state = lambda inst, repo, number: (
            {"state": "open", "reason": ""} if number == 2 else (_ for _ in ()).throw(util.BrainError("GitHub respondeu 500")))
        try:
            events, notes = feedback.sync(self.brain)
        finally:
            feedback.issue_state = orig
        self.assertEqual([e["id"] for e in events], ["FB-0002"])   # só a segunda conseguiu
        self.assertTrue(any(n.startswith("⚠ FB-0001") for n in notes))

    def test_synced_exige_issue_criada(self):
        feedback.add(self.brain, "bug", "Sem issue ainda")
        with self.assertRaises(util.BrainError):
            self.brain.record_one({"type": "feedback.synced", "id": "FB-0001", "by": "system",
                                   "data": {"state": "open", "reason": ""}})
        with self.assertRaises(util.BrainError):
            self.brain.record_one({"type": "feedback.synced", "id": "FB-0001", "by": "system",
                                   "data": {"state": "travada", "reason": ""}})

    def test_sync_issue_apagada_vira_estado_gone(self):
        feedback.add(self.brain, "sugestao", "Issue removida a mão")
        self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "system",
                               "data": {"number": 9, "url": "https://github.com/x/issues/9"}})
        self._fake_env()
        orig, calls = feedback.issue_state, []

        def fake(inst, repo, number):
            calls.append(number)
            return {"state": "gone", "reason": ""}

        feedback.issue_state = fake
        try:
            events, notes = feedback.sync(self.brain)
            events2, _ = feedback.sync(self.brain)          # gone já gravado: nem consulta de novo
        finally:
            feedback.issue_state = orig
        self.assertEqual([e["data"]["state"] for e in events], ["gone"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.brain.state.feedbacks["FB-0001"].issue_state, "gone")
        self.assertTrue(any("apagada" in n for n in notes))

    def test_model_payload_tem_feedback(self):
        from brainlib import model as model_mod
        feedback.add(self.brain, "sugestao", "Modo escuro no painel")
        m = model_mod.build(self.brain)
        self.assertEqual(m["feedback"][0]["id"], "FB-0001")
        self.assertEqual((m["feedback"][0]["kind"], m["feedback"][0]["status"]), ("sugestao", "pendente"))
        self.assertEqual(m["counts"]["feedback_pending"], 1)

    def test_cli_add_no_push(self):
        from brainlib import cli as cli_mod
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli_mod.main(["feedback", "add", "Pela CLI", "--kind", "sugestao", "--no-push", "--by", "owner"])
        self.assertEqual(rc, 0)
        self.assertIn("FB-0001", out.getvalue())
        self.assertEqual(self.brain.reload() or self.brain.state.feedbacks["FB-0001"].status, "pendente")


class FeedbackClientTests(unittest.TestCase):
    """O cliente GitHub em isolado: sem rede de verdade, urlopen falso."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.inst = _inst(Path(self._td.name))

    def tearDown(self):
        self._td.cleanup()

    def test_sem_token(self):
        import brainlib.feedback as fb
        os.environ.pop("GITHUB_TOKEN", None)
        (self.inst.config_dir / ".env").write_text("", encoding="utf-8")
        with self.assertRaises(util.BrainError) as cm:
            fb.create_issue(self.inst, "o/r", "t", "b", [])
        self.assertIn("GITHUB_TOKEN", str(cm.exception))

    def test_http_error_vira_brainerror_sem_token(self):
        import brainlib.feedback as fb
        (self.inst.config_dir / ".env").write_text("GITHUB_TOKEN=segredo-fake\n", encoding="utf-8")

        class Resp(io.BytesIO):
            pass

        def fake_urlopen(req, timeout=None):
            import email.message
            raise urllib.error.HTTPError(req.full_url, 422, "Unprocessable", email.message.Message(),
                                         Resp(b'{"message": "Validation Failed"}'))

        orig = fb.urllib.request.urlopen
        fb.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(util.BrainError) as cm:
                fb.create_issue(self.inst, "o/r", "t", "b", ["bug"])
        finally:
            fb.urllib.request.urlopen = orig
        msg = str(cm.exception)
        self.assertIn("422", msg)
        self.assertNotIn("segredo-fake", msg)              # o token nunca vaza na mensagem


class FeedbackIdsTests(unittest.TestCase):
    def test_prefixo_e_normalizacao(self):
        self.assertEqual(ids.make("feedback", 3), "FB-0003")
        self.assertEqual(ids.normalize("fb-3"), "FB-0003")
        self.assertEqual(ids.entity_of("FB-0003"), "feedback")
        self.assertTrue(ids.ANY_ID.match("FB-0042"))


if __name__ == "__main__":
    unittest.main()
