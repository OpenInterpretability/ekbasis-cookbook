# Pré-registro: `read_once` como padrão no migration guard

Congelado em 2026-10-11, antes de qualquer chamada pontuada. Única chamada feita antes: a checagem de
compatibilidade da seção 2, num estado sintético que não pertence ao conjunto rotulado.

## 1. Pergunta

O migration guard faz 2 perguntas (`lost`, `fails`) ou 3 (mais `half`, em autocommit) sobre o mesmo estado. Hoje
(`ekbasis` `3bf2769`, `migrations._check_file`) ele chama `client.ask(state, qs)`, e o servidor lê o estado uma vez
por pergunta. Com `read_once=True`, o servidor lê o estado uma vez e responde tudo na mesma passada.

A pergunta é: **nos mesmos itens, o veredito do guard com `read_once=True` é não-inferior ao de hoje, e o custo em
tokens de entrada cai pelo menos 35%?**

Evidência prévia, que o desenho leva em conta: o README do ekbasis registra uma perda de 0,9 a 3,1 pp de acurácia nos
mundos de regras (78,0% contra 81,2% nos não treinados; 91,5% contra 92,4% nos treinados). O `safer.py` não usa
`read_once` por esse motivo. Ninguém mediu isso em migrações.

## 2. Checagem de compatibilidade (feita antes deste congelamento, declarada)

`compat/compat.py`, saída em `compat/compat_out.json`. Um estado sintético (DROP COLUMN numa tabela de 1.000 linhas),
fora do conjunto rotulado, com Q_LOST e Q_FAILS do produto, uma chamada em cada modo:

| | HTTP | input_tokens | P(lost) | P(fails) | model ms |
|---|---|---|---|---|---|
| SEP | 200 | 384 | 0,978 | 0,031 | 2.780 |
| ONCE | 200 | 296 | 0,981 | 0,006 | 674 |

O servidor aceita o campo e o `usage` cai. Num estado tão curto, o texto das perguntas domina, e por isso a queda foi
pequena. Nos estados reais (~3–4 mil tokens), espera-se algo perto de 50%.

## 3. Itens e rótulos

* As **184 migrações do v3** (128 benignas e 56 arriscadas), com os rótulos congelados `label_product`
  (`v4/data/labels_v3.jsonl`). Arriscada = `lost` ou `fails`. Motivo verdadeiro = `fails` se `fails`; senão, `loses`.
* Os estados são os do braço OLD do v4 (`8071e38`), em `v4/st/req_t2_old.{N,R}.jsonl`. Entre `8071e38` e `3bf2769`,
  nada mudou em `build_state`, nas regras nem nas perguntas (conferido no diff). Nenhum item é decidido em código; os
  184 vão ao modelo nos dois regimes.
* **Regimes:** N (sem réplica, o padrão da Action) e R (réplica semeada, com estatísticas).
* Perguntas: as do produto, palavra por palavra. O `run.py` checa, item a item, que cada pergunta é igual a `Q_LOST`,
  `Q_FAILS` ou `Q_HALF` do `3bf2769`. Há 174 itens com 2 perguntas e 10 com 3, por regime.
* **Fora do escopo:** o TS-Bench tem uma pergunta por passo (a segunda, `level`, é exploratória e não teve as respostas
  publicadas), e o AgentDojo oficial é execução de agente ao vivo, sem itens estáticos com várias perguntas. Nenhum dos
  dois tem o formato que o migration guard usa. A decisão vale só para o migration guard.

## 4. Braços e execução

* **SEP:** `Ekbasis.ask(state, qs)`, como o guard faz hoje.
* **ONCE:** `Ekbasis.ask(state, qs, read_once=True)`.
* Cliente do clone `3bf2769`, API hospedada (`https://openinterp.org/api/v1`), chave de estudo, surface
  `read-once-parity`. Concorrência 1. Cache de veredito não envolvido, porque a chamada é direta ao cliente.
