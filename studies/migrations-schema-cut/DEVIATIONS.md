# Desvios do PREREG (sha256 02f3ba6c…)

1. **Interrupção da sessão (2026-10-11, à tarde).** O agente caiu por limite de sessão depois de congelar o PREREG,
   montar as entradas do T2 (`data/items_t2`) e clonar os repositórios do T3. Nenhuma chamada ao Ekbasis tinha sido
   feita, então nenhuma resposta se perdeu ou foi refeita. O trabalho retomou do passo seguinte (estados do T2). O
   estado OLD das 192 entradas reconstruídas, que incluem as 184 rotuladas, é byte a byte o do v4
   (`t2_same_as_v4.txt`: same 192, differ 0).
2. **T3, estado OLD.** O PREREG pede o estado OLD do `main`. No T3, ele foi gerado por `_named_state` do branch, que é
   o `build_state` do 0.1.17 sem mudança de código. A equivalência foi verificada no T2: nas 184 migrações, regime N,
   `_named_state` dá estados byte a byte iguais aos do checkout `ec91a41`.
3. **T3, chirpstack.** Pela regra do PREREG, entra a pasta PostgreSQL com mais arquivos encontrada pelos `DEFAULT_GLOBS`.
   No chirpstack, essa pasta é `chirpstack/src/integration/postgresql/migrations`, com 1 arquivo. A pasta principal,
   `migrations_postgres/*/up.sql`, não casa com nenhum glob padrão. A regra foi seguida e nenhuma reserva entrou,
   porque havia uma pasta encontrada. O efeito é que o T3 tem 1 migração do chirpstack, e não as dezenas da pasta
   principal.
4. **T3, base suja.** No fider (46 de 49), no webstudio (1) e no harbor (1), uma migração anterior não aplicou no
   scratch com o papel sem superusuário. As seguintes que falham no schema viram `cannot_foresee_base`, como no
   produto. Isso não muda a medida primária: nenhum estado OLD passou de 60 mil caracteres.
5. **Documentação depois do teste.** O commit `aea2632` (CHANGELOG e `docs/MIGRATION_GUARD.md`) veio depois do T2 e
   não muda código. O código testado é o `fab1d95`.
6. **Correção de um fato do §3 do PREREG.** O PREREG diz que os 2 fallbacks nos casos reais eram um EXECUTE
   (mattermost) e um estado longo demais (lemmy), e que coder-chat-search-update ficou correto depois do conserto das
   tabelas de transição. Isso foi escrito antes de rodar de novo os casos reais no `fab1d95`. A nova rodada mostra outra
   coisa:
   * os 2 fallbacks são mattermost-attribute-view (EXECUTE) e coder-chat-search-update, que continua sem resolver
     `chat_message_history_new_rows` e `chat_message_history_old_rows`;
   * lemmy-aggregates-deferred é cortado, com 50.459 caracteres.

   O conserto só reconhece as tabelas de transição declaradas na mesma migração ou nos triggers das tabelas tocadas, e
   este caso tem outra origem. Nada de código mudou, e nenhum veredito em código difere entre OLD e NEW nos 34 casos.
