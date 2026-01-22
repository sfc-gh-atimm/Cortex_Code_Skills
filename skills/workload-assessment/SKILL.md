---
name: workload-assessment
description: "Assess workload suitability for Standard Tables, Hybrid Tables, or Interactive Analytics using customer session ID via Snowhouse queries. Use when analyzing table performance or recommending table type conversions."
---

# Workload Assessment for Table Type Selection (Snowhouse)

## Overview
This skill analyzes query patterns from a customer session ID using Snowhouse internal data to recommend the optimal table type: Standard Table, Hybrid Table, or Interactive Analytics (Interactive Warehouse). All queries run against Snowhouse - no customer environment access required.

## Prerequisites
- Snowhouse connection configured (typically named "Snowhouse" in connections.toml)
- SALES_ENGINEER or equivalent role with access to SNOWHOUSE_IMPORT.PROD views

## Query Execution Methods

### Recommended: `snow sql` with PAT connection (batched queries)
Use the `Snowhouse_PAT` connection with Programmatic Access Token for non-interactive auth.
**Batch multiple queries** to reduce CLI overhead:

```bash
snow sql -c Snowhouse_PAT -q "
-- Query 1: Session context
SELECT 'SESSION_CONTEXT' as query_name, ACCOUNT_ID, DEPLOYMENT, DATABASE_NAME, SCHEMA_NAME, 
       MIN(CREATED_ON) as first_query, MAX(CREATED_ON) as last_query, COUNT(*) as total_queries
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE SESSION_ID = <SESSION_ID> AND CREATED_ON > DATEADD(day, -90, CURRENT_TIMESTAMP())
GROUP BY ACCOUNT_ID, DEPLOYMENT, DATABASE_NAME, SCHEMA_NAME;

-- Query 2: Latency distribution  
SELECT 'LATENCY_DIST' as query_name,
    CASE WHEN TOTAL_DURATION < 10 THEN '< 10ms'
         WHEN TOTAL_DURATION < 100 THEN '10-100ms'
         WHEN TOTAL_DURATION < 1000 THEN '100ms-1s'
         WHEN TOTAL_DURATION < 10000 THEN '1-10s'
         ELSE '> 10s' END as latency_bucket,
    COUNT(*) as query_count
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE SESSION_ID = <SESSION_ID> AND CREATED_ON > DATEADD(day, -90, CURRENT_TIMESTAMP()) AND ERROR_CODE IS NULL
GROUP BY latency_bucket;

-- Query 3: Hybrid table access
SELECT 'HYBRID_ACCESS' as query_name, COUNT(*) as total, 
       SUM(CASE WHEN ACCESS_KV_TABLE THEN 1 ELSE 0 END) as hybrid_queries
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE SESSION_ID = <SESSION_ID> AND CREATED_ON > DATEADD(day, -90, CURRENT_TIMESTAMP());
"
```

### Fallback: `snow sql` with externalbrowser (interactive)
If PAT is not available, use the browser-authenticated connection:
```bash
snow sql -c Snowhouse -q "YOUR SQL HERE"
```
Note: This requires interactive browser login.

### Performance Tips
1. **Batch all queries in single call** - Combine multiple statements separated by semicolons
2. **Use PAT connection** - `Snowhouse_PAT` avoids browser auth overhead
3. **Add time filters early** - Always filter by `CREATED_ON > DATEADD(day, -N, CURRENT_TIMESTAMP())`
4. **Use LIMIT for exploration** - When sampling data, use LIMIT to avoid full scans
5. **Consider warehouse size** - SNOWADHOC may be small; larger warehouse = faster queries

## Workflow

### Step 1: Collect Input Parameters
Ask the user for session details using ask_user_question:

