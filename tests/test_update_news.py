"""Versão visível + aviso de atualização + novidades (estilo Hermes) — stdlib unittest."""
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

os.environ.setdefault("BRAIN_NOW", "2026-11-05T10:00:00-03:00")

from brainlib import config, render, upstream, util                     # noqa: E402
from brainlib.core import Brain                                        # noqa: E402

CHANGELOG = """# Novidades

## 2.1.0 — 2026-11-05
- Setup assistido com um clique
- Memória em dois modos
- Aviso de atualização no painel

## 2.0.2 — 2026-10-30
- Correções de estabilidade na TUI

## 2.0.0 — 2026-10-20
- A constituição v2
"""


class ChangelogTests(unittest.TestCase):
    def test_parse(self):
        entries = upstream.parse_changelog(CHANGELOG)
        self.assertEqual([e[0] for e in entries], ["2.1.0", "2.0.2", "2.0.0"])
        self.assertEqual(entries[0][1], "2026-11-05")
        self.assertEqual(len(entries[0][2]), 3)

    def test_news_between(self):
        self.assertEqual(upstream.news_between(CHANGELOG, "2.0.2", "2.1.0"),
                         ["Setup assistido com um clique", "Memória em dois modos",
                          "Aviso de atualização no painel"])
        self.assertEqual(upstream.news_between(CHANGELOG, "2.0.0", "2.0.2"),
                         ["Correções de estabilidade na TUI"])
        self.assertEqual(upstream.news_between(CHANGELOG, "2.1.0"), [])      # já na última
        self.assertEqual(upstream.news_between(CHANGELOG, "2.0.0", "2.1.0"),
                         ["Setup assistido com um clique", "Memória em dois modos",
                          "Aviso de atualização no painel", "Correções de estabilidade na TUI"])


def _git(cwd, *args, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.returncode, r.stdout, r.stderr


class _RepoCase(unittest.TestCase):
    """Remote com uma versão NOVA; clone local numa versão velha — o mundo real de upgrade."""

    def setUp(self):
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                    "HOME": str(Path(tempfile.mkdtemp()))}
        self.td = Path(tempfile.mkdtemp())
        self.remote = self.td / "origin.git"
        _git(self.td, "init", "-q", "--bare", "-b", "main", str(self.remote))
        # 1) upstream nasce na v2.2.0 (com changelog)
        src = self.td / "src"
        (src / "brainlib").mkdir(parents=True)
        (src / "brainlib" / "__init__.py").write_text('__version__ = "2.2.0"\n', encoding="utf-8")
        (src / "CHANGELOG.md").write_text(
            "# Novidades\n\n## 2.2.0 — 2026-12-01\n- Modo full da memória\n- Painel mais rápido\n",
            encoding="utf-8")
        _git(src, "init", "-q", "-b", "main")
        _git(src, "add", "-A")
        _git(src, "commit", "-q", "-m", "v2.2.0")
        _git(src, "push", "-q", str(self.remote), "main")
        # 2) clone local e REGRESSA à v2.1.0 (o usuário numa versão velha)
        self.work = self.td / "brain"
        _git(self.td, "clone", "-q", str(self.remote), str(self.work))
        (self.work / "brainlib" / "__init__.py").write_text('__version__ = "2.1.0"\n', encoding="utf-8")
        (self.work / "CHANGELOG.md").write_text(
            "# Novidades\n\n## 2.1.0 — 2026-11-05\n- Setup assistido\n", encoding="utf-8")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", "local v2.1.0")
        _git(self.work, "push", "-q", str(self.remote), "main")
        # 3) upstream avança (changelog ganha a seção da versão velha de volta)
        _git(src, "pull", "-q", str(self.remote), "main")
        (src / "brainlib" / "__init__.py").write_text('__version__ = "2.2.0"\n', encoding="utf-8")
        (src / "CHANGELOG.md").write_text(
            "# Novidades\n\n## 2.2.0 — 2026-12-01\n- Modo full da memória\n- Painel mais rápido\n"
            "\n## 2.1.0 — 2026-11-05\n- Setup assistido\n", encoding="utf-8")
        _git(src, "add", "-A")
        _git(src, "commit", "-q", "-m", "up: v2.2.0 com changelog completo")
        _git(src, "push", "-q", str(self.remote), "main")
        self.assertNotEqual(_git(self.remote, "rev-parse", "main")[1], _git(self.work, "rev-parse", "HEAD")[1], "fixture: remote não avançou")
        # 4) instância brain dentro do clone
        for d in ("PLANNING", "RAW/inbox", "PROCESSED/_ledger", "FRESH"):
            (self.work / "vault" / d).mkdir(parents=True, exist_ok=True)
        (self.work / "config").mkdir(exist_ok=True)
        (self.work / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n',
                                                         encoding="utf-8")
        (self.work / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
        (self.work / "vault" / "PROCESSED" / "_ledger" / "events.jsonl").write_text("", encoding="utf-8")
        self.inst = config.load(self.work)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.td, ignore_errors=True)


