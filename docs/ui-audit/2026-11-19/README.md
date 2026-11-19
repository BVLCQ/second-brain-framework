# Auditoria de UI/UX — 2026-11-19

Achados da auditoria visual/estrutural das superfícies HTML (painel `dashboard` e
`portfolio` standalone), com screenshots **antes/depois** por issue e **variantes de
direção** (2–3 quando existem direções reais; 1 quando o conserto é determinístico;
0 quando não há nada visual a variar).

**Todas as capturas vêm da instância demo fictícia do framework** (padaria
"Forno & Farinha", elenco `*-demo`) — nenhum dado real.

| Issue | Pasta | Variantes |
|---|---|---|
| #43 pílula da face (11px, 2,97:1 escuro) | `01-face-pill` | a: tinta invertida + 12,5px · b: pílula mais escura · c: neutra com borda de acento |
| #44 contraste tema claro | `02-light-contrast` | a: escurecer tokens · c: cores dirigidas por elemento. **Beco sem saída testado:** clarear só os fundos não chega a 4,5 (chip "proposta" 2,92→3,06 — o fundo dele não é token; ver #53) |
| #45 agenda fora de ordem | `03-agenda-order` | única correção possível (ordem cronológica) — ordenação errada tem um conserto |
| #46 datas ISO × dd/mm | `04-date-format` | a: dd/mm/aaaa · b: dd/mm/aa · c: forma longa ("2 de fev de 2027") |
| #47 ⌘K anunciado e inexistente | `05-cmdk` | a: implementar Ctrl/⌘K · b: remover a menção |
| #48 headings h1→h3 | — | estrutural, sem variante visual |
| #49 truncagem da meta do projeto | `07-goal-meta-truncation` | a: clamp 2 linhas · b: envolver · c: "próximo" em linha própria |
| #50 overflow em tela estreita | `08-narrow-overflow` | a: wrap responsivo (documento 718→485 medido) · b: scroll contido no main (doc 485/500) · c: coluna única (485/485) |
| #51 alvos de toque < 24px | `09-target-size` | a: mínimos de 24px visuais · b: área de toque expandida invisível (contorno tracejado = anotação do mockup) |
| #52 zeros enganosos em Pessoas | `10-people-zeros` | a: travessão · b: ocultar colunas aparadas · c: "n/d" |
| #53 higiene CSS | — | estrutural, sem variante visual |
| #54 chip do goal sem motivo | `12-goal-chip-reason` | a: tooltip no chip · b: linha de motivo inline · c: mini-chip âncora para o projeto |

Mockups são esboços de direção (CSS/payload/JS aplicados sobre a demo renderizada),
não patches prontos — a implementação real segue os moldes descritos em cada issue.
Variantes de contraste (#44) e overflow (#50) foram verificadas numericamente
(sonda de contraste WCAG e `scrollWidth`); as demais, por conteúdo renderizado.
