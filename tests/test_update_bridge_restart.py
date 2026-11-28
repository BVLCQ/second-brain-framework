"""Atualizar pelo painel: a ponte volta depois do pull, e um clone só atrasado não acusa "melhorias locais".

1. O restart agendado depois de um update bem-sucedido roda numa thread NÃO daemon: o restart derruba o httpd, o
   `serve_forever` da thread principal retorna e o processo termina — daemon, a thread morria antes de subir a ponte
   nova (painel em "Ponte demorou para voltar").
2. Quem atualiza a partir de uma versão com o defeito roda o restart velho: a conferência dos serviços (watchdog,
   abertura) religa a ponte quando o último evento dela no serve.log é um update e não há ponte no ar.
3. `brain update` conta como melhoria local só o que mudou desde o ponto de separação — não o que o remoto mudou.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import serve, services, upstream  # noqa: E402


class RestartThreadOutlivesTheServer(unittest.TestCase):
    def test_restart_timer_is_not_daemon(self):
        src = (ROOT / "brainlib" / "serve.py").read_text(encoding="utf-8")
        i = src.index("threading.Timer(1.2, restart_fn)")
        block = src[i:i + 200]
        self.assertIn("t.daemon = False", block)
        self.assertNotIn("t.daemon = True", block)

    def test_a_non_daemon_timer_finishes_after_the_main_thread_returns(self):
        """O mecanismo, num processo de verdade: a thread principal sai logo; o arquivo só existe se o timer rodou."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "spawned"
            for daemon, expect in ((False, True), (True, False)):
                out.unlink(missing_ok=True)
                code = (f"import threading, time, pathlib\n"
                        f"def later():\n    time.sleep(0.3); pathlib.Path({str(out)!r}).write_text('x')\n"
                        f"t = threading.Timer(0.2, later); t.daemon = {daemon}; t.start()\n")
                subprocess.run([sys.executable, "-c", code], timeout=10, check=True)
                time.sleep(0.8)
                self.assertEqual(out.exists(), expect, f"daemon={daemon}")


class ReviveBridgeAfterUpdate(unittest.TestCase):
    def _inst(self, td: str, log: str, age_s: float = 0):
        logs = Path(td) / "logs"
        logs.mkdir()
        p = logs / "serve.log"
        p.write_text(log, encoding="utf-8")
        t = time.time() - age_s
        os.utime(p, (t, t))
        return types.SimpleNamespace(logs=logs, root=Path(td), cfg={"memory": {}})

    def _revive(self, inst, live=None):
        calls = []
        with mock.patch.object(serve, "live_panel_url", lambda _i: live):
            ok = services.revive_bridge_after_update(inst, spawn=lambda: calls.append(1) or "http://127.0.0.1:8787/")
        return ok, calls

    def test_bridge_that_died_in_an_update_restart_comes_back(self):
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td, "✓ ponte CLI no ar (Ctrl+C encerra)\n[serve] ↻ update → job=abc\n"
                                  "[serve] 127.0.0.1 \"GET /api/update/job/abc HTTP/1.1\" 200 -\n")
            ok, calls = self._revive(inst)
            self.assertTrue(ok)
            self.assertEqual(calls, [1])
            self.assertIn("ponte do painel religada", (inst.logs / "services.log").read_text(encoding="utf-8"))

    def test_nothing_when_the_bridge_came_back_is_live_or_the_log_is_old(self):
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td, "[serve] ↻ update → job=abc\n✓ ponte CLI no ar (Ctrl+C encerra)\n")
            self.assertEqual(self._revive(inst), (False, []))                   # já voltou
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td, "✓ ponte CLI no ar\n[serve] ↻ update → job=abc\n")
            self.assertEqual(self._revive(inst, live="http://127.0.0.1:8787/"), (False, []))   # há ponte no ar
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td, "✓ ponte CLI no ar\n[serve] ↻ update → job=abc\n", age_s=2 * 3600)
            self.assertEqual(self._revive(inst), (False, []))                   # antiga: o dono fechou o Brain
        with tempfile.TemporaryDirectory() as td:
            inst = types.SimpleNamespace(logs=Path(td) / "nada", root=Path(td), cfg={"memory": {}})
            self.assertFalse(services.revive_bridge_after_update(inst, spawn=lambda: self.fail("não sobe")))

    def test_ensure_calls_it_outside_the_nightly_only(self):
        with tempfile.TemporaryDirectory() as td:
            inst = self._inst(td, "")
            seen = []
            with mock.patch.object(services, "revive_bridge_after_update", lambda i: seen.append(1)), \
                    mock.patch.object(services, "PAUSE", Path(td) / "sem-pausa"):
                services.ensure(inst, reason="watchdog", probes={}, run=lambda *a, **k: (0, ""))
                services.ensure(inst, reason="nightly", probes={}, run=lambda *a, **k: (0, ""))
            self.assertEqual(seen, [1])


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}).stdout.strip()


class BehindIsNotLocalWork(unittest.TestCase):
    def test_a_clean_clone_that_is_only_behind_has_nothing_pending(self):
        with tempfile.TemporaryDirectory() as td:
            up, clone = Path(td) / "up", Path(td) / "clone"
            up.mkdir()
            _git(up, "init", "-q", "-b", "main")
            (up / "a.txt").write_text("1")
            _git(up, "add", "a.txt")
            _git(up, "commit", "-qm", "1")
            _git(td, "clone", "-q", str(up), str(clone))
            for i in range(3):                                   # o remoto anda: 3 arquivos que o clone não tem
                (up / f"novo{i}.txt").write_text(str(i))
                _git(up, "add", f"novo{i}.txt")
                _git(up, "commit", "-qm", f"n{i}")
            _git(clone, "fetch", "-q", "origin")
            ref = "origin/main"
            self.assertEqual(len(upstream._pending_files(clone, ref)[0]), 3)           # o defeito: contra o ref
            base = upstream._merge_base(clone, ref)
            self.assertEqual(upstream._pending_files(clone, base), ([], []))          # o certo: nada local
            (clone / "a.txt").write_text("mudei")                                     # mudança local de verdade
            self.assertEqual(upstream._pending_files(clone, base)[0], ["a.txt"])
            self.assertEqual(upstream._merge_base(clone, None), "")


if __name__ == "__main__":
    unittest.main()
