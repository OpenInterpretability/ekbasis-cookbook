# Adendo A1 ao pré-registro v7 (Rails): código rebaseado na 0.1.20, estados refeitos

Congelado em 2026-10-11, antes de qualquer chamada válida. Complementa `PREREG_v7.md` (sha256 `9858d296…f2e4`).
Amostra, procedimento de rótulo, critérios P1–P5 e regras de decisão **não mudam**. Muda só o código avaliado, e com
ele os estados enviados ao modelo.

## 1. Por quê

O commit congelado no PREREG 1.0 (`132fa58`, sobre o main `2498cdd`) é anterior a duas versões já publicadas:
* **0.1.19:** corte de esquema no `build_state` e MAX_CHARS de 200k;
* **0.1.20:** code probes, que acrescentam fatos ao estado e decidem "fails" em código.

Avaliar um código que não vai ser lançado não serve para decidir o merge. As 486 chamadas feitas sobre o código antigo
(teste 302, P5 184) foram **descartadas**; os detalhes estão em `DEVIATIONS_v7.md`, item 6. Elas não entram em
nenhuma análise.

## 2. Código avaliado

* **NEW = `rails-v7` `982612b`**, rebaseado no main **`4654485`** (0.1.20 + o limiar estrito do intent_check; vira
  0.1.21 no release, CHANGELOG em [Unreleased]). 283 testes passam, incluindo PostgreSQL e docker.
* **A regra só-esquema continua depois da resposta.** Em `_check_file`, a ordem é:
  1. sonda no esquema;
  2. probes (`probe_facts`); uma decisão delas retorna antes;
  3. `build_state` cortado;
  4. resposta do modelo;
  5. regra (`schema_only_plan`).

  A regra não interfere nas probes: elas cobrem INSERT, DELETE e UPDATE, e nenhuma dessas instruções é só-esquema.
* **Os estados foram construídos com o código de `migrations.py`, `probes.py` e `frameworks.py` idêntico ao de
  `982612b`.**
  * O replay do Rails (render, rótulo e insumos) rodou com `15ac9cb`, sobre a 0.1.19. O `frameworks.py` dele é
    idêntico ao de `982612b`, e o lado do rótulo não usa o produto.
  * Os estados finais saíram de `restate` com `9079841`, sobre a 0.1.20. Entre `9079841` e `982612b`, o pacote só
    difere em `intent.py`.

## 3. Teste Rails: estados refeitos

* **Build completo refeito com o produto rebaseado**, incluindo o replay dos históricos. Comparado ao build antigo:
  * rótulos: 0 diferenças;
  * exclusões e decisões: 0 diferenças;
  * SQL renderizado: 1 diferença, um timestamp de `Time.now` numa migração do Consul.
* **Insumos guardados por item** em `eval/data/inputs/` (dump do esquema base e estatísticas). A reconstrução a partir
  deles, sem probes, reproduz byte a byte os requests do build (`822fa940…`). Com as probes, ela dá os estados
  congelados.
* **O espelho do `_check_file` no harness** (`harness7.product_side`) agora roda as probes:
  * 2 itens passam a ser decididos em código ("probe_fails"); ambos são falhas reais;
  * nenhum item recebeu fato condicional.

| | Itens | Ao modelo | code_not_foreseen | Decididos em código |
|---|---|---|---|---|
| Todos (após 4 exclusões) | 343 | **300** | 36 | 7 (vazio 3, esquema 2, probes 2) |

* **Respondidas:** 307, das quais 119 arriscadas (115 perdem, 4 falham) e 188 benignas.
* **Regras R3∨F1 nos 307:** acurácia 0,730, recall 1,000, motivo 0,966, alarme falso 0,441 (inalterado).
* **Estados:** mediana de 2.585 caracteres, contra 3.486 antes do corte.
* **Observado no build, sem modelo:** dos 300 enviados, 216 são só-esquema (110 perdem, 106 ok, 0 falham). Nos 84
  restantes, 77 são ok, 5 perdem e 2 falham.

## 4. P5: estados refeitos, OLD = main `4654485`

* **Estados:** os das 184 do v3, construídos uma vez por item. O estado de OLD (pacote do main, carregado como
  `p5/oldpkg/ekbasis_old`) e o de NEW são gerados no mesmo banco, com as mesmas estatísticas, cada um com o seu
  `build_state` e as suas probes.
* **Assert do líder:** em cada item, o estado de OLD e o de NEW precisam ser **byte a byte iguais**, e a decisão das
  probes também. Item que divergir sai da análise e é contado à parte (`analysis_p5.py` imprime a lista).
  * Resultado no build: **0 divergências em 182 estados**.
  * Hashes por item em `p5/data/state_hashes_v3.jsonl`.
* **Itens:** 184. 2 são decididos pelas probes (iguais em OLD e NEW) e 182 vão ao modelo.
* **Rótulos:** a verdade é o rótulo **congelado do v3** (`pr_eval3/data/labels_v3.jsonl`). A reconstrução ressemeia,
  e o semeador não é determinístico: 1 item (`calcom/20260430000000_drop_instant_meeting_webhook_trigger`) saiu com
  `lost` diferente nesta reconstrução, e para ele vale o rótulo congelado.
* **Um único conjunto de respostas, aprovado pelo líder:** OLD é a lógica de veredito do main aplicada às mesmas
  respostas, e NEW é a do branch.
* **Critérios inalterados:** acurácia ≥ OLD − 0,02; alarmes falsos ≤ OLD + 3; recall ≥ OLD − 2; motivo ≥ OLD − 2.

## 5. Arquivos congelados (A1)

| Arquivo | sha256 |
|---|---|
| `eval/data/requests_v7.jsonl` (300) | `f249f85a6c042f59af2250210abe406a98fce14a920acc559110441c107d1267` |
| `eval/data/labels_v7.jsonl` (343) | `eb3c5bb9abee78f15a5fe4910bfb8767656d605b239b674cfc9e629b779fc45f` |
| `p5/data/requests_v3.jsonl` (182) | `6ddad53823b1ab3284287f36406ee666cdfae1ff34c4cf53d01430a9f69a784f` |
| `p5/data/labels_v3.jsonl` (184) | `2f2061ce796fda9db6b4af4d2eb0024a87c52eb47bb8f253bd4d638e31c0224a` |
| `p5/data/state_hashes_v3.jsonl` (182) | `cf04a0c4ac97c4e8ed8bf36a1e0947ff5506a1863ae43dddff59654a3cbca6fe` |

Scripts, itens, insumos e os pacotes NEW e OLD estão em `MANIFEST_A1.sha256`.

## 6. Procedimento

Igual ao PREREG 1.0: piloto de 10, depois o resto do teste, depois o P5. Concorrência 1, `instructions`, até 3
tentativas por item. O runner grava em `preds/` novos, e os descartados ficam em `discarded_stale/`.

**Antes do piloto:** `git fetch` e conferência de que o main não mexeu em `migrations.py`, `probes.py` ou
`frameworks.py` desde `4654485`. Se mexeu, paro e aviso o líder.

sha256(MANIFEST_A1.sha256) = a8ee20fde4d615af756b800c5e1c40595e4a7ef7544c48c0bc2edac26e48206d
NEW commit: 982612bed52cdef884b114cf4cefb2ff5301ea28
OLD (P5): main 46544855120d4db3bbfe692b12f67f0beaed9842
