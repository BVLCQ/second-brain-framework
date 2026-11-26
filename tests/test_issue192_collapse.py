"""#192: cada cabeçalho de tipo da aba Fontes recolhe e reabre só o seu grupo (painel e TUI)."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_cache  # noqa: E402

from brainlib import config, render, watch  # noqa: E402
from brainlib.core import Brain  # noqa: E402
from brainlib.tui import rows, store  # noqa: E402

HAVE_TEXTUAL = importlib.util.find_spec("textual") is not None


class _Fixture(unittest.TestCase):
    NOW = "2026-10-19T10:00:00-03:00"

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name) / "inst"
        demo_cache.build(self.root)
        self.inst = config.load(self.root)
        old = os.environ.get("BRAIN_NOW")
        os.environ["BRAIN_NOW"] = self.NOW
        self.addCleanup(lambda: os.environ.pop("BRAIN_NOW", None) if old is None else os.environ.__setitem__("BRAIN_NOW", old))
        for key, kind, extra in (("slack-geral", "slack", {"channel": "#geral"}), ("slack-dados", "slack", {"channel": "#dados"}),
                                 ("gcal-14d", "gcal", {}), ("gmail-falha", "gmail", {})):
            watch.add(self.inst, key, {"kind": kind, "window": "1d", **extra})
        self.b = Brain(self.inst)
        for key in ("slack-geral", "slack-dados", "gcal-14d", "gmail-falha"):
            self.b.record_one({"type": "connector.pulled", "id": key, "by": "system", "date": "2026-10-19",
                               "data": {"changed": False}})
        self.b.record_one({"type": "connector.failed", "id": "gmail-falha", "by": "system", "date": "2026-10-19",
                           "data": {"error": "timeout"}})


class StoreCollapseTests(_Fixture):
    def ids(self, collapsed=None, filt=""):
        st = store.Store(self.inst)
        return [i.id for i in st.items(0, 1, 1, False, filt, collapsed or set())]

    def test_sem_nada_recolhido_a_lista_e_a_de_sempre(self):
        ids = self.ids()
        self.assertEqual(ids.count("src:slack-geral"), 1)
        self.assertIn("sgrp:slack", ids)

    def test_recolher_um_tipo_esconde_so_as_linhas_dele(self):
        ids = self.ids({"sgrp:slack"})
        self.assertIn("sgrp:slack", ids)                                    # o cabeçalho fica
        self.assertNotIn("src:slack-geral", ids)
        self.assertNotIn("src:slack-dados", ids)
        self.assertIn("src:gcal-14d", ids)                                   # os outros tipos não mudam
        self.assertIn("src:gmail-falha", ids)

    def test_cabecalho_recolhido_guarda_contagem_e_selo_de_problema(self):
        st = store.Store(self.inst)
        hdr = next(i for i in st.items(0, 1, 1, False, "", {"sgrp:gmail"}) if i.id == "sgrp:gmail")
        self.assertTrue(hdr.data["collapsed"])
        self.assertEqual((hdr.data["count"], hdr.data["problems"]), (1, 1))
        line = rows.row(st, hdr, 80).plain
        self.assertIn("▸", line)
        self.assertIn("⚠ 1", line)

    def test_cabecalho_aberto_mostra_o_chevron_aberto(self):
        st = store.Store(self.inst)
        hdr = next(i for i in st.items(0, 1, 1, False, "", set()) if i.id == "sgrp:slack")
        self.assertFalse(hdr.data["collapsed"])
        self.assertIn("▾", rows.row(st, hdr, 80).plain)

    def test_filtrar_mostra_o_que_casa_mesmo_em_grupo_recolhido(self):
        ids = self.ids({"sgrp:slack"}, filt="slack-geral")
        self.assertIn("src:slack-geral", ids)

    def test_grupo_de_fonte_avulsa_tambem_recolhe(self):
        self.b.record_one({"type": "connector.pulled", "id": "fornada-avulsa", "by": "system", "data": {"changed": False}})
        self.assertIn("src:fornada-avulsa", self.ids())
        self.assertNotIn("src:fornada-avulsa", self.ids({"sgrp:avulsa"}))


@unittest.skipUnless(HAVE_TEXTUAL, "textual não instalado (./brain tui --setup)")
class TuiCollapseTest(_Fixture, unittest.IsolatedAsyncioTestCase):
    async def test_espaco_recolhe_o_grupo_da_linha_e_reabre_no_cabecalho(self):
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "]")
            self.assertEqual((app.p, app.tab[1]), (1, 1))
            app.jump_source("slack-geral")
            self.assertEqual(app.cur().id, "src:slack-geral")
            await pilot.press("space")                                          # recolhe o grupo slack
            await pilot.pause(0.2)
            ids = [i.id for i in app.items(1)]
            self.assertNotIn("src:slack-geral", ids)
            self.assertIn("src:gcal-14d", ids)
            self.assertEqual(app.cur().id, "sgrp:slack")                         # a seleção vai para o cabeçalho recolhido
            await pilot.press("space")                                          # reabre
            await pilot.pause(0.2)
            ids = [i.id for i in app.items(1)]
            self.assertIn("src:slack-geral", ids)
            self.assertNotEqual(app.cur().kind, "sgrp")                          # cabeçalho aberto volta a ser pulado

    async def test_d_em_fonte_avulsa_esta_disponivel_como_tirar_da_lista(self):
        self.b.record_one({"type": "connector.pulled", "id": "fornada-avulsa", "by": "system", "data": {"changed": False}})
        from brainlib.tui.app import BrainApp
        app = BrainApp(self.inst)
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("1", "]")
            app.jump_source("fornada-avulsa")
            self.assertEqual(app.cur().id, "src:fornada-avulsa")
            keys = {k.k: k.label for k in app.ctx_keys()}
            self.assertEqual(keys.get("d"), "tirar da lista")


class PanelCollapseTest(_Fixture):
    def _node(self, body: str) -> dict:
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node não disponível no ambiente")
        vm = render.view_model(self.b)
        script = """
