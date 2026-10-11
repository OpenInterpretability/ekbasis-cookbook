# Pré-registro: "este bump do Dependabot quebra o CI?" (piloto de vertical do Ekbasis)

Versão 1.0, congelada em 2026-10-11, **antes de qualquer chamada ao Ekbasis** e antes de qualquer rótulo ser
calculado. O sha256 deste arquivo vai ao líder ("main") antes da primeira chamada. `MANIFEST.sha256` fixa o código e
as listas de PRs (dev e teste). Desvios vão para `DEVIATIONS.md`, datados; este arquivo não muda.

## 1. Pergunta e hipótese

Pergunta operacional: dado um PR do Dependabot que atualiza **um** pacote (npm ou PyPI), com os fatos coletados por
código escritos no estado (delta de semver, trechos das notas de versão, requisitos de runtime, peers, formato de
módulo, diff do lockfile, uso do pacote e dos nomes citados nas notas dentro do repositório, comandos do CI), o
Ekbasis prevê melhor do que uma regra fixa se o CI do PR vai quebrar por causa do upgrade?

Hipótese de trabalho: o Ekbasis só ganha da regra quando o fato aponta um mecanismo concreto (um nome removido que o
repositório usa, um runtime abaixo do mínimo, um peer incompatível, um pacote que virou ESM-only e é carregado com
require()). Sem esses fatos, ele deve ficar perto da regra "major = quebra".

## 2. Dados e amostra (congelados, só pelo título)

* **Repositórios.** Busca do GitHub por repositórios TypeScript, JavaScript e Python, em três faixas de estrelas
  (100–500, 500–3.000, 3.000–40.000), com push depois de 2026-09-20, não fork, não arquivados, menores que 150 MB;
  duas páginas de 100 por combinação (`collect.py`). 
* **PRs.** Abertos por `dependabot[bot]` **depois de 2026-06-01** (para reduzir memorização), de um só pacote (título
  "Bump X from A to B"; grupos excluídos), branch `dependabot/npm_and_yarn/*`, `dependabot/pip/*` ou
  `dependabot/uv/*`. Só Dependabot (o Renovate fica fora porque o formato de título e de corpo é outro; um único
  formato evita viés de parser).
* **Deduplicação.** Um PR por (repositório, pacote): o mais recente.
* **Divisão dev/teste por dono do repositório**: `int(sha256(owner)[:8], 16) % 10 < 3` → dev, senão teste. Nenhum
  dono aparece nos dois conjuntos.
* **Estratificação.** Por repositório, até 3 PRs semver-major e até 3 outros, sorteados (semente 20261011). Teto de
  200 PRs no dev e 450 no teste (repositórios sorteados, inteiros, até o teto). O sobre-amostramento de majors é
  deliberado, para haver positivos; as métricas valem para essa mistura, não para o fluxo natural do Dependabot.
* **Semver-major**: muda o primeiro componente, ou, em 0.x, o segundo.
* As listas ficam em `dev_ids.txt` e `test_ids.txt` (hashes no MANIFEST), congeladas antes de qualquer rótulo e de
  qualquer chamada.

## 3. Rótulo (decidido em código, `label.py`)

Só check runs do app GitHub Actions, sem os jobs que não são build nem teste (bots, revisão e tarefas do repositório:
nomes que casam com `META` em `label.py`, por exemplo Dependabot, copilot, auto-merge, labeler, stale,
dependency-review, CodeQL/Analyze, título de PR, CLA/DCO, codecov), `filter=latest` (uma nova execução de um job substitui a antiga: um job
re-executado que passou conta como passou, o que já remove parte do flaky).

* **Quebrado (1)**: algum job falha (`failure`, `timed_out`, `startup_failure`) no commit do PR **e o job de mesmo
  nome passou (`success`) no commit base do PR**, e o job não é sistemático (abaixo).
* **Não quebrado (0)**: nenhum job falha no commit do PR e pelo menos um passa.
* **Excluídos** (contados e relatados): `no_ci` (nenhum job concluído com sucesso ou falha), `pending` (job não
  concluído), `human_commits` (algum commit do PR não é do Dependabot: alguém já mexeu), `unattributable` (todo job
  que falha também falha, ou não existe, na base: não dá para atribuir ao upgrade), `error` (erro do GitHub) e
  falha ao extrair os fatos.
* **Job sistemático** (ignorado): falha em pelo menos metade dos PRs amostrados daquele repositório em que rodou,
  com pelo menos 4 PRs. É a assinatura de falha comum a todo PR do Dependabot (segredo ausente, workflow quebrado),
  não do upgrade. Justificativa: com no máximo 6 PRs por repositório e até 3 majors, um job que falha em metade ou
  mais quase sempre é ambiente; o custo é perder um repositório onde 2–3 majors quebram o mesmo job.
* Ruído conhecido e aceito: um job que falha por flakiness no PR e passa na base conta como quebrado. Não há re-run
  nosso (nada é executado no repositório de terceiros).

## 4. Estado (congelado, `facts.py` + `state.py`)

