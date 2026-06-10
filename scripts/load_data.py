#!/usr/bin/env python3
"""
Load environmental IoT telemetry CSV data into MongoDB in recoverable batches.

Reads the dataset in chunks, transforms rows into structured documents with nested
measurements and explicit quality metadata, and upserts by deterministic _id.
Checkpointing allows resuming after interruption without reprocessing earlier batches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from pymongo import ReplaceOne
from pymongo.collection import Collection
from pymongo.errors import (
    AutoReconnect,
    BulkWriteError,
    ConnectionFailure,
    NetworkTimeout,
    ServerSelectionTimeoutError,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mongo_client import connect_with_retry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = [
    "ts",
    "device",
    "co",
    "humidity",
    "light",
    "lpg",
    "motion",
    "smoke",
    "temp",
]

FLOAT_MEASUREMENTS = ("co", "humidity", "lpg", "smoke", "temp")
BOOL_MEASUREMENTS = ("light", "motion")

SOURCE_METADATA = {
    "dataset": "Environmental Sensor Telemetry Data",
    "platform": "Kaggle",
    "url": "https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k",
}

DEFAULT_MONGO_HOST = "localhost"
DEFAULT_MONGO_PORT = 27017
DEFAULT_MONGO_DB = "city_environment"
DEFAULT_MONGO_COLLECTION = "sensor_measurements"
DEFAULT_DATA_FILE = "data/sample_iot_telemetry_data.csv"
DEFAULT_BATCH_SIZE = 1000
DEFAULT_CHECKPOINT_PATH = "outputs/load_checkpoint.json"
DEFAULT_MAX_WRITE_RETRIES = 3
DEFAULT_WRITE_RETRY_DELAY_SECONDS = 2.0

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "load_summary.json"
FAILURES_PATH = PROJECT_ROOT / "outputs" / "load_failures.json"
INVALID_ROWS_PATH = PROJECT_ROOT / "outputs" / "invalid_rows.jsonl"
QUALITY_REPORT_PATH = PROJECT_ROOT / "outputs" / "data_quality_report.json"

RETRYABLE_WRITE_ERRORS = (
    AutoReconnect,
    BulkWriteError,
    ConnectionFailure,
    NetworkTimeout,
    ServerSelectionTimeoutError,
)

QUALITY_CONSEQUENCES = (
    "Rejected rows (missing/invalid ts or device) are not stored in MongoDB; "
    "they are logged to outputs/invalid_rows.jsonl and excluded from analytics. "
    "Rows with invalid or missing measurements are stored with null values and "
    "quality flags so downstream queries can filter or warn on unreliable readings. "
    "Sparse per-device data reduces confidence in device-level averages. "
    "Dense bursts can skew time-window aggregations unless queries use limits. "
    "High variance across devices requires per-device filters rather than global thresholds."
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigurationError(ValueError):
    """Raised when environment configuration is missing or invalid."""


@dataclass(frozen=True)
class LoadConfig:
    """Runtime settings for the batch CSV load pipeline."""

    mongo_host: str
    mongo_port: int
    mongo_db: str
    mongo_collection: str
    data_file: Path
    batch_size: int
    checkpoint_path: Path
    max_batches: int | None
    reset_checkpoint: bool

    @property
    def mongo_uri(self) -> str:
        return f"mongodb://{self.mongo_host}:{self.mongo_port}"


@dataclass
class QualityCounters:
    """Cumulative counters for data quality reporting."""

    total_rows_seen: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    rows_with_quality_flags: int = 0
    invalid_measurement_values: dict[str, int] = field(default_factory=dict)
    rejected_reasons: dict[str, int] = field(default_factory=dict)
    device_counts: dict[str, int] = field(default_factory=dict)
    batch_quality_status: list[dict[str, Any]] = field(default_factory=list)

    def merge_from_checkpoint(self, data: dict[str, Any]) -> None:
        """Restore cumulative counters from a prior checkpoint."""
        self.total_rows_seen = int(data.get("rows_processed", 0))
        self.rows_loaded = int(data.get("rows_loaded", 0))
        self.rows_rejected = int(data.get("rows_rejected", 0))
        self.rows_with_quality_flags = int(data.get("rows_with_quality_flags", 0))
        self.invalid_measurement_values = dict(data.get("invalid_measurement_values", {}))
        self.rejected_reasons = dict(data.get("rejected_reasons", {}))
        self.device_counts = dict(data.get("device_counts", {}))
        self.batch_quality_status = list(data.get("batch_quality_status", []))

    def to_checkpoint_fields(self) -> dict[str, Any]:
        """Serialize counter state for checkpoint persistence."""
        return {
            "rows_processed": self.total_rows_seen,
            "rows_loaded": self.rows_loaded,
            "rows_rejected": self.rows_rejected,
            "rows_with_quality_flags": self.rows_with_quality_flags,
            "invalid_measurement_values": self.invalid_measurement_values,
            "rejected_reasons": self.rejected_reasons,
            "device_counts": self.device_counts,
            "batch_quality_status": self.batch_quality_status,
        }


@dataclass
class RowTransformResult:
    """Outcome of transforming one CSV row."""

    document: dict[str, Any] | None = None
    rejected: bool = False
    rejection_reason: str | None = None
    raw_row: dict[str, Any] | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for recoverable batch loading."""
    parser = argparse.ArgumentParser(
        description="Load environmental sensor CSV data into MongoDB in recoverable batches."
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Process only this many batches in this run, then stop successfully.",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Ignore any existing checkpoint and start from the first batch.",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=Path,
        default=None,
        help=f"Checkpoint file path (default: {DEFAULT_CHECKPOINT_PATH}).",
    )
    return parser.parse_args(argv)


