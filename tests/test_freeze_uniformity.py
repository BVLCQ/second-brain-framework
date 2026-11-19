"""Relógio congelado uniforme (#63): o primeiro módulo importado no processo vence o
`os.environ.setdefault("BRAIN_NOW", …)`. Qualquer módulo que pine uma data diferente da
canônica quebra, em ordem de execução não-alfabética, fixtures de data de módulos
irmãos (agregação de custo mensal, notas com data no nome). Aqui a suíte inteira é
obrigada a congelar na MESMA data — módulo que precisar de outra data usa override
por teste (`os.environ["BRAIN_NOW"] = …` dentro do teste), que não vaza.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CANONICAL = "2026-10-09T10:00:00-03:00"   # a mesma data do test_brain (a maioria da suíte)
FREEZE_RE = re.compile(r"""os\.environ\.setdefault\(\s*['"]BRAIN_NOW['"]\s*,\s*['"]([^'"]+)['"]\s*\)""")


class FreezeUniformityTests(unittest.TestCase):
    def test_guard_detecta_valores_divergentes(self):
        """Sabotage: o scanner precisa pegar as datas que causaram o bug (#63)."""
        src = ('os.environ.setdefault("BRAIN_NOW", "2026-11-07T10:00:00-03:00")\n'
               'x = 1\n'
               "os.environ.setdefault('BRAIN_NOW', '2026-11-05T10:00:00-03:00')\n")
        achados = [m.group(1) for m in FREEZE_RE.finditer(src)]
        self.assertEqual(achados, ["2026-11-07T10:00:00-03:00", "2026-11-05T10:00:00-03:00"])

    def test_guard_ignora_override_por_teste(self):
        """Override POR TESTE (dentro de função) não vaza entre módulos — é válido."""
        src = ('def test_x(self):\n'
               '    os.environ["BRAIN_NOW"] = "2026-10-22T01:30:00+00:00"\n'
               '    with mock.patch.dict(os.environ, {"BRAIN_NOW": "2026-10-22T01:30:00+00:00"}):\n'
               '        pass\n')
        self.assertEqual([m.group(1) for m in FREEZE_RE.finditer(src)], [])

    def test_todo_freeze_de_modulo_usa_a_data_canonica(self):
        divergent: list[str] = []
        for p in sorted((ROOT / "tests").glob("*.py")):
            if p.resolve() == Path(__file__).resolve():
                continue                    # este guard carrega as datas divergentes nos próprios testes
            for m in FREEZE_RE.finditer(p.read_text(encoding="utf-8")):
                if m.group(1) != CANONICAL:
                    divergent.append(f"{p.name}: {m.group(1)}")
        self.assertEqual(
            divergent, [],
            "BRAIN_NOW divergente em nível de módulo (o primeiro import vence e quebra "
            "fixtures de data dos irmãos em ordem não-alfabética — use override POR TESTE "
            "se precisar de outra data): " + "; ".join(divergent))


if __name__ == "__main__":
    unittest.main()
