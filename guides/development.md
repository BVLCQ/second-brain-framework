# Desenvolvimento do framework

Como uma mudança no framework chega ao repositório público: branch, pull request, CI nos runners do
mantenedor e portão de dados. É o mesmo fluxo dos outros projetos do mantenedor.

## O fluxo

1. **Issue.** O trabalho começa numa issue (molde por tipo em `.github/ISSUE_TEMPLATE/`). Mudança de
   tela vem com o print do estado atual, as variantes e a recomendação (`[UI]`).
2. **Branch e pull request.** Um branch por mudança, a partir da `main`; o PR referencia a issue e
   segue o molde de `.github/pull_request_template.md`. Criar o branch, commitar e abrir o PR é do
   agente — não espera aprovação.
3. **CI.** O PR roda no runner do mantenedor (abaixo), em duas execuções: o portão de dados — com o
   workflow da `main`, para o PR não enfraquecer o próprio portão — e a suíte em Python 3.11–3.14.
   Os dois precisam ficar verdes.
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
- **No CI, em todo PR e em todo push na `main`.** O job `data-gate` varre o que o PR acrescenta à
  `main` (`origin/main` até a ponta do branch), commit a commit. A suíte só roda depois dele limpo.

No CI a lista privada mora no host do runner, num volume Docker (`brain-public-denylist`) que só
esse job monta, como só leitura — nunca vai ao repositório, nem como segredo. O job varre com os
scripts e a configuração da `main`, num worktree do PR: o PR traz os commits, não as regras. Sem a
lista (ausente ou vazia) o portão falha: ele não atesta nada.

Para rodar na máquina, com a sua cópia da lista:

    python3 scripts/dev/public_gate.py gate --base origin/main --denylist ~/.config/brain/public-denylist

Códigos de saída: 0 limpo · 4 achado (só arquivo, linha e regra: o valor achado nunca é ecoado) · 1 erro.

## Runner do mantenedor

O CI roda em workers do mantenedor (containers Docker na máquina dele), não nos runners do GitHub:
não consome minutos. Cada worker é um runner registrado só neste repositório, com o label `brain`.

    scripts/dev/runner-setup.sh --tag m3              # registra e sobe; idempotente
    scripts/dev/runner-setup.sh --tag m3 --workers 2  # quantos jobs rodam em paralelo
    scripts/dev/runner-setup.sh --tag m3 --remove     # descadastra e apaga

Pré-requisitos: Docker (OrbStack), `gh` como administrador do repositório e a lista privada em
`~/.config/brain/public-denylist` (0600). Cada máquina do mantenedor tem a sua (`--tag m3`, `--tag m4`).
A imagem do runner é fixada no script; para subir a versão, mude `RUNNER_IMAGE` e rode de novo.

**Runner em repositório público.** A suíte só roda no runner código que veio de dentro do
repositório: PR de fork não a roda (o `if` do job), e quem é de fora propõe por issue — o
mantenedor traz o código para um branch daqui. O que roda para qualquer PR é o portão de dados,
que só lê texto e usa o workflow da `main`. O token do job é só de leitura e nenhum job usa
segredo. Não registre esse runner em outro repositório: a máquina fica exposta ao código que ele
receber.

O workflow não usa actions em JavaScript: o checkout é git puro, o Python vem da imagem oficial
`python:` e o `node` entra por um tarball com versão e checksum fixados.

## Evidência no PR

O GitHub não tem API para anexar arquivo a issue ou PR. O caminho usado aqui é um release rascunho,
um por PR:

    scripts/dev/pr_evidence.sh <número do PR> antes-painel.png depois-painel.png fluxo.mp4

Os anexos ficam num release rascunho (`evidence/pr-<n>`): não aparecem na página de releases, e os
links só abrem para quem tem acesso de escrita ao repositório. O script imprime o trecho de Markdown
para o corpo do PR. Print e vídeo abrem como download, não tocam dentro da página — para isso,
anexe pelo navegador (arrastar para o campo de comentário).
