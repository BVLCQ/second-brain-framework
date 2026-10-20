"""Instância de demonstração — ver o painel antes do /init.

⚠ Conteúdo 100% fictício, gerado por IA apenas para demonstrar o framework. O cenário (a padaria
artesanal "Forno & Farinha" abrindo um segundo ponto) foi criado do zero, sem relação com pessoas,
empresas, projetos ou números reais. O elenco (voce, marina-demo, heitor-demo, sonia-demo, caio-demo) é o canônico do
repo: demo, fixtures de teste e exemplos de docs. Datas são offsets relativos a hoje.
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from . import config, rawsort, util
from .core import Brain

BANNER = "⚠ Instância DEMO — conteúdo 100% fictício, gerado por IA apenas para demonstrar o framework."
DISCLAIMER = ("> ⚠ **Conteúdo fictício, gerado por IA** para demonstrar o uso do framework Segundo\n"
              "> Cérebro. Pessoas, negócios, valores e eventos abaixo não existem.\n\n")

# `{-8d}` / `{+45d}` = hoje ± N dias (nunca datas literais: o demo roda em qualquer dia)
GOALS = """# PLANNING — goals, projetos, entregáveis (DEMO — dados fictícios)

## G1 — Abrir o segundo ponto da Forno & Farinha
- status: ativo
- horizonte: {+75d}
- por quê: o primeiro ponto esgotou a capacidade; o novo bairro amplia a clientela

### P1 — Reforma do novo ponto
- status: ativo
- dono: voce
- [x] P1.1 Projeto executivo aprovado · prazo: {-8d} · feito: {-8d} · peso: 2
- [-] P1.2 Alvenaria da esquina · cancelado (ponto trocado)
- [ ] P1.3 Reforma da galeria · prazo: {+45d} · peso: 4
- [ ] P1.4 Licença de funcionamento · prazo: {+65d} · peso: 2

### P2 — Cardápio do novo ponto
- status: ativo
- dono: marina-demo
- [x] P2.1 Testes de receitas · prazo: {-5d} · feito: {-5d} · peso: 2
- [ ] P2.2 Cardápio e precificação · prazo: {-1d} · peso: 3
- [-] P2.3 Fornada noturna · cancelado

## G2 — Primeiro ponto sem sustos
- status: ativo
- horizonte: {+90d}
- por quê: abrir o segundo ponto não pode degradar a operação que paga as contas

### P3 — Padronizar processos
- status: ativo
- dono: heitor-demo
- [x] P3.1 Manual de rotinas v1 · prazo: {-4d} · feito: {-4d} · peso: 2
- [ ] P3.2 Treinar a equipe no manual · prazo: {+50d} · peso: 3

## G3 — Parceria com produtores locais
- status: ativo
- horizonte: {+60d}
- por quê: insumos frescos e história pra contar no balcão

### P4 — Acordos com produtores
- status: ativo
- dono: voce
- [ ] P4.1 Contratos com 3 produtores · prazo: {+30d} · peso: 3
"""

# slug → (título, offset, tipo, pessoas, projetos, resumo)
ARTIFACTS = {
    "vistoria-imovel": ("Vistoria do imóvel da esquina", -12, "reuniao", ["voce", "marina-demo", "caio-demo"], ["P1"],
                        "Ponto novo fica na loja da esquina (aluguel 8.200); contrato passa pela Sônia-demo antes de assinar."),
    "fornos-pesquisa": ("Pesquisa: forno a lenha vs elétrico", -8, "documento", [], ["P1"],
                        "Lenha (R$ 32 mil + duto de R$ 6 mil) vs elétrico (R$ 18 mil); decisão: lenha, com o duto na reforma."),
    "1a1-marina-demo": ("1:1 com Marina-demo", -6, "reuniao", ["voce", "marina-demo"], ["P2", "P4"],
                   "Estreia do cardápio: 70% clássicas, 30% novas (8 receitas prontas); degustação com os produtores antes de contratar."),
    "reuniao-numeros": ("Reunião de números do ponto novo", -3, "reuniao", ["voce", "marina-demo", "sonia-demo"], ["P1"],
                        "Galeria vence a esquina (break-even no 9º mês, reforma de até 25 mil); ponto novo é o espaço da galeria."),
}

# Fontes originais (RAW) — o demo precisa de RAW real para o /dump e o /ask.
RAW_SOURCES = {
    "vistoria-imovel": """# Vistoria do imóvel da esquina — ata resumida

