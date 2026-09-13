"""Interface de linha de comando do pacote."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .audio import import_audio_inventory, inspect_candidate_audio
from .audit import audit
from .collect import collect_evidence_assets
from .course import build_course
from .external import preflight_report
from .ingest import ingest
from .planning import create_plan, import_map
from .prompts import write_all_prompts
from .providers import import_candidates, manual_search, yt_dlp_search
from .release import package_release, validate_release, validate_zip
from .util import atomic_write_json, atomic_write_text, ensure_external_workspace, sha256_file
from .validation import validate_workspace


def _workspace(value: str) -> Path:
    return ensure_external_workspace(Path(value))


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _doctor(args: argparse.Namespace) -> dict[str, object]:
    del args
    return preflight_report()


def _compact_search_output(
    workspace: Path, report: dict[str, object]
) -> dict[str, object]:
    """Mantém o relatório completo em disco sem despejar centenas de IDs no terminal."""

    compact = dict(report)
    for field in ("pending_ready_query_ids", "pending_localization_query_ids"):
        values = compact.pop(field, [])
        if isinstance(values, list):
            compact[f"{field}_preview"] = values[:20]
            compact[f"{field}_preview_truncated"] = len(values) > 20
    compact["full_report"] = str(
        (workspace / "ledgers" / "search_report.json").resolve()
    )
    return compact


def _create(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    if any(workspace.iterdir()):
        raise ValueError("workspace de criação deve estar vazio")

    # ``create`` é uma transação única: ingestão, mapa V0 e prompts aparecem
    # juntos ou não aparecem. Isso evita workspaces sem manifesto ou sem mapa
    # depois de limite de arquivo, falha de extrator ou erro de planejamento.
    with tempfile.TemporaryDirectory(
        prefix=f".{workspace.name}.create-", dir=str(workspace.parent)
    ) as temporary_name:
        staging = Path(temporary_name)
        manifest = ingest(
            args.input,
            staging,
            title=args.title,
            allow_network=args.allow_network,
            extra_inputs=args.source,
            ocr_scanned_pdf=args.ocr_scanned_pdf,
        )
        ledger = create_plan(staging)
        staged_prompts = write_all_prompts(staging)
        prompt_relatives = [path.relative_to(staging) for path in staged_prompts]

        # O alvo foi criado por ``ensure_external_workspace`` e continua vazio.
        # A troca ocorre no mesmo sistema de arquivos, depois de todo o fluxo
        # ter passado, para não publicar estado parcial.
        workspace.rmdir()
        try:
            os.replace(staging, workspace)
        except Exception:
            workspace.mkdir(parents=True, exist_ok=True)
            raise

    prompts = [workspace / relative for relative in prompt_relatives]
    return {
        "workspace": str(workspace),
        "course_id": manifest["course_id"],
        "source_count": manifest["source_count"],
        "unit_count": len(ledger["units"]),
        "map_state": ledger["map_state"],
        "prompts": [str(path) for path in prompts],
        "next": "Conferir prompts/01_REFINAR_MAPA.md e executar import-map.",
    }


def _import_map(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    ledger = import_map(workspace, Path(args.file).expanduser().resolve())
    write_all_prompts(workspace)
    return {
        "workspace": str(workspace),
        "unit_count": len(ledger["units"]),
        "map_state": ledger["map_state"],
        "next": "Executar search; busca não aprova vídeos.",
    }


def _search(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    if args.provider == "manual":
        report = manual_search(
            workspace,
            unit_ids=args.unit_id,
            include_optional=args.include_optional,
            include_control=args.include_control,
        )
    else:
        report = yt_dlp_search(
            workspace,
            limit=args.limit,
            max_queries=args.max_queries,
            timeout_seconds=args.timeout,
            retry_failed=args.retry_failed,
            languages=args.language,
            unit_ids=args.unit_id,
            search_stages=args.stage,
            include_optional=args.include_optional,
            include_control=args.include_control,
        )
    return _compact_search_output(workspace, report)


def _import_candidates(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    document = import_candidates(workspace, Path(args.file).expanduser().resolve())
    return {
        "workspace": str(workspace),
        "candidate_count": document["candidate_count"],
        "next": "Inventariar áudio com prompts/03_INVENTARIAR_AUDIO.md e auditar com prompts/04_AUDITAR_VIDEOS.md.",
    }


def _collect(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    return collect_evidence_assets(
        workspace,
        args.candidate_id,
        frame_times=args.frame_at,
        audio_track_id=args.audio_track,
        audio_segments=args.audio_segment,
        subtitle_languages=args.subtitle_language,
        include_automatic_subtitles=args.automatic_subtitles,
        max_video_mb=args.max_video_mb,
        timeout_seconds=args.timeout,
    )


def _inspect_audio(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    return inspect_candidate_audio(
        workspace, args.candidate_id, timeout_seconds=args.timeout
    )


def _import_audio(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    document = import_audio_inventory(
        workspace, Path(args.file).expanduser().resolve()
    )
    return {
        "workspace": str(workspace),
        "audio_inventory_record_count": len(document["records"]),
        "next": "Ouça as faixas PT/EN e registre audio_reviews na evidência.",
    }


def _audio_segment(value: str) -> tuple[float, float]:
    try:
        start_text, end_text = value.split(":", 1)
        start = float(start_text)
        end = float(end_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("use START:END em segundos") from exc
    if start < 0 or end <= start:
        raise argparse.ArgumentTypeError("audio-segment exige 0 <= START < END")
    return start, end


def _audit(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    result = audit(workspace, Path(args.evidence).expanduser().resolve())
    return {
        "workspace": str(workspace),
        "map_verified": result["map_verified"],
        "classification_counts": result["classification_counts"],
        "next": "Executar build; lacunas permanecem explícitas.",
    }


def _build(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    course = build_course(workspace)
    return {
        "workspace": str(workspace),
        "course_state": course["course_state"],
        "unit_count": course["unit_count"],
        "released_unit_count": course["released_unit_count"],
        "total_useful_seconds": course["total_useful_seconds"],
        "course_markdown": str(workspace / "course" / "COURSE.md"),
        "course_html": str(workspace / "course" / "index.html"),
    }


def _validate_workspace(args: argparse.Namespace) -> dict[str, object]:
    return validate_workspace(_workspace(args.workspace))


def _validate_release(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.path).expanduser().resolve()
    report: dict[str, object] = {
        "release": validate_release(root, require_origin=args.require_origin)
    }
    if args.zip:
        report["zip"] = validate_zip(Path(args.zip).expanduser().resolve(), root.name)
    return report


def _package(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.path).expanduser().resolve()
    zip_path = (
        Path(args.zip).expanduser().resolve()
        if args.zip
        else root.parent / f"{root.name}.zip"
    )
    return package_release(
        root,
        zip_path,
        overwrite=args.overwrite,
        require_origin=args.require_origin,
    )


def _demo(args: argparse.Namespace) -> dict[str, object]:
    workspace = _workspace(args.workspace)
    if any(workspace.iterdir()):
        raise ValueError("workspace da demonstração deve estar vazio")
    source = workspace / "DEMO_FONTE.md"
    atomic_write_text(
        source,
        """# Soma dos primeiros números ímpares

