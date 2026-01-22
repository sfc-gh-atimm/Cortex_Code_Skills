# Hybrid Table Query Analyzer Skill

Analyzes Hybrid Table query performance using Snowhouse telemetry and SnowVI JSON exports.

## Overview

This skill runs the Hybrid Table Query Analyzer pipeline from Cortex Code CLI, providing the same analysis capabilities as the Snowsight Streamlit app.

## Features

- Fetches Snowhouse metadata for a given query UUID
- Enriches analysis with SnowVI JSON exports (optional)
- Applies policy-guided best practices analysis
- Generates ASE-facing diagnosis and next steps via Cortex LLM
- Interactive mode prompts for inputs when invoked without flags
- Supports before/after comparison of query runs

## Usage

```bash
python scripts/run_ht_analysis.py \
  --uuid "<query_uuid>" \
  --snowvi-path "<path_to_snowvi_json>" \
  --snowhouse-connection "Snowhouse" \
  --include-snowvi-link \
  --debug
```

## Flags

| Flag | Description |
|------|-------------|
| `--uuid` | Query UUID to analyze (required) |
| `--snowvi-path` | Path to SnowVI JSON export (optional) |
| `--deployment` | Snowflake deployment (auto-detected from SnowVI) |
| `--snowhouse-connection` | Snowflake CLI connection name (default: Snowhouse) |
| `--include-snowvi-link` | Include SnowVI URL in output |
| `--include-history-table` | Include query history table and timeline |
| `--debug` | Show progress messages, disable telemetry |

## Telemetry

Events are logged to `AFE.PUBLIC_APP_STATE.APP_EVENTS`:

| Event | Description |
|-------|-------------|
| `RUN_ANALYSIS` | Single query analysis |
| `RUN_COMPARISON` | Before/after comparison |
| `RUN_BATCH_ANALYSIS` | Batch analysis |
| `AI_SUMMARY_GENERATED` | LLM summary generated |
| `ERROR_ANALYSIS` | Analysis failed |

App identifier: `Hybrid Table Query Analyzer (Skill)`

## Example Trigger Phrases

- "Analyze Hybrid Table performance for UUID 01234567-89ab-cdef-0123-456789abcdef"
- "Explain why this Hybrid Table query is slow"
- "Compare these two runs of the same Hybrid Table query"
- "Run the HT analyzer"

## Files

- `SKILL.md` - Main skill definition
- `scripts/run_ht_analysis.py` - CLI entry point
- `ht_analyzer/` - Core analysis modules
- `sql_analysis/` - SQL parsing and rules
