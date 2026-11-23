"""Testes de regressão para dossiê de decisão, promoção, roteador, one-pager e funil (#90, #91, #81)."""
from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import cli_portfolio, config, dossier, index, onepager, portfolio, route, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH", "reports"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona Demo"\n\n[memory]\nengine = "none"\n',
        encoding="utf-8",
    )
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Abrir segundo ponto\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: crescer\n\n"
        "### PROJ-1 — Reforma da galeria\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Instalar forno · prazo: 2026-10-20 · peso: 2\n",
        encoding="utf-8",
    )
    return config.load(tmp)


def _brain(tmp: Path) -> Brain:
    b = Brain(_inst(tmp))
    today = util.today().isoformat()
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona Demo", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Mari-demo"], "email": "marina-demo@example.com"}})
    b.record_one({"type": "area.added", "id": "operacoes", "by": "owner",
                  "data": {"name": "Operações"}})
    b.record_one({"type": "opportunity.added", "by": "owner", "date": today,
                  "data": {"title": "Automatizar triagem", "area": "operacoes", "problem": "fila manual"}})
    index.rebuild(b)
    return b


class _FakeHS:
    def __init__(self):
        self.calls: list[tuple[str, str, list[str] | None]] = []

    def recall(self, bank: str, query: str, tags: list[str] | None = None) -> dict:
        self.calls.append((bank, query, tags))
        return {"results": [{"text": "Trecho sobre a galeria", "document_id": "RAW/ata.md", "occurred_start": "2026-10-01"}]}


