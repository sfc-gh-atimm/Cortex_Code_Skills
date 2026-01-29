---
name: oltp-health-check
description: "Health check and performance monitoring for existing OLTP workloads (Hybrid Tables, Interactive Analytics, Snowflake Postgres). Use when: monitoring customer OLTP performance, diagnosing degradation, reviewing adoption health, identifying optimization opportunities. Triggers: health check, OLTP health, hybrid table performance, IA health, postgres performance, workload monitoring, performance review, HT latency, FDB timeout."
---

# OLTP Health Check

## Setup

**Load** `references/snowhouse_reference.md` for table schemas.
**Load** `references/health_scoring_guide.md` when scoring health metrics.
**Load** `references/issue_patterns.md` when detecting issues and generating recommendations.

## Prerequisites
- Snowhouse connection configured (`Snowhouse` with PAT authentication)
- Access to `SNOWHOUSE.PRODUCT` and `SNOWHOUSE_IMPORT.<DEPLOYMENT>` views

## Products Monitored

| Product | Health Focus | Key Metrics |
|---------|--------------|-------------|
| **Hybrid Tables** | OLTP latency, FDB health | P50/P99 latency, FDB timeouts, optimal query % |
| **Interactive Analytics** | Query performance, cache efficiency | Sub-second %, cache hit rate, compilation time |
| **Snowflake Postgres** | Connection health, throughput | Query latency, connection patterns, transaction rate |

---

## Workflow

### Step 1: Collect Customer Information

```json
{
  "questions": [
    {"header": "Customer", "question": "Enter the customer name (or partial name for search)", "type": "text", "defaultValue": "Acme Corp"},
    {"header": "Account Locator", "question": "Enter account locator if known (e.g., GCB59607)", "type": "text", "defaultValue": ""},
    {"header": "Deployment", "question": "Enter deployment region if known (or 'unknown' to search all)", "type": "text", "defaultValue": "unknown"},
    {"header": "Analysis Period", "question": "How many days of history to analyze?", "type": "options", "multiSelect": false, "options": [
      {"label": "7 days", "description": "Quick health check"},
      {"label": "14 days", "description": "Two weeks trend analysis"},
      {"label": "30 days", "description": "Full month analysis (recommended)"}
    ]},
    {"header": "Output Format", "question": "What output format do you prefer?", "type": "options", "multiSelect": false, "options": [
      {"label": "Markdown Report", "description": "Standard markdown health report"},
      {"label": "Streamlit Dashboard", "description": "Interactive dashboard with visualizations"}
    ]},
    {"header": "Report Path", "question": "Where should the health report be saved?", "type": "text", "defaultValue": "/path/to/customer/folder/"}
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
ORDER BY a.CREATED_ON DESC LIMIT 20;
```

**If multiple accounts found**, ask user to select one or analyze all.

---

### Step 3: Detect Current OLTP Product Usage

#### 3a: Hybrid Tables Usage Detection

```sql
SELECT 
    'HYBRID_TABLES' as PRODUCT,
    COUNT(*) as TOTAL_QUERIES,
    SUM(CASE WHEN ACCESS_KV_TABLE THEN 1 ELSE 0 END) as HT_QUERIES,
    ROUND(SUM(CASE WHEN ACCESS_KV_TABLE THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) as HT_QUERY_PCT,
    MIN(CASE WHEN ACCESS_KV_TABLE THEN CREATED_ON END) as FIRST_HT_QUERY,
    MAX(CASE WHEN ACCESS_KV_TABLE THEN CREATED_ON END) as LAST_HT_QUERY
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL;
```

#### 3b: Interactive Analytics Usage Detection

```sql
SELECT 
    'INTERACTIVE_ANALYTICS' as PRODUCT,
    COUNT(*) as TOTAL_QUERIES,
    SUM(CASE WHEN WAREHOUSE_TYPE = 'INTERACTIVE' OR DESCRIPTION ILIKE '%INTERACTIVE%' THEN 1 ELSE 0 END) as IA_QUERIES,
    ROUND(SUM(CASE WHEN TOTAL_DURATION < 1000 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) as SUB_SECOND_PCT
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
  AND DESCRIPTION ILIKE 'SELECT%';
```

