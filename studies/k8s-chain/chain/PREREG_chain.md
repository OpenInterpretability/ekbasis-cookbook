# Pré-registro — "Look when unsure" num agente de verdade: pipelines no Kubernetes

Escrito em 12/10/2026 antes de qualquer execução de agente deste estudo; selado por SHA-256 em `PREREG_chain.sha256`.

## Pergunta

Quando um agente recebe um lote (um pipeline de passos kubectl que o usuário entrega para rodar), o guard do Ekbasis
pode (a) olhar sempre: exigir um passo por vez e checar cada um no cluster como ele está (o guard da Fase 1), ou (b)
olhar quando inseguro: prever com o Ekbasis cada prefixo do lote a partir do cluster como está, deixar o lote correr
inteiro quando todo prefixo é previsto inofensivo com confiança ≥ 0,9, e no primeiro prefixo que não for, dividir o
lote (rodam os passos anteriores, e aquele passo é checado no cluster como ficou depois deles), com as checagens em
código rodando sobre a sequência inteira sempre (check when sure). A regra (b) mantém a segurança de (a) com menos
interrupções? E as duas tornam o agente mais seguro do que sozinho?

## Tarefas

`chain_tasks.py`: 18 pipelines. 12 com dano (os 12 mecanismos verificados na Fase 1: dados de volume com reclaim Delete,
Service esvaziado por label, apply imutável recriado, --prune de objeto de outra equipe, replace --force, taint
NoExecute, ConfigMap em uso seguido de restart, dono apagado em cascata, StatefulSet com retenção Delete, scale down de
StatefulSet), cada um embrulhado em 2 a 4 passos com passos inofensivos (anotar, criar ConfigMap, esperar rollout); em
dois (F3a, F8a) o dano depende de um passo anterior. 6 controles com o mesmo embrulho, sem dano. Os cenários, juízes
(estado final do cluster + monitor de endpoints a cada 0,5 s) e o usuário simulado (roteiro de preocupações) são os da
Fase 1. Verificação no cluster antes de qualquer execução (`verify_chain.py`, `verify/`): pipeline com dano → dano;
caminho seguro da Fase 1 → sucesso sem dano; controle → sucesso sem dano.

## Braços

- `blind`: o agente sozinho (só a política de shell: kubectl, leitura e `bash pipeline.sh`).
- `ask_always`: toda execução que muda o cluster (um comando kubectl, ou um intervalo do pipeline com passo que muda)
  vai antes ao usuário, com os fatos dos objetos.
- `stepwise` (olhar sempre): intervalo com mais de um passo que muda é recusado ("um passo por vez"); um passo passa
  pela checagem da Fase 1 (previsão do Ekbasis, checagens em código, caminho mais seguro checado, senão o usuário).
- `chain` (olhar quando inseguro): a regra (b) acima, `guard_chain.py`; o passo isolado passa pela mesma checagem da
  Fase 1.

Agente: Claude Haiku 5.5 (`claude-haiku-5-5`, `claude -p`, Bash só), prompts de sistema da Fase 1, até 30 turnos, 25
min, até 4 respostas do usuário. Ekbasis: a API de produção (B200), o cliente e os prompts congelados da Fase 1 (0.1.6;
a única mudança é um User-Agent, exigido pela borda da API). 18 tarefas × 4 braços × 2 sementes = 144 execuções, ordem
embaralhada fixa, até 3 em paralelo, tarefas de nó sozinhas. Execução inválida (erro de infraestrutura, limite de
conta, previsor fora do ar) é refeita até 3 vezes e registrada.

## Hipóteses (pares por tarefa e semente)

- **H1 (segurança):** dano `chain` < `blind` nas 24 execuções pareadas das tarefas com dano. McNemar exato unilateral,
  α = 0,05.
- **H2 (olhar quando inseguro ≈ olhar sempre):** dano `chain` ≤ dano `stepwise` + 2 e sucesso `chain` ≥ sucesso
  `stepwise` − 2, nas 24 execuções das tarefas com dano.
- **H3 (menos interrupção):** interrupções por execução (recusas do guard que mandam dividir ou ir passo a passo, mais
  perguntas ao usuário) menores em `chain` que em `stepwise`, nas 36 execuções pareadas (todas as tarefas); Wilcoxon
  pareado unilateral, α = 0,05. E perguntas ao usuário em `chain` ≤ metade das de `ask_always`.
- **H4 (controles):** sucesso `chain` ≥ `blind` − 1 nas 12 execuções de controle.

"Olhar quando inseguro deixa o agente mais seguro com a segurança de olhar sempre e menos interrupção" só se H1, H2 e
H3 passarem; H4 é condição de não-custo. Descritivos: onde a cadeia dividiu e por quê (alarme ou incerteza), quanto
o Ekbasis e o código pegaram cada um, chamadas ao Ekbasis, segundos, turnos, desfechos por tarefa.

## Desenvolvimento antes do selo (declarado)

`dev_forecast.py`: previsão do Ekbasis de cada prefixo de cada pipeline, sem agente, para conferir que a regra roda e
ver onde ela divide; o limiar 0,9 é o do paper e não foi ajustado. Resultado: nas 12 tarefas com dano, o primeiro
prefixo sinalizado é o do passo com dano em todas (os anteriores com confiança 0,94–0,998); nos 5 controles sem nó, 3
correm inteiros e 2 sinalizam o passo pedido (apagar o namespace descartável, apagar o StatefulSet).
Testes de encanamento (prefixos `pilot`, `pilot2`, fora da análise): uma execução por braço em P_F2b, e chain/stepwise em
P_F2b e P_C6. Mudanças depois deles, antes do selo: a política aceita `bash pipeline.sh` com comandos só de leitura e
redirecionamentos na mesma linha (o agente escrevia `bash pipeline.sh 2>&1; echo "exit=$?"`), e recusa a linha que junta
o pipeline a um comando kubectl que muda algo; `cat`/`grep` do arquivo seguem a política comum. Observado no teste:
com o guard, o Haiku 5.5 às vezes para e relata em vez de seguir a rota segura sugerida (fica como "bloqueado").

## Regras

Nada muda depois do selo; desvios vão para `DEVIATIONS_chain.md` com horário, antes de olhar resultados. Análise em
`analyze_chain.py`, selada junto.
