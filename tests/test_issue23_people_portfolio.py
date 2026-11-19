"""Testes da issue #23: mover Pessoas da face Execução para Portfólio."""
import argparse
import asyncio
import contextlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from brainlib import config
from brainlib.demo import cli as demo_cli
from brainlib.tui.app import BrainApp
from brainlib.tui.store import PANELS_EXEC, PANELS_PORT, Store

ROOT = Path(__file__).resolve().parent.parent


class PeoplePortfolioTests(unittest.TestCase):

    def test_panel_tabs_order_in_sources_and_built_dashboard(self):
        """No core.js e no dashboard.html montado, 'people' saiu de TABS_EXEC e entrou em TABS_PF após pf/areas e pf/docs."""
        core_src = (ROOT / "brainlib" / "assets" / "src" / "core.js").read_text(encoding="utf-8")
        dashboard_html = (ROOT / "brainlib" / "assets" / "dashboard.html").read_text(encoding="utf-8")

        for label, content in [("core.js", core_src), ("dashboard.html", dashboard_html)]:
            m_exec = re.search(r"const TABS_EXEC = (\[[\s\S]*?\]);", content)
            self.assertIsNotNone(m_exec, f"{label} deve declarar TABS_EXEC")
            exec_str = m_exec.group(1)
            self.assertNotIn('"people"', exec_str, f"{label}: 'people' não deve estar em TABS_EXEC")

            m_pf = re.search(r"const TABS_PF = (\[[\s\S]*?\]);", content)
            self.assertIsNotNone(m_pf, f"{label} deve declarar TABS_PF")
            pf_str = m_pf.group(1)
            self.assertIn('"people"', pf_str, f"{label}: 'people' deve estar em TABS_PF")

            idx_areas = pf_str.find('"pf/areas"')
            idx_docs = pf_str.find('"pf/docs"')
            idx_people = pf_str.find('"people"')
            self.assertTrue(idx_areas < idx_docs < idx_people,
                            f"{label}: ordem deve ser pf/areas < pf/docs < people, got {idx_areas}, {idx_docs}, {idx_people}")

    def test_node_router_routes_people_and_person_to_portfolio_and_cycles_back(self):
        """Roteador no node: #people e #person/marina-demo caem na face 'portfolio' com aba 'people', e alternar face vai para execucao."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node ausente no ambiente")

        script = r"""
const fs = require("fs");
const path = require("path");

const core = fs.readFileSync(path.join(process.argv[1], "brainlib/assets/src/core.js"), "utf8");

let curTabs = null, curView = null, curParent = null, curFace = null;
const localStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }
};
const location = { hash: "" };
const window = {
  location, localStorage, PF_ONLY: false,
  addEventListener() {}, scrollTo() {},
  renderTabs(view, tabs, parent) { curView = view; curTabs = tabs; curParent = parent; },
  renderFaces(face, faces) { curFace = face; }
};
const document = {
  getElementById(id) {
    if (id === "data") return {
      textContent: JSON.stringify({
        owner: { id: "marina-demo", name: "Marina" },
        agenda: [],
        people: [{ id: "marina-demo", name: "Marina", aliases: [], owes_me: [], i_owe: [], decisions: [] }],
        portfolio: { areas: [], opportunities: [], processes: [] },
        actions: [], decisions: [], projects: [], goals: [], artifacts: []
      })
    };
    return { addEventListener() {}, innerHTML: "", dataset: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } } };
  },
  querySelector(s) { return { addEventListener() {}, innerHTML: "", classList: { add() {}, remove() {}, toggle() {} } }; },
  querySelectorAll() { return []; },
  addEventListener() {},
  createElement() { return { querySelectorAll() { return []; }, addEventListener() {} }; },
  body: { appendChild() {} },
  documentElement: { dataset: {} }
};
const matchMedia = () => ({ matches: false });

eval(core);

// 1. Rota #people
location.hash = "#people";
window.BRAIN.route();
const facePeople = curFace;
const activeTabPeople = (curTabs.find(t => t[0] === curView || curParent[curView] === t[0]) || [])[0];

// Alternar face a partir de #people
const switchFromPeople = ((curFace === "portfolio" || location.hash.startsWith("#pf/") || location.hash === "#people" || location.hash.startsWith("#person/")) ? "execucao" : "portfolio");

// 2. Rota #person/marina-demo
location.hash = "#person/marina-demo";
window.BRAIN.route();
const facePerson = curFace;
const activeTabPerson = (curTabs.find(t => t[0] === curView || curParent[curView] === t[0]) || [])[0];

// Alternar face a partir de #person/marina-demo
const switchFromPerson = ((curFace === "portfolio" || location.hash.startsWith("#pf/") || location.hash === "#people" || location.hash.startsWith("#person/")) ? "execucao" : "portfolio");

console.log(JSON.stringify({
  facePeople,
  activeTabPeople,
  switchFromPeople,
  facePerson,
  activeTabPerson,
  switchFromPerson
}));
"""
        proc = subprocess.run([node, "-e", script, str(ROOT)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Node script falhou:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        res = json.loads(proc.stdout)
        self.assertEqual(res["facePeople"], "portfolio")
        self.assertEqual(res["activeTabPeople"], "people")
        self.assertEqual(res["switchFromPeople"], "execucao")
        self.assertEqual(res["facePerson"], "portfolio")
        self.assertEqual(res["activeTabPerson"], "people")
        self.assertEqual(res["switchFromPerson"], "execucao")

    def test_tui_panels_and_person_jump(self):
        """TUI store.py e BrainApp: Registro da Execução sem Pessoas, Portfólio com Pessoas no final, e jump para marina-demo."""
        self.assertNotIn("Pessoas", PANELS_EXEC[5][1])
        self.assertEqual(PANELS_EXEC[5][1], ["Decisões", "Entregas", "Artefatos"])
        self.assertEqual(PANELS_PORT[5][1][-1], "Pessoas")
        self.assertEqual(PANELS_PORT[5][1], ["Áreas", "Documentos", "Pessoas"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "inst"
            with contextlib.redirect_stdout(io.StringIO()):
                demo_cli(argparse.Namespace(dir=str(root), open=False))
            inst = config.load(root)
            store = Store(inst)
            loc = store.locate("marina-demo")
            self.assertEqual(loc, (1, 5, 2))

            app = BrainApp(inst)

            async def run_jump():
                async with app.run_test(size=(140, 44)) as pilot:
                    await pilot.pause(0.4)
                    app.jump("marina-demo")
                    await pilot.pause(0.2)
                    self.assertEqual((app.face, app.p, app.tab[5]), (1, 5, 2))
                    self.assertEqual(app.cur().id, "marina-demo")

            asyncio.run(run_jump())


if __name__ == "__main__":
    unittest.main()
