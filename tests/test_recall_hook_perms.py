"""Hook de recall no Claude Code (.claude/settings.local.json via perms.sync) + guardas do recall_context.py."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, index, perms, util                     # noqa: E402
from brainlib.core import Brain                                     # noqa: E402


def _inst(tmp: Path, toml: str = "") -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(toml, encoding="utf-8")
    goals = tmp / "vault" / "PLANNING" / "goals.md"
    if not goals.exists():
        goals.write_text(
            "# PLANNING\n\n## GOAL-1 — Abrir o segundo ponto\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n",
            encoding="utf-8",
        )
    return config.load(tmp)


def _brain(tmp: Path, title: str = "Revisar orçamento") -> Brain:
    b = Brain(_inst(tmp, '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "none"\n'))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    b.record_one({"type": "person.added", "id": "marina-demo", "by": "owner",
                  "data": {"name": "Marina-demo", "aliases": ["Mari-demo"]}})
    late = b.record_one({"type": "action.opened", "by": "agent", "date": "2026-10-02",
                         "prov": "observado", "source": "chat",
                         "data": {"title": title, "owner": "marina-demo", "due": "2026-10-04"}})
    b._ids = {"late": late["id"]}
    index.update(b)
    return b


class RecallHookConfigTest(unittest.TestCase):
    def test_default_off_and_legacy_auto_normalizes_to_false(self):
        """Desde a 2.25 não existe "auto": default false; o legado "auto" vira false no load."""
        self.assertIs(config.DEFAULTS["memory"]["recall_hook"], False)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            for raw, expected in (('recall_hook = "auto"', False),        # legado: aceito, normalizado
                                  ("recall_hook = true", True),
                                  ("recall_hook = false", False)):
                inst = _inst(p, f"[memory]\n{raw}\n")
                self.assertIs(inst.cfg["memory"]["recall_hook"], expected)
            for bad in ('recall_hook = "sempre"', "recall_hook = 1", 'recall_hook = ""'):
                with self.assertRaises(util.BrainError):
                    _inst(p, f"[memory]\n{bad}\n")


class RecallHookPermsTest(unittest.TestCase):
    def test_hook_follows_recall_hook_bool_only(self):
        cases = [
            ('recall_hook = true\n', 1),                                # o único jeito de ligar: explícito
            ('recall_hook = false\nharnesses = ["claude-code"]\n', 0),  # harnesses é chave morta (2.25)
            ('recall_hook = "auto"\n', 0),                              # legado: normalizado para false
            ('recall_hook = true\nharnesses = ["claude-code"]\n', 1),   # harnesses presente e irrelevante
        ]
        for mem_toml, expected_count in cases:
            with self.subTest(mem_toml=mem_toml), tempfile.TemporaryDirectory() as td:
                inst = _inst(Path(td), f"[memory]\n{mem_toml}")
                res = perms.sync(inst)
                self.assertTrue(res["changed"])
                data = json.loads(perms.local_path(inst).read_text(encoding="utf-8"))
                ups = (data.get("hooks") or {}).get("UserPromptSubmit") or []
                recall_entries = [e for e in ups if perms._is_recall(e)]
                self.assertEqual(len(recall_entries), expected_count)
                if expected_count == 0:
                    self.assertNotIn("hooks", data)
                self.assertFalse(perms.sync(inst)["changed"])

    def test_command_tokens_and_route_by_engine(self):
        with tempfile.TemporaryDirectory() as td:
            inst = _inst(
                Path(td),
                '[memory]\nengine = "none"\nbank = "brain"\nharness_bank = "banco-agentes"\n'
                'url = "http://localhost:8888"\nrecall_hook = true\n',
            )
            cfg = inst.cfg
            cmd = perms.recall_hook_command(inst)
            tokens = shlex.split(cmd)
            self.assertIn(f"BRAIN_RECALL_BANKS={cfg['memory']['bank']}", tokens)
            self.assertTrue(tokens[-1].endswith("services/hooks/recall_context.py"))
            self.assertTrue(all(cfg["memory"]["harness_bank"] not in t for t in tokens))
            self.assertIn("BRAIN_RECALL_ROUTE=ledger", tokens)
            self.assertIn(f"BRAIN_HINDSIGHT_URL={cfg['memory']['url']}", tokens)
            self.assertIn(f"BRAIN_HOME={inst.root}", tokens)

            inst_hs = _inst(
                Path(td),
                '[memory]\nengine = "hindsight"\nbank = "brain"\nharness_bank = "banco-agentes"\nrecall_hook = true\n',
            )
            tokens_hs = shlex.split(perms.recall_hook_command(inst_hs))
            self.assertIn("BRAIN_RECALL_ROUTE=embed", tokens_hs)

    def test_owner_hook_entry_and_other_events_survive_sync_on_and_off(self):
        owner_entry = {"hooks": [{"type": "command", "command": "echo oi"}]}
        other_event = [{"hooks": [{"type": "command", "command": "echo stop"}]}]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            lf = p / ".claude" / "settings.local.json"
            lf.parent.mkdir(parents=True)
            lf.write_text(
                json.dumps({"hooks": {"UserPromptSubmit": [owner_entry], "Stop": other_event}}),
                encoding="utf-8",
            )
            inst_on = _inst(p, '[memory]\nrecall_hook = true\n')
            self.assertTrue(perms.sync(inst_on)["changed"])
            self.assertFalse(perms.sync(inst_on)["changed"])
            data_on = json.loads(lf.read_text(encoding="utf-8"))
            ups_on = data_on["hooks"]["UserPromptSubmit"]
            self.assertIn(owner_entry, ups_on)
            self.assertEqual(len([e for e in ups_on if perms._is_recall(e)]), 1)
            self.assertEqual(data_on["hooks"]["Stop"], other_event)

            inst_off = _inst(p, '[memory]\nrecall_hook = false\nharnesses = ["claude-code"]\n')
            self.assertTrue(perms.sync(inst_off)["changed"])
            self.assertFalse(perms.sync(inst_off)["changed"])
            data_off = json.loads(lf.read_text(encoding="utf-8"))
            self.assertEqual(data_off["hooks"]["UserPromptSubmit"], [owner_entry])
            self.assertEqual(data_off["hooks"]["Stop"], other_event)


class RecallHookRuntimeGuardsTest(unittest.TestCase):
    HOOK = ROOT / "services" / "hooks" / "recall_context.py"

    def test_nightly_and_recall_off_exit_zero_with_empty_stdout(self):
        with tempfile.TemporaryDirectory() as td:
            _brain(Path(td))
            for flag in ("BRAIN_NIGHTLY", "BRAIN_RECALL_OFF"):
                env = {**os.environ, "BRAIN_NOW": "2026-10-09T10:00:00-03:00",
                       "BRAIN_HOME": td, "BRAIN_RECALL_ROUTE": "ledger", flag: "1"}
                r = subprocess.run([sys.executable, str(self.HOOK)],
                                   input=json.dumps({"prompt": "o que está atrasado com a Marina-demo?"}),
                                   capture_output=True, text=True, cwd=ROOT, env=env, timeout=30)
                self.assertEqual(r.returncode, 0)
                self.assertEqual(r.stdout, "")

    def test_finds_instance_from_brain_home_first_then_cwd_and_silences_without_instance(self):
        with tempfile.TemporaryDirectory() as td_home, tempfile.TemporaryDirectory() as td_cwd, (
                tempfile.TemporaryDirectory()) as td_empty:
            _brain(Path(td_home), title="Orçamento da casa")
            _brain(Path(td_cwd), title="Orçamento do cwd")
            base_env = {k: v for k, v in os.environ.items() if k != "BRAIN_HOME"}
            base_env["BRAIN_NOW"] = "2026-10-09T10:00:00-03:00"
            base_env["BRAIN_RECALL_ROUTE"] = "ledger"

            # 1) BRAIN_HOME vence cwd
            r_home = subprocess.run([sys.executable, str(self.HOOK)],
                                    input=json.dumps({"prompt": "o que está atrasado?"}),
                                    capture_output=True, text=True, cwd=td_cwd,
                                    env={**base_env, "BRAIN_HOME": td_home}, timeout=30)
            self.assertEqual(r_home.returncode, 0)
            self.assertIn("Orçamento da casa", r_home.stdout)
            self.assertNotIn("Orçamento do cwd", r_home.stdout)

            # 2) Sem BRAIN_HOME, acha a instância pelo cwd
            r_cwd = subprocess.run([sys.executable, str(self.HOOK)],
                                   input=json.dumps({"prompt": "o que está atrasado?"}),
                                   capture_output=True, text=True, cwd=td_cwd,
                                   env=base_env, timeout=30)
            self.assertEqual(r_cwd.returncode, 0)
            self.assertIn("Orçamento do cwd", r_cwd.stdout)

            # 3) Sem instância em BRAIN_HOME nem no cwd → sai 0 em silêncio
            r_none = subprocess.run([sys.executable, str(self.HOOK)],
                                    input=json.dumps({"prompt": "o que está atrasado?"}),
                                    capture_output=True, text=True, cwd=td_empty,
                                    env=base_env, timeout=30)
            self.assertEqual(r_none.returncode, 0)
            self.assertEqual(r_none.stdout, "")


if __name__ == "__main__":
    unittest.main()
