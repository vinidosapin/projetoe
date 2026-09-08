"""Inventário de faixas de áudio e legendas; metadados nunca aprovam dublagem."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .external import run_command, yt_dlp_command
from .languages import (
    language_family,
    normalize_language_tag,
    normalize_provider_language_tag,
)
from .network import validate_automated_video_url
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


AUDIO_KIND_HINTS = {"ORIGINAL", "DUB_MANUAL", "DUB_AUTOMATIC", "UNKNOWN"}
SUBTITLE_KINDS = {"MANUAL", "AUTOMATIC", "UNKNOWN"}


def _kind_hint(*values: object) -> str:
    text = " ".join(str(value or "").lower() for value in values)
    if any(token in text for token in ("dubbed-auto", "auto-dub", "automatic dub", "dublagem automática")):
        return "DUB_AUTOMATIC"
    if any(token in text for token in ("human dub", "manual dub", "dublagem manual")):
        return "DUB_MANUAL"
    if "original" in text:
        return "ORIGINAL"
    return "UNKNOWN"


def _finite_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _track_from_raw(raw: Any, candidate_id: str, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{where} deve ser objeto")
    allowed = {
        "track_id",
        "external_track_id",
        "language",
        "label",
        "audio_kind_hint",
        "metadata_basis",
        "is_default",
        "formats",
        "language_family",
        "metadata_only",
        "provider_language_tag",
        "normalization_warning",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{where} contém campos desconhecidos: {unknown}")
    language = normalize_language_tag(raw.get("language"))
    provider_language_tag = raw.get("provider_language_tag")
    if provider_language_tag is not None and not isinstance(provider_language_tag, str):
        raise ValueError(f"{where}.provider_language_tag inválido")
    normalization_warning = raw.get("normalization_warning")
    if normalization_warning is not None and not isinstance(normalization_warning, str):
        raise ValueError(f"{where}.normalization_warning inválido")
    label = raw.get("label", "faixa sem rótulo")
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"{where}.label inválido")
    kind = raw.get("audio_kind_hint", "UNKNOWN")
    if kind not in AUDIO_KIND_HINTS:
        raise ValueError(f"{where}.audio_kind_hint inválido")
    external_id = raw.get("external_track_id")
    if external_id is not None and (not isinstance(external_id, str) or not external_id.strip()):
        raise ValueError(f"{where}.external_track_id inválido")
    basis = unique_strings(
        raw.get("metadata_basis", []), field=f"{where}.metadata_basis", allow_empty=True
    )
    is_default = raw.get("is_default", False)
    if not isinstance(is_default, bool):
        raise ValueError(f"{where}.is_default deve ser booleano")
    raw_formats = raw.get("formats", [])
    if not isinstance(raw_formats, list):
        raise ValueError(f"{where}.formats deve ser lista")
    formats: list[dict[str, Any]] = []
    seen_formats: set[str] = set()
    for index, item in enumerate(raw_formats):
        place = f"{where}.formats[{index}]"
        if not isinstance(item, dict) or set(item) - {"format_id", "ext", "abr", "audio_only"}:
            raise ValueError(f"{place} inválido")
        format_id = item.get("format_id")
        if not isinstance(format_id, str) or not format_id.strip():
            raise ValueError(f"{place}.format_id ausente")
        if format_id in seen_formats:
            continue
        seen_formats.add(format_id)
        ext = item.get("ext")
        if ext is not None and not isinstance(ext, str):
            raise ValueError(f"{place}.ext inválido")
        abr = _finite_number(item.get("abr"))
        audio_only = item.get("audio_only", False)
        if not isinstance(audio_only, bool):
            raise ValueError(f"{place}.audio_only deve ser booleano")
        formats.append(
            {
                "format_id": format_id.strip(),
                "ext": ext.strip() if isinstance(ext, str) and ext.strip() else None,
                "abr": abr,
                "audio_only": audio_only,
            }
        )
    semantic_external = external_id.strip() if isinstance(external_id, str) else ""
    track_identity = semantic_external or normalize_text(label)
    track_id = stable_id("ATRACK", candidate_id, track_identity, language)
    return {
        "track_id": track_id,
        "external_track_id": semantic_external or None,
        "language": language,
        "language_family": language_family(language),
        "provider_language_tag": provider_language_tag,
        "normalization_warning": normalization_warning,
        "label": label.strip(),
        "audio_kind_hint": kind,
        "metadata_basis": basis,
        "is_default": is_default,
        "formats": sorted(formats, key=lambda row: row["format_id"]),
        "metadata_only": True,
    }


def _subtitle_from_raw(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) - {
        "language",
        "language_family",
        "kind",
        "formats",
        "counts_as_dubbing",
        "provider_language_tag",
        "normalization_warning",
    }:
        raise ValueError(f"{where} inválido")
    language = normalize_language_tag(raw.get("language"))
    provider_language_tag = raw.get("provider_language_tag")
    if provider_language_tag is not None and not isinstance(provider_language_tag, str):
        raise ValueError(f"{where}.provider_language_tag inválido")
    normalization_warning = raw.get("normalization_warning")
    if normalization_warning is not None and not isinstance(normalization_warning, str):
        raise ValueError(f"{where}.normalization_warning inválido")
    kind = raw.get("kind", "UNKNOWN")
    if kind not in SUBTITLE_KINDS:
        raise ValueError(f"{where}.kind inválido")
    formats = unique_strings(
        raw.get("formats", []), field=f"{where}.formats", allow_empty=True
    )
    return {
        "language": language,
        "language_family": language_family(language),
        "provider_language_tag": provider_language_tag,
        "normalization_warning": normalization_warning,
        "kind": kind,
        "formats": formats,
        "counts_as_dubbing": False,
    }


def validate_audio_inventory(value: Any, candidate_doc: dict[str, Any]) -> dict[str, Any]:
    require_no_forbidden_assertions(value)
    if not isinstance(value, dict):
        raise ValueError("inventário de áudio deve ser objeto JSON")
    if value.get("schema_name") != "projeto-e-video.audio-inventory":
        raise ValueError("schema_name inválido para inventário de áudio")
    if value.get("schema_version") not in {1, 2}:
        raise ValueError("schema_version inválido para inventário de áudio")
    allowed = {"schema_name", "schema_version", "created_at", "course_id", "records"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"inventário de áudio contém campos desconhecidos: {unknown}")
    rows = value.get("records")
    if not isinstance(rows, list):
        raise ValueError("audio-inventory.records deve ser lista")
    candidates = {row["candidate_id"]: row for row in candidate_doc["candidates"]}
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        where = f"records[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} deve ser objeto")
        allowed_record = {
            "candidate_id",
            "candidate_url",
            "provider",
            "inspected_at",
            "tracks",
            "subtitles",
            "warnings",
            "notice",
        }
        unknown_record = sorted(set(raw) - allowed_record)
        if unknown_record:
            raise ValueError(f"{where} contém campos desconhecidos: {unknown_record}")
        candidate_id = raw.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in candidates:
            raise ValueError(f"{where}.candidate_id desconhecido")
        if candidate_id in seen:
            raise ValueError(f"registro de áudio duplicado: {candidate_id}")
        seen.add(candidate_id)
        candidate_url = raw.get("candidate_url")
        if candidate_url != candidates[candidate_id]["url"]:
            raise ValueError(f"{where}.candidate_url diverge do candidato canônico")
        provider = raw.get("provider", "manual")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError(f"{where}.provider inválido")
        inspected_at = raw.get("inspected_at")
        if not isinstance(inspected_at, str) or not inspected_at.strip():
            raise ValueError(f"{where}.inspected_at inválido")
        raw_tracks = raw.get("tracks", [])
        raw_subtitles = raw.get("subtitles", [])
        if not isinstance(raw_tracks, list) or not isinstance(raw_subtitles, list):
            raise ValueError(f"{where}.tracks/subtitles devem ser listas")
        tracks = [
            _track_from_raw(item, candidate_id, f"{where}.tracks[{track_index}]")
            for track_index, item in enumerate(raw_tracks)
        ]
        track_ids = [row["track_id"] for row in tracks]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError(f"{where}.tracks possui identidade duplicada")
        subtitles = [
            _subtitle_from_raw(item, f"{where}.subtitles[{subtitle_index}]")
            for subtitle_index, item in enumerate(raw_subtitles)
        ]
        warnings = unique_strings(
            raw.get("warnings", []), field=f"{where}.warnings", allow_empty=True
        )
        records.append(
            {
                "candidate_id": candidate_id,
                "candidate_url": candidate_url,
                "provider": provider.strip(),
                "inspected_at": inspected_at.strip(),
                "tracks": sorted(tracks, key=lambda row: row["track_id"]),
                "subtitles": sorted(
                    subtitles, key=lambda row: (row["language"], row["kind"])
                ),
                "warnings": warnings,
                "notice": "Metadados de faixa não comprovam idioma nem qualidade da dublagem.",
            }
        )
    return {
        "schema_name": "projeto-e-video.audio-inventory",
        "schema_version": 2,
        "created_at": value.get("created_at")
        if isinstance(value.get("created_at"), str) and value["created_at"].strip()
        else now_iso(),
        "course_id": candidate_doc["course_id"],
        "records": sorted(records, key=lambda row: row["candidate_id"]),
    }


def reconcile_audio_inventory(workspace: Path, candidate_doc: dict[str, Any]) -> dict[str, Any]:
    target = workspace / "ledgers" / "audio_inventory.json"
    if target.is_file():
        existing = read_json(target)
        known = {row["candidate_id"] for row in candidate_doc["candidates"]}
        raw_records = [
            row
            for row in existing.get("records", [])
            if isinstance(row, dict) and row.get("candidate_id") in known
        ]
    else:
        raw_records = []
    normalized = validate_audio_inventory(
        {
            "schema_name": "projeto-e-video.audio-inventory",
            "schema_version": 1,
            "records": raw_records,
        },
        candidate_doc,
    )
    atomic_write_json(target, normalized)
    return normalized


def import_audio_inventory(workspace: Path, file_path: Path) -> dict[str, Any]:
    candidate_doc = read_json(workspace / "ledgers" / "candidates.json")
    normalized = validate_audio_inventory(read_json(file_path), candidate_doc)
    atomic_write_json(workspace / "ledgers" / "audio_inventory.json", normalized)
    from .prompts import write_audit_prompt

    write_audit_prompt(workspace)
    return normalized


def _formats_to_tracks(
    payload: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    all_formats = [raw for raw in payload.get("formats") or [] if isinstance(raw, dict)]
    audio_only = [
        raw
        for raw in all_formats
        if raw.get("vcodec") == "none" and raw.get("acodec") not in {None, "none"}
    ]
    selected_formats = audio_only or all_formats
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    warnings: list[str] = []
    for raw in selected_formats:
        if not isinstance(raw, dict):
            continue
        acodec = raw.get("acodec")
        format_id = raw.get("format_id")
        if not isinstance(format_id, str) or not format_id or acodec in {None, "none"}:
            continue
        language, provider_tag, warning = normalize_provider_language_tag(
            raw.get("language")
        )
        if warning:
            warnings.append(warning)
        note = str(raw.get("format_note") or raw.get("format") or "faixa sem rótulo").strip()
        kind = _kind_hint(note, raw.get("language_preference"), raw.get("preference"))
        platform_track_id = str(raw.get("audio_track_id") or "").strip()
        note_parts = [part.strip() for part in note.split(",") if part.strip()]
        semantic_parts = [
            part
            for part in note_parts
            if ascii_fold(part)
            not in {"low", "medium", "high", "audio only", "faixa sem rotulo"}
        ]
        semantic_label = ", ".join(semantic_parts)
        synthetic_identity = ascii_fold(semantic_label) or "default"
        external_id = platform_track_id or f"ytfmt:{kind.lower()}:{synthetic_identity}"
        label = semantic_label or f"{language} — faixa detectada; confirme no player"
        key = (language, kind, external_id)
        row = grouped.setdefault(
            key,
            {
                "external_track_id": external_id,
                "language": language,
                "provider_language_tag": provider_tag,
                "normalization_warning": warning,
                "label": label,
                "audio_kind_hint": kind,
                "metadata_basis": [
                    "YT_DLP_FORMATS",
                    "YT_DLP_TRACK_ID"
                    if platform_track_id
                    else "YT_DLP_DERIVED_STREAM_GROUP",
                ],
                "is_default": bool(
                    isinstance(raw.get("language_preference"), (int, float))
                    and not isinstance(raw.get("language_preference"), bool)
                    and raw.get("language_preference", -1) > 0
                ),
                "formats": [],
            },
        )
        row["formats"].append(
            {
                "format_id": format_id,
                "ext": raw.get("ext") if isinstance(raw.get("ext"), str) else None,
                "abr": _finite_number(raw.get("abr")),
                "audio_only": raw.get("vcodec") == "none",
            }
        )
    return list(grouped.values()), list(dict.fromkeys(warnings))


def _subtitle_rows(
    payload: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for field, kind in (("subtitles", "MANUAL"), ("automatic_captions", "AUTOMATIC")):
        mapping = payload.get(field)
        if not isinstance(mapping, dict):
            continue
        for language, formats in mapping.items():
            if not isinstance(formats, list):
                continue
            normalized_language, provider_tag, warning = normalize_provider_language_tag(
                language
            )
            if warning:
                warnings.append(warning)
            if language_family(normalized_language) not in {"pt", "en"}:
                continue
            extensions = sorted(
                {
                    str(item.get("ext"))
                    for item in formats
                    if isinstance(item, dict) and item.get("ext")
                }
            )
            rows.append(
                {
                    "language": normalized_language,
                    "provider_language_tag": provider_tag,
                    "normalization_warning": warning,
                    "kind": kind,
                    "formats": extensions,
                }
            )
    return rows, list(dict.fromkeys(warnings))


def inspect_candidate_audio(
    workspace: Path,
    candidate_id: str,
    *,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    if not 1 <= timeout_seconds <= 900:
        raise ValueError("timeout_seconds deve ficar entre 1 e 900")
    command = yt_dlp_command()
    if command is None:
        raise ValueError("yt-dlp não encontrado; importe inventário manual do navegador")
    candidate_doc = read_json(workspace / "ledgers" / "candidates.json")
    candidates = {row["candidate_id"]: row for row in candidate_doc["candidates"]}
    if candidate_id not in candidates:
        raise ValueError(f"candidato não encontrado: {candidate_id}")
    candidate = candidates[candidate_id]
    validate_automated_video_url(candidate["url"])
    result = run_command(
        command
        + [
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            candidate["url"],
        ],
        timeout_seconds=timeout_seconds,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError("yt-dlp não conseguiu inspecionar o vídeo: " + (detail[-1200:] or "erro sem detalhe"))
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"yt-dlp devolveu JSON inválido: {exc}") from exc
    tracks, track_warnings = _formats_to_tracks(payload)
    subtitles, subtitle_warnings = _subtitle_rows(payload)
    record = {
        "candidate_id": candidate_id,
        "candidate_url": candidate["url"],
        "provider": "yt-dlp",
        "inspected_at": now_iso(),
        "tracks": tracks,
        "subtitles": subtitles,
        "warnings": [*track_warnings, *subtitle_warnings],
    }
    target = workspace / "ledgers" / "audio_inventory.json"
    current = reconcile_audio_inventory(workspace, candidate_doc)
    rows = [row for row in current["records"] if row["candidate_id"] != candidate_id]
    rows.append(record)
    normalized = validate_audio_inventory(
        {
            "schema_name": "projeto-e-video.audio-inventory",
            "schema_version": 1,
            "records": rows,
        },
        candidate_doc,
    )
    atomic_write_json(target, normalized)
    from .prompts import write_audit_prompt

    write_audit_prompt(workspace)
    return next(row for row in normalized["records"] if row["candidate_id"] == candidate_id)


def inventory_indexes(
    inventory: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    records = {row["candidate_id"]: row for row in inventory.get("records", [])}
    tracks = {
        track["track_id"]: track
        for record in records.values()
        for track in record.get("tracks", [])
    }
    return records, tracks
