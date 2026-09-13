"""Geração de pacotes literais para agentes de navegador."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .util import atomic_write_text, read_json


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


def _bounded_rows(
    rows: list[dict[str, Any]], fields: tuple[str, ...], *, limit: int
) -> dict[str, Any]:
    selected = [
        {field: row.get(field) for field in fields if field in row}
        for row in rows[:limit]
    ]
    return {
        "total": len(rows),
        "included_in_prompt": len(selected),
        "truncated": len(rows) > limit,
        "items": selected,
    }


def _manifest_index(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "course_id": manifest["course_id"],
        "title": manifest["title"],
        "source_count": manifest["source_count"],
        "extracted_source_count": manifest.get("extracted_source_count", 0),
        "sources": _bounded_rows(
            manifest["sources"],
            (
                "source_id",
                "kind",
                "exact_locator",
                "media_type",
                "sha256",
                "extraction_status",
                "text_path",
                "warnings",
            ),
            limit=30,
        ),
    }


def _ledger_index(ledger: dict[str, Any], *, include_steps: bool) -> dict[str, Any]:
    fields = (
        "unit_id",
        "source_ids",
        "source_locators",
        "title",
        "product",
        "route_policy",
        "verification_state",
        "required_steps",
    ) if include_steps else (
        "unit_id",
        "source_ids",
        "source_locators",
        "title",
        "product",
        "route_policy",
        "verification_state",
        "extraction_gap",
    )
    return {
        "course_id": ledger["course_id"],
        "map_state": ledger["map_state"],
        "unit_count": len(ledger["units"]),
        "units": _bounded_rows(ledger["units"], fields, limit=30),
    }


def _query_index(queries: dict[str, Any]) -> dict[str, Any]:
    ready = [row for row in queries["queries"] if row.get("execution_ready")]
    return {
        "search_scope": queries["search_scope"],
        "query_count": len(queries["queries"]),
        "ready_count": len(ready),
        "seed_language_count": len(queries["seed_languages"]),
        "counts_by_language": dict(Counter(row["language"] for row in ready)),
        "counts_by_stage": dict(Counter(row["search_stage"] for row in queries["queries"])),
        "first_queries_in_execution_order": _bounded_rows(
            queries["queries"],
            (
                "query_id",
                "unit_id",
                "language",
                "query",
                "search_stage",
                "strategy",
                "execution_ready",
                "localization_note",
            ),
            limit=24,
        ),
    }


def _candidate_index(candidates: dict[str, Any]) -> dict[str, Any]:
    rows = candidates.get("candidates", [])
    return {
        "candidate_count": len(rows),
        "search_attempt_count": len(candidates.get("search_attempts", [])),
        "candidates": _bounded_rows(
            rows,
            (
                "candidate_id",
                "unit_ids",
                "url",
                "title",
                "channel",
                "language",
                "language_basis",
                "metadata_triage",
            ),
            limit=30,
        ),
    }


def _inventory_index(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_count": len(inventory.get("records", [])),
        "records": _bounded_rows(
            inventory.get("records", []),
            ("candidate_id", "candidate_url", "tracks", "subtitles", "warnings"),
            limit=30,
        ),
    }


def write_map_prompt(workspace: Path) -> Path:
    manifest = read_json(workspace / "ingest" / "source_manifest.json")
    ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
    manifest_path = (workspace / "ingest" / "source_manifest.json").resolve()
    ledger_path = (workspace / "ledgers" / "unit_ledger.v0.json").resolve()
    prompt = f"""# TAREFA LITERAL — CONFERIR O MAPA DO CURSO

Você é o cartógrafo da fonte. Não busque vídeos nesta etapa.

## Arquivos canônicos obrigatórios

- manifesto completo: `{manifest_path}`
- mapa V0 completo: `{ledger_path}`
- textos extraídos: `{(workspace / "ingest" / "text").resolve()}`

O índice abaixo é deliberadamente limitado para não derrubar o agente com um
livro inteiro. Ele **não define o escopo e não autoriza omissões**. Leia o
pedido/escopo recebido e confira diretamente todas as fontes correspondentes;
abra os arquivos canônicos em partes quando necessário.

Índice do manifesto:

{_json_block(_manifest_index(manifest))}

Índice do mapa heurístico:

{_json_block(_ledger_index(ledger, include_steps=False))}

## Faça exatamente isto

