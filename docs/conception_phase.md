# Conception Phase

**Repository:** https://github.com/falberino/environmental-sensor-data-system

## Goal

Design a simple batch system that stores environmental IoT sensor readings from a CSV file in a database (portfolio Task 1).

## Dataset

- **Environmental Sensor Telemetry Data** — https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k  
- Full file (local): `data/iot_telemetry_data.csv`  
- Sample in repo: `data/sample_iot_telemetry_data.csv` (10k rows)  
- Columns: `ts`, `device`, `co`, `humidity`, `light`, `lpg`, `motion`, `smoke`, `temp`

Public sample data, not a real municipal deployment.

## Database choice: MongoDB

I considered SQLite (easy locally but weak for nested sensor fields) and PostgreSQL (strong, but more setup for a small prototype). MongoDB fits because:

- one reading = one document  
- nested `measurements` matches the CSV  
- batch `bulk_write` / upsert is straightforward  
- aggregation pipelines are enough for demo queries  

## Planned architecture

```
CSV → load_data.py (chunks) → MongoDB
         ↑
    init_db.py (indexes)
         ↓
validate_data.py / example_queries.py → outputs/*.json
```

**Database:** `city_environment`  
**Collection:** `sensor_measurements`

## Indexes (planned)

- `timestamp`, `device`  
- compound `timestamp` + `device`  
- `measurements.smoke`, `measurements.temp`, `measurements.co`

## Out of scope (conception)

- Real-time ingestion  
- Web dashboard  
- Cloud deployment  
- Production alerting rules  

See [development phase](development_phase.md) for what was actually built.
