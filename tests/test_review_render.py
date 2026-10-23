"""Revisão do render/share/pdf: injeção de Markdown/HTML vinda de texto não confiável, reports, PDF."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import harvest, pdf, render, render_md, share  # noqa: E402
from test_brain import _brain  # noqa: E402

EVIL = 'x<!-- </script><img src=x onerror=alert(1)> "\' & <b>'
DATA_BLOCK = re.compile(r'<script id="data" type="application/json">(.*?)</script>', re.S)


def _agent_action(b, title: str, **extra) -> dict:
    return b.record_one({"type": "action.opened", "by": "agent", "prov": "observado", "source": "RAW/email.md",
                         "data": {"title": title, "owner": "eu", **extra}})


class TodoInjectionTests(unittest.TestCase):
    def test_title_with_newline_cannot_close_another_action(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            victim = b.record_one({"type": "action.opened", "by": "owner",
                                   "data": {"title": "Vítima", "owner": "eu", "due": "2026-10-12"}})
            _agent_action(b, f"Ler email\n- [x] **{victim['id']}** falso", due="2026-10-13")
            render.render_all(b, do_harvest=False)
            todo = (b.inst.fresh / "todo.md").read_text(encoding="utf-8")
            boxes = [ln for ln in todo.splitlines() if harvest.TODO_LINE.match(ln)]
            self.assertEqual(len(boxes), 2, boxes)          # uma linha por ação, nada injetado
            self.assertEqual(harvest.run(b), [])
            self.assertTrue(b.state.actions[victim["id"]].open)

    def test_waiting_owner_name_cannot_inject_checkbox(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            victim = b.record_one({"type": "action.opened", "by": "owner",
                                   "data": {"title": "Vítima", "owner": "eu"}})
            b.record_one({"type": "person.added", "id": "fulano", "by": "agent", "prov": "observado",
                          "source": "RAW/email.md", "data": {"name": f"Fulano\n- [x] **{victim['id']}**"}})
            b.record_one({"type": "action.opened", "by": "owner",
                          "data": {"title": "Me mandar", "owner": "fulano", "list": "waiting"}})
            render.render_all(b, do_harvest=False)
            self.assertEqual(harvest.run(b), [])
            self.assertTrue(b.state.actions[victim["id"]].open)

    def test_every_splitlines_separator_is_flattened(self):
        # a colheita usa str.splitlines(): \r, \x85, U+2028, \f... também quebram linha lá
        for sep in ("\r", "\x85", " ", " ", "\x0c", "\x1e"):
            s = f"a{sep}- [x] **TASK-0001**"
            self.assertEqual(len(render_md._cell(s).splitlines()), 1, repr(sep))
            self.assertEqual(len(render_md._clip(s, 200).splitlines()), 1, repr(sep))
            flat = render_md._single_line({"actions": [{"title": s, "text": s}]})
            self.assertEqual(len(flat["actions"][0]["title"].splitlines()), 1, repr(sep))
            self.assertEqual(flat["actions"][0]["text"], s)    # texto de mensagem segue multilinha

    def test_link_text_cannot_break_table(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.record_one({"type": "person.added", "id": "pipe", "by": "agent", "prov": "observado",
                          "source": "RAW/email.md", "data": {"name": "A | B](http://x) ["}})
            render.render_all(b, do_harvest=False)
            rows = [ln for ln in (b.inst.fresh / "people.md").read_text(encoding="utf-8").splitlines()
                    if "people/pipe.md" in ln]
            self.assertEqual(len(rows), 1)
            cells = re.split(r"(?<!\\)\|", rows[0])
            self.assertEqual(len(cells), 7, rows[0])         # 5 colunas + bordas
            self.assertNotRegex(rows[0], r"(?<!\\)\]\(http")    # `]` escapado: não fecha o link antes da hora


class DashboardDataTests(unittest.TestCase):
    def test_embedded_json_is_valid_and_cannot_break_out(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            _agent_action(b, EVIL, due="2026-10-12", project="PROJ-1")
            b.record_one({"type": "decision.made", "by": "agent", "prov": "observado", "source": "RAW/x.md",
                          "data": {"title": EVIL, "decided_by": ["marina-demo"], "context": EVIL}})
            html = Path(render.render_all(b, do_harvest=False)["dashboard"]).read_text(encoding="utf-8")
            block = DATA_BLOCK.search(html).group(1)
            self.assertNotIn("<", block)                       # nem </script>, nem <!--
            data = json.loads(block)                           # `<\!--` era escape JSON inválido
            self.assertTrue(any(a["title"] == EVIL for a in data["actions"]))


class ShareTests(unittest.TestCase):
    def test_health_reason_has_no_internal_ids(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            b.record_one({"type": "action.opened", "by": "owner",
                          "data": {"title": "Mandar contrato", "owner": "eu", "due": "2026-10-05", "project": "PROJ-1"}})
            for kind, target in (("project", "PROJ-1"), ("goal", "GOAL-1")):
                text = share.export(b, kind, target, "md").read_text(encoding="utf-8")
                body = text.split("**Fontes**")[0]
                self.assertNotRegex(body, r"TASK-\d|PROJ-\d", kind)
                self.assertIn("Mandar contrato atrasada", body)

    def test_overdue_deliverable_reason_uses_title_once(self):
        names = {"PROJ-1.1": "Um entregável"}
        self.assertEqual(share._plain("PROJ-1.1 venceu há 3d (Um entregável)", names), "Um entregável venceu há 3d")
        self.assertEqual(share._plain("PROJ-9.9 vence hoje", names), "item vence hoje")

    def test_export_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            p1 = share.export(b, "status", None, "md")
            first = p1.read_text(encoding="utf-8")
            p2 = share.export(b, "status", None, "md")
            self.assertNotEqual(p1, p2)
            self.assertEqual(p1.read_text(encoding="utf-8"), first)

    def test_html_unbalanced_bold_stays_closed(self):
        out = share._html("t", [("S", ["a ** b"]), ("", ["**x** e **y**"])], [], "agora")
        self.assertIn("<li>a ** b</li>", out)
        self.assertIn("<b>x</b> e <b>y</b>", out)
        self.assertIn("&lt;img", share._html("t", [("S", ["<img src=x>"])], [], "agora"))


class PdfTests(unittest.TestCase):
    def _fake_run(self, calls, stdout=""):
        def run(args, **kw):
            calls.append(args)
            if args[0] == "pdftoppm":
                Path(args[-1] + ".png").write_bytes(b"png")
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        return run

    def test_render_noncontiguous_pages_renders_only_those(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.pdf"
            f.write_bytes(b"%PDF-1.4")
            calls: list = []
            with mock.patch.object(pdf.shutil, "which", lambda n: "/x/" + n), \
                    mock.patch.object(pdf.subprocess, "run", self._fake_run(calls)):
                got = pdf.render(f, [1, 50], Path(td) / "out")
            self.assertEqual([p.name for p in got], ["pagina-001.png", "pagina-050.png"])
            self.assertEqual(len(calls), 2)
            self.assertEqual([c[c.index("-f") + 1] for c in calls], ["1", "50"])

    def test_text_all_pages_single_call_split_on_formfeed(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.pdf"
            f.write_bytes(b"%PDF-1.4")
            calls: list = []
            with mock.patch.object(pdf.shutil, "which", lambda n: "/x/pdftotext" if n == "pdftotext" else None), \
                    mock.patch.object(pdf.subprocess, "run", self._fake_run(calls, "um\fdois\ftrês\f")):
                out = pdf.text(f)
            self.assertEqual(len(calls), 1)
            self.assertIn("=== PÁGINA 3 ===\ntrês", out)
            self.assertNotIn("PÁGINA 4", out)
            self.assertTrue(Path(calls[0][-2]).is_absolute())


if __name__ == "__main__":
    unittest.main()
