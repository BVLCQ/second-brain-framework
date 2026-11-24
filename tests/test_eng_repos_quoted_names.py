"""`brain repos pull`: documento cujo nome o git entregava entre aspas entra na leitura completa.

Sem `-z` o git entrega entre aspas e com escapes o nome com acento, aspas, barra invertida ou tabulação
(`"docs/relat\\303\\263rio.md"`). A leitura completa partia a lista de arquivos por linha e lia o nome assim:
o sufixo dava `.md"`, o documento nem entrava na conta de documentos e o conteúdo nunca era lido — sem erro
nenhum. A lista de arquivos de cada commit mostrava o nome nesse formato. Agora as duas listas saem do git
entre NULs (`-z`) e são lidas como NOME (`os.fsdecode`). No snapshot o byte que não é UTF-8 válido e o
caractere de controle aparecem como escape: snapshot é arquivo UTF-8 e a linha é a estrutura do Markdown.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from brainlib import repos, watch  # noqa: E402
from test_brain import _brain  # noqa: E402
from test_repos import OLD, commit, git  # noqa: E402


@unittest.skipUnless(shutil.which("git"), "git ausente")
class QuotedNamesInRepoOverview(unittest.TestCase):
    def setUp(self):
        # o código sob teste lê a config global do git: sem isto, uma máquina com core.quotePath=false não
        # reproduziria o caso do acento, e o vermelho significaria uma coisa em cada máquina
        cfg = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        p = mock.patch.dict(os.environ, cfg)
        p.start()
        self.addCleanup(p.stop)
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.repo = Path(td.name)
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "docs").mkdir()

    def _overview(self) -> str:
        return "\n".join(repos._overview(self.repo, "HEAD"))

    def test_document_with_an_accented_name_is_read(self):
        """Antes: o nome chegava entre aspas com escape, o sufixo dava `.md"` e o documento ficava fora da conta."""
        commit(self.repo, "README.md", "# Projeto de exemplo", date=OLD)
        commit(self.repo, "docs/relatório.md", "relatório do mês", date=OLD)
        texto = self._overview()
        self.assertIn("## Documentos (2)", texto)
        self.assertIn("### docs/relatório.md", texto)
        self.assertIn("relatório do mês", texto)
        self.assertIn("- docs/relatório.md", texto)
        self.assertNotIn("\\303", texto)

    def test_document_with_a_quote_or_a_backslash_in_its_name_is_read(self):
        """A aspas e a barra invertida o git entrega entre aspas em qualquer config — não é só o acento."""
        commit(self.repo, "README.md", "# Projeto de exemplo", date=OLD)
        commit(self.repo, 'notas "d".md', "notas com aspas", date=OLD)
        commit(self.repo, "caminho\\nome.md", "nome com barra invertida", date=OLD)
        texto = self._overview()
        self.assertIn("## Documentos (3)", texto)
        self.assertIn('### notas "d".md', texto)
        self.assertIn("notas com aspas", texto)
        self.assertIn("### caminho\\nome.md", texto)
        self.assertIn("nome com barra invertida", texto)

    def test_control_character_in_a_name_does_not_break_the_line_of_the_snapshot(self):
        """Nome com tabulação: no snapshot aparece como escape, senão a linha deixa de ser a estrutura."""
        commit(self.repo, "com\ttab.md", "conteúdo com tabulação", date=OLD)
        texto = self._overview()
        self.assertIn("## Documentos (1)", texto)
        self.assertIn(r"- com\x09tab.md", texto)
        self.assertIn(r"### com\x09tab.md", texto)
        self.assertNotIn("com\ttab.md", texto)
        self.assertIn("conteúdo com tabulação", texto)

    def test_file_list_of_each_commit_shows_the_real_names(self):
        """A lista de arquivos do commit (adição e renomeação) traz o nome de verdade, sem aspas nem escape."""
        commit(self.repo, "relatório.md", "primeiro", date=OLD)
        sha1 = git(self.repo, "rev-parse", "HEAD").strip()
        commit(self.repo, 'n"d.md', "segundo", date=OLD)
        git(self.repo, "mv", "relatório.md", "renomeado-á.md")
        git(self.repo, "commit", "-q", "-m", "terceiro")
        sha2 = git(self.repo, "rev-parse", "HEAD").strip()
        achado = repos._files_batch(self.repo, [sha1, sha2])
        self.assertEqual(sorted(achado), sorted([sha1, sha2]))
        self.assertEqual(achado[sha1], ["A relatório.md"])
        self.assertEqual(achado[sha2], ["R100 relatório.md renomeado-á.md"])

    def test_document_whose_name_is_not_utf8_is_read_and_the_snapshot_stays_utf8(self):
        """Só onde o sistema de arquivos guarda nome que não é UTF-8 válido: o Linux aceita, o APFS recusa."""
        base = os.fsencode(self.repo)
        try:
            with open(base + b"/caf\xe9-ruim.md", "wb") as fh:
                fh.write("conteúdo de nome inválido\n".encode("utf-8"))
        except OSError as e:
            self.skipTest(f"este sistema de arquivos recusa nome que não é UTF-8 (errno {e.errno})")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "nome inválido")
        texto = self._overview()
        self.assertIn("## Documentos (1)", texto)
        self.assertIn("conteúdo de nome inválido", texto)
        self.assertIn(r"caf\udce9-ruim.md", texto)             # o byte aparece como escape no snapshot
        texto.encode("utf-8")                                   # e o snapshot continua sendo UTF-8 válido

    def test_shown_name_escapes_what_the_snapshot_cannot_hold(self):
        """Portátil: o nome com byte inválido não existe no APFS, mas a regra do que vai para o snapshot pode
        ser provada direto — byte guardado como surrogate vira escape, caractere de controle idem."""
        self.assertEqual(repos._show("caf\udce9.py"), r"caf\udce9.py")
        self.assertEqual(repos._show("relatório.md"), "relatório.md")
        self.assertEqual(repos._show("a\tb\n c.md"), r"a\x09b\x0a c.md")
        repos._show("caf\udce9.py").encode("utf-8")

    def test_first_pull_writes_the_document_into_the_snapshot(self):
        """Ponta a ponta, pelo caminho do dono: a primeira leitura de um repo com documento acentuado."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            brain = _brain(tmp / "inst")
            github = tmp / "Github"
            repo = github / "app"
            (repo / "docs").mkdir(parents=True)
            git(repo, "init", "-q", "-b", "main")
            commit(repo, "README.md", "# Projeto de exemplo", date=OLD)
            commit(repo, "docs/relatório.md", "relatório do mês", date=OLD)
            watch.add(brain.inst, "github-repos", {"kind": "github", "window": "auto", "path": str(github)})
            r = repos.pull(brain, "github-repos")
            self.assertFalse(r["failed"])
            self.assertTrue(r["repos"][0]["full"])
            arquivos = sorted(brain.inst.inbox.glob("github-*.md"))
            self.assertEqual(len(arquivos), 1)
            texto = arquivos[0].read_text(encoding="utf-8")
            self.assertIn("## Documentos (2)", texto)
            self.assertIn("### docs/relatório.md", texto)
            self.assertIn("relatório do mês", texto)
            self.assertNotIn("\\303", texto)
