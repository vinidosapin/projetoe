"""Coleta opcional, sem API key, de legendas, frames e áudio para inspeção."""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .audio import inventory_indexes, validate_audio_inventory
from .external import run_command, yt_dlp_command
from .network import validate_automated_video_url
from .languages import normalize_language_tag
from .util import (
    atomic_write_json,
    atomic_write_text,
    now_iso,
    read_json,
    sha256_file,
)


# Prefira um fluxo HTTP progressivo. No YouTube, ``worstvideo`` pode escolher
# primeiro um manifesto HLS; em alguns vídeos, o recorte por tempo desse fluxo
# termina como um MP4 válido porém sem frames. O fallback HLS continua disponível
# para provedores que não exponham formato progressivo.
FRAME_FORMAT_SELECTOR = (
    "worstvideo[height<=480][protocol=https]/"
    "worstvideo[protocol=https]/"
    "worstvideo[height<=480]/worstvideo/"
    "bestvideo[height<=480][protocol=https]/"
    "bestvideo[protocol=https]/"
    "bestvideo[height<=480]/bestvideo"
)


def _candidate(workspace: Path, candidate_id: str) -> dict[str, Any]:
    document = read_json(workspace / "ledgers" / "candidates.json")
    matches = [row for row in document["candidates"] if row["candidate_id"] == candidate_id]
    if not matches:
        raise ValueError(f"candidato não encontrado: {candidate_id}")
    return matches[0]


def _run(command: list[str], *, timeout: int) -> tuple[bool, str]:
    result = run_command(command, timeout_seconds=timeout)
    detail = (
        result.stderr.decode("utf-8", errors="replace").strip()
        or result.stdout.decode("utf-8", errors="replace").strip()
    )
    return result.returncode == 0, detail[-2000:]


