# Proposta — A configuração guiada mora na face Configurações

> **Estado: SUPERSEDED por `guides/plans/onboarding-unification.md`.** A 2.17.0 entregou
> os passos 3–5 (abas, Memória unificada, Visão geral, remoção do atalho); a direção
> visual (decisão 1, opção b) foi decidida em 2026-11-18 e entregue na 2.23.0; os dois
> passos pendentes viraram F1 (entregue) e F8 (pendente) do plano unificado.

Executor: agente de código da instância. Regime dos outros planos: testes verdes (`python3 -m unittest discover -s tests`),
um commit local por passo, nada do dono no repo, `./brain upstream scan` antes de propor o push.

## 1. O problema — a experiência quebra ao sair do onboarding

A configuração guiada (`/onboarding`, `brainlib/assets/onboarding.html`) funciona bem: um passo por
vez, linguagem simples, prévia antes de gravar. A quebra acontece no botão "Abrir meu Brain".

1. **Dois sistemas visuais.** O onboarding é navy com vidro e gradiente ciano→violeta, com tokens
   próprios (`--cy`, `--vi`, `--panel`). O painel é neutro, claro por padrão, com `--accent #3b5bdb`.
   Quem termina a configuração cai no que parece outro aplicativo.
2. **Dois modelos de navegação.** O onboarding usa uma lista de passos com progresso; o painel, um
   carrossel de faces com abas.
3. **Configuração em dobro.** O passo *Memória* do onboarding repete `cfg/memoria`. Conectores e
   permissões aparecem também nos avisos de *Saúde*. São duas telas para a mesma coisa, cada uma
   com seu vocabulário: o onboarding diz `lite`, a CLI e o `brain.toml` dizem `embed`.
4. **Um atalho que parece pendência.** O botão "Configuração guiada" (`#onboard`) aparece abaixo das
   abas de **todas** as faces. Fica fora da face Configurações e dá a impressão de que há algo por fazer.

## 2. O que fica como está

- **A primeira vez.** `brain open` abre a configuração guiada enquanto `onboard.needed()` for
  verdadeiro, e o `install.sh` abre a configuração ao criar o app. É o comportamento certo.
- **O conteúdo e a ordem dos passos**, as rotas `/api/onboard/*` e as travas da ponte: token, corpo
  fora do log, upload limitado à inbox.
- **`finished` é permanente.** Rever um passo depois de concluído não devolve a instância ao modo
  de primeira vez. `needed()` já retorna `False` quando `progress.finished` existe.

## 3. A proposta

### 3.1 Cada passo vira uma aba de Configurações

| Passo do onboarding | Depois da primeira vez |
|---|---|
| Boas-vindas | só na primeira vez; "rever a boas-vindas" fica na Visão geral |
| Você + Sobre você | aba **Perfil** |
| Sua rotina | aba **Rotina** |
| Conectores + Permissões | aba **Conectores** (permissões como seção da mesma aba) |
| Memória | **funde** com a aba **Memória** atual: o modo (nenhuma · embed · full) no topo, provedores e harnesses abaixo, numa tela só |
| Integrações | aba **Integrações** (tokens, sem mostrar valor) |
| Goals e projetos | só na primeira vez; depois mora em Execução › Projetos, atrás do gate do `/goal` |
| Pronto | só na primeira vez |
| — | **Saúde** continua como está |

A face ganha uma primeira aba, **Visão geral**: a lista dos passos com o estado de cada um
(`feito` · `depois`) e um link para cada aba. A configuração guiada fica nela, e só nela.

```
Configurações
  Visão geral      ← lista dos passos; a configuração guiada mora aqui
  Perfil
  Rotina
  Conectores
  Memória
  Integrações
  Saúde        5   ← o único contador da face: problemas reais (doctor)
```

### 3.2 Pendência só quando existe

- **O botão `#onboard` sai das outras faces.** Ele é removido no mesmo commit que cria a Visão
  geral, nunca antes: em nenhum momento pode faltar o caminho de volta.
