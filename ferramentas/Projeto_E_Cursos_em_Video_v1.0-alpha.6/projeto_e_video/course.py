"""Composição e renderização do curso a partir da auditoria derivada."""

from __future__ import annotations

import html
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

from .audit import audit as derive_audit
from .models import APPROVED_CLASSIFICATIONS
from .util import (
    atomic_write_json,
    atomic_write_text,
    format_seconds,
    now_iso,
    read_json,
    sha256_file,
)


def _timestamp_url(url: str, start: float, end: float) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.netloc.lower().endswith("youtube.com") or parsed.netloc.lower() == "youtu.be":
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(key, value) for key, value in query if key != "t"]
        query.append(("t", str(int(start))))
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
        )
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.query, f"t={start:.3f},{end:.3f}")
    )


GATE_LABELS = {
    "map_verified": "o mapa curricular ainda não foi conferido",
    "candidate_identity_confirmed": "a identidade do vídeo não foi confirmada",
    "speech_or_transcript_verified": "a fala ou transcrição interna não foi verificada",
    "visual_evidence_verified": "faltam frames ou inspeção visual do conteúdo",
    "timestamps_have_artifacts": "há timestamps sem artefatos associados",
    "all_required_steps_observed": "nem todos os passos obrigatórios foram observados",
    "each_step_has_linked_speech_and_visual": "há passo sem fala e quadro ligados ao mesmo intervalo",
    "prerequisites_complete": "o vídeo exige pré-requisitos não incluídos",
    "equivalence_explained": "a equivalência estrutural não foi justificada",
    "unit_specific_evidence": "a mesma janela audiovisual foi reciclada para outra unidade",
    "target_audio_verified": "nenhuma faixa em português ou inglês foi realmente ouvida e aprovada",
    "internal_inspection_missing": "o candidato ainda não foi inspecionado por dentro",
}


def _human_gate(value: str) -> str:
    return GATE_LABELS.get(value, value.replace("_", " "))


def _video_entry(
    candidate: dict[str, Any],
    *,
    intervals: list[dict[str, Any]],
    useful_seconds: float,
    selected_audio: dict[str, Any],
    covered_step_ids: list[str],
    fixture: bool,
) -> dict[str, Any]:
    segments = []
    for interval in intervals:
        start = interval["start_seconds"]
        end = interval["end_seconds"]
        segments.append(
            {
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": end - start,
                "label": f"{format_seconds(start)}–{format_seconds(end)}",
                "url": _timestamp_url(candidate["url"], start, end),
            }
        )
    return {
        "candidate_id": candidate["candidate_id"],
        "title": candidate["title"],
        "channel": candidate["channel"],
        "source_language_hint": candidate["language"],
        "covered_step_ids": covered_step_ids,
        "audio": selected_audio,
        "audio_selection_instruction": (
            "No player, abra Configurações > Faixa de áudio e selecione "
            f"“{selected_audio['label']}”. Confirme o idioma antes de começar."
        ),
        "url": candidate["url"],
        "segments": segments,
        "useful_seconds": useful_seconds,
        "fixture": fixture,
    }