```json
{
  "questions": [
    {"header": "Session ID", "question": "Enter the customer session ID to analyze", "type": "text", "defaultValue": "<session_id>"},
    {"header": "Deployment", "question": "Enter the deployment region (e.g., va3, aws_us_west_2)", "type": "text", "defaultValue": "va3"},
    {"header": "Account", "question": "Enter the account locator (e.g., GCB59607)", "type": "text", "defaultValue": "<account_locator>"},
    {"header": "Report Path", "question": "Where should the assessment report be saved?", "type": "text", "defaultValue": "/path/to/customer/folder/"}
  ]
}
```

### Step 2: Run Batched Session Analysis (Single Call)
Execute all session-level queries in one batch:

```bash
snow sql -c Snowhouse_PAT -q "
-- 1. Session context
SELECT 'SESSION_CONTEXT' as query_type, 
    ACCOUNT_ID::VARCHAR as val1, DEPLOYMENT as val2, DATABASE_NAME as val3, SCHEMA_NAME as val4,
    MIN(CREATED_ON)::VARCHAR as val5, MAX(CREATED_ON)::VARCHAR as val6, COUNT(*)::VARCHAR as val7
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE SESSION_ID = <SESSION_ID> AND CREATED_ON > DATEADD(day, -90, CURRENT_TIMESTAMP())
GROUP BY ACCOUNT_ID, DEPLOYMENT, DATABASE_NAME, SCHEMA_NAME

UNION ALL

-- 2. Hybrid table access check
SELECT 'HYBRID_CHECK' as query_type,
    COUNT(*)::VARCHAR as val1,
    SUM(CASE WHEN ACCESS_KV_TABLE THEN 1 ELSE 0 END)::VARCHAR as val2,
    ROUND(SUM(CASE WHEN ACCESS_KV_TABLE THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2)::VARCHAR as val3,
    NULL, NULL, NULL, NULL
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE SESSION_ID = <SESSION_ID> AND CREATED_ON > DATEADD(day, -90, CURRENT_TIMESTAMP());

-- 3. Query category analysis
WITH session_queries AS (
    SELECT TOTAL_DURATION, ACCESS_KV_TABLE,
        CASE 
            WHEN DESCRIPTION ILIKE 'SELECT%WHERE%=%' AND DESCRIPTION NOT ILIKE '%JOIN%' AND DESCRIPTION NOT ILIKE '%GROUP BY%' THEN 'POINT_LOOKUP'
            WHEN DESCRIPTION ILIKE 'SELECT%WHERE%BETWEEN%' OR DESCRIPTION ILIKE 'SELECT%WHERE%>%' THEN 'RANGE_SCAN'
            WHEN DESCRIPTION ILIKE '%INSERT%' THEN 'INSERT'
            WHEN DESCRIPTION ILIKE '%UPDATE%' THEN 'UPDATE'
            WHEN DESCRIPTION ILIKE '%DELETE%' THEN 'DELETE'
            WHEN DESCRIPTION ILIKE '%MERGE%' THEN 'MERGE'
            WHEN DESCRIPTION ILIKE '%GROUP BY%' OR DESCRIPTION ILIKE '%SUM(%' OR DESCRIPTION ILIKE '%COUNT(%' THEN 'AGGREGATION'
            WHEN DESCRIPTION ILIKE '%JOIN%' THEN 'JOIN'
            ELSE 'OTHER'
        END as query_category
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
    WHERE SESSION_ID = <SESSION_ID> AND CREATED_ON > DATEADD(day, -90, CURRENT_TIMESTAMP()) AND ERROR_CODE IS NULL
)
SELECT query_category, COUNT(*) as query_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage,
    ROUND(AVG(TOTAL_DURATION), 2) as avg_duration_ms,
    ROUND(MEDIAN(TOTAL_DURATION), 2) as median_duration_ms,
    MAX(TOTAL_DURATION) as max_duration_ms,
    SUM(CASE WHEN ACCESS_KV_TABLE THEN 1 ELSE 0 END) as hybrid_table_queries
FROM session_queries GROUP BY query_category ORDER BY query_count DESC;

-- 4. Latency distribution
SELECT 
    CASE WHEN TOTAL_DURATION < 10 THEN '1_< 10ms'
         WHEN TOTAL_DURATION < 100 THEN '2_10-100ms'
         WHEN TOTAL_DURATION < 1000 THEN '3_100ms-1s'
         WHEN TOTAL_DURATION < 10000 THEN '4_1-10s'
         ELSE '5_> 10s' END as latency_bucket,
    COUNT(*) as query_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE SESSION_ID = <SESSION_ID> AND CREATED_ON > DATEADD(day, -90, CURRENT_TIMESTAMP()) AND ERROR_CODE IS NULL
GROUP BY latency_bucket ORDER BY latency_bucket;

-- 5. Top 10 slowest queries
SELECT LEFT(DESCRIPTION, 100) as query_preview, TOTAL_DURATION, DUR_COMPILING, DUR_XP_EXECUTING, ACCESS_KV_TABLE
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE SESSION_ID = <SESSION_ID> AND CREATED_ON > DATEADD(day, -90, CURRENT_TIMESTAMP()) AND ERROR_CODE IS NULL
ORDER BY TOTAL_DURATION DESC LIMIT 10;
"
```

