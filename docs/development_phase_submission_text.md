# Development Phase — Submission Text

**Project:** environmental-sensor-data-system  
**GitHub:** https://github.com/falberino/environmental-sensor-data-system

---

## Purpose

This system supports **city environmental monitoring** with historical IoT sensor data. Stakeholders need reliable stored readings for air-quality analysis, alerting, sensor maintenance, and future dashboards. The MongoDB database `city_environment.sensor_measurements` holds batch-loaded telemetry with explicit **quality metadata** so analysts can query high smoke/CO/LPG values, silent devices, sparse or dense sampling, invalid measurements, and recovery state after failed loads.

Processing is **batch-based**, not real-time streaming.

---

## User stories

Five role-based stories are documented in [docs/user_stories.md](user_stories.md):

1. Environmental operations analyst — incident detection and thresholds  
2. Public health / safety analyst — exposure and evidence for advisories  
3. Sensor maintenance technician — silent or flaky devices  
4. Dashboard / API developer — stable schema with quality warnings  
5. Data engineer — recoverable pipeline operation  

Each story includes acceptance criteria and consequences when data is missing, wrong, sparse, dense, varying, or when processing fails.

---

## Recoverable batch design

The loader (`scripts/load_data.py`) processes CSV rows in batches (default 1000). It does **not** require processing the whole file in one run.

- **Checkpoint** (`outputs/load_checkpoint.json`) stores `data_file`, `file_fingerprint`, `last_successful_batch`, `rows_processed`, and cumulative quality counters after each successful batch.
- **`--max-batches`** stops intentionally after N batches with success.
- **`--reset-checkpoint`** starts a fresh load.
- **Retries:** MongoDB connection and each batch write (up to 3 attempts).
- **Idempotency:** deterministic SHA-256 `_id` plus `ReplaceOne` upserts prevent duplicate documents on retry.

If a write fails, the checkpoint is **not** advanced. The operator re-runs the same command; completed batches are skipped and the failed batch is retried.

Design details: [docs/batch_design.md](batch_design.md)

---

## Data quality consequences

Invalid or missing values are no longer silent `None` results:

| Case | Behavior |
|------|----------|
| Missing/invalid `ts` or `device` | Row **rejected**; logged to `outputs/invalid_rows.jsonl` |
| Invalid numeric measurement | `null` in `measurements` + flag e.g. `invalid_numeric_co` |
| Invalid boolean measurement | `null` + flag e.g. `invalid_boolean_light` |
| Missing measurement | `null` + flag e.g. `missing_measurement_temp` |

Each stored document includes:

```json
"quality": {
  "is_valid": false,
  "flags": ["invalid_numeric_co"],
  "invalid_measurement_count": 1
}
```

`outputs/data_quality_report.json` summarizes `total_rows_seen`, `rows_loaded`, `rows_rejected`, `rows_with_quality_flags`, `rejected_reasons`, `device_counts`, and consequences for downstream analytics.

Rules: [docs/data_quality_rules.md](data_quality_rules.md)

---

## What happens when data is missing, wrong, dense, sparse, or varying

- **Missing/wrong identity fields** — row excluded from MongoDB; counts in quality report; queries do not see the row.  
- **Wrong measurements** — stored with `null` and flags; alerts must filter `quality.is_valid` or handle nulls.  
- **Sparse data** — few readings per device; validation reports `readings_per_device`; device averages are low-confidence.  
- **Dense data** — many readings per interval; aggregations should bucket by time to avoid misleading spikes.  
- **Varying data** — wide min/max per field; per-device filters and percentiles are safer than one global threshold.

---

## Failure handling

Documented in [docs/failure_handling.md](failure_handling.md):

| Failure | Operator action |
|---------|-----------------|
| MongoDB unavailable | Start MongoDB; re-run load |
| Write failure after retries | Re-run load; same batch retried; see `load_failures.json` |
| CSV missing | Fix `DATA_FILE`; re-run |
| Schema mismatch | Fix CSV header; re-run with `--reset-checkpoint` if needed |
| Intentional partial load | `--max-batches`; resume without reset |
| CSV changed mid-load | Fingerprint mismatch; `--reset-checkpoint` |

---

## How operators resume after failure

```bash
docker compose run --rm app python scripts/load_data.py
```

Checkpoint ensures batches `<= last_successful_batch` are skipped. Failed batch is retried. No duplicate advancement on partial write failure.

Clean reproducibility test:

```bash
docker compose down -v
docker compose up -d mongodb
docker compose run --rm app python scripts/init_db.py
docker compose run --rm app python scripts/load_data.py --reset-checkpoint --max-batches 2
docker compose run --rm app python scripts/load_data.py --max-batches 2
docker compose run --rm app python scripts/validate_data.py
```

---

## Why MongoDB

- One document per sensor reading with nested `measurements` matches the CSV row shape.  
- Docker Compose provides a reproducible local database without host installation.  
- Aggregation pipelines support alert, maintenance, and density queries.  
- Upserts with deterministic `_id` make batch retries safe.

---

## Validation

`scripts/validate_data.py` checks quality field presence, `quality.is_valid = false` counts, null counts per measurement, device density, timestamp range, and `ready_for_queries`. Results: `outputs/validation_summary.json`.

---

## Implementation summary

Docker Compose runs MongoDB 7 and a Python app container. Workflow: `init_db.py` → `load_data.py` → `validate_data.py` → `example_queries.py`. The repo includes a **10,000-row sample CSV** for reproducibility under the 25 MB submission limit; the full ~405k-row Kaggle file is optional locally.
