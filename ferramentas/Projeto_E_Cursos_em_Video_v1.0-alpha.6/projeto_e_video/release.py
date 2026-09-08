"""Validação e empacotamento seguro da versão isolada."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .util import atomic_write_json, now_iso, sha256_file, tree_files


MAX_PACKAGE_BYTES = 500_000_000
MANIFEST_NAME = "RELEASE_MANIFEST.json"
REQUIRED_FILES = {
    "VERSION",
    "README.md",
    "AGENTS.md",
    "ARQUITETURA.md",
    "PROMPT_MESTRE_PARA_AGENTE.md",
    "pyproject.toml",
    "BASELINE_ORIGEM_Projeto_E_Cursos_em_Video_v1.0-alpha.5.json",
    "LINEAGE_SEMANTICA_Projeto_E_v4.7-alpha.1.json",
    "docs/AUDITORIA_LANCAMENTO.md",
    "docs/REQUISITOS_CORRECAO_ALPHA5.md",
    "docs/REQUISITOS_CORRECAO_ALPHA6.md",
    "docs/RELEASE_CHECKLIST.md",
    "projeto_e_video/cli.py",
    "projeto_e_video/audio.py",
    "projeto_e_video/languages.py",
    "projeto_e_video/audit.py",
    "projeto_e_video/course.py",
    "schemas/evidence_input.schema.json",
    "schemas/audio_inventory.schema.json",
    "tests/test_audit.py",
}
FORBIDDEN_PARTS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "htmlcov",
    "runs",
    "workspaces",
    "evidence",
    "ledgers",
}
FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".avi",
    ".wav",
    ".mp3",
    ".m4a",
    ".opus",
    ".ogg",
    ".aac",
    ".flac",
    ".vtt",
    ".srt",
    ".env",
}
SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "google_api_key": re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "github_token": re.compile(rb"\bgh[opusr]_[A-Za-z0-9]{30,}\b"),
}


def tree_digest(root: Path, *, exclude_manifest: bool = False) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in tree_files(root):
        relative = path.relative_to(root).as_posix()
        if exclude_manifest and relative == MANIFEST_NAME:
            continue
        file_hash = sha256_file(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        count += 1
        total += path.stat().st_size
    return {
        "algorithm": "project-e-tree-sha256-v1",
        "framing": "path_posix_utf8 + NUL + sha256_hex_lower_ascii_64; sem terminador",
        "sha256": digest.hexdigest(),
        "file_count": count,
        "total_file_bytes": total,
    }


def _scan_file(path: Path) -> list[str]:
    if path.stat().st_size > 8 * 1024 * 1024:
        return []
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [f"não foi possível ler {path}: {exc}"]
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(data)]


def _expected_pep440(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)-alpha\.(\d+)", version)
    if not match:
        raise ValueError(f"VERSION fora do padrão esperado: {version}")
    major, minor, alpha = match.groups()
    return f"{major}.{minor}.0a{alpha}"


def _declared_project_version(path: Path) -> str:
    """Lê o campo PEP 621 necessário sem depender de tomllib (Python 3.11+)."""

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"pyproject.toml inválido: {exc}") from exc
    section = re.search(
        r"(?ms)^\[project\][ \t]*(?:#.*)?\r?\n(?P<body>.*?)(?=^\[|\Z)",
        text,
    )
    if section is None:
        raise ValueError("pyproject.toml não contém a seção [project]")
    matches = re.findall(
        r"(?m)^[ \t]*version[ \t]*=[ \t]*([\"'])([^\"'\r\n]+)\1"
        r"[ \t]*(?:#.*)?$",
        section.group("body"),
    )
    if len(matches) != 1:
        raise ValueError("pyproject.toml deve declarar exatamente uma versão literal")
    return matches[0][1]


def validate_baseline(root: Path, *, require_available: bool = False) -> dict[str, Any]:
    paths = sorted(root.glob("BASELINE_ORIGEM_*.json"))
    if len(paths) != 1:
        raise ValueError("release deve conter exatamente uma BASELINE_ORIGEM_*.json")
    try:
        document = json.loads(paths[0].read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"baseline inválida: {exc}") from exc
    origin = document.get("origin")
    if not isinstance(origin, dict):
        raise ValueError("baseline não contém origin")
    raw_path = origin.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("baseline não contém origin.path")
    origin_path = (root / raw_path).resolve()
    if not origin_path.is_dir():
        if require_available:
            raise ValueError(f"origem da baseline não está disponível: {origin_path}")
        return {
            "available": False,
            "verified": False,
            "identity": origin.get("identity"),
            "path": str(origin_path),
        }
    digest = tree_digest(origin_path)
    for field in ("algorithm", "framing", "sha256", "file_count", "total_file_bytes"):
        if origin.get(field) != digest.get(field):
            raise ValueError(f"baseline diverge da origem no campo {field}")
    return {
        "available": True,
        "verified": True,
        "identity": origin.get("identity"),
        "path": str(origin_path),
        **digest,
    }


def _validate_manifest(root: Path, version: str) -> None:
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise ValueError("RELEASE_MANIFEST.json ausente")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"RELEASE_MANIFEST.json inválido: {exc}") from exc
    expected_entries = []
    for file_path in tree_files(root):
        relative = file_path.relative_to(root).as_posix()
        if relative == MANIFEST_NAME:
            continue
        expected_entries.append(
            {
                "path": relative,
                "byte_size": file_path.stat().st_size,
                "sha256": sha256_file(file_path),
            }
        )
    if manifest.get("version") != version:
        raise ValueError("manifesto declara versão divergente")
    if manifest.get("promotion_ready") is not False:
        raise ValueError("manifesto alpha não pode declarar promoção pedagógica")
    if manifest.get("files") != expected_entries:
        raise ValueError("manifesto está desatualizado em relação à árvore")
    if manifest.get("tree_without_manifest") != tree_digest(
        root, exclude_manifest=True
    ):
        raise ValueError("digest do manifesto está desatualizado")


def validate_release(
    root: Path,
    *,
    require_origin: bool = False,
    require_current_manifest: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"pasta de release inexistente: {root}")
    version_path = root / "VERSION"
    if not version_path.is_file():
        raise ValueError("VERSION ausente")
    version = version_path.read_text(encoding="utf-8").strip()
    expected_name = f"Projeto_E_Cursos_em_Video_v{version}"
    if root.name != expected_name:
        raise ValueError(f"pasta deve se chamar {expected_name}")
    present = {path.relative_to(root).as_posix() for path in tree_files(root)}
    missing = sorted(REQUIRED_FILES - present)
    if missing:
        raise ValueError(f"arquivos obrigatórios ausentes: {missing}")
    declared_package_version = _declared_project_version(root / "pyproject.toml")
    if declared_package_version != _expected_pep440(version):
        raise ValueError("versão do pyproject.toml diverge de VERSION")
    init_text = (root / "projeto_e_video" / "__init__.py").read_text(encoding="utf-8")
    if f'__version__ = "{version}"' not in init_text:
        raise ValueError("__version__ diverge de VERSION")
    findings: list[str] = []
    total = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_symlink():
            findings.append(f"link simbólico proibido: {relative.as_posix()}")
            continue
        if not path.is_file():
            continue
        total += path.stat().st_size
        if any(part.startswith(".") for part in relative.parts):
            findings.append(f"arquivo oculto proibido: {relative.as_posix()}")
        lowered = {part.lower() for part in relative.parts}
        if lowered & {part.lower() for part in FORBIDDEN_PARTS}:
            findings.append(f"pasta proibida: {relative.as_posix()}")
        if any(part.lower().endswith(".egg-info") for part in relative.parts):
            findings.append(f"metadata de instalação proibido: {relative.as_posix()}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.lower() == ".env" or path.name.lower().startswith(".env."):
            findings.append(f"tipo de arquivo proibido: {relative.as_posix()}")
        if any(
            token in path.name.lower()
            for token in ("credentials", "client_secret", "access_token")
        ):
            findings.append(f"nome sensível proibido: {relative.as_posix()}")
        for secret in _scan_file(path):
            findings.append(f"segredo provável ({secret}): {relative.as_posix()}")
        if path.suffix.lower() == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                findings.append(f"JSON inválido {relative.as_posix()}: {exc}")
    if total > MAX_PACKAGE_BYTES:
        findings.append(f"pacote excede 500 MB decimais: {total} bytes")
    if findings:
        raise ValueError("release inválida:\n- " + "\n- ".join(findings))
    baseline = validate_baseline(root, require_available=require_origin)
    if require_current_manifest:
        _validate_manifest(root, version)
    digest = tree_digest(root)
    return {
        "schema_name": "projeto-e-video.release-validation",
        "schema_version": 1,
        "created_at": now_iso(),
        "valid": True,
        "path": str(root),
        "version": version,
        "limit_bytes": MAX_PACKAGE_BYTES,
        "baseline": baseline,
        **digest,
    }


def write_release_manifest(root: Path) -> dict[str, Any]:
    entries = []
    for path in tree_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST_NAME:
            continue
        entries.append(
            {
                "path": relative,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    digest = tree_digest(root, exclude_manifest=True)
    created_at = now_iso()
    previous_path = root / MANIFEST_NAME
    if previous_path.is_file():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            previous = None
        if (
            isinstance(previous, dict)
            and previous.get("files") == entries
            and previous.get("tree_without_manifest") == digest
            and isinstance(previous.get("created_at"), str)
        ):
            created_at = previous["created_at"]
    manifest = {
        "schema_name": "projeto-e-video.release-manifest",
        "schema_version": 1,
        "created_at": created_at,
        "version": (root / "VERSION").read_text(encoding="utf-8").strip(),
        "promotion_ready": False,
        "manifest_excludes_itself": True,
        "tree_without_manifest": digest,
        "files": entries,
    }
    atomic_write_json(root / MANIFEST_NAME, manifest)
    return manifest


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.create_system = 3
    return info


def validate_zip(zip_path: Path, expected_root: str) -> dict[str, Any]:
    if not zip_path.is_file():
        raise ValueError(f"ZIP inexistente: {zip_path}")
    if zip_path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError("ZIP excede 500 MB decimais")
    with zipfile.ZipFile(zip_path) as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        names = [item.filename for item in infos]
        if sum(item.file_size for item in infos) > MAX_PACKAGE_BYTES:
            raise ValueError("ZIP excede 500 MB descompactados")
        if len(names) != len(set(names)):
            raise ValueError("ZIP possui entradas duplicadas")
        roots = set()
        for item in infos:
            name = item.filename
            pure = PurePosixPath(name)
            if (
                "\\" in name
                or pure.is_absolute()
                or ".." in pure.parts
                or len(pure.parts) < 2
            ):
                raise ValueError(f"entrada insegura ou fora da raiz: {name}")
            mode = (item.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise ValueError(f"link simbólico proibido no ZIP: {name}")
            relative_parts = pure.parts[1:]
            if any(part.startswith(".") for part in relative_parts):
                raise ValueError(f"arquivo oculto proibido no ZIP: {name}")
            if {part.lower() for part in relative_parts} & {
                part.lower() for part in FORBIDDEN_PARTS
            }:
                raise ValueError(f"pasta proibida no ZIP: {name}")
            if any(part.lower().endswith(".egg-info") for part in relative_parts):
                raise ValueError(f"metadata de instalação proibido no ZIP: {name}")
            if pure.suffix.lower() in FORBIDDEN_SUFFIXES:
                raise ValueError(f"tipo de arquivo proibido no ZIP: {name}")
            roots.add(pure.parts[0])
        if roots != {expected_root}:
            raise ValueError(f"ZIP deve ter uma raiz {expected_root}; encontrou {sorted(roots)}")
        test_name = archive.testzip()
        if test_name:
            raise ValueError(f"CRC inválido em {test_name}")
        manifest_name = f"{expected_root}/{MANIFEST_NAME}"
        if manifest_name not in names:
            raise ValueError("ZIP não contém RELEASE_MANIFEST.json")
        try:
            manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"manifesto inválido no ZIP: {exc}") from exc
        manifest_files = manifest.get("files")
        if not isinstance(manifest_files, list):
            raise ValueError("manifesto do ZIP não contém files")
        if manifest.get("schema_name") != "projeto-e-video.release-manifest":
            raise ValueError("schema_name inválido no manifesto do ZIP")
        if manifest.get("promotion_ready") is not False:
            raise ValueError("manifesto do ZIP não pode promover a alpha")
        version = manifest.get("version")
        if expected_root != f"Projeto_E_Cursos_em_Video_v{version}":
            raise ValueError("raiz do ZIP diverge da versão do manifesto")
        expected_names = {manifest_name}
        tree_hash = hashlib.sha256()
        tree_count = 0
        tree_bytes = 0
        seen_manifest_paths: set[str] = set()
        ordered_paths: list[str] = []
        for row in manifest_files:
            if (
                not isinstance(row, dict)
                or set(row) != {"path", "byte_size", "sha256"}
                or not isinstance(row.get("path"), str)
            ):
                raise ValueError("entrada inválida no manifesto do ZIP")
            relative = PurePosixPath(row["path"])
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in row["path"]
                or not relative.parts
            ):
                raise ValueError("caminho inseguro no manifesto do ZIP")
            relative_name = relative.as_posix()
            if relative_name in seen_manifest_paths:
                raise ValueError("manifesto do ZIP possui caminhos duplicados")
            seen_manifest_paths.add(relative_name)
            ordered_paths.append(relative_name)
            member = f"{expected_root}/{relative_name}"
            expected_names.add(member)
            if member not in names:
                raise ValueError(f"arquivo do manifesto ausente no ZIP: {relative_name}")
            digest = hashlib.sha256()
            size = 0
            with archive.open(member) as source:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    digest.update(chunk)
            if size != row.get("byte_size"):
                raise ValueError(f"tamanho divergente no ZIP: {relative_name}")
            file_hash = digest.hexdigest()
            if file_hash != row.get("sha256"):
                raise ValueError(f"hash divergente no ZIP: {relative_name}")
            tree_hash.update(relative_name.encode("utf-8"))
            tree_hash.update(b"\0")
            tree_hash.update(file_hash.encode("ascii"))
            tree_count += 1
            tree_bytes += size
        if ordered_paths != sorted(ordered_paths, key=lambda value: value.encode("utf-8")):
            raise ValueError("arquivos do manifesto do ZIP não estão em ordem canônica")
        expected_tree = {
            "algorithm": "project-e-tree-sha256-v1",
            "framing": "path_posix_utf8 + NUL + sha256_hex_lower_ascii_64; sem terminador",
            "sha256": tree_hash.hexdigest(),
            "file_count": tree_count,
            "total_file_bytes": tree_bytes,
        }
        if manifest.get("tree_without_manifest") != expected_tree:
            raise ValueError("digest da árvore no manifesto do ZIP é divergente")
        if set(names) != expected_names:
            extras = sorted(set(names) - expected_names)
            raise ValueError(f"ZIP contém arquivos fora do manifesto: {extras[:10]}")
    return {
        "valid": True,
        "path": str(zip_path.resolve()),
        "root": expected_root,
        "entry_count": len(names),
        "byte_size": zip_path.stat().st_size,
        "sha256": sha256_file(zip_path),
    }


def package_release(
    root: Path,
    zip_path: Path,
    *,
    overwrite: bool = False,
    require_origin: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    zip_path = zip_path.resolve()
    if root in zip_path.parents:
        raise ValueError("o ZIP deve ficar fora da pasta versionada")
    if zip_path.exists() and not overwrite:
        raise ValueError(f"ZIP já existe: {zip_path}; use --overwrite conscientemente")
    write_release_manifest(root)
    validation = validate_release(root, require_origin=require_origin)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{zip_path.name}.", suffix=".tmp", dir=str(zip_path.parent), delete=False
    ) as handle:
        temporary_zip = Path(handle.name)
    try:
        with zipfile.ZipFile(
            temporary_zip,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in tree_files(root):
                relative = path.relative_to(root).as_posix()
                archive.writestr(
                    _zip_info(f"{root.name}/{relative}"), path.read_bytes()
                )
        validate_zip(temporary_zip, root.name)
        os.replace(temporary_zip, zip_path)
    except Exception:
        temporary_zip.unlink(missing_ok=True)
        raise
    zip_validation = validate_zip(zip_path, root.name)
    return {
        "schema_name": "projeto-e-video.package-result",
        "schema_version": 1,
        "created_at": now_iso(),
        "release": validation,
        "zip": zip_validation,
    }