* **Ordem:** os 368 pares (item × regime) são embaralhados com semente 20261011, e a ordem dos braços dentro de cada
  par é sorteada. Os dois braços de um item correm um logo depois do outro.
* **Falhas:** HTTP 429 espera 30 s e não conta como tentativa. Outros erros têm até 3 tentativas. Um item sem resposta
  num dos braços sai do pareamento daquele regime e é relatado.
* Uma resposta por braço, sem repetição.

## 5. Veredito (o do produto)

Igual ao `score_v4.verdict` e a `FileVerdict.kind`, com limiar de 0,5. Se houver erro de esquema em autocommit,
P(fails) = 1. Se P(fails) ≥ 0,5, o veredito é arriscado com motivo `fails`. Senão, se P(lost) ≥ 0,5, é arriscado com
motivo `loses`. Senão, é ok. `p_half` não entra no veredito do produto, assim como hoje.

## 6. Critérios (por regime; a decisão exige que **os dois regimes** passem em tudo)

| | Critério |
|---|---|
| C1 | Limite inferior do IC 95% (bootstrap pareado, 10.000 reamostragens, semente 20261011) de acurácia ONCE − SEP ≥ −2 pp |
| C2 | Alarmes falsos (benignas marcadas): ONCE ≤ SEP + 3 |
| C3 | Recall (arriscadas marcadas): ONCE ≥ SEP − 2 |
| C4 | Motivo exato (arriscadas marcadas com o motivo verdadeiro): ONCE ≥ SEP − 2 |
| C5 | Mediana de \|Δp\| entre ONCE e SEP, sobre todas as respostas (lost, fails e half) ≤ 0,05 |
| G1 | Ganho: 1 − mediana(input_tokens ONCE) / mediana(input_tokens SEP) ≥ 35% |
| — | Completude: no máximo 5 itens sem par por regime; acima disso, o resultado é **inconclusivo** |

Nota sobre o C1: com n = 184, um item vale 0,54 pp. Com o IC pareado, o critério tolera na prática uma perda líquida de
cerca de 1 item. É exigente de propósito: trata-se de mudar um padrão.

**Decisão:** se tudo passar nos dois regimes, abro um PR numa branch do meu clone (sem merge) que liga o `read_once`
por padrão no `_check_file`, com teste e entrada no CHANGELOG. Se algo falhar, não há PR, e relato onde diverge.

## 7. Relatado sem critério (descritivo)

AUROC, Brier e ECE (10 faixas) por pergunta e por braço; distribuição de \|Δp\| (p75, p90, p99, máximo, e quantas
respostas passam de 0,1 e de 0,3); a lista de itens cujo veredito muda; latência (relógio do cliente e `model` do
Server-Timing, mediana e p90); totais de tokens; e a deriva do SEP contra as respostas do v4 nos mesmos estados.

## 8. Arquivos congelados (sha256)

```
897acff22f2257c644308e6fd8afd9a423494759f88f527b674c63f81c343694  run.py
6dfeda16f03a7e6d4b237813f1f244605465252f6f51f0968d0e4491ef5bbd27  analyze.py
de4b89485d50f10996dcfd40aa5804ae0686c2a427d2caaaa90631bebaee0043  compat/compat.py
0cb4470f1b8c831aae769717bcb08ff37e8546151b07bd69e0638a2180282486  v4/data/labels_v3.jsonl
1d749a16866baf8e37589e09ead9996f861975afc92712c3347770fe7ab64aaf  v4/st/req_t2_old.N.jsonl
980b9254371ee5d091bb0f6b41dae7688655dd57273fec388a9687a4d1141500  v4/st/req_t2_old.R.jsonl
cf663f9040817afe21bec32eb9d217002206f6687c9fbd3f826b0876633c3092  v4/st/t2_old.N.jsonl
8451d978417f33eecc46f76045f907738740da4790517f6f0214de21e730f37c  v4/st/t2_old.R.jsonl
```

Commit do ekbasis: `3bf2769`.
