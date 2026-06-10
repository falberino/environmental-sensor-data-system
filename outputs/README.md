# Outputs

JSON and JSONL files created when you run the pipeline. They are listed in `.gitignore` and can be regenerated anytime.

| File | Script |
|------|--------|
| `load_summary.json` | `load_data.py` — per-run load statistics |
| `load_checkpoint.json` | `load_data.py` — resume position after successful batches |
| `data_quality_report.json` | `load_data.py` — cumulative quality metrics and consequences |
| `invalid_rows.jsonl` | `load_data.py` — rejected CSV rows (one JSON object per line) |
| `load_failures.json` | `load_data.py` — failed batch write details (when retries exhaust) |
| `validation_summary.json` | `validate_data.py` |
| `example_query_results.json` | `example_queries.py` |

Use these for the development phase report or to verify that a run completed successfully.
