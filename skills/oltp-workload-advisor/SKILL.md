---
name: oltp-workload-advisor
description: "Analyze customer workloads via Snowhouse to identify tables/queries suitable for conversion to Hybrid Tables, Interactive Analytics, or Snowflake Postgres. Use when: prospecting for Unistore opportunities, identifying conversion candidates, analyzing customer query patterns, detecting Postgres data flows, finding OLTP patterns. Triggers: customer workload analysis, hybrid table candidates, interactive analytics candidates, snowflake postgres, postgres migration, postgres consolidation, conversion opportunities, Unistore prospecting, OLTP analysis, point lookup patterns, CDC pipelines, RDS Aurora, workload advisor."
---

# OLTP Workload Advisor

## Setup

**Load** `references/snowhouse_reference.md` for table schemas and company aliases.
**Load** `references/scoring_guide.md` when scoring candidates.
**Load** `references/report_template.md` when generating markdown reports.

## Prerequisites
- Snowhouse connection configured (`Snowhouse` with PAT authentication)
- Access to `SNOWHOUSE.PRODUCT` and `SNOWHOUSE_IMPORT.<DEPLOYMENT>` views

## Products Evaluated

| Product | Best For | Key Indicators |
|---------|----------|----------------|
| **Hybrid Tables** | True OLTP with sub-10ms point lookups, high single-row DML | High UPDATE/DELETE %, parameterized queries, point lookups |
| **Interactive Analytics** | Read-heavy analytical on wide tables, sub-second response | 99%+ reads, wide tables, dashboard/BI patterns |
| **Snowflake Postgres** | PostgreSQL-compatible workloads, consolidate external Postgres | Postgres CDC pipelines, pg_* tables, RDS/Aurora data flows |

---

## Workflow

### Step 1: Collect Customer Information

```json
{
  "questions": [
    {"header": "Customer", "question": "Enter the customer name (or partial name for search)", "type": "text", "defaultValue": "Acme Corp"},
    {"header": "Alternate Name", "question": "Enter alternate/former company name if known (or leave blank)", "type": "text", "defaultValue": ""},
    {"header": "Account Locator", "question": "Enter account locator if known (e.g., GCB59607)", "type": "text", "defaultValue": ""},
    {"header": "Deployment", "question": "Enter deployment region if known (or 'unknown' to search all)", "type": "text", "defaultValue": "unknown"},
    {"header": "Analysis Period", "question": "How many days of history to analyze?", "type": "options", "multiSelect": false, "options": [
      {"label": "7 days", "description": "Quick analysis of recent activity"},
      {"label": "14 days", "description": "Two weeks of patterns"},
      {"label": "30 days", "description": "Full month analysis (recommended)"}
    ]},
    {"header": "Output Format", "question": "What output format do you prefer?", "type": "options", "multiSelect": false, "options": [
      {"label": "Markdown Report", "description": "Standard markdown report file"},
      {"label": "Streamlit Dashboard", "description": "Interactive Plotly dashboard with visualizations"}
    ]},
    {"header": "Report Path", "question": "Where should the analysis report be saved?", "type": "text", "defaultValue": "/path/to/customer/folder/"}
  ]
}
```

---

### Step 2: Find Customer Account(s)

```sql
SELECT DISTINCT a.ID as ACCOUNT_ID, a.NAME as ACCOUNT_NAME, a.DEPLOYMENT, a.CREATED_ON
FROM SNOWHOUSE.PRODUCT.ALL_LIVE_ACCOUNTS a
WHERE a.NAME = '<ACCOUNT_LOCATOR>'
   OR UPPER(a.NAME) ILIKE '%<CUSTOMER_NAME>%'
   OR UPPER(a.NAME) ILIKE '%<ALTERNATE_NAME>%'
ORDER BY a.CREATED_ON DESC LIMIT 20;
```

**If multiple accounts found**, ask user to select one or analyze all.

---

### Step 3: Account Query Volume Analysis

