# Changelog

## 1.0-alpha.6 — 2026-08-29

- reconhece exportações semanais `flashlist.weekly-study` somente quando a
  pasta ou o manifesto são entradas explícitas e cria uma unidade estável por
  item; um PDF é sempre tratado como o arquivo autônomo pedido;
- preserva disciplina, tópico, dificuldade, estado do asset e política de rota,
  mantendo enunciado ausente como lacuna explícita;
- acrescenta uma consulta exata mínima sem remover as buscas estrita, de
  ecossistema e equivalente;
- rejeita placeholders e IDs de YouTube que não tenham a forma de um vídeo
  direto real;
- impede que intervalos e hashes audiovisuais idênticos sejam reciclados para
  aprovar unidades diferentes;
- permite documentar inspeção visual `UNVERIFIABLE` sem inventar fala, sem
  afrouxar qualquer gate de aprovação;
- testa os três relatórios semanais e os 338 slides reais, separando links
  antigos quebrados, candidatos e rotas efetivamente liberadas.

## 1.0-alpha.5 — 2026-08-27

- impede consultas híbridas: em idioma diferente da fonte, texto bibliográfico
  e rótulos não traduzidos deixam de tornar a busca executável;
- permite busca estrangeira sem tradução somente com notação estrutural ou com
  identificador oficial/autor combinado a código numérico transportável;
- restringe busca manual e automática a unidades `REQUIRED` por padrão e exige
  opt-in por ID ou flags para `OPTIONAL` e `CONTROL_NO_AUTOMATIC`;
- separa o progresso obrigatório das pendências opcionais e de controle;
- adiciona `doctor` offline, extra instalável `automation` e instrução
  reproduzível para `yt-dlp`, mantendo o fallback de navegador sem API key;
- revalida o mapa real de 18 erros, três difíceis opcionais e um controle fácil,
  sem promover metadados, legenda ou áudio não ouvido a cobertura.

## 1.0-alpha.4 — 2026-08-26

- torna `ingest` e `create` transacionais: uma falha não publica diretórios,
  manifesto, mapa ou prompts parciais;
- rejeita `--input`/`--source` vazios antes de sondar caminhos, impedindo a
  ingestão silenciosa do diretório corrente;
- aumenta os limites para 64 MiB por arquivo/URL e 32 milhões de caracteres,
  mantendo 200 MiB por conjunto ou arquivo descompactado;
- limita o rascunho V0 a 32 unidades por fonte e 128 no conjunto, preservando
  todas as fontes e faixas de páginas no mapa, com o texto integral no ingest;
- troca consultas genéricas com ruído bibliográfico por objetos curtos
  localizados e mantém equivalente estrutural separado de objeto exato;
- adiciona OCR opt-in de PDF digitalizado, página a página e limitado, com
  `--ocr-scanned-pdf`, `pdfinfo`, `pdftoppm` e `tesseract`;
- faz OCR de imagem escolher PT/EN entre os idiomas realmente instalados, sem
  exigir os dois pacotes simultaneamente;
- acrescenta regressões para transação, entrada vazia, livro de 1.000 páginas,
  64 fontes, consultas curtas, OCR e todos os contêineres Office/EPUB
  declarados;
- valida em materiais reais do Dropbox livro TXT de 4 MB, PDF textual de 25 MB,
  PDF digitalizado, livros, slides, artigo, exercícios ZIP/imagem/LaTeX,
  código, relatórios e documentos Office;
- no corpus heterogêneo real, reduz o V0 de 1.740 para 66 unidades e, na mesma
  rodada PT/EN/ES, amplia candidatos de 10 para 133 sem promover metadados a
  cobertura;
- audita internamente quatro candidatos reais como `PARCIAL`, mantém as outras
  unidades `NAO_VERIFICAVEL`, libera zero rota sem áudio ouvido e preserva o
  curso como `PARCIAL` com tempo útil zero.

## 1.0-alpha.3 — 2026-08-25

- agrega fontes não contíguas com `--source`, trata literais longos sem
  `ENAMETOOLONG` e valida hashes de fontes/textos;
- mantém `search_queries.json` vazio no mapa V0 e limita prompts gerados a
  índices compactos, mesmo para fontes extensas;
- vincula cada localização curricular ao manifesto e rejeita referência
  externa não inventariada;
- acrescenta identidade bibliográfica, idioma-fonte, fórmulas, termos,
  ecossistemas oficiais, traduções conferidas e política da rota ao mapa V1;
- impede consultas híbridas em idioma estrangeiro quando falta tradução e
  torna essa pendência explícita;