1. Leia primeiro o escopo pedido pelo usuário. Depois leia a fonte somente nas
   localizações que pertencem a esse escopo. Não transforme automaticamente o
   restante de um livro em curso. Se o escopo estiver ausente ou ambíguo, pare e
   peça o recorte; não adivinhe.
2. Leia a fonte nas localizações registradas. Se não conseguir lê-la, preserve
   a unidade com `extraction_gap=true`; não invente conteúdo.
   Em pacote FlashList, preserve exatamente uma unidade por item do manifesto,
   use o localizador `#flashlist-item:<item_ref>` já fornecido e mantenha o
   `route_policy` derivado. Nunca funda itens em uma unidade genérica do PDF.
3. Divida em unidades atômicas ensináveis. Preserve cada conceito, procedimento,
   exercício, restrição e exemplo obrigatório da fonte.
4. Para cada unidade selecione exatamente um produto:
   `CURSO_DE_TEORIA` ou `CURSO_DE_RESOLUCOES_DE_EXERCICIOS`.
5. Escreva pré-requisitos em ordem. Não use resultados de busca para redefinir
   o currículo.
6. Escreva `required_steps` observáveis. Em resolução, inclua leitura do alvo,
   método, hipóteses, passos decisivos, interpretação e conferência. Em teoria,
   inclua definições, relações, exemplo e preparação para prática.
7. Escreva pré-teste, pós-teste equivalente e retenção após 48–72 h.
8. Use `verification_state = VERIFIED_BY_AGENT` somente para unidades que você
   conferiu diretamente na fonte.
9. Cada `source_locator` deve começar pelo `exact_locator` de um `source_id`
   da própria unidade. Não cite PDF, slide ou página ausente do manifesto.
10. Preencha `search_identity` literalmente: idioma da fonte; autor/criador,
   obra, edição, capítulo, seção e exercício; frases exatas; notação; termos
   técnicos; canais/domínios oficiais e traduções que você realmente conferiu.
   Use string/lista vazia quando a fonte não informar. Não invente bibliografia.
11. Escolha `route_policy`: `REQUIRED`, `OPTIONAL` ou
   `CONTROL_NO_AUTOMATIC`. Controle fácil nunca é recomendado automaticamente.
12. Não inclua `approved`, `classification`, `coverage_status`, porcentagem,
   domínio ou promoção.

## Saída única

Devolva somente um objeto JSON com `schema_name =
projeto-e-video.unit-ledger`, `schema_version = 1`, `title` e `units`.
Preserve `source_ids` e `source_locators` existentes. O importador recalculará
cada `unit_id` usando o contexto da fonte e o conteúdo curricular; não use IDs
temporários como referência externa antes de importar.
"""
    target = workspace / "prompts" / "01_REFINAR_MAPA.md"
    atomic_write_text(target, prompt)
    return target


def write_search_prompt(
    workspace: Path,
    *,
    eligible_unit_ids: list[str] | None = None,
) -> Path:
    ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
    queries = read_json(workspace / "ledgers" / "search_queries.json")
    ledger_path = (workspace / "ledgers" / "unit_ledger.json").resolve()
    queries_path = (workspace / "ledgers" / "search_queries.json").resolve()
    if ledger.get("map_state") != "V1_VERIFIED":
        prompt = f"""# BUSCA BLOQUEADA — MAPA AINDA NÃO CONFERIDO

Não pesquise vídeos. O mapa está em `{ledger.get('map_state')}` e possui
{len(ledger.get('units', []))} unidades heurísticas. Consultas executáveis só
são criadas depois de `import-map` produzir `V1_VERIFIED`.

Faça exatamente isto:

1. conclua `prompts/01_REFINAR_MAPA.md`;
2. importe o JSON pela CLI com `import-map`;
3. abra novamente este arquivo, que será regenerado;
4. não invente candidatos nem tentativas de busca enquanto o bloqueio existir.