```sql
-- Daily query volume (last N days)
SELECT DATE_TRUNC('day', jf.CREATED_HOUR) as DAY,
    SUM(jf.JOBS) as TOTAL_QUERIES,
    SUM(CASE WHEN st.STATEMENT_TYPE = 'SELECT' THEN jf.JOBS ELSE 0 END) as SELECTS,
    SUM(CASE WHEN st.STATEMENT_TYPE IN ('INSERT', 'UPDATE', 'DELETE', 'MERGE') THEN jf.JOBS ELSE 0 END) as DML,
    ROUND(AVG(jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0)), 2) as AVG_DURATION_MS
FROM SNOWHOUSE.PRODUCT.JOB_FACT jf
JOIN SNOWHOUSE.PRODUCT.STATEMENT_TYPE st ON jf.STATEMENT_TYPE_ID = st.ID
WHERE jf.DEPLOYMENT = '<DEPLOYMENT>' AND jf.ACCOUNT_ID = <ACCOUNT_ID>
  AND jf.CREATED_HOUR >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
GROUP BY DAY ORDER BY DAY DESC;
```

```sql
-- Statement type breakdown
SELECT st.STATEMENT_TYPE, SUM(jf.JOBS) as TOTAL_QUERIES,
    ROUND(SUM(jf.JOBS) * 100.0 / SUM(SUM(jf.JOBS)) OVER(), 4) as PCT,
    ROUND(AVG(jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0)), 2) as AVG_DURATION_MS
FROM SNOWHOUSE.PRODUCT.JOB_FACT jf
JOIN SNOWHOUSE.PRODUCT.STATEMENT_TYPE st ON jf.STATEMENT_TYPE_ID = st.ID
WHERE jf.DEPLOYMENT = '<DEPLOYMENT>' AND jf.ACCOUNT_ID = <ACCOUNT_ID>
  AND jf.CREATED_HOUR >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND st.STATEMENT_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE')
GROUP BY st.STATEMENT_TYPE ORDER BY TOTAL_QUERIES DESC;
```

---

### Step 4: Classify UPDATE Patterns (ETL vs OLTP)

```sql
SELECT CASE 
    WHEN je.DESCRIPTION ILIKE '%TEMP_DB%' OR je.DESCRIPTION ILIKE '%_STG%' OR je.DESCRIPTION ILIKE '%_TEMP%' THEN 'ETL/Staging'
    WHEN je.DESCRIPTION ILIKE '%SET%WHERE%=%?%' OR je.DESCRIPTION ILIKE '%SET%WHERE%=%:%' THEN 'Point Update (Parameterized)'
    WHEN je.DESCRIPTION ILIKE '%SET%WHERE%=%' AND je.DESCRIPTION NOT ILIKE '%IN (SELECT%' THEN 'Point Update (Literal)'
    ELSE 'Bulk/Other'
END as UPDATE_TYPE, COUNT(*) as COUNT, ROUND(AVG(je.TOTAL_DURATION), 2) as AVG_DURATION_MS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
  AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND je.DESCRIPTION ILIKE 'UPDATE%' AND je.ERROR_CODE IS NULL
GROUP BY UPDATE_TYPE ORDER BY COUNT DESC;
```

**Interpretation:**
- **Point Update (Parameterized)**: Strong HT candidates (OLTP pattern)
- **ETL/Staging**: Exclude from HT consideration

---

### Step 5: Identify Hybrid Table Candidates

```sql
-- Tables with UPDATE activity (excluding ETL/staging)
WITH update_queries AS (
    SELECT SPLIT_PART(SPLIT_PART(je.DESCRIPTION, ' ', 2), ' SET', 1) as TABLE_NAME,
        je.TOTAL_DURATION,
        CASE WHEN je.DESCRIPTION ILIKE '%WHERE%=%?%' OR je.DESCRIPTION ILIKE '%WHERE%=%:%' THEN 'Parameterized' ELSE 'Literal' END as QUERY_TYPE
    FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
    WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
      AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
      AND je.DESCRIPTION ILIKE 'UPDATE%' AND je.ERROR_CODE IS NULL
      AND je.DESCRIPTION NOT ILIKE '%TEMP_DB%' AND je.DESCRIPTION NOT ILIKE '%_STG%'
)
SELECT TABLE_NAME, COUNT(*) as UPDATE_COUNT,
    SUM(CASE WHEN QUERY_TYPE = 'Parameterized' THEN 1 ELSE 0 END) as PARAMETERIZED_COUNT,
    ROUND(AVG(TOTAL_DURATION), 2) as AVG_DURATION_MS,
    ROUND(MEDIAN(TOTAL_DURATION), 2) as P50_DURATION_MS
FROM update_queries WHERE TABLE_NAME IS NOT NULL AND LENGTH(TABLE_NAME) > 3
GROUP BY TABLE_NAME HAVING UPDATE_COUNT >= 500
ORDER BY UPDATE_COUNT DESC LIMIT 30;
```

