# Referência da CLI — v1.0-alpha.6

| Comando | Função | Rede |
|---|---|---|
| `doctor` | relata ferramentas, capacidades e fallbacks | não |
| `create` | ingere e cria mapa V0 | somente com `--allow-network` |
| `import-map` | valida mapa V1 | não |
| `search --provider manual` | prepara busca de navegador | não |
| `search --provider yt-dlp` | executa sementes públicas | sim, sem API key |
| `import-candidates` | importa candidatos + tentativas | não |
| `inspect-audio` | inventaria faixas/legendas | sim, sem API key |
| `import-audio-inventory` | importa inventário do navegador | não |
| `collect` | coleta legendas, frames e/ou áudio | opcional |
| `audit` | deriva conteúdo e acesso PT/EN | não |
| `build` | gera JSON, Markdown e HTML | não |
| `validate-workspace` | rederiva e valida o curso | não |
| `demo` | fixture ponta a ponta | não |
| `validate-release` | valida versão/ZIP | não |
| `package-release` | manifesto + ZIP reproduzível | não |

Use `python3 -m projeto_e_video COMANDO --help` para argumentos. No fechamento
do acervo, `validate-release` e `package-release` devem receber
`--require-origin`.

`collect --audio-segment` recebe `START:END` em segundos e exige
`--audio-track ATRACK-...`.

`create --source` pode ser repetido para fontes adicionais. O V0 cria zero
consultas; `import-map` materializa o plano V1. `search` preserva o progresso,
aceita filtros repetíveis `--language`, `--unit-id`, `--stage` e aceita
`--retry-failed`. Por padrão, pesquisa somente `REQUIRED`; `--unit-id` faz
opt-in individual e `--include-optional`/`--include-control` fazem opt-in por
política. A saída do terminal mostra apenas uma prévia dos IDs; o
relatório completo fica em `ledgers/search_report.json`.
`create --ocr-scanned-pdf` habilita OCR local página a página somente quando um
PDF não tem camada textual; a opção exige `pdfinfo`, `pdftoppm` e `tesseract`.
Entrada vazia é erro e toda criação é publicada de forma transacional.
`collect --subtitle-language TAG` é opt-in;
`--automatic-subtitles` precisa ser solicitado separadamente. Frames e áudio
usam `--download-sections` internamente.

`inspect-audio` e `collect` automatizados resolvem DNS e aceitam somente
YouTube, Vimeo e Dailymotion. Para outro provedor, use inspeção no navegador e
os comandos de importação.
