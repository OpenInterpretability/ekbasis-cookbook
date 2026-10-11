# Desvios do PREREG.md (sha256 dfbdbff8…d612)

## D1: o 32k não rodou no pipeline (bug), e rodou depois, por último

* **O bug.** A trava "estados de 64k ou mais em concorrência 1" do `run_long.py` comparava **caracteres** com 90.000.
  Os estados de 32k têm de 112.699 a 133.453 caracteres (~4 caracteres por token). Então o `run_long.py` recusou o 32k
  em concorrência 2 **antes de qualquer chamada**, e o pipeline seguiu para 64k e 120k. Não houve chamada parcial nem
  descartada.
* **A correção.** O limite passou para 200.000 caracteres: o maior estado de 32k tem 133k, e o menor de 64k, 242k. A
  cópia congelada está em `run_long.frozen.py`, e a única linha que muda é essa.
* **A execução.** O 32k rodou depois da 120k, com os mesmos estados congelados (`data/req_32k.jsonl`, hash no
  MANIFEST), os 184 itens e concorrência 2.
* **Efeito possível.** O tempo é outro (carga e cache do servidor), mas o veredito não depende de carga. Os estados e as
  perguntas são os registrados.

## D2: orçamento contado em tokens únicos

* **O que o prereg dizia.** Contava 50 M de **usage**, e o servidor cobra o estado uma vez por pergunta.
* **O que mudou.** Depois do congelamento, o "main" definiu que o teto vale em **tokens únicos**: o trabalho de GPU
  acompanha esses tokens, porque o prefixo do estado é reaproveitado entre as perguntas. Isso dá até ~94 M de usage.
  A execução do 32k usou `CTX_CAP=94000000`.
* **Consumo.**
  * Pipeline original: 49,41 M de usage, ~24,7 M únicos.
  * Mais o 32k: 61,18 M de usage no total, ~30,6 M únicos.

## D3: o 120k fica exploratório, com 65 de 184 itens

* A 120k parou na trava antiga de 50 M de usage, depois de 65 itens da ordem estratificada (`data/order_120k.txt`).
* O "main" aprovou os 184 a 120k desde que um adendo com hash fosse congelado **antes** da primeira chamada a 120k.
  Esse adendo **não foi escrito a tempo**, porque a sessão caiu às 15:26 UTC com o pipeline rodando. Também não foi
  criado depois com data retroativa.
* Como no prereg congelado, **a 120k é exploratória e não pode ser o teto**. Os 119 itens restantes não foram pedidos.

## D4: a pergunta, reenquadrada (texto, não método)

* Depois do congelamento, o "main" pediu para deixar explícito que isto é um **teste de capacidade do modelo** com
  estados longos: o fato decisivo diluído num contexto realista.
* O guard 0.1.17 mostra no máximo 8 tabelas e não monta estados assim. O resultado vale para o teto servido e para usos
  futuros (sessões longas no `intent_check`, PR inteiro, schema grande se o corte mudar).
* A ressalva 1 do §8 já dizia isso. Nada muda no método.

## D5: o secundário (`intent_check`) não rodou

O §7 exigia um adendo com hash próprio antes das chamadas, e ele não foi escrito.