### Step 3: Run Batched 30-Day Account Analysis (Single Call)
After getting ACCOUNT_ID, DEPLOYMENT, DATABASE_NAME, SCHEMA_NAME from Step 2:

```bash
snow sql -c Snowhouse_PAT -q "
-- 1. Read:Write ratio (30 days)
SELECT 'READ_WRITE_RATIO' as query_type,
    ROUND(SUM(CASE WHEN DESCRIPTION ILIKE 'SELECT%' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 4) as select_pct,
    ROUND(SUM(CASE WHEN DESCRIPTION ILIKE 'INSERT%' OR DESCRIPTION ILIKE 'UPDATE%' OR DESCRIPTION ILIKE 'DELETE%' OR DESCRIPTION ILIKE 'MERGE%' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 6) as dml_pct,
    SUM(CASE WHEN DESCRIPTION ILIKE 'SELECT%' THEN 1 ELSE 0 END) as total_selects,
    SUM(CASE WHEN DESCRIPTION ILIKE 'INSERT%' THEN 1 ELSE 0 END) as total_inserts,
    SUM(CASE WHEN DESCRIPTION ILIKE 'UPDATE%' THEN 1 ELSE 0 END) as total_updates,
    SUM(CASE WHEN DESCRIPTION ILIKE 'DELETE%' THEN 1 ELSE 0 END) as total_deletes
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID> AND DEPLOYMENT = '<DEPLOYMENT>'
AND DATABASE_NAME = '<DATABASE_NAME>' AND SCHEMA_NAME = '<SCHEMA_NAME>'
AND CREATED_ON > DATEADD(day, -30, CURRENT_TIMESTAMP()) AND ERROR_CODE IS NULL;

-- 2. Daily DML breakdown (14 days)
SELECT DATE_TRUNC('day', CREATED_ON)::DATE as day,
    SUM(CASE WHEN DESCRIPTION ILIKE 'SELECT%' THEN 1 ELSE 0 END) as selects,
    SUM(CASE WHEN DESCRIPTION ILIKE 'INSERT%' THEN 1 ELSE 0 END) as inserts,
    SUM(CASE WHEN DESCRIPTION ILIKE 'UPDATE%' THEN 1 ELSE 0 END) as updates,
    SUM(CASE WHEN DESCRIPTION ILIKE 'DELETE%' THEN 1 ELSE 0 END) as deletes,
    COUNT(*) as total
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V
WHERE ACCOUNT_ID = <ACCOUNT_ID> AND DEPLOYMENT = '<DEPLOYMENT>'
AND DATABASE_NAME = '<DATABASE_NAME>' AND SCHEMA_NAME = '<SCHEMA_NAME>'
AND CREATED_ON > DATEADD(day, -14, CURRENT_TIMESTAMP()) AND ERROR_CODE IS NULL
GROUP BY day ORDER BY day DESC;
"
```

