"""Instância de demonstração (dados fictícios, datas relativas a hoje) — ver o painel antes do /init."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from . import config, util
from .core import Brain

GOALS = """# PLANNING — goals, projetos, entregáveis (DEMO — dados fictícios)

## G1 — Destravar a frente de dados
- status: ativo
- horizonte: {h1}
- por quê: sem dicionário comum, toda análise nasce discutida

### P1 — Padronização de métricas
- status: ativo
- dono: voce
- [x] P1.1 Dicionário de dados v1 · prazo: {d_m2} · feito: {d_m1}
- [ ] P1.2 Pipeline de métricas no padrão X · prazo: {d_p21} · peso: 2
- [ ] P1.3 Treinamento do time de CS no dicionário · prazo: {d_p45}

### P2 — Base de contatos unificada
- status: ativo
- dono: voce
- [ ] P2.1 MVP em planilha validado com CS · prazo: {d_m3}
- [ ] P2.2 Base no BigQuery com as três fontes · prazo: {d_p30} · peso: 2

## G2 — Agente de suporte com qualidade
- status: ativo
- horizonte: {h2}
- por quê: demanda cresce sem headcount e o agente atual resolve pouco

### P3 — Diagnóstico do agente atual
- status: ativo
- dono: voce
- [ ] P3.1 Leitura de qualidade e deflexão · prazo: {d_p5} · estado: em-andamento
- [ ] P3.2 Recomendação: corrigir, congelar ou portar · prazo: {d_p20}

## G3 — Playground de IA do time
- status: ativo
- horizonte: {h2}
- por quê: automações sem dono viram risco

### P4 — Ambiente agnóstico
- status: ativo
- dono: voce
- [ ] P4.1 Inventário de automações e MCPs · prazo: {d_p10}
"""

ARTIFACTS = {
    "reuniao-1a1-ana": ("1:1 com Ana (gestora)", -6, "reuniao", ["ana", "bruno"], ["P1"],
                        "Dicionário sai como draft sem esperar o pipeline; Bruno revisa."),
    "cerimonia-migracao": ("Cerimônia do time de dados", -4, "reuniao", ["ana", "bruno", "carla"], ["P1", "P2"],
                           "Bruno vira revisor técnico; Carla entrega MVP da planilha."),
    "kickoff-agente": ("Kickoff do agente de suporte", -10, "reuniao", ["ana", "diego"], ["P3"],
                       "Congelar features novas no agente atual até o diagnóstico."),
    "status-agente-v2": ("Status report do agente (doc)", -2, "documento", ["diego"], ["P3"],
                         "Deflexão de 17,8% em julho; proposta de portar para plataforma própria."),
}

# Fontes originais (RAW) de duas entradas — o demo precisa de RAW real para o
# extrator (`brain extract --selftest`) ter o que ler.
RAW_SOURCES = {
    "reuniao-1a1-ana": """# 1:1 com Ana — notas da transcrição

Ana: o dicionário v1 não pode esperar o pipeline novo. Decide assim: sai como
draft sexta, sem bloquear ninguém. Prefiro meio dicionário em produção do que
perfeito em dezembro.

Você: então eu envio o draft pro Bruno hoje à tarde.

Ana: isso, e o Bruno entra como revisor técnico. Depois do draft aprovado, você
publica a v1 para o time — semana que vem no máximo. Ah, e separa umas 2h pra
isso, vai dar trabalho.
""",
    "kickoff-agente": """# Kickoff do agente de suporte — ata resumida

Diego: congelamos features novas no agente atual até sair o diagnóstico. Ana
concordou.

