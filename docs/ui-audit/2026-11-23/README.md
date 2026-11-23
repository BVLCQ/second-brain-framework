# Evidência UI/UX — issues #95–#100 (lote 2026-11-23)

Todas as capturas vêm da **instância demo** (`brain demo`, Forno & Farinha — conteúdo 100% fictício).
Nenhum dado real do vault aparece aqui. Medidas coletadas com sonda DOM em Chrome headless
(dump-dom + `data-r`), screenshot em `--headless=new`.

| Pasta | Issue | Conteúdo |
|---|---|---|
| `95-linha-entregavel/` | #95 | before + 3 variantes (clamp 2, quebra total, linha própria+clamp) + metrics.json |
| `96-alvos-clique/` | #96 | before + alvos visíveis 24px + hitbox invisível (::after) |
| `97-foco-teclado/` | #97 | before (anel UA) + accent claro/escuro + sombra + neutro |
| `98-microtipografia/` | #98 | before + escala 11,5px |
| `99-slug-tipo/` | #99 | before + rótulo humano no chip de tipo (payload mapeado) |
| `100-nits-varredura/` | #100 | before + escala por papel + uniformização densa |

Cada `metrics.json` traz os números crus da sonda (alturas, scrollWidth/Height, fontes computadas,
censo de padding/altura) para antes e por variante. Recomendações registradas nos comentários das issues.
