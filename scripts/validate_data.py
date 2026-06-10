#!/usr/bin/env python3
"""
Validate that environmental sensor data was loaded correctly into MongoDB.

Inspects the target collection, prints human-readable checks, and writes a JSON
summary to outputs/validation_summary.json for portfolio evidence.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from mongo_client import connect_with_retry

# Expected nested measurement keys produced by load_data.py
EXPECTED_MEASUREMENT_FIELDS = [
    "co",
    "humidity",
    "light",
    "lpg",
    "motion",
    "smoke",
    "temp",
]

STAT_FIELDS = ("temp", "humidity", "co", "lpg", "smoke")
BOOL_FIELDS = ("light", "motion")

DEFAULT_MONGO_HOST = "localhost"
DEFAULT_MONGO_PORT = 27017
DEFAULT_MONGO_DB = "city_environment"
DEFAULT_MONGO_COLLECTION = "sensor_measurements"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "validation_summary.json"


class ConfigurationError(ValueError):
    """Raised when environment configuration is missing or invalid."""


@dataclass(frozen=True)
class ValidateConfig:
    """MongoDB connection settings for validation."""

    mongo_host: str
    mongo_port: int
    mongo_db: str
    mongo_collection: str

    @property
    def mongo_uri(self) -> str:
        return f"mongodb://{self.mongo_host}:{self.mongo_port}"


def load_config() -> ValidateConfig:
    """Load MongoDB settings from environment variables."""
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.example", override=False)

    host = os.getenv("MONGO_HOST", DEFAULT_MONGO_HOST).strip()
    port_raw = os.getenv("MONGO_PORT", str(DEFAULT_MONGO_PORT)).strip()
    database = os.getenv("MONGO_DB", DEFAULT_MONGO_DB).strip()
    collection = os.getenv("MONGO_COLLECTION", DEFAULT_MONGO_COLLECTION).strip()

    if not host:
        raise ConfigurationError("MONGO_HOST must not be empty.")
    if not database:
        raise ConfigurationError("MONGO_DB must not be empty.")
    if not collection:
        raise ConfigurationError("MONGO_COLLECTION must not be empty.")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"MONGO_PORT must be a valid integer, got: {port_raw!r}"
        ) from exc

    if not (1 <= port <= 65535):
        raise ConfigurationError(f"MONGO_PORT must be between 1 and 65535, got: {port}")

    return ValidateConfig(
        mongo_host=host,
        mongo_port=port,
        mongo_db=database,
        mongo_collection=collection,
    )


def serialize_value(value: Any) -> Any:
    """Convert MongoDB/BSON values into JSON-serializable Python types."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    return value


def get_time_bounds(collection: Collection) -> tuple[str | None, str | None]:
    """Return ISO-formatted first and latest timestamp values."""
    pipeline = [
        {
            "$group": {
                "_id": None,
                "first_timestamp": {"$min": "$timestamp"},
                "latest_timestamp": {"$max": "$timestamp"},
            }
        }
    ]
    result = list(collection.aggregate(pipeline))
    if not result:
        return None, None

    row = result[0]
    first = row.get("first_timestamp")
    latest = row.get("latest_timestamp")
    return (
        first.isoformat() if isinstance(first, datetime) else None,
        latest.isoformat() if isinstance(latest, datetime) else None,
    )


def discover_measurement_fields(collection: Collection) -> list[str]:
    """
    Return measurement field names found in the collection.

    Uses one sample document when available; otherwise falls back to the
    expected schema from the load pipeline.
    """
    sample = collection.find_one({"measurements": {"$exists": True}}, {"measurements": 1})
    if sample and isinstance(sample.get("measurements"), dict):
        return sorted(sample["measurements"].keys())
    return list(EXPECTED_MEASUREMENT_FIELDS)


def compute_basic_statistics(collection: Collection) -> dict[str, Any]:
    """
    Compute min, max, average, and non-null count for selected measurements.

    Fields: measurements.temp, measurements.humidity, measurements.co,
            measurements.lpg, measurements.smoke
    """
    group_stage: dict[str, Any] = {"_id": None}
    for field in STAT_FIELDS:
        path = f"$measurements.{field}"
        group_stage[f"{field}_min"] = {"$min": path}
        group_stage[f"{field}_max"] = {"$max": path}
        group_stage[f"{field}_avg"] = {"$avg": path}
        group_stage[f"{field}_count"] = {
            "$sum": {
                "$cond": [{"$ne": [path, None]}, 1, 0],
            }
        }

    pipeline = [{"$group": group_stage}]
    rows = list(collection.aggregate(pipeline))
    if not rows:
        return {field: None for field in STAT_FIELDS}

    row = rows[0]
    statistics: dict[str, Any] = {}

    for field in STAT_FIELDS:
        avg_val = row.get(f"{field}_avg")
        statistics[field] = {
            "min": row.get(f"{field}_min"),
            "max": row.get(f"{field}_max"),
            "avg": round(avg_val, 4) if avg_val is not None else None,
            "non_null_count": row.get(f"{field}_count", 0),
        }

    return statistics


