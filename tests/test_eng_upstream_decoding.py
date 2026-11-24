"""A saída do git é UTF-8 em qualquer locale, e nome com byte que não é UTF-8 válido nunca derruba o comando.

Saída da revisão independente dos commits que puseram `-z` e bytes nas listas de caminho do `upstream scan`:
- sem `encoding`, o subprocess decodifica o texto (diff, log) com o encoding do locale. Num locale de byte único
  (ISO-8859-1; `cp1252` no Windows em português é o mesmo mecanismo) o nome acentuado do cabeçalho do diff virava
  outro nome: o achado saía com o nome trocado, e o binário com nome acentuado não era lido — o segredo de
  dentro passava sem acusação;
- `os.fsdecode`, adotado naquela decodificação, levanta UnicodeDecodeError no Windows com byte isolado que não é
  UTF-8 válido (ali o handler é `surrogatepass`): a varredura e a leitura de repositório caíam em vez de guardar
  o byte;
- a mensagem de erro do git, lida em texto com `surrogateescape`, podia carregar surrogate para dentro do
  `BrainError` — e imprimir a exceção derrubava quem tratava do erro;
- `--json` sai com `ensure_ascii=False`, direto no stdout: nome com surrogate derrubava o print. O mesmo formato
  tinha `repos list` e `repos pull`, com o nome da pasta do repositório vindo do sistema de arquivos.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import repos, upstream, util  # noqa: E402


LOCAIS_BYTE_1 = ("pt_BR.ISO8859-1", "pt_BR.iso88591", "en_US.ISO8859-1", "en_US.iso88591", "fr_FR.iso88591")


def _filho(script: str, loc: str) -> str:
    """Roda o script num interpretador novo, no locale dado, sem variável do Python nem do Brain por perto. O
    fonte do filho é só ASCII e o acento vai por escape: o argumento de linha de comando é decodificado no encoding
    do locale, e um acento literal mudaria de forma antes de chegar ao filho."""
    limpo = {k: v for k, v in os.environ.items()
             if not k.startswith(("PYTHON", "BRAIN_")) and k not in ("LC_ALL", "LC_CTYPE", "LANG")}
    limpo.update({"LC_ALL": loc, "LC_CTYPE": loc, "LANG": loc})
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, errors="replace",
                       env=limpo, cwd=str(ROOT))
    return r.stdout


class GitOutputIsUtf8WhateverTheLocale(unittest.TestCase):
    """Num locale de byte único (ISO-8859-1 aqui; cp1252 no Windows em português é o mesmo mecanismo) o Python
    decodifica o texto do subprocess no encoding do locale. Sem `encoding="utf-8"` no `_git`, o nome acentuado do
    cabeçalho do diff chegava trocado: o achado saía com o nome errado, e o arquivo binário com nome acentuado
    não era lido — o git era pedido com o nome trocado e a falha era em silêncio. A lista de caminho (`_paths`, em
    bytes) sempre devolveu o nome certo. O locale C não serve de prova: nele o Python liga o modo UTF-8 sozinho."""

    @classmethod
    def setUpClass(cls):
        for loc in LOCAIS_BYTE_1:                      # o nome muda de sistema para sistema
            enc = _filho("import locale\nprint(locale.getencoding())", loc).splitlines()
            if enc and "8859" in enc[0].replace("-", ""):
                break
        else:
            raise unittest.SkipTest("nenhum locale de byte único (ISO-8859-1) instalado neste sistema")
        script = f"""
import locale, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from brainlib import upstream
print(locale.getencoding())
with tempfile.TemporaryDirectory() as td:
    repo = Path(td)
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@x.com", *a],
                                    check=True, capture_output=True)
    git("init", "-q")
    (repo / "ol\\u00e1.py").write_text("x = 1\\n", encoding="utf-8")
    (repo / "relat\\u00f3rio.bin").write_bytes(b"\\x00\\xffP = \\"/Users/pessoa-demo/segredo\\"\\n\\x00")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    texto = upstream._git(repo, "-c", "core.quotePath=false", "log", "-p", "-U0", "--no-color", "--format=%x01%H",
                          errors="surrogateescape").stdout       # como a varredura pede: sem aspas no acento
    achados = []
    upstream._scan_diff(repo, texto, lambda arq, n, t: achados.append(arq))
    print("ol\\u00e1.py" in texto)
    print(sum("ol\\u00e1.py" in a for a in achados))
    print(sum("relat\\u00f3rio.bin" in a and "[bin" in a for a in achados))
