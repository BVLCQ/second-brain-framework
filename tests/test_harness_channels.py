"""Canais do cérebro nos agentes (hook de recall no Claude Code + MCP somente-leitura + #19 Hermes provider)."""
from __future__ import annotations

import contextlib
import importlib.util as _ilu
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import cli, config, doctor, harness, memory, perms                    # noqa: E402
from brainlib.core import Brain                                                     # noqa: E402

_spec = _ilu.spec_from_file_location("test_brain", ROOT / "tests" / "test_brain.py")
_tb = _ilu.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_tb)
FakeHindsight = _tb.FakeHindsight


def _inst(tmp: Path, extra_mem: str = "") -> config.Instance:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROFILE").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "RAW" / "inbox").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "PROCESSED").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "FRESH").mkdir(parents=True, exist_ok=True)
    (tmp / "vault" / "reports").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n' + extra_mem,
        encoding="utf-8",
    )
    goals = tmp / "vault" / "PLANNING" / "goals.md"
    if not goals.exists():
        goals.write_text(
            "# PLANNING\n\n## GOAL-1 — Meta\n- status: ativo\n- horizonte: 2026-12-31\n- por quê: t\n",
            encoding="utf-8",
        )
    return config.load(tmp)


def _brain(tmp: Path, extra_mem: str = "") -> Brain:
    b = Brain(_inst(tmp, extra_mem))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class _RecRun:
    """Runner injetável que registra todas as chamadas sem tocar em binários reais."""

    def __init__(self, rc: int = 0, stdout: str = "", stderr: str = "", side_effect=None):
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.side_effect = side_effect
        self.argvs: list[list[str]] = []

    def __call__(self, cmd, **kw):
        argv = list(cmd)
        self.argvs.append(argv)
        if self.side_effect:
            res = self.side_effect(argv, **kw)
            if res is not None:
                return res
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