Caio-demo: a esquina tem 90 m² e pé-direito alto — dá pra tirar um mezanino pra
escrita. Mas a rede elétrica está no limite; forno a lenha resolve uma parte.

Marina-demo: eu gostei do fluxo: salão pra um lado, cozinha aberta pro outro. Se
assinarmos até o fim do mês, o proprietário fecha por 8.200.

Você: 8.200 mais condomínio… ainda assim é a melhor vitrine da rua. Decidido:
o ponto novo é a loja da esquina.

Marina-demo: fechado. Mas o contrato passa pela Sônia-demo antes de assinar.

Você: combinado. Caio-demo, eu te mando o projeto executivo ainda esta semana.

Caio-demo: manda. Se a planta passar, começo a alvenaria em duas semanas.

Marina-demo: e a confeitaria precisa de bancada fria — já bota na lista de compras.
""",
    "fornos-pesquisa": """# Pesquisa: forno a lenha vs elétrico para o novo ponto

Comparativo de 3 fornecedores orçados em outubro:

- **Lenha (R$ 32 mil instalado):** sabor assinatura da casa; exige duto de
  exaustão novo (R$ 6 mil) e manutenção mensal. Aumento médio de 12% na
  avaliação de clientes em padarias do bairro, segundo o corretor.
- **Elétrico (R$ 18 mil):** controle preciso de temperatura, sem obra de
  exaustão, energia 220 V disponível.

## Conclusão

A lenha vale pela assinatura da casa — mas só com o duto orçado dentro da
reforma. Decisão: forno a lenha no novo ponto.
""",
    "1a1-marina-demo": """# 1:1 com Marina-demo — notas da conversa

Marina-demo: o cardápio do ponto novo não pode nascer do zero. Testei as 12
receitas novas; 8 ficaram prontas pra escalar.

Você: então a estreia leva as clássicas mais as 8 aprovadas.

Marina-demo: isso — 70% clássicas, 30% novas. Não assusta o freguês no primeiro
mês, e a gente troca o mix conforme vender.

Você: fecho assim. Eu monto o cardápio com precificação até semana que vem.

Marina-demo: a Sônia-demo quer o fechamento de setembro revisado antes do dia 20.

Você: tá na fila dela na minha lista. E o Heitor-demo assume a fermentação natural
no manual?

Marina-demo: assume. Anota aí: degustação com os produtores da feira antes de
fechar qualquer contrato.
""",
    "reuniao-numeros": """# Reunião de números do ponto novo

Sônia-demo: projeção da esquina: aluguel 8.200 + reforma estimada em 60 mil. O
ponto paga a conta só no 14º mês. Apertado.

Marina-demo: e o espaço da galeria do mesmo quarteirão? Menor, mas o aluguel é
5.400 e já tem exaustão instalada — sobra o duto do forno.

Sônia-demo: na galeria o break-even cai pro 9º mês e a reforma não passa de 25
mil. Na planilha não há discussão.

Você: então a esquina morre. Trocamos: o ponto novo é o espaço da galeria.

Marina-demo: avisa o Caio-demo hoje — a alvenaria da esquina não pode nem começar.

Você: aviso. Licença a gente pede depois da reforma aprovada; contratação
temporária só depois da licença.

