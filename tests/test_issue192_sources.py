"""#192: a aba Fontes. Fonte avulsa sai da lista, e o erro some quando a fonte volta a responder."""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_cache  # noqa: E402

from brainlib import config, snapshot, util, watch  # noqa: E402
from brainlib.core import Brain  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name) / "inst"
        demo_cache.build(self.root)
        self.inst = config.load(self.root)
        self.b = Brain(self.inst)

    def fresh(self) -> Brain:
        """O estado relido do ledger em disco: é o que o próximo comando enxerga."""
        return Brain(config.load(self.root))

    def pull(self, key: str, **extra):
        self.b.record_one({"type": "connector.pulled", "id": key, "by": "system", "data": {"changed": False, **extra}})

    def push_fail(self, key: str, why: str = "canal sem acesso"):
        self.b.record_one({"type": "connector.failed", "id": key, "by": "system", "data": {"error": why}})


class StrayAndRemovedSourcesTests(_Base):
    def test_avulsa_sai_da_lista_e_o_ledger_continua_valido(self):
        self.pull("fornada-avulsa")
        self.assertIn("fornada-avulsa", self.b.state.connectors)
        self.assertEqual(watch.remove_source(self.b, "fornada-avulsa"), "avulsa")
        self.assertNotIn("fornada-avulsa", self.b.state.connectors)
        self.assertNotIn("fornada-avulsa", self.fresh().state.connectors)       # o ledger relido, não só a memória
        self.assertEqual(self.fresh().validate_all(), [])

    def test_a_lista_nao_so_cresce(self):
        for k in ("fornada-avulsa", "fornada-avulsa-2", "fornada-avulsa-3"):
            self.pull(k)
        for k in ("fornada-avulsa", "fornada-avulsa-2"):
            watch.remove_source(self.b, k)
        self.assertEqual([k for k in self.fresh().state.connectors if k.startswith("fornada-avulsa")], ["fornada-avulsa-3"])

    def test_remover_fonte_do_watch_nao_deixa_fantasma_como_avulsa(self):
        watch.add(self.inst, "receitas-canal", {"kind": "slack", "window": "1d", "channel": "#receitas"})
        self.pull("receitas-canal")
        self.assertEqual(watch.remove_source(self.b, "receitas-canal"), "watch")
        self.assertNotIn("receitas-canal", {s["key"] for s in watch.list_sources(self.inst)})
        self.assertNotIn("receitas-canal", self.fresh().state.connectors)

    def test_fonte_do_watch_que_nunca_puxou_remove_sem_erro(self):
        watch.add(self.inst, "receitas-canal", {"kind": "slack", "window": "1d", "channel": "#receitas"})
        self.assertEqual(watch.remove_source(self.b, "receitas-canal"), "watch")

    def test_chave_que_nao_existe_em_lugar_nenhum_e_erro_claro(self):
        with self.assertRaises(util.BrainError) as cm:
            watch.remove_source(self.b, "nunca-existiu")
        self.assertIn("nunca-existiu", str(cm.exception))
        self.assertEqual(cm.exception.code, 3)                                  # o mesmo código que o remove sempre deu

    def test_noturno_nao_esquece_nem_remove(self):
        self.pull("fornada-avulsa")
        with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
            with self.assertRaises(util.BrainError) as cm:
                watch.remove_source(self.b, "fornada-avulsa")
        self.assertEqual(cm.exception.code, 4)
        self.assertIn("fornada-avulsa", self.fresh().state.connectors)

    def test_um_novo_pull_traz_a_avulsa_de_volta(self):
        self.pull("fornada-avulsa")
        watch.remove_source(self.b, "fornada-avulsa")
        self.pull("fornada-avulsa")
        self.assertIn("fornada-avulsa", self.fresh().state.connectors)
        self.assertEqual(self.fresh().state.connectors["fornada-avulsa"].pulls, 1)      # o contador recomeça

    def test_cli_remove_de_avulsa_diz_o_que_fez(self):
        self.pull("fornada-avulsa")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            watch.cli(argparse.Namespace(wcmd="remove", key="fornada-avulsa"), self.b)
        self.assertIn("avulsa", out.getvalue())
        self.assertNotIn("fornada-avulsa", self.fresh().state.connectors)


