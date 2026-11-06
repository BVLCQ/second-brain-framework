"""Rubric do ICE — a fonte única do texto (CLI, TUI, painel, guia e skill).

O score continua I × C × F (1–5 por eixo, 1–125), validado e calculado pelo CLI
(`schema`/`state`). Aqui vive só a orientação: o que cada nota significa em cada
eixo, as regras de desconto e o vínculo com as medidas de sucesso. O rubric é
orientação, não validação — quem pontua é o dono (o agente só sugere).

Sem dependência de UI: só stdlib. A renderização rica (rich/Textual) fica na TUI
(`tui/rows.py`), que importa este módulo.
"""
from __future__ import annotations

import textwrap

AXES = ("impact", "confidence", "ease")

# O que o ICE deve refletir (a–d) e os princípios que atravessam os três eixos.
SUCCESS_MEASURES = [
    ("a", "horas economizadas e processos redesenhados"),
    ("b", "MVPs validados e levados à produção via engenharia"),
    ("c", "taxa de acerto e efeito em custo, receita ou eficiência"),
    ("d", "adoção por outras pessoas, sem depender do dono"),
]
PRINCIPLES = ["impacto antes de ferramenta", "humano no loop", "documentar para escalar", "segurança e dados"]

RUBRIC: dict = {
    "impact": {
        "name": "Impacto",
        "question": "Quanto isso move o ponteiro se der certo?",
        "extra_col": "Redução de horas/mês",
        "links_col": "Vínculo com o seu sucesso",
        "levels": {
            5: {
                "label": "5 · Muda resultado de goal ou várias áreas (>40h/mês)",
                "criterion": "Muda um resultado de goal ativo, ou afeta várias áreas ou muita gente",
                "anchor": "mais de 40h",
                "link": "Redesenha processo em mais de uma área ou move custo, receita ou eficiência de forma mensurável (a, c). Outras pessoas usam sem depender do dono (d).",
            },
            4: {
                "label": "4 · Ganho claro em processo crítico ou área (20–40h)",
                "criterion": "Ganho claro em um processo crítico, ou em uma área inteira",
                "anchor": "20–40h",
                "link": "Horas economizadas e processo redesenhado em uma área, com ganho em tempo ou erro manual (a).",
            },
            3: {
                "label": "3 · Melhora relevante, localizada (10–20h)",
                "criterion": "Melhora relevante, mas localizada (um time, um fluxo)",
                "anchor": "10–20h",
                "link": "Ganho real em um fluxo, que beneficia só um time (a).",
            },
            2: {
                "label": "2 · Ganho pequeno, para poucos (5–10h)",
                "criterion": "Conforto ou ganho pequeno, perceptível só para poucos",
                "anchor": "5–10h",
                "link": "Alivia uma dor individual. Não redesenha processo.",
            },
            1: {
                "label": "1 · Cosmético ou sem efeito mensurável (<5h)",
                "criterion": "Cosmético, ou sem efeito mensurável",
                "anchor": "menos de 5h",
                "link": "Sem ganho em horas, custo ou receita.",
            },
        },
        "rules": [
            "sem ganho esperado em horas, custo ou receita o impacto fica no máximo em 2",
            "as horas são declaradas pelo dono (o cérebro não estima)",
            "se escopo e horas divergem, vale a menor nota",
            "se só o dono consegue operar a solução, desconte 1 (d)",
        ],
    },
    "confidence": {
        "name": "Confiança",
        "question": "Quão sustentado está o impacto e a viabilidade?",
        "extra_col": "Proveniência",
        "links_col": "Vínculo com o sucesso (eixo dados)",
        "levels": {
            5: {
                "label": "5 · Evidência em documento/dado, ou piloto validado",
                "criterion": "Evidência em documento ou dado, ou já validado em piloto",
                "anchor": "[doc]",
                "link": "O dado existe, é confiável e tem dono. Há taxa de acerto medida em piloto (c).",
            },
            4: {
                "label": "4 · Várias fontes observadas, sem contradição",
                "criterion": "Várias fontes observadas, sem contradição",
                "anchor": "[observado] em 2 ou mais fontes",
                "link": "O dado existe e é acessível, com dono definido. A dor apareceu em mais de uma conversa.",
            },
            3: {
                "label": "3 · Uma fonte boa, ou raciocínio sólido sem dado",
                "criterion": "Uma fonte boa, ou raciocínio sólido sem dado",
                "anchor": "[observado] em 1 fonte",
                "link": "O dado existe, mas ainda não foi validado.",
            },
            2: {
                "label": "2 · Só relato ou intuição",
                "criterion": "Só relato ou intuição",
                "anchor": "[declarado] sem dado",
                "link": "O dado é frágil ou não tem dono.",
            },
            1: {
                "label": "1 · Palpite, sem base",
                "criterion": "Palpite. Não há base nenhuma",
                "anchor": "[sem-fonte]",
                "link": "O dado não existe, ou ninguém sabe onde está.",
            },
        },
        "rules": [
            "confiança mede evidência, não entusiasmo",
            "sem fonte citável, no máximo 2",
            "dado inexistente ou sem dono limita a nota a 2",
            "piloto que falhou baixa a confiança (parar uma iniciativa é resultado legítimo)",
        ],
    },
    "ease": {
        "name": "Facilidade",
        "question": "Quão barato e rápido é fazer?",
        "extra_col": "Prazo",
        "links_col": "Vínculo com o sucesso (do MVP à produção)",
        "levels": {
            5: {
                "label": "5 · Dias, sem dependência de ninguém",
                "criterion": "Dias, sem dependência de ninguém",
                "anchor": "dias",
                "link": "O dono faz sozinho, em ferramenta já aprovada, com humano no loop.",
            },
            4: {
                "label": "4 · 1–2 semanas, dependência pequena",
                "criterion": "1–2 semanas, dependência pequena",
                "anchor": "1–2 semanas",
                "link": "MVP do dono, com apoio de uma pessoa (dado ou acesso).",
            },
            3: {
                "label": "3 · ~1 mês, ou precisa de 1–2 times",
                "criterion": "Um mês, ou precisa de 1–2 times",
                "anchor": "cerca de 1 mês",
                "link": "Acordo com 1–2 times. Para produção, exige PRD simples.",
            },
            2: {
                "label": "2 · ~1 trimestre, engenharia ou aprovação externa",
                "criterion": "Um trimestre, ou depende de engenharia ou aprovação externa",
                "anchor": "cerca de 1 trimestre",
                "link": "Precisa de engenharia (PRD que atenda o DOR) ou de aprovação de segurança.",
            },
            1: {
                "label": "1 · Projeto grande, muitas dependências, risco alto",
                "criterion": "Projeto grande, com muitas dependências e risco alto",
                "anchor": "mais de 1 trimestre",
                "link": "Muitas dependências, dado sensível, ou decisão crítica que não pode ter humano no loop.",
            },
        },
        "rules": ["facilidade 5 é bom (fácil). Não confunda com esforço."],
    },
}

