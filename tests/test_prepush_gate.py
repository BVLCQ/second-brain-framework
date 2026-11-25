"""Hook pre-push com a lista privada da máquina: o portão de dados roda antes do push.

Na máquina de quem mantém, com a cópia da lista privada (`~/.config/brain/public-denylist`, ou
`$BRAIN_PUBLIC_DENYLIST`), o hook varre os commits do push com os termos da lista e barra o anexo
fechado — o que antes só o CI barrava, com o branch já público. Sem a lista, nada muda. A lista é
lida só no caminho do hook (`cli_upstream`); quem chama `pre_push_scan` direto passa a lista, ou não.

Termo de empresa é inventado (`acme-corp`, `rede-interna`). Todo push de verdade aqui leva
`BRAIN_PUBLIC_DENYLIST` explícito: a lista real de quem roda a suíte nunca entra.
"""
from __future__ import annotations

import contextlib
import gzip
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

from brainlib import config, upstream, util  # noqa: E402

LISTA = "# termos de teste\nacme-corp\nrede-interna\n"
ZERO = "0" * 40
REGRA_LISTA = upstream.term_rule("lista privada")
REGRA_ANEXO = "anexo fechado (a varredura não lê o que há dentro)"
MARCA = "com a lista privada desta máquina e o anexo fechado"
ZIP = b"PK\x03\x04" + b"\0" * 26


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


