# Development Phase

**Repository:** https://github.com/falberino/environmental-sensor-data-system

## What I implemented

A Dockerized MongoDB setup and four Python scripts:

| Script | Purpose |
|--------|---------|
| `init_db.py` | Create indexes |
| `load_data.py` | Batch load CSV with upsert |
| `validate_data.py` | Check collection + write `validation_summary.json` |
| `example_queries.py` | Ten demo queries → `example_query_results.json` |

Helper: `mongo_client.py` (connection retries after Docker start).

## Stack

- MongoDB 7 in Docker  
- Python 3.11, pandas, pymongo  
- Docker Compose (`mongodb`, `app`, optional `pipeline` service)

## How to run

```bash
docker compose up -d mongodb
docker compose run --rm app python scripts/init_db.py
docker compose run --rm app python scripts/load_data.py
docker compose run --rm app python scripts/validate_data.py
docker compose run --rm app python scripts/example_queries.py
```

Or: `docker compose up --build` for the full pipeline.

## Document schema

Each CSV row → document with `timestamp`, `timestamp_unix`, `device`, nested `measurements`, `source`, `ingested_at`. See README for an example.

## Outputs (from a real run)

| File | Key results |
|------|-------------|
| `load_summary.json` | 405,184 rows processed, 405,171 upserts, ~15 s |
| `validation_summary.json` | 456,346 documents, 3 devices, 2020-07-12 → 2020-07-20 |
| `example_query_results.json` | Ten query result sets |

## Limitations

- **Sample Kaggle data**, not real city infrastructure.  
- **Batch load only** — no streaming.  
- **Local Docker MongoDB** — not a managed cloud service.  
- **Demo thresholds** in example queries (90th percentile), not real alert policy.  
- **No front-end** — JSON outputs only.  
- **Document count** can exceed the latest CSV load if the same Docker volume was reused across tests; use `docker compose down -v` for a clean reload.

## Related docs

- [README](../README.md)  
- [Development notes](development_notes.md)  
- [Submission text](development_phase_submission_text.md)
