"""Motor determinístico de cobertura por evidência audiovisual."""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from .audio import inventory_indexes, validate_audio_inventory
from .languages import TARGET_AUDIO_LANGUAGES, language_family
from .models import (
    APPROVED_CLASSIFICATIONS,
    CLASSIFICATIONS,
    INTERNAL_INSPECTIONS,
    SPEECH_INSPECTIONS,
    VISUAL_INSPECTIONS,
)
from .util import (
    atomic_write_json,
    merge_intervals,
    now_iso,
    read_json,
    require_no_forbidden_assertions,
    sha256_file,
    sha256_json,
    stable_id,
    unique_strings,
)


MATCH_OBSERVATIONS = {
    "EXACT",
    "EQUIVALENT",
    "PARTIAL",
    "THEORY",
    "CONFLICT",
    "UNVERIFIABLE",
}
ARTIFACT_KINDS = {"FRAME", "SCREENSHOT", "TRANSCRIPT", "AUDIO", "OTHER"}
VISUAL_KINDS = {"FRAME", "SCREENSHOT"}
AUDIO_ACCESS_TYPES = {"ORIGINAL", "DUB_MANUAL", "DUB_AUTOMATIC"}
AUDIO_VERIFICATION_METHODS = {"AUDIO_ARTIFACT", "DIRECT_PLAYBACK"}
AUDIO_VERIFIED_STATUSES = {
    "ORIGINAL_PT",
    "ORIGINAL_EN",
    "DUB_MANUAL_PT",
    "DUB_MANUAL_EN",
    "DUB_AUTOMATIC_PT",
    "DUB_AUTOMATIC_EN",
}


def _safe_artifact(
    workspace: Path,
    value: Any,
    where: str,
    *,
    candidate_id: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} deve ser objeto")
    allowed = {"artifact_id", "path", "sha256", "kind", "byte_size"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{where} contém campos desconhecidos: {unknown}")
    artifact_id = value.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise ValueError(f"{where}.artifact_id ausente")
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"{where}.path ausente")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{where}.path deve ser relativo e seguro")
    if tuple(relative.parts[:3]) != ("evidence", "assets", candidate_id):
        raise ValueError(
            f"{where}.path deve ficar em evidence/assets/{candidate_id}/"
        )
    resolved_workspace = workspace.resolve()
    resolved = (workspace / Path(*relative.parts)).resolve()
    if resolved_workspace not in resolved.parents:
        raise ValueError(f"{where}.path escapa do workspace")
    if not resolved.is_file():
        raise ValueError(f"artefato não encontrado: {raw_path}")
    if resolved.stat().st_size > 100 * 1024 * 1024:
        raise ValueError(f"artefato excede 100 MiB: {raw_path}")
    expected = value.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"{where}.sha256 inválido")
    actual = sha256_file(resolved)
    if actual != expected.lower():
        raise ValueError(f"hash divergente no artefato {raw_path}")
    kind = value.get("kind")
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"{where}.kind inválido")
    actual_size = resolved.stat().st_size
    declared_size = value.get("byte_size")
    if declared_size is not None and declared_size != actual_size:
        raise ValueError(f"{where}.byte_size diverge do arquivo")
    return {
        "artifact_id": artifact_id.strip(),
        "path": relative.as_posix(),
        "sha256": actual,
        "kind": kind,
        "byte_size": actual_size,
    }