class TestDossierDecision(unittest.TestCase):
    def test_decision_ref_builds_decision_dossier(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            today = util.today().isoformat()
            dec1 = b.record_one({
                "type": "decision.made", "by": "owner", "date": today,
                "data": {
                    "title": "Escolher galeria central",
                    "decided_by": ["marina-demo"],
                    "project": "PROJ-1",
                    "context": "Aluguel da esquina subiu",
                    "rationale": "Fluxo maior na galeria",
                },
            })
            dec2 = b.record_one({
                "type": "decision.made", "by": "owner", "date": today,
                "data": {
                    "title": "Revisar fachada da galeria",
                    "decided_by": ["eu"],
                    "project": "PROJ-1",
                },
            })
            act = b.record_one({
                "type": "action.opened", "by": "owner", "date": today,
                "data": {"title": "Assinar contrato", "owner": "eu", "project": "PROJ-1"},
            })
            b.record_one({
                "type": "delivery.recorded", "by": "owner", "date": today,
                "data": {"title": "Contrato assinado", "result": "ok", "ref": act["id"]},
            })
            index.rebuild(b)

            hs = _FakeHS()
            d = dossier.build(b, dec1["id"], hs=hs)
            self.assertEqual((d["kind"], d["id"]), ("decision", dec1["id"]))
            self.assertEqual(d["ficha"]["title"], "Escolher galeria central")
            self.assertEqual(d["ficha"]["decided_by_names"], ["Marina-demo"])
            self.assertEqual(d["ficha"]["project"], "PROJ-1")
            self.assertEqual(d["ficha"]["rationale"], "Fluxo maior na galeria")
            self.assertEqual([x["id"] for x in d["decisions"]], [dec2["id"]])
            self.assertEqual([x["title"] for x in d["deliveries"]], ["Contrato assinado"])
            self.assertEqual(hs.calls[-1][2], ["proj:PROJ-1"])

            md = dossier.render(d)
            self.assertIn("Escolher galeria central", md)
            self.assertIn("Marina-demo", md)
            self.assertIn("Fluxo maior na galeria", md)
            self.assertNotIn("PLANNING/goals.md", md)

            # forma legada D-1 e formas curtas de planejamento continuam via ids.normalize
            d_legacy = dossier.build(b, "D-1")
            self.assertEqual((d_legacy["kind"], d_legacy["id"]), ("decision", "DEC-0001"))
            self.assertEqual(dossier.build(b, "G1")["id"], "GOAL-1")
            self.assertEqual(dossier.build(b, "P1")["id"], "PROJ-1")
            self.assertEqual(dossier.build(b, "Mari-demo")["id"], "marina-demo")

            with self.assertRaises(util.BrainError):
                dossier.build(b, "DEC-9999")


class TestPromoteDeliverableRollback(unittest.TestCase):
    def _args(self, **kw) -> argparse.Namespace:
        defaults = {
            "id": "OPP-0001", "level": "deliverable", "goal": None, "project": "PROJ-1",
            "title": None, "reason": None, "evidence": "ata", "approval": "ok", "json": False,
        }
        defaults.update(kw)
        return argparse.Namespace(**defaults)

    def test_log_oserror_and_base_exception_restore_goals_file(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            before = b.inst.planning_file.read_bytes()
            with mock.patch.object(cli_portfolio, "_append_plan_log", side_effect=OSError("disco cheio")):
                with self.assertRaisesRegex(OSError, "disco cheio"):
                    cli_portfolio._promote(self._args(), b)
            self.assertEqual(b.inst.planning_file.read_bytes(), before)

            with tempfile.TemporaryDirectory() as td2:
                b2 = _brain(Path(td2))
                before2 = b2.inst.planning_file.read_bytes()
                with mock.patch.object(cli_portfolio, "_append_plan_log", side_effect=KeyboardInterrupt()):
                    with self.assertRaises(KeyboardInterrupt):
                        cli_portfolio._promote(self._args(), b2)
                self.assertEqual(b2.inst.planning_file.read_bytes(), before2)


class TestPromoteMissingFlagMessage(unittest.TestCase):
    def test_missing_goal_and_project_messages(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            for level, flag in (("project", "--goal"), ("deliverable", "--project")):
                args = argparse.Namespace(
                    id="OPP-0001", level=level, goal=None, project=None,
                    title=None, reason=None, evidence=None, approval="ok", json=False,
                )
                with self.assertRaises(util.BrainError) as ctx:
                    cli_portfolio._promote(args, b)
                self.assertEqual(ctx.exception.code, 3)
                self.assertIn(f"exige {flag}", str(ctx.exception))
                self.assertNotIn("None", str(ctx.exception))


class TestRouteHygiene(unittest.TestCase):
    def test_ids_exist_called_once(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            today = util.today().isoformat()
            act = b.record_one({
                "type": "action.opened", "by": "owner", "date": today,
                "data": {"title": "Checar estoque", "owner": "eu"},
            })
            index.rebuild(b)
            db_path = index.db_path(b.inst)
            with mock.patch("brainlib.route._ids_exist", wraps=route._ids_exist) as spy:
                res = route.classify(f"como está {act['id']}?", db=db_path)
            self.assertEqual(spy.call_count, 1)
            self.assertEqual(res["route"], "ledger")
            self.assertEqual(res["ids"], [act["id"]])

    def test_short_token_not_matched_without_index(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            db_path = index.db_path(b.inst)
            with mock.patch("brainlib.route._find_db", return_value=None):
                res1 = route.classify("bug P1 urgente")
                res2 = route.classify("o que é G1?")
                res3 = route.classify("ver TASK-0001")
                res4 = route.classify("ver P1 e PROJ-1")
            self.assertEqual(res1["ids"], [])
            self.assertIsNone(res1["route"])
            self.assertEqual(res2["ids"], [])
            self.assertIsNone(res2["route"])
            self.assertEqual(res3["ids"], ["TASK-0001"])
            self.assertEqual(res3["route"], "ledger")
            self.assertEqual(res4["ids"], ["PROJ-1"])
            self.assertEqual(res4["route"], "ledger")

            res_idx = route.classify("como vai P1?", db=db_path)
            self.assertEqual(res_idx["ids"], ["PROJ-1"])
            self.assertEqual(res_idx["route"], "ledger")


class TestOnepagerIdRegex(unittest.TestCase):
    def test_one_to_five_digit_ids_matched_and_linked(self):
        hits = onepager.ID_RE.findall("ver OPP-1, OPP-0023, OPP-10000, TASK-12345 e OPP-123456")
        self.assertEqual(hits, [("OPP", "1"), ("OPP", "0023"), ("OPP", "10000"), ("TASK", "12345")])

        fake_b = SimpleNamespace(
            state=SimpleNamespace(
                opportunities={
                    "OPP-0001": SimpleNamespace(title="Atual", docs=[], source="chat", evidence=[]),
                    "OPP-10000": SimpleNamespace(
                        title="Escala de pedidos",
                        docs=[SimpleNamespace(kind="one-pager", ref="doc-10000")],
                    ),
                },
                processes={}, actions={}, decisions={}, deliveries={}, proposals={}, artifacts={},
            )
        )
        lk = onepager.links(fake_b, "OPP-0001", {"relacionado": "ver OPP-10000"})
        self.assertEqual(lk, {"OPP-10000: Escala de pedidos": onepager.DOC_URL.format("doc-10000")})

        expanded = onepager.expand_detail(
            fake_b,
            "Ver OPP-10000 e manter [OPP-10000: custom](https://example.com/keep)",
        )
        self.assertIn(f"[OPP-10000: Escala de pedidos]({onepager.DOC_URL.format('doc-10000')})", expanded)
        self.assertIn("[OPP-10000: custom](https://example.com/keep)", expanded)


class TestPortfolioFunnel(unittest.TestCase):
    def test_unknown_status_ignored(self):
        opps = [
            SimpleNamespace(status="ideia"),
            SimpleNamespace(status="priorizada"),
            SimpleNamespace(status="estranho"),
        ]
        res = portfolio.funnel(opps)
        self.assertEqual(list(res.keys()), list(portfolio.FUNNEL_ORDER))
        self.assertNotIn("estranho", res)
        self.assertEqual((res["ideia"], res["priorizada"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
