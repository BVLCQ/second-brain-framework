"""Testes da varredura de nits (Issue #100, opção A).

Escala de padding por papel (listas 12px, brief 14px, matriz 8px), altura do
botão tiny alinhada ao primário (29px), classe própria para as ações do feed e
guard de chip com modificador fora do vocabulário (avisa, não silencia).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORE_JS = ROOT / "brainlib" / "assets" / "src" / "core.js"
DASHBOARD_CSS = ROOT / "brainlib" / "assets" / "src" / "dashboard.css"
DASHBOARD_HTML = ROOT / "brainlib" / "assets" / "dashboard.html"

CHIP_STUB = """
const esc = s => String(s);
const STAGES_PIPE = ["ideia","triagem","priorizada","em-andamento","piloto","validando","entregue"];
const STAGES_LAT = ["em-espera","descartada"];
const warns = [];
const console = { warn: (...a) => warns.push(a.join(" ")) };
"""

class PaddingScaleTests(unittest.TestCase):
    def test_escala_por_papel(self):
        css = DASHBOARD_CSS.read_text(encoding="utf-8")
        self.assertRegex(css, re.compile(r"\.card\{[^}]*padding:12px 14px"))
        self.assertRegex(css, re.compile(r"\.card\.mini\{padding:8px 10px\}"))
        self.assertRegex(css, re.compile(r"\.brief-card\{padding:14px 16px"))

    def test_botao_tiny_alinhado_ao_primario(self):
        css = DASHBOARD_CSS.read_text(encoding="utf-8")
        self.assertRegex(css, re.compile(r"\.btn\.tiny\{[^}]*min-height:29px"))

    def test_classe_das_acoes_do_feed(self):
        src = CORE_JS.read_text(encoding="utf-8")
        self.assertEqual(src.count('class="feed-act"'), 4)  # decidir, ver, revisar, responder
        css = DASHBOARD_CSS.read_text(encoding="utf-8")
        self.assertIn(".feed a.feed-act{", css)
        built = DASHBOARD_HTML.read_text(encoding="utf-8")
        self.assertIn("feed-act", built)


class ChipGuardTests(unittest.TestCase):
    def _eval_chip(self) -> dict:
        src = CORE_JS.read_text(encoding="utf-8")
        lv_start = src.index("const CHIP_LEVELS")
        lv_end = src.index("]);", lv_start) + 3
        levels_stmt = src[lv_start:lv_end]
        chip_start = src.index("const chip = (level")
        chip_end = src.index("const idc = id =>")
        harness = (CHIP_STUB + levels_stmt + "\n" + src[chip_start:chip_end] +
                   '\nconst _pre = warns.slice();'
                   '\nprocess.stdout.write(JSON.stringify({empty: chip("", "x"), known: chip("em-risco", "y"),'
                   '\n  sStage: chip("s-priorizada", "z"), unknown: chip("nova-cor", "w"), warns, warnsBefore: _pre}));')
        proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_modificador_vazio_nao_gera_classe_morta(self):
        r = self._eval_chip()
        self.assertEqual(r["empty"], '<span class="chip">x</span>')

    def test_nivel_conhecido_nao_avisa(self):
        r = self._eval_chip()
        self.assertIn("h-em-risco", r["known"])
        self.assertIn("h-s-priorizada", r["sStage"])
        self.assertEqual(r["warnsBefore"], [])

    def test_nivel_desconhecido_avisa(self):
        r = self._eval_chip()
        self.assertIn("h-nova-cor", r["unknown"])  # segue renderizando (estilo base)…
        self.assertEqual(len(r["warns"]), 1)       # …mas não em silêncio
        self.assertIn("nova-cor", r["warns"][0])


if __name__ == "__main__":
    unittest.main()
