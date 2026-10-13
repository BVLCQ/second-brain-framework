# Guia do dono — Segundo Cérebro v2

Este arquivo explica o **porquê**. O passo a passo de cada tela e comando está
em `guides/manual.md`. A lei está em `AGENTS.md`. Se os dois brigarem, a
constituição vence.

## Para que serve

Você já tem calendário, Slack, Jira, Drive e uma cabeça. O cérebro não
substitui nenhum deles. Ele responde quatro perguntas que essas ferramentas
respondem mal, juntas:

1. **Para onde estou indo?** — goals → projetos → entregáveis, com progresso
   que não depende de alguém atualizar um percentual no feeling.
2. **Quem decidiu o quê, quando, com base em quê?** — decisões são entidades,
   não uma frase perdida numa ata.
3. **O que eu devo, o que me devem, o que é só contexto?** — três listas.
   O cérebro não cobra o que você só está observando.
4. **O que aconteceu de verdade?** — entregas com resultado, não checkboxes.

Ele também **protege tempo** (blocos de foco no seu calendário) e **escreve
mensagens** (você aprova o texto e manda). Não cria card no Jira, não responde
e-mail, não comenta PR.

## As duas camadas

**Determinística (`./brain`)** — IDs, validação, progresso, atraso, saúde de
projeto, painel, plano de foco, portas. Stdlib, sem rede, em segundos.
Pode rodar num cron sem LLM.

**LLM (o agente)** — lê reunião, classifica, extrai, redige, julga se uma
evidência *parece* fechar uma ação (e **propõe**, não fecha). Sem o CLI, o
agente inventa número de ação e perde o fio.

Se uma conta não fecha, o bug é do CLI, não "do modelo".

## Onde mora o quê

| Lugar | É verdade? | Quem escreve |
|---|---|---|
| `PLANNING/goals.md` | a árvore | você (estrutura) + agente (checkbox, com log) |
| `PROCESSED/_ledger/events.jsonl` | ações, decisões, entregas, pessoas | só `./brain` |
| `PROCESSED/<ano>/<mês>/*.md` | o texto extraído | o agente, uma vez |
| `RAW/` | o original | o mundo (e você, soltando arquivo) |
| `FRESH/` | um retrato | `./brain render` (descarta edição solta, colhe checkbox/status) |
| `reports/` | um PDF/HTML de um dia | `./brain share` — não atualiza |
| Hindsight | um índice | `./brain memory sync` — se o servidor cair, o vault continua |

Ler o `vault/` num editor de texto qualquer é opcional e bom. O painel HTML não
precisa de nada.

## As três listas

- **Minhas** — você deve. Entram no foco, no brief, no atraso.
- **Aguardando** — outra pessoa deve a você. O cérebro cobra no brief; você
  manda a mensagem pelo `/outbox` se quiser.
- **Observando** — o time deve a si mesmo. Aparece no projeto, some do TODO
  que cobra. O agente **não** propõe fechar estas só porque o Slack andou.

## O gate

Mudar a árvore de goals é a única decisão estrutural do sistema. O agente
mostra o diff e espera um "ok". Tudo o mais (abrir ação, registrar decisão,
marcar entregável feito) é fato, e fato se registra.

Há gates menores nas portas: um "ok" para o lote de foco da semana, um
"enviar 1" para cada mensagem, um "publica" para cada post no canal do time.

## Foco

Uma vez por semana o agente lê suas ações abertas (com prazo e esforço) e a
sua agenda, e encaixa blocos — prazo mais próximo primeiro, sem furar
almoço, férias ou o teto diário. Você vê a tabela. Diz "ok". Os blocos
nascem no calendário primário como *Focus time* (recusam convite novo) ou
viram um `.ics` se o OAuth ainda não estiver pronto.

Fechou a ação? O bloco futuro some no próximo sync. Não arraste o evento
para outro dia à mão e espere o cérebro "entender" — mude o prazo da ação
e regenere o plano.

## Memória e outras IAs

Hindsight é um índice. Serve para `/ask` achar mais rápido e para outra IA
(via `./brain mcp`) consultar o mesmo cérebro **sem escrever**. Se o índice
diverge do vault, o vault ganha; `memory rebuild` reconstrói.

## Noturno

Às 5h (ou o que você agendar) o CLI regenera as views, chama o agente
headless com `/update`, tira blocos de ações fechadas, sincroniza a memória
e, no domingo, faz backup. O agente noturno **não pode** aprovar, enviar,
publicar nem aplicar foco no Google: o ledger recusa. O que ele achar
dúbio vira proposta para você de manhã.

## Migração da v1

A v1 (`~/brain`) fica como arquivo. Esta instância nasce vazia. Se um dia
você quiser trazer um pedaço, copie o RAW e rode `/dump` — não existe
importador mágico do ledger antigo (eram linhas de Markdown, não eventos).

## Se algo cheirar mal

```
./brain doctor
./brain validate
```

Ledger corrompido (JSON inválido no meio) é o único caso em que se edita
`events.jsonl` — e mesmo assim, à mão, com backup, uma linha. Fora isso,
apende.