Arquivos: `{ledger_path}` e `{queries_path}`.
"""
        target = workspace / "prompts" / "02_BUSCAR_CANDIDATOS.md"
        atomic_write_text(target, prompt)
        return target
    known_unit_ids = {unit["unit_id"] for unit in ledger["units"]}
    if eligible_unit_ids is None:
        selected_unit_ids = {
            unit["unit_id"]
            for unit in ledger["units"]
            if unit.get("route_policy", "REQUIRED") == "REQUIRED"
        }
    else:
        selected_unit_ids = set(eligible_unit_ids)
        unknown = selected_unit_ids - known_unit_ids
        if unknown:
            raise ValueError(
                f"escopo do prompt contém unidades desconhecidas: {sorted(unknown)}"
            )
    scoped_ledger = {
        **ledger,
        "units": [
            unit for unit in ledger["units"] if unit["unit_id"] in selected_unit_ids
        ],
    }
    scoped_queries = {
        **queries,
        "queries": [
            row
            for row in queries["queries"]
            if row["unit_id"] in selected_unit_ids
        ],
    }
    policy_counts = dict(
        Counter(unit.get("route_policy", "REQUIRED") for unit in scoped_ledger["units"])
    )
    prompt = f"""# TAREFA LITERAL — LOCALIZAR CANDIDATOS DE VÍDEO

Você é somente pesquisador. Não aprove, não monte o curso e não declare
cobertura.

## Arquivos canônicos obrigatórios

- unidades congeladas: `{ledger_path}`
- consultas em ordem de execução: `{queries_path}`
- progresso acumulado: `{(workspace / "ledgers" / "candidates.json").resolve()}`

## Escopo autorizado desta execução

Unidades selecionadas: `{len(selected_unit_ids)}`. Políticas selecionadas:
`{json.dumps(policy_counts, ensure_ascii=False, sort_keys=True)}`.

Processe todos os itens canônicos pertencentes a esses IDs e nenhum item fora
deles. Sem opção explícita, o escopo contém somente `REQUIRED`. Uma unidade
`OPTIONAL` ou `CONTROL_NO_AUTOMATIC` só entra quando o operador usa seu
`--unit-id`, `--include-optional` ou `--include-control`. Truncamento dos
índices nunca autoriza omitir item selecionado nem acrescentar item fora do
escopo.

{_json_block(_ledger_index(scoped_ledger, include_steps=False))}

{_json_block(_query_index(scoped_queries))}

## Faça exatamente isto

Antes das unidades, faça uma passagem por obra: use autor, obra,
`official_domains` e `official_channels` para localizar curso, canal, página e
playlists oficiais. Página e playlist são índices de navegação, nunca
candidatos; registre somente URLs diretos de vídeo. Relacione conceitos do
sumário às aulas mesmo quando as numerações não coincidem.

Se a contagem selecionada for zero, não pesquise. Solicite opt-in explícito.

Para cada unidade selecionada, sem apagar tentativas anteriores:

1. Respeite a ordem de `search_queries.json`: `EXACT_OBJECT` vem antes de
   `RIGOROUS_EQUIVALENT`. Dentro do estágio exato, execute primeiro a estratégia
   `EXACT_OBJECT_MINIMAL`, somente com o objeto distintivo localizado, sem
   autor, número ou ação genérica; depois use as demais sementes exatas e o
   ecossistema oficial da fonte.
   Comece por português e inglês,
   depois percorra as sementes fornecidas e amplie para qualquer idioma que
   possa conter o objeto. `VERIFIED_CHANNEL_ALLOWLIST` significa que nenhum idioma-fonte pode
   ser excluído.
2. Para outros idiomas, traduza título, trecho do enunciado e termos técnicos;
   preserve literalmente fórmulas, símbolos, autor, edição, capítulo e número.
   Nunca anexe uma ação japonesa/chinesa/etc. a um título português e chame isso
   de tradução. Consulta com `execution_ready=false` exige `OPEN_EXPANSION` com
   termos realmente traduzidos.
3. Registre toda consulta executada em `search_attempts`, inclusive quando
   retornar zero resultados ou falhar. Não declare `NAO_ENCONTRADO` por conta
   própria.
   - consulta do plano: copie o `query_id` `Q-...`; o importador completa
     `origin`, unidade, idioma e texto canônicos;
   - consulta criada fora das sementes: use `origin = OPEN_EXPANSION`, informe
     `unit_id`, idioma BCP-47 e o texto literal da consulta. Pode usar um ID
     temporário; o importador o troca por `QX-...` estável.
4. Abra o link direto e confirme que ele carrega o vídeo observado. Resultado
   de busca, playlist, snippet, thumbnail e descrição são somente triagem. No
   YouTube, copie o ID real de exatamente 11 caracteres; nunca use título,
   assunto, exercício, termo de busca ou placeholder como ID.
