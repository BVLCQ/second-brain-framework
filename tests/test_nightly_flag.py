"""`BRAIN_NIGHTLY` lido por um ponto só (`util.is_nightly`) — qualquer valor truthy é noturno, não só "1" (#134)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config, util                                     # noqa: E402
from brainlib.core import Brain                                       # noqa: E402

TRUTHY = ("1", "true", "TRUE", "True", "yes", "on", " yes ", "1 ")
FALSY = (None, "", "0", "false", "no", "off", "não")


@contextmanager
def _nightly(value):
    """Troca BRAIN_NIGHTLY pelo valor dado (None = ausente) e devolve o original no fim."""
    old = os.environ.get("BRAIN_NIGHTLY")
    if value is None:
        os.environ.pop("BRAIN_NIGHTLY", None)
    else:
        os.environ["BRAIN_NIGHTLY"] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("BRAIN_NIGHTLY", None)
        else:
            os.environ["BRAIN_NIGHTLY"] = old


def _inst(tmp: Path) -> config.Instance:
    for rel in ("config", "vault/PLANNING", "vault/PROFILE", "vault/RAW/inbox", "vault/PROCESSED", "vault/FRESH"):
        (tmp / rel).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "none"\n\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text(
        "# PLANNING\n\n## GOAL-1 — Abrir o segundo ponto\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n\n",
        encoding="utf-8")
    return config.load(tmp)


class IsNightlyTest(unittest.TestCase):
    def test_truthy_values(self):
        for v in TRUTHY:
            with self.subTest(v=v), _nightly(v):
                self.assertTrue(util.is_nightly())

    def test_falsy_and_unset(self):
        for v in FALSY:
            with self.subTest(v=v), _nightly(v):
                self.assertFalse(util.is_nightly())


class EveryGateHonoursTruthyValuesTest(unittest.TestCase):
    """Os três pontos citados pelo issue (ledger, TUI, hook) recusam com `true`/`yes`/`on` igual a com "1"."""

    def test_ledger_refuses_owner_event(self):
        for v in ("1", "true", "yes", "on"):
            with self.subTest(v=v), tempfile.TemporaryDirectory() as td, _nightly(v):
                b = Brain(_inst(Path(td)))
                with self.assertRaises(util.BrainError) as cm:
                    b.record_one({"type": "person.added", "id": "eu", "by": "owner", "data": {"name": "Dona"}})
                self.assertEqual(cm.exception.code, 4)
                self.assertIn("noturno", str(cm.exception))

    def test_ledger_accepts_owner_event_when_flag_is_falsy(self):
        for v in FALSY:
            with self.subTest(v=v), tempfile.TemporaryDirectory() as td, _nightly(v):
                b = Brain(_inst(Path(td)))
                ev = b.record_one({"type": "person.added", "id": "eu", "by": "owner", "data": {"name": "Dona"}})
                self.assertEqual(ev["id"], "eu")

    def test_tui_refuses_to_open(self):
        from brainlib import tui
        for v in ("1", "true", "yes", "ON"):
            with self.subTest(v=v), _nightly(v):
                with self.assertRaises(util.BrainError) as cm:
                    tui.cli(SimpleNamespace(setup=False), brain=SimpleNamespace(inst=None))
                self.assertEqual(cm.exception.code, 4)
                self.assertIn("noturno", str(cm.exception))

    def test_recall_hook_exits_zero_and_silent(self):
        hook = ROOT / "services" / "hooks" / "recall_context.py"
        for v in ("true", "yes", "on"):
            with self.subTest(v=v), tempfile.TemporaryDirectory() as td:
                env = {**os.environ, "BRAIN_HOME": td, "BRAIN_RECALL_ROUTE": "ledger", "BRAIN_NIGHTLY": v}
                r = subprocess.run([sys.executable, str(hook)], input=json.dumps({"prompt": "o que está atrasado?"}),
                                   capture_output=True, text=True, cwd=ROOT, env=env, timeout=30)
                self.assertEqual((r.returncode, r.stdout), (0, ""))


class SingleReaderGuardTest(unittest.TestCase):
    """Nenhum módulo do framework lê BRAIN_NIGHTLY por conta própria: a única leitura é `util.is_nightly()`.

    Guarda por varredura do fonte (pula o próprio arquivo): a regex é montada por concatenação para que o
    scanner não se acuse, e setters legítimos (`env={..., "BRAIN_NIGHTLY": "1"}`) continuam permitidos."""

    def test_no_ad_hoc_read_outside_util(self):
        flag = "BRAIN_" + "NIGHTLY"
        setter = re.compile(flag + r'"\s*:')
        roots = [ROOT / "brainlib", ROOT / "scripts", ROOT / "services"]
        files = [p for base in roots if base.is_dir() for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts]
        if (ROOT / "brain").is_file():
            files.append(ROOT / "brain")
        hits = []
        for p in files:
            if p.name in {Path(__file__).name, "util.py"}:  # este teste e o próprio helper
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if flag not in line or "is_nightly" in line or line.lstrip().startswith("#"):
                    continue
                if setter.search(line) and "environ.get" not in line and "getenv" not in line:
                    continue
                if "environ" in line or "getenv" in line:
                    hits.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()}")
        self.assertEqual(hits, [], "\nleitura fora do helper:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
