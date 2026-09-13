# Operação sem API key — v1.0-alpha.6

O núcleo não chama modelo, serviço pago nem API autenticada. Python 3.10+
basta para ingestão textual, mapa, importações, auditoria, curso, validação e
empacotamento.

## Busca

`--provider manual` entrega um prompt literal para o navegador.
`--provider yt-dlp` executa consultas públicas. Ambos usam o mesmo
`candidates.json` v3 e nenhum exige chave.

Diagnóstico e instalação opcional:

```bash
python3 -m projeto_e_video doctor
python3 -m pip install '.[automation]'
```

`doctor` não usa rede nem instala ferramentas. Sem `yt-dlp`, o fluxo manual
permanece funcional e os mesmos gates continuam obrigatórios.

O plano é `VERIFIED_CHANNEL_ALLOWLIST`: possui mais de 30 sementes e manda o agente ampliar
para qualquer idioma. Cada tentativa fica registrada. Nenhum idioma de consulta
é atribuído automaticamente ao vídeo.

O V0 não contém consultas executáveis. No V1, teoria usa descoberta curta no
ecossistema oficial; exercícios tentam objeto/número exato antes de equivalente.
Filtros por idioma, unidade e fase permitem testar e retomar lotes pequenos sem
apagar as pendências globais.

Somente `REQUIRED` entra por padrão. `OPTIONAL` e `CONTROL_NO_AUTOMATIC`
exigem ID ou flag explícita. O progresso obrigatório fica separado em
`policy_progress`. Em idioma diferente da fonte, texto não localizado não é
âncora: apenas tradução conferida, notação ou autor/canal + código numérico
podem produzir semente executável.

Sementes usam `SEED_PLAN`; traduções e consultas livres usam
`OPEN_EXPANSION` e recebem um ID `QX-...` estável no importador. Portanto, a
abertura mundial não depende de uma lista fechada nem perde a cadeia de origem.
O relatório separa a quantidade de sementes concluídas das expansões abertas;
uma importação cumulativa nunca infla a contagem do plano.

## Áudio e visual

Ferramentas opcionais:

- `yt-dlp`: busca, metadados, faixas e legendas públicas;
- `ffmpeg`: frames e amostras de áudio;
- `pdftotext`: PDFs;
- `pdfinfo` e `pdftoppm`: contagem/renderização de PDF digitalizado;
- `tesseract`: OCR de imagens e, por opt-in, de PDFs digitalizados.

Sem elas, o navegador produz candidatos, inventário de áudio, screenshots e
observações nos mesmos contratos. Ausência de ferramenta nunca afrouxa o gate.
Automação de mídia é limitada a YouTube, Vimeo e Dailymotion; demais hosts usam
o mesmo contrato por inspeção direta no navegador.

Fluxo manual:

1. `create`;
2. conferir e `import-map`;
3. `search --provider manual`;
4. importar candidatos e tentativas;
5. inventariar áudio e importar;
6. ouvir PT/EN, inspecionar frames e registrar evidência;
7. `audit`, `build` e `validate-workspace`.

Legenda, título traduzido e nome da faixa não contam como dublagem. Campos de
aprovação continuam proibidos.

## Credenciais

Não coloque chaves em JSON, `.env`, prompts, exemplos ou ZIP. Integração
externa criada pelo operador deve guardar credenciais no ambiente, fora desta
versão e do workspace compartilhado.

## Política fechada de canais YouTube — Projeto E

A descoberta de vídeos do YouTube opera em **HARD_ALLOWLIST**. O agente só pode pesquisar, avaliar, importar ou recomendar vídeos destes três canais:

1. Portal da Matemática OBMEP — `@portalmatematicaobmep`
2. Portal da Física OBMEP — `@portalfisicaobmep`
3. Brasil Escola Oficial — `@brasilescola`

Regras obrigatórias:
- não executar busca aberta/global no YouTube;
- Matemática: Portal da Matemática OBMEP tem prioridade; Brasil Escola é complementar;
- Física: Portal da Física OBMEP tem prioridade; Brasil Escola é complementar;
- demais disciplinas: usar somente Brasil Escola;
- qualquer quarto canal é rejeitado, inclusive quando o vídeo parece excelente;
- não existe fallback para canal não aprovado;
- se nenhum canal permitido cobrir o tópico com aderência suficiente, registrar `NAO_ENCONTRADO` e manter a lacuna.



## Política Projeto E v0.38 — canais YouTube fechados

Para a Convergência Acadêmica v0.38-alpha.1, a busca de YouTube é **HARD_ALLOWLIST** e contém exatamente três canais:

1. Portal da Matemática OBMEP — `@portalmatematicaobmep`
2. Portal da Física OBMEP — `@portalfisicaobmep`
3. Brasil Escola Oficial — `@brasilescola`

Regras operacionais: não usar busca global do YouTube; não aceitar quarto canal; não usar fallback externo; manter o tópico sem vídeo quando os canais permitidos não tiverem correspondência semanticamente suficiente. Em Matemática/Física, OBMEP tem prioridade editorial sobre Brasil Escola.


## Política Projeto E v0.39 — HARD_ALLOWLIST + prova independente de canal

A Convergência Acadêmica v0.39-alpha.1 aceita **exatamente** três canais YouTube: `@portalmatematicaobmep`, `@portalfisicaobmep` e `@brasilescola`. O agente não pode executar busca global, não pode aceitar quarto canal e não pode usar fallback. Além disso, a etiqueta de fonte herdada ou o fato de um portal oficial embutir um vídeo **não prova** que o vídeo foi publicado pelo canal aprovado. Para integração ativa é obrigatória prova independente de canal. Sem prova ou sem vídeo semanticamente suficiente, o tópico permanece sem vídeo.
