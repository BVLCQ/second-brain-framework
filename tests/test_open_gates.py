"""Testes dos gates sob BRAIN_AGENT / BRAIN_NIGHTLY e preservação de tui/painel (#102, #109, #110)."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from brainlib import cli, config, gates, review, util  # noqa: E402
from test_brain import _brain  # noqa: E402


@contextlib.contextmanager
def _env_vars(**overrides: str | None):
    """Define/remove variáveis em `os.environ` e restaura o estado anterior sem vazar."""
    saved = {k: os.environ.get(k) for k in ("BRAIN_AGENT", "BRAIN_NIGHTLY", *overrides)}
    try:
        os.environ.pop("BRAIN_AGENT", None)
        os.environ.pop("BRAIN_NIGHTLY", None)
        for k, v in overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _run_cli(root: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "BRAIN_HOME": str(root)}
    env.pop("BRAIN_AGENT", None)
    env.pop("BRAIN_NIGHTLY", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(ROOT / "brain"), *args],
        capture_output=True, text=True, env=env,
    )


class OpenGatesUnitTests(unittest.TestCase):
    def test_without_agent_or_nightly_literal_and_surface_pass(self):
        with _env_vars():
            self.assertEqual(gates.verify_approval("ok"), ("ok", "literal"))
            self.assertEqual(gates.verify_approval("aprovo"), ("aprovo", "literal"))
            self.assertEqual(gates.verify_approval("tui"), ("tui", "surface"))
            self.assertEqual(gates.verify_approval("painel"), ("painel", "surface"))
            self.assertEqual(gates.verify_approval("enviar 1", pattern=gates.OUTBOX_RE), ("enviar 1", "literal"))
            with self.assertRaises(util.BrainError) as cm:
                gates.verify_approval("painel", allow_surface=False)
            self.assertEqual(cm.exception.code, 4)

    def test_brain_agent_refuses_literal_and_surface_with_code_4(self):
        for flag in ("1", "true", "yes", "on"):
            with self.subTest(BRAIN_AGENT=flag), _env_vars(BRAIN_AGENT=flag):
                for val, pat in (("ok", None), ("aprovo", None), ("tui", None), ("painel", None), ("enviar 1", gates.OUTBOX_RE)):
                    with self.assertRaises(util.BrainError) as cm:
                        gates.verify_approval(val, what="teste", pattern=pat)
                    self.assertEqual(cm.exception.code, 4)
                    msg = str(cm.exception).lower()
                    self.assertIn("agente", msg)
                    self.assertIn("não pode aprovar no lugar do dono", msg)

    def test_brain_nightly_refuses_literal_and_surface_with_code_4(self):
        for flag in ("1", "true", "yes", "on"):
            with self.subTest(BRAIN_NIGHTLY=flag), _env_vars(BRAIN_NIGHTLY=flag):
                for val in ("ok", "aprovo", "tui", "painel"):
                    with self.assertRaises(util.BrainError) as cm:
                        gates.verify_approval(val, what="teste")
                    self.assertEqual(cm.exception.code, 4)
                    msg = str(cm.exception).lower()
                    self.assertIn("noturno", msg)
                    self.assertIn("não pode aprovar no lugar do dono", msg)

    def test_both_agent_and_nightly_refuse_with_code_4(self):
        with _env_vars(BRAIN_AGENT="1", BRAIN_NIGHTLY="1"):
            with self.assertRaises(util.BrainError) as cm:
                gates.verify_approval("ok", what="teste")
            self.assertEqual(cm.exception.code, 4)
            msg = str(cm.exception).lower()
            self.assertIn("agente", msg)
            self.assertIn("noturno", msg)
            self.assertIn("não pode aprovar no lugar do dono", msg)


class OpenGatesCliTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.brain = _brain(self.root)

    def test_ask_answer_uses_shared_policy_and_refuses_under_agent_and_nightly(self):
        self.brain.record_one({
            "type": "question.asked", "by": "agent", "prov": "observado", "source": "chat",
            "data": {"text": "Confirmar?", "options": ["sim", "nao"]},
        })

        for env_key, expected_word in (("BRAIN_AGENT", "agente"), ("BRAIN_NIGHTLY", "noturno")):
            with self.subTest(env=env_key):
                r = _run_cli(
                    self.root, "ask", "answer", "ASK-0001", "sim", "--by", "owner",
                    env_extra={env_key: "1"},
                )
                self.assertEqual(r.returncode, 4, r.stderr)
                err = r.stderr.lower()
                self.assertIn(expected_word, err)
                self.assertIn("não pode aprovar no lugar do dono", err)
                self.brain.reload()
                self.assertEqual(self.brain.state.questions["ASK-0001"].status, "aberta")

        # Sem env: ask answer --by owner funciona normalmente e chama o helper central
        with _env_vars(BRAIN_HOME=str(self.root)):
            with mock.patch.object(gates, "require_owner_present", wraps=gates.require_owner_present) as spy:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = cli.main(["ask", "answer", "ASK-0001", "sim", "--by", "owner"])
                self.assertEqual(rc, 0)
                spy.assert_called_once_with(what="ask answer")
        self.brain.reload()
        self.assertEqual(self.brain.state.questions["ASK-0001"].status, "respondida")

        # question.applied não é aprovação do dono: o agente pode aplicar mesmo sob BRAIN_AGENT=1
        r_app = _run_cli(
            self.root, "ask", "applied", "ASK-0001", "--how", "registrado",
            "--prov", "observado", "--source", "chat",
            env_extra={"BRAIN_AGENT": "1"},
        )
        self.assertEqual(r_app.returncode, 0, r_app.stderr)
        self.brain.reload()
        self.assertEqual(self.brain.state.questions["ASK-0001"].status, "aplicada")

    def test_review_and_share_inherit_refusal_under_brain_agent(self):
        pid = self.brain.record_one({
            "type": "proposal.opened", "by": "agent", "prov": "observado", "source": "chat",
            "data": {"kind": "outro", "summary": "Proposta 1"},
        })["id"]
        rep = self.root / "vault" / "reports" / "share" / "status.html"
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text("<h1>ok</h1>", encoding="utf-8")
        sha = util.sha(rep.read_bytes())
        config.set_keys(self.brain.inst, "publish", {"destinations": ["slack:#seu-canal"]})
        self.brain.inst = config.load(self.root)
        sid = self.brain.record_one({
            "type": "share.requested", "by": "agent", "prov": "sistema", "source": "chat",
            "data": {"report": "reports/share/status.html", "destination": "slack:#seu-canal", "content_sha": sha},
        })["id"]

        for quote in ("ok", "painel"):
            with self.subTest(gate="review", quote=quote):
                with _env_vars(BRAIN_AGENT="1"):
                    with self.assertRaises(util.BrainError) as cm:
                        review.accept_batch(self.brain, [pid], quote=quote)
                    self.assertEqual(cm.exception.code, 4)
                    self.assertIn("não pode aprovar no lugar do dono", str(cm.exception).lower())
                r_rev = _run_cli(self.root, "review", "accept", pid, "--quote", quote, env_extra={"BRAIN_AGENT": "1"})
                self.assertEqual(r_rev.returncode, 4, r_rev.stderr)
                self.assertIn("não pode aprovar no lugar do dono", r_rev.stderr.lower())

            with self.subTest(gate="publish", quote=quote):
                r_pub = _run_cli(self.root, "publish", "approve", sid, "--quote", quote, env_extra={"BRAIN_AGENT": "1"})
                self.assertEqual(r_pub.returncode, 4, r_pub.stderr)
                self.assertIn("não pode aprovar no lugar do dono", r_pub.stderr.lower())

        self.brain.reload()
        self.assertEqual(self.brain.state.proposals[pid].status, "aberta")
        self.assertEqual(self.brain.state.shares[sid].status, "solicitada")

        # Sem BRAIN_AGENT, as aprovações continuam funcionando (incluindo surface word)
        r_rev_ok = _run_cli(self.root, "review", "accept", pid, "--quote", "painel")
        self.assertEqual(r_rev_ok.returncode, 0, r_rev_ok.stderr)
        r_pub_ok = _run_cli(self.root, "publish", "approve", sid, "--quote", "ok")
        self.assertEqual(r_pub_ok.returncode, 0, r_pub_ok.stderr)
        self.brain.reload()
        self.assertEqual(self.brain.state.proposals[pid].status, "aceita")
        self.assertEqual(self.brain.state.shares[sid].status, "aprovada")


if __name__ == "__main__":
    unittest.main()
