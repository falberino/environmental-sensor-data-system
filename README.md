# Environmental Sensor Data System

A recoverable batch-loading system for environmental IoT sensor data. The project reads CSV telemetry in checkpoints, stores readings in MongoDB with explicit data-quality metadata, and supports validation and example queries for city environmental monitoring workflows.

**GitHub:** https://github.com/falberino/environmental-sensor-data-system

```bash
git clone https://github.com/falberino/environmental-sensor-data-system.git
cd environmental-sensor-data-system
```

---

## Purpose of the System

This system supports **city environmental monitoring** using historical IoT sensor telemetry. Public agencies, analysts, and engineers need reliable stored readings for:

- **Air-quality monitoring** — smoke, CO, LPG, temperature, humidity
- **Alerting** — identifying unusually high readings by device and time
- **Maintenance** — detecting silent devices or flaky measurements
- **Future dashboards and APIs** — stable document schema with quality metadata

The MongoDB collection `city_environment.sensor_measurements` is designed for queries such as:

- High smoke / CO / LPG readings in a time window
- Devices with no recent data (silent sensors)
- Sparse vs dense sampling per device
- Documents with invalid or missing measurements (`quality.flags`)
- Recovery state after a failed or partial batch load

This is **batch processing**, not real-time streaming. CSV files are loaded in configurable chunks with checkpointing so operators do not need to process the entire file in one run.

---

## What this project does

1. Start MongoDB in Docker
2. Create indexes on `city_environment.sensor_measurements`
3. Load CSV data in **recoverable batches** (checkpoint + retries)
4. Track data quality consequences (rejected rows, quality flags, reports)
5. Validate the load (schema, quality field, density, null counts)
6. Run example queries (useful for dashboards and alert lists)

No web UI — storage, quality tracking, and querying only.

---

## User Stories

Role-based stories with acceptance criteria and data consequences:

- [docs/user_stories.md](docs/user_stories.md) — environmental operations analyst, public health analyst, maintenance technician, dashboard developer, data engineer

---

## Dataset

| | |
|---|---|
| **Name** | Environmental Sensor Telemetry Data |
| **Kaggle** | https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k |
| **Columns** | `ts`, `device`, `co`, `humidity`, `light`, `lpg`, `motion`, `smoke`, `temp` |

### Included in the repo (for submission, under 25 MB)

`data/sample_iot_telemetry_data.csv` — **10,000 rows**, ~1.5 MB. Default for Docker and `.env.example`.

### Full dataset (optional, local only)

`data/iot_telemetry_data.csv` — ~59 MB, ~405k rows. Not in Git. Download from Kaggle and set `DATA_FILE=data/iot_telemetry_data.csv` in `.env`.

See [data/README.md](data/README.md).

---

## Why MongoDB

Each reading is one document with nested `measurements` and a `quality` object. MongoDB fits this coursework prototype because:

- Document shape matches one sensor reading per row
- Docker Compose runs MongoDB without a local install
- Batch upserts with deterministic `_id` give idempotent reloads
- Aggregation pipelines support alert and maintenance queries

---

## Prerequisites

- Docker and Docker Compose
- Sample CSV included for quick tests (or generate with `create_sample_data.py`)

---

## Setup

```bash
git clone https://github.com/falberino/environmental-sensor-data-system.git
cd environmental-sensor-data-system
cp .env.example .env
```

---

## Recommended Phase 3 demonstration: partial batch + resume

This is the **main demonstration** for portfolio submission. It proves the system processes a small part of the CSV, stops intentionally, saves a checkpoint, and continues later without reprocessing earlier batches.

```bash
docker compose down -v
docker compose up -d mongodb
docker compose ps   # wait until mongodb is healthy

docker compose run --rm app python scripts/init_db.py
docker compose run --rm app python scripts/load_data.py --reset-checkpoint --max-batches 2
docker compose run --rm app python scripts/load_data.py --max-batches 2
docker compose run --rm app python scripts/validate_data.py
docker compose run --rm app python scripts/example_queries.py
pytest tests/ -v
```

After the first load command, inspect `outputs/load_checkpoint.json` (`last_successful_batch: 2`). The second load command skips batches 1–2 and processes batches 3–4.

Step-by-step evidence guide: [docs/run_evidence.md](docs/run_evidence.md)

---

## Optional: full load in one command

If you only need a complete sample load without demonstrating resume:

```bash
docker compose up -d mongodb
docker compose run --rm app python scripts/init_db.py
docker compose run --rm app python scripts/load_data.py --reset-checkpoint
docker compose run --rm app python scripts/validate_data.py
docker compose run --rm app python scripts/example_queries.py
```

Makefile shortcuts: `make start`, `make init-db`, `make load-data`, `make validate`, `make queries`

Full pipeline service (all steps in one container): `docker compose up --build`

---

## Recoverable Batch Processing