class HealthyReadClearsTheErrorTests(_Base):
    def test_pull_saudavel_zera_falhas_e_o_texto_do_erro(self):
        self.push_fail("receitas-drive", "leitura recusada")
        c = self.b.state.connectors["receitas-drive"]
        self.assertEqual((c.consecutive_failures, c.last_error), (1, "leitura recusada"))
        self.pull("receitas-drive")
        c = self.b.state.connectors["receitas-drive"]
        self.assertEqual((c.consecutive_failures, c.last_error), (0, ""))
        self.assertEqual(self.fresh().state.connectors["receitas-drive"].last_error, "")

    def test_chip_e_selo_somem_no_estado_da_fonte(self):
        src = {"key": "receitas-drive", "kind": "drive", "window": "1d"}
        self.push_fail("receitas-drive")
        self.assertTrue(watch.source_status(src, self.b.state.connectors["receitas-drive"])["problem"])
        self.pull("receitas-drive")
        self.assertFalse(watch.source_status(src, self.b.state.connectors["receitas-drive"])["problem"])

    def _state_com_revisao(self, key: str, rev: str):
        util.write_json(self.inst.state_file, {f"snapshot:{key}": {"hash": "h", "rev": rev}})

    def _check(self, key: str, rev: str) -> str:
        out = io.StringIO()
        args = argparse.Namespace(key=key, item=None, check=True, rev=rev, fail=None, empty=False)
        with contextlib.redirect_stdout(out):
            snapshot.cli(args, self.b)
        return out.getvalue()

    def test_checagem_inalterada_limpa_o_erro_de_quem_estava_com_falha(self):
        self.pull("receitas-drive")
        self._state_com_revisao("receitas-drive", "r1")
        self.push_fail("receitas-drive", "drive fora do ar")
        self.assertIn("inalterado", self._check("receitas-drive", "r1"))
        c = self.fresh().state.connectors["receitas-drive"]
        self.assertEqual((c.consecutive_failures, c.last_error), (0, ""))

    def test_checagem_inalterada_de_fonte_saudavel_continua_silenciosa(self):
        self.pull("receitas-drive")
        self._state_com_revisao("receitas-drive", "r1")
        before = len(self.b.read_events())
        self.assertIn("inalterado", self._check("receitas-drive", "r1"))
        self.assertEqual(len(self.fresh().read_events()), before)       # hash idêntico segue sendo silêncio

    def test_checagem_que_mudou_nao_limpa_o_erro(self):
        self.pull("receitas-drive")
        self._state_com_revisao("receitas-drive", "r1")
        self.push_fail("receitas-drive")
        self.assertIn("mudou", self._check("receitas-drive", "r2"))
        self.assertEqual(self.fresh().state.connectors["receitas-drive"].consecutive_failures, 1)

    def test_item_de_pasta_com_falha_grava_o_pull_mesmo_dentro_da_janela_de_5_min(self):
        # o atalho de "pulsou há pouco" não pode engolir o pull que cura
        self.pull("pasta-drive")
        self.push_fail("pasta-drive")
        snapshot._pulled(self.b, "pasta-drive", "doc-1", False)
        self.assertEqual(self.fresh().state.connectors["pasta-drive"].consecutive_failures, 0)

    def test_item_de_pasta_saudavel_dentro_da_janela_continua_sem_evento(self):
        self.pull("pasta-drive")
        before = len(self.b.read_events())
        snapshot._pulled(self.b, "pasta-drive", "doc-1", False)
        self.assertEqual(len(self.fresh().read_events()), before)


if __name__ == "__main__":
    unittest.main()
