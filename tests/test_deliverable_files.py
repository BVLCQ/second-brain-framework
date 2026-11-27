"""Arquivos por nível: o artefato pode apontar o entregável que sustenta (`brain artifact --deliverable`).

- o entregável lista só os artefatos ligados a ele (não herda a lista do projeto);
- o projeto continua listando todos (o painel separa os "do projeto" pelo campo);
- o artefato e o bruto dele viram um documento só (o artefato leva `raw`, o bruto leva `of`);
- evento antigo, sem o campo, continua valendo (fica no nível do projeto).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, linked, model, util  # noqa: E402
from brainlib.core import Brain  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GOALS = """# PLANNING

## GOAL-1 — Abrir a padaria nova
- status: ativo
- horizonte: 2026-12-31

### PROJ-1 — Reforma
- status: ativo
- dono: eu
- [ ] PROJ-1.1 Projeto aprovado · prazo: 2026-10-30
- [ ] PROJ-1.2 Obra · prazo: 2026-11-30

### PROJ-2 — Cardápio
- status: ativo
- dono: eu
- [ ] PROJ-2.1 Receitas testadas · prazo: 2026-11-15
"""


def _inst(td: str) -> Path:
    root = Path(td)
    (root / "config").mkdir()
    (root / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
    for sub in ("PLANNING", "RAW/inbox", "RAW/2026/10/documents", "RAW/2026/10/meetings", "PROCESSED/2026/10", "FRESH"):
        (root / "vault" / sub).mkdir(parents=True)
    (root / "vault" / "PLANNING" / "goals.md").write_text(GOALS, encoding="utf-8")
    for rel in ("RAW/2026/10/documents/planta.pdf", "RAW/2026/10/meetings/obra.md", "RAW/2026/10/documents/receitas.xlsx"):
        (root / "vault" / rel).write_bytes(b"demo\n")
    for rel in ("PROCESSED/2026/10/planta.md", "PROCESSED/2026/10/obra.md", "PROCESSED/2026/10/receitas.md",
                "PROCESSED/2026/10/antigo.md"):
        (root / "vault" / rel).write_text("# resumo\n", encoding="utf-8")
    b = Brain(config.load(root))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner", "data": {"name": "Dona", "relation": "dono"}})
    return root


def _brain(root: Path, *argv: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, BRAIN_HOME=str(root))
    env.pop("BRAIN_NIGHTLY", None)
    return subprocess.run([sys.executable, str(ROOT / "brain"), *argv], env=env, capture_output=True, text=True)


class ArtifactDeliverableTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = _inst(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _art(self, rel, raw, *extra):
        return _brain(self.root, "artifact", rel, "--kind", "documento", "--title", Path(rel).stem,
                      "--raw", raw, "--prov", "doc", "--source", raw, *extra)

    def test_cli_grava_o_entregavel_e_traz_o_projeto(self):
        r = self._art("PROCESSED/2026/10/planta.md", "RAW/2026/10/documents/planta.pdf", "--deliverable", "P1.1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PROJ-1.1", r.stdout)                                     # ID antigo aceito na entrada
        art = Brain(config.load(self.root)).state.artifacts["PROCESSED/2026/10/planta.md"]
        self.assertEqual(art.deliverable, "PROJ-1.1")
        self.assertEqual(art.projects, ["PROJ-1"])                              # o projeto do entregável vem junto

    def test_entregavel_que_nao_existe_e_recusado(self):
        r = self._art("PROCESSED/2026/10/planta.md", "RAW/2026/10/documents/planta.pdf", "--deliverable", "PROJ-9.9")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("não é entregável", r.stdout + r.stderr)
        self.assertNotIn("PROCESSED/2026/10/planta.md", Brain(config.load(self.root)).state.artifacts)

    def test_entregavel_fora_dos_projetos_do_evento_e_recusado(self):
        b = Brain(config.load(self.root))
        with self.assertRaises(util.BrainError) as cm:
            b.record_one({"type": "artifact.added", "id": "PROCESSED/2026/10/planta.md", "by": "agent", "prov": "doc",
                          "source": "RAW/2026/10/documents/planta.pdf",
                          "data": {"kind": "documento", "title": "Planta", "projects": ["PROJ-2"], "deliverable": "PROJ-1.1"}})
        self.assertIn("precisa estar em projects", str(cm.exception))

    def test_evento_antigo_sem_o_campo_fica_no_projeto(self):
        b = Brain(config.load(self.root))
        b.record_one({"type": "artifact.added", "id": "PROCESSED/2026/10/antigo.md", "by": "agent", "prov": "doc", "source": "chat",
                      "data": {"kind": "documento", "title": "Antigo", "projects": ["PROJ-1"]}})
        self.assertEqual(Brain(config.load(self.root)).state.artifacts["PROCESSED/2026/10/antigo.md"].deliverable, "")


class LinkedByLevelTests(unittest.TestCase):
    """O mesmo `linked.collect` serve o painel e a TUI: o nível decide o que entra."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = _inst(self._td.name)
        for rel, raw, extra in (
            ("PROCESSED/2026/10/planta.md", "RAW/2026/10/documents/planta.pdf", ["--deliverable", "PROJ-1.1"]),
            ("PROCESSED/2026/10/obra.md", "RAW/2026/10/meetings/obra.md", ["--projects", "PROJ-1"]),
            ("PROCESSED/2026/10/receitas.md", "RAW/2026/10/documents/receitas.xlsx", ["--deliverable", "PROJ-2.1"]),
        ):
            r = _brain(self.root, "artifact", rel, "--kind", "documento", "--title", Path(rel).stem, "--raw", raw,
                       "--prov", "doc", "--source", raw, *extra)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.m = model.build(Brain(config.load(self.root)))

    def tearDown(self):
        self._td.cleanup()

    def _proj(self, pid):
        return next(p for p in self.m["projects"] if p["id"] == pid)

    def _deliv(self, did):
        return next(d for d in self._proj(did.split(".")[0])["deliverables"] if d["id"] == did)

    def test_entregavel_so_ve_o_que_e_dele(self):
        self.assertEqual([f["rel"] for f in self._deliv("PROJ-1.1")["files"] if f["kind"] == "artefato"],
                         ["PROCESSED/2026/10/planta.md"])
        self.assertEqual(self._deliv("PROJ-1.2")["files"], [])                 # antes: herdava os 4 arquivos do projeto

    def test_projeto_ve_todos_e_o_painel_separa_pelo_campo(self):
        arts = {f["rel"]: f for f in self._proj("PROJ-1")["files"] if f["kind"] == "artefato"}
        self.assertEqual(set(arts), {"PROCESSED/2026/10/planta.md", "PROCESSED/2026/10/obra.md"})
        self.assertEqual(arts["PROCESSED/2026/10/planta.md"]["deliverable"], "PROJ-1.1")
        self.assertNotIn("deliverable", arts["PROCESSED/2026/10/obra.md"])  # sem entregável: "do projeto"
        self.assertNotIn("PROCESSED/2026/10/receitas.md", arts)

    def test_artefato_e_bruto_viram_um_documento(self):
        files = self._deliv("PROJ-1.1")["files"]
        art = next(f for f in files if f["kind"] == "artefato")
        raw = next(f for f in files if f["kind"] == "RAW")
        self.assertEqual(art["raw"], "RAW/2026/10/documents/planta.pdf")
        self.assertEqual(raw["of"], art["rel"])
        self.assertEqual(raw["ext"], "pdf")                                     # o chip mostra a extensão, nunca o app

    def test_goal_soma_os_projetos(self):
        g = next(x for x in self.m["goals"] if x["id"] == "GOAL-1")
        rels = {f["rel"] for f in g["files"] if f["kind"] == "artefato"}
        self.assertEqual(rels, {"PROCESSED/2026/10/planta.md", "PROCESSED/2026/10/obra.md", "PROCESSED/2026/10/receitas.md"})

    def test_bruto_citado_antes_ganha_o_vinculo(self):
        inst = config.load(self.root)
        arts = [{"id": "PROCESSED/2026/10/planta.md", "title": "Planta", "raw": "RAW/2026/10/documents/planta.pdf",
                 "projects": ["PROJ-1"], "deliverable": "PROJ-1.1"}]
        out = linked.collect(inst, {}, arts, sources=("RAW/2026/10/documents/planta.pdf", "PROCESSED/2026/10/planta.md"))
        raw = next(f for f in out if f["rel"] == "RAW/2026/10/documents/planta.pdf")
        self.assertEqual(raw["of"], "PROCESSED/2026/10/planta.md")
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
