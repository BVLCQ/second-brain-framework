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

from brainlib import config, demo as demo_mod, planning, util, watch
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


class ActionViewTest(unittest.TestCase):
    TODAY = date(2026, 10, 14)   # quarta; a semana vai até domingo 18/10

    def bucket(self, **kw):
        from brainlib.tui.store import action_view
        a = {"open": True, "parked": False, "due": None, "status": "aberta"} | kw
        return action_view(a, self.TODAY)

    def test_buckets(self):
        self.assertEqual(self.bucket(due="2026-10-01"), 1)                   # atrasada fica em "esta semana"
        self.assertEqual(self.bucket(due="2026-10-18"), 1)                   # domingo ainda é a semana
        self.assertEqual(self.bucket(due="2026-10-19"), 2)                   # segunda: semana que vem
        self.assertEqual(self.bucket(), 2)                                   # sem prazo: depois
        self.assertEqual(self.bucket(status="fazendo"), 1)                   # sem prazo mas em andamento: agora
        self.assertEqual(self.bucket(parked=True, due="2026-10-01"), 3)      # adiada de propósito vence o atraso
        self.assertEqual(self.bucket(open=False, due="2026-10-15"), 0)       # fechada só em "Todas"


class BridgeTest(unittest.TestCase):
    def test_display_quotes_arguments(self):
        self.assertEqual(bridge.display(["action", "close", "TASK-0001", "--how", "enviei o draft"]),
                         "brain action close TASK-0001 --how 'enviei o draft'")

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


