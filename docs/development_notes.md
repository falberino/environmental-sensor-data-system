# Development notes

Short notes on how I actually built this project.

## Choices

- **MongoDB** — Sensor rows are semi-structured (mixed numeric and boolean fields). Documents with a nested `measurements` object were easier to work with than designing a full relational schema for a first version.
- **Docker Compose** — I did not want to install MongoDB directly on macOS. One `docker compose up -d mongodb` command was enough for development.
- **Separate scripts** — `init_db`, `load_data`, `validate_data`, and `example_queries` are separate files so I could run and debug each step on its own.

## What I built

1. `init_db.py` — connect and create indexes on `timestamp`, `device`, and a few `measurements` fields.
2. `load_data.py` — read the CSV in chunks of 1000 rows, convert `ts` to datetime, upsert into MongoDB.
3. `validate_data.py` — count documents, list devices, show timestamp range and basic stats, write `validation_summary.json`.
4. `example_queries.py` — ten queries saved to JSON to show how a dashboard or alert list could use the data later.

## Issues I actually ran into

- **Stale `.env` file** — An older version pointed to `iot_environmental` / `sensor_readings`. I fixed this by aligning `.env` with `.env.example` (`city_environment` / `sensor_measurements`).
- **MongoDB not ready immediately after Docker start** — The first connection sometimes failed if the container was still starting. I added a small retry helper in `mongo_client.py`.
- **Mixed documents in the collection** — After changing the schema, some older test documents did not have a `measurements` field. That caused a `KeyError` in the query script until I filtered queries to documents with `measurements` and used safer printing.
- **Document count vs CSV rows** — Validation showed more documents than the latest CSV load (456,346 vs 405,171 upserts) because MongoDB still had data from earlier test runs on the same Docker volume. For a clean test I use `docker compose down -v` before reloading.

## Submission size (25 MB limit)

The full CSV is ~59 MB, so it cannot go in the portfolio ZIP. I added:

- `data/sample_iot_telemetry_data.csv` (10,000 rows, ~1.2 MB)
- `scripts/create_sample_data.py` — rebuild sample from the full local file
- `scripts/create_submission_zip.py` — ZIP without `.venv`, full CSV, or `.git`

Default `DATA_FILE` now points to the sample. The full file stays on my machine only.

## Reproducibility

The main thing I checked was that someone else (or future me) could run the same Docker commands and get JSON files in `outputs/`. The load and validation summaries are what I used for the development phase write-up.
