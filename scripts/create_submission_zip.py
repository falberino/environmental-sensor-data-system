#!/usr/bin/env python3
"""
Create a submission ZIP of the project (under 25 MB target).

Excludes .git, virtualenvs, full CSV, caches, and large generated files.
Includes the sample CSV and all source code needed to run the project.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ZIP_NAME = "environmental-sensor-data-system-submission.zip"
MAX_SIZE_MB = 25

# Paths/patterns to skip entirely
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".ipynb_checkpoints",
    "node_modules",
    "mongo-data",
}

SKIP_FILE_NAMES = {
    ".DS_Store",
    ZIP_NAME,
    "environmental-sensor-data-system-submission.zip",
}

# File path substrings to exclude
SKIP_PATH_PARTS = (
    "/.git/",
    "/.venv/",
    "/venv/",
    "/__pycache__/",
)

# Specific files to exclude (relative to project root)
EXCLUDE_FILES = {
    "data/iot_telemetry_data.csv",
    ".env",
}

# Allow sample CSV even though other CSVs are excluded
ALLOW_FILES = {
    "data/sample_iot_telemetry_data.csv",
    "data/README.md",
    "outputs/README.md",
}


def should_include(path: Path, rel: str) -> bool:
    """Return True if a file should be added to the ZIP."""
    if rel in EXCLUDE_FILES:
        return False
    if path.name in SKIP_FILE_NAMES:
        return False
    if path.suffix.lower() == ".zip":
        return False
    if path.name.endswith(".pyc"):
        return False
    if rel.endswith(".zip"):
    return False
    
    for part in path.parts:
        if part in SKIP_DIR_NAMES:
            return False

    for marker in SKIP_PATH_PARTS:
        if marker in f"/{rel}/".replace("\\", "/"):
            return False

    # Exclude large CSV except sample
    if rel.endswith(".csv") and rel not in ALLOW_FILES:
        return False

    # Exclude large generated JSON (reproducible by running scripts)
    if rel.startswith("outputs/") and rel.endswith(".json"):
        return False

    # Exclude logs
    if rel.endswith(".log"):
        return False

    return True


def create_zip(dest: Path) -> tuple[list[str], list[str]]:
    """Build the ZIP and return (included, excluded) relative paths."""
    included: list[str] = []
    excluded: list[str] = []

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # Prune directories in-place
            dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]

            for name in files:
                full = Path(root) / name
                rel = full.relative_to(PROJECT_ROOT).as_posix()

                if not should_include(full, rel):
                    excluded.append(rel)
                    continue

                zf.write(full, rel)
                included.append(rel)

    return included, excluded


def main() -> None:
    zip_path = PROJECT_ROOT / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()

    included, excluded = create_zip(zip_path)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    under_limit = size_mb < MAX_SIZE_MB

    print(f"ZIP file: {zip_path}")
    print(f"ZIP size: {size_mb:.2f} MB")
    print(f"Under {MAX_SIZE_MB} MB: {'YES' if under_limit else 'NO'}")
    print(f"\nFiles included: {len(included)}")
    for path in sorted(included)[:40]:
        print(f"  + {path}")
    if len(included) > 40:
        print(f"  ... and {len(included) - 40} more")

    print(f"\nFiles excluded (sample): {len(excluded)}")
    for path in sorted(excluded)[:20]:
        print(f"  - {path}")
    if len(excluded) > 20:
        print(f"  ... and {len(excluded) - 20} more")

    if not under_limit:
        print(
            "\nWARNING: ZIP exceeds target size. "
            "Reduce sample rows or exclude more files.",
            file=__import__("sys").stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
