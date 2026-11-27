## 2.59.0 — Memória: modo e provedores numa tela só

- **Uma tela, todos os campos.** Configurações › Memória junta o modo (nenhuma · embed · full) e os provedores. Cada slot (LLM · embeddings · reranker · decisão) traz provedor, chave, modelo, modelo por operação do LLM, base URL, dimensões, teto de candidatos e decisor no recall — tudo o que `memory providers set` aceita —, pré-preenchido com o que está gravado. O cabeçalho de cada slot mostra o que vale hoje, no lugar da tabela antiga. No embed, o reranker aparece também.
- **Aplicar usa a rota do passo Memória.** Só o slot que mudou é regravado, com exatamente o que a tela mostra: campo apagado volta ao recomendado. O servidor sobe ou é recriado e o job narra. O formulário de provedor (`memory providers set`) continua na TUI e no terminal; a ponte do painel deixou de aceitar essa linha.
- **Trocar de provedor não deixa resto no `.env`.** O modelo de cada operação do LLM, a dimensão dos embeddings e o teto do reranker do provedor anterior ficavam: Fireworks → local seguia pedindo 1536 dimensões ao bge-m3 (que tem 1024), e Fireworks → Cohere seguia com o teto 50. Agora o que a troca não diz volta ao padrão do provedor novo, ou do servidor. Mudar a dimensão pede o `memory rebuild`, como trocar o modelo.
- **Decisor local sem URL é instalado.** Escolher Local na Decisão sem informar a URL instala e liga o servidor. A URL de fábrica como padrão pulava a instalação e deixava o slot sem chave; o aviso do `doctor` agora diz o caminho.

## 2.58.0 — o menu do painel abre no índice e ganha a ordem nova

- **Início e Visão geral sempre abrem a barra.** Execução começa em Início, Portfólio em Visão geral e Configurações em Visão geral, sem rótulo acima. Trocar de face cai sempre nessa página.
- **Execução em três blocos.** Agora (Tarefas, Perguntas), Registro (Projetos, Decisões, Linha do tempo) e Tools (Foco, Mensagens). O TODO se chama Tarefas. Fontes saiu daqui, junto com o badge de falha, e Conquistas deixou a barra: a página segue no ⌘K e no endereço `#wins`.
- **Configurações reorganizada.** Visão geral e Saúde no topo; Conta (Perfil, Rotina, Agentes/Harness), Conexões (Memória, Conectores, Fontes, Integrações) e Melhore o App (Sugestões). "Seu agente" virou Agentes/Harness no menu, na paleta e no título da página.
- **Rótulos de categoria em preto e branco.** Pretos no tema claro, brancos no escuro.

## 2.57.0 — todo arquivo que o painel cita agora tem link

- **Linha do tempo, "última interação" e busca ligam o artefato.** A linha do tempo escondia a reunião ou o documento de onde cada item nasceu; a ficha da pessoa e os resultados da busca mostravam o caminho como texto solto. Agora cada um tem o botão Ver, que abre o leitor embutido.
- **Mensagens e fontes mostram os arquivos.** A mensagem lista os arquivos da ação ou do artefato que a motivou, e a referência no cabeçalho vira link. A fonte ganha "ver último pull", que abre o snapshot que o pull gravou. A entrega, nas conquistas e na busca, lista os arquivos dela.
- **Um teste percorre todas as páginas.** Renderiza cada tela do painel com o modelo de uma instância demo e acusa caminho do vault fora de link. A lista de textos fixos permitidos é explícita e comentada.

## 2.56.0 — Fontes: grupos recolhem, avulsas saem da lista e o erro some quando a fonte se recupera

- **Cada tipo de fonte recolhe e reabre sozinho.** No painel, clique (ou Enter/Espaço) no cabeçalho; na TUI, Espaço na linha ou no cabeçalho. Recolhido, o grupo mostra só a contagem e o selo de problema. Vale na sessão; o liga/desliga por fonte não mudou.
- **Fonte avulsa sai da lista.** `brain watch remove KEY` agora também esquece o registro de pulls (evento `connector.forgotten`), e o `d` do painel e da TUI funciona em fonte avulsa. Tirar uma fonte do `watch.toml` não deixa mais um fantasma em "avulsas". Snapshots e eventos antigos ficam.
- **O erro some quando a fonte volta.** Um pull saudável limpa o texto do último erro, e uma checagem "inalterado" numa fonte com falha em aberto grava o pull que limpa o chip e o selo do grupo. Fonte saudável continua em silêncio.

## 2.55.0 — arquivos do vault viram link na ficha e no FRESH

- **A ficha mostra os arquivos ligados.** Ação, decisão, projeto, pessoa, oportunidade, processo, pergunta, foco, publicação e goal trazem a mesma lista da TUI: tipo, nome e para onde abre. O clique passa pelo servidor local, só dentro do vault. Fora do vault, ou com `..`, é recusado.
- **Sem editor, o leitor embutido.** Markdown com títulos, listas e tabelas. Um `<script>` no texto aparece escapado. Na própria ficha dá para trocar entre editor e leitor, e abrir todos de uma vez.
- **A nota em FRESH também liga o arquivo.** A ficha da ação e da decisão lista os arquivos como link, em vez de caminho solto.

## 2.54.0 — a barra lateral ganha seções, e Fontes sai do dia

- **Rótulos, nada some.** Execução separa Agora, Atenção e Registro. Portfólio separa Mapa, Trabalho e Cadastro. Configurações separa Conta, Conexões, Instância e Meta. O rótulo não é link.
- **Sugestões foi para Configurações.** É sobre o cérebro, não sobre o dia. A paleta continua achando a página.
- **Fontes foi para o lado de Conectores.** Na Execução fica só o badge, e só quando há falha de pull. O clique abre a página, que mora em Configurações.

## 2.53.0 — o diálogo de atualização lista o assunto de cada commit

- **Uma linha por commit, no máximo 140 caracteres.** O assunto aparece inteiro se cabe. Se passa, corta no último espaço e põe reticências. A conta é de caracteres, não de bytes. O hash curto fica ao lado e não entra na conta.
- **O changelog deixa de ser a leitura padrão.** Os parágrafos longos continuam no CHANGELOG.md e atrás de "ver changelog". A checagem não descarta assunto depois do vigésimo. A mesma lista sai no `brain update --check`.

## 2.52.0 — a suíte roda em paralelo e uma thread do OAuth deixa de vazar

- **`scripts/dev/run_tests.py` roda a suíte em paralelo** (só stdlib, um worker por CPU; `-j N` muda; aceita prefixo de módulo, classe ou teste). O CI passa a usá-lo. O resultado é o mesmo do `unittest discover`, em bem menos tempo.
- **O fluxo OAuth do Google não deixa mais uma thread rodando.** A thread que atende o redirect seguia até `wait_s` (300 s) depois de a função voltar. Agora `stop` a encerra no `finally`.
- **Os testes pararam de se atrasar uns aos outros.** Aquela thread, com um servidor falso, virava laço ocupado e travava o que rodasse depois no mesmo processo. A instância demo dos testes de TUI é montada uma vez por processo e copiada, em vez de remontada a cada teste.
- **Um teste que não testava nada foi corrigido.** `WatchdogShTests` procurava no `watchdog.sh` texto de uma implementação que já tinha saído de lá. Falhava em quem tem zsh e o CI o pulava.

## 2.51.0 — o ícone do Dock não troca a página

- **O clique no ícone traz a aba, não recarrega.** Se a ponte já está no ar, o Dock só ativa a aba do Brain. A página em que o dono estava continua. Sem nonce, sem URL nova.
- **Ponte que subiu de novo entrega o token sem apagar a rota.** O fragmento que sobra depois do token é a página, não vazio. Sem aba, ou sem rota, abre no Início.

## 2.50.0 — o texto da sugestão aparece formatado, e o rascunho do agente espera leitura

- **A aba Sugestões mostra o texto que sobe, formatado.** Título com a tag, molde e rodapé entram no leitor de Markdown. Um `<script>` no texto aparece escapado. O hash do texto fica ao lado do link da issue.
- **Rascunho do agente espera leitura.** Enquanto o dono não publica, a aba e a TUI marcam "aguardando leitura". O `brain doctor` avisa o mesmo.

## 2.49.0 — o sync avisa se o texto no GitHub divergiu

- **O sync avisa se o GitHub divergiu.** `feedback sync` compara o corpo da issue com o texto que o Brain enviou. Se alguém editou lá fora, o evento marca a divergência. A aba Sugestões e a lista da TUI mostram o aviso. Sem corpo na resposta, não acusa.

## 2.48.0 — o ok de uma sugestão fica amarrado ao texto que subiria

- **Aprovar uma sugestão grava o texto exato.** `feedback approve` guarda o hash do título com a tag e do corpo com molde e rodapé. Depois desse ok, `feedback push` publica sem pedir o ok de novo, mas só fora do agente e do noturno. Se o texto mudar depois, o push recusa até um novo ok. Sem aprovação nenhuma, o push mostra o texto e para, e diz os dois comandos que fecham a publicação. Uma pré-checagem que falha (token, texto público) não grava o ok. O lote `brain add` não forja esse ok. O clique no painel continua publicando o texto que está na tela. A aba Sugestões mostra o título e o corpo finais, não só o rascunho cru.

## 2.47.0 — os cartões do TODO filtram o quadro

- **A visão geral do TODO filtra.** Clicar em Atrasadas, Vencem em 7 dias ou qualquer outro cartão deixa no quadro só esse recorte, nas colunas de sempre. Outro clique soma. Clicar de novo tira. "Limpar filtros" volta ao quadro inteiro. O filtro se junta ao de projeto, vista e ordem. Cartão selecionado fica marcado; os outros esmaecem enquanto houver filtro. Enter e Espaço alternam, e o estado é anunciado.

## 2.46.0 — o push não chama falha de git de dado pessoal, e o diálogo de atualização cabe na janela

- **Falha do git na varredura não é dado pessoal.** Se o git falha ou estoura o tempo no meio do `upstream scan`, o comando sai com código 1. O hook diz para corrigir o erro acima e tentar de novo. Código 4 continua só para achado de verdade. Quem usa o git direto no `update` não muda.
- **O diálogo de atualização cabe na janela.** Título e botões ficam visíveis. Só a lista de mudanças rola, dentro do diálogo. Rolar em cima dele não move a página atrás.

## 2.45.0 — o decisor local se instala sozinho, e o Brain religa o que estiver fora

- **Escolher Local instala o servidor.** Decisão → Local (wizard, painel ou CLI) instala o `hs-decide-1-flash` num venv próprio, sobe o `/v1/systemone` (MLX no Apple Silicon, vLLM no Linux com GPU) e só grava o slot depois de um julgamento de verdade. Sem Apple Silicon e sem GPU NVIDIA, a escolha é recusada e nada é instalado. Chave, modelo e URL não são pedidos: a chave local fica numa variável separada da `hsk_` da nuvem. Se o teste falha, o slot volta a desligado.
- **Trocar de Local não apaga a chave da nuvem.** O serviço para e sai do gerenciador; os pesos ficam. A chave `hsk_` que estava guardada volta para o lugar.
- **Abrir o Brain confere o stack.** `brain services ensure` sabe o que a memória exige (contêiner, LM Studio, decisor) e religa o que estiver fora, sem travar a abertura. O watchdog chama a mesma função e o setup o instala. O noturno só religa — não instala. A tela de Saúde mostra pronto, subindo ou falhou.

## 2.44.0 — no modo full, embeddings podem ficar na máquina

- **Embeddings locais no full.** O modo full deixa de exigir embeddings de nuvem. O LLM continua só na nuvem (assinatura ou chave); o bge-m3 do LM Studio volta ao cardápio, como escolha — o recomendado do full segue o de nuvem. Quem já usa o local no embed sobe para o full com ele pré-selecionado; um pedido que não nomeia embeddings cai no de nuvem.
- **O contêiner não sobe no escuro.** Com embeddings locais, o wizard, o `brain setup --only memoria`, o job do painel e o login de assinatura conferem o LM Studio antes de recriar o servidor. Fora do ar, o fluxo para e diz o comando que resolve. O watchdog não fica recriando um contêiner que morreria no boot.
- **A troca avisa o custo.** Trocar embeddings entre local e nuvem, nos dois sentidos, pede o `brain memory rebuild` antes de gravar. No full, esse rebuild reenvia o vault inteiro e paga a extração de novo.
- **O que sai da máquina fica dito.** Full com embeddings locais grava `cloud_llm` ligado e `cloud_embeddings` desligado. Wizard, painel, TUI e doctor dizem que os vetores ficam na máquina e o texto segue indo ao LLM. "Nada sai da máquina" continua sendo só do embed.

## 2.43.0 — o push passa pelo portão inteiro na máquina de quem mantém, e a `main` protegida

- **O hook `pre-push` roda o portão de dados quando a lista privada está na máquina.** Com a cópia da lista em `~/.config/brain/public-denylist` (ou no caminho de `BRAIN_PUBLIC_DENYLIST`), o push varre os commits que leva com os termos da lista somados aos da instância e barra o anexo fechado (zip, PDF, banco, binário) — o que antes só o CI barrava, depois de o branch já estar público. São os mesmos commits que o hook já varria: só o que o push leva, nunca o que o remoto já tem. A saída do push diz `com a lista privada desta máquina e o anexo fechado`, e cada achado sai com arquivo e linha, nunca com o valor. Lista ilegível, vazia ou com termo curto barra o push; `BRAIN_PUBLIC_DENYLIST=` (vazio) desliga para um push. Sem a lista, nada muda: toda outra instância segue só com as regras públicas.
- **A `main` protegida no GitHub.** A `main` só muda por PR, com o status `data-gate (status)` e os quatro `tests` verdes; push forçado e apagar a `main` são recusados, sem exceção. O repositório aceita só actions dele mesmo, e workflow de PR de quem vem de fora só roda depois que quem mantém aprova (`guides/development.md`).

