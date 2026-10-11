# Desvios e ocorrências

## 1. Sessão do agente interrompida depois da coleta (sem efeito nos dados)

O agente caiu por limite de sessão depois de a coleta terminar. O líder leu "parou no item 367 de 736" no `run.log`, mas
o número na primeira coluna do log é o índice do par (item × regime), de 0 a 367: os 368 pares, cada um com 2 braços,
dão as 736 chamadas.

Conferido às 17:51 UTC, antes de qualquer retomada:
* `ans/answers.jsonl` tem 736 linhas, com 736 chaves (id, regime, braço) distintas e 0 erros;
* todas as linhas são JSON válido;
* a primeira resposta é das 15:04:26 UTC e a última das 16:33:52 UTC;
* o processo terminou sozinho.

**Nada foi retomado nem refeito.** O `run.py` é retomável: ele pula as chaves já respondidas sem erro. Se tivesse sido
relançado, não faria nenhuma chamada.

## 2. Teste exploratório pós-coleta

A deriva do SEP de agora contra as respostas do v4, nos mesmos estados, foi calculada por um script inline. Ela era
descritiva na seção 7 do PREREG; a saída está em `drift.txt`.

Os scripts `run.py` e `analyze.py` não mudaram desde o congelamento (sha256 conferido antes da análise).
