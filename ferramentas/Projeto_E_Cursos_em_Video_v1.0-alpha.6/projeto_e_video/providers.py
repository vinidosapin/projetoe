"""Provedores de candidatos: metadados somente, nunca cobertura."""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

from .audio import reconcile_audio_inventory
from .external import run_command, yt_dlp_command
from .languages import normalize_language_tag
from .network import validate_http_url
from .prompts import write_audio_prompt, write_audit_prompt, write_search_prompt
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


METADATA_FIELDS = {
    "TITLE",
    "CHANNEL",
    "DURATION",
    "LANGUAGE",
    "PUBLISHED_AT",
    "THUMBNAIL",
}
LANGUAGE_BASES = {"PLATFORM_METADATA", "MANUAL_OBSERVATION", "UNKNOWN"}
SEARCH_SCOPES = {"VERIFIED_CHANNEL_ALLOWLIST", "LEGACY_LIMITED", "UNDECLARED"}
SEARCH_ATTEMPT_STATES = {"COMPLETED", "FAILED"}
SEARCH_ATTEMPT_ORIGINS = {"SEED_PLAN", "OPEN_EXPANSION"}
QUERY_SEARCH_STAGES = {"EXACT_OBJECT", "RIGOROUS_EQUIVALENT", "LOCALIZATION_REQUIRED"}
SEARCH_ROUTE_POLICIES = ("REQUIRED", "OPTIONAL", "CONTROL_NO_AUTOMATIC")
WEB_HTTP = "http" + "://"
WEB_HTTPS = "https" + "://"
YOUTUBE_BASE = WEB_HTTPS + "www.youtube.com"
YOUTUBE_WATCH_PREFIX = YOUTUBE_BASE + "/watch?"


# Projeto E v0.45-alpha.1: política editorial fechada para YouTube.
# O provedor automático NÃO executa busca aberta; cada consulta é feita dentro
# das páginas de busca dos canais explicitamente aprovados pelo mantenedor.
VERIFIED_YOUTUBE_CHANNELS = (
    {
        "id": "YT-OBMEP-MAT",
        "name": "Portal da Matemática OBMEP",
        "handle": "@portalmatematicaobmep",
        "url": YOUTUBE_BASE + "/@portalmatematicaobmep",
        "profiles": {"MATEMATICA", "ESTATISTICA_PROBABILIDADE"},
        "priority": 1,
    },
    {
        "id": "YT-OBMEP-FIS",
        "name": "Portal da Física OBMEP",
        "handle": "@portalfisicaobmep",
        "url": YOUTUBE_BASE + "/@portalfisicaobmep",
        "profiles": {"FISICA"},
        "priority": 1,
    },
    {
        "id": "YT-BRASIL-ESCOLA",
        "name": "Brasil Escola Oficial",
        "handle": "@brasilescola",
        "url": YOUTUBE_BASE + "/@brasilescola",
        "profiles": {"*"},
        "priority": 3,
    },
)


