# Pré-registro: Ekbasis como guarda de merge para migrações de banco

Versão 1.0, congelada em 2026-10-10, antes de qualquer chamada a modelo. O sha256 deste arquivo vai no relatório ao
líder. `MANIFEST.sha256` fixa o código, a amostra e os rótulos que este texto descreve. Qualquer desvio depois daqui vai
para a seção "Desvios" de um adendo datado, e este arquivo não muda.

## 1. Pergunta e hipótese

Hipótese: o Ekbasis serve como **guarda de merge barata para mudanças com consequência**, aqui migrações SQL que perdem
dados ou falham no meio. Ele não serve como revisor de código geral ("os testes passam?", "tem bug?"); essa segunda parte
não é testada aqui, ver §8. A pergunta operacional: com os fatos decisivos escritos no estado (esquema, contagens,
NULLs, valores), o Ekbasis prevê melhor que regras de linter o que a migração vai causar quando roda num banco com
dados?

## 2. Tarefa, estado e perguntas (congelados)

* **Formato do estado.** É o layout `world_state` do cliente (`ekbasis.prompts`), o mesmo que o
  `preflight.check_sql` usa para SQL. A ordem é: regras, `Current state:`, os statements da migração como ações
  numeradas e a nota "The questions are about the state after all these actions." O texto exato sai de
  `statebuild.py` (constantes `RULES`, `QUESTIONS`, `world_state`).
* **Regras do estado.** PostgreSQL 16, statements em ordem em autocommit (BEGIN/COMMIT dentro do arquivo valem). Um
  statement que falha não muda nada, e o próximo roda mesmo assim (semântica do `psql -f`).
* **Conteúdo do estado.** É construído do banco **semeado, antes de a migração rodar**, sem ler nada da execução.
  Entram:
  * o DDL (colunas, tipos, NOT NULL, DEFAULT, constraints, índices) das tabelas que a migração nomeia e das ligadas a
    elas por FK, no máximo 8 tabelas;
  * os enums usados;
  * por tabela: número de linhas, 2 linhas de exemplo e fatos por coluna (quantos NULL, quantos valores repetidos,
    contagem de valores para colunas com até 4 valores distintos fora de texto, maior comprimento de texto);
  * quantas linhas batem com cada literal que os statements comparam (`WHERE slug = 'x'`, `id IN (...)`);
  * as demais tabelas, só com a contagem.

  Os comentários SQL são removidos de tudo. O Prisma escreve "All the data in the column will be lost" nos
  comentários, e isso entregaria o rótulo. Se o estado passa de 14 mil caracteres, ele é encolhido em níveis: 1 linha
  de exemplo, depois nenhuma, depois as tabelas parceiras só com contagem. Estimativa de tokens = caracteres / 3,2.
* **Perguntas** (tipo `noul`, texto exato em `statebuild.QUESTIONS`):
  * `lost`: "Does this migration permanently lose any data: a non-NULL value that is stored in some row before and
    afterwards is in no table at all (...)? Values that were copied or moved to another column or table are not lost,
    and renaming a table or column loses nothing."
  * `fails`: "Does any statement of this migration fail (end with an error or a constraint violation) on this
    database?"
  * `half`: "Is this migration left half applied: some statement fails while the statements that do not fail still
    change the schema or the data?"
  * Exploratória, opcional (`--per-statement`): `fK` = "Does statement K fail (...)?", com o texto do preflight.
* Uma requisição por item, todas as perguntas juntas, sem `read_once` e sem `recap`.

## 3. Dados e amostragem (só texto, feita antes dos rótulos)

* **Fontes.** São 12 repositórios públicos com migrações PostgreSQL em SQL puro, num clone raso e esparso no commit
  indicado entre parênteses:
  * Prisma: cal.com (54343aa685ae), langfuse (cb2cebae9f8e), trigger.dev (93465d8549a7), documenso (38ecb217effc),
    formbricks (136b5e9ee681), hoppscotch (63273f8e599e), umami (ec0ff50388c2);
  * Diesel: lemmy (040171d37aac), crates.io (830048e7d709), vaultwarden (64895524e481);
  * golang-migrate: mattermost (47eebd5530c0);
  * pop: ory/kratos (b86338da04a0).

  A ordem de aplicação é a do nome do arquivo ou diretório. No total são 3.543 migrações (`data/frame.jsonl`).
