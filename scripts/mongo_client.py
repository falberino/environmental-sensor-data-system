"""
Shared MongoDB connection helper with retries for Docker startup timing.
"""

from __future__ import annotations

import time
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError


def _resolve_names(config: Any) -> tuple[str, str, str]:
    """Read URI, database, and collection from config objects with varying field names."""
    uri = getattr(config, "mongo_uri", None) or config.uri
    database = getattr(config, "mongo_db", None) or config.database
    collection = getattr(config, "mongo_collection", None) or config.collection
    return uri, database, collection


def connect_with_retry(
    config: Any,
    *,
    max_attempts: int = 10,
    delay_seconds: float = 2.0,
) -> tuple[MongoClient, Collection]:
    """
    Connect to MongoDB and return the configured collection.

    Retries when MongoDB is still starting (common with Docker Compose).
    """
    uri, database, collection_name = _resolve_names(config)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            collection = client[database][collection_name]
            return client, collection
        except (ConnectionFailure, ServerSelectionTimeoutError, OSError) as exc:
            last_error = exc
            if attempt < max_attempts:
                print(
                    f"MongoDB not ready (attempt {attempt}/{max_attempts}), "
                    f"retrying in {delay_seconds:.0f}s..."
                )
                time.sleep(delay_seconds)

    assert last_error is not None
    raise last_error
