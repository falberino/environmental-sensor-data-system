# Data folder

## Included in the repository (submission)

```
data/sample_iot_telemetry_data.csv
```

- About **1.5 MB**, **10,000 rows** from the full Kaggle file  
- Same columns: `ts`, `device`, `co`, `humidity`, `light`, `lpg`, `motion`, `smoke`, `temp`  
- Used by default (`DATA_FILE=data/sample_iot_telemetry_data.csv`)  
- Enough to test Docker, loading, validation, and queries after cloning  

Regenerate from your full local CSV:

```bash
python scripts/create_sample_data.py
python scripts/create_sample_data.py -n 5000   # smaller sample if needed
```

---

## Full dataset (local only, not in Git/ZIP)

```
data/iot_telemetry_data.csv
```

- **Environmental Sensor Telemetry Data** — https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k  
- The Kaggle download archive may be named `Enviromental Sensor Telemetry Data.zip` (misspelled). Extract `iot_telemetry_data.csv` from it. The GitHub repository name is correctly spelled **environmental-sensor-data-system**.
- About **59 MB**, ~405,000 rows  
- **Ignored by Git** (too large for a 25 MB submission)  
- Keep your copy locally for full-scale tests  

To load the full file:

```bash
# in .env
DATA_FILE=data/iot_telemetry_data.csv
```

Then run `load_data.py` as usual.

---

## Why two files?

The portfolio submission must stay **under 25 MB**. The sample proves the pipeline works; the full CSV is optional for local development.