class AgentRunTest(unittest.TestCase):
    """Passo 2 de agent-questions: rodada com sessão, saída stream-json e resume."""
    CFG = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "agent": "claude", "allow": ["mcp__x__ler"]},
                             "tui": {"agent_allow": ["mcp__x__enviar"]}}

    def argv(self, **kw):
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            return bridge.agent_argv(self.CFG, "/dump", **kw)

    def test_claude_runs_stream_json_with_run_id_in_the_prompt(self):
        argv = self.argv(run_id="run-20261022-100000")
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", argv)
        self.assertLess(argv.index("--verbose"), argv.index("--allowedTools"))
        self.assertIn("run-20261022-100000", argv[2])
        self.assertIn("./brain ask add", argv[2])
        self.assertTrue(argv[2].endswith("/dump"))
        self.assertEqual(argv[-2:], ["mcp__x__ler", "mcp__x__enviar"])

    def test_resume_argv_keeps_flags_and_adds_the_new_allow(self):
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            argv = bridge.resume_argv(self.CFG, "sess-123", "O dono respondeu: ASK-0001 = marina-demo", ["Bash(./brain ask:*)"], "run-2")
            self.assertEqual(argv[:5], ["claude", "-p", argv[2], "--resume", "sess-123"])
            self.assertIn("O dono respondeu", argv[2])
            self.assertIn("stream-json", argv)
            self.assertEqual(argv[-1], "Bash(./brain ask:*)")
            self.assertIsNone(bridge.resume_argv(self.CFG, "", "x"))                       # sem sessão
            codex = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "agent": "codex"}}
            self.assertIsNone(bridge.resume_argv(codex, "sess-123", "x"))                   # agente sem resume conhecido
            custom = config.DEFAULTS | {"runner": {**config.DEFAULTS["runner"], "command": "meu-agente {prompt}"}}
            self.assertIsNone(bridge.resume_argv(custom, "sess-123", "x"))

    def test_stream_parser_text_session_result_and_denials(self):
        import json
        info = bridge.RunInfo(id="run-1")
        p = bridge.StreamParser(info)
        lines = [
            {"type": "system", "subtype": "init", "session_id": "sess-9"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Lendo a inbox.\nAchei 2 itens."},
                                                           {"type": "tool_use", "name": "Bash", "input": {"command": "./brain status"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "Pronto.", "session_id": "sess-9",
             "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "./brain add <<'JSON'"}, "tool_use_id": "t1"},
                                    {"tool_name": "mcp__x__enviar", "tool_input": {"to": "a"}}]},
        ]
        out = [x for ln in lines for x in p.feed(json.dumps(ln))]
        self.assertEqual(out, ["Lendo a inbox.", "Achei 2 itens."])
        self.assertEqual((info.session_id, info.result, info.structured), ("sess-9", "Pronto.", True))
        self.assertEqual(info.denials, [{"tool_name": "Bash", "tool_input": {"command": "./brain add <<'JSON'"}},
                                        {"tool_name": "mcp__x__enviar", "tool_input": {"to": "a"}}])
        # linha que não é JSON (outros agentes) vai como texto; JSON quebrado também
        q = bridge.StreamParser(bridge.RunInfo())
        self.assertEqual(q.feed("texto simples"), ["texto simples"])
        self.assertEqual(q.feed("{quebrado"), ["{quebrado"])
        self.assertEqual(q.feed(""), [])
        self.assertFalse(q.info.structured)
        err = bridge.StreamParser(bridge.RunInfo())
        self.assertEqual(err.feed(json.dumps({"type": "result", "is_error": True, "result": "sessão expirada"})), ["erro do agente: sessão expirada"])

    def test_record_run_writes_argv_without_the_prompt(self):
        import json
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp) / "inst"
            demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
            inst = config.load(root)
            from brainlib import ask
            from brainlib.core import Brain
            ask.add(Brain(inst), "Qual Marina?", [], [], source="chat", run="run-7")
            info = bridge.RunInfo(id="run-7", session_id="sess-1", rc=0, denials=[{"tool_name": "Bash", "tool_input": {}}])
            bridge.record_run(inst, info, ["claude", "-p", "um prompt grande", "--resume", "sess-0"], "um prompt grande")
            row = json.loads((inst.logs / "agent-runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(row["argv"], ["claude", "-p", "<prompt>", "--resume", "sess-0"])
            self.assertEqual((row["id"], row["session_id"], row["asks"], len(row["denials"])), ("run-7", "sess-1", ["ASK-0001"], 1))


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class DetailTest(unittest.TestCase):
    def test_suggested_due_is_purple_until_owner_decides(self):
        from brainlib.tui import rows
        base = {"open": True, "due": "2026-10-20", "due_in": 3, "overdue_days": 0, "closed": None}
        plain, sug = rows.due_tag(base), rows.due_tag({**base, "due_suggested": True})
        self.assertEqual(plain.plain, sug.plain)
        self.assertTrue(all(str(sp.style).endswith(rows.PUR) for sp in sug.spans))
        self.assertFalse(any(rows.PUR in str(sp.style) for sp in plain.spans))
        late = rows.due_tag({**base, "due_in": -2, "overdue_days": 2, "due_suggested": True})
        self.assertTrue(all(rows.PUR in str(sp.style) for sp in late.spans))

    def test_every_action_detail_renders(self):
        """Regressão: ação que destrava outra (campo 'destrava') quebrava a ficha com ValueError do rich."""
        from brainlib.tui import rows, store
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp) / "inst"
            demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
            st = store.Store(config.load(root))
            self.assertTrue(any(a["unblocks"] for a in st.m["actions"]))
            for a in st.m["actions"]:
                rows.d_action(st, store.Item(a["id"], "action", a))

    def test_linked_files_section_and_opener(self):
        """Detalhe lista os arquivos ligados (nota, artefato, RAW), clicáveis; o app vem de [tui.open], senão o padrão do sistema."""
        from brainlib import opener
        from brainlib.tui import rows, store
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp) / "inst"
            demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
            inst = config.load(root)
            inst.cfg["tui"]["open"] = {"md": "Cursor", "mp4": "VLC"}
            note = inst.vault / "RAW" / "2026" / "10" / "notes" / "TASK-0001-2026-10-21-note.md"
            note.parent.mkdir(parents=True)
            note.write_text("---\ntipo: nota\nvinculo: TASK-0001\ncriada: 2026-10-21 09:00\n---\ntexto\n", encoding="utf-8")
            st = store.Store(inst)
            rel = inst.rel(note)
            a = next(a for a in st.m["actions"] if a["id"] == "TASK-0001")
            files = st.linked_files(a["id"], (a["source"],))
            self.assertIn(rel, [f["rel"] for f in files])
            self.assertEqual(len({f["rel"] for f in files}), len(files))      # sem repetidos
            doc = rows.d_action(st, store.Item(a["id"], "action", a)).text()
            self.assertIn("Arquivos linkados", doc.plain)
            clicks = [sp.style.meta["@click"] for sp in doc.spans if getattr(sp.style, "meta", None) and "open_file" in sp.style.meta.get("@click", "")]
            self.assertIn(f"app.open_file({rel!r})", clicks)
            # app por extensão; sem mapa = padrão do sistema; fora do vault é recusado
            self.assertEqual(opener.argv_for(inst.cfg, Path("/v/a.md"), "darwin"), ["open", "-a", "Cursor", "/v/a.md"])
            self.assertEqual(opener.argv_for(inst.cfg, Path("/v/a.MP4"), "darwin"), ["open", "-a", "VLC", "/v/a.MP4"])
            self.assertEqual(opener.argv_for(inst.cfg, Path("/v/a.pdf"), "darwin"), ["open", "/v/a.pdf"])
            self.assertEqual(opener.argv_for(inst.cfg, Path("/v/a.pdf"), "linux"), ["xdg-open", "/v/a.pdf"])
            for bad in ("../config/brain.toml", "/etc/hosts", "RAW/nao-existe.md"):
                with self.assertRaises(util.BrainError):
                    opener.resolve(inst, bad)

    def test_linked_ids_carry_their_title(self):
        """Na Detalhe, TASK/GOAL/PROJ/entregável vinculados trazem o título, não só o ID."""
        from brainlib.tui import rows, store
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp) / "inst"
            demo_mod.cli(argparse.Namespace(dir=str(root), open=False))
            st = store.Store(config.load(root))
            a, g, p = st.m["actions"][0], st.m["goals"][0], st.m["projects"][0]
            d = next(d for pr in st.m["projects"] for d in pr["deliverables"])
            for ref, title in ((a["id"], a["title"]), (g["id"], g["title"]), (p["id"], p["title"]), (d["id"], d["title"])):
                self.assertEqual(rows.titled(st, ref).plain, f"{ref} {title}")
            self.assertEqual(rows.titled(st, "2025-01-01:2025-03-31").plain, "2025-01-01:2025-03-31")

            class Prop:
                id, kind, status, summary, evidence, into = "PROP-0001", "unificar-acao", "aberta", "x", "e", g["id"]
                target = a["id"]
            plain = rows.d_prop(st, store.Item("PROP-0001", "prop", Prop)).text().plain
            self.assertIn(f"{a['id']} {a['title']}", plain)
            self.assertIn(f"{g['id']} {g['title']}", plain)


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
            "prompt = sys.argv[1]\nprint('agente de mentira recebeu:', prompt.rsplit('. ', 1)[-1][:60])\n"
            "m = re.search(r'MSG-\\d{4}', prompt)\n"
            "if m:\n    subprocess.run([sys.executable, os.environ['FAKE_BRAIN'], 'outbox', 'sent', m.group(0), '--link', 'https://example.com/p/1'], check=True)\n"
            "m = re.search(r'PUB-\\d{4}', prompt)\n"
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

    async def settle_new_action(self, app, pilot) -> None:
        """Ação criada sem prazo: o agente oferece sugerir um (modal ⚡). Aqui só dispensa; o teste dele é à parte."""
        for _ in range(80):
            await pilot.pause(0.1)
            if type(app.screen).__name__ == "AgentModal":
                self.assertIn("Sugerir prazo", app.screen.title_)
                await pilot.press("escape")
                break
        await self.settle(app, pilot)

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
            # painéis só mudam pelos números; setas (e h l) trocam de aba como [ ]; Tab gira as faces (ida e volta)
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

    # ── face Portfólio ─────────────────────────────────────────────────────
    def seed_portfolio(self) -> dict:
        """Áreas, processos e oportunidades genéricos no ledger do demo; devolve os ids criados."""
        from brainlib.core import Brain
        b = Brain(self.inst)
        owner = b.owner
        for slug, name in (("operacoes", "Operações"), ("growth", "Growth"), ("vazia", "Área vazia")):
            b.record_one({"type": "area.added", "id": slug, "by": "owner", "data": {"name": name}})
        p1 = b.record_one({"type": "process.added", "by": "owner", "data": {
            "title": "Fechamento mensal", "area": "operacoes", "owner": owner, "executors": [owner],
            "recurrence": "mensal", "duration": "2h", "pains": ["retrabalho"]}})["id"]
        p2 = b.record_one({"type": "process.added", "by": "owner", "data": {"title": "Relatório semanal", "area": "growth"}})["id"]
        b.record_one({"type": "doc.linked", "by": "owner", "data": {
            "target": p1, "kind": "playbook", "ref": "https://example.com/playbook", "title": "Playbook do fechamento"}})

        def opp(title, area, ice=None, status=None, suggested=False, **data):
            oid = b.record_one({"type": "opportunity.added", "by": "owner", "data": {"title": title, "area": area, **data}})["id"]
            if ice:
                b.record_one({"type": "opportunity.scored", "id": oid, "by": "agent" if suggested else "owner", "prov": "observado",
                              "data": {**dict(zip(("impact", "confidence", "ease"), ice)), **({"ice_suggested": True, "reason": "parece simples"} if suggested else {})}})
            if status:
                b.record_one({"type": "opportunity.status", "id": oid, "by": "owner", "data": {"status": status, "reason": "x"}})
            return oid
        ids = {"p1": p1, "p2": p2,
               "rapido": opp("Automatizar conciliação", "operacoes", (5, 4, 4), "priorizada", process=p1, hours_saved=8, problem="conciliação manual demora"),
               "aposta": opp("Plataforma de dados", "growth", (5, 3, 1), "triagem"),
               "sugerida": opp("Alerta de metas", "growth", (4, 3, 4), None, suggested=True),
               "semice": opp("Revisar templates", "growth"),
               "arquivo": opp("Ideia antiga", "operacoes", (1, 1, 1), "descartada"),
               "prior": opp("Revisão de SLAs", "operacoes", (3, 3, 3), "priorizada")}
        b.record_one({"type": "opportunity.promoted", "id": ids["rapido"], "by": "owner", "data": {"project": "PROJ-1", "goal": "GOAL-1"}})
        b.record_one({"type": "opportunity.status", "id": ids["rapido"], "by": "owner", "data": {"status": "em-andamento", "reason": "promovida"}})
        return ids

    async def test_portfolio_tabs_render_with_data(self):
        from brainlib.tui import rows
        ids = self.seed_portfolio()
        app = self.app()
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("tab")
            seen = 0
            for panel, name in ((1, "Visão"), (2, "Processos"), (3, "Oportunidades"), (4, "Matriz"), (5, "Registro")):
                for tab in range(len(app.panels[panel][1])):
                    await pilot.press(str(panel))
                    app.tab[panel] = tab
                    app.redraw()
                    its = app.items(panel)
                    self.assertTrue(its, f"{name} aba {tab} vazia")
                    for it in its:
                        self.assertTrue(rows.row(app.store, it, 80).plain)
                        self.assertTrue(rows.detail(app.store, it).plain)
                        seen += 1
            self.assertGreater(seen, 30)
            # abas de Oportunidades pelo status
            def has(panel, tab, *want, none=()):
                app.tab[panel] = tab
                got = {i.id for i in app.items(panel)}
                self.assertTrue(set(want) <= got, (panel, tab, want, got))
                self.assertFalse(set(none) & got)
            has(3, 0, ids["aposta"], ids["sugerida"], ids["semice"], none=[ids["rapido"], ids["arquivo"]])   # triagem = ideia + triagem
            has(3, 1, ids["prior"], none=[ids["aposta"]])
            has(3, 2, ids["rapido"], none=[ids["aposta"]])             # em curso = promovida
            has(3, 3, ids["arquivo"], none=[ids["rapido"]])
            has(2, 2, ids["p2"], none=[ids["p1"]])                     # lacunas: só o processo incompleto
            app.tab[4] = 1                                            # ranking: sem a descartada, maior ICE primeiro
            self.assertEqual([i.id for i in app.items(4)][0], ids["rapido"])
            self.assertNotIn(ids["arquivo"], [i.id for i in app.items(4)])
            app.tab[1] = 1                                            # Por área: cabeçalhos + oportunidades
            self.assertEqual([i.kind for i in app.items(1)][:1], ["pgrp"])
            app.filt = (1, 1, "plataforma")
            app._items = {}
            self.assertEqual([i.kind for i in app.items(1)], ["opp"])    # filtro tira os cabeçalhos

    async def test_portfolio_row_shows_pink_score_when_suggested(self):
        from brainlib.tui import rows
        ids = self.seed_portfolio()
        app = self.app()
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            by_id = {i.id: i for i in app.store.items(1, 3, 0)}
            sug = rows.row(app.store, by_id[ids["sugerida"]], 100)
            self.assertTrue(any(rows.PNK in str(sp.style) for sp in sug.spans))
            firm = rows.row(app.store, by_id[ids["aposta"]], 100)
            self.assertFalse(any(rows.PNK in str(sp.style) for sp in firm.spans))

    async def test_jump_to_opportunity_and_process_switches_face_and_tab(self):
        ids = self.seed_portfolio()
        app = self.app()
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            app.jump(ids["rapido"])
            self.assertEqual((app.face, app.p, app.tab[3], app.cur().id), (1, 3, 2, ids["rapido"]))
            app.jump(ids["p2"])
            self.assertEqual((app.face, app.p, app.cur().id), (1, 2, ids["p2"]))
            app.jump("PROJ-1")                                           # plano é da Execução
            self.assertEqual((app.face, app.p), (0, 3))

    async def test_portfolio_keys_build_the_right_commands(self):
        ids = self.seed_portfolio()
        app = self.app()
        got: list = []
        app.exec = lambda cmds, **kw: got.append((cmds, kw))
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("tab", "3")                            # Oportunidades › Triagem
            app.tab[3] = 0
            app.set_sel(3, [i.id for i in app.items(3)].index(ids["sugerida"]))
            app.redraw()
            keys = {k.k for k in app.ctx_keys()}
            self.assertEqual({"n", "e", "s", "i", "c", "l", "v", "O", "p", "x"}, keys)
            # c: confirmar ICE sugerido → o mesmo ICE, agora do dono
            await pilot.press("c")
            self.assertEqual(got[-1][0], [["opportunity", "score", ids["sugerida"], "--impact", "4", "--confidence", "3", "--ease", "4", "--by", "owner"]])
            # s: status por picker; lateral pede motivo
            await pilot.press("s")
            await pilot.pause(0.3)
            await self.typ(pilot, "triagem")
            await pilot.pause(0.4)
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertEqual(got[-1][0], [["opportunity", "status", ids["sugerida"], "triagem", "--by", "owner"]])
            await pilot.press("s")
            await pilot.pause(0.3)
            await self.typ(pilot, "descartada")
            await pilot.pause(0.4)
            await pilot.press("enter")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            await self.fill(pilot, reason="duplicada")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(got[-1][0], [["opportunity", "status", ids["sugerida"], "descartada", "--reason", "duplicada", "--by", "owner"]])
            # i: ICE
            await pilot.press("i")
            await pilot.pause(0.3)
            await self.fill(pilot, impact="9")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertIn("1 a 5", self.text_of(app.screen.query_one("#err")))
            await self.fill(pilot, impact="2", confidence="3", ease="4")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(got[-1][0], [["opportunity", "score", ids["sugerida"], "--impact", "2", "--confidence", "3", "--ease", "4", "--by", "owner"]])
            self.assertEqual(got[-1][1]["show"], "ICE gravado")
            # v: evidência · l: documento (vigiar pede Drive)
            await pilot.press("v")
            await pilot.pause(0.3)
            await self.fill(pilot, source="PROCESSED/2026/10/reuniao.md")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(got[-1][0], [["opportunity", "evidence", ids["sugerida"], "--source", "PROCESSED/2026/10/reuniao.md", "--by", "owner"]])
            await pilot.press("l")
            await pilot.pause(0.3)
            await self.fill(pilot, ref="https://example.com/x", watch="sim")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")             # sim sem playbook do Drive: erro
            await self.fill(pilot, kind="playbook", ref="1AbCdEfGhIjKlMnOpQrS")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(got[-1][0], [["doc", "link", ids["sugerida"], "--kind", "playbook", "--ref", "1AbCdEfGhIjKlMnOpQrS", "--by", "owner", "--watch"]])

    async def test_new_opportunity_warns_about_duplicates_before_writing(self):
        ids = self.seed_portfolio()
        app = self.app()
        got: list = []
        app.exec = lambda cmds, **kw: got.append(cmds)
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("tab", "3", "n")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Automatizar a conciliação", problem="conciliação manual demora", area="operacoes")
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "ConfirmModal")
            self.assertIn(ids["rapido"], app.screen.body)
            await pilot.press("escape")
            await pilot.pause(0.2)
            self.assertEqual(got, [])                                            # nada gravado
            await pilot.press("n")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Algo totalmente novo", problem="outro assunto", area="growth", hours="12")
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            self.assertEqual(got[-1], [["opportunity", "add", "Algo totalmente novo", "--by", "owner", "--area", "growth",
                                        "--kind", "melhoria-de-processo", "--problem", "outro assunto", "--hours-saved", "12.0"]])

    async def test_portfolio_o_opens_opportunity_map(self):
        """Face Portfólio: `o` na Visão e na Matriz abre o mapa HTML (o mesmo gesto do painel da face Execução)."""
        self.seed_portfolio()
        app = self.app()
        got: list = []
        app.exec = lambda cmds, **kw: got.append(cmds)
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            for panel in ("1", "4"):
                await pilot.press("tab", panel)
                await pilot.press("o")
                await pilot.pause(0.1)
                self.assertEqual(got[-1], [["render", "--open", "portfolio"]])
                await pilot.press("tab")                                         # volta à face Execução

    async def test_process_keys_and_open_playbook(self):
        ids = self.seed_portfolio()
        app = self.app()
        got: list = []
        opened: list = []
        app.exec = lambda cmds, **kw: got.append(cmds)
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("tab", "2")
            app.set_sel(2, [i.id for i in app.items(2)].index(ids["p1"]))
            app.redraw()
            self.assertEqual({k.k for k in app.ctx_keys()}, {"n", "e", "l", "o", "a", "x"})
            with mock.patch("webbrowser.open", side_effect=opened.append):
                await pilot.press("o")
            self.assertEqual(opened, ["https://example.com/playbook"])
            await pilot.press("x")
            await pilot.pause(0.3)
            await self.fill(pilot, reason="acabou")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(got[-1], [["process", "retire", ids["p1"], "--reason", "acabou", "--by", "owner"]])
            await pilot.press("a")                                               # nova OPP a partir do processo
            await pilot.pause(0.3)
            self.assertEqual(app.screen.query_one("#f_process").value, ids["p1"])
            self.assertEqual(app.screen.query_one("#f_area").value, "operacoes")
            await pilot.press("escape")
            await pilot.pause(0.2)
            await pilot.press("e")
            await pilot.pause(0.3)
            await self.fill(pilot, owner="", tools="Sheets, Jira", per_month="")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(got[-1], [["process", "update", ids["p1"], "--by", "owner", "--tools", "Sheets, Jira"]])

    async def test_areas_and_documents_tabs_have_their_keys(self):
        ids = self.seed_portfolio()
        app = self.app()
        got: list = []
        app.exec = lambda cmds, **kw: got.append(cmds)
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("tab", "5", "n")
            await pilot.pause(0.3)
            await self.fill(pilot, slug="Ops Ruim")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")             # slug inválido
            await self.fill(pilot, slug="suporte", name="Suporte", alias="CS, Atendimento")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(got[-1], [["area", "add", "suporte", "--by", "owner", "--name", "Suporte", "--alias", "CS, Atendimento"]])
            await pilot.press("]")
            app.set_sel(5, [i.id for i in app.items(5)].index(f"{ids['p1']}#0"))
            app.redraw()
            keys = {k.k for k in app.ctx_keys()}
            self.assertEqual(keys, {"enter", "u"})
            await pilot.press("u")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "ConfirmModal")
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertEqual(got[-1], [["doc", "unlink", ids["p1"], "--ref", "https://example.com/playbook", "--by", "owner"]])

    async def test_promote_is_a_gate_and_really_creates_the_project(self):
        ids = self.seed_portfolio()
        from brainlib.core import Brain
        Brain(self.inst).record_one({"type": "opportunity.status", "id": ids["aposta"], "by": "owner", "data": {"status": "priorizada"}})
        app = self.app()
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("tab", "3")
            app.tab[3] = 1
            app.set_sel(3, [i.id for i in app.items(3)].index(ids["aposta"]))
            app.redraw()
            await pilot.press("p")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertTrue(app.screen.spec.gate)
            self.assertIn("### P", str(app.screen.spec.extra))                    # o diff proposto aparece antes de qualquer escrita
            before = (self.inst.planning_file).read_text(encoding="utf-8")
            await pilot.press("ctrl+s")                                           # sem aprovação digitada não passa
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertEqual(self.inst.planning_file.read_text(encoding="utf-8"), before)
            await self.fill(pilot, quote="ok")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            st = self.state(app)
            o = st.opportunities[ids["aposta"]]
            self.assertEqual((o.status, o.goal), ("em-andamento", "GOAL-1"))
            self.assertIn(f"### {o.project} — Plataforma de dados", self.inst.planning_file.read_text(encoding="utf-8"))
            self.assertEqual((app.face, app.cur().id), (1, ids["aposta"]))
            self.assertEqual(app.tab[3], 2)                                        # a aba segue o status novo


    # ── perguntas do agente (agent-questions, passo 4) ────────────────────
    def seed_asks(self):
        from brainlib import ask
        from brainlib.core import Brain
        b = Brain(self.inst)
        _, a, _ = ask.add(b, "Qual Marina? A Marina-demo ou a Mari-demo?", ["marina-demo", "mari-demo"], ["TASK-0001"], "identidade", "run-1", source="chat")
        _, c, _ = ask.add(b, "Esta ata é reunião ou documento?", [], [], "classificacao", "run-1", source="chat")
        return a, c

    def fake_resume(self, app):
        """O resume vira um comando de mentira que só ecoa o prompt (o claude de verdade não roda nos testes)."""
        calls = []
        script = Path(self.tmp.name) / "fake_resume.py"
        script.write_text("import sys\nprint('retomado:', sys.argv[1][:200])\n", encoding="utf-8")

        def fake(cfg, session_id, prompt, extra=None, run_id=None):
            calls.append({"session": session_id, "prompt": prompt, "extra": extra, "run": run_id})
            return [sys.executable, str(script), prompt]
        return calls, mock.patch.object(bridge, "resume_argv", side_effect=fake)

    async def test_questions_tab_lists_open_first_and_shows_the_counter(self):
        a, c = self.seed_asks()
        from brainlib.core import Brain
        Brain(self.inst).record_one({"type": "question.answered", "id": c, "by": "owner", "data": {"answer": "documento"}})
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            self.assertIn("Perguntas", app._title(4).plain)
            self.assertIn("Perguntas 1", app._title(4).plain)                                         # contador no título da aba
            self.assertIn("1 pergunta", self.text_of(app.query_one("#p1")))                           # painel 1 também mostra
            await pilot.press("4")
            self.assertEqual(app.tab[4], 0)
            self.assertEqual([i.id for i in app.items(4)], [a, c])                                    # aberta no topo, respondida abaixo
            self.assertEqual(app.items(4)[0].kind, "ask")
            from brainlib.tui import rows
            for it in app.items(4):
                self.assertTrue(rows.row(app.store, it, 80).plain)
                self.assertIn(it.id, rows.detail(app.store, it).plain)
            self.assertIn("marina-demo", rows.detail(app.store, app.items(4)[0]).plain)
            keys = {k.k for k in app.ctx_keys()}
            self.assertEqual({"enter", "a", "x", "R", "T"}, keys)
            app.jump(c)
            self.assertEqual((app.p, app.tab[4], app.cur().id), (4, 0, c))
            self.assertNotIn("a", {k.k for k in app.ctx_keys()})                                      # respondida: sem responder

    async def test_answer_by_option_by_free_text_and_drop(self):
        a, c = self.seed_asks()
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "a")
            await pilot.pause(0.4)
            self.assertEqual(type(app.screen).__name__, "PickerModal")
            await self.typ(pilot, "mari-demo")
            await pilot.pause(0.4)
            await pilot.press("enter")
            await self.settle(app, pilot)
            q = self.state(app).questions[a]
            self.assertEqual((q.status, q.answer, q.free), ("respondida", "mari-demo", False))
            self.assertEqual(app.cur().id, c)                                                          # abertas primeiro: a próxima é a outra
            await pilot.press("enter")                                                                 # sem opções: texto livre direto
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            await self.fill(pilot, answer="é uma ata de reunião")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            q = self.state(app).questions[c]
            self.assertEqual((q.status, q.answer), ("respondida", "é uma ata de reunião"))
        # fora das opções: "outra resposta…" vira texto livre (free)
        from brainlib import ask
        from brainlib.core import Brain
        _, d, _ = ask.add(Brain(self.inst), "Terceira dúvida?", ["sim", "não"], [], "outro", "", source="chat")
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "a")
            await pilot.pause(0.4)
            await self.typ(pilot, "outra")
            await pilot.pause(0.4)
            await pilot.press("enter")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            await self.fill(pilot, answer="depende")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            q = self.state(app).questions[d]
            self.assertEqual((q.answer, q.free), ("depende", True))
            await pilot.press("4")
            self.assertEqual(self.state(app).questions[d].status, "respondida")

    async def test_drop_question_needs_a_reason(self):
        a, c = self.seed_asks()
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "x")
            await pilot.pause(0.3)
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")                                  # sem motivo não descarta
            await self.fill(pilot, reason="já resolvi")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            q = self.state(app).questions[a]
            self.assertEqual((q.status, q.reason), ("descartada", "já resolvi"))

    async def test_answering_the_last_open_question_offers_to_resume_the_agent(self):
        a, c = self.seed_asks()
        calls, patch = self.fake_resume(None)
        app = self.app()
        app.last_run = bridge.RunInfo(id="run-1", session_id="sess-42")
        with patch:
            async with app.run_test(size=(140, 44)) as pilot:
                await pilot.pause(0.4)
                app.answer_question(self.state(app).questions[a], "marina-demo")
                await self.settle(app, pilot)
                self.assertEqual(calls, [])                                                            # ainda há uma aberta: não pergunta
                app.answer_question(self.state(app).questions[c], "reunião")
                for _ in range(40):
                    await pilot.pause(0.1)
                    if type(app.screen).__name__ == "ConfirmModal":
                        break
                self.assertEqual(type(app.screen).__name__, "ConfirmModal")
                self.assertIn("Retomar o agente agora?", app.screen.title_)
                await pilot.press("enter")
                for _ in range(60):
                    await pilot.pause(0.1)
                    if calls and not app.busy and type(app.screen).__name__ != "ConfirmModal":
                        break
                await self.settle(app, pilot)
                self.assertEqual(calls[0]["session"], "sess-42")
                self.assertEqual(calls[0]["prompt"], f"O dono respondeu: {a} = marina-demo; {c} = reunião. Aplique (passo 0) e continue de onde parou.")
                self.assertIn("retomado: O dono respondeu", self.log_text(app))

    async def test_resume_without_session_leaves_answers_in_the_queue(self):
        a, c = self.seed_asks()
        from brainlib.core import Brain
        Brain(self.inst).record_one({"type": "question.answered", "id": a, "by": "owner", "data": {"answer": "marina-demo"}})
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "R")
            await pilot.pause(0.2)
            self.assertIn("sem sessão do agente para retomar", self.log_text(app))
            self.assertIn("passo 0", self.log_text(app))
            self.assertEqual(self.state(app).questions[a].status, "respondida")                       # nada se perde: fica para o passo 0
            self.assertEqual([x.id for x in app.store.answered_asks()], [a])

    async def test_free_reply_resumes_the_session_or_saves_a_note(self):
        calls, patch = self.fake_resume(None)
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.pending_reply = True
            before = len(app.query_one("#log").lines)
            await pilot.press("r")                                                                    # pendente: r é resposta livre, não render
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            self.assertIn("nota", app.screen.spec.sub)                                                # sem sessão: vira nota
            app.screen.query_one("#f_text").text = "A Marina é a sócia, não a fornecedora."
            await pilot.pause(0.15)
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            notes = list((self.inst.inbox).glob("*note*.md"))
            self.assertTrue(any("A Marina é a sócia" in n.read_text(encoding="utf-8") for n in notes))
            app.last_run = bridge.RunInfo(id="run-3", session_id="sess-7")
            with patch:
                await pilot.press("ctrl+t")
                await pilot.press("ctrl+t")
                app.free_reply()
                await pilot.pause(0.3)
                self.assertNotIn("nota", app.screen.spec.sub)
                app.screen.query_one("#f_text").text = "pode seguir com a Marina-demo"
                await pilot.pause(0.15)
                await pilot.press("ctrl+s")
                await self.settle(app, pilot, n=150)
            self.assertEqual((calls[0]["session"], calls[0]["prompt"]), ("sess-7", "pode seguir com a Marina-demo Aplique (passo 0) e continue de onde parou."))
            self.assertFalse(app.pending_reply)
        app2 = self.app()
        async with app2.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("r")                                                                    # sem pendência, r continua sendo render
            await self.settle(app2, pilot)
            self.assertIn("brain render", self.log_text(app2))

    async def test_denied_permissions_become_questions_and_external_writes_are_never_freed(self):
        from brainlib.core import Brain
        app = self.app()
        info = bridge.RunInfo(id="run-9", session_id="sess-9", denials=[
            {"tool_name": "mcp__x__list_files", "tool_input": {"q": "a"}},
            {"tool_name": "mcp__x__list_files", "tool_input": {"q": "a"}},                              # repetida: uma pergunta só
            {"tool_name": "mcp__slack__slack_send_message", "tool_input": {"to": "caio-demo"}},
            {"tool_name": "Bash", "tool_input": {"command": "./brain add <<'JSON'\n[]\nJSON"}}])
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await app.after_run(info)
            await app.reload_for_test() if hasattr(app, "reload_for_test") else await app._reload()
            qs = {q.id: q for q in Brain(self.inst).state.questions.values() if q.run == "run-9"}
            self.assertEqual(len(qs), 3)
            by_ctx = {q.context[0]: q for q in qs.values()}
            read = by_ctx["allow:mcp__x__list_files"]
            self.assertEqual((read.kind, read.options), ("permissao", ["liberar sempre", "não liberar"]))
            write = by_ctx["allow:mcp__slack__slack_send_message"]
            self.assertEqual(write.options, ["entendi"])
            self.assertIn("/outbox", write.text)
            bash = by_ctx["allow:Bash(./brain add:*)"]
            self.assertIn("./brain add", bash.text)
            # liberar sempre: responde, grava a regra pelo CLI e marca aplicada
            app.answer_question(read, "liberar sempre")
            await self.settle(app, pilot)
            self.assertIn("mcp__x__list_files", config.load(self.root).cfg["runner"]["allow"])        # MCP de leitura vale para o noturno também
            self.assertEqual(self.state(app).questions[read.id].status, "aplicada")
            app.answer_question(bash, "liberar sempre")
            await self.settle(app, pilot)
            self.assertIn("Bash(./brain add:*)", config.load(self.root).cfg["tui"]["agent_allow"])
            # escrita externa: só "entendi", nada é liberado
            before = (self.root / "config" / "brain.toml").read_text(encoding="utf-8")
            app.answer_question(write, "entendi")
            await self.settle(app, pilot)
            self.assertEqual((self.root / "config" / "brain.toml").read_text(encoding="utf-8"), before)
            self.assertEqual(self.state(app).questions[write.id].status, "aplicada")
            # mesmo que a pergunta seja forçada a "liberar sempre", a CLI recusa a ferramenta de escrita
            res = bridge.run_brain(self.inst, ["agent", "allow", "mcp__slack__slack_send_message"])
            self.assertEqual(res.rc, 4)

    async def test_agent_round_with_stream_json_reports_questions_and_denials(self):
        script = Path(self.tmp.name) / "fake_stream.py"
        script.write_text(
            "import json, os, re, subprocess, sys\n"
            "prompt = sys.argv[1]\nrun = re.search(r'run-\\d{8}-\\d{6}', prompt).group(0)\n"
            "def out(o): print(json.dumps(o), flush=True)\n"
            "out({'type': 'system', 'subtype': 'init', 'session_id': 'sess-stream'})\n"
            "out({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Processando a inbox.'}]}})\n"
            "subprocess.run([sys.executable, os.environ['FAKE_BRAIN'], 'ask', 'add', 'Qual Marina?', '--option', 'a', '--option', 'b', '--run', run,\n"
            "                '--prov', 'observado', '--source', 'chat'], check=True, capture_output=True)\n"
            "out({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'feito', 'session_id': 'sess-stream',\n"
            "     'permission_denials': [{'tool_name': 'mcp__x__list_files', 'tool_input': {'q': 'z'}}]})\n", encoding="utf-8")
        with open(self.root / "config" / "brain.toml", "a", encoding="utf-8") as fh:
            fh.write("")
        app = self.app()
        app.inst.cfg["runner"]["command"] = f"{sys.executable} {script} {{prompt}}"
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "d")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "AgentModal")
            await pilot.press("enter")
            await self.settle(app, pilot, n=200)
            log = " ".join(self.log_text(app).split())                                                  # o log quebra linha
            self.assertIn("Processando a inbox.", log)                                                  # texto do assistente, sem o JSON cru
            self.assertNotIn('"type"', log)
            self.assertIn("⚠ o agente deixou 1 pergunta e 1 permissão negada · 2 para responder (painel 4 › Perguntas) · r resposta livre", log)
            self.assertTrue(app.pending_reply)
            self.assertEqual(app.last_run.session_id, "sess-stream")
            qs = list(self.state(app).questions.values())
            self.assertEqual(sorted(q.kind for q in qs), ["outro", "permissao"])
            self.assertTrue(all(q.run == app.last_run.id for q in qs))
            row = __import__("json").loads((self.inst.logs / "agent-runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual((row["session_id"], len(row["asks"]), len(row["denials"])), ("sess-stream", 2, 1))
            self.assertIn("Perguntas 2", app._title(4).plain)

    # ── faces (carrossel no Tab) ───────────────────────────────────────────
    async def test_tab_cycles_faces_and_each_face_remembers_where_it_was(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            self.assertEqual((app.face, app.p), (0, 2))
            self.assertIn("[Execução]", self.text_of(app.query_one("#faces")))
            await pilot.press("j", "]")                              # Execução: segunda ação, aba "aguardando"
            sel, tab = app.cur().id, app.tab[2]
            await pilot.press("tab")
            self.assertEqual((app.face, app.p), (1, 3))              # Portfólio abre em Oportunidades
            self.assertIn("[Portfólio]", self.text_of(app.query_one("#faces")))
            self.assertIn("Oportunidades", str(app.query_one("#p3").border_title))
            self.assertIn("Visão", str(app.query_one("#p1").border_title))
            self.assertTrue(app.items(3))                                              # o demo traz oportunidades
            await pilot.press("5", "enter")                          # Registro › Áreas, detalhe ampliado
            self.assertTrue(app.zoom)
            await pilot.press("tab")                                 # volta à Execução (carrossel)
            self.assertEqual((app.face, app.p, app.tab[2], app.cur().id), (0, 2, tab, sel))
            self.assertFalse(app.zoom)
            await pilot.press("shift+tab")                           # para trás: também gira (0 → 1)
            self.assertEqual((app.face, app.p, app.tab[5], app.zoom), (1, 5, 0, True))
            await pilot.press("shift+tab")
            self.assertEqual(app.face, 0)

    async def test_filter_and_zoom_are_saved_on_the_face_of_origin(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.filt = (2, 0, "bancada")
            app._items = {}
            app.zoom = True
            app.redraw()
            await pilot.press("tab")
            self.assertEqual((app.filt, app.zoom), (None, False))
            await pilot.press("tab")
            self.assertEqual((app.filt, app.zoom), ((2, 0, "bancada"), True))
            await pilot.press("escape", "escape")                    # esc desfaz zoom e depois o filtro
            self.assertEqual((app.filt, app.zoom), (None, False))

    async def test_tab_inside_a_modal_still_moves_the_form_field(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            before = app.screen.focused.id
            await pilot.press("tab")
            await pilot.pause(0.1)
            self.assertNotEqual(app.screen.focused.id, before)
            await pilot.press("shift+tab")
            await pilot.pause(0.1)
            self.assertEqual(app.screen.focused.id, before)
            self.assertEqual(app.face, 0)                            # o Tab do modal não girou a face
            await pilot.press("escape")
            await pilot.pause(0.2)
            await pilot.press("tab")                                 # fechado o modal, volta a girar
            self.assertEqual(app.face, 1)

    async def test_jump_and_catalog_switch_face_and_click_on_the_strip(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            aid = app.items(2)[0].id
            await pilot.press("tab")
            self.assertEqual(app.store.locate(aid)[0], 0)
            app.jump(aid)                                            # id da Execução, estando no Portfólio
            self.assertEqual((app.face, app.p, app.cur().id), (0, 2, aid))
            app.run_catalog((1, 3, 3, None))                         # item de outra face na paleta
            self.assertEqual((app.face, app.p, app.tab[3]), (1, 3, 3))
            strip = self.text_of(app.query_one("#faces"))
            await pilot.click("#faces", offset=(strip.index("Execução") + 1, 0))
            self.assertEqual(app.face, 0)

    async def test_help_and_palette_know_the_face(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("tab", "question_mark")
            await pilot.pause(0.2)
            self.assertIn("Portfólio", str(app.screen.title_) if hasattr(app.screen, "title_") else "")
            await pilot.press("escape")

    async def test_context_keys_change_with_panel_and_tab(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            keys = lambda: {k.k for k in app.ctx_keys()}  # noqa: E731
            self.assertIn("c", keys())                      # ações: fechar
            await pilot.press("3")
            self.assertIn("E", keys())                      # plano: gate
            await pilot.press("4", "]", "]")
            self.assertIn("n", keys())                      # outbox: rascunhar
            await pilot.press("1")
            self.assertEqual({"u", "c", "d", "b", "o"}, keys())   # resumo: agente e painel
            every = {k.k for k in app.ctx_keys(every=True, panel=4, tab=2)}
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
            await pilot.press(*"bancada")
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertEqual([i.id for i in app.items(2)], [i.id for i in app.items(2) if "bancada" in i.q.lower()])
            await pilot.press("escape")
            self.assertIsNone(app.filt)
            await pilot.press("g")
            await pilot.pause(0.3)
            await pilot.press(*"galeria")
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

    async def test_new_action_without_due_offers_agent_suggestion(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Sem prazo dito")
            await pilot.press("ctrl+s")
            for _ in range(80):
                await pilot.pause(0.1)
                if type(app.screen).__name__ == "AgentModal":
                    break
            self.assertEqual(type(app.screen).__name__, "AgentModal")
            aid = next(x for x in self.state(app).actions.values() if x.title == "Sem prazo dito").id
            self.assertIn(f"/todo prazo {aid}", app.screen.prompt)
            await pilot.press("escape")
            await self.settle(app, pilot)
            # com prazo digitado, não há o que sugerir
            await pilot.press("n")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Com prazo dito", due="2026-10-30")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(len(app.screen_stack), 1)

    async def test_new_action_resolves_natural_date(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")
            await pilot.pause(0.2)
            await pilot.press(*"Ligar", "space", *"para", "space", *"marina-demo")
            await pilot.press("tab", *"+3d")
            await pilot.press("enter")
            await self.settle(app, pilot)
            a = next(x for x in self.state(app).actions.values() if x.title == "Ligar para marina-demo")
            self.assertEqual(a.due, util.today().replace() + (date(2026, 10, 12) - date(2026, 10, 9)))
            self.assertEqual(a.owner, self.inst.owner_id)

    async def test_new_action_goal_filters_active_projects_with_names(self):
        planning.edit_node(self.inst.vault / "PLANNING" / "goals.md", "PROJ-2", status="congelado")
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("n")
            await pilot.pause(0.3)
            form = app.screen
            ids = [f.id for f in form.spec.fields]
            self.assertLess(ids.index("goal"), ids.index("project"))              # goal antes do projeto
            proj = lambda: [str(v) for _, v in form.query_one("#f_project")._options]  # noqa: E731
            labels = lambda: [str(r) for r, _ in form.query_one("#f_project")._options]  # noqa: E731
            self.assertEqual(proj()[0], "—")
            self.assertNotIn("PROJ-2", proj())                                    # congelado não aparece
            self.assertIn("PROJ-1", proj())
            self.assertTrue(any("PROJ-1 · Reforma do novo ponto" in x for x in labels()))   # o nome aparece
            self.assertIn("GOAL-1", [str(v) for _, v in form.query_one("#f_goal")._options])
            form.query_one("#f_goal").value = "GOAL-3"                            # o goal restringe os projetos
            await pilot.pause(0.3)
            self.assertEqual(proj(), ["—", "PROJ-4"])
            self.assertEqual(form.query_one("#f_project").value, "—")
            form.query_one("#f_project").value = "PROJ-4"
            await self.fill(pilot, title="Com projeto filtrado")
            self.assertIn("--project PROJ-4", self.text_of(form.query_one("#cmdp")))
            self.assertNotIn("--goal", self.text_of(form.query_one("#cmdp")))     # o goal só filtra
            await pilot.press("ctrl+s")
            await self.settle_new_action(app, pilot)
            a = next(x for x in self.state(app).actions.values() if x.title == "Com projeto filtrado")
            self.assertEqual(a.project, "PROJ-4")

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
            app.exec([["action", "close", "TASK-9999", "--how", "x", "--by", "owner"]])
            await self.settle(app, pilot)
            log = self.log_text(app)
            self.assertIn("ERRO", log)
            self.assertNotIn("↻ brain render", log)

    async def test_proposal_accept_needs_literal_quote(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "]")
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
            await pilot.press("4", "]", "]")
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
            await pilot.press("4", "]", "]", "n")
            await pilot.pause(0.2)
            await pilot.press(*"heitor-demo", "tab", *"oi", "enter")
            await pilot.pause(0.2)
            self.assertIn("[outbound].allow", self.text_of(app.screen.query_one("#err")))

    async def test_focus_approve_then_apply_ics(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("4", "]", "]", "]")
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
            app.jump("PROJ-1.3")
            before = app.store.by_project["PROJ-1"]["progress"]["pct"]
            await pilot.press("space")
            await pilot.pause(0.2)
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertGreater(app.store.by_project["PROJ-1"]["progress"]["pct"], before)
            self.assertIn("$ brain plan deliverable PROJ-1.3 --status feito", self.log_text(app))

    async def test_plan_gate_logs_only_with_typed_approval_and_restores_on_cancel(self):
        editor = Path(self.tmp.name) / "editor.py"
        editor.write_text("import sys\nopen(sys.argv[1], 'a').write('\\n## GOAL-9 — Meta nova\\n- status: ativo\\n- horizonte: 2027-01-01\\n- por quê: teste\\n')\n", encoding="utf-8")
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
            self.assertIn("GOAL-9", goals.read_text(encoding="utf-8"))
            await pilot.press("escape")                               # cancelar desfaz a edição
            await pilot.pause(0.2)
            self.assertEqual(goals.read_text(encoding="utf-8"), original)
            await pilot.press("E")
            await pilot.pause(0.5)
            await pilot.press(*"GOAL-9", "space", *"nasce", "tab", *"nova", "space", *"meta", "tab", "tab", *"ok", "enter")
            await self.settle(app, pilot)
            self.assertIn("GOAL-9", goals.read_text(encoding="utf-8"))
            changes = self.state(app).plan_changes
            self.assertEqual(changes[-1]["approval"], "ok")

    async def test_sys_validate_and_door_confirmation(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.run_catalog((0, 1, 3, "enter", "sys:validate"))
            await self.settle(app, pilot)
            self.assertIn("$ brain validate", self.log_text(app))
            app.run_catalog((0, 1, 3, "enter", "sys:backup"))
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
            if op.get("form") or op.get("agent"):
                continue
            for args in (op["args"], op.get("apply")):
                if args:
                    parser.parse_args(args)                       # levanta SystemExit se a CLI não conhecer

    async def test_system_ai_commands_open_the_agent_modal(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.run_catalog((0, 1, 3, "enter", "sys:ai-week"))            # sem argumento: vai direto ao modal ⚡
            await self.settle_modal(app, pilot, "AgentModal")
            self.assertEqual(app.screen.prompt, "/week")
            await pilot.press("escape")
            app.run_catalog((0, 1, 3, "enter", "sys:ai-slack"))           # argumento obrigatório: pede antes
            await self.settle_modal(app, pilot, "FormModal")
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            await self.typ(pilot, "#time-estrategia 3d")
            await pilot.press("enter")
            await self.settle_modal(app, pilot, "AgentModal")
            self.assertEqual(app.screen.prompt, "/slack #time-estrategia 3d")
            await pilot.press("escape")
            app.run_catalog((0, 1, 3, "enter", "sys:ai-dump"))            # os cinco antigos reaproveitam o fluxo próprio
            await self.settle_modal(app, pilot, "AgentModal")
            self.assertEqual(app.screen.prompt, "/dump")
            await pilot.press("escape")

    async def test_system_output_opens_in_a_modal(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            app.run_catalog((0, 1, 3, "enter", "sys:doctor"))
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
            app.run_catalog((0, 1, 3, "enter", "sys:recall"))
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
            await pilot.press(*["tab"] * 11)                      # +1: o campo goal vem antes do projeto
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
            await self.typ(pilot, "Alinhar com Caio-demo")
            for _ in range(8):                                 # +1: o campo goal vem antes do projeto
                await pilot.press("tab")
            await self.typ(pilot, "PROJ-1.3")
            await pilot.press("tab")
            await self.typ(pilot, "caio-demo")
            await pilot.press("enter")
            await self.settle_new_action(app, pilot)
            a = next(x for x in self.state(app).actions.values() if x.title == "Alinhar com Caio-demo")
            self.assertEqual(a.deliverable, "PROJ-1.3")
            self.assertIn("caio-demo", a.people)

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

    async def test_O_sorts_actions_by_due_then_id(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            self.assertIn("O", {k.k for k in app.ctx_keys(every=True)})
            by_due = [i.id for i in app.items(2)]
            await pilot.press("O")
            self.assertEqual(app.sort, 1)
            its = app.items(2)
            self.assertEqual(sorted(by_due), sorted(i.id for i in its))
            opens = [i for i in its if i.data["open"]]
            ids = [i.id for i in opens]
            self.assertEqual(ids, sorted(ids))
            await pilot.press("O")                                  # volta ao prazo
            self.assertEqual([i.id for i in app.items(2)], by_due)

    async def test_v_cycles_views_and_z_parks_an_action(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            all_n = len(app.items(2))
            self.assertIn("v", {k.k for k in app.ctx_keys(every=True)})
            seen = []
            for _ in range(4):                                       # Todas → semana → depois → não agora → Todas
                await pilot.press("v")
                seen.append((app.view, len(app.items(2))))
            self.assertEqual([v for v, _ in seen], [1, 2, 3, 0])
            self.assertEqual(seen[-1][1], all_n)
            self.assertEqual(seen[0][1] + seen[1][1], sum(1 for i in app.items(2) if i.data["open"]))
            self.assertEqual(seen[2][1], 0)                          # nada adiado ainda
            target = app.cur().id
            await pilot.press("z")
            await self.settle(app, pilot)
            self.assertTrue(self.state(app).actions[target].parked)
            await pilot.press("v", "v", "v")                         # não agora
            self.assertEqual([i.id for i in app.items(2)], [target])
            await pilot.press("z")                                   # volta
            await self.settle(app, pilot)
            self.assertFalse(self.state(app).actions[target].parked)

    async def test_registry_forms_and_share_publish_flow(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("5", "n")                             # decisão
            await pilot.pause(0.3)
            await self.typ(pilot, "Adiar o piloto")
            await pilot.press("tab")
            await self.typ(pilot, "marina-demo")
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
            await self.typ(pilot, "Marina-demo")
            await pilot.press("enter")
            await pilot.pause(1.2)
            self.assertIn("marina-demo", self.log_text(app))
            # exportar status → pedir → aprovar → publicar pelo agente
            await pilot.press("3", "S")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await self.settle(app, pilot)
            await pilot.press("4", "]", "]", "]", "]", "n")
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
            app.jump("GOAL-1")
            await pilot.press("P")
            await pilot.pause(0.3)
            await self.typ(pilot, "60")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(app.store.by_goal["GOAL-1"]["declared"]["pct"], 60)
            await pilot.press("4", "]", "]", "]", "s")
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
            await self.fill(pilot, key="nova", channel="#nova", other="semigual")
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertIn("campo=valor", self.text_of(app.screen.query_one("#err")))
            self.assertEqual(len(watch.list_sources(self.inst)), 2)

    async def test_source_form_is_contextual_by_kind(self):
        app = self.app()
        async with app.run_test(size=(140, 60)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "]", "]", "n")
            await pilot.pause(0.3)
            shown = lambda: {b.id[2:] for b in app.screen.query(".fbox") if b.display}
            self.assertEqual(shown(), {"key", "note", "kind", "query", "window", "other"})       # gmail
            await self.fill(pilot, kind="drive-doc")
            self.assertEqual(shown(), {"key", "note", "kind", "doc", "other"})                  # só a URL; vínculo é opcional
            await self.fill(pilot, kind="drive")
            self.assertEqual(shown(), {"key", "note", "kind", "folder", "window", "other"})
            await self.fill(pilot, key="drive-mops", folder="https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWx?usp=x")
            await pilot.press("enter")
            await self.settle(app, pilot)
            got = next(x for x in watch.list_sources(self.inst) if x["key"] == "drive-mops")
            self.assertEqual(got["folder"], "1AbCdEfGhIjKlMnOpQrStUvWx")                     # URL → id
            await pilot.press("n")
            await pilot.pause(0.3)
            await self.fill(pilot, key="jira-epico", kind="jira", jscope="epic")
            await self.fill(pilot, jref="https://acme.atlassian.net/browse/OPS-42", mode="state")
            self.assertNotIn("window", shown())                                                 # estado completo não tem janela
            await pilot.press("enter")
            await self.settle(app, pilot)
            got = next(x for x in watch.list_sources(self.inst) if x["key"] == "jira-epico")
            self.assertEqual((got["jql"], got["cloud"], got["mode"]),
                             ("parent = OPS-42 AND statusCategory != Done ORDER BY key", "acme.atlassian.net", "state"))
            self.assertNotIn("window", got)

    def test_jira_scope_to_jql(self):
        self.assertEqual(watch.jira_jql("project", "https://a.atlassian.net/jira/software/c/projects/OPS/boards/12"),
                         "project = OPS AND updated >= -1d")
        self.assertEqual(watch.jira_jql("board", "https://a.atlassian.net/jira/software/c/projects/OPS/boards/12", "state"),
                         "project = OPS AND statusCategory != Done ORDER BY key")
        self.assertEqual(watch.jira_jql("filter", "https://a.atlassian.net/issues/?filter=10042"), "filter = 10042 AND updated >= -1d")
        self.assertEqual(watch.jira_jql("epic", "ops-7"), "parent = OPS-7 AND updated >= -1d")
        self.assertEqual(watch.jira_jql("jql", "project = X"), "project = X")
        self.assertTrue(watch.jira_jql("mine", "").startswith(watch.JIRA_MINE))
        self.assertEqual(watch.jira_cloud("https://Acme.atlassian.net/browse/OPS-1"), "acme.atlassian.net")
        with self.assertRaises(util.BrainError):
            watch.jira_base("board", "12")                                  # id sozinho não diz o projeto
        with self.assertRaises(util.BrainError):
            watch.add(self.inst, "drive-x", {"kind": "drive", "folder": "não é drive"})

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
            app.screen.query_one("#f_link").value = "TASK-9999"
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
        for link in ("GOAL-1", "PROJ-1", "PROJ-1.1"):
            notes.create(b, f"nota de {link}", link)
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3")
            for it in app.items(3):
                if it.id in ("GOAL-1", "PROJ-1", "PROJ-1.1"):
                    app.set_sel(3, [i.id for i in app.items(3)].index(it.id))
                    app.redraw()
                    self.assertIn(f"▌ nota de {it.id}", self.text_of(app.query_one("#detail")))

    async def test_second_note_same_day_asks_edit_or_new(self):
        from brainlib import notes
        from brainlib.core import Brain
        b = Brain(self.inst)
        notes.create(b, "primeira", "PROJ-1")
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3")
            app.set_sel(3, [i.id for i in app.items(3)].index("PROJ-1"))
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
            self.assertEqual(files, ["PROJ-1-2026-10-09-note.md"])
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
                             ["PROJ-1-2026-10-09-note-2.md", "PROJ-1-2026-10-09-note.md"])
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
        src = notes.create(b, "já arquivada", "PROJ-1")
        dest = self.inst.vault / "RAW" / "2026" / "10"
        dest.mkdir(parents=True, exist_ok=True)
        src.rename(dest / src.name)
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("3", "N")
            await pilot.pause(0.3)
            app.screen.query_one("#f_text").text = "nova"
            app.screen.query_one("#f_link").value = "PROJ-1"
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)                      # sem pergunta: RAW é imutável
        self.assertTrue((self.inst.inbox / "PROJ-1-2026-10-09-note-2.md").exists())

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

    async def test_plan_e_edits_goal_project_deliverable(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            # entregável: sem gate
            self._select3(app, "PROJ-1.1")
            self.assertIn("e", {k.k for k in app.ctx_keys()})
            await pilot.press("e")
            await pilot.pause(0.3)
            self.assertIn("Editar PROJ-1.1", self.text_of(app.screen.query_one("#mt")))
            await self.fill(pilot, title="Entregável editado", due="2026-12-20", weight="3")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            d = app.store.brain.plan.deliverables["PROJ-1.1"]
            self.assertEqual((d.title, d.due, d.weight), ("Entregável editado", date(2026, 12, 20), 3))
            self.assertIn("$ brain plan edit PROJ-1.1", self.log_text(app))
            # projeto: gate (sem aprovação não passa)
            self._select3(app, "PROJ-1")
            await pilot.press("e")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Projeto editado")
            await pilot.press("ctrl+s")
            await pilot.pause(0.2)
            self.assertEqual(type(app.screen).__name__, "FormModal")
            await self.fill(pilot, quote="ok")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            self.assertEqual(app.store.brain.plan.projects["PROJ-1"].title, "Projeto editado")
            # goal: gate
            self._select3(app, "GOAL-1")
            await pilot.press("e")
            await pilot.pause(0.3)
            await self.fill(pilot, title="Goal editado", horizon="2027-05-01", quote="ok")
            await pilot.press("ctrl+s")
            await self.settle(app, pilot)
            g = app.store.brain.plan.goals["GOAL-1"]
            self.assertEqual((g.title, g.horizon), ("Goal editado", "2027-05-01"))
            self.assertEqual(sum(1 for e in app.store.brain.read_events() if e["type"] == "plan.changed"), 2)

    async def test_plan_n_is_contextual_goal_project_deliverable(self):
        app = self.app()
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            label = lambda: next(k.label for k in app.ctx_keys() if k.k == "n")  # noqa: E731
            self._select3(app, "GOAL-1")
            self.assertEqual(label(), "novo projeto")
            self._select3(app, "PROJ-1")
            self.assertEqual(label(), "novo entregável")
            self._select3(app, "PROJ-1.1")
            self.assertEqual(label(), "nova ação")
            self.assertIn("G", {k.k for k in app.ctx_keys()})
            # goal → projeto (gate: exige a aprovação digitada)
            self._select3(app, "GOAL-1")
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
            self.assertEqual(plan.projects[pid].goal_id, "GOAL-1")
            self.assertEqual((app.p, app.cur().id), (3, pid))                  # a seleção vai para o novo projeto
            self.assertIn("plan.changed", [e["type"] for e in app.store.brain.read_events()])
            self.assertIn("$ brain plan add-project GOAL-1", self.log_text(app))
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
            await self.settle_new_action(app, pilot)
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
            # PROJ-1 não pega PROJ-10: filtro por id é exato; texto livre continua sendo substring
            self.assertNotIn("PROJ-10", shown(3, 0, "PROJ-1"))
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
            self.assertEqual(f.value, a["deliverable"].split(".")[1])         # PROJ-1.2 aparece só como 2
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
            await self.settle_new_action(app, pilot)
            b = next(x for x in self.state(app).actions.values() if x.title == "Com número")
            self.assertEqual(b.deliverable, f"{proj}.1")


class CoverageTest(unittest.TestCase):
    """Todo subcomando da CLI tem tecla no TUI ou uma razão explícita para não ter."""
    READ_ONLY_VIEWS = {   # a leitura já está num painel (modelo em processo), sem precisar chamar a CLI
        "person list", "action show", "action list", "decision list", "plan show", "focus show", "outbox show",
        "outbox list", "proposal list", "publish list", "doctor", "search", "status", "artifact", "watch list", "watch since", "watch folders",
        "repos list", "note list", "raw where", "ask list", "area list", "process show", "process list", "opportunity show", "opportunity list",
        "action dupes"}   # o aviso de parecida aparece no campo título da nova ação

    AGENT_ONLY = {        # quem escreve é o agente (extração, snapshot, envio), conforme a Constituição
        "init", "add", "snapshot", "repos pull", "proposal add", "outbox sent", "outbox failed", "publish done",
        "pdf text", "pdf render", "video transcribe", "video frames", "person merge",
        "raw archive", "raw sort", "ask add", "ask applied",
        "oppdrive status", "oppdrive onepager", "oppdrive record", "oppdrive suggested",   # porta do Drive: quem cria é o agente
        "oppdrive build", "oppdrive sync", "oppdrive synced", "oppdrive restyle", "oppdrive links",    # (e quem mantém o Resumo)
        "action not-dup"}     # julgamento do agente sobre um par de candidatas; o dono decide pela proposta
    NOT_IN_TUI = {"demo", "tui", "migrate ids"}      # migração única, feita no terminal com o dono (backup + dry-run)
    DYNAMIC = {"memory recall", "memory reflect"}      # o formulário "Memória: perguntar" monta o subcomando

    def test_every_cli_subcommand_is_accounted_for(self):
        import re
        from brainlib import cli
        src = "".join((ROOT / "brainlib" / "tui" / f).read_text(encoding="utf-8") for f in ("app.py", "store.py", "portfolio_keys.py", "ask_keys.py"))
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
