# Desvios do PREREG.md (datados, UTC)

1. **2026-10-11 ~13:30, antes de qualquer chamada ao Ekbasis.** O limite horário da API do GitHub estourou durante o
   rótulo do teste e os fatos do dev (`RuntimeError: API rate limit exceeded`). `ghc.py` passou a esperar 300 s e
   repetir (até 30 vezes) em vez de desistir após 6 tentativas. Só mudou a política de espera: URLs, cache e conteúdo
   não mudaram. Os fatos do dev foram recalculados do zero (as respostas do GitHub ficam em cache).
2. **2026-10-11 ~13:55, antes de qualquer chamada ao Ekbasis.** `facts.py`: duas threads baixavam o mesmo
   repositório@commit ao mesmo tempo (`FileExistsError` em 6 PRs do dev). Um lock por repositório@commit resolve; nenhuma
   regra de extração mudou. sha256 e647497a73527596…
3. **Mesma hora.** `state.py` e `run_ekbasis.py` passam a importar o cliente `ekbasis==0.1.16` instalado do PyPI em
   `vendor/` (o /tmp/ekbasis_pr estava sendo alterado por outro agente com git stash). `prompts.py` e `client.py` são
   idênticos aos de /tmp/ekbasis_pr (diff vazio). Texto do estado e perguntas inalterados.
   state.py 2217fc686143d2f1…, run_ekbasis.py ec107ed8f3881498…, ghc.py 1451d6a981cabccf…
4. **Revisão (c) do dev**: cache de código-fonte corrompido pela mesma corrida do item 2. Apagado e baixado de novo
   antes da rodada 2 do dev (ver ADDENDUM_DEV.md). Não é desvio do §7; fica registrado aqui também.
5. **Teste, fatos.** 6 PRs de um repositório (cytoscape/cytoscape.js) deram `FileNotFoundError` na extração (link
   simbólico no tarball) e saíram pela regra "falha ao extrair os fatos" (§3). Um deles era positivo. O teste fica
   com 329 PRs e 42 positivos. Não tentei corrigir depois de ver o teste.
6. **Análise, contagem de tokens.** `analysis.py` lia `usage.prompt_tokens`, mas a API devolve `usage.input_tokens`,
   então o campo `input_tokens_total` saiu 0. O total certo vem de `explore.py` (dev e teste: 1.307.829 tokens de
   entrada). Nenhuma métrica registrada depende disso.
7. **Rodada do teste.** Houve 5 HTTP 500 da API, todos no mesmo PR, e a 6ª tentativa respondeu. Nenhum PR ficou sem
   resposta.
8. **Janelas de reinício do vLLM informadas pelo líder (12:47–12:52 e 14:22–14:27 UTC).** Nenhuma chamada caiu na
   primeira, porque as chamadas começaram por volta de 13:55. Os 5 HTTP 500 do item 7 (o primeiro PR do teste,
   0xAX/linux-insides#972) são da segunda janela. O item foi refeito automaticamente e a resposta gravada é a da
   tentativa que funcionou. Nenhuma outra resposta veio de chamada com erro.
9. **Campo da pergunta.** O código sempre usou `instructions` (via `ekbasis.prompts.yes_no`), nunca `question`. Checagem:
   p_api ≠ p_other em 144 de 148 PRs do dev e em 325 de 329 do teste, então as perguntas foram lidas. Nada foi anulado.
