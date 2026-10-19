"""Testes do TUI (Textual). Rodam só com o extra instalado: `./brain tui --setup` e depois
`.venv-tui/bin/python -m unittest tests.test_tui`. Sem o Textual, a classe de UI é pulada.
Usam a instância de demonstração numa pasta temporária — nunca o vault do dono."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, demo as demo_mod, util, watch
from brainlib.tui import bridge, dates

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


class DatesTest(unittest.TestCase):
    TODAY = date(2026, 10, 15)   # quinta

    def test_formats(self):
        p = lambda s: dates.parse_due(s, self.TODAY)  # noqa: E731
        self.assertEqual(p("hoje"), self.TODAY)
        self.assertEqual(p("amanhã"), date(2026, 10, 16))
        self.assertEqual(p("amanha"), date(2026, 10, 16))
        self.assertEqual(p("sex"), date(2026, 10, 16))
        self.assertEqual(p("qui"), date(2026, 10, 22))        # mesmo dia da semana = a próxima
        self.assertEqual(p("sáb"), date(2026, 10, 17))
        self.assertEqual(p("sexta-feira"), date(2026, 10, 16))
        self.assertEqual(p("segunda"), date(2026, 10, 19))
        self.assertEqual(p("+3d"), date(2026, 10, 18))
        self.assertEqual(p("20/10"), date(2026, 10, 20))
        self.assertEqual(p("20/10/2027"), date(2027, 10, 20))
        self.assertEqual(p("2026-11-01"), date(2026, 11, 1))
        self.assertIsNone(p(""))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            dates.parse_due("semana que vem", self.TODAY)
        with self.assertRaises(ValueError):
            dates.parse_due("qualquer dia", self.TODAY)          # não é "qua"
        self.assertIn("não reconhecida", dates.describe("xyz", self.TODAY))
        self.assertIn("2026-10-16", dates.describe("sex", self.TODAY))


class BridgeTest(unittest.TestCase):
    def test_display_quotes_arguments(self):
        self.assertEqual(bridge.display(["action", "close", "A-0001", "--how", "enviei o draft"]),
                         "brain action close A-0001 --how 'enviei o draft'")

    def test_agent_argv_uses_custom_command_and_prompt(self):
        cfg = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "command": "meu-agente --p {prompt}"}}
        argv = bridge.agent_argv(cfg, "/dump")
        self.assertEqual(argv[:2], ["meu-agente", "--p"])
        self.assertTrue(argv[2].endswith("/dump"))
        self.assertIn("dono está presente", argv[2])

    def test_agent_argv_claude_gets_runner_allow_then_tui_extras(self):
        cfg = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "agent": "claude", "allow": ["mcp__x__ler"]},
                                 "tui": {"agent_allow": ["mcp__x__enviar"]}}
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            argv = bridge.agent_argv(cfg, "/update")
        self.assertEqual(argv[-2:], ["mcp__x__ler", "mcp__x__enviar"])

    def test_agent_argv_claude_uses_tui_model_and_effort_before_allowed_tools(self):
        cfg = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "agent": "claude", "allow": ["mcp__x__ler"]},
                                 "tui": {"agent_allow": [], "model": "claude-haiku-5-5", "effort": "high"}}
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            argv = bridge.agent_argv(cfg, "/update")
        i = argv.index("--model")
        self.assertEqual(argv[i:i + 4], ["--model", "claude-haiku-5-5", "--effort", "high"])
        self.assertLess(i, argv.index("--allowedTools"))
        self.assertEqual(argv[-1], "mcp__x__ler")

    def test_agent_argv_none_when_disabled(self):
        cfg = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "agent": "none"}}
        self.assertIsNone(bridge.agent_argv(cfg, "/dump"))


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class TuiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "inst"
        with contextlib.redirect_stdout(io.StringIO()):
            demo_mod.cli(argparse.Namespace(dir=str(self.root), open=False))
        fake = Path(self.tmp.name) / "fake_agent.py"
        fake.write_text(
            "import os, re, subprocess, sys\n"
            "prompt = sys.argv[1]\nprint('agente de mentira recebeu:', prompt.split('. ', 1)[-1][:60])\n"
            "m = re.search(r'M-\\d{4}', prompt)\n"
            "if m:\n    subprocess.run([sys.executable, os.environ['FAKE_BRAIN'], 'outbox', 'sent', m.group(0), '--link', 'https://example.com/p/1'], check=True)\n"
            "m = re.search(r'S-\\d{4}', prompt)\n"
            "if m:\n    subprocess.run([sys.executable, os.environ['FAKE_BRAIN'], 'publish', 'done', m.group(0), '--link', 'https://example.com/canvas/1'], check=True)\n",
            encoding="utf-8")
        os.environ["FAKE_BRAIN"] = str(ROOT / "brain")
        self.addCleanup(os.environ.pop, "FAKE_BRAIN", None)
        with open(self.root / "config" / "brain.toml", "a", encoding="utf-8") as fh:
            fh.write(f'\n[runner]\ncommand = "{sys.executable} {fake} {{prompt}}"\ntimeout_min = 1\n')
        self.inst = config.load(self.root)
        watch.add(self.inst, "slack-dados", {"kind": "slack", "window": "1d", "channel": "#dados"})
        watch.add(self.inst, "gcal-14d", {"kind": "gcal", "window": "14d"})

    # ── infra ──────────────────────────────────────────────────────────────
    async def settle(self, app, pilot, n=80):
        for _ in range(n):
            await pilot.pause(0.1)
            if not app.busy and not app._lock.locked() and len(app.screen_stack) == 1:
                return
        self.fail("o TUI não terminou de executar")

    def app(self):
        from brainlib.tui.app import BrainApp
        return BrainApp(self.inst)

    KEYS = {" ": "space", ".": "full_stop", "-": "minus", ",": "comma", "#": "number_sign", ":": "colon", "/": "slash"}

    async def typ(self, pilot, text: str) -> None:
        for ch in text:
            await pilot.press(self.KEYS.get(ch, ch))

    async def fill(self, pilot, **vals) -> None:
        """Preenche campos do formulário aberto pelo id (rápido e independente da ordem de tab)."""
        for k, v in vals.items():
            pilot.app.screen.query_one(f"#f_{k}").value = v
        await pilot.pause(0.15)

    @staticmethod
    def text_of(widget) -> str:
        return str(getattr(widget, "content", None) or widget.render())

    def log_text(self, app) -> str:
        return "\n".join(str(l.text) for l in app.query_one("#log").lines)

    def state(self, app):
        from brainlib.core import Brain
        return Brain(self.inst).state

    # ── navegação ──────────────────────────────────────────────────────────
    async def test_panels_tabs_and_selection(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            self.assertEqual(app.p, 2)
            for k, p in (("1", 1), ("3", 3), ("5", 5), ("4", 4)):
                await pilot.press(k)
                self.assertEqual(app.p, p)
            await pilot.press("]")
            self.assertEqual(app.tab[4], 1)
            await pilot.press("[", "[")
            self.assertEqual(app.tab[4], 0)
            await pilot.press("2", "j")
            self.assertEqual(app.sel_index(2), 1)
            await pilot.press("k")
            self.assertEqual(app.sel_index(2), 0)
            # painéis só mudam pelos números; setas (e h l) trocam de aba como [ ]
            await pilot.press("tab", "shift+tab")
            self.assertEqual(app.p, 2)
            await pilot.press("right")
            self.assertEqual((app.p, app.tab[2]), (2, 1))
            await pilot.press("l")
            self.assertEqual(app.tab[2], 2)
            await pilot.press("right")                          # no fim da lista de abas, fica
            self.assertEqual((app.p, app.tab[2]), (2, 2))
            await pilot.press("left", "h")
            self.assertEqual((app.p, app.tab[2]), (2, 0))
            await pilot.press("3", "right", "left")             # painel de uma aba só: nada muda
            self.assertEqual((app.p, app.tab[3]), (3, 0))

    async def test_context_keys_change_with_panel_and_tab(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            keys = lambda: {k.k for k in app.ctx_keys()}  # noqa: E731
            self.assertIn("c", keys())                      # ações: fechar
            await pilot.press("3")
            self.assertIn("E", keys())                      # plano: gate
            await pilot.press("4", "]")
            self.assertIn("n", keys())                      # outbox: rascunhar
            await pilot.press("1")
            self.assertEqual({"u", "c", "d", "b", "o"}, keys())   # resumo: agente e painel
            every = {k.k for k in app.ctx_keys(every=True, panel=4, tab=1)}
            self.assertEqual({"n", "A", "S", "x", "T"}, every)

    async def test_click_on_hint_and_tab(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.press("a")
            await pilot.pause(0.1)
            self.assertTrue(app.show_all)
            panel = app.query_one("#p4")
            x0, x1, i = panel.tab_spans[1]
            await pilot.click("#p4", offset=(x0 + 2, 0))
            self.assertEqual((app.p, app.tab[4]), (4, 1))

    async def test_zoom_help_palette_filter_search(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("enter")
            self.assertTrue(app.zoom)
            await pilot.press("escape")
            self.assertFalse(app.zoom)
            await pilot.press("question_mark")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "TextModal")
            await pilot.press("escape")
            await pilot.press("colon")
            await pilot.pause(0.3)
            await pilot.press(*"fechar")
            await pilot.pause(0.4)
            await pilot.press("enter")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")      # paleta → formulário de fechar
            await pilot.press("escape")
            await pilot.press("slash")
            await pilot.press(*"pauta")
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertEqual([i.id for i in app.items(2)], [i.id for i in app.items(2) if "pauta" in i.q.lower()])
            await pilot.press("escape")
            self.assertIsNone(app.filt)
            await pilot.press("g")
            await pilot.pause(0.3)
            await pilot.press(*"dicionário")
            await pilot.pause(0.8)
            await pilot.press("enter")
            await pilot.pause(0.3)
            self.assertEqual(len(app.screen_stack), 1)

    # ── escritas pela CLI ──────────────────────────────────────────────────
    async def test_close_action_runs_cli_and_logs_the_command(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            target = app.cur().id
            await pilot.press("c")
            await pilot.pause(0.2)
            await pilot.press("enter")                                # sem "como foi": não deixa passar
            await pilot.pause(0.1)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            await pilot.press(*"enviei", "space", *"ok")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).actions[target].status, "fechada")
            log = self.log_text(app)
            self.assertIn(f"$ brain action close {target} --how", log)
            self.assertIn("brain render", log)

    async def test_new_action_resolves_natural_date(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")
            await pilot.pause(0.2)
            await pilot.press(*"Ligar", "space", *"para", "space", *"Carla")
            await pilot.press("tab", *"+3d")
            await pilot.press("enter")
            await self.settle(app, pilot)
            a = next(x for x in self.state(app).actions.values() if x.title == "Ligar para Carla")
            self.assertEqual(a.due, util.today().replace() + (date(2026, 10, 12) - date(2026, 10, 9)))
            self.assertEqual(a.owner, self.inst.owner_id)

    async def test_invalid_date_blocks_submit(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n", *"x", "tab", *"qualquer", "space", *"dia", "enter")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertIn("não reconhecida", self.text_of(app.screen.query_one("#err")))

    async def test_failed_command_shows_error_and_skips_render(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.exec([["action", "close", "A-9999", "--how", "x", "--by", "owner"]])
            await self.settle(app, pilot)
            log = self.log_text(app)
            self.assertIn("ERRO", log)
            self.assertNotIn("↻ brain render", log)

    async def test_proposal_accept_needs_literal_quote(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4")
            rid = app.cur().id
            await pilot.press("a")
            await pilot.pause(0.2)
            await pilot.press("enter")                                # sem resposta: não aceita
            await pilot.pause(0.1)
            self.assertEqual(self.state(app).proposals[rid].status, "aberta")
            await pilot.press(*"ok")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).proposals[rid].status, "aceita")

    async def test_outbox_approve_then_agent_sends(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "]")
            mid = app.cur().id
            self.assertEqual(app.cur().data["status"], "rascunho")
            await pilot.press("A")
            await pilot.pause(0.2)
            await pilot.press(*"enviar", "space", "1", "enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).messages[mid].status, "aprovada")
            await pilot.press("S")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "AgentModal")
            await pilot.press("enter")
            await self.settle(app, pilot, n=150)
            m = self.state(app).messages[mid]
            self.assertEqual((m.status, m.link), ("enviada", "https://example.com/p/1"))
            self.assertIn("agente de mentira", self.log_text(app))

    async def test_outbox_rejects_recipient_outside_allowlist(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "]", "n")
            await pilot.pause(0.2)
            await pilot.press(*"diego", "tab", *"oi", "enter")
            await pilot.pause(0.2)
            self.assertIn("[outbound].allow", self.text_of(app.screen.query_one("#err")))

    async def test_focus_approve_then_apply_ics(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "]", "]")
            fid = app.store.m["focus"]["id"]
            await pilot.press("A")
            await pilot.pause(0.2)
            await pilot.press(*"ok", "enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).focus_plans[fid].status, "aprovado")
            await pilot.press("a")
            await pilot.pause(0.2)
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).focus_plans[fid].status, "aplicado")
            self.assertTrue((self.inst.fresh / "focus" / f"{fid}.ics").exists())

    async def test_deliverable_toggle_updates_progress(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.jump("P1.2")
            before = app.store.by_project["P1"]["progress"]["pct"]
            await pilot.press("space")
            await pilot.pause(0.2)
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertGreater(app.store.by_project["P1"]["progress"]["pct"], before)
            self.assertIn("$ brain plan deliverable P1.2 --status feito", self.log_text(app))

    async def test_plan_gate_logs_only_with_typed_approval_and_restores_on_cancel(self):
        editor = Path(self.tmp.name) / "editor.py"
        editor.write_text("import sys\nopen(sys.argv[1], 'a').write('\\n## G9 — Meta nova\\n- status: ativo\\n- horizonte: 2027-01-01\\n- por quê: teste\\n')\n", encoding="utf-8")
        os.environ["EDITOR"] = f"{sys.executable} {editor}"
        self.addCleanup(os.environ.pop, "EDITOR", None)
        goals = self.inst.planning_file
        original = goals.read_text(encoding="utf-8")
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3", "E")
            await pilot.pause(0.5)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertIn("G9", goals.read_text(encoding="utf-8"))
            await pilot.press("escape")                               # cancelar desfaz a edição
            await pilot.pause(0.2)
            self.assertEqual(goals.read_text(encoding="utf-8"), original)
            await pilot.press("E")
            await pilot.pause(0.5)
            await pilot.press(*"G9", "space", *"nasce", "tab", *"nova", "space", *"meta", "tab", "tab", *"ok", "enter")
            await self.settle(app, pilot)
            self.assertIn("G9", goals.read_text(encoding="utf-8"))
            changes = self.state(app).plan_changes
            self.assertEqual(changes[-1]["approval"], "ok")

    async def test_sys_validate_and_door_confirmation(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.run_catalog((1, 3, "enter", "sys:validate"))
            await self.settle(app, pilot)
            self.assertIn("$ brain validate", self.log_text(app))
            app.run_catalog((1, 3, "enter", "sys:backup"))
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "ConfirmModal")
            await pilot.press("escape")                               # porta: cancelar não executa nada
            await pilot.pause(0.2)
            self.assertNotIn("$ brain backup", self.log_text(app))

    # ── cobertura de uso: cliques, auto-refresh, estado vazio, saída ───────
    async def test_whole_hint_is_clickable_and_double_click_zooms(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.click("#hints", offset=(3, 0))               # no rótulo, não só na tecla
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            await pilot.press("escape")
            await pilot.click("#globals", offset=(3, 0))
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "TextModal")
            await pilot.press("escape")
            await pilot.double_click("#p2", offset=(6, 2))
            await pilot.pause(0.3)
            self.assertTrue(app.zoom)

    async def test_vault_changed_outside_is_picked_up(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            before = len(app.store.m["actions"])
            r = bridge.run_brain(self.inst, ["action", "open", "Criada fora do TUI", "--by", "owner"])
            self.assertTrue(r.ok, r.err)
            await app._watch()
            self.assertEqual(len(app.store.m["actions"]), before + 1)
            self.assertIn("mudou fora do TUI", self.log_text(app))

    async def test_quit_asks_twice_while_busy(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.busy = "agente…"
            await pilot.press("q")
            await pilot.pause(0.2)
            self.assertTrue(app._quit_armed)
            self.assertTrue(app.is_running)
            self.assertIn("Aperte q de novo", self.log_text(app))
            app.busy = ""

    async def test_theme_toggle(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            before = app.theme
            await pilot.press("ctrl+t")
            self.assertNotEqual(app.theme, before)
            await pilot.press("ctrl+t")
            self.assertEqual(app.theme, before)

    async def test_empty_brain_shows_welcome_and_init(self):
        root = Path(self.tmp.name) / "vazio"
        for d in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH", "vault/reports"):
            (root / d).mkdir(parents=True)
        (root / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
        (root / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
        inst = config.load(root)
        from brainlib.core import Brain
        Brain(inst).record_one({"type": "person.added", "id": "eu", "by": "owner", "data": {"name": "Dona", "relation": "dono"}})
        from brainlib.tui.app import BrainApp
        app = BrainApp(inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.5)
            await pilot.press("1")
            self.assertTrue(app.store.is_empty())
            self.assertIn("Cérebro novo", self.text_of(app.query_one("#detail")))
            self.assertIn("i", {k.k for k in app.ctx_keys()})
            await pilot.press("i")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "AgentModal")

    async def test_every_system_operation_is_valid_cli(self):
        from brainlib import cli
        from brainlib.tui.store import SYS_OPS
        parser = cli.build_parser()
        for op in SYS_OPS:
            if op.get("form"):
                continue
            for args in (op["args"], op.get("apply")):
                if args:
                    parser.parse_args(args)                       # levanta SystemExit se a CLI não conhecer

    async def test_system_output_opens_in_a_modal(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.run_catalog((1, 3, "enter", "sys:doctor"))
            await self.settle_modal(app, pilot, "TextModal")
            self.assertIn("ledger", self.text_of(app.screen.query_one("#mb")))
            await pilot.press("escape")

    async def settle_modal(self, app, pilot, name, n=80):
        for _ in range(n):
            await pilot.pause(0.1)
            if type(app.screen).__name__ == name:
                return
        self.fail(f"o modal {name} não abriu")

    async def test_memory_ask_reports_disabled_engine(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.run_catalog((1, 3, "enter", "sys:recall"))
            await pilot.pause(0.3)
            await self.typ(pilot, "o que foi decidido")
            await pilot.press("enter")
            await self.settle(app, pilot)
            log = self.log_text(app)
            self.assertIn("$ brain memory recall", log)
            self.assertIn("memória desligada", log)
            self.assertNotIn("↻ brain render", log)

    async def test_edit_action_sends_only_what_changed(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            target = app.cur().id
            await pilot.press("e")
            await pilot.pause(0.3)
            spec = app.screen.spec
            cmd = spec.build(app.screen.vals())[0]
            self.assertNotIn("--priority", cmd)                   # nada mudou: nada além de --by
            self.assertEqual(cmd[:3], ["action", "update", target])
            await pilot.press("end")                              # (foco no título) e escreve uma nota
            await pilot.press("tab", "tab", "tab", "tab", "tab", "tab", "tab", "tab", "tab", "tab")
            await self.typ(pilot, "revisada")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertIn("--note revisada", self.log_text(app))

    async def test_new_action_with_people_and_deliverable(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")
            await pilot.pause(0.3)
            await self.typ(pilot, "Alinhar com Bruno")
            for _ in range(7):
                await pilot.press("tab")
            await self.typ(pilot, "P1.2")
            await pilot.press("tab")
            await self.typ(pilot, "bruno")
            await pilot.press("enter")
            await self.settle(app, pilot)
            a = next(x for x in self.state(app).actions.values() if x.title == "Alinhar com Bruno")
            self.assertEqual(a.deliverable, "P1.2")
            self.assertIn("bruno", a.people)

    async def test_status_due_drop_reopen_and_chase(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            target = app.cur().id
            await pilot.press("s")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).actions[target].status, "fazendo")
            await pilot.press("t")
            await pilot.pause(0.2)
            await self.typ(pilot, "+9")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).actions[target].due, util.today() + (date(2026, 10, 18) - date(2026, 10, 9)))
            await pilot.press("D")
            await pilot.pause(0.2)
            await self.typ(pilot, "mudou de ideia")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).actions[target].status, "descartada")
            await pilot.press("a")                                  # mostra todas; a descartada ainda aparece
            app.jump(target)
            await pilot.press("o")
            await pilot.pause(0.2)
            await self.typ(pilot, "voltou")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).actions[target].status, "aberta")
            await pilot.press("]")                                  # waiting → m cobra: abre rascunho já preenchido
            await pilot.press("m")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertTrue(app.screen.vals()["to"])
            await pilot.press("escape")

    async def test_registry_forms_and_share_publish_flow(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("5", "n")                             # decisão
            await pilot.pause(0.3)
            await self.typ(pilot, "Adiar o piloto")
            await pilot.press("tab")
            await self.typ(pilot, "ana")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertTrue(any(d.title == "Adiar o piloto" for d in self.state(app).decisions.values()))
            await pilot.press("]", "n")                             # entrega
            await pilot.pause(0.3)
            await self.typ(pilot, "Painel no ar")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertTrue(any(e.title == "Painel no ar" for e in self.state(app).deliveries.values()))
            await pilot.press("]", "n")                             # pessoa
            await pilot.pause(0.3)
            await self.typ(pilot, "Lia Prado")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertIn("lia-prado", self.state(app).people)
            self.assertEqual(app.cur().id, "lia-prado")            # a nova pessoa já vem selecionada
            await pilot.press("u")                                  # editar pessoa
            await pilot.pause(0.3)
            await pilot.press("tab")
            await self.typ(pilot, "Analista")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).people["lia-prado"].role, "Analista")
            await pilot.press("R")                                  # resolver nome
            await pilot.pause(0.3)
            await self.typ(pilot, "Ana")
            await pilot.press("enter")
            await pilot.pause(1.2)
            self.assertIn("ana", self.log_text(app))
            # exportar status → pedir → aprovar → publicar pelo agente
            await pilot.press("3", "S")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await self.settle(app, pilot)
            await pilot.press("4", "]", "]", "]", "n")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await self.settle(app, pilot)
            sid = app.cur().id
            self.assertEqual(self.state(app).shares[sid].status, "solicitada")
            await pilot.press("A")
            await pilot.pause(0.2)
            await self.typ(pilot, "ok publica")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).shares[sid].status, "aprovada")
            await pilot.press("P")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await self.settle(app, pilot, n=150)
            self.assertEqual(self.state(app).shares[sid].status, "publicada")

    async def test_progress_and_focus_sync(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.jump("G1")
            await pilot.press("P")
            await pilot.pause(0.3)
            await self.typ(pilot, "60")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(app.store.by_goal["G1"]["declared"]["pct"], 60)
            await pilot.press("4", "]", "]", "s")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertIn("brain focus sync --dry-run", self.log_text(app))

    # ── fontes (watch.toml) e /update, /connect ────────────────────────────
    async def test_sources_tab_add_edit_remove(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "]", "]")
            self.assertEqual((app.p, app.tab[1]), (1, 2))
            self.assertEqual([i.id for i in app.items(1)], ["src:slack-dados", "src:gcal-14d"])
            await pilot.press("n")                                  # adicionar
            await pilot.pause(0.3)
            await self.fill(pilot, key="gmail-hoje", kind="gmail", window="1d", other="label=inbox; x=1")
            await pilot.press("enter")
            await self.settle(app, pilot)
            added = next(x for x in watch.list_sources(self.inst) if x["key"] == "gmail-hoje")
            self.assertEqual((added["kind"], added["window"], added["label"], added["x"]), ("gmail", "1d", "inbox", "1"))
            self.assertEqual(app.cur().id, "src:gmail-hoje")            # a nova fonte já vem selecionada
            await pilot.press("e")                                  # editar: janela, renomear, tira um campo
            await pilot.pause(0.3)
            await self.fill(pilot, key="gmail-dia", window="7d", other="label=inbox")
            await pilot.press("enter")
            await self.settle(app, pilot)
            edited = next(x for x in watch.list_sources(self.inst) if x["key"] == "gmail-dia")
            self.assertEqual((edited["window"], "x" in edited, edited["label"]), ("7d", False, "inbox"))
            self.assertNotIn("gmail-hoje", [x["key"] for x in watch.list_sources(self.inst)])
            self.assertIn("$ brain watch edit gmail-hoje --rename gmail-dia", self.log_text(app))
            await pilot.press("x")                                  # remover pede confirmação
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "ConfirmModal")
            await pilot.press("escape")
            self.assertIn("gmail-dia", [x["key"] for x in watch.list_sources(self.inst)])
            await pilot.press("x")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertNotIn("gmail-dia", [x["key"] for x in watch.list_sources(self.inst)])

    async def test_source_form_validation(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "]", "]", "n")
            await pilot.pause(0.3)
            await self.fill(pilot, key="Slack Dados", kind="slack")           # key inválida
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertIn("minúsculas", self.text_of(app.screen.query_one("#err")))
            await self.fill(pilot, key="slack-dados")                         # já existe
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertIn("já existe", self.text_of(app.screen.query_one("#err")))
            await self.fill(pilot, key="nova", other="semigual")
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertIn("campo=valor", self.text_of(app.screen.query_one("#err")))
            self.assertEqual(len(watch.list_sources(self.inst)), 2)

    async def test_adhoc_connector_can_be_included_in_watch(self):
        import subprocess
        env = {**os.environ, "BRAIN_HOME": str(self.root)}
        r = subprocess.run([sys.executable, str(ROOT / "brain"), "snapshot", "--key", "avulsa-1", "--prefix", "nota"],
                           input="olá", capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.jump_source("avulsa-1")
            await pilot.press("1", "]", "]")
            app.jump_source("avulsa-1")
            self.assertFalse(app.cur().data["in_watch"])
            self.assertIn("w", {k.k for k in app.ctx_keys()})
            self.assertNotIn("e", {k.k for k in app.ctx_keys()})              # avulsa não se edita nem remove
            await pilot.press("w")
            await pilot.pause(0.3)
            await self.fill(pilot, kind="gmail")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertIn("avulsa-1", [x["key"] for x in watch.list_sources(self.inst)])

    async def test_update_all_runs_the_agent_with_the_slash_command(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "u")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "AgentModal")
            await pilot.press("enter")
            await self.settle(app, pilot, n=150)
            self.assertIn("agente de mentira recebeu: /update", self.log_text(app))

    async def test_connect_picks_a_source_from_watch(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "c")
            await pilot.pause(0.5)
            self.assertEqual(type(app.screen).__name__, "PickerModal")
            await self.typ(pilot, "slack")
            await pilot.pause(0.6)
            await pilot.press("enter")
            await pilot.pause(0.4)
            self.assertEqual(type(app.screen).__name__, "AgentModal")
            await pilot.press("enter")
            await self.settle(app, pilot, n=150)
            self.assertIn("recebeu: /connect slack-dados", self.log_text(app))

    async def test_update_without_sources_explains_instead_of_asking_the_agent(self):
        for k in ("slack-dados", "gcal-14d"):
            watch.remove(self.inst, k)
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "u")
            await pilot.pause(0.3)
            self.assertEqual(len(app.screen_stack), 1)
            self.assertIn("watch.toml", self.log_text(app))

    async def test_watch_toml_changed_outside_is_picked_up(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            watch.add(self.inst, "jira-me", {"kind": "jira"})
            await app._watch()
            self.assertIn("jira-me", [x["key"] for x in app.store.sources])

    # ── painel 6 (log) e notas ─────────────────────────────────────────────
    async def test_log_is_panel_six_and_expands_when_selected(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            log, detail = app.query_one("#log"), app.query_one("#detailwrap")
            small = log.outer_size.height
            self.assertEqual(small, 10)                                # fechado: o mesmo tamanho de sempre
            await pilot.press("6")
            await pilot.pause(0.2)
            self.assertEqual(app.p, 6)
            self.assertGreater(log.outer_size.height, small)                 # selecionado: expande
            self.assertLess(detail.outer_size.height, 10)
            self.assertTrue(log.has_class("-on"))
            self.assertIn("[6]", str(log.border_title))
            self.assertEqual(app.query_one("#p2").size.height > 3, True)   # a lista da esquerda continua preenchida
            await pilot.press("c")                                     # tecla do contexto do log
            await pilot.pause(0.1)
            self.assertEqual(len(app.query_one("#log").lines), 0)
            await pilot.press("2")
            await pilot.pause(0.2)
            self.assertEqual(log.outer_size.height, small)                   # volta ao tamanho original
            await pilot.click("#log")                                  # clique também seleciona
            self.assertEqual(app.p, 6)

    async def test_note_form_creates_file_in_inbox_linked_and_shows_in_detail(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            aid = app.cur().id
            await pilot.press("N")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            ta = app.screen.query_one("#f_text")
            self.assertEqual(type(ta).__name__, "TextArea")
            self.assertEqual(app.screen.query_one("#f_link").value, aid)       # vem da seleção
            await pilot.press(*"linha", "enter", *"dois")                        # enter quebra a linha, não confirma
            await pilot.pause(0.1)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertEqual(ta.text, "linha\ndois")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
        files = sorted(p.name for p in self.inst.inbox.glob("*-note.md"))
        self.assertEqual(files, [f"{aid}-2026-10-09-note.md"])
        body = (self.inst.inbox / files[0]).read_text(encoding="utf-8")
        self.assertIn(f"vinculo: {aid}", body)
        self.assertIn("criada: 2026-10-09 10:00", body)
        self.assertTrue(body.endswith("linha\ndois\n"))
        app2 = self.app()
        async with app2.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            target = [it.id for it in app2.items(2)]
            app2.set_sel(2, target.index(aid))
            app2.redraw()
            text = self.text_of(app2.query_one("#detail"))
            self.assertIn("2026-10-09 10:00", text)
            self.assertIn("nota: linha", text)                       # linha no histórico, com data e hora
            self.assertLess(text.index("Histórico"), text.index("Notas"))
            self.assertIn("▌ dois", text)

    async def test_note_without_link_and_invalid_link(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3", "N")
            await pilot.pause(0.3)
            app.screen.query_one("#f_text").text = "ideia solta"
            app.screen.query_one("#f_link").value = "A-9999"
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")            # vínculo inexistente barra
            self.assertIn("não encontrada", self.text_of(app.screen.query_one("#err")))
            app.screen.query_one("#f_link").value = ""
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertTrue((self.inst.inbox / "note-2026-10-09-note.md").exists())

    async def test_plan_detail_lists_notes_under_goal_project_and_deliverable(self):
        from brainlib import notes
        from brainlib.core import Brain
        b = Brain(self.inst)
        for link in ("G1", "P1", "P1.1"):
            notes.create(b, f"nota de {link}", link)
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3")
            for it in app.items(3):
                if it.id in ("G1", "P1", "P1.1"):
                    app.set_sel(3, [i.id for i in app.items(3)].index(it.id))
                    app.redraw()
                    self.assertIn(f"▌ nota de {it.id}", self.text_of(app.query_one("#detail")))

    async def test_second_note_same_day_asks_edit_or_new(self):
        from brainlib import notes
        from brainlib.core import Brain
        b = Brain(self.inst)
        notes.create(b, "primeira", "P1")
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3")
            app.set_sel(3, [i.id for i in app.items(3)].index("P1"))
            app.redraw()
            # 1) editar a existente: o texto novo entra no fim e o arquivo é reescrito
            await pilot.press("N")
            await pilot.pause(0.3)
            app.screen.query_one("#f_text").text = "segunda"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "ChoiceModal")
            await pilot.press("e")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertEqual(app.screen.query_one("#f_text").text, "primeira\n\nsegunda")
            app.screen.query_one("#f_text").text = "primeira, revisada\n\nsegunda"
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            files = sorted(p.name for p in self.inst.inbox.glob("*-note*.md"))
            self.assertEqual(files, ["P1-2026-10-09-note.md"])
            body = (self.inst.inbox / files[0]).read_text(encoding="utf-8")
            self.assertIn("primeira, revisada", body)
            self.assertIn("editada: 2026-10-09 10:00", body)
            self.assertIn("criada: 2026-10-09 10:00", body)
            # 2) criar nova: vira -note-2
            await pilot.press("N")
            await pilot.pause(0.3)
            app.screen.query_one("#f_text").text = "outra coisa"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            await pilot.press("n")
            await self.settle(app, pilot)
            self.assertEqual(sorted(p.name for p in self.inst.inbox.glob("*-note*.md")),
                             ["P1-2026-10-09-note-2.md", "P1-2026-10-09-note.md"])
            # 3) esc volta ao formulário com o que foi digitado
            await pilot.press("N")
            await pilot.pause(0.3)
            app.screen.query_one("#f_text").text = "rascunho"
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            await pilot.press("escape")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertEqual(app.screen.query_one("#f_text").text, "rascunho")

    async def test_archived_note_is_not_offered_for_edit(self):
        from brainlib import notes
        from brainlib.core import Brain
        b = Brain(self.inst)
        src = notes.create(b, "já arquivada", "P1")
        dest = self.inst.vault / "RAW" / "2026" / "10"
        dest.mkdir(parents=True, exist_ok=True)
        src.rename(dest / src.name)
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3", "N")
            await pilot.pause(0.3)
            app.screen.query_one("#f_text").text = "nova"
            app.screen.query_one("#f_link").value = "P1"
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)                      # sem pergunta: RAW é imutável
        self.assertTrue((self.inst.inbox / "P1-2026-10-09-note-2.md").exists())

    async def test_note_text_can_be_edited_in_the_external_editor(self):
        editor = Path(self.tmp.name) / "fake_editor.py"
        editor.write_text("import sys\np = sys.argv[1]\nt = open(p, encoding='utf-8').read()\n"
                          "open(p, 'w', encoding='utf-8').write('# Título\\n\\n- item\\n' + t)\n", encoding="utf-8")
        os.environ["EDITOR"] = f"{sys.executable} {editor}"
        self.addCleanup(os.environ.pop, "EDITOR", None)
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("N")
            await pilot.pause(0.3)
            ta = app.screen.query_one("#f_text")
            ta.text = "corpo"
            await pilot.press("ctrl+o")
            await pilot.pause(0.5)
            self.assertEqual(ta.text, "# Título\n\n- item\ncorpo")

    # ── painel 3: n contextual e novo goal ─────────────────────────────────
    def _select3(self, app, node):
        app.p = 3
        app.set_sel(3, [i.id for i in app.items(3)].index(node))
        app.redraw()

    async def test_plan_n_is_contextual_goal_project_deliverable(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            label = lambda: next(k.label for k in app.ctx_keys() if k.k == "n")  # noqa: E731
            self._select3(app, "G1")
            self.assertEqual(label(), "novo projeto")
            self._select3(app, "P1")
            self.assertEqual(label(), "novo entregável")
            self._select3(app, "P1.1")
            self.assertEqual(label(), "nova ação")
            self.assertIn("G", {k.k for k in app.ctx_keys()})
            # goal → projeto (gate: exige a aprovação digitada)
            self._select3(app, "G1")
            await pilot.press("n")
            await pilot.pause(0.3)
            self.assertIn("Novo projeto", self.text_of(app.screen.query_one("#mt")))
            await self.fill(pilot, title="Projeto criado na TUI", owner="", reason="")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")          # sem aprovação não passa
            await self.fill(pilot, quote="ok")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            plan = app.store.brain.plan
            pid = next(p.id for p in plan.projects.values() if p.title == "Projeto criado na TUI")
            self.assertEqual(plan.projects[pid].goal_id, "G1")
            self.assertEqual((app.p, app.cur().id), (3, pid))                  # a seleção vai para o novo projeto
            self.assertIn("plan.changed", [e["type"] for e in app.store.brain.read_events()])
            self.assertIn("$ brain plan add-project G1", self.log_text(app))
            # projeto → entregável (sem gate)
            await pilot.press("n")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Entregável da TUI", due="2026-12-01", weight="2")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            d = app.store.brain.plan.deliverables[f"{pid}.1"]
            self.assertEqual((d.title, d.due, d.weight), ("Entregável da TUI", date(2026, 12, 1), 2))
            # entregável → ação ligada
            await pilot.press("n")
            await pilot.pause(0.3)
            self.assertEqual(app.screen.query_one("#f_deliv").value, f"{pid}.1")
            self.assertEqual(app.screen.query_one("#f_project").value, pid)
            await self.fill(pilot, title="Tarefa do entregável")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            a = next(x for x in self.state(app).actions.values() if x.title == "Tarefa do entregável")
            self.assertEqual((a.deliverable, a.project), (f"{pid}.1", pid))

    async def test_plan_new_goal_with_G_needs_approval(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3")
            await pilot.press("G")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Goal novo", horizon="2027-06-30", why="destrava tudo", quote="")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            await self.fill(pilot, quote="ok")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            g = next(g for g in app.store.brain.plan.goals.values() if g.title == "Goal novo")
            self.assertEqual((g.horizon, g.why), ("2027-06-30", "destrava tudo"))
            self.assertEqual(app.cur().id, g.id)
            self.assertIn(g.id, (self.inst.planning_log).read_text(encoding="utf-8"))

    # ── decisões no detalhe do plano e filtro por associação ───────────────
    async def test_plan_detail_shows_decisions_of_goal_project_and_deliverable(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            st = app.store
            pid = next(p for p in st.by_project if st.decisions_of(p))
            deliv = st.by_project[pid]["deliverables"][0]["id"]
            goal = st.by_project[pid]["goal"]
            ids = [d["id"] for d in st.decisions_of(pid)]
            for node in (pid, deliv, goal):
                self._select3(app, node)
                text = self.text_of(app.query_one("#detail"))
                self.assertIn("Decisões", text)
                for did in ids:
                    self.assertIn(did, text)
            self._select3(app, deliv)
            self.assertIn("Decisões do projeto", self.text_of(app.query_one("#detail")))

    async def test_filter_by_id_shows_everything_associated(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            st = app.store
            pid = next(p for p in st.by_project if st.decisions_of(p))
            goal = st.by_project[pid]["goal"]
            deliv_ids = {d["id"] for d in st.by_project[pid]["deliverables"]}

            def shown(panel, tab, text):
                app.filt = (panel, tab, text)
                app._items = {}
                app.tab[panel] = tab
                return {i.id for i in app.items(panel)}

            # plano: o projeto, o goal acima e os entregáveis abaixo — mesmo com o goal recolhido
            app.collapsed.add(goal)
            self.assertEqual(shown(3, 0, pid), {pid, goal} | deliv_ids)
            # decisões do projeto e só elas
            self.assertEqual(shown(5, 0, pid), {d["id"] for d in st.decisions_of(pid)})
            # ações: as do projeto ou dos seus entregáveis (inclusive fechadas, em todas as listas)
            want = {a["id"] for a in st.m["actions"] if a["project"] == pid or a["deliverable"] in deliv_ids}
            got = set()
            for t in (0, 1, 2):
                app.show_all = True
                got |= shown(2, t, pid)
            self.assertEqual(got, want)
            # de uma ação para cima: seu entregável, projeto e goal aparecem no plano
            a = next(a for a in st.m["actions"] if a["deliverable"])
            self.assertEqual(shown(3, 0, a["id"]), {a["deliverable"], a["project"] or st.by_deliv[a["deliverable"]][0]["id"],
                                                       st.by_project[st.by_deliv[a["deliverable"]][0]["id"]]["goal"]})
            # P1 não pega P10: filtro por id é exato; texto livre continua sendo substring
            self.assertNotIn("P10", shown(3, 0, "P1"))
            app.filt = None

    async def test_deliverable_by_number_inside_the_project(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            st = app.store
            a = next(a for a in st.m["actions"] if a["open"] and a["mine"] and a["list"] == "mine" and a["deliverable"])
            proj = a["deliverable"].split(".")[0]
            others = [d["id"].split(".")[1] for d in st.by_project[proj]["deliverables"] if d["id"] != a["deliverable"]]
            self.assertTrue(others)
            n = others[0]
            app.set_sel(2, [i.id for i in app.items(2)].index(a["id"]))
            app.redraw()
            await pilot.press("e")
            await pilot.pause(0.3)
            f = app.screen.query_one("#f_deliv")
            self.assertEqual(f.value, a["deliverable"].split(".")[1])         # P1.2 aparece só como 2
            await self.fill(pilot, deliv="99")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertIn("não existe", self.text_of(app.screen.query_one("#err")))
            await self.fill(pilot, deliv=n)
            self.assertIn(f"→ {proj}.{n}", self.text_of(app.screen.query_one("#r_deliv")))
            self.assertIn(f"--deliverable {proj}.{n}", self.text_of(app.screen.query_one("#cmdp")))
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(self.state(app).actions[a["id"]].deliverable, f"{proj}.{n}")
            # ação nova: o número vale para o projeto escolhido no formulário
            await pilot.press("n")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Com número", deliv="1")
            await pilot.press("ctrl+s")                                        # sem projeto, só o número não resolve
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertIn("escolha o projeto", self.text_of(app.screen.query_one("#err")))
            app.screen.query_one("#f_project").value = proj
            await pilot.pause(0.2)
            self.assertIn(f"--deliverable {proj}.1", self.text_of(app.screen.query_one("#cmdp")))
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            b = next(x for x in self.state(app).actions.values() if x.title == "Com número")
            self.assertEqual(b.deliverable, f"{proj}.1")


class CoverageTest(unittest.TestCase):
    """Todo subcomando da CLI tem tecla no TUI ou uma razão explícita para não ter."""
    READ_ONLY_VIEWS = {   # a leitura já está num painel (modelo em processo), sem precisar chamar a CLI
        "person list", "action show", "action list", "decision list", "plan show", "focus show", "outbox show",
        "outbox list", "proposal list", "publish list", "doctor", "search", "status", "artifact", "watch list", "watch since",
        "note list"}
    AGENT_ONLY = {        # quem escreve é o agente (extração, snapshot, envio), conforme a Constituição
        "init", "add", "snapshot", "extract", "proposal add", "outbox sent", "outbox failed", "publish done"}
    NOT_IN_TUI = {"demo", "tui"}
    DYNAMIC = {"memory recall", "memory reflect"}      # o formulário "Memória: perguntar" monta o subcomando

    def test_every_cli_subcommand_is_accounted_for(self):
        import re
        from brainlib import cli
        src = "".join((ROOT / "brainlib" / "tui" / f).read_text(encoding="utf-8") for f in ("app.py", "store.py"))
        sub = next(a for a in cli.build_parser()._actions if a.__class__.__name__ == "_SubParsersAction")
        uncovered = []
        for name, p in sub.choices.items():
            inner = [a for a in p._actions if a.__class__.__name__ == "_SubParsersAction"]
            for sc in (inner[0].choices if inner else [None]):
                label = f"{name} {sc}" if sc else name
                pat = re.compile(r'\[\s*"%s"\s*,\s*"%s"' % (name, sc)) if sc else re.compile(r'\[\s*"%s"\s*[,\]]' % name)
                if pat.search(src) or label in self.READ_ONLY_VIEWS | self.AGENT_ONLY | self.NOT_IN_TUI | self.DYNAMIC:
                    continue
                uncovered.append(label)
        self.assertEqual(uncovered, [], "subcomandos sem lugar no TUI (e sem justificativa em CoverageTest)")


class CliTest(unittest.TestCase):
    def test_tui_refuses_nightly_mode(self):
        import subprocess
        env = {**os.environ, "BRAIN_NIGHTLY": "1", "BRAIN_TUI_REEXEC": "1"}
        r = subprocess.run([sys.executable, str(ROOT / "brain"), "tui"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 4)
        self.assertIn("noturno", r.stderr)

    def test_tui_without_textual_points_to_setup(self):
        if HAVE_TEXTUAL:
            self.skipTest("textual instalado neste interpretador")
        import subprocess
        env = {**os.environ, "BRAIN_TUI_REEXEC": "1"}
        r = subprocess.run([sys.executable, str(ROOT / "brain"), "tui"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 3)
        self.assertIn("--setup", r.stderr)


if __name__ == "__main__":
    unittest.main()
