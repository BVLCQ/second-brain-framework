#!/usr/bin/env python3
"""Portão de dados do repositório público — o que entra no repo passa pela varredura do brain.

O repositório é público e é a origem: cada pull request acrescenta commits a ele. O hook pre-push
já varre na máquina de quem sobe (`brain upstream scan`); o CI repete a varredura de forma
independente, antes de rodar a suíte — a mesma varredura do brain (caminho da máquina, segredo,
workspace do Slack, dado pessoal da instância) mais uma lista privada de termos (nome de empresa,
de rede interna, o que o mantenedor nunca quiser ver lá), que mora no host do runner e nunca vai ao
repo.

    public_gate.py gate --base <ref|sha> [--root <repo>] --denylist <arquivo>

Varre `<base>..HEAD` do repositório `--root` (padrão: o deste script), commit a commit. A lista
privada é um termo por linha (ou separado por vírgula). No CI o `--root` é um worktree do PR: os
scripts e a configuração da varredura vêm do checkout da main — o PR nunca diz quais são os termos.

Códigos de saída: 0 limpo · 4 achado (o valor achado nunca é ecoado: só arquivo, linha e regra) ·
1 erro — inclusive lista privada ausente ou vazia: sem ela o portão não atesta nada.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from brainlib import config, upstream, util  # noqa: E402

KIND = "lista privada"                 # nome da regra nos achados
MIN_TERM = upstream.MIN_TERM           # mesmo piso do `brain upstream scan`: evita termo curto que casa tudo
CLEAN, FOUND, ERROR = 0, 4, 1


def parse_denylist(text: str) -> list[str]:
    """Uma linha ou vírgula por termo; sem repetição, na ordem de chegada; termo curto demais não entra."""
    out: list[str] = []
    for raw in re.split(r"[\n,]+", text or ""):
        term = raw.strip()
        if len(term) >= MIN_TERM and term.casefold() not in {t.casefold() for t in out}:
            out.append(term)
    return out


def load_denylist(path: Path) -> list[str]:
    """Lê a lista privada do arquivo. Ilegível ou sem nenhum termo válido é erro: o portão não passa."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as e:
        raise RuntimeError(f"lista privada ilegível: {type(e).__name__}") from e
    terms = parse_denylist(text)
    if not terms:
        raise RuntimeError("lista privada vazia: sem termos o portão não atesta nada")
    return terms


def install_denylist(terms: list[str]):
    """Acrescenta os termos privados aos termos pessoais da instância, na varredura do brain.

    A varredura lê os termos por `_leak_terms`; sem instância configurada (o CI) sobram só as regras
    genéricas — a lista privada é o que cobre o dado de empresa nesse ponto. Devolve o original.
    """
    original = upstream._leak_terms

    def with_denylist(inst: config.Instance) -> list[tuple[str, str]]:
        return original(inst) + [(t, KIND) for t in terms]

    upstream._leak_terms = with_denylist
    return original


def scan_range(root: Path, base: str | None, trusted: Path | None = None) -> list[dict]:
    """Varre os commits de `<base>..HEAD` (ou todo o histórico, sem `base`) como o hook pre-push faria.

    A configuração — os termos da instância — vem de `trusted`, o checkout de onde este script saiu
    (padrão). `root` só diz qual repositório varrer: o PR fornece os commits, não as regras.
    """
    src = config.load(trusted or ROOT)
    inst = config.Instance(root=Path(root), vault=src.vault, config_dir=src.config_dir, cfg=src.cfg)
    revsets = [[f"{base}..HEAD"] if base else ["HEAD"]]
    return upstream.scan(inst, None, committed=True, revsets=revsets)


def main(argv: list[str] | None = None, trusted: Path | None = None) -> int:
    """`trusted` é o checkout de onde vêm a configuração da varredura (padrão: o deste script)."""
    p = argparse.ArgumentParser(description="portão de dados do repositório público")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate", help="varre <base>..HEAD; código 4 se achar algo")
    g.add_argument("--base", required=True, help="ref ou sha do último commit já público")
    g.add_argument("--root", default=str(ROOT), help="repositório a varrer (padrão: o deste script)")
    g.add_argument("--denylist", required=True, help="arquivo com a lista privada de termos (um por linha)")
    a = p.parse_args(argv)
    try:
        deny = load_denylist(Path(a.denylist))
        restore = install_denylist(deny)
        try:
            findings = scan_range(Path(a.root), a.base, trusted=trusted)
        finally:
            upstream._leak_terms = restore
        if findings:
            print(f"✗ portão de dados: {len(findings)} achado(s) em {a.base}..HEAD")
            upstream._print_findings(findings)
            return FOUND
        print(f"✓ portão de dados limpo em {a.base}..HEAD")
        return CLEAN
    except (RuntimeError, subprocess.CalledProcessError, util.BrainError) as e:
        # a mensagem destas exceções não carrega valor achado: só a classe do erro de git
        detail = e.stderr.strip()[-200:] if isinstance(e, subprocess.CalledProcessError) else str(e)
        print(f"✗ portão de dados: {detail}")
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
