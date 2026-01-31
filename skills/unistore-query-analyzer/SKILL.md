---
name: unistore-query-analyzer
description: "Diagnose slow Hybrid Table queries. Use when: analyzing HT performance, debugging HT latency, comparing before/after query runs."
version: 0.4.0
schema-version: 1.0
tags:
  - snowflake
  - hybrid-tables
  - performance
  - diagnostics
---

# Hybrid Table Query Analyzer

Analyze Hybrid Table query performance using Snowhouse telemetry and SnowVI enrichment.

## When to Invoke

- "Analyze Hybrid Table performance for UUID `<UUID>`"
- "Explain why this HT query is slow: `<UUID>`"
- "Compare these two HT query runs"
- "Debug Hybrid Table latency"

## Workflow

### Step 1: Gather Query UUID

```json
{
  "questions": [
    {"header": "Query UUID", "question": "Enter the Snowflake Query UUID to analyze:", "type": "text", "defaultValue": ""}
  ]
}
```

### Step 2: Lookup Query & Check SnowVI Availability

**If user did NOT provide a SnowVI JSON path**, first lookup the query and check if SnowVI data was persisted:

```sql
WITH params AS (
    SELECT 
        '<QUERY_UUID>'::string AS uuid,
        TO_TIMESTAMP(TO_NUMBER(LEFT('<QUERY_UUID>', 8), 'XXXXXXXX') * 60) AS uuid_ts
)
SELECT
    q.uuid AS QUERY_ID,
    q.deployment AS DEPLOYMENT,
    q.total_duration AS TOTAL_DURATION_MS,
    q.account_id AS ACCOUNT_ID,
    q.created_on AS QUERY_TIMESTAMP,
    q.query_parameterized_hash AS QUERY_HASH,
    LEFT(q.description, 200) AS QUERY_PREVIEW,
    BITAND(q.flags, 1125899906842624) = 0 AS SNOWVI_DATA_AVAILABLE,
    temp.perfsol.get_deployment_link(q.deployment, q.uuid) AS SNOWVI_LINK
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V q
JOIN params p ON q.uuid = p.uuid
WHERE q.created_on BETWEEN DATEADD(minute, -20, p.uuid_ts) AND DATEADD(minute, 20, p.uuid_ts)
LIMIT 1;
```

### Step 3: Present Results & SnowVI Status (REQUIRED)

**ALWAYS present this step to the user.** Display the query overview and SnowVI status:

#### If `SNOWVI_DATA_AVAILABLE = true`:

```
**Query Overview:**
| Field | Value |
|-------|-------|
| Query ID | <QUERY_ID> |
| Snowflake Account ID | <ACCOUNT_ID> |
| Deployment | <DEPLOYMENT> |
| Duration | <TOTAL_DURATION_MS> ms |


✅ **SnowVI data is available** for this query.

**SnowVI Link:** <SNOWVI_LINK>

**To download the SnowVI JSON for deeper analysis:**
1. Open the SnowVI link above
2. Wait for the query profile to load
3. Click the **"Export"** button (top-right)
4. Select **"Export as JSON"**
5. Save the file locally
6. Re-run this skill with the path to the downloaded JSON
```

Then ask:

```json
{
  "questions": [
    {
      "header": "Continue",
      "question": "How would you like to proceed?",
      "type": "options",
      "multiSelect": false,
      "options": [
        {"label": "Continue without SnowVI", "description": "Proceed with basic Snowhouse analysis"},
        {"label": "I have the JSON", "description": "I downloaded the SnowVI JSON and will provide the path"}
      ]
    }
  ]
}
```

**If user selects "I have the JSON"**, first find the newest JSON file in ~/Downloads:

```bash
ls -t ~/Downloads/*.json 2>/dev/null | head -1
```

Then ask for the path, using the newest JSON file as the default (or fallback to generic path if none found):

```json
{
  "questions": [
    {"header": "SnowVI JSON", "question": "Enter the path to the SnowVI JSON file:", "type": "text", "defaultValue": "<newest_json_file_or_~/Downloads/snowvi-export.json>"}
  ]
}
```

#### If `SNOWVI_DATA_AVAILABLE = false`:

```
**Query Overview:**
| Field | Value |
|-------|-------|
| Query ID | <QUERY_ID> |
| Deployment | <DEPLOYMENT> |
| Duration | <TOTAL_DURATION_MS> ms |
| Account ID | <ACCOUNT_ID> |

❌ **SnowVI data was NOT persisted** for this query (flag not set).

**SnowVI Link:** <SNOWVI_LINK> (basic view only, no detailed profiling)

Proceeding with Snowhouse-only analysis.
```

Then continue directly to Step 4.

### Step 4: Gather Analysis Options

```json
{
  "questions": [
    {
      "header": "Options",
      "question": "Select analysis options:",
      "type": "options",
      "multiSelect": true,
      "options": [
        {"label": "History table", "description": "Include query history timeline"},
        {"label": "Debug mode", "description": "Show detailed progress"}
      ]
    }
  ]
}
```

### Step 5: Fetch Full Query Metadata

