# Auditoria de UI/UX — 2026-11-19

Achados da auditoria visual/estrutural das superfícies HTML (painel `dashboard` e
`portfolio` standalone), com screenshots **antes/depois** por issue. Os dois issues
sem pasta aqui (#48 headings e #53 higiene CSS) são estruturais — correção sem
variante visual.

**Todas as capturas vêm da instância demo fictícia do framework** (padaria
"Forno & Farinha", elenco `*-demo`) — nenhum dado real.

| Issue | Pasta | Variantes |
|---|---|---|
| #43 pílula da face (11px, 2,97:1 escuro) | `01-face-pill` | a: tinta invertida + 12,5px · b: pílula mais escura |
| #44 contraste tema claro | `02-light-contrast` | a: escurecer tokens |
| #45 agenda fora de ordem | `03-agenda-order` | a: ordem cronológica |
| #46 datas ISO × dd/mm | `04-date-format` | a: formato BR |
| #47 ⌘K anunciado e inexistente | `05-cmdk` | a: implementar Ctrl/⌘K · b: remover a menção |
| #49 truncagem da meta do projeto | `07-goal-meta-truncation` | a: clamp 2 linhas · b: envolver |
| #50 overflow em tela estreita | `08-narrow-overflow` | a: wrap responsivo (medido 718→500) |
| #51 alvos de toque < 24px | `09-target-size` | a: mínimos de 24px |
| #52 zeros enganosos em Pessoas | `10-people-zeros` | a: travessão |

Mockups são esboços de direção (CSS/payload/JS aplicados sobre a demo renderizada),
não patches prontos — a implementação real segue os moldes descritos em cada issue.
