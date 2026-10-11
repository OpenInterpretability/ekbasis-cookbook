# Pré-registro v7: migration guard para Rails, com Redis no gerador e "falha" decidida em código

Versão 1.0, congelada em 2026-10-11, antes de qualquer chamada a modelo nesta avaliação (teste e P5). Qualquer desvio
vai para `DEVIATIONS_v7.md`, datado. A sessão de trabalho foi interrompida uma vez antes do congelamento (item 1 do
DEVIATIONS); nada tinha sido sorteado, rotulado ou enviado ao modelo.

## 1. O que é avaliado

`ekbasis migrate-gen --framework rails` (atrás de `EKBASIS_EXPERIMENTAL_RAILS=1`) e `migrate-check --bundle --on-code
warn`, no commit **`132fa58`** do branch `rails-v7` (PR #23, draft; 0.1.19), que é o main `2498cdd` mais três commits:

* **Redis no gerador.** `--redis auto|on|off` (input `redis` da Action, padrão `auto`): um `redis:7-alpine` descartável
  na mesma rede interna sem saída do gerador, sem senha, sem porta publicada, removido no fim. `auto` liga quando o
  Gemfile (ou requirements/pyproject) depende de redis, sidekiq, resque, kredis etc.
* **"Falha" decidida em código** (`migrations.schema_only_plan`, código COMUM a todos os frameworks e ao SQL puro). Se
  a migração já rodou sem erro no esquema base (a sonda) e toda instrução só pode falhar por causa do esquema, P(falha)
  vira 0; a resposta do modelo fica em `p_fail_model`. Qualificam: DROP, RENAME, tabelas novas e seus índices, ADD
  COLUMN anulável ou com default, constraints e índices únicos em tabelas criadas na mesma migração, FK/UNIQUE em
  colunas recém-adicionadas anuláveis sem default, e o bloco `DO` de catálogo do `create_enum` do Rails. Não
  qualificam: DML, SET NOT NULL, mudança de tipo, constraints sobre linhas existentes, índices únicos/de expressão/
  parciais em tabelas existentes, colunas GENERATED.
* **Correção do renderizador Rails**: versões comparadas como inteiros (as migrações do Redmine têm zero à esquerda e
  saíam sem SQL).

Os itens do teste foram construídos com o commit `75db41f`; entre ele e `132fa58` o pacote `ekbasis/` só muda em
`shell.py`, `preflight.py` e `_version.py` (diff vazio em `migrations.py` e `frameworks.py`).

**Diagnóstico que motivou a regra (desenvolvimento, já visto).** Nos 5 casos do Maybe do v6 em que o produto disse
"may fail" para migrações que só perdiam dado, o modelo deu P(falha) entre 0,50 e 0,95 a migrações de DROP/RENAME que
já tinham rodado sem erro no esquema base; nada nelas depende das linhas. A regra corrige 4 dos 5; o 5º
(`reverse_transfer_relations`, INSERT…SELECT para um índice único) depende de dados e continua com o modelo.
Desenvolvimento com respostas antigas (sem chamadas novas): v6 Rails, motivo 0,825 → 0,925; v5, alarmes falsos 7 → 6;
v4, 11 → 10; v2 (582 SQL), 253 migrações só-esquema, 0 falhas reais entre elas, 9 falsos "falha" removidos; casos
reais (34), 5 só-esquema, 0 vereditos mudam (2 dos 5 falham já na sonda e continuam "schema").

## 2. Amostra de teste (Rails, projetos novos, PostgreSQL)

**Projetos** (histórico reaplicável do zero, verificado antes do sorteio):
* **Redmine** `fw/redmine` (Ruby 3.4): moldura 329, sorteados 82 (A 25 + 45, B 7, C 5; semente `20261011:v7:redmine`).
* **OpenProject** `fw/openproject` (Ruby 4.0.7): moldura 290, sorteados 85 (A 70, B 10, C 5).
* **Consul Democracy** `fw/consuldemocracy` `0f268cb` (Rails 8.0.5.1, Ruby 3.4.11, 606 migrações, todas reaplicam
  em 16 s): **ampliação** feita depois que o build do Redmine mostrou 4 arriscadas entre 58 respondidas, e antes de
  qualquer chamada: todo o estrato A elegível (165) + B 10 + C 5, semente `20261011:v7:consuldemocracy:ext`.

**Excluídos antes dos sorteios:** Chatwoot (o histórico para na migração 24 de 192, `ActsAsTaggableOn`), Loomio (540
das 1089 migrações herdam `ActiveRecord::Migration` sem versão, que o Rails 8 recusa), Discourse (post-deploy e
plugins; não tentado).

**Rótulos**, como no v6: o próprio Rails roda cada migração (`ctx.run(:up, version)`) numa cópia do banco de
progresso semeada com 20 linhas sintéticas; `lost` pelo snapshot antes/depois, `fails` pelo erro. O lado do rótulo
e o do produto alcançam o Redis da rede da avaliação (o produto agora tem Redis). Um boot do Rails por item
(DEVIATIONS item 4).

| | Itens | Ao modelo | code_not_foreseen | Decididos em código (vazio/esquema) |
|---|---|---|---|---|
| Todos (após 4 exclusões `named_table_not_seeded`) | 343 | 302 | 36 (10,5%) | 5 |

* **Respondidas** (tudo menos code_not_foreseen): **307, com 119 arriscadas** (115 perdem, 4 falham) e 188 benignas.
  Exigência do líder (≥ 50 arriscadas respondidas): cumprida.
* **Por projeto**, arriscadas respondidas: Consul 108 de 177, OpenProject 7 de 72, Redmine 4 de 58.
* **Cannot foresee por falha de render:** 0 (nenhum render falhou; nenhum por falta de serviço externo).
* **Observado no build, sem modelo:** dos 302 enviados ao modelo, 216 são só-esquema (110 perdem, 106 ok, 0 falham);
  nos 86 restantes, 4 falham, 5 perdem, 77 ok. Ou seja, no teste a regra só pode zerar P(falha) em itens que de fato
  não falham.

## 3. Arquivos congelados

| Arquivo | sha256 |
|---|---|
| `eval/data/requests_v7.jsonl` (302) | `ad51a2c273e2585b6202a6133581bb10c84064d15eef0c60749e63a578d7f21f` |
| `eval/data/labels_v7.jsonl` (343) | `d7435d6faf03f404a5accb31cf34263c7cde776fad188a24f310d91ad4fb0dc2` |
| `p5/data/requests_v3.jsonl` (184) | `0c608c79cbc876425266f06c1be888d606d33f32b8cdd1c718b484134e473630` |
| `p5/data/labels_v3.jsonl` (184) | `2d2b977085ab369c001b72c7d44932db052372acbc95c796adb989b6c6c80bb3` |

Scripts, itens, molduras e amostras em `MANIFEST_v7.sha256`.

## 4. Teste Rails: métricas e hipóteses (só nos itens que o produto responde)

**Linha de base.** Regras R3 ou F1 sobre o SQL renderizado, nos mesmos 307 itens, calculadas antes de qualquer chamada:
acurácia 0,730, recall 1,000 (119/119), motivo 0,966, alarme falso 0,441 (83/188).

| | Métrica | Critério de "passa" (o mesmo da v3 e do v6) |
|---|---|---|
| P1 | Acurácia arriscada/ok | ≥ 0,85, limite inferior do IC95 ≥ 0,80, **e** acima das regras (IC pareado > 0) |
| P2 | Motivo exato nas arriscadas marcadas | ≥ 0,85, limite inferior de Wilson ≥ 0,75 |
| P3 | Alarme falso nas benignas | ≤ 0,20, limite superior de Wilson ≤ 0,30, **e** abaixo das regras (McNemar p < 0,05) |
| P4 | Recall nas arriscadas | ≥ 0,85 |

Veredito do produto = o de `_check_file` com a regra só-esquema (`eval/analysis_v7.py`, função `product`), limiares
t_f = t_l = 0,5, transação "as Rails runs it". Item sem resposta após 3 tentativas conta como cannot foresee (arriscado,
motivo errado).

**Reportado sem critério:** fração de code_not_foreseen e a verdade dentro dela (10 perdem, 3 falham, 23 ok); recall
total contando code_not_foreseen como não pego (no máximo 119/132 = 0,902); **matriz de confusão do motivo**
(verdade falha/perde × dito falha/perde/cannot foresee) nas arriscadas marcadas; **cannot foresee por falta de serviço
externo** (0 no build); resultados por projeto.

## 5. P5: não-inferioridade nas 184 do v3 (a correção toca código comum)

* **Itens:** as 184 migrações SQL do v3, mesma amostra e semente, estados reconstruídos agora com o produto v7
  (`p5/build_p5.py`, cópia de `pr_eval3/build_v3.py` só com caminhos trocados). Rótulos idênticos aos do v3 (0
  diferenças).
* **OLD = main `2498cdd` (0.1.18), NEW = `132fa58`.** O estado e as perguntas são os mesmos nos dois: o diff de
  `migrations.py` entre eles só acrescenta código, aplicado depois da resposta. Por isso **um único conjunto de
  respostas, obtido agora no servidor atual (contexto 128k), serve aos dois braços**, e OLD/NEW são a lógica de
  veredito de cada versão aplicada às mesmas respostas (pareamento exato). Nenhuma resposta antiga é reaproveitada.
  Motivo de não rodar dois builds separados: dois builds independentes diferem em 57 de 184 estados só pelas frações
  de NULL do semeador (não determinístico nas tentativas), ruído que não tem nada a ver com a mudança.
* **Critérios (todos precisam passar):** acurácia NEW ≥ OLD − 0,02; alarmes falsos NEW ≤ OLD + 3 itens; recall NEW ≥
  OLD − 2 itens; motivo exato NEW ≥ OLD − 2 itens (`p5/analysis_p5.py`).

## 6. Decisão

Se P1–P4 **e** P5 passarem: PR tirando o Rails do `EKBASIS_EXPERIMENTAL_RAILS` (continua opt-in por `framework:
rails`). Se não: o Rails continua experimental, com os números na documentação. Se P5 falhar, a regra só-esquema não
vai para o main, independentemente do Rails.

## 7. Procedimento

* API hospedada, chave de estudo, perguntas com `instructions`, **concorrência 1**, Server-Timing gravado, até 3
  tentativas por item. A API divide GPU com a produção. Erros dentro de uma janela de reinício avisada são falha de
  infraestrutura: o item é refeito e registrado no DEVIATIONS.
* Ordem: piloto de 10 itens do teste (entram na análise), depois o restante do teste, depois os 184 do P5.
* Containers da avaliação (`ekeval7-*`, rede `ekeval7-net`) e o PostgreSQL local do P5 são derrubados no fim.

## 8. Ameaças

* **Concentração.** Consul tem 108 das 119 arriscadas respondidas, quase todas `remove_column`/`drop_table` que perdem
  dado. O teste mede sobretudo "perde" em migrações só-esquema, exatamente o caso que a regra mira; há só 4 falhas
  reais, então P2 quase não mede a direção "falha dita como perda".
* **Regra e rótulo no mesmo eixo.** O build mostra que nenhuma das 4 falhas reais é só-esquema; isso foi visto antes
  das chamadas, mas não muda a regra (congelada no commit `cef5b68`/`e00c984`, antes desta amostra existir).
* Valem as do v4–v6: dados sintéticos, rótulo literal de perda, renderizador Rails em esquema vazio (laços Ruby sobre
  linhas não enviam SQL; só viram code_not_foreseen quando reconhecidos por `rails_ruby_ops`).
* Semeador não determinístico em contagens (1–3 linhas em algumas tabelas, DEVIATIONS item 4); não muda rótulos nos
  itens comparados.

sha256(MANIFEST_v7.sha256) = a38bb9d573a269dba5f2f9cb669386febf43a262055938f876298349f0e2f6c5
product commit: 132fa58a4dcfd81b135e09e2d0475e921ae5587b
main (OLD in P5): 2498cddb9d90136c0dfc9f7d953f5dd85aa44e9c
