"""Decisor local e `brain services ensure` (#172)."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brainlib import config, decider, forms, providers, services, util
from brainlib.core import Brain

ROOT = Path(__file__).resolve().parents[1]


def _brain(tmp: Path) -> Brain:
    (tmp / "config").mkdir(parents=True)
    for zone in ("PLANNING", "PROFILE", "RAW/inbox", "PROCESSED", "FRESH", "reports"):
        (tmp / "vault" / zone).mkdir(parents=True)
    (tmp / "config" / "brain.toml").write_text(
        '[owner]\nid = "eu"\nname = "Dona"\n\n[memory]\nengine = "hindsight"\n',
        encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    (tmp / "vault" / "logs").mkdir(parents=True, exist_ok=True)
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner",
                  "data": {"name": "Dona", "aliases": ["Eu"], "relation": "dono"}})
    return b


class PlatformTests(unittest.TestCase):
    def test_apple_silicon_is_mlx(self):
        self.assertEqual(decider.platform_kind(system="darwin", machine="arm64"), "mlx")

    def test_linux_gpu_is_vllm(self):
        self.assertEqual(decider.platform_kind(system="linux", machine="x86_64", nvidia=True), "vllm")

    def test_linux_without_gpu_refuses(self):
        self.assertIsNone(decider.platform_kind(system="linux", machine="x86_64", nvidia=False))

    def test_smoke_waits_for_the_server_to_bind(self):
        calls = []

        def post(url, body, key):
            calls.append(url)
            return len(calls) >= 3

        self.assertTrue(decider._wait_smoke("http://127.0.0.1:8000", "bdk_x", http_post=post,
                                            sleep=lambda _s: None, attempts=5, pause=3))
        self.assertEqual(len(calls), 3)
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            ran = []
            with self.assertRaises(util.BrainError) as cm:
                decider.prepare(b, run=lambda cmd: ran.append(cmd) or (0, ""),
                                system="linux", machine="x86_64", nvidia=False)
            self.assertIn("nada foi instalado", str(cm.exception))
            self.assertEqual(ran, [])
            self.assertFalse(decider.installed(b.inst))


class UnitPlistTests(unittest.TestCase):
    """O plist do LaunchAgent já saiu malformado (`</key>` no lugar de `</dict>`): o launchd recusou
    em silêncio, o decisor nunca subiu e o `decider.log` nem foi criado. Os testes antigos rodam em
    pasta de teste, onde a unit não é instalada, então nada olhava o XML."""

    def test_plist_is_well_formed_and_complete(self):
        import plistlib
        d = plistlib.loads(decider.unit_plist("/opt/demo/Meu Brain & Cia").encode("utf-8"))
        self.assertEqual(d["Label"], decider.LABEL)
        self.assertEqual(d["ProgramArguments"],
                         ["/bin/sh", "/opt/demo/Meu Brain & Cia/services/decider-serve.sh"])
        self.assertEqual(d["EnvironmentVariables"], {"BRAIN_DIR": "/opt/demo/Meu Brain & Cia"})
        self.assertIs(d["RunAtLoad"], True)
        self.assertIs(d["KeepAlive"], True)
        self.assertEqual(d["StandardOutPath"], "/opt/demo/Meu Brain & Cia/vault/logs/decider.log")
        self.assertEqual(d["StandardErrorPath"], d["StandardOutPath"])

    def test_repo_template_matches_generated_plist(self):
        import plistlib
        raw = (ROOT / "services" / "com.segundo-cerebro.decider.plist").read_text(encoding="utf-8")
        self.assertEqual(plistlib.loads(raw.replace("__BRAIN_DIR__", "/x").encode("utf-8")),
                         plistlib.loads(decider.unit_plist("/x").encode("utf-8")))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("plutil"), "plutil só no macOS")
    def test_plutil_accepts_the_generated_plist(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "d.plist"
            p.write_text(decider.unit_plist(td), encoding="utf-8")
            out = subprocess.run(["plutil", "-lint", str(p)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_launchd_refusal_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            home = Path(td) / "home"

            def run(cmd):
                return (5, "Bootstrap failed: 5: Input/output error") if "bootstrap" in cmd else (0, "")

            with mock.patch.object(decider.sys, "platform", "darwin"), \
                    mock.patch.object(decider, "_scratch", return_value=False), \
                    mock.patch.object(decider.Path, "home", return_value=home):
                with self.assertRaises(util.BrainError) as cm:
                    decider._install_unit(b.inst, run=run)
            self.assertIn("launchd recusou", str(cm.exception))
            self.assertIn("Input/output error", str(cm.exception))

    def test_smoke_failure_says_when_the_service_never_started(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with mock.patch.object(decider, "_install_unit"), mock.patch.object(decider, "_start_unit"), \
                    mock.patch.object(decider, "stop_service"):
                with self.assertRaises(util.BrainError) as cm:
                    decider.prepare(b, system="darwin", machine="arm64", nvidia=False,
                                    python=sys.executable, run=lambda cmd: (0, ""),
                                    http_post=lambda *a: False, sleep=lambda _s: None)
            self.assertIn("nem chegou a escrever", str(cm.exception))


class NightlyTests(unittest.TestCase):
    def test_prepare_refuses_install_at_night(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
                with self.assertRaises(util.BrainError) as cm:
                    decider.prepare(b, system="darwin", machine="arm64", nvidia=False,
                                    run=lambda cmd: (0, ""))
            self.assertIn("não instala", str(cm.exception))

    def test_ensure_does_not_install_at_night(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {"decision_provider": "local", "embeddings_provider": "fireworks"})
            b.inst = config.load(b.inst.root)
            calls = []

            def run(cmd):
                calls.append(cmd)
                return 0, ""

            probes = {"docker": lambda: True, "hindsight": lambda: True,
                      "lmstudio": lambda: True, "decider": lambda: False}
            with mock.patch.dict(os.environ, {"BRAIN_NIGHTLY": "1"}):
                row = services.ensure(b.inst, reason="nightly", install=True, probes=probes, run=run,
                                      sleep=lambda _s: None, waits=1)
            self.assertEqual(row["deps"]["decider"]["state"], "failed")
            self.assertIn("não instala", row["deps"]["decider"]["detail"])
            self.assertFalse(any("pip" in " ".join(c) for c in calls))

    def test_scratch_with_real_probes_does_not_sleep(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            config.set_keys(b.inst, "memory", {"engine": "hindsight", "decision_provider": "local"})
            b.inst = config.load(b.inst.root)
            slept = []
            row = services.ensure(b.inst, reason="nightly", sleep=lambda _s: slept.append(1))
            self.assertEqual(slept, [])
            self.assertEqual(row["state"], "ready")
            self.assertIn("temporária", row["detail"])


class StackMapTests(unittest.TestCase):
    def test_required_follows_memory(self):
        self.assertEqual(services.required({"engine": "none"}), [])
        self.assertEqual(services.required({"engine": "hindsight", "embeddings_provider": "fireworks"}),
                         ["docker", "hindsight"])
        self.assertEqual(
            services.required({"engine": "hindsight", "embeddings_provider": "local", "decision_provider": "local"}),
            ["docker", "hindsight", "lmstudio", "decider"])
        # chave ausente = padrão de fábrica (local), o mesmo contrato do watchdog antigo
        self.assertIn("lmstudio", services.required({"engine": "hindsight", "extract": True}))

    def test_compose_argv_full_and_embed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            services_dir = root / "services"
            services_dir.mkdir()
            env = root / "config"
            env.mkdir()
            (env / ".env").write_text("X=1\n", encoding="utf-8")
            full = services.compose_argv(root, "full", services_dir=services_dir)
            self.assertIn("--env-file", full)
            self.assertIn(str(services_dir / "compose.full.yaml"), full)
            self.assertEqual(full[-2:], ["up", "-d"])
            embed = services.compose_argv(root, "embed", services_dir=services_dir)
            self.assertNotIn("--env-file", embed)
            self.assertNotIn(str(services_dir / "compose.full.yaml"), embed)

    def test_full_local_embeddings_does_not_recreate_while_lmstudio_is_down(self):
        msg = services.hindsight_blocked(
            {"engine": "hindsight", "extract": True, "embeddings_provider": "local"}, False)
        self.assertIn("não recrio o contêiner", msg)
        self.assertIsNone(services.hindsight_blocked(
            {"engine": "hindsight", "extract": True, "embeddings_provider": "fireworks"}, False))
        self.assertIn("modo none", services.hindsight_blocked({"engine": "none"}, True))


class KeySeparationTests(unittest.TestCase):
    def test_local_stashes_cloud_key_and_off_restores_it(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "decision", "hindsight", key="hsk-" + "cloud-demo")
            providers.set_slot(b, "decision", "local", key="bdk_" + "local-demo",
                               base_url="http://host.docker.internal:8000")
            env = config.load_env(b.inst)
            self.assertEqual(env.get("BRAIN_DECISION_LOCAL_API_KEY"), "bdk_" + "local-demo")
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_MODEL_API_KEY"), "bdk_" + "local-demo")
            self.assertEqual(env.get("HINDSIGHT_API_DECISION_CLOUD_API_KEY"), "hsk-" + "cloud-demo")
            providers.set_slot(b, "decision", "off")
            env_off = config.load_env(b.inst)
            self.assertEqual(env_off.get("HINDSIGHT_API_DECISION_MODEL_API_KEY"), "hsk-" + "cloud-demo")
            self.assertEqual(env_off.get("HINDSIGHT_API_DECISION_CLOUD_API_KEY"), "hsk-" + "cloud-demo")
            self.assertNotIn("HINDSIGHT_API_DECISION_MODEL_BASE_URL", env_off)

    def test_smoke_failure_returns_slot_to_off(self):
        with tempfile.TemporaryDirectory() as td:
            b = _brain(Path(td))
            providers.set_slot(b, "decision", "local", key="bdk_" + "local-demo",
                               base_url="http://host.docker.internal:8000")
            with mock.patch.object(decider, "prepare", side_effect=util.BrainError("fumaça falhou", code=4)):
                with self.assertRaises(util.BrainError):
                    providers.set_slot(b, "decision", "local")
            self.assertEqual(config.load(b.inst.root).cfg["memory"]["decision_provider"], "off")


class FormTests(unittest.TestCase):
    def test_local_hides_key_and_model(self):
        fm = forms.FORMS["memory.provider"]
        hidden = forms.hidden(fm, {"slot": "decision", "provider": "local", "advanced": "off"})
        self.assertIn("key", hidden)
        self.assertIn("model", hidden)
        self.assertIn("base_url", hidden)
        shown = forms.hidden(fm, {"slot": "decision", "provider": "local", "advanced": "on"})
        self.assertNotIn("base_url", shown)
        self.assertIn("key", shown)


class IdleTests(unittest.TestCase):
    def test_idle_stop_writes_flag_and_skips_when_busy(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "idle_unload", ROOT / "services" / "idle_unload.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as td:
            flag = Path(td) / "idle-stopped"
            stopped = []
            note, seen = mod.maybe_stop_decider(True, 100.0, up=lambda: True, stop=lambda: stopped.append(1),
                                                flag=flag, idle_s=15)
            self.assertEqual(note, "ocupado")
            self.assertEqual(stopped, [])
            note, seen = mod.maybe_stop_decider(False, 100.0, up=lambda: True, stop=lambda: stopped.append(1),
                                                flag=flag, last_busy=0.0, idle_s=15)
            self.assertEqual(note, "aguardando")
            self.assertEqual(stopped, [])
            note, seen = mod.maybe_stop_decider(False, 120.0, up=lambda: True, stop=lambda: stopped.append(1),
                                                flag=flag, last_busy=seen, idle_s=15)
            self.assertEqual(note, "parado")
            self.assertEqual(stopped, [1])
            self.assertTrue(flag.is_file())
