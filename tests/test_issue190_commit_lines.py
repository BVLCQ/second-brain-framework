"""#190: o diálogo lista o assunto do commit, aparado em 140 caracteres."""
import contextlib
import io
import unittest

from brainlib.upstream import _print_update, clip_subject, commit_lines


class CommitLineTests(unittest.TestCase):
    def test_curto_cabe_inteiro(self):
        self.assertEqual(clip_subject("corrige o diálogo"), "corrige o diálogo")
        self.assertEqual(len(clip_subject("a" * 40)), 40)

    def test_longo_corta_no_espaco_e_cedilha_conta_um(self):
        text = ("palavra " * 20) + "final"
        got = clip_subject(text)
        self.assertLessEqual(len(got), 141)  # 140 + reticências
        self.assertTrue(got.endswith("…"))
        self.assertNotIn("final", got)
        self.assertFalse(got[:-1].endswith(" "))
        cedilha = "ç" * 140
        self.assertEqual(clip_subject(cedilha), cedilha)
        self.assertEqual(len(clip_subject("ç" * 200)), 141)

    def test_sem_espaco_corta_no_limite(self):
        got = clip_subject("x" * 200)
        self.assertEqual(got, "x" * 140 + "…")

    def test_mais_de_vinte_nao_some_e_o_teto_diz_quantos(self):
        incoming = [f"abc{i:04d} assunto {i}" for i in range(25)]
        all_rows = commit_lines(incoming)
        self.assertEqual(len(all_rows), 25)
        self.assertTrue(all_rows[0].startswith("abc0000 "))
        capped = commit_lines(incoming, limit=20)
        self.assertEqual(capped[-1], "e mais 5")
        self.assertEqual(len(capped), 21)

    def test_paragrafo_de_changelog_nao_entra_na_linha(self):
        long = "x" * 1200
        rows = commit_lines([f"deadbee {long}"])
        self.assertEqual(len(rows), 1)
        subject = rows[0].split(" ", 1)[1]
        self.assertLessEqual(len(subject), 141)
        self.assertNotIn(long, rows[0])

    def test_terminal_limita_a_lista_e_diz_quantos_faltam(self):
        res = {"remote": "origin", "branch": "main", "behind": 30, "checked_only": True, "version_before": "1.0.0",
               "incoming": [f"abc{i:04d} assunto {i}" for i in range(30)], "areas": {"brainlib": 3}}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            _print_update(res)
        text = out.getvalue()
        self.assertIn("abc0019 assunto 19", text)
        self.assertNotIn("abc0020", text)
        self.assertIn("e mais 10", text)
