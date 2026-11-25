# Desenvolvimento do framework

Como uma mudança no framework chega ao repositório público: branch, pull request, CI no GitHub e
portão de dados. É o mesmo fluxo dos outros projetos do mantenedor.

## O fluxo

1. **Issue.** O trabalho começa numa issue (molde por tipo em `.github/ISSUE_TEMPLATE/`). Mudança de
   tela vem com o print do estado atual, as variantes e a recomendação (`[UI]`).
2. **Branch e pull request.** Um branch por mudança, a partir da `main`; o PR referencia a issue e
   segue o molde de `.github/pull_request_template.md`. Criar o branch, commitar e abrir o PR é do
   agente — não espera aprovação.
3. **CI.** O PR roda no GitHub (abaixo), em dois workflows: o portão de dados (`data-gate.yml`, com
   o workflow da `main`, para o PR não enfraquecer o próprio portão) e a suíte em Python 3.11–3.14
   (`ci.yml`). Os dois precisam ficar verdes: a proteção da `main` exige o status `data-gate (status)`
   e os quatro `tests`. Mudança no portão só vale para os PR abertos depois do merge: o evento dele
   só lê o workflow da `main`.
4. **"ok" do dono.** O PR fica aberto até o "ok" literal do dono; o "ok" é o merge. Nada entra na
   `main` sem PR com o CI verde (proteção de branch) e sem o "ok".

## O que nunca entra no repositório

O repositório é público. Nada do dono vai para lá: nomes, e-mails, pessoas do ledger, canais do
Slack, caminhos da máquina, segredos — e nada da empresa do dono. Use os dados fictícios da padaria
(`marina-demo`, `contato@example.com`). Em mudança de tela, print e vídeo saem apenas do vault de
demonstração.

## Portão de dados

Duas varreduras iguais, em lugares diferentes, com as regras do `brain upstream scan` (caminho de
máquina, segredo, workspace do Slack, dado pessoal da instância) mais uma **lista privada de termos**
— nome de empresa, de rede interna, o que o mantenedor nunca quiser ver lá:

- **Na máquina, antes do push.** O hook `pre-push` varre os commits que o push leva e barra achados.
- **No CI, em todo PR e em todo push na `main`.** O job `data-gate` (`data-gate.yml`) varre o que o
  PR acrescenta à `main` (`origin/main` até a ponta do branch), commit a commit.

No CI a lista privada mora num segredo do repositório (`PUBLIC_DENYLIST_B64`: o arquivo da lista em
base64), que só o job `data-gate` recebe — nunca vai ao código, e o job da suíte, que executa o
código do PR, não a vê. O job varre com os scripts e a configuração da `main`, num worktree do PR:
o PR traz os commits, não as regras. Sem a lista (ausente, vazia, toda em comentário ou com termo
curto demais) o portão falha: ele não atesta nada.

Além dos termos, contam como dado: nome e e-mail de autor e de quem commitou em commit novo (de
e-mail novo, só o domínio; identidade que já aparece num commit público não conta), texto em UTF-16
e UTF-32, e arquivo que a varredura não varre — grande demais (mais de 50 MB) ou ilegível. Não varrido
nunca é "limpo".

**O push da `main` é alarme, não bloqueio.** No push o portão roda depois que o conteúdo já está público, e
com o workflow do próprio push. O que bloqueia é o status no PR, exigido pela proteção da `main`.

**O portão é outro arquivo, e o que vale é um status de commit.** `ci.yml` é o workflow DO PR: quem
abre o PR pode editá-lo. Se o portão morasse nele, bastaria apagar um `if:` — no `pull_request`, job
"skipped" conta como sucesso — ou acrescentar um job de mesmo nome: o check run casa pelo texto. Por
isso o portão vive em `data-gate.yml`, no evento que usa o workflow da `main`, sem `if:` nenhum até o
portão rodar, e publica o resultado como status de commit `data-gate (status)` na ponta do PR, com o
token do job. PR de fork só tem token de leitura: não consegue emitir um igual. A proteção da `main`
exige esse status — nunca o check `data-gate`. `tests/test_ci_hardening.py` trava tudo isso.

Só o CI barra também **anexo fechado**: arquivo compactado ou documento (zip, gzip, 7z, RAR, PDF,
Office) que o PR acrescenta é achado por si, mesmo sem termo — o portão não lê o que está comprimido
dentro. Imagem e vídeo não são bloqueados: captura de tela com dado interno só é vista por quem revisa.

Para rodar na máquina, da pasta do checkout, com a sua cópia da lista:

    python3 scripts/dev/public_gate.py gate --base origin/main --denylist ~/.config/brain/public-denylist

Códigos de saída: 0 limpo · 4 achado (só arquivo, linha e regra: o valor achado nunca é ecoado) · 1 erro.

No CI, achado da lista privada sai sem arquivo nem linha, e sem contagem: o log é público, e quem abre
PR de fork escolhe o conteúdo do alcance — cada execução com "onde" seria uma medida da lista privada.
Na máquina, acrescente `--detalhes` para ver onde bateu.

## Onde o CI roda

Nos runners hospedados do GitHub (`ubuntu-24.04`), numa máquina nova para cada job. O repositório é
público, e nele os runners padrão do GitHub são gratuitos.

**Nunca em runner próprio.** O workflow do `pull_request` é o do PR: quem abre o PR escolhe onde o
job roda e o que ele executa. Num repositório público, um job desse evento em runner próprio entrega
essa máquina a qualquer fork — por isso o workflow não tem nenhum, e `tests/test_ci_hardening.py`
barra um `runs-on` que não seja `ubuntu-24.04`.

O workflow não usa actions em JavaScript: o checkout é git puro, o Python vem da imagem oficial
`python:` e o `node` entra por um tarball com versão e checksum fixados. O `pip` só instala o que o
`requirements` trava por hash.

### Trocar a lista privada

A lista nasce na máquina do mantenedor (`~/.config/brain/public-denylist`, 0600) e vai para o
segredo em base64; quem faz isso precisa ser administrador do repositório:

    base64 < ~/.config/brain/public-denylist | gh secret set PUBLIC_DENYLIST_B64 --repo BVLCQ/second-brain-framework

Um termo por linha, ou separado por vírgula. Linha que começa com `#` é comentário; comentário no
meio de um termo não existe (vira parte dele). Termo com menos de 4 caracteres é recusado: o portão
falha em vez de varrer uma lista menor do que a pedida. O valor novo vale para a próxima execução
do CI.

## Evidência no PR

O GitHub não tem API para anexar arquivo a issue ou PR. O caminho usado aqui é um release rascunho,
um por PR:

    scripts/dev/pr_evidence.sh <número do PR> antes-painel.png depois-painel.png fluxo.mp4

Os anexos ficam num release rascunho (`evidence/pr-<n>`): não aparecem na página de releases, e os
links só abrem para quem tem acesso de escrita ao repositório. O script imprime o trecho de Markdown
para o corpo do PR. Print e vídeo abrem como download, não tocam dentro da página — para isso,
anexe pelo navegador (arrastar para o campo de comentário).
