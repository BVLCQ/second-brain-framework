"""Segundo Cérebro v2 — núcleo determinístico (stdlib apenas).

O LLM extrai e julga; este pacote faz a contabilidade: IDs, validação,
livro-razão append-only, views derivadas, planejamento de foco e as portas
estreitas de saída (calendário, Slack, publicação), sempre com aprovação.
"""
import sys

if sys.version_info < (3, 11):  # tomllib, dataclass slots etc.
    raise SystemExit(
        "brain requer Python 3.11+ ( encontrado %d.%d ).\n"
        "Rode `mise install` na raiz do repo (veja mise.toml) ou instale um "
        "Python 3.11+ e chame ./brain com ele." % (sys.version_info[0], sys.version_info[1])
    )

__version__ = "2.0.0"
