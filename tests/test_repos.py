"""`brain repos` — fonte kind=github: commits novos dos clones locais (stdlib + git local, sem rede)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import rawsort, repos, watch  # noqa: E402
from test_brain import _brain  # noqa: E402

RECENT = "2026-10-08T12:00:00-03:00"
OLD = "2024-03-01T12:00:00-03:00"        # antigo: a primeira leitura pega igual


def git(repo: Path, *args: str, date: str = RECENT) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Marina-demo", "GIT_AUTHOR_EMAIL": "marina-demo@example.com",
           "GIT_COMMITTER_NAME": "Marina-demo", "GIT_COMMITTER_EMAIL": "marina-demo@example.com",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def commit(repo: Path, name: str, msg: str, date: str = RECENT) -> None:
    (repo / name).write_text(msg + "\n", encoding="utf-8")
    git(repo, "add", name, date=date)
    git(repo, "commit", "-q", "-m", msg, date=date)


@unittest.skipUnless(shutil.which("git"), "git ausente")
class ReposTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.brain = _brain(self.tmp / "inst")
        self.github = self.tmp / "Github"
        self.repo = self.github / "app"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, "README.md", "# Projeto de exemplo", date=OLD)
        commit(self.repo, "a.txt", "commit antigo", date=OLD)
        commit(self.repo, "b.txt", "commit recente")
        watch.add(self.brain.inst, "github-repos", {"kind": "github", "window": "auto", "path": str(self.github)})

    def inbox(self) -> list[Path]:
        return sorted(self.brain.inst.inbox.glob("github-*.md"))

    def test_first_pull_reads_the_whole_repo_then_silence(self):
        r = repos.pull(self.brain, "github-repos")
        self.assertFalse(r["failed"])
        self.assertEqual([(x["repo"], x["new"], x["full"]) for x in r["repos"]], [("app", 3, True)])
        [snap] = self.inbox()
        self.assertRegex(snap.name, r"^github-app-\d{4}-\d{2}-\d{2}T\d{6}\.md$")
        text = snap.read_text(encoding="utf-8")
        self.assertIn("commit antigo", text)                                 # fora de qualquer janela: entra igual
        self.assertIn("commit recente", text)
        self.assertIn("A b.txt", text)
        self.assertIn("- README.md", text)                                   # árvore
        self.assertIn("### README.md\n\n````\n# Projeto de exemplo\n````", text)  # conteúdo do documento
        self.assertEqual(rawsort.classify(snap.name), "github")
        r = repos.pull(self.brain, "github-repos")
        self.assertEqual(r["repos"][0]["new"], 0)
        self.assertEqual(len(self.inbox()), 1)
        r = repos.pull(self.brain, "github-repos", full=True)                # --full relê tudo
        self.assertTrue(r["repos"][0]["full"])
        self.assertEqual(r["repos"][0]["new"], 3)

    def test_new_commits_are_exact_not_by_date(self):
        repos.pull(self.brain, "github-repos")
        commit(self.repo, "c.txt", "terceiro, com data velha", date=OLD)
        r = repos.pull(self.brain, "github-repos")
        self.assertEqual((r["repos"][0]["new"], r["repos"][0]["full"]), (1, False))
        text = Path(self.brain.inst.vault / r["repos"][0]["snapshot"]).read_text(encoding="utf-8")
        self.assertIn("terceiro, com data velha", text)
        self.assertNotIn("commit recente", text)                             # já relatado no pull anterior
        self.assertNotIn("### README.md", text)                              # documentos só na leitura completa

    def test_fetch_reads_the_remote_and_strips_credentials(self):
        bare = self.tmp / "remote.git"
        git(self.tmp, "clone", "-q", "--bare", str(self.repo), str(bare))
        git(self.repo, "remote", "add", "origin", str(bare))
        git(self.repo, "fetch", "-q", "origin")
        repos.pull(self.brain, "github-repos")
        other = self.tmp / "colega"
        git(self.tmp, "clone", "-q", str(bare), str(other))
        commit(other, "d.txt", "commit da colega")
        git(other, "push", "-q", "origin", "main")
        self.assertEqual(repos.pull(self.brain, "github-repos", fetch=False)["repos"][0]["new"], 0)  # sem fetch: nada
        r = repos.pull(self.brain, "github-repos")                           # fetch é o padrão
        self.assertEqual(r["repos"][0]["new"], 1)
        self.assertIn("commit da colega", (self.brain.inst.vault / r["repos"][0]["snapshot"]).read_text(encoding="utf-8"))
        git(self.repo, "remote", "set-url", "origin", "https://user:segredo@example.com/org/app.git")
        self.assertEqual(repos._remote(self.repo), "https://example.com/org/app.git")

    def test_nested_org_folders_and_missing_path(self):
        nested = self.github / "org" / "lib"
        nested.mkdir(parents=True)
        git(nested, "init", "-q", "-b", "main")
        commit(nested, "x.txt", "lib inicial")
        self.assertEqual([p.relative_to(self.github).as_posix() for p in repos.discover(self.github)], ["app", "org/lib"])
        self.assertEqual({x["repo"] for x in repos.pull(self.brain, "github-repos")["repos"]}, {"app", "org/lib"})
        watch.edit(self.brain.inst, "github-repos", {"path": str(self.tmp / "nada")})
        r = repos.pull(self.brain, "github-repos")
        self.assertTrue(r["failed"])
        self.assertEqual(self.brain.state.connectors["github-repos"].consecutive_failures, 1)


if __name__ == "__main__":
    unittest.main()
