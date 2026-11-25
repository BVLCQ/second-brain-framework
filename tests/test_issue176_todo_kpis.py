"""Cartões da visão geral do TODO filtram o quadro, com seleção múltipla (#176)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORE = ROOT / "brainlib" / "assets" / "src" / "core.js"


def _fn(src: str) -> str:
    m = re.search(r"function todoKpiHit\(a, key, recent\)\{.*?\n\}", src, re.S)
    if not m:
        raise AssertionError("todoKpiHit não está em core.js")
    return m.group(0)


def _hit(actions: list[dict], key: str, today: str = "2026-11-25") -> list[bool]:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node ausente")
    script = (
        _fn(CORE.read_text(encoding="utf-8"))
        + "\nconst recent = new Date(" + json.dumps(today) + " + 'T12:00:00');"
        + "\nrecent.setDate(recent.getDate() - 14);"
        + "\nconst actions = " + json.dumps(actions) + ";"
        + "\nprocess.stdout.write(JSON.stringify(actions.map(a => todoKpiHit(a, "
        + json.dumps(key) + ", recent))));"
    )
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


class TodoKpiFilterTests(unittest.TestCase):
    def test_source_wires_cards_as_toggles(self):
        src = CORE.read_text(encoding="utf-8")
        self.assertIn('data-kpi="', src)
        self.assertIn("aria-pressed", src)
        self.assertIn('id="kpiclear"', src)
        self.assertIn('q.get("k")', src)
        self.assertIn('k !== "outros" && todoKpiHit(a, k, recent)', src)

    def test_overdue_is_atrasada_not_vencendo(self):
        late = {"list": "mine", "open": True, "parked": False, "overdue_days": 3,
                "status": "aberta", "due_in": -3}
        soon = {"list": "mine", "open": True, "parked": False, "overdue_days": 0,
                "status": "fazendo", "due_in": 4}
        self.assertEqual(_hit([late, soon], "atrasadas"), [True, False])
        self.assertEqual(_hit([late, soon], "vencem"), [False, True])
        self.assertEqual(_hit([late, soon], "fazendo"), [False, True])

    def test_parked_depois_and_waiting_outros_stay_apart(self):
        parked = {"list": "mine", "open": True, "parked": True, "status": "aberta"}
        waiting = {"list": "waiting", "open": True, "parked": False, "status": "aberta", "overdue_days": 2}
        self.assertEqual(_hit([parked, waiting], "depois"), [True, False])
        self.assertEqual(_hit([parked, waiting], "abertas"), [False, False])
        self.assertEqual(_hit([parked, waiting], "outros"), [False, True])
        self.assertEqual(_hit([parked, waiting], "atrasadas"), [False, False])

    def test_feitas_14d_ignores_older_closed(self):
        fresh = {"list": "mine", "open": False, "status": "fechada", "closed": "2026-11-20"}
        old = {"list": "mine", "open": False, "status": "fechada", "closed": "2026-10-01"}
        self.assertEqual(_hit([fresh, old], "feitas"), [True, False])
