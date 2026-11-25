"""Portão de dados do repositório público (`scripts/dev/public_gate.py`): o CI só deixa entrar o que a varredura deixa.

O repositório de prova é real (git de verdade) e a lista privada é um arquivo: termo bloqueado sem
eco do valor, lista ausente ou vazia, regras do brain e o PR que tenta ditar a própria varredura.
"""
from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, upstream


def _load():
    spec = importlib.util.spec_from_file_location("public_gate", ROOT / "scripts" / "dev" / "public_gate.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)
    return r.stdout.strip()


def _repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "Teste")
    (repo / "notas.md").write_text("primeira revisão\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _commit(repo: Path, name: str, text: str, msg: str = "mais um") -> str:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _denylist(tmp: Path, text: str) -> Path:
    path = tmp / "lista-privada"
    path.write_text(text, encoding="utf-8")
    return path


# caminho de máquina montado por partes: escrito inteiro aqui, o próprio arquivo de teste viria achado
MACHINE_PATH = "/Use" + "rs/pessoa-real/projeto"


class GateTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self._leak = upstream._leak_terms
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo = _repo(self.tmp)
        self.base = _git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        upstream._leak_terms = self._leak

    def _gate(self, base: str | None = None) -> tuple[int, str]:
        out = io.StringIO()
        deny = _denylist(self.tmp, "acme-corp\nrede-interna\n")
        with mock.patch("sys.stdout", out):
            code = self.mod.main(["gate", "--base", base or self.base, "--root", str(self.repo),
                                  "--denylist", str(deny)], trusted=self.tmp / "confiavel")
        return code, out.getvalue()

    def test_lista_privada_uma_por_linha_ou_virgula_comentario_ignorado_e_termo_curto_e_erro(self):
        parse = self.mod.parse_denylist
        self.assertEqual(parse("acme-corp\n, rede-interna,,\n"), ["acme-corp", "rede-interna"])
        self.assertEqual(parse("ACME-corp, acme-corp"), ["ACME-corp"])
        self.assertEqual(parse(""), [])
        # linha que começa com `#` é comentário inteiro: a vírgula dentro dela não vira termo
        self.assertEqual(parse("# nota, com vírgula\nacme-corp\n\n   \n"), ["acme-corp"])
        # termo curto demais ao lado de um válido não some em silêncio: a lista deixaria de cobrir
        for lista in ("acme-corp\nab\n", "acme-corp, e:"):
            with self.subTest(lista=lista), self.assertRaises(RuntimeError) as cm:
                parse(lista)
            self.assertNotIn("ab", str(cm.exception))                 # o erro não ecoa o termo
            self.assertNotIn("e:", str(cm.exception))

    def test_diff_limpo_passa(self):
        _commit(self.repo, "cliente.md", "conta da marina-demo no relatório\n")
        self.assertEqual(self._gate(), (self.mod.CLEAN, "✓ portão de dados limpo em %s..HEAD\n" % self.base))

    def test_termo_da_lista_privada_bloqueia_e_nao_ecoa_o_valor(self):
        _commit(self.repo, "cliente.md", "conta da acme-corp no relatorio\n")
        code, out = self._gate()
        self.assertEqual(code, self.mod.FOUND)
        self.assertIn("lista privada", out)
        self.assertIn("cliente.md", out)
        for valor in ("acme-corp", "rede-interna", "lista-privada"):     # só arquivo, linha e regra
            self.assertNotIn(valor, out)

    def test_termo_na_mensagem_do_commit_tambem_bloqueia(self):
        _commit(self.repo, "notas.md", "sem dado nenhum aqui\n", msg="conta da rede-interna migrada")
        self.assertEqual(self._gate()[0], self.mod.FOUND)

    def test_regra_do_brain_continua_valendo_caminho_de_maquina(self):
        _commit(self.repo, "instalacao.md", f"roda em {MACHINE_PATH}/brain\n")
        rules = {f["rule"] for f in self.mod.scan_range(self.repo, self.base, trusted=self.tmp)}
        self.assertIn("caminho da máquina", rules)

    def test_lista_privada_e_regra_da_instancia_somam(self):
        restore = self.mod.install_denylist(["acme-corp"])
        try:
            kinds = {kind for _, kind in upstream._leak_terms(config.load(self.tmp))}
        finally:
            upstream._leak_terms = restore
        self.assertIn(self.mod.KIND, kinds)

    def test_lista_privada_sem_termo_valido_e_erro_nao_limpo(self):
        _commit(self.repo, "notas.md", "diff limpo\n")                  # o erro é da lista, não do diff
        out = io.StringIO()
        sem_termo = (self.tmp / "nao-existe", _denylist(self.tmp, ""), _denylist(self.tmp, "e:\nab\n"),
                     _denylist(self.tmp, "# tudo comentado, nada vale\n"), _denylist(self.tmp, "acme-corp\nab\n"))
        for path in sem_termo:
            with self.subTest(lista=path.name), mock.patch("sys.stdout", out):
                code = self.mod.main(["gate", "--base", self.base, "--root", str(self.repo),
                                      "--denylist", str(path)], trusted=self.tmp)
            self.assertEqual(code, self.mod.ERROR)
            self.assertIn("✗ portão de dados: lista privada", out.getvalue())
        # a lista veio inteira em comentário ou perdeu um termo: o portão não atesta "limpo"
        self.assertNotIn("limpo", out.getvalue())
        self.assertNotIn("nao-existe", out.getvalue())                  # nem o caminho da lista sai

    def test_o_pr_nao_dita_as_regras_da_varredura(self):
        # um config/brain.toml inválido na árvore do repo varrido não muda nada: a configuração
        # (e os termos dela) vem do checkout confiável, não do que o PR põe no disco
        _commit(self.repo, "notas.md", "diff limpo\n")
        (self.repo / "config").mkdir()
        (self.repo / "config" / "brain.toml").write_text("isto nao é toml =\n", encoding="utf-8")
        self.assertEqual(self._gate()[0], self.mod.CLEAN)

    def test_sem_root_varre_a_pasta_de_onde_foi_chamado(self):
        # o padrão antigo era o repositório do script: chamado de outro checkout, varria o lugar
        # errado — o alcance ficava vazio e o portão dava "limpo" sem olhar o commit
        _commit(self.repo, "instalacao.md", f"roda em {MACHINE_PATH}/brain\n")
        deny = _denylist(self.tmp, "acme-corp\n")
        out = io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            with mock.patch("sys.stdout", out):
                code = self.mod.main(["gate", "--base", self.base, "--denylist", str(deny)],
                                     trusted=self.tmp / "confiavel")
        finally:
            os.chdir(cwd)
        self.assertEqual(code, self.mod.FOUND, out.getvalue())

    def test_base_invalida_e_erro_nao_limpo(self):
        code, out = self._gate(base="ref-que-nao-existe")
        self.assertEqual(code, self.mod.ERROR)
        self.assertIn("✗ portão de dados:", out)


if __name__ == "__main__":
    unittest.main()
