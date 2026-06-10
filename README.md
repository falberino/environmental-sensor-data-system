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
- Devices with no recent data, also called silent sensors
- Sparse vs dense sampling per device
- Documents with invalid or missing measurements through `quality.flags`
- Recovery state after a failed or partial batch load

This is **batch processing**, not real-time streaming. CSV files are loaded in configurable chunks with checkpointing so operators do not need to process the entire file in one run.

---

## What this project does

1. Starts MongoDB in Docker.
2. Creates indexes on `city_environment.sensor_measurements`.
3. Loads CSV data in **recoverable batches** using checkpoints and retries.
4. Tracks data quality consequences, including rejected rows, quality flags, and reports.
5. Validates the load by checking schema, quality fields, device density, and null counts.
6. Runs example queries that could support dashboards, alert lists, and maintenance checks.

No web UI is included. This repository focuses on storage, batch loading, quality tracking, validation, and querying.

---

## User Stories

Role-based stories with acceptance criteria and data consequences are documented here:

- [docs/user_stories.md](docs/user_stories.md)

The user stories cover:

- Environmental operations analyst
- Public health or safety analyst
- Sensor maintenance technician
- Dashboard/API developer
- Data engineer operating the batch pipeline

These stories explain how people would use the database and what happens when data is missing, wrong, too sparse, too dense, too variable, or when a batch load fails.

---

## Dataset

| | |
|---|---|
| **Name** | Environmental Sensor Telemetry Data |
| **Kaggle** | https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k |
| **Columns** | `ts`, `device`, `co`, `humidity`, `light`, `lpg`, `motion`, `smoke`, `temp` |

### Included in the repository

`data/sample_iot_telemetry_data.csv` — 10,000 rows, approximately 1.5 MB.

This sample file is the default dataset for Docker, `.env.example`, loading, validation, and example queries.

### Full dataset

`data/iot_telemetry_data.csv` — approximately 59 MB and around 405k rows.

The full dataset is optional and should be kept local only. It should not be uploaded to GitHub. To use the full dataset, download it from Kaggle and set this value in `.env`:

```env
DATA_FILE=data/iot_telemetry_data.csv
```

See [data/README.md](data/README.md) for more detail.

---

## Why MongoDB

Each sensor reading is stored as one document with nested `measurements` and `quality` objects. MongoDB fits this coursework prototype because:

- The document shape matches one sensor reading per CSV row.
- Docker Compose can run MongoDB without requiring a local database installation.
- Batch upserts with deterministic `_id` values make reloads idempotent.
- Aggregation pipelines support alert, monitoring, validation, and maintenance queries.
- The schema can be extended with quality flags without redesigning relational tables.

---

## Prerequisites

- Docker
- Docker Compose
- Python 3.11 or newer, only needed for local testing or creating the submission ZIP

The sample CSV is included for quick tests. A new sample can also be generated with:

```bash
python scripts/create_sample_data.py
```

---

## Setup

```bash
git clone https://github.com/falberino/environmental-sensor-data-system.git
cd environmental-sensor-data-system
cp .env.example .env
```

The `.env.example` file is committed to the repository. The `.env` file is local only and should not be uploaded.

---

## Recommended Phase 3 demonstration: partial batch + resume

This is the **main demonstration** for the portfolio submission. It proves that the system processes only a small part of the CSV, stops intentionally, saves a checkpoint, and continues later without reprocessing earlier successful batches.

```bash
docker compose down -v
docker compose up -d mongodb
docker compose ps   # wait until mongodb is healthy

docker compose run --rm app python scripts/init_db.py

# First run: process only two batches and stop successfully
docker compose run --rm app python scripts/load_data.py --reset-checkpoint --max-batches 2

# Second run: resume from the checkpoint and process two more batches
docker compose run --rm app python scripts/load_data.py --max-batches 2

# Validate and query the stored data
docker compose run --rm app python scripts/validate_data.py
docker compose run --rm app python scripts/example_queries.py

# Run tests inside the Docker app container
docker compose run --rm app pytest tests/ -v
```

After the first load command, inspect:

```text
outputs/load_checkpoint.json
```

The checkpoint should show that the last successful batch is batch 2. The second load command should skip batches 1 and 2 and continue with the next unprocessed batch.

Step-by-step evidence guide:

- [docs/run_evidence.md](docs/run_evidence.md)

---

## Optional: full sample load

Use this only when you want to load the complete sample dataset without demonstrating the stop-and-resume behavior.

