# AGENTS.md — Projeto E Cursos em Vídeo v1.0-alpha.6

Esta pasta é uma versão isolada derivada diretamente da `v1.0-alpha.5` e
semanticamente da `Projeto_E_v4.7-alpha.1`. Não edite nenhuma origem nem versão
irmã para sincronizá-la.

## Invariantes

1. Aceite qualquer entrada, mas não finja ter extraído conteúdo ilegível,
   cifrado, corrompido ou inacessível.
2. Feche o mapa como `V1_VERIFIED` antes de procurar ou importar vídeos. O
   programa deve bloquear busca no mapa V0.
3. Cada unidade pertence a exatamente um produto interno:
   `CURSO_DE_TEORIA` ou `CURSO_DE_RESOLUCOES_DE_EXERCICIOS`. Um curso composto
   pode orquestrar ambos, mas a evidência nunca é compartilhada.
4. Teoria não cobre resolução; texto não cobre vídeo; título, snippet,
   thumbnail e metadados não cobrem conteúdo.
5. `EXATO` e `EQUIVALENTE_RIGOROSO` exigem inspeção interna, timestamps,
   fala/transcrição, frames ou inspeção direta e todos os passos essenciais.
6. O agente fornece observações brutas. `projeto_e_video.audit` deriva o estado;
   campos como `approved`, `classification` e `coverage_status` são proibidos
   na entrada.
7. Curso parcial deve mostrar lacunas. Nunca aceite vídeo ruim para completar
   visualmente a rota.
8. Assistir não é aprender. Toda rota liberada inclui tentativa anterior,
   problema equivalente e teste posterior de retenção.
9. Saúde, direito, segurança e outros temas sensíveis recebem sobreposição de
   risco; não prometer cura, diagnóstico ou substituição profissional.
10. Runs, fontes do usuário, vídeos baixados, transcrições completas,
    credenciais e `.env` ficam fora desta pasta e do ZIP.
11. A busca é `VERIFIED_CHANNEL_ALLOWLIST`: começa pelas sementes multilíngues, admite qualquer
    idioma-fonte e registra tentativas. Nunca declare busca universal exaustiva.
12. Idioma da consulta não é idioma do vídeo. Faixa anunciada e legenda não são
    dublagem verificada.
13. Uma rota real exige conteúdo `EXATO`/`EQUIVALENTE_RIGOROSO` e ao menos uma
    faixa PT/EN realmente ouvida, com terminologia, notação, alinhamento e
    sincronização conferidos em cada componente.
14. Consultas-semente usam `SEED_PLAN`; consultas novas usam
    `OPEN_EXPANSION` e identidade `QX-...` derivada. Não invente IDs canônicos.
15. Cada timestamp traz fala/transcrição local. Artefatos pertencem à pasta do
    candidato, amostras de áudio contêm o `track_id`, e a faixa precisa cobrir
    todos os passos reivindicados pelo componente; a união é derivada pelo motor.
16. Extração automática de mídia fica restrita às plataformas allowlisted;
    outras URLs públicas usam inspeção manual, sem afrouxar os gates.
17. Busca automática é retomável e nunca apaga progresso. Consulta sem tradução
    ou âncora confiável fica `LOCALIZATION_REQUIRED`.
18. `OPTIONAL` e `CONTROL_NO_AUTOMATIC` exigem opt-in e nunca são recomendados
    automaticamente. Sem filtro explícito, busca manual e automática processam
    somente `REQUIRED`; `--unit-id`, `--include-optional` e
    `--include-control` são atos de opt-in.
19. Entrada vazia nunca significa diretório corrente. `ingest` e `create`
    publicam tudo ou nada; falha deve preservar o workspace vazio ou anterior.
20. O texto integral fica em `ingest/text/`; o V0 permanece limitado a 32
    unidades por fonte e 128 no conjunto, representando cada fonte e suas
    faixas completas antes da revisão V1.
21. OCR de PDF é explícito com `--ocr-scanned-pdf`, limitado e auditável.
    Ausência de camada, ferramenta ou idioma produz lacuna, nunca conteúdo
    presumido.
22. Em idioma diferente da fonte, obra, enunciado e rótulos textuais de
    capítulo/exercício só entram após tradução conferida. Sem ela, apenas
    notação ou identificador oficial + código numérico podem ser executados.
23. FlashList só é pacote estruturado quando a pasta ou o `manifest.json` forem
    entradas explícitas. Se a entrada for um PDF, cubra somente o PDF; imagens
    vizinhas podem ser uma fila mutável paralela e nunca entram por inferência.
24. Placeholder não é URL de vídeo. IDs diretos de plataforma devem ser
    sintaticamente válidos; a mesma janela e os mesmos artefatos não podem ser
    reciclados para afirmar cobertura de unidades distintas.

## Como alterar

- Edite código em `projeto_e_video/`, prompts em `PROMPTS/`, esquemas em
  `schemas/` e fixtures em `examples/` ou `tests/fixtures/`.
- Não confunda `PROMPTS/` estático com `workspace/prompts/` gerado. Workspaces
  sempre ficam fora desta árvore.
- Execute `python3 -m unittest discover -s tests -p 'test_*.py' -v`.
- Execute `python3 -m projeto_e_video validate-release .`.
- Para fechar o pacote no acervo, acrescente `--require-origin`.
- Regenere manifesto e ZIP somente depois da última alteração.
- O ZIP precisa conter uma única pasta-raiz com este nome e permanecer abaixo
  de 500 MB.

Fixtures provam infraestrutura, não qualidade docente nem aprendizagem real.
Na entrega, informe versão tocada, pasta/ZIP, hashes, testes e pendências.

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

## Política v0.44 — TOTAL_ALLOWLIST

O agente só pode pesquisar, avaliar ou integrar vídeos dos canais @portalmatematicaobmep, @portalfisicaobmep e @brasilescola. URLs de sites externos e vídeos de qualquer outro canal devem ser rejeitados.
