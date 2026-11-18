"""Testes da Issue #25: executar ações do agente pelo painel HTML via `brain serve`."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, demo as demo_mod, model, runner, serve  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.tui import bridge  # noqa: E402


def _demo_inst(td: str) -> config.Instance:
    with contextlib.redirect_stdout(io.StringIO()):
        demo_mod.cli(argparse.Namespace(dir=str(Path(td) / "inst"), open=False))
    return config.load(Path(td) / "inst")


class BridgeAndModelAgentTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.inst = _demo_inst(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _cfg(self, **runner_over) -> dict:
        return {**config.DEFAULTS, "runner": {**config.DEFAULTS["runner"], **runner_over}}

    def test_bridge_agent_argv_usa_prompt_da_acao_e_respeita_none_ou_ausente(self):
        with mock.patch("shutil.which", side_effect=lambda b: "/bin/claude" if b == "claude" else None):
            argv = bridge.agent_argv(self._cfg(agent="auto"), "/update", "run-1")
            self.assertIsNotNone(argv)
            self.assertEqual(argv[0], "claude")
            self.assertTrue(any("/update" in a and "run-1" in a for a in argv))
            self.assertFalse(any("MODO NOTURNO" in a for a in argv))

            self.assertIsNone(bridge.agent_argv(self._cfg(agent="none"), "/update", "run-1"))

        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(bridge.agent_argv(self._cfg(agent="auto"), "/update", "run-1"))

        cmd_argv = bridge.agent_argv(self._cfg(command=f"{sys.executable} -c 'pass' {{prompt}}"), "/brief", "run-2")
        self.assertIsNotNone(cmd_argv)
        self.assertEqual(cmd_argv[0], sys.executable)
        self.assertTrue(any("/brief" in a and "run-2" in a for a in cmd_argv))

    def test_model_agent_ok_sem_disparar_processo(self):
        b = Brain(self.inst)
        with mock.patch.object(runner.subprocess, "run", side_effect=AssertionError("não deve rodar subprocesso")), \
             mock.patch("shutil.which", side_effect=lambda x: "/bin/claude" if x == "claude" else None):
            m = model.build(b)
            self.assertTrue(m["agent_ok"])

        with mock.patch.object(runner.subprocess, "run", side_effect=AssertionError("não deve rodar subprocesso")), \
             mock.patch("shutil.which", return_value=None):
            m = model.build(b)
            self.assertFalse(m["agent_ok"])

        config.set_keys(self.inst, "runner", {"agent": "none", "command": ""})
        b2 = Brain(config.reload(self.inst))
        with mock.patch("shutil.which", return_value="/bin/claude"):
            self.assertFalse(model.build(b2)["agent_ok"])

        config.set_keys(self.inst, "runner", {"command": f"{sys.executable} -c pass {{prompt}}"})
        b3 = Brain(config.reload(self.inst))
        self.assertTrue(model.build(b3)["agent_ok"])

        config.set_keys(self.inst, "runner", {"command": "binario-inexistente-xyz {prompt}"})
        b4 = Brain(config.reload(self.inst))
        self.assertFalse(model.build(b4)["agent_ok"])


class ServeAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls.td.name)
        cls.inst = _demo_inst(cls.td.name)
        cls.token = "tok-agent-25"
        serve._Handler.state = serve._State(cls.inst, cls.token)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        serve._Handler.state.port = cls.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.td.cleanup()

    def setUp(self):
        # limpa jobs entre testes para não vazar estado
        with serve._Handler.state.agent_lock:
            serve._Handler.state.agent_jobs.clear()
        config.set_keys(self.inst, "runner", {"agent": "auto", "command": ""})

    def _req(self, path: str, token: str | None = None, host: str = "127.0.0.1",
             origin: str | None = None, method: str = "GET", body: dict | None = None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        if token:
            r.add_header("X-Brain-Token", token)
        if origin is not None:
            r.add_header("Origin", origin)
        if body is not None:
            r.add_header("Content-Type", "application/json")
        r.add_header("Host", host)
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_guards_token_origin_host_e_nightly(self):
        code, _ = self._req("/api/agent", method="POST", body={"action": "update"})
        self.assertEqual(code, 401)
        code, _ = self._req("/api/agent/job/nope", token="errado")
        self.assertEqual(code, 401)
        code, _ = self._req("/api/agent", token=self.token, host="atacante.invalid",
                            method="POST", body={"action": "update"})
        self.assertEqual(code, 403)
        code, _ = self._req("/api/agent/job/nope", token=self.token, origin="http://atacante.invalid")
        self.assertEqual(code, 403)
        code, _ = self._req("/api/agent", token=self.token, origin="http://atacante.invalid",
                            method="POST", body={"action": "update"})
        self.assertEqual(code, 403)

        with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
            code, body = self._req("/api/agent", token=self.token, method="POST", body={"action": "update"})
            self.assertEqual(code, 403)
            self.assertFalse(body["ok"])

    def test_validacao_de_acoes_argumentos_e_runner_ausente(self):
        code, body = self._req("/api/agent", token=self.token, method="POST", body={"action": "desconhecida"})
        self.assertEqual(code, 400)
        self.assertFalse(body["ok"])

        code, body = self._req("/api/agent", token=self.token, method="POST", body={"action": "slack", "arg": ""})
        self.assertEqual(code, 400)
        self.assertIn("obrigatório", body["error"])

        code, body = self._req("/api/agent", token=self.token, method="POST", body={"action": "drive"})
        self.assertEqual(code, 400)

        code, body = self._req("/api/agent/job/inexistente", token=self.token)
        self.assertEqual(code, 404)
        self.assertFalse(body["ok"])

        config.set_keys(self.inst, "runner", {"agent": "none", "command": ""})
        code, body = self._req("/api/agent", token=self.token, method="POST", body={"action": "update"})
        self.assertEqual(code, 503)
        self.assertIn("Runner não configurado", body["error"])

    def _write_fake_runner(self, name: str, code_src: str) -> Path:
        p = self.tmp / name
        p.write_text(code_src, encoding="utf-8")
        return p

    def test_execucao_streaming_e_bloqueio_de_concorrencia_409(self):
        started = self.tmp / "started.flag"
        release = self.tmp / "release.flag"
        prompt_out = self.tmp / "prompt.txt"
        started.unlink(missing_ok=True)
        release.unlink(missing_ok=True)
        prompt_out.unlink(missing_ok=True)

        script = self._write_fake_runner(
            "fake_agent.py",
            "import pathlib, sys, time\n"
            f"pathlib.Path({str(prompt_out)!r}).write_text(sys.argv[1], encoding='utf-8')\n"
            "print('lendo fontes...', flush=True)\n"
            f"pathlib.Path({str(started)!r}).write_text('1', encoding='utf-8')\n"
            "deadline = time.time() + 5.0\n"
            f"while not pathlib.Path({str(release)!r}).exists() and time.time() < deadline:\n"
            "    time.sleep(0.02)\n"
            "print('✓ tudo processado', flush=True)\n",
        )
        config.set_keys(self.inst, "runner", {"command": f"{sys.executable} {script} {{prompt}}"})

        code, start = self._req("/api/agent", token=self.token, method="POST",
                                body={"action": "connect", "arg": "gmail-hoje"})
        self.assertEqual(code, 200)
        self.assertTrue(start["ok"])
        self.assertEqual(start["action"], "connect")
        self.assertEqual(start["status"], "running")
        jid = start["id"]

        # espera o processo falso realmente iniciar antes de disparar o segundo pedido
        deadline = time.time() + 5.0
        while not started.exists() and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(started.exists(), "runner falso não iniciou a tempo")

        code2, conflict = self._req("/api/agent", token=self.token, method="POST", body={"action": "dump"})
        self.assertEqual(code2, 409)
        self.assertFalse(conflict["ok"])
        self.assertIn("execução", conflict["error"])

        release.write_text("go", encoding="utf-8")

        job = None
        deadline = time.time() + 5.0
        while time.time() < deadline:
            jc, jr = self._req(f"/api/agent/job/{jid}", token=self.token)
            self.assertEqual(jc, 200)
            self.assertTrue(jr["ok"])
            job = jr["job"]
            if job["status"] != "running":
                break
            time.sleep(0.03)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["rc"], 0)
        self.assertIn("lendo fontes...", job["lines"])
        self.assertIn("✓ tudo processado", job["lines"])
        self.assertIn("/connect gmail-hoje", prompt_out.read_text(encoding="utf-8"))

        # log em agent-runs.jsonl gravado sem vazar o prompt
        runs_log = self.inst.logs / "agent-runs.jsonl"
        self.assertTrue(runs_log.exists())
        last_row = json.loads(runs_log.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last_row["rc"], 0)
        self.assertIn("<prompt>", last_row["argv"])

    def test_runner_com_erro_marca_status_error_e_preserva_rc(self):
        script = self._write_fake_runner(
            "fail_agent.py",
            "import sys\n"
            "print('falhou no meio', flush=True)\n"
            "sys.exit(3)\n",
        )
        config.set_keys(self.inst, "runner", {"command": f"{sys.executable} {script} {{prompt}}"})

        code, start = self._req("/api/agent", token=self.token, method="POST", body={"action": "brief"})
        self.assertEqual(code, 200)
        jid = start["id"]

        job = None
        deadline = time.time() + 5.0
        while time.time() < deadline:
            _, jr = self._req(f"/api/agent/job/{jid}", token=self.token)
            job = jr["job"]
            if job["status"] != "running":
                break
            time.sleep(0.02)

        self.assertEqual(job["status"], "error")
        self.assertEqual(job["rc"], 3)
        self.assertIn("falhou no meio", job["lines"])


class PanelJsAgentAuditTests(unittest.TestCase):
    def test_js_audit_agent_ok_e_rotas_sem_comandos_falsos(self):
        core = (ROOT / "brainlib/assets/src/core.js").read_text(encoding="utf-8")
        extra = (ROOT / "brainlib/assets/src/extra.js").read_text(encoding="utf-8")
        dash = (ROOT / "brainlib/assets/dashboard.html").read_text(encoding="utf-8")

        self.assertIn("m.agent_ok = !!m.agent_ok;", core)
        self.assertIn("D0.agent_ok = !!D0.agent_ok;", extra)
        self.assertIn("/api/agent", extra)
        self.assertIn("/api/agent/job/", extra)
        self.assertIn("ponte serve desligada", extra)
        self.assertIn("runner não configurado", extra)

        # portas do agente permanecem como avisos de porta, sem executar diretamente
        self.assertIn("publish done", extra)
        self.assertIn("claude -p --resume", extra)
        self.assertIn("envio pelo MCP do Slack como o dono", extra)
        self.assertIn("brain share opportunity", extra)

        # nunca emitir comandos falsos `brain update` / `brain dump` / `brain connect` pelo painel
        for fake in ("brain update", "brain dump", "brain connect", "brain brief", "brain week"):
            self.assertIsNone(re.search(r"\b" + re.escape(fake) + r"\b", extra + core),
                              f"não deve emitir {fake!r}")
        self.assertIn("/api/agent", dash)


if __name__ == "__main__":
    unittest.main()