#### 3c: Snowflake Postgres Usage Detection

```sql
SELECT 
    'SNOWFLAKE_POSTGRES' as PRODUCT,
    COUNT(*) as TOTAL_QUERIES,
    SUM(CASE WHEN CLIENT_APPLICATION_ID ILIKE '%postgres%' OR CLIENT_APPLICATION_ID ILIKE '%psycopg%' 
             OR CLIENT_APPLICATION_ID ILIKE '%JDBC%PostgreSQL%' THEN 1 ELSE 0 END) as POSTGRES_PROTOCOL_QUERIES
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL;
```

**Interpretation:**
- If HT_QUERIES > 0: Customer has active Hybrid Tables
- If IA_QUERIES > 0: Customer uses Interactive Analytics
- If POSTGRES_PROTOCOL_QUERIES > 0: Customer uses Snowflake Postgres

---

### Step 4: Hybrid Tables Health Assessment

#### 4a: Daily HT Latency Trends

```sql
SELECT 
    DATE_TRUNC('day', CREATED_ON) as DAY,
    COUNT(*) as HT_QUERIES,
    ROUND(AVG(TOTAL_DURATION), 2) as AVG_MS,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY TOTAL_DURATION), 2) as P50_MS,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY TOTAL_DURATION), 2) as P95_MS,
    ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY TOTAL_DURATION), 2) as P99_MS,
    MAX(TOTAL_DURATION) as MAX_MS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND ACCESS_KV_TABLE = TRUE
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
GROUP BY DAY ORDER BY DAY DESC;
```

#### 4b: HT Performance Tier Distribution

```sql
SELECT 
    CASE 
        WHEN TOTAL_DURATION < 10 THEN '1_OPTIMAL (<10ms)'
        WHEN TOTAL_DURATION < 100 THEN '2_ACCEPTABLE (10-100ms)'
        WHEN TOTAL_DURATION < 1000 THEN '3_SLOW (100ms-1s)'
        ELSE '4_CRITICAL (>1s)'
    END as PERFORMANCE_TIER,
    COUNT(*) as QUERY_COUNT,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as PCT,
    ROUND(AVG(TOTAL_DURATION), 2) as AVG_DURATION_MS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND ACCESS_KV_TABLE = TRUE
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
GROUP BY PERFORMANCE_TIER ORDER BY PERFORMANCE_TIER;
```

#### 4c: FDB Health Check (Errors & Timeouts)

```sql
SELECT 
    DATE_TRUNC('day', CREATED_ON) as DAY,
    COUNT(*) as TOTAL_HT_QUERIES,
    SUM(CASE WHEN ERROR_CODE IS NOT NULL THEN 1 ELSE 0 END) as HT_ERRORS,
    SUM(CASE WHEN ERROR_CODE ILIKE '%FDB%' OR ERROR_CODE ILIKE '%TIMEOUT%' THEN 1 ELSE 0 END) as FDB_TIMEOUTS,
    ROUND(SUM(CASE WHEN ERROR_CODE ILIKE '%FDB%' OR ERROR_CODE ILIKE '%TIMEOUT%' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 4) as FDB_TIMEOUT_RATE
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND ACCESS_KV_TABLE = TRUE
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
GROUP BY DAY ORDER BY DAY DESC;
```

#### 4d: HT Query Pattern Analysis