```sql
-- Tables with DELETE activity
WITH delete_queries AS (
    SELECT SPLIT_PART(SPLIT_PART(REPLACE(je.DESCRIPTION, 'delete from ', 'DELETE FROM '), 'DELETE FROM ', 2), ' ', 1) as TABLE_NAME,
        je.TOTAL_DURATION
    FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
    WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
      AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
      AND je.DESCRIPTION ILIKE 'DELETE%' AND je.ERROR_CODE IS NULL
      AND je.DESCRIPTION NOT ILIKE '%TEMP_DB%' AND je.DESCRIPTION NOT ILIKE '%_STG%'
)
SELECT TABLE_NAME, COUNT(*) as DELETE_COUNT, ROUND(AVG(TOTAL_DURATION), 2) as AVG_DURATION_MS
FROM delete_queries WHERE TABLE_NAME IS NOT NULL AND LENGTH(TABLE_NAME) > 3
GROUP BY TABLE_NAME HAVING DELETE_COUNT >= 100
ORDER BY DELETE_COUNT DESC LIMIT 25;
```

---

### Step 6: Identify Interactive Analytics Candidates

```sql
-- Read-heavy tables (IA candidates)
WITH table_activity AS (
    SELECT SPLIT_PART(SPLIT_PART(je.DESCRIPTION, 'FROM ', 2), ' ', 1) as TABLE_NAME,
        CASE WHEN je.DESCRIPTION ILIKE 'SELECT%' THEN 'SELECT' ELSE 'DML' END as OP_TYPE,
        je.TOTAL_DURATION
    FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
    WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
      AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
      AND (je.DESCRIPTION ILIKE 'SELECT%FROM%' OR je.DESCRIPTION ILIKE 'INSERT%' OR je.DESCRIPTION ILIKE 'UPDATE%')
      AND je.ERROR_CODE IS NULL AND je.DESCRIPTION NOT ILIKE '%TEMP_DB%'
)
SELECT TABLE_NAME, COUNT(*) as TOTAL_OPS,
    SUM(CASE WHEN OP_TYPE = 'SELECT' THEN 1 ELSE 0 END) as SELECTS,
    SUM(CASE WHEN OP_TYPE = 'DML' THEN 1 ELSE 0 END) as DML,
    ROUND(SELECTS * 100.0 / COUNT(*), 2) as READ_PCT,
    ROUND(AVG(CASE WHEN OP_TYPE = 'SELECT' THEN TOTAL_DURATION END), 2) as AVG_SELECT_MS,
    CASE WHEN SELECTS * 100.0 / COUNT(*) >= 99 AND AVG(CASE WHEN OP_TYPE = 'SELECT' THEN TOTAL_DURATION END) BETWEEN 100 AND 5000 THEN 'STRONG'
         WHEN SELECTS * 100.0 / COUNT(*) >= 95 THEN 'MODERATE' ELSE 'LOW' END as IA_FIT
FROM table_activity WHERE TABLE_NAME IS NOT NULL AND LENGTH(TABLE_NAME) > 5
GROUP BY TABLE_NAME HAVING COUNT(*) >= 1000 AND SELECTS * 100.0 / COUNT(*) >= 90
ORDER BY IA_FIT, TOTAL_OPS DESC LIMIT 30;
```

---

### Step 7: Detect Postgres Data Patterns

Run these queries to identify Snowflake Postgres consolidation opportunities:

