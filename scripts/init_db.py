#!/usr/bin/env python3
"""
Initialize MongoDB for the environmental IoT sensor data system.

Connects using host/port environment variables, ensures the target database
and collection exist, and creates indexes for time-series and measurement queries.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow imports when running as `python scripts/init_db.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, OperationFailure, ServerSelectionTimeoutError

from mongo_client import connect_with_retry

# Defaults align with portfolio database/collection naming.
DEFAULT_MONGO_HOST = "localhost"
DEFAULT_MONGO_PORT = 27017
DEFAULT_MONGO_DB = "city_environment"
DEFAULT_MONGO_COLLECTION = "sensor_measurements"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class MongoConfig:
    """MongoDB connection and namespace settings."""

    host: str
    port: int
    database: str
    collection: str

    @property
    def uri(self) -> str:
        """Build a MongoDB connection URI from host and port."""
        return f"mongodb://{self.host}:{self.port}"

    @property
    def mongo_uri(self) -> str:
        return self.uri

    @property
    def mongo_db(self) -> str:
        return self.database

    @property
    def mongo_collection(self) -> str:
        return self.collection


class ConfigurationError(ValueError):
    """Raised when required or invalid environment configuration is detected."""


def load_config() -> MongoConfig:
    """
    Load MongoDB settings from environment variables.

    Variables:
        MONGO_HOST: MongoDB hostname (default: localhost)
        MONGO_PORT: MongoDB port (default: 27017)
        MONGO_DB: Database name (default: city_environment)
        MONGO_COLLECTION: Collection name (default: sensor_measurements)
    """
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    load_dotenv(os.path.join(PROJECT_ROOT, ".env.example"), override=False)

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
        raise ConfigurationError(
            f"MONGO_PORT must be between 1 and 65535, got: {port}"
        )

    return MongoConfig(
        host=host,
        port=port,
        database=database,
        collection=collection,
    )


def create_indexes(collection: Collection) -> list[str]:
    """
    Create indexes on timestamp, device, and nested measurement fields.

    Returns:
        List of index names created or already present.
    """
    index_specs: list[tuple[list[tuple[str, int]], dict[str, Any]]] = [
        ([("timestamp", ASCENDING)], {"name": "idx_timestamp"}),
        ([("device", ASCENDING)], {"name": "idx_device"}),
        (
            [("timestamp", ASCENDING), ("device", ASCENDING)],
            {"name": "idx_timestamp_device"},
        ),
        ([("measurements.smoke", ASCENDING)], {"name": "idx_measurements_smoke"}),
        ([("measurements.temp", ASCENDING)], {"name": "idx_measurements_temp"}),
        ([("measurements.co", ASCENDING)], {"name": "idx_measurements_co"}),
    ]

    created: list[str] = []
    for keys, options in index_specs:
        name = collection.create_index(keys, **options)
        created.append(name)
    return created


def main() -> int:
    """
    Initialize the MongoDB database, collection, and indexes.

    Returns:
        0 on success, 1 on configuration, connection, or index errors.
    """
    print("Initializing MongoDB for environmental sensor data...\n")

    # --- Configuration ---
    try:
        config = load_config()
    except ConfigurationError as exc:
        print("ERROR: Invalid configuration.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        print(
            "\nSet MONGO_HOST, MONGO_PORT, MONGO_DB, and MONGO_COLLECTION in .env",
            file=sys.stderr,
        )
        return 1

    print(f"Configuration loaded: {config.host}:{config.port}")
    print(f"  Database:   {config.database}")
    print(f"  Collection: {config.collection}\n")

    # --- Connection ---
    print(f"Connecting to MongoDB at {config.uri} ...")
    try:
        client, collection = connect_with_retry(config)
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        print("ERROR: MongoDB is unavailable.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        print(
            "\nEnsure MongoDB is running, e.g.: docker compose up -d mongodb",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print("ERROR: Connection failure.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1

    print("Connected to MongoDB.")

    database = client[config.database]
    print(f"Database selected: {database.name}")
    print(f"Collection selected: {collection.name}")

    # --- Indexes ---
    print("\nCreating indexes...")
    try:
        index_names = create_indexes(collection)
    except OperationFailure as exc:
        print("ERROR: Failed to create indexes.", file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        client.close()
        return 1

    print("Indexes created:")
    for name in index_names:
        print(f"  - {name}")

    client.close()
    print("\nDatabase initialization complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