def load_config(args: argparse.Namespace) -> LoadConfig:
    """
    Load pipeline settings from environment variables and CLI arguments.

    Variables:
        MONGO_HOST, MONGO_PORT, MONGO_DB, MONGO_COLLECTION
        DATA_FILE (default: data/sample_iot_telemetry_data.csv)
        BATCH_SIZE (default: 1000)
    """
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.example", override=False)

    host = os.getenv("MONGO_HOST", DEFAULT_MONGO_HOST).strip()
    port_raw = os.getenv("MONGO_PORT", str(DEFAULT_MONGO_PORT)).strip()
    database = os.getenv("MONGO_DB", DEFAULT_MONGO_DB).strip()
    collection = os.getenv("MONGO_COLLECTION", DEFAULT_MONGO_COLLECTION).strip()
    data_file = os.getenv("DATA_FILE", DEFAULT_DATA_FILE).strip()
    batch_raw = os.getenv("BATCH_SIZE", str(DEFAULT_BATCH_SIZE)).strip()

    if not host:
        raise ConfigurationError("MONGO_HOST must not be empty.")
    if not database:
        raise ConfigurationError("MONGO_DB must not be empty.")
    if not collection:
        raise ConfigurationError("MONGO_COLLECTION must not be empty.")
    if not data_file:
        raise ConfigurationError("DATA_FILE must not be empty.")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"MONGO_PORT must be a valid integer, got: {port_raw!r}"
        ) from exc

    if not (1 <= port <= 65535):
        raise ConfigurationError(f"MONGO_PORT must be between 1 and 65535, got: {port}")

    try:
        batch_size = int(batch_raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"BATCH_SIZE must be a valid integer, got: {batch_raw!r}"
        ) from exc

    if batch_size < 1:
        raise ConfigurationError(f"BATCH_SIZE must be at least 1, got: {batch_size}")

    if args.max_batches is not None and args.max_batches < 1:
        raise ConfigurationError(
            f"--max-batches must be at least 1, got: {args.max_batches}"
        )

    path = Path(data_file)
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    checkpoint = args.checkpoint_path or (PROJECT_ROOT / DEFAULT_CHECKPOINT_PATH)
    if not checkpoint.is_absolute():
        checkpoint = PROJECT_ROOT / checkpoint

    return LoadConfig(
        mongo_host=host,
        mongo_port=port,
        mongo_db=database,
        mongo_collection=collection,
        data_file=path,
        batch_size=batch_size,
        checkpoint_path=checkpoint,
        max_batches=args.max_batches,
        reset_checkpoint=args.reset_checkpoint,
    )


# ---------------------------------------------------------------------------
# Data transformation
# ---------------------------------------------------------------------------


