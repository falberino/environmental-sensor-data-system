#!/usr/bin/env python3
"""
Example MongoDB queries for environmental sensor data.

Demonstrates that stored telemetry is accessible for dashboards, monitoring,
and alert-style front-end applications. Results are printed and saved to JSON.
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
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from mongo_client import connect_with_retry

# Demonstration thresholds used when the collection is empty or percentiles
# cannot be computed. Tune these for portfolio demos if needed.
DEMO_THRESHOLD_SMOKE = 0.05
DEMO_THRESHOLD_CO = 0.01
DEMO_THRESHOLD_LPG = 0.01

DEFAULT_MONGO_HOST = "localhost"
DEFAULT_MONGO_PORT = 27017
DEFAULT_MONGO_DB = "city_environment"
DEFAULT_MONGO_COLLECTION = "sensor_measurements"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "example_query_results.json"


class ConfigurationError(ValueError):
    """Raised when environment configuration is missing or invalid."""


@dataclass(frozen=True)
class QueryConfig:
    """MongoDB connection settings for example queries."""

    mongo_host: str
    mongo_port: int
    mongo_db: str
    mongo_collection: str

    @property
    def mongo_uri(self) -> str:
        return f"mongodb://{self.mongo_host}:{self.mongo_port}"


def load_config() -> QueryConfig:
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

    return QueryConfig(
        mongo_host=host,
        mongo_port=port,
        mongo_db=database,
        mongo_collection=collection,
    )


def serialize_results(data: Any) -> Any:
    """Convert MongoDB result documents into JSON-safe structures."""
    if isinstance(data, datetime):
        return data.isoformat()
    if isinstance(data, dict):
        return {key: serialize_results(value) for key, value in data.items()}
    if isinstance(data, list):
        return [serialize_results(item) for item in data]
    return data


def derive_alert_thresholds(collection: Collection) -> dict[str, float]:
    """
    Derive high-reading thresholds from the 90th percentile of each metric.

    Falls back to fixed demonstration values when the collection is empty or
    percentiles cannot be calculated. Suitable for dashboard alert prototypes.
    """
    thresholds = {
        "smoke": DEMO_THRESHOLD_SMOKE,
        "co": DEMO_THRESHOLD_CO,
        "lpg": DEMO_THRESHOLD_LPG,
    }

    if collection.count_documents({}) == 0:
        return thresholds

    for field in thresholds:
        pipeline = [
            {"$match": {f"measurements.{field}": {"$ne": None}}},
            {
                "$group": {
                    "_id": None,
                    "p90": {
                        "$percentile": {
                            "input": f"$measurements.{field}",
                            "p": [0.9],
                            "method": "approximate",
                        }
                    },
                }
            },
        ]
        try:
            rows = list(collection.aggregate(pipeline))
        except Exception:
            continue

        if rows and rows[0].get("p90"):
            value = rows[0]["p90"][0]
            if value is not None:
                thresholds[field] = round(float(value), 6)

    return thresholds


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------


def query_latest_readings(collection: Collection, limit: int = 5) -> list[dict]:
    """Return the most recent sensor readings (default: 5)."""
    pipeline = [
        {"$match": {"measurements": {"$exists": True, "$type": "object"}}},
        {"$sort": {"timestamp": -1}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "device": 1,
                "timestamp": 1,
                "measurements": 1,
            }
        },
    ]
    return serialize_results(list(collection.aggregate(pipeline)))


def query_readings_per_device(collection: Collection) -> list[dict]:
    """Count total readings grouped by device."""
    pipeline = [
        {"$group": {"_id": "$device", "reading_count": {"$sum": 1}}},
        {"$sort": {"reading_count": -1}},
        {
            "$project": {
                "_id": 0,
                "device": "$_id",
                "reading_count": 1,
            }
        },
    ]
    return list(collection.aggregate(pipeline))


def query_avg_temperature_by_device(collection: Collection) -> list[dict]:
    """Calculate average temperature per device."""
    pipeline = [
        {"$match": {"measurements.temp": {"$ne": None}}},
        {
            "$group": {
                "_id": "$device",
                "avg_temp": {"$avg": "$measurements.temp"},
                "readings": {"$sum": 1},
            }
        },
        {"$sort": {"avg_temp": -1}},
        {
            "$project": {
                "_id": 0,
                "device": "$_id",
                "avg_temp": {"$round": ["$avg_temp", 2]},
                "readings": 1,
            }
        },
    ]
    return list(collection.aggregate(pipeline))


def query_avg_humidity_by_device(collection: Collection) -> list[dict]:
    """Calculate average humidity per device."""
    pipeline = [
        {"$match": {"measurements.humidity": {"$ne": None}}},
        {
            "$group": {
                "_id": "$device",
                "avg_humidity": {"$avg": "$measurements.humidity"},
                "readings": {"$sum": 1},
            }
        },
        {"$sort": {"avg_humidity": -1}},
        {
            "$project": {
                "_id": 0,
                "device": "$_id",
                "avg_humidity": {"$round": ["$avg_humidity", 2]},
                "readings": 1,
            }
        },
    ]
    return list(collection.aggregate(pipeline))


def query_high_metric_readings(
    collection: Collection,
    field: str,
    threshold: float,
    limit: int = 20,
) -> list[dict]:
    """Find readings where a measurement exceeds the given threshold."""
    pipeline = [
        {"$match": {f"measurements.{field}": {"$gte": threshold}}},
        {"$sort": {f"measurements.{field}": -1}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "device": 1,
                "timestamp": 1,
                "value": f"$measurements.{field}",
            }
        },
    ]
    return serialize_results(list(collection.aggregate(pipeline)))


def query_readings_by_day(collection: Collection) -> list[dict]:
    """Count readings per calendar day (UTC)."""
    pipeline = [
        {
            "$group": {
                "_id": {
                    "$dateTrunc": {"date": "$timestamp", "unit": "day"},
                },
                "reading_count": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
        {
            "$project": {
                "_id": 0,
                "day": "$_id",
                "reading_count": 1,
            }
        },
    ]
    return serialize_results(list(collection.aggregate(pipeline)))


def query_highest_temperatures(collection: Collection, limit: int = 10) -> list[dict]:
    """Return the highest temperature readings."""
    pipeline = [
        {"$match": {"measurements.temp": {"$ne": None}}},
        {"$sort": {"measurements.temp": -1}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "device": 1,
                "timestamp": 1,
                "temp": "$measurements.temp",
            }
        },
    ]
    return serialize_results(list(collection.aggregate(pipeline)))


def query_highest_smoke_readings(collection: Collection, limit: int = 10) -> list[dict]:
    """Return the highest smoke readings."""
    pipeline = [
        {"$match": {"measurements.smoke": {"$ne": None}}},
        {"$sort": {"measurements.smoke": -1}},
        {"$limit": limit},
        {
            "$project": {
                "_id": 0,
                "device": 1,
                "timestamp": 1,
                "smoke": "$measurements.smoke",
            }
        },
    ]
    return serialize_results(list(collection.aggregate(pipeline)))


def run_all_queries(collection: Collection) -> dict[str, Any]:
    """Execute all example queries and return structured results."""
    thresholds = derive_alert_thresholds(collection)

    return {
        "thresholds_used": thresholds,
        "threshold_note": (
            "High-reading thresholds use the 90th percentile when data exists; "
            "otherwise demonstration defaults apply."
        ),
        "latest_readings": query_latest_readings(collection, limit=5),
        "readings_per_device": query_readings_per_device(collection),
        "avg_temperature_by_device": query_avg_temperature_by_device(collection),
        "avg_humidity_by_device": query_avg_humidity_by_device(collection),
        "high_smoke_readings": query_high_metric_readings(
            collection, "smoke", thresholds["smoke"]
        ),
        "high_co_readings": query_high_metric_readings(
            collection, "co", thresholds["co"]
        ),
        "high_lpg_readings": query_high_metric_readings(
            collection, "lpg", thresholds["lpg"]
        ),
        "readings_by_day": query_readings_by_day(collection),
        "highest_temperature_readings": query_highest_temperatures(collection),
        "highest_smoke_readings": query_highest_smoke_readings(collection),
    }


# ---------------------------------------------------------------------------
# Console output helpers
# ---------------------------------------------------------------------------


def get_measurements(row: dict[str, Any]) -> dict[str, Any]:
    """Return the nested measurements dict, or an empty dict if absent."""
    measurements = row.get("measurements")
    return measurements if isinstance(measurements, dict) else {}


def format_reading_summary(row: dict[str, Any]) -> str:
    """Build a one-line summary for a sensor reading document."""
    m = get_measurements(row)
    return (
        f"{row.get('timestamp')} | {row.get('device')} | "
        f"temp={m.get('temp')} humidity={m.get('humidity')} smoke={m.get('smoke')}"
    )


def print_section(title: str, rows: list[dict] | Any, formatter) -> None:
    """Print a titled query section using a row formatter callable."""
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)
    if not rows:
        print("  (no results)")
        return
    if isinstance(rows, dict):
        formatter(rows)
        return
    for row in rows:
        formatter(row)


def print_all_results(results: dict[str, Any]) -> None:
    """Print human-readable summaries for each query."""
    print("\nAlert thresholds (90th percentile or demo fallback):")
    for metric, value in results["thresholds_used"].items():
        print(f"  {metric}: >= {value}")

    print_section(
        "1. Latest 5 sensor readings",
        results["latest_readings"],
        lambda r: print(f"  {format_reading_summary(r)}"),
    )

    print_section(
        "2. Readings per device",
        results["readings_per_device"][:10],
        lambda r: print(f"  {r.get('device')}: {r.get('reading_count')} readings"),
    )
    if len(results["readings_per_device"]) > 10:
        print(f"  ... and {len(results['readings_per_device']) - 10} more devices")

    print_section(
        "3. Average temperature by device (top 10)",
        results["avg_temperature_by_device"][:10],
        lambda r: print(
            f"  {r.get('device')}: {r.get('avg_temp')}°C ({r.get('readings')} readings)"
        ),
    )

    print_section(
        "4. Average humidity by device (top 10)",
        results["avg_humidity_by_device"][:10],
        lambda r: print(
            f"  {r.get('device')}: {r.get('avg_humidity')}% ({r.get('readings')} readings)"
        ),
    )

    print_section(
        f"5. High smoke readings (>= {results['thresholds_used']['smoke']})",
        results["high_smoke_readings"][:10],
        lambda r: print(
            f"  {r.get('timestamp')} | {r.get('device')} | smoke={r.get('value')}"
        ),
    )

    print_section(
        f"6. High CO readings (>= {results['thresholds_used']['co']})",
        results["high_co_readings"][:10],
        lambda r: print(
            f"  {r.get('timestamp')} | {r.get('device')} | co={r.get('value')}"
        ),
    )

    print_section(
        f"7. High LPG readings (>= {results['thresholds_used']['lpg']})",
        results["high_lpg_readings"][:10],
        lambda r: print(
            f"  {r.get('timestamp')} | {r.get('device')} | lpg={r.get('value')}"
        ),
    )

    print_section(
        "8. Readings by day (first 10 days)",
        results["readings_by_day"][:10],
        lambda r: print(f"  {r.get('day')}: {r.get('reading_count')} readings"),
    )
    if len(results["readings_by_day"]) > 10:
        print(f"  ... and {len(results['readings_by_day']) - 10} more days")

    print_section(
        "9. Highest temperature readings",
        results["highest_temperature_readings"],
        lambda r: print(
            f"  {r.get('timestamp')} | {r.get('device')} | temp={r.get('temp')}°C"
        ),
    )

    print_section(
        "10. Highest smoke readings",
        results["highest_smoke_readings"],
        lambda r: print(
            f"  {r.get('timestamp')} | {r.get('device')} | smoke={r.get('smoke')}"
        ),
    )


def write_results(payload: dict[str, Any], path: Path) -> None:
    """Save query outputs to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def main() -> int:
    """Run example queries, print results, and save JSON output."""
    print("Environmental sensor data — example queries\n")

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
        print("\nStart MongoDB with: docker compose up -d", file=sys.stderr)
        return 1
    except Exception as exc:
        print("ERROR: Connection failure.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    print("Connected to MongoDB.\n")

    doc_count = collection.count_documents({})
    print(f"Database:   {config.mongo_db}")
    print(f"Collection: {config.mongo_collection}")
    print(f"Documents:  {doc_count}")

    if doc_count == 0:
        print("\nWARNING: Collection is empty. No queries to run.")
        print("Load data first: python -m scripts.load_data")

        empty_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "database": config.mongo_db,
            "collection": config.mongo_collection,
            "document_count": 0,
            "queries": {},
            "message": "Collection is empty. Run load_data.py before example queries.",
        }
        write_results(empty_payload, OUTPUT_PATH)
        client.close()
        print(f"\nEmpty results written to: {OUTPUT_PATH}")
        return 1

    print(f"\nRunning 10 example queries on {doc_count:,} documents...")
    query_results = run_all_queries(collection)
    client.close()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": config.mongo_db,
        "collection": config.mongo_collection,
        "document_count": doc_count,
        "queries": query_results,
    }

    print_all_results(query_results)
    write_results(payload, OUTPUT_PATH)

    print(f"\n{'=' * 60}")
    print("All query results saved to:")
    print(f"  {OUTPUT_PATH}")
    print("\nDone. Use the JSON file for reports or further analysis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