Sônia-demo: manda o contrato da galeria que eu reviso em 48h.
""",
}


def build(target: Path) -> Path:
    target = target.resolve()
    (target / "config").mkdir(parents=True, exist_ok=True)
    (target / "vault" / "PLANNING").mkdir(parents=True, exist_ok=True)
    for z in ("PROFILE", "RAW/inbox", "FRESH", "reports"):
        (target / "vault" / z).mkdir(parents=True, exist_ok=True)
    t = util.today()
    d = lambda n: (t + timedelta(days=n)).isoformat()  # noqa: E731
    (target / "config" / "brain.toml").write_text(
        '[owner]\nid = "voce"\nname = "Você (demo)"\n\n'
        '[outbound]\nallow = ["caio-demo", "sonia-demo"]\n\n'
        '[publish]\ndestinations = ["slack:#padaria-socios"]\n\n'
        f'[[vacations]]\nstart = "{d(40)}"\nend = "{d(49)}"\n', encoding="utf-8")
    (target / "vault" / "PLANNING" / "goals.md").write_text(
        re.sub(r"\{([+-]\d+)d\}", lambda m: d(int(m.group(1))), GOALS), encoding="utf-8")
    (target / "vault" / "PLANNING" / "log.md").write_text(
        f"# Log de mudanças em PLANNING\n\n{d(-14)} · nascimento (demo) · aprovado: \"ok\"\n", encoding="utf-8")
    (target / "vault" / "PROFILE" / "profile.md").write_text(
        "Perfil fictício gerado por IA para demonstração do framework. Nenhuma informação real.\n\n"
        "# PROFILE (demo)\n\nSócio-padeiro de uma padaria artesanal de bairro que está abrindo um segundo ponto.\n",
        encoding="utf-8")

    inst = config.load(target)
    b = Brain(inst)
    if b.state.events:
        return target
    owner = {"by": "owner"}
    b.record([
        {"type": "person.added", "id": "voce", **owner, "data": {"name": "Você (demo)", "relation": "dono do cérebro",
                                                                  "role": "Sócio-padeiro"}},
        {"type": "person.added", "id": "marina-demo", **owner, "data": {"name": "Marina-demo", "aliases": ["Marina-demo", "Mari-demo"],
                                                                    "role": "Sócia, chef de confeitaria",
                                                                    "relation": "sócia", "email": "marina-demo@example.com"}},
        {"type": "person.added", "id": "heitor-demo", **owner, "data": {"name": "Heitor-demo", "aliases": ["Heitor-demo"],
                                                                    "role": "Padeiro-chefe", "relation": "par",
                                                                    "email": "heitor-demo@example.com"}},
        {"type": "person.added", "id": "sonia-demo", **owner, "data": {"name": "Sônia-demo", "aliases": ["Sônia-demo"],
                                                                   "role": "Contadora (externa)", "relation": "fornecedora",
                                                                   "email": "sonia-demo@example.com"}},
        {"type": "person.added", "id": "caio-demo", **owner, "data": {"name": "Caio-demo", "aliases": ["Caio-demo"],
                                                                  "role": "Empreiteiro da reforma (externo)",
                                                                  "relation": "fornecedor", "email": "caio-demo@example.com"}},
    ])
    for slug, (title, offset, kind, people, projects, summary) in ARTIFACTS.items():
        day = t + timedelta(days=offset)
        rel = f"PROCESSED/{day:%Y}/{day:%m}/{slug}.md"
        path = inst.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\ntipo: {kind} · evento: {day.isoformat()}\n\n{summary}\n", encoding="utf-8")
        raw_rel = f"RAW/{day:%Y}/{day:%m}/{rawsort.KIND_FOLDER.get(kind, 'misc')}/{slug}.md"
        raw_path = inst.vault / raw_rel
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(DISCLAIMER + RAW_SOURCES[slug], encoding="utf-8")
        b.record_one({"type": "artifact.added", "id": rel, "date": day.isoformat(), "prov": "observado",
                      "source": raw_rel,
                      "data": {"kind": kind, "title": title, "raw": raw_rel,
                               "people": people, "projects": projects, "summary": summary}})
    src = {k: f"PROCESSED/{(t + timedelta(days=v[1])):%Y}/{(t + timedelta(days=v[1])):%m}/{k}.md"
           for k, v in ARTIFACTS.items()}
    agent = lambda s: {"by": "agent", "prov": "observado", "source": src[s]}  # noqa: E731
    b.record([
        {"type": "decision.made", "date": d(-12), **agent("vistoria-imovel"),
         "data": {"title": "Ponto novo fica na loja da esquina", "decided_by": ["voce", "marina-demo"], "project": "P1",
                  "context": "vistoria do imóvel"}},
        {"type": "decision.made", "date": d(-8), "by": "agent", "prov": "doc", "source": src["fornos-pesquisa"],
         "data": {"title": "Forno principal do novo ponto será a lenha", "decided_by": ["voce"], "project": "P1",
                  "rationale": "assinatura da casa; duto orçado dentro da reforma"}},
        {"type": "decision.made", "date": d(-6), **agent("1a1-marina-demo"),
         "data": {"title": "Estreia do cardápio: 70% clássicas, 30% novas", "decided_by": ["marina-demo"], "project": "P2",
                  "rationale": "não assusta o freguês no primeiro mês; o mix troca conforme vender"}},
        {"type": "decision.made", "date": d(-3), "by": "owner",
         "data": {"title": "Contratação temporária só depois da licença", "decided_by": ["voce"], "project": "P1"}},
        {"type": "decision.made", "date": d(-3), **agent("reuniao-numeros"),
         "data": {"title": "Trocar a esquina pelo espaço da galeria", "decided_by": ["voce", "marina-demo"], "project": "P1",
                  "rationale": "break-even no 9º mês (contra o 14º) e reforma de até 25 mil",
                  "supersedes": "D-0001"}},
        {"type": "decision.superseded", "id": "D-0001", "date": d(-3), **agent("reuniao-numeros"),
         "data": {"by": "D-0005", "reason": "a galeria vence a esquina na projeção de números"}},
    ])
    b.record([
        {"type": "action.opened", "date": d(-12), **agent("vistoria-imovel"),
         "data": {"title": "Enviar projeto executivo para a Marina-demo", "owner": "voce", "due": d(-9),
                  "effort_min": 90, "project": "P1", "deliverable": "P1.1", "people": ["marina-demo"]}},
        {"type": "action.opened", "date": d(-6), **agent("1a1-marina-demo"),
         "data": {"title": "Montar cardápio com precificação", "owner": "voce", "due": d(4), "effort_min": 180,
                  "project": "P2", "deliverable": "P2.2", "priority": "alta", "people": ["marina-demo"]}},
        {"type": "action.opened", "date": d(-12), **agent("vistoria-imovel"),
         "data": {"title": "Comprar bancada fria da confeitaria", "owner": "voce", "effort_min": 60}},
        {"type": "action.opened", "date": d(-6), **agent("1a1-marina-demo"),
         "data": {"title": "Agendar degustação com os produtores", "owner": "voce", "due": d(12), "effort_min": 45,
                  "project": "P4", "deliverable": "P4.1"}},
        {"type": "action.opened", "date": d(-6), **agent("1a1-marina-demo"),
         "data": {"title": "Entregar fechamento mensal revisado", "owner": "sonia-demo", "list": "waiting", "due": d(3),
                  "people": ["sonia-demo"]}},
        {"type": "action.opened", "date": d(-12), **agent("vistoria-imovel"),
         "data": {"title": "Concluir alvenaria da esquina", "owner": "caio-demo", "list": "mine", "project": "P1",
                  "people": ["caio-demo"]}},
        {"type": "action.opened", "date": d(-6), **agent("1a1-marina-demo"),
         "data": {"title": "Aprovar as 8 receitas novas para escala", "owner": "marina-demo", "list": "waiting",
                  "due": d(2), "project": "P2", "unblocks": ["A-0002"]}},
        {"type": "action.opened", "date": d(-3), **agent("reuniao-numeros"),
         "data": {"title": "Revisar orçamento da reforma da galeria", "owner": "caio-demo", "list": "waiting",
                  "due": d(-1), "project": "P1", "deliverable": "P1.3", "people": ["caio-demo"]}},
        {"type": "action.opened", "date": d(-5), "by": "owner",
         "data": {"title": "Novo regulamento de exaustão da prefeitura", "owner": "voce", "list": "watching"}},
        {"type": "action.opened", "date": d(-10), "by": "owner",
         "data": {"title": "Entrevistar Heitor-demo sobre fermentação natural", "owner": "voce", "due": d(-7),
                  "effort_min": 60, "project": "P3", "deliverable": "P3.1", "people": ["heitor-demo"]}},
        {"type": "action.updated", "id": "A-0002", "date": d(-6), "by": "owner",
         "data": {"blocked_by": ["A-0007"]}},
    ])
    b.record([
        {"type": "action.closed", "id": "A-0001", "date": d(-8), "by": "owner",
         "data": {"how": "aprovado sem ressalvas"}},
        {"type": "action.closed", "id": "A-0010", "date": d(-7), "by": "owner",
         "data": {"how": "entrevista feita", "outcome": "alimentou o manual de rotinas"}},
        {"type": "action.dropped", "id": "A-0006", "date": d(-3), "by": "owner",
         "data": {"reason": "ponto trocado para a galeria — D-0005"}},
        {"type": "action.updated", "id": "A-0002", "date": d(-1), "by": "owner",
         "data": {"status": "fazendo", "note": "começou a precificar as clássicas"}},
        {"type": "delivery.recorded", "date": d(-4), "by": "owner",
         "data": {"title": "Manual de rotinas v1 publicado", "ref": "P3.1",
                  "result": "14 páginas, 6 rotinas",
                  "impact": "treino da equipe nova sai 3 semanas mais rápido"}},
        {"type": "delivery.recorded", "date": d(-2), "by": "owner",
         "data": {"title": "Fechamento de setembro conferido",
                  "result": "conferido, 2 ajustes", "impact": "livra a abertura de multa"}},
        {"type": "progress.declared", "id": "G1", "date": d(-1), "by": "owner",
         "data": {"pct": 40, "note": "projeto aprovado; reforma da galeria nem começou"}},
        {"type": "proposal.opened", "date": d(0), "by": "agent", "prov": "observado", "source": src["reuniao-numeros"],
         "data": {"kind": "atualizar-acao", "target": "A-0003",
                  "summary": "A reunião de números fixou o ponto na galeria — a compra da bancada fria (A-0003, sem prazo) "
                             "pode ganhar prazo ligado à reforma (P1.3)?",
                  "evidence": src["reuniao-numeros"]}},
    ])
    from . import outbox
    outbox.draft(b, "caio-demo", "Oi Caio-demo! O orçamento da reforma da galeria estava previsto para "
                            f"{util.fmt_date(d(-1))}. Consegue me mandar até amanhã? Ele define o prazo da "
                            "reforma do lado de cá.", "A-0008", "cobrar orçamento atrasado")
    return target


def cli(args) -> None:
    from . import focus, render
    print(BANNER)
    target = build(Path(args.dir))
    b = Brain(config.load(target))
    if not b.state.focus_plans:
        events = [{"start": {"dateTime": (util.now().replace(hour=10, minute=0, second=0, microsecond=0)
                                          + timedelta(days=i)).isoformat()},
                   "end": {"dateTime": (util.now().replace(hour=11, minute=0, second=0, microsecond=0)
                                        + timedelta(days=i)).isoformat()}, "summary": "Reunião (demo)"}
                  for i in range(0, 7)]
        body = focus.build_plan(b, focus.parse_busy(events, b.inst.cfg))
        b.record_one({"type": "focus.planned", "by": "system", "source": "demo",
                      "data": {"plan_file": "FRESH/focus.md", **body}})
    report = render.render_all(b)
    print(f"✓ demo em {target}\n" + render.summary(report))
    if args.open:
        render.open_dashboard(b)
