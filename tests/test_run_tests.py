"""O runner paralelo da suíte (scripts/dev/run_tests.py): o CI passa a depender dele."""
import importlib.util
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "dev" / "run_tests.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_tests_under_test", RUNNER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tests_dir(td: str, bad: bool) -> Path:
    d = Path(td)
    (d / "test_good.py").write_text(textwrap.dedent("""
        import unittest
        class A(unittest.TestCase):
            def test_1(self): pass
            def test_2(self): pass
        class B(unittest.TestCase):
            def test_3(self): pass
    """), encoding="utf-8")
    if bad:
        (d / "test_bad.py").write_text(textwrap.dedent("""
            import unittest
            class C(unittest.TestCase):
                def test_quebrado(self): self.assertEqual(1, 2)
        """), encoding="utf-8")
    return d


class SplitTests(unittest.TestCase):
    def test_classe_grande_e_partida_e_nenhum_teste_se_perde(self):
        rt = _load()
        ids = [f"test_x.Big.test_{i:02d}" for i in range(23)] + ["test_x.Small.test_a", "test_x.Small.test_b"]
        with tempfile.TemporaryDirectory() as td:
            units = rt.make_units(ids, Path(td))
        flat = [i for _label, members, _w in units for i in members]
        self.assertEqual(sorted(flat), sorted(ids))                     # nada some, nada duplica
        self.assertGreater(len([u for u in units if u[0].startswith("test_x.Big[")]), 1)
        self.assertTrue(any(u[0] == "test_x.Small" for u in units))     # classe pequena fica inteira
        self.assertEqual([u[2] for u in units], sorted((u[2] for u in units), reverse=True))   # mais pesadas primeiro


class EndToEndTests(unittest.TestCase):
    def _run(self, td: Path, *extra: str):
        return subprocess.run([sys.executable, str(RUNNER), "--tests-dir", str(td), "-j", "2", *extra],
                              capture_output=True, text=True, timeout=120)

    def test_tudo_verde_sai_com_zero_e_conta_os_testes(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._run(_tests_dir(td, bad=False))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("3 testes", r.stdout)

    def test_falha_sai_com_um_e_nomeia_o_teste(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._run(_tests_dir(td, bad=True))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("test_bad.C.test_quebrado", r.stdout)
        self.assertIn("1 com falha", r.stdout)

    def test_filtro_por_prefixo_e_nenhum_teste_e_erro(self):
        with tempfile.TemporaryDirectory() as td:
            d = _tests_dir(td, bad=True)
            ok = self._run(d, "test_good")
            none = self._run(d, "test_nao_existe")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)     # o filtro deixa de fora o teste quebrado
        self.assertEqual(none.returncode, 1)                           # zero testes nunca vale como verde


if __name__ == "__main__":
    unittest.main()
