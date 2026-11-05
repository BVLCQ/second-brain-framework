"""Modos de memória embed/full (plano guides/plans/memory-setups.md) — stdlib unittest, sem rede."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, dossier, index, memory, util                   # noqa: E402
from brainlib.core import Brain                                            # noqa: E402

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("test_brain", ROOT / "tests" / "test_brain.py")
_tb = _ilu.module_from_spec(_spec)
spec_ok = _spec.loader.exec_module(_tb) or True
FakeHindsight = _tb.FakeHindsight


def _inst(tmp: Path) -> config.Instance:
    (tmp / "config").mkdir(parents=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True)
    (tmp / "vault" / "reports").mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n\n"
        "### PROJ-1 — Pagamentos demo\n- status: ativo\n- dono: eu\n"
        "- [ ] PROJ-1.1 Um entregável · prazo: 2026-10-20 · peso: 2\n", encoding="utf-8")
    return config.load(tmp)


def _brain(tmp: Path, mem_extra: str = "") -> Brain:
    _inst(tmp)
    if mem_extra:
        p = tmp / "config" / "brain.toml"
        extra = mem_extra.replace("[memory]\n", "", 1)           # mescla no [memory] já existente
        p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + "\n" + extra, encoding="utf-8")
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Marina-demo", "Mari-demo"], "email": "marina-demo@x.com"}})
    return b


def _raw(b: Brain, rel: str, text: str = "ata com a Marina-demo sobre o forno") -> Path:
    p = b.inst.vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class ModeTests(unittest.TestCase):
    def test_mode_derivation(self):
        self.assertEqual(memory.mode({"engine": "none"}), "none")
        self.assertEqual(memory.mode({"engine": "hindsight", "extract": False}), "embed")
        self.assertEqual(memory.mode({"engine": "hindsight", "extract": True, "cloud_llm": True}), "full")

    def test_extract_without_cloud_llm_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td), mem_extra='[memory]\nextract = true')
            with self.assertRaises(util.BrainError) as cm:
                memory.documents(b)
            self.assertIn("cloud_llm", str(cm.exception))

    def test_invalid_awaiting_dump_refused(self):
        with self.assertRaises(util.BrainError):
            memory.validate({"engine": "hindsight", "raw_awaiting_dump": "amanha"})


class SetupByModeTests(unittest.TestCase):
    def test_embed_setup_single_bank_chunks(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            hs = FakeHindsight()
            banks = memory.setup(b, hs)
            self.assertEqual(banks, ["brain"])                      # banco único (decisão 8)
            self.assertEqual(hs.configs["brain"], memory.NO_LLM_CONFIG)

    def test_full_setup_single_bank_custom_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td), mem_extra='[memory]\nextract = true\ncloud_llm = true\nraw_awaiting_dump = "hold"')
            hs = FakeHindsight()
            banks = memory.setup(b, hs)
            self.assertEqual(banks, ["brain"])
            cfg = hs.configs["brain"]
            self.assertEqual(cfg["retain_extraction_mode"], "custom")
            self.assertEqual(cfg["retain_custom_instructions"], memory.EXTRACT_INSTRUCTIONS)
            self.assertTrue(cfg["enable_observations"])
            self.assertTrue(cfg["enable_auto_consolidation"])

    def test_full_setup_refused_without_cloud_llm_contract(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td), mem_extra='[memory]\nextract = true')   # sem cloud_llm
            hs = FakeHindsight()
            with self.assertRaises(util.BrainError):
                memory.setup(b, hs, mode_="full")


def _full(td, awaiting="hold"):
    return _brain(Path(td), mem_extra=f'[memory]\nextract = true\ncloud_llm = true\nraw_awaiting_dump = "{awaiting}"')

class FullDocumentsTests(unittest.TestCase):

    def test_hold_excludes_raw_without_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            b = _full(td)
            _raw(b, "RAW/2026/10/meetings/ata-x.md")
            ids = {d["id"] for d in memory.documents(b)}
            self.assertNotIn("RAW/2026/10/meetings/ata-x.md", ids)
            self.assertEqual(memory.awaiting_dump(b), ["RAW/2026/10/meetings/ata-x.md"])

    def test_hold_sends_raw_with_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            b = _full(td)
            _raw(b, "RAW/2026/10/meetings/ata-x.md")
            b.record_one({"type": "artifact.added", "id": "PROCESSED/2026/10/ata-x.md", "by": "agent",
                          "prov": "observado", "source": "RAW/2026/10/meetings/ata-x.md", "date": "2026-10-08",
                          "data": {"kind": "reuniao", "title": "Ata X", "raw": "RAW/2026/10/meetings/ata-x.md",
                                   "people": ["marina-demo"], "projects": [], "summary": ""}})
            docs = {d["id"]: d for d in memory.documents(b)}
            d = docs["RAW/2026/10/meetings/ata-x.md"]
            self.assertEqual(d["date"], "2026-10-08")                       # data do mundo pelo artefato
            self.assertIn("pessoa: Marina-demo (id marina-demo", d["context"])
            self.assertTrue(any(e["id"] == "marina-demo" for e in d["entities"]))

    def test_embed_raw_without_artifact_waits_then_degrades(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            p = _raw(b, "RAW/2026/10/meetings/ata-x.md")
            ids = {d["id"] for d in memory.documents(b)}
            self.assertNotIn("RAW/2026/10/meetings/ata-x.md", ids)          # fresco: espera o /dump
            old = util.parse_dt("2026-09-28T00:00:00-03:00").timestamp()      # 11 dias antes do BRAIN_NOW
            os.utime(p, (old, old))                                         # entra degradado
            docs = {d["id"]: d for d in memory.documents(b)}
            d = docs["RAW/2026/10/meetings/ata-x.md"]
            self.assertIn("sem-artefato:1", d["tags"])
            self.assertNotIn("entities", d)                                 # sem identidade ainda
            self.assertEqual(memory.awaiting_dump(b), [])                   # hold é regra do full

    def test_exclude_types_never_go(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            _raw(b, "RAW/2026/10/connectors/jira-mirror.md")
            _raw(b, "RAW/2026/10/github/pr-42.md")
            ids = {d["id"] for d in memory.documents(b)}
            self.assertNotIn("RAW/2026/10/connectors/jira-mirror.md", ids)
            self.assertNotIn("RAW/2026/10/github/pr-42.md", ids)

    def test_world_date_fallbacks(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            # só mês/ano no caminho
            _raw(b, "RAW/2026/09/meetings/sem-data.md")
            self.assertEqual(memory._raw_date(b.inst.vault / "RAW/2026/09/meetings/sem-data.md",
                                              "RAW/2026/09/meetings/sem-data.md", b.state), "2026-09-01")
            # carimbo no nome
            _raw(b, "RAW/2026/09/meetings/snapshot-2026-10-02T181500.md")
            self.assertEqual(memory._raw_date(b.inst.vault / "RAW/2026/09/meetings/snapshot-2026-10-02T181500.md",
                                              "RAW/2026/09/meetings/snapshot-2026-10-02T181500.md", b.state), "2026-10-02")
            # cabeçalho criada:
            _raw(b, "RAW/2026/09/meetings/nota.md", "---\ncriada: 2026-10-05 09:02\n---\ncorpo")
            self.assertEqual(memory._raw_date(b.inst.vault / "RAW/2026/09/meetings/nota.md",
                                              "RAW/2026/09/meetings/nota.md", b.state), "2026-10-05")

    def test_full_context_and_entities_in_sync(self):
        with tempfile.TemporaryDirectory() as td:
            b = _full(td)
            _raw(b, "RAW/2026/10/meetings/ata-x.md")
            b.record_one({"type": "artifact.added", "id": "PROCESSED/2026/10/ata-x.md", "by": "agent",
                          "prov": "observado", "source": "RAW/2026/10/meetings/ata-x.md", "date": "2026-10-08",
                          "data": {"kind": "reuniao", "title": "Ata X", "raw": "RAW/2026/10/meetings/ata-x.md",
                                   "people": ["marina-demo"], "projects": [], "summary": ""}})
            hs = FakeHindsight()
            memory.sync(b, hs=hs)
            item = next(i for i in hs.items if i["document_id"] == "RAW/2026/10/meetings/ata-x.md")
            self.assertTrue(item["context"].startswith("CONTEXTO\n"))
            self.assertIn("marina-demo", item["context"])
            ents = item["entities"]                          # 1.2.0: entidade top-level com `text`
            self.assertTrue(any(e["id"] == "marina-demo" and e["type"] == "PERSON" and e["text"] for e in ents))
            self.assertEqual(item["timestamp"], "2026-10-08T12:00:00")


class ShadowDeleteTests(unittest.TestCase):
    def test_document_out_of_corpus_is_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            p = _raw(b, "RAW/2026/10/connectors/espelho.md")               # connectors NÃO é excluído aqui…
            old = util.parse_dt("2026-09-27T00:00:00-03:00").timestamp()      # antes do BRAIN_NOW congelado
            os.utime(p, (old, old))                                         # sem /dump: só entra degradado
            (b.inst.cfg["memory"])  # noqa: B018 — modo embed, exclude_types padrão aplica no documents()
            hs = FakeHindsight()
            # primeiro sync com exclusão desligada (como se o doc tivesse ido antes da regra)
            config.set_keys(b.inst, "memory", {"exclude_types": []})
            b.inst = config.load(b.inst.root); b.reload()
            memory.sync(b, hs=hs)
            self.assertIn("RAW/2026/10/connectors/espelho.md", {doc for _, doc in hs.sent})
            # religa a exclusão: o doc sai do corpus e o próximo sync apaga do banco
            config.set_keys(b.inst, "memory", {"exclude_types": ["connectors", "github"]})
            b.inst = config.load(b.inst.root); b.reload()
            res = memory.sync(b, hs=hs)
            self.assertIn("brain:RAW/2026/10/connectors/espelho.md", hs.deleted)
            self.assertEqual(res["sent"], 0)


class CostTests(unittest.TestCase):
    def test_embed_reports_zero(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            c = memory.cost(b, FakeHindsight())
            self.assertEqual(c["usd"], 0.0)
            self.assertIn("não usa LLM", c["detail"])

    def test_full_aggregates_month(self):
        with tempfile.TemporaryDirectory() as td:
            b = _full(td)
            hs = FakeHindsight()
            hs.stats_payload = {"requests": [
                {"operation": "retain", "model": "haiku", "created_at": "2026-10-02T10:00:00+00:00",
                 "requests": 10, "input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.4},
                {"operation": "retain", "model": "haiku", "created_at": "2026-09-20T10:00:00+00:00",
                 "requests": 99, "input_tokens": 99999, "output_tokens": 9999, "cost_usd": 9.9},
                {"operation": "reflect", "model": "sonnet", "created_at": "2026-10-04T10:00:00+00:00",
                 "requests": 2, "input_tokens": 8000, "output_tokens": 2000, "cost_usd": 0.6},
            ]}
            c = memory.cost(b, hs)
            self.assertEqual(c["usd"], 1.0)                                 # só outubro (BRAIN_NOW = 2026-10-09)
            self.assertEqual([r["operation"] for r in c["rows"]], ["reflect", "retain"])

    def test_none_mode_reports_zero(self):
        with tempfile.TemporaryDirectory() as td:
            (td := Path(td)).mkdir(exist_ok=True)
            (td / "config").mkdir()
            (td / "config/brain.toml").write_text('[owner]\nid = "eu"\nname = "D"\n', encoding="utf-8")
            b = Brain(config.load(td))
            c = memory.cost(b, FakeHindsight())
            self.assertEqual(c["mode"], "none")


class CorpusTests(unittest.TestCase):
    """§3.2/3.4: RAW + DEC/WIN vão; PROCESSED, ações, pessoas e PLANNING/PROFILE ficam de fora."""

    def _rich(self, td):
        b = _brain(Path(td))
        _raw(b, "RAW/2026/10/meetings/ata-x.md", "ata com a Marina-demo sobre o forno")
        p = b.inst.vault / "PROCESSED/2026/10/ata-x.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("artefato de teste", encoding="utf-8")
        b.record_one({"type": "artifact.added", "id": "PROCESSED/2026/10/ata-x.md", "by": "agent",
                      "prov": "observado", "source": "RAW/2026/10/meetings/ata-x.md", "date": "2026-10-08",
                      "data": {"kind": "reuniao", "title": "Ata X", "raw": "RAW/2026/10/meetings/ata-x.md",
                               "people": ["marina-demo"], "projects": ["PROJ-1"], "summary": ""}})
        b.record_one({"type": "action.opened", "by": "owner",
                      "data": {"title": "Ligar pro forno", "owner": "eu", "effort_min": 30}})
        b.record_one({"type": "decision.made", "by": "owner", "date": "2026-10-01", "source": "chat",
                      "data": {"title": "Congelar o forno-demo", "decided_by": ["eu"], "project": "PROJ-1"}})
        b.record_one({"type": "delivery.recorded", "by": "owner", "date": "2026-10-02", "source": "chat",
                      "data": {"title": "Forno instalado", "result": "ok"}})
        return b

    def test_only_raw_and_dec_win_go(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._rich(td)
            ids = {d["id"] for d in memory.documents(b)}
            self.assertIn("RAW/2026/10/meetings/ata-x.md", ids)
            self.assertIn("ledger/DEC-0001", ids)
            self.assertIn("ledger/WIN-0001", ids)
            for out_id in ("PROCESSED/2026/10/ata-x.md", "PLANNING/goals.md", "PROFILE/profile.md",
                           "ledger/TASK-0001", "ledger/person/eu"):
                self.assertNotIn(out_id, ids)

    def test_goal_tag_from_planning_tree(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._rich(td)
            d = next(d for d in memory.documents(b) if d["id"] == "RAW/2026/10/meetings/ata-x.md")
            self.assertIn("proj:PROJ-1", d["tags"])
            self.assertIn("goal:GOAL-1", d["tags"])                        # PROJ-1 pertence ao GOAL-1
            dec = next(d for d in memory.documents(b) if d["id"] == "ledger/DEC-0001")
            self.assertIn("goal:GOAL-1", dec["tags"])

    def test_reprocessed_artifact_resends(self):
        """Fase 3.8: identidade mudou (alias novo no CONTEXTO do full) ⇒ sha muda ⇒ reenvia."""
        with tempfile.TemporaryDirectory() as td:
            b = self._rich(td)
            config.set_keys(b.inst, "memory", {"extract": True, "cloud_llm": True, "raw_awaiting_dump": "hold"})
            b.inst = config.load(b.inst.root); b.reload()
            before = next(d for d in memory.documents(b) if d["id"] == "RAW/2026/10/meetings/ata-x.md")["sha"]
            b.record_one({"type": "person.updated", "id": "marina-demo", "by": "owner",
                          "data": {"aliases_add": ["Mary-demo"]}})
            b.reload()
            after = next(d for d in memory.documents(b) if d["id"] == "RAW/2026/10/meetings/ata-x.md")["sha"]
            self.assertNotEqual(before, after)

    def test_aliases_synced_at_setup(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._rich(td)
            hs = FakeHindsight()
            memory.setup(b, hs)
            self.assertIn(("brain", "Mari-demo", "Marina-demo"), hs.aliases)


class _RecallHS(FakeHindsight):
    """Recall sempre devolve um trecho — para a perna de memória do dossiê."""

    def recall(self, bank, query, tags=None, budget="mid"):
        super().recall(bank, query, tags, budget)
        return {"results": [{"text": "trecho: a Marina-demo revisou o orcamento-demo",
                             "document_id": "RAW/2026/10/meetings/ata-x.md",
                             "occurred_start": "2026-10-08"}]}


class DossierTests(unittest.TestCase):
    """Fase 5: montagem na leitura — ficha + DEC/WIN ligados + trechos, tudo com fonte."""

    def _fixture(self, td):
        b = _brain(Path(td))
        b.record_one({"type": "decision.made", "by": "owner", "date": "2026-10-01", "source": "chat",
                      "data": {"title": "Congelar o forno-demo", "decided_by": ["marina-demo"],
                               "project": "PROJ-1"}})
        act = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                            "prov": "observado", "source": "chat",
                            "data": {"title": "Revisar orçamento", "owner": "marina-demo",
                                     "due": "2026-10-04", "project": "PROJ-1"}})
        b.record_one({"type": "delivery.recorded", "by": "owner", "date": "2026-10-03", "source": "chat",
                      "data": {"title": "Forno instalado", "result": "ok", "ref": act["id"]}})
        index.update(b)
        return b

    def test_person_by_alias_with_all_layers(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._fixture(td)
            hs = _RecallHS()
            d = dossier.build(b, "Mari-demo", hs=hs)                       # alias resolve
            self.assertEqual((d["kind"], d["id"]), ("person", "marina-demo"))
            self.assertEqual(d["ficha"]["name"], "Marina-demo")
            self.assertTrue(any(dec["title"] == "Congelar o forno-demo" for dec in d["decisions"]))
            self.assertTrue(any(w["title"] == "Forno instalado" for w in d["deliveries"]))
            self.assertEqual(len(d["chunks"]), 1)
            self.assertEqual(d["chunks"][0]["doc"], "RAW/2026/10/meetings/ata-x.md")
            self.assertEqual(hs.recall_calls[-1][0], "brain")
            self.assertEqual(hs.recall_tags[-1], ["pessoa:marina-demo"])   # filtra pelo tag da entidade
            text = dossier.render(d)
            self.assertIn("⟶ ledger/DEC-", text)
            self.assertIn("Dossiê — Marina-demo", text)

    def test_person_without_anything_gets_only_ficha(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._fixture(td)
            d = dossier.build(b, "eu", hs=FakeHindsight())                 # dono: nada ligado
            self.assertEqual(d["decisions"], [])
            self.assertEqual(d["deliveries"], [])
            self.assertEqual(d["chunks"], [])
            self.assertIn("só a ficha", dossier.render(d))

    def test_goal_dossier_scopes_its_projects(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._fixture(td)
            d = dossier.build(b, "GOAL-1", hs=FakeHindsight())             # PROJ-1 é filho do GOAL-1
            self.assertEqual(d["kind"], "goal")
            self.assertTrue(any(dec["project"] == "PROJ-1" for dec in d["decisions"]))

    def test_unknown_ref_refused(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._fixture(td)
            with self.assertRaises(util.BrainError):
                dossier.build(b, "pessoa-que-nao-existe")

    def test_works_with_memory_off(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._fixture(td)
            config.set_keys(b.inst, "memory", {"engine": "none"})
            b.inst = config.load(b.inst.root); b.reload()
            d = dossier.build(b, "PROJ-1")                                 # sem servidor: ficha + DEC/WIN
            self.assertEqual(d["chunks"], [])
            self.assertTrue(d["decisions"])


class MentalModelsTests(unittest.TestCase):
    """Fase 8: catálogo do PLANNING + pessoas; sync cria/limpa; full-only."""

    def _full(self, td):
        b = _brain(Path(td))
        b.record_one({"type": "decision.made", "by": "owner", "date": "2026-10-01", "source": "chat",
                      "data": {"title": "Congelar o forno-demo", "decided_by": ["marina-demo"],
                               "project": "PROJ-1"}})
        index.update(b)
        config.set_keys(b.inst, "memory", {"extract": True, "cloud_llm": True,
                                           "raw_awaiting_dump": "hold", "mental_models": True})
        b.inst = config.load(b.inst.root)
        b.reload()
        return b

    def test_catalog_from_planning_and_people(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._full(td)
            cat = {m["id"]: m for m in memory._mm_catalog(b)}
            self.assertIn("mm-goal-1", cat)                      # GOAL-1 ativo
            self.assertIn("mm-proj-1", cat)                      # PROJ-1 ativo
            self.assertIn("mm-pessoa-marina-demo", cat)          # pessoa com vínculos
            self.assertEqual(cat["mm-proj-1"]["tags"], ["proj:PROJ-1"])
            self.assertIn("progresso", cat["mm-goal-1"]["source_query"])   # estado do ledger colado

    def test_sync_creates_and_removes_orphans(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._full(td)
            hs = FakeHindsight()
            hs.mms["mm-proj-99"] = {"id": "mm-proj-99", "name": "velho"}     # projeto fechado
            res = memory.models_sync(b, hs)
            self.assertIn("mm-goal-1", res["created"])
            self.assertEqual(res["removed"], ["mm-proj-99"])
            self.assertIn("mm-proj-1", hs.mms)
            self.assertNotIn("mm-proj-99", hs.mms)
            # idempotente: de novo, tudo mantido
            res2 = memory.models_sync(b, hs)
            self.assertEqual(res2["created"], [])
            self.assertEqual(res2["removed"], [])

    def test_sync_refused_in_embed_and_without_flag(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))                                 # embed
            with self.assertRaises(util.BrainError) as cm:
                memory.models_sync(b, FakeHindsight())
            self.assertIn("full", str(cm.exception))
            with tempfile.TemporaryDirectory() as td2:
                b2 = self._full(td2)
                config.set_keys(b2.inst, "memory", {"mental_models": False})
                b2.inst = config.load(b2.inst.root); b2.reload()
                with self.assertRaises(util.BrainError) as cm2:
                    memory.models_sync(b2, FakeHindsight())
                self.assertIn("mental_models", str(cm2.exception))


class FreshnessTests(unittest.TestCase):
    """Fresnness do servidor (plano memory-harness-wizard.md §4.4): informação, nunca bloqueio."""

    def _cache(self, b, latest):
        util.write_json(b.inst.fresh / memory.VERSION_CACHE,
                        {"latest": latest, "checked_at": util.now().isoformat(timespec="seconds")})

    def test_current_server_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            hs = FakeHindsight()
            hs.server_version = "1.2.0"
            self._cache(b, "1.2.0")
            s = memory.status(b, online=True, hs=hs)
            self.assertIn("servidor 1.2.0 (última)", s["detail"])
            self.assertEqual(s["level"], "ok")

    def test_old_server_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            hs = FakeHindsight()
            hs.server_version = "0.10.1"
            self._cache(b, "1.2.0")
            s = memory.status(b, online=True, hs=hs)
            self.assertIn("servidor 0.10.1 < Hindsight 1.2.0", s["detail"])

    def test_no_cache_is_quiet(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            s = memory.status(b, online=True, hs=FakeHindsight())
            self.assertNotIn("(última)", s["detail"])
            self.assertNotIn("< Hindsight", s["detail"])

    def test_version_check_tolerates_server_without_version(self):
        class NoVersion(FakeHindsight):
            def version(self):
                raise util.BrainError("Hindsight GET /version → 404", code=2)
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            self.assertIsNone(memory.version_check(b, NoVersion()))


class ApplyModeTests(unittest.TestCase):
    def test_full_without_key_in_env_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with self.assertRaises(util.BrainError) as cm:
                memory._apply_mode(b, "full")
            self.assertIn("config/.env", str(cm.exception))

    def test_full_with_key_writes_config(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            (b.inst.config_dir / ".env").write_text("HINDSIGHT_API_LLM_API_KEY=demo-key\n", encoding="utf-8")
            memory._apply_mode(b, "full")
            b.reload()
            mem = b.inst.cfg["memory"]
            self.assertEqual(memory.mode(mem), "full")
            self.assertTrue(mem["cloud_llm"])
            self.assertEqual(mem["raw_awaiting_dump"], "hold")

    def test_embed_writes_config(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            memory._apply_mode(b, "embed")
            b.reload()
            self.assertEqual(memory.mode(b.inst.cfg["memory"]), "embed")
            self.assertEqual(b.inst.cfg["memory"]["raw_awaiting_dump"], "degraded")


if __name__ == "__main__":
    unittest.main()
