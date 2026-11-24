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
  tinha `repos list` e `repos pull`, com o nome da pasta do repositório vindo do sistema de arquivos;
- lido em bytes, o nome voltava ao git e ao disco como `str`: num locale de byte único o Python o codificava em
  latin-1, o nome chegava trocado e o binário acentuado ficava sem ler; no caminho do `upstream scan` sem
  `--committed`, o pathspec não casava e o arquivo pendente saía como `já público` (rodada 6).
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

from brainlib import config, repos, upstream, util  # noqa: E402


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

    def test_the_probe_for_an_invalid_byte_name_never_takes_the_module_down(self):
        """No Windows o `open` de um caminho em bytes decodifica como UTF-8 com `surrogatepass` (o controle acima):
        o byte isolado levanta `UnicodeDecodeError`, que não é `OSError`. A sondagem roda na importação — se
        levantar, o módulo inteiro some da suíte em vez de pular só os testes que dependem do arquivo."""
        ruim = UnicodeDecodeError("utf-8", b"caf" + bytes([0xE9]) + b".py", 3, 4, "invalid continuation byte")
        with mock.patch("builtins.open", side_effect=ruim):
            self.assertFalse(_aceita_byte_invalido())


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


# --- Revisão independente, rodada 6: o nome volta para o git e para o disco em bytes -----------------------
SEG_AWS = b"AKIA" + b"ABCDEFGHIJKLMNOP"  # sintética: 16 letras depois de AKIA — não é chave de ninguém
BIN_UTF, NOTA_UTF = b"relat\xc3\xb3rio.bin", b"jo\xc3\xa3o-notas.md"     # nome em bytes UTF-8, como o git guarda
SEM_BYTE_INVALIDO = "este sistema de arquivos não guarda nome com byte que não é UTF-8 válido"


def _aceita_byte_invalido() -> bool:
    """O sistema de arquivos guarda nome com byte que não é UTF-8 válido? O Linux guarda; o APFS (macOS) recusa com
    EILSEQ — lá os testes que precisam desse arquivo em disco pulam e ficam para o contêiner Linux.
    No Windows o `open` de um caminho em bytes com esse nome levanta `UnicodeDecodeError` (PEP 529):
    a sondagem responde não, e os testes que dependem do arquivo pulam."""
    with tempfile.TemporaryDirectory() as td:
        try:
            open(os.fsencode(td) + b"/caf\xe9.py", "wb").close()
        except (OSError, ValueError):       # no Windows é UnicodeDecodeError (PEP 529), que não é OSError
            return False
    return True


ACEITA_BYTE_INVALIDO = _aceita_byte_invalido()


@contextlib.contextmanager
def _fronteira_latin1():
    """Emula, no processo de prova, as BORDAS de um Python de locale ISO-8859-1 (a prova real é `dock-locale.zsh`,
    em contêiner): caminho e argumento de linha de comando em str viram bytes em latin-1, não em UTF-8; bytes passa
    inteiro. Só a borda — a decodificação da saída do git é a do código sob teste."""
    def b(x):
        if isinstance(x, os.PathLike):
            x = os.fspath(x)
        if isinstance(x, bytes):
            return x                   # bytes passa inteiro: é o que a máquina de byte único faz
        try:
            return x.encode("latin-1", "surrogateescape")
        except UnicodeEncodeError:      # caractere fora do latin-1: numa máquina dessas ele não estaria num caminho
            return x.encode("utf-8") if isinstance(x, str) else x
    run, isfile, stat, abrir, read_bytes = subprocess.run, os.path.isfile, os.stat, open, Path.read_bytes
    with contextlib.ExitStack() as pilha:
        pilha.enter_context(mock.patch.object(subprocess, "run", 
            lambda cmd, *a, **kw: run([b(c) for c in cmd], *a, **kw)))
        pilha.enter_context(mock.patch.object(os.path, "isfile", lambda p, *a, **kw: isfile(b(p), *a, **kw)))
        pilha.enter_context(mock.patch.object(os, "stat", lambda p, *a, **kw: stat(b(p), *a, **kw)))
        pilha.enter_context(mock.patch("builtins.open", lambda p, *a, **kw: abrir(b(p), *a, **kw)))
        pilha.enter_context(mock.patch.object(Path, "read_bytes", lambda self: abrir(b(self), "rb").read()))
        yield


