# Data Folder

This folder contains the sample dataset used to reproduce the environmental sensor data system.

## Included Dataset

```text
sample_iot_telemetry_data.csv
```

This CSV file is the default input for the Docker-based batch ingestion pipeline. It allows the project to be executed locally without downloading any additional data.

## Dataset Content

The file contains environmental IoT sensor telemetry with the following columns:

| Column | Description |
|---|---|
| `ts` | Unix timestamp of the sensor reading |
| `device` | Sensor device identifier |
| `co` | Carbon monoxide measurement |
| `humidity` | Humidity measurement |
| `light` | Light measurement |
| `lpg` | Liquefied petroleum gas measurement |
| `motion` | Motion sensor value |
| `smoke` | Smoke measurement |
| `temp` | Temperature measurement |

## Use in the Project

The sample dataset is loaded by:

```text
scripts/load_data.py
```

The default file path is configured in:

```text
.env.example
```

with the following value:

```env
DATA_FILE=data/sample_iot_telemetry_data.csv
```

During execution, the loader reads the CSV file in configurable batches, validates and transforms each row, adds data-quality metadata, and writes the resulting documents to MongoDB.

## Dataset Source

The sample is based on the public Environmental Sensor Telemetry Data dataset from Kaggle:

```text
https://www.kaggle.com/datasets/garystafford/environmental-sensor-data-132k
```

## Reproducibility Note

The submitted repository includes the sample CSV so that the pipeline can be reproduced locally with Docker Compose. No additional dataset download is required for the portfolio demonstration.
