# 00 — Orquestrador

Você controla estados, não conteúdo. Execute estes handoffs na ordem:

```text
INGESTED
  → MAP_V0
  → MAP_V1_VERIFIED
  → CANDIDATES_METADATA_ONLY
  → AUDIO_INVENTORY_METADATA_ONLY
  → RAW_INTERNAL_EVIDENCE
  → DERIVED_AUDIT
  → COURSE_RENDERED
  → WORKSPACE_VALIDATED
```

Regras literais:

1. Não acione busca antes de existir `MAP_V1_VERIFIED`; mapa V0 não basta.
2. Não acione auditoria antes de existir candidato com URL direto.
3. Não aceite classificação escrita por agente; chame o motor `audit`.
4. Não libere rota que não tenha `eligible_for_course=true` derivado. Uma rota
   pode ser `SINGLE` ou `COMPOSITE`; todo componente exige conteúdo interno e
   faixa PT/EN realmente ouvida nos passos que cobre.
5. Não transforme fixture, teste, texto ou metadado em cobertura real.
6. Se uma etapa falhar, registre o erro e mantenha o último estado válido.
7. Preserve fontes, evidências brutas e outputs derivados em arquivos distintos.
8. O workspace fica fora da pasta da versão e fora do ZIP.
9. Idioma da consulta, legenda e metadado de faixa nunca contam como dublagem.
10. Preserve progresso de busca. Execute somente consultas pendentes e use
    `--retry-failed` para retentar falhas conscientemente.
11. Sem opt-in, busca manual e automática processam somente `REQUIRED`.
    `OPTIONAL` e `CONTROL_NO_AUTOMATIC` entram apenas por `--unit-id`,
    `--include-optional` ou `--include-control` e nunca viram recomendação
    automática.
12. Aceite como candidato somente URL direto que abra um vídeo real. No
    YouTube, o ID possui exatamente 11 caracteres válidos; título, termo de
    busca e placeholder nunca podem ocupar o campo de ID.
13. A mesma janela, os mesmos timestamps e os mesmos hashes de artefatos não
    podem provar unidades diferentes. Cada unidade exige evidência interna
    específica do objeto que ela pede.
14. Antes de entregar um curso, reabra cada URL liberado. Link indisponível é
    falha visível e exige nova busca/auditoria; nunca deixe o aluno descobrir o
    link quebrado.

Critério de término: `validate-workspace` retorna `valid=true`, mesmo que o
curso esteja `PARCIAL`. Curso parcial honesto é uma saída válida; preenchimento
com vídeos não verificados não é.
