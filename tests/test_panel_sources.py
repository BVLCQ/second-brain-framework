"""Testes do painel Fontes (#29): agrupamento por tipo, priorização de falhas,
ordenação por Último pull e alternador enabled por fonte.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import cli, config, render, serve, watch  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n"
        "- por quê: teste\n\n### PROJ-1 — Projeto\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Entregável · prazo: 2026-10-20 · peso: 1\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Marina"], "email": "marina-demo@x.com"}})
    return b


def _run_cli(root: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"BRAIN_HOME": str(root)}):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
    return rc, out.getvalue(), err.getvalue()


class PanelSourcesGroupingAndToggleTest(unittest.TestCase):
    NOW = "2026-10-19T10:00:00-03:00"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.brain = _brain(self.root)
        self.inst = self.brain.inst
        self.old_now = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = self.NOW
        self.addCleanup(self._restore_now)

        # Multi-type watch.toml com:
        # - falha (slack-fail)
        # - nunca puxada / unpulled (gmail-unpulled)
        # - desligada / disabled (slack-disabled)
        # - saudáveis habilitadas (slack-ok, gcal-ok)
        watch.add(self.inst, "slack-fail", {"kind": "slack", "window": "1d", "channel": "#falhas"})
        watch.add(self.inst, "slack-ok", {"kind": "slack", "window": "1d", "channel": "#geral"})
        watch.add(self.inst, "slack-disabled", {"kind": "slack", "window": "1d", "channel": "#antigo", "enabled": False})
        watch.add(self.inst, "gcal-ok", {"kind": "gcal", "window": "14d"})
        watch.add(self.inst, "gmail-unpulled", {"kind": "gmail", "window": "1d"})

        # Histórico de pulls / falhas
        self.brain.record_one({"type": "connector.pulled", "id": "slack-fail", "by": "system",
                               "date": "2026-10-19", "data": {"changed": False}})
        self.brain.record_one({"type": "connector.failed", "id": "slack-fail", "by": "system",
                               "date": "2026-10-19", "data": {"error": "HTTP 500 Server Error"}})
        self.brain.record_one({"type": "connector.pulled", "id": "slack-ok", "by": "system",
                               "date": "2026-10-19", "data": {"changed": False}})
        self.brain.record_one({"type": "connector.pulled", "id": "slack-disabled", "by": "system",
                               "date": "2026-10-19", "data": {"changed": False}})
        self.brain.record_one({"type": "connector.pulled", "id": "gcal-ok", "by": "system",
                               "date": "2026-10-19", "data": {"changed": False}})

    def _restore_now(self):
        if self.old_now is None:
            os.environ.pop("BRAIN_NOW", None)
        else:
            os.environ["BRAIN_NOW"] = self.old_now

    def test_view_model_and_render_html_payload(self):
        """view_model e render_html incluem campos do Chunk 2 e marcadores de asset no HTML."""
        vm = render.view_model(self.brain)
        sources_by_key = {s["key"]: s for s in vm["sources"]}

        # 1. Verifica payload M.sources
        self.assertIn("slack-fail", sources_by_key)
        self.assertTrue(sources_by_key["slack-fail"]["enabled"])
        self.assertTrue(sources_by_key["slack-fail"]["problem"])
        self.assertIn("falha", sources_by_key["slack-fail"]["problem_reason"])
        self.assertEqual(sources_by_key["slack-fail"]["failures"], 1)

        self.assertIn("gmail-unpulled", sources_by_key)
        self.assertTrue(sources_by_key["gmail-unpulled"]["enabled"])
        self.assertTrue(sources_by_key["gmail-unpulled"]["problem"])
        self.assertEqual(sources_by_key["gmail-unpulled"]["problem_reason"], "nunca puxada")

        self.assertIn("slack-disabled", sources_by_key)
        self.assertFalse(sources_by_key["slack-disabled"]["enabled"])
        self.assertFalse(sources_by_key["slack-disabled"]["problem"])
        self.assertEqual(sources_by_key["slack-disabled"]["problem_reason"], "desligada")

        self.assertIn("slack-ok", sources_by_key)
        self.assertTrue(sources_by_key["slack-ok"]["enabled"])
        self.assertFalse(sources_by_key["slack-ok"]["problem"])

        self.assertIn("gcal-ok", sources_by_key)
        self.assertTrue(sources_by_key["gcal-ok"]["enabled"])
        self.assertFalse(sources_by_key["gcal-ok"]["problem"])

        # 2. Renderiza dashboard.html
        html = render.render_html(vm)
        self.assertNotIn("__DATA__", html)

        # 3. Marcadores de asset exigidos pelo spec
        self.assertIn("Último pull", html)
        self.assertIn("brain watch edit", html)
        self.assertIn("desligada", html)
        self.assertIn("data-src-sort", html)
        self.assertIn("data-src-toggle", html)
        self.assertIn('aria-label="Ligar/desligar fonte"', html)

    def test_serve_allowlist_accepts_watch_edit(self):
        """serve.py aceita brain watch edit <key> --set enabled=false."""
        self.assertTrue(serve._allowed_argv(["watch", "edit", "slack-ok", "--set", "enabled=false"]))
        self.assertTrue(serve._allowed_argv(["watch", "edit", "slack-disabled", "--set", "enabled=true"]))
        self.assertTrue(serve._allowed_argv(["watch", "edit", "slack-ok", "--window", "7d"]))

    def test_cli_watch_edit_toggle_in_process(self):
        """Edição em processo via CLI altera enabled no watch.toml e reflete no render."""
        rc, out, err = _run_cli(self.root, "watch", "edit", "slack-ok", "--set", "enabled=false")
        self.assertEqual(rc, 0, err)
        self.assertIn("slack-ok atualizada", out)

        toml_text = watch.path(self.inst).read_text(encoding="utf-8")
        self.assertIn("enabled = false", toml_text)

        vm = render.view_model(self.brain)
        s_ok = next(s for s in vm["sources"] if s["key"] == "slack-ok")
        self.assertFalse(s_ok["enabled"])
        self.assertEqual(s_ok["problem_reason"], "desligada")

    def test_node_renders_sources_grouping_and_problem_first(self):
        """Node executa V.sources(): grupos com falha primeiro, falhas no topo da tabela, toggle asc/desc."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node não disponível no ambiente")

        vm = render.view_model(self.brain)
        node_script = """
const fs = require("fs");
const model = JSON.parse(process.argv[1]);
const dummyEl = {
  innerHTML: "", textContent: "", dataset: {},
  classList: {toggle: () => {}, add: () => {}, remove: () => {}, contains: () => false},
  addEventListener: () => {}
};
global.document = {
  getElementById: id => id === "data" ? {textContent: JSON.stringify(model)} : dummyEl,
  querySelector: () => dummyEl,
  querySelectorAll: () => [],
  addEventListener: () => {},
  documentElement: {dataset: {}}
};
global.window = global;
global.scrollTo = () => {};
global.addEventListener = () => {};
global.localStorage = {getItem: () => null, setItem: () => {}};
global.matchMedia = () => ({matches: false});
global.location = {hash: "sources"};

const core = fs.readFileSync("brainlib/assets/src/core.js", "utf8");
eval(core);

// 1. Render padrão (S_SORT === "desc")
window.BRAIN.S_SORT = "desc";
const htmlDesc = window.BRAIN.V.sources();

// 2. Render invertido (S_SORT === "asc")
window.BRAIN.S_SORT = "asc";
const htmlAsc = window.BRAIN.V.sources();

process.stdout.write(JSON.stringify({desc: htmlDesc, asc: htmlAsc}));
"""
        proc = subprocess.run([node, "-e", node_script, json.dumps(vm, default=str)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        html_desc, html_asc = out["desc"], out["asc"]

        # Grupos com problema (gmail, slack) aparecem antes de gcal (sem problema)
        idx_gmail = html_desc.find("▾ gmail · e-mails")
        idx_slack = html_desc.find("▾ slack · canal ou DM")
        idx_gcal = html_desc.find("▾ gcal · agenda")
        self.assertTrue(0 <= idx_gmail < idx_slack < idx_gcal,
                        f"esperado gmail < slack < gcal; índices: gmail={idx_gmail}, slack={idx_slack}, gcal={idx_gcal}")

        # Badges de atenção nos grupos com problema
        self.assertIn("⚠ 1 com problema", html_desc[idx_gmail:idx_slack])
        self.assertIn("⚠ 1 com problema", html_desc[idx_slack:idx_gcal])

        # Em slack: problema sempre no topo, disabled sempre no final
        idx_s_fail = html_desc.find('data-sel="src:slack-fail"')
        idx_s_ok = html_desc.find('data-sel="src:slack-ok"')
        idx_s_dis = html_desc.find('data-sel="src:slack-disabled"')
        self.assertTrue(0 <= idx_s_fail < idx_s_ok < idx_s_dis,
                        f"esperado fail < ok < disabled em desc; índices: fail={idx_s_fail}, ok={idx_s_ok}, dis={idx_s_dis}")

        # Indicador de seta no cabeçalho
        self.assertIn("Último pull ↓", html_desc)
        self.assertIn("Último pull ↑", html_asc)

        # Mesmo em asc, problem continua no topo e disabled continua no final
        idx_s_fail_asc = html_asc.find('data-sel="src:slack-fail"')
        idx_s_ok_asc = html_asc.find('data-sel="src:slack-ok"')
        idx_s_dis_asc = html_asc.find('data-sel="src:slack-disabled"')
        self.assertTrue(0 <= idx_s_fail_asc < idx_s_ok_asc < idx_s_dis_asc,
                        f"esperado fail < ok < disabled em asc; índices: fail={idx_s_fail_asc}, ok={idx_s_ok_asc}, dis={idx_s_dis_asc}")


if __name__ == "__main__":
    unittest.main()
