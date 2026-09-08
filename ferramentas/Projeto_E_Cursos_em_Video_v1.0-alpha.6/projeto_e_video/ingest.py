"""Ingestão segura de tópicos, arquivos, diretórios, URLs e ZIPs."""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from .external import run_command
from .network import validate_public_network_url
from .util import (
    atomic_write_json,
    atomic_write_text,
    normalize_text,
    now_iso,
    sha256_bytes,
    stable_id,
)


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".ipynb",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".sql",
    ".r",
    ".m",
    ".tex",
    ".rst",
    ".srt",
    ".vtt",
}

HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
XML_EXTENSIONS = {".xml", ".svg"}
OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp", ".epub"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
FLASHLIST_SCHEMA_NAME = "flashlist.weekly-study"
FLASHLIST_SOURCE_KIND = "FLASHLIST_ITEM"
FLASHLIST_LOCATOR_SEPARATOR = "::item:"


@dataclass(frozen=True)
class IngestLimits:
    max_files: int = 1000
    max_file_bytes: int = 64 * 1024 * 1024
    max_total_input_bytes: int = 200 * 1024 * 1024
    max_archive_uncompressed_bytes: int = 200 * 1024 * 1024
    max_extracted_chars: int = 32_000_000
    max_url_bytes: int = 64 * 1024 * 1024
    max_pdf_ocr_pages: int = 500


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        clean = data.strip()
        if clean:
            self.parts.append(clean)

    def text(self) -> str:
        return "\n".join(self.parts)


def _decode_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _strip_html(data: bytes) -> str:
    text, _ = _decode_text(data)
    parser = _TextHTMLParser()
    parser.feed(text)
    return parser.text()


def _xml_text(data: bytes) -> str:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        text, _ = _decode_text(data)
        return re.sub(r"<[^>]+>", " ", text)
    parts = [node.text.strip() for node in root.iter() if node.text and node.text.strip()]
    return "\n".join(parts)


def _sort_numeric_path(name: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name))


