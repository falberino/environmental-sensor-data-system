"""Lightweight tests for CSV transformation and checkpoint behavior."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from load_data import (  # noqa: E402
    build_document_id,
    compute_file_fingerprint,
    initialize_run_state,
    load_config,
    parse_args,
    save_checkpoint,
    transform_row,
)
from load_data import LoadConfig  # noqa: E402


@pytest.fixture
def ingested_at() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_invalid_timestamp_row_is_rejected(ingested_at: datetime) -> None:
    result = transform_row(
        {
            "ts": "not-a-timestamp",
            "device": "aa:bb:cc:dd:ee:ff",
            "co": 1.0,
            "humidity": 50.0,
            "light": "false",
            "lpg": 0.1,
            "motion": "false",
            "smoke": 0.2,
            "temp": 22.0,
        },
        ingested_at,
    )

    assert result.rejected is True
    assert result.rejection_reason == "invalid_ts"
    assert result.document is None


def test_invalid_measurement_creates_quality_flag(ingested_at: datetime) -> None:
    result = transform_row(
        {
            "ts": 1594512094.0,
            "device": "aa:bb:cc:dd:ee:ff",
            "co": "bad-value",
            "humidity": 50.0,
            "light": "maybe",
            "lpg": 0.1,
            "motion": "false",
            "smoke": 0.2,
            "temp": 22.0,
        },
        ingested_at,
    )

    assert result.rejected is False
    assert result.document is not None
    quality = result.document["quality"]
    assert quality["is_valid"] is False
    assert "invalid_numeric_co" in quality["flags"]
    assert "invalid_boolean_light" in quality["flags"]
    assert result.document["measurements"]["co"] is None
    assert result.document["measurements"]["light"] is None


def test_deterministic_id_prevents_duplicates(ingested_at: datetime) -> None:
    row = {
        "ts": 1594512094.0,
        "device": "aa:bb:cc:dd:ee:ff",
        "co": 0.1,
        "humidity": 50.0,
        "light": "false",
        "lpg": 0.1,
        "motion": "false",
        "smoke": 0.2,
        "temp": 22.0,
    }
    first = transform_row(row, ingested_at).document
    second = transform_row(row, ingested_at).document

    assert first is not None and second is not None
    assert first["_id"] == second["_id"]
    assert first["_id"] == build_document_id(
        first["timestamp_unix"],
        first["device"],
        first["measurements"],
    )


def test_checkpoint_advances_only_after_success(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("ts,device,co,humidity,light,lpg,motion,smoke,temp\n", encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"

    fingerprint = compute_file_fingerprint(csv_path)
    save_checkpoint(
        checkpoint_path,
        {
            "data_file": str(csv_path),
            "file_fingerprint": fingerprint,
            "last_successful_batch": 1,
            "rows_processed": 1000,
            "rows_loaded": 999,
            "rows_rejected": 1,
            "rows_with_quality_flags": 0,
            "invalid_measurement_values": {},
            "rejected_reasons": {"missing_ts": 1},
            "device_counts": {"aa:bb:cc:dd:ee:ff": 999},
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )

    config = LoadConfig(
        mongo_host="localhost",
        mongo_port=27017,
        mongo_db="city_environment",
        mongo_collection="sensor_measurements",
        data_file=csv_path,
        batch_size=1000,
        checkpoint_path=checkpoint_path,
        max_batches=None,
        reset_checkpoint=False,
    )

    last_batch, counters, _ = initialize_run_state(config)
    assert last_batch == 1
    assert counters.rows_loaded == 999
    assert counters.rejected_reasons["missing_ts"] == 1

    args = parse_args(["--reset-checkpoint", "--checkpoint-path", str(checkpoint_path)])
    reset_config = load_config(args)
    reset_config = LoadConfig(
        mongo_host=reset_config.mongo_host,
        mongo_port=reset_config.mongo_port,
        mongo_db=reset_config.mongo_db,
        mongo_collection=reset_config.mongo_collection,
        data_file=csv_path,
        batch_size=reset_config.batch_size,
        checkpoint_path=checkpoint_path,
        max_batches=None,
        reset_checkpoint=True,
    )
    last_batch_after_reset, counters_after_reset, outputs_reset = initialize_run_state(
        reset_config
    )
    assert last_batch_after_reset == 0
    assert counters_after_reset.rows_loaded == 0
    assert outputs_reset is True
    assert not checkpoint_path.exists()
