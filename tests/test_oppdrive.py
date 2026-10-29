"""`brain oppdrive` — porta das pastas de oportunidade no Drive (só contabilidade; quem escreve no Drive é o agente)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from brainlib import onepager, runner           # noqa: E402
from test_brain import _brain                   # noqa: E402

RAIZ, PASTA, DOC, OUTRA = "1RaizRaizRaizRaiz", "1PastaPastaPasta", "1DocDocDocDocDoc", "1OutraOutraOutra"
TOOLS = ["mcp__drive__create_file", "mcp__docs__update_doc"]


def _brain_of(td):
    """Lê o ledger que o CLI gravou em `td` (sem tocar nele)."""
    from brainlib import config
    from brainlib.core import Brain
    return Brain(config.load(Path(td)))


class OppDriveTests(unittest.TestCase):
    def _run(self, td, *a):
        env = {**os.environ, "BRAIN_HOME": td}
        env.pop("BRAIN_NIGHTLY", None)
        return subprocess.run([sys.executable, str(ROOT / "brain"), *a], capture_output=True, text=True, env=env)

    def _ok(self, td, *a):
        r = self._run(td, *a)
        self.assertEqual(r.returncode, 0, f"{a}: {r.stderr}")
        return r.stdout

    def _setup(self, td, enabled=True):
        _brain(Path(td))
        cfg = Path(td) / "config" / "brain.toml"
        cfg.write_text(cfg.read_text() + f'\n[oppdrive]\nenabled = {"true" if enabled else "false"}\n'
                       f'root = "https://drive.google.com/drive/u/0/folders/{RAIZ}"\ntools = {json.dumps(TOOLS)}\n')
        self._ok(td, "area", "add", "operacoes", "--by", "owner")
        self._ok(td, "opportunity", "add", "Roteamento de tickets", "--area", "operacoes",
                 "--problem", "triagem manual", "--by", "owner")

    def _status(self, td):
        return json.loads(self._ok(td, "oppdrive", "status", "--json"))["opportunities"][0]

    def test_disabled_door_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td, enabled=False)
            self.assertEqual(self._run(td, "oppdrive", "status").returncode, 4)

    def test_folder_onepager_and_suggestion_flow(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            st = self._status(td)
            self.assertEqual((st["todo"], st["folder_title"]), (["pasta", "one-pager"], "OPP-0001: Roteamento de tickets"))
            md = self._ok(td, "oppdrive", "onepager", "OPP-0001")
            self.assertIn("# OPP-0001: Roteamento de tickets", md)
            self.assertIn("triagem manual", md)
            self.assertIn("| **Arquivos relacionados** |", md)
            self.assertIn("## Detalhamento", md)
            # pasta fora da raiz: recusada, nada gravado
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--folder", PASTA, "--parent", OUTRA).returncode, 4)
            # one-pager antes da pasta: recusado
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--onepager", DOC, "--parent", PASTA).returncode, 4)
            self.assertIn("fonte oppdrive", self._ok(td, "oppdrive", "record", "OPP-0001", "--folder", PASTA, "--parent", RAIZ))
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--onepager", DOC, "--parent", OUTRA).returncode, 4)
            out = self._ok(td, "oppdrive", "record", "OPP-0001", "--onepager",
                           f"https://docs.google.com/document/d/{DOC}/edit", "--parent", PASTA)
            self.assertIn("one-pager-opp-0001", out)                        # vigiado pelo watch
            watch = json.loads(self._ok(td, "watch", "list", "--json"))
            self.assertIn({"key": "oppdrive", "doc": None}, [{"key": w["key"], "doc": w.get("doc")} for w in watch])
            self.assertIn({"key": "one-pager-opp-0001", "doc": DOC}, [{"key": w["key"], "doc": w.get("doc")} for w in watch])
            # cria uma vez só
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--onepager", OUTRA, "--parent", PASTA).returncode, 4)
            self.assertEqual(self._status(td)["todo"], [])
            # arquivo de outra pessoa ligado → pendente até virar sugestão no one-pager
            url = "https://docs.google.com/spreadsheets/d/1PlanilhaPlanilha/edit"
            self._ok(td, "doc", "link", "OPP-0001", "--kind", "planilha", "--ref", url, "--title", "Base de tickets",
                     "--prov", "observado", "--source", "RAW/inbox/x.md")
            self.assertIn("OPP-0001", self._ok(td, "oppdrive", "status", "--pending"))
            self.assertEqual(self._run(td, "oppdrive", "suggested", "OPP-0001", "--doc", OUTRA, "--what", "x").returncode, 4)
            self._ok(td, "oppdrive", "suggested", "OPP-0001", "--doc", DOC, "--what", f"Arquivos relacionados: {url}")
            self.assertTrue(self._status(td)["related"][0]["in_onepager"])
            self.assertIn("nada pendente", self._ok(td, "oppdrive", "status", "--pending"))
            self.assertIn("✓", self._ok(td, "validate"))

    def _linked(self, td):
        self._ok(td, "oppdrive", "record", "OPP-0001", "--folder", PASTA, "--parent", RAIZ)
        self._ok(td, "oppdrive", "record", "OPP-0001", "--onepager", DOC, "--parent", PASTA)

    def test_build_sync_and_divergence(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            self._linked(td)
            self.assertEqual(self._status(td)["template"], "antigo")
            detail, plan = Path(td) / "d.md", Path(td) / "plan.json"
            detail.write_text("### Proposta\n1. **Fila única** de triagem\n2. Regras por [tipo](https://example.com/x)\n", "utf-8")
            sync = json.loads(self._ok(td, "oppdrive", "sync", "OPP-0001", "--json"))
            self.assertEqual(sync["state"], "template-antigo")
            self._ok(td, "oppdrive", "build", "OPP-0001", "--detail", str(detail), "--end", "300", "--out", str(plan))
            p = json.loads(plan.read_text())
            self.assertEqual((p["documentId"], p["writeControl"]), (DOC, {"writeMode": "EDIT"}))
            self.assertEqual(p["requests"][0], {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 299}}})
            names = {r["createNamedRange"]["name"] for r in p["requests"] if "createNamedRange" in r}
            self.assertEqual(names, {f"brain:{k}" for k in onepager.KEYS + ["carimbo"]})
            self.assertEqual(p["fields"]["problema"], "triagem manual")
            self._ok(td, "oppdrive", "synced", "OPP-0001", "--plan", str(plan))
            self.assertEqual(self._status(td)["template"], "novo")
            # o template novo não é reescrito inteiro: o Detalhamento é de quem edita
            self.assertEqual(self._run(td, "oppdrive", "build", "OPP-0001", "--detail", str(detail), "--end", "2",
                                       "--out", str(plan)).returncode, 4)
            self.assertIn("· ok ·", self._ok(td, "oppdrive", "sync", "OPP-0001"))
            # Brain mudou → só o campo que mudou (e o carimbo), por intervalo nomeado
            self._ok(td, "opportunity", "update", "OPP-0001", "--gain", "menos retrabalho", "--by", "owner")
            out = Path(td) / "sync.json"
            self.assertIn("desatualizado", self._ok(td, "oppdrive", "sync", "OPP-0001", "--out", str(out)))
            reqs = json.loads(out.read_text())["requests"]
            self.assertEqual([r["replaceNamedRangeContent"]["namedRangeName"] for r in reqs], ["brain:ganho", "brain:carimbo"])
            self._ok(td, "oppdrive", "synced", "OPP-0001", "--plan", str(out))
            # alguém editou o Resumo no doc (export com cabeçalho vazio e escapes, como o Drive devolve)
            snap = Path(td) / "snap.md"
            snap.write_text("|  |  |  |\n| :-: | :-: | :-: |\n| \\*\\*Área\\*\\* | \\*\\*Tipo\\*\\* | \\*\\*Status\\*\\* |\n"
                            "| operacoes | melhoria-de-processo | ideia |\n\n|  |  |\n| :-: | :-: |\n"
                            "| **Problema** | triagem manual e lenta |\n| **Ganho esperado** | menos   retrabalho |\n", "utf-8")
            parsed = onepager.parse_markdown(snap.read_text())
            self.assertEqual((parsed["problema"], parsed["status"]), ("triagem manual e lenta", "ideia"))
            div = json.loads(self._ok(td, "oppdrive", "sync", "OPP-0001", "--snapshot", str(snap), "--json"))
            self.assertEqual((div["state"], div["divergent"], div["n_requests"]), ("divergente", ["problema"], 0))
            asks = json.loads(self._ok(td, "ask", "list", "--open", "--json"))
            self.assertEqual(asks[0]["id"], div["ask"])
            self.assertIn("triagem manual e lenta", asks[0]["text"])
            # mesma divergência de novo: mesma pergunta, não outra
            again = json.loads(self._ok(td, "oppdrive", "sync", "OPP-0001", "--snapshot", str(snap), "--json"))
            self.assertEqual(again["ask"], div["ask"])
            # resposta "o Brain vale" → --force reescreve tudo
            self.assertIn("--force", self._ok(td, "oppdrive", "sync", "OPP-0001", "--force", "--out", str(out)))
            self.assertIn("✓", self._ok(td, "validate"))

    def test_ids_links_stamp_and_fontes(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            self._linked(td)
            raw = Path(td) / "vault" / "RAW" / "2026" / "10"
            for kind, name, text in (("meetings", "reuniao.md", "transcricao secreta"), ("documents", "playbook.md", "# Playbook")):
                (raw / kind).mkdir(parents=True, exist_ok=True)
                (raw / kind / name).write_text(text, "utf-8")
            self._ok(td, "person", "add", "Ana Souza", "--id", "ana", "--alias", "ana", "--by", "owner")
            self._ok(td, "artifact", "PROCESSED/2026/10/reuniao.md", "--kind", "reuniao", "--title", "Alinhamento — 23/10/2026",
                     "--raw", "RAW/2026/10/meetings/reuniao.md", "--people", "ana", "--by", "agent", "--prov", "observado",
                     "--source", "RAW/2026/10/meetings/reuniao.md", "--date", "2026-10-23")
            self._ok(td, "artifact", "PROCESSED/2026/10/playbook.md", "--kind", "documento", "--title", "Playbook de triagem",
                     "--raw", "RAW/2026/10/documents/playbook.md", "--by", "agent", "--prov", "observado",
                     "--source", "RAW/2026/10/documents/playbook.md", "--date", "2026-10-20")
            for src in ("PROCESSED/2026/10/reuniao.md", "PROCESSED/2026/10/playbook.md"):
                self._ok(td, "opportunity", "evidence", "OPP-0001", "--source", src, "--by", "owner")
            self._ok(td, "opportunity", "add", "Outra ideia", "--area", "operacoes", "--by", "owner",
                     "--problem", "ligada à OPP-0001 e ao PROJ-9", "--force")
            _, f = onepager.fields(_brain_of(td), "OPP-0002")
            self.assertIn("OPP-0001: Roteamento de tickets", f["problema"])       # ID sempre com título
            self.assertIn("PROJ-9", f["problema"])                                 # PROJ-# pode ser do Jira: não se mexe
            self.assertRegex(onepager.stamp(), r"^Resumo atualizado em \d{2}/\d{2}/\d{4} \d{2}:\d{2}$")
            md = self._ok(td, "oppdrive", "onepager", "OPP-0001")
            self.assertIn("Reunião Alinhamento — 23/10/2026 · participantes: Ana Souza", md)
            self.assertNotIn("transcricao secreta", md)
            # Fontes: só documento sobe; reunião é menção
            st = self._status(td)
            self.assertEqual(st["todo"], ["fontes"])
            self.assertEqual([x["name"] for x in st["upload"]], ["playbook.md"])
            self.assertEqual(len(st["mention"]), 1)
            FONTES, ARQ = "1FontesFontesFontes", "1ArquivoArquivoArq"
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--sources-folder", FONTES, "--parent", OUTRA).returncode, 4)
            self._ok(td, "oppdrive", "record", "OPP-0001", "--sources-folder", FONTES, "--parent", PASTA)
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--sources-folder", FONTES, "--parent", PASTA).returncode, 4)
            self.assertEqual(self._run(td, "oppdrive", "record", "OPP-0001", "--source-file", ARQ, "--raw", "reuniao.md",
                                       "--parent", FONTES).returncode, 4)     # transcrição nunca sobe
            self._ok(td, "oppdrive", "record", "OPP-0001", "--source-file", ARQ, "--raw", "playbook.md", "--parent", FONTES)
            st = self._status(td)
            self.assertEqual((st["todo"], st["upload"], st["related"]), ([], [], []))
            # links: a OPP citada com one-pager vira link; o documento enviado também
            self._ok(td, "oppdrive", "record", "OPP-0002", "--folder", OUTRA, "--parent", RAIZ)
            self._ok(td, "oppdrive", "record", "OPP-0002", "--onepager", "1Doc2Doc2Doc2Doc2", "--parent", OUTRA)
            _, f2 = onepager.fields(_brain_of(td), "OPP-0002")
            lk = onepager.links(_brain_of(td), "OPP-0002", f2)
            self.assertEqual(lk, {"OPP-0001: Roteamento de tickets": onepager.DOC_URL.format(DOC)})
            lk1 = onepager.links(_brain_of(td), "OPP-0001", onepager.fields(_brain_of(td), "OPP-0001")[1])
            self.assertEqual(list(lk1.values()), [onepager.FILE_URL.format(ARQ)])
            # Detalhamento: ID solto vira `ID: Título` e, com one-pager, link
            d = onepager.expand_detail(_brain_of(td), "- ver OPP-0001 e [OPP-0001: x](https://e.com) e OPP-0002: Outra ideia")
            self.assertIn(f"[OPP-0001: Roteamento de tickets]({onepager.DOC_URL.format(DOC)})", d)
            self.assertIn("[OPP-0001: x](https://e.com)", d)
            self.assertIn("[OPP-0002: Outra ideia](https://docs.google.com/document/d/1Doc2Doc2Doc2Doc2/edit)", d)
            # sync detecta link novo sem campo mudado: o plano vem sem pedidos de campo, e `links` casa com o doc
            plan = Path(td) / "p.json"
            self._ok(td, "oppdrive", "build", "OPP-0002", "--detail", str(self._write(td, "d.md", "### Timeline\n- OPP-0001")),
                     "--end", "2", "--out", str(plan))
            reqs = json.loads(plan.read_text())["requests"]
            links_in_table = [r for r in reqs if "updateTextStyle" in r and "link" in r["updateTextStyle"]["textStyle"]]
            self.assertTrue(any(r["updateTextStyle"]["textStyle"]["link"]["url"] == onepager.DOC_URL.format(DOC)
                                for r in links_in_table))
            self.assertIn("✓", self._ok(td, "validate"))

    def _write(self, td, name, text):
        p = Path(td) / name
        p.write_text(text, "utf-8")
        return p

    def test_link_requests_on_written_doc(self):
        def doc(runs):
            els, at = [], 10
            for text, link in runs:
                els.append({"startIndex": at, "endIndex": at + len(text), "textRun": {
                    "content": text, "textStyle": {"link": {"url": link}} if link else {}}})
                at += len(text)
            row = {"tableCells": [{"content": [{"paragraph": {"elements": els}}]}]}
            return {"body": {"content": [{"table": {"tableRows": [row]}}]}}
        url, lab = "https://docs.google.com/document/d/X/edit", "OPP-0001: Roteamento"
        reqs = onepager.link_requests(doc([(f"ver {lab}\n", None)]), {lab: url})
        self.assertEqual(reqs[0]["updateTextStyle"]["range"], {"startIndex": 14, "endIndex": 14 + len(lab)})
        self.assertEqual(onepager.link_requests(doc([("ver ", None), (lab, url), ("\n", None)]), {lab: url}), [])
        stale = onepager.link_requests(doc([(f"ver {lab}\n", url)]), {lab: url})      # texto novo herdou o link
        self.assertEqual(len(stale), 2)
        self.assertNotIn("link", stale[0]["updateTextStyle"]["textStyle"])

    def test_table_cell_indices(self):
        pl = onepager._Plan()
        pl.table([[("a", None, True), ("b", "x", False), ("c", None, False)],
                  [("d", None, False), ("e", None, False), ("f", "y", False)]], [(0, 0)])
        at = [r["insertText"]["location"]["index"] for r in pl.reqs if "insertText" in r][1:]
        self.assertEqual(at, [16, 14, 12, 9, 7, 5])          # tabela em 2: células de trás para frente
        # padrão de tabela: rótulo na cor da marca, texto branco; valor preto; mesmas posições que o doc terá
        heads = [r["updateTableCellStyle"]["tableCellStyle"]["backgroundColor"] for r in pl.reqs
                 if "tableRange" in r.get("updateTableCellStyle", {})]
        self.assertEqual(heads, [onepager.HEAD_BG])
        texts = [(r["updateTextStyle"]["range"]["startIndex"], r["updateTextStyle"]["range"]["endIndex"],
                  r["updateTextStyle"]["textStyle"]["foregroundColor"] == onepager.WHITE)
                 for r in pl.reqs if "foregroundColor" in r.get("updateTextStyle", {}).get("textStyle", {})]
        self.assertEqual(texts, [(5, 22, False), (5, 6, True)])       # tabela toda preta, depois o rótulo em branco
        doc = {"content": {"documentId": DOC, "tabs": [{"documentTab": {"body": {"content": [
            {"startIndex": 2, "endIndex": 12, "table": {"rows": 1, "columns": 3, "tableRows": [{"tableCells": [
                {"endIndex": 7, "content": [{"startIndex": 5}]}, {"endIndex": 9, "content": [{"startIndex": 7}]},
                {"endIndex": 11, "content": [{"startIndex": 9}]}]}]}},
            {"startIndex": 13, "endIndex": 20, "table": {"rows": 1, "columns": 2, "tableRows": [{"tableCells": [
                {"endIndex": 17, "content": [{"startIndex": 16}]}, {"endIndex": 19, "content": [{"startIndex": 18}]}]}]}}]}}}]}}
        rs = onepager.restyle_requests(doc)
        self.assertTrue(any("updateTableColumnProperties" in r for r in rs))   # coluna de rótulo com largura fixa
        self.assertEqual(sum("tableRange" in r.get("updateTableCellStyle", {}) for r in rs), 2)   # uma faixa por tabela
        self.assertEqual(onepager.u16("é𝄞"), 3)

    def test_door_tools_only_when_enabled(self):
        cfg = {"runner": {"allow": []}, "oppdrive": {"enabled": True, "root": RAIZ, "tools": TOOLS}}
        self.assertEqual(runner.door_allow(cfg), TOOLS)
        self.assertEqual(runner.door_allow({**cfg, "oppdrive": {**cfg["oppdrive"], "enabled": False}}), [])
        self.assertEqual(runner.door_allow({**cfg, "oppdrive": {**cfg["oppdrive"], "root": ""}}), [])


if __name__ == "__main__":
    unittest.main()
