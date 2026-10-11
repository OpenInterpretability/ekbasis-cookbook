# Pré-registro v3: o veredito e o motivo do produto (decididos em código) numa amostra nova

Versão 1.0, congelada em 2026-10-11, antes de qualquer chamada a modelo desta avaliação. Desvios vão num adendo datado.

## 1. O que é avaliado

`ekbasis migrate-check` no commit **`b18bb43`** do branch `migration-guard` (PR #10). Desde o v2, a decisão passou ao
código:

* O arquivo é arriscado se P(falha) ≥ t_f, **ou** se P(perda) ≥ t_l, **ou** se falha no esquema da base (decidido em
  código).
* O motivo também é decidido em código, nesta ordem:
  * esquema: "erro do próprio PR";
  * falha: "may fail …; nothing in the file would be applied", mais "if it ran, it would also lose data" quando a
    perda passa do limiar;
  * perda: "may lose …";
  * ok.
* Uma migração que exige privilégios, ou cuja base está incompleta e que falha no esquema, vira cannot foresee: conta
  como arriscada (fail closed), com motivo errado.
* **Limiares congelados: t_f = t_l = 0,5.** São os do estudo e do v2. Não são retunados, porque escolher limiar nos
  dados de avaliação favoreceria o produto.
* As perguntas e o estado são os mesmos do v2. O v2 mostrou que o texto do estado no commit final é idêntico ao avaliado
  em 582 de 582 itens.

## 2. Amostra nova

* **Moldura.** É a mesma do estudo (`frame.jsonl`: enumeração, filtro de tamanho, sem a primeira migração, estratos
  A/B/C pelos mesmos padrões), **só com migrações nunca sorteadas** (fora das 599 do estudo).
* **Sorteio.** Semente `20261011:v3:<repo>`, com teto por repositório de A 16, B 8 e C 4. Saíram 192 migrações de 11
  repositórios.
* **kratos fica de fora.** O layout pop (uma migração em vários arquivos de dialeto) não é o que o produto descobre.
* **Exclusões.** São as regras do estudo. Só `untracked_rows` ocorreu, em 8 itens. Ficam **184 itens**: estrato A 84,
  B 63, C 37.
* **Execução.**
  * **Rótulos.** Vêm do executor congelado do estudo, em autocommit e em transação. O rótulo primário é
    `label_product`, o do regime que o produto declara: 160 arquivos em transação e 24 em autocommit.
  * **Lado do produto.** Usa o código do produto. O esquema é montado pelo papel sem superusuário, aplicando as
    migrações anteriores. A migração é sondada no esquema vazio, com as decisões em código do `_check_file` (nenhuma
    ocorreu: os 184 vão ao modelo). As estatísticas do planner vêm do banco semeado, que faz o papel de réplica.
* **Verdade.** "Arriscada" = `fails` ou `lost`. São 56 arriscadas (21 falham, 35 só perdem) e 128 benignas.
  * Motivo verdadeiro: "falha" se falha; senão, "perda".

## 3. Arquivos congelados

| Arquivo | SHA-256 |
|---|---|
| `data/requests_v3.jsonl` (184) | `ccd2c90c8ed0fa3dd7ff5397c1d0e55ff9f8d87b1185cf87e358fe4c8fcf2904` |
| `data/labels_v3.jsonl` | `0cb4470f1b8c831aae769717bcb08ff37e8546151b07bd69e0638a2180282486` |

Os hashes dos scripts (`sample_v3.py`, `build_v3.py`, `convert_v3.py`, `run_v3.py`, `analysis_v3.py`) e da amostra
estão em `MANIFEST_v3.sha256`.

## 4. Métricas e hipóteses de produto (confirmatórias)

**Linha de base:** regras, R3 **ou** F1, com motivo F1 → falha e R3 → perda. Calculada antes de qualquer chamada:
acurácia 0,696, recall 0,982, motivo exato 0,836, alarme falso em benignas 0,430.

**Referência retrospectiva** (não é hipótese): a lógica v3 sobre as respostas do A2 do v2 nos 582 itens antigos dá
acurácia 0,880, recall 0,915, motivo exato 0,898 e alarme falso em benignas 0,142. As metas abaixo foram fixadas
olhando esses números, com margem.

| | Métrica | Critério de "passa" |
|---|---|---|
| P1 | Acurácia do veredito arriscado/ok contra a verdade | ≥ 0,85, limite inferior do IC95 ≥ 0,80, **e** diferença pareada contra as regras com limite inferior > 0 |
| P2 | Exatidão do motivo, nos itens arriscados de verdade que o produto marca | ≥ 0,85 e limite inferior de Wilson ≥ 0,75 |
| P3 | Taxa de alarme falso nas benignas | ≤ 0,20, limite superior de Wilson ≤ 0,30, **e** menor que a das regras (McNemar exato p < 0,05) |
| P4 | Recall do veredito nas arriscadas de verdade | ≥ 0,85 |

* **Funcional (H7):** a Action rodou de ponta a ponta no commit `b18bb43`, antes deste pré-registro: 5 PRs com os
  vereditos esperados, 1 comentário por PR, chave ausente dos logs, e o PR hostil (COPY TO PROGRAM) deu cannot
  foresee. Fica registrado como verificação funcional desse mesmo commit.
* **Decisão: "produto pronto"** se P1, P2, P3 e P4 passarem.
* **Exploratório:**
  * resultado por estrato;
  * o motivo nas que falham e nas que só perdem;
  * quantos motivos a ordem do v2 (perda primeiro) acertaria;
  * custo e latência.

## 5. Procedimento

* **API.** Hospedada, chave de estudo, **concorrência 1**, Server-Timing gravado, até 3 tentativas por item.
* **Piloto de 10 itens:** só checa o encanamento. As respostas entram na análise, porque estado e perguntas não mudam.
* **Itens sem resposta:** contam como cannot foresee (arriscado, motivo errado).

## 6. Poder e ameaças

* **Tamanho.** São n = 184. A acurácia tem IC de ±0,05. O motivo é medido em cerca de 50 itens, com IC de Wilson de
  ±0,10. Os alarmes falsos são medidos em 128 benignas, com IC de ±0,06.
* **Rótulos sobre dados sintéticos.** Valem as mesmas ressalvas do estudo (NULL a 25%, FKs ao acaso).
* **Réplica.** É o banco semeado: as estatísticas são exatas sobre 20 linhas, e em produção seriam estimativas.
* **Amostra pequena por repositório** (hoppscotch tem 1, umami 2).

sha256(MANIFEST_v3.sha256) = aeeae3bf83c3a53c917b6841459e201a6e9cc534374ea5d954568721db0eaa87
product commit: b18bb43d9c88605f240c191af7525ed30217b519