def collect_evidence_assets(
    workspace: Path,
    candidate_id: str,
    *,
    frame_times: list[float] | None = None,
    audio_track_id: str | None = None,
    audio_segments: list[tuple[float, float]] | None = None,
    subtitle_languages: list[str] | None = None,
    include_automatic_subtitles: bool = False,
    max_video_mb: int = 250,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Coleta artefatos; não interpreta o conteúdo nem produz classificação."""

    if not 1 <= max_video_mb <= 1000:
        raise ValueError("max_video_mb deve ficar entre 1 e 1000")
    if not 1 <= timeout_seconds <= 3600:
        raise ValueError("timeout_seconds deve ficar entre 1 e 3600")
    times = sorted(set(float(value) for value in (frame_times or [])))
    if any(not math.isfinite(value) or value < 0 or value > 24 * 3600 for value in times):
        raise ValueError("frame-at deve ficar entre 0 e 86400 segundos")
    if len(times) > 100:
        raise ValueError("no máximo 100 frames por execução")
    segments = sorted(set((float(start), float(end)) for start, end in (audio_segments or [])))
    if len(segments) > 20:
        raise ValueError("no máximo 20 segmentos de áudio por execução")
    if any(
        not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end <= start
        or end > 24 * 3600
        or end - start > 10 * 60
        for start, end in segments
    ):
        raise ValueError("segmentos de áudio devem estar entre 0 e 24h e durar até 10min")
    if sum(end - start for start, end in segments) > 30 * 60:
        raise ValueError("segmentos de áudio excedem 30 minutos no total")
    if bool(audio_track_id) != bool(segments):
        raise ValueError("audio-track e audio-segment devem ser usados juntos")
    subtitle_languages = sorted(
        {
            normalize_language_tag(value)
            for value in (subtitle_languages or [])
        }
    )
    if "und" in subtitle_languages:
        raise ValueError("subtitle-language exige idioma BCP-47 conhecido")
    if len(subtitle_languages) > 10:
        raise ValueError("no máximo 10 idiomas de legenda por execução")
    if not times and not segments and not subtitle_languages:
        raise ValueError(
            "solicite ao menos frame-at, audio-segment ou subtitle-language"
        )
    yt_dlp = yt_dlp_command()
    if yt_dlp is None:
        raise ValueError("yt-dlp não encontrado")
    candidate = _candidate(workspace, candidate_id)
    validate_automated_video_url(candidate["url"])
    target = workspace / "evidence" / "assets" / candidate_id
    target.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    selected_audio: dict[str, Any] | None = None
    selected_format: dict[str, Any] | None = None

    # Valide toda a seleção antes da primeira chamada de rede. Assim, uma faixa
    # adulterada ou pertencente a outro vídeo não dispara nem a coleta de legendas.
    if audio_track_id and segments:
        inventory_path = workspace / "ledgers" / "audio_inventory.json"
        if not inventory_path.is_file():
            raise ValueError("inventário de áudio ausente; execute inspect-audio")
        candidate_doc = read_json(workspace / "ledgers" / "candidates.json")
        normalized_inventory = validate_audio_inventory(
            read_json(inventory_path), candidate_doc
        )
        records, tracks = inventory_indexes(normalized_inventory)
        selected_audio = tracks.get(audio_track_id)
        if selected_audio is None:
            raise ValueError(f"faixa de áudio desconhecida: {audio_track_id}")
        candidate_track_ids = {
            row["track_id"]
            for row in records.get(candidate_id, {}).get("tracks", [])
        }
        if audio_track_id not in candidate_track_ids:
            raise ValueError("faixa de áudio não pertence ao candidato solicitado")
        formats = selected_audio.get("formats", [])
        if not formats:
            raise ValueError("faixa não possui format_id coletável; use inspeção direta")
        selected_format = min(
            formats,
            key=lambda row: (
                0 if row.get("audio_only") else 1,
                abs(float(row.get("abr") or 128) - 128),
                row["format_id"],
            ),
        )

    operation_status: dict[str, dict[str, Any]] = {
        "subtitles": {"requested": bool(subtitle_languages), "succeeded": 0},
        "frames": {"requested": len(times), "succeeded": 0},
        "audio": {"requested": len(segments), "succeeded": 0},
    }
    if subtitle_languages:
        subtitle_template = str(target / "subtitle.%(language)s.%(ext)s")
        subtitle_command = yt_dlp + [
            "--skip-download",
            "--no-playlist",
            "--write-subs",
        ]
        if include_automatic_subtitles:
            subtitle_command.append("--write-auto-subs")
        subtitle_command.extend(
            [
                "--sub-langs",
                ",".join(subtitle_languages),
                "--sub-format",
                "vtt",
                "-o",
                subtitle_template,
                candidate["url"],
            ]
        )
        ok, detail = _run(subtitle_command, timeout=timeout_seconds)
        after = set(target.glob("subtitle.*"))
        operation_status["subtitles"]["succeeded"] = len(after)
        if not ok:
            warnings.append("legendas: " + detail)
        elif not after:
            warnings.append("legendas: comando concluiu sem produzir arquivo VTT")

    frame_paths: list[Path] = []
    if times:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            warnings.append("frames: ffmpeg não encontrado")
        else:
            with tempfile.TemporaryDirectory(
                prefix=f"{candidate_id}-", dir=str(workspace / "evidence")
            ) as temp_name:
                temp_dir = Path(temp_name)
                for seconds in times:
                    millis = int(round(seconds * 1000))
                    section_start = max(0.0, seconds - 3.0)
                    section_end = seconds + 3.0
                    video_template = str(
                        temp_dir / f"frame_source_{millis:09d}.%(ext)s"
                    )
                    downloaded, download_detail = _run(
                        yt_dlp
                        + [
                            "--no-playlist",
                            "--download-sections",
                            f"*{section_start:.3f}-{section_end:.3f}",
                            "--force-keyframes-at-cuts",
                            "--max-filesize",
                            f"{max_video_mb}M",
                            "-f",
                            FRAME_FORMAT_SELECTOR,
                            "-o",
                            video_template,
                            candidate["url"],
                        ],
                        timeout=timeout_seconds,
                    )
                    videos = sorted(
                        temp_dir.glob(f"frame_source_{millis:09d}.*")
                    )
                    if not downloaded or not videos:
                        warnings.append(
                            f"trecho para frame {seconds:.3f}s: {download_detail}"
                        )
                        continue
                    video = max(videos, key=lambda path: path.stat().st_size)
                    frame = target / f"frame_{millis:09d}ms.jpg"
                    extracted, frame_detail = _run(
                        [
                            ffmpeg,
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-ss",
                            f"{seconds - section_start:.3f}",
                            "-i",
                            str(video),
                            "-frames:v",
                            "1",
                            "-q:v",
                            "2",
                            "-y",
                            str(frame),
                        ],
                        timeout=120,
                    )
                    if extracted and frame.exists():
                        frame_paths.append(frame)
                    else:
                        warnings.append(f"frame {seconds:.3f}s: {frame_detail}")

    audio_paths: list[Path] = []
    if audio_track_id and segments:
        if selected_format is None:
            raise ValueError("seleção de formato de áudio não foi validada")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            warnings.append("áudio: ffmpeg não encontrado")
        else:
            with tempfile.TemporaryDirectory(
                prefix=f"{candidate_id}-audio-", dir=str(workspace / "evidence")
            ) as temp_name:
                temp_dir = Path(temp_name)
                for start, end in segments:
                    start_ms = int(round(start * 1000))
                    end_ms = int(round(end * 1000))
                    audio_template = str(
                        temp_dir
                        / f"source_{start_ms:09d}_{end_ms:09d}.%(ext)s"
                    )
                    downloaded, download_detail = _run(
                        yt_dlp
                        + [
                            "--no-playlist",
                            "--download-sections",
                            f"*{start:.3f}-{end:.3f}",
                            "--max-filesize",
                            f"{max_video_mb}M",
                            "-f",
                            selected_format["format_id"],
                            "-o",
                            audio_template,
                            candidate["url"],
                        ],
                        timeout=timeout_seconds,
                    )
                    source_files = sorted(
                        temp_dir.glob(
                            f"source_{start_ms:09d}_{end_ms:09d}.*"
                        )
                    )
                    if not downloaded or not source_files:
                        warnings.append(
                            f"faixa {start:.3f}–{end:.3f}s: {download_detail}"
                        )
                        continue
                    source_audio = max(
                        source_files, key=lambda path: path.stat().st_size
                    )
                    audio_path = target / (
                        f"audio_{audio_track_id}_{start_ms:09d}_{end_ms:09d}.wav"
                    )
                    extracted, audio_detail = _run(
                        [
                            ffmpeg,
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-ss",
                            "0.000",
                            "-t",
                            f"{end - start:.3f}",
                            "-i",
                            str(source_audio),
                            "-vn",
                            "-ac",
                            "1",
                            "-ar",
                            "16000",
                            "-c:a",
                            "pcm_s16le",
                            "-y",
                            str(audio_path),
                        ],
                        timeout=180,
                    )
                    if extracted and audio_path.is_file():
                        audio_paths.append(audio_path)
                    else:
                        warnings.append(
                            f"áudio {start:.3f}–{end:.3f}s: {audio_detail}"
                        )
    operation_status["frames"]["succeeded"] = len(frame_paths)
    operation_status["audio"]["succeeded"] = len(audio_paths)

    review_path = target / "REVIEW_CHECKLIST.md"
    atomic_write_text(
        review_path,
        "\n".join(
            [
                "# Revisão audiovisual obrigatória",
                "",
                f"- Candidato: `{candidate_id}`",
                f"- URL canônica: {candidate['url']}",
                f"- Faixa solicitada: `{audio_track_id or 'nenhuma'}`",
                "",
                "Ouça cada amostra ou o mesmo trecho no player. Para cada passo,",
                "registre a fala realmente ouvida, confira terminologia, notação,",
                "alinhamento semântico e sincronização. Veja também o frame do mesmo",
                "intervalo. Metadados, legenda e transcrição automática isolados não",
                "comprovam a faixa nem liberam o vídeo.",
                "",
                "Se este runtime não reproduz áudio, entregue este pacote a uma pessoa",
                "ou agente com reprodução real e mantenha audio_reviews vazio até a",
                "escuta ocorrer.",
                "",
            ]
        ),
    )

    artifact_paths = sorted(
        {
            path
            for path in target.iterdir()
            if path.is_file()
            and path.name not in {"collection_manifest.json", "REVIEW_CHECKLIST.md"}
        },
        key=lambda path: path.name,
    )
    artifacts = []
    for path in artifact_paths:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            kind = "FRAME"
        elif suffix in {".wav", ".mp3", ".m4a", ".opus", ".ogg", ".aac"}:
            kind = "AUDIO"
        elif suffix in {".vtt", ".srt", ".txt"}:
            kind = "TRANSCRIPT"
        else:
            kind = "OTHER"
        artifacts.append(
            {
                "path": path.relative_to(workspace).as_posix(),
                "kind": kind,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schema_name": "projeto-e-video.collection-manifest",
        "schema_version": 2,
        "created_at": now_iso(),
        "candidate_id": candidate_id,
        "candidate_url": candidate["url"],
        "requested_frame_times": times,
        "frame_count": len(frame_paths),
        "requested_audio_track_id": audio_track_id,
        "requested_audio_segments": [
            {"start_seconds": start, "end_seconds": end} for start, end in segments
        ],
        "selected_audio_language": selected_audio.get("language")
        if selected_audio
        else None,
        "audio_sample_count": len(audio_paths),
        "requested_subtitle_languages": subtitle_languages,
        "automatic_subtitles_requested": include_automatic_subtitles,
        "operation_status": operation_status,
        "review_checklist_path": review_path.relative_to(workspace).as_posix(),
        "review_checklist_sha256": sha256_file(review_path),
        "artifacts": artifacts,
        "warnings": warnings,
        "notice": "Artefatos coletados ainda exigem inspeção semântica pelo auditor.",
    }
    atomic_write_json(target / "collection_manifest.json", manifest)
    return manifest
