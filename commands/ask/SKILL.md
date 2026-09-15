---
name: ask
description: "Pergunta livre ao cérebro ('o que sabemos sobre X?'). Responde sempre citando a fonte do artefato e a proveniência; 'não consta' é resposta válida. Use quando o dono perguntar qualquer coisa que o cérebro possa saber."
---

# /ask — interrogar o cérebro

## Caminho de leitura (em ordem, pare quando bastar)

1. **Índices** (`_indices/`) — achar a entidade (aliases!) e a lista de
   artefatos que a mencionam.
2. **Artefato(s)** em PROCESSED — extrair a resposta com ID (A-/D-) e data.
3. **RAW** — descer ao original SÓ para a letra exata (página do PDF, minuto
   da transcrição, mensagem do Slack). Citar a âncora ao responder.

Nunca varrer RAW inteiro — o índice existe para isso.

## Contrato de resposta

```
<resposta direta, 1–3 linhas>

  · <evidência 1> — fonte: <artefato> (<data>) [<proveniência>]
  · <evidência 2> — fonte: <artefato> (<data>) [<proveniência>]

Não consta: <o que o cérebro NÃO sabe sobre a pergunta>
```

Regras:
- Proveniência sempre visível: "[observado]" (dito em reunião/canal) pesa
  diferente de "[doc]" (escrito em documento).
- **"Não consta" é resposta válida e frequente** — o dono confia no cérebro
  porque ele admite buracos. Inventar memória é o erro imperdoável.
- Se a pergunta é sobre fonte viva (doc do Drive, card), checar staleness e
  oferecer `/connect <fonte>` antes de responder com dado velho.
- Se duas fontes se contradizem: apresentar as duas com datas, não escolher.