# Faixas de horas/mês declaradas → nota de impacto sugerida (só dica, nunca grava):
# >40 → 5 · 20–40 → 4 · 10–20 → 3 · 5–10 → 2 · <5 → 1 (piso inclusivo, como nas tabelas).
def hint_from_hours(h) -> int | None:
    if h is None:
        return None
    if h > 40:
        return 5
    if h >= 20:
        return 4
    if h >= 10:
        return 3
    if h >= 5:
        return 2
    return 1


def levels(axis: str) -> list[int]:
    """Notas do eixo em ordem 5 → 1 (a ordem das tabelas e dos dropdowns)."""
    _axis(axis)
    return sorted(RUBRIC[axis]["levels"], reverse=True)


def _axis(axis: str) -> None:
    if axis not in RUBRIC:
        raise KeyError(f"eixo desconhecido: {axis!r} (use {', '.join(AXES)})")


def options(axis: str) -> list[tuple[str, str]]:
    """[(valor, rótulo)] para os dropdowns: a opção vazia primeiro, depois 5 → 1."""
    _axis(axis)
    return [("", "— escolha —")] + [(str(n), RUBRIC[axis]["levels"][n]["label"]) for n in levels(axis)]


def describe(axis: str, n) -> str:
    """Critério completo da nota + âncora da tabela (horas, proveniência ou prazo)."""
    _axis(axis)
    lv = RUBRIC[axis]["levels"].get(int(n))
    if lv is None:
        return ""
    return lv["criterion"] + (f" · {lv['anchor']}" if lv["anchor"] else "")