"""
        cls.linhas = _filho(script, loc).splitlines()
        if len(cls.linhas) < 4:
            raise AssertionError(f"o interpretador filho não respondeu no locale {loc}: {cls.linhas!r}")

    def test_accented_name_in_the_diff_text_keeps_its_name(self):
        self.assertEqual(self.linhas[1], "True", f"no locale {self.linhas[0]} o nome acentuado do diff mudou")
        self.assertNotEqual(self.linhas[2], "0", "o achado saiu com o nome trocado")

    def test_binary_file_with_an_accented_name_is_read(self):
        self.assertNotEqual(self.linhas[3], "0",
                            f"no locale {self.linhas[0]} o binário com nome acentuado não foi lido")


class NameWithAnInvalidByteNeverRaises(unittest.TestCase):
    """No Windows o nome de arquivo decodifica como UTF-8 com `surrogatepass` (PEP 529): par que recusa byte isolado
    que não é UTF-8 válido — o controle abaixo prova. `os.fsdecode`, adotado naquela decodificação, levantava
    UnicodeDecodeError lá: a varredura caía em vez de guardar o byte. O handler do Windows não se empresta a um
    processo POSIX (o CPython decide o codec de nome uma vez); o raise é posto no lugar do `os.fsdecode`."""

    @staticmethod
    def _como_no_windows(b: bytes) -> str:
        raise UnicodeDecodeError("utf-8", b, 1, 2, "invalid continuation byte")

    def test_control_utf8_with_surrogatepass_refuses_the_byte(self):
        """Controle: é o par encoding/handler do Windows — sem isto a simulação não provaria nada."""
        with self.assertRaises(UnicodeDecodeError):
            b"caf\xe9-ruim.py".decode("utf-8", "surrogatepass")

    def test_path_list_keeps_the_byte(self):
        pronto = subprocess.CompletedProcess(["git"], 0, stdout=b"caf\xe9-ruim.py\0", stderr=b"")
        with mock.patch.object(os, "fsdecode", self._como_no_windows):
            self.assertEqual(upstream._paths(pronto), ["caf\udce9-ruim.py"])      # Antes: UnicodeDecodeError
            self.assertEqual(repos._names(b"caf\xe9-ruim.py\0"), ["caf\udce9-ruim.py"])

    def test_file_list_of_the_commit_keeps_the_byte(self):
        saida = repos._END_B + b"abc123\0\nA\0caf\xe9-ruim.py\0"
        with mock.patch.object(os, "fsdecode", self._como_no_windows), \
                mock.patch.object(repos, "_git_bytes", return_value=saida):
            achado = repos._files_batch(Path("."), ["abc123"])
        self.assertEqual(achado, {"abc123": ["A " + r"caf\udce9-ruim.py"]})


class ErrorAndJsonStayPrintable(unittest.TestCase):
    def test_git_error_that_quotes_a_name_with_an_invalid_byte(self):
        """O stderr vem na mesma leitura em texto do diff (`surrogateescape`): o byte ia cru para dentro do
        `BrainError`, e imprimir a exceção derrubava quem tratava do erro."""
        falha = subprocess.CompletedProcess(["git"], 128, stdout="", stderr="fatal: caf\udce9-ruim.py não existe")
        with mock.patch.object(subprocess, "run", return_value=falha):
            with self.assertRaises(util.BrainError) as ctx:
                upstream._git(Path("."), "diff", errors="surrogateescape")
        texto = str(ctx.exception)
        texto.encode("utf-8")                               # Antes: UnicodeEncodeError (surrogates not allowed)
        self.assertIn(r"caf\udce9-ruim.py", texto)

    def test_json_output_holds_a_name_with_an_invalid_byte(self):
        """`--json` sai com `ensure_ascii=False`: guardar o byte (surrogate) abriu um caminho em que o print
        derrubava o comando num stdout UTF-8 estrito. Na saída o byte aparece como escape, como no relato."""
        nome = "caf\udce9-ruim.py"
        st = {"remote": "origin", "branch": "batch/x", "ref": None, "ahead": 1, "behind": 0, "unpushed_base": True,
              "changed": [nome], "new": [], "local_scripts": [], "committed_only": False,
              "findings": [{"file": nome, "line": 1, "rule": "caminho da máquina", "hint": "P = …"}]}
        args = argparse.Namespace(ucmd="scan", committed=False, remote=None, branch=None, fetch=False, json=True)
        saida = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
        with mock.patch.object(upstream.config, "load", return_value=object()), \
                mock.patch.object(upstream, "upstream_scan", return_value=st), \
                mock.patch.dict(os.environ, {"BRAIN_PRE_PUSH": ""}), \
                contextlib.redirect_stdout(saida):
            with self.assertRaises(SystemExit):              # achado em cima: o comando sai com 4
                upstream.cli_upstream(args, None)
            saida.flush()
        texto = saida.buffer.getvalue().decode("utf-8")     # Antes: UnicodeEncodeError no print
        lido = json.loads(texto)
        self.assertEqual((lido["changed"], lido["findings"][0]["file"]), ([r"caf\udce9-ruim.py"], r"caf\udce9-ruim.py"))


class ReposOutputStaysPrintable(unittest.TestCase):
    """`repos list` e `repos pull`: o nome do repositório vem do sistema de arquivos e pode guardar surrogate (byte
    que não é UTF-8 válido). A saída ia direto no stdout com `ensure_ascii=False`: num stdout UTF-8 estrito o
    print derrubava a lista. O nome aqui é só um `Path` — não toca o sistema de arquivos, roda onde o APFS recusa
    o nome de verdade."""

    NOME = "caf\udce9-repo"

    def _cli(self, args, correcoes) -> str:
        saida = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
        with contextlib.ExitStack() as pilha:
            for alvo, nome, valor in correcoes:
                pilha.enter_context(mock.patch.object(alvo, nome, return_value=valor))
            pilha.enter_context(contextlib.redirect_stdout(saida))
            repos.cli(args, mock.Mock())
            saida.flush()
        return saida.buffer.getvalue().decode("utf-8")     # Antes: UnicodeEncodeError no print

    def test_list_holds_a_name_with_an_invalid_byte(self):
        raiz = Path(tempfile.gettempdir()).resolve()     # o cli() resolve a raiz (`/var` → `/private/var` no macOS)
        achados = [raiz / self.NOME]
        base = [(repos, "source", {"path": str(raiz)}), (repos, "discover", achados)]
        texto = self._cli(argparse.Namespace(rcmd="list", key="k", json=True), base)
        self.assertEqual(json.loads(texto), [r"caf\udce9-repo"])
        texto = self._cli(argparse.Namespace(rcmd="list", key="k", json=False), [*base, (repos, "_remote", "")])
        self.assertIn("caf\\udce9-repo\t—", texto)       # nome com escape, separador de tabulação intacto

    def test_pull_holds_a_name_with_an_invalid_byte(self):
        r = {"key": "k", "failed": False, "fetch": False, "repos": [
            {"repo": self.NOME, "new": 0, "full": False, "snapshot": None, "warning": None, "error": None}]}
        args = argparse.Namespace(rcmd="pull", key="k", json=True, fetch=False, full=False)
        texto = self._cli(args, [(repos, "pull", r)])
        self.assertEqual(json.loads(texto)["repos"][0]["repo"], r"caf\udce9-repo")
        args.json = False
        self.assertIn(r"✓ caf\udce9-repo: sem novidades", self._cli(args, [(repos, "pull", r)]))


if __name__ == "__main__":
    unittest.main()
