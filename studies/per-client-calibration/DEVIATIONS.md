# Desvios e esclarecimentos

1. **Empate na seleção do método primário (dev, k = 20).** A e AR tiveram exatamente a mesma Δacurácia no dev
   (+0,0428): nos clientes de dev o piso de recall nunca chegou a ser acionado. O PREREG diz "o de maior Δacurácia" e não
   define desempate; o `analysis.py` congelado desempata pela ordem da lista {A, AR, C, B0, B} e escolheu **A**. Não
   mudei nada. No teste, AR também falha H1 (+0,0099 [−0,0077, +0,0399]), então o veredito não depende do desempate.
2. **Aviso de overflow em `exp`** durante a fase de teste: vem de σ(a·z + b) com |z| até 13,8 (p recortado em 1e−6).
   O NumPy devolve 0 ou 1, que é o valor correto do limite; não altera nenhuma decisão.
3. **Clientes que saem por k.** Pela regra de ≥ 10 itens de avaliação, em k = 20 o teste tem 18 clientes-pergunta
   (umami sai); em k = 50 tem 10 (só kratos, mattermost, triggerdev e os 4 do TS-Bench). Era esperado pelo desenho.

Nenhuma outra alteração. Nenhuma chamada à API foi feita.
