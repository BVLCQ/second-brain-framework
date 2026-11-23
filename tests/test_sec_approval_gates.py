"""Testes de segurança dos gates de aprovação literal, feedback, ask answer, modo full e set_env (#102, #104, #108, #109, #110, #144)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import cli, config, feedback, focus, gates, memory, outbox, schema, setup, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from test_brain import _brain  # noqa: E402


def _run_cli(root: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "BRAIN_HOME": str(root)}
    env.pop("BRAIN_NIGHTLY", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(ROOT / "brain"), *args],
        capture_output=True, text=True, env=env,
    )


class ApprovalGatesTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.brain = _brain(self.root)
        self._old_home = os.environ.get("BRAIN_HOME")
        os.environ["BRAIN_HOME"] = str(self.root)
        os.environ.pop("BRAIN_NIGHTLY", None)
        os.environ.pop("GITHUB_TOKEN", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.pop("BRAIN_NIGHTLY", None)
        os.environ.pop("GITHUB_TOKEN", None)
        if self._old_home is not None:
            os.environ["BRAIN_HOME"] = self._old_home
        else:
            os.environ.pop("BRAIN_HOME", None)

    def test_verify_approval_words_surfaces_and_echo_limit(self):
        for w in ("ok", "OK", "  ok ", "aprovo", "Aprovo"):
            self.assertEqual(gates.verify_approval(w), (w.strip().lower(), "literal"))
        for s in ("tui", "TUI", "painel", "Painel"):
            self.assertEqual(gates.verify_approval(s), (s.strip().lower(), "surface"))
        with self.assertRaises(util.BrainError) as cm:
            gates.verify_approval("tui", allow_surface=False)
        self.assertEqual(cm.exception.code, 4)

        for bad in ("", "   ", "x", "sim", "pode fazer", "enviar 1"):
            with self.assertRaises(util.BrainError) as cm:
                gates.verify_approval(bad, what="teste")
            self.assertEqual(cm.exception.code, 4)

        long_secret = "segredo-" + ("z" * 50)
        with self.assertRaises(util.BrainError) as cm:
            gates.verify_approval(long_secret, what="teste")
        self.assertEqual(cm.exception.code, 4)
        self.assertNotIn(long_secret, str(cm.exception))
        self.assertIn("recebido outra coisa", str(cm.exception))

        self.assertEqual(gates.verify_approval("enviar 1", pattern=gates.OUTBOX_RE), ("enviar 1", "literal"))
        self.assertEqual(gates.verify_approval("2A", pattern=gates.OUTBOX_RE), ("2a", "literal"))

    def test_cli_gates_accept_only_ok_or_aprovo_or_surface(self):
        # Seed entities for every gate
        self.brain.record_one({"type": "area.added", "id": "operacoes", "by": "owner", "data": {"name": "Operações"}})
        self.brain.record_one({"type": "opportunity.added", "by": "owner", "data": {"title": "Opp A", "area": "operacoes"}})
        self.brain.record_one({"type": "opportunity.added", "by": "owner", "data": {"title": "Opp B", "area": "operacoes"}})
        p1 = self.brain.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "chat",
                                    "data": {"kind": "outro", "summary": "Proposta 1"}})["id"]
        p2 = self.brain.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "chat",
                                    "data": {"kind": "outro", "summary": "Proposta 2"}})["id"]
        p3 = self.brain.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "chat",
                                    "data": {"kind": "outro", "summary": "Proposta 3"}})["id"]
        p_rej = self.brain.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "chat",
                                       "data": {"kind": "outro", "summary": "Proposta rej"}})["id"]
        m1 = outbox.draft(self.brain, "marina-demo", "Oi Marina", None, None)["id"]
        m2 = outbox.draft(self.brain, "marina-demo", "Oi de novo", None, None)["id"]
        m3 = outbox.draft(self.brain, "marina-demo", "Oi 3", None, None)["id"]
        self.brain.record_one({"type": "action.opened", "by": "owner",
                               "data": {"title": "Focar", "owner": "eu", "due": util.today().isoformat(), "effort_min": 60}})
        body = focus.build_plan(self.brain, [])
        f1 = self.brain.record_one({"type": "focus.planned", "by": "system", "source": "x",
                                    "data": {"plan_file": "FRESH/focus.md", **body}})["id"]
        rep = self.root / "vault" / "reports" / "share" / "status.html"
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text("<h1>ok</h1>", encoding="utf-8")
        sha = util.sha(rep.read_bytes())
        config.set_keys(self.brain.inst, "publish", {"destinations": ["slack:#seu-canal"]})
        self.brain.inst = config.load(self.root)
        s1 = self.brain.record_one({"type": "share.requested", "by": "agent", "prov": "sistema", "source": "chat",
                                    "data": {"report": "reports/share/status.html", "destination": "slack:#seu-canal",
                                             "content_sha": sha}})["id"]
        s2 = self.brain.record_one({"type": "share.requested", "by": "agent", "prov": "sistema", "source": "chat",
                                    "data": {"report": "reports/share/status.html", "destination": "slack:#seu-canal",
                                             "content_sha": sha}})["id"]
        fb1 = feedback.add(self.brain, "sugestao", "Gate no push", "Corpo")["id"]
        fb2 = feedback.add(self.brain, "sugestao", "Gate no retract", "Corpo")["id"]
        self.brain.record_one({"type": "feedback.pushed", "id": fb2, "by": "owner",
                               "data": {"number": 55, "url": "https://github.com/o/r/issues/55"}})

        # Bad strings must fail with exit code 4 across all CLI gates
        bad_cmds = [
            ["plan", "log", "--diff", "d", "--reason", "r", "--approval", "sim"],
            ["plan", "log", "--diff", "d", "--reason", "r", "--approval", "enviar 1"],
            ["plan", "add-goal", "Novo goal", "--approval", "x"],
            ["plan", "add-project", "GOAL-1", "Novo proj", "--approval", "pode fazer"],
            ["plan", "edit", "GOAL-1", "--title", "X", "--approval", "sim"],
            ["opportunity", "promote", "OPP-0001", "--goal", "GOAL-1", "--approval", "sim"],
            ["proposal", "accept", p1, "--quote", "x"],
            ["outbox", "approve", m1, "--quote", "sim"],
            ["focus", "approve", f1, "--quote", "pode"],
            ["publish", "approve", s1, "--quote", "sim"],
            ["review", "accept", p1, "--quote", "sim"],
            ["feedback", "push", fb1, "--approval", "bogus"],
            ["feedback", "retract", fb2, "--correct", "--reason", "r", "--body", "b", "--approval", "sim", "--by", "owner"],
        ]
        for argv in bad_cmds:
            with self.subTest(bad=argv):
                r = _run_cli(self.root, *argv)
                self.assertEqual(r.returncode, 4, f"{argv} -> rc={r.returncode} stderr={r.stderr}")

        # proposal reject keeps non-empty check ("não" passes, blank fails)
        self.assertEqual(_run_cli(self.root, "proposal", "reject", p_rej, "--quote", "  ").returncode, 4)
        self.assertEqual(_run_cli(self.root, "proposal", "reject", p_rej, "--quote", "não").returncode, 0)

        # Valid literal words pass
        ok_cmds = [
            ["plan", "log", "--diff", "d", "--reason", "r", "--approval", "OK"],
            ["plan", "add-goal", "Goal ok", "--approval", "aprovo"],
            ["plan", "add-project", "GOAL-1", "Proj ok", "--approval", "ok"],
            ["plan", "edit", "GOAL-1", "--title", "Goal ok editado", "--approval", "aprovo"],
            ["opportunity", "promote", "OPP-0001", "--goal", "GOAL-1", "--approval", "ok"],
            ["opportunity", "promote", "OPP-0002", "--project", "PROJ-1", "--approval", "aprovo"],
            ["proposal", "accept", p1, "--quote", "OK"],
            ["review", "accept", p2, p3, "--quote", "aprovo"],
            ["outbox", "approve", m1, "--quote", "ok"],
            ["outbox", "approve", m2, "--quote", "enviar 1"],
            ["outbox", "approve", m3, "--quote", "3a"],
            ["focus", "approve", f1, "--quote", "ok"],
            ["publish", "approve", s1, "--quote", "ok"],
            ["publish", "approve", s2, "--quote", "aprovo"],
        ]
        for argv in ok_cmds:
            with self.subTest(ok=argv):
                r = _run_cli(self.root, *argv)
                self.assertEqual(r.returncode, 0, f"{argv} -> rc={r.returncode} stderr={r.stderr}")
        f2 = self.brain.record_one({"type": "focus.planned", "by": "system", "source": "x",
                                    "data": {"plan_file": "FRESH/focus.md", **body}})["id"]
        r = _run_cli(self.root, "focus", "approve", f2, "--quote", "aprovo")
        self.assertEqual(r.returncode, 0, f"focus approve aprovo -> rc={r.returncode} stderr={r.stderr}")

    def test_feedback_add_agent_never_auto_pushes_and_push_requires_owner_approval(self):
        self.assertNotIn("feedback.pushed", schema.OWNER_ONLY)
        self.assertEqual(schema.NEVER_AGENT["feedback.pushed"], {"owner", "system"})
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=" + "ghp_" + "demo_token\n", encoding="utf-8")

        # O ledger recusa feedback.pushed do agente; `system` segue válido como histórico de instâncias
        # anteriores ao gate (nada é reescrito) e o dono é quem grava a partir de agora
        fb = feedback.add(self.brain, "sugestao", "Manual")
        with self.assertRaises(util.BrainError):
            self.brain.record_one({"type": "feedback.pushed", "id": fb["id"], "by": "agent",
                                   "data": {"number": 1, "url": "https://github.com/o/r/issues/1"}})
        self.brain.record_one({"type": "feedback.pushed", "id": fb["id"], "by": "system",
                               "data": {"number": 1, "url": "https://github.com/o/r/issues/1"}})
        self.assertEqual(self.brain.validate_all(), [])

        body = "### Resumo\nResumo de teste.\n\n### Problema\nProblema.\n\n### Proposta\nSugestão de teste."
        called = []

        def fake_create(inst, repo, title, b, labels):
            called.append(title)
            return {"number": 10 + len(called), "url": f"https://github.com/o/r/issues/{10 + len(called)}"}

        with mock.patch.object(feedback, "create_issue", side_effect=fake_create):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["feedback", "add", "Ideia do agente", "--kind", "sugestao", "--body", body,
                               "--by", "agent", "--prov", "observado", "--source", "chat"])
            self.assertEqual(rc, 0)
            self.assertIn("brain feedback push FB-0002 --approval ok", out.getvalue())
            self.assertEqual(called, [])
            self.brain.reload()
            self.assertEqual(self.brain.state.feedbacks["FB-0002"].status, "pendente")

            # Owner add without --approval stays pendente without calling create_issue
            out2 = io.StringIO()
            with contextlib.redirect_stdout(out2):
                rc2 = cli.main(["feedback", "add", "Ideia do dono", "--kind", "sugestao", "--by", "owner"])
            self.assertEqual(rc2, 0)
            self.assertEqual(called, [])
            self.brain.reload()
            self.assertEqual(self.brain.state.feedbacks["FB-0003"].status, "pendente")

            # Push without approval or as agent fails with code 4
            with self.assertRaises(util.BrainError) as cm:
                feedback.push(self.brain, "FB-0002")
            self.assertEqual(cm.exception.code, 4)
            with self.assertRaises(util.BrainError) as cm:
                feedback.push(self.brain, "FB-0002", approval="ok", by="agent")
            self.assertEqual(cm.exception.code, 4)
            self.assertEqual(called, [])

            # Push with literal approval records by="owner" and quote="ok" (without surface)
            ev_lit = feedback.push(self.brain, "FB-0002", approval="OK")
            self.assertEqual(ev_lit["by"], "owner")
            self.assertEqual(ev_lit["data"]["quote"], "ok")
            self.assertNotIn("surface", ev_lit["data"])

            # Push with surface approval records quote="tui" and surface="tui"
            ev_surf = feedback.push(self.brain, "FB-0003", approval="tui")
            self.assertEqual(ev_surf["by"], "owner")
            self.assertEqual(ev_surf["data"]["quote"], "tui")
            self.assertEqual(ev_surf["data"]["surface"], "tui")

        # Backward compatibility: legacy events without quote/approval still validate
        legacy = [
            {"seq": 1, "ts": "2026-10-09T10:00:00-03:00", "type": "feedback.added", "id": "FB-0001",
             "date": "2026-10-09", "by": "owner", "prov": "declarado", "source": "chat",
             "data": {"kind": "bug", "title": "Antigo"}},
            {"seq": 2, "ts": "2026-10-09T10:01:00-03:00", "type": "feedback.pushed", "id": "FB-0001",
             "date": "2026-10-09", "by": "owner", "prov": "declarado", "source": "chat",
             "data": {"number": 1, "url": "https://github.com/o/r/issues/1"}},
            {"seq": 3, "ts": "2026-10-09T10:02:00-03:00", "type": "feedback.retracted", "id": "FB-0001",
             "date": "2026-10-09", "by": "owner", "prov": "declarado", "source": "chat",
             "data": {"mode": "correct", "reason": "r", "number": 1, "url": "https://github.com/o/r/issues/1", "body": "b"}},
        ]
        self.assertEqual(self.brain.validate_events(legacy, self.brain.plan), [])

    def test_feedback_retract_correct_persists_verified_approval(self):
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=" + "ghp_" + "demo_token\n", encoding="utf-8")
        fb = feedback.add(self.brain, "sugestao", "Titulo")
        self.brain.record_one({"type": "feedback.pushed", "id": fb["id"], "by": "owner",
                               "data": {"number": 7, "url": "https://github.com/o/r/issues/7"}})

        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("sem rede")):
            for bad in ("", "x", "sim"):
                with self.assertRaises(util.BrainError) as cm:
                    feedback.retract(self.brain, fb["id"], mode="correct", reason="ajuste",
                                     body="Novo corpo", approval=bad, by="owner")
                self.assertEqual(cm.exception.code, 4)

        class _Resp:
            def __init__(self, payload):
                self._raw = json.dumps(payload).encode("utf-8")
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return self._raw

        def fake_urlopen(req, timeout=0):
            if req.full_url.endswith("/comments"):
                return _Resp({"html_url": "https://github.com/o/r/issues/7#issuecomment-1"})
            return _Resp({"number": 7, "html_url": "https://github.com/o/r/issues/7", "state": "open"})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ev = feedback.retract(self.brain, fb["id"], mode="correct", reason="ajuste",
                                  body="Novo corpo limpo", approval="OK", by="owner")
        self.assertEqual(ev["data"]["approval"], "ok")

    def test_ask_answer_requires_explicit_by_owner(self):
        parser = cli.build_parser()
        ns = parser.parse_args(["ask", "answer", "ASK-0001", "sim"])
        self.assertIsNone(ns.by)

        self.brain.record_one({"type": "question.asked", "by": "agent", "prov": "observado", "source": "chat",
                               "data": {"text": "Qual?", "options": ["sim", "nao"]}})
        r_no_by = _run_cli(self.root, "ask", "answer", "ASK-0001", "sim")
        self.assertEqual(r_no_by.returncode, 4, r_no_by.stderr)

        r_agent = _run_cli(self.root, "ask", "answer", "ASK-0001", "sim", "--by", "agent")
        self.assertEqual(r_agent.returncode, 4, r_agent.stderr)

        r_owner = _run_cli(self.root, "ask", "answer", "ASK-0001", "sim", "--by", "owner")
        self.assertEqual(r_owner.returncode, 0, r_owner.stderr)
        self.brain.reload()
        self.assertEqual(self.brain.state.questions["ASK-0001"].status, "respondida")

    def test_memory_setup_full_requires_typed_ok_and_refuses_nightly(self):
        (self.brain.inst.config_dir / ".env").write_text(
            "HINDSIGHT_API_LLM_API_KEY=" + "sk-" + "ant-oat01-demo\n", encoding="utf-8"
        )
        for bad in ("", "tui", "painel", "sim"):
            with self.assertRaises(util.BrainError) as cm:
                memory._apply_mode(self.brain, "full", approval=bad)
            self.assertEqual(cm.exception.code, 4)

        os.environ["BRAIN_NIGHTLY"] = "1"
        with self.assertRaises(util.BrainError) as cm:
            memory._apply_mode(self.brain, "full", approval="ok")
        self.assertEqual(cm.exception.code, 4)
        os.environ.pop("BRAIN_NIGHTLY", None)

        memory._apply_mode(self.brain, "full", approval="aprovo")
        self.assertEqual(memory.mode(self.brain.inst.cfg["memory"]), "full")

        # validate_memory_setup also rejects surface tokens and nightly, accepts ok/aprovo
        for bad in ("", "tui", "painel", "sim"):
            with self.assertRaises(util.BrainError) as cm:
                setup.validate_memory_setup({"mode": "full", "approval": bad, "key": "k"})
            self.assertEqual(cm.exception.code, 4)
        self.assertTrue(setup.validate_memory_setup({"mode": "full", "approval": "aprovo", "key": "k"})["consent"])

        os.environ["BRAIN_NIGHTLY"] = "1"
        with self.assertRaises(util.BrainError) as cm:
            setup.validate_memory_setup({"mode": "full", "approval": "ok", "key": "k"})
        self.assertEqual(cm.exception.code, 4)
        os.environ.pop("BRAIN_NIGHTLY", None)

        r = _run_cli(self.root, "memory", "setup", "--mode", "full", "--approval", "tui")
        self.assertEqual(r.returncode, 4, r.stderr)


class SetEnvGuardTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.inst = _brain(self.root).inst

    def test_rejects_newlines_nul_and_bad_keys_without_echoing_value(self):
        secret_val = "sk-" + "ant-oat01-demo\nEXTRA=1"
        for val in ("abc\ndef", "abc\rdef", "abc\x00def", secret_val):
            with self.subTest(val=repr(val)):
                with self.assertRaises(util.BrainError) as cm:
                    setup.set_env(self.inst, {"GITHUB_TOKEN": val})
                self.assertEqual(cm.exception.code, 4)
                msg = str(cm.exception)
                self.assertIn("GITHUB_TOKEN", msg)
                self.assertNotIn("EXTRA=1", msg)
                self.assertNotIn("abcdef", msg)
                self.assertNotIn("ant-oat01-demo", msg)

        for bad_key in ("", "1ABC", "BAD-KEY", "A B", "KEY\nINJ", "KEY\rINJ", "KEY\x00INJ"):
            with self.subTest(key=repr(bad_key)):
                with self.assertRaises(util.BrainError) as cm:
                    setup.set_env(self.inst, {bad_key: "valor-secreto-nao-ecoar"})
                self.assertEqual(cm.exception.code, 4)
                self.assertNotIn("valor-secreto-nao-ecoar", str(cm.exception))

        changed = setup.set_env(self.inst, {"_VALID_KEY_1": "ok-val"})
        self.assertEqual(changed, ["_VALID_KEY_1"])
        self.assertEqual(self.inst.env_file.read_text(encoding="utf-8"), "_VALID_KEY_1=ok-val\n")


class FeedbackSurfacesTest(unittest.TestCase):
    """O gate de `feedback` exige a resposta do dono: toda superfície que publica tem de mandá-la (#104)."""

    PUSH_SITES = ('runCommand("brain feedback push " + id0 + " --approval painel")',      # botão "publicar"
                  'runCommand("brain feedback push " + fb.id + " --approval painel")')    # atalho `p`
    BARE_PUSH = re.compile(r'feedback push ["\'] \+ [\w.]+\)')

    @staticmethod
    def _argv(surface: str, pub: str) -> list[str]:
        from brainlib import forms
        return forms.build("feedback.new", {"title": "T", "kind": "sugestao", "pub": pub}, m={}, surface=surface)[0]

    def test_new_feedback_form_carries_the_surface_approval_only_when_publishing_now(self):
        for surface in ("painel", "tui"):
            with self.subTest(surface=surface):
                argv = self._argv(surface, "agora")
                self.assertIn("--approval", argv)
                self.assertEqual(argv[argv.index("--approval") + 1], surface)
                self.assertNotIn("--no-push", argv)
                argv = self._argv(surface, "depois")
                self.assertNotIn("--approval", argv)
                self.assertIn("--no-push", argv)
        argv = self._argv("", "agora")        # sem superfície ninguém preenche: o gate recusa sozinho
        self.assertNotIn("--approval", argv)

    def test_panel_publishes_feedback_with_the_surface_approval(self):
        for name in ("dashboard.html", "portfolio.html"):
            with self.subTest(asset=name):
                html = (ROOT / "brainlib" / "assets" / name).read_text(encoding="utf-8")
                for site in self.PUSH_SITES:
                    self.assertIn(site, html)
                self.assertIsNone(self.BARE_PUSH.search(html))


if __name__ == "__main__":
    unittest.main()