Ana: levanta as métricas de deflexão até a próxima semana. Uns 240 minutos de
trabalho deve dar.
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
        '[outbound]\nallow = ["carla", "bruno"]\n\n'
        '[publish]\ndestinations = ["slack:#time-dados"]\n\n'
        f'[[vacations]]\nstart = "{d(40)}"\nend = "{d(49)}"\n', encoding="utf-8")
    (target / "vault" / "PLANNING" / "goals.md").write_text(GOALS.format(
        h1=d(60), h2=d(120), d_m2=d(-2), d_m1=d(-1), d_p21=d(21), d_p45=d(45), d_m3=d(-3), d_p30=d(30),
        d_p5=d(5), d_p20=d(20), d_p10=d(10)), encoding="utf-8")
    (target / "vault" / "PLANNING" / "log.md").write_text(
        f"# Log de mudanças em PLANNING\n\n{d(-14)} · nascimento (demo) · aprovado: \"ok\"\n", encoding="utf-8")
    (target / "vault" / "PROFILE" / "profile.md").write_text(
        "# PROFILE (demo)\n\nAnalista de dados fictício, para demonstração do painel.\n", encoding="utf-8")

    inst = config.load(target)
    b = Brain(inst)
    if b.state.events:
        return target
    owner = {"by": "owner"}
    b.record([
        {"type": "person.added", "id": "voce", **owner, "data": {"name": "Você (demo)", "relation": "dono do cérebro"}},
        {"type": "person.added", "id": "ana", **owner, "data": {"name": "Ana Ribeiro", "aliases": ["Ana"],
                                                                 "role": "Gestora de dados", "relation": "gestora",
                                                                 "email": "ana@example.com"}},
        {"type": "person.added", "id": "bruno", **owner, "data": {"name": "Bruno Lima", "aliases": ["Bruno"],
                                                                   "role": "Engenheiro de dados", "relation": "par",
                                                                   "email": "bruno@example.com"}},
        {"type": "person.added", "id": "carla", **owner, "data": {"name": "Carla Souza", "aliases": ["Carla"],
                                                                   "role": "Analista de BI", "relation": "par",
                                                                   "email": "carla@example.com"}},
        {"type": "person.added", "id": "diego", **owner, "data": {"name": "Diego Alves", "aliases": ["Diego"],
                                                                   "role": "Tech lead do agente", "relation": "parceiro"}},
    ])
    for slug, (title, offset, kind, people, projects, summary) in ARTIFACTS.items():
        day = t + timedelta(days=offset)
        rel = f"PROCESSED/{day:%Y}/{day:%m}/{slug}.md"
        path = inst.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\ntipo: {kind} · evento: {day.isoformat()}\n\n{summary}\n", encoding="utf-8")
        raw_rel = f"RAW/{day:%Y}/{day:%m}/{slug}.md"
        raw_path = inst.vault / raw_rel
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(RAW_SOURCES.get(slug, f"# {title}\n\n{summary}\n"), encoding="utf-8")
        b.record_one({"type": "artifact.added", "id": rel, "date": day.isoformat(), "prov": "observado",
                      "source": raw_rel,
                      "data": {"kind": kind, "title": title, "raw": raw_rel,
                               "people": people, "projects": projects, "summary": summary}})
    src = {k: f"PROCESSED/{(t + timedelta(days=v[1])):%Y}/{(t + timedelta(days=v[1])):%m}/{k}.md"
           for k, v in ARTIFACTS.items()}
    agent = lambda s: {"by": "agent", "prov": "observado", "source": src[s]}  # noqa: E731
    b.record([
        {"type": "decision.made", "date": d(-10), **agent("kickoff-agente"),
         "data": {"title": "Congelar features novas no agente atual até o diagnóstico", "decided_by": ["diego"],
                  "project": "P3", "context": "kickoff do agente"}},
        {"type": "decision.made", "date": d(-10), **agent("kickoff-agente"),
         "data": {"title": "Pipeline de métricas migra para o padrão X", "decided_by": ["ana", "bruno"],
                  "project": "P1", "rationale": "padrão X já é usado pelo time de plataforma"}},
        {"type": "decision.made", "date": d(-6), **agent("reuniao-1a1-ana"),
         "data": {"title": "Dicionário v1 sai como draft, sem esperar o pipeline novo", "decided_by": ["ana"],
                  "project": "P1", "rationale": "prefiro meio dicionário em produção do que perfeito em dezembro"}},
        {"type": "decision.made", "date": d(-4), **agent("cerimonia-migracao"),
         "data": {"title": "Bruno é o revisor técnico do dicionário", "decided_by": ["ana"], "project": "P1"}},
        {"type": "decision.made", "date": d(-2), "by": "agent", "prov": "doc", "source": src["status-agente-v2"],
         "data": {"title": "Portar o agente para plataforma própria no próximo trimestre",
                  "decided_by": ["ana", "diego"], "project": "P3", "supersedes": "D-0001"}},
    ])
    b.record([
        {"type": "action.opened", "date": d(-6), **agent("reuniao-1a1-ana"),
         "data": {"title": "Enviar draft do dicionário para o Bruno", "owner": "voce", "due": d(-3),
                  "effort_min": 90, "project": "P1", "deliverable": "P1.1", "people": ["bruno"]}},
        {"type": "action.opened", "date": d(-4), **agent("cerimonia-migracao"),
         "data": {"title": "Revisar draft do dicionário", "owner": "bruno", "list": "waiting", "due": d(2),
                  "project": "P1"}},
        {"type": "action.opened", "date": d(-4), **agent("cerimonia-migracao"),
         "data": {"title": "Publicar dicionário v1 para o time", "owner": "voce", "due": d(4), "effort_min": 120,
                  "project": "P1", "blocked_by": ["A-0002"], "priority": "alta"}},
        {"type": "action.opened", "date": d(-4), **agent("cerimonia-migracao"),
         "data": {"title": "Mapear tabelas de renovação para a base de contatos", "owner": "voce", "due": d(3),
                  "effort_min": 180, "project": "P2", "people": ["carla"]}},
        {"type": "action.opened", "date": d(-4), **agent("cerimonia-migracao"),
         "data": {"title": "Entregar MVP da planilha de contatos", "owner": "carla", "list": "waiting",
                  "due": d(-3), "project": "P2", "deliverable": "P2.1"}},
        {"type": "action.opened", "date": d(-10), **agent("kickoff-agente"),
         "data": {"title": "Levantar métricas de deflexão do agente", "owner": "voce", "due": d(5),
                  "effort_min": 240, "project": "P3", "deliverable": "P3.1"}},
        {"type": "action.opened", "date": d(-3), "by": "owner",
         "data": {"title": "Ler a política de dados v3", "owner": "voce"}},
        {"type": "action.opened", "date": d(-10), **agent("kickoff-agente"),
         "data": {"title": "Migrar canal de parceiros para o agente novo", "owner": "diego", "list": "watching",
                  "project": "P3"}},
        {"type": "action.opened", "date": d(-10), **agent("kickoff-agente"),
         "data": {"title": "Entrevistar o Diego sobre o histórico do agente", "owner": "voce", "due": d(-7),
                  "effort_min": 60, "project": "P3", "people": ["diego"]}},
        {"type": "action.opened", "date": d(-1), "by": "owner",
         "data": {"title": "Preparar pauta do 1:1 com a Ana", "owner": "voce", "due": d(1), "effort_min": 30,
                  "people": ["ana"]}},
    ])
    b.record([
        {"type": "action.closed", "id": "A-0009", "date": d(-7), "by": "owner",
         "data": {"how": "entrevista feita; 3 problemas de qualidade mapeados"}},
        {"type": "action.closed", "id": "A-0001", "date": d(-2), "by": "owner",
         "data": {"how": "enviado; Bruno confirmou recebimento", "outcome": "draft em revisão técnica"}},
        {"type": "delivery.recorded", "date": d(-2), "by": "owner",
         "data": {"title": "Draft do dicionário de dados v1", "ref": "A-0001",
                  "result": "em revisão técnica com o Bruno", "evidence": "e-mail de confirmação"}},
        {"type": "delivery.recorded", "date": d(-5), "by": "agent", "prov": "observado",
         "source": src["kickoff-agente"],
         "data": {"title": "Diagnóstico inicial do agente apresentado ao time", "ref": "P3",
                  "result": "deflexão de 17,8% adotada como linha de base", "impact": "time alinhado no ponto de partida"}},
        {"type": "action.updated", "id": "A-0004", "date": d(-1), "by": "owner",
         "data": {"status": "fazendo", "note": "começou o mapeamento"}},
        {"type": "progress.declared", "id": "G1", "date": d(-1), "by": "owner",
         "data": {"pct": 45, "note": "dicionário andou; pipeline ainda não começou"}},
        {"type": "proposal.opened", "date": d(0), "by": "agent", "prov": "observado", "source": src["status-agente-v2"],
         "data": {"kind": "atualizar-acao", "target": "A-0006",
                  "summary": "O status report já traz a deflexão de julho (17,8%) — A-0006 pode ser reduzida a validar o número?",
                  "evidence": src["status-agente-v2"]}},
    ])
    from . import outbox
    outbox.draft(b, "carla", "Oi Carla! O MVP da planilha de contatos estava previsto para "
                             f"{util.fmt_date(d(-3))}. Consegue me dizer uma nova data? Ele destrava o mapeamento "
                             "de renovação do meu lado.", "A-0005", "cobrar dependência atrasada")
    return target


def cli(args) -> None:
    from . import focus, render
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
