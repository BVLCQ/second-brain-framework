"""Testes de regressão do filtro 'todas' do TODO (Issue #22).

Garante que marcar 'todas (fechadas além de 14d)' exibe todas as ações fechadas
sem limite de data, mantendo a janela de 14 dias apenas quando desmarcado.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import util  # noqa: E402

CORE_JS_PATH = ROOT / "brainlib" / "assets" / "src" / "core.js"
DASHBOARD_HTML_PATH = ROOT / "brainlib" / "assets" / "dashboard.html"


def extract_feita_predicate(source: str) -> str:
    """Extrai o predicado da coluna Feita definido em V.todo."""
    m = re.search(r'\["Feita"[^\n]*,\s*(a\s*=>\s*[^,\n]+),\s*"fechada"\]', source)
    if not m:
        raise ValueError("Predicado da coluna Feita não encontrado no código")
    return m.group(1).strip()


def eval_feita_actions(
    predicate_src: str,
    today_iso: str,
    show_all: bool,
    actions: list[dict[str, Any]],
    node_bin: str | None = None,
    run: Callable[..., Any] = subprocess.run,
) -> list[bool]:
    """Executa o predicado JS via node para uma lista de ações com run injetável."""
    node = node_bin or shutil.which("node")
    if not node:
        raise RuntimeError("node ausente")

    script = (
        f"const M = {{ today: {json.dumps(today_iso)} }};\n"
        f"const showAll = {'true' if show_all else 'false'};\n"
        f"const recent = new Date(M.today + 'T12:00:00');\n"
        f"recent.setDate(recent.getDate() - 14);\n"
        f"const predicate = ({predicate_src});\n"
        f"const actions = {json.dumps(actions)};\n"
        f"process.stdout.write(JSON.stringify(actions.map(predicate)));\n"
    )

    res = run([node, "-e", script], capture_output=True, text=True, check=True)
    out: list[bool] = json.loads(res.stdout)
    return out


class TestTodoFilterSourceRegression(unittest.TestCase):
    """Verificações estáticas nas fontes e nos assets compilados."""

    def test_core_js_predicate_and_unconditional_recent(self):
        src = CORE_JS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("if (!showAll) recent.setDate", src)
        self.assertIn("recent.setDate(recent.getDate() - 14);", src)
        self.assertIn("(showAll || new Date(a.closed + \"T12:00:00\") >= recent)", src)

        predicate = extract_feita_predicate(src)
        self.assertTrue(
            predicate.startswith("a => a.status === \"fechada\" && a.closed && (showAll ||"),
            f"Formato inesperado do predicado extraído: {predicate}",
        )

    def test_built_dashboard_html_contains_fix(self):
        dash = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        self.assertNotIn("if (!showAll) recent.setDate", dash)
        self.assertIn("recent.setDate(recent.getDate() - 14);", dash)
        self.assertIn("(showAll || new Date(a.closed + \"T12:00:00\") >= recent)", dash)


class TestTodoFilterBehavior(unittest.TestCase):
    """Testes comportamentais do predicado executado com node."""

    def test_eval_feita_actions_accepts_custom_run(self):
        """Garante que a função aceita executor run injetável sem chamar node."""
        calls: list[list[str]] = []

        class DummyResult:
            stdout = "[true, false]"

        def fake_run(argv: list[str], **kwargs: Any) -> DummyResult:
            calls.append(argv)
            return DummyResult()

        predicate = "a => a.status === 'fechada' && a.closed && (showAll || new Date(a.closed + 'T12:00:00') >= recent)"
        res = eval_feita_actions(
            predicate_src=predicate,
            today_iso=util.now().date().isoformat(),
            show_all=False,
            actions=[{"status": "fechada", "closed": util.now().date().isoformat()}],
            node_bin="/dummy/node",
            run=fake_run,
        )
        self.assertEqual(res, [True, False])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "/dummy/node")

    def test_predicate_behavior_with_node(self):
        if not shutil.which("node"):
            self.skipTest("node ausente")

        src = CORE_JS_PATH.read_text(encoding="utf-8")
        predicate = extract_feita_predicate(src)

        today = util.now().date()
        today_iso = today.isoformat()
        closed_today = today.isoformat()
        closed_3d = (today - timedelta(days=3)).isoformat()
        closed_20d = (today - timedelta(days=20)).isoformat()
        closed_45d = (today - timedelta(days=45)).isoformat()

        action_today = {"id": "TASK-0001", "status": "fechada", "closed": closed_today}
        action_3d = {"id": "TASK-0002", "status": "fechada", "closed": closed_3d}
        action_20d = {"id": "TASK-0003", "status": "fechada", "closed": closed_20d}
        action_45d = {"id": "TASK-0004", "status": "fechada", "closed": closed_45d}
        action_open = {"id": "TASK-0005", "status": "aberta", "closed": closed_today}
        action_no_date = {"id": "TASK-0006", "status": "fechada", "closed": ""}

        actions = [
            action_today,
            action_3d,
            action_20d,
            action_45d,
            action_open,
            action_no_date,
        ]

        # Com showAll = false: 3 dias passa, 20 dias falha
        res_unchecked = eval_feita_actions(
            predicate_src=predicate,
            today_iso=today_iso,
            show_all=False,
            actions=actions,
        )
        self.assertTrue(res_unchecked[1], "Ação fechada há 3 dias deve passar com showAll=false")
        self.assertFalse(res_unchecked[2], "Ação fechada há 20 dias deve falhar com showAll=false")

        # Com showAll = true: hoje, 3 dias e 45 dias passam
        res_checked = eval_feita_actions(
            predicate_src=predicate,
            today_iso=today_iso,
            show_all=True,
            actions=actions,
        )
        self.assertTrue(res_checked[0], "Ação fechada hoje deve passar com showAll=true")
        self.assertTrue(res_checked[1], "Ação fechada há 3 dias deve passar com showAll=true")
        self.assertTrue(res_checked[3], "Ação fechada há 45 dias deve passar com showAll=true")

        # Mesmo com showAll = true, status aberta ou sem data de fechamento não entram em Feita
        self.assertFalse(res_checked[4], "Ação aberta não deve entrar em Feita")
        self.assertFalse(res_checked[5], "Ação sem closed não deve entrar em Feita")


if __name__ == "__main__":
    unittest.main()
