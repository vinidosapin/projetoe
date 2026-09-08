"""Validação cruzada de um workspace de curso."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .audio import validate_audio_inventory
from .audit import (
    AUDIO_VERIFIED_STATUSES,
    audit as derive_audit,
    validate_evidence_input,
)
from .course import build_course, render_course
from .ingest import validate_source_manifest
from .models import APPROVED_CLASSIFICATIONS, CLASSIFICATIONS
from .planning import build_queries, validate_refined_map
from .providers import validate_candidates
from .util import atomic_write_json, now_iso, read_json


def _require(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"arquivo obrigatório ausente: {path}")


def validate_workspace(workspace: Path, *, write_report: bool = True) -> dict[str, Any]:
    required = [
        workspace / "ingest" / "source_manifest.json",
        workspace / "ledgers" / "unit_ledger.json",
        workspace / "ledgers" / "search_queries.json",
        workspace / "ledgers" / "candidates.json",
        workspace / "ledgers" / "audio_inventory.json",
        workspace / "evidence" / "evidence_input.json",
        workspace / "audit" / "audit.json",
        workspace / "course" / "course.json",
        workspace / "course" / "COURSE.md",
        workspace / "course" / "index.html",
    ]
    for path in required:
        _require(path)
    manifest = read_json(required[0])
    source_validation = validate_source_manifest(workspace, manifest)
    ledger = read_json(required[1])
    queries = read_json(required[2])
    candidate_doc = read_json(required[3])
    audio_inventory = read_json(required[4])
    evidence = read_json(required[5])
    audit = read_json(required[6])
    course = read_json(required[7])
    course_id = manifest.get("course_id")
    for name, document in (
        ("ledger", ledger),
        ("queries", queries),
        ("candidates", candidate_doc),
        ("audio_inventory", audio_inventory),
        ("evidence", evidence),
        ("audit", audit),
        ("course", course),
    ):
        if document.get("course_id") != course_id:
            raise ValueError(f"course_id divergente em {name}")
    units = {row["unit_id"]: row for row in ledger.get("units", [])}
    if not units:
        raise ValueError("ledger sem unidades")
    if len(units) != len(ledger["units"]):
        raise ValueError("unit_id duplicado no ledger")
    query_units = {row.get("unit_id") for row in queries.get("queries", [])}
    if query_units - set(units):
        raise ValueError("consulta aponta unidade desconhecida")
    normalized_ledger = validate_refined_map(ledger, manifest)
    comparable_ledger = dict(ledger)
    comparable_normalized_ledger = dict(normalized_ledger)
    comparable_ledger.pop("created_at", None)
    comparable_normalized_ledger.pop("created_at", None)
    if comparable_ledger != comparable_normalized_ledger:
        raise ValueError("unit_ledger.json não está em forma canônica V1")
    expected_queries = build_queries(ledger)
    comparable_queries = dict(queries)
    comparable_expected_queries = dict(expected_queries)
    comparable_queries.pop("created_at", None)
    comparable_expected_queries.pop("created_at", None)
    if comparable_queries != comparable_expected_queries:
        raise ValueError("search_queries.json diverge do mapa V1")

    # Reexecuta os validadores de fronteira; eles não confiam nos arquivos já
    # presentes no workspace.
    normalized_candidates = validate_candidates(
        candidate_doc, ledger, query_doc=queries, allow_fixtures=True
    )
    if any(
        normalized_candidates.get(field) != candidate_doc.get(field)
        for field in (
            "schema_name",
            "schema_version",
            "course_id",
            "search_scope",
            "search_attempts",
            "candidate_count",
            "candidates",
        )
    ):
        raise ValueError("candidates.json não está em forma canônica")
    normalized_audio = validate_audio_inventory(audio_inventory, candidate_doc)
    if any(
        normalized_audio.get(field) != audio_inventory.get(field)
        for field in ("schema_name", "schema_version", "course_id", "records")
    ):
        raise ValueError("audio_inventory.json não está em forma canônica")
    validate_evidence_input(
        workspace,
        evidence,
        ledger,
        candidate_doc,
        audio_inventory=audio_inventory,
        allow_fixtures=True,
    )
    expected_audit = derive_audit(
        workspace,
        workspace / "evidence" / "evidence_input.json",
        allow_fixtures=True,
        write_outputs=False,
    )
    comparable_audit = dict(audit)
    comparable_expected_audit = dict(expected_audit)
    comparable_audit.pop("created_at", None)
    comparable_expected_audit.pop("created_at", None)
    if comparable_audit != comparable_expected_audit:
        raise ValueError("audit.json diverge da derivação da evidência bruta")
    candidates = {row["candidate_id"]: row for row in candidate_doc["candidates"]}
    candidate_results = audit.get("candidate_results")
    unit_results = audit.get("unit_results")
    if not isinstance(candidate_results, list) or not isinstance(unit_results, list):
        raise ValueError("audit.json incompleto")
    if {row.get("unit_id") for row in unit_results} != set(units):
        raise ValueError("audit não cobre exatamente todas as unidades")
    for result in candidate_results:
        classification = result.get("classification")
        if classification not in CLASSIFICATIONS:
            raise ValueError("classificação inválida na auditoria")
        candidate_id = result.get("candidate_id")
        unit_id = result.get("unit_id")
        if candidate_id not in candidates or unit_id not in units:
            raise ValueError("resultado de candidato aponta ID desconhecido")
        if unit_id not in candidates[candidate_id]["unit_ids"]:
            raise ValueError("resultado candidato/unidade incompatível")
        expected_eligibility = (
            classification in APPROVED_CLASSIFICATIONS
            and result.get("audio_access", {}).get("target_audio_verified") is True
            and not result.get("fixture", False)
        )
        if result.get("eligible_for_course") is not expected_eligibility:
            raise ValueError("eligible_for_course não foi derivado corretamente")
        if classification not in APPROVED_CLASSIFICATIONS and result.get("useful_seconds"):
            raise ValueError("tempo útil contado para vídeo não aprovado")
    counts = Counter(row["classification"] for row in unit_results)
    expected_counts = {name: counts.get(name, 0) for name in CLASSIFICATIONS}
    if audit.get("classification_counts") != expected_counts:
        raise ValueError("contagens da auditoria divergentes")

    routes = course.get("routes")
    if not isinstance(routes, list) or len(routes) != len(units):
        raise ValueError("course.json não possui uma rota por unidade")
    released = 0
    required_count = 0
    optional_available_count = 0
    useful = 0.0
    for route in routes:
        if route.get("unit_id") not in units:
            raise ValueError("rota aponta unidade desconhecida")
        if route.get("counts_as_required_coverage"):
            required_count += 1
        if route.get("optional_available"):
            optional_available_count += 1
            if route.get("automatically_recommended"):
                raise ValueError(
                    "rota opcional não pode ser recomendada automaticamente"
                )
            optional_videos = route.get("optional_videos")
            if not isinstance(optional_videos, list) or not optional_videos:
                raise ValueError("rota opcional disponível não contém vídeos")
            for optional_video in optional_videos:
                audio = optional_video.get("audio")
                if (
                    not isinstance(audio, dict)
                    or audio.get("status") not in AUDIO_VERIFIED_STATUSES
                ):
                    raise ValueError("rota opcional sem faixa PT/EN verificada")
        if route.get("released"):
            released += 1
            if route.get("classification") not in APPROVED_CLASSIFICATIONS:
                raise ValueError("rota liberada sem classe aprovada")
            videos = route.get("videos")
            if not isinstance(videos, list) or not videos:
                raise ValueError("rota real sem componente audiovisual")
            mode = route.get("coverage_mode")
            if mode not in {"SINGLE", "COMPOSITE"}:
                raise ValueError("rota real possui modo de cobertura inválido")
            if mode == "SINGLE" and len(videos) != 1:
                raise ValueError("rota SINGLE deve conter exatamente um vídeo")
            if mode == "COMPOSITE" and len(videos) < 2:
                raise ValueError("rota COMPOSITE deve conter ao menos dois vídeos")
            covered_steps = {
                step_id
                for video in videos
                for step_id in video.get("covered_step_ids", [])
            }
            required_steps = {
                row["step_id"] for row in units[route["unit_id"]]["required_steps"]
            }
            if not required_steps <= covered_steps:
                raise ValueError("rota real não cobre todos os passos obrigatórios")
            for video in videos:
                if not isinstance(video, dict) or video.get("fixture"):
                    raise ValueError("rota real contém componente inválido")
                audio = video.get("audio")
                if (
                    not isinstance(audio, dict)
                    or audio.get("status") not in AUDIO_VERIFIED_STATUSES
                ):
                    raise ValueError("rota real sem faixa PT/EN verificada")
            useful += float(route.get("useful_seconds", 0))
        elif route.get("videos") and not route.get("fixture_demonstration"):
            raise ValueError("rota não liberada contém componentes principais")
    if released != course.get("released_unit_count"):
        raise ValueError("released_unit_count divergente")
    if required_count != course.get("required_unit_count"):
        raise ValueError("required_unit_count divergente")
    if optional_available_count != course.get("optional_available_count"):
        raise ValueError("optional_available_count divergente")
    if abs(useful - float(course.get("total_useful_seconds", -1))) > 0.001:
        raise ValueError("total_useful_seconds divergente")
    expected_state = "COBERTA" if released == required_count else "PARCIAL"
    required_routes = [
        route for route in routes if route.get("counts_as_required_coverage")
    ]
    if required_routes and all(
        route.get("fixture_demonstration") for route in required_routes
    ):
        expected_state = "DEMONSTRACAO_FIXTURE"
    if course.get("course_state") != expected_state:
        raise ValueError("course_state divergente")
    if course.get("promotion_ready") is not False:
        raise ValueError("alpha não pode declarar promotion_ready=true")
    expected_course = build_course(workspace, write_outputs=False)
    comparable_course = dict(course)
    comparable_expected_course = dict(expected_course)
    comparable_course.pop("created_at", None)
    comparable_expected_course.pop("created_at", None)
    if comparable_course != comparable_expected_course:
        raise ValueError("course.json diverge da reconstrução determinística")
    expected_markdown, expected_html = render_course(expected_course)
    if (workspace / "course" / "COURSE.md").read_text(encoding="utf-8") != expected_markdown:
        raise ValueError("COURSE.md diverge de course.json")
    if (workspace / "course" / "index.html").read_text(encoding="utf-8") != expected_html:
        raise ValueError("index.html diverge de course.json")
    report = {
        "schema_name": "projeto-e-video.workspace-validation",
        "schema_version": 1,
        "created_at": now_iso(),
        "valid": True,
        "course_id": course_id,
        "unit_count": len(units),
        "candidate_count": len(candidates),
        "released_unit_count": released,
        "course_state": course["course_state"],
        "checks": [
            "manifesto, hashes e vínculo das fontes",
            "IDs cruzados",
            "candidatos canônicos e sem autoaprovação",
            "plano de busca mundial rederivado do mapa V1",
            "inventário de áudio canônico",
            "artefatos existentes com hash",
            "classificações derivadas",
            "somente EXATO/EQUIVALENTE_RIGOROSO liberados",
            "tempo útil sem lacunas ou fixtures",
            "rota somente com faixa PT/EN realmente inspecionada",
            "rotas compostas cobrem a união exata dos passos",
            "alpha sem promoção",
        ],
        "source_validation": source_validation,
    }
    if write_report:
        atomic_write_json(workspace / "validation_report.json", report)
    return report