Formato `world_state` do cliente (`ekbasis.prompts`): regras, `Current state:` com os fatos, uma ação ("Merge this
pull request's changes (upgrade X from A to B) and run the CI jobs on the result.") e a nota padrão. Fatos, todos
extraídos por código; um fato não encontrado não aparece (a regra diz isso):

1. número de arquivos-fonte; pacote, ecossistema, versões e tipo de upgrade (major/minor/patch, 0.x);
2. onde o pacote está declarado (seção do package.json) e arquivos que o PR muda;
3. **notas de versão entre as duas versões**: o corpo do PR do Dependabot (release notes, changelog) mais os
   releases do GitHub do repositório do pacote com versão em (A, B]; só as linhas que citam breaking, removed,
   dropped, deprecated, no longer, renamed, minimum, requires node/python, ESM-only, incompatible ou migrate (até 14);
4. runtime: `engines.node` (npm) ou `requires_python` (PyPI) antes e depois, as versões de Node/Python dos workflows
   do CI e, decidido em código, quais estão abaixo do novo mínimo;
5. npm: virou `"type": "module"` e se é ESM-only (exports sem condição require), e quantos arquivos fazem require()
   do pacote; mudanças de peerDependencies e conflito com a versão que o repositório declara; deprecação no registro;
   dependências próprias adicionadas ou removidas;
6. lockfile: outros pacotes cuja versão o diff muda (majors primeiro, até 8), ou "diff grande demais";
7. uso: arquivos que importam o pacote, subpaths importados, outros arquivos que o citam (config, scripts) e, para
   cada nome entre crases nas linhas do item 3 (até 8), quantas vezes aparece nos arquivos que importam o pacote (ou
   em todo o código, se nenhum importa), com até 2 exemplos `arquivo:linha`;
8. CI: número de workflows que rodam em pull_request e seus comandos `run:` (até 10).

O nome do repositório não entra no estado. Nada do resultado do CI entra no estado.

## 5. Perguntas (congeladas) e veredito em código

Uma requisição por PR, três perguntas sim/não (`noul`), texto exato em `state.py`:

* `api`: "Will a CI job fail because code in this repository uses an API of the upgraded package that this upgrade
  removes or changes?"
* `other`: "Will a CI job fail for another reason introduced by this upgrade (installation, build, type checking,
  lint, tests, or a runtime version the new release no longer supports)?"
* `any`: "Will any CI job fail on this pull request?"

Score primário: `s = max(p_api, p_other)`. Veredito: quebra se `s ≥ t`, com `t = 0,5` salvo escolha no dev (§7).
Concorrência 1; 429/5xx: espera crescente (30 s × tentativa) e repete, até 12 vezes.

## 6. Regras de base (congeladas)

* **R1**: semver-major = quebra.
* **R2**: semver-major **e** alguma linha do item 3 contém "breaking" = quebra.
* A regra de comparação primária no teste é a de **maior F1 no dev** (fixada no adendo do dev).

## 7. Uso do dev (limitado e registrado antes do teste)

1. Uma rodada do Ekbasis em todo o dev com o código congelado.
2. Permitido só no dev, e só isto: (a) escolher o score entre `max(api, other)` e `any` pela AUROC do dev; (b) escolher
   `t` em {0,2; 0,3; …; 0,8} pelo F1 do dev; (c) corrigir **bugs de extração** de fatos vistos lendo estados do dev
   (sem mudar perguntas nem regras), no máximo uma revisão, com nova rodada do dev.
3. As escolhas vão para `ADDENDUM_DEV.md`, com sha256 enviado ao líder **antes da primeira chamada do teste**. O teste
   roda uma vez, sem mudança depois de visto.

## 8. Critérios no teste (congelados)

Intervalos: bootstrap percentil 95% por **repositório** (2.000 reamostragens, semente 7).

* **H1 (discrimina)**: AUROC do score ≥ 0,70 e limite inferior do IC > 0,50.
* **H2 (ganha da regra)**: F1(Ekbasis) − F1(regra de comparação) ≥ +0,05 e limite inferior do IC > 0.
* **H3 (McNemar)**: McNemar exato bilateral sobre acerto por PR, p < 0,05, com mais pares discordantes a favor do
  Ekbasis.
* **H4 (alarme falso)**: taxa de alarme falso (FP / negativos) do Ekbasis ≤ a da regra de comparação.
* **H5 (secundária, além do semver)**: AUROC dentro dos PRs semver-major ≥ 0,65.
* Relatados sem critério: precisão, recall, ECE, AUROC por pergunta, por ecossistema, nos não-major, varredura de
  limiar, tokens e tempo de modelo.
* **Ressalva de poder**: com menos de 30 positivos no teste, H2 e H3 são indicativos, não conclusivos, e o relatório
  diz isso. O IC de H2 com ~30 positivos tem largura da ordem de ±0,10.
* **Decisão de produto**: "vale virar produto" só com H1, H2 e H4. H1 sem H2: serve para ordenar o risco, não como
  gate. Sem H1: não vale.