---

## Decision Framework

### Calculate Read:Write Ratio
```
Read:Write Ratio = total_selects / total_dml
```

### Decision Matrix

| Read:Write Ratio | DML % | Recommendation |
|------------------|-------|----------------|
| > 10,000:1 | < 0.01% | **Interactive Analytics** |
| 1,000:1 - 10,000:1 | 0.01% - 0.1% | **Interactive Analytics** (if read-only acceptable) |
| 100:1 - 1,000:1 | 0.1% - 1% | Evaluate latency requirements |
| < 100:1 | > 1% | **Hybrid Tables** (if OLTP pattern) |

### Query Pattern Criteria

#### Standard Tables - Recommended When:
- Primarily batch analytical queries (aggregations, joins)
- Large scan operations are common
- Write operations are bulk/batch oriented
- Query latency requirements are > 1 second
- Cost optimization is priority over latency

#### Hybrid Tables - Recommended When:
- High percentage of POINT_LOOKUP queries (> 50%)
- **AND** DML percentage > 1% (significant writes)
- **AND** Latency requirement is < 10ms
- OLTP-style transactional patterns
- Frequent single-row INSERT/UPDATE/DELETE
- Clear primary key exists in workload

#### Interactive Analytics - Recommended When:
- Read:Write ratio > 1,000:1 (essentially read-only)
- Sub-second analytical query requirements (not sub-10ms)
- Dashboard/BI workloads with dynamic queries
- Point lookups acceptable at sub-second (vs sub-10ms)
- Data is append-only or infrequently updated
- Cost efficiency for read-heavy workloads is important

---

## Output Report Template

Generate a markdown report with the following structure:

```markdown
# Workload Assessment Report

**Customer:** [Customer Name]
**Account Locator:** [LOCATOR]
**Account ID:** [ID]
**Deployment:** [deployment]
**Assessment Date:** [Date]

---

## Executive Summary

[1-2 sentence recommendation with key rationale]

---

## Session Analysis

### Session Overview
| Field | Value |
|-------|-------|
| Session ID | [value] |
| Database.Schema | [value] |
| Date Range | [value] |
| Total Queries | [value] |

### Query Pattern Distribution
| Category | Count | % | Avg Latency | Median | Max |
|----------|-------|---|-------------|--------|-----|
| ... | ... | ... | ... | ... | ... |

### Latency Distribution
| Bucket | Count | % |
|--------|-------|---|
| < 10ms | ... | ... |
| 10-100ms | ... | ... |
| 100ms-1s | ... | ... |
| 1-10s | ... | ... |
| > 10s | ... | ... |

---

## 30-Day Account Analysis

### Read vs Write Profile
| Metric | Value |
|--------|-------|
| Total Queries | [value] |
| SELECT Queries | [value] ([%]) |
| INSERT Queries | [value] ([%]) |
| UPDATE Queries | [value] ([%]) |
| DELETE Queries | [value] ([%]) |
| **Read:Write Ratio** | **[X]:1** |

### Daily Pattern (Last 14 Days)
[Table showing daily breakdown]

---

## Recommendation Matrix

| Criteria | Standard | Hybrid | Interactive Analytics |
|----------|:--------:|:------:|:---------------------:|
| Read:Write Ratio | [✓/✗/~] | [✓/✗/~] | [✓/✗/~] |
| Query Pattern | [✓/✗/~] | [✓/✗/~] | [✓/✗/~] |
| Latency Needs | [✓/✗/~] | [✓/✗/~] | [✓/✗/~] |
| Cost Efficiency | [✓/✗/~] | [✓/✗/~] | [✓/✗/~] |

---

## Final Recommendation

### Primary: [Recommended Option]

**Rationale:**
1. [Key reason 1]
2. [Key reason 2]
3. [Key reason 3]

### Expected Performance Improvement
| Metric | Current | Expected |
|--------|---------|----------|
| Median latency | [value] | [value] |
| Max latency | [value] | [value] |

### Next Steps
1. [Action item 1]
2. [Action item 2]
3. [Action item 3]

---

## Appendix: Snowhouse Queries Used
[Include key queries for reproducibility]
```