```bash
docker compose down -v
docker compose up -d mongodb
docker compose ps   # wait until mongodb is healthy

docker compose run --rm app python scripts/init_db.py
docker compose run --rm app python scripts/load_data.py --reset-checkpoint
docker compose run --rm app python scripts/validate_data.py
docker compose run --rm app python scripts/example_queries.py
```

---

## Optional: full pipeline service

The full pipeline can also be executed through the `pipeline` service:

```bash
docker compose up --build pipeline
```

This starts the pipeline container and runs initialization, loading, validation, and example queries in sequence.

---

## Recoverable Batch Processing

The loader processes CSV rows in batches. The default batch size is 1000 rows. After each **successful** MongoDB write, the loader saves a checkpoint to:

```text
outputs/load_checkpoint.json
```

| CLI flag | Purpose |
|---|---|
| `--max-batches N` | Process only N new batches during this run, then stop successfully. |
| `--reset-checkpoint` | Start from batch 1 and clear the previous checkpoint and invalid-row log. |
| `--checkpoint-path PATH` | Use a custom checkpoint file. The default is `outputs/load_checkpoint.json`. |

Each batch prints:

- Batch number
- Rows read
- Documents built
- Invalid rows
- Rows with quality flags
- Inserted/updated document counts
- Checkpoint location

Details:

- [docs/batch_design.md](docs/batch_design.md)

---

## How to resume after failure

If a batch write fails after retries:

- The checkpoint is **not** advanced.
- The failure is logged to `outputs/load_failures.json`.
- The current batch can be retried by running the loader again.
- Completed batches are skipped because the checkpoint records the last successful batch.

```bash
docker compose run --rm app python scripts/load_data.py
```

See:

- [docs/failure_handling.md](docs/failure_handling.md)

---

## Data Quality Rules and Consequences

The transformation logic is implemented in:

```text
scripts/load_data.py
```

| Case | Behavior |
|---|---|
| Missing or invalid `ts` | Row is rejected and logged to `outputs/invalid_rows.jsonl`. |
| Missing or invalid `device` | Row is rejected and logged to `outputs/invalid_rows.jsonl`. |
| Invalid numeric measurement | Measurement is stored as `null` and a quality flag is added. |
| Invalid boolean measurement | Measurement is stored as `null` and a quality flag is added. |
| Valid row | Row is stored with `quality.is_valid`, `quality.flags`, and `quality.invalid_measurement_count`. |
| Duplicate reading | Deterministic `_id` and MongoDB upsert prevent duplicate documents. |
| Sparse device data | Device can be flagged during validation as potentially silent or unreliable. |
| Dense device data | Device can be flagged as unusually frequent or potentially misconfigured. |
| Highly varying data | Values can be reviewed as potential real events or sensor issues. |

Reports generated by the loader:

| File | Purpose |
|---|---|
| `outputs/data_quality_report.json` | Cumulative data quality counts and consequences. |
| `outputs/invalid_rows.jsonl` | Rejected rows with rejection reasons. |
| `outputs/load_summary.json` | Summary of the loading run. |

Full rules:

- [docs/data_quality_rules.md](docs/data_quality_rules.md)

---

## Failure Handling

Failure handling covers:

- MongoDB unavailable at startup
- MongoDB write failure during a batch
- Disk full
- Missing CSV file
- Invalid rows
- Schema mismatch
- Partial batch failure
- Checkpoint mismatch after changing the source file

The key recovery rule is:

> A checkpoint is advanced only after a batch is written successfully.

This means a failed batch can be retried safely during the next run.

See:

- [docs/failure_handling.md](docs/failure_handling.md)

---

## Expected outputs after running scripts

Generated output files are stored in the `outputs/` folder. They are regenerated each run and are not required in the submission ZIP.

| File | Created by |
|---|---|
| `outputs/load_summary.json` | `load_data.py` |
| `outputs/load_checkpoint.json` | `load_data.py` |
| `outputs/data_quality_report.json` | `load_data.py` |
| `outputs/invalid_rows.jsonl` | `load_data.py` |
| `outputs/load_failures.json` | `load_data.py`, only when a write failure occurs |
| `outputs/validation_summary.json` | `validate_data.py` |
| `outputs/example_query_results.json` | `example_queries.py` |

The repository should keep only `outputs/README.md` by default. Generated JSON, JSONL, and log files should not be uploaded unless specifically needed as run evidence.

---

## Configuration