class PrePushGateTests(unittest.TestCase):
    """Um remoto bare e uma instância (B) que empurra para ele, como em `UpstreamTests`."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"})
        env.start()
        self.addCleanup(env.stop)
        for k in ("BRAIN_NIGHTLY", "BRAIN_PRE_PUSH", upstream.PRIVATE_DENYLIST_ENV):
            os.environ.pop(k, None)                       # dentro do patch.dict: volta no fim do teste
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.remote, self.b = self.tmp / "remote.git", self.tmp / "b"
        _git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        _git(self.tmp, "clone", "-q", str(self.remote), str(self.b))
        (self.b / ".gitignore").write_text("/vault/\nconfig/brain.toml\n/brain\n", encoding="utf-8")
        (self.b / "notas.md").write_text("primeira revisão\n", encoding="utf-8")
        self._commit("base")
        _git(self.b, "push", "-q", "origin", "HEAD:main")
        (self.b / "config").mkdir()
        (self.b / "config" / "brain.toml").write_text('[owner]\nid = "dona"\nname = "Fulana Quiteria"\n',
                                                      encoding="utf-8")
        (self.b / "vault" / "PROFILE").mkdir(parents=True)
        self.inst = config.load(self.b)
        self.lista = self.tmp / "lista-privada"
        self.lista.write_text(LISTA, encoding="utf-8")

    def _commit(self, msg: str = "mais um") -> str:
        _git(self.b, "add", "-A")
        _git(self.b, "commit", "-q", "-m", msg)
        return _git(self.b, "rev-parse", "HEAD").stdout.strip()

    def _write(self, name: str, data: str | bytes) -> None:
        p = self.b / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            p.write_text(data, encoding="utf-8")

    def _stdin(self, branch: str = "main", remote_sha: str | None = None) -> str:
        """A linha que o git passa ao hook ao empurrar HEAD para `branch` (sha remoto: o do origin/main)."""
        local = _git(self.b, "rev-parse", "HEAD").stdout.strip()
        remote = _git(self.b, "rev-parse", "origin/main").stdout.strip() if remote_sha is None else remote_sha
        return f"refs/heads/{branch} {local} refs/heads/{branch} {remote}\n"

    def _scan(self, stdin: str | None = None, denylist: Path | None = None) -> dict:
        return upstream.pre_push_scan(self.inst, "origin", stdin or self._stdin(), denylist=denylist)

    @staticmethod
    def _printed(st: dict) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            upstream._print_scan(st)
        return out.getvalue()

    # ---- sem a lista: nada muda -----------------------------------------------------------------

    def test_sem_lista_o_hook_segue_so_com_as_regras_publicas(self):
        self._write("notas.md", "contrato com a acme-corp\n")
        self._write("dados.zip", ZIP)
        self._commit()
        st = self._scan()
        self.assertEqual((st["findings"], st["private"]), ([], False))
        saida = self._printed(st)
        self.assertNotIn(MARCA, saida)
        self.assertIn("✓ varredura limpa", saida)                  # varreu os commits do push: não é "nada pendente"
        self.assertNotIn("nada pendente", saida)

    # ---- com a lista: o portão inteiro, só sobre o que o push leva ------------------------------

    def test_com_lista_termo_da_lista_barra_e_o_valor_nunca_sai(self):
        self._write("notas.md", "contrato com a acme-corp\n")
        self._commit("ajuste pedido pela rede-interna")
        antes = upstream._leak_terms
        st = self._scan(denylist=self.lista)
        self.assertIs(upstream._leak_terms, antes)                  # a lista não fica instalada depois
        self.assertNotIn("lista privada", upstream.PLAIN_KINDS)
        self.assertTrue(st["private"])
        onde = sorted((f["file"].split(" (commit")[0], f["line"]) for f in st["findings"] if f["rule"] == REGRA_LISTA)
        self.assertEqual(onde, [("(mensagem de commit)", 1), ("notas.md", 1)])
        saida = self._printed(st)
        self.assertIn(MARCA, saida)
        self.assertIn("notas.md", saida)                            # na máquina de quem mantém: com onde
        self.assertNotIn("acme-corp", saida)                        # o valor, nunca
        self.assertNotIn("rede-interna", saida)

    def test_com_lista_anexo_fechado_barra_pelo_nome_e_pela_assinatura(self):
        casos = (("pelo nome", "dados.zip", ZIP),
                 ("pela assinatura", "planilha.dat", gzip.compress(b"planilha de clientes")))
        for rotulo, nome, dado in casos:
            with self.subTest(caso=rotulo):
                _git(self.b, "reset", "-q", "--hard", "origin/main")
                self._write(nome, dado)
                self._commit("anexa")
                (self.b / nome).unlink()
                self._commit("tira")                                # o blob continua no histórico do push
                st = self._scan(denylist=self.lista)
                self.assertEqual([(f["file"], f["rule"]) for f in st["findings"]], [(nome, REGRA_ANEXO)])

    def test_o_alcance_e_o_do_push_o_que_ja_e_publico_fica_fora(self):
        self._write("antigo.md", "acme-corp\n")
        self._write("antigo.zip", ZIP)
        self._commit("antigo")
        _git(self.b, "push", "-q", "origin", "HEAD:main")           # sem hook neste clone: já é público
        for rotulo, conteudo, achou in (("commit novo limpo", "limpo\n", False),
                                        ("controle: commit novo com termo", "rede-interna\n", True)):
            self._write("novo.md", conteudo)
            self._commit("novo")
            for forma, stdin in (("branch que já existe", self._stdin()),
                                 ("branch nova", self._stdin(branch="feat", remote_sha=ZERO))):
                with self.subTest(caso=rotulo, forma=forma):
                    st = self._scan(stdin, denylist=self.lista)
                    self.assertTrue(st["private"])
                    self.assertEqual({f["file"].split(" (commit")[0] for f in st["findings"]},
                                     {"novo.md"} if achou else set())

    def test_mesmo_anexo_em_dois_refs_do_push_e_um_achado(self):
        self._write("dados.zip", ZIP)
        self._commit("anexa")
        head = _git(self.b, "rev-parse", "HEAD").stdout.strip()
        stdin = f"refs/heads/um {head} refs/heads/um {ZERO}\nrefs/heads/dois {head} refs/heads/dois {ZERO}\n"
        st = self._scan(stdin, denylist=self.lista)
        self.assertEqual(len(st["revsets"]), 2)
        self.assertEqual([(f["file"], f["rule"]) for f in st["findings"]], [("dados.zip", REGRA_ANEXO)])

    def test_apagar_ref_nao_varre_nem_precisa_do_portao(self):
        head = _git(self.b, "rev-parse", "HEAD").stdout.strip()
        with mock.patch.object(upstream, "GATE_SCRIPT", self.tmp / "nao-existe.py"):
            st = self._scan(f"refs/heads/feat {ZERO} refs/heads/feat {head}\n", denylist=self.lista)
        self.assertEqual((st["revsets"], st["findings"], st["private"]), ([], [], False))

    # ---- falha fecha: sem portão que rode, o push para -------------------------------------------

    def test_lista_quebrada_ou_ausente_barra_o_push_sem_ecoar_termo(self):
        self._write("notas.md", "limpo\n")
        self._commit()
        antes = upstream._leak_terms
        for rotulo, texto in (("termo curto", "acme-corp\nabc\n"), ("só comentário", "# nada\n"), ("vazia", "")):
            with self.subTest(caso=rotulo):
                self.lista.write_text(texto, encoding="utf-8")
                with self.assertRaises(util.BrainError) as cm:
                    self._scan(denylist=self.lista)
                self.assertEqual(cm.exception.code, 1)
                self.assertIn("portão de dados", str(cm.exception))
                self.assertNotIn("acme-corp", str(cm.exception))
                self.assertNotIn("abc", str(cm.exception))
        with self.subTest(caso="caminho que não existe"):
            with self.assertRaises(util.BrainError) as cm:
                self._scan(denylist=self.tmp / "sumiu")
            self.assertEqual(cm.exception.code, 1)
        self.assertIs(upstream._leak_terms, antes)

    def test_sem_o_script_do_portao_o_push_para(self):
        self._write("notas.md", "limpo\n")
        self._commit()
        with mock.patch.object(upstream, "GATE_SCRIPT", self.tmp / "nao-existe.py"), \
                self.assertRaises(util.BrainError) as cm:
            self._scan(denylist=self.lista)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn(f"{upstream.PRIVATE_DENYLIST_ENV}= (vazio)", str(cm.exception))

    # ---- onde a máquina guarda a lista -----------------------------------------------------------

    def test_onde_a_maquina_guarda_a_lista(self):
        home = self.tmp / "home"
        padrao = home / ".config" / "brain" / "public-denylist"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            os.environ.pop(upstream.PRIVATE_DENYLIST_ENV, None)
            self.assertIsNone(upstream.private_denylist())                         # sem lista: nada muda
            padrao.parent.mkdir(parents=True)
            padrao.write_text(LISTA, encoding="utf-8")
            self.assertEqual(upstream.private_denylist(), padrao)                  # a cópia de quem mantém
            os.environ[upstream.PRIVATE_DENYLIST_ENV] = ""
            self.assertIsNone(upstream.private_denylist())                         # vazia desliga, com a lista lá
            os.environ[upstream.PRIVATE_DENYLIST_ENV] = str(self.tmp / "outra")
            self.assertEqual(upstream.private_denylist(), self.tmp / "outra")      # caminho dito vale, mesmo sem arquivo
            os.environ[upstream.PRIVATE_DENYLIST_ENV] = "~/lista"
            self.assertEqual(upstream.private_denylist(), home / "lista")
            # algo no lugar da lista que não se lê (link quebrado) é lista pedida: o push para, não segue sem ela
            os.environ.pop(upstream.PRIVATE_DENYLIST_ENV)
            padrao.unlink()
            padrao.symlink_to(self.tmp / "sumiu")
            self.assertEqual(upstream.private_denylist(), padrao)
        self._write("notas.md", "limpo\n")
        self._commit()
        with self.assertRaises(util.BrainError) as cm:
            self._scan(denylist=padrao)
        self.assertEqual(cm.exception.code, 1)

    # ---- o push de verdade, pelo hook instalado --------------------------------------------------

    def test_push_de_verdade_pelo_hook_instalado(self):
        self.assertEqual(upstream.hook(self.inst, "install"), "instalado")
        (self.b / "brain").write_text(f"#!/bin/sh\nBRAIN_HOME={self.b} exec {sys.executable} {ROOT / 'brain'} \"$@\"\n",
                                      encoding="utf-8")
        (self.b / "brain").chmod(0o755)

        def push(lista: str) -> tuple[int, str]:
            r = subprocess.run(["git", "-C", str(self.b), "push", "origin", "HEAD:main"], capture_output=True, text=True,
                               env={**os.environ, upstream.PRIVATE_DENYLIST_ENV: lista})
            return r.returncode, r.stdout + r.stderr

        for rotulo, nome, dado, regra in (("termo da lista", "notas.md", "contrato com a acme-corp\n", REGRA_LISTA),
                                          ("anexo fechado", "planilha.dat", gzip.compress(b"planilha"), REGRA_ANEXO)):
            with self.subTest(caso=rotulo):
                _git(self.b, "reset", "-q", "--hard", "origin/main")
                self._write(nome, dado)
                self._commit()
                code, saida = push(str(self.lista))
                self.assertNotEqual(code, 0, saida)
                self.assertIn("push bloqueado", saida)
                self.assertIn(regra, saida)
                self.assertIn(MARCA, saida)
                self.assertNotIn("acme-corp", saida)
                code, saida = push("")                      # a mesma ponta, sem a lista, passa: é a lista que barra
                self.assertEqual(code, 0, saida)
                self.assertNotIn(MARCA, saida)
        self._write("limpo.md", "nada de mais\n")
        self._commit()
        code, saida = push(str(self.lista))
        self.assertEqual(code, 0, saida)
        self.assertIn(MARCA, saida)
        self.assertIn("✓ varredura limpa", saida)


if __name__ == "__main__":
    unittest.main()
