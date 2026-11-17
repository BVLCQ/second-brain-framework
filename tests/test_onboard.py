"""Onboarding no navegador (brainlib/onboard.py + rotas /api/onboard/* da ponte)."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import tomllib
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import config, onboard, serve, util       # noqa: E402
from brainlib.core import Brain                         # noqa: E402

TEMPLATE_PROFILE = "# PROFILE\n\n## Papel\n\n(a preencher no /init)\n"


def _inst(tmp: Path) -> config.Instance:
    for d in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH",
              "vault/reports"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dono do cérebro"\n\n[work]\nstart = "09:00"\nend = "18:00"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    (tmp / "vault" / "PROFILE" / "profile.md").write_text(TEMPLATE_PROFILE, encoding="utf-8")
    return config.load(tmp)


class StepTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.b = Brain(_inst(self.tmp))

    def tearDown(self):
        self._td.cleanup()

    def test_fresh_instance_needs_onboarding_and_finish_closes_it(self):
        self.assertTrue(onboard.needed(self.b))
        onboard._save_progress(self.b.inst, finished="2026-01-01")
        self.assertFalse(onboard.needed(self.b))

    def test_configured_instance_without_progress_does_not_need_it(self):
        onboard.save_about(self.b, {"name": "Marina Demo"})
        (self.tmp / "vault/PROFILE/profile.md").write_text("# PROFILE\n\n## Papel\n\nPadeira.\n", encoding="utf-8")
        onboard._progress_file(self.b.inst).unlink()
        self.assertFalse(onboard.needed(self.b))

    def test_about_generates_the_id_from_the_name(self):
        r = onboard.save_about(self.b, {"name": "Marina Demo", "nickname": "Mari", "role": "Padeira",
                                        "email": "contato@example.com"})
        self.assertEqual(r["id"], "marina-demo")
        cfg = tomllib.loads((self.tmp / "config/brain.toml").read_text(encoding="utf-8"))
        self.assertEqual(cfg["owner"]["id"], "marina-demo")
        p = self.b.state.people["marina-demo"]
        self.assertEqual((p.name, p.aliases, p.role, p.email), ("Marina Demo", ["Mari"], "Padeira", "contato@example.com"))
        ev = [e for e in self.b.read_events() if e["type"] == "person.added"][0]
        self.assertEqual((ev["by"], ev["prov"]), ("owner", "declarado"))

    def test_about_again_keeps_the_id_and_adds_the_alias(self):
        onboard.save_about(self.b, {"name": "Marina Demo"})
        onboard.save_about(self.b, {"name": "Marina D. Demo", "nickname": "Mari"})
        self.assertEqual(self.b.owner, "marina-demo")
        self.assertEqual(self.b.state.people["marina-demo"].name, "Marina D. Demo")
        self.assertIn("Mari", self.b.state.people["marina-demo"].aliases)

    def test_about_validates(self):
        with self.assertRaises(util.BrainError):
            onboard.save_about(self.b, {"name": "  "})
        with self.assertRaises(util.BrainError):
            onboard.save_about(self.b, {"name": "Marina", "email": "sem-arroba"})

    def test_profile_preview_then_save_and_no_silent_overwrite(self):
        onboard.save_about(self.b, {"name": "Marina Demo", "nickname": "Mari", "role": "Padeira"})
        md = onboard.profile_markdown(self.b, {"about": "Cuido da produção.", "focus": "Abrir a 2ª loja."})
        self.assertIn("Marina Demo (Mari) — Padeira.", md)
        self.assertIn("## Sobre mim\n\nCuido da produção.", md)
        onboard.save_profile(self.b, {"markdown": md})
        self.assertFalse(onboard.profile_is_template(self.b.inst))
        with self.assertRaises(util.BrainError):                    # já escrito: só com confirmação explícita
            onboard.save_profile(self.b, {"markdown": md})
        onboard.save_profile(self.b, {"markdown": md, "overwrite": True})
        with self.assertRaises(util.BrainError):
            onboard.save_profile(self.b, {"markdown": "lixo", "overwrite": True})

    def test_routine_validates_and_saves(self):
        onboard.save_routine(self.b, {"timezone": "America/Sao_Paulo", "start": "08:30", "end": "17:30",
                                      "lunch": "12:00-13:00"})
        self.assertEqual(self.b.inst.cfg["work"]["start"], "08:30")
        for bad in ({"timezone": "Marte/Olympus"}, {"start": "18:00", "end": "09:00"}, {"lunch": "meio-dia"}):
            data = {"timezone": "UTC", "start": "09:00", "end": "18:00", "lunch": "", **bad}
            with self.assertRaises(util.BrainError):
                onboard.save_routine(self.b, data)

    def test_connectors_enable_only_read_tools_and_simple_sources(self):
        from brainlib import watch
        onboard.enable_connectors(self.b, {"connectors": ["slack", "gmail", "inexistente"],
                                           "slack_channels": "#time-demo, compras, #ruim;rm"})
        allow = self.b.inst.cfg["runner"]["allow"]
        self.assertIn("mcp__claude_ai_Slack__slack_read_channel", allow)
        self.assertIn("mcp__claude_ai_Gmail__search_threads", allow)
        self.assertFalse([r for r in allow if config.is_external_write(r)], "nenhuma ferramenta de escrita")
        self.assertFalse([r for r in allow if "send" in r or "create" in r])
        keys = {s["key"] for s in watch.list_sources(self.b.inst)}
        self.assertEqual(keys, {"gmail-hoje", "slack-time-demo", "slack-compras"})
        onboard.enable_connectors(self.b, {"connectors": ["slack", "gmail"], "slack_channels": "#time-demo"})
        self.assertEqual(len(self.b.inst.cfg["runner"]["allow"]), len(allow))          # idempotente

    def test_parse_mcp_list(self):
        out = onboard.parse_mcp_list("Checking…\n\nclaude.ai Slack: https://x/mcp - ✔ Connected\n"
                                     "claude.ai Gmail: https://y - ! Needs authentication\n"
                                     "claude.ai Outro: https://z - ✘ Failed to connect\n")
        self.assertEqual(out, {"claude.ai Slack": "connected", "claude.ai Gmail": "auth", "claude.ai Outro": "error"})
        st = {c["key"]: c["status"] for c in onboard.connector_status(out, self.b.inst.cfg)}
        self.assertEqual((st["slack"], st["gmail"], st["drive"]), ("connected", "auth", "missing"))

    def test_keys_accept_only_known_names_and_never_echo_values(self):
        r = onboard.save_keys(self.b, {"GITHUB_TOKEN": "github_pat_FAKE", "PATH": "/tmp/x"})
        self.assertEqual(r, {"keys": {"GITHUB_TOKEN": True}})
        env = config.load_env(self.b.inst)
        self.assertEqual(env.get("GITHUB_TOKEN"), "github_pat_FAKE")
        self.assertNotIn("PATH=/tmp/x", (self.tmp / "config/.env").read_text(encoding="utf-8"))
        self.assertNotIn("github_pat_FAKE", json.dumps(onboard.state(self.b)))
        with self.assertRaises(util.BrainError):
            onboard.save_keys(self.b, {"GITHUB_TOKEN": "com espaço"})

    def test_memory_later_and_full_needs_consent(self):
        self.assertEqual(onboard.apply_memory(self.b, {"mode": "full", "later": True}), {"later": True})
        self.assertEqual(onboard.progress(self.b.inst)["memory_later"], "full")
        with self.assertRaises(util.BrainError):
            onboard.apply_memory(self.b, {"mode": "full", "key": "sk-x"})
        with self.assertRaises(util.BrainError):
            onboard.apply_memory(self.b, {"mode": "turbo"})

    def test_upload_lands_in_the_inbox_with_a_safe_name(self):
        r = onboard.save_upload(self.b, "../../../etc/Planejamento 2027 (v2).PDF", b"%PDF-1.4 teste")
        self.assertEqual(r["name"], "planejamento-2027-v2.pdf")
        self.assertTrue((self.tmp / "vault/RAW/inbox/planejamento-2027-v2.pdf").exists())
        self.assertEqual(onboard.save_upload(self.b, "Planejamento 2027 (v2).pdf", b"x")["name"],
                         "planejamento-2027-v2-2.pdf")                       # colisão: sufixo, nunca sobrescreve
        for name, body in (("virus.exe", b"x"), ("vazio.pdf", b""), ("grande.pdf", b"x" * (onboard.UPLOAD_MAX + 1))):
            with self.assertRaises(util.BrainError):
                onboard.save_upload(self.b, name, body)
        self.assertEqual(sorted(onboard.progress(self.b.inst)["planning_sources"]),
                         ["RAW/inbox/planejamento-2027-v2-2.pdf", "RAW/inbox/planejamento-2027-v2.pdf"])

    def test_proposal_parsing_cleans_what_the_agent_returns(self):
        text = 'Pronto:\n```json\n{"goals": [{"title": "Abrir a 2ª loja", "horizon": "março", "why": "não consta",' \
               ' "projects": [{"title": "Ponto", "deliverables": [{"title": "Escolher", "due": "2026-12-15"},' \
               ' {"title": "", "due": ""}]}]}, {"title": ""}], "summary": "Você quer abrir a 2ª loja."}\n```'
        p = onboard._parse_proposal(text)
        self.assertEqual(p["goals"], [{"title": "Abrir a 2ª loja", "horizon": "", "why": "",
                                       "projects": [{"title": "Ponto",
                                                     "deliverables": [{"title": "Escolher", "due": "2026-12-15"}]}]}])
        with self.assertRaises(util.BrainError):
            onboard._parse_proposal("não entendi")

    def test_planning_apply_goes_through_the_gate(self):
        onboard.save_about(self.b, {"name": "Marina Demo"})
        proposal = {"goals": [{"title": "Abrir a 2ª loja", "horizon": "2027-03-31", "why": "crescer",
                               "projects": [{"title": "Ponto", "deliverables": [{"title": "Escolher", "due": ""}]}]}]}
        with self.assertRaises(util.BrainError):                     # sem a confirmação, nada nasce
            onboard.apply_planning(self.b, {"proposal": proposal})
        self.assertEqual(self.b.plan.goals, {})
        r = onboard.apply_planning(self.b, {"proposal": proposal, "approved": True})
        self.assertEqual(r["created"], ["GOAL-1", "PROJ-1", "PROJ-1.1"])
        changed = [e for e in self.b.read_events() if e["type"] == "plan.changed"]
        self.assertEqual(len(changed), 2)
        self.assertTrue(all(e["data"]["approval"] for e in changed))
        self.assertIn("aprovado:", (self.tmp / "vault/PLANNING/log.md").read_text(encoding="utf-8"))


class MoreStepTests(unittest.TestCase):
    setUp, tearDown = StepTests.setUp, StepTests.tearDown

    def test_unchecking_a_connector_revokes_its_rules_and_default_source(self):
        from brainlib import watch
        onboard.enable_connectors(self.b, {"connectors": ["slack", "gmail"]})
        r = onboard.enable_connectors(self.b, {"connectors": ["slack"]})
        allow = self.b.inst.cfg["runner"]["allow"]
        self.assertFalse([x for x in allow if "Gmail" in x])
        self.assertTrue([x for x in allow if "Slack" in x])
        self.assertEqual(r["removed"], ["gmail-hoje"])
        self.assertNotIn("gmail-hoje", {s["key"] for s in watch.list_sources(self.b.inst)})

    def test_returning_user_is_not_trapped_in_onboarding(self):
        onboard.save_about(self.b, {"name": "Marina Demo"})
        (self.tmp / "vault/PROFILE/profile.md").write_text("# PROFILE\n\n## Papel\n\nPadeira.\n", encoding="utf-8")
        onboard._progress_file(self.b.inst).unlink()
        onboard.run_action(self.b, "routine", {"timezone": "UTC", "start": "09:00", "end": "18:00", "lunch": ""})
        self.assertFalse(onboard.progress(self.b.inst)["started_unconfigured"])
        self.assertFalse(onboard.needed(self.b))                  # reabriu, salvou um passo, saiu: não volta preso

    def test_new_user_who_stops_midway_resumes(self):
        onboard.run_action(self.b, "about", {"name": "Marina Demo"})
        (self.tmp / "vault/PROFILE/profile.md").write_text("# PROFILE\n\n## Papel\n\nPadeira.\n", encoding="utf-8")
        self.assertTrue(onboard.progress(self.b.inst)["started_unconfigured"])
        self.assertTrue(onboard.needed(self.b))

    def test_planning_apply_is_idempotent_and_logs_deliverables(self):
        onboard.save_about(self.b, {"name": "Marina Demo"})
        proposal = {"goals": [{"title": "Abrir a 2ª loja", "projects": [
            {"title": "Ponto", "deliverables": [{"title": "Escolher"}, {"title": "Assinar"}]}]}]}
        onboard.apply_planning(self.b, {"proposal": proposal, "approved": True})
        proposal["goals"][0]["projects"][0]["deliverables"].append({"title": "Reformar"})
        r = onboard.apply_planning(self.b, {"proposal": proposal, "approved": True})   # repetir não duplica
        self.assertEqual(r["created"], ["PROJ-1.3"])
        self.assertEqual(len(self.b.plan.goals), 1)
        log = (self.tmp / "vault/PLANNING/log.md").read_text(encoding="utf-8")
        self.assertIn("PROJ-1.3 entregável criado sob PROJ-1: Reformar", log)

    def test_memory_full_goes_through_the_wizard_gate_with_the_key(self):
        from unittest import mock
        from brainlib import memory, setup
        calls = {}
        with mock.patch.object(setup, "docker_available", return_value=True), \
                mock.patch.object(setup, "hindsight_health", return_value={"status": "ok"}), \
                mock.patch.object(setup, "compose_up", return_value=True), \
                mock.patch.object(setup, "wait_hindsight", return_value=True), \
                mock.patch.object(setup, "lmstudio_up", return_value=True), \
                mock.patch.object(memory, "setup", side_effect=lambda b: calls.setdefault("setup", True) and ["brain"]):
            r = onboard.apply_memory(self.b, {"mode": "full", "provider": "anthropic", "key": "sk-ant-FAKE",
                                              "consent": True})
            for _ in range(200):
                j = onboard.job(r["job"])
                if j["status"] != "running":
                    break
                import time
                time.sleep(0.05)
        self.assertEqual(j["status"], "done", j["log"])
        self.assertEqual(j["result"], {"mode": "full"})
        self.assertTrue(calls.get("setup"))
        env = config.load_env(config.reload(self.b.inst))
        self.assertEqual(env.get("HINDSIGHT_API_LLM_API_KEY"), "sk-ant-FAKE")
        self.assertNotIn("sk-ant-FAKE", json.dumps(j))


class OpenTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.b = Brain(_inst(Path(self._td.name)))

    def tearDown(self):
        self._td.cleanup()

    def _open(self, setup=False):
        import argparse
        from brainlib import cli
        cli.cmd_open(argparse.Namespace(panel="execucao", setup=setup), self.b)

    def test_needed_opens_the_onboarding_url_with_the_token(self):
        from unittest import mock
        from brainlib import render
        opened = []
        with mock.patch.object(render, "ensure_bridge", return_value="http://127.0.0.1:8787/#t=abc"), \
                mock.patch.object(util, "open_url", side_effect=opened.append), \
                contextlib.redirect_stdout(io.StringIO()):
            self._open()
        self.assertEqual(opened, ["http://127.0.0.1:8787/onboarding#t=abc"])

    def test_configured_instance_opens_the_panel(self):
        from unittest import mock
        from brainlib import render
        onboard._save_progress(self.b.inst, finished="2026-01-01")
        with mock.patch.object(render, "render_all", return_value={}) as ra, \
                mock.patch.object(render, "summary", return_value="ok"), \
                mock.patch.object(render, "open_dashboard") as od, \
                contextlib.redirect_stdout(io.StringIO()):
            self._open()
        ra.assert_called_once()
        od.assert_called_once_with(self.b, "execucao")

    def test_no_bridge_fails_visibly_instead_of_opening_the_panel(self):
        from unittest import mock
        from brainlib import render
        with mock.patch.object(render, "ensure_bridge", return_value=None), \
                mock.patch.object(render, "open_dashboard") as od, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(util.BrainError):
                self._open()
        od.assert_not_called()

    def test_same_version_bridge_is_not_stopped(self):
        f = serve.live_url_file(self.b.inst)
        f.parent.mkdir(parents=True, exist_ok=True)
        from brainlib import __version__
        f.write_text(json.dumps({"url": "http://127.0.0.1:1/#t=x", "port": 1, "pid": 999999,
                                 "version": __version__}), encoding="utf-8")
        self.assertFalse(serve.stop_stale(self.b.inst))
        f.write_text(json.dumps({"url": "http://127.0.0.1:1/#t=x", "port": 1, "pid": 999999}), encoding="utf-8")
        self.assertFalse(serve.stop_stale(self.b.inst))           # versão antiga, mas morta: nada a encerrar


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.inst = _inst(Path(cls.td.name))
        cls.token = "tok-onboard"
        serve._Handler.state = serve._State(cls.inst, cls.token)
        from http.server import ThreadingHTTPServer
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

    def _req(self, path, body=None, token=True, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                   method="POST" if data is not None else "GET")
        if token:
            r.add_header("X-Brain-Token", self.token)
        for k, v in (headers or {}).items():
            r.add_header(k, v)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_page_boots_without_token_but_api_requires_it(self):
        code, html = self._req("/onboarding", token=False)
        self.assertEqual(code, 200)
        self.assertIn("Vamos montar o seu Brain", html)
        self.assertEqual(self._req("/brain.svg", token=False)[0], 200)
        self.assertEqual(self._req("/api/onboard/state", token=False)[0], 401)
        self.assertEqual(self._req("/api/onboard/about", {"name": "X"}, token=False)[0], 401)

    def test_state_and_about_through_the_bridge(self):
        code, body = self._req("/api/onboard/state")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["state"]["needed"])
        code, body = self._req("/api/onboard/acao-que-nao-existe", {})
        self.assertEqual(code, 400)

    def test_secret_never_reaches_the_log(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code, body = self._req("/api/onboard/keys", {"GITHUB_TOKEN": "github_pat_NAOVAZA"})
        self.assertEqual(code, 200)
        self.assertNotIn("NAOVAZA", buf.getvalue())
        self.assertNotIn("NAOVAZA", body)

    def test_upload_route(self):
        code, body = self._req("/api/onboard/upload", raw=b"# metas\n", headers={"X-File-Name": "metas%202027.md"})
        self.assertEqual(code, 200, body)
        self.assertEqual(json.loads(body)["name"], "metas-2027.md")
        code, _ = self._req("/api/onboard/upload", raw=b"MZ", headers={"X-File-Name": "x.exe"})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