Exercício: prove que a soma dos primeiros n números ímpares é n². Identifique
o padrão, justifique a indução, execute o passo indutivo e confira um caso.
""",
    )
    ingest(str(source), workspace, title="Demonstração — Curso auditável")
    ledger = create_plan(workspace)
    refined = json.loads(json.dumps(ledger))
    for unit in refined["units"]:
        unit["verification_state"] = "VERIFIED_BY_HUMAN"
    map_file = workspace / "DEMO_MAP.json"
    atomic_write_json(map_file, refined)
    ledger = import_map(workspace, map_file)
    write_all_prompts(workspace)

    candidate_raw = {
        "schema_name": "projeto-e-video.candidates",
        "schema_version": 2,
        "search_scope": "VERIFIED_CHANNEL_ALLOWLIST",
        "search_attempts": [],
        "candidates": [
            {
                "unit_ids": [unit["unit_id"] for unit in ledger["units"]],
                "url": "https://www.youtube.com/watch?v=nEMC80cWYtE",
                "title": "Vídeo fictício para testar a infraestrutura",
                "channel": "Brasil Escola Oficial",
                "language": "pt",
                "language_basis": "MANUAL_OBSERVATION",
                "discovery_languages": ["pt"],
                "duration_seconds": 180,
                "provider": "fixture",
                "metadata_observed": ["TITLE", "CHANNEL", "DURATION"],
                "fixture": True,
            }
        ],
    }
    candidate_file = workspace / "DEMO_CANDIDATES.json"
    atomic_write_json(candidate_file, candidate_raw)
    candidate_doc = import_candidates(
        workspace, candidate_file, allow_fixtures=True
    )
    candidate = candidate_doc["candidates"][0]

    audio_inventory_file = workspace / "DEMO_AUDIO_INVENTORY.json"
    atomic_write_json(
        audio_inventory_file,
        {
            "schema_name": "projeto-e-video.audio-inventory",
            "schema_version": 1,
            "records": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_url": candidate["url"],
                    "provider": "fixture",
                    "inspected_at": "fixture",
                    "tracks": [
                        {
                            "language": "pt-BR",
                            "label": "áudio original fixture",
                            "audio_kind_hint": "ORIGINAL",
                            "metadata_basis": ["FIXTURE"],
                            "is_default": True,
                            "formats": [],
                        }
                    ],
                    "subtitles": [],
                    "warnings": [],
                }
            ],
        },
    )
    audio_inventory = import_audio_inventory(workspace, audio_inventory_file)
    audio_track = audio_inventory["records"][0]["tracks"][0]

    demo_assets = workspace / "evidence" / "assets" / candidate["candidate_id"]
    transcript_path = demo_assets / "demo_transcript.txt"
    frame_path = demo_assets / "demo_frame.svg"
    audio_path = demo_assets / f"demo_audio_{audio_track['track_id']}.txt"
    atomic_write_text(
        transcript_path,
        "Fixture: o professor identifica o padrão, apresenta a base, executa o "
        "passo indutivo e confere o resultado. Não representa vídeo real.\n",
    )
    atomic_write_text(
        frame_path,
        f"""<svg xmlns={chr(34)}{"http" + "://www.w3.org/2000/svg"}{chr(34)} width={chr(34)}640{chr(34)} height={chr(34)}360{chr(34)}>