def _validate_audio_review(
    raw: Any,
    *,
    where: str,
    candidate_id: str,
    candidate_tracks: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    timestamps: list[dict[str, Any]],
    inspection_methods: set[str],
    speech_observed: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{where} deve ser objeto")
    allowed = {
        "track_id",
        "target_language",
        "access_type_observed",
        "verification_method",
        "audio_artifact_ids",
        "track_selection_artifact_id",
        "direct_playback_observed",
        "technical_terminology_checked",
        "mathematical_notation_checked",
        "semantic_alignment_checked",
        "synchronization_checked",
        "issues",
        "reviewer_notes",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{where} contém campos desconhecidos: {unknown}")
    track_id = raw.get("track_id")
    if track_id not in candidate_tracks:
        raise ValueError(f"{where}.track_id não pertence ao candidato {candidate_id}")
    track = candidate_tracks[track_id]
    target = language_family(raw.get("target_language"))
    if target not in TARGET_AUDIO_LANGUAGES:
        raise ValueError(f"{where}.target_language deve ser pt ou en")
    if track["language_family"] != target:
        raise ValueError(f"{where}: idioma da faixa diverge do idioma-alvo")
    access_type = raw.get("access_type_observed")
    if access_type not in AUDIO_ACCESS_TYPES:
        raise ValueError(f"{where}.access_type_observed inválido")
    method = raw.get("verification_method")
    if method not in AUDIO_VERIFICATION_METHODS:
        raise ValueError(f"{where}.verification_method inválido")
    audio_artifact_ids = unique_strings(
        raw.get("audio_artifact_ids", []),
        field=f"{where}.audio_artifact_ids",
        allow_empty=True,
    )
    if set(audio_artifact_ids) - set(artifacts):
        raise ValueError(f"{where}.audio_artifact_ids contém referência desconhecida")
    if any(artifacts[item]["kind"] != "AUDIO" for item in audio_artifact_ids):
        raise ValueError(f"{where}.audio_artifact_ids deve apontar somente AUDIO")
    selection_id = raw.get("track_selection_artifact_id")
    if selection_id is not None:
        if selection_id not in artifacts:
            raise ValueError(f"{where}.track_selection_artifact_id desconhecido")
        if artifacts[selection_id]["kind"] not in VISUAL_KINDS:
            raise ValueError(f"{where}.track_selection_artifact_id deve ser visual")
    direct = raw.get("direct_playback_observed", False)
    if not isinstance(direct, bool):
        raise ValueError(f"{where}.direct_playback_observed deve ser booleano")
    timestamp_refs = {
        artifact_id
        for timestamp in timestamps
        for artifact_id in timestamp["artifact_ids"]
    }
    if method == "AUDIO_ARTIFACT":
        if not audio_artifact_ids or not set(audio_artifact_ids) <= timestamp_refs:
            raise ValueError(
                f"{where}: AUDIO_ARTIFACT exige amostras AUDIO ligadas aos timestamps"
            )
        if any(
            track_id not in PurePosixPath(artifacts[item]["path"]).name
            for item in audio_artifact_ids
        ):
            raise ValueError(
                f"{where}: nome de cada amostra AUDIO deve conter o track_id"
            )
    elif not (
        direct
        and selection_id
        and selection_id in timestamp_refs
        and inspection_methods & {"FALA_VERIFICADA", "DIRETA"}
        and len(speech_observed.split()) >= 4
    ):
        raise ValueError(
            f"{where}: DIRECT_PLAYBACK exige fala ouvida e captura da faixa selecionada"
        )
    checks: dict[str, bool] = {}
    for field in (
        "technical_terminology_checked",
        "mathematical_notation_checked",
        "semantic_alignment_checked",
        "synchronization_checked",
    ):
        value = raw.get(field)
        if not isinstance(value, bool):
            raise ValueError(f"{where}.{field} deve ser booleano")
        checks[field] = value
    issues = unique_strings(
        raw.get("issues", []), field=f"{where}.issues", allow_empty=True
    )
    notes = raw.get("reviewer_notes", "")
    if not isinstance(notes, str) or len(notes.strip()) < 20:
        raise ValueError(f"{where}.reviewer_notes deve registrar a inspeção")
    return {
        "track_id": track_id,
        "target_language": target,
        "access_type_observed": access_type,
        "verification_method": method,
        "audio_artifact_ids": audio_artifact_ids,
        "track_selection_artifact_id": selection_id,
        "direct_playback_observed": direct,
        **checks,
        "issues": issues,
        "reviewer_notes": notes.strip(),
    }


def _validate_observation(
    workspace: Path,
    raw: Any,
    *,
    index: int,
    candidates: dict[str, dict[str, Any]],
    units: dict[str, dict[str, Any]],
    audio_records: dict[str, dict[str, Any]],
    require_timestamp_speech: bool,
) -> dict[str, Any]:
    where = f"observations[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{where} deve ser objeto")
    allowed = {
        "observation_id",
        "candidate_id",
        "unit_id",
        "candidate_identity_confirmed",
        "inspection_methods",
        "match_observation",
        "artifacts",
        "transcript",
        "timestamps",
        "speech_observed",
        "equivalence_rationale",
        "missing_prerequisites",
        "conflict",
        "reviewer_notes",
        "audio_reviews",
        "fixture",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{where} contém campos desconhecidos: {unknown}")
    candidate_id = raw.get("candidate_id")
    unit_id = raw.get("unit_id")
    if candidate_id not in candidates:
        raise ValueError(f"{where}.candidate_id desconhecido")
    if unit_id not in units:
        raise ValueError(f"{where}.unit_id desconhecido")
    if unit_id not in candidates[candidate_id]["unit_ids"]:
        raise ValueError(f"{where}: candidato não foi associado a essa unidade")
    identity = raw.get("candidate_identity_confirmed")
    if not isinstance(identity, bool):
        raise ValueError(f"{where}.candidate_identity_confirmed deve ser booleano")
    methods = unique_strings(
        raw.get("inspection_methods", []),
        field=f"{where}.inspection_methods",
        allow_empty=True,
    )
    if set(methods) - INTERNAL_INSPECTIONS:
        raise ValueError(f"{where}.inspection_methods contém método inválido")
    match = raw.get("match_observation")
    if match not in MATCH_OBSERVATIONS:
        raise ValueError(f"{where}.match_observation inválido")

    raw_artifacts = raw.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        raise ValueError(f"{where}.artifacts deve ser lista")
    artifacts: list[dict[str, Any]] = []
    artifact_ids: set[str] = set()
    for artifact_index, item in enumerate(raw_artifacts):
        artifact = _safe_artifact(
            workspace,
            item,
            f"{where}.artifacts[{artifact_index}]",
            candidate_id=candidate_id,
        )
        if artifact["artifact_id"] in artifact_ids:
            raise ValueError(f"{where}.artifacts contém ID duplicado")
        artifact_ids.add(artifact["artifact_id"])
        artifacts.append(artifact)

    transcript = raw.get("transcript", {"available": False, "artifact_id": None})
    if not isinstance(transcript, dict):
        raise ValueError(f"{where}.transcript deve ser objeto")
    if set(transcript) - {"available", "artifact_id", "language"}:
        raise ValueError(f"{where}.transcript contém campos desconhecidos")
    transcript_available = transcript.get("available")
    if not isinstance(transcript_available, bool):
        raise ValueError(f"{where}.transcript.available deve ser booleano")
    transcript_artifact_id = transcript.get("artifact_id")
    if transcript_artifact_id is not None and transcript_artifact_id not in artifact_ids:
        raise ValueError(f"{where}.transcript.artifact_id desconhecido")
    artifact_by_id = {item["artifact_id"]: item for item in artifacts}
    if transcript_available:
        if not transcript_artifact_id:
            raise ValueError(f"{where}: transcrição disponível exige artifact_id")
        if artifact_by_id[transcript_artifact_id]["kind"] != "TRANSCRIPT":
            raise ValueError(f"{where}: artefato da transcrição tem kind incorreto")
    language = transcript.get("language", "und")
    if not isinstance(language, str) or not language.strip():
        raise ValueError(f"{where}.transcript.language inválido")

    timestamps_raw = raw.get("timestamps", [])
    if not isinstance(timestamps_raw, list):
        raise ValueError(f"{where}.timestamps deve ser lista")
    timestamps: list[dict[str, Any]] = []
    duration = candidates[candidate_id].get("duration_seconds")
    known_steps = {step["step_id"] for step in units[unit_id]["required_steps"]}
    for timestamp_index, item in enumerate(timestamps_raw):
        place = f"{where}.timestamps[{timestamp_index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{place} deve ser objeto")
        allowed_timestamp = {
            "start_seconds",
            "end_seconds",
            "observed_step_ids",
            "observed",
            "speech_or_transcript_observed",
            "artifact_ids",
        }
        if set(item) - allowed_timestamp:
            raise ValueError(f"{place} contém campos desconhecidos")
        start = item.get("start_seconds")
        end = item.get("end_seconds")
        if (
            not isinstance(start, (int, float))
            or isinstance(start, bool)
            or not isinstance(end, (int, float))
            or isinstance(end, bool)
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end <= start
        ):
            raise ValueError(f"{place} possui intervalo inválido")
        if duration is not None and duration > 0 and end > duration + 1:
            raise ValueError(f"{place} excede a duração conhecida do vídeo")
        step_ids = unique_strings(
            item.get("observed_step_ids", []),
            field=f"{place}.observed_step_ids",
            allow_empty=True,
        )
        if set(step_ids) - known_steps:
            raise ValueError(f"{place} aponta step_id desconhecido")
        observed = item.get("observed")
        if not isinstance(observed, str) or len(observed.strip()) < 12:
            raise ValueError(f"{place}.observed deve descrever a observação")
        spoken = item.get("speech_or_transcript_observed", "")
        if not isinstance(spoken, str):
            raise ValueError(f"{place}.speech_or_transcript_observed deve ser string")
        if (
            require_timestamp_speech
            and match != "UNVERIFIABLE"
            and len(spoken.strip()) < 12
        ):
            raise ValueError(
                f"{place}.speech_or_transcript_observed deve registrar a fala da janela"
            )
        refs = unique_strings(
            item.get("artifact_ids", []),
            field=f"{place}.artifact_ids",
            allow_empty=True,
        )
        if set(refs) - artifact_ids:
            raise ValueError(f"{place}.artifact_ids contém referência desconhecida")
        timestamps.append(
            {
                "start_seconds": float(start),
                "end_seconds": float(end),
                "observed_step_ids": step_ids,
                "observed": observed.strip(),
                "speech_or_transcript_observed": spoken.strip(),
                "artifact_ids": refs,
            }
        )

    speech = raw.get("speech_observed", "")
    if not isinstance(speech, str):
        raise ValueError(f"{where}.speech_observed deve ser string")
    raw_audio_reviews = raw.get("audio_reviews", [])
    if not isinstance(raw_audio_reviews, list):
        raise ValueError(f"{where}.audio_reviews deve ser lista")
    candidate_record = audio_records.get(candidate_id, {"tracks": []})
    candidate_tracks = {
        track["track_id"]: track for track in candidate_record.get("tracks", [])
    }
    audio_reviews: list[dict[str, Any]] = []
    reviewed_targets: set[str] = set()
    for review_index, review_raw in enumerate(raw_audio_reviews):
        review = _validate_audio_review(
            review_raw,
            where=f"{where}.audio_reviews[{review_index}]",
            candidate_id=candidate_id,
            candidate_tracks=candidate_tracks,
            artifacts=artifact_by_id,
            timestamps=timestamps,
            inspection_methods=set(methods),
            speech_observed=speech.strip(),
        )
        if review["target_language"] in reviewed_targets:
            raise ValueError(f"{where}.audio_reviews repete idioma-alvo")
        reviewed_targets.add(review["target_language"])
        audio_reviews.append(review)
    rationale = raw.get("equivalence_rationale", "")
    if not isinstance(rationale, str):
        raise ValueError(f"{where}.equivalence_rationale deve ser string")
    missing = unique_strings(
        raw.get("missing_prerequisites", []),
        field=f"{where}.missing_prerequisites",
        allow_empty=True,
    )
    conflict = raw.get("conflict")
    if conflict is not None:
        if not isinstance(conflict, dict) or set(conflict) - {
            "description",
            "timestamp_seconds",
        }:
            raise ValueError(f"{where}.conflict inválido")
        description = conflict.get("description")
        at = conflict.get("timestamp_seconds")
        if not isinstance(description, str) or len(description.strip()) < 12:
            raise ValueError(f"{where}.conflict.description insuficiente")
        if (
            not isinstance(at, (int, float))
            or isinstance(at, bool)
            or not math.isfinite(at)
            or at < 0
        ):
            raise ValueError(f"{where}.conflict.timestamp_seconds inválido")
        conflict = {"description": description.strip(), "timestamp_seconds": float(at)}
    if match == "CONFLICT" and conflict is None:
        raise ValueError(f"{where}: CONFLICT exige descrição e timestamp")
    notes = raw.get("reviewer_notes", "")
    if not isinstance(notes, str):
        raise ValueError(f"{where}.reviewer_notes deve ser string")
    fixture = raw.get("fixture", False)
    if not isinstance(fixture, bool):
        raise ValueError(f"{where}.fixture deve ser booleano")
    if fixture != candidates[candidate_id].get("fixture", False):
        raise ValueError(f"{where}.fixture diverge do candidato")
    observation_id = stable_id("OBS", candidate_id, unit_id)
    return {
        "observation_id": observation_id,
        "candidate_id": candidate_id,
        "unit_id": unit_id,
        "candidate_identity_confirmed": identity,
        "inspection_methods": methods,
        "match_observation": match,
        "artifacts": artifacts,
        "transcript": {
            "available": transcript_available,
            "artifact_id": transcript_artifact_id,
            "language": language.strip(),
        },
        "timestamps": timestamps,
        "speech_observed": speech.strip(),
        "audio_reviews": sorted(
            audio_reviews, key=lambda row: row["target_language"]
        ),
        "equivalence_rationale": rationale.strip(),
        "missing_prerequisites": missing,
        "conflict": conflict,
        "reviewer_notes": notes.strip(),
        "fixture": fixture,
    }


def validate_evidence_input(
    workspace: Path,
    value: Any,
    ledger: dict[str, Any],
    candidate_doc: dict[str, Any],
    *,
    audio_inventory: dict[str, Any] | None = None,
    allow_fixtures: bool = False,
) -> dict[str, Any]:
    require_no_forbidden_assertions(value)
    if not isinstance(value, dict):
        raise ValueError("evidência deve ser objeto JSON")
    if value.get("schema_name") != "projeto-e-video.evidence-input":
        raise ValueError("schema_name inválido para evidência")
    if value.get("schema_version") not in {1, 2}:
        raise ValueError("schema_version inválido para evidência")
    allowed_top = {
        "schema_name",
        "schema_version",
        "created_at",
        "course_id",
        "observations",
    }
    unknown_top = sorted(set(value) - allowed_top)
    if unknown_top:
        raise ValueError(f"evidência contém campos desconhecidos: {unknown_top}")
    rows = value.get("observations")
    if not isinstance(rows, list):
        raise ValueError("observations deve ser lista")
    if len(rows) > 10000:
        raise ValueError("observations excede 10000 entradas")
    candidates = {row["candidate_id"]: row for row in candidate_doc["candidates"]}
    units = {row["unit_id"]: row for row in ledger["units"]}
    if audio_inventory is None:
        inventory_path = workspace / "ledgers" / "audio_inventory.json"
        if not inventory_path.is_file():
            raise ValueError("inventário de áudio ausente; execute inspect-audio ou importe-o")
        audio_inventory = read_json(inventory_path)
    normalized_inventory = validate_audio_inventory(audio_inventory, candidate_doc)
    audio_records, _ = inventory_indexes(normalized_inventory)
    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(rows):
        observation = _validate_observation(
            workspace,
            raw,
            index=index,
            candidates=candidates,
            units=units,
            audio_records=audio_records,
            require_timestamp_speech=value.get("schema_version") == 2,
        )
        key = (observation["candidate_id"], observation["unit_id"])
        if key in seen:
            raise ValueError(f"observação duplicada para candidato/unidade: {key}")
        seen.add(key)
        if observation["fixture"] and not allow_fixtures:
            raise ValueError("fixtures só são aceitas pelo comando demo")
        observations.append(observation)
    return {
        "schema_name": "projeto-e-video.evidence-input",
        "schema_version": 2,
        "created_at": value.get("created_at")
        if isinstance(value.get("created_at"), str) and value["created_at"].strip()
        else now_iso(),
        "course_id": ledger["course_id"],
        "observations": observations,
    }


def _derive_audio_access(
    observation: dict[str, Any],
    audio_record: dict[str, Any] | None,
    required_steps: list[str],
) -> dict[str, Any]:
    reviews = {
        row["target_language"]: row for row in observation.get("audio_reviews", [])
    }
    tracks = audio_record.get("tracks", []) if audio_record else []
    track_by_id = {track["track_id"]: track for track in tracks}
    subtitles = audio_record.get("subtitles", []) if audio_record else []
    statuses: dict[str, str] = {}
    failures: dict[str, list[str]] = {}
    selected: dict[str, Any] | None = None
    status_prefix = {
        "ORIGINAL": "ORIGINAL",
        "DUB_MANUAL": "DUB_MANUAL",
        "DUB_AUTOMATIC": "DUB_AUTOMATIC",
    }
    for target in TARGET_AUDIO_LANGUAGES:
        review = reviews.get(target)
        target_failures: list[str] = []
        if review:
            checks = (
                "technical_terminology_checked",
                "mathematical_notation_checked",
                "semantic_alignment_checked",
                "synchronization_checked",
            )
            target_failures.extend(field for field in checks if not review[field])
            if review["issues"]:
                target_failures.append("issues_reported")
            hint = track_by_id.get(review["track_id"], {}).get(
                "audio_kind_hint", "UNKNOWN"
            )
            if hint not in {"UNKNOWN", review["access_type_observed"]}:
                target_failures.append("metadata_kind_conflict")
            if review["verification_method"] == "AUDIO_ARTIFACT":
                linked_audio = set(review["audio_artifact_ids"])
                all_steps_heard = all(
                    any(
                        step_id in timestamp["observed_step_ids"]
                        and bool(linked_audio.intersection(timestamp["artifact_ids"]))
                        and len(
                            timestamp["speech_or_transcript_observed"].split()
                        )
                        >= 4
                        for timestamp in observation.get("timestamps", [])
                    )
                    for step_id in required_steps
                )
            else:
                all_steps_heard = all(
                    any(
                        step_id in timestamp["observed_step_ids"]
                        and len(
                            timestamp["speech_or_transcript_observed"].split()
                        )
                        >= 4
                        for timestamp in observation.get("timestamps", [])
                    )
                    for step_id in required_steps
                )
            if not all_steps_heard:
                target_failures.append("audio_not_linked_to_all_required_steps")
            if not target_failures:
                suffix = "PT" if target == "pt" else "EN"
                status = f"{status_prefix[review['access_type_observed']]}_{suffix}"
                statuses[target] = status
                if selected is None:
                    selected_track = track_by_id[review["track_id"]]
                    selected = {
                        "track_id": review["track_id"],
                        "target_language": target,
                        "status": status,
                        "access_type": review["access_type_observed"],
                        "verification_method": review["verification_method"],
                        "label": selected_track["label"],
                        "language": selected_track["language"],
                    }
            else:
                statuses[target] = "NAO_VERIFICAVEL"
        elif any(track.get("language_family") == target for track in tracks):
            statuses[target] = "TRACK_METADATA_ONLY"
        elif any(row.get("language_family") == target for row in subtitles):
            statuses[target] = "SUBTITLE_ONLY"
        elif audio_record:
            statuses[target] = "NO_TARGET_AUDIO"
        else:
            statuses[target] = "NAO_VERIFICAVEL"
        if target_failures:
            failures[target] = target_failures
    return {
        "target_statuses": statuses,
        "target_audio_verified": any(
            status in AUDIO_VERIFIED_STATUSES for status in statuses.values()
        ),
        "selected_audio": selected,
        "review_failures": failures,
        "subtitle_never_counts_as_dubbing": True,
    }


def _derive_result(
    observation: dict[str, Any],
    candidate: dict[str, Any],
    unit: dict[str, Any],
    *,
    map_verified: bool,
    audio_record: dict[str, Any] | None,
    reused_across_unit_ids: list[str] | None = None,
) -> dict[str, Any]:
    reused_across_unit_ids = reused_across_unit_ids or []
    methods = set(observation["inspection_methods"])
    covered_steps = sorted(
        {
            step
            for timestamp in observation["timestamps"]
            for step in timestamp["observed_step_ids"]
        }
    )
    required_steps = [step["step_id"] for step in unit["required_steps"]]
    missing_steps = [step for step in required_steps if step not in covered_steps]
    artifact_by_id = {
        artifact["artifact_id"]: artifact for artifact in observation["artifacts"]
    }
    referred = {
        artifact_id
        for timestamp in observation["timestamps"]
        for artifact_id in timestamp["artifact_ids"]
    }
    visual_artifact = any(
        artifact_by_id[artifact_id]["kind"] in VISUAL_KINDS
        for artifact_id in referred
        if artifact_id in artifact_by_id
    )
    transcript_ok = (
        observation["transcript"]["available"]
        and observation["transcript"]["artifact_id"] in artifact_by_id
        and artifact_by_id[observation["transcript"]["artifact_id"]]["kind"]
        == "TRANSCRIPT"
    )
    speech_ok = bool(methods & SPEECH_INSPECTIONS) and (
        transcript_ok or len(observation["speech_observed"].split()) >= 4
    )
    visual_ok = bool(methods & VISUAL_INSPECTIONS) and visual_artifact
    timestamps_ok = bool(observation["timestamps"]) and all(
        timestamp["artifact_ids"] for timestamp in observation["timestamps"]
    )
    steps_ok = not missing_steps
    direct_speech = bool(methods & {"FALA_VERIFICADA", "DIRETA"}) and len(
        observation["speech_observed"].split()
    ) >= 4
    linked_step_evidence = all(
        any(
            step_id in timestamp["observed_step_ids"]
            and len(timestamp["speech_or_transcript_observed"].split()) >= 4
            and any(
                artifact_by_id[artifact_id]["kind"] in VISUAL_KINDS
                for artifact_id in timestamp["artifact_ids"]
                if artifact_id in artifact_by_id
            )
            and (
                direct_speech
                or any(
                    artifact_by_id[artifact_id]["kind"] in {"TRANSCRIPT", "AUDIO"}
                    for artifact_id in timestamp["artifact_ids"]
                    if artifact_id in artifact_by_id
                )
            )
            for timestamp in observation["timestamps"]
        )
        for step_id in required_steps
    )
    linked_covered_evidence = bool(covered_steps) and all(
        any(
            step_id in timestamp["observed_step_ids"]
            and len(timestamp["speech_or_transcript_observed"].split()) >= 4
            and any(
                artifact_by_id[artifact_id]["kind"] in VISUAL_KINDS
                for artifact_id in timestamp["artifact_ids"]
                if artifact_id in artifact_by_id
            )
            and (
                direct_speech
                or any(
                    artifact_by_id[artifact_id]["kind"] in {"TRANSCRIPT", "AUDIO"}
                    for artifact_id in timestamp["artifact_ids"]
                    if artifact_id in artifact_by_id
                )
            )
            for timestamp in observation["timestamps"]
        )
        for step_id in covered_steps
    )
    prerequisites_ok = not observation["missing_prerequisites"]
    equivalent_ok = (
        observation["match_observation"] != "EQUIVALENT"
        or len(observation["equivalence_rationale"].split()) >= 8
    )
    audio_access = _derive_audio_access(observation, audio_record, required_steps)
    component_audio_access = _derive_audio_access(
        observation, audio_record, covered_steps
    )
    gates = {
        "map_verified": map_verified,
        "candidate_identity_confirmed": observation["candidate_identity_confirmed"],
        "speech_or_transcript_verified": speech_ok,
        "visual_evidence_verified": visual_ok,
        "timestamps_have_artifacts": timestamps_ok,
        "all_required_steps_observed": steps_ok,
        "each_step_has_linked_speech_and_visual": linked_step_evidence,
        "prerequisites_complete": prerequisites_ok,
        "equivalence_explained": equivalent_ok,
        "unit_specific_evidence": not reused_across_unit_ids,
        "target_audio_verified": audio_access["target_audio_verified"],
    }
    match = observation["match_observation"]
    internal_content_observed = (
        observation["candidate_identity_confirmed"]
        and timestamps_ok
        and (speech_ok or visual_ok)
    )
    conflict_at = (
        observation["conflict"]["timestamp_seconds"]
        if observation["conflict"] is not None
        else None
    )
    conflict_evidenced = conflict_at is not None and any(
        timestamp["start_seconds"] <= conflict_at <= timestamp["end_seconds"]
        for timestamp in observation["timestamps"]
    )
    if match == "UNVERIFIABLE" or not internal_content_observed:
        classification = "NAO_VERIFICAVEL"
    elif match == "CONFLICT" and conflict_evidenced:
        classification = "ERRO_MATEMATICO"
    elif match == "CONFLICT":
        classification = "NAO_VERIFICAVEL"
    elif match == "THEORY":
        classification = "TEORIA_APENAS"
    elif match == "PARTIAL" or not steps_ok or not prerequisites_ok or not equivalent_ok:
        classification = "PARCIAL"
    elif not all(
        gates[name]
        for name in (
            "map_verified",
            "candidate_identity_confirmed",
            "speech_or_transcript_verified",
            "visual_evidence_verified",
            "timestamps_have_artifacts",
            "each_step_has_linked_speech_and_visual",
            "unit_specific_evidence",
        )
    ):
        classification = "NAO_VERIFICAVEL"
    elif match == "EXACT":
        classification = "EXATO"
    elif match == "EQUIVALENT":
        classification = "EQUIVALENTE_RIGOROSO"
    else:
        classification = "NAO_VERIFICAVEL"
    accepted_content = classification in APPROVED_CLASSIFICATIONS
    fixture = observation["fixture"] or candidate.get("fixture", False)
    intervals = merge_intervals(
        (timestamp["start_seconds"], timestamp["end_seconds"])
        for timestamp in observation["timestamps"]
    )
    content_useful_seconds = (
        sum(end - start for start, end in intervals) if accepted_content else 0.0
    )
    eligible = accepted_content and audio_access["target_audio_verified"] and not fixture
    useful_seconds = content_useful_seconds if eligible else 0.0
    component_match_ok = match in {"EXACT", "EQUIVALENT"}
    component_content_ok = all(
        (
            map_verified,
            observation["candidate_identity_confirmed"],
            speech_ok,
            visual_ok,
            timestamps_ok,
            linked_covered_evidence,
            prerequisites_ok,
            equivalent_ok,
            component_match_ok,
            bool(covered_steps),
        )
    )
    component_classification = (
        "EXATO"
        if component_content_ok and match == "EXACT"
        else "EQUIVALENTE_RIGOROSO"
        if component_content_ok and match == "EQUIVALENT"
        else None
    )
    component_eligible = bool(
        component_classification
        and component_audio_access["target_audio_verified"]
        and not fixture
    )
    component_useful_seconds = (
        sum(end - start for start, end in intervals) if component_eligible else 0.0
    )
    failed_gates = [name for name, passed in gates.items() if not passed]
    decision_reasons: list[str] = []
    if classification == "PARCIAL":
        decision_reasons.append("a observação interna é parcial")
    elif classification == "TEORIA_APENAS":
        decision_reasons.append("o vídeo oferece teoria, não a execução exigida")
    elif classification == "ERRO_MATEMATICO" and observation["conflict"]:
        decision_reasons.append(
            "conflito interno observado: " + observation["conflict"]["description"]
        )
    elif classification == "NAO_VERIFICAVEL":
        decision_reasons.append("o conteúdo interno não atingiu evidência verificável")
    if observation["missing_prerequisites"]:
        decision_reasons.append(
            "pré-requisitos ausentes: "
            + "; ".join(observation["missing_prerequisites"])
        )
    if accepted_content and not audio_access["target_audio_verified"]:
        decision_reasons.append(
            "nenhuma faixa de áudio em português ou inglês foi ouvida e aprovada"
        )
    if reused_across_unit_ids:
        decision_reasons.append(
            "a mesma janela audiovisual foi reutilizada para unidades distintas: "
            + ", ".join(reused_across_unit_ids)
        )
    return {
        "candidate_id": candidate["candidate_id"],
        "unit_id": unit["unit_id"],
        "classification": classification,
        "eligible_for_course": eligible,
        "fixture": fixture,
        "raw_match_observation": match,
        "acceptance_gates": gates,
        "failed_gates": failed_gates,
        "decision_reasons": decision_reasons,
        "covered_step_ids": covered_steps,
        "missing_step_ids": missing_steps,
        "missing_prerequisites": observation["missing_prerequisites"],
        "equivalence_rationale": observation["equivalence_rationale"],
        "conflict": observation["conflict"],
        "useful_intervals": [
            {"start_seconds": start, "end_seconds": end} for start, end in intervals
        ],
        "useful_seconds": useful_seconds,
        "content_useful_seconds": content_useful_seconds,
        "audio_access": audio_access,
        "component_eligible": component_eligible,
        "component_classification": component_classification,
        "component_covered_step_ids": covered_steps,
        "component_useful_seconds": component_useful_seconds,
        "component_audio_access": component_audio_access,
        "observation_id": observation["observation_id"],
        "artifact_ids": sorted(referred),
        "evidence_reused_across_unit_ids": reused_across_unit_ids,
    }


def _unobserved_result(
    candidate: dict[str, Any],
    unit: dict[str, Any],
    audio_record: dict[str, Any] | None,
) -> dict[str, Any]:
    audio_access = _derive_audio_access(
        {"audio_reviews": [], "timestamps": []}, audio_record, []
    )
    return {
        "candidate_id": candidate["candidate_id"],
        "unit_id": unit["unit_id"],
        "classification": "NAO_VERIFICAVEL",
        "eligible_for_course": False,
        "fixture": candidate.get("fixture", False),
        "raw_match_observation": None,
        "acceptance_gates": {},
        "failed_gates": ["internal_inspection_missing"],
        "decision_reasons": ["o candidato não possui inspeção interna importada"],
        "covered_step_ids": [],
        "missing_step_ids": [step["step_id"] for step in unit["required_steps"]],
        "missing_prerequisites": [],
        "equivalence_rationale": "",
        "conflict": None,
        "useful_intervals": [],
        "useful_seconds": 0.0,
        "content_useful_seconds": 0.0,
        "audio_access": audio_access,
        "component_eligible": False,
        "component_classification": None,
        "component_covered_step_ids": [],
        "component_useful_seconds": 0.0,
        "component_audio_access": audio_access,
        "observation_id": None,
        "artifact_ids": [],
        "evidence_reused_across_unit_ids": [],
    }


def _best_result(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not results:
        return None
    priority = {
        "EXATO": 70,
        "EQUIVALENTE_RIGOROSO": 60,
        "ERRO_MATEMATICO": 50,
        "PARCIAL": 40,
        "TEORIA_APENAS": 30,
        "NAO_VERIFICAVEL": 20,
        "NAO_ENCONTRADO": 10,
    }
    return sorted(
        results,
        key=lambda row: (
            1 if row["eligible_for_course"] else 0,
            priority[row["classification"]],
            len(row["covered_step_ids"]),
            -row["useful_seconds"],
            row.get("candidate_id") or "",
        ),
        reverse=True,
    )[0]


def _composite_cover(
    results: list[dict[str, Any]], unit: dict[str, Any]
) -> dict[str, Any] | None:
    required = {step["step_id"] for step in unit["required_steps"]}
    options = [
        row
        for row in results
        if row.get("component_eligible") and not row.get("fixture")
    ]
    if not options or not required <= {
        step
        for row in options
        for step in row["component_covered_step_ids"]
    }:
        return None
    uncovered = set(required)
    selected: list[dict[str, Any]] = []
    remaining = list(options)
    while uncovered:
        useful = [
            (row, uncovered.intersection(row["component_covered_step_ids"]))
            for row in remaining
        ]
        useful = [(row, new) for row, new in useful if new]
        if not useful:
            return None
        row, newly_covered = min(
            useful,
            key=lambda pair: (
                -len(pair[1]),
                0 if pair[0]["component_classification"] == "EXATO" else 1,
                pair[0]["component_useful_seconds"],
                pair[0]["candidate_id"],
            ),
        )
        selected.append(row)
        uncovered -= newly_covered
        remaining = [item for item in remaining if item is not row]
    if len(selected) < 2:
        return None
    classification = (
        "EXATO"
        if all(row["component_classification"] == "EXATO" for row in selected)
        else "EQUIVALENTE_RIGOROSO"
    )
    components = [
        {
            "candidate_id": row["candidate_id"],
            "classification": row["component_classification"],
            "covered_step_ids": row["component_covered_step_ids"],
            "useful_intervals": row["useful_intervals"],
            "useful_seconds": row["component_useful_seconds"],
            "selected_audio": row["component_audio_access"]["selected_audio"],
            "observation_id": row["observation_id"],
        }
        for row in selected
    ]
    return {
        "classification": classification,
        "eligible_for_course": True,
        "fixture": False,
        "coverage_mode": "COMPOSITE",
        "selected_candidate_id": None,
        "selected_candidate_ids": [row["candidate_id"] for row in selected],
        "selected_components": components,
        "useful_seconds": sum(
            row["component_useful_seconds"] for row in selected
        ),
    }


def _search_state_for_unit(
    unit_id: str,
    query_doc: dict[str, Any],
    candidate_doc: dict[str, Any],
) -> str:
    queries = [
        row
        for row in query_doc.get("queries", [])
        if row.get("unit_id") == unit_id
    ]
    attempts = candidate_doc.get("search_attempts", [])
    completed = {
        row["query_id"]
        for row in attempts
        if row.get("status") == "COMPLETED"
    }
    completed_expansions = {
        (row.get("unit_id"), row.get("language"))
        for row in attempts
        if row.get("status") == "COMPLETED"
        and row.get("origin") == "OPEN_EXPANSION"
    }
    failed = {
        row["query_id"]
        for row in attempts
        if row.get("status") == "FAILED"
    }
    satisfied = {
        row["query_id"]
        for row in queries
        if row["query_id"] in completed
        or (
            not row.get("execution_ready", True)
            and (unit_id, row.get("language")) in completed_expansions
        )
    }
    query_ids = {row["query_id"] for row in queries}
    if not query_ids or not satisfied:
        return "NAO_INICIADA"
    if query_ids <= satisfied:
        return "PLANO_SEMENTE_CONCLUIDO"
    if failed.intersection(query_ids):
        return "FALHAS_PENDENTES"
    if any(
        not row.get("execution_ready", True)
        and row["query_id"] not in satisfied
        for row in queries
    ):
        return "LOCALIZACAO_PENDENTE"
    return "PARCIAL"


def _reused_evidence_by_pair(
    observations: list[dict[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    """Detecta a reciclagem da mesma janela para afirmar coberturas distintas.

    Um vídeo pode cobrir várias unidades, mas cada afirmação precisa apontar a
    janela interna que realmente executa aquela unidade. A mesma combinação de
    intervalos e artefatos não pode ser renomeada com outros ``step_id`` para
    fabricar cobertura.
    """

    signatures: dict[tuple[str, tuple[Any, ...]], list[str]] = {}
    for observation in observations:
        artifact_hashes = {
            artifact["artifact_id"]: artifact["sha256"]
            for artifact in observation["artifacts"]
        }
        windows = tuple(
            sorted(
                (
                    float(timestamp["start_seconds"]),
                    float(timestamp["end_seconds"]),
                    tuple(
                        sorted(
                            artifact_hashes[artifact_id]
                            for artifact_id in timestamp["artifact_ids"]
                            if artifact_id in artifact_hashes
                        )
                    ),
                )
                for timestamp in observation["timestamps"]
            )
        )
        if not windows:
            continue
        key = (observation["candidate_id"], windows)
        signatures.setdefault(key, []).append(observation["unit_id"])
    result: dict[tuple[str, str], list[str]] = {}
    for (candidate_id, _), unit_ids in signatures.items():
        unique_units = sorted(set(unit_ids))
        if len(unique_units) < 2:
            continue
        for unit_id in unique_units:
            result[(candidate_id, unit_id)] = [
                other for other in unique_units if other != unit_id
            ]
    return result


def audit(
    workspace: Path,
    evidence_path: Path,
    *,
    allow_fixtures: bool = False,
    write_outputs: bool = True,
) -> dict[str, Any]:
    ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
    query_doc = read_json(workspace / "ledgers" / "search_queries.json")
    candidate_doc = read_json(workspace / "ledgers" / "candidates.json")
    inventory_path = workspace / "ledgers" / "audio_inventory.json"
    if not inventory_path.is_file():
        raise ValueError("inventário de áudio ausente; execute inspect-audio ou importe-o")
    audio_inventory = validate_audio_inventory(read_json(inventory_path), candidate_doc)
    audio_records, _ = inventory_indexes(audio_inventory)
    normalized = validate_evidence_input(
        workspace,
        read_json(evidence_path),
        ledger,
        candidate_doc,
        audio_inventory=audio_inventory,
        allow_fixtures=allow_fixtures,
    )
    if write_outputs:
        atomic_write_json(workspace / "evidence" / "evidence_input.json", normalized)
    units = {unit["unit_id"]: unit for unit in ledger["units"]}
    candidates = {
        candidate["candidate_id"]: candidate for candidate in candidate_doc["candidates"]
    }
    observation_by_pair = {
        (row["candidate_id"], row["unit_id"]): row
        for row in normalized["observations"]
    }
    reused_evidence = _reused_evidence_by_pair(normalized["observations"])
    map_verified = ledger.get("map_state") == "V1_VERIFIED" and all(
        unit.get("verification_state") in {"VERIFIED_BY_AGENT", "VERIFIED_BY_HUMAN"}
        for unit in units.values()
    )
    results: list[dict[str, Any]] = []
    for candidate in candidates.values():
        for unit_id in candidate["unit_ids"]:
            unit = units[unit_id]
            observation = observation_by_pair.get((candidate["candidate_id"], unit_id))
            if observation:
                results.append(
                    _derive_result(
                        observation,
                        candidate,
                        unit,
                        map_verified=map_verified,
                        audio_record=audio_records.get(candidate["candidate_id"]),
                        reused_across_unit_ids=reused_evidence.get(
                            (candidate["candidate_id"], unit_id), []
                        ),
                    )
                )
            else:
                results.append(
                    _unobserved_result(
                        candidate,
                        unit,
                        audio_records.get(candidate["candidate_id"]),
                    )
                )

    unit_results: list[dict[str, Any]] = []
    for unit in units.values():
        options = [row for row in results if row["unit_id"] == unit["unit_id"]]
        best_real = _best_result(
            [row for row in options if row["eligible_for_course"]]
        )
        composite = None if best_real else _composite_cover(options, unit)
        best = best_real or _best_result(options)
        search_state = _search_state_for_unit(unit["unit_id"], query_doc, candidate_doc)
        if composite:
            unit_results.append(
                {
                    "unit_id": unit["unit_id"],
                    **composite,
                    "candidate_result_count": len(options),
                    "search_state": search_state,
                    "decision_reason": (
                        "a união de componentes audiovisuais auditados cobre todos os passos"
                    ),
                }
            )
        elif best is None:
            classification = (
                "NAO_ENCONTRADO"
                if search_state == "PLANO_SEMENTE_CONCLUIDO"
                else "NAO_VERIFICAVEL"
            )
            unit_results.append(
                {
                    "unit_id": unit["unit_id"],
                    "classification": classification,
                    "coverage_mode": "NONE",
                    "selected_candidate_id": None,
                    "selected_candidate_ids": [],
                    "selected_components": [],
                    "eligible_for_course": False,
                    "fixture": False,
                    "candidate_result_count": 0,
                    "search_state": search_state,
                    "decision_reason": (
                        "nenhum candidato após concluir o plano de sementes"
                        if classification == "NAO_ENCONTRADO"
                        else "busca insuficiente para declarar não encontrado"
                    ),
                }
            )
        else:
            unit_results.append(
                {
                    "unit_id": unit["unit_id"],
                    "classification": best["classification"],
                    "coverage_mode": "SINGLE",
                    "selected_candidate_id": best["candidate_id"],
                    "selected_candidate_ids": [best["candidate_id"]],
                    "selected_components": [],
                    "eligible_for_course": best["eligible_for_course"],
                    "fixture": best["fixture"],
                    "candidate_result_count": len(options),
                    "search_state": search_state,
                    "selected_audio": best["audio_access"]["selected_audio"],
                }
            )
    counts = Counter(row["classification"] for row in unit_results)
    output = {
        "schema_name": "projeto-e-video.audit",
        "schema_version": 3,
        "created_at": now_iso(),
        "course_id": ledger["course_id"],
        "derivation_engine": "projeto_e_video.audit/v3",
        "input_hashes": {
            "unit_ledger_sha256": sha256_json(ledger),
            "candidates_sha256": sha256_json(candidate_doc),
            "audio_inventory_sha256": sha256_json(audio_inventory),
            "evidence_input_sha256": sha256_json(normalized),
        },
        "map_verified": map_verified,
        "unit_count": len(units),
        "candidate_count": len(candidates),
        "observation_count": len(normalized["observations"]),
        "audio_inventory_record_count": len(audio_inventory["records"]),
        "classification_counts": {
            name: counts.get(name, 0) for name in CLASSIFICATIONS
        },
        "unit_results": unit_results,
        "candidate_results": sorted(
            results, key=lambda row: (row["unit_id"], row["candidate_id"])
        ),
        "notice": "Classificações foram derivadas; metadados isolados nunca fecham cobertura.",
    }
    if write_outputs:
        atomic_write_json(workspace / "audit" / "audit.json", output)
    return output
