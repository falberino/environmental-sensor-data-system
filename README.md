# Environmental Sensor Data System

A Docker-based, recoverable batch ingestion system for environmental IoT sensor telemetry. The project loads CSV sensor readings into MongoDB, stores explicit data-quality metadata, supports checkpoint-based recovery, and provides validation and example queries for environmental monitoring use cases.

**Repository:** https://github.com/falberino/environmental-sensor-data-system

---

## Project Purpose

This project was developed for the Model Engineering portfolio as a reproducible local data pipeline. The system supports a city environmental monitoring scenario in which analysts, maintenance staff, and dashboard developers need reliable historical sensor data.

The stored data can support questions such as:

- Which devices reported high smoke, CO, or LPG values?
- Which sensors stopped reporting data?
- Which devices produce sparse or unusually dense readings?
- Which records contain invalid or missing measurements?
- Did a batch load finish successfully, fail, or resume from a checkpoint?

The project focuses on **batch ingestion**, **data quality**, **failure recovery**, and **database validation**. It is not a real-time streaming system and does not include a web dashboard.

---

## Main Features

- Local MongoDB database using Docker Compose
- Python batch loader for CSV telemetry data
- Configurable batch size
- Checkpoint file for stop-and-resume processing
- MongoDB retry handling during batch writes
- Deterministic document IDs to avoid duplicate inserts
- Explicit data-quality flags for invalid measurements
- Rejected-row logging for invalid identity fields
- Validation script for schema, quality, device density, and null values
- Example MongoDB queries for monitoring and maintenance use cases
- Automated tests for transformation and checkpoint behavior

---

## Dataset

The repository includes a reproducible sample dataset:

```text
data/sample_iot_telemetry_data.csv
```

The sample contains environmental IoT telemetry with the following columns:

```text
ts, device, co, humidity, light, lpg, motion, smoke, temp
```

The original dataset is the Environmental Sensor Telemetry Data dataset from Kaggle:

```text
https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k
```

Only the sample CSV is included in the submitted repository so the project remains lightweight and reproducible.

---

## Why MongoDB

Each sensor reading is represented naturally as one document. MongoDB is suitable for this prototype because:

- Each reading can store nested `measurements` and `quality` fields.
- The schema can be extended with quality metadata.
- Deterministic `_id` values and upserts make repeated batch runs idempotent.
- Aggregation queries can support monitoring, validation, and alert-style use cases.
- Docker Compose allows MongoDB to run locally without manual installation.

---

## Repository Structure

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

## Prerequisites

Required:

- Docker
- Docker Compose

Optional for local testing outside Docker:

- Python 3.11 or newer
- `pip`

---

## Setup

Clone the repository and create the local environment file:

```bash
git clone https://github.com/falberino/environmental-sensor-data-system.git
cd environmental-sensor-data-system
cp .env.example .env
```

The `.env.example` file contains the default Docker configuration. The `.env` file is local and is not required in the submitted repository.

---

## Recommended Reproduction: Partial Batch + Resume

This is the main demonstration for the portfolio submission. It proves that the pipeline does not need to process the whole CSV file in one run. Instead, it can process a small number of batches, stop, save a checkpoint, and continue later.

```bash
docker compose down -v
docker compose build app
docker compose up -d mongodb
docker compose ps
```

Initialize the database:

```bash
docker compose run --rm app python scripts/init_db.py
```

Run the first partial batch load:

```bash
docker compose run --rm app python scripts/load_data.py --reset-checkpoint --max-batches 2
```

Inspect the checkpoint:

```bash
python3 -m json.tool outputs/load_checkpoint.json
```

The checkpoint should show that the first two batches were completed.

Run the loader again without resetting the checkpoint:

```bash
docker compose run --rm app python scripts/load_data.py --max-batches 2
```

Inspect the checkpoint again:

```bash
python3 -m json.tool outputs/load_checkpoint.json
```

The checkpoint should now show that the loader continued from the previous state and advanced to the next completed batches.

---

## Validation and Example Queries

After loading data, validate the database contents:

```bash
docker compose run --rm app python scripts/validate_data.py
```

Run example queries:

```bash
docker compose run --rm app python scripts/example_queries.py
```

These scripts demonstrate that the stored data can support environmental monitoring, alert investigation, and sensor-maintenance use cases.

---

## Automated Tests

Run the tests inside the Docker application container:

```bash
docker compose run --rm app pytest tests/ -v
```

The tests cover:

- Invalid timestamp rejection
- Invalid measurement quality flags
- Stable deterministic document IDs
- Checkpoint reset and resume behavior

---

## Recoverable Batch Processing

The loader processes rows in batches. The default batch size is configured in `.env.example`:

```text
BATCH_SIZE=1000
```

The batch loader supports:

| Flag | Purpose |
|---|---|
| `--max-batches N` | Processes only N new batches and then stops successfully. |
| `--reset-checkpoint` | Clears previous progress and starts again from the first batch. |
| `--checkpoint-path PATH` | Uses a custom checkpoint location. |

A checkpoint is written only after a MongoDB batch write succeeds. If a batch fails, the checkpoint is not advanced, so the same batch can be retried during the next run.

Detailed explanation:

```text
docs/batch_design.md
```

---

## Data Quality Rules

The loader does not silently ignore invalid data. It applies explicit quality rules:

| Data issue | System behavior |
|---|---|
| Missing or invalid timestamp | Row is rejected. |
| Missing or invalid device ID | Row is rejected. |
| Invalid numeric measurement | Value is stored as `null` and a quality flag is added. |
| Invalid boolean measurement | Value is stored as `null` and a quality flag is added. |
| Valid row | Row is stored with quality metadata. |
| Duplicate reading | Deterministic `_id` and MongoDB upsert prevent duplicate documents. |

Each stored document contains a quality section similar to:

```json
{
  "quality": {
    "is_valid": true,
    "flags": [],
    "invalid_measurement_count": 0
  }
}
```

Detailed explanation:

```text
docs/data_quality_rules.md
```

---

## Failure Handling

The project documents how the system reacts to common failure situations:

- MongoDB unavailable
- MongoDB write failure
- Disk or storage problem
- Missing CSV file
- Invalid rows
- Schema mismatch
- Partial batch failure
- Checkpoint mismatch

The main recovery rule is:

> The checkpoint is advanced only after a batch is written successfully.

This allows the operator to rerun the loader and continue from the last successful batch.

Detailed explanation:

```text
docs/failure_handling.md
```

---

## Generated Runtime Outputs

The following files are generated locally when the pipeline runs:

```text
outputs/load_summary.json
outputs/load_checkpoint.json
outputs/data_quality_report.json
outputs/invalid_rows.jsonl
outputs/load_failures.json
outputs/validation_summary.json
outputs/example_query_results.json
```

These files are runtime artifacts. They are useful as evidence after executing the pipeline, but they are not part of the clean submitted repository.

---

## Documentation

Additional documentation is provided in the `docs/` folder:

| File | Purpose |
|---|---|
| `docs/user_stories.md` | Explains who uses the system and why. |
| `docs/batch_design.md` | Describes checkpointing, retries, idempotency, and resume behavior. |
| `docs/data_quality_rules.md` | Explains data-quality handling and consequences. |
| `docs/failure_handling.md` | Explains how the system reacts to operational failures. |
| `docs/run_evidence.md` | Contains the reproduction commands and evidence plan. |
| `docs/development_phase_submission_text.md` | Short written explanation for the portfolio submission. |

---

## Submission ZIP

A clean submission ZIP can be created with:

```bash
python3 scripts/create_submission_zip.py
```

The ZIP is designed to include source code, Docker configuration, documentation, tests, and the sample dataset.

---

## Limitations

- The dataset is a public sample dataset, not a live city sensor network.
- The system performs batch ingestion only, not real-time streaming.
- MongoDB runs locally through Docker Compose.
- Example query thresholds are demonstration values.
- No graphical dashboard or web interface is included.
- The system prepares and validates data for future dashboard, API, or analytics use.

---

## Troubleshooting

| Problem | Suggested action |
|---|---|
| MongoDB is not reachable | Run `docker compose up -d mongodb` and wait until it is healthy. |
| Docker Compose error | Run `docker compose config` and check the YAML file. |
| CSV file not found | Confirm that `data/sample_iot_telemetry_data.csv` exists. |
| Old document counts appear | Run `docker compose down -v` before a clean reproduction test. |
| Loader resumes from an old state | Use `--reset-checkpoint` for a fresh run. |
| A batch fails | Fix the issue and rerun the loader without resetting the checkpoint. |
| Tests fail locally | Run the tests inside Docker with `docker compose run --rm app pytest tests/ -v`. |