- **Passo pulado não gera contador.** `depois` é um estado neutro, em cinza, e não um aviso.
- **O contador da face Configurações vem só da Saúde**, a mesma régua do `brain doctor`.

### 3.3 Uma só identidade visual (direção recomendada, decisão 1)

O dono gostou da identidade do onboarding, e é ela que deve virar a do aplicativo, não o contrário.

- **Tema escuro do painel = paleta do onboarding**: fundo navy, superfícies de vidro, destaque
  ciano→violeta no item ativo, nos botões primários e no progresso.
- **Tema claro**: o mesmo destaque (índigo `#4F46E5` com ciano de apoio) sobre superfícies claras.
  Isso mantém a legibilidade que o painel tem hoje.
- **O onboarding passa a usar o shell do painel**: mesma barra lateral, mesma marca, mesmos
  componentes. No modo de primeira vez, a barra mostra só os passos (sem o carrossel de faces e
  sem ⌘K). No "Abrir meu Brain", as faces aparecem no mesmo lugar, sem trocar de página.

### 3.4 Código

- Os renderizadores das abas moram no `extra.js` (seção "face Configurações"), com o mesmo IIFE da ponte
  (token, toast). O `onboarding.html` segue com os próprios até o passo 6, quando ele vira o painel em modo
  de primeira vez e os dois passam a ser um só.
- O painel ganha as views `cfg/inicio`, `cfg/perfil`, `cfg/rotina`, `cfg/conectores` e
  `cfg/integracoes`, que chamam `/api/onboard/*`, os mesmos endpoints de hoje.
- `/onboarding` vira o painel em modo de primeira vez (`#setup/<passo>`), com o mesmo HTML e um
  sinal no view model.
- **Painel sem ponte** (aberto como arquivo, `LIVE` falso): as abas mostram o estado em modo
  leitura, vindo do view model, com "abra pelo app Brain para editar". Hoje o painel já esconde o
  `#onboard` nesse caso; a regra passa a valer para as abas.

## 4. Escada de commits

1. Tokens: o tema escuro do painel adota a paleta do onboarding, e o claro ganha o destaque índigo.
   Sem mudança de estrutura.
2. `setup.js` extraído do `onboarding.html`, com o onboarding atual usando o módulo. Sem mudança de
   comportamento; testes do onboarding verdes.
3. Abas Perfil, Rotina, Conectores e Integrações em Configurações, com o fallback de leitura.
4. Memória unificada: o modo entra no topo de `cfg/memoria`, e o passo do onboarding passa a ser
   essa mesma view.
5. Visão geral (`cfg/inicio`) **e** remoção do `#onboard` das faces, no mesmo commit.
6. `/onboarding` vira o painel em modo de primeira vez; transição para as faces sem recarregar.
7. Guias (`user-guide.md`, `commands.md`) e CHANGELOG.

## 5. Já feito junto com esta proposta (2.16.1)

- O ícone de traço grosso (`assets/icon/brain.svg`) é o ícone do app. A marca simplificada
  (`brain-mark.svg`) atende os tamanhos até 32 px: barra lateral, favicon e os 16/32 px do `.icns`.
  A arte detalhada continua só como ilustração da boas-vindas (`brain-hero.svg`).
- A marca da barra lateral agora é SVG embutido, sem a palavra "demo" ao lado do nome.
- Passo intermediário: o atalho `#onboard` aparece só na face Configurações. O passo 5 da escada
  troca esse atalho pela Visão geral.

## 6. Decisões abertas (do dono)

1. **Direção visual.** (a) *Recomendada:* o aplicativo inteiro adota a identidade do onboarding
   (3.3). (b) O onboarding se veste com os tokens atuais do painel. (b) é mais barata, mas perde o que
   o dono gostou.
2. ~~Nome do modo leve da memória.~~ Decidido na 2.17.0: **embed** em todo lugar, como na CLI (a API ainda
   aceita `lite`).
