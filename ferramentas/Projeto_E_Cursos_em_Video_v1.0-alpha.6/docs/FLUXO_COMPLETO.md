# Fluxo completo e contratos — v1.0-alpha.6

## Estado 1 — entrada inventariada

```bash
python3 -m projeto_e_video create --input ENTRADA --source OUTRA_FONTE --workspace WORKSPACE --title TITULO
```

O workspace deve estar vazio e fora da versão. Cada fonte recebe localização,
hash, método e estado de extração. URL não usa rede sem `--allow-network`.
Entrada principal ou adicional vazia é rejeitada antes de qualquer leitura. A
criação usa staging e só publica o workspace depois que ingestão, mapa V0 e
prompts concluírem; uma falha deixa o destino vazio.

Para PDF digitalizado, o OCR local é explícito:

```bash
python3 -m projeto_e_video create --input LIVRO_SCAN.pdf \
  --workspace WORKSPACE --ocr-scanned-pdf
```

Sem `pdfinfo`, `pdftoppm`, `tesseract`, idioma instalado ou dentro do limite de
500 páginas, a lacuna permanece no manifesto. Nenhuma leitura é presumida.

Artefatos: `ingest/source_manifest.json`, textos extraídos, mapa V0,
`search_queries.json` com zero consultas executáveis e prompts. As consultas só
são materializadas após `import-map` fechar o V1.
O texto integral não é truncado para planejar: ele fica em `ingest/text/`. O
rascunho heurístico coalesce páginas/seções em no máximo 32 unidades por fonte
e 128 por conjunto, mantendo ao menos uma representação por fonte.

Se `ENTRADA` for um PDF, somente esse arquivo entra. Pasta, manifesto ou imagens
vizinhas não são inferidos. Um pacote `flashlist.weekly-study` só é expandido
quando sua pasta ou seu `manifest.json` é fornecido explicitamente.

## Estado 2 — mapa V1 verificado

O agente segue `prompts/01_REFINAR_MAPA.md` e importa:

```bash
python3 -m projeto_e_video import-map --workspace WORKSPACE --file MAPA.json
```

O importador recalcula IDs, valida fontes, produtos, passos, testes e estado de
verificação. Busca e candidatos são bloqueados antes desse estado.
Cada unidade também registra `search_identity` e `route_policy`; toda localização
precisa estar ligada a fonte inventariada.

## Estado 3 — busca mundial registrada

```bash
python3 -m projeto_e_video search --workspace WORKSPACE --provider manual
# ou
python3 -m projeto_e_video search --workspace WORKSPACE --provider yt-dlp
# repita para continuar; use --retry-failed somente para falhas
```

Ambos os modos selecionam somente `REQUIRED` por padrão. Uma unidade não
obrigatória exige `--unit-id`; lotes exigem `--include-optional` ou
`--include-control`.

Uma rodada pode ser filtrada sem ocultar o restante do trabalho:

```bash
python3 -m projeto_e_video search --workspace WORKSPACE --provider yt-dlp \
  --language en --unit-id U-ID --stage EXACT_OBJECT --max-queries 1
```

`search_queries.json` versão 3 contém:

- `search_scope=GLOBAL_OPEN`;
- alvos de áudio `pt,en`;
- mais de 30 idiomas-semente;
- consultas por unidade e idioma;
- política para ampliar a qualquer idioma.
- âncoras usadas, estratégia e `execution_ready`; tradução não conferida fica
  pendente em vez de produzir consulta híbrida.
- `SOURCE_ECOSYSTEM_DISCOVERY` para teoria e como fallback exato de exercícios,
  com termos amplos; consultas estritas não são transformadas em uma frase
  super-restrita para preencher metadados bibliográficos.
- `EXACT_OBJECT_MINIMAL` como primeira tentativa de exercício, contendo apenas
  o objeto distintivo localizado; autor, número e ação ficam separados.

`candidates.json` versão 3 separa:

- `language`: indício do idioma real, ou `und`;
- `language_basis`: origem desse indício;
- `discovery_languages`: idiomas das consultas que acharam o URL;
- `search_attempts`: consultas concluídas/falhas, inclusive zero resultados.
- `metadata_triage`: prioridade, correspondências e colisões somente para
  ordenar inspeção; nunca aprovação.

Cada tentativa contém `query_id`, `origin`, `unit_id`, `language`, `query`,
`status`, `result_count` e `error`. Consultas do plano usam `SEED_PLAN` e o ID
`Q-...`; expansões usam `OPEN_EXPANSION`, podem chegar com alias temporário e
recebem ID canônico `QX-...` no importador.

Busca nunca produz cobertura. Sem completar as sementes de uma unidade, zero
candidatos significa busca insuficiente, não `NAO_ENCONTRADO`.
Cada rodada preserva o ledger anterior e avança apenas pelas pendências.
Importações também rederivam `search_report.json`; consultas do plano e
expansões `QX-...` têm contadores separados.

## Estado 4 — inventário de áudio