def _route(
    unit: dict[str, Any],
    unit_result: dict[str, Any],
    results: dict[str, dict[str, Any]],
    candidates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    accepted_classification = unit_result["classification"] in APPROVED_CLASSIFICATIONS
    coverage_mode = unit_result.get("coverage_mode", "NONE")
    route_policy = unit.get("route_policy", "REQUIRED")
    candidate_id = unit_result.get("selected_candidate_id")
    result = results.get(candidate_id) if candidate_id else None
    candidate = candidates.get(candidate_id) if candidate_id else None
    evidence_available = bool(unit_result["eligible_for_course"])
    real_release = evidence_available and route_policy == "REQUIRED"
    fixture_demo = bool(
        coverage_mode == "SINGLE"
        and
        accepted_classification
        and unit_result.get("fixture")
        and result
        and result.get("audio_access", {}).get("target_audio_verified")
        and candidate
    )
    candidate_videos: list[dict[str, Any]] = []
    if result and candidate and (evidence_available or fixture_demo):
        selected_audio = result.get("audio_access", {}).get("selected_audio")
        if selected_audio:
            candidate_videos.append(
                _video_entry(
                    candidate,
                    intervals=result["useful_intervals"],
                    useful_seconds=result["useful_seconds"],
                    selected_audio=selected_audio,
                    covered_step_ids=result["covered_step_ids"],
                    fixture=fixture_demo,
                )
            )
    elif evidence_available and coverage_mode == "COMPOSITE":
        for component in unit_result.get("selected_components", []):
            component_candidate = candidates[component["candidate_id"]]
            candidate_videos.append(
                _video_entry(
                    component_candidate,
                    intervals=component["useful_intervals"],
                    useful_seconds=component["useful_seconds"],
                    selected_audio=component["selected_audio"],
                    covered_step_ids=component["covered_step_ids"],
                    fixture=False,
                )
            )
    if evidence_available and not candidate_videos:
        raise ValueError("rota marcada como liberada sem componentes audiovisuais")
    videos = candidate_videos if real_release or fixture_demo else []
    optional_videos = (
        candidate_videos
        if evidence_available and route_policy in {"OPTIONAL", "CONTROL_NO_AUTOMATIC"}
        else []
    )
    video = videos[0] if len(videos) == 1 else None
    gap_reasons: list[str] = []
    if route_policy == "REQUIRED" and not real_release:
        if fixture_demo:
            gap_reasons.append("Fixture demonstra o fluxo, mas não é evidência real.")
        elif result:
            gap_reasons.extend(
                _human_gate(value) for value in result.get("failed_gates", [])
            )
            gap_reasons.extend(result.get("decision_reasons", []))
            if result.get("missing_step_ids"):
                gap_reasons.append(
                    "passos ausentes: " + ", ".join(result["missing_step_ids"])
                )
        else:
            gap_reasons.append("nenhum candidato encontrado")
    gap_reasons = list(dict.fromkeys(gap_reasons))
    optional_advanced = None
    if (
        result
        and candidate
        and result.get("raw_match_observation") == "EQUIVALENT"
        and result.get("missing_prerequisites")
    ):
        optional_advanced = {
            "student_opt_in_required": True,
            "candidate_id": candidate["candidate_id"],
            "title": candidate["title"],
            "url": candidate["url"],
            "missing_prerequisites": result["missing_prerequisites"],
            "counts_as_coverage": False,
        }
    if result:
        route_audio_access = result.get("audio_access")
    elif candidate_videos:
        selected_audios = [row["audio"] for row in candidate_videos]
        target_statuses = {"pt": "NO_TARGET_AUDIO", "en": "NO_TARGET_AUDIO"}
        for selected in selected_audios:
            target_statuses[selected["target_language"]] = selected["status"]
        route_audio_access = {
            "target_statuses": target_statuses,
            "target_audio_verified": True,
            "selected_audio": None,
            "selected_audios": selected_audios,
            "review_failures": {},
            "subtitle_never_counts_as_dubbing": True,
        }
    else:
        route_audio_access = {
            "target_statuses": {"pt": "NAO_VERIFICAVEL", "en": "NAO_VERIFICAVEL"},
            "target_audio_verified": False,
            "selected_audio": None,
            "selected_audios": [],
            "review_failures": {},
            "subtitle_never_counts_as_dubbing": True,
        }
    return {
        "unit_id": unit["unit_id"],
        "title": unit["title"],
        "product": unit["product"],
        "profile": unit["profile"],
        "safety_overlay": unit["safety_overlay"],
        "source_ids": unit["source_ids"],
        "source_locators": unit.get("source_locators", []),
        "objective": unit["objective"],
        "prerequisites": unit.get("prerequisites", []),
        "required_steps": unit["required_steps"],
        "classification": unit_result["classification"],
        "coverage_mode": coverage_mode,
        "route_policy": route_policy,
        "counts_as_required_coverage": route_policy == "REQUIRED",
        "automatically_recommended": real_release,
        "search_state": unit_result.get("search_state", "NAO_INICIADA"),
        "audio_access": route_audio_access,
        "released": real_release,
        "fixture_demonstration": fixture_demo,
        "pretest": unit["pretest"],
        "video": video,
        "videos": videos,
        "optional_videos": optional_videos,
        "optional_available": bool(optional_videos),
        "useful_seconds": sum(row["useful_seconds"] for row in videos)
        if real_release
        else 0.0,
        "optional_useful_seconds": sum(
            row["useful_seconds"] for row in optional_videos
        ),
        "posttest": unit["posttest"],
        "retention_test": unit["retention_test"],
        "retention_window": "48–72 horas",
        "mastery_criterion": unit["mastery_criterion"],
        "gap_reasons": gap_reasons,
        "optional_advanced_route": optional_advanced,
        "learning_notice": "Assistir não comprova aprendizagem; registre a tentativa e os testes.",
    }


def _markdown(course: dict[str, Any]) -> str:
    lines = [
        f"# {course['title']}",
        "",
        f"**Estado derivado:** `{course['course_state']}`  ",
        f"**Unidades:** {course['unit_count']}  ",
        f"**Cobertura obrigatória:** {course['released_unit_count']}/{course['required_unit_count']}  ",
        f"**Rotas opcionais disponíveis:** {course['optional_available_count']}  ",
        f"**Tempo útil real:** {format_seconds(course['total_useful_seconds'])}",
        "",
        "> Um vídeo assistido não é evidência de domínio. Faça o pré-teste, use",
        "> somente o trecho indicado, execute o pós-teste e volte em 48–72 horas.",
        "",
    ]
    for index, route in enumerate(course["routes"], start=1):
        lines.extend(
            [
                f"## {index}. {route['title']}",
                "",
                f"- Produto: `{route['product']}`",
                f"- Classificação: `{route['classification']}`",
                f"- Objetivo: {route['objective']}",
            ]
        )
        if route["prerequisites"]:
            lines.append("- Pré-requisitos: " + "; ".join(route["prerequisites"]))
        if route["safety_overlay"] == "SENSIVEL":
            lines.append(
                "- Segurança: conteúdo educacional; não substitui avaliação profissional."
            )
        lines.extend(["", "### 1) Pré-teste", "", route["pretest"], ""])
        if route["videos"]:
            marker = (
                "DEMONSTRAÇÃO FIXTURE"
                if route["fixture_demonstration"]
                else "ROTA COMPOSTA LIBERADA"
                if route["coverage_mode"] == "COMPOSITE"
                else "VÍDEO LIBERADO"
            )
            lines.extend([f"### 2) {marker}", ""])
            for video_index, video in enumerate(route["videos"], start=1):
                if len(route["videos"]) > 1:
                    lines.extend([f"#### Componente {video_index}", ""])
                lines.extend(
                    [
                        f"[{video['title']}]({video['url']}) — {video['channel']}",
                        "Passos cobertos: " + ", ".join(video["covered_step_ids"]),
                        f"Faixa verificada: `{video['audio']['status']}` "
                        f"— {video['audio']['label']} (`{video['audio']['track_id']}`)",
                        video["audio_selection_instruction"],
                        "",
                    ]
                )
                for segment in video["segments"]:
                    lines.append(
                        f"- [{segment['label']}]({segment['url']}) — "
                        f"{format_seconds(segment['duration_seconds'])} úteis"
                    )
                lines.append("")
        elif route["optional_videos"]:
            label = (
                "CONTROLE DISPONÍVEL SOMENTE SOB SOLICITAÇÃO"
                if route["route_policy"] == "CONTROL_NO_AUTOMATIC"
                else "ROTA OPCIONAL — EXIGE ESCOLHA DO ALUNO"
            )
            lines.extend([f"### 2) {label}", ""])
            for video_index, video in enumerate(route["optional_videos"], start=1):
                if len(route["optional_videos"]) > 1:
                    lines.extend([f"#### Componente {video_index}", ""])
                lines.extend(
                    [
                        f"[{video['title']}]({video['url']}) — {video['channel']}",
                        "Passos cobertos: " + ", ".join(video["covered_step_ids"]),
                        f"Faixa verificada: `{video['audio']['status']}` — {video['audio']['label']}",
                        video["audio_selection_instruction"],
                        "",
                    ]
                )
                for segment in video["segments"]:
                    lines.append(
                        f"- [{segment['label']}]({segment['url']}) — "
                        f"{format_seconds(segment['duration_seconds'])} úteis"
                    )
                lines.append("")
        else:
            lines.extend(
                [
                    "### 2) Lacuna de vídeo",
                    "",
                    "Nenhum vídeo foi liberado para esta unidade.",
                    "",
                ]
            )
        if route["gap_reasons"]:
            lines.append(
                "Falhas que impediram liberação: "
                + "; ".join(route["gap_reasons"])
            )
            lines.append("")
        if route["optional_advanced_route"]:
            optional = route["optional_advanced_route"]
            lines.extend(
                [
                    "### Alternativa mais difícil (opcional; não conta como cobertura)",
                    "",
                    f"[{optional['title']}]({optional['url']})",
                    "",
                    "Pré-requisitos faltantes: "
                    + "; ".join(optional["missing_prerequisites"]),
                    "",
                ]
            )
        lines.extend(
            [
                "### 3) Pós-teste equivalente",
                "",
                route["posttest"],
                "",
                "### 4) Retenção",
                "",
                route["retention_test"],
                "",
                f"Critério: {route['mastery_criterion']}",
                "",
            ]
        )
    if course["gaps"]:
        lines.extend(["## Lacunas consolidadas", ""])
        for gap in course["gaps"]:
            lines.append(
                f"- `{gap['unit_id']}` — `{gap['classification']}` — {gap['title']}"
            )
        lines.append("")
    lines.append(
        "Este documento é gerado de evidência auditada; metadados isolados não fecham cobertura."
    )
    lines.append("")
    return "\n".join(lines)


def _html(course: dict[str, Any]) -> str:
    cards: list[str] = []
    for index, route in enumerate(course["routes"], start=1):
        video = "<p class='gap'>Nenhum vídeo liberado.</p>"
        display_videos = route["videos"] or route["optional_videos"]
        if display_videos:
            rendered: list[str] = []
            for video_index, item in enumerate(display_videos, start=1):
                links = "".join(
                    "<li><a target='_blank' rel='noopener' href='{}'>{}</a> — {}</li>".format(
                        html.escape(segment["url"], quote=True),
                        html.escape(segment["label"]),
                        html.escape(format_seconds(segment["duration_seconds"])),
                    )
                    for segment in item["segments"]
                )
                component_heading = (
                    f"<h4>Componente {video_index}</h4>"
                    if len(display_videos) > 1
                    else ""
                )
                rendered.append(
                    f"{component_heading}<p><a target='_blank' rel='noopener' href='"
                    f"{html.escape(item['url'], quote=True)}'>"
                    f"{html.escape(item['title'])}</a></p>"
                    f"<p>Passos cobertos: {html.escape(', '.join(item['covered_step_ids']))}</p>"
                    f"<p>Faixa verificada: <code>{html.escape(item['audio']['status'])}</code> "
                    f"— {html.escape(item['audio']['label'])}</p>"
                    f"<p>{html.escape(item['audio_selection_instruction'])}</p>"
                    f"<ul>{links}</ul>"
                )
            fixture = (
                "<strong>Fixture: demonstração, não cobertura real.</strong>"
                if route["fixture_demonstration"]
                else ""
            )
            optional_notice = (
                "<p class='optional'><strong>Não recomendado automaticamente; "
                "abra somente por escolha explícita.</strong></p>"
                if route["optional_videos"]
                else ""
            )
            video = fixture + optional_notice + "".join(rendered)
        gaps = ""
        if route["gap_reasons"]:
            gaps = "<p class='gap'>" + html.escape("; ".join(route["gap_reasons"])) + "</p>"
        safety = ""
        if route["safety_overlay"] == "SENSIVEL":
            safety = "<p class='safety'>Conteúdo educacional; não substitui avaliação profissional.</p>"
        cards.append(
            f"""<section>
<h2>{index}. {html.escape(route['title'])}</h2>
<p><code>{html.escape(route['classification'])}</code> · <code>{html.escape(route['product'])}</code></p>
<p>{html.escape(route['objective'])}</p>{safety}
<h3>1. Pré-teste</h3><p>{html.escape(route['pretest'])}</p>
<h3>2. Trecho útil</h3>{video}{gaps}
<h3>3. Pós-teste equivalente</h3><p>{html.escape(route['posttest'])}</p>
<h3>4. Retenção em 48–72 h</h3><p>{html.escape(route['retention_test'])}</p>
<p class='notice'>{html.escape(route['learning_notice'])}</p>
</section>"""
        )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(course['title'])}</title>
