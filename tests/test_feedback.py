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
        self.assertIn("FB-0001 · pendente · [Bug] Painel demora a abrir", feedback.line(f))

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
            feedback.push(self.brain, "FB-0001", approval="ok")
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
            ev = feedback.push(self.brain, "FB-0001", approval="ok")
        finally:
            feedback.create_issue = orig
        self.assertEqual(ev["type"], "feedback.pushed")
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual((f.status, f.number, f.url),
                         ("criado", 7, "https://github.com/BVLCQ/second-brain-framework/issues/7"))
        repo, title, body, labels = calls[0]
        self.assertEqual(repo, "BVLCQ/second-brain-framework")
        self.assertEqual(title, "[Sugestão] Modo escuro no painel")
        self.assertEqual(labels, ["sugestão"])
        self.assertNotIn("FB-0001", body)                   # id local nunca sobe
        with self.assertRaises(util.BrainError):          # issue já criada: não empurra duas vezes
            feedback.push(self.brain, "FB-0001", approval="ok")

    def test_push_avisa_quando_a_issue_sai_sem_o_label(self):
        feedback.add(self.brain, "bug", "Sem permissão de label")
        self._fake_env()
        orig = feedback.create_issue
        try:
            feedback.create_issue = lambda *a, **k: {"number": 5, "url": "https://github.com/o/r/issues/5", "labels": []}
            ev = feedback.push(self.brain, "FB-0001", approval="ok")
        finally:
            feedback.create_issue = orig
        self.assertIn("label 'bug'", ev["label_note"])
        self.assertEqual(self.brain.state.feedbacks["FB-0001"].status, "criado")

    def test_push_falha_de_api_registra_failed_e_retry(self):
        feedback.add(self.brain, "bug", "Erro 500 no GitHub")
        self._fake_env()
        orig = feedback.create_issue
        try:
            feedback.create_issue = lambda *a, **k: (_ for _ in ()).throw(util.BrainError("GitHub recusou o issue (502)"))
            with self.assertRaises(util.BrainError) as cm:
                feedback.push(self.brain, "FB-0001", approval="ok")
            self.assertIn("de novo", str(cm.exception))
            self.assertEqual(self.brain.state.feedbacks["FB-0001"].status, "falhou")
            feedback.create_issue = lambda *a, **k: {"number": 9, "url": "https://github.com/x/issues/9"}
            feedback.push(self.brain, "FB-0001", approval="ok")
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
                feedback.push(self.brain, "FB-0001", approval="ok")
        finally:
            feedback.create_issue = orig
        self.assertIn("pública", str(cm.exception))
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
                feedback.push(self.brain, "FB-0001", approval="ok")
            # e o ledger também recusa o evento direto
            with self.assertRaises(util.BrainError):
                self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "owner",
                                       "data": {"number": 1, "url": "u"}})
        finally:
            feedback.create_issue = orig
            os.environ.pop("BRAIN_NIGHTLY", None)
        self.assertEqual(called, [])                       # nenhuma chamada na rede
        self.assertIn("noturno", str(cm.exception))
        self.assertEqual(self.brain.state.feedbacks["FB-0001"].status, "pendente")

    def test_pushed_manual(self):
        feedback.add(self.brain, "bug", "Issue criada na mão por gh")
        self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "owner",
                               "data": {"number": 12, "url": "https://github.com/x/issues/12"}})
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual((f.status, f.number), ("criado", 12))
        with self.assertRaises(util.BrainError):           # failed em item já criado não grava
            self.brain.record_one({"type": "feedback.failed", "id": "FB-0001", "by": "system",
                                   "data": {"error": "x"}})

    def test_number_precisa_ser_inteiro_positivo(self):
        feedback.add(self.brain, "bug", "Nº estranho")
        with self.assertRaises(util.BrainError):
            self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "owner",
                                   "data": {"number": "12", "url": "u"}})

    # ── render do issue + dobra do estado ──────────────────────────────────
    def test_issue_render(self):
        feedback.add(self.brain, "bug", "Dashboard quebra", "StackTrace tal")
        f = self.brain.state.feedbacks["FB-0001"]
        self.assertEqual(feedback.issue_title(f), "[Bug] Dashboard quebra")
        body = feedback.issue_body(f)
        self.assertIn("🐞 bug", body)
        self.assertIn("### Resumo\nStackTrace tal", body)
        self.assertNotIn("FB-0001", body)                   # id local nunca sobe

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
        self.assertNotIn("Contexto", body)

    def test_estado_reconstroi_do_ledger(self):
        feedback.add(self.brain, "sugestao", "Primeira")
        feedback.add(self.brain, "bug", "Segunda")
        events = self.brain.read_events()
        st = state.build(json.loads(json.dumps(events)))
        self.assertEqual({f.status for f in st.feedbacks.values()}, {"pendente"})
        self.assertIn("FB-0001", st.collection("feedback"))

    def test_sync_registra_mudanca_e_e_idempotente(self):
        feedback.add(self.brain, "sugestao", "Modo escuro", force=True)
        self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "owner",
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
            self.brain.record_one({"type": "feedback.pushed", "id": f"FB-000{i:04d}", "by": "owner",
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
        self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "owner",
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
        self.assertEqual(m["feedback"][0]["issue_title"], feedback.issue_title(self.brain.state.feedbacks["FB-0001"]))
        self.assertEqual(m["feedback"][0]["issue_body"], feedback.issue_body(self.brain.state.feedbacks["FB-0001"]))
        self.assertEqual(m["feedback"][0]["text_sha"], feedback.public_sha(self.brain.state.feedbacks["FB-0001"]))

    def test_push_sem_aprovacao_mostra_o_texto_exato(self):
        feedback.add(self.brain, "sugestao", "Lembrete de fornada", "A marina-demo esquece o timer")
        with self.assertRaises(util.BrainError) as cm:
            feedback.push(self.brain, "FB-0001", approval="")
        self.assertIn("[Sugestão] Lembrete de fornada", str(cm.exception))
        self.assertIn("sem aprovação", str(cm.exception))
        self.assertEqual(self.brain.state.feedbacks["FB-0001"].status, "pendente")

    def test_revise_depois_do_ok_recusa_o_push(self):
        feedback.add(self.brain, "sugestao", "Lembrete de fornada", "A marina-demo esquece o timer")
        feedback.approve(self.brain, "FB-0001", "ok")
        feedback.revise(self.brain, "FB-0001", title="Lembrete da fornada da tarde")
        with self.assertRaises(util.BrainError) as cm:
            feedback.push(self.brain, "FB-0001", approval="ok")
        self.assertIn("texto mudou", str(cm.exception))
        feedback.approve(self.brain, "FB-0001", "ok")
        self.assertEqual(feedback._bound_sha(self.brain.state.feedbacks["FB-0001"]),
                         feedback.public_sha(self.brain.state.feedbacks["FB-0001"]))

    def test_cli_add_no_push(self):
        from brainlib import cli as cli_mod
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli_mod.main(["feedback", "add", "Pela CLI", "--kind", "sugestao", "--no-push", "--by", "owner"])
        self.assertEqual(rc, 0)
        self.assertIn("FB-0001", out.getvalue())
        self.assertEqual(self.brain.reload() or self.brain.state.feedbacks["FB-0001"].status, "pendente")


class FrameworkProposalTests(unittest.TestCase):
    """Proposta `framework` aceita pelo dono → issue no GitHub (porta 7). create_issue é falso; sem rede."""

    TITLE = "Checagem em lote das fontes do Drive"
    BODY = ("### Resumo\nChecar vários docs do Drive numa só consulta.\n\n"
            "### Contexto\nA Padaria Pão Quente vigia 36 fichas de receita e o /update consulta uma por vez.\n\n"
            "### Proposta\nUm comando lista os docs vigiados e compara as revisões de uma vez.\n\n"
            "### Critérios de aceite\n- só os docs alterados são lidos\n- doc removido aparece como falha")

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.brain = _brain(self.tmp)
        for k in ("GITHUB_TOKEN", "BRAIN_NIGHTLY"):
            os.environ.pop(k, None)
        self._orig = feedback.create_issue
        self.calls: list = []
        feedback.create_issue = lambda inst, repo, title, body, labels: (
            self.calls.append((repo, title, body, labels)) or {"number": 12, "url": "https://github.com/o/r/issues/12"})

    def tearDown(self):
        feedback.create_issue = self._orig
        os.environ.pop("BRAIN_NIGHTLY", None)
        self._td.cleanup()

    def _token(self):
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=fake-token-teste\n", encoding="utf-8")

    def _propose(self, kind="framework", **extra):
        data = {"kind": kind, "summary": "resumo interno com TASK-0001"}
        if kind == "framework":
            data.update(issue_title=self.TITLE, issue_body=self.BODY)
        data.update(extra)
        return self.brain.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado",
                                      "source": "chat", "data": data})["id"]

    def _accept(self, pid):
        self.brain.record_one({"type": "proposal.accepted", "id": pid, "by": "owner", "data": {"quote": "ok"}})
        return feedback.from_proposal(self.brain, pid)

    def test_aceitar_cria_fb_e_issue_com_o_texto_publico(self):
        self._token()
        pid = self._propose()
        fid, warn = self._accept(pid)
        self.assertEqual((fid, warn), ("FB-0001", ""))
        f = self.brain.state.feedbacks[fid]
        self.assertEqual((f.status, f.number, f.kind, f.by, f.proposal), ("criado", 12, "sugestao", "owner", pid))
        self.assertEqual(self.brain.state.proposals[pid].feedback, fid)
        repo, title, body, labels = self.calls[0]
        self.assertEqual((title, labels), ("[Proposta] " + self.TITLE, ["sugestão"]))
        self.assertIn(self.BODY, body)
        self.assertNotIn("TASK-0001", body)                # o resumo interno nunca sobe
        self.assertNotIn(pid, body)                        # nem o PROP-####

    def test_sem_token_aceite_vale_e_fb_fica_pendente(self):
        pid = self._propose()
        fid, warn = self._accept(pid)
        self.assertEqual(self.brain.state.proposals[pid].status, "aceita")
        self.assertEqual(self.brain.state.feedbacks[fid].status, "pendente")
        self.assertIn("pendente", warn)
        self.assertEqual(self.calls, [])

    def test_so_framework_gera_issue(self):
        self._token()
        pid = self._propose("outro")
        self.assertEqual(self._accept(pid), (None, ""))
        self.assertEqual(self.brain.state.feedbacks, {})
        self.assertEqual(self.calls, [])

    def test_rejeitada_nao_gera_issue(self):
        self._token()
        pid = self._propose()
        self.brain.record_one({"type": "proposal.rejected", "id": pid, "by": "owner", "data": {"quote": "não"}})
        self.assertEqual(self.brain.state.feedbacks, {})
        self.assertEqual(self.calls, [])

    def test_nao_cria_segundo_fb_para_a_mesma_proposta(self):
        self._token()
        pid = self._propose()
        fid, _ = self._accept(pid)
        self.assertEqual(feedback.from_proposal(self.brain, pid), (fid, ""))
        self.assertEqual(len(self.brain.state.feedbacks), 1)
        self.assertEqual(len(self.calls), 1)

    def test_framework_exige_texto_publico(self):
        for data in ({"kind": "framework", "summary": "x"},
                     {"kind": "framework", "summary": "x", "issue_title": "t"},
                     {"kind": "framework", "summary": "x", "issue_title": " ", "issue_body": "b"}):
            with self.assertRaises(util.BrainError):
                self.brain.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado",
                                       "source": "chat", "data": data})

    def test_ids_do_vault_e_dado_do_dono_sao_recusados(self):
        with self.assertRaises(util.BrainError) as cm:
            feedback.public_text_guard(self.brain.inst, "Melhoria (ASK-0025)", "corpo")
        self.assertIn("ASK-0025", str(cm.exception))
        with self.assertRaises(util.BrainError):
            feedback.public_text_guard(self.brain.inst, "ok", "ver OPP-0003 e PROJ-3.2")
        with self.assertRaises(util.BrainError):           # nome do dono (regras do upstream)
            feedback.public_text_guard(self.brain.inst, "Pedido da Dona", "corpo")
        feedback.public_text_guard(self.brain.inst, self.TITLE, self.BODY)   # texto limpo passa

    def test_texto_vazado_no_ledger_nao_derruba_o_aceite(self):
        self._token()
        pid = self._propose(issue_body="veja OPP-0001")    # gravado por fora do CLI
        fid, warn = self._accept(pid)
        self.assertIsNone(fid)
        self.assertIn("OPP-0001", warn)
        self.assertEqual(self.brain.state.proposals[pid].status, "aceita")
        self.assertEqual(self.calls, [])

    def test_noturno_nao_aceita_nem_publica(self):
        self._token()
        pid = self._propose()
        os.environ["BRAIN_NIGHTLY"] = "1"
        with self.assertRaises(util.BrainError):
            self.brain.record_one({"type": "proposal.accepted", "id": pid, "by": "owner", "data": {"quote": "ok"}})
        self.assertEqual(self.brain.state.proposals[pid].status, "aberta")
        self.assertEqual(self.calls, [])

    def test_cli_add_e_accept(self):
        from brainlib import cli as cli_mod
        self._token()
        os.environ["BRAIN_HOME"] = str(self.tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = cli_mod.main(["proposal", "add", "--kind", "framework", "--summary", "s",
                                   "--by", "agent", "--prov", "observado", "--source", "chat"])
            self.assertNotEqual(rc, 0)                     # sem texto público
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc = cli_mod.main(["proposal", "add", "--kind", "framework", "--summary", "s",
                                   "--issue-title", self.TITLE, "--issue-body", self.BODY,
                                   "--by", "agent", "--prov", "observado", "--source", "chat"])
            self.assertEqual(rc, 0)
            self.assertIn("vira issue", out.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc = cli_mod.main(["proposal", "accept", "PROP-0001", "--quote", "ok"])
            self.assertEqual(rc, 0)
            self.assertIn("FB-0001 (criado)", out.getvalue())
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = cli_mod.main(["proposal", "add", "--kind", "outro", "--summary", "s", "--issue-title", "x",
                                   "--by", "agent", "--prov", "observado", "--source", "chat"])
            self.assertNotEqual(rc, 0)                     # texto público só vale em framework
        finally:
            os.environ.pop("BRAIN_HOME", None)


class FeedbackSetupTests(unittest.TestCase):
    """Token no setup e no doctor (sem rede: urlopen falso)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.brain = _brain(self.tmp)
        os.environ.pop("GITHUB_TOKEN", None)

    def tearDown(self):
        self._td.cleanup()

    def _fake(self, payload=None, code=None):
        from brainlib import setup as setup_mod

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return json.dumps(payload or {}).encode()

        def urlopen(req, timeout=0):
            if code:
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
            return R()
        orig = setup_mod.urllib.request.urlopen
        setup_mod.urllib.request.urlopen = urlopen
        self.addCleanup(lambda: setattr(setup_mod.urllib.request, "urlopen", orig))
        return setup_mod

    def test_repo_visivel_e_com_issues(self):
        m = self._fake({"has_issues": True, "archived": False})
        self.assertEqual(m.github_repo_access("t", "o/r")[0], True)

    def test_repo_404_diz_como_corrigir_sem_vazar_token(self):
        m = self._fake(code=404)
        ok, why = m.github_repo_access("segredo-fake", "o/r")
        self.assertFalse(ok)
        self.assertIn("404", why)
        self.assertNotIn("segredo-fake", why)

    def test_repo_arquivado_ou_sem_issues_e_recusado(self):
        self.assertFalse(self._fake({"archived": True}).github_repo_access("t", "o/r")[0])
        self.assertFalse(self._fake({"has_issues": False}).github_repo_access("t", "o/r")[0])

    def test_doctor_avisa_fila_sem_token_e_com_token(self):
        from brainlib import doctor
        feedback.add(self.brain, "sugestao", "Algo a publicar")
        rows = [c for c in doctor.checks(self.brain) if c["title"] == "feedback"]
        self.assertEqual((len(rows), rows[0]["level"]), (1, "warn"))
        self.assertIn("GITHUB_TOKEN", rows[0]["detail"])
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=fake-token-teste\n", encoding="utf-8")
        rows = [c for c in doctor.checks(self.brain) if c["title"] == "feedback"]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("GITHUB_TOKEN", rows[0]["detail"])


class FeedbackClientTests(unittest.TestCase):
    """O cliente GitHub em isolado: sem rede de verdade, urlopen falso."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.inst = _inst(Path(self._td.name))
        # Em isolado de verdade: um GITHUB_TOKEN no ambiente (o de um CI, o de um shell do mantenedor)
        # vence o config/.env em `config.load_env` e trocaria o token falso pelo real.
        self._tok = os.environ.pop("GITHUB_TOKEN", None)

    def tearDown(self):
        if self._tok is not None:
            os.environ["GITHUB_TOKEN"] = self._tok
        self._td.cleanup()

    def test_token_do_ambiente_vence_o_env_file(self):
        # É por isso que o setUp tira o GITHUB_TOKEN do ar: no ambiente, ele vence o config/.env.
        os.environ["GITHUB_TOKEN"] = "token-do-ambiente"
        try:
            (self.inst.config_dir / ".env").write_text("GITHUB_TOKEN=segredo-fake\n", encoding="utf-8")
            self.assertEqual(config.load_env(self.inst)["GITHUB_TOKEN"], "token-do-ambiente")
        finally:
            os.environ.pop("GITHUB_TOKEN", None)

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

    def test_add_comment_e_update_issue_injetavel(self):
        import brainlib.feedback as fb
        (self.inst.config_dir / ".env").write_text("GITHUB_TOKEN=segredo-fake\n", encoding="utf-8")
        seen = []

        class _R:
            def __init__(self, obj):
                self._raw = json.dumps(obj).encode("utf-8")
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return self._raw

        def fake_urlopen(req, timeout=None):
            seen.append((req.get_method(), req.full_url, req.get_header("Authorization"),
                         json.loads(req.data.decode("utf-8"))))
            if req.get_method() == "POST":
                return _R({"html_url": "https://github.com/o/r/issues/7#issuecomment-1"})
            return _R({"number": 7, "html_url": "https://github.com/o/r/issues/7",
                       "state": "closed", "state_reason": "not_planned"})

        cm = fb.add_comment(self.inst, "o/r", 7, "Retratado", urlopen=fake_urlopen)
        up = fb.update_issue(self.inst, "o/r", 7, state="closed", state_reason="not_planned", urlopen=fake_urlopen)
        self.assertEqual(cm["html_url"], "https://github.com/o/r/issues/7#issuecomment-1")
        self.assertEqual((up["state"], up["state_reason"]), ("closed", "not_planned"))
        self.assertEqual(seen[0][0], "POST")
        self.assertEqual(seen[0][2], "Bearer segredo-fake")
        self.assertEqual(seen[1][0], "PATCH")
        self.assertEqual(seen[1][3], {"state": "closed", "state_reason": "not_planned"})


class FeedbackIdsTests(unittest.TestCase):
    def test_prefixo_e_normalizacao(self):
        self.assertEqual(ids.make("feedback", 3), "FB-0003")
        self.assertEqual(ids.normalize("fb-3"), "FB-0003")
        self.assertEqual(ids.entity_of("FB-0003"), "feedback")
        self.assertTrue(ids.ANY_ID.match("FB-0042"))


if __name__ == "__main__":
    unittest.main()
