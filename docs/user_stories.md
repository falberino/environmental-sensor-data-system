# User Stories — Environmental Sensor Data System

These stories describe how different roles use the `city_environment.sensor_measurements` collection and what happens when data is missing, wrong, sparse, dense, varying, or when batch processing fails.

---

## Environmental Operations Analyst

**As an** environmental operations analyst,  
**I want** to query historical smoke, CO, and LPG readings by device and time window,  
**So that** I can identify unusual air-quality events and prioritize field inspections.

### Acceptance criteria

- Documents include `timestamp`, `device`, and nested `measurements.smoke`, `measurements.co`, `measurements.lpg`.
- Example queries can filter readings above alert thresholds (e.g. 90th percentile).
- Rejected rows (invalid `ts`/`device`) never appear in query results.
- Documents with `quality.is_valid = false` can be excluded from alert calculations.

### Data consequences

| Situation | Consequence |
|-----------|-------------|
| Missing/wrong `ts` or `device` | Row rejected; not queryable; logged to `outputs/invalid_rows.jsonl`. |
| Invalid measurement | Stored as `null` with quality flag; alert queries must handle nulls or filter flagged docs. |
| Sparse data (few readings per device) | Device-level averages and trend detection are unreliable; use `device_density` from validation. |
| Dense data (many readings per minute) | Time-window counts spike; dashboards should aggregate (e.g. hourly) to avoid misleading peaks. |
| High variance across devices | Global thresholds mis-rank devices; filter by `device` before comparing readings. |
| Batch load failure | Checkpoint not advanced; partial data from earlier batches remains; re-run resumes safely. |

---

## Public Health / Safety Analyst

**As a** public health and safety analyst,  
**I want** to review historical exposure patterns and periods of elevated pollutants,  
**So that** I can support incident reports and public advisories with evidence from stored sensor history.

### Acceptance criteria

- Validation report shows timestamp range, device coverage, and null counts per measurement.
- Quality-flagged documents are countable and separable from fully valid readings.
- Data quality report explains how invalid measurements affect exposure estimates.

### Data consequences

| Situation | Consequence |
|-----------|-------------|
| Missing measurements | Stored as `null`; exposure models must impute or exclude those intervals. |
| Wrong numeric values | Rejected at parse time become `null` with flags; prevents silent use of garbage values. |
| Sparse coverage | Gaps in time series weaken confidence in exposure duration estimates. |
| Dense bursts | Short spikes may overstate sustained exposure unless aggregated over longer windows. |
| Varying device calibration | Cross-device comparisons require per-device baselines, not a single city-wide threshold. |
| Partial batch failure | Only completed batches are checkpointed; analysts see incomplete date ranges until operator resumes. |

---

## Sensor Maintenance Technician

**As a** sensor maintenance technician,  
**I want** to see which devices have gone silent or produce frequent invalid readings,  
**So that** I can schedule battery checks, cleaning, or hardware replacement.

### Acceptance criteria

- Queries can count readings per device and find the latest timestamp per device.
- `quality.flags` identify recurring invalid measurements per device.
- Validation summary reports `readings_per_device` and timestamp bounds.

### Data consequences

| Situation | Consequence |
|-----------|-------------|
| Silent device (no new rows) | Latest timestamp stops advancing; distinguish from sparse but active devices via density metrics. |
| Invalid boolean/numeric fields | `quality.invalid_measurement_count` highlights flaky sensors. |
| Missing device identity | Row rejected entirely; cannot attribute maintenance to a device. |
| Dense duplicate-like readings | Deterministic `_id` upserts prevent duplicate documents; technician sees one doc per unique reading identity. |
| Load failure mid-run | Devices loaded in earlier batches still appear; silent detection works on partial data with noted incompleteness. |

---

## Dashboard / API Developer

**As a** dashboard or API developer,  
**I want** a stable document schema with explicit quality metadata,  
**So that** I can build charts and endpoints that warn users when underlying data is incomplete or unreliable.

### Acceptance criteria

- Every loaded document includes `quality.is_valid`, `quality.flags`, and `quality.invalid_measurement_count`.
- Validation confirms `ready_for_queries` before example queries run.
- Null measurement counts are available per field in `outputs/validation_summary.json`.

### Data consequences

| Situation | Consequence |
|-----------|-------------|
| Missing measurements | Render as gaps or “no data” in charts; do not interpolate without business rules. |
| Quality flags | Show badge/tooltip on affected readings; offer “valid only” filter. |
| Sparse devices | Charts with few points should show low-confidence styling. |
| Dense devices | Paginate or downsample API responses to keep dashboards responsive. |
| Schema mismatch | Load fails at header validation; API developer sees empty or stale collection until fixed. |
| Processing failure | Checkpoint preserves progress; API may serve partial history until load completes. |

---

## Data Engineer Operating the Batch Pipeline

**As a** data engineer,  
**I want** recoverable batch loading with checkpoints, retries, and quality reports,  
**So that** I can load large CSV files safely, resume after failure, and prove data quality to stakeholders.

### Acceptance criteria

- `load_data.py` supports `--max-batches`, `--reset-checkpoint`, and `--checkpoint-path`.
- Checkpoint advances only after successful MongoDB write.
- Failed writes log to `outputs/load_failures.json` and exit non-zero without advancing checkpoint.
- `outputs/data_quality_report.json` and `outputs/invalid_rows.jsonl` are produced during load.
- Re-running after failure retries the same batch; completed batches are skipped.

### Data consequences

| Situation | Consequence |
|-----------|-------------|
| MongoDB unavailable | Connection retry then exit; no checkpoint change; operator starts MongoDB and re-runs. |
| Write failure after retries | Same batch retried on next run; no duplicate advancement. |
| CSV missing | Exit before processing; checkpoint unchanged. |
| Invalid rows | Logged and excluded from MongoDB; counts in quality report. |
| File changed mid-load | Fingerprint mismatch blocks resume; `--reset-checkpoint` required. |
| Intentional partial load (`--max-batches`) | Stops with success; checkpoint saved; next run continues. |
