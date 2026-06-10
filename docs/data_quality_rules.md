# Data Quality Rules and Consequences

Rules applied during CSV transformation in `scripts/load_data.py` and validated by `scripts/validate_data.py`.

---

## Accepted schema

Each stored document contains:

```json
{
  "_id": "<sha256>",
  "timestamp": "<UTC datetime>",
  "timestamp_unix": 1594512094.0,
  "device": "b8:27:eb:bf:9d:51",
  "measurements": {
    "co": 0.0049,
    "humidity": 51.0,
    "lpg": 0.0076,
    "smoke": 0.0204,
    "temp": 22.7,
    "light": false,
    "motion": false
  },
  "quality": {
    "is_valid": true,
    "flags": [],
    "invalid_measurement_count": 0
  },
  "source": { "...": "..." },
  "ingested_at": "<UTC datetime>"
}
```

CSV columns required: `ts`, `device`, `co`, `humidity`, `light`, `lpg`, `motion`, `smoke`, `temp`.

---

## Rejected rows

Rows are **rejected** (not stored in MongoDB) when:

| Rule | Flag / reason |
|------|----------------|
| Missing `ts` | `missing_ts` |
| Unparseable `ts` | `invalid_ts` |
| Missing `device` | `missing_device` |
| Empty `device` after trim | `empty_device` |

Rejected rows are appended to `outputs/invalid_rows.jsonl` with `rejection_reason` and row snapshot.

**Consequence:** Rejected rows never appear in MongoDB queries. Counts appear in `rejected_reasons` inside `outputs/data_quality_report.json`.

---

## Null measurement handling

Measurements are stored under `measurements.*`:

| Case | Stored value | Quality flag |
|------|--------------|--------------|
| Missing numeric field | `null` | `missing_measurement_<field>` |
| Invalid numeric field | `null` | `invalid_numeric_<field>` |
| Missing boolean field | `null` | `missing_measurement_<field>` |
| Invalid boolean field | `null` | `invalid_boolean_<field>` |

`quality.is_valid` is `false` when any flag exists.  
`quality.invalid_measurement_count` counts flagged measurements.

**Consequence:** Downstream analytics must not treat `null` as zero. Filter `quality.is_valid` or handle nulls explicitly in aggregations.

---

## Quality flags

Flags are explicit strings on each document, for example:

- `missing_measurement_temp`
- `invalid_numeric_co`
- `invalid_boolean_light`

**Consequence:** Dashboards and alerts can surface unreliable readings instead of silently plotting missing points as zero.

---

## Duplicate handling

`_id` is deterministic from timestamp, device, and measurements. Reloading the same row upserts the same document.

**Consequence:** Re-runs and batch retries do not create duplicate readings for identical sensor events.

---

## Too sparse data

**Definition:** A device has far fewer readings than peers (low `readings_per_device` in validation).

**Consequence:**

- Per-device averages and trend lines are statistically weak.
- “Silent device” detection must compare against expected sampling interval.
- Validation reports `min_readings_per_device` and `avg_readings_per_device`.

---

## Too dense data

**Definition:** Many readings per device in a short interval (high max density).

**Consequence:**

- Raw counts in short windows look like spikes.
- Aggregations should use time buckets (hourly/daily).
- Example queries use limits and percentiles to avoid overload.

---

## Too varying data

**Definition:** Large spread of values across devices or time (high min/max range per field).

**Consequence:**

- Global alert thresholds mis-rank devices.
- Use per-device baselines or percentiles (see `example_queries.py`).
- Validation `basic_statistics` documents min/max/avg per field.

---

## Downstream analytics consequences

| Quality issue | Analytics impact |
|---------------|------------------|
| Rejected identity rows | Missing points in time series; device may appear quieter than reality |
| Flagged measurements | Nullable fields reduce sample size for averages |
| Sparse devices | Unreliable maintenance and alert ranking |
| Dense devices | Needs aggregation to avoid chart/API overload |
| Varying devices | Requires per-device filters, not one city-wide rule |

Full cumulative metrics: `outputs/data_quality_report.json`  
Post-load checks: `outputs/validation_summary.json`
