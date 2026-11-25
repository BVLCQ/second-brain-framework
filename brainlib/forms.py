"""Formulários do dono — fonte ÚNICA da TUI e do painel HTML.

Cada formulário que uma das duas interfaces mostra mora AQUI, declarado como dado: título, texto de apoio,
campos (id, rótulo, exemplo, obrigatório, lista de escolha, quando aparece, validação, dica), o valor que cada
campo traz ao editar e como os valores viram a linha `brain …`. As duas pontas só desenham:

- a TUI monta os `Field` do Textual a partir daqui (`tui/app.py::open_form`) e roda `build()`;
- o painel recebe `export()` no view model (`m["forms"]`) e o `forms.js` desenha e monta o comando com a
  MESMA regra (`formArgv`, `CHECKS`, `HINTS`, `XF`, `INIT`, `SOURCES`, `PRED` — os nomes são os daqui).

Nada de campo escrito à mão numa ponta só: `tests/test_forms.py` recusa `Field(`/`fields: [` fora deste arquivo
(salvo a lista justificada) e compara, pelo node, o comando que o Python e o JS montam para os mesmos valores.
Regra de ouro: o que transforma valor (data natural, JQL do Jira, entregável por número) tem implementação nas
duas pontas com o mesmo nome — ou mora na CLI. Validação que precisa do ledger inteiro (alias de pessoa,
similaridade) pode ser só do Python: fica em `PY_ONLY`, com o porquê, e a CLI valida de novo ao gravar.

Stdlib apenas: a TUI (Textual) importa daqui, nunca o contrário.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass, replace
from datetime import date

from . import dates, ids, schema, util
from . import providers as _providers

# LLM por assinatura não tem chave de API: o campo some (autenticação é `brain memory auth`).
_LLM_SUBSCRIPTIONS = tuple(p for p, v in _providers.PROVIDERS["llm"].items()
                           if v.get("family") == "subscription")

ELLIPSIS = "…"                       # obrigatório vazio no preview (o formulário não deixa confirmar assim)
NONE = "—"                           # opção "sem valor" das listas


# ── declaração ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class F:
    id: str
    label: str
    ph: str = ""
    req: bool | str = False              # True · "@chave" (obrigatório quando o ctx diz)
    multi: bool = False                  # caixa de texto grande
    secret: bool = False                 # digita escondido (chave de API)
    choices: tuple | str | None = None   # ((valor, rótulo), …) ou "@fonte" (SOURCES)
    depends: str | None = None           # a fonte é recalculada quando este campo muda
    show: dict | str | None = None       # {"campo": [v…]} · {"campo!": [v…]} · {"@ctx": [v…]} · "predicado" (PRED)
    check: str | None = None             # "nome" ou "nome:arg" (CHECKS) — só roda com valor
    hint: str | None = None              # texto de apoio ao lado do campo (HINTS) — só com valor
    suggest: str | None = None           # "@fonte": texto livre com sugestões (datalist / Suggester)
    value: str = ""                      # valor inicial fixo
    init: str | None = None              # valor inicial de ctx: "chave[:fmt]" do item, ou "@chave" do ctx (INIT)
    base: str | None = None              # edição: com o que comparar para saber se mudou (padrão: init)
    fill: tuple | None = None            # (campo, regra): preenche sozinho quando aquele campo muda (FILL)
    # → linha da CLI
    arg: str | None = None               # "--due"
    many: bool = False                   # "a, b" → --arg a --arg b
    set: str | None = None               # --set <set>=valor · "*" = pares "k=v; k=v"
    flag: dict | None = None             # valor → tokens (ex.: {"sim": ["--force"]})
    skip: tuple = ()                     # valores que não viram nada (padrão do CLI)
    xf: str | None = None                # transforma o valor antes da CLI (XF)
    clear: tuple | None = None           # edição: esvaziou → estes tokens (sem isso, esvaziar não manda nada)
    always: bool = False                 # edição: vai mesmo sem mudar (nota, alias novo)
    auto: str | None = None              # "surface": preenchido pela superfície ("tui"/"painel") ao confirmar; sem input


@dataclass(frozen=True)
class Form:
    id: str
    title: str                           # "{chave}" vem do ctx
    cmd: tuple                           # "{campo}" posicional · "{?campo}" some se vazio · "{*campo}" um por item · "{@ctx}"
    fields: tuple = ()
    sub: str = ""
    gate: bool = False                   # aprovação literal (borda âmbar)
    edit: bool = False                   # só o que mudou vai para a CLI
    tail: tuple = ()                     # tokens fixos no fim (ex.: --by owner)
    order: tuple = ()                    # ordem dos argumentos (padrão: a dos campos)
    more: tuple = ()                     # ((predicado, template), …): comandos que vêm depois do principal
    help: str | None = None              # "ice": ? abre a metodologia
    where: str = "both"                  # both · tui · panel
    why: str = ""                        # por que não está nas duas


# ── peças repetidas ─────────────────────────────────────────────────────────
OWNER = ("--by", "owner")
QUOTE = F("quote", "sua aprovação", req=True, ph="digite a resposta literal, ex.: ok", arg="--quote",
          always=True, auto="surface")
APPROVAL = F("quote", "sua aprovação", req=True, ph="digite a resposta literal, ex.: ok", arg="--approval",
             always=True, auto="surface")


def _reason(ph: str = "", req: bool = True) -> F:
    return F("reason", "motivo", req=req, ph=ph or ("opcional" if not req else ""), arg="--reason")


def _goal_project(project_arg: bool = True) -> tuple:
    """Goal antes de projeto: o goal só filtra a lista de projetos (nenhuma CLI o recebe)."""
    return (F("goal", "goal", choices="@goal_filter", init=":goal_of", value=NONE),
            F("project", "projeto", choices="@projects_of_goal", depends="goal", init="project", value=NONE,
              arg="--project" if project_arg else None, skip=(NONE, "")))


LISTS = (("mine", "mine — eu devo"), ("waiting", "waiting — outra pessoa me deve"), ("watching", "watching — só contexto"))
PRIORITY = (("normal", "normal"), ("alta", "alta"), ("baixa", "baixa"))
RELATIONS = (("par", "par"), ("gestor", "gestor"), ("stakeholder", "stakeholder"), ("time", "time"))
YESNO = (("não", "não"), ("sim", "sim"))
OPP_STATUS = ("ideia", "triagem", "priorizada", "em-andamento", "piloto", "validando", "entregue", "em-espera", "descartada")
OPP_LATERAL = ("em-espera", "descartada")


def _source_fields(edit: bool) -> tuple:
    """Fonte do watch.toml: só aparece o que o `kind` usa. Drive aceita a URL; Jira monta a JQL pelo escopo."""
    from . import watch
    s = lambda key: ({"set": key, "clear": ("--unset", key)} if edit else {"set": key})  # noqa: E731
    no_window = sorted(watch.NO_WINDOW)
    return (
        F("key", "key", req=True, ph="slack-time-dados", check="watch_key", init="key",
          **({"arg": "--rename"} if edit else {})),
        F("note", "nota", ph="para que serve esta fonte", init="note", arg="--note",
          **({"clear": ("--unset", "note")} if edit else {})),
        F("kind", "tipo", choices="@source_kinds", value="gmail", init="kind", **({"arg": "--kind"} if edit else {})),
        F("channel", "canal", req=True, ph="#time-dados ou @pessoa", show={"kind": ["slack"]}, init="channel", **s("channel")),
        F("user", "só de quem", ph="@pessoa (opcional)", show={"kind": ["slack"]}, init="user", **s("user")),
        F("exclude", "ignorar (DMs)", ph="U12345, @fulano (opcional)", show={"kind": ["slack-dm"]}, init="exclude:csv",
          **s("exclude")),
        F("query", "filtro", ph="from:alguem label:x (opcional; busca do Gmail)", show={"kind": ["gmail"]}, init="query",
          **s("query")),
        F("folder", "pasta (URL)", req=True, ph="https://drive.google.com/drive/folders/…", show={"kind": ["drive"]},
          check="drive", hint="drive", init="folder", **s("folder")),
        F("doc", "doc (URL)", req=True, ph="URL do Doc, Planilha ou Slides", show={"kind": [watch.DRIVE_DOC]},
          check="drive", hint="drive", init="doc", **s("doc")),
        F("jscope", "o quê", choices=tuple(watch.JIRA_SCOPES), show={"kind": ["jira"]}, init="jql:jscope", base="jql",
          xf="jql", **s("jql")),
        F("jref", "chave / URL", req=True, ph="OPS-123 · OPS · URL do épico, board ou filtro · JQL",
          show={"kind": ["jira"], "jscope!": ["mine"]}, init="jql", base="jql", check="jira", hint="jira"),
        F("mode", "leitura", choices=(("", "só o que mudou (janela)"), ("state", "estado completo (o que está aberto)")),
          show={"kind": ["jira"]}, init="mode", flag={"state": ["--set", "mode=state"]},
          **({"clear": ("--unset", "mode")} if edit else {})),
        F("cloud", "site", ph="<site>.atlassian.net (vem da URL, se colar uma)", show={"kind": ["jira"]},
          init="cloud:cloud0", base="cloud", xf="jira_cloud", **s("cloud")),
        F("path", "pasta local", req=True, ph="~/Github/", show={"kind": ["github"]}, init="path", **s("path")),
        F("window", "janela", ph="auto · 1d · 7d", show={"kind!": no_window, "mode!": ["state"]}, init="window",
          arg="--window", **({"clear": ("--unset", "window")} if edit else {})),
        *((F("enabled", "ativa", choices=(("true", "sim — puxar normalmente"), ("false", "não — desligada")),
             value="true", init="enabled:bool", set="enabled"),) if edit else ()),
        F("other", "outros", ph="campo=valor; campo=valor", check="pairs", init=":source_other", set="*"),
    )


_SRC_ORDER = ("key", "kind", "window", "note", "channel", "user", "query", "folder", "doc", "path", "jscope", "cloud",
              "mode", "exclude", "enabled", "other")


def _proc_fields() -> tuple:
    return (
        F("title", "título", req=True, ph="Fechamento mensal", init="title", arg="--title"),
        F("area", "área", choices="@areas", init="area", arg="--area"),
        F("owner", "responsável", ph="id ou alias da pessoa (1)", suggest="@people", check="people", init="owner",
          arg="--owner"),
        F("executors", "executores", ph="ids ou aliases, vírgula", suggest="@people", check="people",
          init="executors:csv", arg="--executor"),
        F("recurrence", "recorrência", choices="@recurrence", value=NONE, init="recurrence", arg="--recurrence",
          skip=(NONE,)),
        F("per_month", "execuções/mês", ph="só sob-demanda / por-evento", check="num", init="per_month:num",
          arg="--per-month", xf="num"),
        F("duration", "duração", ph="por execução: 45m · 1h30m", check="duration_pos", init="duration_min:dur",
          arg="--duration"),
        F("tools", "ferramentas", ph="Sheets, Jira", init="tools:csv", arg="--tools"),
        F("io", "entradas → saídas", ph="planilha de vendas → relatório fechado", init="io", arg="--io"),
        F("pain", "dor", ph="uma dor a adicionar (opcional)", arg="--pain", always=True),
        F("maturity", "maturidade", ph="1–5", check="int:1:5", init="maturity", arg="--maturity"),
        F("note", "nota", ph="opcional", arg="--note", always=True),
    )


def _opp_fields() -> tuple:
    return (
        F("title", "título", req=True, ph="Automatizar a conciliação", init="title", arg="--title"),
        F("area", "área", choices="@areas", init="area", arg="--area"),
        F("process", "processo", ph="PROC-#### (opcional)", suggest="@processes", check="proc", init="process",
          arg="--process"),
        F("kind", "tipo", choices="@opp_kinds", value="melhoria-de-processo", init="kind", arg="--kind"),
        F("problem", "problema", ph="o que dói hoje", init="problem", arg="--problem"),
        F("suggestion", "sugestão", ph="como resolver", init="suggestion", arg="--suggestion"),
        F("gain", "ganho esperado", ph="texto livre", init="gain", arg="--gain"),
        F("hours", "horas/mês poupadas", ph="declarado por você (opcional)", check="num", init="hours_saved:num",
          arg="--hours-saved", xf="num"),
        F("goal", "goal", ph="GOAL-# (opcional)", suggest="@goals", check="goal", init="goal", arg="--goal"),
        F("people", "pessoas", ph="ids ou aliases, vírgula (opcional)", suggest="@people", check="people",
          arg="--person", always=True),
    )


def _forms() -> list[Form]:
    from . import watch
    due = lambda **kw: F("due", "prazo", **{"ph": dates.HELP, "check": "date", "hint": "date", "xf": "date", "arg": "--due", **kw})  # noqa: E731
    out = [
        # ── PLANNING ──────────────────────────────────────────────────────────
        Form("goal.new", "Novo goal {nid}", ("plan", "add-goal", "{title}"), (
            F("title", "título", req=True, ph="Marketing com IA onde faz sentido"),
            F("horizon", "horizonte", ph=dates.HELP, check="date", hint="date", xf="date", arg="--horizon"),
            F("why", "por quê", ph="o que isto destrava", arg="--why"),
            _reason("opcional: por que agora", req=False), APPROVAL),
            sub="Criar goal é mudança estrutural: único gate do sistema. Nasce em PLANNING/goals.md, com linha em "
                "PLANNING/log.md e no ledger.", gate=True, order=("why", "reason", "horizon", "quote")),
        Form("project.new", "Novo projeto {nid} em {goal}", ("plan", "add-project", "{goal}", "{title}"), (
            F("title", "título", req=True, ph="Padronização de métricas"),
            F("owner", "dono", ph="id ou alias da pessoa (opcional)", suggest="@people", arg="--owner"),
            _reason("opcional: por que agora", req=False), APPROVAL),
            sub="{goal} · {goal_title}. Criar projeto é mudança estrutural: confirmar aprova a alteração.", gate=True),
        Form("deliverable.new", "Novo entregável {nid} em {project}", ("plan", "add-deliverable", "{project}", "{title}"), (
            F("title", "título", req=True, ph="Manual de rotinas v1", check="no_dot"),
            due(),
            F("weight", "peso", value="1", ph="1 · 2 · 3…", check="int:1:", arg="--weight", skip=("", "1"))),
            sub="{project} · {project_title}. Entregável não é goal nem projeto: entra no goals.md sem gate "
                "(o título não pode ter “·”)."),
        Form("goal.edit", "Editar {id}", ("plan", "edit", "{id}"), (
            F("title", "título", req=True, init="title", arg="--title"),
            F("status", "status", choices="@node_status", init="status", arg="--status"),
            F("horizon", "horizonte", ph="vazio remove · " + dates.HELP, check="date", hint="date", xf="date",
              init="horizon", arg="--horizon", clear=("--horizon", "")),
            F("why", "por quê", ph="vazio remove", init="why", arg="--why", clear=("--why", "")),
            _reason("opcional: por que mudar", req=False), APPROVAL),
            sub="Editar goal é mudança estrutural: confirmar aprova a alteração.", gate=True, edit=True),
        Form("project.edit", "Editar {id}", ("plan", "edit", "{id}"), (
            F("title", "título", req=True, init="title", arg="--title"),
            F("status", "status", choices="@node_status", init="status", arg="--status"),
            F("owner", "dono", ph="id ou alias da pessoa · vazio remove", suggest="@people", init="owner",
              arg="--owner", clear=("--owner", "")),
            _reason("opcional: por que mudar", req=False), APPROVAL),
            sub="Editar projeto é mudança estrutural: confirmar aprova a alteração.", gate=True, edit=True),
        Form("deliverable.edit", "Editar {id}", ("plan", "edit", "{id}"), (
            F("title", "título", req=True, check="no_dot", init="title", arg="--title"),
            due(ph="vazio remove · " + dates.HELP, init="due", clear=("--due", "")),
            F("weight", "peso", ph="1 · 2 · 3…", check="int:1:", init="weight", arg="--weight")),
            sub="Entregável não é goal nem projeto: a edição entra no goals.md sem gate (o estado — feito, em "
                "andamento — segue em espaço/s).", edit=True),
        Form("plan.log", "Mudança na árvore do plano", ("plan", "log"), (
            F("diff", "resumo do diff", req=True, ph="PROJ-5 nasce sob GOAL-2", arg="--diff", init="@diff"),
            F("reason", "motivo", req=True, ph="nova frente de retenção MX", arg="--reason", init="@reason"),
            F("ev", "evidência", ph="reunião de planejamento", arg="--evidence", init="@ev"), APPROVAL),
            sub="Único gate estrutural: criar, renomear ou fechar goal e projeto exige a sua aprovação. "
                "Cancelar desfaz a edição do goals.md (e o registro que falhar também).", gate=True,
            where="tui", why="nasce da edição do goals.md no $EDITOR (a TUI mostra o diff); o painel edita a árvore "
                             "pelos formulários de goal/projeto/entregável"),
        Form("deliverable.done", "Marcar {id} como feito", ("plan", "deliverable", "{id}", "--status", "feito"), (
            F("ev", "evidência", ph="subiu em produção", arg="--evidence"),), sub="{title}", tail=OWNER),
        Form("deliverable.state", "Estado de {id}", ("plan", "deliverable", "{id}", "--status", "{st}"), (
            F("st", "estado", choices=(("nao-iniciado", "não iniciado"), ("em-andamento", "em andamento"),
                                       ("feito", "feito"), ("cancelado", "cancelado")), init="status"),
            F("ev", "evidência", ph="opcional", arg="--evidence")), sub="{title}", tail=OWNER),
        Form("progress.declare", "Declarar progresso de {id}", ("progress", "{id}", "{pct}"), (
            F("pct", "percentual", req=True, ph="0 a 100", check="int:0:100"),
            F("note", "nota", ph="cardápio andou; reforma não", arg="--note")),
            sub="Aparece ao lado do calculado; nunca o substitui."),
        Form("share.export", "Exportar para um colega", ("share", "{kind}", "{?target}"), (
            F("kind", "tipo", choices=(("project", "projeto"), ("goal", "goal"), ("status", "status"),
                                       ("period", "período")), init="@kind", value="status"),
            F("target", "alvo", ph="PROJ-1 · GOAL-1 · 2026-09-01:2026-09-30", suggest="@plan_nodes",
              show={"kind!": ["status"]}, init="@target"),
            F("fmt", "formato", choices=(("html", "html"), ("md", "md")), value="html", arg="--format")),
            sub="Gera um documento autocontido, sem jargão interno, em vault/reports/share/."),

        # ── ações ────────────────────────────────────────────────────────────
        Form("action.new", "Nova ação{in_deliv}", ("action", "open", "{title}"), (
            F("title", "título", req=True, ph="o que precisa acontecer", hint="dup_action"),
            due(),
            F("effort", "esforço", ph="90m · 2h · 1h30 · 1d", check="duration", arg="--effort"),
            *_goal_project(),
            F("prio", "prioridade", choices=PRIORITY, value="normal", arg="--priority", skip=("normal",)),
            F("list", "lista", choices=LISTS, init="@list", value="mine", arg="--list", skip=("mine",)),
            F("owner", "dono", ph="eu (ou id/alias da pessoa)", suggest="@people", init="@owner", value="eu",
              fill=("list", "owner_for_list"), arg="--owner"),
            F("deliv", "entregável", ph="9 (do projeto escolhido) ou PROJ-#.# · opcional", init="@deliv",
              check="deliv", hint="deliv", xf="deliv", arg="--deliverable"),
            F("people", "pessoas", ph="marina-demo, heitor-demo (opcional)", suggest="@people", arg="--people"),
            F("blocked", "bloqueada por", ph="TASK-#### (opcional)", suggest="@actions", xf="nospace", arg="--blocked-by"),
            F("unblocks", "destrava", ph="TASK-#### (opcional)", suggest="@actions", xf="nospace", arg="--unblocks"),
            F("link", "link", ph="URL ou arquivo de origem (opcional)", arg="--link")),
            sub="Equivalente ao /todo. Sem prazo, o agente oferece uma sugestão (roxa).",
            tail=("--by", "owner"),
            order=("list", "owner", "due", "effort", "project", "prio", "deliv", "people", "blocked", "unblocks", "link")),
        Form("action.edit", "Editar {id}", ("action", "update", "{id}"), (
            F("title", "título", req=True, init="title", arg="--title"),
            due(ph="vazio remove o prazo", init="due", clear=("--clear-due",)),
            F("effort", "esforço", ph="90m · 2h · 1h30 · 1d", check="duration", init="effort_min:dur", arg="--effort"),
            F("prio", "prioridade", choices=PRIORITY, init="priority:prio", arg="--priority"),
            *_goal_project(),
            F("deliv", "entregável", ph="só o número, no projeto escolhido (9 → PROJ-1.9), ou PROJ-#.#",
              init=":deliv_short", base="deliverable", check="deliv", hint="deliv", xf="deliv", arg="--deliverable"),
            F("blocked", "bloqueada por", ph="TASK-#### (a CLI não remove bloqueio)", suggest="@actions",
              init="blocked_by_all:csvc", xf="nospace", arg="--blocked-by"),
            F("people", "pessoas", ph="adiciona: marina-demo, heitor-demo", suggest="@people", xf="new_people",
              arg="--people", always=True),
            F("list", "lista", choices=LISTS, init="list", arg="--list"),
            F("owner", "dono", ph="reatribui: eu, id ou alias", suggest="@people", init=":owner_shown",
              base=":owner_base", fill=("list", "owner_for_list"), xf="lower_eu", arg="--owner"),
            F("note", "nota", ph="vai para o histórico da ação", arg="--note", always=True)),
            sub="{title}", edit=True, tail=OWNER),
        Form("action.close", "Fechar {id}", ("action", "close", "{id}", "--how", "{how}"), (
            F("how", "como foi", req=True, ph="enviei o draft, Heitor-demo confirmou"),
            F("outcome", "resultado", ph="opcional: resultado observável (vira entrega WIN-####)", arg="--outcome")),
            sub="{title}", tail=OWNER),
        Form("action.due", "Prazo de {id}", ("action", "update", "{id}"), (
            due(init="due", clear=("--clear-due",), always=True),), sub="{due_sub}", edit=True, tail=OWNER),
        Form("action.drop", "Descartar {id}", ("action", "drop", "{id}", "--reason", "{reason}"), (
            F("reason", "motivo", req=True, ph="projeto cancelado"),),
            sub="Não foi feita e não será. O histórico fica no ledger.", tail=OWNER),
        Form("action.merge", "Mesclar {id}", ("action", "merge", "{id}", "--into", "{into}", "--by", "owner"), (
            F("into", "mesclar em (TASK)", req=True, ph="TASK-####", suggest="@actions", check="merge_into"),
            _reason(req=False)),
            sub="“{title}” é duplicada: o que ela tem (pessoas, link, prazo, bloqueios) passa para a que fica."),
        Form("action.reopen", "Reabrir {id}", ("action", "reopen", "{id}", "--reason", "{reason}"), (
            F("reason", "motivo", req=True, ph="faltou a parte do México"),), sub="{title}", tail=OWNER),

        # ── notas ────────────────────────────────────────────────────────────
        Form("note.add", "Nova nota", ("note", "add"), (
            F("text", "nota", req=True, multi=True, ph="escreva à vontade: ideias, contexto, o que ouviu…", init="@text",
              arg="--text"),
            F("link", "vínculo", ph="TASK-#### · GOAL-# · PROJ-# · PROJ-#.# (opcional)", suggest="@link_targets",
              init="@link", check="note_link", hint="note_link", xf="note_link", arg="--link")),
            sub="Cai na inbox como arquivo .md (nome: vínculo-data-note). O /dump arquiva no RAW; até lá e depois, a nota "
                "aparece no detalhe do vínculo, abaixo do histórico.", order=("link", "text"),
            more=()),
        Form("note.edit", "Editar {name}", ("note", "edit", "{path}", "--text", "{text}"), (
            F("text", "nota", req=True, multi=True, init="@text"),),
            sub="Reescreve o arquivo na inbox (criada {created}); vínculo e hora de criação ficam. Depois do /dump a nota "
                "vira RAW e não se edita mais.",
            where="tui", why="editar a nota de hoje pede o arquivo da inbox aberto; o painel cria notas e as mostra"),

        # ── propostas e perguntas ────────────────────────────────────────────
        Form("proposal.accept", "Aceitar {id}", ("proposal", "accept", "{id}", "--quote", "{quote}"), (
            F("quote", "sua resposta", req=True, ph="ok, pode fechar", auto="surface"),
            F("how", "como foi", req=True, init="@summary", show={"@kind": ["fechar-acao"]}),
            F("effort", "novo esforço", req=True, ph="90m · 2h · 1h30", check="duration", show={"@kind": ["reestimar"]})),
            sub="{summary}", gate=True,
            more=(("prop_close", ("action", "close", "{@target}", "--how", "{how}", "--by", "owner")),
                  ("prop_effort", ("action", "update", "{@target}", "--effort", "{effort}", "--by", "owner")),
                  ("prop_merge", ("action", "merge", "{@target}", "--into", "{@into}", "--by", "owner")),
                  ("prop_drop", ("action", "drop", "{@target}", "--reason", "duplicada de {@into}",
                                 "--duplicate-of", "{@into}", "--by", "owner")))),
        Form("proposal.reject", "Rejeitar {id}", ("proposal", "reject", "{id}", "--quote", "{quote}"), (
            F("quote", "sua resposta", req=True, ph="não, ainda falta o México", auto="surface"),), sub="{summary}"),
        Form("ask.answer", "Responder {id}", ("ask", "answer", "{id}", "{answer}", "--by", "owner"), (
            F("answer", "resposta", req=True, ph="texto livre", suggest="@ask_options"),), sub="{text}"),
        Form("ask.drop", "Descartar {id}", ("ask", "drop", "{id}", "--reason", "{reason}"), (
            F("reason", "motivo", req=True, ph="já resolvi / não importa"),), sub="{text}", tail=OWNER),
        Form("agent.arg", "{name}", (), (
            F("arg", "{arg_label}", ph="{arg_ph}", req="@arg_req"),), sub="{desc}",
            where="tui", why="argumento de um comando ⚡ do agente (/gmail, /slack…); o painel dispara as ações ⚡ direto pela ponte, sem formulário intermediário"),
        Form("ask.free", "Resposta livre ao agente", ("note", "add", "--text", "{text}"), (
            F("text", "resposta", req=True, multi=True, ph="o que o agente deve saber ou fazer"),), sub="{sub}",
            where="tui", why="retoma a sessão do agente (claude --resume); o painel não roda o agente"),

        # ── mensagens (porta 2) ──────────────────────────────────────────────
        Form("outbox.draft", "Rascunhar mensagem", ("outbox", "draft", "--to", "{to}", "--text", "{text}"), (
            F("to", "para", req=True, ph="id da pessoa ou #canal", suggest="@recipients", init="@to", check="recipient"),
            F("text", "texto", req=True, ph="Oi …", init="@text"),
            F("ref", "ref", ph="TASK-####", suggest="@actions", init="@ref", arg="--ref"),
            F("why", "por quê", init="@why", arg="--why"),
            F("channel", "canal", choices=(("slack", "slack"), ("email", "email")), value="slack", arg="--channel",
              skip=("slack",))),
            sub="Nada sai sem a sua aprovação do texto exato (porta 2). O agente envia depois, como você; o texto "
                "aprovado fica travado por hash."),
        Form("outbox.approve", "Aprovar {id} → {to_name}", ("outbox", "approve", "{id}", "--quote", "{quote}"), (
            F("quote", "sua aprovação", req=True, ph="enviar {n}", auto="surface"),),
            sub="Você aprova este texto exato. Se mudar uma palavra, a aprovação cai.", gate=True),
        Form("outbox.cancel", "Cancelar {id}", ("outbox", "cancel", "{id}"), (_reason(req=False),), sub="{text}"),

        # ── foco (porta 1) ───────────────────────────────────────────────────
        Form("focus.plan", "Planejar foco", ("focus", "plan", "--days", "{days}"), (
            F("days", "horizonte (dias)", req=True, init="@days", check="int:1:30"),),
            sub="Blocos EDF nas suas ações mine com prazo. Nada vai ao calendário ainda."),
        Form("focus.approve", "Aprovar plano {id}", ("focus", "approve", "{id}", "--quote", "{quote}"), (
            F("quote", "sua aprovação", req=True, ph="ok", auto="surface"),),
            sub="Um ok libera o lote inteiro. Só depois dele o aplicar vira possível.", gate=True),
        Form("focus.apply", "Aplicar {id}", ("focus", "apply", "{id}", "--mode", "{mode}"), (
            F("mode", "modo", choices=(("ics", "ics — arquivo local"), ("google", "google — Calendar")), init="@mode"),),
            sub="google cria só eventos marcados brain_focus=1 no calendário primário. ics gera um arquivo e não toca na "
                "API.", gate=True),
        Form("focus.sync", "Sincronizar o foco", ("focus", "sync"), (
            F("mode", "o que fazer", choices=(("dry", "só mostrar (dry-run)"), ("apply", "remover agora")), value="dry",
              flag={"dry": ["--dry-run"]}),),
            sub="Blocos futuros de ações já fechadas: no modo google saem do calendário; no ics, o arquivo avisa."),

        # ── publicação (porta 3) ─────────────────────────────────────────────
        Form("publish.request", "Pedir publicação", ("publish", "request", "{report}", "--to", "{to}"), (
            F("report", "report", req=True, ph="reports/share/… (gere com Exportar)", suggest="@reports", init="@report"),
            F("to", "destino", req=True, choices="@destinations")),
            sub="Uma aprovação por publicação. O conteúdo fica travado por hash."),
        Form("publish.approve", "Aprovar {id}", ("publish", "approve", "{id}", "--quote", "{quote}"), (
            F("quote", "sua aprovação", req=True, ph="ok, publica", auto="surface"),),
            sub="Publicar {report} em {destination}", gate=True),

        # ── registro: decisões, entregas, pessoas ────────────────────────────
        Form("decision.new", "Registrar decisão", ("decision", "add", "{title}"), (
            F("title", "título", req=True, ph="o que passa a valer"),
            F("by", "quem decidiu", req=True, ph="marina-demo, sonia-demo", suggest="@people", arg="--decided-by",
              many=True),
            *_goal_project(),
            F("context", "contexto", ph="com base em quê (opcional)", arg="--context"),
            F("why", "porquê", ph="opcional", arg="--rationale")),
            tail=OWNER, order=("by", "project", "context", "why")),
        Form("decision.supersede", "Superar {id}", ("decision", "supersede", "{id}", "--reason", "{reason}"), (
            F("reason", "motivo", req=True, ph="mudou o cenário"),
            F("by_decision", "substituída por", ph="DEC-#### (opcional: a decisão nova, registre antes com n)",
              suggest="@decisions", arg="--by-decision")),
            sub="{title} — decisões são imutáveis: a superada fica no histórico.", tail=OWNER),
        Form("delivery.new", "Registrar entrega", ("delivery", "{title}"), (
            F("title", "título", req=True, ph="o que saiu"),
            F("ref", "ligada a", ph="PROJ-2 · TASK-#### · GOAL-1", suggest="@plan_nodes", arg="--ref"),
            F("result", "resultado", arg="--result"),
            F("impact", "impacto", arg="--impact"),
            F("evidence", "evidência", ph="caminho do artefato/RAW (opcional)", arg="--evidence")),
            sub="Conquista com resultado, sem precisar fechar uma ação.", tail=OWNER),
        Form("person.new", "Nova pessoa", ("person", "add", "{name}"), (
            F("name", "nome", req=True, ph="Nome Sobrenome"),
            F("id", "id curto", ph="derivado do nome", arg="--id"),
            F("alias", "aliases", ph="Lu, Lu M.", arg="--alias", many=True),
            F("role", "papel", arg="--role"),
            F("rel", "relação", choices=RELATIONS, value="par", arg="--relation"),
            F("email", "e-mail", arg="--email")),
            tail=OWNER, order=("id", "alias", "role", "rel", "email")),
        Form("person.edit", "Editar {id}", ("person", "update", "{id}"), (
            F("name", "nome", req=True, init="name", arg="--name"),
            F("role", "papel", init="role", arg="--role"),
            F("rel", "relação", init="relation", suggest="@relations", arg="--relation"),
            F("email", "e-mail", init="email", arg="--email")),
            sub="Para aliases novos use a. A CLI não apaga campos, só os troca.", edit=True, tail=OWNER),
        Form("person.alias", "Alias para {id}", ("person", "alias", "{id}", "{*al}"), (
            F("al", "aliases", req=True, ph="Mari-demo, M.-demo"),), sub="Evita uma segunda ficha para a mesma pessoa.",
            tail=OWNER),
        Form("person.resolve", "Quem é…?", ("person", "resolve", "{text}"), (
            F("text", "nome ou alias", req=True, ph="a Marina-demo"),),
            sub="Diz a quem o texto se refere, sem gravar nada. Ambíguo vira erro: a pergunta é sua."),
        Form("memory.ask", "Memória: perguntar", ("memory", "{mode}", "{q}", "--bank", "{bank}"), (
            F("q", "pergunta", req=True, ph="o que foi decidido sobre o forno?"),
            F("mode", "como", choices=(("recall", "recall — trechos"), ("reflect", "reflect — resposta sintetizada"))),
            F("bank", "banco", choices=(("mem", "mem"), ("raw", "raw"))),
            F("tags", "tags", ph="proj:PROJ-1,pessoa:marina-demo (opcional)", arg="--tags")),
            sub="recall devolve trechos; reflect pede uma resposta sintetizada. Confirme no arquivo do vault antes de "
                "afirmar.", where="tui", why="o painel não fala com o servidor da memória; a busca dele é o índice"),
        Form("feedback.new", "Sugestão ou bug", ("feedback", "add", "{title}", "--kind", "{kind}"), (
            F("kind", "tipo", choices=(("sugestao", "💡 sugestão"), ("bug", "🐞 bug")), value="sugestao"),
            F("title", "título", req=True, ph="curto e claro", check="fb_dup"),
            F("body", "descrição", multi=True, ph="o que, onde, como reproduzir", arg="--body"),
            F("pub", "publicar", choices=(("agora", "agora — cria a issue já"), ("depois", "depois — só registra (--no-push)")),
              value="agora", flag={"depois": ["--no-push"]}),
            F("force", "criar mesmo assim", choices=(("nao", "não"), ("sim", "sim (--force)")), value="nao",
              show="fb_dup", flag={"sim": ["--force"]}),
            replace(APPROVAL, show={"pub": ["agora"]})),
            sub="porta 7 — vira issue pública no repo do framework; sem dados pessoais (a porta recusa)",
            gate=True, tail=OWNER),
        Form("feedback.withdraw", "Retirar {id}", ("feedback", "withdraw", "{id}"), (
            _reason(ph="duplicado, não faz mais sentido…", req=True),),
            sub="{title} — rascunho ainda não publicado; fica no ledger como retirado.", tail=OWNER),
        Form("feedback.retract", "Retratar {id}", ("feedback", "retract", "{id}"), (
            F("mode", "como retratar", choices=(("withdraw", "retirar — fecha a issue como não planejada"),
                                                ("correct", "corrigir — atualiza o texto da issue (gate)")),
              value="withdraw", flag={"withdraw": ["--withdraw"], "correct": ["--correct"]}),
            _reason(ph="motivo que vai para o comentário público da issue", req=True),
            F("body", "novo corpo", multi=True, req=True, ph="descrição corrigida (sem dados pessoais)",
              show={"mode": ["correct"]}, init="body", arg="--body"),
            replace(APPROVAL, show={"mode": ["correct"]})),
            sub="porta 7 — {title}. Comentário e texto vão para a issue pública no GitHub (sem dados pessoais).",
            gate=True, tail=OWNER),

        # ── portfólio ────────────────────────────────────────────────────────
        Form("process.new", "Novo processo", ("process", "add", "{title}", "--by", "owner"), _proc_fields(),
             sub="Horas/mês = execuções/mês × duração × nº de executores; quem calcula é o CLI."),
        Form("process.edit", "Editar {id}", ("process", "update", "{id}", "--by", "owner"), _proc_fields(),
             sub="Só o que mudou vai para a CLI. Executores e ferramentas substituem a lista; dor e nota são "
                 "acrescentadas.", edit=True),
        Form("process.retire", "Aposentar {id}", ("process", "retire", "{id}", "--reason", "{reason}"), (
            F("reason", "motivo", req=True, ph="deixou de existir"),), sub="{title}", tail=OWNER),
        Form("opportunity.new", "Nova oportunidade", ("opportunity", "add", "{title}", "--by", "owner"), _opp_fields(),
             sub="Nasce em 'ideia'. O detector de duplicatas olha título e problema antes de gravar."),
        Form("opportunity.edit", "Editar {id}", ("opportunity", "update", "{id}", "--by", "owner"), _opp_fields(),
             sub="Só o que mudou vai para a CLI. Status, ICE e promoção têm teclas próprias (s, i, p).", edit=True),
        Form("opportunity.status", "Status de {id}", ("opportunity", "status", "{id}", "{status}"), (
            F("status", "estágio", choices="@opp_status", init="status", check="opp_status"),
            F("reason", "motivo", req=True, ph="por que fica assim", show={"status": list(OPP_LATERAL)},
              arg="--reason")),
            sub="{title} · em-espera e descartada pedem motivo; em-andamento só nasce da promoção (p).", tail=OWNER),
        Form("opportunity.score", "ICE de {id}", ("opportunity", "score", "{id}", "--impact", "{impact}",
                                                  "--confidence", "{confidence}", "--ease", "{ease}"), (
            F("impact", "@ice:impact", req=True, choices="@ice:impact", init="impact", hint="ice_impact"),
            F("confidence", "@ice:confidence", req=True, choices="@ice:confidence", init="confidence", hint="ice:confidence"),
            F("ease", "@ice:ease", req=True, choices="@ice:ease", init="ease", hint="ice:ease")),
            sub="Score = impacto × confiança × facilidade (1–125). O CLI calcula e mostra o resultado.{ice_reason}",
            tail=OWNER, help="ice"),
        Form("opportunity.evidence", "Evidência de {id}", ("opportunity", "evidence", "{id}", "--source", "{source}"), (
            F("source", "fonte", req=True, ph="PROCESSED/2026/10/reuniao.md", suggest="@artifacts"),),
            sub="Artefato ou RAW que reforça esta oportunidade.", tail=OWNER),
        Form("opportunity.promote", "Promover {id}", ("opportunity", "promote", "{id}", "--level", "{level}"), (
            F("level", "nível", choices=(("project", "projeto — num goal"), ("deliverable", "entregável — num projeto"),
                                         ("goal", "goal novo")), value="project", hint="promote_diff"),
            F("goal", "goal alvo", choices="@goals_active", show={"level": ["project"]}, arg="--goal"),
            F("project", "projeto alvo", choices="@projects_active", show={"level": ["deliverable"]}, arg="--project"),
            F("title", "título do nó", req=True, init="title", base="title", arg="--title"),
            _reason(req=False), APPROVAL),
            sub="Criar nó do PLANNING (goal, projeto ou entregável) é mudança estrutural: único gate do sistema. Nasce em "
                "PLANNING/goals.md, com linha em PLANNING/log.md e no ledger; a oportunidade vira em-andamento.",
            gate=True),
        Form("area.new", "Nova área", ("area", "add", "{slug}", "--by", "owner"), (
            F("slug", "id", req=True, ph="operacoes", check="slug"),
            F("name", "nome", ph="Operações", arg="--name"),
            F("alias", "aliases", ph="Ops, Operacoes (vírgula)", arg="--alias"),
            F("note", "nota", arg="--note")), sub="Áreas são do ledger: cadastre quantas quiser."),
        Form("area.edit", "Editar a área {id}", ("area", "update", "{id}", "--by", "owner"), (
            F("name", "nome", req=True, init="name", arg="--name"),
            F("alias", "novo alias", ph="vírgula", arg="--alias", always=True),
            F("note", "nota", init="note", arg="--note")), sub="Aliases novos são acrescentados.", edit=True),
        Form("doc.link", "Ligar documento a {target}", ("doc", "link", "{target}", "--kind", "{kind}", "--ref", "{ref}",
                                                        "--by", "owner"), (
            F("target", "ligar a", req=True, suggest="@doc_targets", init="@target", show="no_target_ctx"),
            F("kind", "tipo", choices="@doc_kinds", value="playbook"),
            F("ref", "ref", req=True, ph="URL, id do Drive ou caminho do vault"),
            F("title", "título", ph="opcional", arg="--title"),
            F("watch", "vigiar", choices=YESNO, value="não", check="doc_watch", flag={"sim": ["--watch"]})),
            sub="Playbook vigiado do Drive: o /update só relê quando o modifiedTime muda."),
        Form("doc.unlink", "Desligar o documento de {target}", ("doc", "unlink", "{target}", "--ref", "{ref}",
                                                                "--by", "owner"),
             sub="{doc_title} — o documento continua onde está; só a ligação sai."),

        # ── fontes (watch.toml) ──────────────────────────────────────────────
        Form("watch.add", "Adicionar fonte ao watch.toml", ("watch", "add", "{key}", "--kind", "{kind}"),
             _source_fields(edit=False),
             sub="Fonte que não está no watch.toml não é puxada pelo /update nem pelo noturno. Os campos mudam com o tipo.",
             order=_SRC_ORDER),
        Form("watch.edit", "Editar a fonte {key0}", ("watch", "edit", "{key0}"), _source_fields(edit=True),
             sub="Mudar a key renomeia a fonte; o histórico de pulls fica na key antiga.", edit=True, order=_SRC_ORDER),
        Form("watch.remove", "Remover a fonte {key}", ("watch", "remove", "{key}"),
             sub="O /update e o noturno deixam de puxá-la. Snapshots já gravados e o ledger ficam como estão."),

        # ── configurações ────────────────────────────────────────────────────
        Form("memory.mode", "Memória: modo e provedores", ("memory", "setup", "--mode", "{mode}"), (
            F("mode", "modo", choices=(("none", "nenhuma — busca por palavra"),
                                       ("embed", "embed — semântica; local ou nuvem"),
                                       ("full", "full — fatos; LLM de nuvem")), value="embed", init="mode"),
            F("provider", "LLM", choices="@memory_llm", init="provider",
              show={"mode": ["full"]}, arg="--provider"),
            F("model", "modelo do LLM", ph="gpt-… (exigido no OpenAI)",
              show={"mode": ["full"], "provider": ["openai"]}, arg="--model"),
            F("embeddings", "embeddings", choices="@memory_embs", depends="mode", init="embeddings",
              show={"mode": ["embed", "full"]}, arg="--embeddings"),
            F("reranker", "reranker", choices="@memory_reranker", init="reranker",
              show={"mode": ["embed", "full"]}, arg="--reranker"),
            F("key", "API key (LLM)", secret=True, ph="vazio = mantém a do .env",
              show={"mode": ["full"]}, arg="--key"),
            F("emb_key", "API key (embeddings)", secret=True, ph="vazio = mantém a do .env",
              show={"mode": ["embed", "full"]}, arg="--emb-key"),
            F("reranker_key", "API key (reranker)", secret=True,
              ph="vazio = mantém (fireworks nos embeddings e no reranker usam a mesma conta)",
              show={"mode": ["embed", "full"], "reranker!": ["", "off"]}, arg="--reranker-key"),
            F("quote", "sua aprovação", req=True, ph="digite a resposta literal, ex.: ok",
              show={"mode": ["full"]}, arg="--approval")),
            sub="Embeddings local (bge-m3 no LM Studio) ou de nuvem, nos dois modos; o LLM do full é sempre de "
                "nuvem (o texto do vault vai a ele). No full, o recomendado dos embeddings é o de nuvem. As chaves "
                "vão ao config/.env (nunca voltam em output) e o container é recriado pelo fluxo. No painel: "
                "Configurações › Memória.",
            edit=True, gate=True, where="tui",
            why="o painel tem o passo Memória dedicado (Configurações), com o mesmo resultado"),
        Form("memory.provider", "Provedor da memória", ("memory", "providers", "set", "{slot}", "--provider", "{provider}"), (
            F("slot", "slot", choices=(("llm", "LLM — só vale no modo full"), ("embeddings", "embeddings"),
                                       ("reranker", "reranker"),
                                       ("decision", "decisão — opcional (só full): juiz rápido que corta ~40% das chamadas")),
              value="embeddings"),
            F("provider", "provedor", choices="@providers", depends="slot", init="@provider"),
            F("model", "modelo", ph="vazio = recomendado do provedor", hint="provider_model",
              show="need_model", arg="--model"),
            F("advanced", "avançado",
              choices=(("off", "não — o Brain instala e preenche"), ("on", "sim — informar a URL")),
              value="off", show={"slot": ["decision"], "provider": ["local"]}),
            F("base_url", "base URL", ph="custom / openai-wire / local /v1/systemone", show="need_base_url", arg="--base-url"),
            F("key", "API key", ph="vazio = mantém a do config/.env", secret=True,
              show="need_provider_key", arg="--key"),
            F("models", "modelos por operação", ph="retain=…,consolidation=… (vazio = recomendados)",
              show={"slot": ["llm"]}, arg="--models"),
            F("recall", "usar no recall",
              choices=(("off", "off — só consolidação/reflect (padrão)"),
                       ("on", "on — julga cada candidato no recall (exige top-N; sem fallback)")),
              value="off", init="@recall", show={"slot": ["decision"], "provider": ["hindsight"]},
              check="recall_candidates", hint="recall_note", arg="--recall"),
            F("candidates", "top-N candidatos", ph="exigido com recall on; vazio = default do reranker",
              show="show_candidates", check="int:1:500", arg="--candidates")),
            sub="A escolha vai ao config/.env (chave nunca volta em output) e ao [memory]. Provedor de LLM por "
                "assinatura (claude-code, xai-oauth…) não tem chave de API: autentique com `brain memory auth "
                "<provedor>`. Trocou embeddings? vetores "
                "antigos ficam incompatíveis — brain memory rebuild. Depois recrie o container (modo full inclui o "
                "override): docker compose -f services/compose.yaml -f services/compose.full.yaml "
                "--env-file config/.env up -d — no embed, sem o segundo -f. No full, trocar embeddings (local ↔ nuvem) "
                "exige o rebuild e repaga a extração; o LLM é sempre de nuvem (embeddings local e decisor local "
                "/v1/systemone não mandam texto para fora)."),
    ]
    del watch
    return out


FORMS: dict[str, Form] = {f.id: f for f in _forms()}


# ── fontes de listas (do view model: as mesmas chaves que o painel lê em M) ──
def _short(t: str, n: int = 46) -> str:
    return t if len(t) <= n else t[: n - 1] + "…"


def _active(x: dict) -> bool:
    return x.get("status") in ("ativo", "ativa")


def _src_goal_filter(m, v, ctx):
    keep = _goal_of((ctx or {}).get("item") or {"project": (ctx or {}).get("project")}, ctx, m)
    return [(NONE, "— (todos os goals)")] + [(g["id"], f"{g['id']} · {_short(g['title'])}")
                                            for g in m.get("goals", []) if _active(g) or g["id"] == keep]


def _src_projects_of_goal(m, v, ctx):
    g = (v or {}).get("goal") or NONE
    keep = (ctx.get("item") or {}).get("project") or ctx.get("project") or ""
    keep_goal = next((p["goal"] for p in m.get("projects", []) if p["id"] == keep), NONE)
    keep = keep if g in (NONE, keep_goal) else ""
    return [(NONE, NONE)] + [(p["id"], f"{p['id']} · {_short(p['title'])}") for p in m.get("projects", [])
                             if (_active(p) and (g == NONE or p["goal"] == g)) or p["id"] == keep]


def _ice(axis):
    def src(m, v, ctx):
        r = ((m.get("portfolio") or {}).get("ice_rubric") or {}).get("axes", {}).get(axis)
        return [("", "— escolha —")] + [(str(lv["n"]), lv["label"]) for lv in (r or {}).get("levels", [])]
    return src


def _src_source_kinds(m, v, ctx):
    kinds = [tuple(k) for k in m.get("source_kinds", [])]
    cur = ((ctx or {}).get("item") or {}).get("kind")
    return kinds + ([(cur, cur)] if cur and cur not in {k for k, _ in kinds} else [])


def _src_opp_status(m, v, ctx):
    it = (ctx or {}).get("item") or {}
    out = []
    for s in OPP_STATUS:
        note = (" ← atual" if s == it.get("status") else " (pede motivo)" if s in OPP_LATERAL
                else " (só promovendo: p)" if s == "em-andamento" and not (it.get("promoted") or it.get("project")) else "")
        out.append((s, s + note))
    return out


def memory_provider_options(slot: str, mode: str = "embed") -> list[tuple[str, str]]:
    """Cardápio de provedores de um slot derivado do registro providers.PROVIDERS — o mesmo que o
    `brain memory setup` aceita (cli._flat_memory_providers; um teste cruza os dois). Sem `custom`
    (exige model + base_url) e sem `cursor` (indisponível no Docker); guiados e chave de API vêm
    primeiro, manual por último."""
    return [(pid, info.get("label") or pid)
            for pid, info in _providers.menu_providers(slot, include_custom=False, include_unavailable=False, mode=mode)]


def _with_current(opts: list[tuple[str, str]], cur: str) -> list[tuple[str, str]]:
    if cur and all(k != cur for k, _ in opts):
        return [(cur, f"{cur} (atual)"), *opts]
    return list(opts)


def _src_providers(m, v, ctx):
    slot = (v or {}).get("slot") or "embeddings"
    return [tuple(x) for x in (m.get("form_static") or {}).get("providers", {}).get(slot, [])]


def _src_memory_llm(m, v, ctx):
    opts = memory_provider_options("llm", (v or {}).get("mode") or "embed")
    return _with_current(opts, ((ctx or {}).get("item") or {}).get("provider", ""))


def _src_memory_embs(m, v, ctx):
    """Cardápio de embeddings pelo modo — modo fora da tabela (ex.: none) cai no cardápio do embed.
    Fonte dinâmica nunca devolve vazio: o Select do formulário exige opções (IndexError no compose)."""
    tbl = (m.get("form_static") or {}).get("memory_embs", {})
    mode = (v or {}).get("mode") or "embed"
    opts = [tuple(x) for x in tbl.get(mode, tbl.get("embed", []))]
    cur = ((ctx or {}).get("item") or {}).get("embeddings", "")
    return _with_current(opts, cur)


def _src_memory_reranker(m, v, ctx):
    opts = memory_provider_options("reranker")
    return _with_current(opts, ((ctx or {}).get("item") or {}).get("reranker", ""))


SOURCES = {
    "people": lambda m, v, ctx: [(p["id"], p["name"]) for p in m.get("people", [])],
    "recipients": lambda m, v, ctx: [(p["id"], p["name"]) for p in m.get("people", []) if not p.get("is_owner")],
    "actions": lambda m, v, ctx: [(a["id"], a["title"]) for a in m.get("actions", [])
                                  if a.get("open") and a.get("id") != (ctx or {}).get("id")],
    "relations": lambda m, v, ctx: list(RELATIONS),
    "areas": lambda m, v, ctx: [(a["id"], a["name"]) for a in (m.get("portfolio") or {}).get("areas", [])],
    "processes": lambda m, v, ctx: [(p["id"], f"{p['id']} · {_short(p['title'])}")
                                    for p in (m.get("portfolio") or {}).get("processes", [])],
    "doc_targets": lambda m, v, ctx: [(x["id"], f"{x['id']} · {_short(x['title'])}")
                                      for k in ("processes", "opportunities") for x in (m.get("portfolio") or {}).get(k, [])],
    "goals": lambda m, v, ctx: [(g["id"], f"{g['id']} · {_short(g['title'])}") for g in m.get("goals", [])],
    "goals_active": lambda m, v, ctx: [(g["id"], f"{g['id']} · {_short(g['title'])}") for g in m.get("goals", []) if _active(g)],
    "projects_active": lambda m, v, ctx: [(p["id"], f"{p['id']} · {_short(p['title'])}")
                                          for p in m.get("projects", []) if _active(p)],
    "goal_filter": _src_goal_filter,
    "projects_of_goal": _src_projects_of_goal,
    "plan_nodes": lambda m, v, ctx: [(g["id"], f"{g['id']} · {_short(g['title'])}") for g in m.get("goals", [])]
                                    + [(p["id"], f"{p['id']} · {_short(p['title'])}") for p in m.get("projects", [])],
    "link_targets": lambda m, v, ctx: [(a["id"], f"{a['id']} · {_short(a['title'])}") for a in m.get("actions", []) if a.get("open")]
                                      + SOURCES["plan_nodes"](m, v, ctx),
    "decisions": lambda m, v, ctx: [(d["id"], f"{d['id']} · {_short(d['title'])}") for d in m.get("decisions", [])
                                    if d.get("status") == "ativa"],
    "artifacts": lambda m, v, ctx: [(a["id"], _short(a.get("title") or a["id"])) for a in m.get("artifacts", [])],
    "ask_options": lambda m, v, ctx: [(o, o) for o in ((ctx or {}).get("item") or {}).get("options") or []],
    "node_status": lambda m, v, ctx: [(s, s) for s in ["ativo", "congelado", "depois", "finalizado"]
                                      + ([((ctx or {}).get("item") or {}).get("status")]
                                         if ((ctx or {}).get("item") or {}).get("status") not in
                                         (None, "", "ativo", "congelado", "depois", "finalizado") else [])],
    "recurrence": lambda m, v, ctx: [(NONE, NONE)] + [(r, r) for r in (m.get("form_static") or {}).get("recurrence", [])],
    "opp_kinds": lambda m, v, ctx: [(k, schema.opp_kind_label(k)) for k in (m.get("form_static") or {}).get("opp_kinds", [])],
    "doc_kinds": lambda m, v, ctx: [(k, k) for k in m.get("doc_kinds", [])],
    "source_kinds": _src_source_kinds,
    "opp_status": _src_opp_status,
    "reports": lambda m, v, ctx: [(r, r) for r in (m.get("form_static") or {}).get("reports", [])],
    "destinations": lambda m, v, ctx: [(d, d) for d in (m.get("form_static") or {}).get("destinations", [])],
    "providers": _src_providers,
    "memory_llm": _src_memory_llm,
    "memory_embs": _src_memory_embs,
    "memory_reranker": _src_memory_reranker,
    "ice:impact": _ice("impact"), "ice:confidence": _ice("confidence"), "ice:ease": _ice("ease"),
}


def options(f: F, m: dict, v: dict | None = None, ctx: dict | None = None) -> list[tuple[str, str]]:
    """(valor, rótulo) de um campo de escolha (ou das sugestões de um texto livre)."""
    src = f.choices if f.choices is not None else f.suggest
    if src is None:
        return []
    if isinstance(src, str):
        return [tuple(x) for x in SOURCES[src.lstrip("@")](m, v or {}, ctx or {})]
    return [tuple(x) for x in src]


SUGGEST_LIMIT = 12


def filter_options(items, query: str = "", limit: int = SUGGEST_LIMIT) -> list[dict[str, str]]:
    """Filtra opções de autocompletar por prefixo do ID ou palavras dobradas (util.fold) do título/nome.
    Devolve [{id, label}] ordenado (prefixo exato do ID primeiro, depois pelo rótulo) e limitado a `limit`."""
    q = util.fold(query)
    words = q.split()
    matched: list[tuple[tuple[int, str, str], dict[str, str]]] = []
    for raw in items or ():
        if isinstance(raw, dict):
            oid = str(raw.get("id") or "")
            lab = str(raw.get("label") or raw.get("title") or raw.get("name") or oid)
        elif isinstance(raw, (tuple, list)):
            oid = str(raw[0])
            lab = str(raw[1] if len(raw) > 1 else raw[0])
        else:
            oid = lab = str(raw)
        prefix = f"{oid} · "
        if lab.startswith(prefix):
            lab = lab[len(prefix):]
        fid, flab = util.fold(oid), util.fold(lab)
        id_pref = bool(q) and fid.startswith(q)
        num_pref = bool(q) and q.isascii() and q.isdigit() and "-" in fid and (
            fid.split("-", 1)[1].startswith(q) or fid.split("-", 1)[1].lstrip("0").startswith(q)
        )
        if not words or id_pref or num_pref or all(w in flab or w in fid for w in words):
            key = (0 if id_pref else 1, flab, fid)
            matched.append((key, {"id": oid, "label": lab}))
    matched.sort(key=lambda x: x[0])
    return [x[1] for x in matched[: max(0, limit)]]


def label(f: F, m: dict, ctx: dict | None = None) -> str:
    """Rótulo do campo — o ICE usa a pergunta do eixo, que vem do rubric (fonte única)."""
    if f.label.startswith("@ice:"):
        ax = ((m.get("portfolio") or {}).get("ice_rubric") or {}).get("axes", {}).get(f.label[5:]) or {}
        return f"{ax.get('name', f.label[5:])} — {ax.get('question', '')}".rstrip(" —")
    return _fmt(f.label, ctx) if ctx is not None else f.label


def required(f: F, ctx: dict | None = None) -> bool:
    return bool((ctx or {}).get(f.req[1:])) if isinstance(f.req, str) else f.req


# ── valor inicial (edição) ──────────────────────────────────────────────────
def _fmt_dur(mins) -> str:
    if not mins:
        return ""
    h, mi = divmod(int(mins), 60)
    return f"{h}h{mi}m" if h and mi else f"{h}h" if h else f"{mi}m"


def _num(x) -> str:
    if x in (None, ""):
        return ""
    if isinstance(x, str) and not x.isascii():
        return x
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    return str(int(f)) if f == int(f) else repr(f)


def _goal_of(item, ctx, m):
    p = item.get("project") if isinstance(item, dict) else None
    return next((x["goal"] for x in m.get("projects", []) if x["id"] == p), NONE) if p and p != NONE else NONE


def _deliv_short(item, ctx, m):
    d, p = item.get("deliverable") or "", item.get("project") or ""
    return d.split(".", 1)[1] if p and d.startswith(p + ".") else d


def _source_other(item, ctx, m):
    meta = {"key", "kind", "in_watch", "last_ok", "last_error", "failures", "pulls", "last_changed", "window", "note",
            "channel", "user", "query", "folder", "doc", "jql", "cloud", "mode", "path", "exclude", "enabled",
            "problem", "problem_reason"}
    return "; ".join(f"{k}={v}" for k, v in item.items() if k not in meta and v not in (None, ""))


def _cloud0(item, ctx, m):
    return item.get("cloud") or next((s["cloud"] for s in m.get("sources", []) if s.get("cloud")), "")


INIT = {   # "chave:fmt" → fmt(valor cru do item)
    "str": lambda x: "" if x is None else str(x),
    "bool": lambda x: "false" if x is False or str(x).strip().lower() in ("false", "0", "nao", "não") else "true",
    "csv": lambda x: ", ".join(x or []),
    "csvc": lambda x: ",".join(x or []),
    "dur": _fmt_dur,
    "num": _num,
    "prio": lambda x: x or "normal",
    "jscope": lambda x: "jql" if x else "mine",
}
IFMT = {   # "chave:fmt" ou ":fmt" → fmt(item, ctx, m) — precisa de mais que o valor cru
    "goal_of": _goal_of,
    "deliv_short": _deliv_short,
    "owner_shown": lambda item, ctx, m: "eu" if item.get("mine") or item.get("list") == "mine" else item.get("owner") or "",
    "owner_base": lambda item, ctx, m: "eu" if item.get("mine") else item.get("owner") or "",
    "source_other": _source_other,
    "cloud0": _cloud0,
}


def _init_of(spec: str | None, ctx: dict, m: dict) -> str:
    if not spec:
        return ""
    item = ctx.get("item") or {}
    if spec.startswith("@"):
        return "" if ctx.get(spec[1:]) is None else str(ctx.get(spec[1:]))
    key, _, fmt = spec.partition(":")
    if fmt in IFMT:
        return IFMT[fmt](item, ctx, m)
    return INIT[fmt or "str"](item.get(key))


def initial(form: Form, ctx: dict | None = None, m: dict | None = None) -> dict[str, str]:
    """Valor com que cada campo abre (padrão fixo, ou o que o item já tem)."""
    ctx, m = ctx or {}, m or {}
    out = {}
    for f in form.fields:
        got = _init_of(f.init, ctx, m) if f.init else ""
        out[f.id] = got if got != "" else (f.value or "")
    return out


def baseline(form: Form, ctx: dict | None = None, m: dict | None = None) -> dict[str, str]:
    ctx, m = ctx or {}, m or {}
    return {f.id: _init_of(f.base or f.init, ctx, m) for f in form.fields}


# ── visibilidade, validação, dicas, transformações ──────────────────────────
def _fb_dup(v, ctx, m):
    key = " ".join(util.fold(v.get("title") or "").split())
    kind = v.get("kind") or "sugestao"
    return next((f for f in m.get("feedback", []) if key and f.get("kind") == kind
                 and " ".join(util.fold(f.get("title") or "").split()) == key), None)


PRED = {   # (valores, ctx, m) → bool — visibilidade de campo e comandos extras
    "fb_dup": lambda v, ctx, m: _fb_dup(v, ctx, m) is not None,
    "no_target_ctx": lambda v, ctx, m: not ctx.get("target_fixed"),
    "prop_close": lambda v, ctx, m: ctx.get("kind") == "fechar-acao" and bool(ctx.get("target")),
    "prop_effort": lambda v, ctx, m: ctx.get("kind") == "reestimar" and bool(ctx.get("target")),
    "prop_merge": lambda v, ctx, m: ctx.get("kind") == "unificar-acao" and bool(ctx.get("target")) and bool(ctx.get("into")),
    "prop_drop": lambda v, ctx, m: ctx.get("kind") == "descartar-acao" and bool(ctx.get("target")) and bool(ctx.get("into")),
    "need_base_url": lambda v, ctx, m: v.get("provider") == "custom"
                                       or (v.get("slot") == "decision" and v.get("provider") == "local"
                                           and v.get("advanced") == "on"),
    "need_model": lambda v, ctx, m: not (v.get("slot") == "decision" and v.get("provider") == "local"),
    "need_provider_key": lambda v, ctx, m: v.get("provider", "") not in ("off", "", *_LLM_SUBSCRIPTIONS)
                                           and not (v.get("slot") == "embeddings" and v.get("provider") == "local")
                                           and not (v.get("slot") == "decision" and v.get("provider") == "local"),
    "show_candidates": lambda v, ctx, m: (v.get("slot") == "reranker" and v.get("provider", "") not in ("", "off"))
                                         or (v.get("slot") == "decision" and v.get("provider") == "hindsight"
                                             and v.get("recall") == "on"),
}


def _cond(c, v: dict, ctx: dict, m: dict) -> bool:
    if c is None:
        return True
    if isinstance(c, str):
        return bool(PRED[c](v, ctx, m))
    for k, vals in c.items():
        neg = k.endswith("!")
        k = k.rstrip("!")
        got = ctx.get(k[1:]) if k.startswith("@") else v.get(k, "")
        got = "" if got is None else str(got)
        if (got in vals) == neg:
            return False
    return True


def _clean(form: Form, raw: dict, surface: str = "") -> dict[str, str]:
    clean: dict[str, str] = {}
    for f in form.fields:
        s = ("" if raw.get(f.id) is None else str(raw.get(f.id))).strip()
        if f.auto == "surface" and surface and not s:
            s = surface
        clean[f.id] = s
    return clean


def hidden(form: Form, raw: dict, ctx: dict | None = None, m: dict | None = None) -> set[str]:
    clean = {k: ("" if val is None else str(val)).strip() for k, val in (raw or {}).items()}
    return {f.id for f in form.fields if not _cond(f.show, clean, ctx or {}, m or {})}


def values(form: Form, raw: dict, ctx: dict | None = None, m: dict | None = None, surface: str = "") -> dict[str, str]:
    """Valores que valem: aparados, e escondido = vazio (não conta, nem para obrigatório)."""
    clean = _clean(form, raw, surface)
    hid = hidden(form, clean, ctx, m)
    return {k: ("" if k in hid else x) for k, x in clean.items()}


def _today(m: dict) -> date:
    return util.parse_date(m.get("today")) if m.get("today") else util.today()


def _ck_date(x, v, ctx, m):
    try:
        dates.parse_due(x, _today(m))
        return ""
    except ValueError as e:
        return str(e)


def _ck_duration(x, v, ctx, m, positive=False):
    try:
        mins = util.parse_duration(x)
    except util.BrainError as e:
        return str(e)
    return "Use uma duração maior que zero (45m, 1h30m)." if positive and not mins else ""


_DOT_NUM_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_COMMA_NUM_RE = re.compile(r"^[0-9]+,[0-9]{1,2}$")
_THOUSANDS_RE = re.compile(r"^[0-9.,]+$")


def _ck_int(lo, hi):
    def ck(x, v, ctx, m):
        ok = x.isascii() and x.isdigit() and (lo is None or int(x) >= lo) and (hi is None or int(x) <= hi)
        if ok:
            return ""
        if lo is not None and hi is not None:
            return f"Use um inteiro de {lo} a {hi}."
        return f"Use um inteiro a partir de {lo}."
    return ck


def _ck_num(x, v, ctx, m):
    if _DOT_NUM_RE.fullmatch(x):
        return "" if float(x) > 0 else "Use um número maior que zero."
    if _COMMA_NUM_RE.fullmatch(x):
        return "" if float(x.replace(",", ".")) > 0 else "Use um número maior que zero."
    if "," in x and _THOUSANDS_RE.fullmatch(x):
        return "Use ponto decimal ou vírgula só para decimais (sem separador de milhar)."
    return "Use um número maior que zero."


def _ck_watch_key(x, v, ctx, m):
    from .watch import KEY_RE
    if not KEY_RE.match(x):
        return "key: minúsculas, números, '.', '_' e '-' (ex.: slack-time-dados)"
    taken = {s["key"] for s in m.get("sources", []) if s.get("in_watch") and s["key"] != ctx.get("key0")}
    return "já existe uma fonte com essa key" if x in taken else ""


def _ck_drive(x, v, ctx, m):
    from .watch import drive_doc_id
    return "" if drive_doc_id(x) else "cole a URL (ou o id) do Drive"


def _ck_jira(x, v, ctx, m):
    from .watch import jira_base
    try:
        jira_base(v.get("jscope") or "mine", x)
        return ""
    except util.BrainError as e:
        return str(e)


def _ck_pairs(x, v, ctx, m):
    from .watch import FIELD_RE
    for part in [p for p in x.split(";") if p.strip()]:
        k, sep, _ = part.partition("=")
        if not sep or not FIELD_RE.match(k.strip()):
            return f"use campo=valor separados por ponto e vírgula (recebi {part.strip()!r})"
    return ""


def _deliv_full(x: str, project: str) -> str:
    r = ids.normalize((x or "").strip().upper().lstrip("."))
    if r.isascii() and r.isdigit():
        return f"{project}.{int(r)}" if project and project != NONE else ""
    return r


def _all_delivs(m):
    return {d["id"]: (p, d) for p in m.get("projects", []) for d in p.get("deliverables", [])}


def _ck_deliv(x, v, ctx, m):
    proj = v.get("project", "")
    full = _deliv_full(x, proj)
    if not full:
        return "Só o número precisa do campo projeto: escolha o projeto ou escreva PROJ-#.# por inteiro."
    if full in _all_delivs(m):
        return ""
    p = full.split(".")[0]
    nums = [d["id"].split(".")[1] for pr in m.get("projects", []) if pr["id"] == p for d in pr.get("deliverables", [])]
    return f"{full} não existe" + (f" (os de {p} são {', '.join(nums)})" if nums else "")


def _ck_merge_into(x, v, ctx, m):
    t = next((a for a in m.get("actions", []) if a["id"] == ids.normalize(x)), None)
    if t is None or t["id"] == ctx.get("id"):
        return "informe outra ação existente (TASK-####)"
    return "" if t.get("open") else f"{t['id']} precisa estar aberta"


def _ck_proc(x, v, ctx, m):
    return "" if any(p["id"] == x for p in (m.get("portfolio") or {}).get("processes", [])) else f"{x} não existe (use PROC-####)."


def _ck_goal(x, v, ctx, m):
    return "" if any(g["id"] == x for g in m.get("goals", [])) else f"{x} não existe no PLANNING (use GOAL-#)."


def _ck_slug(x, v, ctx, m):
    return "" if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", x) else "Use minúsculas, números e hífens (ex.: growth)."


def _ck_doc_watch(x, v, ctx, m):
    from .watch import drive_doc_id
    if x != "sim":
        return ""
    if v.get("kind") != "playbook":
        return "Só playbook é vigiado."
    return "" if drive_doc_id(v.get("ref", "")) else "Vigiar pede um doc do Drive (URL ou id)."


def _ck_fb_dup(x, v, ctx, m):
    f = _fb_dup(v, ctx, m)
    if f and v.get("force") != "sim":
        return (f"mesmo título e tipo de {f['id']} — acrescente detalhe ao existente "
                f"(`brain feedback show {f['id']}`) ou marque “criar mesmo assim”")
    return ""


def _ck_opp_status(x, v, ctx, m):
    it = ctx.get("item") or {}
    if x == "em-andamento" and x != it.get("status") and not (it.get("promoted") or it.get("project")):
        return f"{it.get('id', '')}: 'em-andamento' só existe depois de promover (tecla p, em qualquer nível)."
    return ""


def _note_link(x: str) -> str:
    """notes.normalize_link: 'a-146'/'task146' → 'TASK-0146'; o resto passa por ids.normalize (maiúsculas)."""
    v = (x or "").strip().upper()
    mm = re.fullmatch(r"(?:A|TASK)-?(\d{1,})", v)
    return f"TASK-{int(mm.group(1)):04d}" if mm else ids.normalize(v)


def _ck_note_link(x, v, ctx, m):
    """As mensagens de notes.check_link — o vínculo existe na ação ou na árvore do PLANNING."""
    link = _note_link(x)
    if not ids.LINK_ID.match(link):
        return f"vínculo inválido: {link!r} (use TASK-####, GOAL-#, PROJ-# ou PROJ-#.#)"
    if link.startswith("TASK-"):
        return "" if any(a["id"] == link for a in m.get("actions", [])) else f"{link}: ação não encontrada"
    plan = {g["id"] for g in m.get("goals", [])} | {p["id"] for p in m.get("projects", [])} | set(_all_delivs(m))
    return "" if link in plan else f"{link}: não existe em PLANNING/goals.md"


def _ck_no_dot(x, v, ctx, m):
    return "O título não pode ter “·”." if "·" in x else ""


def _ck_recall_candidates(x, v, ctx, m):
    if x == "on" and not (v.get("candidates") or "").strip():
        return 'Preencha "top-N candidatos" (exigido ao ligar o decisor no recall).'
    return ""


CHECKS = {   # (valor, valores, ctx, m) → mensagem ("" = ok)
    "date": _ck_date,
    "duration": _ck_duration,
    "duration_pos": lambda x, v, ctx, m: _ck_duration(x, v, ctx, m, positive=True),
    "int": None,                       # "int:lo:hi" — montado em check()
    "num": _ck_num,
    "slug": _ck_slug,
    "watch_key": _ck_watch_key,
    "drive": _ck_drive,
    "jira": _ck_jira,
    "pairs": _ck_pairs,
    "deliv": _ck_deliv,
    "merge_into": _ck_merge_into,
    "proc": _ck_proc,
    "goal": _ck_goal,
    "doc_watch": _ck_doc_watch,
    "fb_dup": _ck_fb_dup,
    "opp_status": _ck_opp_status,
    "note_link": _ck_note_link,
    "no_dot": _ck_no_dot,
    "recall_candidates": _ck_recall_candidates,
    "people": None,                    # PY_ONLY — a TUI liga o resolvedor de aliases do ledger
    "recipient": None,                 # PY_ONLY — [outbound].allow é config, não view model
}


def check(name: str | None, x: str, v: dict, ctx: dict | None = None, m: dict | None = None, extra: dict | None = None) -> str:
    if not name or not x:
        return ""
    base, _, arg = name.partition(":")
    if base == "int":
        lo, _, hi = arg.partition(":")
        return _ck_int(int(lo) if lo else None, int(hi) if hi else None)(x, v, ctx or {}, m or {})
    fn = (extra or {}).get(base) or CHECKS.get(base)
    return fn(x, v, ctx or {}, m or {}) if fn else ""


def _h_date(x, v, ctx, m):
    return dates.describe(x, _today(m))


def _h_drive(x, v, ctx, m):
    from .watch import drive_doc_id
    got = drive_doc_id(x)
    return f"id {got}" if got else "não parece uma URL ou id do Drive"


def _h_jira(x, v, ctx, m):
    from .watch import jira_jql
    try:
        return "→ " + jira_jql(v.get("jscope") or "mine", x, v.get("mode") or "")
    except util.BrainError as e:
        return str(e)


def _h_deliv(x, v, ctx, m):
    full = _deliv_full(x, v.get("project", ""))
    hit = _all_delivs(m).get(full)
    return f"→ {full} · {hit[1]['title']}" if hit else ""


def _h_ice(axis):
    def h(x, v, ctx, m):
        r = ((m.get("portfolio") or {}).get("ice_rubric") or {}).get("axes", {}).get(axis) or {}
        lv = next((lv for lv in r.get("levels", []) if str(lv["n"]) == x), None)
        return f"{lv['criterion']} · {lv['anchor']}" if lv else ""
    return h


def _hint_from_hours(h: float) -> int:
    return 5 if h > 40 else 4 if h >= 20 else 3 if h >= 10 else 2 if h >= 5 else 1


def _h_ice_impact(x, v, ctx, m):
    out = _h_ice("impact")(x, v, ctx, m)
    h = (ctx.get("item") or {}).get("hours_saved")
    if x.isascii() and x.isdigit() and h:
        hint = _hint_from_hours(float(h))
        out += f"\nhoras declaradas: {float(h):g} h/mês → faixa sugerida {hint}"
        if int(x) > hint:
            out += " · ⚠ escopo e horas divergem: vale a menor nota"
    return out


def _h_note_link(x, v, ctx, m):
    link = _note_link(x)
    if _ck_note_link(x, v, ctx, m):
        return _ck_note_link(x, v, ctx, m)
    a = next((a for a in m.get("actions", []) if a["id"] == link), None)
    title = (a or {}).get("title") or next((n["title"] for n in m.get("goals", []) + m.get("projects", [])
                                            if n["id"] == link), "") or (_all_delivs(m).get(link, (None, {}))[1] or {}).get("title", "")
    return f"→ {link} · {title}" if title else ""


HINTS = {   # (valor, valores, ctx, m) → texto de apoio
    "date": _h_date,
    "drive": _h_drive,
    "jira": _h_jira,
    "deliv": _h_deliv,
    "note_link": _h_note_link,
    "ice:impact": _h_ice("impact"), "ice:confidence": _h_ice("confidence"), "ice:ease": _h_ice("ease"),
    "ice_impact": _h_ice_impact,
    "recall_note": lambda x, v, ctx, m: (
        "Cada candidato é uma requisição própria ao decisor; sem fallback para RRF nesta versão (1.2.0) — "
        "se o decisor cair, o recall falha fechado."
    ) if x == "on" else "",
    "dup_action": None,                # PY_ONLY — similaridade (dupes.py) sobre o ledger inteiro
    "promote_diff": None,              # PY_ONLY — diff do goals.md que nasceria (planning.py)
    "provider_model": None,            # PY_ONLY — recomendados por operação (providers.py)
}


def hint(name: str | None, x: str, v: dict, ctx: dict | None = None, m: dict | None = None, extra: dict | None = None) -> str:
    if not name or not x:
        return ""
    fn = (extra or {}).get(name) or HINTS.get(name)
    return fn(x, v, ctx or {}, m or {}) if fn else ""


def _xf_date(x, v, ctx, m):
    try:
        d = dates.parse_due(x, _today(m))
    except ValueError:
        return ""
    return d.isoformat() if d else ""


def _xf_jql(x, v, ctx, m):
    from .watch import jira_jql
    if not x:                          # escondido (tipo não é jira): nada de JQL
        return ""
    try:
        return jira_jql(x or "mine", v.get("jref", ""), v.get("mode", ""))
    except util.BrainError:
        return v.get("jref") or ELLIPSIS


def _xf_jira_cloud(x, v, ctx, m):
    from .watch import jira_cloud
    return x or (jira_cloud(v.get("jref", "")) or "")


def _xf_new_people(x, v, ctx, m):
    had = set((ctx.get("item") or {}).get("people") or [])
    return ",".join(p.strip() for p in x.split(",") if p.strip() and p.strip() not in had)


XF = {   # (valor, valores, ctx, m) → valor que vai para a CLI
    "date": _xf_date,
    "deliv": lambda x, v, ctx, m: _deliv_full(x, v.get("project", "")) or x,
    "nospace": lambda x, v, ctx, m: x.replace(" ", ""),
    "num": lambda x, v, ctx, m: _num(x.replace(",", ".") if _COMMA_NUM_RE.fullmatch(x) else x) if x else "",
    "note_link": lambda x, v, ctx, m: _note_link(x) if x else "",
    "lower_eu": lambda x, v, ctx, m: "eu" if x.lower() == "eu" else x,
    "jql": _xf_jql,
    "jira_cloud": _xf_jira_cloud,
    "new_people": _xf_new_people,
}

FILL = {   # (valores) → novo valor | None (não mexe)
    "owner_for_list": lambda v: "eu" if v.get("list") == "mine" else ("" if (v.get("owner") or "").lower() == "eu" else None),
}

# Só o Python tem — e por quê. O painel não valida/dica estes; a CLI valida de novo ao gravar.
PY_ONLY = {
    "check:people": "resolver alias de pessoa usa o índice de aliases do ledger (people.resolve)",
    "check:recipient": "[outbound].allow mora no config/brain.toml, fora do view model",
    "hint:dup_action": "similaridade de ações (dupes.similar) roda sobre o ledger inteiro",
    "hint:promote_diff": "o diff do goals.md que nasceria vem de planning.py",
    "hint:provider_model": "os modelos recomendados por operação vêm de providers.py",
}


# ── montagem do comando ─────────────────────────────────────────────────────
def _pairs(x: str) -> dict[str, str]:
    out = {}
    for part in [p for p in (x or "").split(";") if p.strip()]:
        k, _, val = part.partition("=")
        out[k.strip()] = val.strip()
    return out


def _xf(f: F, x: str, v: dict, ctx: dict, m: dict) -> str:
    return XF[f.xf](x, v, ctx, m) if f.xf else x


def _tok(t: str, form: Form, v: dict, ctx: dict, m: dict) -> list[str]:
    fields = {f.id: f for f in form.fields}
    out: list[str] = []
    for piece in [t]:
        mm = re.fullmatch(r"\{([?*@]?)([\w.]+)\}", piece)
        if not mm:
            out.append(re.sub(r"\{@(\w+)\}", lambda g: str(ctx.get(g.group(1)) or ELLIPSIS), piece))
            continue
        mode, name = mm.groups()
        if mode == "@" or name not in fields:
            val = ctx.get(name)
            out.append(ELLIPSIS if val in (None, "") else str(val))
            continue
        f = fields[name]
        val = _xf(f, v.get(name, ""), v, ctx, m)
        if val == "" and ctx.get(name) not in (None, ""):      # campo escondido/vazio: o ctx fixa (ex.: alvo já escolhido)
            val = str(ctx[name])
        if mode == "*":
            parts = [p.strip() for p in val.split(",") if p.strip()]
            out += parts or [ELLIPSIS]
        elif mode == "?":
            out += [val] if val else []
        else:
            out.append(val or ELLIPSIS)
    return out


def _arg(f: F, val: str) -> list[str]:
    if f.flag is not None:
        return list(f.flag.get(val, []))
    if f.set == "*":
        return [t for k, x in _pairs(val).items() for t in ("--set", f"{k}={x}")]
    if f.set:
        return ["--set", f"{f.set}={val}"]
    if f.many:
        return [t for p in val.split(",") if p.strip() for t in (f.arg, p.strip())]
    return [f.arg, val] if f.arg else []


def _emits(f: F) -> bool:
    return bool(f.arg or f.set or f.flag is not None)


def build(form_id: str, raw: dict, ctx: dict | None = None, m: dict | None = None, surface: str = "") -> list[list[str]]:
    """Valores do formulário → comandos `brain` (listas de argumentos). A MESMA regra do `formArgv` do forms.js."""
    form, ctx, m = FORMS[form_id], ctx or {}, m or {}
    clean = _clean(form, raw, surface)
    hid = hidden(form, clean, ctx, m)
    v = {k: ("" if k in hid else x) for k, x in clean.items()}
    fields = {f.id: f for f in form.fields}
    placed = {re.sub(r"[{}?*@]", "", t) for t in form.cmd if t.startswith("{")}
    main: list[str] = []
    for t in form.cmd:
        main += _tok(t, form, v, ctx, m)
    base = baseline(form, ctx, m) if form.edit else {}
    base_hid = hidden(form, base, ctx, m) if form.edit else set()
    order = list(form.order) + [f.id for f in form.fields if f.id not in form.order]
    for fid in order:
        f = fields.get(fid)
        if f is None or fid in placed or not _emits(f) or fid in hid:
            continue
        val = _xf(f, v[fid], v, ctx, m)
        if form.edit and not f.always:
            if f.set == "*":
                old, new = _pairs(base.get(fid, "")), _pairs(val)
                main += [t for k, x in new.items() if old.get(k) != x for t in ("--set", f"{k}={x}")]
                if fid not in base_hid:
                    main += [t for k in old if k not in new for t in ("--unset", k)]
                continue
            was = _xf(f, base.get(fid, ""), v, ctx, m) if f.xf not in ("new_people",) else base.get(fid, "")
            if val == was:
                continue
            if val == "":
                if fid not in base_hid:
                    main += list(f.clear or [])
                continue
        if val == "" or val in f.skip:
            continue
        main += _arg(f, val)
    main += list(form.tail)
    cmds = [main]
    for pred, tpl in form.more:
        if PRED[pred](v, ctx, m):
            c: list[str] = []
            for t in tpl:
                c += _tok(t, form, v, ctx, m)
            cmds.append(c)
    return cmds


def missing(form_id: str, raw: dict, ctx: dict | None = None, m: dict | None = None, extra: dict | None = None,
            surface: str = "") -> str:
    """Primeiro problema que impede confirmar ("" = pode): obrigatório vazio ou validação que falhou."""
    form, ctx, m = FORMS[form_id], ctx or {}, m or {}
    clean = _clean(form, raw, surface)
    hid = hidden(form, clean, ctx, m)
    v = {k: ("" if k in hid else x) for k, x in clean.items()}
    for f in form.fields:
        if f.id in hid:
            continue
        if required(f, ctx) and not v[f.id]:
            return f'Preencha "{label(f, m, ctx)}".'
        msg = check(f.check, v[f.id], v, ctx, m, extra)
        if msg:
            return msg
    return ""


def title(form_id: str, ctx: dict | None = None) -> str:
    return _fmt(FORMS[form_id].title, ctx or {})


def sub(form_id: str, ctx: dict | None = None) -> str:
    return _fmt(FORMS[form_id].sub, ctx or {})


def _fmt(s: str, ctx: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda g: "" if ctx.get(g.group(1)) is None else str(ctx.get(g.group(1))), s)


def secret_flags() -> frozenset[str]:
    """Opções de CLI cujo valor é segredo (derivado dos campos `secret=True` dos formulários)."""
    return frozenset(f.arg for fm in FORMS.values() for f in fm.fields if f.secret and f.arg)


def redact_args(args: list[str], flags: set[str] | frozenset[str] | None = None) -> list[str]:
    """Substitui o valor de opções secretas (`--key <v>`, `--key=<v>`) por `***` antes de exibir ou logar."""
    sflags = secret_flags() if flags is None else flags
    out: list[str] = []
    mask_next = False
    for a in args:
        if mask_next:
            out.append("***")
            mask_next = False
            continue
        if a in sflags:
            out.append(a)
            mask_next = True
            continue
        flag, sep, _ = a.partition("=")
        if sep and flag in sflags:
            out.append(f"{flag}=***")
            continue
        out.append(a)
    return out


def display(cmds: list[list[str]]) -> str:
    """A linha como as duas pontas mostram (`shlex.join`, a mesma do bridge.display sem encurtar)."""
    return "\n".join("brain " + shlex.join(redact_args(c)) for c in cmds)


# ── exportação para o painel ────────────────────────────────────────────────
def _patterns() -> dict:
    """As regexes que validam/transformam — o painel compila AS MESMAS (sem cópia no JS que possa divergir)."""
    from . import watch
    pats = {"key": watch.KEY_RE, "field": watch.FIELD_RE, "drive_id": watch.DRIVE_ID_RE, "drive_url": watch.DRIVE_URL_RE,
            "jira_issue": watch.JIRA_ISSUE_RE, "jira_project": watch.JIRA_PROJECT_RE, "jira_filter": watch.JIRA_FILTER_RE,
            "jira_host": watch.JIRA_HOST_RE, "link_id": ids.LINK_ID, "dur": util._DUR_RE}
    out = {k: [r.pattern, "i" if r.flags & re.I else ""] for k, r in pats.items()}
    out["jira_mine"] = [watch.JIRA_MINE, ""]
    out["legacy_long"] = [ids.LEGACY_LONG, ""]
    out["long_prefixes"] = [ids.LONG_PREFIXES, ""]
    return out


def static(brain=None) -> dict:
    """Listas fixas que o painel precisa (o resto das fontes sai do próprio view model)."""
    from . import schema
    from . import providers as prov
    out = {"recurrence": sorted(schema.RECURRENCE), "opp_kinds": sorted(schema.OPP_KINDS),
           "providers": {slot: [(p, info.get("label") or p)
                                for p, info in prov.menu_providers(slot, include_custom=True, include_unavailable=False)]
                         for slot in prov.PROVIDERS},
           "memory_embs": {
               "embed": [list(x) for x in memory_provider_options("embeddings", "embed")],
               "full": [list(x) for x in memory_provider_options("embeddings", "full")],
           },
           "reports": [], "destinations": [], "re": _patterns(), "weekdays": util.WEEKDAYS_PT, "date_help": dates.HELP,
           "secret_flags": sorted(secret_flags())}
    if brain is not None:
        d = brain.inst.reports / "share"
        out["reports"] = sorted((brain.inst.rel(p) for p in d.glob("*.*") if p.is_file()), reverse=True) if d.exists() else []
        out["destinations"] = list(brain.inst.cfg.get("publish", {}).get("destinations", []))
    return out


def export() -> dict:
    """Os formulários como dado (JSON) — o painel desenha e monta a linha com isto."""
    def fd(f: F) -> dict:
        d = {k: v for k, v in asdict(f).items() if v not in (None, "", (), False, {})}
        if isinstance(f.choices, tuple):
            d["choices"] = [list(x) for x in f.choices]
        for k in ("skip", "clear"):
            if k in d:
                d[k] = list(d[k])
        return d

    out = {}
    for fm in FORMS.values():
        if fm.where == "tui":
            continue
        d = {k: v for k, v in asdict(fm).items() if k not in ("fields", "more") and v not in (None, "", (), False)}
        d["cmd"] = list(fm.cmd)
        d["tail"] = list(fm.tail)
        d["order"] = list(fm.order)
        d["fields"] = [fd(f) for f in fm.fields]
        d["more"] = [[p, list(t)] for p, t in fm.more]
        out[fm.id] = d
    return out


__all__ = ["F", "Form", "FORMS", "SOURCES", "INIT", "IFMT", "PRED", "CHECKS", "HINTS", "XF", "FILL", "PY_ONLY",
           "SUGGEST_LIMIT", "memory_provider_options", "build", "missing", "required", "initial", "baseline",
           "values", "hidden", "options", "filter_options", "label", "title", "sub", "secret_flags", "redact_args",
           "display", "export", "static"]
