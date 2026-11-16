# Sugestões, bugs e propostas de código — como escrever a issue

O Segundo Cérebro abre issues no repositório **público** do framework (porta 7, `brain feedback`).
Tudo que sobe é público e fica indexado: por isso o texto segue um molde e passa por validadores
que **recusam** o que não pode sair da máquina. Não há override.

## Título e o que nunca sobe

O título sobe sempre como **`[Sugestão] …`**, **`[Bug] …`** ou **`[Proposta] …`** (proposta de código aceita) — a
origem e o assunto à primeira vista. Tag escrita à mão no título é removida e substituída pela oficial.

**O id local (`FB-####`, `TASK-####`, `PROP-####`…) nunca vai ao repositório**, nem no título, nem no corpo, nem
no rodapé: ele é numeração da instância (outra instância tem outro `FB-0001`) e geraria issues duplicadas e
confusas. O `feedback push` confere o texto final antes de publicar e recusa se achar algum.

## Os três moldes

Cada campo vira `### <Título>` — o mesmo que o GitHub escreve quando alguém envia o formulário em
`.github/ISSUE_TEMPLATE/` —, então issue aberta pelo cérebro e issue aberta à mão têm a mesma cara.
`brain feedback template --kind sugestao|bug|framework` imprime o molde em branco.

| Molde | Quando | Campos (✱ = obrigatório) |
|---|---|---|
| `sugestao` | uma ideia de melhoria | Resumo ✱ · Problema ✱ · Proposta ✱ · Alternativas consideradas · Como validar |
| `bug` | algo quebra | Resumo ✱ · O que aconteceu ✱ · O que era esperado ✱ · Como reproduzir ✱ · Ambiente · Trecho do log |
| `framework` | proposta do cérebro que muda código/estrutura, aceita pelo dono | Resumo ✱ · Contexto ✱ · Proposta ✱ · Fora do escopo · Critérios de aceite ✱ |

Quem segue o molde:
- **agente** (`--by agent`) e **propostas `framework`**: o corpo precisa ter todos os campos obrigatórios
  preenchidos e nenhum campo fora do molde — senão o comando recusa e aponta o que falta;
- **dono** pelo painel/TUI: texto livre é aceito (vira o campo Resumo); se usar `###`, também segue o molde.

Fluxo do agente (headless não passa heredoc — escreva o arquivo e passe `--body-file`):

```bash
./brain feedback template --kind sugestao            # o molde com as dicas
./brain feedback add "Avisar quando a fornada passar do ponto" --kind sugestao \
  --body-file corpo.md --by agent --prov observado --source chat
./brain feedback show FB-0001                        # o texto EXATO que vai ao GitHub
./brain feedback revise FB-0001 --body-file corpo.md # corrige antes de publicar (ledger append-only)
```

Proposta de código (o dono aceita vendo este texto; aceitar = aprovar a issue):

```bash
./brain proposal add --kind framework --summary "resumo interno" \
  --issue-title "Avisar quando a fornada passar do ponto" --issue-body-file corpo.md \
  --by agent --prov observado --source chat
```

## Exemplo completo (dados fictícios da padaria)

```markdown
### Resumo
Avisar quando a massa da Padaria Pão Quente passar do ponto.

### Problema
A marina-demo esquece a fermentação de 12 horas e perde a fornada.

### Proposta
Um lembrete `brain action open "Assar a fornada" --due 2026-01-10` com aviso 1h antes.

### Alternativas consideradas
Alarme no celular — não fica registrado no ledger.

### Como validar
Criar a ação de teste com contato@example.com e conferir o aviso.
```

Os exemplos **sempre** usam o elenco fictício: `marina-demo`, `heitor-demo`, `sonia-demo`, `caio-demo`,
"Padaria Pão Quente", `contato@example.com`. O sufixo `-demo` marca dado fictício declarado e é aceito.

## O que os validadores recusam

Rodam em todo caminho que publica — `feedback add/revise`, `proposal add --kind framework`, o aceite da
proposta e, por último, o próprio `feedback push` (que varre o título e o corpo crus). O erro diz o **tipo**
e a **linha**, nunca o valor.

| Tipo | O que pega |
|---|---|
| dado do dono | nomes e e-mails de pessoas do ledger, domínio/empresa, destinatários, caminhos da máquina, tokens, workspace do Slack |
| ID do vault | `TASK-####`, `OPP-####`, `ASK-####`, `PROP-####`, `PROJ-#`… — o leitor público não os resolve |
| imagem ou print | `![](…)`, `<img>`, anexos do GitHub, `data:` URI, nome de arquivo `.png/.jpg/.mp4/.pdf`… |
| link externo / interno | qualquer URL fora de github.com, example.* e localhost; Drive, Slack, Jira, Notion, Granola… sempre |
| e-mail | fora dos domínios reservados `example.com/.org/.net` (e `-demo`) |
| @menção | o GitHub avisaria uma pessoa real (decorador em `código` é ignorado) |
| telefone, CPF, CNPJ, IP | dado pessoal |
| ID opaco | id de doc do Drive, id de canal/usuário do Slack |

Hosts extras permitidos: `[feedback].allow_hosts = ["docs.exemplo.org"]` no `config/brain.toml`.

## O que os validadores NÃO pegam

Nome de pessoa que **não está** no ledger e frase que descreve um caso real (“o time de X perdeu o
contrato Y”) passam. Contra isso valem a regra do exemplo fictício da padaria e a caixa de confirmação do
formulário da issue. Em dúvida: reescreva como a padaria, ou descreva o problema geral em vez do caso.

## Issues abertas à mão

`.github/ISSUE_TEMPLATE/` traz os formulários **Sugestão**, **Bug** e **Proposta de código**, com os mesmos
campos do molde, o aviso de privacidade e uma confirmação obrigatória de que não há dado real. Quem não tem
token pode abrir a issue direto no GitHub por eles.
