---
name: unistore-query-analyzer
description: "Diagnose slow Hybrid Table queries. Use when: analyzing HT performance, debugging HT latency, comparing before/after query runs."
version: 0.5.0
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

If the user provided a SnowVI JSON file, use the `references/snowvi_parser.py` module:

```bash
python3 references/snowvi_parser.py "<JSON_PATH>"
```

Or inline:

```python
import json

with open('<JSON_PATH>') as f:
    d = json.load(f)

# SnowVI JSON Structure:
# - d['queryId'] - Query UUID
# - d['queryData']['data']['globalInfo']['queryOverview']['sqlText'] - Full SQL
# - d['sdls'][step_id]['rsos'] - Scan operators (RSOs)
# - d['sdls'][step_id]['catalog']['objects'] - Table definitions
# - d['sdls'][step_id]['catalog']['columns'] - Column definitions
# - d['processes'][n]['lastReport']['xpRsoPerfAnalyzerStats'] - HT scan performance
# - d['processes'][n]['lastReport']['snowtramFdbStats'] - FDB I/O stats

# Extract scan operators from SDLs
sdls = d.get('sdls', {})
for step_id, step in sdls.items():
    # Table catalog
    tables = {obj['id']: obj['name'] for obj in step.get('catalog', {}).get('objects', [])}
    
    # Scan operators (RSOs)
    for rso in step.get('rsos', []):
        rso_type = rso.get('type', '')  # e.g., 'HybridKvTableScan'
        table_id = rso.get('object', 0)
        table_name = tables.get(table_id, f'table_{table_id}')
        filter_push = rso.get('filterPush', [])  # Pushed predicates = filter optimization
        has_filter = len(filter_push) > 0
        
        print(f"{rso_type} on {table_name}: filter_pushdown={has_filter}")
```

#### Check 3: Hybrid Table Scan Performance

Extract HT scan stats from process reports:

```python
# Extract HT scan performance from worker processes
processes = d.get('processes', [])
for proc in processes:
    for perf in proc.get('lastReport', {}).get('xpRsoPerfAnalyzerStats', []):
        if perf.get('statType') == 'hybridTableScanPerformanceStats':
            print(f"RSO: {perf.get('rso')}")
            print(f"  Exec time: {perf.get('execTime', 0) / 1000:.2f} ms")
            print(f"  Rows: {perf.get('numFilteredRows', 0):,} / {perf.get('totalNumRows', 0):,}")
            print(f"  Bytes: {perf.get('totalNumBytes', 0):,}")
            print(f"  Ranges: {perf.get('processedRanges', 0)}")
            print(f"  Skew: {perf.get('skew', 0)}%")
```

**Example output:**

```
✅ **Hybrid Table Scan Performance**

| RSO | Table | Exec Time | Rows (filtered/total) | Selectivity | Ranges | Skew |
|-----|-------|-----------|----------------------|-------------|--------|------|
| KvTableScan0 | FULL_LOAD_NOTIFICATIONS | 8.3 ms | 2 / 2 | 100% | 13 | 82% |
```

#### Check 4: Filter Pushdown Verification

For Hybrid Tables, verify predicates are pushed down:

```python
# Check if filters are pushed to scan operators
for step_id, step in sdls.items():
    for rso in step.get('rsos', []):
        if 'Hybrid' in rso.get('type', '') or 'Kv' in rso.get('type', ''):
            filter_push = rso.get('filterPush', [])
            if filter_push:
                print(f"✅ Filter pushdown on {rso['type']}: {len(filter_push)} predicate(s)")
            else:
                print(f"⚠️ No filter pushdown on {rso['type']} - possible full scan")
```

**If filter pushdown is present:**

```
✅ **Filter pushdown active**

- Operator: `HybridKvTableScan` on `FULL_LOAD_NOTIFICATIONS`
- Pushed predicates: 2 (entity_name, is_processed)
- This enables efficient index-based lookup
```

**If NO filter pushdown:**

