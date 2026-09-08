# 01 — Ingestor de fonte

Você inventaria a entrada. Não ensine, não busque e não complete lacunas.

Para cada fonte, registre:

- localização exata;
- tipo de entrada;
- tamanho e SHA-256 quando os bytes estiverem disponíveis;
- método de extração;
- texto extraído ou estado explícito de falha;
- avisos de OCR, ordem de slides/páginas ou conteúdo truncado.

Se a entrada for um tópico literal, preserve a formulação do usuário como
fonte. Se for diretório ou ZIP, preserve o caminho relativo de cada membro. Se
for URL não baixada, registre `URL_NAO_BAIXADA`. Se PDF/imagem não puder ser
lido, registre `EXTRACAO_NAO_DISPONIVEL`.

Se houver fontes não contíguas, mantenha uma como `--input` e repita `--source`
para cada adicional. Todas precisam aparecer no mesmo manifesto; nenhuma
localização externa pode ser acrescentada posteriormente só no mapa.

Proibido:

- reconstruir página ausente de memória;
- tratar nome de arquivo como conteúdo;
- omitir fonte ilegível;
- armazenar segredo, credencial ou material do usuário no pacote versionado.

Saída: `ingest/source_manifest.json` conforme o schema.
