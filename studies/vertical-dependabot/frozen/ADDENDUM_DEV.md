# Adendo do dev (PREREG §7), congelado antes de qualquer chamada do teste

Data: 2026-10-11 (UTC). Dev: 200 PRs sorteados e 148 rotulados (17 quebrados, 131 não). Excluídos: no_ci 37,
unattributable 8, human_commits 7.

## Revisão (c), a única permitida

Rodada 1: AUROC de max(api, other) = 0,648 e de any = 0,655. Lendo os estados do dev, achei um bug de extração: a
corrida entre threads (DEVIATIONS 2) já tinha **corrompido o cache de código-fonte** de alguns repositórios. Um
download era apagado no meio por outra thread e mesmo assim marcado como pronto. Exemplo: em plankanban/planka faltava
`client/package.json`. Corrigi apagando todo o `cache/src` e baixando de novo; o código de extração não mudou. Os
fatos mudaram em 13 dos 148 PRs. A rodada 2 do dev usou esses fatos. As respostas da rodada 1 ficam em
`dev_answers_v1.jsonl`.

## Escolhas pela rodada 2 do dev (regras do §7)

* **Score**: `max(p_api, p_other)`. AUROC no dev de 0,639 [0,411; 0,881] contra 0,635 [0,489; 0,800] do `any`. A
  regra manda escolher a maior AUROC; a diferença é ruído.
* **Limiar**: `t = 0,2`, o maior F1 no dev para esse score (0,333; com 0,5 o F1 é 0,182).
* **Regra de comparação**: **R1** (major = quebra), F1 0,361 no dev contra 0,233 da R2.

Leitura honesta do dev, registrada antes do teste: no dev o Ekbasis **não** ganha da R1 (F1 0,333 com t = 0,2 contra
0,361). A AUROC de `p_api` sozinho foi 0,743, mas o §7 não permite trocar o score por ela; fica como análise
exploratória no teste, sem critério. A expectativa registrada é que H2 e H3 falhem no teste.

## O que fica igual no teste

O código é o mesmo dos hashes abaixo: perguntas, estado, rótulo e regras sem mudança. O teste roda uma vez.
e647497a735275964a38d7b81f605540de58328094574532354848409c22234f  facts.py
2217fc686143d2f19689080e7918d43ddefc7537a0c7408259248c6718312919  state.py
ec107ed8f3881498ede1600a324bad6ae56391dae4282b13c48b67baac6483b3  run_ekbasis.py
ce9a0ec21785eea6935f6488fa7be8362d1d9385487177d1b5db9422911a634d  analysis.py
670af296153078a979f7fe3eba2164439b95b8c71c977253863e5de44a74b21e  label.py
1451d6a981cabccf64d18d1657e0f98e48f24412532da858d3fbc85e03f58ee6  ghc.py
