#!/usr/bin/env python3
"""
Create a small sample CSV from the full IoT telemetry file.

Reads data/iot_telemetry_data.csv (must exist locally) and writes
data/sample_iot_telemetry_data.csv for repository submission.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FULL_CSV = PROJECT_ROOT / "data" / "iot_telemetry_data.csv"
SAMPLE_CSV = PROJECT_ROOT / "data" / "sample_iot_telemetry_data.csv"

REQUIRED_COLUMNS = [
    "ts", "device", "co", "humidity", "light", "lpg", "motion", "smoke", "temp",
]


def create_sample(rows: int, source: Path, dest: Path) -> None:
    """Write the first N data rows (plus header) to the sample file."""
    if not source.is_file():
        print(
            f"ERROR: Full CSV not found at {source}\n"
            "Download from Kaggle and save as data/iot_telemetry_data.csv first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    df = pd.read_csv(source, nrows=rows)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        print(f"ERROR: Missing columns: {missing}", file=sys.stderr)
        raise SystemExit(1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"Created: {dest}")
    print(f"Rows:    {len(df)}")
    print(f"Size:    {size_mb:.2f} MB")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create sample IoT telemetry CSV")
    parser.add_argument(
        "-n", "--rows",
        type=int,
        default=10_000,
        help="Number of data rows to copy (default: 10000)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=FULL_CSV,
        help="Path to full CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SAMPLE_CSV,
        help="Path for sample CSV output",
    )
    args = parser.parse_args()

    if args.rows < 1:
        print("ERROR: row count must be at least 1", file=sys.stderr)
        raise SystemExit(1)

    create_sample(args.rows, args.source, args.output)


if __name__ == "__main__":
    main()