def _extract_office(data: bytes, suffix: str) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return "", "office_zip", ["contêiner Office/EPUB inválido"]

    names = archive.namelist()
    selected: list[str]
    if suffix == ".docx":
        selected = [name for name in names if name == "word/document.xml"]
    elif suffix == ".pptx":
        selected = sorted(
            (name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=_sort_numeric_path,
        )
    elif suffix == ".xlsx":
        selected = [name for name in names if name == "xl/sharedStrings.xml"]
        selected += sorted(
            (name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
            key=_sort_numeric_path,
        )
    elif suffix == ".epub":
        selected = sorted(
            name for name in names if Path(name).suffix.lower() in HTML_EXTENSIONS
        )
    else:
        selected = sorted(
            name
            for name in names
            if name.endswith(".xml") and ("content.xml" in name or "/slide" in name)
        )

    if len(selected) > 1000:
        archive.close()
        return "", "office_zip_xml", ["contêiner excede 1000 partes selecionadas"]
    selected_size = 0
    for name in selected:
        info = archive.getinfo(name)
        if info.file_size > 20 * 1024 * 1024:
            archive.close()
            return "", "office_zip_xml", [f"parte interna excessiva: {name}"]
        selected_size += info.file_size
        if selected_size > 50 * 1024 * 1024:
            archive.close()
            return "", "office_zip_xml", ["contêiner excede 50 MiB descompactados"]

    parts: list[str] = []
    for index, name in enumerate(selected, start=1):
        try:
            raw = archive.read(name)
        except (KeyError, RuntimeError) as exc:
            warnings.append(f"não foi possível ler {name}: {exc}")
            continue
        extracted = _strip_html(raw) if Path(name).suffix.lower() in HTML_EXTENSIONS else _xml_text(raw)
        if extracted.strip():
            parts.append(f"\n--- {name} [{index}] ---\n{extracted}")
    archive.close()
    return "\n".join(parts).strip(), "office_zip_xml", warnings


def _pdf_page_count(path: Path) -> tuple[int | None, str | None]:
    executable = shutil.which("pdfinfo")
    if not executable:
        return None, "OCR de PDF exige pdfinfo para limitar o número de páginas"
    result = run_command([executable, str(path)], timeout_seconds=30)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        return None, detail or "pdfinfo não conseguiu ler o PDF"
    text, _ = _decode_text(result.stdout)
    match = re.search(r"(?mi)^Pages:\s*(\d+)\s*$", text)
    if not match:
        return None, "pdfinfo não informou o número de páginas"
    return int(match.group(1)), None


def _tesseract_language(executable: str) -> str | None:
    result = run_command([executable, "--list-langs"], timeout_seconds=30)
    if result.returncode:
        return None
    text, _ = _decode_text(result.stdout)
    languages = {
        line.strip()
        for line in text.splitlines()
        if re.fullmatch(r"[A-Za-z0-9_+-]+", line.strip())
    }
    preferred = [language for language in ("por", "eng") if language in languages]
    if preferred:
        return "+".join(preferred)
    return sorted(languages)[0] if languages else None


def _ocr_pdf(path: Path, limits: IngestLimits) -> tuple[str, str, list[str]]:
    renderer = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    missing = [
        name
        for name, executable in (("pdftoppm", renderer), ("tesseract", tesseract))
        if not executable
    ]
    if missing:
        return "", "none", ["OCR de PDF exige " + " e ".join(missing)]
    assert renderer is not None and tesseract is not None
    page_count, page_error = _pdf_page_count(path)
    if page_count is None:
        return "", "pdftoppm+tesseract", [page_error or "número de páginas desconhecido"]
    if page_count < 1:
        return "", "pdftoppm+tesseract", ["PDF não contém páginas"]
    if page_count > limits.max_pdf_ocr_pages:
        return "", "pdftoppm+tesseract", [
            f"PDF tem {page_count} páginas; OCR está limitado a "
            f"{limits.max_pdf_ocr_pages} por execução"
        ]

    language = _tesseract_language(tesseract)
    warnings: list[str] = []
    page_texts: list[str] = []
    extracted_chars = 0
    with tempfile.TemporaryDirectory(prefix="projeto-e-pdf-ocr-") as temp_name:
        temporary = Path(temp_name)
        for page_number in range(1, page_count + 1):
            prefix = temporary / f"page-{page_number:05d}"
            image = prefix.with_suffix(".png")
            rendered = run_command(
                [
                    renderer,
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    "-r",
                    "150",
                    "-gray",
                    "-png",
                    "-singlefile",
                    str(path),
                    str(prefix),
                ],
                timeout_seconds=90,
            )
            if rendered.returncode or not image.is_file():
                detail = rendered.stderr.decode("utf-8", errors="replace").strip()
                warnings.append(
                    f"OCR página {page_number}: renderização falhou"
                    + (f": {detail[-300:]}" if detail else "")
                )
                page_texts.append("")
                continue
            command = [tesseract, str(image), "stdout"]
            if language:
                command.extend(["-l", language])
            recognized = run_command(command, timeout_seconds=180)
            if recognized.returncode:
                detail = recognized.stderr.decode("utf-8", errors="replace").strip()
                warnings.append(
                    f"OCR página {page_number}: tesseract falhou"
                    + (f": {detail[-300:]}" if detail else "")
                )
                page_texts.append("")
                continue
            page_text, _ = _decode_text(recognized.stdout)
            page_text = page_text.strip()
            extracted_chars += len(page_text)
            if extracted_chars > limits.max_extracted_chars:
                raise ValueError("OCR do PDF excede limite de texto extraído")
            page_texts.append(page_text)
            try:
                image.unlink()
            except FileNotFoundError:
                pass
    text = "\f".join(page_texts).strip()
    if not text:
        warnings.append("OCR concluiu sem reconhecer texto")
    return text, "pdftoppm+tesseract", warnings


def _extract_pdf(
    path: Path,
    *,
    ocr_scanned_pdf: bool = False,
    limits: IngestLimits | None = None,
) -> tuple[str, str, list[str]]:
    limits = limits or IngestLimits()
    executable = shutil.which("pdftotext")
    if not executable:
        warnings = ["PDF exige pdftotext para extração textual local"]
    else:
        result = run_command(
            [executable, "-layout", str(path), "-"],
            timeout_seconds=120,
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            warnings = [detail or "pdftotext não conseguiu extrair o PDF"]
        else:
            text, _ = _decode_text(result.stdout)
            if text.strip():
                return text, "pdftotext", []
            warnings = ["PDF não possui camada textual utilizável"]
    if not ocr_scanned_pdf:
        warnings.append("use --ocr-scanned-pdf para tentar OCR local explícito")
        return "", "pdftotext" if executable else "none", warnings
    text, extractor, ocr_warnings = _ocr_pdf(path, limits)
    return text, extractor, [*warnings, *ocr_warnings]


def _extract_image(path: Path) -> tuple[str, str, list[str]]:
    executable = shutil.which("tesseract")
    if not executable:
        return "", "none", ["imagem exige tesseract para OCR local"]
    command = [executable, str(path), "stdout"]
    language = _tesseract_language(executable)
    if language:
        command.extend(["-l", language])
    result = run_command(command, timeout_seconds=120)
    if result.returncode:
        return "", "tesseract", [result.stderr.decode("utf-8", errors="replace").strip()]
    text, _ = _decode_text(result.stdout)
    return text, "tesseract", []


def _extract_data(data: bytes, suffix: str) -> tuple[str, str, list[str]]:
    suffix = suffix.lower()
    if suffix in XML_EXTENSIONS:
        return _xml_text(data), "xml_parser", []
    if suffix in TEXT_EXTENSIONS:
        text, encoding = _decode_text(data)
        if suffix in {".json", ".ipynb"}:
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        return text, f"text:{encoding}", []
    if suffix in HTML_EXTENSIONS:
        return _strip_html(data), "html_parser", []
    if suffix in OFFICE_EXTENSIONS:
        return _extract_office(data, suffix)
    return "", "none", [f"extração não disponível para {suffix or 'extensão ausente'}"]


def _safe_archive_name(name: str) -> PurePosixPath:
    normalized = PurePosixPath(name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"caminho inseguro no ZIP: {name}")
    return normalized


def _zip_members(path: Path, limits: IngestLimits) -> list[tuple[str, bytes]]:
    result: list[tuple[str, bytes]] = []
    total = 0
    seen_names: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) > limits.max_files:
                raise ValueError(f"ZIP excede {limits.max_files} arquivos")
            for item in members:
                safe = _safe_archive_name(item.filename)
                safe_name = safe.as_posix()
                if safe_name in seen_names:
                    raise ValueError(f"membro duplicado no ZIP: {safe_name}")
                seen_names.add(safe_name)
                mode = (item.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError(f"link simbólico não permitido no ZIP: {item.filename}")
                if item.file_size > limits.max_file_bytes:
                    raise ValueError(f"arquivo do ZIP excede limite: {item.filename}")
                total += item.file_size
                if total > limits.max_archive_uncompressed_bytes:
                    raise ValueError("ZIP excede limite de bytes descompactados")
                result.append((safe_name, archive.read(item)))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"arquivo ZIP inválido: {path}") from exc
    return result


def _url_bytes(url: str, limits: IngestLimits) -> tuple[bytes, str]:
    validate_public_network_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Projeto-E-Cursos-em-Video/1.0-alpha.6"},
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    with opener.open(request, timeout=30) as response:
        validate_public_network_url(response.geturl())
        content_type = response.headers.get_content_type()
        declared_length = response.headers.get("Content-Length")
        if declared_length:
            try:
                if int(declared_length) > limits.max_url_bytes:
                    raise ValueError("URL declara conteúdo acima do limite")
            except ValueError as exc:
                if "acima do limite" in str(exc):
                    raise
        data = response.read(limits.max_url_bytes + 1)
    if len(data) > limits.max_url_bytes:
        raise ValueError("URL excede limite de download")
    return data, content_type


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_public_network_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _record_from_bytes(
    *,
    locator: str,
    data: bytes,
    suffix: str,
    text_dir: Path,
    source_kind: str,
    path_for_tools: Path | None = None,
    limits: IngestLimits | None = None,
    ocr_scanned_pdf: bool = False,
) -> dict[str, Any]:
    source_id = stable_id("SRC", locator, sha256_bytes(data))
    media_type = mimetypes.guess_type(locator)[0] or "application/octet-stream"
    if suffix.lower() == ".pdf":
        if path_for_tools is not None:
            text, extractor, warnings = _extract_pdf(
                path_for_tools,
                ocr_scanned_pdf=ocr_scanned_pdf,
                limits=limits,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="projeto-e-pdf-") as temp_name:
                temporary = Path(temp_name) / "source.pdf"
                temporary.write_bytes(data)
                text, extractor, warnings = _extract_pdf(
                    temporary,
                    ocr_scanned_pdf=ocr_scanned_pdf,
                    limits=limits,
                )
    elif suffix.lower() in IMAGE_EXTENSIONS:
        if path_for_tools is not None:
            text, extractor, warnings = _extract_image(path_for_tools)
        else:
            with tempfile.TemporaryDirectory(prefix="projeto-e-image-") as temp_name:
                temporary = Path(temp_name) / f"source{suffix.lower()}"
                temporary.write_bytes(data)
                text, extractor, warnings = _extract_image(temporary)
    else:
        text, extractor, warnings = _extract_data(data, suffix)
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text_path: str | None = None
    text_hash: str | None = None
    status = "EXTRAIDA" if text else "EXTRACAO_NAO_DISPONIVEL"
    if text:
        target = text_dir / f"{source_id}.txt"
        atomic_write_text(target, text + "\n")
        text_path = target.parent.name + "/" + target.name
        text_hash = sha256_bytes(text.encode("utf-8"))
    return {
        "source_id": source_id,
        "kind": source_kind,
        "locator": locator,
        "exact_locator": locator,
        "media_type": media_type,
        "byte_size": len(data),
        "sha256": sha256_bytes(data),
        "extraction_status": status,
        "extractor": extractor,
        "text_path": text_path,
        "text_sha256": text_hash,
        "warnings": [warning for warning in warnings if warning],
    }


def _existing_path(value: str) -> Path | None:
    """Sonda um caminho sem deixar limites do SO quebrarem uma entrada literal."""

    if not value.strip():
        return None
    try:
        candidate = Path(value).expanduser()
        return candidate if candidate.exists() else None
    except (OSError, ValueError):
        # ENAMETOOLONG e valores que não podem ser representados como caminho
        # são tópicos válidos; a decisão semântica ocorre depois.
        return None


def _flashlist_document(path: Path) -> tuple[Path, dict[str, Any]] | None:
    """Reconhece um pacote semanal somente quando ele é pedido explicitamente.

    Uma pasta ou o próprio ``manifest.json`` seleciona o pacote estruturado. Um
    PDF vizinho continua sendo uma fonte PDF autônoma: o usuário pode usar as
    imagens como fila mutável em paralelo sem que elas entrem silenciosamente
    no curso ou invalidem a execução baseada somente no relatório.
    """

    if path.is_dir():
        manifest_path = path / "manifest.json"
    elif path.is_file() and path.name == "manifest.json":
        manifest_path = path
    else:
        return None
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_name") != FLASHLIST_SCHEMA_NAME:
        return None
    if value.get("schema_version") != 1:
        raise ValueError("versão do manifesto semanal FlashList não suportada")
    return manifest_path.resolve(), value


def _flashlist_ref(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", value):
        raise ValueError(f"{field} inválido no manifesto FlashList")
    return value


def _flashlist_asset_path(manifest_path: Path, asset: dict[str, Any]) -> Path:
    raw = asset.get("file")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("asset.file ausente no manifesto FlashList")
    relative = PurePosixPath(raw.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("asset.file inseguro no manifesto FlashList")
    path = manifest_path.parent / Path(*relative.parts)
    resolved = path.resolve()
    try:
        resolved.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise ValueError("asset.file escapa da pasta FlashList") from exc
    if path.is_symlink():
        raise ValueError("link simbólico não permitido em asset FlashList")
    return resolved


def _flashlist_item_payload(
    *,
    item: dict[str, Any],
    asset: dict[str, Any],
    image_sha256: str | None,
) -> bytes:
    """Serialização estável usada para identidade e verificação externa."""

    return json.dumps(
        {"item": item, "asset": asset, "image_sha256": image_sha256},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _flashlist_policy(difficulty_key: str) -> str:
    if difficulty_key == "easy":
        return "CONTROL_NO_AUTOMATIC"
    if difficulty_key == "hard":
        return "OPTIONAL"
    return "REQUIRED"


def _flashlist_item_record(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    item: dict[str, Any],
    asset: dict[str, Any],
    text_dir: Path,
    limits: IngestLimits,
) -> dict[str, Any]:
    item_ref = _flashlist_ref(item.get("item_ref"), field="item_ref")
    asset_ref = _flashlist_ref(item.get("asset_ref"), field="item.asset_ref")
    if asset_ref != _flashlist_ref(asset.get("asset_ref"), field="asset.asset_ref"):
        raise ValueError(f"item {item_ref} aponta asset divergente")
    image_path = _flashlist_asset_path(manifest_path, asset)
    image_data: bytes | None = None
    image_digest: str | None = None
    warnings: list[str] = []
    ocr_text = ""
    extractor = "flashlist_manifest"
    content_status = "ASSET_MISSING"
    if image_path.is_file():
        size = image_path.stat().st_size
        if size > limits.max_file_bytes:
            raise ValueError(f"asset FlashList excede limite: {image_path}")
        image_data = image_path.read_bytes()
        image_digest = sha256_bytes(image_data)
        ocr_text, ocr_extractor, ocr_warnings = _extract_image(image_path)
        warnings.extend(ocr_warnings)
        if ocr_text.strip():
            extractor += f"+{ocr_extractor}"
            content_status = "OCR_EXTRACTED"
        else:
            content_status = "IMAGE_TEXT_NOT_EXTRACTED"
            warnings.append(
                "enunciado da imagem não foi extraído; o mapa V1 deve conferi-lo antes da busca"
            )
    else:
        warnings.append(
            "asset declarado no manifesto está ausente; o mapa V1 deve recuperar o enunciado"
        )

    payload = _flashlist_item_payload(
        item=item,
        asset=asset,
        image_sha256=image_digest,
    )
    payload_digest = sha256_bytes(payload)
    locator = f"{manifest_path}{FLASHLIST_LOCATOR_SEPARATOR}{item_ref}"
    source_id = stable_id("SRC", locator, payload_digest)
    raw_context = item.get("context")
    context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
    raw_difficulty = item.get("difficulty")
    difficulty: dict[str, Any] = (
        raw_difficulty if isinstance(raw_difficulty, dict) else {}
    )
    raw_availability = item.get("availability")
    availability: dict[str, Any] = (
        raw_availability if isinstance(raw_availability, dict) else {}
    )
    difficulty_key = normalize_text(str(difficulty.get("key", "unknown"))).lower()
    difficulty_label = normalize_text(str(difficulty.get("label", difficulty_key)))
    discipline = normalize_text(str(context.get("discipline", "Disciplina não informada")))
    physical_topic = normalize_text(str(context.get("physical_topic", "Tópico não informado")))
    policy = _flashlist_policy(difficulty_key)
    prefix = {
        "REQUIRED": "ERRO",
        "OPTIONAL": "DIFÍCIL OPCIONAL",
        "CONTROL_NO_AUTOMATIC": "CONTROLE FÁCIL",
    }[policy]
    title = f"[{prefix}] {discipline} — {physical_topic}"
    raw_scope = manifest.get("scope")
    scope: dict[str, Any] = raw_scope if isinstance(raw_scope, dict) else {}
    text_lines = [
        "[FLASHLIST_WEEKLY_ITEM]",
        f"item_ref: {item_ref}",
        f"asset_ref: {asset_ref}",
        f"title: {title}",
        f"route_policy: {policy}",
        f"difficulty_key: {difficulty_key or 'unknown'}",
        f"difficulty_label: {difficulty_label or 'Não informada'}",
        f"availability_key: {normalize_text(str(availability.get('key', 'unknown')))}",
        f"discipline: {discipline}",
        f"physical_topic: {physical_topic}",
        f"period_start: {normalize_text(str(scope.get('local_start_date', '')))}",
        f"period_end: {normalize_text(str(scope.get('local_end_date', '')))}",
        f"asset_file: {normalize_text(str(asset.get('file', '')))}",
        f"asset_sha256: {image_digest or 'AUSENTE'}",
        f"content_status: {content_status}",
        "kind: EXERCICIO_REPORTADO_PELO_ALUNO",
    ]
    if ocr_text.strip():
        text_lines.extend(("", "[ENUNCIADO_OCR_NAO_CONFERIDO]", ocr_text.strip()))
    text = "\n".join(text_lines).strip()
    target = text_dir / f"{source_id}.txt"
    atomic_write_text(target, text + "\n")
    return {
        "source_id": source_id,
        "kind": FLASHLIST_SOURCE_KIND,
        "locator": locator,
        "exact_locator": locator,
        "media_type": "application/vnd.flashlist.weekly-item+json",
        "byte_size": len(payload) + (len(image_data) if image_data is not None else 0),
        "sha256": payload_digest,
        "extraction_status": "EXTRAIDA",
        "extractor": extractor,
        "text_path": target.parent.name + "/" + target.name,
        "text_sha256": sha256_bytes(text.encode("utf-8")),
        "warnings": sorted(set(warning for warning in warnings if warning)),
    }


def _flashlist_sources(
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    text_dir: Path,
    limits: IngestLimits,
) -> list[dict[str, Any]]:
    items = manifest.get("items")
    assets = manifest.get("assets")
    if not isinstance(items, list) or not items:
        raise ValueError("manifesto FlashList não contém items")
    if not isinstance(assets, list) or not assets:
        raise ValueError("manifesto FlashList não contém assets")
    if len(items) > limits.max_files:
        raise ValueError(f"manifesto FlashList excede {limits.max_files} itens")
    asset_index: dict[str, dict[str, Any]] = {}
    for raw in assets:
        if not isinstance(raw, dict):
            raise ValueError("asset inválido no manifesto FlashList")
        asset_ref = _flashlist_ref(raw.get("asset_ref"), field="asset.asset_ref")
        if asset_ref in asset_index:
            raise ValueError(f"asset_ref duplicado no manifesto FlashList: {asset_ref}")
        asset_index[asset_ref] = raw
    result: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("item inválido no manifesto FlashList")
        item_ref = _flashlist_ref(raw.get("item_ref"), field="item_ref")
        if item_ref in seen_items:
            raise ValueError(f"item_ref duplicado no manifesto FlashList: {item_ref}")
        seen_items.add(item_ref)
        asset_ref = _flashlist_ref(raw.get("asset_ref"), field="item.asset_ref")
        asset = asset_index.get(asset_ref)
        if asset is None:
            raise ValueError(f"item {item_ref} aponta asset inexistente: {asset_ref}")
        result.append(
            _flashlist_item_record(
                manifest_path=manifest_path,
                manifest=manifest,
                item=raw,
                asset=asset,
                text_dir=text_dir,
                limits=limits,
            )
        )
    return result


def _flashlist_external_payload(locator: str) -> bytes | None:
    if FLASHLIST_LOCATOR_SEPARATOR not in locator:
        return None
    manifest_name, item_ref = locator.rsplit(FLASHLIST_LOCATOR_SEPARATOR, 1)
    manifest_path = Path(manifest_name)
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict) or manifest.get("schema_name") != FLASHLIST_SCHEMA_NAME:
        return None
    items = manifest.get("items")
    assets = manifest.get("assets")
    if not isinstance(items, list) or not isinstance(assets, list):
        return None
    item = next(
        (row for row in items if isinstance(row, dict) and row.get("item_ref") == item_ref),
        None,
    )
    if item is None:
        return None
    asset_ref = item.get("asset_ref")
    asset = next(
        (row for row in assets if isinstance(row, dict) and row.get("asset_ref") == asset_ref),
        None,
    )
    if asset is None:
        return None
    image_path = _flashlist_asset_path(manifest_path, asset)
    image_digest = sha256_bytes(image_path.read_bytes()) if image_path.is_file() else None
    return _flashlist_item_payload(
        item=item,
        asset=asset,
        image_sha256=image_digest,
    )


def _ingest_uncommitted(
    input_value: str,
    workspace: Path,
    *,
    title: str | None = None,
    allow_network: bool = False,
    extra_inputs: list[str] | None = None,
    limits: IngestLimits | None = None,
    ocr_scanned_pdf: bool = False,
) -> dict[str, Any]:
    """Monta manifesto e textos em uma área ainda não publicada."""

    limits = limits or IngestLimits()
    ingest_dir = workspace / "ingest"
    text_dir = ingest_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    input_values = [input_value, *(extra_inputs or [])]
    if not all(isinstance(value, str) for value in input_values):
        raise ValueError("todas as entradas devem ser strings")
    if any(not value.strip() for value in input_values):
        raise ValueError("entradas não podem ser vazias")
    if len(input_values) > limits.max_files:
        raise ValueError(f"conjunto excede {limits.max_files} entradas")
    sources: list[dict[str, Any]] = []
    input_rows: list[dict[str, Any]] = []

    for current_input in input_values:
        source_path = _existing_path(current_input)
        input_kind: str
        if source_path is not None:
            resolved = source_path.resolve()
            flashlist = _flashlist_document(resolved)
            if flashlist is not None:
                input_kind = "DIRECTORY" if resolved.is_dir() else "FILE"
                manifest_path, flashlist_manifest = flashlist
                sources.extend(
                    _flashlist_sources(
                        manifest_path,
                        flashlist_manifest,
                        text_dir=text_dir,
                        limits=limits,
                    )
                )
            elif resolved.is_dir():
                input_kind = "DIRECTORY"
                entries = list(resolved.rglob("*"))
                links = [path for path in entries if path.is_symlink()]
                if links:
                    relative = links[0].relative_to(resolved).as_posix()
                    raise ValueError(
                        f"link simbólico não permitido no diretório: {relative}"
                    )
                files = sorted(
                    (path for path in entries if path.is_file()),
                    key=lambda path: path.relative_to(resolved)
                    .as_posix()
                    .encode("utf-8"),
                )
                files = [
                    path
                    for path in files
                    if "__pycache__" not in path.parts
                    and not any(
                        part.startswith(".")
                        for part in path.relative_to(resolved).parts
                    )
                ]
                if len(files) > limits.max_files:
                    raise ValueError(
                        f"diretório excede {limits.max_files} arquivos"
                    )
                for path in files:
                    size = path.stat().st_size
                    if size > limits.max_file_bytes:
                        raise ValueError(f"arquivo excede limite: {path}")
                    relative = path.relative_to(resolved).as_posix()
                    data = path.read_bytes()
                    sources.append(
                        _record_from_bytes(
                            locator=f"{resolved}::{relative}",
                            data=data,
                            suffix=path.suffix,
                            text_dir=text_dir,
                            source_kind="DIRECTORY_FILE",
                            path_for_tools=path,
                            limits=limits,
                            ocr_scanned_pdf=ocr_scanned_pdf,
                        )
                    )
            elif resolved.suffix.lower() == ".zip":
                input_kind = "ZIP"
                for member_name, data in _zip_members(resolved, limits):
                    suffix = Path(member_name).suffix
                    sources.append(
                        _record_from_bytes(
                            locator=f"{resolved}::{member_name}",
                            data=data,
                            suffix=suffix,
                            text_dir=text_dir,
                            source_kind="ZIP_MEMBER",
                            limits=limits,
                            ocr_scanned_pdf=ocr_scanned_pdf,
                        )
                    )
            else:
                input_kind = "FILE"
                if resolved.stat().st_size > limits.max_file_bytes:
                    raise ValueError("arquivo excede limite de entrada")
                sources.append(
                    _record_from_bytes(
                        locator=str(resolved),
                        data=resolved.read_bytes(),
                        suffix=resolved.suffix,
                        text_dir=text_dir,
                        source_kind="FILE",
                        path_for_tools=resolved,
                        limits=limits,
                        ocr_scanned_pdf=ocr_scanned_pdf,
                    )
                )
        elif urllib.parse.urlparse(current_input).scheme in {"http", "https"}:
            input_kind = "URL"
            if allow_network:
                data, content_type = _url_bytes(current_input, limits)
                suffix = Path(urllib.parse.urlparse(current_input).path).suffix
                if not suffix and content_type == "text/html":
                    suffix = ".html"
                sources.append(
                    _record_from_bytes(
                        locator=current_input,
                        data=data,
                        suffix=suffix,
                        text_dir=text_dir,
                        source_kind="URL",
                        limits=limits,
                        ocr_scanned_pdf=ocr_scanned_pdf,
                    )
                )
            else:
                source_id = stable_id("SRC", current_input)
                sources.append(
                    {
                        "source_id": source_id,
                        "kind": "URL",
                        "locator": current_input,
                        "exact_locator": current_input,
                        "media_type": "unknown",
                        "byte_size": None,
                        "sha256": None,
                        "extraction_status": "URL_NAO_BAIXADA",
                        "extractor": "none",
                        "text_path": None,
                        "text_sha256": None,
                        "warnings": ["use --allow-network ou forneça o arquivo"],
                    }
                )
        else:
            input_kind = "TOPIC"
            clean = normalize_text(current_input)
            if not clean:
                raise ValueError("tópico vazio")
            data = clean.encode("utf-8")
            topic_locator = f"topic://user-input/{sha256_bytes(data)[:12]}"
            sources.append(
                _record_from_bytes(
                    locator=topic_locator,
                    data=data,
                    suffix=".txt",
                    text_dir=text_dir,
                    source_kind="TOPIC",
                    limits=limits,
                    ocr_scanned_pdf=ocr_scanned_pdf,
                )
            )
        input_rows.append(
            {
                "kind": input_kind,
                "value": current_input,
                "allow_network": allow_network,
            }
        )

    deduplicated: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    for source in sources:
        if source["source_id"] not in seen_source_ids:
            deduplicated.append(source)
            seen_source_ids.add(source["source_id"])
    sources = deduplicated
    if not sources:
        raise ValueError("nenhuma fonte foi encontrada nas entradas")
    if len(sources) > limits.max_files:
        raise ValueError(f"conjunto excede {limits.max_files} fontes")
    total_input_bytes = sum(
        int(source["byte_size"])
        for source in sources
        if isinstance(source.get("byte_size"), int)
    )
    if total_input_bytes > limits.max_total_input_bytes:
        raise ValueError("conjunto excede limite total de entrada")
    extracted_chars = 0
    for source in sources:
        if source.get("text_path"):
            extracted_chars += len((ingest_dir / str(source["text_path"])).read_text(encoding="utf-8"))
    if extracted_chars > limits.max_extracted_chars:
        raise ValueError("texto extraído excede limite; divida a entrada")

    first_path = _existing_path(input_value)
    inferred_title = (
        first_path.stem
        if len(input_values) == 1 and first_path is not None
        else normalize_text(input_value)[:120]
        if len(input_values) == 1
        else f"Curso de {len(input_values)} entradas"
    )
    manifest = {
        "schema_name": "projeto-e-video.source-manifest",
        "schema_version": 2,
        "created_at": now_iso(),
        "course_id": stable_id("COURSE", *(input_values + [title or ""])),
        "title": title or inferred_title,
        "input": {
            "kind": input_rows[0]["kind"] if len(input_rows) == 1 else "BUNDLE",
            "value": input_value if len(input_rows) == 1 else f"{len(input_rows)} entradas",
            "allow_network": allow_network,
            "items": input_rows,
        },
        "limits": {**limits.__dict__, "ocr_scanned_pdf": ocr_scanned_pdf},
        "source_count": len(sources),
        "extracted_source_count": sum(1 for row in sources if row["extraction_status"] == "EXTRAIDA"),
        "sources": sources,
    }
    atomic_write_json(ingest_dir / "source_manifest.json", manifest)
    return manifest


def ingest(
    input_value: str,
    workspace: Path,
    *,
    title: str | None = None,
    allow_network: bool = False,
    extra_inputs: list[str] | None = None,
    limits: IngestLimits | None = None,
    ocr_scanned_pdf: bool = False,
) -> dict[str, Any]:
    """Ingere fontes de forma transacional e publica ``ingest/`` no sucesso.

    Extração de PDF, OCR e validações de limite podem falhar depois de parte do
    trabalho ter sido feita. Por isso, nenhum byte intermediário é gravado no
    workspace definitivo. Uma falha deixa o estado anterior exatamente como
    estava e permite corrigir a entrada e tentar novamente.
    """

    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    target = workspace / "ingest"
    if target.exists():
        raise ValueError("workspace já contém ingestão; use um workspace novo")

    with tempfile.TemporaryDirectory(
        prefix=f".{workspace.name}.ingest-", dir=str(workspace.parent)
    ) as temporary_name:
        staging_workspace = Path(temporary_name)
        manifest = _ingest_uncommitted(
            input_value,
            staging_workspace,
            title=title,
            allow_network=allow_network,
            extra_inputs=extra_inputs,
            limits=limits,
            ocr_scanned_pdf=ocr_scanned_pdf,
        )
        staged_ingest = staging_workspace / "ingest"
        if target.exists():
            raise ValueError("workspace recebeu outra ingestão durante a operação")
        os.replace(staged_ingest, target)
    return manifest


def validate_source_manifest(
    workspace: Path, value: Any
) -> dict[str, Any]:
    """Valida o manifesto, textos preservados e originais ainda disponíveis."""

    if not isinstance(value, dict):
        raise ValueError("source_manifest deve ser objeto")
    if value.get("schema_name") != "projeto-e-video.source-manifest":
        raise ValueError("schema_name inválido no source_manifest")
    if value.get("schema_version") != 2:
        raise ValueError("schema_version inválido no source_manifest")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("source_manifest.sources deve ser lista não vazia")
    if value.get("source_count") != len(sources):
        raise ValueError("source_count diverge de sources")
    source_ids: set[str] = set()
    extracted_count = 0
    external_verified = 0
    external_unavailable: list[str] = []
    for index, source in enumerate(sources):
        where = f"sources[{index}]"
        if not isinstance(source, dict):
            raise ValueError(f"{where} deve ser objeto")
        source_id = source.get("source_id")
        locator = source.get("exact_locator")
        digest = source.get("sha256")
        if not isinstance(source_id, str) or not source_id.startswith("SRC-"):
            raise ValueError(f"{where}.source_id inválido")
        if source_id in source_ids:
            raise ValueError(f"source_id duplicado: {source_id}")
        source_ids.add(source_id)
        if not isinstance(locator, str) or not locator:
            raise ValueError(f"{where}.exact_locator inválido")
        if digest is not None and (
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError(f"{where}.sha256 inválido")
        expected_id = (
            stable_id("SRC", locator, digest)
            if digest is not None
            else stable_id("SRC", locator)
        )
        if source_id != expected_id:
            raise ValueError(f"{where}.source_id diverge do contexto e hash")
        text_path = source.get("text_path")
        text_digest = source.get("text_sha256")
        if text_path is not None:
            relative = PurePosixPath(str(text_path))
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or tuple(relative.parts[:1]) != ("text",)
            ):
                raise ValueError(f"{where}.text_path inseguro")
            path = (workspace / "ingest" / Path(*relative.parts)).resolve()
            if not path.is_file():
                raise ValueError(f"texto extraído ausente: {text_path}")
            text = path.read_text(encoding="utf-8").rstrip("\n")
            if sha256_bytes(text.encode("utf-8")) != text_digest:
                raise ValueError(f"hash do texto extraído diverge: {text_path}")
            extracted_count += 1
        elif text_digest is not None:
            raise ValueError(f"{where}.text_sha256 existe sem text_path")

        original: bytes | None = None
        kind = source.get("kind")
        try:
            if kind == "FILE":
                path = Path(locator)
                if path.is_file():
                    original = path.read_bytes()
            elif kind == "DIRECTORY_FILE" and "::" in locator:
                root, relative_name = locator.split("::", 1)
                path = Path(root) / Path(*PurePosixPath(relative_name).parts)
                if path.is_file():
                    original = path.read_bytes()
            elif kind == "ZIP_MEMBER" and "::" in locator:
                archive_name, member = locator.split("::", 1)
                archive_path = Path(archive_name)
                if archive_path.is_file():
                    with zipfile.ZipFile(archive_path) as archive:
                        original = archive.read(member)
            elif kind == FLASHLIST_SOURCE_KIND:
                original = _flashlist_external_payload(locator)
        except (OSError, KeyError, zipfile.BadZipFile):
            original = None
        if original is None:
            if kind in {
                "FILE",
                "DIRECTORY_FILE",
                "ZIP_MEMBER",
                FLASHLIST_SOURCE_KIND,
            }:
                external_unavailable.append(source_id)
        else:
            if sha256_bytes(original) != digest:
                raise ValueError(f"fonte externa mudou desde a ingestão: {locator}")
            external_verified += 1
    if value.get("extracted_source_count") != extracted_count:
        raise ValueError("extracted_source_count diverge das fontes")
    return {
        "valid": True,
        "source_count": len(sources),
        "extracted_source_count": extracted_count,
        "external_source_verified_count": external_verified,
        "external_source_unavailable_ids": external_unavailable,
    }