```
⚠️ **No filter pushdown detected**

The query scans `HybridKvTableScan` without pushed predicates.

**Impact:**
- Full table scan instead of index lookup
- Higher latency and FDB I/O
- Poor scalability as table grows

**Possible causes:**
1. Filter column not in predicate
2. Type mismatch preventing pushdown
3. Complex expression not pushable

**Recommendation:** Check that filter columns match index columns and types.
```

#### Check 5: FDB I/O Analysis

```python
# Extract FDB stats from processes
total_fdb_io = 0
total_fdb_exec_us = 0

for proc in d.get('processes', []):
    for fdb in proc.get('lastReport', {}).get('snowtramFdbStats', []):
        total_fdb_io += fdb.get('fdbIoBytes', 0) or 0
        total_fdb_exec_us += fdb.get('fdbExecutionUs', 0) or 0

print(f"FDB I/O: {total_fdb_io:,} bytes")
print(f"FDB Execution: {total_fdb_exec_us / 1000:.2f} ms")
```

**Thresholds:**
- FDB I/O > 10MB: Consider index optimization
- FDB Execution > 100ms: Investigate throttling or contention

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
    '0.5.0',
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
- `references/snowvi_parser.py` - Python module for parsing SnowVI JSON
- `ht_analyzer/field_manual/` - Finding-specific documentation

## SnowVI JSON Schema Reference

```
d = json.load(snowvi_file)

# Top-level
d['queryId']                    # Query UUID
d['queryData']                  # Main query data
d['workersData']                # Worker execution data (list)
d['processes']                  # Process stats (list)
d['sdls']                       # SDL per step (dict: step_id -> SDL)

# Query Overview
d['queryData']['data']['globalInfo']['queryOverview']
    .id                         # Query UUID
    .sqlText                    # Full SQL text
    .status                     # SUCCESS, FAILED, etc.
    .state                      # SUCCEEDED, etc.

# Session Info
d['queryData']['data']['globalInfo']['session']
    .accountName                # Snowflake account
    .userName                   # User who ran query
    .clientApplication          # e.g., "PythonConnector 3.17.3"

# SDL Structure (per step)
d['sdls'][step_id]
    .sql                        # SQL for this step
    .stmtType                   # SELECT, INSERT, etc.
    .catalog.objects[]          # Table definitions
        .id                     # Table ID
        .name                   # Full table name (DB.SCHEMA.TABLE)
        .databaseName           # Database name
        .schemaName             # Schema name
        .datastoreId            # Datastore ID
    .catalog.columns[]          # Column definitions
        .id                     # Column ID
        .label                  # Column label
        .logicalType            # text, fixed, boolean, etc.
        .physicalType           # lob, sb8, etc.
    .rsos[]                     # Scan operators
        .id                     # RSO ID
        .type                   # HybridKvTableScan, TableScan, etc.
        .object                 # Table ID reference
        .logicalId              # Logical plan ID
        .filterPush[]           # Pushed predicates (key for index usage!)
            .colPos[]           # Column positions
            .filter             # Filter definition
        .scansetId              # Scan set ID
        .blobScanMode           # Scan mode

# Process Stats (per worker)
d['processes'][n]['lastReport']
    .stats                      # General stats dict
    .snowtramFdbStats[]         # FDB I/O stats
        .dbId                   # Database ID
        .fdbIoBytes             # FDB I/O bytes
        .fdbExecutionUs         # FDB execution microseconds
        .fdbThrottlingUs        # FDB throttling microseconds
    .xpRsoPerfAnalyzerStats[]   # RSO performance stats
        .statType               # "hybridTableScanPerformanceStats"
        .rso                    # RSO name (e.g., "KvTableScan0")
        .rsoId                  # RSO ID
        .tableId                # Table ID
        .execTime               # Execution time (microseconds)
        .numFilteredRows        # Rows after filtering
        .totalNumRows           # Total rows scanned
        .totalNumBytes          # Bytes scanned
        .processedRanges        # Number of ranges processed
        .columnarCacheParquetBytes  # Cache hit bytes
        .skew                   # Skew percentage
```