Use the `DEPLOYMENT`, `ACCOUNT_ID`, and `QUERY_TIMESTAMP` from Step 2:

```sql
SELECT
    uuid AS QUERY_ID,
    account_id AS ACCOUNT_ID,
    total_duration AS TOTAL_DURATION_MS,
    dur_compiling AS DUR_COMPILING_MS,
    dur_gs_executing AS DUR_GS_EXECUTING_MS,
    dur_xp_executing AS DUR_XP_EXECUTING_MS,
    access_kv_table AS ACCESS_KV_TABLE,
    database_name AS DATABASE_NAME,
    schema_name AS SCHEMA_NAME,
    warehouse_name AS WAREHOUSE_NAME,
    LEFT(description, 500) AS QUERY_PREVIEW,
    stats:stats.producedRows::NUMBER AS ROWS_PRODUCED,
    stats:stats.snowTramFDBIOBytes::NUMBER AS FDB_IO_BYTES,
    error_code AS ERROR_CODE,
    query_parameterized_hash AS QUERY_HASH,
    created_on AS CREATED_ON
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_JPS_V
WHERE uuid = '<QUERY_UUID>'
  AND account_id = <ACCOUNT_ID>
  AND created_on BETWEEN DATEADD(minute, -20, '<QUERY_TIMESTAMP>'::timestamp) AND DATEADD(minute, 20, '<QUERY_TIMESTAMP>'::timestamp)
LIMIT 1;
```

### Step 6: Fetch Query History (If Selected)

Use the `QUERY_HASH` and `ACCOUNT_ID` from Step 2:

```sql
WITH executions AS (
    SELECT
        DATE(created_on) AS execution_date,
        total_duration AS duration_ms
    FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_JPS_V
    WHERE query_parameterized_hash = '<QUERY_HASH>'
      AND account_id = '<ACCOUNT_ID>'
      AND created_on >= DATEADD(day, -30, CURRENT_TIMESTAMP())
      AND error_code IS NULL
)
SELECT
    execution_date,
    COUNT(*) AS execution_count,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50_latency,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_latency,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_latency
FROM executions
GROUP BY execution_date
ORDER BY execution_date DESC;
```

### Step 7: Apply Analysis Heuristics

| Metric | Threshold | Finding |
|--------|-----------|---------|
| `TOTAL_DURATION_MS` > 1000 | Slow query | Review execution plan |
| `DUR_XP_EXECUTING_MS` > 500 | XP bottleneck | Check index usage |
| `FDB_IO_BYTES` > 10MB | High FDB I/O | Consider index optimization |
| `ACCESS_KV_TABLE` = false | Not using HT path | Query may not benefit from HT |
| `DUR_COMPILING_MS` > 200 | Slow compilation | Check for plan cache issues |

## Step 8: Log Telemetry (REQUIRED)

After completing analysis, log telemetry:

```bash
snow sql -c Snowhouse -q "
INSERT INTO AFE.PUBLIC_APP_STATE.APP_EVENTS (
    APP, APP_NAME, APP_VERSION,
    USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
    ACTION_TYPE, ACTION_CONTEXT, SUCCESS
)
SELECT
    'unistore-query-analyzer',
    'unistore-query-analyzer',
    '0.4.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    'RUN_ANALYSIS',
    PARSE_JSON('{
        \"query_uuid\": \"<QUERY_UUID>\",
        \"account_id\": \"<ACCOUNT_ID>\",
        \"deployment\": \"<DEPLOYMENT>\",
        \"total_duration_ms\": <DURATION>,
        \"analysis_method\": \"sql_fallback\",
        \"snowvi_enriched\": <true|false>,
        \"findings_count\": <COUNT>,
        \"grade\": \"<GRADE>\"
    }'),
    TRUE
;"
```

## Output

Present analysis results with:
- **Query Overview**: UUID, deployment, account, duration
- **Performance Breakdown**: Compilation, GS execution, XP execution times
- **Findings**: Based on heuristics above
- **SnowVI Link**: If available
- **Recommendations**: Actionable next steps

---

## Python Script (DISABLED)

> **Note:** Python script is currently disabled due to Snowpark cffi memory issues. Use SQL fallback above.

<!--
### Option A: Python Script (Full Analysis)

```bash
python scripts/run_ht_analysis.py \
  --uuid "<query_uuid>" \
  --snowvi-path "<path_if_provided>" \
  --snowhouse-connection Snowhouse \
  --include-snowvi-link \
  --include-history-table
```

| Flag | Purpose |
|------|---------|
| `--uuid` | Query UUID to analyze |
| `--snowvi-path` | SnowVI JSON path (if provided) |
| `--deployment` | Override deployment detection |
| `--comparison-uuid` | Second UUID for comparison |
| `--include-snowvi-link` | Generate SnowVI URL |
| `--include-history-table` | Include history data |
| `--debug` | Verbose output |
| `--quick` | Skip LLM, deterministic only |
-->

## References

- `references/workflow.md` - Detailed workflow steps
- `references/json_schema.md` - Full output schema
- `references/sql_fallback.md` - SQL queries for manual analysis
- `ht_analyzer/field_manual/` - Finding-specific documentation
