"""Testes do Garbage Collector de jobs e timeout do agente na ponte serve (#35)."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, demo as demo_mod, serve  # noqa: E402
from brainlib.tui import bridge  # noqa: E402


def _demo_inst(td: str) -> config.Instance:
    with contextlib.redirect_stdout(io.StringIO()):
        demo_mod.cli(argparse.Namespace(dir=str(Path(td) / "inst"), open=False))
    return config.load(Path(td) / "inst")


class ServeGCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls.td.name)
        cls.inst = _demo_inst(cls.td.name)
        cls.token = "tok-serve-gc-test"
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
        with serve._Handler.state.agent_lock:
            serve._Handler.state.agent_jobs.clear()
        config.set_keys(self.inst, "runner", {
            "agent": "auto",
            "command": f"{sys.executable} -c 'pass' {{prompt}}",
            "timeout_min": 10,
        })

    def _req(self, path: str, token: str | None = None, method: str = "GET", body: dict | None = None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        if token:
            r.add_header("X-Brain-Token", token)
        if body is not None:
            r.add_header("Content-Type", "application/json")
        r.add_header("Host", "127.0.0.1")
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_job_running_expirado_limpa_e_aceita_novo_post(self):
        old_jid = "job-expirado-123"
        with serve._Handler.state.agent_lock:
            serve._Handler.state.agent_jobs[old_jid] = {
                "id": old_jid,
                "action": "brief",
                "status": "running",
                "lines": ["linha inicial antiga"],
                "rc": None,
                "_started": time.time() - 4000,
            }

        code, body = self._req("/api/agent", token=self.token, method="POST", body={"action": "brief"})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "running")
        self.assertNotEqual(body["id"], old_jid)

        new_jid = body["id"]

        with serve._Handler.state.agent_lock:
            old_job = serve._Handler.state.agent_jobs.get(old_jid)
            self.assertIsNotNone(old_job)
            self.assertEqual(old_job["status"], "error")
            self.assertEqual(old_job["rc"], 124)
            self.assertIn("expirado: GC da ponte (job preso)", old_job["lines"])

        # Aguarda a finalização do novo job para testar o pop do job antigo
        deadline = time.time() + 5.0
        while time.time() < deadline:
            with serve._Handler.state.agent_lock:
                j = serve._Handler.state.agent_jobs.get(new_jid)
                if j and j.get("status") != "running":
                    break
            time.sleep(0.02)

        # Em um ciclo subsequente, o job agora finalizado com idade > 3600s é removido pelo pop do GC
        code2, body2 = self._req("/api/agent", token=self.token, method="POST", body={"action": "brief"})
        self.assertEqual(code2, 200)
        self.assertTrue(body2["ok"])
        with serve._Handler.state.agent_lock:
            self.assertNotIn(old_jid, serve._Handler.state.agent_jobs)

    def test_job_running_recente_continua_retornando_409(self):
        recent_jid = "job-recente-456"
        with serve._Handler.state.agent_lock:
            serve._Handler.state.agent_jobs[recent_jid] = {
                "id": recent_jid,
                "action": "brief",
                "status": "running",
                "lines": ["rodando"],
                "rc": None,
                "_started": time.time() - 10,
            }

        code, body = self._req("/api/agent", token=self.token, method="POST", body={"action": "brief"})
        self.assertEqual(code, 409)
        self.assertFalse(body["ok"])
        self.assertIn("Já existe uma ação do agente em execução", body["error"])

    def test_run_agent_processo_fecha_stdout_mas_trava_sofre_timeout_e_retorna_124(self):
        cfg = {**config.DEFAULTS, "runner": {**config.DEFAULTS["runner"], "timeout_min": 0.001}}
        inst = type("DummyInst", (), {"cfg": cfg, "root": self.tmp, "logs": self.tmp})()
        script = "import os, time; os.close(1); os.close(2); time.sleep(10)"
        lines: list[str] = []

        t0 = time.monotonic()
        rc = asyncio.run(bridge.run_agent(inst, [sys.executable, "-c", script], lines.append))
        duration = time.monotonic() - t0

        self.assertEqual(rc, 124)
        self.assertGreaterEqual(duration, 0.9)
        self.assertLess(duration, 5.0)
        self.assertTrue(any("tempo esgotado" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