class CheckUpdateTests(_RepoCase):
    def test_detects_behind_with_news(self):
        c = upstream.check_update(self.inst, force=True)
        self.assertEqual(c["behind"], 1)
        self.assertEqual(c["version"], "2.1.0")
        self.assertEqual(c["remote_version"], "2.2.0")
        self.assertEqual(c["news"], ["Modo full da memória", "Painel mais rápido"])

    def test_cache_prevents_refetch_within_24h(self):
        upstream.check_update(self.inst, force=True)
        cache_file = self.inst.fresh / upstream.CHECK_CACHE
        saved = json.loads(cache_file.read_text(encoding="utf-8"))
        # muda o remote de novo; sem force, o cache (24h) vence
        c = upstream.check_update(self.inst, force=False)
        self.assertEqual(c, saved)
        self.assertEqual(c["behind"], 1)

    def test_offline_falls_back_to_cache(self):
        upstream.check_update(self.inst, force=True)
        # quebra o remote (aponta pra lugar inexistente) e força "offline"
        _git(self.work, "remote", "set-url", "origin", str(self.td / "nao-existe.git"))
        inst2 = config.load(self.work)
        c = upstream.check_update(inst2, force=True)
        self.assertEqual(c.get("behind"), 1)                       # cache preservado
        self.assertTrue(c.get("error"))                            # e o erro registrado


class UpdateFlowTests(_RepoCase):
    def test_update_pulls_and_reports_news(self):
        res = upstream.update(self.inst)
        self.assertTrue(res["updated"])
        self.assertEqual(res["version_before"], "2.1.0")
        self.assertEqual(res["version_after"], "2.2.0")
        self.assertIn("Modo full da memória", res["news"])
        # cache re-basado: depois de atualizar, não há mais novidade
        c = upstream.read_check_cache(self.inst)
        self.assertEqual(c.get("behind"), 0)
        self.assertEqual(c.get("news"), [])


class SurfacesTests(_RepoCase):
    def test_render_embeds_update_block_and_badge(self):
        upstream.check_update(self.inst, force=True)
        b = Brain(self.inst)
        b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                      "data": {"name": "Dona", "relation": "dono"}})
        m = render.view_model(b)
        from brainlib import __version__
        self.assertEqual(m["update"]["version"], __version__)       # a versão do módulo em execução
        self.assertEqual(m["update"]["behind"], 1)
        self.assertEqual(m["update"]["news"], ["Modo full da memória", "Painel mais rápido"])
        report = render.render_all(b, do_harvest=False)
        html = Path(report["dashboard"]).read_text(encoding="utf-8")
        self.assertIn("verbadge", html)                             # badge no painel construído
        self.assertIn("newsback", html)

    def test_doctor_warns_when_behind(self):
        from brainlib import doctor
        upstream.check_update(self.inst, force=True)
        b = Brain(self.inst)
        b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                      "data": {"name": "Dona", "relation": "dono"}})
        got = [c for c in doctor.checks(b) if c["title"] == "framework"]
        self.assertTrue(any("atualização disponível" in c["detail"] for c in got))


if __name__ == "__main__":
    unittest.main()
