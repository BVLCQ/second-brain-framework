"""#171: a barra do painel ganha seções (A) e move Sugestões (D) e Fontes (D2)."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _array(content, name):
    m = re.search(r"const %s = (\[[\s\S]*?\]);" % name, content)
    return m.group(1) if m else ""


class SidebarGroupTests(unittest.TestCase):
    def test_secoes_e_mudanca_de_face_no_core_e_no_html(self):
        core = (ROOT / "brainlib/assets/src/core.js").read_text(encoding="utf-8")
        html = (ROOT / "brainlib/assets/dashboard.html").read_text(encoding="utf-8")
        for label, content in (("core.js", core), ("dashboard.html", html)):
            exec_tabs = _array(content, "TABS_EXEC")
            cfg = _array(content, "TABS_CFG")
            self.assertIn('["", "Agora"]', exec_tabs, label)
            self.assertIn('["", "Atenção"]', exec_tabs, label)
            self.assertIn('["", "Registro"]', exec_tabs, label)
            self.assertLess(exec_tabs.find('"todo"'), exec_tabs.find('"wins"'), label)
            self.assertLess(exec_tabs.find('"focus"'), exec_tabs.find('"timeline"'), label)
            self.assertLess(exec_tabs.find('"outbox"'), exec_tabs.find('"wins"'), label)
            self.assertNotIn('"feedback"', exec_tabs, label)
            self.assertIn('"badge"', exec_tabs, label)
            self.assertLess(cfg.find('"cfg/conectores"'), cfg.find('"sources"'), label)
            self.assertLess(cfg.find('"sources"'), cfg.find('"cfg/memoria"'), label)
            self.assertIn('"feedback"', cfg, label)
            self.assertIn("v === \"sources\" || v === \"feedback\"", content, label)

    def test_rotulo_nao_e_link_e_badge_some_sem_falha(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node ausente")
        script = r"""
const fs = require("fs");
const extra = fs.readFileSync(process.argv[1], "utf8");
const fn = extra.match(/window\.renderTabs = function\(view, TABS, PARENT\)\{[\s\S]*?\n\};/);
if (!fn) { console.error("renderTabs ausente"); process.exit(2); }
let html = "";
const document = { getElementById(){ return { set innerHTML(v){ html = v; } }; } };
const window = {};
eval(fn[0].replace("window.renderTabs", "window.renderTabs"));
window.renderTabs("home", [["sources", "Fontes", () => 0, "badge"], ["", "Agora"], ["home", "Início"]], {});
const quiet = html;
window.renderTabs("home", [["sources", "Fontes", () => 2, "badge"], ["", "Agora"]], {});
const loud = html;
console.log(JSON.stringify({quiet, loud}));
"""
        proc = subprocess.run(
            [node, "-e", script, str(ROOT / "brainlib/assets/src/extra.js")],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout)
        self.assertIn('<div class="nav-sec">Agora</div>', got["quiet"])
        self.assertNotIn("<a", got["quiet"].split("Agora")[0])
        self.assertNotIn("sources", got["quiet"])
        self.assertIn('href="#sources"', got["loud"])
        self.assertIn(">2</span>", got["loud"])
        self.assertIn('<div class="nav-sec">Agora</div>', got["loud"])
