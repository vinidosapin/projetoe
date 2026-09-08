"""Descoberta e execução controlada de ferramentas opcionais."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from typing import Any, Sequence


def yt_dlp_command() -> list[str] | None:
    """Retorna um comando utilizável sem exigir instalação global."""

    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return None


def preflight_report() -> dict[str, Any]:
    """Relata capacidades locais sem rede, instalação ou alteração de estado."""

    yt_dlp = yt_dlp_command()
    executables = {
        name: shutil.which(name)
        for name in ("ffmpeg", "pdftotext", "pdfinfo", "pdftoppm", "tesseract")
    }
    tools = {
        "yt-dlp": {
            "available": yt_dlp is not None,
            "command": yt_dlp or [],
            "install": "python3 -m pip install '.[automation]'",
        },
        **{
            name: {"available": path is not None, "path": path}
            for name, path in executables.items()
        },
    }
    yt_ready = yt_dlp is not None
    ffmpeg_ready = executables["ffmpeg"] is not None
    return {
        "schema_name": "projeto-e-video.preflight",
        "schema_version": 1,
        "python": {
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "supported": sys.version_info >= (3, 10),
        },
        "api_key_required": False,
        "core_ready": sys.version_info >= (3, 10),
        "manual_browser_flow_ready": True,
        "tools": tools,
        "capabilities": {
            "automatic_public_search": yt_ready,
            "automatic_audio_inventory": yt_ready,
            "automatic_frame_and_audio_collection": yt_ready and ffmpeg_ready,
            "text_pdf_extraction": executables["pdftotext"] is not None,
            "scanned_pdf_ocr": all(
                executables[name] is not None
                for name in ("pdfinfo", "pdftoppm", "tesseract")
            ),
            "image_ocr": executables["tesseract"] is not None,
        },
        "next": (
            "Automação pública disponível; ainda é obrigatório inspecionar conteúdo e ouvir PT/EN."
            if yt_ready
            else "Use --provider manual ou instale o extra automation; nenhum gate será reduzido."
        ),
    }


def run_command(
    command: Sequence[str],
    *,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    """Executa sem shell e converte timeout em erro operacional legível."""

    if timeout_seconds < 1:
        raise ValueError("timeout_seconds deve ser positivo")
    try:
        return subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        rendered = " ".join(str(part) for part in command[:4])
        raise ValueError(
            f"ferramenta externa excedeu {timeout_seconds}s: {rendered}"
        ) from exc
