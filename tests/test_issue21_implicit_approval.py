"""Issue #21: aprovação implícita ao confirmar formulários no painel e na TUI."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import cli as cli_mod  # noqa: E402
from brainlib import config, forms, render  # noqa: E402
from brainlib import demo as demo_mod  # noqa: E402
from brainlib.core import Brain  # noqa: E402

try:
    import textual  # noqa: F401
    HAVE_TEXTUAL = True
except ImportError:
    HAVE_TEXTUAL = False


SURFACE_GATE_FORMS = (
    "plan.log",
    "goal.new",
    "project.new",
    "goal.edit",
    "project.edit",
    "opportunity.promote",
    "outbox.approve",
    "focus.approve",
    "publish.approve",
    "proposal.accept",
    "proposal.reject",
)


def _now_iso() -> str:
    return os.environ.get("BRAIN_NOW") or datetime.now().astimezone().replace(microsecond=0).isoformat()


def _demo_vm(tmp_dir: str) -> tuple[Path, dict]:
    root = Path(tmp_dir) / "inst"
    with mock.patch.dict(os.environ, {"BRAIN_NOW": _now_iso()}), contextlib.redirect_stdout(io.StringIO()):
        demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
    with mock.patch.dict(os.environ, {"BRAIN_NOW": _now_iso()}):
        b = Brain(config.load(root))
        return root, json.loads(json.dumps(render.view_model(b), default=str))


class ImplicitApprovalSpecsTest(unittest.TestCase):
    """Todos os 11 formulários de gate/quote com auto='surface' injetam 'painel' no JS e 'tui' no Python."""

    def test_all_surface_gate_forms_emit_surface_tokens_and_keep_empty_value(self):
        with tempfile.TemporaryDirectory() as td:
            _, m = _demo_vm(td)
            goal = m["goals"][0]
            proj = m["projects"][0]
            opp = m["portfolio"]["opportunities"][0]
            ctx_map = {
                "plan.log": {"diff": "GOAL-9 nasce", "reason": "expansao da padaria", "ev": "ata"},
                "goal.new": {"nid": "GOAL-9"},
                "project.new": {"nid": "PROJ-9", "goal": goal["id"], "goal_title": goal["title"]},
                "goal.edit": {"id": goal["id"], "item": goal},
                "project.edit": {"id": proj["id"], "item": proj},
                "opportunity.promote": {"id": opp["id"], "item": opp},
                "outbox.approve": {"id": "MSG-0001", "to_name": "Heitor-demo", "n": "1"},
                "focus.approve": {"id": "FOCUS-0001"},
                "publish.approve": {"id": "PUB-0001", "report": "reports/share/status.html", "destination": "slack:#padaria"},
                "proposal.accept": {"id": "PROP-0001", "summary": "fechar tarefa", "kind": "fechar-acao",
                                    "target": "TASK-0001", "into": ""},
                "proposal.reject": {"id": "PROP-0001", "summary": "fechar tarefa"},
            }
            raw_map = {
                "plan.log": {"diff": "GOAL-9 nasce", "reason": "expansao da padaria"},
                "goal.new": {"title": "Abrir segunda loja"},
                "project.new": {"title": "Forno novo"},
                "goal.edit": {"title": "Titulo revisado", "status": "ativo"},
                "project.edit": {"title": "Projeto revisado", "status": "ativo"},
                "opportunity.promote": {"level": "project", "goal": goal["id"], "title": opp["title"]},
                "outbox.approve": {},
                "focus.approve": {},
                "publish.approve": {},
                "proposal.accept": {"how": "confirmado por marina-demo"},
                "proposal.reject": {},
            }

            for fid in SURFACE_GATE_FORMS:
                fm = forms.FORMS[fid]
                qfield = next(f for f in fm.fields if f.id == "quote")
                self.assertEqual(qfield.value, "", f"{fid}.quote precisa manter value=''")
                self.assertTrue(qfield.req, f"{fid}.quote precisa manter req=True")
                self.assertEqual(qfield.auto, "surface", f"{fid}.quote precisa de auto='surface'")
                self.assertTrue(forms.missing(fid, raw_map[fid], ctx_map[fid], m),
                                f"{fid}: sem surface continua exigindo aprovação")
                self.assertEqual(forms.missing(fid, raw_map[fid], ctx_map[fid], m, surface="tui"), "")
                cmd_tui = forms.build(fid, raw_map[fid], ctx_map[fid], m, surface="tui")[0]
                flag = qfield.arg or "--quote"
                self.assertIn(flag, cmd_tui, f"{fid} tui: {cmd_tui}")
                self.assertEqual(cmd_tui[cmd_tui.index(flag) + 1], "tui", f"{fid} tui: {cmd_tui}")

            node = shutil.which("node")
            if node:
                exported = forms.export()
                panel_forms = [fid for fid in SURFACE_GATE_FORMS if forms.FORMS[fid].where != "tui"]
                script = (
                    "const F = require(process.argv[2]);\n"
                    "const fs = require('fs');\n"
                    "const {m, cases} = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));\n"
                    "const out = cases.map(c => ({\n"
                    "  id: c.id,\n"
                    "  missing: F.missing(m.forms[c.id], c.raw, c.ctx, m),\n"
                    "  argv: F.formArgv(m.forms[c.id], c.raw, c.ctx, m),\n"
                    "}));\n"
                    "process.stdout.write(JSON.stringify(out));\n"
                )
                payload = {"m": {**m, "forms": exported},
                           "cases": [{"id": fid, "raw": raw_map[fid], "ctx": ctx_map[fid]} for fid in panel_forms]}
                data_path = Path(td) / "cases.json"
                js_path = Path(td) / "run.js"
                data_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                js_path.write_text(script, encoding="utf-8")
                r = subprocess.run([node, str(js_path), str(ROOT / "brainlib" / "assets" / "src" / "forms.js"),
                                    str(data_path)], capture_output=True, text=True, check=True)
                for row in json.loads(r.stdout):
                    fid = row["id"]
                    self.assertEqual(row["missing"], "", f"JS {fid}: {row}")
                    cmd = row["argv"][0]
                    qfield = next(f for f in forms.FORMS[fid].fields if f.id == "quote")
                    flag = qfield.arg or "--quote"
                    self.assertIn(flag, cmd, f"JS {fid}: {cmd}")
                    self.assertEqual(cmd[cmd.index(flag) + 1], "painel", f"JS {fid}: {cmd}")

    def test_memory_egress_retains_typed_approval_and_no_auto(self):
        fm = forms.FORMS["memory.mode"]
        qfield = next(f for f in fm.fields if f.id == "quote")
        self.assertIsNone(qfield.auto)
        self.assertEqual(qfield.value, "")
        self.assertTrue(qfield.req)
        self.assertTrue(forms.missing("memory.mode", {"mode": "full", "provider": "anthropic", "embeddings": "fireworks"},
                                      {}, {}, surface="tui"))
        self.assertEqual(forms.missing("memory.mode", {"mode": "full", "provider": "anthropic",
                                                       "embeddings": "fireworks", "quote": "ok"},
                                       {}, {}, surface="tui"), "")

    def test_built_assets_and_js_sources_have_new_seal_and_no_ok_literal(self):
        for rel in ("brainlib/assets/src/extra.js", "brainlib/assets/src/forms.js",
                    "brainlib/assets/dashboard.html", "brainlib/assets/portfolio.html"):
            txt = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("ok literal", txt, f"{rel} ainda menciona 'ok literal'")
            if "forms.js" not in rel:
                self.assertIn("gate — confirmar aprova", txt, f"{rel} sem novo selo de gate")


class ImplicitApprovalCliTest(unittest.TestCase):
    """CLI end-to-end com Padaria Pão Quente (marina-demo): 'painel'/'tui' gravam no ledger; vazio falha."""

    def _run_cli(self, root: Path, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"BRAIN_HOME": str(root), "BRAIN_NOW": _now_iso()}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli_mod.main(list(args))
            except SystemExit as exc:
                rc = int(exc.code or 0)
        return rc, out.getvalue(), err.getvalue()

    def test_cli_accepts_painel_and_tui_tokens_and_rejects_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = _demo_vm(td)
            # --approval vazio continua recusado no CLI
            rc_empty, _, _ = self._run_cli(root, "plan", "edit", "GOAL-1", "--title", "Bloqueado", "--approval", "")
            self.assertNotEqual(rc_empty, 0)

            rc_painel, _, err_p = self._run_cli(root, "plan", "edit", "GOAL-1",
                                                "--title", "Padaria Pão Quente — Expansão", "--approval", "painel")
            self.assertEqual(rc_painel, 0, err_p)
            rc_tui, _, err_t = self._run_cli(root, "plan", "edit", "GOAL-1",
                                             "--title", "Padaria Pão Quente — Consolidada", "--approval", "tui")
            self.assertEqual(rc_tui, 0, err_t)

            # outbox draft + approve com --quote "" (falha), --quote painel e --quote tui
            rc_d1, _, err_d1 = self._run_cli(root, "outbox", "draft", "--to", "caio-demo",
                                             "--text", "Oi Caio-demo, fornada pronta.", "--why", "alinhamento")
            self.assertEqual(rc_d1, 0, err_d1)
            rc_d2, _, err_d2 = self._run_cli(root, "outbox", "draft", "--to", "sonia-demo",
                                             "--text", "Oi Sonia-demo, entrega confirmada.", "--why", "alinhamento")
            self.assertEqual(rc_d2, 0, err_d2)

            b = Brain(config.load(root))
            drafts = sorted(mid for mid, msg in b.state.messages.items() if msg.status == "rascunho")
            self.assertGreaterEqual(len(drafts), 2)
            m1, m2 = drafts[-2], drafts[-1]

            rc_qempty, _, _ = self._run_cli(root, "outbox", "approve", m1, "--quote", "")
            self.assertNotEqual(rc_qempty, 0)
            rc_qp, _, err_qp = self._run_cli(root, "outbox", "approve", m1, "--quote", "painel")
            self.assertEqual(rc_qp, 0, err_qp)
            rc_qt, _, err_qt = self._run_cli(root, "outbox", "approve", m2, "--quote", "tui")
            self.assertEqual(rc_qt, 0, err_qt)

            events = Brain(config.load(root)).read_events()
            approvals = [e["data"].get("approval") for e in events if e["type"] == "plan.changed"]
            self.assertIn("painel", approvals)
            self.assertIn("tui", approvals)
            quotes = {e["id"]: e["data"].get("quote") for e in events if e["type"] == "message.approved"}
            self.assertEqual(quotes.get(m1), "painel")
            self.assertEqual(quotes.get(m2), "tui")


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado")
class ImplicitApprovalTuiTest(unittest.IsolatedAsyncioTestCase):
    """TUI: gates de superfície não renderizam #f_quote e confirmam direto; memory.mode full mantém #f_quote."""

    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {"BRAIN_NOW": _now_iso()}))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root, _ = _demo_vm(self.tmp.name)
        self.inst = config.load(self.root)

    async def test_outbox_approve_has_no_input_keeps_message_extra_and_approves_on_enter(self):
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "]", "]")
            mid = app.cur().id
            msg_text = app.cur().data["text"]
            await pilot.press("A")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertFalse(app.screen.query("#f_quote"))
            self.assertIn(msg_text, str(app.screen.query_one("#mx").render()))
            self.assertIn("--quote tui", str(app.screen.query_one("#cmdp").render()))
            await pilot.press("enter")
            for _ in range(80):
                await pilot.pause(0.1)
                if not app.busy and not app._lock.locked() and len(app.screen_stack) == 1:
                    break
            ev = next(e for e in reversed(Brain(self.inst).read_events())
                      if e["type"] == "message.approved" and e["id"] == mid)
            self.assertEqual(ev["data"]["quote"], "tui")

    async def test_memory_mode_full_retains_quote_input_in_tui(self):
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.open_form("memory.mode", values={"mode": "full", "provider": "anthropic", "embeddings": "fireworks"})
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            inp = app.screen.query_one("#f_quote")
            self.assertEqual(inp.value, "")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            # continua aberto por falta da aprovação digitada
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertIn("Preencha", str(app.screen.query_one("#err").render()))


if __name__ == "__main__":
    unittest.main()