```sql
SELECT 
    CASE 
        WHEN DESCRIPTION ILIKE 'SELECT%WHERE%=%' AND DESCRIPTION NOT ILIKE '%JOIN%' AND DESCRIPTION NOT ILIKE '%GROUP BY%' THEN 'POINT_LOOKUP'
        WHEN DESCRIPTION ILIKE 'SELECT%WHERE%BETWEEN%' OR DESCRIPTION ILIKE 'SELECT%WHERE%>%' THEN 'RANGE_SCAN'
        WHEN DESCRIPTION ILIKE 'SELECT%JOIN%' THEN 'JOIN_QUERY'
        WHEN DESCRIPTION ILIKE '%INSERT%' THEN 'INSERT'
        WHEN DESCRIPTION ILIKE '%UPDATE%' THEN 'UPDATE'
        WHEN DESCRIPTION ILIKE '%DELETE%' THEN 'DELETE'
        ELSE 'OTHER'
    END as QUERY_TYPE,
    COUNT(*) as COUNT,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as PCT,
    ROUND(AVG(TOTAL_DURATION), 2) as AVG_MS,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY TOTAL_DURATION), 2) as P50_MS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND ACCESS_KV_TABLE = TRUE
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
GROUP BY QUERY_TYPE ORDER BY COUNT DESC;
```

#### 4e: Top Slow HT Queries (for Investigation)

```sql
SELECT 
    UUID as QUERY_UUID,
    QUERY_PARAMETERIZED_HASH,
    LEFT(DESCRIPTION, 200) as QUERY_PREVIEW,
    DESCRIPTION as FULL_SQL,
    TOTAL_DURATION as DURATION_MS,
    DUR_COMPILING as COMPILE_MS,
    DUR_XP_EXECUTING as EXEC_MS,
    CREATED_ON
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND ACCESS_KV_TABLE = TRUE
  AND CREATED_ON >= DATEADD('day', -7, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
ORDER BY TOTAL_DURATION DESC LIMIT 20;
```

**Query Identifiers Explained:**
- **QUERY_UUID**: Unique identifier for each query execution - use this to look up specific query details
- **QUERY_PARAMETERIZED_HASH**: Hash of the query structure (parameters replaced) - use to find recurrent query patterns
- **FULL_SQL**: Complete SQL text for the query - review for optimization opportunities

#### 4f: Deep-Dive Query Analysis (JOB_ETL_JPS_V)

**⚠️ WARNING: Use JOB_ETL_JPS_V sparingly - queries are SLOW!**

Only use this table when you have a **specific query UUID** from Step 4e and need detailed HT execution metrics:

```sql
-- Deep-dive on a specific problematic query
SELECT 
    UUID as QUERY_UUID,
    QUERY_PARAMETERIZED_HASH,
    DESCRIPTION as FULL_SQL,
    TOTAL_DURATION,
    DUR_COMPILING,
    DUR_XP_EXECUTING,
    KV_PROBES,
    KV_RESULTS,
    ACCESS_KV_TABLE,
    WAREHOUSE_SIZE,
    CREATED_ON
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_JPS_V
WHERE UUID = '<SPECIFIC_QUERY_UUID>'
LIMIT 1;
```

**Table Selection Guide:**
| Scenario | Use Table |
|----------|-----------|
| Health check queries, trends, aggregations | `JOB_ETL_V` (fast) |
| Top slow queries list | `JOB_ETL_V` (fast) |
| Deep-dive on ONE specific query UUID | `JOB_ETL_JPS_V` (slow but detailed) |
| Find all executions of a query pattern | `JOB_ETL_V` with `QUERY_PARAMETERIZED_HASH` filter |

---

### Step 5: Interactive Analytics Health Assessment

#### 5a: Daily IA Query Performance

```sql
SELECT 
    DATE_TRUNC('day', CREATED_ON) as DAY,
    COUNT(*) as TOTAL_QUERIES,
    SUM(CASE WHEN TOTAL_DURATION < 1000 THEN 1 ELSE 0 END) as SUB_SECOND_QUERIES,
    ROUND(SUM(CASE WHEN TOTAL_DURATION < 1000 THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) as SUB_SECOND_PCT,
    ROUND(AVG(TOTAL_DURATION), 2) as AVG_MS,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY TOTAL_DURATION), 2) as P50_MS,
    ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY TOTAL_DURATION), 2) as P99_MS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND (WAREHOUSE_TYPE = 'INTERACTIVE' OR DESCRIPTION ILIKE '%INTERACTIVE%')
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
GROUP BY DAY ORDER BY DAY DESC;
```

