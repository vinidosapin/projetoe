# Arquitetura — v1.0-alpha.6

## Princípio

O código controla identidade, estado e derivação; agente ou revisor observa a
fonte, o vídeo e a faixa selecionada. Nenhum campo escrito pelo agente pode
autoaprovar cobertura.

```text
INGESTÃO
  ↓
MAPA V0 HEURÍSTICO
  ↓ revisão direta da fonte
MAPA V1 VERIFICADO
  ↓
PLANO DE BUSCA GLOBAL_OPEN
  ↓ tentativas registradas
CANDIDATOS — METADADOS
  ↓
INVENTÁRIO DE ÁUDIO/LEGENDAS — METADADOS
  ↓ conteúdo + faixa realmente inspecionados
EVIDÊNCIA BRUTA
  ├─ cobertura do conteúdo
  └─ acesso linguístico PT/EN
       ↓
AUDITORIA DERIVADA
       ↓
COURSE.md + course.json + index.html
```

## Fronteiras obrigatórias

- `ingest.py`: agrega fontes não contíguas em uma transação, extrai ou registra
  lacuna, oferece OCR explícito e valida hashes; PDF é autônomo e pacote
  FlashList exige pasta/manifesto explícito; não pesquisa.
- `planning.py`: conserva o texto integral, limita o rascunho V0 a 32 unidades
  por fonte/128 no conjunto e constrói consultas após o V1; resultados não
  definem o currículo.
- `providers.py`: pesquisa metadados de forma retomável, preserva progresso,
  deriva triagem não aprobatória e bloqueia mapa V0.
- `audio.py`: inventaria faixas/legendas; toda faixa continua
  `metadata_only=true`.
- `collect.py`: coleta somente legendas/frames/amostras pedidos, usando seções
  curtas, e prepara checklist de escuta; não interpreta.
- `audit.py`: valida artefatos, liga passos a timestamps e deriva conteúdo e
  acesso linguístico separadamente.
- `course.py`: libera rota somente quando ambas as dimensões passam.
- `validation.py`: rederiva todos os outputs do workspace.
- `release.py`: verifica versão, baseline, segredos, manifesto e ZIP.

## Busca mundial

O plano automático contém português, inglês e mais de 30 sementes de consulta.
As consultas são ordenadas por idioma para cobrir todas as unidades em PT antes
de EN e depois ampliar mundialmente. Âncoras bibliográficas e fórmulas viajam
entre idiomas; texto da fonte só é usado no idioma correspondente ou após
tradução conferida. `LOCALIZATION_REQUIRED` impede consultas híbridas falsas.
No V0, a lista de consultas é vazia. Depois do V1, teoria usa
`SOURCE_ECOSYSTEM_DISCOVERY`; exercícios começam por `EXACT_OBJECT_MINIMAL`
com o objeto localizado, e mantêm objeto/número estrito e passagem ampla em
tentativas separadas antes do equivalente. Isso impede que uma única consulta
com autor, edição, seção, frase e fórmula esconda resultados válidos.

Não existe conjunto finito que prove “todos os idiomas humanos”. Por isso:

- `GLOBAL_OPEN` significa ausência de exclusão linguística;
- cada tentativa possui `query_id`, estado e quantidade de resultados;
- chamadas sucessivas executam apenas pendências; falhas exigem
  `--retry-failed` para nova tentativa;
- filtros de idioma/unidade/fase limitam somente a rodada atual; o relatório
  continua mostrando todas as pendências;
- sementes usam `origin=SEED_PLAN`; expansões livres usam
  `origin=OPEN_EXPANSION` e recebem `QX-...` canônico no importador;
- idioma da consulta fica em `discovery_languages`;
- idioma do vídeo fica `und` até metadado ou observação específica;
- `NAO_ENCONTRADO` só é derivado após concluir o plano de sementes daquela
  unidade; antes disso, o estado é `NAO_VERIFICAVEL`.
- importações rederivam o relatório e mantêm contadores distintos para o plano
  `Q-...` e expansões `QX-...`.

## Conteúdo versus acesso linguístico

Classificações de conteúdo:

`EXATO | EQUIVALENTE_RIGOROSO | PARCIAL | TEORIA_APENAS |
ERRO_MATEMATICO | NAO_VERIFICAVEL | NAO_ENCONTRADO`

Estados de acesso por idioma:

`ORIGINAL_PT | ORIGINAL_EN | DUB_MANUAL_PT | DUB_MANUAL_EN |
DUB_AUTOMATIC_PT | DUB_AUTOMATIC_EN | TRACK_METADATA_ONLY |
SUBTITLE_ONLY | NO_TARGET_AUDIO | NAO_VERIFICAVEL`

`EXATO` sem áudio PT/EN verificado preserva a classificação de conteúdo, mas
produz `eligible_for_course=false` e tempo recomendado zero.

## Gate de áudio

Uma revisão de faixa exige:

1. `track_id` pertencente ao candidato;
2. idioma-alvo PT ou EN compatível com a faixa;
3. reprodução direta registrada ou artefato AUDIO com hash;
4. ligação da amostra/captura aos timestamps usados para o conteúdo;
5. cobertura, pela faixa, de todos os passos reivindicados pelo componente;
6. terminologia técnica conferida;
7. fórmulas/notação e nomes próprios conferidos;
8. alinhamento semântico conferido;
9. sincronização conferida;
10. nenhum problema aberto;
11. consistência com o rótulo original/manual/automático quando conhecido.

Legenda possui `counts_as_dubbing=false` por contrato.

## Evidência de conteúdo

Cada passo essencial precisa aparecer em ao menos um intervalo com:

- descrição concreta;
- fala direta, transcrição ou áudio;
- frame/screenshot;
- IDs de artefato existentes;
- hashes correspondentes;
- identidade do candidato confirmada.

Todo timestamp registra localmente `speech_or_transcript_observed`; uma
descrição global não substitui essa prova. Artefatos ficam vinculados ao
candidato em `evidence/assets/<candidate_id>/`, e amostras de áudio trazem o
`track_id` no nome.

Um artefato solto ou uma transcrição não ligada aos timestamps não fecha o gate.
A mesma janela, os mesmos intervalos e os mesmos hashes não podem ser usados
para aprovar unidades distintas do mesmo candidato.

## Integridade

`audit.json` inclui hashes canônicos do mapa, consultas/candidatos, inventário
de áudio e evidência. `build` reexecuta a auditoria. `validate-workspace`
reconstrói ainda o curso, Markdown e HTML; edição manual de derivados falha.

## Rotas únicas e compostas

Cada unidade pertence a exatamente um produto:

- `CURSO_DE_TEORIA`;
- `CURSO_DE_RESOLUCOES_DE_EXERCICIOS`.

Um curso pode ordenar ambos, mas vídeo teórico nunca fecha resolução.

Uma rota `SINGLE` usa um vídeo que fecha todos os passos. Uma rota `COMPOSITE`
usa a união determinística de componentes; cada componente precisa ser o mesmo
objeto ou equivalente rigoroso no seu subconjunto, ter evidência audiovisual
local e faixa PT/EN ouvida nesses passos. Conflito, pré-requisito ausente ou
observação meramente `PARTIAL` impede sua participação.

`route_policy=REQUIRED` entra no denominador. `OPTIONAL` e
`CONTROL_NO_AUTOMATIC` podem ser oferecidos sob escolha explícita, sem
recomendação automática.

## Armazenamento e rede

Workspaces e mídia ficam fora da versão. Downloads de URL de entrada exigem
`--allow-network` e rejeitam rede privada/local/reservada, credenciais e
portas não usuais, inclusive em redirecionamentos. Ferramentas externas são
executadas sem shell e com timeout. Coleta automática de vídeo é restrita a
YouTube, Vimeo e Dailymotion; outras plataformas permanecem disponíveis para
inspeção manual no navegador.

`create` usa staging irmão no mesmo sistema de arquivos e só troca o workspace
depois de ingestão, mapa V0 e prompts concluírem. PDF sem texto pode usar
`pdftoppm+tesseract` página a página apenas com `--ocr-scanned-pdf`; ausência de
ferramenta ou limite excedido continua registrada como lacuna.
