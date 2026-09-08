#!/usr/bin/env python3
"""Calcula uma identidade reproduzível para uma pasta de versão do Projeto E."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ALGORITHM = "project-e-tree-sha256-v1"
FRAMING = "path_posix_utf8 + NUL + sha256_hex_lower_ascii_64; sem terminador"


def iter_files(root: Path) -> list[Path]:
    """Retorna arquivos em ordem binária do caminho relativo, sem caches Python."""
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.relative_to(root).parts
        ),
        key=lambda path: path.relative_to(root).as_posix().encode("utf-8"),
    )


def hash_tree(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"pasta inexistente: {root}")

    aggregate = hashlib.sha256()
    total_bytes = 0
    files = iter_files(root)
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        aggregate.update(relative)
        aggregate.update(b"\0")
        aggregate.update(file_digest)
        total_bytes += path.stat().st_size

    return {
        "algorithm": ALGORITHM,
        "framing": FRAMING,
        "sha256": aggregate.hexdigest(),
        "file_count": len(files),
        "total_file_bytes": total_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="pasta cuja árvore será identificada")
    args = parser.parse_args()
    print(json.dumps(hash_tree(args.path), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
