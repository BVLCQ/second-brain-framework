"""`scripts/google_auth.py` grava o refresh token no config/.env e nunca o ecoa no terminal (#137)."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brainlib import config                                            # noqa: E402

TOKEN = "refresh-token-ficticio-so-para-teste"
CREDS = {"GOOGLE_CLIENT_ID": "cid-example", "GOOGLE_CLIENT_SECRET": "csec-example"}


def _load_script():
    spec = importlib.util.spec_from_file_location("google_auth_script", ROOT / "scripts" / "google_auth.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GoogleAuthScriptTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        (self.root / "config").mkdir()
        (self.root / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
        self.inst = config.load(self.root)
        self.env_file = self.inst.env_file
        self.script = _load_script()

    def _run(self, argv, env=None):
        out = io.StringIO()
        with mock.patch.object(config, "load", return_value=self.inst), \
                mock.patch.object(config, "load_env", return_value=CREDS if env is None else env), \
                mock.patch.object(self.script.setup, "google_refresh_token", return_value=TOKEN) as flow, \
                redirect_stdout(out):
            code = self.script.main(argv)
        return code, out.getvalue(), flow

    def test_token_is_written_to_env_and_never_echoed(self):
        code, out, _ = self._run([])
        self.assertEqual(code, 0)
        self.assertNotIn(TOKEN, out)
        self.assertIn(hashlib.sha256(TOKEN.encode()).hexdigest()[:12], out)
        self.assertIn("gravado", out)
        self.assertIn(f"GOOGLE_REFRESH_TOKEN={TOKEN}", self.env_file.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(os.stat(self.env_file).st_mode), 0o600)

    def test_existing_keys_in_env_are_preserved(self):
        self.env_file.write_text("GOOGLE_CLIENT_ID=cid-example\nOTHER=1\n", encoding="utf-8")
        self._run([])
        text = self.env_file.read_text(encoding="utf-8")
        self.assertIn("GOOGLE_CLIENT_ID=cid-example\n", text)
        self.assertIn("OTHER=1\n", text)
        self.assertEqual(text.count("GOOGLE_REFRESH_TOKEN="), 1)

    def test_print_is_an_explicit_opt_in(self):
        code, out, _ = self._run(["--print"])
        self.assertEqual(code, 0)
        self.assertIn(f"GOOGLE_REFRESH_TOKEN={TOKEN}", out)
        self.assertIn("ATENÇÃO", out)
        self.assertFalse(self.env_file.exists())

    def test_missing_credentials_exit_before_the_flow(self):
        with self.assertRaises(SystemExit) as cm, mock.patch.object(config, "load", return_value=self.inst), \
                mock.patch.object(config, "load_env", return_value={}), \
                mock.patch.object(self.script.setup, "google_refresh_token") as flow, redirect_stdout(io.StringIO()):
            self.script.main([])
        self.assertIn("GOOGLE_CLIENT_ID", str(cm.exception))
        flow.assert_not_called()

    def test_source_has_no_unconditional_print_of_the_token(self):
        src = (ROOT / "scripts" / "google_auth.py").read_text(encoding="utf-8")
        printed = [ln.strip() for ln in src.splitlines() if "print(" in ln and "{refresh}" in ln]
        self.assertEqual(len(printed), 1, printed)
        guard = next(i for i, ln in enumerate(src.splitlines()) if "if args.print:" in ln)
        line = next(i for i, ln in enumerate(src.splitlines()) if ln.strip() == printed[0])
        self.assertGreater(line, guard, "o token só pode ser impresso dentro do ramo `--print`")


class LeakScannerRuleTest(unittest.TestCase):
    """O scanner do upstream acha segredo do Google de verdade, mas não o template que imprime a variável."""

    @classmethod
    def setUpClass(cls):
        from brainlib import upstream
        cls.rule = next(rx for name, rx in upstream._SECRET_RES if name == "segredo do Google")

    def test_real_sized_credentials_are_still_flagged(self):
        for sample in ("GOOGLE_CLIENT_SECRET=" + "GOCSPX-abcdefghijklmnopqrstuvw",
                       "GOOGLE_REFRESH_TOKEN= " + "1//0g-" + "a" * 80):
            with self.subTest(sample=sample[:26]):
                self.assertIsNotNone(self.rule.search(sample))

    def test_code_templates_and_placeholders_are_not_findings(self):
        for sample in ('print(f"GOOGLE_REFRESH_TOKEN={refresh}")',
                       'self.assertIn(f"GOOGLE_REFRESH_TOKEN={TOKEN}", out)',
                       "GOOGLE_REFRESH_TOKEN=…", "GOOGLE_CLIENT_SECRET=curto"):
            with self.subTest(sample=sample):
                self.assertIsNone(self.rule.search(sample))


if __name__ == "__main__":
    unittest.main()
