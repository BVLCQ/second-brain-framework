"""O quadro de ações se chama Tarefas em toda tela do painel e do onboarding — não só no menu."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("brainlib/assets/src/core.js", "brainlib/assets/src/extra.js", "brainlib/assets/src/dashboard.css",
         "brainlib/assets/dashboard.html", "brainlib/assets/portfolio.html", "brainlib/assets/onboarding.html")
# identificadores internos (rota `#todo`, chaves de armazenamento) não são texto de tela
INTERNAL = re.compile(r"TODO_KPI_KEY|TODO_LINE")


class TarefasNamingTests(unittest.TestCase):
    def test_nenhum_rotulo_todo_nas_telas(self):
        for rel in FILES:
            text = INTERNAL.sub("", (ROOT / rel).read_text(encoding="utf-8"))
            hits = [ln.strip()[:100] for ln in text.splitlines() if re.search(r"\bTODO\b", ln)]
            self.assertEqual(hits, [], f"{rel}: rótulo 'TODO' em tela (o nome é Tarefas)")

    def test_titulo_da_pagina_e_tarefas(self):
        core = (ROOT / "brainlib/assets/src/core.js").read_text(encoding="utf-8")
        self.assertIn("<h1>Tarefas</h1>", core)
        self.assertIn("← Tarefas", core)

    def test_view_markdown_se_chama_tarefas(self):
        src = (ROOT / "brainlib/render_md.py").read_text(encoding="utf-8")
        self.assertIn('self.header("Tarefas"', src)
        self.assertIn('self.link(f, "todo.md", "Tarefas")', src)


if __name__ == "__main__":
    unittest.main()