- substitui buscas teóricas super-restritas por descoberta curta no ecossistema
  da fonte e separa, para exercícios, objeto exato, curso/canal e equivalente;
- torna a busca `yt-dlp` retomável, cumulativa, capaz de retentar falhas e de
  percorrer mais de 500 consultas em rodadas;
- rederiva `search_report.json` após importações e separa contagens das
  consultas-semente das expansões `OPEN_EXPANSION`;
- deriva triagem de metadados com razões e colisões, sem usar a pontuação como
  aprovação;
- tolera tags privadas de idioma do provedor, preserva o valor bruto e mantém
  as outras faixas;
- torna legendas opt-in, coleta frames/áudio por seções curtas e separa falhas
  de cada operação;
- prefere vídeo HTTPS progressivo para frames antes de HLS, corrigindo recortes
  MP4 vazios observados em um vídeo público real;
- gera pacote/checklist de escuta sem enfraquecer o gate humano de áudio;
- permite rota `COMPOSITE` somente pela união de componentes audiovisuais
  estritos com faixa PT/EN ouvida nos passos cobertos;
- adiciona `OPTIONAL` e `CONTROL_NO_AUTOMATIC`, sempre sob escolha explícita;
- substitui códigos internos por mensagens legíveis e corrige duplicação de
  segmentos no HTML;
- amplia validação cruzada, schemas e regressões para os defeitos do piloto;
- executa piloto independente com capítulo bibliográfico e exercícios reais,
  preservando como lacuna toda busca sem resolução adequada.

## 1.0-alpha.2 — 2026-08-25

- bloqueia busca e importação de candidatos antes do mapa `V1_VERIFIED`;
- substitui PT/EN/ES fixos por `GLOBAL_OPEN`, com mais de 30 sementes,
  expansão livre e registro de todas as tentativas;
- canonicaliza expansões livres como `QX-...` e preserva a ligação entre
  tentativa e candidato;
- deixa de inferir o idioma do vídeo a partir do idioma da consulta;
- acrescenta inventário canônico de faixas e legendas;
- agrupa codecs/qualidades da mesma faixa e conserva todas as faixas de áudio,
  limitando somente as legendas automáticas às famílias PT/EN;
- distingue áudio original, dublagem manual, automática e estado desconhecido;
- exige ouvir e auditar faixa PT/EN antes de liberar qualquer rota;
- fixa que legenda e metadado de faixa não contam como dublagem;
- coleta amostras de áudio por `track_id` e intervalo, sem API key;
- exige evidência de fala/áudio e visual ligada a cada passo e timestamp;
- exige fala/transcrição local em toda janela, artefatos vinculados ao
  candidato, `track_id` no áudio e revisão linguística sobre todos os passos;
- deriva busca incompleta separadamente de `NAO_ENCONTRADO`;
- bloqueia URLs privadas/locais/reservadas e redirecionamentos inseguros;
- restringe extração automática a plataformas públicas conhecidas, mantendo
  fallback manual para outras plataformas;
- converte timeout externo em erro operacional sem traceback;
- valida versão Python/PEP 440, baseline direta, manifesto e ZIP;
- mantém o validador executável no Python 3.10 sem depender de `tomllib`;
- corrige a governança para coleções físicas e caminhos de agentes futuros;
- amplia testes de áudio, busca, coleta, segurança, instalação e release.

## 1.0-alpha.1 — 2026-08-24

- cria produto isolado para transformar tópico, arquivo, diretório, URL ou ZIP em curso por vídeos;
- aceita texto, Markdown, CSV, JSON, HTML, código, DOCX, PPTX, XLSX, EPUB e, quando ferramentas locais existem, PDF e imagem;
- separa unidades de teoria e famílias de exercícios sem compartilhar cobertura;
- gera mapa curricular, consultas multilíngues e pacotes literais para agente de navegador;
- integra busca opcional com `yt-dlp`, sem API key;
- deriva `EXATO`, `EQUIVALENTE_RIGOROSO`, `PARCIAL`, `TEORIA_APENAS`, `ERRO_MATEMATICO`, `NAO_VERIFICAVEL` e `NAO_ENCONTRADO` a partir de evidência bruta;
- exige timestamps, fala/transcrição e frames ou inspeção direta para aprovar vídeo;
- gera `COURSE.md`, `course.json` e `index.html` com pré-teste, trecho útil, pós-teste e retenção;
- mantém entradas, vídeos completos, runs e credenciais fora do pacote versionado;
- inclui demonstração e testes inteiramente offline;
- recalcula a auditoria durante a construção e detecta adulteração de
  `audit.json`, `course.json`, Markdown e HTML;
- verifica o conteúdo do ZIP contra o manifesto, arquivo por arquivo.