5. Não escreva que o vídeo ensina ou resolve algo nesta etapa. Metadados não são
   inspeção.
6. Não use texto, PDF ou gabarito escrito para preencher uma vaga de vídeo.
7. O idioma da consulta não é o idioma do vídeo. Use `language = und` salvo
   quando a plataforma ou uma observação direta fornecer o idioma; registre o
   idioma da consulta em `discovery_languages`.
8. Se uma busca zerar, não junte mais restrições. Registre passagens separadas:
   (a) ecossistema oficial + conceito; (b) autor/obra/número; (c) frase
   distintiva; (d) fórmula + dados; (e) tradução conferida; (f) busca dentro do
   canal/curso e das transcrições. Cada consulta nova é `OPEN_EXPANSION`.
9. Para resolução, preserve número, edição/capítulo quando relevantes,
   hipóteses, decisões e formato de resposta. Teoria genérica não encerra a
   procura; equivalente estrutural vem somente depois das passagens exatas.
10. Antes do handoff, reabra cada URL registrado. Se deixou de carregar, não o
    entregue como candidato ativo; preserve a tentativa e registre a falha.

## Saída única

Retorne JSON no formato:

```json
{{
  "schema_name": "projeto-e-video.candidates",
  "schema_version": 3,
  "search_scope": "VERIFIED_CHANNEL_ALLOWLIST",
  "search_attempts": [
    {{
      "query_id": "Q-copiado-de-search_queries",
      "status": "COMPLETED",
      "result_count": 0,
      "error": null
    }},
    {{
      "query_id": "TEMP-expansao-01",
      "origin": "OPEN_EXPANSION",
      "unit_id": "U-...",
      "language": "ja",
      "query": "texto literal realmente pesquisado",
      "status": "COMPLETED",
      "result_count": 1,
      "error": null
    }}
  ],
  "candidates": [
    {{
      "unit_ids": ["U-..."],
      "url": "URL_DIRETA_VERIFICADA_A_INSERIR",
      "title": "título observado",
      "channel": "autoria observada ou desconhecida",
      "language": "tag BCP-47 observada ou und",
      "language_basis": "PLATFORM_METADATA|MANUAL_OBSERVATION|UNKNOWN",
      "discovery_languages": ["pt", "en", "ja"],
      "duration_seconds": null,
      "provider": "browser",
      "metadata_observed": ["TITLE", "CHANNEL", "DURATION"],
      "query_ids": ["TEMP-expansao-01"]
    }}
  ]
}}
```

Não inclua estado, aprovação, equivalência ou cobertura. Não copie
`metadata_triage`: o importador a recalcula e ela serve somente para ordenar a
inspeção. Você pode omitir
`candidate_id`: o importador sempre o recalcula do URL canônico e funde URLs
duplicados. Em `query_ids`, use o mesmo ID que registrou na tentativa; o
importador também troca aliases temporários de expansão pelo `QX-...` canônico.
"""
    target = workspace / "prompts" / "02_BUSCAR_CANDIDATOS.md"
    atomic_write_text(target, prompt)
    return target


def write_audio_prompt(workspace: Path) -> Path:
    candidates_path = workspace / "ledgers" / "candidates.json"
    candidates = read_json(candidates_path) if candidates_path.exists() else {
        "schema_name": "projeto-e-video.candidates",
        "schema_version": 2,
        "candidates": [],
    }
    prompt = f"""# TAREFA LITERAL — INVENTARIAR ÁUDIO PT/EN

Você é o inspetor de acessibilidade linguística. Metadados não aprovam uma
faixa, legenda não é dublagem e o idioma da consulta não prova o idioma do vídeo.

## Arquivo canônico obrigatório

Abra `{candidates_path.resolve()}` e processe todos os candidatos. O índice
compacto abaixo pode estar truncado e nunca autoriza omissões:

{_json_block(_candidate_index(candidates))}

## Faça exatamente isto

1. Para cada candidato, execute `inspect-audio` quando `yt-dlp` estiver
   disponível. Caso contrário, abra o menu de áudio do vídeo e produza um
   inventário manual conforme `schemas/audio_inventory.schema.json`.
2. Registre todas as faixas visíveis, seus idiomas BCP-47 e se a plataforma
   rotula a faixa como original, dublagem manual, automática ou desconhecida.