#### 5b: IA Compilation Time Analysis

```sql
SELECT 
    CASE 
        WHEN DUR_COMPILING < 100 THEN '1_FAST (<100ms)'
        WHEN DUR_COMPILING < 500 THEN '2_MODERATE (100-500ms)'
        WHEN DUR_COMPILING < 1000 THEN '3_SLOW (500ms-1s)'
        ELSE '4_VERY_SLOW (>1s)'
    END as COMPILE_TIER,
    COUNT(*) as QUERY_COUNT,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as PCT,
    ROUND(AVG(DUR_COMPILING), 2) as AVG_COMPILE_MS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND (WAREHOUSE_TYPE = 'INTERACTIVE' OR DESCRIPTION ILIKE '%INTERACTIVE%')
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
GROUP BY COMPILE_TIER ORDER BY COMPILE_TIER;
```

---

### Step 6: Snowflake Postgres Health Assessment

#### 6a: Postgres Query Latency Distribution

```sql
SELECT 
    CASE 
        WHEN TOTAL_DURATION < 10 THEN '1_<10ms'
        WHEN TOTAL_DURATION < 100 THEN '2_10-100ms'
        WHEN TOTAL_DURATION < 1000 THEN '3_100ms-1s'
        ELSE '4_>1s'
    END as LATENCY_BUCKET,
    COUNT(*) as QUERY_COUNT,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as PCT
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND (CLIENT_APPLICATION_ID ILIKE '%postgres%' OR CLIENT_APPLICATION_ID ILIKE '%psycopg%')
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
GROUP BY LATENCY_BUCKET ORDER BY LATENCY_BUCKET;
```

#### 6b: Postgres Daily Throughput

```sql
SELECT 
    DATE_TRUNC('day', CREATED_ON) as DAY,
    COUNT(*) as TOTAL_QUERIES,
    COUNT(DISTINCT SESSION_ID) as UNIQUE_SESSIONS,
    ROUND(AVG(TOTAL_DURATION), 2) as AVG_MS,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY TOTAL_DURATION), 2) as P50_MS
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID>
  AND (CLIENT_APPLICATION_ID ILIKE '%postgres%' OR CLIENT_APPLICATION_ID ILIKE '%psycopg%')
  AND CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NULL
GROUP BY DAY ORDER BY DAY DESC;
```

---

### Step 7: Calculate Health Scores

**Load** `references/health_scoring_guide.md` for thresholds.

#### Hybrid Tables Health Score (0-100)

Calculate based on:
- **Latency Score (40 points)**: P50 < 10ms = 40, P50 10-100ms = 20, P50 > 100ms = 0
- **Optimal Query % (30 points)**: >80% = 30, 50-80% = 15, <50% = 0
- **FDB Health (30 points)**: Timeout rate <0.1% = 30, 0.1-1% = 15, >1% = 0

#### Interactive Analytics Health Score (0-100)

Calculate based on:
- **Sub-second % (50 points)**: >90% = 50, 70-90% = 25, <70% = 0
- **Compilation Efficiency (30 points)**: >80% fast compiles = 30, 50-80% = 15, <50% = 0
- **Error Rate (20 points)**: <0.1% = 20, 0.1-1% = 10, >1% = 0

#### Snowflake Postgres Health Score (0-100)

Calculate based on:
- **Latency Distribution (50 points)**: >70% sub-100ms = 50, 50-70% = 25, <50% = 0
- **Throughput Stability (30 points)**: Low variance = 30, moderate = 15, high = 0
- **Error Rate (20 points)**: <0.1% = 20, 0.1-1% = 10, >1% = 0

---

### Step 8: Identify Issues & Recommendations

**Load** `references/issue_patterns.md` for remediation guidance.

#### Issue Detection Rules