@contextlib.contextmanager
def _linha_de_comando_somente_ascii():
    """Emula uma plataforma em que a linha de comando não carrega o nome como ele é: o que não é ASCII chega ao git
    com U+FFFD no lugar. É para o nome com byte inválido, que o Windows não carrega — e que nenhum destes testes
    exercita de verdade. Argumento em str vira bytes, que é o que o POSIX faz de qualquer jeito."""
    run = subprocess.run

    def perde(x):
        s = x.encode("utf-8", "surrogateescape") if isinstance(x, str) else x
        return s.decode("ascii", "replace").encode("utf-8")

    with mock.patch.object(subprocess, "run", lambda cmd, *a, **kw: run([perde(c) for c in cmd], *a, **kw)):
        yield


class NameGoesBackToGitAsBytes(unittest.TestCase):
    """Revisão independente (rodada 6): achado 2 e endurecimento do achado 1. O nome saía do git em UTF-8 e VOLTAVA
    para o git e para o disco como str — e o Python codifica str de caminho e de argumento no encoding do locale.
    Numa máquina de locale de byte único (ISO-8859-1; a prova real é `dock-locale.zsh`, em contêiner) `relatório`
    chegava como `relat\xf3rio`: o binário com nome acentuado não era lido e o segredo de dentro passava sem
    acusação. O commit que pôs UTF-8 na leitura trouxe isso — antes os dois lados usavam o locale e o nome fechava,
    só com outro rótulo. Agora o nome volta em bytes, pelo mesmo par da leitura (`_arg`, `_fs_path`); no Windows, onde
    a linha de comando é UTF-16, segue str."""

    REL_MD = BIN_UTF[:-4] + b".md"                   # `relatório.md`, texto
    CAF_PY = b'caf\xe9.py'         # nome com byte que não é UTF-8 válido
    ANL_BIN = b'an\xe1lise".bin'    # aspas + byte inválido: o git imprime o nome entre aspas

    @staticmethod
    def _git(repo: Path, *a: str) -> None:
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@x.com", *a],
                       check=True, capture_output=True)

    @staticmethod
    def _por_bytes(repo: Path, nome: bytes, dados: bytes) -> None:
        with open(os.fsencode(str(repo)) + b"/" + nome, "wb") as fh:
            fh.write(dados)

    def _cenario(self, repo: Path) -> None:
        """Base já no remoto; binário rastreado `relatório.bin` alterado na árvore de trabalho, com o segredo."""
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "remote", "add", "origin", "/tmp/origin-que-nao-existe")
        (repo / "base.md").write_text("base\n", encoding="utf-8")
        self._por_bytes(repo, BIN_UTF, b"\x00\xfeversao limpa\x00")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "base")
        self._git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self._por_bytes(repo, BIN_UTF, b"\x00\xffk = '" + SEG_AWS + b"'\n\x00")

    def _achados(self, st: dict) -> list[str]:
        return sorted(f["file"] for f in st["findings"] if f["rule"] == "chave AWS")

    def test_the_public_question_never_carries_a_name_on_the_command_line(self):
        """A pergunta do `_public_paths` vai SEM pathspec. Com o nome na linha de comando, ele era re-codificado no
        encoding do locale — ou perdia o byte, no Windows —, não casava com nada, e o arquivo saía como já público."""
        comandos: list[list[str]] = []

        def git_de_prova(_root, *args, **_kw):
            comandos.append(list(args))
            if args[0] == "for-each-ref":
                return subprocess.CompletedProcess(args, 0, "t" * 40 + chr(10), "")
            nomes = bytes([0]).join([b"a.py", b"pasta/b.md"]) + bytes([0])
            return subprocess.CompletedProcess(args, 0, nomes, b"")

        with mock.patch.object(upstream, "_git", side_effect=git_de_prova):
            publicos = upstream._public_paths(Path("."), "origin", ["a.py", "pasta/b.md", "c.txt"])
        self.assertEqual(publicos, ["c.txt"])
        perguntas = [c for c in comandos if "diff" in c]
        self.assertEqual(len(perguntas), 1, comandos)
        self.assertNotIn("--", perguntas[0])                      # sem pathspec: o nome nunca entra na linha
        for nome in ("a.py", "pasta/b.md", "c.txt"):
            self.assertNotIn(nome, perguntas[0])

    def test_the_scan_gives_up_the_pathspec_restriction_when_a_name_may_not_reach_git(self):
        """Achado 1 (Windows — aqui não dá para exercitar): com nome de byte inválido entre os pendentes, o pathspec do
        `keep` pode não casar com nada — a linha de comando de lá é UTF-16 — e o diff vazio deixaria o arquivo fora da
        varredura. Abre mão da restrição; sem nome assim, a restrição fica. Decide-se olhando o nome, não o sistema."""
        vistas: list = []

        def scan_de_prova(_inst, _base, **kw):
            vistas.append(kw.get("keep"))

        casos = [([upstream._decode(self.CAF_PY), "b.md"], None), (["a.py", "b.md"], ["a.py", "b.md"])]
        for nomes, _esperado in casos:
            trocas = {"_ref_offline": {"return_value": (None, None, None)},
                      "_unpushed_range": {"return_value": (1, "ponta", [])},
                      "_pending_files": {"return_value": (list(nomes), [])},
                      "_public_paths": {"return_value": []},
                      "_local_scripts": {"return_value": []},
                      "scan": {"side_effect": scan_de_prova}}
            with contextlib.ExitStack() as pilha:
                for nome, kw in trocas.items():
                    pilha.enter_context(mock.patch.object(upstream, nome, **kw))
                upstream.upstream_scan(Path("."), fetch=False)
        self.assertEqual(vistas, [esperado for _nomes, esperado in casos])
    def test_tracked_binary_with_an_accented_name_is_read_at_a_single_byte_locale(self):
        """Árvore de trabalho × remoto: o nome do cabeçalho virava caminho de disco em str."""
        with tempfile.TemporaryDirectory() as td, _fronteira_latin1():
            repo = Path(td)
            self._cenario(repo)
            self.assertEqual(self._achados(upstream.upstream_scan(config.load(repo))), ["relatório.bin [binário]"])

    def test_committed_binary_with_an_accented_name_is_read_at_a_single_byte_locale(self):
        """Binário já commitado (`git log -p` + `cat-file`): o nome viaja pela linha de comando."""
        with tempfile.TemporaryDirectory() as td, _fronteira_latin1():
            repo = Path(td)
            self._cenario(repo)
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-q", "-m", "com segredo")
            sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                                 text=True).stdout.strip()[:9]      # no modo committed o rótulo traz o commit
            self.assertEqual(self._achados(upstream.upstream_scan(config.load(repo), committed=True)),
                             [f"relatório.bin (commit {sha}) [binário]"])

    def test_untracked_file_with_an_accented_name_is_read_at_a_single_byte_locale(self):
        """Arquivo novo: lido pelo nome da listagem. Na ponta anterior este caso passava no locale real por acaso
        (nome lido no encoding do locale e re-codificado nele); com o nome lido em UTF-8 ele só passa pelo caminho
        em bytes — este teste fixa o caminho. Na emulação, a ponta anterior o perde."""
        with tempfile.TemporaryDirectory() as td, _fronteira_latin1():
            repo = Path(td)
            self._cenario(repo)
            self._por_bytes(repo, NOTA_UTF, b"k = '" + SEG_AWS + b"'\n")
            self.assertEqual(self._achados(upstream.upstream_scan(config.load(repo))),
                             ["joão-notas.md", "relatório.bin [binário]"])
    def _unpushed(self, repo: Path, remoto: Path, nome: bytes) -> None:
        """Clone de prova com a base já no remoto e um arquivo alterado num branch sem referência no remoto."""
        self._git(remoto.parent, "init", "-q", "--bare", "-b", "main", str(remoto))
        subprocess.run(["git", "clone", "-q", str(remoto), str(repo)], check=True, capture_output=True)
        (repo / "brainlib").mkdir()
        (repo / "brainlib" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
        (repo / ".gitignore").write_text('/vault/\nconfig/brain.toml\nconfig/.env\n',
                                         encoding="utf-8")
        self._por_bytes(repo, nome, b'limpo\n')
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "base")
        self._git(repo, "push", "-q", "origin", "HEAD:main")
        self._git(repo, "checkout", "-q", "-b", "batch/x")
        self._por_bytes(repo, nome, b"k = '" + SEG_AWS + b"'\n")

    def test_unpushed_file_with_an_accented_name_is_not_taken_for_public_at_a_single_byte_locale(self):
        """Branch sem referência no remoto. `_public_paths` perguntava ao git, por pathspec, quais candidatos diferem
        da ponta do remoto e lia "não diferencia" como "já é público": com o pathspec em str, num locale de byte
        único, ele não casava com nada e o arquivo saía da varredura, em silêncio. Agora a pergunta vai sem pathspec —
        o nome nunca entra na linha de comando."""
        with tempfile.TemporaryDirectory() as td, _fronteira_latin1():
            repo, remoto = Path(td) / "fw", Path(td) / "remote.git"
            self._unpushed(repo, remoto, self.REL_MD)
            self.assertEqual(self._achados(upstream.upstream_scan(config.load(repo))), ["relatório.md"])

    @unittest.skipUnless(ACEITA_BYTE_INVALIDO, SEM_BYTE_INVALIDO)
    def test_unpushed_file_whose_name_cannot_reach_git_is_scanned_unrestricted(self):
        """Achado 1, endurecido: nome com byte inválido numa plataforma em que a linha de comando não o carrega. Sem
        pathspec no `_public_paths`, o arquivo deixa de ser tomado por público; e como o git não reconhece o caminho
        do `keep`, a varredura abre mão da restrição — pode acusar arquivo que já é público, nunca deixar um de fora."""
        with tempfile.TemporaryDirectory() as td, _linha_de_comando_somente_ascii():
            repo, remoto = Path(td) / "fw", Path(td) / "remote.git"
            self._unpushed(repo, remoto, self.CAF_PY)
            self.assertEqual(self._achados(upstream.upstream_scan(config.load(repo))),
                             [self.CAF_PY.decode("utf-8", "surrogateescape")])
    @unittest.skipUnless(ACEITA_BYTE_INVALIDO, SEM_BYTE_INVALIDO)
    def test_committed_binary_whose_quoted_name_carries_an_invalid_byte_is_read(self):
        """Nome com aspas E byte inválido: com `core.quotePath=false` o git imprime o nome entre aspas com o byte
        CRU lá dentro e a aspa escapada (medido no contêiner Linux, git 2.54). O texto do diff passou a guardar o
        byte como surrogate, e o `_unquote` codificava o caractere comum em UTF-8 estrito: `UnicodeEncodeError`
        derrubava a varredura inteira. Na main, que lê o texto com `replace`, o byte virava U+FFFD, que não é nome
        de arquivo nenhum — o `cat-file` não achava o blob e o binário saía sem acusação."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "remote", "add", "origin", "/tmp/origin-que-nao-existe")
            self._por_bytes(repo, self.ANL_BIN, b"\x00\xffk = '" + SEG_AWS + b"'\x00")
            self._git(repo, "add", "-A")
            self._git(repo, "commit", "-q", "-m", "com segredo")
            sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                                 text=True).stdout.strip()[:9]      # no modo committed o rótulo traz o commit
            self.assertEqual(self._achados(upstream.upstream_scan(config.load(repo), committed=True)),
                             [self.ANL_BIN.decode("utf-8", "surrogateescape") + f" (commit {sha}) [binário]"])
    def test_the_quoted_name_keeps_its_byte_whatever_git_prints(self):
        """Função pura — roda também onde o sistema de arquivos recusa o arquivo (APFS). Medido no contêiner Linux
        (git 2.54): com `core.quotePath=false`, como a varredura pede, o git imprime o nome entre aspas com o byte
        CRU e a aspa escapada; no padrão dele, o byte vem em octal. O `_unquote` codificava o caractere comum em
        UTF-8 estrito, e a primeira forma derrubava a varredura (`UnicodeEncodeError`)."""
        esperado = self.ANL_BIN.decode("utf-8", "surrogateescape")
        escapada = self.ANL_BIN.replace(bytes([34]), bytes([92, 34]))       # a aspa do nome sai com barra antes
        formas = (b'"b/' + escapada + b'"',                                 # byte cru: quotePath=false
                  b'"b/' + escapada.replace(bytes([0xE1]), bytes([92]) + b"341") + b'"')    # octal: padrão do git
        for forma in formas:
            with self.subTest(forma=forma):
                texto = forma.decode("utf-8", "surrogateescape")            # como o texto do diff chega à função
                self.assertEqual(upstream._unquote(texto), "b/" + esperado)  # _unquote só tira as aspas; o prefixo do lado é do _strip_side
                self.assertEqual(upstream._strip_side(texto, "b"), esperado)

if __name__ == "__main__":
    unittest.main()
