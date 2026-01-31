# JSON Output Schema

## Success Response

```jsonc
{
  "status": "ok",
  "schema_version": "1.0",
  "analysis_mode": "single|compare",
  "query_uuid": "string",
  "comparison_uuid": "string | null",
  "deployment": "string",
  "snowvi_link": "string | null",
  "customer_info": {
    "name": "string | null",
    "account_id": "string | null",
    "deployment": "string"
  },
  "best_practices_summary": {
    "grade": "A-F | null",
    "score": "number | null",
    "workload_type": "string | null",
    "errors": 0,
    "warnings": 0,
    "passed": 0
  },
  "summary_markdown": "string",
  "analysis": {
    "bp_findings": {},
    "sql_findings": [],
    "coverage": [],
    "history_context": {}
  },
  "history_table": [],
  "history_chart_markdown": "string | null",
  "candidate_actions": [],
  "next_steps_markdown": "string",
  "root_cause_classification": {
    "label": "OLTP_OPTIMAL | OLTP_SLOW | HYBRID_ANALYTIC | MISSING_INDEX | FDB_BOTTLENECK",
    "description": "Human-readable description"
  },
  "comparison_result": {
    "primary_cause": "DATA_VOLUME | FDB_LATENCY | XP_EXECUTION_ENVIRONMENT",
    "primary_cause_description": "Human-readable explanation",
    "secondary_cause": "string | null",
    "diff": {},
    "diff_summary": "Formatted summary"
  },
  "faqs": {},
  "prioritized_findings": []
}
```

## Error Response

```json
{
  "status": "error",
  "schema_version": "1.0",
  "error_code": "INVALID_UUID | INVALID_COMPARISON_MODE | ANALYSIS_ERROR | CORTEX_ERROR",
  "error_message": "string",
  "details": {}
}
```

## Root Cause Classifications

| Label | Description |
|-------|-------------|
| `OLTP_OPTIMAL` | Query is well-optimized for HT |
| `OLTP_SLOW` | OLTP pattern but slow execution |
| `HYBRID_ANALYTIC` | Analytic workload on HT (anti-pattern) |
| `MISSING_INDEX` | Hot predicates without index coverage |
| `FDB_BOTTLENECK` | FoundationDB layer bottleneck |