## 2.42.0 — portão de dados em todo PR, e o CI preso aos runners do GitHub

- **Portão de dados em todo PR.** Todo PR e todo push na `main` passam pela varredura do `brain upstream scan` mais uma lista privada de termos (nome de empresa, de rede interna, o que o mantenedor nunca quiser ver lá), que mora num segredo do repositório e nunca vai ao código. O portão é um workflow próprio (`data-gate.yml`), pelo evento `pull_request_target`, com o workflow e os scripts da `main`: o PR não consegue enfraquecer o próprio portão, e o job não executa nada que venha do PR. O job não tem `if:` — nunca fica "skipped", que o GitHub conta como sucesso — e publica o resultado como status de commit `data-gate (status)` na ponta do PR. É esse status, nunca o check `data-gate`, que a proteção da `main` exige: o check casa pelo nome, e um fork consegue emitir um igual; status de commit pede token de escrita, que PR de fork não tem. No push da `main` o portão é alarme, não bloqueio: roda depois que o conteúdo já está público, e com o workflow do próprio push. Sem a lista ele falha — e lista toda em comentário ou com termo curto demais também é erro, não "limpo". O status nasce `pending` no primeiro passo do job, antes de qualquer checkout, e o último passo o troca por `success`, `failure` ou `error` — sem o script, quando o checkout da `main` falhou: o GitHub só exige status e check de mesmo nome quando os dois existem, e até lá bastaria o check que um fork emite. A imagem do job é fixada por digest. No CI nenhum achado sai com caminho — nem o da lista privada, nem o das regras públicas: o log é público, e quem abre PR de fork escolhe os nomes de arquivo; da lista privada sai um bit por execução (ao menos um termo aparece), das demais regras só os nomes. Na máquina de quem mantém, `--detalhes` diz onde (`scripts/dev/public_gate.py`).
- **A varredura lê o que passava direto.** Nome e e-mail de autor e de quem commitou entram como dado: são metadados, não passam pelo diff. De e-mail que o repositório ainda não mostra entra só o domínio; identidade que já aparece num commit público não conta. Texto em UTF-16 e UTF-32 (arquivo "Unicode" do Windows e do Excel) é lido como texto, em vez de sumir entre bytes zero. Linha de diff com CR ou com quebra exótica no meio era cortada em duas, e a segunda metade ficava fora da varredura. Arquivo grande demais para varrer (mais de 50 MB), ou que a varredura não consegue ler, é achado — nunca "limpo" por tamanho. Termo colado em outra palavra (`<termo>_prod`, `<termo>VPN`) também conta, e linha de commit com endereço `noreply` é lida, só o endereço sai. Byte que não é UTF-8 numa linha de diff derrubava a varredura em vez de acusar. Texto em CP1252 (planilha em pt-BR exportada pelo Excel) é lido como texto. Nome decomposto (NFD, como vem do macOS) e nome com espaço a mais (dois espaços, tabulação) casam como o mesmo nome. O sufixo `-demo` isenta só o termo do ledger: `<termo da lista privada>-demo` é dado de empresa de verdade, e passava. Em binário, trecho legível do tamanho de um termo (4 bytes) entra — não só os de 6. Dado comprimido com zlib, que não tem assinatura fixa, agora é reconhecido como anexo fechado mesmo sem nome que entregue.
- **Anexo fechado é achado.** Zip, gzip, 7z, RAR, PDF e documento de escritório, cópia de banco e de arquivo (`.dump`, `.backup`, `.bak`; dump do PostgreSQL também pela assinatura), keystore (`.p12`, `.pfx`, `.kdbx`) e texto cifrado (`.gpg`, `.age`) que um PR acrescenta param o portão pelo nome ou pela assinatura, mesmo sem termo nenhum: o dado pode estar comprimido dentro, e a busca de texto não lê. Vale também para o anexo que o próprio PR adiciona e depois apaga — o blob continua no histórico. Imagem e vídeo não são bloqueados (o repositório os usa em ícones e na auditoria de interface): captura de tela com dado interno é revisão de quem mantém. Quem barra é o portão do CI; na máquina, `scripts/dev/public_gate.py` rodado à mão acusa o mesmo. O hook `pre-push` continua só com as regras públicas do `brain upstream scan`: sem anexo fechado e sem a lista privada.
- **Nenhum job em runner próprio.** O workflow do `pull_request` é o do PR: quem abre o PR escolhe onde o job roda. Num repositório público, um job desse evento em runner próprio entrega a máquina do mantenedor a qualquer fork — por isso os dois jobs rodam só nos runners do GitHub (`ubuntu-24.04`, máquina nova para cada job, gratuitos em repositório público), e `tests/test_ci_hardening.py` trava o `runs-on`. PR de fork roda a suíte como qualquer outro: o job não recebe segredo e o token do job é só de leitura.
- **A suíte roda sem o token do job.** O token (só de leitura) fica no passo do checkout, em `env` próprio, e o passo da suíte o tira do ambiente de vez. O workflow deixou de usar actions, mesmo fixadas por SHA: o checkout é git puro, o Python vem da imagem oficial `python:`, o `node` entra por um tarball com versão e checksum fixados e o `pip` só instala o que o `requirements` trava por hash.
- **Erro do portão nunca vira traceback.** Qualquer exceção que escape do portão vira erro dele (código 1). No CI sai só a classe da exceção — traceback no log público é a mensagem sem máscara, com o nome de arquivo que ela carregar; a mensagem só aparece com `--detalhes`, com termo da lista privada mascarado.
- **Molde de mudança de tela e molde de PR.** Issue `[UI]` com o estado atual, as variantes e a recomendação; PR com evidência e gates. A evidência (prints e vídeo) vai por um release rascunho, que só quem mantém o repositório abre (`scripts/dev/pr_evidence.sh`).

## 2.41.0 — TODO: coluna "Depois" para o que você adiou, e visão geral recolhível

- **Coluna "Depois", à esquerda do quadro.** Arrastar um cartão para lá adia a ação de propósito (`--park`, só o dono). Arrastar para fora, ou clicar em "↩ voltar", traz a ação de volta (`--unpark`, com o status da coluna onde ela cair). Ação que estava em "fazendo" volta para "a fazer" ao ser adiada. Bloqueada também pode ir para Depois.
- **O que está em Depois não atrasa.** Prazo vencido de ação adiada não entra em "atrasadas", nem em "vencem em 7 dias", nem na saúde do projeto, no índice (`brain query actions --overdue`) ou no roteamento. O cartão mostra a data apagada, sem ⚠. A ação segue aberta e continua em "abertas".
- **Visão geral no TODO.** Os cartões do quadro (abertas, atrasadas, vencem em 7 dias, fazendo, bloqueadas, depois, aguardando outros, feitas 14d) ficam no topo do TODO e seguem o filtro de projeto. Um clique recolhe tudo em uma linha, e o painel lembra a escolha neste navegador.
- **Um nome para cada coisa.** "Não agora" passa a se chamar **Depois** em todas as superfícies (CLI, TUI, `todo.md`, guias). A antiga vista "depois" (semana que vem em diante) agora se chama **Mais adiante**. A vista "não agora" do painel saiu, porque a coluna faz esse papel.

## 2.40.0 — o aviso de atualização checa o repositório a cada 2h e não afirma "em dia" sem ter conferido

- **Poll do upstream a cada 2h.** Um LaunchAgent opcional (`services/com.segundo-cerebro.updatecheck.plist`) roda `brain update --check` no login e de 2 em 2 horas. `update --check` passa a perguntar ao remoto de verdade, em vez de reaproveitar um cache de 24h; a validade do cache cai para 2h.
- **O noturno confere o upstream todo dia.** A checagem usava o cache de 24h: uma checagem feita de dia dispensava a da madrugada seguinte. Agora o noturno força a checagem e a faz antes do render final, para o painel da manhã nascer com o resultado de hoje, não o de ontem.
- **"Em dia" só com verificação recente.** O selo do painel e o doctor mostram "sem verificar" quando a última verificação tem mais de 4h ou falhou por rede, em vez de afirmar "em dia" por causa de um `behind: 0` antigo.

## 2.39.0 — o scan não cai com nome estranho, e o recall gravado não se desliga sozinho

- **Nome entre aspas com byte inválido não derruba o scan.** O git imprime esse nome entre aspas, com o byte cru lá dentro. A leitura quebrava a varredura inteira. O byte fica guardado e o arquivo entra na acusação.
- **Arquivo que a linha de comando não consegue nomear não sai como já público.** A pergunta do que já está no remoto não leva o nome na linha de comando. Se um nome não pode chegar ao git, a varredura abre mão do filtro em vez de pular o arquivo em silêncio. O conteúdo de um binário com esse nome é pedido no stdin, não no argv — senão o Windows lia o arquivo como inexistente e o segredo de dentro passava.
- **O recall gravado fica, quando o pedido não fala dele.** Regravar o slot de decisão sem mencionar o recall não desliga o decisor no recall nem regrava o reranker. Vale no formato aninhado e no plano. Um teto de candidatos que não é positivo, pedido com o recall já ligado, é recusado — não é gravado.

## 2.38.0 — as 12 issues abertas: painel, memória e os buracos de segurança que ainda estavam abertos