def _verified_channels_for_unit(unit: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Retorna somente canais aprovados, com OBMEP antes do Brasil Escola."""

    profile = str(unit.get("profile") or "UNIVERSAL")
    selected = [
        channel
        for channel in VERIFIED_YOUTUBE_CHANNELS
        if "*" in channel["profiles"] or profile in channel["profiles"]
    ]
    return tuple(sorted(selected, key=lambda row: (row["priority"], row["id"])))


def _channel_search_url(channel: dict[str, Any], query_text: str) -> str:
    return channel["url"].rstrip("/") + "/search?query=" + urllib.parse.quote_plus(query_text)


def _is_verified_youtube_channel_name(value: str) -> bool:
    folded = ascii_fold(value).strip()
    aliases = {
        "portal da matematica obmep",
        "portal da fisica obmep",
        "brasil escola",
        "brasil escola oficial",
    }
    return folded in aliases


def canonical_video_url(value: str) -> str:
    """Remove parâmetros de rastreio sem trocar a identidade do vídeo."""

    try:
        parsed = validate_http_url(value, resolve=False)
    except ValueError as exc:
        raise ValueError(f"URL de vídeo inválida: {exc}") from exc
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    host = (parsed.hostname or "").rstrip(".").lower()
    if host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com":
        video_id: str | None = None
        if host == "youtu.be":
            parts = [part for part in parsed.path.split("/") if part]
            video_id = urllib.parse.unquote(parts[0]) if parts else None
        elif parsed.path.rstrip("/") == "/watch":
            video_id = dict(query).get("v")
        else:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
                video_id = urllib.parse.unquote(parts[1])
        if not video_id:
            raise ValueError("URL do YouTube não identifica um vídeo direto")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError(
                "URL do YouTube contém ID inválido; placeholders e termos de busca não são vídeos"
            )
        return YOUTUBE_WATCH_PREFIX + urllib.parse.urlencode(
            {"v": video_id}
        )
    else:
        keep = [
            (key, val)
            for key, val in query
            if not key.lower().startswith("utm_")
            and key.lower() not in {"fbclid", "gclid", "si"}
        ]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            urllib.parse.urlencode(keep),
            "",
        )
    )


def _candidate_from_raw(raw: dict[str, Any], known_units: set[str]) -> dict[str, Any]:
    allowed = {
        "candidate_id",
        "unit_ids",
        "url",
        "title",
        "channel",
        "language",
        "language_basis",
        "discovery_languages",
        "duration_seconds",
        "provider",
        "metadata_observed",
        "query_ids",
        "published_at",
        "fixture",
        "metadata_triage",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"campos desconhecidos em candidato: {unknown}")
    url = canonical_video_url(str(raw.get("url", "")))
    if not url.startswith(YOUTUBE_WATCH_PREFIX):
        raise ValueError("candidato fora da política: somente vídeos diretos do YouTube são aceitos")
    unit_ids = unique_strings(raw.get("unit_ids"), field="candidate.unit_ids")
    invalid = set(unit_ids) - known_units
    if invalid:
        raise ValueError(f"candidato aponta unidades desconhecidas: {sorted(invalid)}")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("candidate.title ausente")
    channel = raw.get("channel", "desconhecido")
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError("candidate.channel inválido")
    if url.startswith(YOUTUBE_WATCH_PREFIX) and not _is_verified_youtube_channel_name(channel):
        raise ValueError(
            "canal do YouTube fora da allowlist: somente Portal da Matemática OBMEP, "
            "Portal da Física OBMEP e Brasil Escola Oficial são aceitos"
        )
    language = normalize_language_tag(raw.get("language"))
    language_basis = raw.get("language_basis", "UNKNOWN")
    if language_basis not in LANGUAGE_BASES:
        raise ValueError(f"candidate.language_basis inválido: {language_basis}")
    discovery_languages = [
        normalize_language_tag(value)
        for value in unique_strings(
            raw.get("discovery_languages", []),
            field="candidate.discovery_languages",
            allow_empty=True,
        )
    ]
    duration = raw.get("duration_seconds")
    if duration is not None and (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ValueError("candidate.duration_seconds deve ser número não negativo ou null")
    provider = raw.get("provider", "manual")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("candidate.provider inválido")
    metadata = unique_strings(
        raw.get("metadata_observed", []),
        field="candidate.metadata_observed",
        allow_empty=True,
    )
    if set(metadata) - METADATA_FIELDS:
        raise ValueError("candidate.metadata_observed contém valor não reconhecido")
    query_ids = unique_strings(
        raw.get("query_ids", []), field="candidate.query_ids", allow_empty=True
    )
    published_at = raw.get("published_at")
    if published_at is not None and not isinstance(published_at, str):
        raise ValueError("candidate.published_at deve ser string ou null")
    fixture = raw.get("fixture", False)
    if not isinstance(fixture, bool):
        raise ValueError("candidate.fixture deve ser booleano")
    return {
        # O identificador é sempre recalculado do endereço canônico. IDs temporários
        # de ferramentas externas nunca entram no contrato interno.
        "candidate_id": stable_id("VID", url),
        "unit_ids": unit_ids,
        "url": url,
        "title": title.strip(),
        "channel": channel.strip(),
        "language": language,
        "language_basis": language_basis,
        "discovery_languages": sorted(set(discovery_languages)),
        "duration_seconds": float(duration) if duration is not None else None,
        "provider": provider.strip(),
        "metadata_observed": metadata,
        "query_ids": query_ids,
        "published_at": published_at,
        "fixture": fixture,
    }


def _metadata_triage(
    candidate: dict[str, Any], units: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Prioriza inspeção com metadados; deliberadamente não aprova conteúdo."""

    text = ascii_fold(
        " ".join(
            (
                candidate.get("title", ""),
                candidate.get("channel", ""),
                candidate.get("url", ""),
            )
        )
    )
    score = 0
    matches: list[str] = []
    reasons: list[str] = []
    collision_risks: list[str] = []
    official_match = False
    solution_marker = bool(
        re.search(
            r"\b(solved|solution|exercise|problem|resolucao|resolvido|exercicio|"
            r"solucion|resuelto|ejercicio|corrige|proof|demonstracao|"
            r"demonstration|demostracion|preuve|exercice|beweis|losung|aufgabe|"
            r"risolto|esercizio|dimostrazione)\b",
            text,
        )
    )
    theory_only_marker = bool(
        re.search(r"\b(introduction|intro|overview|teoria|theory|conceitos basicos)\b", text)
    )
    for unit_id in candidate["unit_ids"]:
        identity = units[unit_id].get("search_identity", {})
        for field, weight in (
            ("creator", 12),
            ("work", 18),
            ("chapter", 10),
            ("section", 8),
            ("exercise", 20),
        ):
            value = ascii_fold(str(identity.get(field, ""))).strip()
            if value and value in text:
                score += weight
                matches.append(f"{unit_id}:{field}:{identity[field]}")
        for field, weight in (
            ("exact_phrases", 20),
            ("technical_terms", 7),
            ("notation", 16),
        ):
            for raw in identity.get(field, []):
                value = ascii_fold(str(raw)).strip()
                if len(value) >= 3 and value in text:
                    score += weight
                    matches.append(f"{unit_id}:{field}:{raw}")
        for localized in identity.get("localized_terms", []):
            if not isinstance(localized, dict):
                continue
            language = localized.get("language", "und")
            for raw in localized.get("terms", []):
                value = ascii_fold(str(raw)).strip()
                if len(value) >= 4 and value in text:
                    score += 12
                    matches.append(
                        f"{unit_id}:localized_terms[{language}]:{raw}"
                    )
        for channel in identity.get("official_channels", []):
            if ascii_fold(channel) in text:
                score += 30
                official_match = True
                matches.append(f"{unit_id}:official_channel:{channel}")
        host = (urllib.parse.urlsplit(candidate["url"]).hostname or "").lower()
        for domain in identity.get("official_domains", []):
            normalized_domain = domain.lower().split("://")[-1].split("/", 1)[0]
            if host == normalized_domain or host.endswith("." + normalized_domain):
                score += 30
                official_match = True
                matches.append(f"{unit_id}:official_domain:{domain}")
        notation = " ".join(str(row) for row in identity.get("notation", []))
        if "!" in notation and re.search(
            r"\b(factorial moment|momento fatorial|factorial moments)\b", text
        ) and "e(x!)" not in text.replace(" ", ""):
            collision_risks.append(
                f"{unit_id}: possível colisão entre fatorial da variável e momento fatorial"
            )
        if units[unit_id].get("product") == "CURSO_DE_RESOLUCOES_DE_EXERCICIOS":
            if solution_marker:
                score += 8
            if theory_only_marker and not solution_marker:
                score -= 18
                reasons.append(
                    f"{unit_id}: metadados sugerem introdução/teoria para uma unidade de resolução"
                )
    if collision_risks:
        score -= 35 * len(collision_risks)
    score = max(-100, min(100, score))
    if collision_risks or score < 0:
        status = "RUIDO_PROVAVEL"
    elif score >= 30:
        status = "PRIORITARIO"
    else:
        status = "REVISAR"
    if official_match:
        reasons.append("canal ou domínio coincide com ecossistema oficial informado")
    if not matches:
        reasons.append("nenhuma impressão digital forte aparece nos metadados")
    reasons.append("triagem por metadados; inspeção interna continua obrigatória")
    return {
        "status": status,
        "score": score,
        "fingerprint_matches": sorted(set(matches)),
        "collision_risks": sorted(set(collision_risks)),
        "reasons": list(dict.fromkeys(reasons)),
        "official_ecosystem_hint": official_match,
        "metadata_only": True,
    }


def _normalize_search_attempts(
    raw_attempts: Any,
    *,
    query_doc: dict[str, Any] | None,
    known_units: set[str],
) -> tuple[list[dict[str, Any]], dict[str, str], set[str]]:
    if not isinstance(raw_attempts, list):
        raise ValueError("search_attempts deve ser lista")
    if len(raw_attempts) > 10000:
        raise ValueError("search_attempts excede 10000 entradas")
    seed_queries = {
        row["query_id"]: row
        for row in (query_doc or {}).get("queries", [])
        if isinstance(row, dict) and isinstance(row.get("query_id"), str)
    }
    attempts: list[dict[str, Any]] = []
    aliases: dict[str, str] = {query_id: query_id for query_id in seed_queries}
    attempted_ids: set[str] = set()
    supplied_aliases: set[str] = set()
    for index, raw in enumerate(raw_attempts):
        where = f"search_attempts[{index}]"
        allowed = {
            "query_id",
            "origin",
            "unit_id",
            "language",
            "query",
            "status",
            "result_count",
            "error",
        }
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError(f"{where} inválido")
        supplied_id = raw.get("query_id")
        if supplied_id is not None and (
            not isinstance(supplied_id, str) or not supplied_id.strip()
        ):
            raise ValueError(f"{where}.query_id inválido")
        supplied_id = supplied_id.strip() if isinstance(supplied_id, str) else None
        seed = seed_queries.get(supplied_id or "")
        if seed is not None:
            origin = "SEED_PLAN"
            for field in ("unit_id", "language", "query"):
                if raw.get(field) is not None and raw[field] != seed[field]:
                    raise ValueError(f"{where}.{field} diverge da consulta-semente")
            if raw.get("origin") not in {None, origin}:
                raise ValueError(f"{where}.origin diverge da consulta-semente")
            query_id = seed["query_id"]
            unit_id = seed["unit_id"]
            language = seed["language"]
            query_text = seed["query"]
        else:
            if raw.get("origin") != "OPEN_EXPANSION":
                raise ValueError(
                    f"{where}: consulta fora do plano exige origin=OPEN_EXPANSION"
                )
            unit_id = raw.get("unit_id")
            if unit_id not in known_units:
                raise ValueError(f"{where}.unit_id desconhecido")
            language = normalize_language_tag(raw.get("language"))
            query_value = raw.get("query")
            if not isinstance(query_value, str):
                raise ValueError(f"{where}.query ausente")
            query_text = normalize_text(query_value)
            if not 3 <= len(query_text) <= 1000:
                raise ValueError(f"{where}.query deve ter entre 3 e 1000 caracteres")
            origin = "OPEN_EXPANSION"
            query_id = stable_id("QX", unit_id, language, query_text)
            if supplied_id:
                if supplied_id in supplied_aliases:
                    raise ValueError(f"alias de consulta duplicado: {supplied_id}")
                supplied_aliases.add(supplied_id)
                aliases[supplied_id] = query_id
            aliases[query_id] = query_id
        if query_id in attempted_ids:
            raise ValueError(f"tentativa de busca duplicada: {query_id}")
        attempted_ids.add(query_id)
        status = raw.get("status")
        if status not in SEARCH_ATTEMPT_STATES:
            raise ValueError(f"{where}.status inválido")
        result_count = raw.get("result_count", 0)
        if (
            not isinstance(result_count, int)
            or isinstance(result_count, bool)
            or result_count < 0
        ):
            raise ValueError(f"{where}.result_count inválido")
        error = raw.get("error")
        if error is not None and not isinstance(error, str):
            raise ValueError(f"{where}.error inválido")
        if status == "FAILED":
            if not (isinstance(error, str) and error.strip()):
                raise ValueError(f"{where}: FAILED exige error")
            if result_count:
                raise ValueError(f"{where}: FAILED exige result_count=0")
        elif isinstance(error, str) and error.strip():
            raise ValueError(f"{where}: COMPLETED exige error=null")
        attempts.append(
            {
                "query_id": query_id,
                "origin": origin,
                "unit_id": unit_id,
                "language": language,
                "query": query_text,
                "status": status,
                "result_count": result_count,
                "error": error.strip()
                if isinstance(error, str) and error.strip()
                else None,
            }
        )
    return (
        sorted(attempts, key=lambda row: row["query_id"]),
        aliases,
        attempted_ids,
    )


def validate_candidates(
    value: Any,
    ledger: dict[str, Any],
    *,
    query_doc: dict[str, Any] | None = None,
    additional_query_ids: set[str] | None = None,
    allow_fixtures: bool = False,
) -> dict[str, Any]:
    require_no_forbidden_assertions(value)
    if not isinstance(value, dict):
        raise ValueError("candidatos devem formar um objeto JSON")
    if value.get("schema_name") != "projeto-e-video.candidates":
        raise ValueError("schema_name inválido para candidatos")
    input_version = value.get("schema_version")
    if input_version not in {1, 2, 3}:
        raise ValueError("schema_version inválido para candidatos")
    allowed_top = {
        "schema_name",
        "schema_version",
        "created_at",
        "course_id",
        "candidate_count",
        "candidates",
        "search_scope",
        "search_attempts",
    }
    unknown_top = sorted(set(value) - allowed_top)
    if unknown_top:
        raise ValueError(f"candidatos contêm campos desconhecidos: {unknown_top}")
    rows = value.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("candidates deve ser lista")
    if len(rows) > 10000:
        raise ValueError("candidates excede 10000 entradas")
    units = {unit["unit_id"]: unit for unit in ledger["units"]}
    known_units = set(units)
    seed_query_ids = {
        row["query_id"]
        for row in (query_doc or {}).get("queries", [])
        if isinstance(row, dict) and isinstance(row.get("query_id"), str)
    }
    attempts, query_aliases, attempted_ids = _normalize_search_attempts(
        value.get("search_attempts", []),
        query_doc=query_doc,
        known_units=known_units,
    )
    known_queries = seed_query_ids | attempted_ids | (additional_query_ids or set())
    merged: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"candidates[{index}] deve ser objeto")
        candidate = _candidate_from_raw(raw, known_units)
        candidate["query_ids"] = sorted(
            {query_aliases.get(query_id, query_id) for query_id in candidate["query_ids"]}
        )
        if known_queries and set(candidate["query_ids"]) - known_queries:
            raise ValueError(
                "candidato aponta consultas desconhecidas: "
                + str(sorted(set(candidate["query_ids"]) - known_queries))
            )
        if candidate["fixture"] and not allow_fixtures:
            raise ValueError("fixtures só são aceitas pelo comando demo")
        candidate_id = candidate["candidate_id"]
        if candidate_id not in merged:
            merged[candidate_id] = candidate
            continue
        previous = merged[candidate_id]
        if previous["fixture"] != candidate["fixture"]:
            raise ValueError("URL duplicado não pode alternar estado de fixture")
        previous["unit_ids"] = sorted(set(previous["unit_ids"] + candidate["unit_ids"]))
        previous["query_ids"] = sorted(set(previous["query_ids"] + candidate["query_ids"]))
        previous["metadata_observed"] = sorted(
            set(previous["metadata_observed"] + candidate["metadata_observed"])
        )
        previous["discovery_languages"] = sorted(
            set(previous["discovery_languages"] + candidate["discovery_languages"])
        )
        if previous["language"] == "und" and candidate["language"] != "und":
            previous["language"] = candidate["language"]
            previous["language_basis"] = candidate["language_basis"]
        elif (
            candidate["language"] != "und"
            and previous["language"] != "und"
            and previous["language"] != candidate["language"]
        ):
            previous["language"] = "und"
            previous["language_basis"] = "UNKNOWN"
    scope = value.get(
        "search_scope", "LEGACY_LIMITED" if input_version == 1 else "UNDECLARED"
    )
    if scope not in SEARCH_SCOPES:
        raise ValueError("search_scope inválido")
    for candidate in merged.values():
        candidate["metadata_triage"] = _metadata_triage(candidate, units)
    return {
        "schema_name": "projeto-e-video.candidates",
        "schema_version": 3,
        "created_at": now_iso(),
        "course_id": ledger["course_id"],
        "search_scope": scope,
        "search_attempts": attempts,
        "candidate_count": len(merged),
        "candidates": sorted(merged.values(), key=lambda row: row["candidate_id"]),
    }


