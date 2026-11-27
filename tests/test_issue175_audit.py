"""#175: auditoria de links. Toda página do painel que cita um arquivo do vault o torna navegável.

Renderiza TODAS as páginas (`V.*`) em Node com o modelo de uma instância demo e confere duas coisas:
A) nenhum caminho do vault aparece como texto solto, fora de link ou de uma linha de "Arquivos linkados";
B) as referências que o modelo traz (linha do tempo, última interação, mensagem, snapshot da fonte) viram
   botão de leitura/abertura na página certa. Esse era o furo: a linha do tempo escondia o artefato.
"""
from __future__ import annotations

import json
import re
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

from brainlib import config, linked, render, watch  # noqa: E402
from brainlib.core import Brain  # noqa: E402

LI_LINKED = re.compile(r"<li>(?:(?!</li>).)*?data-(?:read|open)=(?:(?!</li>).)*?</li>", re.S)
LINK = re.compile(r"<(a|button)\b[^>]*>.*?</\1>", re.S)
TAG = re.compile(r"<[^>]+>")
PATH = re.compile(r"(?:\b(?:RAW|PROCESSED|PLANNING|PROFILE|FRESH|reports)/[\w./#-]+)|(?:[\w-]+\.(?:md|json|pdf|png|csv|txt|toml)\b)")

# Texto fixo do painel (instrução ou diagnóstico do sistema), não referência a arquivo do dono.
STATIC_COPY = {
    "FRESH/_index": "saúde: o banco do índice",
    "settings.json": "saúde: permissões do agente",
    "watch.toml": "descrição da aba Fontes",
    "FRESH/todo.md": "instrução do TODO: onde marcar",
}

# O harness carrega o core.js DO PRÓPRIO REPOSITÓRIO com eval (mesmo padrão de test_panel_sources.py): é código
# versionado, não entrada externa. O modelo chega por argv como JSON.
NODE = r"""
const fs = require("fs");
const model = JSON.parse(process.argv[1]);
const dummyEl = {innerHTML: "", textContent: "", dataset: {}, classList: {toggle(){}, add(){}, remove(){}, contains: () => false}, addEventListener(){}};
global.document = {getElementById: id => id === "data" ? {textContent: JSON.stringify(model)} : dummyEl, querySelector: () => dummyEl,
  querySelectorAll: () => [], addEventListener(){}, documentElement: {dataset: {}}};
global.window = global; global.scrollTo = () => {}; global.addEventListener = () => {};
global.localStorage = {getItem: () => null, setItem(){}}; global.matchMedia = () => ({matches: false});
global.location = {hash: "home"};
eval(fs.readFileSync("brainlib/assets/src/core.js", "utf8"));
const V = window.BRAIN.V, M = model;
const first = a => (a && a[0] && a[0].id) || "";
const ids = {action: first(M.actions), decision: first(M.decisions), project: first(M.projects),
  person: (M.people[1] || M.people[0]).id, "pf/opp": first(M.portfolio.opportunities),
  "pf/proc": first(M.portfolio.processes), "pf/area": first(M.portfolio.areas)};
if (process.argv[2]) ids.person = process.argv[2];
const out = {}, threw = {};
for (const k of Object.keys(V)) {
  try { out[k] = String(V[k](new URLSearchParams(""), ids[k] || "")); } catch (e) { threw[k] = String(e).slice(0, 160); }
}
for (const term of ["reuni", "vistoria", "marina", "receita"]) {      // a busca mostra caminhos nos resultados
  try { out["search?" + term] = String(V.search(new URLSearchParams("q=" + term), "")); } catch (e) { threw["search?" + term] = String(e).slice(0, 160); }
}
process.stdout.write(JSON.stringify({out, threw}));
"""


class PanelLinkAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node não disponível no ambiente")
        cls._td = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._td.cleanup)
        root = Path(cls._td.name) / "inst"
        demo_cache.build(root)
        cls.inst = config.load(root)
        cls.b = Brain(cls.inst)
        # uma fonte do watch com um pull que gravou snapshot (o arquivo existe no vault)
        watch.add(cls.inst, "slack-geral", {"kind": "slack", "window": "1d", "channel": "#geral"})
        snap = cls.inst.vault / "RAW" / "inbox" / "slack-geral-snap.md"
        snap.write_text("# Canal geral\n\nconversa da padaria\n", encoding="utf-8")
        cls.b.record_one({"type": "connector.pulled", "id": "slack-geral", "by": "system",
                          "data": {"changed": True, "snapshot": "RAW/inbox/slack-geral-snap.md"}})
        # uma mensagem que cita um artefato (o arquivo do artefato existe)
        cls.art = next(iter(cls.b.state.artifacts))
        cls.b.record_one({"type": "message.drafted", "by": "owner", "data": {
            "to": "marina-demo", "text": "Oi! Segue a receita da fornada.", "ref": cls.art, "why": "pediu ontem"}})
        vm = render.view_model(cls.b)
        cls.vm = vm
        proc = subprocess.run(["node", "-e", NODE, json.dumps(vm, default=str)], capture_output=True, text=True, cwd=ROOT)
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        cls.pages, cls.threw = data["out"], data["threw"]

    def test_todas_as_paginas_renderizam(self):
        self.assertEqual(self.threw, {})
        self.assertGreaterEqual(len(self.pages), 30)         # sem isto a varredura passaria no vazio

    def test_nenhum_caminho_do_vault_aparece_solto(self):
        for name, html in sorted(self.pages.items()):
            text = TAG.sub(" ", LINK.sub(" ", LI_LINKED.sub(" ", html)))
            loose = sorted(set(PATH.findall(text)) - set(STATIC_COPY))
            self.assertEqual(loose, [], f"página '{name}' cita arquivo sem link: {loose}")

    def test_o_detector_acusa_um_caminho_solto(self):
        html = "<p>origem: PROCESSED/2026/11/reuniao.md</p><button data-read=\"x\">x</button>"
        text = TAG.sub(" ", LINK.sub(" ", LI_LINKED.sub(" ", html)))
        self.assertEqual(sorted(set(PATH.findall(text))), ["PROCESSED/2026/11/reuniao.md"])
        ok = '<li><button data-read="a.md">Ver</button> RAW · a.md</li>'
        self.assertEqual(PATH.findall(TAG.sub(" ", LINK.sub(" ", LI_LINKED.sub(" ", ok)))), [])

    # ── B: o que o modelo cita e a página precisa ligar ─────────────────────
    def test_linha_do_tempo_liga_cada_artefato_do_passado(self):
        refs = [it["id"] for it in self.vm["timeline"]["past"] if "/" in it["id"]]
        self.assertTrue(refs, "a demo precisa ter artefato na linha do tempo")
        for ref in refs:
            self.assertIn(f'data-read="{ref}"', self.pages["timeline"], f"linha do tempo sem link para {ref}")

    def test_ficha_da_pessoa_liga_a_ultima_interacao(self):
        com = [p for p in self.vm["people"] if (p.get("last_interaction") or {}).get("artifact")]
        self.assertTrue(com)
        pid = com[0]["id"]
        proc = subprocess.run(["node", "-e", NODE, json.dumps(self.vm, default=str), pid],
                              capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        page = json.loads(proc.stdout)["out"]["person"]
        self.assertIn(f'data-read="{com[0]["last_interaction"]["artifact"]}"', page)

    def test_mensagem_que_cita_um_artefato_mostra_o_arquivo(self):
        msg = next(m for m in self.vm["outbox"] if m["ref"] == self.art)
        self.assertTrue(msg["files"], "o modelo da mensagem precisa trazer os arquivos")
        page = self.pages["outbox"]
        for f in msg["files"]:                     # um documento por linha: o nome pré-visualiza o resumo, o chip abre o original
            if f["kind"] == "artefato":
                self.assertIn(f'data-doc="{f["rel"]}"', page)
                self.assertIn(f'data-open="{f.get("raw") or f["rel"]}"', page)
            else:
                self.assertTrue(f'data-open="{f["rel"]}"' in page or f'data-doc="{f["rel"]}"' in page, f["rel"])

    def test_fonte_com_snapshot_oferece_ver_o_ultimo_pull(self):
        src = next(s for s in self.vm["sources"] if s["key"] == "slack-geral")
        self.assertEqual([f["rel"] for f in src["files"]], ["RAW/inbox/slack-geral-snap.md"])
        self.assertIn('data-read="RAW/inbox/slack-geral-snap.md"', self.pages["sources"])

    def test_fonte_sem_snapshot_nao_ganha_link(self):
        self.assertEqual(next(s for s in self.vm["sources"] if s["key"] == "slack-geral")["files"][0]["kind"], "RAW")
        sem = [s for s in self.vm["sources"] if not s.get("last_snapshot")]
        for s in sem:
            self.assertEqual(s["files"], [])

    def test_referencia_para_arquivo_fora_do_vault_nao_vira_link(self):
        self.assertIsNone(linked.vault_file(self.inst, "../fora.md"))
        self.assertIsNone(linked.vault_file(self.inst, "/etc/passwd"))


if __name__ == "__main__":
    unittest.main()