| Variable | Default |
|---|---|
| `MONGO_HOST` | `mongodb` |
| `MONGO_PORT` | `27017` |
| `MONGO_DB` | `city_environment` |
| `MONGO_COLLECTION` | `sensor_measurements` |
| `DATA_FILE` | `data/sample_iot_telemetry_data.csv` |
| `BATCH_SIZE` | `1000` |

The default `MONGO_HOST=mongodb` is intended for Docker Compose. If running scripts directly from the host machine, use:

```env
MONGO_HOST=localhost
```

---

## Tests

Run tests inside Docker:

```bash
docker compose run --rm app pytest tests/ -v
```

Or run tests locally:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest tests/ -v
```

The tests cover:

- Invalid timestamp rejection
- Invalid measurement quality flags
- Stable deterministic `_id` generation
- Checkpoint resume/reset behavior

---

## Local validation commands

Before uploading or submitting the repository, run:

```bash
python -m py_compile scripts/*.py
python -m py_compile tests/*.py
docker compose config
```

Then run:

```bash
docker compose down -v
docker compose up -d mongodb
docker compose run --rm app python scripts/init_db.py
docker compose run --rm app python scripts/load_data.py --reset-checkpoint --max-batches 2
docker compose run --rm app python scripts/load_data.py --max-batches 2
docker compose run --rm app python scripts/validate_data.py
docker compose run --rm app python scripts/example_queries.py
docker compose run --rm app pytest tests/ -v
docker compose down
```

---

## Project layout

```text
environmental-sensor-data-system/
├── README.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
│
├── data/
│   ├── README.md
│   └── sample_iot_telemetry_data.csv
│
├── docs/
│   ├── user_stories.md
│   ├── batch_design.md
│   ├── data_quality_rules.md
│   ├── failure_handling.md
│   ├── run_evidence.md
│   └── development_phase_submission_text.md
│
├── outputs/
│   └── README.md
│
├── scripts/
│   ├── init_db.py
│   ├── load_data.py
│   ├── validate_data.py
│   ├── example_queries.py
│   ├── mongo_client.py
│   ├── create_sample_data.py
│   └── create_submission_zip.py
│
└── tests/
    └── test_transformation.py
```

---

## Files that should not be uploaded

Before uploading the project manually to GitHub, make sure these files and folders are not included:

```text
.env
.venv/
venv/
__pycache__/
.pytest_cache/
*.pyc
data/iot_telemetry_data.csv
data/*.zip
outputs/*.json
outputs/*.jsonl
outputs/*.log
mongo-data/
environmental-sensor-data-system-submission.zip
```

The repository should include the sample CSV, not the full dataset archive.

---

## Submission ZIP

Create a clean submission ZIP with:

```bash
python scripts/create_submission_zip.py
```

This creates:

```text
environmental-sensor-data-system-submission.zip
```

The ZIP script should exclude:

- Local environment files
- Python cache files
- Full datasets
- ZIP archives
- Generated output JSON/JSONL/log files
- Local Docker database files

---

## Limitations

- The project uses public Kaggle sample data, not a live city sensor network.
- The system performs batch loading only, not real-time streaming.
- MongoDB runs locally through Docker Compose and is not configured as a cloud production database.
- Alert thresholds in the example queries are demonstration thresholds.
- No dashboard or graphical user interface is included.
- The system stores and validates data for later use by dashboards, analysts, or APIs.

---

## Troubleshooting

| Problem | Try |
|---|---|
| CSV not found | Run `python scripts/create_sample_data.py` or use the included sample file. |
| MongoDB connection error | Run `docker compose up -d mongodb` and wait until the service is healthy. |
| Stale document count | Run `docker compose down -v` and reload with `--reset-checkpoint`. |
| Checkpoint file mismatch | Use `--reset-checkpoint` after changing the source CSV. |
| Load failed mid-batch | Re-run `load_data.py` without reset so the failed batch is retried. |
| Docker Compose config error | Run `docker compose config` and check YAML indentation. |
| Tests fail locally | Run tests inside Docker with `docker compose run --rm app pytest tests/ -v`. |

---

## Documentation

- [User stories](docs/user_stories.md)
- [Batch design](docs/batch_design.md)
- [Data quality rules](docs/data_quality_rules.md)
- [Failure handling](docs/failure_handling.md)
- [Phase 3 run evidence](docs/run_evidence.md)
- [Submission text](docs/development_phase_submission_text.md)
- [Dataset notes](data/README.md)