def _merge_attempt_rows(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Une históricos sem permitir que uma importação apague uma busca anterior."""

    merged = {row["query_id"]: dict(row) for row in existing}
    for row in incoming:
        query_id = row["query_id"]
        previous = merged.get(query_id)
        if previous is None:
            merged[query_id] = dict(row)
            continue
        immutable = ("origin", "unit_id", "language", "query")
        if any(previous[field] != row[field] for field in immutable):
            raise ValueError(f"tentativa importada diverge do histórico: {query_id}")
        if previous["status"] == "COMPLETED" or row["status"] == "COMPLETED":
            merged[query_id] = {
                **previous,
                "status": "COMPLETED",
                "result_count": max(previous["result_count"], row["result_count"]),
                "error": None,
            }
        else:
            # Ambas falharam. Preserve a observação importada mais recente sem
            # transformar a falha em conclusão.
            merged[query_id] = dict(row)
    return list(merged.values())


def _merge_candidate_documents(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    ledger: dict[str, Any],
    query_doc: dict[str, Any],
    *,
    allow_fixtures: bool,
) -> dict[str, Any]:
    scope = "VERIFIED_CHANNEL_ALLOWLIST"
    return validate_candidates(
        {
            "schema_name": "projeto-e-video.candidates",
            "schema_version": 3,
            "search_scope": scope,
            "search_attempts": _merge_attempt_rows(
                existing["search_attempts"], incoming["search_attempts"]
            ),
            "candidates": [*existing["candidates"], *incoming["candidates"]],
        },
        ledger,
        query_doc=query_doc,
        allow_fixtures=allow_fixtures,
    )


def _selected_search_unit_ids(
    ledger: dict[str, Any],
    *,
    unit_ids: list[str] | None,
    include_optional: bool,
    include_control: bool,
) -> set[str]:
    """Resolve o escopo e transforma qualquer unidade não obrigatória em opt-in."""

    units = {unit["unit_id"]: unit for unit in ledger["units"]}
    requested = set(unit_ids or [])
    unknown = requested - set(units)
    if unknown:
        raise ValueError(f"filtro contém unidades desconhecidas: {sorted(unknown)}")
    if requested:
        selected = set(requested)
    else:
        selected = {
            unit_id
            for unit_id, unit in units.items()
            if unit.get("route_policy", "REQUIRED") == "REQUIRED"
        }
    if include_optional:
        selected.update(
            unit_id
            for unit_id, unit in units.items()
            if unit.get("route_policy") == "OPTIONAL"
        )
    if include_control:
        selected.update(
            unit_id
            for unit_id, unit in units.items()
            if unit.get("route_policy") == "CONTROL_NO_AUTOMATIC"
        )
    return selected


def _search_progress(
    query_doc: dict[str, Any],
    document: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Deriva progresso obrigatório sem misturar opt-ins ou expansões abertas."""

    query_by_id = {row["query_id"]: row for row in query_doc["queries"]}
    policy_by_unit = {
        unit["unit_id"]: unit.get("route_policy", "REQUIRED")
        for unit in ledger["units"]
    }
    queries_by_policy = {
        policy: [
            row
            for row in query_doc["queries"]
            if policy_by_unit.get(row["unit_id"], "REQUIRED") == policy
        ]
        for policy in SEARCH_ROUTE_POLICIES
    }
    completed_ids = {
        row["query_id"]
        for row in document["search_attempts"]
        if row["status"] == "COMPLETED"
    }
    failed_ids = {
        row["query_id"]
        for row in document["search_attempts"]
        if row["status"] == "FAILED"
    }
    all_seed_ids = set(query_by_id)
    completed_seed_ids_all = completed_ids & all_seed_ids
    failed_seed_ids_all = failed_ids & all_seed_ids
    required_queries = queries_by_policy["REQUIRED"]
    required_ids = {row["query_id"] for row in required_queries}
    ready_queries = [
        row for row in required_queries if row.get("execution_ready", True)
    ]
    completed_seed_ids = completed_seed_ids_all & required_ids
    failed_seed_ids = failed_seed_ids_all & required_ids
    remaining_ready = [
        row["query_id"]
        for row in ready_queries
        if row["query_id"] not in completed_seed_ids | failed_seed_ids
    ]
    localization_pending = [
        row["query_id"]
        for row in required_queries
        if not row.get("execution_ready", True)
    ]
    completed_expansion_ids = {
        row["query_id"]
        for row in document["search_attempts"]
        if row["origin"] == "OPEN_EXPANSION" and row["status"] == "COMPLETED"
    }
    failed_expansion_ids = {
        row["query_id"]
        for row in document["search_attempts"]
        if row["origin"] == "OPEN_EXPANSION" and row["status"] == "FAILED"
    }
    completed_by_unit = Counter(
        query_by_id[query_id]["unit_id"] for query_id in completed_seed_ids
    )
    completed_by_language = Counter(
        query_by_id[query_id]["language"] for query_id in completed_seed_ids
    )
    policy_progress: dict[str, dict[str, int]] = {}
    for policy, rows in queries_by_policy.items():
        ids = {row["query_id"] for row in rows}
        ready_ids = {
            row["query_id"] for row in rows if row.get("execution_ready", True)
        }
        completed = completed_seed_ids_all & ids
        failed = failed_seed_ids_all & ids
        policy_progress[policy] = {
            "queries_total": len(rows),
            "queries_ready": len(ready_ids),
            "queries_completed": len(completed),
            "queries_failed": len(failed),
            "queries_pending_ready": len(ready_ids - completed - failed),
            "queries_pending_localization": len(ids - ready_ids),
        }
    return {
        "progress_scope": "REQUIRED",
        "queries_total": len(required_queries),
        "queries_total_required": len(required_queries),
        "queries_total_all_policies": len(query_doc["queries"]),
        "queries_ready": len(ready_queries),
        "queries_completed": len(completed_seed_ids),
        "queries_failed": len(failed_seed_ids),
        "queries_pending_ready": len(remaining_ready),
        "queries_pending_localization": len(localization_pending),
        "pending_ready_query_ids": remaining_ready,
        "pending_localization_query_ids": localization_pending,
        "pending_ready_by_unit": dict(
            sorted(
                Counter(
                    query_by_id[query_id]["unit_id"]
                    for query_id in remaining_ready
                ).items()
            )
        ),
        "pending_ready_by_language": dict(
            sorted(
                Counter(
                    query_by_id[query_id]["language"]
                    for query_id in remaining_ready
                ).items()
            )
        ),
        "completed_queries_by_unit": dict(sorted(completed_by_unit.items())),
        "completed_queries_by_language": dict(
            sorted(completed_by_language.items())
        ),
        "policy_progress": policy_progress,
        "open_expansion_attempts_completed": len(completed_expansion_ids),
        "open_expansion_attempts_failed": len(failed_expansion_ids),
        "search_attempts_total": len(document["search_attempts"]),
        "candidate_count": document["candidate_count"],
        "search_scope": document["search_scope"],
    }


def _write_import_search_report(
    workspace: Path,
    query_doc: dict[str, Any],
    document: dict[str, Any],
    ledger: dict[str, Any],
) -> None:
    report = {
        "schema_name": "projeto-e-video.search-report",
        "schema_version": 1,
        "created_at": now_iso(),
        "provider": "import-candidates",
        "queries_executed_this_run": 0,
        "queries_eligible_for_filters": 0,
        **_search_progress(query_doc, document, ledger),
        "retry_failed_requested": False,
        "filters": {"languages": [], "unit_ids": [], "search_stages": []},
        "warnings": [],
        "allowed_youtube_channels": [
            {"id": row["id"], "name": row["name"], "url": row["url"]}
            for row in VERIFIED_YOUTUBE_CHANNELS
        ],
        "open_youtube_search": False,
        "warning": "Metadados são triagem; nenhum vídeo foi internamente inspecionado. A descoberta automática está restrita à allowlist de três canais.",
    }
    atomic_write_json(workspace / "ledgers" / "search_report.json", report)


def import_candidates(
    workspace: Path,
    file_path: Path,
    *,
    allow_fixtures: bool = False,
) -> dict[str, Any]:
    ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
    _require_verified_map(ledger)
    query_doc = read_json(workspace / "ledgers" / "search_queries.json")
    target = workspace / "ledgers" / "candidates.json"
    if target.is_file():
        existing = validate_candidates(
            read_json(target),
            ledger,
            query_doc=query_doc,
            allow_fixtures=allow_fixtures,
        )
        incoming = validate_candidates(
            read_json(file_path),
            ledger,
            query_doc=query_doc,
            additional_query_ids={
                row["query_id"] for row in existing["search_attempts"]
            },
            allow_fixtures=allow_fixtures,
        )
        document = _merge_candidate_documents(
            existing,
            incoming,
            ledger,
            query_doc,
            allow_fixtures=allow_fixtures,
        )
    else:
        document = validate_candidates(
            read_json(file_path),
            ledger,
            query_doc=query_doc,
            allow_fixtures=allow_fixtures,
        )
    atomic_write_json(target, document)
    reconcile_audio_inventory(workspace, document)
    _write_import_search_report(workspace, query_doc, document, ledger)
    write_audio_prompt(workspace)
    write_audit_prompt(workspace)
    return document


def manual_search(
    workspace: Path,
    *,
    unit_ids: list[str] | None = None,
    include_optional: bool = False,
    include_control: bool = False,
) -> dict[str, Any]:
    ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
    _require_verified_map(ledger)
    selected_units = _selected_search_unit_ids(
        ledger,
        unit_ids=unit_ids,
        include_optional=include_optional,
        include_control=include_control,
    )
    query_doc = read_json(workspace / "ledgers" / "search_queries.json")
    target = workspace / "ledgers" / "candidates.json"
    if target.exists():
        document = validate_candidates(
            read_json(target), ledger, query_doc=query_doc, allow_fixtures=True
        )
    else:
        document = validate_candidates(
            {
                "schema_name": "projeto-e-video.candidates",
                "schema_version": 2,
                "search_scope": "VERIFIED_CHANNEL_ALLOWLIST",
                "search_attempts": [],
                "candidates": [],
            },
            ledger,
            query_doc=query_doc,
        )
    atomic_write_json(target, document)
    reconcile_audio_inventory(workspace, document)
    write_search_prompt(workspace, eligible_unit_ids=sorted(selected_units))
    write_audio_prompt(workspace)
    write_audit_prompt(workspace)
    report = {
        "schema_name": "projeto-e-video.search-report",
        "schema_version": 1,
        "created_at": now_iso(),
        "provider": "manual",
        "queries_executed_this_run": 0,
        "queries_eligible_for_filters": sum(
            1
            for row in query_doc["queries"]
            if row.get("execution_ready", True)
            and row["unit_id"] in selected_units
        ),
        **_search_progress(query_doc, document, ledger),
        "candidate_count": document["candidate_count"],
        "search_scope": document["search_scope"],
        "filters": {
            "unit_ids": sorted(unit_ids or []),
            "include_optional": include_optional,
            "include_control": include_control,
            "selected_unit_count": len(selected_units),
        },
        "notes": [
            "Use prompts/02_BUSCAR_CANDIDATOS.md e importe o JSON resultante.",
            "Nenhum candidato foi aprovado por este comando.",
            "Somente unidades REQUIRED entram por padrão; OPTIONAL e controle exigem opt-in explícito.",
        ],
    }
    atomic_write_json(workspace / "ledgers" / "search_report.json", report)
    return report


def _youtube_url(entry: dict[str, Any]) -> str | None:
    webpage = entry.get("webpage_url")
    if isinstance(webpage, str) and webpage.startswith((WEB_HTTP, WEB_HTTPS)):
        return webpage
    raw = entry.get("url")
    if isinstance(raw, str) and raw.startswith((WEB_HTTP, WEB_HTTPS)):
        return raw
    video_id = entry.get("id")
    if isinstance(video_id, str) and video_id:
        return YOUTUBE_WATCH_PREFIX + urllib.parse.urlencode({"v": video_id})
    return None


def _require_verified_map(ledger: dict[str, Any]) -> None:
    if ledger.get("map_state") != "V1_VERIFIED" or not ledger.get("units"):
        raise ValueError("busca/importação exige mapa V1_VERIFIED")
    if any(
        unit.get("verification_state") not in {"VERIFIED_BY_AGENT", "VERIFIED_BY_HUMAN"}
        for unit in ledger["units"]
    ):
        raise ValueError("busca/importação exige todas as unidades conferidas")


def yt_dlp_search(
    workspace: Path,
    *,
    limit: int = 3,
    max_queries: int = 60,
    timeout_seconds: int = 90,
    retry_failed: bool = False,
    languages: list[str] | None = None,
    unit_ids: list[str] | None = None,
    search_stages: list[str] | None = None,
    include_optional: bool = False,
    include_control: bool = False,
) -> dict[str, Any]:
    if not 1 <= limit <= 10:
        raise ValueError("limit deve ficar entre 1 e 10")
    if not 1 <= max_queries <= 10000:
        raise ValueError("max_queries deve ficar entre 1 e 10000")
    if not 1 <= timeout_seconds <= 900:
        raise ValueError("timeout_seconds deve ficar entre 1 e 900")
    ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
    _require_verified_map(ledger)
    query_doc = read_json(workspace / "ledgers" / "search_queries.json")
    units = {unit["unit_id"]: unit for unit in ledger["units"]}
    selected_languages = {
        normalize_language_tag(language) for language in (languages or [])
    }
    selected_units = _selected_search_unit_ids(
        ledger,
        unit_ids=unit_ids,
        include_optional=include_optional,
        include_control=include_control,
    )
    selected_stages = set(search_stages or [])
    unknown_stages = selected_stages - QUERY_SEARCH_STAGES
    if unknown_stages:
        raise ValueError(f"filtro contém fases desconhecidas: {sorted(unknown_stages)}")
    unknown_query_units = {
        row.get("unit_id")
        for row in query_doc.get("queries", [])
        if row.get("unit_id") not in units
    }
    if unknown_query_units:
        raise ValueError(
            f"consultas apontam unidades desconhecidas: {sorted(unknown_query_units)}"
        )
    target = workspace / "ledgers" / "candidates.json"
    if target.is_file():
        existing = validate_candidates(
            read_json(target), ledger, query_doc=query_doc, allow_fixtures=True
        )
    else:
        existing = validate_candidates(
            {
                "schema_name": "projeto-e-video.candidates",
                "schema_version": 3,
                "search_scope": "VERIFIED_CHANNEL_ALLOWLIST",
                "search_attempts": [],
                "candidates": [],
            },
            ledger,
            query_doc=query_doc,
        )
    candidates: list[dict[str, Any]] = list(existing["candidates"])
    warnings: list[str] = []
    attempt_by_id = {
        row["query_id"]: row for row in existing["search_attempts"]
    }
    ready_queries = [
        row for row in query_doc["queries"] if row.get("execution_ready", True)
    ]
    eligible_queries = [
        row
        for row in ready_queries
        if (not selected_languages or row["language"] in selected_languages)
        and row["unit_id"] in selected_units
        and (not selected_stages or row.get("search_stage") in selected_stages)
    ]
    pending_queries = [
        row
        for row in eligible_queries
        if row["query_id"] not in attempt_by_id
        or (
            retry_failed
            and attempt_by_id[row["query_id"]]["status"] == "FAILED"
        )
    ]
    command = yt_dlp_command()
    if pending_queries and command is None:
        raise ValueError(
            "yt-dlp não encontrado; execute python3 -m pip install "
            "'.[automation]' nesta pasta ou use --provider manual"
        )
    executed = 0
    for query in pending_queries[:max_queries]:
        assert command is not None
        executed += 1
        query_text = query["query"]
        result_count = 0
        successful_channel_searches = 0
        channel_errors: list[str] = []
        channels = _verified_channels_for_unit(units[query["unit_id"]])
        for channel in channels:
            search_url = _channel_search_url(channel, query_text)
            result = run_command(
                command + [
                    "--dump-single-json",
                    "--flat-playlist",
                    "--skip-download",
                    "--no-warnings",
                    "--playlist-end",
                    str(limit),
                    search_url,
                ],
                timeout_seconds=timeout_seconds,
            )
            if result.returncode:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                message = f"{channel['id']}: {detail[-350:] or 'falha no yt-dlp'}"
                channel_errors.append(message)
                warnings.append(f"{query['query_id']}: {message}")
                continue
            try:
                payload = json.loads(result.stdout.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                message = f"{channel['id']}: JSON inválido: {exc}"
                channel_errors.append(message)
                warnings.append(f"{query['query_id']}: {message}")
                continue
            successful_channel_searches += 1
            for entry in payload.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                url = _youtube_url(entry)
                if not url:
                    continue
                language = normalize_language_tag(entry.get("language"))
                metadata = ["TITLE", "CHANNEL"]
                if entry.get("duration") is not None:
                    metadata.append("DURATION")
                if language != "und":
                    metadata.append("LANGUAGE")
                # A identidade editorial vem da rota de busca do canal, não de
                # texto livre retornado pelo mecanismo. Isso impede a entrada
                # de um quarto canal no fluxo automático.
                candidates.append(
                    {
                        "unit_ids": [query["unit_id"]],
                        "url": url,
                        "title": str(entry.get("title") or "Título não informado"),
                        "channel": channel["name"],
                        "language": language,
                        "language_basis": "PLATFORM_METADATA"
                        if language != "und"
                        else "UNKNOWN",
                        "discovery_languages": [query["language"]],
                        "duration_seconds": entry.get("duration"),
                        "provider": "yt-dlp",
                        "metadata_observed": metadata,
                        "query_ids": [query["query_id"]],
                    }
                )
                result_count += 1
        if not successful_channel_searches:
            attempt_by_id[query["query_id"]] = {
                "query_id": query["query_id"],
                "status": "FAILED",
                "result_count": 0,
                "error": " | ".join(channel_errors)[-500:] or "falha nos canais verificados",
            }
            continue
        attempt_by_id[query["query_id"]] = {
            "query_id": query["query_id"],
            "status": "COMPLETED",
            "result_count": result_count,
            "error": None,
        }
    document = validate_candidates(
        {
            "schema_name": "projeto-e-video.candidates",
            "schema_version": 3,
            "search_scope": "VERIFIED_CHANNEL_ALLOWLIST",
            "search_attempts": list(attempt_by_id.values()),
            "candidates": candidates,
        },
        ledger,
        query_doc=query_doc,
    )
    atomic_write_json(target, document)
    reconcile_audio_inventory(workspace, document)
    progress = _search_progress(query_doc, document, ledger)
    report = {
        "schema_name": "projeto-e-video.search-report",
        "schema_version": 1,
        "created_at": now_iso(),
        "provider": "yt-dlp",
        "queries_executed_this_run": executed,
        "queries_eligible_for_filters": len(eligible_queries),
        **progress,
        "retry_failed_requested": retry_failed,
        "filters": {
            "languages": sorted(selected_languages),
            "unit_ids": sorted(unit_ids or []),
            "search_stages": sorted(selected_stages),
            "include_optional": include_optional,
            "include_control": include_control,
            "selected_unit_count": len(selected_units),
            "selected_route_policies": sorted(
                {
                    units[unit_id].get("route_policy", "REQUIRED")
                    for unit_id in selected_units
                }
            ),
        },
        "warnings": warnings,
        "allowed_youtube_channels": [
            {"id": row["id"], "name": row["name"], "url": row["url"]}
            for row in VERIFIED_YOUTUBE_CHANNELS
        ],
        "open_youtube_search": False,
        "warning": "Metadados são triagem; nenhum vídeo foi internamente inspecionado. A descoberta automática está restrita à allowlist de três canais.",
    }
    atomic_write_json(workspace / "ledgers" / "search_report.json", report)
    write_audio_prompt(workspace)
    write_audit_prompt(workspace)
    return report