def compute_null_counts(collection: Collection) -> dict[str, int]:
    """Count null measurement values per field across the collection."""
    null_counts: dict[str, int] = {}
    all_fields = list(STAT_FIELDS) + list(BOOL_FIELDS)

    for field in all_fields:
        path = f"measurements.{field}"
        null_counts[field] = collection.count_documents({path: None})

    return null_counts


def compute_quality_metrics(collection: Collection) -> dict[str, Any]:
    """Summarize quality metadata stored on loaded documents."""
    total_documents = collection.count_documents({})
    with_quality_field = collection.count_documents({"quality": {"$exists": True}})
    invalid_quality_docs = collection.count_documents({"quality.is_valid": False})
    flagged_docs = collection.count_documents({"quality.flags.0": {"$exists": True}})

    return {
        "documents_with_quality_field": with_quality_field,
        "documents_missing_quality_field": total_documents - with_quality_field,
        "documents_with_quality_is_valid_false": invalid_quality_docs,
        "documents_with_quality_flags": flagged_docs,
        "quality_field_present": with_quality_field == total_documents and total_documents > 0,
    }


def compute_device_density(collection: Collection) -> dict[str, Any]:
    """Compute readings per device for density checks."""
    pipeline = [
        {"$group": {"_id": "$device", "readings": {"$sum": 1}}},
        {"$sort": {"readings": -1}},
    ]
    rows = list(collection.aggregate(pipeline))
    counts = {row["_id"]: row["readings"] for row in rows if row.get("_id")}

    if not counts:
        return {
            "readings_per_device": {},
            "min_readings_per_device": 0,
            "max_readings_per_device": 0,
            "avg_readings_per_device": 0.0,
        }

    values = list(counts.values())
    return {
        "readings_per_device": counts,
        "min_readings_per_device": min(values),
        "max_readings_per_device": max(values),
        "avg_readings_per_device": round(sum(values) / len(values), 2),
    }


def assess_data_validity(
    total_documents: int,
    unique_devices: int,
    first_timestamp: str | None,
    latest_timestamp: str | None,
    measurement_fields: list[str],
    example_document: dict[str, Any] | None,
    quality_metrics: dict[str, Any],
) -> bool:
    """
    Return True when loaded documents appear structurally valid for analytics.

    Checks for non-empty collection, required fields, nested measurements,
    quality metadata, and a coherent timestamp range.
    """
    if total_documents == 0:
        return False
    if unique_devices == 0:
        return False
    if not first_timestamp or not latest_timestamp:
        return False
    if first_timestamp > latest_timestamp:
        return False

    expected = set(EXPECTED_MEASUREMENT_FIELDS)
    if not expected.issubset(set(measurement_fields)):
        return False

    if not example_document:
        return False
    if "device" not in example_document or "timestamp" not in example_document:
        return False
    if not isinstance(example_document.get("measurements"), dict):
        return False
    if not quality_metrics.get("quality_field_present"):
        return False

    return True


