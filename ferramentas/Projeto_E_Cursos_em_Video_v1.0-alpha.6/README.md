# Projeto E — Cursos em Vídeo

**Versão:** `1.0-alpha.6`  
**Tipo de lançamento:** alpha técnica distribuível  
**Promoção pedagógica:** `promotion_ready=false`  
**Núcleo obrigatório:** Python 3.10+, sem API key  
**Limite do ZIP:** 500 MB decimais

Este pacote transforma um objetivo, livro, slide, lista, código ou relatório em
uma rota de aprendizagem por vídeos:

```text
fonte → mapa V1 conferido → busca mundial registrada → candidatos
      → inventário de áudio/legendas → inspeção interna de conteúdo e faixa
      → cobertura derivada → pré-teste + trechos + pós-teste + retenção
```

A alpha.6 separa duas perguntas:

1. o vídeo ensina ou resolve exatamente o que a unidade exige?
2. existe uma faixa em português ou inglês que foi realmente ouvida e
   conferida?

Um “sim” na primeira não compensa um “não” na segunda. Título, descrição,
thumbnail, idioma da consulta, nome da faixa e legenda são metadados; nenhum
deles libera uma rota.

## Instalação

Uso direto:

```bash
cd Projeto_E_Cursos_em_Video_v1.0-alpha.6
python3 -m projeto_e_video --help
python3 -m projeto_e_video doctor
```

Instalação isolada:

```bash
python3 -m venv /tmp/projeto-e-video-venv
/tmp/projeto-e-video-venv/bin/python -m pip install .
/tmp/projeto-e-video-venv/bin/projeto-e-video --help
```

O núcleo não baixa modelos nem exige credencial. Integrações opcionais:

- `yt-dlp`: busca pública, inventário de formatos e coleta;
- `ffmpeg`: frames e amostras de áudio;
- `pdftotext`: PDFs com camada textual;
- `pdfinfo` + `pdftoppm` + `tesseract`: OCR local opt-in de PDFs
  digitalizados;
- `tesseract`: OCR de imagens, usando os idiomas realmente instalados.

Para instalar a automação pública de busca, inventário e coleta sem API key:

```bash
python3 -m pip install '.[automation]'
python3 -m projeto_e_video doctor
```

`doctor` é somente leitura e não usa rede. Ele mostra o que está disponível e
quais capacidades continuam no fluxo manual.

Sem qualquer ferramenta opcional, o fluxo manual por navegador continua
disponível por prompts e importação JSON.

Há duas famílias de instruções, com funções diferentes:

- `PROMPTS/`: papéis permanentes e literais que pertencem a esta versão;
- `<workspace>/prompts/`: tarefas geradas pelo programa com IDs e conteúdo do
  curso corrente.

Não copie IDs de um workspace para outro.

## Demonstração offline

```bash
python3 -m projeto_e_video demo --workspace /tmp/projeto-e-video-demo
```

A demonstração usa apenas fixtures e deve terminar como
`DEMONSTRACAO_FIXTURE`. Ela testa infraestrutura, nunca qualidade de vídeos ou
aprendizagem.

## Fluxo real

### 1. Ingerir e criar mapa V0

```bash
python3 -m projeto_e_video create \
  --input "/caminho/livro-ou-pasta" \
  --source "/outro/caminho/lista-de-exercicios.pdf" \
  --workspace "/caminho/externo/curso-01" \
  --title "Meu curso"
```

Também é possível usar um tópico literal. Para URL, a rede só é acessada com
`--allow-network`; hosts privados, locais, reservados, credenciais e portas
incomuns são bloqueados.
`--source` pode ser repetido para reunir arquivos não contíguos. Todos entram no
mesmo manifesto com hash; o mapa rejeita localizações que não pertençam a ele.
O arquivo `search_queries.json` existe no V0, mas sua lista `queries` fica
literalmente vazia. Nenhuma busca é materializada antes da conferência V1.
`create` publica ingestão, mapa e prompts como uma única transação. Entrada
vazia é rejeitada e nunca representa o diretório corrente. Livros extensos
permanecem integrais em `ingest/text/`, enquanto o V0 é limitado a 32 unidades
por fonte e 128 no conjunto para não sobrecarregar o agente de revisão.

O escopo é literal. Se a entrada for `relatorio_semanal.pdf`, somente esse PDF
é inventariado; `manifest.json`, imagens e demais arquivos ao lado não são
inferidos. Para usar um pacote FlashList estruturado, forneça explicitamente a
pasta do pacote ou seu `manifest.json`.

PDF digitalizado requer autorização explícita para o trabalho de OCR:

```bash
python3 -m projeto_e_video create \
  --input "/caminho/livro-digitalizado.pdf" \
  --workspace "/caminho/externo/curso-ocr" \
  --ocr-scanned-pdf
```

Sem a opção ou sem as ferramentas locais, a fonte fica inventariada com a
lacuna correspondente; o programa não finge ter lido o PDF.

### 2. Conferir e importar mapa V1

Siga `prompts/01_REFINAR_MAPA.md` e importe o JSON:

```bash
python3 -m projeto_e_video import-map \
  --workspace /caminho/externo/curso-01 \
  --file /caminho/mapa-conferido.json
```

Busca e importação de candidatos são bloqueadas enquanto o mapa não for
`V1_VERIFIED`.

### 3. Buscar em escopo mundial

Modo navegador:

```bash
python3 -m projeto_e_video search \
  --workspace /caminho/externo/curso-01 \
  --provider manual
```

Modo opcional sem API key:

```bash
python3 -m projeto_e_video search \
  --workspace /caminho/externo/curso-01 \
  --provider yt-dlp --limit 3 --max-queries 120
```

Para uma rodada curta e auditável:

```bash
python3 -m projeto_e_video search \
  --workspace /caminho/externo/curso-01 \
  --provider yt-dlp --language en --unit-id U-... \
  --stage EXACT_OBJECT --limit 3 --max-queries 1
```

Sem opção de política, ambos os provedores processam somente unidades
`REQUIRED`. O próprio `--unit-id` é opt-in quando aponta para uma unidade não
obrigatória. Para lotes inteiros, use conscientemente `--include-optional` ou
`--include-control`; controle fácil nunca entra por omissão.

O plano começa por PT/EN e inclui mais de 30 sementes linguísticas. O agente de
navegador deve ampliar para qualquer idioma relevante e registrar cada
tentativa. `GLOBAL_OPEN` significa “nenhum idioma excluído”, não a alegação
impossível de ter consultado todos os idiomas humanos. Uma busca incompleta não
pode produzir `NAO_ENCONTRADO`.

O mapa V1 registra idioma da fonte, autor/obra/edição/capítulo/exercício,
frases, notação, termos e ecossistemas oficiais. Uma semente sem âncora neutra
ou tradução conferida fica `execution_ready=false`: a automação não mistura
cegamente um título português com uma ação em outro idioma. Fora do idioma da
fonte, texto bibliográfico e rótulos só entram após localização conferida; sem
ela, apenas notação ou autor/canal + código numérico podem tornar a consulta
executável.
Para teoria, `SOURCE_ECOSYSTEM_DISCOVERY` usa uma consulta curta e sem excesso
de aspas no curso/canal oficial. Para exercícios, `EXACT_OBJECT_MINIMAL`
consulta primeiro apenas o objeto distintivo localizado. Número, autor, fonte
e ação genérica ficam em tentativas separadas; equivalente rigoroso só vem
depois. Uma playlist pode orientar a navegação, mas nunca entra como candidato
no lugar do URL direto.

Chamadas `yt-dlp` são incrementais: preservam tentativas e candidatos, avançam
pelas pendências e mostram progresso. Use `--retry-failed` para repetir apenas
falhas. A pontuação `metadata_triage` explica prioridade e colisões lexicais,
mas nunca libera conteúdo.

Tentativas das sementes preservam o `Q-...` e usam `origin=SEED_PLAN`.
Traduções e consultas novas usam `origin=OPEN_EXPANSION`; o importador gera um
`QX-...` estável a partir da unidade, idioma e consulta literal e atualiza os
vínculos dos candidatos. Assim, a busca pode ultrapassar a lista inicial sem
perder rastreabilidade.
`search_report.json` é rederivado também após cada importação. O progresso
principal cobre somente `REQUIRED`, enquanto `policy_progress` mantém opcionais
e controle separados. Contagens de
sementes e de `OPEN_EXPANSION` ficam separadas, de modo que concluídas +
pendentes permaneça coerente com o plano automático.

Para o modo manual, importe o JSON v3:

```bash
python3 -m projeto_e_video import-candidates \
  --workspace /caminho/externo/curso-01 \
  --file /caminho/candidatos.json
```

### 4. Inventariar áudio e legendas

```bash
python3 -m projeto_e_video inspect-audio \
  --workspace /caminho/externo/curso-01 \
  --candidate-id VID-...
```

Sem `yt-dlp`, siga `prompts/03_INVENTARIAR_AUDIO.md` e importe:

```bash
python3 -m projeto_e_video import-audio-inventory \
  --workspace /caminho/externo/curso-01 \
  --file /caminho/audio_inventory.json
```

O inventário v2 permanece `metadata_only=true`. Legenda é registrada
separadamente com `counts_as_dubbing=false`. O inventário automático agrupa os
vários codecs/níveis de qualidade da mesma faixa, preserva todas as faixas de
áudio detectadas e limita legendas às famílias PT/EN. Metadados do `yt-dlp` são
auxiliares e não substituem a confirmação no seletor do player.
Tags privadas de provedor são preservadas, reduzidas ao prefixo BCP-47
confiável e acompanhadas de aviso sem interromper as outras faixas.

### 5. Coletar evidências

Frames e legendas solicitadas explicitamente:

```bash
python3 -m projeto_e_video collect \
  --workspace /caminho/externo/curso-01 \
  --candidate-id VID-... --frame-at 60 --frame-at 180 \
  --subtitle-language pt-BR
```

Amostras da faixa escolhida:

```bash
python3 -m projeto_e_video collect \
  --workspace /caminho/externo/curso-01 \
  --candidate-id VID-... \
  --audio-track ATRACK-... \
  --audio-segment 60:95 --audio-segment 180:225
```

Todo artefato recebe tamanho e SHA-256. Coleta não equivale a inspeção.
Cada artefato fica em `evidence/assets/<candidate_id>/`; amostras de áudio
incluem o `track_id` no nome. A coleta automática aceita YouTube, Vimeo e
Dailymotion. Outros hosts continuam auditáveis manualmente no navegador.
Frames e áudio usam somente seções curtas; legendas não são baixadas sem
`--subtitle-language`. Cada execução produz `REVIEW_CHECKLIST.md`. Se o runtime
não reproduz áudio, a revisão fica pendente e `audio_reviews` permanece vazio.
Na coleta de frames, um stream HTTPS progressivo é preferido antes do fallback
HLS, evitando recortes MP4 vazios observados em vídeos públicos reais.

### 6. Auditar conteúdo e faixa

Siga `prompts/04_AUDITAR_VIDEOS.md`. Para cada unidade, confira:

- identidade do vídeo;
- fala/transcrição e evidência visual ligadas aos mesmos timestamps;
- `speech_or_transcript_observed` preenchido em cada timestamp, não apenas uma
  descrição geral;
- todos os passos obrigatórios em rota única, ou todos os passos reivindicados
  por cada componente de uma futura rota composta;
- equivalência e pré-requisitos;
- faixa PT/EN realmente ouvida;
- termos técnicos, fórmulas, nomes, alinhamento e sincronização;
- erros ou incertezas.

A faixa escolhida deve ser ouvida nos mesmos trechos dos passos reivindicados.
Ouvir uma amostra isolada não valida a faixa para o vídeo inteiro.

```bash
python3 -m projeto_e_video audit \
  --workspace /caminho/externo/curso-01 \
  --evidence /caminho/evidencias.json
```

O código deriva `EXATO`, `EQUIVALENTE_RIGOROSO`, `PARCIAL`,
`TEORIA_APENAS`, `ERRO_MATEMATICO`, `NAO_VERIFICAVEL` ou
`NAO_ENCONTRADO`. Somente as duas primeiras, junto de faixa PT/EN verificada,
podem entrar no curso.
O motor também pode derivar `coverage_mode=COMPOSITE`: a união de dois ou mais
vídeos fecha os passos somente quando cada componente é internamente
exato/equivalente, não tem conflito/pré-requisito ausente e possui áudio PT/EN
ouvido para o seu subconjunto.

### 7. Construir e validar

```bash
python3 -m projeto_e_video build --workspace /caminho/externo/curso-01
python3 -m projeto_e_video validate-workspace \
  --workspace /caminho/externo/curso-01
```

Saídas:

```text
course/
├── COURSE.md
├── course.json
└── index.html
```

O validador rederiva mapa, consultas, candidatos, inventário, auditoria, curso,
Markdown e HTML. Uma lacuna honesta mantém o curso `PARCIAL`.
Unidades `OPTIONAL` e `CONTROL_NO_AUTOMATIC` podem ficar disponíveis por escolha
explícita, mas não são recomendadas automaticamente nem entram no denominador
obrigatório.

## Entradas

- tópico ou objetivo literal;
- arquivo ou diretório;
- ZIP com proteção contra travessia, duplicatas, symlinks e expansão excessiva;
- texto, Markdown, CSV, JSON, notebook, XML, HTML e código;
- DOCX, PPTX, XLSX, ODT, ODS, ODP e EPUB pela biblioteca padrão;
- PDF textual com `pdftotext` e PDF digitalizado por OCR local explícito;
- imagem com `tesseract`, sem exigir simultaneamente PT e EN;
- pacote FlashList por pasta ou `manifest.json` explícito, nunca inferido de um
  PDF vizinho;
- URL declarada ou baixada com autorização explícita.

Formato ilegível permanece `EXTRACAO_NAO_DISPONIVEL`.

## Limites honestos

- O sistema garante estados explícitos e gates; não garante que a internet
  contenha um vídeo adequado para todo assunto.
- Falha de ingestão ou planejamento não deixa workspace parcial; o operador
  pode corrigir a entrada e repetir com o mesmo destino vazio.
- Plataformas podem limitar formatos ou legendas por região, conta, runtime,
  bloqueio temporário ou taxa; a falha fica registrada e o fluxo manual
  permanece disponível.
- Encontrar um vídeo não prova que o aluno aprendeu.
- `promotion_ready=false` permanece até revisão humana e piloto estudantil.
- Vídeos, fontes, transcrições, áudio, frames, runs e credenciais ficam fora do
  pacote e do ZIP.

Leia [ARQUITETURA.md](ARQUITETURA.md),
[PROMPT_MESTRE_PARA_AGENTE.md](PROMPT_MESTRE_PARA_AGENTE.md) e
[docs/FLUXO_COMPLETO.md](docs/FLUXO_COMPLETO.md).
