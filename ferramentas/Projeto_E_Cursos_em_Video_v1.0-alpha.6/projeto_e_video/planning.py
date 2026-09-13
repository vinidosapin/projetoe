"""Atomização, mapa curricular e importação de mapa conferido."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import (
    PRODUCT_SOLUTIONS,
    PRODUCT_THEORY,
    PRODUCTS,
    choose_profile,
    detect_product,
    detect_safety_overlay,
)
from .languages import (
    TARGET_AUDIO_LANGUAGES,
    global_seed_languages,
    normalize_language_tag,
    query_action,
)
from .util import (
    ascii_fold,
    atomic_write_json,
    normalize_text,
    now_iso,
    read_json,
    require_no_forbidden_assertions,
    stable_id,
    unique_strings,
)


HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BULLET = re.compile(r"^\s*(?:[-*+] |\d+[.)]\s+)(.+?)\s*$")
SENTENCE = re.compile(r"(?<=[.!?;:])\s+")
NOTATION = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9_]*\([^\n)]{1,40}\)|"
    r"[A-Za-z0-9_]+\s*(?:<=|>=|!=|=|<|>|≤|≥|∈|∑|∫|√|→)\s*[^,.;:\n]{1,50})"
)
ROUTE_POLICIES = {"REQUIRED", "OPTIONAL", "CONTROL_NO_AUTOMATIC"}
MAX_QUERY_CHARS = 280
SEARCH_STAGES = {
    "EXACT_OBJECT",
    "RIGOROUS_EQUIVALENT",
    "LOCALIZATION_REQUIRED",
}
MAX_DRAFT_UNITS_PER_SOURCE = 32
MAX_DRAFT_UNITS_TOTAL = 128


def _guess_source_language(text: str) -> str:
    """Palpite conservador para o rascunho; o mapa V1 deve conferi-lo."""

    folded = ascii_fold(text)
    scores = {
        "pt": sum(
            folded.count(token)
            for token in (" o ", " a ", " de ", " que ", " exercicio", " resolva", " capitulo")
        ),
        "en": sum(
            folded.count(token)
            for token in (" the ", " of ", " and ", " exercise", " solve", " chapter")
        ),
        "es": sum(
            folded.count(token)
            for token in (" el ", " la ", " de ", " ejercicio", " resuelva", " capitulo")
        ),
    }
    best = max(scores, key=lambda language: scores[language])
    ordered = sorted(scores.values(), reverse=True)
    return best if scores[best] >= 2 and scores[best] > ordered[1] else "und"


def _default_search_identity(title: str, content: str) -> dict[str, Any]:
    exact_phrases = [normalize_text(title)]
    first_sentence = normalize_text(SENTENCE.split(normalize_text(content))[0])
    if len(first_sentence) >= 16 and first_sentence not in exact_phrases:
        exact_phrases.append(first_sentence[:240])
    notation = []
    for match in NOTATION.finditer(content):
        value = normalize_text(match.group(0))
        if value and value not in notation:
            notation.append(value)
        if len(notation) == 8:
            break
    return {
        "source_language": _guess_source_language(f" {title} {content} "),
        "creator": "",
        "work": "",
        "edition": "",
        "chapter": "",
        "section": "",
        "exercise": "",
        "exact_phrases": exact_phrases[:3],
        "notation": notation,
        "technical_terms": [normalize_text(title)],
        "official_domains": [],
        "official_channels": [],
        "localized_terms": [],
    }


def _normalize_search_identity(
    value: Any,
    *,
    where: str,
    fallback_title: str,
    fallback_excerpt: str,
) -> dict[str, Any]:
    if value is None:
        return _default_search_identity(fallback_title, fallback_excerpt)
    if not isinstance(value, dict):
        raise ValueError(f"{where} deve ser objeto")
    scalar_fields = {
        "source_language",
        "creator",
        "work",
        "edition",
        "chapter",
        "section",
        "exercise",
    }
    list_fields = {
        "exact_phrases",
        "notation",
        "technical_terms",
        "official_domains",
        "official_channels",
    }
    allowed = scalar_fields | list_fields | {"localized_terms"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{where} contém campos desconhecidos: {unknown}")
    source_language = normalize_language_tag(value.get("source_language"))
    scalars: dict[str, str] = {}
    for field in scalar_fields - {"source_language"}:
        raw = value.get(field, "")
        if not isinstance(raw, str):
            raise ValueError(f"{where}.{field} deve ser string")
        scalars[field] = normalize_text(raw)
    lists = {
        field: [normalize_text(item) for item in unique_strings(
            value.get(field, []), field=f"{where}.{field}", allow_empty=True
        )]
        for field in list_fields
    }
    if not lists["exact_phrases"] and not lists["technical_terms"]:
        lists["exact_phrases"] = [normalize_text(fallback_title)]
    raw_localized = value.get("localized_terms", [])
    if not isinstance(raw_localized, list):
        raise ValueError(f"{where}.localized_terms deve ser lista")
    localized: list[dict[str, Any]] = []
    seen_languages: set[str] = set()
    for index, row in enumerate(raw_localized):
        place = f"{where}.localized_terms[{index}]"
        if not isinstance(row, dict) or set(row) != {"language", "terms"}:
            raise ValueError(f"{place} deve conter somente language e terms")
        language = normalize_language_tag(row["language"])
        if language == "und" or language in seen_languages:
            raise ValueError(f"{place}.language inválido ou duplicado")
        seen_languages.add(language)
        terms = [
            normalize_text(item)
            for item in unique_strings(row["terms"], field=f"{place}.terms")
        ]
        localized.append({"language": language, "terms": terms})
    return {
        "source_language": source_language,
        **{field: scalars[field] for field in (
            "creator", "work", "edition", "chapter", "section", "exercise"
        )},
        **{field: lists[field] for field in (
            "exact_phrases", "notation", "technical_terms",
            "official_domains", "official_channels"
        )},
        "localized_terms": sorted(localized, key=lambda row: row["language"]),
    }


def _chunk_size(item_count: int, maximum_groups: int) -> int:
    return max(1, (item_count + maximum_groups - 1) // maximum_groups)


def _content_title(content: str, fallback_title: str) -> str:
    for line in content.splitlines():
        clean = normalize_text(line)
        if clean and not re.fullmatch(r"\[Página \d+\]", clean):
            return clean[:100]
    return fallback_title


def _flashlist_item_fields(text: str) -> dict[str, str] | None:
    """Lê o cabeçalho literal produzido pelo ingestor semanal FlashList."""

    if not text.startswith("[FLASHLIST_WEEKLY_ITEM]"):
        return None
    fields: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if not line.strip():
            break
        key, separator, value = line.partition(":")
        if separator and re.fullmatch(r"[a-z_]+", key):
            fields[key] = normalize_text(value)
    return fields


def _coalesce_sections(
    sections: list[tuple[str, str, str]], maximum: int
) -> list[tuple[str, str, str]]:
    """Agrupa seções adjacentes sem descartar conteúdo do rascunho."""

    if len(sections) <= maximum:
        return sections
    grouped: list[tuple[str, str, str]] = []
    size = _chunk_size(len(sections), maximum)
    for start in range(0, len(sections), size):
        rows = sections[start : start + size]
        first = start + 1
        last = start + len(rows)
        locator = f"section:{first}" if first == last else f"sections:{first}-{last}"
        title = rows[0][1]
        if len(rows) > 1:
            title = f"{title} — seções {first}–{last}"
        content = "\n\n".join(
            f"# {section_title}\n{section_content}"
            for _, section_title, section_content in rows
        )
        grouped.append((locator, title, content))
    return grouped


def _sections(
    text: str, fallback_title: str, *, maximum: int = MAX_DRAFT_UNITS_PER_SOURCE
) -> list[tuple[str, str, str]]:
    """Retorna um rascunho limitado de (localizador, título, conteúdo).

    O texto integral continua preservado em ``ingest/text``. O limite existe
    somente para impedir que um livro de centenas de páginas produza milhares
    de unidades heurísticas antes da revisão semântica V1.
    """

    if maximum < 1:
        raise ValueError("maximum deve ser positivo")

    pages = text.split("\f")
    while len(pages) > 1 and not pages[-1].strip():
        pages.pop()
    if len(pages) > 1:
        grouped_pages: list[tuple[str, str, str]] = []
        size = _chunk_size(len(pages), maximum)
        for start in range(0, len(pages), size):
            page_rows = pages[start : start + size]
            first = start + 1
            last = start + len(page_rows)
            content = "\n\n".join(
                f"[Página {first + offset}]\n{page.strip()}"
                for offset, page in enumerate(page_rows)
                if page.strip()
            ).strip()
            if not content:
                continue
            locator = f"pages:{first}-{last}"
            grouped_pages.append(
                (locator, _content_title(content, fallback_title), content)
            )
        return grouped_pages or [("pages:1-1", fallback_title, normalize_text(text))]

    lines = text.splitlines()
    result: list[tuple[str, str, str]] = []
    current_title = fallback_title
    current: list[str] = []
    heading_count = 0

    def flush() -> None:
        nonlocal current
        content = "\n".join(current).strip()
        if content:
            result.append((f"section:{len(result)+1}", current_title, content))
        current = []

    for line in lines:
        match = HEADING.match(line)
        if match:
            flush()
            heading_count += 1
            current_title = normalize_text(match.group(2)) or fallback_title
        else:
            current.append(line)
    flush()

    if heading_count and result:
        return _coalesce_sections(result, maximum)

    # Documento sem títulos: agrupa parágrafos para evitar uma unidade gigante.
    paragraphs = [normalize_text(p) for p in re.split(r"\n\s*\n", text) if normalize_text(p)]
    grouped: list[tuple[str, str, str]] = []
    size = max(4, _chunk_size(len(paragraphs), maximum)) if paragraphs else 1
    for index in range(0, len(paragraphs), size):
        group = paragraphs[index : index + size]
        title = group[0][:100] if group else fallback_title
        first = index + 1
        last = index + len(group)
        grouped.append((f"paragraphs:{first}-{last}", title, "\n\n".join(group)))
    return grouped or [("section:1", fallback_title, normalize_text(text))]


def _required_steps(product: str, content: str) -> list[dict[str, str]]:
    bullets = []
    for line in content.splitlines():
        match = BULLET.match(line)
        if match:
            clean = normalize_text(match.group(1))
            if len(clean) >= 8 and clean not in bullets:
                bullets.append(clean)
    candidates = bullets[:8]
    if not candidates:
        candidates = [
            normalize_text(sentence)
            for sentence in SENTENCE.split(normalize_text(content))
            if len(normalize_text(sentence)) >= 25
        ][:6]
    if product == PRODUCT_SOLUTIONS:
        defaults = [
            "Identificar dados, incógnitas, alvo e restrições do enunciado",
            "Escolher o método e justificar por que suas hipóteses valem",
            "Executar os passos decisivos sem ocultar transformações",
            "Interpretar a resposta no formato pedido",
            "Conferir o resultado ou auditar o limite de validade",
        ]
    else:
        defaults = [
            "Definir os conceitos centrais com condições de uso",
            "Explicar as relações causais, lógicas ou estruturais da unidade",
            "Executar ao menos um exemplo substantivo",
            "Preparar o aluno para uma prática observável",
        ]
    if len(candidates) < 2:
        candidates = defaults
    return [
        {"step_id": f"S{index:02d}", "description": value}
        for index, value in enumerate(candidates, start=1)
    ]


def _unit(
    *,
    source_id: str,
    source_locator: str,
    section_locator: str,
    title: str,
    content: str,
    extraction_gap: bool = False,
    product_override: str | None = None,
    route_policy: str = "REQUIRED",
) -> dict[str, Any]:
    clean_title = normalize_text(title)[:160] or "Unidade sem título"
    clean_content = normalize_text(content)
    if product_override is not None and product_override not in PRODUCTS:
        raise ValueError("product_override inválido")
    if route_policy not in ROUTE_POLICIES:
        raise ValueError("route_policy inválida")
    product = product_override or detect_product(clean_title + " " + clean_content)
    unit_id = stable_id("U", source_id, section_locator, clean_title, clean_content[:500])
    profile = choose_profile(clean_title + " " + clean_content)
    safety = detect_safety_overlay(clean_title + " " + clean_content)
    if extraction_gap:
        product = product_override or PRODUCT_THEORY
        steps = [
            {"step_id": "S01", "description": "Recuperar e conferir o conteúdo da fonte"}
        ]
        objective = (
            "Recuperar e conferir o enunciado antes de procurar uma resolução"
            if product == PRODUCT_SOLUTIONS
            else "Tornar a fonte legível antes de definir o curso"
        )
    else:
        steps = _required_steps(product, content)
        objective = (
            f"Resolver e verificar: {clean_title}"
            if product == PRODUCT_SOLUTIONS
            else f"Compreender e aplicar: {clean_title}"
        )
    return {
        "unit_id": unit_id,
        "source_ids": [source_id],
        "source_locators": [f"{source_locator}#{section_locator}"],
        "title": clean_title,
        "product": product,
        "profile": profile,
        "safety_overlay": safety,
        "objective": objective,
        "prerequisites": [],
        "required_steps": steps,
        "mastery_criterion": "Explicar e executar todos os passos essenciais sem consultar a resolução.",
        "pretest": "Tente cumprir o objetivo da unidade antes de abrir qualquer vídeo e registre os passos.",
        "posttest": "Resolva uma tarefa equivalente, com dados ou contexto diferentes, sem consultar o vídeo.",
        "retention_test": "Após 48–72 horas, resolva nova variante e explique por que o método ainda se aplica.",
        "verification_state": "HEURISTIC_DRAFT",
        "source_excerpt": clean_content[:1200],
        "extraction_gap": extraction_gap,
        "search_identity": _default_search_identity(clean_title, clean_content),
        "route_policy": route_policy,
    }


def _query_token(
    value: str, *, maximum: int = 88, quote_phrases: bool = True
) -> str:
    """Produz um token curto; uma consulta não deve virar a ficha bibliográfica."""

    clean = normalize_text(value).replace('"', " ").strip()
    if len(clean) > maximum:
        clean = clean[: maximum - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return f'"{clean}"' if quote_phrases and " " in clean else clean


def _creator_hint(value: str) -> str:
    """Usa um sobrenome distintivo em vez da lista inteira de autores."""

    first = normalize_text(value).split(";", 1)[0].split(",", 1)[0]
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9'-]+", first)
    return words[-1] if words else ""


def _neutral_numeric_locator(identity: dict[str, Any]) -> str:
    """Extrai somente códigos numéricos que sobrevivem à troca de idioma.

    Rótulos como ``Exercício`` ou ``Chapter`` pertencem ao idioma da fonte.
    O número de uma questão/seção, por outro lado, pode acompanhar uma ação já
    localizada sem criar uma consulta híbrida.
    """

    for field in ("exercise", "section", "chapter"):
        matches = re.findall(
            r"(?<![\w.])\d+(?:\.\d+)*(?:\s*[-–—]\s*\d+(?:\.\d+)*)?(?![\w.])",
            identity[field],
        )
        if matches:
            return " ".join(
                normalize_text(match).replace("–", "-").replace("—", "-")
                for match in matches[:2]
            )
    return ""


def _query_text(
    terms: list[str], action: str, *, quote_phrases: bool = True
) -> tuple[str, list[str]]:
    fingerprints = unique_strings(
        [normalize_text(value) for value in terms if normalize_text(value)],
        field="query.fingerprints_used",
        allow_empty=True,
    )
    selected: list[str] = []
    for value in fingerprints:
        candidate = " ".join(
            [
                *(
                    _query_token(item, quote_phrases=quote_phrases)
                    for item in selected
                ),
                _query_token(value, quote_phrases=quote_phrases),
                action,
            ]
        )
        if len(candidate) > MAX_QUERY_CHARS:
            continue
        selected.append(value)
    text = " ".join(
        [
            *(
                _query_token(value, quote_phrases=quote_phrases)
                for value in selected
            ),
            action,
        ]
    ).strip()
    if len(text) > MAX_QUERY_CHARS:
        # `action` vem de uma tabela interna e é curta, mas mantenha o limite como
        # invariante mesmo se essa tabela mudar no futuro.
        text = text[:MAX_QUERY_CHARS].rstrip()
    return text, selected


def _query_row(
    unit: dict[str, Any],
    language: str,
    *,
    terms: list[str],
    strategy: str,
    search_stage: str,
    authoritative_scope: bool,
    localization_note: str = "",
    quote_phrases: bool = True,
    action_override: str | None = None,
) -> dict[str, Any]:
    action = (
        query_action(language, unit["product"])
        if action_override is None
        else action_override
    )
    query_text, fingerprints = _query_text(
        terms, action, quote_phrases=quote_phrases
    )
    execution_ready = bool(fingerprints) and search_stage != "LOCALIZATION_REQUIRED"
    if not execution_ready:
        search_stage = "LOCALIZATION_REQUIRED"
        strategy = "LOCALIZATION_REQUIRED"
        # A estratégia mínima pode deliberadamente omitir a ação genérica, mas
        # uma consulta ainda não localizada precisa continuar sendo um texto
        # válido e orientar o operador no idioma-alvo.
        query_text = query_action(language, unit["product"])
        fingerprints = []
        localization_note = (
            "Crie OPEN_EXPANSION com tradução conferida do objeto; não reutilize "
            "o título da fonte como se estivesse neste idioma."
        )
    query_id = stable_id(
        "Q", unit["unit_id"], language, search_stage, strategy, query_text
    )
    return {
        "query_id": query_id,
        "unit_id": unit["unit_id"],
        "language": language,
        "query": query_text,
        "purpose": "EXACT_OR_RIGOROUS_EQUIVALENT",
        "tier": "TARGET_AUDIO_LANGUAGE"
        if language in TARGET_AUDIO_LANGUAGES
        else "GLOBAL_SEED",
        "search_stage": search_stage,
        "strategy": strategy,
        "execution_ready": execution_ready,
        "fingerprints_used": fingerprints,
        "authoritative_scope": authoritative_scope,
        "localization_note": localization_note,
    }


def _official_ecosystem_hint(identity: dict[str, Any]) -> str:
    """Obtém uma âncora curta para descobrir o curso/canal oficial."""

    if identity["official_channels"]:
        return identity["official_channels"][0]
    for raw in identity["official_domains"]:
        host = normalize_text(raw).lower().split("://")[-1].split("/", 1)[0]
        labels = [
            label
            for label in re.split(r"[^a-z0-9-]+", host)
            if label
            and label
            not in {"www", "com", "org", "net", "edu", "gov", "co", "ac"}
        ]
        if labels:
            return labels[-1]
    return ""


def _queries_for_unit(unit: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """Cria buscas curtas: fonte/ecossistema, objeto exato e equivalente.

    O piloto real mostrou que citar autores, edição, capítulo e seção inteiros em
    uma única consulta ocultava o número do exercício e retornava zero resultados.
    Aqui cada campo entra por prioridade e nunca apenas pela ordem no JSON.
    """

    identity = unit["search_identity"]
    source_language = identity["source_language"]
    localized: list[str] = next(
        (
            row["terms"]
            for row in identity["localized_terms"]
            if row["language"] == language
        ),
        [],
    )
    source_terms = (
        [*identity["exact_phrases"][:1], *identity["technical_terms"][:1]]
        if source_language == language
        else []
    )
    source_or_localized = source_language == language or bool(localized)
    subject_terms = localized[:2] or source_terms
    creator = _creator_hint(identity["creator"])
    work = identity["work"]
    ecosystem = _official_ecosystem_hint(identity)
    source_locator = ""
    if identity["exercise"]:
        exercise = identity["exercise"]
        source_locator = (
            exercise
            if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", exercise)
            else f"Exercise {exercise}"
        )
    elif identity["section"]:
        source_locator = identity["section"]
    elif identity["chapter"]:
        source_locator = identity["chapter"]
    neutral_locator = _neutral_numeric_locator(identity)
    locator = source_locator if source_language == language else neutral_locator
    notation = identity["notation"][:1]
    if source_or_localized:
        exact_terms = [
            work,
            locator,
            *subject_terms[:1],
            *notation,
            creator,
            ecosystem,
        ]
        neutral_anchor_ready = False
    else:
        # Sem tradução conferida, não reutilize título de obra, capítulo ou
        # enunciado em outro idioma. Só fórmulas, identificadores oficiais e a
        # combinação autor/canal + código numérico são âncoras transportáveis.
        neutral_anchor_ready = bool(notation) or bool(
            neutral_locator and (creator or ecosystem)
        )
        exact_terms = (
            [*notation, creator, neutral_locator, ecosystem]
            if neutral_anchor_ready
            else []
        )
    official = [*identity["official_channels"], *identity["official_domains"]]
    if official and source_or_localized and (work or locator or subject_terms):
        exact_strategy = "OFFICIAL_SOURCE_EXACT"
    elif source_terms:
        exact_strategy = "SOURCE_EXACT"
    elif localized:
        exact_strategy = "BIBLIOGRAPHIC_ANCHOR"
    elif neutral_anchor_ready and notation:
        exact_strategy = "STRUCTURAL_NOTATION"
    elif neutral_anchor_ready:
        exact_strategy = "BIBLIOGRAPHIC_ANCHOR"
    else:
        exact_strategy = "LOCALIZATION_REQUIRED"
    rows: list[dict[str, Any]] = []
    if unit["product"] == PRODUCT_SOLUTIONS:
        strict_exact = _query_row(
            unit,
            language,
            terms=exact_terms,
            strategy=exact_strategy,
            search_stage="EXACT_OBJECT",
            authoritative_scope=bool(official),
        )
        # Uma consulta exata longa pode ter excelente identidade e recall zero.
        # Comece somente pelo objeto distintivo localizado, sem autor, número ou
        # a expressão genérica “passo a passo”. Esses qualificadores fizeram o
        # YouTube retornar zero mesmo quando havia vídeos para o objeto. A busca
        # larga continua sendo triagem: a auditoria decide se o resultado é o
        # exercício exato, um equivalente ou apenas teoria.
        minimal_exact_terms = (
            subject_terms[:1] or notation[:1] or [locator]
            if source_or_localized
            else notation[:1]
            if notation
            else [creator or ecosystem, neutral_locator]
            if neutral_anchor_ready and (creator or ecosystem)
            else []
        )
        minimal_exact = _query_row(
            unit,
            language,
            terms=minimal_exact_terms,
            strategy="EXACT_OBJECT_MINIMAL",
            search_stage="EXACT_OBJECT",
            authoritative_scope=False,
            quote_phrases=False,
            action_override="",
        )
        rows.append(minimal_exact)
        if strict_exact["query"] != minimal_exact["query"]:
            rows.append(strict_exact)

    discovery_subject = localized[:2]
    if not discovery_subject and source_language == language:
        discovery_subject = [
            *identity["technical_terms"][:1],
            *identity["exact_phrases"][:1],
        ]
    if ecosystem and source_or_localized:
        discovery_terms = [
            ecosystem,
            *discovery_subject[:2],
            creator,
            locator if unit["product"] == PRODUCT_SOLUTIONS else "",
        ]
    elif unit["product"] == PRODUCT_SOLUTIONS and source_or_localized:
        # Descoberta bibliográfica e equivalência estrutural são passagens
        # diferentes. Não misture aqui todos os termos traduzidos, fórmulas e
        # a ficha inteira: o piloto real mostrou que o YouTube retorna zero.
        discovery_terms = [work, creator, locator, *localized[:1]]
    else:
        # Para teoria sem canal oficial, o objeto pedagógico traduzido é uma
        # âncora melhor que uma lista multilíngue de autores e livros.
        discovery_terms = discovery_subject[:1]
    discovery = _query_row(
        unit,
        language,
        terms=discovery_terms,
        strategy="SOURCE_ECOSYSTEM_DISCOVERY",
        search_stage="EXACT_OBJECT",
        authoritative_scope=bool(ecosystem),
        quote_phrases=False,
    )
    if all(discovery["query"] != row["query"] for row in rows):
        rows.append(discovery)

    # A segunda busca deliberadamente remove número de exercício/livro: ela só
    # procura uma resolução estruturalmente equivalente depois da exata. Sem
    # termos conferidos neste idioma, o navegador deve criar OPEN_EXPANSION.
    equivalent_terms = subject_terms[-1:] if subject_terms else []
    equivalent = _query_row(
        unit,
        language,
        terms=equivalent_terms,
        strategy="LOCALIZED_EQUIVALENT"
        if localized
        else "STRUCTURAL_NOTATION",
        search_stage="RIGOROUS_EQUIVALENT",
        authoritative_scope=False,
        quote_phrases=False,
    )
    if all(equivalent["query"] != row["query"] for row in rows):
        rows.append(equivalent)
    return rows


def build_queries(ledger: dict[str, Any]) -> dict[str, Any]:
    seed_languages = global_seed_languages()
    queries: list[dict[str, Any]] = []
    if ledger.get("map_state") == "V1_VERIFIED":
        # Para cada idioma, cubra todas as unidades com a consulta exata antes de
        # gastar orçamento em equivalentes. Assim um limite operacional não fica
        # preso nas duas consultas da primeira unidade.
        for language in seed_languages:
            language_rows = [
                row
                for unit in ledger["units"]
                for row in _queries_for_unit(unit, language)
            ]
            for stage in (
                "EXACT_OBJECT",
                "RIGOROUS_EQUIVALENT",
                "LOCALIZATION_REQUIRED",
            ):
                queries.extend(
                    row for row in language_rows if row["search_stage"] == stage
                )
    return {
        "schema_name": "projeto-e-video.search-queries",
        "schema_version": 3,
        "created_at": now_iso(),
        "course_id": ledger["course_id"],
        "search_scope": "VERIFIED_CHANNEL_ALLOWLIST",
        "target_audio_languages": list(TARGET_AUDIO_LANGUAGES),
        "seed_languages": seed_languages,
        "open_language_policy": (
            "As sementes não limitam idiomas. Consultas sem âncora neutra ou "
            "tradução conferida ficam LOCALIZATION_REQUIRED e não são executadas "
            "automaticamente. O navegador cria OPEN_EXPANSION no idioma real. "
            "Nenhuma consulta é materializada antes do mapa V1 conferido."
        ),
        "queries": queries,
    }


def create_plan(workspace: Path) -> dict[str, Any]:
    manifest = read_json(workspace / "ingest" / "source_manifest.json")
    units: list[dict[str, Any]] = []
    sources = manifest["sources"]
    per_source_budget = max(
        1,
        min(
            MAX_DRAFT_UNITS_PER_SOURCE,
            MAX_DRAFT_UNITS_TOTAL // max(1, len(sources)),
        ),
    )
    for source in sources:
        source_id = source["source_id"]
        locator = source["exact_locator"]
        text_path = source.get("text_path")
        if not text_path:
            units.append(
                _unit(
                    source_id=source_id,
                    source_locator=locator,
                    section_locator="unavailable",
                    title=Path(str(locator)).name or "Fonte não extraída",
                    content="",
                    extraction_gap=True,
                )
            )
            continue
        text = (workspace / "ingest" / str(text_path)).read_text(encoding="utf-8")
        flashlist_fields = _flashlist_item_fields(text)
        if flashlist_fields is not None:
            route_policy = flashlist_fields.get("route_policy", "REQUIRED")
            if route_policy not in ROUTE_POLICIES:
                raise ValueError(
                    f"route_policy FlashList inválida: {route_policy}"
                )
            item_ref = flashlist_fields.get("item_ref", source_id)
            title = flashlist_fields.get("title", manifest["title"])
            extraction_gap = flashlist_fields.get("content_status") != "OCR_EXTRACTED"
            units.append(
                _unit(
                    source_id=source_id,
                    source_locator=locator,
                    section_locator=f"flashlist-item:{item_ref}",
                    title=title,
                    content=text,
                    extraction_gap=extraction_gap,
                    product_override=PRODUCT_SOLUTIONS,
                    route_policy=route_policy,
                )
            )
            continue
        for section_locator, title, content in _sections(
            text, manifest["title"], maximum=per_source_budget
        ):
            units.append(
                _unit(
                    source_id=source_id,
                    source_locator=locator,
                    section_locator=section_locator,
                    title=title,
                    content=content,
                )
            )
    if not units:
        raise ValueError("nenhuma unidade pôde ser criada")
    ledger = {
        "schema_name": "projeto-e-video.unit-ledger",
        "schema_version": 1,
        "created_at": now_iso(),
        "course_id": manifest["course_id"],
        "title": manifest["title"],
        "map_state": "V0_HEURISTIC_DRAFT",
        "units": units,
    }
    ledgers_dir = workspace / "ledgers"
    atomic_write_json(ledgers_dir / "unit_ledger.v0.json", ledger)
    atomic_write_json(ledgers_dir / "unit_ledger.json", ledger)
    atomic_write_json(ledgers_dir / "search_queries.json", build_queries(ledger))
    return ledger


def validate_refined_map(value: Any, source_manifest: dict[str, Any]) -> dict[str, Any]:
    require_no_forbidden_assertions(value)
    if not isinstance(value, dict):
        raise ValueError("mapa deve ser objeto JSON")
    if value.get("schema_name") != "projeto-e-video.unit-ledger":
        raise ValueError("schema_name inválido")
    if value.get("schema_version") != 1:
        raise ValueError("schema_version inválido")
    allowed_top = {
        "schema_name",
        "schema_version",
        "created_at",
        "course_id",
        "title",
        "map_state",
        "units",
    }
    unknown_top = sorted(set(value) - allowed_top)
    if unknown_top:
        raise ValueError(f"mapa contém campos desconhecidos: {unknown_top}")
    units = value.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("units deve ser lista não vazia")
    title = value.get("title") or source_manifest["title"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title deve ser string não vazia")
    source_by_id = {
        row["source_id"]: row for row in source_manifest["sources"]
    }
    known_sources = set(source_by_id)
    ids: set[str] = set()
    normalized_units: list[dict[str, Any]] = []
    for index, unit in enumerate(units):
        where = f"units[{index}]"
        if not isinstance(unit, dict):
            raise ValueError(f"{where} deve ser objeto")
        allowed = {
            "unit_id",
            "source_ids",
            "source_locators",
            "title",
            "product",
            "profile",
            "safety_overlay",
            "objective",
            "prerequisites",
            "required_steps",
            "mastery_criterion",
            "pretest",
            "posttest",
            "retention_test",
            "verification_state",
            "source_excerpt",
            "extraction_gap",
            "search_identity",
            "route_policy",
        }
        unknown_fields = sorted(set(unit) - allowed)
        if unknown_fields:
            raise ValueError(f"{where} contém campos desconhecidos: {unknown_fields}")
        sources = unique_strings(unit.get("source_ids"), field=f"{where}.source_ids")
        unknown = set(sources) - known_sources
        if unknown:
            raise ValueError(f"{where} usa fontes desconhecidas: {sorted(unknown)}")
        source_locators = unique_strings(
            unit.get("source_locators", []),
            field=f"{where}.source_locators",
            allow_empty=True,
        )
        if not source_locators:
            raise ValueError(f"{where}.source_locators não pode ser vazio")
        matched_sources: set[str] = set()
        for locator in source_locators:
            matches = {
                source_id
                for source_id in sources
                if locator == source_by_id[source_id]["exact_locator"]
                or locator.startswith(
                    str(source_by_id[source_id]["exact_locator"]) + "#"
                )
            }
            if not matches:
                raise ValueError(
                    f"{where}.source_locators contém referência não inventariada: {locator}"
                )
            matched_sources.update(matches)
        if matched_sources != set(sources):
            raise ValueError(
                f"{where}: cada source_id deve possuir localização correspondente"
            )
        product = unit.get("product")
        if product not in PRODUCTS:
            raise ValueError(f"{where}.product inválido")
        state = unit.get("verification_state")
        if state not in {"VERIFIED_BY_AGENT", "VERIFIED_BY_HUMAN"}:
            raise ValueError(f"{where}.verification_state deve indicar revisão")
        steps = unit.get("required_steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"{where}.required_steps vazio")
        step_ids: set[str] = set()
        normalized_steps: list[dict[str, str]] = []
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"{where}.required_steps[{step_index}] inválido")
            step_id = step.get("step_id")
            description = step.get("description")
            if not isinstance(step_id, str) or not step_id.strip() or step_id in step_ids:
                raise ValueError(f"{where}.required_steps contém ID ausente ou duplicado")
            if not isinstance(description, str) or len(description.split()) < 3:
                raise ValueError(f"{where}.required_steps[{step_index}].description curta")
            step_ids.add(step_id)
            normalized_steps.append(
                {"step_id": step_id.strip(), "description": normalize_text(description)}
            )
        for field in (
            "title",
            "objective",
            "mastery_criterion",
            "pretest",
            "posttest",
            "retention_test",
            "profile",
            "safety_overlay",
        ):
            if not isinstance(unit.get(field), str) or not unit[field].strip():
                raise ValueError(f"{where}.{field} ausente")
        if unit["safety_overlay"] not in {"ROTINA", "SENSIVEL"}:
            raise ValueError(f"{where}.safety_overlay inválido")
        prerequisites = unique_strings(
            unit.get("prerequisites", []), field=f"{where}.prerequisites", allow_empty=True
        )
        excerpt = unit.get("source_excerpt", "")
        if not isinstance(excerpt, str):
            raise ValueError(f"{where}.source_excerpt deve ser string")
        extraction_gap = unit.get("extraction_gap", False)
        if not isinstance(extraction_gap, bool):
            raise ValueError(f"{where}.extraction_gap deve ser booleano")
        search_identity = _normalize_search_identity(
            unit.get("search_identity"),
            where=f"{where}.search_identity",
            fallback_title=unit["title"],
            fallback_excerpt=excerpt,
        )
        route_policy = unit.get("route_policy", "REQUIRED")
        if route_policy not in ROUTE_POLICIES:
            raise ValueError(f"{where}.route_policy inválido")
        unit_id = stable_id(
            "U",
            "|".join(sorted(sources)),
            "|".join(source_locators),
            normalize_text(unit["title"]),
            normalize_text(unit["objective"]),
            route_policy,
            "|".join(
                f"{step['step_id']}:{step['description']}" for step in normalized_steps
            ),
        )
        if unit_id in ids:
            raise ValueError(f"unidades canônicas duplicadas: {unit_id}")
        ids.add(unit_id)
        normalized_units.append(
            {
                "unit_id": unit_id,
                "source_ids": sources,
                "source_locators": source_locators,
                "title": normalize_text(unit["title"]),
                "product": product,
                "profile": unit["profile"].strip(),
                "safety_overlay": unit["safety_overlay"],
                "objective": normalize_text(unit["objective"]),
                "prerequisites": prerequisites,
                "required_steps": normalized_steps,
                "mastery_criterion": normalize_text(unit["mastery_criterion"]),
                "pretest": normalize_text(unit["pretest"]),
                "posttest": normalize_text(unit["posttest"]),
                "retention_test": normalize_text(unit["retention_test"]),
                "verification_state": state,
                "source_excerpt": excerpt,
                "extraction_gap": extraction_gap,
                "search_identity": search_identity,
                "route_policy": route_policy,
            }
        )
    return {
        "schema_name": "projeto-e-video.unit-ledger",
        "schema_version": 1,
        "created_at": now_iso(),
        "course_id": source_manifest["course_id"],
        "title": title.strip(),
        "map_state": "V1_VERIFIED",
        "units": normalized_units,
    }


def import_map(workspace: Path, file_path: Path) -> dict[str, Any]:
    source_manifest = read_json(workspace / "ingest" / "source_manifest.json")
    refined = validate_refined_map(read_json(file_path), source_manifest)
    atomic_write_json(workspace / "ledgers" / "unit_ledger.json", refined)
    atomic_write_json(workspace / "ledgers" / "search_queries.json", build_queries(refined))
    return refined