---

## Key Snowhouse Tables Reference

| Table | Purpose |
|-------|---------|
| `SNOWHOUSE_IMPORT.PROD.JOB_ETL_V` | Query execution history with timing, SQL text, and metrics |
| `SNOWHOUSE_IMPORT.PROD.TABLE_ETL_V` | Table metadata (use NAME column, not TABLE_NAME) |
| `SNOWHOUSE_IMPORT.PROD.SESSION_ETL_V` | Session information |
| `SNOWHOUSE_IMPORT.PROD.ACCOUNT_ETL_V` | Account metadata |

## Key JOB_ETL_V Columns

| Column | Description |
|--------|-------------|
| `SESSION_ID` | Session identifier (NUMBER) |
| `ACCOUNT_ID` | Customer account ID (NUMBER) |
| `DEPLOYMENT` | Deployment region (VARCHAR) |
| `DESCRIPTION` | SQL query text |
| `TOTAL_DURATION` | Total query duration in milliseconds |
| `DUR_COMPILING` | Compilation time in ms |
| `DUR_XP_EXECUTING` | Execution time in ms |
| `ACCESS_KV_TABLE` | TRUE if query accessed Hybrid Table (BOOLEAN) |
| `ERROR_CODE` | NULL if successful |
| `CREATED_ON` | Query timestamp |

---

## When to Apply This Skill

- User provides a session ID for workload analysis
- User asks "analyze this session for table optimization"
- User wants to know if workload suits Hybrid or Interactive Analytics
- User asks about table performance for a specific customer session
- User asks "is this table performing as well as it could"
- User asks "would this table be better as a hybrid table or interactive table"
- Internal assessment of customer workload patterns

---

## Step 0: Verify Product Status (REQUIRED)

**Before making any recommendations, search internal documentation to verify current status of each table type:**

### Use snowflake_product_docs tool to search for:
1. "Hybrid Tables" - Verify GA status, current limitations, supported regions
2. "Interactive Analytics" OR "Interactive Tables" OR "Interactive Warehouse" - Verify preview status (PuPr/PrPr/GA), eligibility requirements
3. "Unistore" - Check for any recent changes or announcements

### Use web_search or internal wikis to check:
- Current feature availability by region/cloud
- Known limitations or constraints
- Pricing model differences
- Customer eligibility requirements for preview features

### Document findings in report:
```markdown
## Product Availability (as of [date])

| Product | Status | Availability | Key Limitations |
|---------|--------|--------------|-----------------|
| Standard Tables | GA | All regions | [any relevant notes] |
| Hybrid Tables | [GA/Preview] | [regions] | [limitations] |
| Interactive Analytics | [PuPr/PrPr/GA] | [eligibility] | [limitations] |
```

**Do NOT rely on cached knowledge about product status - always verify current state.**

---

## Important Notes

1. **Always check 30-day DML patterns** - Session analysis alone can be misleading; account-level write patterns determine if Hybrid Tables are warranted.

2. **Read:Write ratio is the key metric** - Ratios > 1,000:1 strongly favor Interactive Analytics over Hybrid Tables.

3. **Zero UPDATEs is significant** - If UPDATE count is 0, the workload is append-only and Hybrid Table's transactional write infrastructure provides no benefit.

4. **Verify product availability** - Always search internal documentation to confirm current GA/Preview status before recommending. Do not assume availability based on prior knowledge.

5. **Report storage path** - Ask the user where to save the report. Use ask_user_question:
```json
{
  "questions": [
    {"header": "Report Path", "question": "Where should the assessment report be saved?", "type": "text", "defaultValue": "/path/to/customer/folder/workload_assessment_<account>_<date>.md"}
  ]
}
```

---

## Telemetry