def assess_query_readiness(
    data_valid: bool,
    total_documents: int,
    quality_metrics: dict[str, Any],
    device_density: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Determine whether the collection is ready for downstream example queries."""
    blockers: list[str] = []

    if total_documents == 0:
        blockers.append("collection is empty")
    if not data_valid:
        blockers.append("structural validation failed")
    if quality_metrics.get("documents_missing_quality_field", 0) > 0:
        blockers.append("some documents are missing the quality field")
    if device_density.get("min_readings_per_device", 0) < 1:
        blockers.append("no per-device readings available")

    return len(blockers) == 0, blockers


def build_validation_report(collection: Collection) -> dict[str, Any]:
    """Collect validation metrics and package them for console and JSON output."""
    total_documents = collection.count_documents({})
    unique_devices = len(collection.distinct("device"))
    first_timestamp, latest_timestamp = get_time_bounds(collection)
    measurement_fields = discover_measurement_fields(collection)

    example_raw = collection.find_one()
    example_document = serialize_value(example_raw) if example_raw else None

    basic_statistics = (
        compute_basic_statistics(collection) if total_documents > 0 else {}
    )
    null_measurement_counts = (
        compute_null_counts(collection) if total_documents > 0 else {}
    )
    quality_metrics = compute_quality_metrics(collection)
    device_density = compute_device_density(collection)

    data_valid = assess_data_validity(
        total_documents=total_documents,
        unique_devices=unique_devices,
        first_timestamp=first_timestamp,
        latest_timestamp=latest_timestamp,
        measurement_fields=measurement_fields,
        example_document=example_document,
        quality_metrics=quality_metrics,
    )
    ready_for_queries, readiness_blockers = assess_query_readiness(
        data_valid=data_valid,
        total_documents=total_documents,
        quality_metrics=quality_metrics,
        device_density=device_density,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_documents": total_documents,
        "unique_devices": unique_devices,
        "first_timestamp": first_timestamp,
        "latest_timestamp": latest_timestamp,
        "timestamp_range_valid": bool(
            first_timestamp and latest_timestamp and first_timestamp <= latest_timestamp
        ),
        "measurement_fields": measurement_fields,
        "basic_statistics": basic_statistics,
        "null_measurement_counts": null_measurement_counts,
        "quality_metrics": quality_metrics,
        "device_density": device_density,
        "example_document": example_document,
        "data_present": total_documents > 0,
        "data_valid": data_valid,
        "ready_for_queries": ready_for_queries,
        "readiness_blockers": readiness_blockers,
    }


def print_report(report: dict[str, Any], config: ValidateConfig) -> None:
    """Print a human-readable validation summary to stdout."""
    print(f"Database:   {config.mongo_db}")
    print(f"Collection: {config.mongo_collection}\n")

    total = report["total_documents"]
    print(f"Total documents:   {total}")
    print(f"Unique devices:    {report['unique_devices']}")
    print(f"First timestamp:   {report['first_timestamp']}")
    print(f"Latest timestamp:  {report['latest_timestamp']}")
    print(f"Timestamp range:   {'valid' if report['timestamp_range_valid'] else 'invalid'}")

    print("\nMeasurement fields:")
    for field in report["measurement_fields"]:
        print(f"  - {field}")

    print("\nBasic statistics:")
    stats = report.get("basic_statistics") or {}
    for field in STAT_FIELDS:
        field_stats = stats.get(field)
        if not field_stats:
            print(f"  measurements.{field}: no data")
            continue
        print(
            f"  measurements.{field}: "
            f"min={field_stats['min']}, "
            f"max={field_stats['max']}, "
            f"avg={field_stats['avg']}, "
            f"non_null_count={field_stats['non_null_count']}"
        )

    print("\nNull measurement counts:")
    null_counts = report.get("null_measurement_counts") or {}
    for field in list(STAT_FIELDS) + list(BOOL_FIELDS):
        print(f"  measurements.{field}: null_count={null_counts.get(field, 0)}")

    quality = report.get("quality_metrics") or {}
    print("\nQuality field checks:")
    print(f"  quality field present on all docs: {quality.get('quality_field_present')}")
    print(
        "  documents with quality.is_valid=false: "
        f"{quality.get('documents_with_quality_is_valid_false', 0)}"
    )
    print(
        f"  documents with quality flags: "
        f"{quality.get('documents_with_quality_flags', 0)}"
    )

    density = report.get("device_density") or {}
    print("\nDevice density:")
    print(f"  min readings per device: {density.get('min_readings_per_device', 0)}")
    print(f"  max readings per device: {density.get('max_readings_per_device', 0)}")
    print(f"  avg readings per device: {density.get('avg_readings_per_device', 0)}")

    print("\nExample document:")
    if report["example_document"]:
        print(json.dumps(report["example_document"], indent=2, default=str))
    else:
        print("  (none — collection is empty)")


def print_conclusion(report: dict[str, Any]) -> None:
    """Print a short pass/fail style conclusion for the operator."""
    print("\n--- Conclusion ---")

    if report["data_present"]:
        print("Database contains data: YES")
    else:
        print("Database contains data: NO")
        print("Inserted data appears valid: N/A (collection is empty)")
        print("Ready for example queries: NO")
        print("\nRun `python scripts/load_data.py` after placing the CSV file.")
        return

    if report["data_valid"]:
        print("Inserted data appears valid: YES")
    else:
        print("Inserted data appears valid: NO")
        print("Review documents and re-run the load pipeline if needed.")

    if report["ready_for_queries"]:
        print("Ready for example queries: YES")
        print("You can run: python scripts/example_queries.py")
    else:
        print("Ready for example queries: NO")
        blockers = report.get("readiness_blockers") or []
        if blockers:
            print("Blockers:")
            for blocker in blockers:
                print(f"  - {blocker}")


def write_summary(report: dict[str, Any], path: Path) -> None:
    """Write the validation JSON report to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)


def main() -> int:
    """Connect to MongoDB, validate loaded data, and write the summary report."""
    print("Environmental sensor data — validation\n")

    try:
        config = load_config()
    except ConfigurationError as exc:
        print("ERROR: Invalid configuration.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    print(f"Connecting to MongoDB at {config.mongo_uri} ...")
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

    if collection.count_documents({}) == 0:
        print("WARNING: Collection is empty.\n")
        report = build_validation_report(collection)
        print_report(report, config)
        print_conclusion(report)
        write_summary(report, SUMMARY_PATH)
        client.close()
        print(f"\nValidation summary written to: {SUMMARY_PATH}")
        return 1

    report = build_validation_report(collection)
    print_report(report, config)
    print_conclusion(report)
    write_summary(report, SUMMARY_PATH)
    client.close()

    print(f"\nValidation summary written to: {SUMMARY_PATH}")

    if report["ready_for_queries"]:
        print("\nValidation PASSED.")
        return 0

    print("\nValidation completed with issues.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