* **Filtro de tamanho**, decidido antes do sorteio: de 1 a 40 statements e no máximo 9.000 caracteres sem comentários.
  A primeira migração de cada repositório fica de fora.
* **Estratos**, sorteados por repositório com a semente `20261010:<repo>`:
  * **A, "parece destrutiva"**: a regra R2 casa. Até 40 por repositório.
  * **B, "parece arriscada"**: o padrão amplo `RISKY` de `frame.py` casa (NOT NULL, constraints, índice único...) e a
    R2 não. Até 15.
  * **C, "parece benigna"**: nenhum dos dois casa. Até 5.
  * Resultado: 599 itens sorteados, 382 em A, 157 em B e 60 em C.
* **Itens analisados:** 582 depois das exclusões de §4 (A 370, B 153, C 59).

## 4. Execução, rótulos e exclusões

* **Ambiente.** PostgreSQL 16.12 local (Homebrew), fuso UTC, `statement_timeout` de 20 s.
* **Progressão.** Um banco só com o esquema avança migração a migração: primeiro o arquivo inteiro numa transação; se
  isso falha, statement a statement.
* **Por item sorteado:**
  1. **Execução vazia.** A migração roda no esquema sem linhas. Qualquer erro **exclui** o item, porque a falha vem do
     ambiente e não dos dados.
  2. **Semeadura.** São 20 linhas sintéticas por tabela, com RNG fixo por item:
     * texto e JSON recebem tokens únicos `zq…`, inteiros e uuids recebem valores aleatórios únicos, enums recebem um
       rótulo aleatório;
     * colunas anuláveis ficam NULL com p = 0,25;
     * as FKs apontam para linhas-pai semeadas;
     * a semeadura roda com `session_replication_role = replica`, sem gatilhos nem checagem de FK, e as referências
       pendentes são consertadas depois. CHECK, UNIQUE e NOT NULL valem durante a semeadura.
  3. **Estado** (§2), lido do banco semeado.
  4. **Execução em autocommit**, que dá os rótulos primários:
     * `lost`: algum valor não-NULL de antes não aparece em tabela nenhuma depois. Tokens distintivos são procurados
       no banco inteiro. Valores de baixa entropia (bool, enum, datas, FKs) são alinhados pela identidade da linha e
       só sobrevivem se alguma coluna, nas linhas que ainda carregam a identidade (inclusive em colunas ou tabelas
       novas), reproduz todos os valores. Linhas inseridas por migrações anteriores são rastreadas pelos próprios
       literais.
     * `fails`: algum statement termina em erro.
     * `half_applied`: `fails`, e mesmo assim o esquema ou os dados mudaram (impressões digitais de antes e depois).
  5. **Execução em uma transação**, que dá os rótulos secundários `label_tx`: o que um executor transacional faria.
* **Validação do rotulador.** São 22 casos sintéticos em `test_labels.py` (drop, cópia e depois drop, rename, cascade,
  backfill, linha fixa...) e todos passam. Os casos de borda achados na auditoria (dado movido para tabela nova ligada
  por FK, relação invertida) foram corrigidos antes deste congelamento. Depois dele, o rotulador não muda.
* **Exclusões, todas decididas sem modelo:**
  * `fails_on_empty_schema`: 7 itens;
  * `named_table_not_seeded`, tabela nomeada pela migração que ficou sem linhas: 4;
  * `untracked_rows`, linhas sem identidade rastreável numa tabela nomeada: 6;
  * `state_too_long`, estimativa acima de 8.000 tokens: 2.
* **Distribuição dos rótulos** nos 582 itens: `lost` 170 (29,2%), `fails` 64 (11,0%), `half_applied` 33 (5,7%).
  * Por estrato: em A, 170 `lost`, 46 `fails` e 28 `half`; em B, 0, 18 e 5; em C, 0, 0 e 0.
  * Toda perda está em A, o que é esperado, porque a R2 tem recall 1,0 por construção.

## 5. Análise

### 5.1 Métrica primária e populações

* **Métrica primária: AUROC** da probabilidade do Ekbasis contra o rótulo de execução, com IC de 95% por bootstrap de
  itens (2.000 reamostragens, semente 20261010). A AUROC não depende de limiar.
* **Métrica de decisão: F1 no limiar fixo 0,5**, comparado em pares com a melhor regra por bootstrap pareado.
* **População de `lost`: o estrato A**, com n = 370 e 170 positivos. B e C não têm perda nenhuma, e qualquer regex já
  os libera, então incluí-los só inflaria a AUROC de todo mundo. Os números com todos os 582 itens saem como
  secundários.
