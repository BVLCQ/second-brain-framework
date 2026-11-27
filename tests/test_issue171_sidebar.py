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
            def order(tabs, *keys):
                pos = [tabs.find('"%s"' % k) for k in keys]
                self.assertNotIn(-1, pos, f"{label}: faltou item em {keys}")
                self.assertEqual(pos, sorted(pos), f"{label}: ordem esperada {keys}")

            order(exec_tabs, "home", "Agora", "todo", "ask", "Registro", "projects", "decisions", "timeline",
                  "Tools", "focus", "outbox")
            self.assertIn('"Tarefas"', exec_tabs, label)
            self.assertNotIn('"TODO"', exec_tabs, label)
            for gone in ("sources", "feedback", "wins", "Atenção", "badge"):
                self.assertNotIn('"%s"' % gone, exec_tabs, label)   # Fontes só mora em Configurações
            order(cfg, "cfg/inicio", "cfg/saude", "Conta", "cfg/perfil", "cfg/rotina", "cfg/agente", "Conexões",
                  "cfg/memoria", "cfg/conectores", "sources", "cfg/integracoes", "Melhore o App", "feedback")
            self.assertIn('"Agentes/Harness"', cfg, label)
            self.assertNotIn('"Seu agente"', cfg, label)
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

    def test_pagina_indice_e_sempre_a_primeira_de_cada_face(self):
        """Início / Visão geral abrem cada barra, sem rótulo de seção acima."""
        core = (ROOT / "brainlib/assets/src/core.js").read_text(encoding="utf-8")
        html = (ROOT / "brainlib/assets/dashboard.html").read_text(encoding="utf-8")
        for label, content in (("core.js", core), ("dashboard.html", html)):
            for name, first in (("TABS_EXEC", '["home","Início"]'), ("TABS_PF", '["pf/visao","Visão geral"]'),
                                ("TABS_CFG", '["cfg/inicio","Visão geral"]')):
                arr = re.sub(r"\s+", "", _array(content, name))
                self.assertTrue(arr.startswith("[" + re.sub(r"\s+", "", first)), f"{label}: {name} deve começar em {first}")

    def test_categoria_preta_no_claro_e_branca_no_escuro(self):
        css = (ROOT / "brainlib/assets/src/dashboard.css").read_text(encoding="utf-8")
        self.assertIn("color:var(--cat-ink)", re.search(r"nav\.side-nav \.nav-sec\{[^}]*\}", css).group(0))
        light = re.search(r":root\{[^}]*\}", css).group(0)
        dark = re.search(r"html\[data-theme=dark\]\{[^}]*\}", css).group(0)
        self.assertIn("--cat-ink:#000", light)
        self.assertIn("--cat-ink:#fff", dark)
