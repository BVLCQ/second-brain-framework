"""Testes de integridade sha256 dos instaladores remotos (#141, #142) — sem rede."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import setup, util  # noqa: E402

PINS_FILE = ROOT / "scripts" / "installer-pins.json"
INSTALL_SH = ROOT / "install.sh"

_SH_BASE_TOOLS = ("sh", "id", "mktemp", "rm", "tr", "dirname", "grep", "cat", "touch", "sed")


class _StubUI:
    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, msg: str) -> None:
        self.said.append(msg)


def _make_stub(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class PinsFileTests(unittest.TestCase):
    def test_pins_json_has_note_and_four_real_digests(self) -> None:
        data = json.loads(PINS_FILE.read_text(encoding="utf-8"))
        self.assertIsInstance(data.get("note"), str)
        self.assertTrue(data["note"].strip())

        expected_urls = {
            "homebrew": "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh",
            "mise": "https://mise.jdx.dev/install.sh",
            "docker": "https://get.docker.com",
            "lmstudio": "https://lmstudio.ai/install.sh",
        }
        pins = data.get("pins", {})
        self.assertEqual(set(pins.keys()), set(expected_urls.keys()))
        for name, url in expected_urls.items():
            entry = pins[name]
            self.assertEqual(entry["url"], url)
            digest = entry["sha256"]
            self.assertEqual(len(digest), 64, name)
            self.assertEqual(digest, digest.lower(), name)
            int(digest, 16)

        loaded = setup._load_installer_pins(PINS_FILE)
        self.assertEqual(set(loaded.keys()), set(expected_urls.keys()))


class SetupFetchVerifiedTests(unittest.TestCase):
    def test_matching_bytes_allowed(self) -> None:
        payload = b"#!/bin/sh\necho ok\n"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "inst.sh"
            err = setup._fetch_verified(
                "https://example.com/install.sh",
                dest,
                "mise",
                fetch=lambda url, d, timeout=120: (d.write_bytes(payload), None)[1],
                pins={"mise": digest},
            )
            self.assertIsNone(err)
            self.assertEqual(dest.read_bytes(), payload)

    def test_mutated_bytes_refused_with_expected_and_got(self) -> None:
        good = b"#!/bin/sh\necho ok\n"
        bad = b"#!/bin/sh\necho pwned\n"
        expected = hashlib.sha256(good).hexdigest()
        got = hashlib.sha256(bad).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "inst.sh"
            err = setup._fetch_verified(
                "https://example.com/install.sh",
                dest,
                "docker",
                fetch=lambda url, d, timeout=120: (d.write_bytes(bad), None)[1],
                pins={"docker": expected},
            )
            self.assertIsNotNone(err)
            self.assertIn(expected, err)
            self.assertIn(got, err)

    def test_missing_pin_refused_with_got(self) -> None:
        payload = b"#!/bin/sh\necho unknown\n"
        got = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "inst.sh"
            err = setup._fetch_verified(
                "https://example.com/install.sh",
                dest,
                "lmstudio",
                fetch=lambda url, d, timeout=120: (d.write_bytes(payload), None)[1],
                pins={},
            )
            self.assertIsNotNone(err)
            self.assertIn("ausente", err)
            self.assertIn(got, err)

    def test_download_error_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "inst.sh"
            err = setup._fetch_verified(
                "https://example.com/install.sh",
                dest,
                "docker",
                fetch=lambda url, d, timeout=120: "network down",
                pins={"docker": "0" * 64},
            )
            self.assertEqual(err, "network down")


class SetupEnsurePinEnforcementTests(unittest.TestCase):
    def test_docker_ensure_refuses_mutated_bytes_without_calling_run(self) -> None:
        good = b"#!/bin/sh\necho docker\n"
        bad = b"#!/bin/sh\necho mutated\n"
        expected = hashlib.sha256(good).hexdigest()
        got = hashlib.sha256(bad).hexdigest()
        calls: list[list[str]] = []
        ui = _StubUI()

        with mock.patch.object(util, "on_macos", return_value=False), \
                mock.patch.object(util, "on_linux", return_value=True), \
                mock.patch.object(setup, "docker_available", return_value=False), \
                mock.patch.object(setup, "_ORB_APP", Path("/nao/existe/OrbStack.app")), \
                mock.patch.object(setup, "_ORB_XBIN_DOCKER", Path("/nao/existe/xbin/docker")):
            ok = setup.docker_ensure(
                ui,
                run=lambda cmd, cwd=None, timeout=120: (calls.append(cmd), (0, "ok"))[1],
                which=lambda c: None,
                fetch=lambda url, d, timeout=120: (d.write_bytes(bad), None)[1],
                pins={"docker": expected},
            )

        self.assertFalse(ok)
        self.assertEqual(calls, [])
        joined = "\n".join(ui.said)
        self.assertIn(expected, joined)
        self.assertIn(got, joined)
        self.assertIn("https://get.docker.com", joined)

    def test_docker_ensure_refuses_missing_pin_without_calling_run(self) -> None:
        payload = b"#!/bin/sh\necho docker\n"
        got = hashlib.sha256(payload).hexdigest()
        calls: list[list[str]] = []
        ui = _StubUI()

        with mock.patch.object(util, "on_macos", return_value=False), \
                mock.patch.object(util, "on_linux", return_value=True), \
                mock.patch.object(setup, "docker_available", return_value=False), \
                mock.patch.object(setup, "_ORB_APP", Path("/nao/existe/OrbStack.app")), \
                mock.patch.object(setup, "_ORB_XBIN_DOCKER", Path("/nao/existe/xbin/docker")):
            ok = setup.docker_ensure(
                ui,
                run=lambda cmd, cwd=None, timeout=120: (calls.append(cmd), (0, "ok"))[1],
                which=lambda c: None,
                fetch=lambda url, d, timeout=120: (d.write_bytes(payload), None)[1],
                pins={},
            )

        self.assertFalse(ok)
        self.assertEqual(calls, [])
        joined = "\n".join(ui.said)
        self.assertIn("ausente", joined)
        self.assertIn(got, joined)
        self.assertIn("https://get.docker.com", joined)

    def test_docker_ensure_runs_temp_script_when_hash_matches(self) -> None:
        payload = b"#!/bin/sh\necho docker\n"
        digest = hashlib.sha256(payload).hexdigest()
        calls: list[list[str]] = []
        observed_script_bytes: list[bytes] = []
        ui = _StubUI()

        def fake_run(cmd, cwd=None, timeout=120):
            calls.append(cmd)
            if cmd[0] == "sh":
                observed_script_bytes.append(Path(cmd[1]).read_bytes())
            return 0, "ok"

        with mock.patch.object(util, "on_macos", return_value=False), \
                mock.patch.object(util, "on_linux", return_value=True), \
                mock.patch.object(setup, "docker_available", side_effect=lambda: len(calls) >= 2), \
                mock.patch.object(setup, "_ORB_APP", Path("/nao/existe/OrbStack.app")), \
                mock.patch.object(setup, "_ORB_XBIN_DOCKER", Path("/nao/existe/xbin/docker")):
            ok = setup.docker_ensure(
                ui,
                run=fake_run,
                which=lambda c: None,
                fetch=lambda url, d, timeout=120: (d.write_bytes(payload), None)[1],
                pins={"docker": digest},
            )

        self.assertTrue(ok, ui.said)
        self.assertEqual(calls[0][0], "sh")
        self.assertEqual(observed_script_bytes, [payload])

    def test_lmstudio_ensure_refuses_mutated_bytes_without_calling_run(self) -> None:
        good = b"#!/bin/sh\necho lms\n"
        bad = b"#!/bin/sh\necho evil\n"
        expected = hashlib.sha256(good).hexdigest()
        got = hashlib.sha256(bad).hexdigest()
        calls: list[list[str]] = []
        ui = _StubUI()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"HOME": td}), \
                mock.patch.object(util, "in_wsl", return_value=False), \
                mock.patch.object(setup, "_LMS_APP_DIRS", ()):
            ok = setup.lmstudio_ensure(
                ui,
                run=lambda cmd, cwd=None, timeout=120: (calls.append(cmd), (0, "ok"))[1],
                which=lambda c: None,
                fetch=lambda url, d, timeout=120: (d.write_bytes(bad), None)[1],
                pins={"lmstudio": expected},
            )

        self.assertFalse(ok)
        self.assertEqual(calls, [])
        joined = "\n".join(ui.said)
        self.assertIn(expected, joined)
        self.assertIn(got, joined)
        self.assertIn("https://lmstudio.ai", joined)

    def test_lmstudio_ensure_refuses_missing_pin_without_calling_run(self) -> None:
        payload = b"#!/bin/sh\necho lms\n"
        got = hashlib.sha256(payload).hexdigest()
        calls: list[list[str]] = []
        ui = _StubUI()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"HOME": td}), \
                mock.patch.object(util, "in_wsl", return_value=False), \
                mock.patch.object(setup, "_LMS_APP_DIRS", ()):
            ok = setup.lmstudio_ensure(
                ui,
                run=lambda cmd, cwd=None, timeout=120: (calls.append(cmd), (0, "ok"))[1],
                which=lambda c: None,
                fetch=lambda url, d, timeout=120: (d.write_bytes(payload), None)[1],
                pins={},
            )

        self.assertFalse(ok)
        self.assertEqual(calls, [])
        joined = "\n".join(ui.said)
        self.assertIn("ausente", joined)
        self.assertIn(got, joined)
        self.assertIn("https://lmstudio.ai", joined)

    def test_lmstudio_ensure_runs_temp_script_when_hash_matches(self) -> None:
        payload = b"#!/bin/sh\necho lms\n"
        digest = hashlib.sha256(payload).hexdigest()
        calls: list[list[str]] = []
        observed_script_bytes: list[bytes] = []
        ui = _StubUI()

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)

            def fake_run(cmd, cwd=None, timeout=120):
                calls.append(cmd)
                if cmd[0] == "bash":
                    observed_script_bytes.append(Path(cmd[1]).read_bytes())
                    b = home / ".lmstudio" / "bin"
                    b.mkdir(parents=True, exist_ok=True)
                    lms = b / "lms"
                    lms.write_text("#!/bin/sh\n", encoding="utf-8")
                    lms.chmod(0o755)
                    return 0, "installed"
                if cmd[1:2] == ["ls"]:
                    return 0, "text-embedding-bge-m3"
                return 0, "ok"

            with mock.patch.dict(os.environ, {"HOME": td}), \
                    mock.patch.object(util, "in_wsl", return_value=False), \
                    mock.patch.object(setup, "_LMS_APP_DIRS", ()), \
                    mock.patch.object(setup, "lmstudio_up", return_value=True):
                ok = setup.lmstudio_ensure(
                    ui,
                    run=fake_run,
                    which=lambda c: None,
                    fetch=lambda url, d, timeout=120: (d.write_bytes(payload), None)[1],
                    pins={"lmstudio": digest},
                )

        self.assertTrue(ok, ui.said)
        self.assertEqual(calls[0][0], "bash")
        self.assertEqual(observed_script_bytes, [payload])


class InstallShPinVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.bin_dir = self.tmp / "bin"
        self.bin_dir.mkdir()
        for tool in _SH_BASE_TOOLS:
            resolved = shutil.which(tool)
            if resolved:
                (self.bin_dir / tool).symlink_to(resolved)
        # Garante ao menos um utilitário real de sha256 no PATH isolado.
        for hasher in ("shasum", "sha256sum"):
            resolved = shutil.which(hasher)
            if resolved:
                (self.bin_dir / hasher).symlink_to(resolved)
                break
        self.home_dir = self.tmp / "home"
        self.home_dir.mkdir()
        self.tmpdir = self.tmp / "tmpdir"
        self.tmpdir.mkdir()

    def tearDown(self) -> None:
        self._tmp_ctx.cleanup()

    def _base_env(self, pins_path: Path | None = None) -> dict[str, str]:
        env = {
            "PATH": str(self.bin_dir),
            "HOME": str(self.home_dir),
            "TMPDIR": str(self.tmpdir),
            "USER": "marina-demo",
        }
        if pins_path is not None:
            env["BRAIN_INSTALLER_PINS"] = str(pins_path)
        return env

    def _setup_fake_repo(self) -> Path:
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "brainlib").mkdir()
        _make_stub(repo, "brain", "exit 0")
        _make_stub(self.bin_dir, "uname", 'echo "Linux"')
        _make_stub(self.bin_dir, "git", "exit 0")
        _make_stub(self.bin_dir, "python3", f'exec {shlex.quote(sys.executable)} "$@"')
        return repo

    def _stub_curl_payload(self, url_to_file: dict[str, Path]) -> None:
        cases = "\n".join(
            f'  {shlex.quote(u)}) cat {shlex.quote(str(p))} > "$out" ;;'
            for u, p in url_to_file.items()
        )
        _make_stub(
            self.bin_dir,
            "curl",
            'out=""\nurl=""\n'
            'while [ "$#" -gt 0 ]; do\n'
            '  case "$1" in\n'
            '    -o) out="$2"; shift 2 ;;\n'
            '    -*) shift ;;\n'
            '    *) url="$1"; shift ;;\n'
            '  esac\n'
            'done\n'
            'case "$url" in\n'
            f'{cases}\n'
            '  *) exit 1 ;;\n'
            'esac',
        )

    def test_sh_syntax_check(self) -> None:
        res = subprocess.run(["sh", "-n", str(INSTALL_SH)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_install_sh_refuses_mutated_bytes_for_mise_and_docker(self) -> None:
        repo = self._setup_fake_repo()
        good_mise = b"#!/bin/sh\ntouch " + str(self.tmp / "mise_ran").encode() + b"\n"
        bad_mise = b"#!/bin/sh\ntouch " + str(self.tmp / "mise_pwned").encode() + b"\n"
        good_docker = b"#!/bin/sh\ntouch " + str(self.tmp / "docker_ran").encode() + b"\n"
        bad_docker = b"#!/bin/sh\ntouch " + str(self.tmp / "docker_pwned").encode() + b"\n"

        bad_mise_file = self.tmp / "bad_mise.sh"
        bad_mise_file.write_bytes(bad_mise)
        bad_docker_file = self.tmp / "bad_docker.sh"
        bad_docker_file.write_bytes(bad_docker)

        pins_file = self.tmp / "pins.json"
        pins_file.write_text(
            json.dumps({
                "note": "fixture",
                "pins": {
                    "mise": {"url": "https://mise.jdx.dev/install.sh",
                             "sha256": hashlib.sha256(good_mise).hexdigest()},
                    "docker": {"url": "https://get.docker.com",
                               "sha256": hashlib.sha256(good_docker).hexdigest()},
                },
            }),
            encoding="utf-8",
        )
        self._stub_curl_payload({
            "https://mise.jdx.dev/install.sh": bad_mise_file,
            "https://get.docker.com": bad_docker_file,
        })

        res = subprocess.run(
            ["sh", str(INSTALL_SH)],
            cwd=repo,
            env=self._base_env(pins_file),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"stdout={res.stdout}\nstderr={res.stderr}")
        self.assertFalse((self.tmp / "mise_pwned").exists())
        self.assertFalse((self.tmp / "docker_pwned").exists())
        self.assertIn(hashlib.sha256(good_mise).hexdigest(), res.stdout)
        self.assertIn(hashlib.sha256(bad_mise).hexdigest(), res.stdout)
        self.assertIn(hashlib.sha256(good_docker).hexdigest(), res.stdout)
        self.assertIn(hashlib.sha256(bad_docker).hexdigest(), res.stdout)
        self.assertIn("⚠ mise não instalado", res.stdout)
        self.assertIn("⚠ Docker não instalado", res.stdout)

    def test_install_sh_refuses_missing_pin(self) -> None:
        repo = self._setup_fake_repo()
        payload = self.tmp / "payload.sh"
        payload.write_bytes(b"#!/bin/sh\ntouch " + str(self.tmp / "should_not_run").encode() + b"\n")
        pins_file = self.tmp / "empty-pins.json"
        pins_file.write_text('{"note":"fixture","pins":{}}', encoding="utf-8")

        self._stub_curl_payload({
            "https://mise.jdx.dev/install.sh": payload,
            "https://get.docker.com": payload,
        })

        res = subprocess.run(
            ["sh", str(INSTALL_SH)],
            cwd=repo,
            env=self._base_env(pins_file),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"stdout={res.stdout}\nstderr={res.stderr}")
        self.assertFalse((self.tmp / "should_not_run").exists())
        self.assertIn("pin sha256 ausente para 'mise'", res.stdout)
        self.assertIn("pin sha256 ausente para 'docker'", res.stdout)
        self.assertIn(hashlib.sha256(payload.read_bytes()).hexdigest(), res.stdout)

    def test_install_sh_allows_matching_bytes(self) -> None:
        repo = self._setup_fake_repo()
        mise_marker = self.tmp / "mise_ok"
        docker_marker = self.tmp / "docker_ok"
        mise_bytes = f"#!/bin/sh\ntouch {shlex.quote(str(mise_marker))}\n".encode()
        docker_bytes = f"#!/bin/sh\ntouch {shlex.quote(str(docker_marker))}\n".encode()

        mise_file = self.tmp / "good_mise.sh"
        mise_file.write_bytes(mise_bytes)
        docker_file = self.tmp / "good_docker.sh"
        docker_file.write_bytes(docker_bytes)

        pins_file = self.tmp / "pins.json"
        pins_file.write_text(
            json.dumps({
                "note": "fixture",
                "pins": {
                    "mise": {"url": "https://mise.jdx.dev/install.sh",
                             "sha256": hashlib.sha256(mise_bytes).hexdigest()},
                    "docker": {"url": "https://get.docker.com",
                               "sha256": hashlib.sha256(docker_bytes).hexdigest()},
                },
            }),
            encoding="utf-8",
        )
        self._stub_curl_payload({
            "https://mise.jdx.dev/install.sh": mise_file,
            "https://get.docker.com": docker_file,
        })

        res = subprocess.run(
            ["sh", str(INSTALL_SH)],
            cwd=repo,
            env=self._base_env(pins_file),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"stdout={res.stdout}\nstderr={res.stderr}")
        self.assertTrue(mise_marker.exists())
        self.assertTrue(docker_marker.exists())

    def test_posix_pin_helper_checks_homebrew_fixture(self) -> None:
        # Extrai e testa verify_installer_pin de install.sh contra um fixture de homebrew
        # (no macOS real, /opt/homebrew/bin/brew já existe, então ensure_brew sai antes do curl).
        src = INSTALL_SH.read_text(encoding="utf-8")
        start = src.index("ok() {")
        end = src.index("is_same_repo() {")
        snippet = src[start:end]

        good_bytes = b"#!/bin/bash\necho brew-ok\n"
        bad_bytes = b"#!/bin/bash\necho brew-bad\n"
        good_file = self.tmp / "good_brew.sh"
        good_file.write_bytes(good_bytes)
        bad_file = self.tmp / "bad_brew.sh"
        bad_file.write_bytes(bad_bytes)

        pins_file = self.tmp / "pins.json"
        pins_file.write_text(
            json.dumps({
                "note": "fixture",
                "pins": {
                    "homebrew": {"url": "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh",
                                 "sha256": hashlib.sha256(good_bytes).hexdigest()},
                },
            }),
            encoding="utf-8",
        )

        env = self._base_env(pins_file)
        ok_res = subprocess.run(
            ["sh", "-c", f'SCRIPT_DIR="{self.tmp}"\n{snippet}\nverify_installer_pin homebrew "$1"', "_", str(good_file)],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(ok_res.returncode, 0, ok_res.stdout + ok_res.stderr)

        bad_res = subprocess.run(
            ["sh", "-c", f'SCRIPT_DIR="{self.tmp}"\n{snippet}\nverify_installer_pin homebrew "$1"', "_", str(bad_file)],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(bad_res.returncode, 0)
        self.assertIn(hashlib.sha256(good_bytes).hexdigest(), bad_res.stdout)
        self.assertIn(hashlib.sha256(bad_bytes).hexdigest(), bad_res.stdout)

        miss_res = subprocess.run(
            ["sh", "-c", f'SCRIPT_DIR="{self.tmp}"\n{snippet}\nverify_installer_pin other "$1"', "_", str(good_file)],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(miss_res.returncode, 0)
        self.assertIn("ausente", miss_res.stdout)


if __name__ == "__main__":
    unittest.main()