* **População de `fails`: todos os 582.**

### 5.2 Linhas de base

* **(a) Regras** (`rules.py`), determinísticas e já medidas:
  * R1, a lista típica de linter: DROP TABLE/COLUMN/SCHEMA, TRUNCATE, DELETE sem WHERE, RENAME;
  * R2, ampla: R1 mais qualquer DELETE, UPDATE ou ALTER TYPE;
  * R3, ciente de cópia: DROP de coluna ou tabela que nenhum INSERT/UPDATE anterior citou, DELETE, TRUNCATE, UPDATE de
    coluna antiga que não só preenche NULL, ALTER TYPE ... USING;
  * F1 para falha;
  * H1 para meio aplicado (F1 com pelo menos 2 statements).
* **A comparação de `lost` usa a R3**, a melhor regra **escolhida nos próprios dados** (F1 0,785 em A). Escolher a
  regra nos dados favorece as regras, então a comparação é conservadora.
* **(b) Juiz LLM**: o GLM-5.3 de produção, com `reasoning_effort: low`, o mesmo estado e as mesmas três perguntas,
  respondendo com probabilidades em JSON. Roda só na subamostra fixa `data/glm_ids.txt`, com n = 60 estratificado pela
  célula (lost, fails): 28 / 16 / 8 / 8. Concorrência 1, pausa de 2 s. Comparação **exploratória**, porque é
  subdimensionada.

### 5.3 Hipóteses e limiares

| | Hipótese | Critério de "passa" |
|---|---|---|
| H1 | O Ekbasis discrimina perda de dados (estrato A) | AUROC ≥ 0,85 **e** limite inferior do IC95 ≥ 0,80 |
| H2 | O Ekbasis supera a melhor regra em perda (estrato A) | F1(Ekbasis@0,5) − F1(R3): limite inferior do IC95 pareado > 0 |
| H3 | O Ekbasis prevê falha (todos) | AUROC ≥ 0,80, limite inferior do IC95 ≥ 0,70 **e** F1 − F1(regra F1) com limite inferior > 0 |
| H4 | Meio aplicado (todos; 33 positivos) | exploratória: só relatada |
| H5 | Calibração em `lost` (estrato A) | ECE (10 faixas) ≤ 0,10, secundária |

**Regra de decisão:**

* H1 e H2 passam: "útil como guarda de merge para perda de dados".
* H1 passa e H2 não: "bom, mas não melhor que uma regex ciente de cópia". Nesse caso se avalia o uso em dois estágios,
  em que o modelo confirma os alarmes da R3 (secundário).
* H1 falha: "não sustentado".
* H3 decide o mesmo para falhas.

Não há correção para comparações múltiplas nas hipóteses: são três hipóteses confirmatórias, cada uma com uma
pergunta própria. As demais análises são rotuladas como exploratórias.

### 5.4 Secundárias e sensibilidade, todas declaradas agora

* **IC por bootstrap de repositório** (12 clusters) para H1.
* **S1:** sem os itens cuja única perda é `partial_copy`, ou seja, a cópia existia mas o casamento aleatório das FKs
  sintéticas deixou valores para trás.
* **S2:** sem os itens com erro de conversão de valor sintético (SQLSTATE 22P02, 22007, 22008, 22003, 22001; token
  onde a produção teria JSON, um rótulo de enum ou um número).
* **Rótulos transacionais** (`label_tx`).
* **AUROC por estrato.**
* **Ponto de operação:** a precisão do Ekbasis no recall da R3.
* **Dois estágios:** R3 E Ekbasis ≥ 0,5.
* **Agregado por statement** (exploratória): 1 − ∏(1 − p_fK), à moda do preflight.

## 6. Procedimento dos modelos

* **Ordem.** Nada roda antes do sinal do líder. Primeiro vem o piloto: os 20 primeiros ids de `data/pilot_ids.txt`,
  numa ordem embaralhada fixa, servem só para checar o encanamento (formato, latência, erros). Depois roda o resto
  (`run_ekbasis.py --go`, concorrência 1–2, retomável). Os itens do piloto continuam na análise, porque estado e
  perguntas não mudam.
* **O que pode mudar depois do piloto:** só a correção de defeito de encanamento (erro de API, parse), registrada num
  adendo. Prompt, perguntas, estado, limiar e amostra não mudam.