| Issue | Detection Criteria | Severity | Recommendation |
|-------|-------------------|----------|----------------|
| HT Latency Degradation | P50 > 100ms or increasing trend | CRITICAL | Review index coverage, check for scans |
| FDB Timeouts | Timeout rate > 0.1% | CRITICAL | Contact support, review FDB cluster health |
| Suboptimal Query Pattern | Point lookup % < 50% | WARNING | Review workload fit, consider Standard Tables |
| IA Compilation Overhead | Slow compiles > 20% | WARNING | Simplify queries, check for schema changes |
| Postgres Latency Spike | P50 increase > 2x week-over-week | WARNING | Review connection pooling, query patterns |

---

### Step 9: Generate Output

**Option A: Markdown Report**
- Save to user-specified path with health scores, trends, and recommendations

**Option B: Streamlit Dashboard (Recommended)**

Save structured output files to `health_check_output/<customer_name>/`:
- `health_metadata.json` - Customer info, health scores
- `ht_latency_trends.csv` - Daily HT latency trends
- `ht_performance_tiers.csv` - Performance tier distribution
- `ht_fdb_health.csv` - FDB error/timeout data
- `ht_query_patterns.csv` - Query type breakdown
- `ht_slow_queries.csv` - Top slow queries
- `ia_daily_performance.csv` - IA daily metrics
- `ia_compile_tiers.csv` - Compilation time distribution
- `postgres_latency.csv` - Postgres latency buckets
- `postgres_throughput.csv` - Daily throughput
- `issues_detected.csv` - Issues with severity and recommendations

```bash
streamlit run /Users/atimm/Documents/Unistore/cortex_skills_repo/skills/oltp-health-check/dashboard/app.py --server.port 8503 --server.headless true
```

---

### Step 10: Log Telemetry (REQUIRED)

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
    'oltp-health-check',
    'oltp-health-check',
    '1.0.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    '<CUSTOMER_NAME>',
    '<ACCOUNT_ID>',
    '<DEPLOYMENT>',
    'RUN_HEALTH_CHECK',
    PARSE_JSON('{
        \"customer_name\": \"<CUSTOMER_NAME>\",
        \"account_name\": \"<ACCOUNT_NAME>\",
        \"analysis_days\": <DAYS>,
        \"output_format\": \"<markdown|streamlit>\",
        \"report_path\": \"<REPORT_PATH>\",
        \"health_scores\": {
            \"hybrid_tables\": <HT_SCORE>,
            \"interactive_analytics\": <IA_SCORE>,
            \"snowflake_postgres\": <PG_SCORE>
        },
        \"usage_detected\": {
            \"hybrid_tables\": <true|false>,
            \"interactive_analytics\": <true|false>,
            \"snowflake_postgres\": <true|false>
        },
        \"issues_found\": {
            \"critical\": <CRITICAL_COUNT>,
            \"warning\": <WARNING_COUNT>,
            \"info\": <INFO_COUNT>
        },
        \"top_issue\": \"<TOP_ISSUE_DESCRIPTION>\"
    }'),
    '<OVERALL_HEALTH_STATUS>',
    TRUE
;"
```

---

## Telemetry Configuration

| Setting | Value |
|---------|-------|
| Database | `AFE` |
| Schema | `PUBLIC_APP_STATE` |
| Table | `APP_EVENTS` |
| App Name | `oltp-health-check` |
| App Version | `1.0.0` |

---

## Stopping Points

- **Step 1**: After collecting customer info
- **Step 2**: If multiple accounts found, ask user to select
- **Step 3**: If no OLTP products detected, inform user and offer oltp-workload-advisor
- **Step 9**: Before generating final output, confirm format preference

---

## Output

- **Markdown**: Health report at user-specified path
- **Dashboard**: Interactive Streamlit app at http://localhost:8503

---

## When to Apply This Skill

- User asks to "check health of [customer] OLTP workloads"
- User asks "how are Hybrid Tables performing for [customer]"
- User asks "is there any FDB issues for [customer]"
- User mentions "performance review", "health check", "latency issues"
- User asks "what's the status of IA for [customer]"
- User asks "are there any problems with [customer] Hybrid Tables"