3. Registre legendas separadamente. Nunca converta `SUBTITLE_ONLY` em dublagem.
4. Não escreva aprovação, qualidade, cobertura ou domínio. A presença da faixa
   é apenas metadado para a etapa seguinte.
5. Preserve português e inglês separadamente. Ausência também deve permanecer
   visível.

## Saída

Retorne somente `projeto-e-video.audio-inventory` versão 2. Preserve em
`provider_language_tag` qualquer etiqueta interna não canônica e registre a
normalização sem interromper as demais faixas. Cada registro usa o
`candidate_id` e o URL canônico de `candidates.json`. Depois importe com
`import-audio-inventory`.
"""
    target = workspace / "prompts" / "03_INVENTARIAR_AUDIO.md"
    atomic_write_text(target, prompt)
    return target


def write_audit_prompt(workspace: Path) -> Path:
    ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
    candidates_path = workspace / "ledgers" / "candidates.json"
    candidates = read_json(candidates_path) if candidates_path.exists() else {
        "schema_name": "projeto-e-video.candidates",
        "schema_version": 1,
        "candidates": [],
    }
    inventory_path = workspace / "ledgers" / "audio_inventory.json"
    inventory = read_json(inventory_path) if inventory_path.exists() else {
        "schema_name": "projeto-e-video.audio-inventory",
        "schema_version": 1,
        "records": [],
    }
    prompt = f"""# TAREFA LITERAL — AUDITAR VÍDEOS POR DENTRO

Você é auditor audiovisual. Não confie em título, descrição, canal ou resposta
final. Não declare classificação; o código fará isso.

## Arquivos canônicos obrigatórios

- unidades e passos: `{(workspace / "ledgers" / "unit_ledger.json").resolve()}`
- candidatos: `{candidates_path.resolve()}`
- faixas e legendas: `{inventory_path.resolve()}`
- ativos coletados: `{(workspace / "evidence" / "assets").resolve()}`

Os índices são limitados. Abra os JSON canônicos e processe todos os pares
candidato/unidade; truncamento aqui nunca significa cobertura nem dispensa.

Unidades:

{_json_block(_ledger_index(ledger, include_steps=True))}

Candidatos:

{_json_block(_candidate_index(candidates))}

Faixas e legendas (metadados; ainda não aprovados):

{_json_block(_inventory_index(inventory))}

## Faça exatamente isto para cada candidato

1. Abra o vídeo direto.
2. Leia a transcrição real quando existir e confirme que ela pertence ao mesmo
   ID/URL. Se não existir, registre isso.
3. Inspecione frames nos instantes em que dados, quadro, fórmula, código,
   demonstração ou conclusão são visíveis.
4. Registre intervalos com `start_seconds < end_seconds`.
5. Ligue cada intervalo somente aos `step_ids` realmente observados.
   Em `speech_or_transcript_observed`, transcreva ou parafraseie precisamente o
   que foi dito naquela mesma janela; descrição global não substitui este campo.
6. Use `match_observation`:
   - `EXACT` para o mesmo objeto, ainda que este vídeo seja um componente que
     execute somente alguns `step_ids` completos;
   - `EQUIVALENT` quando dados/contexto mudam, mas estrutura, hipóteses,
     decisões e verificação coincidem;
   - `PARTIAL` quando o próprio trecho é incompleto, pula parte de um passo ou
     a correspondência não é rigorosa; não use `PARTIAL` apenas porque um vídeo
     foi escolhido conscientemente para cobrir um subconjunto completo;
   - `THEORY` quando não há resolução/aplicação exigida;
   - `CONFLICT` quando há erro ou hipótese incompatível;
   - `UNVERIFIABLE` quando o conteúdo interno não pôde ser verificado.
7. Para `EQUIVALENT`, escreva a correspondência e os pré-requisitos ausentes.
8. Para `CONFLICT`, descreva a passagem incompatível e o timestamp.
9. Não inclua `approved`, `classification`, `coverage_status` ou porcentagem.
10. Não use “assisti tudo” como evidência.
11. Para cada faixa PT/EN utilizável, selecione aquela faixa no player e
    realmente a ouça nos mesmos trechos. Verifique terminologia técnica,
    fórmulas e nomes próprios, alinhamento semântico e sincronização.
    Cada passo que o componente declara cobrir precisa estar ligado, no próprio
    timestamp, à amostra dessa faixa ou à fala conferida por reprodução direta.
    Uma rota única exige todos os passos; o motor pode unir vários componentes
    estritos, mas você não declara essa união.
