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

### Step 2: Lookup Query & Fetch Full Metadata

**If user did NOT provide a SnowVI JSON path**, lookup the query and fetch all metadata:

```sql
WITH params AS (
    SELECT 
        '<QUERY_UUID>'::string AS uuid,
        TO_TIMESTAMP(TO_NUMBER(LEFT('<QUERY_UUID>', 8), 'XXXXXXXX') * 60) AS uuid_ts
)
SELECT
    q.uuid AS QUERY_ID,
    q.deployment AS DEPLOYMENT,
    q.account_id AS ACCOUNT_ID,
    q.created_on AS QUERY_TIMESTAMP,
    q.total_duration AS TOTAL_DURATION_MS,
    q.dur_compiling AS DUR_COMPILING_MS,
    q.dur_gs_executing AS DUR_GS_EXECUTING_MS,
    q.dur_xp_executing AS DUR_XP_EXECUTING_MS,
    q.access_kv_table AS ACCESS_KV_TABLE,
    q.database_name AS DATABASE_NAME,
    q.schema_name AS SCHEMA_NAME,
    q.warehouse_name AS WAREHOUSE_NAME,
    q.query_parameterized_hash AS QUERY_HASH,
    LEFT(q.description, 300) AS QUERY_PREVIEW,
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

**After loading the JSON, verify it matches the query UUID:**

```bash
python3 -c "
import json
with open('<JSON_PATH>') as f:
    d = json.load(f)
query_id = d.get('queryData',{}).get('data',{}).get('globalInfo',{}).get('queryOverview',{}).get('id','')
print(query_id)
"
```

- If the JSON `id` matches `<QUERY_UUID>`, proceed with analysis
- If it does NOT match, inform the user:

```
❌ **JSON mismatch:** The SnowVI JSON contains query ID `<JSON_QUERY_ID>` but you requested `<QUERY_UUID>`.
```

Then ask for a different file:

```json
{
  "questions": [
    {"header": "SnowVI JSON", "question": "Enter the path to a different SnowVI JSON file:", "type": "text", "defaultValue": "~/Downloads/snowvi-export.json"}
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

### Step 5: Fetch Query History (If Selected)

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

### Step 6: Apply Analysis Heuristics

| Metric | Threshold | Finding |
|--------|-----------|---------|
| `TOTAL_DURATION_MS` > 1000 | Slow query | Review execution plan |
| `DUR_XP_EXECUTING_MS` > 500 | XP bottleneck | Check index usage |
| `FDB_IO_BYTES` > 10MB | High FDB I/O | Consider index optimization |
| `ACCESS_KV_TABLE` = false | Not using HT path | Query may not benefit from HT |
| `DUR_COMPILING_MS` > 200 | Slow compilation | Check for plan cache issues |

### Step 7: Verify Best Practices

Analyze the `QUERY_PREVIEW` (or full SQL from SnowVI JSON) for best practice violations:

#### Check 1: Bind Parameters

If the query contains predicates with literal values (e.g., `WHERE id = 123` or `WHERE name = 'foo'`), warn:

```
⚠️ **Literal values detected in predicates**

The query uses literal values instead of bind parameters:
- Example: `WHERE entity_name = 'CDed'`

**Recommendation:** Use bind parameters (e.g., `WHERE entity_name = ?`) to:
- Enable plan caching
- Improve query reuse
- Reduce compilation overhead
```

#### Check 2: CTEs with JOINs

If the query uses a CTE (`WITH ... AS`) AND contains a JOIN between tables, warn:

```
⚠️ **CTE with JOIN detected**

The query uses a Common Table Expression (CTE) with JOIN operations.

**Warning:** Foreign key relationships defined on Hybrid Tables will NOT be used 
when joining through CTEs. The optimizer cannot leverage FK constraints for 
join elimination or cardinality estimation.

**Recommendation:** Consider rewriting the query without CTEs if FK optimization is needed.
```

#### Detection Logic

```python
sql_text = "<QUERY_PREVIEW or full SQL from SnowVI>"
sql_upper = sql_text.upper()

# Check 1: Literal values in predicates
has_literal_strings = re.search(r"=\s*'[^']+'", sql_text)
has_literal_numbers = re.search(r"=\s*\d+(?!\d*-)", sql_text)
uses_literals = has_literal_strings or has_literal_numbers

# Check 2: CTE with JOIN
has_cte = "WITH " in sql_upper and " AS " in sql_upper
has_join = " JOIN " in sql_upper
cte_with_join = has_cte and has_join
```

#### Additional Checks (SnowVI JSON Required)

If the user provided a SnowVI JSON file, perform these additional checks:

#### Check 3: Bind Parameter Type Mismatch

Extract bind parameters and column types from the SnowVI JSON and verify they match:

```python
# Extract from SnowVI JSON
operators = d.get('queryData',{}).get('data',{}).get('operators',{})
# Look for parameter bindings and compare data types with table column definitions

# Example warning if mismatch found:
```

```
⚠️ **Bind parameter type mismatch**

Parameter type does not match column type:
- Column `user_id` is `NUMBER(38,0)` but parameter is `VARCHAR`

**Impact:** Type mismatch can cause:
- Implicit type conversion overhead
- Index bypass (full table scan)
- Incorrect results in edge cases

**Recommendation:** Ensure application passes parameters with matching data types.
```

#### Check 4: Index Usage Verification

For queries with predicates, verify that all scan nodes are using indexes:

```python
# Extract operators from SnowVI JSON
operators = d.get('queryData',{}).get('data',{}).get('operators',{})

# Check each operator for scan type
for op_id, op in operators.items():
    op_type = op.get('operatorType', '')
    # Look for: RowScan, TableScan, IndexScan, etc.
    # Check if 'indexName' or similar field is present
```

**If a predicate exists but no index is used:**

```
⚠️ **No index used for predicate**

The query has filter predicates but is not using an index:
- Operator: `TableScan` on `full_load_notifications`
- Predicate: `entity_name = ?`

**Expected:** `RowScan` or `IndexScan` with index name

**Impact:** Full table scan instead of index lookup causes:
- Higher latency
- Increased FDB I/O
- Poor scalability as table grows

**Recommendation:** 
1. Verify an index exists on the filtered column(s)
2. Check if predicate data type matches index column type
3. Consider creating index: `CREATE INDEX idx_entity ON table(entity_name)`
```

**If ROW SCAN is used with an index:**

```
✅ **Index used for predicate**

- Operator: `RowScan` using index `idx_entity_processed`
- Predicate: `entity_name = ? AND is_processed = ?`
```

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
