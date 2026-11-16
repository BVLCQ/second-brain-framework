"""Molde das issues públicas + validadores de dado sensível (porta 7). stdlib unittest, sem rede.

Todo exemplo usa os dados fictícios da padaria (marina-demo, Padaria Pão Quente, example.com).
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import cli, config, feedback, issues, publicguard, util
from brainlib.core import Brain

PADARIA_SUGESTAO = (
    "### Resumo\nAvisar quando a massa da Padaria Pão Quente passar do ponto.\n\n"
    "### Problema\nA marina-demo esquece a fermentação de 12 horas e perde a fornada.\n\n"
    "### Proposta\nUm lembrete `brain action open \"Assar a fornada\" --due 2026-01-10` com aviso 1h antes.\n\n"
    "### Alternativas consideradas\nAlarme no celular — não fica registrado no ledger.\n\n"
    "### Como validar\nCriar a ação de teste com contato@example.com e conferir o aviso.")


def _brain(tmp: Path) -> Brain:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "RAW/inbox", "PROCESSED", "FRESH"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner", "data": {"name": "Dona", "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "rosana", "by": "owner",
                  "data": {"name": "Rosana Silveira", "email": "rosana@empresa-real.com.br"}})
    return b


class GuardRulesTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.inst = _brain(Path(self._td.name)).inst

    def kinds(self, text: str) -> set[str]:
        return {k for k, _ in publicguard.scan(self.inst, text)}

    def test_padaria_e_dado_ficticio_passam(self):
        ok = ("A Padaria Pão Quente (marina-demo, heitor-demo) manda para contato@example.com; docs em "
              "https://github.com/BVLCQ/second-brain-framework/issues e `@dataclass` em http://localhost:8765. "
              "Versão 2.10.1, commit 4acacd2e4f1b, 2026-11-16 09:55, brain watch docs --revs x.json.")
        self.assertEqual(self.kinds(ok), set())

    def test_cada_regra_pega_o_seu_caso(self):
        cases = {
            "imagem ou print": ["veja ![erro](https://x/y.png)", "anexei erro-forno.png", "<img src=a>",
                                "https://github.com/user-attachments/assets/abc", "arquivo gravacao.mp4"],
            "link externo": ["https://meu-site.com.br/painel"],
            "link interno": ["docs.google.com/document/d/abc", "https://padaria.atlassian.net/browse/X-1",
                             "https://notion.so/pagina"],
            "e-mail": ["fale com joana@padaria-real.com.br"],
            "@menção": ["cc @joana-silva por favor"],
            "telefone": ["ligue (11) 98888-7777", "zap 98888-7777", "+55 11 98888-7777"],
            "CPF/CNPJ": ["cpf 123.456.789-09", "cnpj 12.345.678/0001-95"],
            "endereço IP": ["servidor 10.20.30.40"],
            "ID opaco (Drive/Slack…)": ["doc 1z02OEa45FLgbYjT1yoQDwGY2m77DJio3kiiDDFcdAPQ", "canal C08ABCD1234"],
            "dado pessoal (pessoa)": ["pedido da Rosana Silveira"],
            "dado pessoal (domínio)": ["rosana@empresa-real.com.br"],
            "dado pessoal (dono)": ["a Dona abriu"],
            "caminho da máquina": ["em " + str(Path.home()) + "/brain/vault"],
        }
        for kind, texts in cases.items():
            for t in texts:
                self.assertIn(kind, self.kinds(t), f"{kind!r} não pegou {t!r}: {self.kinds(t)}")

    def test_menção_dentro_de_codigo_e_decorador_nao_conta(self):
        self.assertEqual(self.kinds("use `@property` ou\n```\n@dataclass\nclass A: ...\n```"), set())
        self.assertIn("@menção", self.kinds("obrigada @fulano"))

    def test_demo_marca_dado_ficticio(self):
        self.assertEqual(self.kinds("joana-demo pediu; contato-demo@example.org"), set())

    def test_mensagem_diz_o_que_e_onde_sem_ecoar_o_valor(self):
        with self.assertRaises(util.BrainError) as cm:
            publicguard.guard(self.inst, "Erro", "linha 1 ok\nfale com joana@padaria-real.com.br\n")
        msg = str(cm.exception)
        self.assertIn("e-mail", msg)
        self.assertIn("corpo, linha 2", msg)
        self.assertNotIn("joana", msg)
        self.assertNotIn("padaria-real", msg)
        self.assertIn("padaria", msg)                       # orienta para o exemplo fictício


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.inst = _brain(Path(self._td.name)).inst

    def test_esqueleto_passa_no_validador_e_nao_passa_na_estrutura(self):
        for kind in issues.KINDS:
            sk = issues.skeleton(kind)
            publicguard.guard(self.inst, "t", sk)           # o próprio molde não pode ser recusado
            self.assertTrue(issues.problems(kind, sk))      # em branco não vale como preenchido

    def test_exemplo_da_padaria_segue_o_molde(self):
        self.assertEqual(issues.problems("sugestao", PADARIA_SUGESTAO), [])
        publicguard.guard(self.inst, "Avisar a fornada", PADARIA_SUGESTAO)

    def test_campo_obrigatorio_vazio_e_campo_fora_do_molde(self):
        ps = issues.problems("bug", "### Resumo\nx\n\n### Invento\ny")
        self.assertTrue(any("O que aconteceu" in p for p in ps))
        self.assertTrue(any("fora do molde" in p for p in ps))

    def test_formularios_do_github_tem_os_mesmos_campos_do_molde(self):
        files = {"sugestao": "sugestao.yml", "bug": "bug.yml", "framework": "proposta-codigo.yml"}
        for kind, name in files.items():
            text = (ROOT / ".github" / "ISSUE_TEMPLATE" / name).read_text(encoding="utf-8")
            labels = re.findall(r"^      label: '?(.+?)'?$", text, re.M)
            want = [head for _k, head, _h, _r in issues.TEMPLATES[kind]["fields"]]
            self.assertEqual([x for x in labels if x != "Privacidade"], want, name)
            reqs = re.findall(r"required: (true|false)", text)
            self.assertEqual(reqs[:len(want)], ["true" if r else "false" for *_x, r in issues.TEMPLATES[kind]["fields"]])
            self.assertIn("Privacidade", labels)
            self.assertIn("padaria", text.lower())          # o aviso do exemplo fictício está no formulário


class TitleTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.brain = _brain(Path(self._td.name))

    def test_tags_oficiais_por_origem(self):
        feedback.add(self.brain, "sugestao", "Avisar a fornada", PADARIA_SUGESTAO)
        feedback.add(self.brain, "bug", "Painel demora")
        f1, f2 = self.brain.state.feedbacks["FB-0001"], self.brain.state.feedbacks["FB-0002"]
        self.assertEqual(feedback.issue_title(f1), "[Sugestão] Avisar a fornada")
        self.assertEqual(feedback.issue_title(f2), "[Bug] Painel demora")
        f1.proposal = "PROP-0001"                                    # veio de proposta de código aceita
        self.assertEqual(feedback.issue_title(f1), "[Proposta] Avisar a fornada")

    def test_tag_escrita_a_mao_e_id_local_na_frente_saem_do_titulo(self):
        for raw in ("[bug] Painel demora", "[Bug]  Painel demora", "FB-0003: Painel demora", "FB-0003 · [sugestão] Painel demora"):
            self.assertEqual(issues.strip_tag(raw), "Painel demora", raw)
        self.assertEqual(issues.strip_tag("Painel [novo] demora"), "Painel [novo] demora")   # só prefixo
        feedback.add(self.brain, "bug", "[bug] FB-0009 Painel demora")
        self.assertEqual(feedback.issue_title(self.brain.state.feedbacks["FB-0001"]), "[Bug] Painel demora")

    def test_titulo_com_tag_diferente_conta_como_duplicado(self):
        feedback.add(self.brain, "bug", "Painel demora")
        with self.assertRaises(util.BrainError):
            feedback.add(self.brain, "bug", "[bug] painel DEMORA")

    def test_o_que_sobe_nao_carrega_nenhum_id_local(self):
        feedback.add(self.brain, "bug", "FB-0004 Painel demora", "### Resumo\nr\n\n### O que aconteceu\na\n\n"
                     "### O que era esperado\ne\n\n### Como reproduzir\n1. abrir")
        f = self.brain.state.feedbacks["FB-0001"]
        for text in (feedback.issue_title(f), feedback.issue_body(f)):
            self.assertEqual(feedback.VAULT_REF_RE.findall(text), [], text)
        feedback.refs_guard(feedback.issue_title(f), feedback.issue_body(f))     # a trava final do push passa


class FlowTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)
        self.brain = _brain(self.tmp)
        os.environ["BRAIN_HOME"] = str(self.tmp)
        os.environ.pop("GITHUB_TOKEN", None)
        self.addCleanup(lambda: os.environ.pop("BRAIN_HOME", None))

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_agente_precisa_seguir_o_molde(self):
        rc, _o, e = self.run_cli("feedback", "add", "Avisar a fornada", "--kind", "sugestao", "--no-push",
                                 "--body", "texto solto", "--by", "agent", "--prov", "observado", "--source", "chat")
        self.assertNotEqual(rc, 0)
        self.assertIn("molde", e)
        f = self.tmp / "corpo.md"
        f.write_text(PADARIA_SUGESTAO, encoding="utf-8")
        rc, o, e = self.run_cli("feedback", "add", "Avisar a fornada", "--kind", "sugestao", "--no-push",
                                "--body-file", str(f), "--by", "agent", "--prov", "observado", "--source", "chat")
        self.assertEqual(rc, 0, e)
        self.assertIn("FB-0001", o)

    def test_dono_pode_texto_livre_mas_nao_dado_sensivel(self):
        rc, _o, e = self.run_cli("feedback", "add", "Dashboard lento", "--kind", "bug", "--no-push",
                                 "--body", "demora para abrir", "--by", "owner")
        self.assertEqual(rc, 0, e)
        rc, _o, e = self.run_cli("feedback", "add", "Outra", "--kind", "bug", "--no-push",
                                 "--body", "mandei para rosana@empresa-real.com.br", "--by", "owner")
        self.assertNotEqual(rc, 0)
        self.assertIn("e-mail", e)
        self.assertEqual(len(self.brain.reload() or self.brain.state.feedbacks), 1)    # nada gravado

    def test_push_recusa_print_mesmo_de_fb_antigo_no_ledger(self):
        feedback.add(self.brain, "bug", "Erro visual", "veja ![x](https://github.com/user-attachments/a)")
        (self.brain.inst.config_dir / ".env").write_text("GITHUB_TOKEN=fake-token-teste\n", encoding="utf-8")
        called = []
        orig = feedback.create_issue
        feedback.create_issue = lambda *a, **k: called.append(1) or {"number": 1, "url": "u"}
        try:
            with self.assertRaises(util.BrainError) as cm:
                feedback.push(self.brain, "FB-0001")
        finally:
            feedback.create_issue = orig
        self.assertIn("imagem ou print", str(cm.exception))
        self.assertEqual(called, [])

    def test_revise_corrige_texto_e_liga_a_proposta(self):
        pid = self.brain.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "chat", "data": {
            "kind": "framework", "summary": "s", "issue_title": "t", "issue_body": "b"}})["id"]
        self.brain.record_one({"type": "proposal.accepted", "id": pid, "by": "owner", "data": {"quote": "ok"}})
        feedback.add(self.brain, "sugestao", "Titulo velho", "texto antigo")
        body = ("### Resumo\nr\n\n### Contexto\nc\n\n### Proposta\np\n\n### Critérios de aceite\n- a")
        rc, _o, e = self.run_cli("feedback", "revise", "FB-0001", "--title", "Titulo novo", "--body", body,
                                 "--proposal", pid)
        self.assertEqual(rc, 0, e)
        f = self.brain.reload() or self.brain.state.feedbacks["FB-0001"]
        self.assertEqual((f.title, f.proposal), ("Titulo novo", pid))
        self.assertEqual(self.brain.state.proposals[pid].feedback, "FB-0001")
        self.assertIn("🧩 proposta de código", feedback.issue_body(f))
        self.assertIn("[Proposta] Titulo novo", feedback.issue_title(f))

    def test_revise_liga_proposta_antiga_do_tipo_outro_se_aceita(self):
        pid = self.brain.record_one({"type": "proposal.opened", "by": "agent", "prov": "observado", "source": "chat",
                                     "data": {"kind": "outro", "summary": "melhoria de código"}})["id"]
        feedback.add(self.brain, "sugestao", "Algo")
        with self.assertRaises(util.BrainError):                 # ainda aberta: não vale
            feedback.revise(self.brain, "FB-0001", proposal=pid)
        self.brain.record_one({"type": "proposal.accepted", "id": pid, "by": "owner", "data": {"quote": "ok"}})
        feedback.revise(self.brain, "FB-0001", proposal=pid)
        self.assertEqual(self.brain.state.feedbacks["FB-0001"].proposal, pid)

    def test_revise_nao_vale_depois_da_issue_criada_nem_com_dado_sensivel(self):
        feedback.add(self.brain, "bug", "Algo")
        rc, _o, e = self.run_cli("feedback", "revise", "FB-0001", "--body", "fale com a Rosana Silveira")
        self.assertNotEqual(rc, 0)
        self.assertIn("dado pessoal", e)
        self.brain.record_one({"type": "feedback.pushed", "id": "FB-0001", "by": "system",
                               "data": {"number": 3, "url": "https://github.com/o/r/issues/3"}})
        with self.assertRaises(util.BrainError):
            feedback.revise(self.brain, "FB-0001", body="outro texto")

    def test_template_na_cli(self):
        rc, o, _e = self.run_cli("feedback", "template", "--kind", "framework")
        self.assertEqual(rc, 0)
        self.assertIn("### Critérios de aceite", o)

    def test_proposta_framework_exige_molde_e_guarda(self):
        base = ["proposal", "add", "--kind", "framework", "--summary", "s", "--issue-title", "Lote de docs",
                "--by", "agent", "--prov", "observado", "--source", "chat"]
        rc, _o, e = self.run_cli(*base, "--issue-body", "texto solto")
        self.assertNotEqual(rc, 0)
        self.assertIn("molde", e)
        bad = FlowTest.FRAMEWORK.replace("36 fichas", "36 fichas (ver docs.google.com/document/d/abc)")
        rc, _o, e = self.run_cli(*base, "--issue-body", bad)
        self.assertNotEqual(rc, 0)
        self.assertIn("link", e)
        f = self.tmp / "corpo.md"
        f.write_text(FlowTest.FRAMEWORK, encoding="utf-8")
        rc, _o, e = self.run_cli(*base, "--issue-body-file", str(f))
        self.assertEqual(rc, 0, e)

    FRAMEWORK = ("### Resumo\nChecar docs em lote.\n\n### Contexto\nA Padaria Pão Quente vigia 36 fichas.\n\n"
                 "### Proposta\nUm comando lista as fichas.\n\n### Critérios de aceite\n- só o alterado é lido")


if __name__ == "__main__":
    unittest.main()