This skill logs usage events to the shared telemetry table for tracking and analytics.

### Telemetry Configuration
| Setting | Value |
|---------|-------|
| Database | `AFE` |
| Schema | `PUBLIC_APP_STATE` |
| Table | `APP_EVENTS` |
| App Name | `Workload Assessment (Skill)` |
| App Version | `1.0.0` |

### Step: Log Telemetry Event
After completing the assessment, log a telemetry event using the PAT connection:

```bash
snow sql -c Snowhouse_PAT -q "
INSERT INTO AFE.PUBLIC_APP_STATE.APP_EVENTS (
    APP, APP_NAME, APP_VERSION, USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
    SALESFORCE_ACCOUNT_ID, SALESFORCE_ACCOUNT_NAME,
    SNOWFLAKE_ACCOUNT_ID, DEPLOYMENT,
    ACTION_TYPE, ACTION_CONTEXT, SUCCESS, ERROR_MESSAGE, DURATION_MS,
    VIEWER_EMAIL
)
SELECT
    'Workload Assessment (Skill)',
    'Workload Assessment (Skill)',
    '1.0.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    NULL,  -- salesforce_account_id (populate if known)
    '<CUSTOMER_NAME>',  -- salesforce_account_name
    '<ACCOUNT_ID>',  -- snowflake_account_id (from session analysis)
    '<DEPLOYMENT>',  -- deployment (from session analysis)
    'RUN_ASSESSMENT',
    PARSE_JSON('{
        \"session_id\": \"<SESSION_ID>\",
        \"account_locator\": \"<ACCOUNT_LOCATOR>\",
        \"recommendation\": \"<RECOMMENDATION>\",
        \"read_write_ratio\": \"<RATIO>\",
        \"total_queries_analyzed\": <COUNT>,
        \"report_path\": \"<REPORT_PATH>\"
    }'),
    TRUE,
    NULL,
    <DURATION_MS>,
    NULL;
"
```

### Telemetry Events
| Event | When to Log |
|-------|-------------|
| `RUN_ASSESSMENT` | After successfully generating the assessment report |
| `ERROR_ASSESSMENT` | If analysis fails (set SUCCESS=FALSE, include ERROR_MESSAGE) |

### Example: Log Success Event
After generating report for Elevance Health:
```bash
snow sql -c Snowhouse_PAT -q "
INSERT INTO AFE.PUBLIC_APP_STATE.APP_EVENTS (
    APP, APP_NAME, APP_VERSION, USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
    SALESFORCE_ACCOUNT_NAME, SNOWFLAKE_ACCOUNT_ID, DEPLOYMENT,
    ACTION_TYPE, ACTION_CONTEXT, SUCCESS, DURATION_MS
)
SELECT
    'Workload Assessment (Skill)',
    'Workload Assessment (Skill)',
    '1.0.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    'Elevance Health',
    '204903621273246',
    'va3',
    'RUN_ASSESSMENT',
    PARSE_JSON('{
        \"session_id\": \"5377868606057860091\",
        \"account_locator\": \"GCB59607\",
        \"recommendation\": \"Interactive Analytics\",
        \"read_write_ratio\": \"30213:1\",
        \"total_queries_analyzed\": 368
    }'),
    TRUE,
    45000;
"
```

### Example: Log Error Event
If analysis fails:
```bash
snow sql -c Snowhouse_PAT -q "
INSERT INTO AFE.PUBLIC_APP_STATE.APP_EVENTS (
    APP, APP_NAME, APP_VERSION, USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_ACCOUNT_ID, DEPLOYMENT,
    ACTION_TYPE, SUCCESS, ERROR_MESSAGE
)
SELECT
    'Workload Assessment (Skill)',
    'Workload Assessment (Skill)',
    '1.0.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    '<ACCOUNT_ID>',
    '<DEPLOYMENT>',
    'ERROR_ASSESSMENT',
    FALSE,
    'Session not found or insufficient data';
"
```
