"""`upstream scan` num branch ainda sem referência no remoto varre o que um push enviaria.

Sem `origin/<branch>` a varredura caía no histórico inteiro, que já é público — e um caminho de template da
v1.0 virava achado, com exit 4, em todo branch novo antes do primeiro push. Agora vale a mesma conta do hook:
commits só locais, e árvore de trabalho contra o último commit que o remoto já tem — num branch que mergeou
outra ref do remoto, o que está byte-idêntico ao remoto já é público e fica fora.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, upstream, util


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def _repo(tmp: Path) -> Path:
    """Clone de prova com um commit já no remoto e um commit novo (o que um push enviaria)."""
    remote, repo = tmp / "remote.git", tmp / "fw"
    _git(tmp, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(tmp, "clone", "-q", str(remote), str(repo))
    _git(repo, "config", "user.name", "Marina Demo")
    _git(repo, "config", "user.email", "marina-demo@x.com")
    (repo / "brainlib").mkdir()
    (repo / "brainlib" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (repo / ".gitignore").write_text("/vault/\nconfig/brain.toml\nconfig/.env\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "push", "-q", "origin", "HEAD:main")
    return repo


def _names(findings: list[dict]) -> list[str]:
    return sorted(f["file"].split(" (commit")[0] for f in findings)


@unittest.skipUnless(shutil.which("git"), "git ausente")
class ScanOnUnpushedBranch(unittest.TestCase):
    """Branch ainda sem `origin/<branch>`: a varredura cobre o que um push enviaria (commits só locais +
    árvore de trabalho), não o histórico inteiro — que já é público e carrega placeholder de commit antigo."""

    def test_history_already_public_is_not_rescanned(self):
        """Antes: sem referência remota a varredura caía em `HEAD` inteiro e um caminho de template da v1.0
        virava achado (exit 4) em todo branch novo, antes do primeiro push."""
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            # caminho de template, montado por partes: o próprio teste não pode parecer vazamento na varredura
            old = "<string>//" + "Users/" + "EXEMPLO/brain/scripts/x.sh</string>\n"
            (repo / "old.plist").write_text(old, encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "modelo antigo")
            _git(repo, "push", "-q", "origin", "HEAD:main")                # já é público
            _git(repo, "checkout", "-q", "-b", "batch/x")                  # sem origin/batch/x
            (repo / "c.py").write_text("X = 1\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "só local")

            whole = upstream.scan(config.load(repo), None, committed=True, revsets=[["HEAD"]])
            self.assertIn("old.plist", _names(whole))                      # o scan acusa esse padrão: a faixa é o que importa
            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual(st["findings"], [])                             # o histórico público não volta ao scan
            self.assertEqual((st["ref"], st["unpushed_base"], st["ahead"], st["behind"]), (None, True, 1, 0))

            (repo / "d.py").write_text(f'P = "{Path.home()}/segredo"\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "vazamento só local")
            st = upstream.upstream_scan(config.load(repo), committed=True)
            self.assertEqual((st["ahead"], _names(st["findings"])), (2, ["d.py"]))     # o que é novo continua acusado

            (repo / "e.py").write_text(f'P = "{Path.home()}/x"\n', encoding="utf-8")  # não rastreado
            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual((_names(st["findings"]), st["behind"]), (["d.py", "e.py"], 0))

    @unittest.skipIf(os.name == "nt", "o Windows não aceita `:` em nome de arquivo")
    def test_tracked_file_whose_name_starts_with_a_colon_is_not_dropped(self):
        """Nome que começa com `:` é mágica de pathspec para o git: passado cru, o `git diff` das listas de caminho
        vinha vazio (rc 0) — `_public_paths` dava o arquivo como idêntico ao remoto e ele saía do scan, com o
        vazamento dentro. O diff das listas pede pathspec literal."""
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            (repo / ":x.py").write_text("X = 1\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "dois pontos")
            _git(repo, "push", "-q", "origin", "HEAD:main")            # já é público, limpo
            _git(repo, "checkout", "-q", "-b", "batch/x")              # sem origin/batch/x
            (repo / ":x.py").write_text(f'P = "{Path.home()}/segredo"\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "vazamento só local")

            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual(st["changed"], [":x.py"])                  # alteração pendente: difere do remoto
            self.assertEqual(_names(st["findings"]), [":x.py"])
            self.assertEqual(_names(upstream.upstream_scan(config.load(repo), committed=True)["findings"]), [":x.py"])

    def test_tracked_file_with_brackets_in_its_name_is_not_dropped(self):
        """Nome com colchetes: `[1]` é classe de caractere num glob. Medido no git 2.54: passado como pathspec comum,
        `segredo[1].py` casa consigo mesmo (o git compara o pathspec literalmente antes de tentar o glob) e casa
        também `segredo1.py`; com `--literal-pathspecs` fica exato. O arquivo não sai do scan nos dois casos. Este
        teste guarda o formato contra uma troca para pathspec `:(glob)` ou para filtro por `fnmatch`."""
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            (repo / "segredo[1].py").write_text("X = 1\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "colchetes")
            _git(repo, "push", "-q", "origin", "HEAD:main")            # já é público, limpo
            _git(repo, "checkout", "-q", "-b", "batch/x")              # sem origin/batch/x
            (repo / "segredo[1].py").write_text(f'P = "{Path.home()}/segredo"\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "vazamento só local")

            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual(st["changed"], ["segredo[1].py"])         # alteração pendente: difere do remoto
            self.assertEqual(_names(st["findings"]), ["segredo[1].py"])

    @unittest.skipIf(os.name == "nt", "o NTFS recusa caractere de controle no nome")
    def test_tracked_file_with_a_tab_in_its_name_is_scanned(self):
        """O terceiro caso que `core.quotePath=false` não alcança: o git sempre põe aspas no nome com tabulação."""
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            (repo / "com\ttab.py").write_text("X = 1\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "tabulação")
            _git(repo, "push", "-q", "origin", "HEAD:main")           # já é público, limpo
            _git(repo, "checkout", "-q", "-b", "batch/x")              # sem origin/batch/x
            (repo / "com\ttab.py").write_text(f'P = "{Path.home()}/segredo"\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "vazamento só local")

            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual(st["changed"], ["com\ttab.py"])
            self.assertEqual(_names(st["findings"]), ["com\ttab.py"])

    def test_branch_that_merged_a_public_branch_rescans_nothing_public(self):
        """Antes: a base do diff era o pai do commit só-local mais antigo. Num branch que mergeou outra ref do
        remoto (ex.: um `origin/main` que andou), `base..HEAD` e `diff base` traziam de volta arquivo e mensagem
        de commit que já são públicos — o hook não acusava, a varredura manual acusava."""
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            _git(repo, "checkout", "-q", "-b", "side")
            (repo / "side.py").write_text(f'P = "{Path.home()}/segredo"\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", f"ajusta {Path.home()}/x.py")
            _git(repo, "push", "-q", "origin", "side")                        # já é público
            _git(repo, "checkout", "-q", "main")
            (repo / "m.py").write_text("M = 1\n", encoding="utf-8")          # main anda: o merge não é fast-forward
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "m1")
            _git(repo, "push", "-q", "origin", "main")
            _git(repo, "checkout", "-q", "-b", "batch/x")                     # sem origin/batch/x
            _git(repo, "merge", "-q", "--no-edit", "origin/side")
            (repo / "local.py").write_text(f'P = "{Path.home()}/segredo"\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "l1 só local")

            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual((st["ahead"], st["behind"], _names(st["findings"])), (2, 0, ["local.py"]))
            self.assertEqual(st["changed"], ["local.py"])                      # side.py não é alteração pendente
            self.assertEqual(_names(upstream.upstream_scan(config.load(repo), committed=True)["findings"]), ["local.py"])

            (repo / "side.py").write_text(f'Q = "{Path.home()}/outro"\n', encoding="utf-8")  # edição local
            st = upstream.upstream_scan(config.load(repo))                    # do arquivo público: volta ao scan
            self.assertEqual((sorted(st["changed"]), _names(st["findings"])), (["local.py", "side.py"], ["local.py", "side.py"]))

@unittest.skipUnless(shutil.which("git"), "git ausente")
class GitQuotedPathNames(unittest.TestCase):
    """O git entrega entre aspas, com escapes, o nome de arquivo que tem acento, aspas ou barra invertida
    (`"ol\\303\\241.py"`); `core.quotePath=false` só resolve o caso do acento. Usado como caminho, o nome entre
    aspas não corresponde a arquivo nenhum: ele saía das listas de caminho da varredura (e um vazamento dentro
    ficava fora do scan, sem erro nenhum), não abria como arquivo novo e não correspondia ao prefixo de arquivo do
    dono. Toda lista de caminho pede `-z`, que separa por NUL e nunca põe aspas.

    O `-z` não basta: o nome listado ainda era lido como TEXTO, com o encoding do terminal. No Linux o nome de
    arquivo é qualquer byte fora NUL e `/` — pode não ser UTF-8 válido — e o byte inválido virava U+FFFD, outro
    nome, que não casa com nada. A lista sai em bytes e vira nome com `_decode` (surrogateescape)."""

    def _leak(self) -> str:
        return f'P = "{Path.home()}/segredo"\n'

    def _branch(self, tmp: Path) -> Path:
        repo = _repo(tmp)
        _git(repo, "checkout", "-q", "-b", "batch/x")              # sem origin/batch/x: a lista de pendentes decide
        return repo

    def test_tracked_file_with_an_accented_name_is_scanned(self):
        """Antes: `changed=[] findings=[]` — o nome entre aspas não casava com nada e o arquivo era dado como já público."""
        with tempfile.TemporaryDirectory() as td:
            repo = self._branch(Path(td))
            (repo / "olá.py").write_text(self._leak(), encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "vazamento só local")
            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual((st["changed"], _names(st["findings"])), (["olá.py"], ["olá.py"]))

    @unittest.skipIf(os.name == "nt", "o Windows não aceita aspas nem barra invertida em nome de arquivo")
    def test_tracked_file_with_a_quote_or_a_backslash_in_its_name_is_scanned(self):
        """Os dois casos que `core.quotePath=false` não alcança: o git sempre põe aspas neles."""
        with tempfile.TemporaryDirectory() as td:
            repo = self._branch(Path(td))
            names = sorted(['we"ird.py', "back\\slash.py"])
            for name in names:
                (repo / name).write_text(self._leak(), encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "vazamento só local")
            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual((sorted(st["changed"]), sorted(_names(st["findings"]))), (names, names))

    @unittest.skipIf(os.name == "nt", "o Windows não aceita aspas em nome de arquivo")
    def test_untracked_file_with_a_quote_in_its_name_is_scanned(self):
        """Arquivo novo é lido pelo nome: entre aspas, o caminho não existia e o arquivo era pulado em silêncio."""
        with tempfile.TemporaryDirectory() as td:
            repo = self._branch(Path(td))
            (repo / 'we"ird.py').write_text(self._leak(), encoding="utf-8")      # não rastreado
            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual((st["new"], _names(st["findings"])), (['we"ird.py'], ['we"ird.py']))

    def test_tracked_owner_file_with_an_accented_name_is_flagged(self):
        """A guarda de arquivo do dono rastreado compara o nome com prefixos (`vault/`, `config/`): entre aspas, nunca casa."""
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            _git(repo, "checkout", "-q", "-b", "batch/x")
            (repo / "vault").mkdir()
            (repo / "vault" / "reunião.md").write_text("x\n", encoding="utf-8")
            _git(repo, "add", "-f", "-A")                              # o .gitignore ignora /vault/: força
            _git(repo, "commit", "-q", "-m", "arquivo do dono")
            st = upstream.pre_push_scan(config.load(repo), "origin", "")
            self.assertEqual([f["file"] for f in st["findings"] if f["rule"] == "arquivo do dono rastreado pelo git"],
                             ["vault/reunião.md"])
            with self.assertRaisesRegex(util.BrainError, "vault/reunião.md"):
                upstream._prepare(config.load(repo), None, "batch/x", fetch=False)

    def _imprime(self, st: dict) -> str:
        """O relato da varredura num stdout UTF-8 estrito, como um terminal de verdade."""
        saida = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
        with contextlib.redirect_stdout(saida):
            upstream._print_scan(st)
            saida.flush()
        return saida.buffer.getvalue().decode("utf-8")

    @unittest.skipIf(os.name == "nt", "o git de prova é script de shell, e o argv do Windows não carrega byte cru")
    def test_name_with_a_byte_that_is_not_utf8_is_not_taken_for_already_public(self):
        """Sem criar arquivo (o APFS recusa esse nome): um `git` de prova lista um nome com um byte que não é UTF-8
        válido e só reconhece o mesmo nome como pathspec se ele chegar byte a byte igual. Antes: o byte virava
        U+FFFD na leitura, o pathspec não casava com nada e o arquivo saía dos pendentes como `já público`."""
        esperado = b"caf\xe9-ruim.py"                       # 0xE9 é "é" em latin-1: não é UTF-8 válido
        roteiro = b"".join([
            b"#!/bin/sh\n",
            b"# git de prova: a listagem entrega um nome com um byte que nao e UTF-8; o mesmo nome so conta como\n",
            b"# pathspec (depois de --) se chegar byte a byte igual.\n",
            b"esp='" + esperado + b"'\n",
            b'for a in "$@"; do case "$a" in diff) eh_diff=1;; for-each-ref) echo 1111111111111111111111111111111111111111; exit 0;; esac; done\n',
            b'if [ "$eh_diff" = 1 ]; then\n',
            b"  depois=0; achou=0\n",
            b'  for a in "$@"; do\n',
            b'    case "$a" in --) depois=1;; esac\n',
            b'    if [ "$depois" = 1 ] && [ "$a" = "$esp" ]; then achou=1; fi\n',
            b"  done\n",
            b'  if [ "$achou" = 1 ] || [ "$depois" = 0 ]; then printf \'%s\\000\' "$esp"; fi\n',
            b"fi\n",
            b"exit 0\n",
        ])
        with tempfile.TemporaryDirectory() as td:
            raiz, provas = Path(td) / "repo", Path(td) / "bin"
            raiz.mkdir()
            provas.mkdir()
            (provas / "git").write_bytes(roteiro)
            (provas / "git").chmod(0o755)
            caminho = os.environ.get("PATH")
            os.environ["PATH"] = f"{provas}{os.pathsep}{caminho or os.defpath}"    # o git achado é o de prova
            try:
                rastreados = upstream._pending_files(raiz, "HEAD~1")[0]
                publicos = upstream._public_paths(raiz, "origin", rastreados)
                estranho = upstream._public_paths(raiz, "origin", ["outro.py"])      # o de prova discrimina: nome
            finally:                                                                 # que ele não lista é dado como público
                if caminho is None:
                    os.environ.pop("PATH", None)
                else:
                    os.environ["PATH"] = caminho
            self.assertEqual(estranho, ["outro.py"])
            self.assertEqual(publicos, [], "o arquivo foi dado como já público")
            self.assertEqual([os.fsencode(f) for f in rastreados], [esperado])

    def test_printing_a_name_with_an_invalid_byte_does_not_crash(self):
        """O nome pode guardar um byte que não é UTF-8 (surrogate): stdout em UTF-8 recusa surrogate, e o print
        derrubava a varredura no meio do relato. Na tela o byte aparece como escape; o nome em si segue intacto."""
        nome = "caf\udce9-ruim.py"                          # o byte 0xE9 guardado como surrogate; com `os.fsdecode`
        st = {"remote": "origin", "branch": "batch/x", "ref": None, "ahead": 1, "behind": 0, "unpushed_base": True,  # esse byte levanta no Windows
              "changed": [nome], "new": [], "local_scripts": [], "committed_only": False,
              "findings": [{"file": nome, "line": 1, "rule": "caminho da máquina", "hint": "P = …"}]}
        texto = self._imprime(st)                     # Antes: UnicodeEncodeError (surrogates not allowed)
        self.assertEqual(texto.count("caf\\udce9-ruim.py"), 2)
        self.assertNotIn("\ufffd", nome)

    def test_files_whose_name_is_not_utf8_are_scanned(self):
        """De ponta a ponta, com git de verdade. Depende de um sistema de arquivos que aceite o nome: o Linux aceita
        qualquer byte fora NUL e `/`; o APFS recusa. Antes: `changed=[] findings=[]` — o nome com U+FFFD não casava
        com nada, o rastreado era dado como já público e o novo não abria."""
        with tempfile.TemporaryDirectory() as td:
            repo = self._branch(Path(td))
            try:
                with open(os.fsencode(repo) + b"/caf\xe9-ruim.py", "wb") as fh:   # OSError no APFS: pula o teste
                    fh.write(self._leak().encode("utf-8"))
            except (OSError, UnicodeDecodeError) as e:      # no Windows o próprio nome em bytes já não decodifica
                self.skipTest(f"este sistema de arquivos recusa nome que não é UTF-8 ({getattr(e, 'errno', type(e).__name__)})")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "vazamento só local")
            with open(os.fsencode(repo) + b"/novo\xe9.py", "wb") as fh:            # não rastreado
                fh.write(self._leak().encode("utf-8"))
            rastreado, novo = "caf\udce9-ruim.py", "novo\udce9.py"      # o byte 0xE9 guardado como surrogate
            st = upstream.upstream_scan(config.load(repo))
            self.assertEqual((st["changed"], st["new"]), ([rastreado], [novo]))
            self.assertCountEqual(_names(st["findings"]), [rastreado, novo])
            self.assertIn("caf\\udce9-ruim.py", self._imprime(st))                  # na tela: escape, sem derrubar



if __name__ == "__main__":
    unittest.main()
