"""Testes das guardas públicas de issues (#82, #83, #84, #81). stdlib unittest, sem rede."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BRAIN_NOW", "2026-10-09T10:00:00-03:00")

from brainlib import config, publicguard, util
from brainlib.core import Brain


def _brain(tmp: Path) -> Brain:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    for sub in ("PLANNING", "RAW/inbox", "PROCESSED", "FRESH"):
        (tmp / "vault" / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "brain.toml").write_text('[owner]\nid = "eu"\nname = "Dona"\n', encoding="utf-8")
    (tmp / "vault" / "PLANNING" / "goals.md").write_text("# PLANNING\n", encoding="utf-8")
    b = Brain(config.load(tmp))
    b.record_one({"type": "person.added", "id": "eu", "by": "owner", "data": {"name": "Dona", "relation": "dono"}})
    return b


class _PublicguardCase(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.inst = _brain(Path(self._td.name)).inst

    def kinds(self, text: str) -> set[str]:
        return {k for k, _ in publicguard.scan(self.inst, text)}


class TestCpfCnpjGuard(_PublicguardCase):
    def test_unpunctuated_and_mixed_cpf_cnpj_rejected(self) -> None:
        cpf_digits = "123" + "45678909"
        cnpj_digits = "11" + "222333000181"
        samples = [
            "123.456.789-09",
            cpf_digits,
            "123456789-09",
            "11.222.333/0001-81",
            cnpj_digits,
            "11222333/0001-81",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                hits = publicguard.scan(self.inst, f"doc {sample}")
                self.assertEqual(hits, [("CPF/CNPJ", 1)])
                with self.assertRaises(util.BrainError) as cm:
                    publicguard.guard(self.inst, "Erro", f"doc {sample}")
                msg = str(cm.exception)
                self.assertIn("CPF/CNPJ", msg)
                self.assertNotIn(sample, msg)
                self.assertNotIn(cpf_digits, msg)
                self.assertNotIn(cnpj_digits, msg)

    def test_invalid_check_digits_and_repeated_pass(self) -> None:
        samples = [
            "12345678900",
            "11111111111",
            "00000000000000",
            "11222333000199",
            'A Padaria Pão Quente (marina-demo) envia para contato@example.com.',
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [])


class TestCompactPhoneGuard(_PublicguardCase):
    def test_compact_phones_rejected(self) -> None:
        samples = [
            "(11) 99999-9999",
            "+5511999999999",
            "5511999999999",
            "11999999999",
            "1132345678",
            "+551132345678",
            "ligue 11999999999.",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                hits = publicguard.scan(self.inst, sample)
                self.assertEqual(hits, [("telefone", 1)])
                with self.assertRaises(util.BrainError) as cm:
                    publicguard.guard(self.inst, "Contato", sample)
                self.assertIn("telefone", str(cm.exception))
                self.assertNotIn("99999", str(cm.exception))
                self.assertNotIn("32345678", str(cm.exception))

    def test_non_phones_and_timestamps_pass(self) -> None:
        passing = [
            "11999999",
            "1700000000000",
            "1700000000123",
            "1700000000",
            "1795340000",
            "10999999999",
            "#12345",
            "v1.2.3.4",
            "11222333000181123",
            "11999999999-demo",
            "+5511999999999-demo",
        ]
        for sample in passing:
            with self.subTest(sample=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [])
        cnpj_hits = publicguard.scan(self.inst, "11222333000181")
        self.assertNotIn("telefone", {k for k, _ in cnpj_hits})
        self.assertEqual(cnpj_hits, [("CPF/CNPJ", 1)])


class TestHashAndSlackGuard(_PublicguardCase):
    def test_bare_hex_secret_and_uuid_rejected(self) -> None:
        hex32 = "a1b2c3d4" + "e5f6a1b2" + "c3d4e5f6" + "a1b2c3d4"
        hex40 = "0123456789abcdef" + "0123456789abcdef" + "01234567"
        hex64 = hex32 + hex32
        uuid_no_dash = "550e8400" + "e29b41d4" + "a7164466" + "55440000"
        samples = [
            hex32,
            hex40,
            hex64,
            f"hash {hex64}",
            f"commit {hex64}",
            uuid_no_dash,
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [("ID opaco (Drive/Slack…)", 1)])

    def test_commit_sha_with_context_allowed(self) -> None:
        sha40_a = "4b53058a" + "1b2c3d4e5f607182" + "93a4b5c6d7e8f901"
        sha40_b = "0123456789abcdef" + "0123456789abcdef" + "01234567"
        samples = [
            "regressão no commit 4b53058",
            f"commit {sha40_a}",
            f"git revert {sha40_b}",
            f"https://github.com/org/repo/commit/{sha40_b}",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [])

    def test_slack_team_and_short_mixed_ids_rejected(self) -> None:
        flagged = ["T01234567", "T01AB2C3D4E", "C0123456789", "B01234567", "E0123456789"]
        for sample in flagged:
            with self.subTest(sample=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [("ID opaco (Drive/Slack…)", 1)])

        allowed = ["bge-m3", "text-embedding-bge-m3", "PYTHON312", "SHA256SUM", "X11SERVER", "T1REPORT"]
        for sample in allowed:
            with self.subTest(sample=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [])


class TestPublicguardHygiene(_PublicguardCase):
    def test_four_part_version_not_flagged_as_ip(self) -> None:
        allowed = [
            "v2.35.1.0",
            "versão 1.2.3.4",
            "version: 10.2.3.4",
            "pkg==1.2.3.4",
            "Chrome/120.0.1.2",
            "Python/3.12.1.0",
        ]
        for sample in allowed:
            with self.subTest(sample=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [])

        for sample in ("servidor 192.168.1.42", "10.0.0.5"):
            with self.subTest(sample=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [("endereço IP", 1)])

        for sample in ("http://192.168.1.42:8080/", "https://10.0.0.5", "root@10.0.0.5"):
            with self.subTest(sample=sample):
                self.assertIn("endereço IP", self.kinds(sample))

    def test_ip_glued_to_word_or_in_url_path_is_still_flagged(self) -> None:
        """`v` colado em palavra é host (`srv10.0.0.5`); `/` só isenta produto estilo User-Agent, nunca caminho de URL."""
        for sample in ("srv10.0.0.5", "dev10.0.0.5", "http://example.com/192.168.1.42/admin",
                       "example.com/10.0.0.5", "api/v2/10.0.0.5"):
            with self.subTest(flagged=sample):
                self.assertIn("endereço IP", self.kinds(sample))

        for sample in ("v1.2.3.4", "srv v1.2.3.4", "Python-v1.2.3.4", "Chrome/120.0.0.0",
                       "Mozilla/5.0 (X11) Chrome/120.0.0.0 Safari/537.36", "pkg>=1.2.3.4"):
            with self.subTest(version=sample):
                self.assertEqual(publicguard.scan(self.inst, sample), [])

    def test_localhost_email_suffix_allowed(self) -> None:
        self.assertEqual(publicguard.scan(self.inst, "teste@app.localhost"), [])
        self.assertEqual(publicguard.scan(self.inst, "contato@dev.localhost"), [])
        self.assertEqual(publicguard.scan(self.inst, "pessoa@empresa.local"), [("e-mail", 1)])
        self.assertEqual(publicguard.scan(self.inst, "alguem@sub.empresa.local"), [("e-mail", 1)])


if __name__ == "__main__":
    unittest.main()
