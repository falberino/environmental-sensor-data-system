# Recoverable Batch Design

This document explains how the environmental sensor CSV loader processes data in batches, checkpoints progress, retries writes, and recovers after failure.

**Repository:** https://github.com/falberino/environmental-sensor-data-system

---

## What is a batch?

A **batch** is one chunk of CSV rows read by pandas with `chunksize=BATCH_SIZE` (default **1000**). Each batch is:

1. Read from disk
2. Transformed into MongoDB documents
3. Written to MongoDB with `bulk_write` upserts
4. Checkpointed on success

The loader does **not** need to process the entire file in one run. Operators can load two batches, stop, verify MongoDB, and continue later.

---

## Why partial processing is enough

City environmental monitoring datasets can contain hundreds of thousands of rows. Processing everything at once is fragile:

- A single late failure would force a full restart without checkpointing.
- Operators cannot validate indexes, queries, or quality reports on a small slice first.
- Docker laptops and coursework demos benefit from reproducible **partial** runs (`--max-batches 2`).

Batching plus checkpointing turns a monolithic import into a **resumable workflow**.

---

## Checkpointing

Checkpoint file (default): `outputs/load_checkpoint.json`

After each **successful** batch write, the loader saves:

| Field | Meaning |
|-------|---------|
| `data_file` | CSV path used for this load |
| `file_fingerprint` | Hash of path, size, and mtime |
| `last_successful_batch` | Highest batch number completed |
| `rows_processed` | Cumulative CSV rows seen across successful batches |
| `rows_loaded`, `rows_rejected`, `rows_with_quality_flags` | Cumulative quality counters |
| `batch_quality_status` | Per-batch quality summary for the full load job |
| `updated_at` | UTC timestamp of last checkpoint |

On the next run:

- Batches `<= last_successful_batch` are **skipped**
- Processing resumes at `last_successful_batch + 1`

CLI:

- `--reset-checkpoint` — delete checkpoint and related failure/invalid outputs; start at batch 1
- `--checkpoint-path` — custom checkpoint location
- `--max-batches N` — process only **N new** batches this run, then exit successfully

---

## Retries

**Connection:** `mongo_client.connect_with_retry()` retries MongoDB availability (Docker startup).

**Writes:** Each batch `bulk_write` is retried up to **3** times on transient PyMongo errors (`AutoReconnect`, `NetworkTimeout`, `ConnectionFailure`, `ServerSelectionTimeoutError`, `BulkWriteError`).

If all write retries fail:

- Checkpoint is **not** advanced
- Failure is appended to `outputs/load_failures.json`
- Process exits with non-zero status
- Operator re-runs the same command; the failed batch is retried

---

## Idempotency

Duplicate protection uses two mechanisms:

1. **Deterministic `_id`** — SHA-256 of `timestamp_unix`, `device`, and `measurements`
2. **`ReplaceOne` upsert** — same `_id` updates the existing document instead of creating a duplicate

Re-running a batch (after failure before checkpoint) or reloading the same CSV with `--reset-checkpoint` does not multiply identical readings.

---

## Recovery after failure

| Failure point | State | Operator action |
|---------------|-------|-----------------|
| Before any batch completes | No checkpoint / batch 0 | Fix issue; run `load_data.py` |
| After batch N succeeds | Checkpoint at N | Re-run; batches 1..N skipped |
| During batch N write | Checkpoint still N-1 | Re-run; batch N retried |
| CSV file changed | Fingerprint mismatch | `--reset-checkpoint` or restore original file |
| Intentional pause after partial load | Checkpoint at last success | Re-run without `--reset-checkpoint` |

Example reproducibility test:

```bash
docker compose down -v
docker compose up -d mongodb
docker compose run --rm app python scripts/init_db.py
docker compose run --rm app python scripts/load_data.py --reset-checkpoint --max-batches 2
docker compose run --rm app python scripts/load_data.py --max-batches 2
docker compose run --rm app python scripts/validate_data.py
```

---

## Related outputs

| File | Purpose |
|------|---------|
| `outputs/load_checkpoint.json` | Resume position |
| `outputs/load_summary.json` | Per-run load statistics |
| `outputs/load_failures.json` | Failed batch details |
| `outputs/data_quality_report.json` | Cumulative quality metrics |
| `outputs/invalid_rows.jsonl` | Rejected CSV rows |
