# Failure Handling

Operator guide for batch load failures in the **environmental-sensor-data-system**.

---

## MongoDB unavailable

**Symptoms:** Connection errors during `init_db.py`, `load_data.py`, or `validate_data.py`.

**System behavior:**

- `connect_with_retry()` attempts up to 10 connections with 2s delay
- No CSV batches processed; checkpoint unchanged

**Operator action:**

```bash
docker compose up -d mongodb
docker compose ps   # wait until healthy
docker compose run --rm app python scripts/load_data.py
```

---

## MongoDB write failure

**Symptoms:** Batch processed but `bulk_write` fails after 3 retries.

**System behavior:**

- Checkpoint **not** advanced
- Entry appended to `outputs/load_failures.json`
- Exit code non-zero
- Message: next run retries the **same** batch

**Operator action:**

1. Check MongoDB logs: `docker compose logs mongodb`
2. Ensure disk space and memory are sufficient
3. Re-run the same load command (no `--reset-checkpoint` unless intentionally restarting)

```bash
docker compose run --rm app python scripts/load_data.py
```

---

## Disk full

**Symptoms:** Write errors, Docker volume errors, cannot save checkpoint or JSON outputs.

**System behavior:**

- Batch may fail before or after MongoDB write
- If write did not succeed, checkpoint not advanced

**Operator action:**

1. Free disk space
2. `docker system prune` if needed (careful with volumes)
3. Resume load without reset if checkpoint exists

---

## CSV missing

**Symptoms:** `ERROR: CSV file not found` at startup.

**System behavior:** Exit before reading batches; checkpoint unchanged.

**Operator action:**

- Use included sample: `data/sample_iot_telemetry_data.csv`
- Or generate: `python scripts/create_sample_data.py`
- Or download full Kaggle file to `data/iot_telemetry_data.csv` and set `DATA_FILE` in `.env`

---

## Invalid rows

**Symptoms:** `invalid rows` count printed per batch; `outputs/invalid_rows.jsonl` grows.

**System behavior:**

- Invalid `ts`/`device` rows rejected from MongoDB
- Invalid measurements stored with `quality.flags`
- Counts in `outputs/data_quality_report.json`

**Operator action:**

- Review `invalid_rows.jsonl` for systematic CSV issues
- If rejection rate is acceptable, continue loading
- If source file is corrupt, fix CSV or use `--reset-checkpoint` after replacement

---

## Schema mismatch

**Symptoms:** `CSV is missing required columns` during first batch.

**System behavior:** Exit immediately; no checkpoint update for new file.

**Operator action:**

- Verify header matches: `ts`, `device`, `co`, `humidity`, `light`, `lpg`, `motion`, `smoke`, `temp`
- Use dataset from [Kaggle Environmental Sensor Telemetry Data](https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k)

---

## Partial batch failure (intentional stop)

**Symptoms:** Run ends with “Stopped intentionally after N batch(es)”.

**System behavior:**

- Success exit code
- Checkpoint saved at last completed batch

**Operator action:**

```bash
docker compose run --rm app python scripts/load_data.py --max-batches 2
# later
docker compose run --rm app python scripts/load_data.py
```

---

## Checkpoint / file mismatch

**Symptoms:** `Checkpoint fingerprint does not match the current CSV file`.

**System behavior:** Exit before processing; prevents mixing two different files in one load job.

**Operator action:**

- Restore original CSV, **or**
- Start fresh: `docker compose run --rm app python scripts/load_data.py --reset-checkpoint`

---

## Clean reproducibility test

```bash
docker compose down -v
docker compose up -d mongodb
docker compose run --rm app python scripts/init_db.py
docker compose run --rm app python scripts/load_data.py --reset-checkpoint --max-batches 2
docker compose run --rm app python scripts/load_data.py --max-batches 2
docker compose run --rm app python scripts/validate_data.py
docker compose run --rm app python scripts/example_queries.py
```

---

## Quick reference

| Failure | Checkpoint advanced? | Re-run command |
|---------|----------------------|----------------|
| MongoDB down | No | Same `load_data.py` after MongoDB up |
| Write retry exhausted | No | Same `load_data.py` |
| CSV missing | No | Fix file path, re-run |
| Invalid rows | Yes (for valid rows in batch) | Continue or inspect `invalid_rows.jsonl` |
| `--max-batches` stop | Yes | Continue without reset |
| File fingerprint mismatch | No | `--reset-checkpoint` or restore CSV |
