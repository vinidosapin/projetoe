from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from projeto_e_video.audio import import_audio_inventory
from projeto_e_video.audit import audit
from projeto_e_video.ingest import ingest
from projeto_e_video.planning import create_plan, import_map
from projeto_e_video.providers import import_candidates
from projeto_e_video.util import (
    atomic_write_json,
    atomic_write_text,
    read_json,
    sha256_file,
)


def verified_workspace(
    base: Path,
    *,
    text: str = "# Exercício\nResolva o problema, justifique o método e confira a resposta.",
) -> tuple[Path, dict[str, Any]]:
    workspace = base / "workspace"
    workspace.mkdir()
    source = base / "source.md"
    source.write_text(text, encoding="utf-8")
    ingest(str(source), workspace, title="Curso de teste")
    draft = create_plan(workspace)
    refined = copy.deepcopy(draft)
    for unit in refined["units"]:
        unit["verification_state"] = "VERIFIED_BY_HUMAN"
    map_file = base / "map.json"
    atomic_write_json(map_file, refined)
    return workspace, import_map(workspace, map_file)


def add_candidate(
    base: Path,
    workspace: Path,
    ledger: dict[str, Any],
    *,
    url: str = "https" + "://www.youtube.com/watch?v=abcdefghijk",
    fixture: bool = False,
    audio_kind: str = "ORIGINAL",
    audio_language: str = "pt-BR",
    include_audio_track: bool = True,
    subtitle_language: str | None = None,
) -> dict[str, Any]:
    raw = {
        "schema_name": "projeto-e-video.candidates",
        "schema_version": 2,
        "search_scope": "VERIFIED_CHANNEL_ALLOWLIST",
        "search_attempts": [],
        "candidates": [
            {
                "unit_ids": [unit["unit_id"] for unit in ledger["units"]],
                "url": url,
                "title": "Candidato de teste",
                "channel": "Brasil Escola Oficial",
                "language": "pt",
                "language_basis": "MANUAL_OBSERVATION",
                "discovery_languages": ["pt"],
                "duration_seconds": 600,
                "provider": "test",
                "metadata_observed": ["TITLE", "CHANNEL", "DURATION"],
                "fixture": fixture,
            }
        ],
    }
    path = base / "candidates.json"
    atomic_write_json(path, raw)
    candidate = import_candidates(
        workspace, path, allow_fixtures=fixture
    )["candidates"][0]
    inventory_path = base / "audio-inventory.json"
    atomic_write_json(
        inventory_path,
        {
            "schema_name": "projeto-e-video.audio-inventory",
            "schema_version": 1,
            "records": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_url": candidate["url"],
                    "provider": "test",
                    "inspected_at": "test",
                    "tracks": [
                        {
                            "language": audio_language,
                            "label": "áudio original de teste",
                            "audio_kind_hint": audio_kind,
                            "metadata_basis": ["TEST"],
                            "is_default": True,
                            "formats": [],
                        }
                    ]
                    if include_audio_track
                    else [],
                    "subtitles": [
                        {
                            "language": subtitle_language,
                            "kind": "MANUAL",
                            "formats": ["vtt"],
                        }
                    ]
                    if subtitle_language
                    else [],
                    "warnings": [],
                }
            ],
        },
    )
    import_audio_inventory(workspace, inventory_path)
    return candidate


def artifacts(
    workspace: Path,
    candidate_id: str,
    *,
    track_id: str | None,
    suffix: str = "",
) -> list[dict[str, Any]]:
    directory = workspace / "evidence" / "assets" / candidate_id
    transcript = directory / f"transcript{suffix}.txt"
    frame = directory / f"frame{suffix}.svg"
    audio = directory / f"audio_{track_id or 'NO-TRACK'}{suffix}.txt"
    atomic_write_text(
        transcript,
        "O professor lê o alvo, justifica o método, executa todos os passos e confere o resultado.\n",
    )
    atomic_write_text(
        frame,
        "<svg xmlns='http' + '://www.w3.org/2000/svg'><text>quadro conferido</text></svg>\n",
    )
    atomic_write_text(audio, "Amostra de áudio estrutural usada somente no teste offline.\n")
    return [
        {
            "artifact_id": f"TRANSCRIPT{suffix or '-0'}",
            "path": transcript.relative_to(workspace).as_posix(),
            "sha256": sha256_file(transcript),
            "kind": "TRANSCRIPT",
        },
        {
            "artifact_id": f"FRAME{suffix or '-0'}",
            "path": frame.relative_to(workspace).as_posix(),
            "sha256": sha256_file(frame),
            "kind": "FRAME",
        },
        {
            "artifact_id": f"AUDIO{suffix or '-0'}",
            "path": audio.relative_to(workspace).as_posix(),
            "sha256": sha256_file(audio),
            "kind": "AUDIO",
        },
    ]


