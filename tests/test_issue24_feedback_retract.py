"""Testes da retratação e retirada de feedback (Issue #24): withdraw, retract, regra B, noturno e UI.

Stdlib unittest, sem rede: `urllib.request.urlopen` é substituído por stub; `BRAIN_NOW` congela o relógio;
dados fictícios da Padaria Pão Quente (`marina-demo`, `heitor-demo`, `marina-demo@x.com`).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import cli, config, doctor, feedback, forms, model, serve, state, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.tui import rows as tui_rows, store as tui_store  # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "RAW/inbox", "PROCESSED", "FRESH"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8"
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner", "data": {"name": "Dona", "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "email": "marina-demo@x.com"}})
    b.record_one({"type": "person.added", "id": "heitor-demo", "by": "owner",
                  "data": {"name": "Heitor-demo"}})
    return b


class _FakeResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._raw


class WithdrawAndRetractTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.brain = _brain(self.tmp)
        self._old_home = os.environ.get("BRAIN_HOME")
        os.environ["BRAIN_HOME"] = str(self.tmp)
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("BRAIN_NIGHTLY", None)

    def tearDown(self):
        os.environ.pop("BRAIN_NIGHTLY", None)
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("BRAIN_HOME", None)
        if self._old_home:
            os.environ["BRAIN_HOME"] = self._old_home
        self._td.cleanup()

    def _token(self):
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=fake-token-teste\n", encoding="utf-8")

    def _publish_fb(self, title: str = "Alerta de fornada", body: str = "Texto inicial",
                    by_add: str = "owner", by_push: str = "owner", number: int = 42) -> str:
        ev = feedback.add(
            self.brain, "sugestao", title, body,
            by=by_add, prov="declarado" if by_add == "owner" else "observado", source="chat",
        )
        fid = ev["id"]
        self.brain.record_one({
            "type": "feedback.pushed", "id": fid, "by": by_push,
            "data": {"number": number, "url": f"https://github.com/BVLCQ/second-brain-framework/issues/{number}"},
        })
        return fid

    # ── withdraw ────────────────────────────────────────────────────────────
    def test_withdraw_owner_e_agent_e_bloqueios(self):
        fid_owner = feedback.add(self.brain, "bug", "Bug do dono", by="owner")["id"]
        fid_agent = feedback.add(self.brain, "sugestao", "Ideia do agente",
                                 by="agent", prov="observado", source="chat")["id"]

        # agente não pode retirar rascunho criado pelo dono
        with self.assertRaises(util.BrainError):
            feedback.withdraw(self.brain, fid_owner, "duplicado", by="agent")

        # motivo vazio é recusado
        with self.assertRaises(util.BrainError):
            feedback.withdraw(self.brain, fid_owner, "   ", by="owner")

        # dono retira rascunho do dono
        ev1 = feedback.withdraw(self.brain, fid_owner, "duplicado de outro registro", by="owner")
        self.assertEqual(ev1["type"], "feedback.withdrawn")
        f1 = self.brain.state.feedbacks[fid_owner]
        self.assertEqual((f1.status, f1.reason), ("retirado", "duplicado de outro registro"))

        # agente retira rascunho criado pelo agente (inclusive no noturno)
        os.environ["BRAIN_NIGHTLY"] = "1"
        ev2 = feedback.withdraw(self.brain, fid_agent, "não se sustenta na fonte", by="agent")
        self.assertEqual(ev2["type"], "feedback.withdrawn")
        self.assertEqual(self.brain.state.feedbacks[fid_agent].status, "retirado")
        os.environ.pop("BRAIN_NIGHTLY", None)

        # push e revise recusam item retirado sem tentar token/rede
        with self.assertRaises(util.BrainError):
            feedback.push(self.brain, fid_owner, approval="ok")
        with self.assertRaises(util.BrainError):
            feedback.revise(self.brain, fid_owner, title="Novo título")

        # list omite retirado por padrão; list --all mostra com motivo
        with contextlib.redirect_stdout(io.StringIO()) as out_def:
            self.assertEqual(cli.main(["feedback", "list"]), 0)
        self.assertNotIn(fid_owner, out_def.getvalue())
        self.assertNotIn(fid_agent, out_def.getvalue())

        with contextlib.redirect_stdout(io.StringIO()) as out_all:
            self.assertEqual(cli.main(["feedback", "list", "--all"]), 0)
        self.assertIn(fid_owner, out_all.getvalue())
        self.assertIn("duplicado de outro registro", out_all.getvalue())

    # ── retract --withdraw (dono & agente / Regra B) ────────────────────────
    def test_retract_withdraw_owner_e_agent_regra_b(self):
        self._token()
        fid_agent = self._publish_fb("Fornada demora", by_add="agent", by_push="owner", number=101)
        fid_owner = self._publish_fb("Trocar cor do botão", by_add="owner", by_push="owner", number=102)

        calls: list[tuple[str, str, dict]] = []

        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8")) if req.data else {}
            calls.append((req.get_method(), req.full_url, body))
            if req.full_url.endswith("/comments"):
                return _FakeResponse({"html_url": "https://github.com/BVLCQ/second-brain-framework/issues/101#issuecomment-1"})
            return _FakeResponse({"number": 101, "html_url": "https://github.com/BVLCQ/second-brain-framework/issues/101",
                                  "state": "closed", "state_reason": "not_planned"})

        # Regra B: agente sem --evidence falha ANTES da rede
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(util.BrainError):
                feedback.retract(self.brain, fid_agent, mode="withdraw", reason="já existia", by="agent")
            # agente não pode retratar item criado/publicado pelo dono
            with self.assertRaises(util.BrainError):
                feedback.retract(self.brain, fid_owner, mode="withdraw", reason="duplicado",
                                 evidence="PROCESSED/2026/10/nota.md", by="agent")
            # --withdraw não aceita --body
            with self.assertRaises(util.BrainError):
                feedback.retract(self.brain, fid_owner, mode="withdraw", reason="duplicado",
                                 body="corpo novo", by="owner")
        self.assertEqual(calls, [])

        # agente retrata item criado por agente com evidência
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ev = feedback.retract(
                self.brain, fid_agent, mode="withdraw",
                reason="Padaria Pão Quente já resolveu o fluxo",
                evidence="PROCESSED/2026/10/reuniao.md",
                by="agent",
            )
        self.assertEqual(ev["type"], "feedback.retracted")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "POST")
        self.assertIn("/issues/101/comments", calls[0][1])
        self.assertIn("Padaria Pão Quente", calls[0][2]["body"])
        self.assertEqual(calls[1][0], "PATCH")
        self.assertIn("/issues/101", calls[1][1])
        self.assertEqual(calls[1][2], {"state": "closed", "state_reason": "not_planned"})

        f = self.brain.state.feedbacks[fid_agent]
        self.assertEqual(f.status, "retratado")
        self.assertEqual(f.retract_mode, "withdraw")
        self.assertEqual(f.reason, "Padaria Pão Quente já resolveu o fluxo")
        self.assertEqual(f.comment_url, "https://github.com/BVLCQ/second-brain-framework/issues/101#issuecomment-1")
        self.assertEqual(f.evidence, "PROCESSED/2026/10/reuniao.md")

        # não retrata duas vezes e não publica de novo
        with self.assertRaises(util.BrainError):
            feedback.retract(self.brain, fid_agent, mode="withdraw", reason="de novo", by="owner")
        with self.assertRaises(util.BrainError):
            feedback.push(self.brain, fid_agent, approval="ok")

        # dono pode retratar item do dono (ou do agente) sem precisar de --evidence
        calls.clear()
        with contextlib.redirect_stdout(io.StringIO()), mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            rc = cli.main(["feedback", "retract", fid_owner, "--withdraw", "--reason", "descartado pelo dono", "--by", "owner"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.brain.reload() or self.brain.state.feedbacks[fid_owner].status, "retratado")

    # ── retract --correct ───────────────────────────────────────────────────
    def test_retract_correct_exige_dono_e_aprovacao_literal(self):
        self._token()
        fid = self._publish_fb("Ajustar prazo na fila", body="Texto antigo", by_add="agent", number=77)
        calls: list[tuple[str, str, dict]] = []

        def fake_urlopen(req, timeout=0):
            body = json.loads(req.data.decode("utf-8")) if req.data else {}
            calls.append((req.get_method(), req.full_url, body))
            if req.full_url.endswith("/comments"):
                return _FakeResponse({"html_url": "https://github.com/BVLCQ/second-brain-framework/issues/77#issuecomment-9"})
            return _FakeResponse({"number": 77, "html_url": "https://github.com/BVLCQ/second-brain-framework/issues/77",
                                  "state": "open"})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            # agente não pode usar --correct
            with self.assertRaises(util.BrainError):
                feedback.retract(self.brain, fid, mode="correct", reason="corrigir exemplo",
                                 body="Texto novo", approval="ok", by="agent")
            # sem aprovação literal não passa
            with self.assertRaises(util.BrainError):
                feedback.retract(self.brain, fid, mode="correct", reason="corrigir exemplo",
                                 body="Texto novo", approval="   ", by="owner")
            # sem corpo novo não passa
            with self.assertRaises(util.BrainError):
                feedback.retract(self.brain, fid, mode="correct", reason="corrigir exemplo",
                                 body="", approval="ok", by="owner")
        self.assertEqual(calls, [])

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ev = feedback.retract(
                self.brain, fid, mode="correct",
                reason="esclarece passo da Padaria Pão Quente",
                body="A marina-demo confere o forno antes de fechar.",
                approval="ok", by="owner",
            )
        self.assertEqual(ev["type"], "feedback.retracted")
        self.assertEqual(calls[0][0], "PATCH")
        self.assertIn("A marina-demo confere o forno antes de fechar.", calls[0][2]["body"])
        self.assertNotIn(fid, calls[0][2]["body"])
        self.assertEqual(calls[1][0], "POST")
        self.assertIn("esclarece passo da Padaria Pão Quente", calls[1][2]["body"])

        f = self.brain.state.feedbacks[fid]
        self.assertEqual((f.status, f.retract_mode, f.body), ("retratado", "correct", "A marina-demo confere o forno antes de fechar."))
        self.assertEqual(f.comment_url, "https://github.com/BVLCQ/second-brain-framework/issues/77#issuecomment-9")

    # ── travas públicas (reason + body) ─────────────────────────────────────
    def test_travas_publicas_em_reason_e_body(self):
        self._token()
        fid = self._publish_fb("Trava pública", by_add="owner", number=55)
        bad_snippets = [
            "ver TASK-0001 antes",
            "duplicado de FB-0001",
            "contato marina-demo@x.com",
            "veja https://docs.google.com/document/d/abc123",
            f"log em {Path.home()}/brain/vault",
        ]
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("não deve chamar a rede")):
            for bad in bad_snippets:
                with self.subTest(reason=bad):
                    with self.assertRaises(util.BrainError):
                        feedback.retract(self.brain, fid, mode="withdraw", reason=bad, by="owner")
                with self.subTest(body=bad):
                    with self.assertRaises(util.BrainError):
                        feedback.retract(self.brain, fid, mode="correct", reason="motivo limpo",
                                         body=bad, approval="ok", by="owner")

    # ── erro de rede grava feedback.failed e mantém status criado ───────────
    def test_erro_http_grava_failed_e_preserva_criado(self):
        self._token()
        fid = self._publish_fb("Erro HTTP", by_add="owner", number=66)

        def fail_http(req, timeout=0):
            import email.message
            raise urllib.error.HTTPError(
                req.full_url, 502, "Bad Gateway", email.message.Message(), io.BytesIO(b'{"message": "Bad Gateway"}')
            )

        with mock.patch("urllib.request.urlopen", side_effect=fail_http):
            with self.assertRaises(util.BrainError) as cm:
                feedback.retract(self.brain, fid, mode="withdraw", reason="fechar", by="owner")
        self.assertIn("502", str(cm.exception))
        f = self.brain.state.feedbacks[fid]
        self.assertEqual(f.status, "criado")
        self.assertIn("502", f.error)
        self.assertEqual(f.history[-1]["type"], "feedback.failed")

    # ── noturno (BRAIN_NIGHTLY=1) + doctor + sync ───────────────────────────
    def test_noturno_cria_ask_e_doctor_avisa_e_sync_preserva_retratado(self):
        fid = self._publish_fb("Item noturno", by_add="agent", by_push="owner", number=88)
        os.environ["BRAIN_NIGHTLY"] = "1"
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("zero chamadas no noturno")):
            res = feedback.retract(
                self.brain, fid, mode="withdraw",
                reason="Padaria Pão Quente mudou de rota",
                evidence="PROCESSED/2026/10/nota.md",
                by="agent",
            )
            # ledger direto continua bloqueado no noturno
            with self.assertRaises(util.BrainError):
                self.brain.record_one({
                    "type": "feedback.retracted", "id": fid, "by": "agent", "prov": "observado", "source": "chat",
                    "data": {"mode": "withdraw", "reason": "x", "number": 88, "url": "https://github.com/o/r/issues/88"},
                })
        os.environ.pop("BRAIN_NIGHTLY", None)

        self.assertEqual(res["type"], "question.asked")
        q = self.brain.state.questions[res["id"]]
        self.assertEqual(q.kind, "permissao")
        self.assertIn(fid, q.context)
        self.assertEqual(self.brain.state.feedbacks[fid].status, "criado")

        # doctor avisa da retratação pendente
        fb_checks = [c for c in doctor.checks(self.brain) if c["title"] == "feedback"]
        self.assertTrue(any("retratação descoberta e ainda não aplicada" in c["detail"] for c in fb_checks), fb_checks)

        # agora de dia, retrata e sincroniza fechamento no GitHub
        self._token()

        def fake_urlopen(req, timeout=0):
            if req.get_method() == "GET":
                return _FakeResponse({"state": "closed", "state_reason": "not_planned"})
            if req.full_url.endswith("/comments"):
                return _FakeResponse({"html_url": "https://github.com/BVLCQ/second-brain-framework/issues/88#issuecomment-2"})
            return _FakeResponse({"number": 88, "html_url": "https://github.com/BVLCQ/second-brain-framework/issues/88",
                                  "state": "closed", "state_reason": "not_planned"})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            feedback.retract(self.brain, fid, mode="withdraw", reason="Padaria Pão Quente mudou de rota",
                             evidence="PROCESSED/2026/10/nota.md", by="agent")
            events, _ = feedback.sync(self.brain)

        self.assertEqual(len(events), 1)
        f = self.brain.state.feedbacks[fid]
        self.assertEqual(f.status, "retratado")
        self.assertEqual((f.issue_state, f.issue_reason), ("closed", "not_planned"))

        # doctor para de avisar depois que virou retratado
        fb_checks_after = [c for c in doctor.checks(self.brain) if c["title"] == "feedback"]
        self.assertFalse(any("retratação descoberta e ainda não aplicada" in c["detail"] for c in fb_checks_after))

    # ── superfícies: forms, serve, model, TUI store/rows ────────────────────
    def test_forms_serve_model_e_tui_refletem_withdraw_e_retract(self):
        self.assertTrue(serve._allowed_argv(["feedback", "withdraw", "FB-0001", "--reason", "x"]))
        self.assertTrue(serve._allowed_argv(["feedback", "retract", "FB-0001", "--withdraw", "--reason", "x"]))

        # assimetria dos formulários: withdraw esconde body/approval; correct exige os dois
        fm_ret = forms.FORMS["feedback.retract"]
        ctx = {"id": "FB-0001", "title": "Teste", "item": {"body": "Antigo"}}
        self.assertEqual(
            forms.build("feedback.retract", {"mode": "withdraw", "reason": "duplicado"}, ctx, {}),
            [["feedback", "retract", "FB-0001", "--withdraw", "--reason", "duplicado", "--by", "owner"]],
        )
        self.assertIn("novo corpo", forms.missing("feedback.retract", {"mode": "correct", "reason": "ok", "body": "", "quote": "ok"}, ctx, {}))
        self.assertIn("sua aprovação", forms.missing("feedback.retract", {"mode": "correct", "reason": "ok", "body": "Novo", "quote": ""}, ctx, {}))
        self.assertEqual(
            forms.build("feedback.retract", {"mode": "correct", "reason": "ajuste", "body": "Novo", "quote": "ok"}, ctx, {}),
            [["feedback", "retract", "FB-0001", "--correct", "--reason", "ajuste", "--body", "Novo", "--approval", "ok", "--by", "owner"]],
        )
        self.assertEqual(fm_ret.fields[3].arg, "--approval")

        # model & TUI store/rows
        fid_w = feedback.add(self.brain, "bug", "Rascunho a retirar")["id"]
        feedback.withdraw(self.brain, fid_w, "não era bug", by="owner")
        fid_r = self._publish_fb("Issue a retratar", by_add="owner", number=99)
        self._token()
        with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=0: _FakeResponse(
            {"html_url": "https://github.com/o/r/issues/99#issuecomment-5", "number": 99, "state": "closed"}
        )):
            feedback.retract(self.brain, fid_r, mode="withdraw", reason="já corrigido", by="owner")
        fid_p = feedback.add(self.brain, "sugestao", "Ainda pendente")["id"]

        m = model.build(self.brain)
        self.assertEqual(m["counts"]["feedback_pending"], 1)
        by_id = {x["id"]: x for x in m["feedback"]}
        self.assertEqual(by_id[fid_w]["status"], "retirado")
        self.assertEqual(by_id[fid_w]["reason"], "não era bug")
        self.assertEqual(by_id[fid_r]["status"], "retratado")
        self.assertEqual(by_id[fid_r]["retract_mode"], "withdraw")
        self.assertEqual(by_id[fid_r]["comment_url"], "https://github.com/o/r/issues/99#issuecomment-5")

        st = tui_store.Store(self.brain.inst)
        default_ids = [it.id for it in st._items(0, 6, 1, show_all=False)]
        all_ids = [it.id for it in st._items(0, 6, 1, show_all=True)]
        self.assertEqual(default_ids, [fid_p])
        self.assertEqual(set(all_ids), {fid_p, fid_w, fid_r})
        fb_item = next(it for it in st._items(0, 6, 1, show_all=True) if it.id == fid_r)
        detail = tui_rows.detail(st, fb_item).plain
        self.assertIn("já corrigido", detail)
        self.assertIn("issuecomment-5", detail)

        # painel HTML: badge exclui retirado/retratado e V.feedback oculta por padrão
        core_js = (ROOT / "brainlib" / "assets" / "src" / "core.js").read_text(encoding="utf-8")
        extra_js = (ROOT / "brainlib" / "assets" / "src" / "extra.js").read_text(encoding="utf-8")
        self.assertIn('f.status !== "retirado" && f.status !== "retratado"', core_js)
        self.assertIn("data-fbwithdraw", core_js)
        self.assertIn("data-fbretract", core_js)
        self.assertIn("feedbackWithdrawForm", extra_js)
        self.assertIn("feedbackRetractForm", extra_js)


if __name__ == "__main__":
    unittest.main()
