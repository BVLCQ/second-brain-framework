---
name: person
description: "Panorama de uma pessoa: quem é, histórico, threads abertas, o que cada um deve ao outro, última interação, card de prep de reunião. Use antes de reuniões e quando o dono perguntar sobre alguém."
---

# /person — alguém

1. `./brain person resolve "<nome>"`. Código 2 = ambíguo: mostre os candidatos e pare. Código 3 = não consta: ofereça cadastrar.
2. `./brain render` se `FRESH/people/<id>.md` estiver velho; senão leia a página.
3. No chat (card de prep):
   - quem é (papel, relação, aliases)
   - o que **essa pessoa deve** ao dono (`waiting`) e o que **o dono deve** a ela
   - decisões que ela tomou (quem/quando/fonte)
   - última interação (artefato mais recente)
   - threads abertas — não-ações, o que ficou no ar
4. Não invente tom nem "como ela gosta de ouvir". Se não consta, não consta.