def observation(
    workspace: Path,
    candidate: dict[str, Any],
    unit: dict[str, Any],
    *,
    match: str = "EXACT",
    covered_steps: list[str] | None = None,
    methods: list[str] | None = None,
    transcript_available: bool = True,
    identity: bool = True,
    rationale: str = "",
    missing_prerequisites: list[str] | None = None,
    conflict: dict[str, Any] | None = None,
    fixture: bool = False,
    with_timestamps: bool = True,
    with_audio_review: bool = True,
    audio_issues: list[str] | None = None,
    audio_access_type: str = "ORIGINAL",
    target_language: str = "pt",
) -> dict[str, Any]:
    inventory = read_json(workspace / "ledgers" / "audio_inventory.json")
    record = next(
        row
        for row in inventory["records"]
        if row["candidate_id"] == candidate["candidate_id"]
    )
    tracks = record["tracks"]
    track_id = tracks[0]["track_id"] if tracks else None
    artifact_rows = artifacts(
        workspace,
        candidate["candidate_id"],
        track_id=track_id,
        suffix="-" + unit["unit_id"],
    )
    transcript_id = artifact_rows[0]["artifact_id"]
    frame_id = artifact_rows[1]["artifact_id"]
    audio_id = artifact_rows[2]["artifact_id"]
    steps = covered_steps
    if steps is None:
        steps = [step["step_id"] for step in unit["required_steps"]]
    timestamps = []
    if with_timestamps:
        timestamps = [
            {
                "start_seconds": 20,
                "end_seconds": 80,
                "observed_step_ids": steps,
                "observed": "Os passos listados aparecem na fala e no quadro durante este intervalo.",
                "speech_or_transcript_observed": "O professor lê o alvo, justifica o método e executa os passos indicados.",
                "artifact_ids": [transcript_id, frame_id, audio_id],
            },
            {
                "start_seconds": 70,
                "end_seconds": 100,
                "observed_step_ids": steps,
                "observed": "O professor repete a verificação e explicita a conclusão observada.",
                "speech_or_transcript_observed": "O professor confere o resultado e enuncia verbalmente a conclusão obtida.",
                "artifact_ids": [transcript_id, frame_id, audio_id],
            },
        ]
    result: dict[str, Any] = {
        "candidate_id": candidate["candidate_id"],
        "unit_id": unit["unit_id"],
        "candidate_identity_confirmed": identity,
        "inspection_methods": methods
        if methods is not None
        else ["TRANSCRICAO", "FRAME"],
        "match_observation": match,
        "artifacts": artifact_rows,
        "transcript": {
            "available": transcript_available,
            "artifact_id": transcript_id if transcript_available else None,
            "language": "pt",
        },
        "timestamps": timestamps,
        "speech_observed": "O professor explica verbalmente cada decisão mostrada no quadro.",
        "equivalence_rationale": rationale,
        "missing_prerequisites": missing_prerequisites or [],
        "audio_reviews": [],
        "reviewer_notes": "Observação sintética de teste offline.",
        "fixture": fixture,
    }
    if with_audio_review and with_timestamps:
        if track_id is None:
            raise ValueError("fixture de áudio exige faixa")
        result["audio_reviews"] = [
            {
                "track_id": track_id,
                "target_language": target_language,
                "access_type_observed": audio_access_type,
                "verification_method": "AUDIO_ARTIFACT",
                "audio_artifact_ids": [audio_id],
                "track_selection_artifact_id": None,
                "direct_playback_observed": False,
                "technical_terminology_checked": True,
                "mathematical_notation_checked": True,
                "semantic_alignment_checked": True,
                "synchronization_checked": True,
                "issues": audio_issues or [],
                "reviewer_notes": "A faixa de teste foi ouvida e comparada ao conteúdo esperado.",
            }
        ]
    if conflict is not None:
        result["conflict"] = conflict
    return result


def run_audit(
    base: Path,
    workspace: Path,
    observations: list[dict[str, Any]],
    *,
    fixture: bool = False,
) -> dict[str, Any]:
    path = base / "evidence.json"
    atomic_write_json(
        path,
        {
            "schema_name": "projeto-e-video.evidence-input",
            "schema_version": 2,
            "observations": observations,
        },
    )
    return audit(workspace, path, allow_fixtures=fixture)