<rect width="100%" height="100%" fill="#fff"/><text x="30" y="90" font-size="28">FRAME FIXTURE</text>
<text x="30" y="150" font-size="22">1 + 3 + ... + (2n-1) = n²</text></svg>
""",
    )
    atomic_write_text(
        audio_path,
        "Fixture textual marcada como AUDIO apenas para exercitar o gate estrutural.\n",
    )
    artifacts = [
        {
            "artifact_id": "ART-TRANSCRIPT-DEMO",
            "path": transcript_path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(transcript_path),
            "kind": "TRANSCRIPT",
        },
        {
            "artifact_id": "ART-FRAME-DEMO",
            "path": frame_path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(frame_path),
            "kind": "FRAME",
        },
        {
            "artifact_id": "ART-AUDIO-DEMO",
            "path": audio_path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(audio_path),
            "kind": "AUDIO",
        },
    ]
    observations = []
    for unit in ledger["units"]:
        observations.append(
            {
                "candidate_id": candidate["candidate_id"],
                "unit_id": unit["unit_id"],
                "candidate_identity_confirmed": True,
                "inspection_methods": ["TRANSCRICAO", "FRAME"],
                "match_observation": "EXACT",
                "artifacts": artifacts,
                "transcript": {
                    "available": True,
                    "artifact_id": "ART-TRANSCRIPT-DEMO",
                    "language": "pt",
                },
                "timestamps": [
                    {
                        "start_seconds": 10,
                        "end_seconds": 120,
                        "observed_step_ids": [
                            step["step_id"] for step in unit["required_steps"]
                        ],
                        "observed": "A fixture declara e ilustra todos os passos requeridos apenas para testar o gate.",
                        "speech_or_transcript_observed": "A fala fixture identifica, executa e confere todos os passos requeridos.",
                        "artifact_ids": [
                            "ART-TRANSCRIPT-DEMO",
                            "ART-FRAME-DEMO",
                            "ART-AUDIO-DEMO",
                        ],
                    }
                ],
                "speech_observed": "O professor enuncia e executa os passos da demonstração fixture.",
                "equivalence_rationale": "",
                "missing_prerequisites": [],
                "audio_reviews": [
                    {
                        "track_id": audio_track["track_id"],
                        "target_language": "pt",
                        "access_type_observed": "ORIGINAL",
                        "verification_method": "AUDIO_ARTIFACT",
                        "audio_artifact_ids": ["ART-AUDIO-DEMO"],
                        "track_selection_artifact_id": None,
                        "direct_playback_observed": False,
                        "technical_terminology_checked": True,
                        "mathematical_notation_checked": True,
                        "semantic_alignment_checked": True,
                        "synchronization_checked": True,
                        "issues": [],
                        "reviewer_notes": "Fixture estrutural para validar todos os campos de áudio.",
                    }
                ],
                "reviewer_notes": "Fixture estrutural; não é evidência de vídeo nem de aprendizagem.",
                "fixture": True,
            }
        )
    evidence_file = workspace / "DEMO_EVIDENCE.json"
    atomic_write_json(
        evidence_file,
        {
            "schema_name": "projeto-e-video.evidence-input",
            "schema_version": 2,
            "observations": observations,
        },
    )
    audit(workspace, evidence_file, allow_fixtures=True)
    course = build_course(workspace)
    validation = validate_workspace(workspace)
    return {
        "workspace": str(workspace),
        "course_state": course["course_state"],
        "fixture": True,
        "validation": validation,
        "course_markdown": str(workspace / "course" / "COURSE.md"),
        "course_html": str(workspace / "course" / "index.html"),
        "notice": "A demonstração valida infraestrutura, não vídeos reais nem eficácia.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="projeto-e-video",
        description="Transforma fontes educacionais em cursos por vídeos auditáveis.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser(
        "doctor", help="verificar ferramentas e fallbacks sem rede nem API key"
    )
    doctor.set_defaults(handler=_doctor)

    create = sub.add_parser("create", help="ingerir entrada e criar mapa V0")
    create.add_argument("--input", required=True)
    create.add_argument(
        "--source",
        action="append",
        default=[],
        help="fonte adicional; repita para arquivos/URLs/tópicos não contíguos",
    )
    create.add_argument("--workspace", required=True)
    create.add_argument("--title")
    create.add_argument("--allow-network", action="store_true")
    create.add_argument(
        "--ocr-scanned-pdf",
        action="store_true",
        help=(
            "tentar OCR página a página em PDF sem camada textual; exige "
            "pdfinfo, pdftoppm e tesseract e pode ser demorado"
        ),
    )
    create.set_defaults(handler=_create)

    map_command = sub.add_parser("import-map", help="importar mapa V1 conferido")
    map_command.add_argument("--workspace", required=True)
    map_command.add_argument("--file", required=True)
    map_command.set_defaults(handler=_import_map)

    search = sub.add_parser("search", help="localizar candidatos sem aprová-los")
    search.add_argument("--workspace", required=True)
    search.add_argument("--provider", choices=("manual", "yt-dlp"), default="manual")
    search.add_argument("--limit", type=int, default=3)
    search.add_argument("--max-queries", type=int, default=120)
    search.add_argument("--timeout", type=int, default=90)
    search.add_argument(
        "--language",
        action="append",
        default=[],
        help="restringir esta rodada a uma tag BCP-47; repita quando necessário",
    )
    search.add_argument(
        "--unit-id",
        action="append",
        default=[],
        help="restringir esta rodada a uma unidade; todas as demais ficam pendentes",
    )
    search.add_argument(
        "--include-optional",
        action="store_true",
        help="opt-in explícito para todas as unidades OPTIONAL",
    )
    search.add_argument(
        "--include-control",
        action="store_true",
        help="opt-in explícito para unidades CONTROL_NO_AUTOMATIC",
    )
    search.add_argument(
        "--stage",
        action="append",
        default=[],
        choices=("EXACT_OBJECT", "RIGOROUS_EQUIVALENT"),
        help="restringir a fase nesta rodada sem apagar as demais",
    )
    search.add_argument(
        "--retry-failed",
        action="store_true",
        help="retentar somente consultas que falharam, preservando o restante",
    )
    search.set_defaults(handler=_search)

    candidates = sub.add_parser("import-candidates", help="importar candidatos canônicos")
    candidates.add_argument("--workspace", required=True)
    candidates.add_argument("--file", required=True)
    candidates.set_defaults(handler=_import_candidates)

    collect = sub.add_parser(
        "collect", help="coletar legendas, frames e áudio sem API key"
    )
    collect.add_argument("--workspace", required=True)
    collect.add_argument("--candidate-id", required=True)
    collect.add_argument("--frame-at", action="append", type=float, default=[])
    collect.add_argument("--audio-track")
    collect.add_argument(
        "--audio-segment", action="append", type=_audio_segment, default=[]
    )
    collect.add_argument(
        "--subtitle-language",
        action="append",
        default=[],
        help="tag BCP-47 exata; repita para cada legenda realmente necessária",
    )
    collect.add_argument(
        "--automatic-subtitles",
        action="store_true",
        help="admitir legendas automáticas para transcrição, nunca como dublagem",
    )
    collect.add_argument("--max-video-mb", type=int, default=250)
    collect.add_argument("--timeout", type=int, default=900)
    collect.set_defaults(handler=_collect)

    inspect_audio = sub.add_parser(
        "inspect-audio", help="inventariar faixas e legendas sem aprová-las"
    )
    inspect_audio.add_argument("--workspace", required=True)
    inspect_audio.add_argument("--candidate-id", required=True)
    inspect_audio.add_argument("--timeout", type=int, default=120)
    inspect_audio.set_defaults(handler=_inspect_audio)

    import_audio = sub.add_parser(
        "import-audio-inventory", help="importar inventário observado no navegador"
    )
    import_audio.add_argument("--workspace", required=True)
    import_audio.add_argument("--file", required=True)
    import_audio.set_defaults(handler=_import_audio)

    audit_command = sub.add_parser("audit", help="derivar cobertura de evidência bruta")
    audit_command.add_argument("--workspace", required=True)
    audit_command.add_argument("--evidence", required=True)
    audit_command.set_defaults(handler=_audit)

    build = sub.add_parser("build", help="renderizar curso e lacunas")
    build.add_argument("--workspace", required=True)
    build.set_defaults(handler=_build)

    validate = sub.add_parser("validate-workspace", help="validar um curso gerado")
    validate.add_argument("--workspace", required=True)
    validate.set_defaults(handler=_validate_workspace)

    demo = sub.add_parser("demo", help="executar fixture ponta a ponta")
    demo.add_argument("--workspace", required=True)
    demo.set_defaults(handler=_demo)

    release = sub.add_parser("validate-release", help="validar pasta e ZIP de release")
    release.add_argument("path")
    release.add_argument("--zip")
    release.add_argument("--require-origin", action="store_true")
    release.set_defaults(handler=_validate_release)

    package = sub.add_parser("package-release", help="gerar manifesto e ZIP isolado")
    package.add_argument("path")
    package.add_argument("--zip")
    package.add_argument("--overwrite", action="store_true")
    package.add_argument("--require-origin", action="store_true")
    package.set_defaults(handler=_package)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (ValueError, OSError, TimeoutError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    _print(result)
    return 0