class HermesProviderTests(unittest.TestCase):
    """#19: Hermes só entra em [memory].harnesses quando memory.provider == hindsight."""

    def test_no_hermes_leaves_unregistered_and_hint_has_command_and_cli_exits_1(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst")
            run = _RecRun()
            with mock.patch.object(harness.shutil, "which", return_value=None):
                res = harness.install(b, ["hermes"], home=home, run=run)
            self.assertFalse(res[0]["ok"])
            self.assertNotIn("hermes", b.inst.cfg["memory"]["harnesses"])
            self.assertIn("hermes config set memory.provider hindsight", res[0]["hint"])
            self.assertIn("brain memory harness install hermes", res[0]["hint"])

            # Pela CLI: imprime ✗ com o hint e sai com código 1 quando todos falham
            args = cli.build_parser().parse_args(["memory", "harness", "install", "hermes"])
            buf = io.StringIO()
            with mock.patch.object(harness.shutil, "which", return_value=None), \
                 contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    memory.cli(args, b)
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("✗", buf.getvalue())
            self.assertIn("hermes config set memory.provider hindsight", buf.getvalue())

    def test_which_hermes_and_provider_call_rc_0_registers(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst")
            run = _RecRun(rc=0)
            with mock.patch.object(harness.shutil, "which", return_value="/usr/local/bin/hermes"):
                res = harness.install(b, ["hermes"], home=home, run=run)
            self.assertTrue(res[0]["ok"])
            self.assertIn("hermes", b.inst.cfg["memory"]["harnesses"])
            self.assertIn(["hermes", "config", "set", "memory.provider", "hindsight"], run.argvs)

    def test_config_yaml_with_hindsight_registers_even_if_cli_call_failed(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            y = harness.hermes_yaml(home)
            y.parent.mkdir(parents=True, exist_ok=True)
            y.write_text("# comentário\nmemory:\n  provider: hindsight\n", encoding="utf-8")
            b = _brain(home / "inst")
            run = _RecRun(rc=1, stderr="erro")
            with mock.patch.object(harness.shutil, "which", return_value="/usr/local/bin/hermes"):
                res = harness.install(b, ["hermes"], home=home, run=run)
            self.assertTrue(res[0]["ok"])
            self.assertIn("hermes", b.inst.cfg["memory"]["harnesses"])

    def test_verify_and_doctor_warn_when_registered_hermes_has_builtin_provider(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst", 'harnesses = ["hermes"]\n')
            hc = harness.hermes_config(home)
            hc.parent.mkdir(parents=True, exist_ok=True)
            hc.write_text(json.dumps({"api_url": "http://localhost:8888"}), encoding="utf-8")
            y = harness.hermes_yaml(home)
            y.write_text("memory:\n  provider: builtin\n", encoding="utf-8")
            hs = FakeHindsight()
            hs.put_bank("hermes", {"name": "agentes"})

            v = harness.verify(b, hs, home=home)
            self.assertFalse(v["channels"]["hermes"]["provider"])

            with mock.patch.object(memory, "client", return_value=hs), \
                 mock.patch.object(memory, "status", return_value={"level": "ok", "detail": "ok"}):
                cks = doctor.checks(b, online=False)
            hw = next(c for c in cks if c["title"] == "harnesses")
            self.assertEqual(hw["level"], "warn")
            self.assertIn("hermes: memory.provider não é hindsight — `hermes config set memory.provider hindsight`",
                          hw["detail"])

    def test_doctor_offline_spawns_no_subprocess(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst", 'harnesses = ["hermes", "claude-code"]\n')
            hs = FakeHindsight()
            hs.put_bank("hermes", {"name": "agentes"})
            with mock.patch.object(memory, "client", return_value=hs), \
                 mock.patch.object(memory, "status", return_value={"level": "ok", "detail": "ok"}), \
                 mock.patch("subprocess.run", side_effect=AssertionError("subprocess proibido no doctor offline")):
                cks = doctor.checks(b, online=False)
            self.assertTrue(any(c["title"] == "harnesses" for c in cks))


class McpWritersTests(unittest.TestCase):
    """10b + emendas (b) e (c): Cursor JSON, Codex TOML, Hermes CLI+YAML e Claude CLI+JSON."""

    def test_cursor_preserves_other_server_and_unwires_cleanly(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst")
            p = home / ".cursor" / "mcp.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"mcpServers": {"other": {"command": "/bin/other", "args": []}}}),
                         encoding="utf-8")

            res = harness.wire_mcp(b.inst, "cursor-cli", home=home)
            self.assertTrue(res["ok"])
            self.assertEqual(res["how"], "file")
            self.assertTrue(harness.mcp_present(b.inst, "cursor-cli", home=home))
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn("other", data["mcpServers"])
            self.assertIn("brain", data["mcpServers"])
            self.assertEqual(data["mcpServers"]["brain"]["args"], ["mcp"])
            self.assertEqual(data["mcpServers"]["brain"]["env"]["BRAIN_HOME"], str(b.inst.root))

            un = harness.unwire_mcp(b.inst, "cursor-cli", home=home)
            self.assertTrue(un["ok"])
            self.assertFalse(harness.mcp_present(b.inst, "cursor-cli", home=home))
            after = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(list(after["mcpServers"].keys()), ["other"])

    def test_cursor_invalid_json_returns_manual_without_touching_file(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst")
            p = home / ".cursor" / "mcp.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            broken = "{invalido"
            p.write_text(broken, encoding="utf-8")
            res = harness.wire_mcp(b.inst, "cursor-cli", home=home)
            self.assertFalse(res["ok"])
            self.assertEqual(res["how"], "manual")
            self.assertEqual(p.read_text(encoding="utf-8"), broken)

    def test_codex_wires_idempotently_unwires_byte_for_byte_and_refuses_foreign_brain(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst")
            p = home / ".codex" / "config.toml"
            p.parent.mkdir(parents=True, exist_ok=True)
            orig = '[mcp_servers.other]\ncommand = "/usr/local/bin/other"\nargs = ["--stdio"]\n'
            p.write_text(orig, encoding="utf-8")

            r1 = harness.wire_mcp(b.inst, "codex", home=home)
            self.assertTrue(r1["ok"])
            self.assertEqual(r1["how"], "file")
            r2 = harness.wire_mcp(b.inst, "codex", home=home)
            self.assertTrue(r2["ok"])

            wired_txt = p.read_text(encoding="utf-8")
            self.assertEqual(wired_txt.count(harness.MARK_BEGIN), 1)
            self.assertEqual(wired_txt.count(harness.MARK_END), 1)
            parsed = tomllib.loads(wired_txt)
            self.assertIn("other", parsed["mcp_servers"])
            self.assertIn("brain", parsed["mcp_servers"])
            self.assertEqual(parsed["mcp_servers"]["brain"]["command"], str(harness.FRAMEWORK / "brain"))
            self.assertTrue(harness.mcp_present(b.inst, "codex", home=home))

            un = harness.unwire_mcp(b.inst, "codex", home=home)
            self.assertTrue(un["ok"])
            self.assertEqual(p.read_text(encoding="utf-8"), orig)
            self.assertFalse(harness.mcp_present(b.inst, "codex", home=home))

            # Foreign [mcp_servers.brain] fora dos marcadores → manual e arquivo intocado
            foreign = '[mcp_servers.brain]\ncommand = "/outro/brain"\n'
            p.write_text(foreign, encoding="utf-8")
            rf = harness.wire_mcp(b.inst, "codex", home=home)
            self.assertFalse(rf["ok"])
            self.assertEqual(rf["how"], "manual")
            self.assertIn("já existe um servidor `brain` no config do Codex", rf["hint"])
            self.assertEqual(p.read_text(encoding="utf-8"), foreign)

    def test_hermes_mcp_uses_cli_with_env_before_args_and_line_scans_yaml(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst")
            y = harness.hermes_yaml(home)
            y.parent.mkdir(parents=True, exist_ok=True)
            spec_cmd = str(harness.FRAMEWORK / "brain")

            # 1) Três fixtures de leitura em mcp_present: sem chave / bloco com filhos / inline mcp_servers: {}
            y.write_text("memory:\n  provider: hindsight\n", encoding="utf-8")
            self.assertFalse(harness.mcp_present(b.inst, "hermes", home=home))

            y.write_text("mcp_servers: {}\n", encoding="utf-8")
            self.assertFalse(harness.mcp_present(b.inst, "hermes", home=home))

            y.write_text(
                f"mcp_servers:\n    other:\n        command: /bin/x\n    brain:\n        command: {spec_cmd}\n"
                "        args:\n            - mcp\n        enabled: true\n",
                encoding="utf-8",
            )
            self.assertTrue(harness.mcp_present(b.inst, "hermes", home=home))

            # 2) wire_mcp chama `hermes mcp add` com --env ANTES de --args
            def _save_yaml(argv, **_kw):
                if argv[:3] == ["hermes", "mcp", "add"]:
                    y.write_text(
                        f"mcp_servers:\n  brain:\n    command: {spec_cmd}\n    args:\n      - mcp\n    enabled: true\n",
                        encoding="utf-8",
                    )
                return None

            run = _RecRun(rc=0, side_effect=_save_yaml)
            with mock.patch.object(harness.shutil, "which", return_value="/usr/local/bin/hermes"):
                w = harness.wire_mcp(b.inst, "hermes", home=home, run=run)
            self.assertTrue(w["ok"])
            self.assertEqual(w["how"], "cli")
            expected_argv = [
                "hermes", "mcp", "add", "brain",
                "--command", spec_cmd,
                "--env", f"BRAIN_HOME={b.inst.root}",
                "--args", "mcp",
            ]
            self.assertEqual(run.argvs[0], expected_argv)
            self.assertLess(run.argvs[0].index("--env"), run.argvs[0].index("--args"))

            # 3) Falha de conexão (config não salvo) → ok: False com comando no hint
            y.write_text("memory:\n  provider: hindsight\n", encoding="utf-8")
            run_fail = _RecRun(rc=0, stdout="Failed to connect. Save config anyway? [y/N]")
            with mock.patch.object(harness.shutil, "which", return_value="/usr/local/bin/hermes"):
                wf = harness.wire_mcp(b.inst, "hermes", home=home, run=run_fail)
            self.assertFalse(wf["ok"])
            self.assertIn(f"hermes mcp add brain --command {spec_cmd} --env BRAIN_HOME={b.inst.root} --args mcp",
                          wf["hint"])

            # 4) unwire_mcp chama `hermes mcp remove brain`
            run_rm = _RecRun(rc=0)
            with mock.patch.object(harness.shutil, "which", return_value="/usr/local/bin/hermes"):
                urm = harness.unwire_mcp(b.inst, "hermes", home=home, run=run_rm)
            self.assertTrue(urm["ok"])
            self.assertEqual(run_rm.argvs[0], ["hermes", "mcp", "remove", "brain"])


class ClaudeChannelsAndRemoveTests(unittest.TestCase):
    """10c + 10d: claude-code hook + MCP, --no-mcp, --no-recall, remove e separação de bancos."""

    def test_claude_code_mcp_argv_and_flags_and_remove(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst")
            run = _RecRun(rc=0)
            with mock.patch.object(harness.shutil, "which", side_effect=lambda x: f"/usr/bin/{x}"):
                res = harness.install(b, ["claude-code"], home=home, run=run)
            self.assertTrue(res[0]["ok"])
            self.assertTrue(res[0]["mcp"]["ok"])
            self.assertTrue(res[0]["recall"]["ok"])
            expected_mcp = [
                "claude", "mcp", "add", "--scope", "user", "brain",
                "--env", f"BRAIN_HOME={b.inst.root}",
                "--", str(harness.FRAMEWORK / "brain"), "mcp",
            ]
            self.assertIn(expected_mcp, run.argvs)
            self.assertIs(b.inst.cfg["memory"]["recall_hook"], True)
            local_data = json.loads(perms.local_path(b.inst).read_text(encoding="utf-8"))
            ups = (local_data.get("hooks") or {}).get("UserPromptSubmit") or []
            self.assertEqual(len([e for e in ups if perms._is_recall(e)]), 1)

            # --no-mcp → nenhuma chamada `claude mcp add`
            run_no_mcp = _RecRun(rc=0)
            with mock.patch.object(harness.shutil, "which", side_effect=lambda x: f"/usr/bin/{x}"):
                harness.install(b, ["claude-code"], home=home, run=run_no_mcp, mcp=False)
            self.assertFalse(any(a[:3] == ["claude", "mcp", "add"] for a in run_no_mcp.argvs))

            # --no-recall → recall_hook False e settings.local.json sem entrada de recall
            run_no_rec = _RecRun(rc=0)
            with mock.patch.object(harness.shutil, "which", side_effect=lambda x: f"/usr/bin/{x}"):
                harness.install(b, ["claude-code"], home=home, run=run_no_rec, recall=False)
            self.assertIs(b.inst.cfg["memory"]["recall_hook"], False)
            local_off = json.loads(perms.local_path(b.inst).read_text(encoding="utf-8"))
            ups_off = (local_off.get("hooks") or {}).get("UserPromptSubmit") or []
            self.assertEqual([e for e in ups_off if perms._is_recall(e)], [])

            # Religa e remove → recall_hook == "auto", fora de harnesses, sem recall entry e `claude mcp remove` chamado
            with mock.patch.object(harness.shutil, "which", side_effect=lambda x: f"/usr/bin/{x}"):
                harness.install(b, ["claude-code"], home=home, run=_RecRun(rc=0))
            run_rm = _RecRun(rc=0)
            with mock.patch.object(harness.shutil, "which", side_effect=lambda x: f"/usr/bin/{x}"):
                harness.remove(b, ["claude-code"], home=home, run=run_rm)
            self.assertEqual(b.inst.cfg["memory"]["recall_hook"], "auto")
            self.assertNotIn("claude-code", b.inst.cfg["memory"]["harnesses"])
            local_rm = json.loads(perms.local_path(b.inst).read_text(encoding="utf-8"))
            ups_rm = (local_rm.get("hooks") or {}).get("UserPromptSubmit") or []
            self.assertEqual([e for e in ups_rm if perms._is_recall(e)], [])
            self.assertIn(["claude", "mcp", "remove", "--scope", "user", "brain"], run_rm.argvs)

    def test_bank_separation_across_hook_and_all_mcp_writers(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst", 'bank = "banco-vault"\nharness_bank = "banco-agentes"\nrecall_hook = true\n')
            tokens = shlex.split(perms.recall_hook_command(b.inst))
            self.assertIn("BRAIN_RECALL_BANKS=banco-vault", tokens)
            self.assertNotEqual(b.inst.cfg["memory"]["bank"], b.inst.cfg["memory"]["harness_bank"])
            self.assertTrue(all("banco-agentes" not in t for t in tokens))

            run = _RecRun(rc=0)
            with mock.patch.object(harness.shutil, "which", side_effect=lambda x: f"/usr/bin/{x}"):
                for agent in ("claude-code", "cursor-cli", "codex", "hermes"):
                    harness.wire_mcp(b.inst, agent, home=home, run=run)
            for argv in run.argvs:
                self.assertTrue(all("banco-agentes" not in a for a in argv))
            for rel in (".cursor/mcp.json", ".codex/config.toml"):
                self.assertNotIn("banco-agentes", (home / rel).read_text(encoding="utf-8"))

    def test_doctor_ok_message_keeps_conectados_prefix_and_lists_channels(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"HOME": td}):
            home = Path(td)
            b = _brain(home / "inst", 'harnesses = ["claude-code"]\nrecall_hook = true\n')
            perms.sync(b.inst)
            harness.merge_coding_agent(harness.coding_agent_config(home), "http://localhost:8888", "hermes")
            (home / ".claude.json").write_text(
                json.dumps({"mcpServers": {"brain": harness.mcp_spec(b.inst)}}),
                encoding="utf-8",
            )
            hs = FakeHindsight()
            hs.put_bank("hermes", {"name": "agentes"})
            with mock.patch.object(memory, "client", return_value=hs), \
                 mock.patch.object(memory, "status", return_value={"level": "ok", "detail": "ok"}):
                cks = doctor.checks(b, online=False)
            hw = next(c for c in cks if c["title"] == "harnesses")
            self.assertEqual(hw["level"], "ok")
            self.assertTrue(hw["detail"].startswith("1 conectado(s) · banco 'hermes' responde ao recall"))
            self.assertIn("· canais: claude-code hook+mcp", hw["detail"])


if __name__ == "__main__":
    unittest.main()
