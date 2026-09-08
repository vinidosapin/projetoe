"""Utilidades determinísticas e sem dependências externas."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


FORBIDDEN_ASSERTION_KEYS = {
    "approved",
    "approval",
    "classification",
    "coverage_status",
    "coverage_percent",
    "declared_coverage",
    "declared_status",
    "dominio_demonstrado",
    "mastery_claims",
    "promotion_ready",
    "student_mastery",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\x00", " ")
    return re.sub(r"\s+", " ", value).strip()


def ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def stable_id(prefix: str, *parts: str, length: int = 12) -> str:
    payload = "\x1f".join(normalize_text(part) for part in parts).encode("utf-8")
    return f"{prefix}-{sha256_bytes(payload)[:length]}"


def slugify(value: str, default: str = "curso") -> str:
    folded = ascii_fold(value)
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return slug[:80] or default


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_external_workspace(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = package_root().resolve()
    if resolved == root or root in resolved.parents:
        raise ValueError(
            "workspace deve ficar fora da pasta versionada; runs não entram no ZIP"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def forbidden_paths(value: Any, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            canonical_key = re.sub(
                r"[^a-z0-9]+", "_", ascii_fold(str(key))
            ).strip("_")
            if canonical_key in FORBIDDEN_ASSERTION_KEYS:
                found.append(child_path)
            found.extend(forbidden_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(forbidden_paths(child, f"{prefix}[{index}]"))
    return found


def require_no_forbidden_assertions(value: Any) -> None:
    found = forbidden_paths(value)
    if found:
        raise ValueError("campos de autoaprovação proibidos: " + ", ".join(found))


def sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(payload)


def unique_strings(values: Any, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field} deve ser lista")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} deve conter somente strings não vazias")
        clean = value.strip()
        if clean not in result:
            result.append(clean)
    if not allow_empty and not result:
        raise ValueError(f"{field} não pode ser vazio")
    return result


def format_seconds(value: int | float) -> str:
    total = max(0, int(round(value)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def merge_intervals(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((float(a), float(b)) for a, b in intervals if 0 <= a < b)
    merged: list[list[float]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def tree_files(root: Path, *, include_hidden: bool = False) -> Iterator[Path]:
    for path in sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix().encode("utf-8"),
    ):
        parts = path.relative_to(root).parts
        if "__pycache__" in parts or any(part.endswith(".pyc") for part in parts):
            continue
        if not include_hidden and any(part.startswith(".") for part in parts):
            continue
        yield path