The loader processes CSV rows in batches (default 1000 rows). After each **successful** MongoDB write it saves a checkpoint to `outputs/load_checkpoint.json`.

| CLI flag | Purpose |
|----------|---------|
| `--max-batches N` | Process only N new batches this run, then stop successfully |
| `--reset-checkpoint` | Start from batch 1; clear checkpoint and invalid-row log |
| `--checkpoint-path PATH` | Custom checkpoint file (default: `outputs/load_checkpoint.json`) |

Each batch prints: batch number, rows read, documents built, invalid rows, rows with quality flags, inserted/updated, checkpoint location.

Details: [docs/batch_design.md](docs/batch_design.md)

---

## How to resume after failure

If a batch write fails after retries:

- Checkpoint is **not** advanced
- Failure is logged to `outputs/load_failures.json`
- Re-run the same command — the failed batch is retried; completed batches are skipped

```bash
docker compose run --rm app python scripts/load_data.py
```

See [docs/failure_handling.md](docs/failure_handling.md).

---

## Data Quality Rules and Consequences

Transformation rules in `scripts/load_data.py`:

| Case | Behavior |
|------|----------|
| Missing/invalid `ts` or `device` | Row **rejected**; logged to `outputs/invalid_rows.jsonl` |
| Invalid numeric measurement | Stored as `null` + quality flag |
| Invalid boolean measurement | Stored as `null` + quality flag |
| Valid row | Stored with `quality.is_valid`, `quality.flags`, `quality.invalid_measurement_count` |

Reports:

- `outputs/data_quality_report.json` — cumulative counts and consequences
- `outputs/invalid_rows.jsonl` — rejected rows with reasons

Full rules: [docs/data_quality_rules.md](docs/data_quality_rules.md)

---

## Failure Handling

Covers MongoDB unavailable, write failures, disk full, missing CSV, invalid rows, schema mismatch, partial batches, and checkpoint mismatch.

See [docs/failure_handling.md](docs/failure_handling.md).

---

## Expected outputs (after running scripts)

| File | Script |
|------|--------|
| `outputs/load_summary.json` | `load_data.py` |
| `outputs/load_checkpoint.json` | `load_data.py` |
| `outputs/data_quality_report.json` | `load_data.py` |
| `outputs/invalid_rows.jsonl` | `load_data.py` |
| `outputs/load_failures.json` | `load_data.py` (on write failure) |
| `outputs/validation_summary.json` | `validate_data.py` |
| `outputs/example_query_results.json` | `example_queries.py` |

Regenerated each run; not required in the submission ZIP.

---

## Configuration

| Variable | Default |
|----------|---------|
| `MONGO_HOST` | `mongodb` (`.env.example` default for Docker; use `localhost` when running scripts on the host) |
| `MONGO_DB` | `city_environment` |
| `MONGO_COLLECTION` | `sensor_measurements` |
| `DATA_FILE` | `data/sample_iot_telemetry_data.csv` |
| `BATCH_SIZE` | `1000` |

---

## Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

Covers invalid timestamp rejection, invalid measurement quality flags, deterministic `_id`, and checkpoint resume/reset behavior.

---

## Project layout

```
├── README.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── data/
│   ├── sample_iot_telemetry_data.csv
│   └── iot_telemetry_data.csv          # local only (gitignored)
├── scripts/
│   ├── init_db.py
│   ├── load_data.py
│   ├── validate_data.py
│   ├── example_queries.py
│   ├── create_sample_data.py
│   └── create_submission_zip.py
├── docs/
│   ├── user_stories.md
│   ├── batch_design.md
│   ├── data_quality_rules.md
│   └── failure_handling.md
└── tests/
    └── test_transformation.py
```

---

## Submission ZIP (under 25 MB)

```bash
python scripts/create_submission_zip.py
```

Creates `environmental-sensor-data-system-submission.zip`.

---

## Limitations

- Public **Kaggle sample data**, not a live city sensor network
- **Batch load only** — no real-time streaming
- **Local Docker MongoDB** — not cloud production
- **Demo alert thresholds** in example queries (90th percentile)
- **No dashboard** in this repo

---

## Troubleshooting

| Problem | Try |
|---------|-----|
| CSV not found | Run `python scripts/create_sample_data.py` or use default sample |
| MongoDB connection | `docker compose up -d mongodb`, wait for healthy |
| Stale document count | `docker compose down -v` and reload with `--reset-checkpoint` |
| Checkpoint file mismatch | `--reset-checkpoint` after changing CSV |
| Load failed mid-batch | Re-run `load_data.py` without reset |

---

## Documentation

- [User stories](docs/user_stories.md)
- [Batch design](docs/batch_design.md)
- [Data quality rules](docs/data_quality_rules.md)
- [Failure handling](docs/failure_handling.md)
- [data/README.md](data/README.md)
- [Development notes](docs/development_notes.md)
- [Submission text](docs/development_phase_submission_text.md)
- [Phase 3 run evidence](docs/run_evidence.md)