def is_missing(value: Any) -> bool:
    """Return True if a CSV cell is null, NaN, or an empty string."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "nan", "none", "null"}:
        return True
    return False


def parse_float_measurement(value: Any) -> tuple[float | None, str | None]:
    """
    Parse a numeric sensor reading.

    Returns (parsed_value, quality_flag). A flag is set when the cell is missing
    or present but not parseable as a number.
    """
    if is_missing(value):
        return None, "missing_measurement"
    if isinstance(value, bool):
        return float(value), None
    try:
        return float(value), None
    except (TypeError, ValueError):
        text = str(value).strip().lower()
        if text in {"true", "yes"}:
            return 1.0, None
        if text in {"false", "no"}:
            return 0.0, None
        try:
            return float(text), None
        except ValueError:
            return None, "invalid_numeric"


def parse_bool_measurement(value: Any) -> tuple[bool | None, str | None]:
    """
    Parse light/motion values as booleans.

    Returns (parsed_value, quality_flag). A flag is set when the cell is missing
    or present but not parseable as a boolean.
    """
    if is_missing(value):
        return None, "missing_measurement"
    if isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (0, 0.0):
            return False, None
        if value in (1, 1.0):
            return True, None
        return None, "invalid_boolean"
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True, None
    if text in {"false", "0", "no"}:
        return False, None
    return None, "invalid_boolean"


def parse_measurements(row: dict[str, Any]) -> tuple[dict[str, Any], list[str], int]:
    """Build nested measurements and collect quality flags for invalid/missing values."""
    measurements: dict[str, Any] = {}
    flags: list[str] = []
    invalid_count = 0

    for field_name in FLOAT_MEASUREMENTS:
        parsed, issue = parse_float_measurement(row.get(field_name))
        measurements[field_name] = parsed
        if issue:
            flag = f"{issue}_{field_name}"
            flags.append(flag)
            invalid_count += 1

    for field_name in BOOL_MEASUREMENTS:
        parsed, issue = parse_bool_measurement(row.get(field_name))
        measurements[field_name] = parsed
        if issue:
            flag = f"{issue}_{field_name}"
            flags.append(flag)
            invalid_count += 1

    return measurements, flags, invalid_count


def unix_ts_to_datetime(ts_value: float) -> datetime:
    """
    Convert Unix epoch to UTC datetime.

    Values above 1e12 are treated as milliseconds; otherwise seconds.
    """
    ts_float = float(ts_value)
    if ts_float > 1e12:
        ts_float /= 1000.0
    return datetime.fromtimestamp(ts_float, tz=timezone.utc)


def build_document_id(
    timestamp_unix: float,
    device: str,
    measurements: dict[str, Any],
) -> str:
    """
    Build a deterministic SHA-256 hex id from timestamp, device, and measurements.

    Using a stable JSON payload ensures the same reading always maps to the same _id.
    """
    payload = {
        "timestamp_unix": timestamp_unix,
        "device": device,
        "measurements": measurements,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def transform_row(row: dict[str, Any], ingested_at: datetime) -> RowTransformResult:
    """
    Convert one CSV row to a MongoDB document or a rejection record.

    Missing or invalid ts/device reject the row entirely. Invalid or missing
    measurements are stored as null with explicit quality flags.
    """
    raw_snapshot = {key: row.get(key) for key in REQUIRED_COLUMNS}

    if is_missing(row.get("ts")):
        return RowTransformResult(
            rejected=True,
            rejection_reason="missing_ts",
            raw_row=raw_snapshot,
        )

    try:
        timestamp_unix = float(row["ts"])
    except (TypeError, ValueError):
        return RowTransformResult(
            rejected=True,
            rejection_reason="invalid_ts",
            raw_row=raw_snapshot,
        )

    if is_missing(row.get("device")):
        return RowTransformResult(
            rejected=True,
            rejection_reason="missing_device",
            raw_row=raw_snapshot,
        )

    device = str(row["device"]).strip()
    if not device:
        return RowTransformResult(
            rejected=True,
            rejection_reason="empty_device",
            raw_row=raw_snapshot,
        )

    measurements, flags, invalid_count = parse_measurements(row)
    doc_id = build_document_id(timestamp_unix, device, measurements)

    document = {
        "_id": doc_id,
        "timestamp": unix_ts_to_datetime(timestamp_unix),
        "timestamp_unix": timestamp_unix,
        "device": device,
        "measurements": measurements,
        "quality": {
            "is_valid": len(flags) == 0,
            "flags": flags,
            "invalid_measurement_count": invalid_count,
        },
        "source": dict(SOURCE_METADATA),
        "ingested_at": ingested_at,
    }
    return RowTransformResult(document=document)


def row_to_document(row: dict[str, Any], ingested_at: datetime) -> dict[str, Any] | None:
    """Backward-compatible helper returning only the document when loadable."""
    result = transform_row(row, ingested_at)
    return result.document


def validate_columns(columns: pd.Index) -> None:
    """Raise ValueError when the CSV header is missing required columns."""
    missing = [col for col in REQUIRED_COLUMNS if col not in columns]
    if missing:
        raise ValueError(
            f"CSV is missing required columns: {missing}. "
            f"Expected: {REQUIRED_COLUMNS}"
        )


def chunk_to_results(
    chunk: pd.DataFrame,
    ingested_at: datetime,
) -> list[RowTransformResult]:
    """Transform a DataFrame chunk into per-row transformation results."""
    return [transform_row(row, ingested_at) for row in chunk.to_dict(orient="records")]


# ---------------------------------------------------------------------------
# Checkpointing and reporting
# ---------------------------------------------------------------------------


def compute_file_fingerprint(path: Path) -> str:
    """Build a stable fingerprint from file metadata for checkpoint validation."""
    stat = path.stat()
    payload = f"{path.resolve()}:{stat.st_size}:{int(stat.st_mtime)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_checkpoint(path: Path) -> dict[str, Any] | None:
    """Read an existing checkpoint file, if present."""
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    """Persist checkpoint state after a successful batch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def append_invalid_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Append rejected row records as JSON lines."""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON report to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def append_failure_record(path: Path, record: dict[str, Any]) -> None:
    """Append a failed batch entry to the failures log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if path.is_file():
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
            existing = list(data.get("failures", []))
    existing.append(record)
    write_json(path, {"failures": existing})