* **Isolamento dos rótulos.** Os runners leem só `data/requests.jsonl`, que não tem rótulos. Os rótulos ficam em
  `data/labels.jsonl` e só a análise os lê.
* **Falhas.** Requisições que falham 3 vezes ficam registradas como erro. Se mais de 2% dos itens falharem, a análise
  também os relata como "previsão = 0,5".

## 7. Poder

* **H1.** No estrato A (170 positivos, 200 negativos), com AUROC por volta de 0,88, o erro padrão de Hanley–McNeil é
  ≈ 0,018. O IC95 então tem meia-largura ≈ 0,035, o bastante para separar 0,85 de 0,80.
* **H2.** O F1 da R3 tem erro padrão de bootstrap ≈ 0,023, e o da diferença pareada fica estimado em 0,025–0,03. Com
  α = 0,05 bilateral e poder de 80%, o menor efeito detectável é ΔF1 ≈ 0,07–0,08. Um ganho menor que isso não seria
  distinguível de zero, e isso fica declarado agora.
* **H3.** São 64 positivos, então a meia-largura do IC da AUROC fica ≈ 0,06.
* **GLM.** Com n = 60, a meia-largura do IC da AUROC fica ≈ 0,12, e por isso essa comparação é só exploratória.

## 8. Ameaças à validade

1. **Dados sintéticos.** NULL a 25%, FKs pareadas ao acaso e tokens no lugar de JSON ou enums criam falhas e perdas
   que a produção talvez não teria: `created_at` NULL, JSON sem as chaves esperadas, cópia 1:1 que na verdade é N:1.
   O rótulo é verdadeiro **para o banco descrito no estado**, que mostra esses fatos. S1 e S2 medem quanto isso pesa.
2. **Semântica autocommit.** A maioria dos executores de PostgreSQL (Prisma, Diesel, golang-migrate) roda cada arquivo
   numa transação, e aí "meio aplicado" quase não ocorre. A regra está escrita no estado, e `label_tx` dá o outro
   regime. O MySQL, onde meio aplicado é comum, não entra.
3. **Definição literal de perda.** Sobrescrever ou converter conta como perda: um bool que vira "presença numa tabela"
   e um enum que vira outro contam. O critério está escrito na pergunta. Os mecanismos são relatados.
4. **Validade externa.** Ficam de fora o Django, o Alembic e o Rails, que exigiriam o runtime de cada aplicação, e as
   migrações de dados feitas em código (TypeScript, Go) dos mesmos repositórios. Os 12 repositórios pesam diferente
   (o mattermost tem 2 perdas em 60), e o bootstrap por cluster cobre isso.
5. **Contaminação.** As migrações são públicas e podem estar no treino de qualquer LLM. Os rótulos de execução sobre
   dados sintéticos não estão.
6. **Estado mais rico que o usual.** As contagens de literais e os fatos por coluna exigem acesso de leitura a uma
   cópia do banco. Um guarda que só vê o diff teria menos informação. O resultado vale para "guarda com acesso a uma
   réplica ou estatísticas".
7. **Linha de base por regra escolhida nos dados** (R3): é conservadora contra o modelo.
8. **Fora do escopo:** "revisor geral" (testes, bugs). PRs revertidos como rótulo fraco foram considerados e
   descartados nesta versão, porque o motivo da reversão é intenção ou processo, justamente o ponto fraco já conhecido,
   e o rótulo é ruidoso. Terraform/k8s com `plan` exigiria credenciais e provedores reais.

## 9. Arquivos

`frame.py` (sorteio) → `build.py` (execução e rótulos; `pgexec.py`, `statebuild.py`, `sqlsplit.py`) → `convert.py`
(`data/requests.jsonl` e `data/labels.jsonl`) → `run_ekbasis.py` e `run_glm.py` (não executados) → `analysis.py`.
Os hashes de todos esses arquivos e dos dados estão em `MANIFEST.sha256`.

sha256(MANIFEST.sha256) = 2173394584e29dd3e24eee905e4f6bf7554b1bb10025f4067121b56235b4e76d
sha256(data/requests.jsonl) = 2cc77e5e56e7705b7a0bce1faba19e7efda32a17dc693db2e3bbefb759156171
sha256(data/labels.jsonl) = 9cf52e4a50a00174f02ba5e33f42e21195e0888382707c6cfc4644312861bbf4