12. Dublagem automática exige a mesma inspeção; a etiqueta automática não a
    reprova nem a aprova. Legenda nunca preenche `audio_reviews`.
13. Use `AUDIO_ARTIFACT` com amostra ligada aos timestamps ou
    `DIRECT_PLAYBACK` com fala ouvida e screenshot/frame do menu mostrando a
    faixa selecionada.
14. Não reutilize a mesma janela, os mesmos intervalos e os mesmos hashes de
    artefatos para provar unidades diferentes. Cada unidade exige observação
    interna específica do objeto pedido.

## Saída única

Retorne JSON conforme este molde literal, com uma observação por
candidato/unidade:

```json
{{
  "schema_name": "projeto-e-video.evidence-input",
  "schema_version": 2,
  "observations": [
    {{
      "candidate_id": "VID-copiado-de-candidates-json",
      "unit_id": "U-copiado-do-ledger",
      "candidate_identity_confirmed": true,
      "inspection_methods": ["TRANSCRICAO", "FRAME"],
      "match_observation": "PARTIAL",
      "artifacts": [
        {{
          "artifact_id": "ART-001",
          "path": "evidence/assets/VID-id/frame_060.jpg",
          "sha256": "hash-sha256-real-de-64-hexadecimais",
          "kind": "FRAME"
        }},
        {{
          "artifact_id": "ART-002",
          "path": "evidence/assets/VID-id/subtitle.pt.vtt",
          "sha256": "hash-sha256-real-de-64-hexadecimais",
          "kind": "TRANSCRIPT"
        }}
      ],
      "transcript": {{
        "available": true,
        "artifact_id": "ART-002",
        "language": "pt"
      }},
      "timestamps": [
        {{
          "start_seconds": 60,
          "end_seconds": 95,
          "observed_step_ids": ["S01"],
          "observed": "Descreva concretamente o que a fala e o quadro mostram.",
          "speech_or_transcript_observed": "Transcreva ou parafraseie a fala exata desta janela.",
          "artifact_ids": ["ART-001", "ART-002"]
        }}
      ],
      "speech_observed": "Descreva a fala realmente ouvida ou deixe vazio se a transcrição já a prova.",
      "equivalence_rationale": "Preencha somente para EQUIVALENT.",
      "missing_prerequisites": [],
      "audio_reviews": [
        {{
          "track_id": "ATRACK-copiado-do-audio_inventory",
          "target_language": "pt",
          "access_type_observed": "ORIGINAL|DUB_MANUAL|DUB_AUTOMATIC",
          "verification_method": "AUDIO_ARTIFACT",
          "audio_artifact_ids": ["ART-AUDIO-001"],
          "track_selection_artifact_id": null,
          "direct_playback_observed": false,
          "technical_terminology_checked": true,
          "mathematical_notation_checked": true,
          "semantic_alignment_checked": true,
          "synchronization_checked": true,
          "issues": [],
          "reviewer_notes": "Descreva concretamente o que foi ouvido e conferido."
        }}
      ],
      "conflict": null,
      "reviewer_notes": "Incertezas permanecem explícitas."
    }}
  ]
}}
```

`inspection_methods` usa somente `TRANSCRICAO`, `FALA_VERIFICADA`, `FRAME` ou
`DIRETA`. Cada timestamp contém `observed_step_ids`, `observed`,
`speech_or_transcript_observed` e `artifact_ids`. Todo artefato fica em
`evidence/assets/<candidate_id>/`; toda amostra de áudio inclui o `track_id` no
nome do arquivo; todo hash corresponde ao arquivo real. Se não houver
observação, use `observations: []`. Se houver frames, mas nenhuma fala ou
transcrição real do mesmo vídeo, use `UNVERIFIABLE` e deixe
`speech_or_transcript_observed` vazio; não invente texto para preencher o
campo. Evidência apenas visual nunca é `EXACT` ou `EQUIVALENT`.
"""
    target = workspace / "prompts" / "04_AUDITAR_VIDEOS.md"
    atomic_write_text(target, prompt)
    return target


def write_all_prompts(workspace: Path) -> list[Path]:
    return [
        write_map_prompt(workspace),
        write_search_prompt(workspace),
        write_audio_prompt(workspace),
        write_audit_prompt(workspace),
    ]