def record_batch_quality(
    counters: QualityCounters,
    batch_number: int,
    results: list[RowTransformResult],
) -> None:
    """Update cumulative quality counters from one batch."""
    rows_read = len(results)
    documents = [r.document for r in results if r.document is not None]
    rejected = [r for r in results if r.rejected]
    flagged = [d for d in documents if not d["quality"]["is_valid"]]

    counters.total_rows_seen += rows_read
    counters.rows_loaded += len(documents)
    counters.rows_rejected += len(rejected)
    counters.rows_with_quality_flags += len(flagged)

    for result in rejected:
        reason = result.rejection_reason or "unknown"
        counters.rejected_reasons[reason] = counters.rejected_reasons.get(reason, 0) + 1

    for document in documents:
        device = document["device"]
        counters.device_counts[device] = counters.device_counts.get(device, 0) + 1
        for flag in document["quality"]["flags"]:
            counters.invalid_measurement_values[flag] = (
                counters.invalid_measurement_values.get(flag, 0) + 1
            )

    counters.batch_quality_status.append(
        {
            "batch_number": batch_number,
            "rows_read": rows_read,
            "documents_built": len(documents),
            "invalid_rows": len(rejected),
            "rows_with_quality_flags": len(flagged),
        }
    )


def build_quality_report(counters: QualityCounters, config: LoadConfig) -> dict[str, Any]:
    """Package cumulative quality metrics for operators and downstream docs."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_file": str(config.data_file),
        "total_rows_seen": counters.total_rows_seen,
        "rows_loaded": counters.rows_loaded,
        "rows_rejected": counters.rows_rejected,
        "rows_with_quality_flags": counters.rows_with_quality_flags,
        "invalid_measurement_values": counters.invalid_measurement_values,
        "rejected_reasons": counters.rejected_reasons,
        "device_counts": counters.device_counts,
        "batch_quality_status": counters.batch_quality_status,
        "consequences": QUALITY_CONSEQUENCES,
    }


# ---------------------------------------------------------------------------
# MongoDB operations
# ---------------------------------------------------------------------------


def upsert_batch(collection: Collection, documents: list[dict[str, Any]]) -> int:
    """
    Upsert a batch of documents using bulk_write.

    Returns:
        Number of records inserted or updated in this batch.
    """
    if not documents:
        return 0

    operations = [
        ReplaceOne({"_id": doc["_id"]}, doc, upsert=True) for doc in documents
    ]
    result = collection.bulk_write(operations, ordered=False)
    return result.upserted_count + result.modified_count


def upsert_batch_with_retry(
    collection: Collection,
    documents: list[dict[str, Any]],
    *,
    max_attempts: int = DEFAULT_MAX_WRITE_RETRIES,
    delay_seconds: float = DEFAULT_WRITE_RETRY_DELAY_SECONDS,
) -> int:
    """Retry MongoDB batch writes for transient PyMongo errors."""
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return upsert_batch(collection, documents)
        except RETRYABLE_WRITE_ERRORS as exc:
            last_error = exc
            if attempt < max_attempts:
                print(
                    f"  WARNING: batch write failed (attempt {attempt}/{max_attempts}): "
                    f"{exc}. Retrying in {delay_seconds:.0f}s..."
                )
                time.sleep(delay_seconds)

    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def initialize_run_state(
    config: LoadConfig,
) -> tuple[int, QualityCounters, bool]:
    """
    Prepare checkpoint state for this run.

    Returns:
        last_successful_batch, quality counters, and whether output files were reset.
    """
    counters = QualityCounters()
    outputs_reset = False

    if config.reset_checkpoint:
        if config.checkpoint_path.is_file():
            config.checkpoint_path.unlink()
        for path in (INVALID_ROWS_PATH, FAILURES_PATH):
            if path.is_file():
                path.unlink()
        outputs_reset = True
        return 0, counters, outputs_reset

    checkpoint = load_checkpoint(config.checkpoint_path)
    if not checkpoint:
        return 0, counters, outputs_reset

    expected_fingerprint = compute_file_fingerprint(config.data_file)
    if checkpoint.get("file_fingerprint") != expected_fingerprint:
        raise ConfigurationError(
            "Checkpoint fingerprint does not match the current CSV file. "
            "Use --reset-checkpoint to start a fresh load."
        )
    if str(config.data_file) != checkpoint.get("data_file"):
        raise ConfigurationError(
            "Checkpoint data_file does not match the configured DATA_FILE. "
            "Use --reset-checkpoint to start a fresh load."
        )

    counters.merge_from_checkpoint(checkpoint)
    return int(checkpoint.get("last_successful_batch", 0)), counters, outputs_reset


def main(argv: list[str] | None = None) -> int:
    """Run the recoverable CSV-to-MongoDB batch load pipeline."""
    start_time = datetime.now(timezone.utc)
    pipeline_start = time.perf_counter()

    print("Environmental sensor data — recoverable batch load\n")

    args = parse_args(argv)

    try:
        config = load_config(args)
    except ConfigurationError as exc:
        print("ERROR: Invalid configuration.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    if not config.data_file.is_file():
        print("ERROR: CSV file not found.", file=sys.stderr)
        print(
            f"\nConfigured path: {config.data_file}\n\n"
            "Included in the repo:\n"
            "  data/sample_iot_telemetry_data.csv\n"
            "  (run: python scripts/create_sample_data.py)\n\n"
            "Full Kaggle dataset (optional):\n"
            "  data/iot_telemetry_data.csv\n"
            "  Set DATA_FILE=data/iot_telemetry_data.csv in .env",
            file=sys.stderr,
        )
        return 1

    file_fingerprint = compute_file_fingerprint(config.data_file)

    try:
        last_successful_batch, counters, outputs_reset = initialize_run_state(config)
    except ConfigurationError as exc:
        print("ERROR: Checkpoint conflict.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    print(f"Data file:          {config.data_file}")
    print(f"MongoDB:            {config.mongo_uri}")
    print(f"Database:           {config.mongo_db}")
    print(f"Collection:         {config.mongo_collection}")
    print(f"Batch size:         {config.batch_size}")
    print(f"Checkpoint:         {config.checkpoint_path}")
    print(f"Resume after batch: {last_successful_batch}")
    if config.max_batches is not None:
        print(f"Max batches (run):  {config.max_batches}")
    if config.reset_checkpoint:
        print("Checkpoint reset:   yes")
    print()

    print("Connecting to MongoDB...")
    try:
        client, collection = connect_with_retry(config)
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        print("ERROR: MongoDB is unavailable.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        print("\nStart MongoDB with: docker compose up -d mongodb", file=sys.stderr)
        return 1
    except Exception as exc:
        print("ERROR: Connection failure.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    print("Connected to MongoDB.\n")

    ingested_at = datetime.now(timezone.utc)
    batch_number = 0
    batches_processed_this_run = 0
    total_upserted_this_run = 0
    columns_validated = False
    stopped_early = False

    print("Loading CSV in batches...")

    try:
        reader = pd.read_csv(config.data_file, chunksize=config.batch_size)

        for chunk in reader:
            batch_number += 1

            if not columns_validated:
                validate_columns(chunk.columns)
                columns_validated = True

            if batch_number <= last_successful_batch:
                print(f"  Batch {batch_number}: skipped (already checkpointed)")
                continue

            results = chunk_to_results(chunk, ingested_at)
            documents = [r.document for r in results if r.document is not None]
            rejected_rows = [
                {
                    "rejection_reason": r.rejection_reason,
                    "row": r.raw_row,
                    "batch_number": batch_number,
                }
                for r in results
                if r.rejected
            ]

            rows_in_batch = len(results)
            invalid_rows = len(rejected_rows)
            rows_with_flags = sum(
                1 for doc in documents if not doc["quality"]["is_valid"]
            )

            try:
                upserted = upsert_batch_with_retry(collection, documents)
            except RETRYABLE_WRITE_ERRORS as exc:
                failure_record = {
                    "batch_number": batch_number,
                    "attempts": DEFAULT_MAX_WRITE_RETRIES,
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "rows_in_batch": rows_in_batch,
                    "documents_count": len(documents),
                }
                append_failure_record(FAILURES_PATH, failure_record)
                print(
                    "\nERROR: MongoDB batch write failed after retries.",
                    file=sys.stderr,
                )
                print(f"  Batch: {batch_number}", file=sys.stderr)
                print(f"  Details: {exc}", file=sys.stderr)
                print(
                    f"  Failure logged to: {FAILURES_PATH}",
                    file=sys.stderr,
                )
                print(
                    "  Checkpoint was NOT advanced. Re-run the same command to retry "
                    "this batch.",
                    file=sys.stderr,
                )
                client.close()
                return 1

            record_batch_quality(counters, batch_number, results)
            append_invalid_rows(INVALID_ROWS_PATH, rejected_rows)

            checkpoint_payload = {
                "data_file": str(config.data_file),
                "file_fingerprint": file_fingerprint,
                "last_successful_batch": batch_number,
                **counters.to_checkpoint_fields(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            save_checkpoint(config.checkpoint_path, checkpoint_payload)
            write_quality_report = build_quality_report(counters, config)
            write_json(QUALITY_REPORT_PATH, write_quality_report)

            total_upserted_this_run += upserted
            batches_processed_this_run += 1

            print(
                f"  Batch {batch_number}: "
                f"rows read={rows_in_batch}, "
                f"documents built={len(documents)}, "
                f"invalid rows={invalid_rows}, "
                f"rows with quality flags={rows_with_flags}, "
                f"inserted/updated={upserted}"
            )
            print(f"    checkpoint saved to: {config.checkpoint_path}")

            if config.max_batches is not None and batches_processed_this_run >= config.max_batches:
                stopped_early = True
                print(
                    f"\nStopped intentionally after {config.max_batches} batch(es) "
                    "in this run."
                )
                break

    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        client.close()
        return 1
    except pd.errors.EmptyDataError:
        print("ERROR: CSV file is empty.", file=sys.stderr)
        client.close()
        return 1
    except Exception as exc:
        print(f"ERROR: Failed while reading CSV: {exc}", file=sys.stderr)
        client.close()
        return 1

    client.close()

    end_time = datetime.now(timezone.utc)
    duration = round(time.perf_counter() - pipeline_start, 3)

    summary = {
        "data_file": str(config.data_file),
        "database": config.mongo_db,
        "collection": config.mongo_collection,
        "batch_size": config.batch_size,
        "checkpoint_path": str(config.checkpoint_path),
        "last_successful_batch": batch_number if batches_processed_this_run else last_successful_batch,
        "batches_processed_this_run": batches_processed_this_run,
        "total_rows_seen": counters.total_rows_seen,
        "rows_loaded": counters.rows_loaded,
        "rows_rejected": counters.rows_rejected,
        "rows_with_quality_flags": counters.rows_with_quality_flags,
        "total_inserted_or_updated_this_run": total_upserted_this_run,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_seconds": duration,
        "stopped_early": stopped_early,
        "reset_checkpoint": config.reset_checkpoint,
        "outputs_reset": outputs_reset,
    }
    write_json(SUMMARY_PATH, summary)

    print("\n--- Load run complete ---")
    print(f"Batches processed this run:   {batches_processed_this_run}")
    print(f"Rows seen (cumulative):       {counters.total_rows_seen}")
    print(f"Rows loaded (cumulative):     {counters.rows_loaded}")
    print(f"Rows rejected (cumulative):   {counters.rows_rejected}")
    print(f"Rows with quality flags:      {counters.rows_with_quality_flags}")
    print(f"Inserted/updated this run:    {total_upserted_this_run}")
    print(f"Duration:                     {duration}s")
    print(f"Checkpoint:                   {config.checkpoint_path}")
    print(f"Quality report:               {QUALITY_REPORT_PATH}")
    print(f"Summary written to:           {SUMMARY_PATH}")

    if stopped_early:
        print(
            "\nPartial load completed successfully. Re-run without --reset-checkpoint "
            "to continue from the next batch."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