```sql
-- INBOUND: Postgres CDC/ETL patterns (data flowing INTO Snowflake)
SELECT CASE 
    WHEN je.DESCRIPTION ILIKE '%postgres%' THEN 'POSTGRES_DIRECT'
    WHEN je.DESCRIPTION ILIKE '%pg_%' AND je.DESCRIPTION NOT ILIKE '%page%' THEN 'PG_PREFIX'
    WHEN je.DESCRIPTION ILIKE '%_rds_%' OR je.DESCRIPTION ILIKE '%aurora%' THEN 'AWS_RDS_AURORA'
    WHEN je.DESCRIPTION ILIKE '%fivetran%' THEN 'FIVETRAN'
    WHEN je.DESCRIPTION ILIKE '%airbyte%' THEN 'AIRBYTE'
    WHEN je.DESCRIPTION ILIKE '%hvr%' OR je.DESCRIPTION ILIKE '%debezium%' THEN 'CDC_TOOL'
    ELSE 'OTHER_POSTGRES'
END as SOURCE_PATTERN, COUNT(*) as INBOUND_OPS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
  AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND je.ERROR_CODE IS NULL
  AND (je.DESCRIPTION ILIKE '%postgres%' OR je.DESCRIPTION ILIKE '%pg_%' OR je.DESCRIPTION ILIKE '%rds%' OR je.DESCRIPTION ILIKE '%aurora%' OR je.DESCRIPTION ILIKE '%debezium%')
  AND (je.DESCRIPTION ILIKE 'INSERT%' OR je.DESCRIPTION ILIKE 'MERGE%' OR je.DESCRIPTION ILIKE 'COPY INTO%')
GROUP BY SOURCE_PATTERN ORDER BY INBOUND_OPS DESC;
```

```sql
-- OUTBOUND: Data exports (potential Postgres destinations)
SELECT CASE 
    WHEN je.DESCRIPTION ILIKE '%@%postgres%' OR je.DESCRIPTION ILIKE '%@%pg_%' THEN 'POSTGRES_STAGE'
    WHEN je.DESCRIPTION ILIKE '%s3://%' THEN 'S3_EXPORT'
    WHEN je.DESCRIPTION ILIKE '%@%export%' THEN 'EXPORT_STAGE'
    ELSE 'OTHER_EXPORT'
END as EXPORT_PATTERN, COUNT(*) as OUTBOUND_OPS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
  AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND je.ERROR_CODE IS NULL
  AND je.DESCRIPTION ILIKE 'COPY INTO%@%' AND je.DESCRIPTION NOT ILIKE '%FROM @%'
GROUP BY EXPORT_PATTERN ORDER BY OUTBOUND_OPS DESC;
```

```sql
-- INBOUND destination tables (Postgres → Snowflake)
SELECT REGEXP_SUBSTR(TRIM(REGEXP_SUBSTR(je.DESCRIPTION, 'COPY INTO[[:space:]]+([^[:space:]]+)', 1, 1, 'e')), '[^.]+$') AS DESTINATION_TABLE,
    COUNT(*) AS INBOUND_LOAD_OPS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
  AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND je.ERROR_CODE IS NULL
  AND je.DESCRIPTION ILIKE 'COPY INTO%FROM%@%'
  AND (je.USER_NAME ILIKE '%FIVETRAN%' OR je.USER_NAME ILIKE '%HVR%' OR je.USER_NAME ILIKE '%AIRBYTE%' OR je.DESCRIPTION ILIKE '%postgres%')
GROUP BY DESTINATION_TABLE
HAVING INBOUND_LOAD_OPS >= 100
ORDER BY INBOUND_LOAD_OPS DESC LIMIT 50;
```

```sql
-- OUTBOUND source tables (Snowflake → Postgres via EXP_ naming)
SELECT REGEXP_SUBSTR(je.DESCRIPTION, 'FROM[[:space:]]+([A-Za-z0-9_]+)', 1, 1, 'e') AS SOURCE_TABLE,
    COUNT(*) AS EXPORT_OPS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
  AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND je.ERROR_CODE IS NULL
  AND (je.DESCRIPTION ILIKE '%EXP%' OR je.DESCRIPTION ILIKE 'COPY INTO%@%')
GROUP BY SOURCE_TABLE
HAVING EXPORT_OPS >= 50 AND SOURCE_TABLE ILIKE 'EXP%'
ORDER BY EXPORT_OPS DESC LIMIT 50;
```