```bash
python3 -m projeto_e_video inspect-audio --workspace WORKSPACE --candidate-id VID-ID
# ou
python3 -m projeto_e_video import-audio-inventory --workspace WORKSPACE --file AUDIO.json
```

`audio_inventory.json` v2 preserva faixas e legendas. O parser usa idioma,
`format_id`, rótulo e indícios original/manual/automático do `yt-dlp`, mas
marca toda faixa `metadata_only=true`. Formatos de codec/qualidade são agrupados
por faixa sem esconder os `format_id`. Todas as faixas detectadas permanecem no
inventário; a coleta automática de legendas limita-se às famílias PT/EN.
Sufixos privados do provedor são preservados e normalizados com aviso local,
sem abortar as demais faixas.

Uma faixa presente no inventário resulta apenas em `TRACK_METADATA_ONLY`.
Legenda resulta apenas em `SUBTITLE_ONLY`.

## Estado 5 — coleta externa

```bash
python3 -m projeto_e_video collect \
  --workspace WORKSPACE --candidate-id VID-ID \
  --frame-at 60 --audio-track ATRACK-ID --audio-segment 60:95 \
  --subtitle-language pt-BR
```

Limites:

- até 100 frames;
- até 20 amostras de áudio;
- até 10 minutos por amostra e 30 minutos no total;
- somente seções temporárias curtas, limitadas por tamanho;
- mídia completa nunca entra na versão;
- cada artefato final recebe tamanho e SHA-256.
- cada artefato final fica sob `evidence/assets/<candidate_id>/`;
- toda amostra de áudio inclui o `track_id` no nome;
- automação aceita YouTube, Vimeo e Dailymotion; outros hosts usam inspeção
  manual.
- legenda é opt-in e falha independentemente de frame/áudio;
- `REVIEW_CHECKLIST.md` explicita que escuta real continua obrigatória.
- frame prefere stream HTTPS progressivo e mantém HLS como fallback; o artefato
  ainda precisa ser aberto e inspecionado semanticamente.

## Estado 6 — evidência bruta

O agente segue `prompts/04_AUDITAR_VIDEOS.md` e produz
`evidence-input` versão 2. O importador rejeita campos de autoaprovação.

Conteúdo:

- URL/ID confirmados;
- métodos internos;
- fala/transcrição;
- frames;
- timestamps;
- passos observados;
- fala/transcrição observada em cada janela, no campo
  `speech_or_transcript_observed`;
- equivalência, pré-requisitos e conflitos.

Áudio:

- `track_id`;
- PT ou EN;
- original, manual ou automático observado;
- amostra AUDIO ou reprodução direta com captura da seleção;
- terminologia, notação, alinhamento e sincronização;
- problemas visíveis.

Uma revisão de faixa precisa estar ligada aos timestamps dos passos que o
componente reivindica; uma amostra sem correspondência não libera áudio.

## Estado 7 — auditoria derivada

```bash
python3 -m projeto_e_video audit --workspace WORKSPACE --evidence EVIDENCE.json
```

O motor revalida arquivos e hashes. Cada passo aprovado precisa de fala/áudio ou
transcrição e evidência visual ligados a um timestamp.

Conteúdo e acesso linguístico são derivados separadamente. Somente
`EXATO`/`EQUIVALENTE_RIGOROSO` mais faixa PT/EN verificada geram
`eligible_for_course=true`.
Quando nenhum candidato único fecha a unidade, o motor pode derivar
`coverage_mode=COMPOSITE` pela união de componentes estritos e auditados.

## Estado 8 — curso

```bash
python3 -m projeto_e_video build --workspace WORKSPACE
```

Cada rota contém tentativa anterior, faixa a selecionar, intervalos úteis,
pós-teste equivalente e retenção em 48–72 horas. Somente intervalos de uma rota
realmente elegível somam tempo.
`OPTIONAL` e `CONTROL_NO_AUTOMATIC` exigem opt-in e ficam fora do denominador.

## Estado 9 — validação

```bash
python3 -m projeto_e_video validate-workspace --workspace WORKSPACE
```

O validador confere:

1. manifesto, fontes ainda disponíveis, hashes, IDs e `course_id`;
2. mapa V1 canônico;
3. consultas mundiais rederivadas;
4. candidatos e tentativas canônicos;
5. inventário de áudio canônico;
6. artefatos e hashes;
7. auditoria rederivada;
8. elegibilidade de conteúdo + áudio;
9. união de passos em rota composta e tempo útil;
10. curso JSON, Markdown e HTML reconstruídos;
11. `promotion_ready=false`.

## Estados finais honestos

- `COBERTA`: todas as unidades têm rota real elegível.
- `PARCIAL`: uma ou mais lacunas permanecem.
- `DEMONSTRACAO_FIXTURE`: somente demonstração estrutural.

Um curso parcial validado é funcional e honesto. Não significa que a internet
tenha o vídeo inexistente nem que a aprendizagem foi comprovada.
