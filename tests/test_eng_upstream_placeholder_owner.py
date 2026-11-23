"""`upstream scan` numa cópia sem config de instância não acusa o placeholder público do dono.

O nome padrão de `config.DEFAULTS["owner"]["name"]` é texto público do próprio framework: com ele, fixture de
teste que escreve o placeholder virava "dado pessoal (dono)". Nome de verdade, configurado, segue protegido.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, upstream

PLACEHOLDER = config.DEFAULTS["owner"]["name"]           # "Dono do cérebro": texto público, não é dado de ninguém


def _inst(tmp: Path, *, allow: tuple[str, ...] = ("dona-demo", "marina-demo", "#time")) -> config.Instance:
    """Instância de prova: dono `dona-demo` SEM o alias "eu" — só a dobra de "eu" faz o dono ser achado."""
    for d in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH",
              "vault/reports"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "dona-demo"\nname = "Dona Demo"\n\n'
        '[outbound]\nallow = [' + ", ".join(f'"{x}"' for x in allow) + ']\n\n'
        '[work]\nstart = "09:00"\nend = "18:00"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    return config.load(tmp)

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


@unittest.skipUnless(shutil.which("git"), "git ausente")
class PlaceholderOwnerIsNotLeakTerm(unittest.TestCase):
    def test_leak_terms_skip_the_default_owner_name(self):
        with tempfile.TemporaryDirectory() as td:
            inst = config.load(Path(td))                                # sem config/brain.toml: só DEFAULTS
            self.assertEqual(inst.cfg["owner"]["name"], PLACEHOLDER)
            self.assertNotIn((PLACEHOLDER.lower(), "dono"), upstream._leak_terms(inst))
            real = _inst(Path(td) / "cfg")                               # dono de verdade configurado
            terms = dict(upstream._leak_terms(real))
            self.assertEqual((terms.get("dona demo"), terms.get("dona-demo")), ("dono", "dono"))

    def test_scan_without_instance_config_does_not_flag_the_placeholder(self):
        """Antes: worktree/clone sem config acusava `dado pessoal (dono)` em toda fixture que escreve o placeholder."""
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            (repo / "a.py").write_text(f'OWNER = "{PLACEHOLDER}"\n', encoding="utf-8")
            (repo / "b.py").write_text('OWNER = "Fulana Quiteria"\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "fixtures")
            revsets = [["HEAD", "^origin/main"]]

            findings = upstream.scan(config.load(repo), None, committed=True, revsets=revsets)
            self.assertEqual([f for f in findings if f["rule"] == "dado pessoal (dono)"], [])

            (repo / "config").mkdir()
            (repo / "config" / "brain.toml").write_text('[owner]\nid = "fulana"\nname = "Fulana Quiteria"\n',
                                                         encoding="utf-8")
            findings = upstream.scan(config.load(repo), None, committed=True, revsets=revsets)
            hits = sorted(f["file"].split(" (commit")[0] for f in findings if f["rule"] == "dado pessoal (dono)")
            self.assertEqual(hits, ["b.py"])                             # o nome real continua protegido

if __name__ == "__main__":
    unittest.main()