- **O fim do assistente abre a Home (#164).** O botão "Abrir meu Brain" troca o endereço para `#home` antes de redesenhar o painel. Antes a página continuava em `#onboarding` e o assistente reabria no último passo.
- **O token da ponte só entra no carregamento (#114).** Um `#t=` que aparece só no fragmento, sem recarregar a página, é descartado. Reaproveitar a aba no macOS força uma navegação completa (`?n=`), para o token novo entrar no boot e não ficar eterno na sessão.
- **Noturno e ações ⚡ sem shell livre (#101).** O Claude headless só lê e roda `./brain`. Flags de bypass (`--force`, `--yolo`, `--full-auto`) não sobem no noturno. A sessão interativa do dono não muda.
- **O noturno não aplica atualização (#107).** `brain update` no noturno ou no agente só pode checar. O doctor e o hook só rodam se o commit puxado é o que o fetch prometeu.
- **Agente não aprova no lugar do dono (#102, #109, #110).** Com `BRAIN_AGENT` ou `BRAIN_NIGHTLY`, gate e resposta de pergunta são recusados. Confirmar o formulário na TUI ou no painel continua valendo.
- **Instalador remoto só roda com sha256 (#141, #142).** Homebrew, mise, Docker e LM Studio são conferidos contra um pin antes de executar. Divergência aborta e aponta a receita manual.
- **Esforço padrão da memória é `high` (#159).** Claude Code e Anthropic novos gravam `high`, não `max`. Um `.env` que já tem `max` fica como está; o doctor avisa que difere do padrão.
- **Login manual aparece antes da escolha (#158).** ChatGPT, Nous e Copilot ficam no fim da lista, com o rótulo do que falta. Cursor sai do wizard (indisponível neste Docker) e o doctor não mostra verde sem login no servidor.
- **Decisor no recall e decisor local (#163).** O slot Decisão ganha `local` (nada sai da máquina) e, no provedor hospedado, a opção de julgar o recall — desligada por padrão, com teto de candidatos explícito no que o servidor pinado realmente lê. O recall local fica de fora até haver medição de latência.

## 2.37.1 — wizard: o seletor de Tipo na mesma caixa dos campos, e sem opção que o formulário não sabe preencher

- **Corrigido o seletor menor que o campo ao lado.** No passo "Fontes observadas", os seletores (Tipo e
  Janela) apareciam mais baixos que o campo de texto ao lado, com a seta e o texto fora do eixo: o
  navegador desenha `<select>` com o tema nativo do sistema e não respeita o padding de cima e de
  baixo. Agora seletor e campo têm a mesma altura e a mesma borda, nos dois temas (claro e escuro), com
  a seta desenhada na cor do tema.
- **Fora a opção "slack-dm · DMs e grupos do Slack".** Escolher esse tipo abria um campo com o rótulo
  "undefined" e descartava o que fosse digitado: o formulário do wizard não sabe preencher esse tipo
  (ele nasce pelo `brain watch add --kind slack-dm`, opt-in do dono). O Tipo só lista o que o
  formulário sabe preencher — e um teste guarda isso: tipo novo no servidor sem receita no formulário
  reprova até a decisão ser tomada de propósito.
- **Rótulo longo cabe inteiro.** A coluna do Tipo ganhou largura ("drive-doc · doc, planilha ou slides"
  aparece inteiro, em vez de cortado no meio da letra); quando o tipo não tem janela, Tipo e Key
  ocupam a linha inteira em vez de deixar um buraco à direita.

## 2.37.0 — o brief do dia vira cartão de verdade (#160)

- **Cartão "Seu dia" renderizado (#160):** o brief do agente deixa de aparecer
  em Markdown cru. Seção vira rótulo, lista vira lista, e cada id citado
  (`TASK-`, `DEC-`, `PROP-`, `ASK-`, `GOAL-`…) vira etiqueta com link para a
  ficha — o título e a situação (vence hoje, atrasada 3d, fechada, aguarda
  decisão) vêm do painel, não do texto. Mais de 3 seções ficam recolhidas atrás
  de "Mostrar tudo"; aviso de saúde vira link no cabeçalho para a tela de saúde.
- **Título e "(noturno)" fora:** a primeira linha `# Brief do dia — … (noturno)`
  não aparece (o cartão já tem data e horário) e a skill `/brief` passa a definir
  o formato — Markdown mínimo, sem linha de título, sem seção de saúde, ids
  soltos, gravado com `./brain note write brief --file`.
- **Notas do agente:** o painel renderiza `FRESH/notes/*.md` pelo mesmo caminho
  (o `/week` ganha seções e etiquetas) e o brief de hoje não aparece duas vezes;
  o de outro dia continua legível quando o cartão está quieto.
- **Entrada não confiável:** o brief é texto do agente, que leu a inbox. Tudo
  passa por `esc()` antes de qualquer marca; HTML, imagem, `javascript:`/`data:`
  e atributo vindo do texto nunca entram. Seção vazia não aparece nem conta
  para recolher. Regressão: `tests/test_panel_brief_render.py`.

## 2.36.0 — lote de polimento da interface (#95–#100)

- **Projetos no celular (#95):** o chip de motivo do goal ("↳ …") ganha linha
  própria no cabeçalho e mostra o texto inteiro — antes, em tela estreita,
  cerca de metade da informação ficava escondida no reticências.
- **Alvos de toque (#96):** os links de ação do feed (decidir/ver/revisar) e os
  chips de ID passam a ter 24px de altura — o mínimo confortável (WCAG 2.5.8).
- **Foco de teclado (#97):** navegar com Tab agora desenha o anel na cor do
  tema — o mesmo idioma do anel de seleção j/k — em vez do azul padrão do
  navegador, que não existe na paleta.
- **Tipografia (#98):** os textos secundários (`<small>`) computam 11,5px na
  escala tipográfica do painel; antes cada contexto rendia um tamanho
  levemente diferente (11,11px e 11,67px) por conta do fator do navegador.
- **Tipo de oportunidade (#99):** a ficha exibe "Melhoria de processo" em vez
  do slug cru "melhoria-de-processo" — no painel, na TUI e nos formulários. O
  slug continua sendo o valor no CLI e no ledger.
- **Polimento geral (#100):** padding dos cards por papel (listas 12px, brief
  destacado 14px, matriz 8px), o botão pequeno "declarar %" na altura do
  botão primário da mesma tela, as ações do feed com classe própria
  (`.feed-act`) e um aviso no console quando um chip recebe modificador fora
  do vocabulário — em vez de cair no estilo base em silêncio.

## 2.35.1 — wizard: trabalho que termina depois de avançar de passo não pinta mais na tela errada

- **Corrigido o erro fantasma na criação de goals.** A verificação automática de
  conectores continuava rodando depois de você avançar para o passo seguinte; ao
  terminar, tentava atualizar uma tela que já não existia e o erro vermelho era
  pintado em cima do formulário de goals e projetos — parecia que criar o
  entregável tinha quebrado. Nada tinha quebrado: era mensagem de outro passo.
- Agora cada passo do wizard carrega a sua geração de navegação: trocou de passo,
  a continuação do trabalho anterior continua no servidor mas não escreve nada na
  tela nova — nem erro, nem mensagem de sucesso, nem avanço automático indevido.
  A regra vale para a verificação de conectores, conexão do agente, memória,
  máquina e a proposta de planejamento com IA.
- O caminho bom segue intacto: quem espera no passo continua vendo o resultado
  chegar (status dos conectores, "✓ configurado", avanço automático).

## 2.35.0 — slot Decisão: o juiz rápido opcional que corta ~40% das chamadas do LLM

- **Quarto motor, opcional, desligado de fábrica** (só no modo full): **Decisão — juiz
  rápido**. Quem liga usa o `hs-decide-1-flash` da nuvem de inferência do Hindsight
  (US$ 0,02/1M de entrada, chave `hsk_` por uso, sem assinatura): o modelo de 0,8B
  treinado para os julgamentos internos (repete? muda? ajuda? é suficiente?) — o LLM só
  é chamado quando algo precisa ser escrito. Na leaderboard oficial corta ~40% das
  chamadas do LLM SUBINDO a qualidade (haiku-5.5: US$ 35→21 por 1k casos, 85.5→88.1).
- **Pular é o caminho normal**: sem chave nenhuma, tudo funciona como sempre e cada um
  paga só os tokens do próprio LLM — o padrão do wizard segue `Desligado`, com a chave
  opcional para quem o dono cobrir (a dele e a da equipe). No wizard, na Configuração ›
  Memória, no formulário da TUI e no CLI (`providers set decision --provider
  hindsight --key hsk_…`).
- O doctor fiscaliza: slot ligado sem chave = erro com o comando exato; desligado = ok
  informativo. Se o decisor cai, as operações voltam ao caminho só-LLM (perde-se a
  economia, nunca a operação) — e o recall segue com a fusão RRF de sempre.

## 2.34.0 — o runtime de contêiner também pelo Brain: instala e sobe sozinho

- **Mesma regra do LM Studio, agora para o OrbStack e o Docker** (ruling do dono):
  ativar a memória em qualquer modo traz o runtime de contêiner ao estado que o Brain
  precisa — no macOS instala o OrbStack pelo Homebrew (cask oficial) e sobe com
  `orb start`; no Linux/WSL instala o Docker Engine pelo script oficial (get.docker.com,
  baixado para arquivo antes de rodar) e sobe o daemon pelo systemd. Tudo narrado no
  log do passo; sem Homebrew o Brain para com a receita honesta em vez de adivinhar.
- **Três estados honestos para o OrbStack** na configuração guiada e no hub
  "Seu Brain" (pronto · instalado, parado — ativar sobe · ausente — o Brain instala ao
  ativar); instalado com o daemon parado nunca mais aparece como "falta — baixar".
- O doctor aponta `brain setup --only memoria` como o caminho que instala e sobe.

## 2.33.2 — o Brain instala e configura o LM Studio sozinho

- **A detecção do LM Studio deixou de mentir.** Quem já tinha o app instalado via
  "falta — baixar" só porque o servidor estava desligado — agora existem três
  estados honestos (pronto · instalado · falta) na configuração guiada, no hub
  "Seu Brain" e no doctor, cada um com a dica certa para o seu caso.
- **Ativar o modo Embed traz o LM Studio ao estado do Brain, sozinho** (você fica
  ciente, não executa): instala pelo instalador oficial quando não existe (no WSL
  não instala — lá o LM Studio mora no host Windows), sobe o servidor :1234, baixa
  o modelo bge-m3 (~635 MB, uma única vez — pelo espelho do Hugging Face quando o
  catálogo do LM Studio não resolve o nome) e o carrega. Tudo narrado no log do
  passo, ANTES de subir o servidor de memória — que valida as embeddings no boot
  e antes podia morrer na primeira subida com o LM Studio fora do ar.
- O guia de troubleshooting aponta `brain setup --only memoria` como o caminho
  que resolve tudo sozinho quando o recall falha.

## 2.33.1 — passos do wizard sempre à vista (nota da correção)

- **Correção de UI embarcada na leva 2.32.x**: a lista de passos da configuração
  guiada (modo primeira vez F8 do painel e rota `/onboarding`) escondia opções
  em janelas baixas — o container dos passos encolhia num rolo
  interno sem indicação (círculo cortado no meio, 8 dos 11 passos sumiam numa
  janela de 573 px). Os passos agora têm altura natural (`flex: 1 0 auto`, sem
  rolo interno): se faltar espaço, quem rola é a própria barra lateral; com
  altura normal, tudo cabe sem rolagem. Entrou junto com a leva 2.32.x; esta
  entrada apenas credita a correção no histórico.

## 2.33.0 — recomendações de modelo reais: leaderboard da Hindsight + preço de catálogo

- **Anthropic e Claude Code: Haiku 5.5 em TODAS as operações, esforço max** (régua do dono,
  superando o antigo cenário B com Sonnet nos mental models). A leaderboard oficial da
  Hindsight confirma: haiku-5.5 é a melhor qualidade acessível (88.5 all-ops com decide;
  14/14 idiomas no retain) e a 5.5 derrubou o preço em ~90% ($0.10/$0.50 até 100k de prompt).
- **Cada provedor com o modelo certo por valor**, não o default velho do servidor pinado:
  OpenAI `gpt-6-luna` (#2 geral, retain 95.8 @ $0.43/1k) · Z.ai `glm-5.3-flash` (#1 VALOR,
  $9.33/1k all-ops) · Gemini `gemini-3.1-flash-lite` ($0.25/$1.50 — a 3.8-flash custa 3-6×
  mais e é mais fraca na extração) · SuperGrok `grok-4.7` (idêntico em preço ao 4.6: ficar
  no 4.5 não economiza nada) · Fireworks DeepSeek v4.1-Flash mantido.
- **MiniMax entra no menu**: `MiniMax-M3.1-Flash` é o campeão de extração da leaderboard
  (retain 96.4, qualidade 98.8, $0.81/1k casos; $0.15/$0.60 o 1M de tokens).
- O esforço `max` vai como `HINDSIGHT_API_LLM_REASONING_EFFORT` no config/.env nas duas
  faixas Claude; o placeholder do campo Modelo segue mostrando o recomendado de cada um.

## 2.32.1 — modelo do LLM à mão: vazio = recomendado do provedor

- **Campo Modelo para todo provedor de LLM** (antes só OpenAI/custom): assinatura ou chave,
  o campo aparece com o placeholder dizendo o que o vazio aplica — `vazio =
  claude-sonnet-4-5-20250929`, `vazio = gpt-4o-mini`, `vazio = gemini-3.5-flash`… A tabela
  de defaults vem sondada da imagem Hindsight pinada no compose (a que você roda), com a
  cura do Brain na frente onde existe (Anthropic por operação, Fireworks deepseek-v4p1).
  Modelo digitado vence a tabela por operação do cenário B (vale para todas as operações).
- **Deixar em branco virou caminho de primeira classe**: `providers set llm --provider zai`
  sem `--model` não recusa mais — grava o default explícito no `config/.env`; o wizard
  também aceita Z.ai/OpenAI/Gemini sem digitar modelo (o assistente travava pedindo o que
  agora tem default). Custom continua exigindo modelo.

## 2.32.0 — assinatura sem chave na tela: botão Autenticar e memória vigiada

- **Provedor de LLM por assinatura não pede mais chave na tela.** Escolher `Claude Code
  (assinatura Pro/Max)` — ou `xAI / SuperGrok`, `ChatGPT`, `Cursor`, `Copilot`, `Nous` —
  no passo Motores faz o campo de API key sumir; no lugar nasce o bloco **Autenticar**,
  com o chip de estado (*autenticado* ✓ / *autenticar* ⚠). Vale no wizard do painel, na
  página Configurações › Memória e no formulário de provedores da TUI. Antes o campo
  aparecia — e o assistente ainda travava a ativação pedindo uma chave que esse tipo de
  provedor não tem.
- **O botão Autenticar roda o fluxo de verdade, narrado:** `claude-code` gera o token de
  longo prazo (`claude setup-token`) e grava direto no `config/.env` — nunca passa pela
  tela; `xai-oauth` sobe o servidor com o novo volume de credenciais e narra a URL do
  código de dispositivo para você aprovar no navegador. O mesmo fluxo existe no terminal:
  `brain memory auth claude-code` (ou `xai-oauth`).
- **A memória não morre em silêncio.** O access token o servidor de memória renova
  sozinho; o que pode expirar é o login raiz — e para isso o doctor agora aponta o erro
  com o comando exato, e o noturno abre uma tarefa no seu TODO ("Reautenticar a
  memória…") no mesmo dia em que a credencial fica pendente. Reautenticar é o mesmo
  botão (vira "Reautenticar") ou o mesmo comando.
- **Google Gemini esclarecido no menu:** não há faixa de assinatura do Google no servidor
  de memória — o Gemini (default `gemini-3.8-flash`) entra pela **chave do AI Studio**, e
  o rótulo do provedor agora diz isso. O Gemini também voltou ao cardápio do wizard
  (tinha sumido da lista reserva).

## 2.31.1 — passos do wizard sempre à vista

- **A lista de passos da configuração guiada usa a altura de que precisa**
  (modo primeira vez F8 do painel e rota `/onboarding`): em janelas baixas —
  celular em modo "site do computador", telas curtas — o container dos passos
  encolhia e escondia opções num rolo interno sem nenhuma indicação (círculo
  cortado no meio, nota logo abaixo do corte e meio painel vazio; 8 dos 11
  passos sumiam numa janela de 573 px). Agora os passos têm altura natural
  (`flex: 1 0 auto`, sem rolo interno): se faltar espaço, quem rola é a
  própria barra lateral — e com altura normal tudo cabe sem rolagem nenhuma.

## 2.31.0 — versão no rodapé, atualização pela ponte e frescor à vista

- **A versão mora no rodapé da barra lateral** (#62): no lugar da linha "gerado
  <data>", o rodapé mostra `vX.Y.Z · em dia` quieto — e, quando há atualização,
  `vX.Y.Z → vX.Y.W · N commits atrás` com destaque. O clique abre as Novidades
  (que enfim abrem: o modal nunca aparecia em tema nenhum — faltava a classe
  `open`), agora com a transição de versão, a contagem e a data da verificação.
- **Atualizar sem sair do painel** (#62): no painel vivo, o botão **Atualizar
  agora** roda o `update` como job da ponte (`/api/update`), com o log ao vivo
  (pull, templates semeados, doctor); no sucesso a ponte se reinicia sozinha
  **preservando o token da aba** e o painel recarrega já "em dia". Divergência
  (commits locais à frente) mostra o texto do próprio CLI com o caminho manual
  (`update --rebase`). No retrato aberto por arquivo, o botão vira "copiar
  comando". O `update` continua fora da allowlist do `/api/cmd`.
- **Frescor visível** (#57, parte 2): pílula no rodapé da barra lateral sempre
  mostra a idade dos dados ("dados de hoje" em verde; "há N dias" em âmbar) e o
  clique abre a Saúde. Passado o limiar (dump > 48h, render > 26h — limiares da
  própria telemetria, nunca constantes no JS), a home ganha faixa âmbar
  dispensável-por-hoje: "Última atualização há N dias — 'não consta' pode ser
  falso negativo", com [Atualizar agora] e [Ver saúde]. Instância podre não
  passa mais por saudável.
- **"Seu dia" na home** (#60, parte 2): o brief que a rotina diária deixa pronto
  em `FRESH/notes` aparece no topo da página inicial — chegar e já saber tudo,
  sem pedir nada. Sem novidades, uma linha honesta (nunca silêncio parecido com
  "não rodou"); sem brief de hoje, o aviso de que ele nasce após a rotina.
- **Suíte verde em qualquer ordem** (#63): o congelamento de relógio dos testes
  virou uniforme (todo módulo usa a data canônica) e um guard recusa regressão —
  quem precisar de outra data usa override por teste. Rodar a suíte em ordem
  não-alfabética não derruba mais testes irmãos.

## 2.30.0 — o wizard mora no painel: configuração e uso são o mesmo aplicativo (F8)

- **Primeira vez, mesma página.** O painel bootou em modo wizard: sem faces, sem ⌘K —
  a barra lateral vira a lista de passos (com grupos e progresso), a marca e o tema
  continuam os do painel, e "Abrir meu Brain" faz a transição para as faces **sem
  recarregar a página**. É o F8 do plano `onboarding-unification.md`, o último
  ponto de costura da 2.23.0.
- **A rota antiga `/onboarding` vira atalho** (302 → `/#onboarding`); o app e o
  `./brain open --setup` apontam para o modo. A página própria segue no repo como
  rollback documentado do plano.
- **O hub "Seu Brain" reconfigura sem recarregar** — "Rever boas-vindas" troca para
  o wizard no hash, na mesma página.
- **Retrato continua honesto:** painel aberto como arquivo mostra o aviso de abrir
  pelo app (regra das abas em modo leitura mantida).
- **Contratos pinados por teste** (`tests/test_onboarding_panel.py`): os três
  registros de passos — painel, página própria e `setup.WEB_STEPS` — falam a mesma
  língua; o view model carrega `onboarding.needed` e o `finish` apaga; a rota
  redireciona. Verificação de verdade: probe headless contra ponte viva — boot
  `bridge-live obmode` com os 11 passos renderizados, e retrato com o aviso.

## 2.29.0 — bootstrap do instalador: uma ação, a máquina inteira pronta

- **O `install.sh` deixou de verificar e desistir.** Máquina nova sem nada
  (sem git, sem Homebrew, só o Python 3.9 do sistema): o script instala o
  que faltar, silencioso e idempotente — git (Homebrew no macOS, gerenciador
  de pacotes no Linux) · mise · Python (o pin do `mise.toml`, nunca
  hardcoded) · runtime de contêiner (**OrbStack** no macOS, **Docker
  Engine** no Linux/WSL2). Segunda rodada é no-op. As portas do SO — senha
  sudo da sessão e a janela da Apple das Command Line Tools — continuam do
  sistema, com espera honesta; ao falhar, o script imprime a receita manual
  (`setup.md` §0–§1).
- **Contêiner é instalação; memória é configuração.** OrbStack/Docker entra
  pelo instalador; Hindsight e LM Studio continuam no passo Memória do
  wizard — são escolhas, não pré-requisitos. Falha no contêiner não bloqueia
  o Brain.
- **`doctor` ganha checagens de máquina** (git · mise · contêiner) — sempre
  aviso, nunca erro: docker ausente com memória ligada vem com o comando que
  resolve; com memória desligada, é só informativo.
- **README agnóstico de verdade:** some a lista de "requisitos que o
  instalador não resolve"; Claude Code deixa de ser requisito — qualquer
  agente (ou nenhum) serve, e o passo "Seu agente" conecta quem existir na
  máquina. O modo de memória "lite" virou "embed" no texto. Plano:
  `guides/plans/install-bootstrap.md`.

## 2.28.0 — o lote das issues #56–#61 (ativação, fila de revisão, assinaturas e rotina da manhã)

- **Importar histórico na primeira sessão (#56):** novo `brain seed folder <pasta>` — varre
  .md/.txt/.docx/.pdf, grava snapshots na inbox com a **data de captura original** (o mtime vira
  o nome e o carimbo do arquivo), lote retomável (`--limit`, padrão 30; rodar de novo continua de
  onde parou) e idempotência por hash (pasta já importada = silêncio). Recusa pasta dentro do
  vault (auto-ingestão) e deixa a extração para o `/dump` normal.
- **Fila de revisão (#61):** `brain review list` agrupa, num só lugar derivado do ledger, tudo o
  que espera o dono — propostas com evidência, rascunhos, publicações, perguntas, plano de foco e
  duplicadas — com uma contagem única (`review` no view-model) para painel e TUI. `brain review
  accept <id>…` aceita propostas **em lote com um confirm**, gravando um evento por item (falha em
  um não derruba os outros); portas (mensagem/publicação/foco) nunca entram em lote.
- **Memória full por assinatura (#59):** o slot LLM passa a aceitar **Assinatura** (Claude
  Pro/Max, ChatGPT, Cursor, GitHub Copilot, SuperGrok, Nous Portal — sem chave nova) ou chave de
  API; **LLM local saiu do menu do slot** (máquina pesada; extrator fraco polui). Doctor
  slot-aware: full com assinatura é válido sem chave no .env; embeddings seguem locais por padrão
  e reranker segue opcional — existe full com zero chave nova. `memory cost` marca assinatura
  como custo incluído no plano.
- **Recall com verdade no tempo (#58):** recall ganha decaimento temporal
  (`recall_half_life_days`, padrão 45; 0 desliga) para fatos de estado/configuração/compromisso —
  perenes (preferência, identidade, decisão) não decaem —, contradição marcada (o mais novo
  "vale", o velho aparece "supercedado", nada é apagado), supersessão explícita (`brain memory
  supersede`) e payload com âncora, data e proveniência: item sem âncora no vault chega como
  `[pista]`, nunca como fato. O hook renderiza `[memória · as of AAAA-MM-DD · prov]`.
- **Doctor que cura (#57):** `brain doctor --fix` (dry-run por padrão; `--apply` executa) com diff
  determinístico e quatro classes seguras — pid órfão da ponte, índice de busca velho, views
  velhas, memória dessincronizada; achados de gate viram sugestão com o comando exato, nunca
  auto-fix. Métricas de frescor (idade de dump/render/sync + backlog da inbox) no view-model para
  o painel anunciar a própria decrepitude.
- **Rotina da manhã (#60):** a sincronização diária passa a correr por padrão às **09:00**
  (horário do dono, configurável; quem já agendou mantém a escolha) e termina deixando o **brief
  do dia pronto** em FRESH/notes — uma linha quando não há novidade; `brain note write` grava
  narrativa derivada sem evento de dono (funciona no noturno).

## 2.27.0 — o lote das issues #32–#55 (engenharia + UI/UX do painel)

- **Índice SQLite rápido e confiável (#32, #34, #36):** escrita normal no ledger não refaz mais o
  índice inteiro — crescimento vira append incremental (o tail no offset antigo confirma que nada
  foi reescrito) e rebuild completo só quando o ledger encolhe ou a última linha mudou de verdade.
  Pesos bm25 corrigidos: título volta a levar 3× (o boost caía na coluna `kind` e o corpo pontuava
  zero). Leitores conferem frescor (`last_seq` × ledger) antes de usar o índice e caem na dobra ao
  vivo quando atrasado; falha da atualização pós-escrita ganha linha em `logs/index-errors.log` em
  vez de silêncio.
- **Instância e ledger resistentes (#33, #37):** `brain init` com `BRAIN_HOME` fora do clone semeia
  o vault a partir da raiz do framework (e avisa com os caminhos procurados quando não acha);
  referência quebrada no ledger agora vira `BrainError` nomeando seq/tipo/id + "rode
  ./brain validate" — e o `validate` segue reportando tudo com saída 4, sem traceback.
- **Ponte e subprocessos com limite (#35, #38):** a GC de jobs da ponte roda ANTES da checagem de
  "já existe em execução" — job de agente preso é expirado (rc 124) em vez de deixar as ações ⚡ em
  409 para sempre; o `proc.wait()` pós-EOF do agente herda o orçamento de timeout. pdftotext/
  pdftoppm (120 s), venv+pip (600 s) e abertura de OAuth (15 s) ganham timeout com `BrainError`
  nomeando a ferramenta.
- **TUI (#39, #40, #41, #42):** "Saúde online" da paleta executa `doctor --online` de verdade
  (itens `sys:*` chamam `run_sys` direto); alerta "não cabe: 0" some quando nada está em risco;
  o índice de duplicatas é cacheado por carga da store e a checagem por tecla ganha debounce de
  120 ms; checklist de higiene aplicado (bloqueadores múltiplos na ficha, `esc` só tira o filtro
  da aba em foco, auto-reload sem TOCTOU, código morto removido).
- **Painel — contraste e layout (#43, #44, #49, #50, #51):** pílula da face atual com tinta do
  tema e 12,5 px (6,05:1 no escuro); tokens de primeiro plano do tema claro escurecidos até
  4,5:1 em todos os pares texto×fundo (verificado por teste que calcula a razão WCAG); resumo do
  projeto com clamp de 2 linhas; telas de 500 px sem overflow lateral (grade do Foco com scroller
  próprio); alvos de toque ≥ 24 px nos botões pequenos e área expandida invisível nos links de
  pessoa.
- **Painel — comportamento (#45, #46, #47, #48, #52, #54):** agenda do Início e semana do Foco
  ordenadas por hora (não por id); datas ISO cruas viram dd/mm/aaaa; Ctrl K / ⌘K implementado com
  rótulo por plataforma; hierarquia de títulos h1→h2 sem mudança visual; portfólio standalone
  mostra travessão onde o recorte não traz a contagem (não mais zeros falsos); goals fora de
  "em dia" ganham mini-chip clicável com o motivo que salta até o projeto responsável.
- **CSS higiene (#53):** seletores e `@media` duplicados consolidados preservando a cascata, cores
  literais tokenizadas, tokens mortos removidos e escala tipográfica fechada em
  10,5/11,5/12,5/14/16/20/26 px.
- **Passo "Seu agente" agnóstico (#55):** os quatro agentes conhecidos aparecem sempre, com a
  detecção como selo ("detectado"/"não detectado") — conectar um não detectado devolve a receita
  manual — e o card "Outros harnesses" entrega os snippets MCP prontos (JSON, TOML e CLI) para
  qualquer ferramenta que fale MCP, marcando o passo como manual.

## 2.26.0 — o lote das issues #26–#31

- **Atalho de um clique + aba reaproveitada:** o passo "A máquina" do wizard ganhou a linha
  "Ícone no Dock" (macOS; `pin_shortcut` idempotente, tile `file-tile` bem-formado — um tile
  antigo sem `tile-type` é detectado e regravado) / "Atalho na área de trabalho" (Linux/WSLg,
  cópia executável do `.desktop`). E abrir o painel não espalha abas: a varredura de reuso
  agora procura a aba do Brain em TODOS os navegadores abertos (o padrão primeiro), não só
  no navegador padrão — nunca lança um navegador fechado.
- **Doctor/boot do Hindsight (#27):** `brain doctor` reconhece o estado transitório do container
  nos primeiros 3 minutos pós-boot (ou em restart-loop aguardando o LM Studio) e avisa em vez de
  errar "banco ausente"; o watchdog só aciona o `lms` se ele existir, espera até 30s pelo `:1234`
  e registra o que o `compose up -d` realmente fez (subiu/recriou vs "Running" sem efeito).
- **Operações falhas do servidor no doctor (#26):** o contador `failed_operations` do Hindsight
  entra no `memory status`/doctor — o level vira `warn` mesmo sem documento rastreado localmente e,
  quando o erro diz `No models loaded`, a causa é nomeada junto do comando que corrige (`lms load`
  no LM Studio ou `brain memory providers set llm …`).
- **Arrastar para a inbox (#28):** arrastar arquivo ou pasta sobre o painel vivo (`./brain serve`)
  mostra as zonas **Mover**/**Copiar** (estilo Telegram) e entrega em `vault/RAW/inbox/` pela ponte
  (`POST /api/inbox`: 50 MB por envio, sufixo `-2` em colisão, `.DS_Store`/`.keep.md` ignorados,
  noturno bloqueado). Sem a ponte, o painel avisa como entregar de outra forma; quando o navegador
  não deixa apagar o original, copia e diz isso na tela.
- **Fontes: ligar/desligar, agrupamento e slack-dm (#29, #30):** o `watch.toml` ganha `enabled`
  (padrão `true`; desligada é pulada no `/update`, no noturno e no `watch since`, e segue listada,
  esmaecida) e o novo `kind = "slack-dm"` com `exclude` — DMs e DMs em grupo do dono (recebidas e
  enviadas), um snapshot por conversa ativa, conteúdo só no vault. A aba Fontes (TUI e painel)
  agrupa por tipo, traz os problemas primeiro, alterna a ordem por último pull e liga/desliga por
  fonte (`x` na TUI, interruptor no painel — `brain watch edit <key> --set enabled=…`).
- **Autocompletar entidades nos formulários (#31):** campos que referenciam entidades (destino da
  mesclagem, bloqueios, pessoas) filtram ao digitar — número ou palavras do título/nome, sem
  acento/caixa — mostrando `ID · título` na TUI e no painel pela mesma especificação
  (`forms.filter_options`); confirmar a sugestão preenche o ID.

## 2.25.0 — o cérebro não gerencia memória de agentes

- **Decisão do dono (18/11, revogando a de 05/11):** memória de agente é concern do próprio
  agente. O cérebro **não cria, não aponta e não verifica banco nenhum** de Claude Code,
  Cursor, Codex ou Hermes — quem já tem memória configurada nunca mais tem o ponteiro
  reescrito por baixo (`~/.hermes/hindsight/config.json` e `memory.provider` ficam intactos).
- **Saiu:** `wire_hermes`, o instalador oficial via `npx`, o `~/.hindsight/coding-agent.json`,
  as chaves `[memory].harness_bank`/`harnesses`, `brain memory harness install|verify|remove`,
  o sub-passo "Harnesses" do wizard, a seção de harnesses da aba Memória (painel e TUI) e os
  checks de banco do doctor. **Migração:** configs antigas com `harness_bank`/`harnesses` são
  ignoradas sem erro; `recall_hook = "auto"` vira `false` (o hook liga explícito com
  `brain harness connect claude-code`); blocos do Codex escritos com o marcador antigo ficam
  órfãos — remova à mão se houver.
- **Ficou (não é memória):** o canal de LEITURA do cérebro nos agentes, agora com CLI própria
  e enxuta — `brain harness connect|disconnect|status <agente>` (MCP somente-leitura; no
  Claude Code também o hook de recall, flags `--no-mcp`/`--no-recall`). A detecção de agentes
  do onboarding ("Seu agente") usa a mesma máquina.
- **Guia novo:** *"Memória dos agentes: traga a sua"* (`guides/memory.md`) — a receita de como
  apontar CADA agente para o servidor que VOCÊ escolher, sem passar pelo cérebro.
- **Onboarding (feedback do teste real):** boas-vindas mostra o ícone do app (não a arte
  navy); a dica de conectores segue o agente escolhido; o almoço sai do wizard (tunável fino
  não se pergunta); token do GitHub com passo a passo (link com `public_repo` pré-marcado e
  `No expiration` sugerido); formulário de fonte se molda ao tipo escolhido.

## 2.24.0 — o lote das issues #21–#25: aprovação sem atrito, retratação e painel vivo

- **Confirmar já aprova (#21).** Nos formulários de gate do painel e da TUI (goal/projeto, promover
  oportunidade, aprovar mensagem, plano de foco, publicação, aceitar/rejeitar proposta) o campo
  "sua aprovação" deixa de existir: apertar "aprovar" é a aprovação, e a interface preenche
  `--approval`/`--quote` com `painel` ou `tui` — o ledger segue registrando a aprovação e a
  superfície de origem. Na CLI nada muda (o texto não vazio continua obrigatório) e o consentimento
  do modo full da memória segue digitado, por ser consentimento de nuvem.
- **O TODO não esvazia com "todas" (#22).** Marcado o filtro "todas (fechadas além de 14d)", a coluna
  Feita agora mostra as ações fechadas sem corte de data; desmarcado, mantém a janela de 14 dias.
  (O corte era recuada só com o filtro desligado — ligá-lo fixava o corte em hoje e esvaziava a
  coluna.)
- **Pessoas moram no Portfólio (#23).** No painel e na TUI, o cadastro de pessoas sai da face
  Execução e passa a morar no Portfólio, junto de Áreas, Processos e Documentos — mesmo
  agrupamento nas duas superfícies, com rota, busca e links preservados.
- **A porta de sugestões aprende a se corrigir (#24).** `brain feedback withdraw` retira um rascunho
  pendente (o dono qualquer; o agente só rascunho próprio, sem issue) — sai da fila, `push` recusa,
  `list --all` mostra o motivo. `brain feedback retract` retrata uma issue publicada:
  `--withdraw` comenta e fecha como "não será feita" (o agente pode sozinho em item que ele mesmo
  publicou, com evidência registrada — decisão do dono, opção B); `--correct` revisa o corpo e
  exige o "ok" do dono. No noturno nada chega ao GitHub: vira pergunta (ASK) e o doctor avisa das
  retratações pendentes. Textos de comentário e correção passam pelos mesmos guardas públicos.
- **O painel roda as ações do agente (#25).** Com `brain serve` no ar e runner configurado, os
  botões e atalhos "(agente)" (atualizar tudo, puxar fonte, processar inbox, brief…) disparam o
  mesmo caminho headless da TUI (`/api/agent` + `/api/agent/job/<id>`), com saída transmitida no
  console lateral, uma ação por vez (409 na segunda) e recusa no noturno. Sem ponte ou sem runner,
  o aviso de hoje continua — agora com o motivo.

## 2.23.0 — onboarding unificado: um cérebro, uma configuração

- **Um registro de passos, duas renderizações.** O wizard do navegador e o de terminal agora falam a
  mesma língua: `setup.WEB_STEPS` é a fonte única (id · título · grupo) e o `/onboarding` renderiza
  dela. "Você" e "Sua rotina" viram uma tela; a tela "Permissões" separada deixa de existir.
- **O wizard cobre a máquina inteira (o buraco do `curl | sh`).** Tela "A máquina": noturno, comando
  `brain` no PATH, TUI (ligada por padrão), foco `.ics` e regra de fetch/hook do framework — cada item
  um trabalho visível rodando em segundo plano, com log linha a linha. Quem termina o onboarding no
  navegador chega ao `doctor` sem pendências obrigatórias.
- **Tela "Seu agente" (antes dos conectores).** Detecta Claude Code, Hermes, Cursor e Codex na máquina;
  "Conectar" grava o `[runner].agent`, registra o MCP somente-leitura do cérebro e libera as permissões
  — como job, com cada passo aparecendo. "Fazer depois" cria uma tarefa com nome no TODO, não uma
  frase de ajuda.
- **Conectores sem Claude Code + fontes na tela.** Sem o Claude, ligar Gmail/Slack/Calendar continua
  valendo (as fontes é que provam) e as allow-rules ficam para quem as usa. Novo editor de fontes:
  botão "+" cria a fonte do `watch.toml` (tipo · key · janela · parâmetro) com validação na hora, e o
  × remove — o universo observável deixou de ser arquivo escondido.
- **Memória completa no wizard.** Os três modos na ordem que o dono escolheu — **apenas livro-razão**
  · **embed** · **full** — e os três motores (LLM · embeddings · reranker) com o registry inteiro de
  provedores, defaults "✓ recomendado", chave por slot, aviso de egresso para nuvem e fail-fast de
  chave antes de qualquer job. O modo full segue exigindo o aceite explícito.
- **O onboarding termina de verdade.** `finish` grava `onboarding.finished` no ledger e deixa a
  entrevista de profundidade como pergunta aberta (pessoas + fontes) — o `/init` passa a disparar por
  ela também, então quem onboardou no navegador não perde a conversa.
- **Entrada sem terminal.** `Abrir o Brain.command` na raiz do repo: duplo clique no Finder roda tudo
  (a janela que abre trabalha sozinha) e uma pasta baixada como ZIP do GitHub vira repositório git com
  origin configurado — o `brain update` funciona desde o primeiro dia.
- **Identidade visual única.** O wizard trocou o tema navy próprio pelos tokens do painel (claro e
  escuro, com o mesmo alternador) — configurar o Brain e usá-lo são o mesmo aplicativo agora.

## 2.22.0 — os canais do cérebro nos agentes e multi-instância de verdade

- **O cérebro alcança os agentes de código (#5, #20).** `brain memory harness install` registra, além do
  instalador oficial do Hindsight, os dois canais de LEITURA do cérebro: o hook de submissão de prompt no
  Claude Code (`.claude/settings.local.json`, via `perms.sync` — roteador, teto de 5 itens, abstenção) e o
  servidor MCP somente-leitura (`brain mcp`) no Claude Code, no Hermes (`hermes mcp add brain --command …
  --env BRAIN_HOME=… --args mcp`), no Cursor (`~/.cursor/mcp.json`) e no Codex (`~/.codex/config.toml`,
  bloco demarcado e validado). Toda sessão, em qualquer diretório, ganha consulta sob demanda — e nada do
  banco dos agentes vira fato do vault (a suíte segue cobrindo a separação). `--no-recall`/`--no-mcp`
  desligam um dos canais; `brain memory harness remove <agente>` (tecla `x` na TUI, botão no painel)
  desfaz o registro do hook/MCP e devolve `recall_hook` para "auto".
- **Hermes honesto (#19).** `wire_hermes` só registra o harness quando `memory.provider` fica de fato em
  `hindsight` (checando a CLI e o `~/.hermes/config.yaml`); a verificação e o doctor passam a conferir os
  canais de cada harness — hook, MCP, provider e, com `--online`, o plugin do Hermes — avisando o comando
  exato que corrige o que faltar. Sem CLI do Hermes no PATH, o resultado diz o que rodar em vez de
  declarar conectado.
- **Cada instância com o seu noturno (#9).** O agendamento no macOS usa rótulo `launchd` próprio por
  instância (`com.segundo-cerebro.nightly.<slug>-<hash8>`) e migra o plist legado apenas quando ele
  apontava para a própria instância; no cron, instalar/remover preserva as linhas das outras. O comando
  `brain` e o app Brain não trocam de instância em silêncio: setup e `brain app install` avisam quando já
  apontam para outra instância existente e só trocam com confirmação em terminal interativo (link
  quebrado se repara direto). O doctor de cada instância relata o estado do SEU noturno — inclusive
  quando o agendamento da máquina roda outra instância.
- **Varredura do upstream:** `/Users/marina-demo/…` passa a ser tratado como nome fictício declarado no
  cheque de caminhos de máquina (mesmo critério já usado para os termos do ledger).

## 2.21.0 — o lote das issues #5–#18: noturno honesto, hook de recall e TUI sem armadilhas

- **Noturno que não mente mais (#6, #7).** O agente headless é sondado no setup (interativo) e no
  `doctor --online` com um prompt mínimo — sem login, o dono vê o motivo e o comando que corrige. Quando
  o agente escolhido morre antes de produzir nada (sessão expirada, `Authentication required`), o noturno
  tenta o próximo da ordem automática (`[runner].fallback = true`, desligável); se ele já tocou no ledger
  ou na inbox, não há fallback — o erro sobe inteiro. O doctor mostra o passo e o motivo das falhas em
  vez de um "com falhas" mudo, e quem usa runner que não é o claude com fontes MCP no watch.toml recebe
  o aviso de que só o preset claude recebe as regras de leitura (limite documentado no guia).
- **O contexto do cérebro chega ao Claude Code (#5).** `perms.sync` registra o hook de recall
  (`services/hooks/recall_context.py`) em `UserPromptSubmit` do `.claude/settings.local.json` quando
  `[memory].recall_hook = "auto"` (default) e o harness `claude-code` está conectado — `true`/`false`
  forçam. O hook silencia no noturno (`BRAIN_NIGHTLY=1`), resolve a instância por `BRAIN_HOME` antes do
  cwd e sai em silêncio quando não acha instância. Hooks do dono e o `settings.json` versionado ficam
  intocados.
- **TUI sem armadilhas (#11, #14, #15, #16, #17).** Pousar em painel que a face não define e usar `?`
  ou `h/l`/`[ ]` não derruba mais o app; a tecla `s` volta a mover ação cujo bloqueador já foi fechado
  (só bloqueadores abertos travam, como o status derivado); `brain render` com falha após uma escrita
  vira aviso em amarelo ("FRESH e o painel ficaram velhos") em vez de linha de sucesso; o subtítulo dos
  painéis alinha à direita de verdade (via estilos, não atributo fantasma); o relógio do log segue o fuso
  da instância e o `BRAIN_NOW` dos testes; e um Select que fica sem opções (nenhum goal ativo, p. ex. no
  promover oportunidade) abre em "— escolha —" com o submit barrado — não explode mais.
- **Onboarding e instalador (#8, #13).** Sem o Claude Code na máquina, o passo Conectores conclui com o
  caminho (menciona o Hermes quando presente) em vez de job de erro; o rascunho de planejamento aceita
  qualquer agente configurado e cita o certo. O `install.sh` roda `mise trust` no clone novo antes de
  qualquer Python e, se o `init` falhar, imprime a correção exata em vez de abortar mudo.
- **RAW e memória (#10, #12, #18).** O nome do tipo é prefixo válido: `snapshot --prefix connectors`
  arquiva em `connectors/` (e o snapshot avisa quando um `--prefix` não classifica); arquivos
  `connectors-*`/`github-*` que caíram em `documents/` ficam fora do banco vetorial. O corpus não é mais
  relido e re-hashado várias vezes na mesma execução (`sync`/`status`/`doctor` pagam uma leitura só,
  por assinatura exata), `NO_LLM_CONFIG` existe uma única vez e `gemini` entra na lista do runner no
  wizard.

## 2.20.1 — hotfix: tecla m com a memória desligada não derruba mais a TUI

- **Correção.** Abrir o formulário "Memória: modo e provedores" com o modo atual `nenhuma` derrubava a
  TUI (IndexError no compose do FormModal): o cardápio de embeddings é dinâmico por modo e a tabela
  não tem chave `none` — o Select ficava sem opções. Agora a fonte cai no cardápio do embed quando o
  modo está fora da tabela (e o painel idem no forms.js), e o FormModal degrada para um campo inerte
  ("—") se alguma fonte dinâmica um dia devolver vazio — o formulário abre, nunca trava.
- Testes de regressão nos dois níveis: fonte nunca vazia (`test_forms`) e abertura real do
  formulário com modo none (`test_tui`).

## 2.20.0 — o fluxo da memória nas três superfícies: LLM · embeddings · reranker, lado a lado

- **Full com reranker no cardápio.** O passo Memória agora monta os três pares — LLM, Embeddings e
  Reranking, cada um com provedor + API key lado a lado (era provedor-provedor-chave-chave). Reranker:
  desligado (RRF, default) · Fireworks Qwen3-Reranker-8B · Cohere rerank-v3.5. Fireworks nos embeddings
  e no reranker usam a mesma conta — o fluxo avisa e reusa a chave; OpenAI de LLM e embeddings idem.
- **TUI tem o mesmo fluxo do painel.** Configurações › Provedores, tecla `m`: formulário com modo
  (nenhuma/embed/full), LLM (+modelo no OpenAI), embeddings pelo modo, reranker, as três chaves e a
  aprovação literal do full. Antes a TUI só tinha a troca por slot e o wizard em terminal suspenso.
- **CLI headless.** `brain memory setup --mode full --provider anthropic --embeddings fireworks
  --reranker fireworks --key … --emb-key … --approval ok` roda o mesmo wizard roteirizado do painel
  (provedores → compose → modo → bancos → health/llm). O noturno não liga o full (gate de egress).
- **Uma fonte para as três pontas.** `setup.validate_memory_setup` + `configure_memory` validam e
  rodam o mesmo fluxo para painel (job), TUI (formulário) e CLI; o wizard interativo segue existindo
  (`brain setup --only memoria`, tecla `w`).

## 2.19.0 — full é só-nuvem; o painel liga a memória sem LM Studio

- **Modos com cardápio próprio (decisão do dono).** `embed` aceita embeddings locais (bge-m3 no LM Studio,
  default) ou de nuvem; **`full` é só-nuvem**: o wizard não oferece `local` para embeddings (default Fireworks
  `qwen3-embedding-8b` @1536), o CLI recusa a troca para `local` no full e o doctor avisa instâncias legadas.
  Motivo: full com embeddings locais morria na checagem de boot do Hindsight em qualquer Mac sem LM Studio —
  o caminho recomendado era o quebrado.
- **Painel.** O passo Memória escolhe o provedor de embeddings por modo (embed: local/Fireworks/OpenAI; full:
  Fireworks/OpenAI), pede a chave de CADA conta (LLM e embeddings — OpenAI nos dois usa a mesma) e o LLM OpenAI
  pede o nome do modelo (não há default por operação; Anthropic segue o cenário B Haiku/Sonnet). Antes: full no
  painel sem LM Studio falhava no boot (Anthropic) ou morria no meio do wizard (OpenAI).
- **Verificação depois de ligar o full.** O wizard chama `health/llm` no banco ao terminar: chave ou provedor
  errado aparece na hora ("⚠ verificação do LLM falhou"), não no primeiro retain.
- **Recreate certo.** Os avisos de recriar o container (saída do `providers set` e a ficha do formulário) agora
  incluem o override do full (`-f services/compose.full.yaml`): recriar com o compose base religava
  `SKIP_LLM_VERIFICATION=true`, e um LLM morto virava falha silenciosa de extração.
- TUI e painel compartilham a ficha de provedores (`forms.py`) — a regra vale igual nas três superfícies.

## 2.18.0 — formulários iguais na TUI e no painel; o ícone reaproveita a aba

- **Uma especificação, duas pontas.** Os formulários da TUI e do painel HTML eram escritos duas vezes, à mão, e
  divergiam: campos, nomes, ordem, obrigatórios, o que aparece por tipo e a linha `brain …` montada. Agora todos
  (61) moram em `brainlib/forms.py` — a TUI desenha os campos a partir dali (`open_form`) e o painel recebe a mesma
  especificação no view model (`M.forms`) e monta o comando com o mesmo motor (`assets/src/forms.js`, que compila
  as mesmas regexes do Python).
- **O que mudou no painel** (passa a ser como a TUI): Fontes mostra só os campos do tipo (`drive-doc` pede o doc,
  `slack` o canal, `jira` monta a JQL pelo escopo e tira o site da URL) em vez do "Outros campos"; datas aceitam
  `sex`, `+3d`, `20/10` com a data resolvida ao lado; obrigatório tem `*` e bloqueia o confirmar com a mesma
  mensagem; entregável aceita só o número (`9` → `PROJ-1.9`); a lista `mine` preenche o dono com `eu`; nota rápida
  com vínculo validado; promover pede título, motivo e a sua aprovação; marcar entregável feito pede a evidência;
  "Superar decisão" usa `decision supersede` (como a TUI); cobrar e responder pergunta montam a mesma linha.
- **Correções de gate.** O painel pré-preenchia "ok" em aprovar proposta, publicação, editar goal/projeto e
  estrutura do plano, e o promover mandava `--approval "ok"` sozinho. Aprovação literal agora nunca vem preenchida,
  nas duas pontas (`tests/test_forms.py::test_gates_never_prefill_approval`).
- **O que a TUI ganhou do painel:** contexto na decisão, evidência na entrega, e-mail na nova pessoa, "destrava" na
  nova ação, "substituída por" ao superar decisão, sugestões (autocompletar) nos campos de pessoa, projeto e vínculo.
- **O ícone do app reaproveita a aba do Brain.** No macOS, `util.open_url` (o app, `brain open` e `render --open`)
  procura no navegador **padrão** — Safari, Chrome, Brave, Edge, Arc, Chromium, Vivaldi ou Opera — uma aba já aberta
  na ponte local (`127.0.0.1:<porta>`) e a traz para a frente em vez de abrir outra janela; se a ponte foi reiniciada
  (token novo), a aba recebe o token e recarrega na mesma rota. Só consulta navegador que já está rodando (nunca o
  abre à toa) e só o padrão (o macOS pede uma permissão de automação por app, na primeira vez). Sem permissão, sem
  aba ou em outro navegador (Firefox), abre como antes. Os testes interceptam `webbrowser.open`: nunca mexem nas abas
  do dono.
- **Painel com o mesmo ícone do Dock.** A barra lateral e o favicon do painel usavam a marca simplificada
  (`brain-mark.svg`, com dois nós por lado) e destoavam do ícone do app; agora usam o `brain.svg`, o mesmo do Dock.
  A marca simplificada segue só nos tamanhos de 16/32 px do `.icns` e no favicon do onboarding.
- **Trava:** `tests/test_forms.py` recusa campo escrito à mão fora do `forms.py`, exige que todo formulário abra
  nas duas pontas (ou diga por que não) e roda ~1.000 combinações de valores pelo Python e pelo node comparando
  comando, validação, dicas, listas e valor inicial. As coberturas da CLI (TUI e painel) passam a ler os comandos
  da especificação. `dates.py` sai de `tui/` (o painel usa a mesma regra); a ponte aceita `decision supersede`.

## 2.17.1 — o clone sempre sabe o que o upstream tem

- **Passo `framework` no `brain setup`.** Confere a regra de fetch do `origin` (`remote.origin.fetch`) e o hook
  pre-push, e conserta o que faltar (`brain setup --only framework`). Sem a regra, o `git fetch` comum só atualiza o
  `FETCH_HEAD`: o `origin/main` local fica velho e o `ahead/behind` do `update`, do `doctor` e da conferência antes
  do push mentem — o que parecia "o upstream não andou" era um espelho parado. Um `git clone` normal já traz a
  regra; ela falta em clones montados à mão.
- `brain init` (que o `install.sh` já roda) aplica o mesmo reparo, e o `brain doctor` avisa quando a regra falta.
  Uma regra que já existe, inclusive a de um clone de um ramo só, nunca é alterada.

## 2.17.0 — a configuração guiada mora na face Configurações

- **Um passo por aba.** A face Configurações passa a ter Visão geral, Perfil, Rotina, Conectores, Memória,
  Integrações e Saúde. Cada aba usa os mesmos endpoints da configuração guiada (`/api/onboard/*`): Perfil mantém a
  prévia antes de gravar o `profile.md`, Conectores verifica as conexões só quando você clica, e Permissões virou
  uma seção de Conectores.
- **Visão geral** é a primeira aba da face: a lista dos passos com `feito` ou `depois`, o progresso, "Rever
  boas-vindas" (abre o `/onboarding` do começo) e o atalho para Goals e projetos em Execução. `feito` vem do estado
  real (`onboard.state()["setup"]`), não da lista de passos vistos: passo pulado segue `depois` e não gera contador.
  O único contador da face continua sendo o da Saúde.
- **Memória:** o modo (nenhuma · embed · full) entra no topo da aba, acima dos provedores e harnesses. O onboarding
  também passa a chamar o modo leve de **Embed**, o mesmo nome da CLI e do `brain.toml` (a API aceita `lite` e
  `embed`).
- **O atalho "Configuração guiada" saiu da barra lateral.** O caminho de volta agora é a Visão geral.
- **Painel aberto como arquivo:** as abas novas avisam que a configuração se edita pelo app Brain (a ponte é quem
  grava).
- A primeira vez continua igual: `brain open` abre a configuração guiada enquanto ela não foi concluída.

## 2.16.1 — ícone que se vê no Dock e no painel

- **Ícone legível em tamanho pequeno.** O "Sinapse" detalhado (199 linhas de 4 px numa tela de 1024) virava uma
  mancha escura no Dock e na barra lateral. O ícone do app (`assets/icon/brain.svg`, e o `brain-512.png` gerado
  dele) agora tem traço grosso, fundo índigo→violeta e cinco nós por hemisfério. Até 32 px entra a marca
  simplificada `brain-mark.svg`: barra lateral do painel, favicon e os tamanhos 16/32 do `.icns`. A arte detalhada
  fica como ilustração da boas-vindas do onboarding (`brain-hero.svg`, rota `/brain-hero.svg`). Para ver o ícone
  novo no Dock, reinstale o app com `brain app install`.
- **Barra lateral do painel:** a marca é SVG embutido pelo `scripts/build_assets.py`, recortado no ladrilho, e o
  painel continua abrindo offline. O desenho visível passa de cerca de 20 para 30 px, e o "demo" ao lado do nome
  saiu.
- **"Configuração guiada" só na face Configurações.** Nas faces Execução e Portfólio o atalho parecia uma
  pendência. É o passo intermediário até a integração proposta abaixo.
- **Uma segunda ponte não deixa a primeira órfã.** `brain serve` numa outra porta sobrescrevia o registro
  da ponte do app e o apagava ao encerrar: a ponte principal continuava viva, ocupando a porta, e o app caía
  no retrato (sem comandos e sem o atalho da configuração guiada). Agora cada ponte só registra se não houver
  outra no ar e só apaga o próprio registro.
- **Proposta** `guides/plans/onboarding-in-settings.md`: a configuração guiada passa a morar na face
  Configurações, com um passo por aba, a Visão geral no lugar do atalho global e uma só identidade visual. Ainda
  não foi implementada.

## 2.16.0 — o app Brain: instalação e configuração guiada no navegador

- **App Brain.** O app (e o painel) passam a se chamar **Brain** — Segundo Cérebro segue como nome do framework.
  Ícone novo, o "Sinapse" (`brainlib/assets/icon/brain.svg`): no macOS o `.icns` é montado na instalação com
  `sips` + `iconutil` (vêm com o sistema); sem eles, cai no PNG de 512 px versionado. `brain app install` instala
  em `/Applications` (a pasta Aplicativos) quando a conta escreve lá, senão `~/Applications`, e remove a cópia
  antiga (`~/Applications`, nome "Segundo Cérebro") que ele mesmo criou.
- **Configuração guiada no navegador** (`/onboarding` na ponte local, `brainlib/onboard.py`): você · sobre você
  (prévia do PROFILE antes de gravar) · rotina · conectores (estado pelo `claude mcp list`, em segundo plano;
  ligar um conector libera só as ferramentas de LEITURA em `[runner].allow` e cria as fontes simples no
  `watch.toml`) · permissões (`.claude/settings.local.json`) · memória (nenhuma, lite, full — a API key vai direto
  para o `config/.env` e o full exige o aceite explícito do envio) · integrações (token do GitHub) · goals e
  projetos (texto e documentos entram na `RAW/inbox/`; o agente propõe a árvore; o dono aprova no navegador e ela
  nasce pelo gate do `brain plan`). Rotas novas com as travas da ponte (host, origin, token); o corpo nunca vai
  para o log; upload com nome saneado, tipo e tamanho limitados, só na inbox.
- **`brain open`**: o que o clique no app faz — a configuração guiada enquanto ela não terminou, depois o painel.
  O `install.sh` agora semeia a instância, cria o app e abre a configuração no navegador (o wizard de terminal
  `brain setup` continua para quem prefere e para IAs).
- **Sem id para inventar.** `brain init --owner-name "…"` gera o id do nome (`Marina Demo` → `marina-demo`);
  `--owner-id` vira opcional. O wizard de terminal pergunta só o nome. `doctor` aponta para `./brain setup`.
- A ponte relê o `brain.toml` a cada pedido (`config.reload`, que preserva `BRAIN_VAULT`/`BRAIN_CONFIG`): o
  onboarding e o painel mudam a config com a ponte no ar.
- A abertura do navegador passa por `util.open_url` (no macOS, `/usr/bin/open`).
- README revisado: portas conforme o `AGENTS.md`, comando de testes que o CI roda, instalação pelo app.

## 2.15.0 — mesmas teclas no TUI e no painel

- **Um verbo, uma tecla.** `d` descarta, remove, cancela, aposenta, desliga ou rejeita em toda tela (antes era `D`
  em Ações, `x` em quase tudo, `u` em Documentos, `r` em Propostas). `e` edita (Pessoas deixa de usar `u`),
  `T` alterna só abertas ↔ todas (Ações deixa de usar `a`), `L` liga documento (o `l` volta a ser só navegação
  de abas), `p` publica na aba Publicar (o `P` fica só para progresso), `r` é só render e `enter` só abre a ficha
  (responder pergunta é `a`). As teclas antigas `D`, `a` (Ações) e `u` (Pessoas) seguem valendo, escondidas, por uma versão.
- **Lacunas de paridade fechadas.** Painel: página **Fontes** (`n e d w`), página **Documentos** (`L d enter`),
  `L`/`v` em Oportunidades, `L`/`o` em Processos, `f` corrige o aviso em Saúde, `R` "quem é…?" em Pessoas,
  `T` em Perguntas/Mensagens/Sugestões, `N` nota em qualquer página, `E` mudar árvore, teclas do agente no Início
  (mostram o comando do chat) e `g`/`:`/ctrl+P como a paleta. TUI: `M` mescla ação duplicada e `` ` `` abre/fecha o log.
  A ponte do painel ganhou `doc link|unlink`, `watch add|edit|remove`, `opportunity evidence` e `person resolve`.
- `doctor.fix_for` passa a ser a única regra de "o que fazer com este aviso" (TUI e painel).

## 2.14.0 — ícone clicável do painel

- **`brain app install`**: cria o app **Segundo Cérebro** — clique duplo faz o
  `brain render --open` (regenera as views, sobe a ponte se preciso e abre o
  painel vivo), sem abrir terminal. macOS: `~/Applications/Segundo Cérebro.app`
  (Launchpad, Spotlight, arrastável para o Dock); Linux: entrada `.desktop`.
- Ícone desenhado em Python puro (PNG + `.icns` montados à mão): sem
  dependência nova e sem binário no repo. Se a abertura falhar, o app mostra um
  aviso e o detalhe fica em `vault/logs/app.log`.
- `--dest` (ex.: `~/Desktop`) e `--name` (várias instâncias). `brain app
  uninstall` só remove o que o próprio comando criou — recusa pasta de outro app.
- O wizard (`brain setup`) ganhou o passo **painel**: o modo interativo
  pergunta (padrão sim) e o `--yes` cria direto, como o passo `comando`.
  Refazer o passo (`--only painel`) é idempotente.
- O app guarda o caminho da instância e do framework: mudou a pasta, reinstale.

## 2.13.1 — o chat do Claude Code não pede mais licença

- **Sessão interativa pré-autorizada.** Antes só o agente headless (noturno e
  ações ⚡) tinha as ferramentas liberadas; o chat do terminal/app perguntava a
  cada `ls`, `cat`, pasta fora do cwd e MCP de leitura. Agora o repo traz
  `.claude/settings.json` (git, genérico): `Bash` inteiro, Read, Edit, Write,
  Glob, Grep, NotebookEdit, WebFetch, WebSearch e Task liberados, modo
  `acceptEdits`, e os limites da Constituição em `deny` — livro-razão, `.env`,
  `git push --force`/`-f` e `--no-verify`.
- **`brain agent permissions`** gera `.claude/settings.local.json` (gitignorado)
  com o que é da instância: MCP de leitura (`[runner].allow`), porta oppdrive,
  extras do `[tui].agent_allow` e `additionalDirectories` (raiz da instância,
  vault e pastas de repos do `watch.toml` — a sessão num worktree enxerga o
  vault). Roda sozinho em `init`, `agent allow`, `update` e no noturno; o
  `doctor` avisa se ficou para trás. `--check` só confere.
- MCP de **escrita** no mundo exterior continua fora: só pelas portas.

## 2.13.0 — `mine` é sempre do dono do Brain

- **Lista `mine` preenche o dono**: na TUI e no painel, escolher a lista `mine` põe o dono em `eu` (sair de `mine`
  limpa só o que era você). No ledger, `mine` sem dono grava o dono do Brain, e `mine` com outra pessoa é
  **recusado** ("é waiting"); ação nova de outra pessoa, sem lista dita, nasce `waiting` (antes herdava `mine`).
  Trocar o dono de uma `mine` pede mudar a lista junto (`--list waiting`).
- **"eu" vale o dono do Brain**: `eu`, `Eu` ou `EU` em `--owner`, `--people` e no JSON do `brain add`.
- **TODO do painel filtra pela lista `mine`**, sem exigir que você seja o dono (a TUI sempre foi assim): some a
  diferença entre as duas telas. Cartão de `mine` com dono antigo diferente mostra quem é; a paleta (`⌘K`) também
  fecha e marca "fazendo" essas ações. A semente da demo deixou de ter uma `mine` do Caio-demo.
- Dado antigo não é reescrito: `mine` com outro dono continua no ledger; editar a ação na TUI/painel já vem com
  `eu` preenchido e o comando mostra a correção.

## 2.12.0 — filtros em cascata (TUI e painel)

- **`/` empilha filtros**: o primeiro `/` filtra a lista; `/` de novo abre um filtro
  novo que refina **o que sobrou** do anterior, quantos você quiser. `esc` tira um
  por vez, o último aplicado primeiro (dentro do campo, `esc` desfaz só aquele
  nível). Enter com o campo vazio não cria nível. Cada lista (painel/aba na TUI,
  página no painel) guarda os seus.
- **Filtro à vista**: na TUI o título do painel mostra `⌕ filtro: a › b`, o rodapé
  diz `N de M · filtrado de T`, a lista vazia nomeia a corrente inteira e a barra
  de dicas ganha `esc tira filtro (n)`. Antes só aparecia no detalhe ampliado.
- **Painel HTML com a mesma tecla**: `/` agora filtra os cartões e linhas da página
  (antes abria a paleta), com a mesma cascata e o mesmo `esc`; uma barra no topo
  mostra as fichas de cada filtro (clicáveis para tirar), a contagem `N de M` e o
  "não consta". A paleta de busca e comandos segue em **⌘K** e ganhou o **`g`**,
  como na TUI. Na TUI, um id exato no 2º nível continua mostrando o que se liga a
  ele (dentro do que sobrou); no painel o filtro é por texto.

## 2.11.0 — molde das issues e validadores de dado sensível

- **Molde por tipo** para tudo que o cérebro publica no GitHub: `sugestao`, `bug` e `framework` (proposta de
  código aceita). Cada campo vira `### Título`, igual ao que os formulários novos de `.github/ISSUE_TEMPLATE/`
  (Sugestão, Bug, Proposta de código) escrevem — issue do cérebro e issue à mão têm a mesma cara.
  `brain feedback template --kind …` imprime o molde; o agente é obrigado a segui-lo (`--body-file`).
- **Validadores públicos** (`brainlib/publicguard.py`) em todo caminho que publica: pessoas e domínios do
  ledger, IDs do vault, **prints/imagens**, links externos e internos, e-mails reais, @menções, telefone,
  CPF/CNPJ, IP e IDs opacos do Drive/Slack. Recusam sem override e sem ecoar o valor (só tipo e linha).
  Exemplos usam sempre a padaria fictícia (`marina-demo`, "Padaria Pão Quente"). Guia: `guides/feedback-issues.md`.
- **`brain feedback revise FB-####`** corrige título/corpo de um FB que ainda não virou issue (evento
  `feedback.revised`; o ledger continua append-only) e liga o FB à proposta que o originou.
- `[feedback].allow_hosts` libera hosts extras em links do texto público.
- **Título padronizado**: `[Sugestão] …`, `[Bug] …`, `[Proposta] …` (proposta de código aceita). O **id local
  (`FB-####`) não sobe mais** — nem no título nem no rodapé da issue: é numeração da instância e geraria
  duplicidade no repo público. Tag escrita à mão é trocada pela oficial; o `push` recusa qualquer id local no texto final.

## 2.10.1 — token do GitHub no setup

- **Setup › Portas** explica como criar o token da porta 7 (fine-grained: Issues
  Read and write no repo do framework; clássico `public_repo` para quem não é
  colaborador), valida o token e confere que o repo está visível e com Issues
  ligadas. O valor continua indo só para `config/.env`, mascarado.
- **`brain doctor`** avisa quando há sugestão (`FB-####`) na fila sem
  `GITHUB_TOKEN`, ou ainda não publicada.

## 2.10.0 — propostas de código viram issue + checagem de docs em lote

- **Proposta `framework`**: `brain proposal add --kind framework` é a proposta
  que muda o código ou a estrutura do próprio cérebro. Ela carrega o texto
  **público** da issue (`--issue-title`/`--issue-body`), que você vê ao decidir.
  **Aceitar = aprovar a issue**: o `proposal accept` registra um `FB-####` e
  publica no repo do framework (porta 7). Rejeitada, nada sobe; sem token ou
  rede o aceite vale e o `FB` fica `pendente`. O texto é barrado se citar IDs
  do vault (`TASK-…`, `OPP-…`) além das regras de dado pessoal de sempre. TUI
  mostra "Issue pública" na proposta.
- **`brain watch docs`**: lista as fontes `drive-doc` com o id e a última
  revisão lida (uma busca de metadados no Drive serve a todas) e, com
  `--revs`, diz quais ler (mudou ou nunca lida), quantas estão inalteradas e
  quais o Drive não devolveu. O `/update` passa a checar os one-pagers em lote
  em vez de uma fonte por vez.
- **Fonte `granola`** no `watch.toml` (reuniões e transcrições pelo MCP do Granola, um item por
  reunião) e o `/dump` as trata como reunião (`RAW/…/meetings/`).

## 2.9.2 — fechadas recentes sempre à vista na TUI

- **Paridade com a coluna "Feita" do painel**: na aba **Minhas** da TUI, as
  ações fechadas nos últimos 14 dias agora ficam sempre no fim da lista —
  antes elas só apareciam depois de apertar `a`, e sumiam de novo ao trocar
  de vista. O que foi feito fica visível sem caçar atalho.
- `a` na aba Minhas alterna **só recentes** ↔ **todas** (fechadas antigas e
  descartadas continuam só em "todas", como no painel). Nas abas
  Aguardando/Observando o padrão segue só abertas.
- Vistas de prazo (`v`) continuam só com abertas — a mesma regra do painel.
  Guia §8 atualizado.

## 2.9.1 — paridade CLI × TUI × painel (auditoria dupla)

- **Painel usa a ponte única**: todo gesto passa pelo `runCommand` — no modo
  retrato o comando copiado leva `--by owner` como no vivo (antes 12 atalhos
  copiavam sem, e um copiava uma linha que não era comando).
- **Fechar/reabrir no painel viram diálogo** com os campos da TUI (como foi +
  resultado, que vira entrega WIN; motivo) — tecla, ficha, arrasto e paleta.
- **Gates de verdade no foco**: aprovar pede a resposta literal, aplicar
  escolhe ics ou google (não mais `--mode google` fixo), planejar roda
  `focus plan --days` e o sync escolhe dry-run ou aplicar.
- **Porta 2 no painel**: aprovar mensagem mostra o texto exato e espera seu
  `enviar N`; cancelar cobre rascunho e aprovada, com motivo.
- **Guardas de estado**: mutação só em ação aberta (como a TUI), responder/
  aceitar/descartar só no que está aberto, publicar/descartar de OPP nos
  estados que fazem sentido; `s` numa ação bloqueada explica e não move
  (agora igual nos três: o status "bloqueada" é derivado do `blocked_by`).
- **Seleção respeitada**: outbox, feedback e cobrança agem sobre o item
  selecionado (antes o primeiro da lista).
- **Teclas da TUI no painel**: `v`/`O`/`a` no TODO (vista · ordem · todas),
  `G`/`P`/`S` em Projetos, `u`/`a` em Pessoas, `s`/`i` na Matriz, `c`/`x`/`p`
  na ficha de oportunidade, `a`-nova-opp no processo, `A`/`x` de publicação,
  `s`/`v`/`i` na Configurações › Memória e `o`-testar-online na Saúde
  (`doctor --online` entrou na allowlist do serve).
- **Saúde só na Configurações** em toda parte: o link antigo `#health`
  redireciona, a paleta lista as três faces + as páginas cfg, e o
  portfolio.html não lista mais páginas que não existem lá.
- **TUI**: `n`-nota no Resumo (paridade com o painel), rascunho com canal,
  e a régua de cobertura dos testes anda até a folha do argparse (os
  `memory models …` deixaram de escapar da checagem).

## 2.9.0 — provedores da memória + face Configurações

- **Provedores LLM · embeddings · reranker** (plano memory-providers.md): o wizard pergunta
  os três slots (recomendados — Haiku/Sonnet cenário B, Qwen3-Embedding/Reranker-8B na Fireworks —
  ou custom), o `brain memory providers show|set` grava sem wizard, e o compose injeta o
  config/.env (`env_file`). Chave só no .env, nunca no config/view/painel.
- **Face [Configurações] na TUI** (Execução · Portfólio · Configurações): Memória
  (Provedores · Harnesses) e Instância (Saúde — que saiu de Execução › 1). Wizard da memória
  abre num terminal suspenso (w); provedor muda por formulário (s).
- **Painel**: mesma face Configurações — stack atual, harnesses e formulário de troca
  (mesma linha da TUI/CLI, pela ponte do serve).
- **Doctor**: provedor de nuvem sem chave = erro; conexão harness↔Hindsight verificada
  (banco existe, recall responde, configs apontando para cá) com o comando que corrige.
- Reranker local segue reprovado (benchmark 2026-11-07, §4.2 do plano): default `off`/RRF;
  nuvem entra pelo menu, com o aviso de egress.

# Novidades — Segundo Cérebro

O que mudou em cada versão, em linguagem humana. Para atualizar: `brain update`
(ou `brain setup --only comando` se o `brain` ainda não estiver no PATH).
Mantido pelo dono do framework a cada remessa — veja `guides/commands.md` § upstream.

## 2.8.0 — 2026-11-06

- **Rubric do ICE — a metodologia de pontuação faz parte do Brain.** O que cada nota
  (1–5) significa em impacto, confiança e facilidade — critério, horas/proveniência/prazo e
  vínculo com as medidas de sucesso — mora num único lugar (`brainlib/ice_rubric.py`) e chega
  a todas as superfícies:
  - **CLI:** `brain opportunity rubric` (tabela plana, `--md`, `--json`); o erro de escala e o
    `score --help` apontam para ele.
  - **TUI:** o formulário do ICE (`i`) troca os campos livres por **dropdowns** com o rótulo de
    cada nota e a pergunta do eixo; apoio embaixo de cada campo mostra o critério completo e,
    com horas declaradas, a faixa sugerida (acima dela: aviso "vale a menor nota"). `?` abre a
    **Metodologia · ICE** por cima do formulário (esc volta com tudo preservado), e o comando
    "Metodologia ICE" da paleta abre a mesma tela. Sem as 3 escolhas, não confirma.
  - **Painel:** os mesmos dropdowns e apoio por nota; `?` (mesmo com foco no select), o botão
    "? orientações", o item da paleta e o link "metodologia" na Visão abrem a metodologia
    empilhada — esc fecha só a ajuda. A ficha da oportunidade (TUI e painel) passa a ler o ICE
    pelo rótulo de cada eixo.
  - **Agente e guias:** a triagem (`/opportunity triage`) pontua pelo rubric com fonte por eixo;
    o bloco "Como pontuar o ICE" do guia é **gerado** do módulo (um teste impede divergência);
    MCP `opportunity` aceita `rubric: true`.
  - O score continua I×C×F (1–125), calculado pelo CLI — mudou a orientação, não a contabilidade.

## 2.7.0 — 2026-11-05

- **Dossiê determinístico — `brain memory dossier <ID|alias>` (Fase 5)** — a página
  "onde estamos com X?" montada na hora da leitura: ficha viva do índice, decisões e
  entregas ligadas, e os melhores trechos da memória com as tags da entidade — todo
  parágrafo com fonte, nada pré-computado, nunca velho. Funciona até com a memória
  desligada (ficha + DEC/WIN). O `/person` e o `/project` ganham a "Leitura atual", e o
  `/ask` usa o dossiê quando a rota detecta a entidade. **Setup `embed` completo.**
- **Mental models (Fase 8, modo full)** — `brain memory models sync|refresh|list|show`:
  páginas vivas por goal, projeto e pessoa, criadas com o estado do ledger colado na
  pergunta-fonte, tags da entidade e refresh delta com intervalo mínimo de 24h; projetos
  que fecham saem sozinhos no próximo sync. Exige `full` + `mental_models = true` (o
  refresh usa a sua chave — meça com `brain memory cost`). Contrato validado ao vivo na
  1.2.0; o refresh completo se valida na instância real, com a chave.
- **Eval do conjunto-ouro (Fase 0)** — `brain memory eval`: roda ~60 perguntas curadas
  (`vault/eval/memory-gold.jsonl`, exemplo genérico no `template/`) contra roteador e
  banco, com recall@k, MRR, citação, itens injetados, abstenção e tokens por tipo —
  determinístico, sem LLM no julgamento. O agente propõe as perguntas; você revisa.

## 2.6.0 — 2026-11-05

- **O hook de recall do Claude Code ficou cirúrgico (Fase 4 do plano)** — cada mensagem
  recebe só o contexto da camada certa: pergunta de **estado** (`TASK-…`, "o que está
  atrasado?", título de projeto) injeta até 3 linhas exatas do ledger e **nem consulta**
  o banco vetorial; pergunta **literal** ("o que foi dito", "exatamente", aspas) traz
  1–2 trechos de origem; **pessoa** junta ledger + contexto com a consulta expandida
  pelos aliases; o resto recebe até 3 itens de contexto. Teto de **5 itens** por
  mensagem e **abstenção**: nada relevante (corte 0.62) = silêncio.
- **Degradação com prazo** — a perna vetorial tem 700 ms de orçamento próprio; Hindsight
  lento ou fora deixa a perna do ledger responder sozinha. O velho comportamento (toda
  mensagem ≥12 caracteres virava busca semântica com até 8 itens) acabou.
- **`brain route "<pergunta>"`** — o mesmo classificador na CLI (o `/ask` passou a usá-lo
  antes de buscar). Configurável: `BRAIN_RECALL_ROUTE` (`off` | `ledger` | `embed`, padrão
  `embed`), corte, teto e prazo por variável de ambiente.
- Corrigido no caminho: nomes com hífen ("Marina-demo") agora casam nos aliases do
  roteador (o tokenizador cortava no hífen e a perna de pessoa nunca disparava).

## 2.5.0 — 2026-11-05

- **O banco de memória emagrou e ficou mais inteligente (Fase 3 do plano)** — o que
  entra no Hindsight agora é o que memória semântica resolve: **o RAW como está** (a
  letra exata) + **decisões e entregas como documentos curtos** (`ledger/DEC`, com
  projeto e quem decidiu). Artefatos do PROCESSED, páginas de ação/pessoa e
  PLANNING/PROFILE **saem do vetor** — busca por palavra já é do índice SQLite/FTS5,
  estado já é do `brain query`, e nada fica velho entre syncs.
- **Cada documento nasce com identidade** — tags do ledger (`pessoa:`, `proj:`,
  `goal:`, `sem-artefato:1`), **data do mundo** e **entidades por alias** (top-level,
  alimentando o grafo do servidor); os aliases das pessoas são registrados no banco no
  `memory setup`. O sha do documento cobre texto + identidade: alias novo ou `/dump`
  reprocessado ⇒ o documento reenvia sozinho com a identidade nova.
- **RAW sem `/dump` espera** — no `embed`, arquivo arquivado sem processamento espera
  7 dias (`degraded_after_days`) e então entra **degradado** (tag `sem-artefato:1`,
  sem entidades) — melhor ter a letra exata indexada do que não ter; quando o `/dump`
  processa, ele é reenviado com identidade plena.
- **Ao atualizar**: o próximo `memory sync` faz a limpeza por deleção sombra (os docs
  que saíram do corpus são apagados do banco) e reenvia os RAW com as tags novas —
  custo US$ 0 no embed. Não precisa de `rebuild`.

## 2.4.0 — 2026-11-05

- **Memória em banco único (`brain`)** — os dois bancos antigos do modo `embed`
  (`brain-raw` + `brain-mem`) viraram **um**, nos dois modos. Quem já usava roda
  `brain memory rebuild` e pronto: os bancos legados são apagados do servidor e o
  vault é reenviado (no `embed`, custo US$ 0). O doctor avisa enquanto houver bancos
  legados vivos no servidor.
- **Hindsight 1.2.0** — o servidor subiu de versão (pin por digest no compose). Entre
  outras: conserta a regressão que travava o reflect no Sonnet/Opus (mental models
  voltam a ser viáveis) e passa a validar o endpoint de embeddings no boot — **suba o
  LM Studio antes do `docker compose up -d`**. Máquina que já roda outro Hindsight no
  :8888 adota o servidor existente ou sobrepõe as portas por env (`HINDSIGHT_API_PORT`).
- **O servidor agora também guarda a memória dos seus agentes de código** —
  `brain memory harness install claude-code | cursor-cli | codex | hermes`: Claude
  Code, Cursor e Codex são cablados pelo instalador oficial apontados ao servidor do
  cérebro, o Hermes ganha a config local_external escrita pra você (o plugin em si
  pede confirmação interativa — o comando imprime a linha que falta). Memória dos
  agentes mora no banco próprio `hermes`, nunca tocada pelo `memory rebuild` e com
  proveniência por repo/harness. O wizard pergunta tudo isso no passo Memória, e o
  `brain memory harness verify` confere (banco, recall ping, configs).
- **Fresnness** — o `brain doctor --online` compara a versão do servidor com a última
  publicada lá fora (≤1×/dia, offline tolerado) e avisa quando há atualização —
  informação, nunca bloqueio. O caminho de atualização completo está no
  `guides/memory.md` (§ *Atualizar o Hindsight de versão* e § *Migração de instâncias
  antigas*).

## 2.3.0 — 2026-11-05

- **Promover oportunidade em qualquer nível** — `brain opportunity promote` ganhou `--level
  goal|project|deliverable`: a oportunidade pode virar um **goal novo** (`--level goal`), um
  **projeto num goal** (`--goal GOAL-#`, como antes) ou um **entregável num projeto**
  (`--project PROJ-#`) — as 5 oportunidades do mesmo processo agora cabem como entregáveis do
  mesmo projeto. Sem `--level`, o alvo decide: `--goal` ⇒ projeto, `--project` ⇒ entregável.
  O gate continua o mesmo: sem o seu "ok" literal, só o diff do `goals.md`. `em-andamento`
  continua nascendo só da promoção, de qualquer nível. TUI (`p`) e painel têm o seletor de nível.

## 2.2.0 — 2026-11-05

- **Plano com abas de status (TUI)** — o painel **[3] Plano** agora troca entre
  `Todos · Ativo · Congelado · Depois · Finalizado` (`[` `]` como em qualquer painel).
  A aba filtra goals e projetos pelo status: goal no status abre com todos os projetos;
  projeto no status aparece dentro do goal, como contexto. Cada aba mostra a contagem.
- **Status novo para goal/projeto: `depois` e `finalizado`** — além de `ativo` e
  `congelado`. `depois` é o que fica de lado por escolha (sai da saúde normal, sem
  alertar); `finalizado` é o encerramento (o antigo `fechado` continua valendo na
  entrada e nas linhas antigas do `goals.md` — o cérebro lê como `finalizado`).
  Vale na CLI (`brain plan edit … --status`), no formulário da TUI (`e`) e no painel HTML.

## 2.1.0 — 2026-11-05

- **Setup assistido (`brain setup`)** — o cérebro nasce com um wizard: identidade, rotina,
  comando `brain` no PATH, TUI, noturno, portas e memória. Re-executável, pula o pronto.
  Para máquina nova: `install.sh` (uma linha, do zero ao wizard).
- **Memória em dois modos — `embed` e `full`** — `embed` segue igual (dois bancos, zero
  LLM, nada sai da máquina); `full` é o novo modo com extração de fatos (banco único,
  sua chave de API, medidor de custo mensal). Trocar de modo é um comando, e voltar também.
- **Consultas de estado exatas (`brain query`)** — "o que está atrasado?", "o que a
  Marina me deve?" deixam de depender de busca semântica: um índice SQLite próprio
  responde com precisão, na hora, e o painel de busca usa o mesmo índice.
- **Hook mais calmo** — perguntas de prazo/atraso/ID agora recebem a resposta exata do
  livro-razão (até 3 linhas) em vez de trechos soltos de transcrição; o resto silencia.
- **Versão visível + aviso de atualização** — o número da versão aparece no canto do
  painel e da TUI, com aviso de atualização disponível e as novidades a um clique.
- Dezenas de correções de estabilidade na TUI, no painel, no serve e no lock do estado
  (ondas 2.0.x).

## 2.0.0

- A constituição v2: zonas, livro-razão único, portas estreitas com aprovação, IDs novos
  (`TASK-####`, `DEC-####`…) aceitando os antigos, TUI Textual, painel HTML offline,
  portfólio de processos e oportunidades, portas de foco/mensagens/publicação/backup,
  noturno e MCP somente-leitura.