def as_dict() -> dict:
    """Estrutura completa para o view model (painel HTML e MCP) — sem riqueza, só dados."""
    return {
        "success_measures": [[k, t] for k, t in SUCCESS_MEASURES],
        "principles": list(PRINCIPLES),
        "axes": {ax: {
            "name": RUBRIC[ax]["name"], "question": RUBRIC[ax]["question"],
            "extra_col": RUBRIC[ax]["extra_col"], "links_col": RUBRIC[ax]["links_col"],
            "rules": list(RUBRIC[ax]["rules"]),
            "levels": [{"n": n, "label": RUBRIC[ax]["levels"][n]["label"],
                        "criterion": RUBRIC[ax]["levels"][n]["criterion"],
                        "anchor": RUBRIC[ax]["levels"][n]["anchor"],
                        "link": RUBRIC[ax]["levels"][n]["link"]} for n in levels(ax)],
        } for ax in AXES},
    }


def as_markdown() -> str:
    """As 3 tabelas + medidas de sucesso + regras, em Markdown (guia e `--md`)."""
    out = ["ICE = impacto × confiança × facilidade · 1–5 por eixo · score 1–125 (o CLI calcula).",
           "",
           "**Medidas de sucesso que o ICE reflete:** " + " · ".join(f"({k}) {t}" for k, t in SUCCESS_MEASURES) + ".",
           "**Princípios:** " + " · ".join(PRINCIPLES) + ".",
           ""]
    for ax in AXES:
        r = RUBRIC[ax]
        out.append(f"### {r['name']} — {r['question']}")
        out.append("")
        out.append(f"| Nota | Critério | {r['extra_col']} | {r['links_col']} |")
        out.append("|---|---|---|---|")
        for n in levels(ax):
            lv = r["levels"][n]
            out.append(f"| {n} | {lv['criterion']} | {lv['anchor']} | {lv['link']} |")
        out.append("")
        out.append("Regras: " + " · ".join(r["rules"]) + ".")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def as_text(width: int = 96) -> str:
    """Versão plana para o terminal (`brain opportunity rubric` sem --md)."""
    out = [f"ICE = impacto × confiança × facilidade · 1–5 por eixo · score 1–125 (o CLI calcula)",
           "",
           "Medidas de sucesso: " + " · ".join(f"({k}) {t}" for k, t in SUCCESS_MEASURES),
           "Princípios: " + " · ".join(PRINCIPLES),
           ""]
    for ax in AXES:
        r = RUBRIC[ax]
        out.append(f"{r['name']} — {r['question']}")
        for n in levels(ax):
            lv = r["levels"][n]
            first = textwrap.fill(lv["criterion"], width - 6, subsequent_indent=" " * 6)
            out.append(f"  {n}  {first}")
            out.append(textwrap.fill(f"↳ {r['extra_col']}: {lv['anchor']} · {r['links_col']}: {lv['link']}",
                                     width - 6, subsequent_indent=" " * 6))
        for rule in r["rules"]:
            out.append(textwrap.fill(f"· {rule}", width - 4, subsequent_indent="  "))
        out.append("")
    return "\n".join(out).rstrip() + "\n"