---

### Step 8: Sample Query Text for Validation

```sql
-- Sample UPDATE queries for top candidate
SELECT LEFT(je.DESCRIPTION, 300) as QUERY_PREVIEW, je.TOTAL_DURATION as DURATION_MS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V je
WHERE je.ACCOUNT_ID = <ACCOUNT_ID>
  AND je.CREATED_ON >= DATEADD('day', -7, CURRENT_TIMESTAMP())
  AND je.DESCRIPTION ILIKE 'UPDATE%<CANDIDATE_TABLE>%' AND je.ERROR_CODE IS NULL
ORDER BY RANDOM() LIMIT 15;
```

---

### Step 9: Generate Output

**Option A: Markdown Report**
- **Load** `references/report_template.md`
- Fill in template with analysis results
- Save to user-specified path

**Option B: Streamlit Dashboard (Recommended)**

Save structured output files to `analysis_output/<customer_name>/`:
- `analysis_metadata.json` - Customer info, summary stats
- `daily_activity.csv` - Daily query timeline
- `statement_summary.csv` - Statement type breakdown
- `update_patterns.csv` - ETL vs OLTP classification
- `hybrid_candidates.csv` - HT candidate tables with scores
- `ia_candidates.csv` - IA candidate tables with scores
- `delete_activity.csv` - DELETE activity by table
- `postgres_inbound.csv` - Inbound Postgres patterns
- `postgres_outbound.csv` - Outbound export patterns
- `postgres_inbound_tables.csv` - Detailed inbound destination tables
- `postgres_outbound_tables.csv` - Detailed outbound source tables
- `current_ht_usage.csv` - Current Hybrid Tables usage
- `current_ia_usage.csv` - Current Interactive Analytics usage
- `current_postgres_usage.csv` - Current Snowflake Postgres usage

```bash
streamlit run /Users/atimm/Documents/Unistore/cortex_skills_repo/skills/oltp-workload-advisor/dashboard/app.py --server.port 8502 --server.headless true
```

---

### Step 10: Log Telemetry (REQUIRED)

**After completing the analysis, you MUST log telemetry.**

#### Step 10a: Get CoCo Request ID (Optional but Recommended)

If the Cortex Code session ID is available, retrieve the request_id for traceability:

```sql
-- Query to get CoCo request_id from session_id
SELECT DISTINCT
    REGEXP_SUBSTR(message, 'request_id=([a-f0-9-]+)', 1, 1, 'e') as request_id
FROM eng_cortexsearch.debugging.k8s_logs
WHERE logged_at::date > CURRENT_DATE - 1
  AND message ILIKE '%<SESSION_ID>%'
  AND message LIKE '%request_id=%'
LIMIT 1;
```

Use the first `request_id` returned for the telemetry log below.

#### Step 10b: Insert Telemetry Event

Execute via `snow sql`:

```bash
snow sql -c Snowhouse -q "
INSERT INTO AFE.PUBLIC_APP_STATE.APP_EVENTS (
    APP, APP_NAME, APP_VERSION,
    USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
    SALESFORCE_ACCOUNT_NAME, SNOWFLAKE_ACCOUNT_ID, DEPLOYMENT,
    ACTION_TYPE, ACTION_CONTEXT,
    RECOMMENDATION,
    SUCCESS
)
SELECT
    'oltp-workload-advisor',
    'oltp-workload-advisor',
    '2.5.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    '<CUSTOMER_NAME>',
    '<ACCOUNT_ID>',
    '<DEPLOYMENT>',
    'RUN_PROPENSITY_ANALYSIS',
    PARSE_JSON('{
        \"customer_name\": \"<CUSTOMER_NAME>\",
        \"account_name\": \"<ACCOUNT_NAME>\",
        \"analysis_days\": <DAYS>,
        \"output_format\": \"<markdown|streamlit>\",
        \"report_path\": \"<REPORT_PATH>\",
        \"coco_request_id\": \"<REQUEST_ID>\",
        \"coco_session_id\": \"<SESSION_ID>\",
        \"analysis_results\": {
            \"total_queries_analyzed\": <TOTAL_QUERIES>,
            \"hybrid_table_candidates\": <HT_COUNT>,
            \"interactive_analytics_candidates\": <IA_COUNT>,
            \"postgres_inbound_ops\": <PG_INBOUND>,
            \"postgres_outbound_ops\": <PG_OUTBOUND>,
            \"top_hybrid_candidate\": \"<TOP_HT_TABLE>\",
            \"top_ia_candidate\": \"<TOP_IA_TABLE>\",
            \"postgres_candidate\": <true|false>
        },
        \"workload_profile\": {
            \"select_pct\": <SELECT_PCT>,
            \"update_pct\": <UPDATE_PCT>,
            \"delete_pct\": <DELETE_PCT>,
            \"parameterized_update_pct\": <PARAM_PCT>
        }
    }'),
    '<PRIMARY_RECOMMENDATION>',
    TRUE
;"
```