const fs = require("fs");
const model = JSON.parse(process.argv[1]);
const dummyEl = {innerHTML: "", textContent: "", dataset: {}, classList: {toggle(){}, add(){}, remove(){}, contains: () => false}, addEventListener(){}};
global.document = {getElementById: id => id === "data" ? {textContent: JSON.stringify(model)} : dummyEl, querySelector: () => dummyEl,
  querySelectorAll: () => [], addEventListener(){}, documentElement: {dataset: {}}};
global.window = global; global.scrollTo = () => {}; global.addEventListener = () => {};
global.localStorage = {getItem: () => null, setItem(){}}; global.matchMedia = () => ({matches: false});
global.location = {hash: "sources"};
eval(fs.readFileSync("brainlib/assets/src/core.js", "utf8"));
""" + body
        proc = subprocess.run([node, "-e", script, json.dumps(vm, default=str)], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_recolher_esconde_as_linhas_do_tipo_e_so_dele(self):
        out = self._node("""
const open = window.BRAIN.V.sources();
window.BRAIN.S_COLLAPSED.add("slack");
const closed = window.BRAIN.V.sources();
window.BRAIN.S_COLLAPSED.delete("slack");
const reopened = window.BRAIN.V.sources();
process.stdout.write(JSON.stringify({open, closed, reopened}));
""")
        self.assertIn('data-sel="src:slack-geral"', out["open"])
        self.assertNotIn('data-sel="src:slack-geral"', out["closed"])
        self.assertNotIn('data-sel="src:slack-dados"', out["closed"])
        self.assertIn('data-sel="src:gcal-14d"', out["closed"])                  # outro tipo intacto
        self.assertIn('data-sel="src:gmail-falha"', out["closed"])
        self.assertIn('data-sel="src:slack-geral"', out["reopened"])             # reabrir devolve as linhas

    def test_cabecalho_e_um_botao_acessivel_com_chevron_e_contagem(self):
        out = self._node("""
const open = window.BRAIN.V.sources();
window.BRAIN.S_COLLAPSED.add("gmail");
const closed = window.BRAIN.V.sources();
process.stdout.write(JSON.stringify({open, closed}));
""")
        self.assertIn('data-src-grp="slack"', out["open"])
        self.assertIn('role="button"', out["open"])
        self.assertIn('aria-expanded="true"', out["open"])
        self.assertIn("▾ slack · canal ou DM", out["open"])
        self.assertIn("▸ gmail · e-mails", out["closed"])
        self.assertIn('aria-expanded="false"', out["closed"])
        self.assertIn("(1)", out["closed"])
        self.assertIn("⚠ 1 com problema", out["closed"])                          # o selo continua à vista, recolhido

    def test_fonte_avulsa_oferece_tirar_da_lista(self):
        self.b.record_one({"type": "connector.pulled", "id": "fornada-avulsa", "by": "system", "data": {"changed": False}})
        out = self._node("""process.stdout.write(JSON.stringify({html: window.BRAIN.V.sources()}));""")
        self.assertIn("d tira da lista", out["html"])


if __name__ == "__main__":
    unittest.main()
