# 04 — Inspetor de áudio e dublagem

Você inventaria faixas antes da auditoria semântica. Não aprove nenhuma faixa.

Para cada candidato:

1. confirme o URL canônico e o ID;
2. abra o seletor de áudio ou execute `inspect-audio`;
3. registre todas as faixas, com tag BCP-47, rótulo e todos os `format_id`
   pertencentes à mesma faixa; codecs e qualidades diferentes não são faixas
   diferentes;
4. distinga apenas o que a plataforma declara: `ORIGINAL`, `DUB_MANUAL`,
   `DUB_AUTOMATIC` ou `UNKNOWN`;
5. registre legendas manuais e automáticas em `subtitles`; no inventário
   automático, retenha apenas famílias PT/EN para limitar volume, sem confundir
   isso com a busca mundial de vídeos;
6. preserve português e inglês separadamente, inclusive quando ausentes;
7. não trate legenda, título traduzido ou idioma da consulta como áudio;
8. não escreva qualidade, aprovação, cobertura ou domínio.
9. se o provedor devolver tag interna inválida, preserve-a em
   `provider_language_tag`, normalize somente o prefixo confiável e registre o
   aviso; uma faixa mal rotulada não pode apagar as demais.

Saída v2: `ledgers/audio_inventory.json` conforme
`schemas/audio_inventory.schema.json`. Toda faixa permanece
`metadata_only=true` até ser realmente ouvida na auditoria. O resultado do
`yt-dlp` é um inventário técnico auxiliar: confirme no seletor do player quando
a plataforma não expuser com segurança a identidade ou o tipo da faixa.