**Placeholder Reference:**

| Placeholder | Description |
|-------------|-------------|
| `<CUSTOMER_NAME>` | Customer/company name |
| `<ACCOUNT_ID>` | Snowflake account ID (numeric) |
| `<ACCOUNT_NAME>` | Account locator name |
| `<DEPLOYMENT>` | Deployment region (e.g., va, prod1) |
| `<DAYS>` | Analysis period (7, 14, or 30) |
| `<SESSION_ID>` | CoCo session ID (UUID format, or "unknown") |
| `<REQUEST_ID>` | CoCo request ID from Step 10a (or "unknown") |
| `<TOTAL_QUERIES>` | Total queries analyzed |
| `<HT_COUNT>` | Hybrid Table candidates count |
| `<IA_COUNT>` | Interactive Analytics candidates count |
| `<PG_INBOUND>` | Inbound Postgres operations |
| `<PG_OUTBOUND>` | Outbound export operations |
| `<TOP_HT_TABLE>` | Top HT candidate table (or "none") |
| `<TOP_IA_TABLE>` | Top IA candidate table (or "none") |
| `<PRIMARY_RECOMMENDATION>` | Hybrid Tables, Interactive Analytics, Snowflake Postgres, or None |

---

## Telemetry Configuration

| Setting | Value |
|---------|-------|
| Database | `AFE` |
| Schema | `PUBLIC_APP_STATE` |
| Table | `APP_EVENTS` |
| App Name | `oltp-workload-advisor` |
| App Version | `2.5.0` |

### CoCo Request ID Lookup

To correlate telemetry with Cortex Code sessions:

```sql
-- Get request_ids from a session
SELECT
    logged_at,
    REGEXP_SUBSTR(message, 'request_id=([a-f0-9-]+)', 1, 1, 'e') as request_id,
    REGEXP_SUBSTR(message, 'took=([^\s]+)', 1, 1, 'e') as duration,
    CASE 
        WHEN message ILIKE '%ERROR CODINGAGENT%' THEN 'ERROR'
        WHEN message ILIKE '%SLOW CODINGAGENT%' THEN 'SLOW'
        ELSE 'OK'
    END as status
FROM eng_cortexsearch.debugging.k8s_logs
WHERE logged_at::date > CURRENT_DATE - 7
  AND message ILIKE '%<SESSION_ID>%'
  AND message LIKE '%request_id=%'
ORDER BY logged_at DESC
LIMIT 100;
```

---

## Stopping Points

- ✋ **Step 1**: After collecting customer info
- ✋ **Step 2**: If multiple accounts found, ask user to select
- ✋ **Step 9**: Before generating final output, confirm format preference

---

## Output

- **Markdown**: Report file at user-specified path
- **Dashboard**: Interactive Streamlit app at http://localhost:8502

---

## When to Apply This Skill

- User asks to "analyze [customer] workload for Unistore opportunities"
- User asks "which tables should be Hybrid Tables for [customer]"
- User asks "identify Interactive Analytics candidates for [customer]"
- User mentions "conversion candidates", "workload analysis", "Postgres consolidation"
- User asks "is [customer] a good fit for Snowflake Postgres"
