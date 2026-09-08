# Instruções para agentes futuros

## Identidade desta versão

Esta pasta é `Projeto_E_Cursos_em_Video_v1.0-alpha.6`, sucessora isolada da
`v1.0-alpha.5` e derivada semanticamente de `Projeto_E_v4.7-alpha.1`. Não edite
as origens, não sincronize alterações retroativamente e não substitua arquivos
de versões anteriores.

Antes de alterar, leia na ordem:

1. `AGENTS.md` desta pasta;
2. `README.md`;
3. `ARQUITETURA.md`;
4. este arquivo;
5. o arquivo específico e seus testes.

## Estrutura imutável de responsabilidade

```text
projeto_e_video/   código determinístico
PROMPTS/           papéis estáticos e literais
schemas/           contratos JSON
examples/          exemplos claramente marcados
tests/             testes offline sem API key
docs/              operação e decisões
```

Os prompts gerados para uma execução ficam em `<workspace>/prompts/`, fora da
versão. Eles contêm IDs e conteúdo daquele curso e nunca devem substituir os
papéis estáticos de `PROMPTS/`.

Não coloque `runs/`, workspaces, fontes recebidas, vídeos, transcrições reais,
frames reais, cache, segredo ou credencial dentro da versão.

## Como criar uma versão seguinte

1. Copie a versão inteira para uma nova pasta irmã com nome completo, por
   exemplo `Projeto_E_Cursos_em_Video_v1.0-alpha.7`.
2. Edite somente a nova pasta.
3. Atualize `VERSION`, `pyproject.toml`, `CHANGELOG.md`, documentação e baseline.
4. Preserve IDs, schemas e semântica ou documente migração explícita.
5. Execute todos os testes com bytecode desabilitado.
6. Execute demo em `/tmp` ou outro workspace externo.
7. Execute `validate-release`.
8. Gere um ZIP irmão com o mesmo nome da pasta e uma única pasta-raiz.
9. Confirme tamanho menor que 500 MB decimais e SHA-256.
10. Registre a versão no `CATALOGO_VERSOES.md` da raiz `Projeto E/`, dois níveis
    acima desta versão.
11. Não edite a pasta depois de criar o ZIP; qualquer correção exige repetir
    manifesto, testes, validação, empacotamento e hashes.

Nunca reaproveite o ZIP antigo nem inclua várias versões no mesmo ZIP.

## Gates que não podem ser removidos

- mapa antes de busca;
- entrada vazia nunca significa diretório corrente;
- `ingest` e `create` publicam tudo ou nada; não remova o staging transacional;
- texto integral permanece no ingest e o V0 continua limitado a 32 unidades
  por fonte/128 no conjunto, com ao menos uma por fonte;
- OCR de PDF é opt-in, limitado e nunca pode fingir leitura quando ferramenta,
  idioma ou camada textual estiver ausente;
- produtos teoria/resoluções separados por unidade;
- metadados não são inspeção;
- busca/importação exigem mapa V1 verificado;
- busca mundial é aberta a qualquer idioma e registra as tentativas; sementes
  não são alegação de exaustividade;
- sementes usam `SEED_PLAN`; expansões usam `OPEN_EXPANSION`, recebem ID
  `QX-...` canônico e mantêm o vínculo com candidatos;
- idioma da consulta não pode ser atribuído ao vídeo;
- inventário de faixa continua `metadata_only`;
- legenda não conta como dublagem;
- rota real exige faixa PT/EN ouvida e verificada em terminologia, notação,
  alinhamento e sincronização;
- evidência bruta não aceita classificação;
- `EXATO`/`EQUIVALENTE_RIGOROSO` exigem identidade, áudio/texto, visual,
  timestamps, artefatos e passos completos;
- cada timestamp contém fala/transcrição daquela janela; artefatos pertencem ao
  candidato, amostras contêm o `track_id` e a revisão de faixa cobre os passos
  reivindicados por cada componente;
- pré-requisito faltante impede rota principal;
- fixture não conta;
- tempo útil considera somente intervalos aceitos;
- assistir não prova aprendizagem;
- alpha permanece `promotion_ready=false`;
- coleta automática só usa plataformas públicas allowlisted; demais hosts usam
  inspeção manual com o mesmo contrato.
- busca automática preserva progresso e não executa tradução não conferida;
- texto bibliográfico ou rótulo da fonte não é âncora neutra em outro idioma;
  sem tradução, somente notação ou autor/canal + código numérico é executável;
- o V0 materializa zero consultas; teoria descobre o ecossistema oficial com
  termos amplos, e exercício preserva número/objeto antes do equivalente;
- consultas estritas, descoberta no canal/curso e expansão por frase/fórmula
  são tentativas separadas e registradas, nunca uma consulta gigante;
- contagens do plano `Q-...` e das expansões `QX-...` permanecem separadas;
- composição é derivada, nunca declarada pelo agente;
- busca processa somente `REQUIRED` por padrão; opcional/controle exige
  `--unit-id`, `--include-optional` ou `--include-control` e nunca vira
  recomendação automática.
- entrada PDF cobre somente o PDF. Não infira `manifest.json`, imagens ou
  outros arquivos vizinhos; pacote FlashList só é ativado quando a pasta ou o
  manifesto for a entrada explícita.
- ID direto de vídeo deve ser sintaticamente válido e reaberto antes da
  entrega; não reutilize a mesma janela e os mesmos hashes para unidades
  diferentes.

Se um pedido exigir enfraquecer um gate, crie experimento separado e rotule o
risco; não altere silenciosamente o produto principal.

## Testes mínimos por alteração

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m projeto_e_video demo --workspace /tmp/curso-demo-novo
PYTHONDONTWRITEBYTECODE=1 python3 -m projeto_e_video validate-release . --require-origin
```

Além dos testes afetados, confirme a `v1.0-alpha.5` pelo arquivo
`BASELINE_ORIGEM_Projeto_E_Cursos_em_Video_v1.0-alpha.5.json` e a linhagem v4.7
por `LINEAGE_SEMANTICA_Projeto_E_v4.7-alpha.1.json`.

## Relatório obrigatório na entrega

Informe: versão criada/tocada, pasta, ZIP, SHA-256, tamanho, testes executados,
hash da origem, lacunas e se houve ou não promoção. Validação estrutural nunca
deve ser descrita como prova de aprendizado.