<style>
body{{font:17px/1.55 system-ui,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;background:#f7f8fb;color:#172033}}
header,section{{background:white;border:1px solid #dce1ea;border-radius:14px;padding:1.25rem;margin:1rem 0}}
h1,h2,h3{{line-height:1.2}}code{{background:#eef1f6;padding:.15rem .35rem;border-radius:4px}}
.gap{{color:#8b1e1e}}.safety{{background:#fff3cd;padding:.65rem}}.optional{{background:#eef6ff;padding:.65rem}}.notice{{color:#4a5568}}a{{color:#0757b5}}
</style></head><body>
<header><h1>{html.escape(course['title'])}</h1>
<p>Estado: <code>{html.escape(course['course_state'])}</code> · {course['released_unit_count']}/{course['required_unit_count']} unidades obrigatórias · {course['optional_available_count']} opcionais · {html.escape(format_seconds(course['total_useful_seconds']))} úteis.</p>
<p>Assistir não comprova domínio. Faça os três testes.</p></header>
{''.join(cards)}
</body></html>
"""


def render_course(course: dict[str, Any]) -> tuple[str, str]:
    return _markdown(course), _html(course)


def build_course(workspace: Path, *, write_outputs: bool = True) -> dict[str, Any]:
    manifest = read_json(workspace / "ingest" / "source_manifest.json")
    ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
    audit = derive_audit(
        workspace,
        workspace / "evidence" / "evidence_input.json",
        allow_fixtures=True,
        write_outputs=write_outputs,
    )
    candidate_doc = read_json(workspace / "ledgers" / "candidates.json")
    candidates = {row["candidate_id"]: row for row in candidate_doc["candidates"]}
    results_by_unit: dict[str, dict[str, dict[str, Any]]] = {}
    for row in audit["candidate_results"]:
        results_by_unit.setdefault(row["unit_id"], {})[row["candidate_id"]] = row
    unit_results = {row["unit_id"]: row for row in audit["unit_results"]}
    routes: list[dict[str, Any]] = []
    for unit in ledger["units"]:
        unit_result = unit_results[unit["unit_id"]]
        routes.append(
            _route(
                unit,
                unit_result,
                results_by_unit.get(unit["unit_id"], {}),
                candidates,
            )
        )
    released = [route for route in routes if route["released"]]
    required_routes = [
        route for route in routes if route["counts_as_required_coverage"]
    ]
    fixture_routes = [route for route in routes if route["fixture_demonstration"]]
    optional_available = [route for route in routes if route["optional_available"]]
    total_useful = sum(route["useful_seconds"] for route in released)
    if len(released) == len(required_routes):
        state = "COBERTA"
    elif fixture_routes and len(fixture_routes) == len(required_routes):
        state = "DEMONSTRACAO_FIXTURE"
    else:
        state = "PARCIAL"
    gaps = [
        {
            "unit_id": route["unit_id"],
            "title": route["title"],
            "classification": route["classification"],
            "reasons": route["gap_reasons"],
        }
        for route in routes
        if route["counts_as_required_coverage"] and not route["released"]
    ]
    counts = Counter(route["classification"] for route in routes)
    course = {
        "schema_name": "projeto-e-video.course",
        "schema_version": 3,
        "created_at": now_iso(),
        "course_id": ledger["course_id"],
        "title": ledger["title"],
        "course_state": state,
        "promotion_ready": False,
        "source_manifest_sha256": sha256_file(
            workspace / "ingest" / "source_manifest.json"
        ),
        "audit_input_hashes": audit["input_hashes"],
        "unit_count": len(routes),
        "required_unit_count": len(required_routes),
        "released_unit_count": len(released),
        "optional_available_count": len(optional_available),
        "fixture_unit_count": len(fixture_routes),
        "total_useful_seconds": total_useful,
        "classification_counts": dict(sorted(counts.items())),
        "source_count": manifest["source_count"],
        "routes": routes,
        "gaps": gaps,
        "learning_claim": "Nenhum domínio é inferido de visualização; testes do aluno são obrigatórios.",
    }
    if write_outputs:
        target = workspace / "course"
        markdown, html_document = render_course(course)
        atomic_write_json(target / "course.json", course)
        atomic_write_text(target / "COURSE.md", markdown)
        atomic_write_text(target / "index.html", html_document)
    return course
