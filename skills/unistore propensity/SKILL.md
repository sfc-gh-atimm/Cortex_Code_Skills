---
name: unistore-customer-workload-conversion-advisor
description: "Analyze customer workloads via Snowhouse to identify tables/queries suitable for conversion to Hybrid Tables or Interactive Analytics. Use when: prospecting for Unistore opportunities, identifying conversion candidates, analyzing customer query patterns. Triggers: customer workload analysis, hybrid table candidates, interactive analytics candidates, conversion opportunities, Unistore prospecting."
---

# Unistore Customer Workload Conversion Advisor

## Overview
This skill analyzes a customer's Snowhouse telemetry data (last 30 days) to identify tables and query patterns that would be strong candidates for conversion to Hybrid Tables or Interactive Analytics. It takes customer identifying information (name, account locator, or deployment) and produces actionable recommendations.

## Prerequisites
- Snowhouse connection configured (typically `Snowhouse_PAT` with PAT authentication)
- Access to `SNOWHOUSE.PRODUCT` views and `SNOWHOUSE_IMPORT.PROD` views
- Access to `AFE.PUBLIC_APP_STATE.APP_EVENTS` for telemetry logging

## Products Evaluated

| Product | Best For | Key Indicators |
|---------|----------|----------------|
| **Hybrid Tables** | True OLTP workloads with sub-10ms point lookups, high single-row DML, transactional consistency | High UPDATE/DELETE %, point lookups, parameterized queries, sub-10ms latency requirements |
| **Interactive Analytics** | Read-heavy analytical workloads requiring sub-second (not sub-10ms) response times | 99%+ reads, dashboard/BI patterns, sub-second latency needs |

---

## Workflow

### Step 1: Collect Customer Information
Ask the user for customer identification:

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

### Step 2: Find Customer Account(s) in Snowhouse
Use customer name, alternate name, or account locator to locate their account(s):

```bash
snow sql -c Snowhouse_PAT -q "
-- Find customer accounts by name, alternate name, or locator
SELECT DISTINCT
    a.ID as ACCOUNT_ID,
    a.NAME as ACCOUNT_NAME,
    a.DEPLOYMENT,
    a.CREATED_ON as ACCOUNT_CREATED
FROM SNOWHOUSE.PRODUCT.ALL_LIVE_ACCOUNTS a
WHERE a.NAME = '<ACCOUNT_LOCATOR>'  -- Direct locator match
   OR UPPER(a.NAME) ILIKE '%<CUSTOMER_NAME>%'
   OR UPPER(a.NAME) ILIKE '%<ALTERNATE_NAME>%'
ORDER BY a.CREATED_ON DESC
LIMIT 20;
"
```

**If no accounts found:** Suggest common alternate names (e.g., former company names like Anthem → Elevance Health) or ask for account locator.

If multiple accounts found, present options to user:
```json
{
  "questions": [
    {"header": "Account", "question": "Multiple accounts found. Which account should be analyzed?", "type": "options", "multiSelect": false, "options": [
      {"label": "[ACCOUNT_NAME_1]", "description": "ID: [ID], Deployment: [DEPLOY]"},
      {"label": "[ACCOUNT_NAME_2]", "description": "ID: [ID], Deployment: [DEPLOY]"},
      {"label": "Analyze all accounts", "description": "Run analysis across all matching accounts"}
    ]}
  ]
}
```

---

### Step 3: Account-Level Query Volume Analysis
Get high-level query statistics for the account:

```bash
snow sql -c Snowhouse_PAT -q "
-- Account query volume summary (last 30 days)
SELECT 
    DATE_TRUNC('day', jf.CREATED_HOUR) as DAY,
    SUM(jf.JOBS) as TOTAL_QUERIES,
    SUM(CASE WHEN st.STATEMENT_TYPE = 'SELECT' THEN jf.JOBS ELSE 0 END) as SELECTS,
    SUM(CASE WHEN st.STATEMENT_TYPE IN ('INSERT', 'UPDATE', 'DELETE', 'MERGE') THEN jf.JOBS ELSE 0 END) as DML,
    SUM(CASE WHEN st.STATEMENT_TYPE = 'UPDATE' THEN jf.JOBS ELSE 0 END) as UPDATES,
    SUM(CASE WHEN st.STATEMENT_TYPE = 'DELETE' THEN jf.JOBS ELSE 0 END) as DELETES,
    ROUND(AVG(jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0)), 2) as AVG_DURATION_MS
FROM SNOWHOUSE.PRODUCT.JOB_FACT jf
JOIN SNOWHOUSE.PRODUCT.STATEMENT_TYPE st ON jf.STATEMENT_TYPE_ID = st.ID
WHERE jf.DEPLOYMENT = '<DEPLOYMENT>'
  AND jf.ACCOUNT_ID = <ACCOUNT_ID>
  AND jf.CREATED_HOUR >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
GROUP BY DAY
ORDER BY DAY DESC;
"
```

### Step 3b: Statement Type Summary
Get overall statement type distribution:

```bash
snow sql -c Snowhouse_PAT -q "
-- Statement type breakdown with latency (30 days)
SELECT 
    st.STATEMENT_TYPE,
    SUM(jf.JOBS) as TOTAL_QUERIES,
    ROUND(SUM(jf.JOBS) * 100.0 / SUM(SUM(jf.JOBS)) OVER(), 4) as PCT,
    ROUND(AVG(jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0)), 2) as AVG_DURATION_MS,
    ROUND(MEDIAN(jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0)), 2) as P50_DURATION_MS
FROM SNOWHOUSE.PRODUCT.JOB_FACT jf
JOIN SNOWHOUSE.PRODUCT.STATEMENT_TYPE st ON jf.STATEMENT_TYPE_ID = st.ID
WHERE jf.DEPLOYMENT = '<DEPLOYMENT>'
  AND jf.ACCOUNT_ID = <ACCOUNT_ID>
  AND jf.CREATED_HOUR >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND st.STATEMENT_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE')
GROUP BY st.STATEMENT_TYPE
ORDER BY TOTAL_QUERIES DESC;
"
```

---

### Step 4: Classify UPDATE Patterns (ETL vs OLTP)
Before identifying Hybrid Table candidates, classify UPDATE patterns to distinguish ETL from OLTP:

```bash
snow sql -c Snowhouse_PAT -q "
-- Classify UPDATE patterns (ETL vs OLTP)
SELECT 
    CASE 
        WHEN je.DESCRIPTION ILIKE '%TEMP_DB%' OR je.DESCRIPTION ILIKE '%_STG%' OR je.DESCRIPTION ILIKE '%_TEMP%' OR je.DESCRIPTION ILIKE '%WORK_%' THEN 'ETL/Staging'
        WHEN je.DESCRIPTION ILIKE '%SET%WHERE%=%?%' OR je.DESCRIPTION ILIKE '%SET%WHERE%=%:%' THEN 'Point Update (Parameterized)'
        WHEN je.DESCRIPTION ILIKE '%SET%WHERE%=%' AND je.DESCRIPTION NOT ILIKE '%IN (SELECT%' THEN 'Point Update (Literal)'
        WHEN je.DESCRIPTION ILIKE '%SET%WHERE%IN (SELECT%' THEN 'Bulk Update (Subquery)'
        ELSE 'Bulk/Other'
    END as UPDATE_TYPE,
    COUNT(*) as COUNT,
    ROUND(AVG(je.TOTAL_DURATION), 2) as AVG_DURATION_MS,
    ROUND(MEDIAN(je.TOTAL_DURATION), 2) as P50_DURATION_MS
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V je
WHERE je.DEPLOYMENT = '<DEPLOYMENT>'
  AND je.ACCOUNT_ID = <ACCOUNT_ID>
  AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
  AND je.DESCRIPTION ILIKE 'UPDATE%'
  AND je.ERROR_CODE IS NULL
GROUP BY UPDATE_TYPE
ORDER BY COUNT DESC;
"
```

**Interpretation:**
- **Point Update (Parameterized)**: Strong Hybrid Table candidates (OLTP pattern)
- **Point Update (Literal)**: Potential candidates, needs validation
- **ETL/Staging**: Exclude from Hybrid Table consideration
- **Bulk Update**: Usually not suitable for Hybrid Tables

---

### Step 5: Identify Hybrid Table Candidate Tables
Look for tables with OLTP-like patterns, **excluding ETL/staging tables**:

```bash
snow sql -c Snowhouse_PAT -q "
-- Tables with UPDATE activity (Hybrid Table candidates)
-- Using SPLIT_PART for reliable table name extraction
WITH update_queries AS (
    SELECT 
        SPLIT_PART(SPLIT_PART(je.DESCRIPTION, ' ', 2), ' SET', 1) as TABLE_NAME,
        je.TOTAL_DURATION,
        CASE 
            WHEN je.DESCRIPTION ILIKE '%WHERE%=%?%' OR je.DESCRIPTION ILIKE '%WHERE%=%:%' THEN 'Parameterized'
            ELSE 'Literal'
        END as QUERY_TYPE
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V je
    WHERE je.DEPLOYMENT = '<DEPLOYMENT>'
      AND je.ACCOUNT_ID = <ACCOUNT_ID>
      AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
      AND je.DESCRIPTION ILIKE 'UPDATE%'
      AND je.ERROR_CODE IS NULL
      -- Exclude ETL/staging tables
      AND je.DESCRIPTION NOT ILIKE '%TEMP_DB%'
      AND je.DESCRIPTION NOT ILIKE '%_STG.%'
      AND je.DESCRIPTION NOT ILIKE '%_STG %'
      AND je.DESCRIPTION NOT ILIKE '%_TEMP %'
      AND je.DESCRIPTION NOT ILIKE '%WORK_%'
)
SELECT 
    TABLE_NAME,
    COUNT(*) as UPDATE_COUNT,
    SUM(CASE WHEN QUERY_TYPE = 'Parameterized' THEN 1 ELSE 0 END) as PARAMETERIZED_COUNT,
    ROUND(AVG(TOTAL_DURATION), 2) as AVG_DURATION_MS,
    ROUND(MEDIAN(TOTAL_DURATION), 2) as P50_DURATION_MS,
    ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY TOTAL_DURATION), 2) as P99_DURATION_MS
FROM update_queries
WHERE TABLE_NAME IS NOT NULL AND LENGTH(TABLE_NAME) > 3
GROUP BY TABLE_NAME
HAVING UPDATE_COUNT >= 500
ORDER BY UPDATE_COUNT DESC
LIMIT 30;
"
```

### Step 5b: Identify DELETE Activity
```bash
snow sql -c Snowhouse_PAT -q "
-- Tables with DELETE activity (Hybrid Table candidates)
WITH delete_queries AS (
    SELECT 
        SPLIT_PART(
            SPLIT_PART(
                REPLACE(REPLACE(je.DESCRIPTION, 'delete from ', 'DELETE FROM '), 'Delete from ', 'DELETE FROM '), 
                'DELETE FROM ', 2
            ), ' ', 1
        ) as TABLE_NAME,
        je.TOTAL_DURATION
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V je
    WHERE je.DEPLOYMENT = '<DEPLOYMENT>'
      AND je.ACCOUNT_ID = <ACCOUNT_ID>
      AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
      AND je.DESCRIPTION ILIKE 'DELETE%'
      AND je.ERROR_CODE IS NULL
      -- Exclude ETL/staging tables
      AND je.DESCRIPTION NOT ILIKE '%TEMP_DB%'
      AND je.DESCRIPTION NOT ILIKE '%_STG.%'
      AND je.DESCRIPTION NOT ILIKE '%_STG %'
      AND je.DESCRIPTION NOT ILIKE '%_TEMP %'
      AND je.DESCRIPTION NOT ILIKE '%WORK_%'
)
SELECT 
    TABLE_NAME,
    COUNT(*) as DELETE_COUNT,
    ROUND(AVG(TOTAL_DURATION), 2) as AVG_DURATION_MS,
    ROUND(MEDIAN(TOTAL_DURATION), 2) as P50_DURATION_MS
FROM delete_queries
WHERE TABLE_NAME IS NOT NULL AND LENGTH(TABLE_NAME) > 3
GROUP BY TABLE_NAME
HAVING DELETE_COUNT >= 100
ORDER BY DELETE_COUNT DESC
LIMIT 25;
"
```

---

### Step 6: Identify Interactive Analytics Candidate Tables
Look for read-heavy tables with sub-second latency potential:

```bash
snow sql -c Snowhouse_PAT -q "
-- Read-heavy tables (Interactive Analytics candidates)
WITH table_activity AS (
    SELECT 
        SPLIT_PART(SPLIT_PART(je.DESCRIPTION, 'FROM ', 2), ' ', 1) as TABLE_NAME,
        CASE WHEN je.DESCRIPTION ILIKE 'SELECT%' THEN 'SELECT' ELSE 'DML' END as OP_TYPE,
        je.TOTAL_DURATION
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V je
    WHERE je.DEPLOYMENT = '<DEPLOYMENT>'
      AND je.ACCOUNT_ID = <ACCOUNT_ID>
      AND je.CREATED_ON >= DATEADD('day', -<DAYS>, CURRENT_TIMESTAMP())
      AND (je.DESCRIPTION ILIKE 'SELECT%FROM%' OR je.DESCRIPTION ILIKE 'INSERT%' OR je.DESCRIPTION ILIKE 'UPDATE%' OR je.DESCRIPTION ILIKE 'DELETE%' OR je.DESCRIPTION ILIKE 'MERGE%')
      AND je.ERROR_CODE IS NULL
      -- Exclude temp/staging
      AND je.DESCRIPTION NOT ILIKE '%TEMP_DB%'
      AND je.DESCRIPTION NOT ILIKE '%_STG.%'
      AND je.DESCRIPTION NOT ILIKE '%_TEMP %'
),
table_stats AS (
    SELECT 
        TABLE_NAME,
        COUNT(*) as TOTAL_OPS,
        SUM(CASE WHEN OP_TYPE = 'SELECT' THEN 1 ELSE 0 END) as SELECTS,
        SUM(CASE WHEN OP_TYPE = 'DML' THEN 1 ELSE 0 END) as DML,
        ROUND(AVG(CASE WHEN OP_TYPE = 'SELECT' THEN TOTAL_DURATION END), 2) as AVG_SELECT_MS,
        ROUND(MEDIAN(CASE WHEN OP_TYPE = 'SELECT' THEN TOTAL_DURATION END), 2) as P50_SELECT_MS
    FROM table_activity
    WHERE TABLE_NAME IS NOT NULL AND LENGTH(TABLE_NAME) > 5
    GROUP BY TABLE_NAME
    HAVING TOTAL_OPS >= 1000
)
SELECT 
    TABLE_NAME,
    TOTAL_OPS,
    SELECTS,
    DML,
    ROUND(SELECTS * 100.0 / TOTAL_OPS, 2) as READ_PCT,
    CASE WHEN DML = 0 THEN 'Infinity' ELSE ROUND(SELECTS * 1.0 / DML, 0)::VARCHAR END as READ_WRITE_RATIO,
    AVG_SELECT_MS,
    P50_SELECT_MS,
    CASE 
        WHEN SELECTS * 100.0 / TOTAL_OPS >= 99 AND AVG_SELECT_MS BETWEEN 100 AND 5000 THEN 'STRONG'
        WHEN SELECTS * 100.0 / TOTAL_OPS >= 95 AND AVG_SELECT_MS BETWEEN 100 AND 10000 THEN 'MODERATE'
        ELSE 'LOW'
    END as IA_FIT
FROM table_stats
WHERE SELECTS * 100.0 / TOTAL_OPS >= 90
ORDER BY 
    CASE 
        WHEN SELECTS * 100.0 / TOTAL_OPS >= 99 AND AVG_SELECT_MS BETWEEN 100 AND 5000 THEN 1
        WHEN SELECTS * 100.0 / TOTAL_OPS >= 95 AND AVG_SELECT_MS BETWEEN 100 AND 10000 THEN 2
        ELSE 3
    END,
    TOTAL_OPS DESC
LIMIT 30;
"
```

---

### Step 7: Sample Query Text for Top Candidates
Sample actual query text to validate patterns:

```bash
snow sql -c Snowhouse_PAT -q "
-- Sample UPDATE queries for top candidate table
SELECT 
    LEFT(je.DESCRIPTION, 300) as QUERY_PREVIEW,
    je.TOTAL_DURATION as DURATION_MS
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V je
WHERE je.DEPLOYMENT = '<DEPLOYMENT>'
  AND je.ACCOUNT_ID = <ACCOUNT_ID>
  AND je.CREATED_ON >= DATEADD('day', -7, CURRENT_TIMESTAMP())
  AND je.DESCRIPTION ILIKE 'UPDATE%<CANDIDATE_TABLE>%'
  AND je.ERROR_CODE IS NULL
ORDER BY RANDOM()
LIMIT 15;
"
```

---

## Decision Framework

### Hybrid Table Candidates
Score each candidate table:

| Criteria | Score | Description |
|----------|-------|-------------|
| UPDATE % > 1% of table ops | +3 | Significant UPDATE activity |
| DELETE % > 0.5% of table ops | +2 | Non-trivial DELETE activity |
| Parameterized queries (? or :param) | +3 | OLTP-style prepared statements |
| P50 latency > 500ms (room for improvement) | +2 | Current latency is slow |
| WHERE clause with equality predicates | +2 | Point lookup pattern |
| Non-ETL/staging table | +3 | Production operational table |

**Negative Scores:**
| Criteria | Score | Description |
|----------|-------|-------------|
| Table name contains TEMP/STG/WORK | -5 | ETL/staging table |
| Bulk operations (IN subquery, no WHERE) | -3 | Not suitable for HT |
| Non-parameterized bulk queries | -2 | Batch pattern |

**Score >= 8**: Strong Hybrid Table candidate
**Score 5-7**: Moderate candidate, needs validation
**Score < 5**: Likely not a good fit

### Interactive Analytics Candidates
Score each candidate table:

| Criteria | Score | Description |
|----------|-------|-------------|
| Read % >= 99% | +3 | Almost exclusively reads |
| Read % 95-99% | +2 | Very read-heavy |
| P50 latency 100ms-5s | +3 | Sub-second target, room to improve |
| Query volume > 100K/month | +2 | Frequently accessed |
| Current latency > 1s | +2 | Significant improvement potential |
| No DML activity | +2 | Purely read workload |

**Score >= 8**: Strong IA candidate
**Score 5-7**: Moderate candidate, needs validation
**Score < 5**: May not benefit significantly

---

## Output Options

### Option A: Markdown Report Only
Generate a markdown report file (see template below).

### Option B: Structured Data + Dashboard (RECOMMENDED)
Output structured data files that can be loaded into the pre-built Streamlit dashboard.

#### Step 8: Generate Structured Output Files
After running all analysis queries, save results as structured files:

**Output Folder Structure:**
```
analysis_output/<customer_name>/
├── analysis_metadata.json      # Customer info, summary stats
├── daily_activity.parquet      # Daily query timeline
├── statement_summary.parquet   # Statement type breakdown
├── update_patterns.parquet     # ETL vs OLTP classification
├── hybrid_candidates.parquet   # HT candidate tables with scores
├── ia_candidates.parquet       # IA candidate tables with scores
└── delete_activity.parquet     # DELETE activity by table
```

**Python code to save outputs:**
```python
import pandas as pd
import json
from datetime import datetime
from pathlib import Path

# Create output folder
output_folder = Path("/Users/atimm/Documents/Unistore/analysis_output/<customer_name>")
output_folder.mkdir(parents=True, exist_ok=True)

# Save metadata
metadata = {
    "customer_name": "<CUSTOMER_NAME>",
    "account_id": <ACCOUNT_ID>,
    "account_name": "<ACCOUNT_NAME>",
    "deployment": "<DEPLOYMENT>",
    "analysis_days": <DAYS>,
    "generated_at": datetime.now().isoformat(),
    "total_queries": <TOTAL>,
    "hybrid_candidates_count": len(hybrid_candidates_df),
    "ia_candidates_count": len(ia_candidates_df)
}
with open(output_folder / "analysis_metadata.json", "w") as f:
    json.dump(metadata, f, indent=2)

# Save DataFrames as parquet
daily_activity_df.to_parquet(output_folder / "daily_activity.parquet")
statement_summary_df.to_parquet(output_folder / "statement_summary.parquet")
update_patterns_df.to_parquet(output_folder / "update_patterns.parquet")
hybrid_candidates_df.to_parquet(output_folder / "hybrid_candidates.parquet")
ia_candidates_df.to_parquet(output_folder / "ia_candidates.parquet")
delete_activity_df.to_parquet(output_folder / "delete_activity.parquet")

print(f"Analysis saved to: {output_folder}")
```

#### Step 9: Launch Dashboard
After saving structured output, launch the pre-built dashboard:

```bash
# Start the dashboard (runs on port 8502)
streamlit run /Users/atimm/Documents/Unistore/cortex_skills_repo/skills/unistore-customer-workload-conversion-advisor/dashboard/app.py --server.port 8502 --server.headless true
```

The dashboard will:
1. Auto-detect available analyses in the output folder
2. Let user select which analysis to view
3. Display all visualizations with interactive Plotly charts

**Dashboard Features:**
- 📈 **Daily Timeline**: Stacked area chart for reads, bar chart for writes
- 🎯 **Hybrid Tables**: Scatter plot (volume vs latency), candidate ranking
- 📊 **Interactive Analytics**: Read-heavy table analysis with fit scoring
- 🔍 **UPDATE Patterns**: ETL vs OLTP classification pie chart
- 📋 **Summary**: Executive overview with recommendations

**Dashboard Location:** `skills/unistore-customer-workload-conversion-advisor/dashboard/app.py`

---

## Output Report Template

```markdown
# Customer Workload Conversion Analysis

**Customer:** [Customer Name]
**Account ID:** [ID]
**Account Name:** [NAME]
**Deployment:** [Deployment]
**Analysis Period:** Last [X] days
**Report Date:** [Date]

---

## Executive Summary

**Total Queries Analyzed:** [X]M
**Statement Distribution:** [X]% SELECT, [X]% INSERT, [X]% UPDATE, [X]% DELETE
**Hybrid Table Candidates:** [X] tables
**Interactive Analytics Candidates:** [X] tables

**Key Finding:** [1-2 sentence summary of main opportunity]

---

## Account Activity Summary

| Metric | Value |
|--------|-------|
| Total Queries | [X] |
| Daily Average | [X] |
| Peak Day | [Date]: [X] queries |
| Avg Query Duration | [X]ms |

### Statement Type Distribution

| Type | Count | % | Avg Duration | P50 Duration |
|------|-------|---|--------------|--------------|
| SELECT | [X] | [X]% | [X]ms | [X]ms |
| INSERT | [X] | [X]% | [X]ms | [X]ms |
| UPDATE | [X] | [X]% | [X]ms | [X]ms |
| DELETE | [X] | [X]% | [X]ms | [X]ms |
| MERGE | [X] | [X]% | [X]ms | [X]ms |

### UPDATE Pattern Classification

| Pattern | Count | Avg Duration | Assessment |
|---------|-------|--------------|------------|
| Point Update (Parameterized) | [X] | [X]ms | ✅ HT Candidate |
| Point Update (Literal) | [X] | [X]ms | ⚠️ Needs Review |
| ETL/Staging | [X] | [X]ms | ❌ Exclude |
| Bulk/Other | [X] | [X]ms | ❌ Exclude |

---

## Top Hybrid Table Candidates

| Rank | Table | Score | UPDATE Count | Parameterized % | P50 Latency | Key Indicators |
|------|-------|-------|--------------|-----------------|-------------|----------------|
| 1 | [TABLE_1] | [X/15] | [X] | [X]% | [X]ms | [indicators] |
| 2 | [TABLE_2] | [X/15] | [X] | [X]% | [X]ms | [indicators] |

### Detailed Analysis: [TOP_CANDIDATE]

**Why Hybrid Tables:**
1. [Reason 1 with data]
2. [Reason 2 with data]
3. [Reason 3 with data]

**Sample Query Patterns:**
```sql
-- Parameterized UPDATE example
[QUERY_SAMPLE]
```

**Expected Improvement:**
| Metric | Current | Expected with HT |
|--------|---------|------------------|
| UPDATE P50 | [X]ms | <20ms |
| UPDATE P99 | [X]ms | <100ms |

---

## Top Interactive Analytics Candidates

| Rank | Table | Score | Query Count | Read % | P50 Latency | IA Fit |
|------|-------|-------|-------------|--------|-------------|--------|
| 1 | [TABLE_1] | [X/12] | [X] | [X]% | [X]ms | STRONG |
| 2 | [TABLE_2] | [X/12] | [X] | [X]% | [X]ms | MODERATE |

### Detailed Analysis: [TOP_CANDIDATE]

**Why Interactive Analytics:**
1. [Reason 1 with data]
2. [Reason 2 with data]

**Expected Improvement:**
| Metric | Current | Expected with IA |
|--------|---------|------------------|
| P50 latency | [X]ms | <500ms |
| P99 latency | [X]ms | <2s |

---

## Tables NOT Recommended for Conversion

| Table | Reason |
|-------|--------|
| TEMP_DB.* | ETL/Staging tables |
| *_STG tables | Staging tables for data pipelines |
| *_TEMP tables | Temporary processing tables |

---

## Next Steps

### For Hybrid Table Candidates:
1. [ ] Validate primary key structure on candidate tables
2. [ ] Review query patterns with customer DBA
3. [ ] Assess application compatibility (driver, connection pooling)
4. [ ] Create POC plan for top candidate

### For Interactive Analytics Candidates:
1. [ ] Confirm workload is truly read-only or accept limited DML
2. [ ] Validate dashboard/BI access patterns
3. [ ] Review current caching strategies
4. [ ] Create POC plan for top candidate

### Customer Conversation Points:
- [Key talking point based on analysis]
- [ROI opportunity]
- [Recommended starting point]
```

---

## When to Apply This Skill

- User provides a customer name and asks to find conversion opportunities
- User asks "which tables should be Hybrid Tables for [customer]"
- User asks "identify Interactive Analytics candidates for [customer]"
- User asks "analyze [customer] workload for Unistore opportunities"
- User asks "prospect [customer] for Hybrid Tables"
- User asks "what queries would benefit from sub-10ms latency"
- User mentions "conversion candidates" or "workload analysis"

---

## Key Snowhouse Tables Reference

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `SNOWHOUSE.PRODUCT.ALL_LIVE_ACCOUNTS` | Account lookup | ID, NAME, DEPLOYMENT, CREATED_ON |
| `SNOWHOUSE.PRODUCT.JOB_FACT` | Query execution metrics | ACCOUNT_ID, DEPLOYMENT, DURATION_TOTAL, JOBS, CREATED_HOUR |
| `SNOWHOUSE.PRODUCT.STATEMENT_TYPE` | Statement type classification | ID, STATEMENT_TYPE |
| `SNOWHOUSE_IMPORT.PROD.JOB_ETL_V` | Query text and detailed metrics | ACCOUNT_ID, DEPLOYMENT, DESCRIPTION, TOTAL_DURATION, CREATED_ON |

---

## Common Company Name Aliases

When initial search fails, suggest checking these common patterns:

| Current Name | Former/Alternate Names |
|--------------|------------------------|
| Elevance Health | Anthem |
| Meta | Facebook |
| Alphabet | Google |
| Warner Bros. Discovery | WarnerMedia, Discovery |

---

## Telemetry

### Telemetry Configuration
| Setting | Value |
|---------|-------|
| Database | `AFE` |
| Schema | `PUBLIC_APP_STATE` |
| Table | `APP_EVENTS` |
| App Name | `Unistore Workload Conversion Advisor (Skill)` |
| App Version | `2.0.0` |

### Step: Log Telemetry Event
After completing the analysis, log a telemetry event:

```bash
snow sql -c Snowhouse_PAT -q "
INSERT INTO AFE.PUBLIC_APP_STATE.APP_EVENTS (
    APP, APP_NAME, APP_VERSION, USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
    SALESFORCE_ACCOUNT_NAME, SNOWFLAKE_ACCOUNT_ID, DEPLOYMENT,
    ACTION_TYPE, ACTION_CONTEXT, SUCCESS, DURATION_MS
)
SELECT
    'Unistore Workload Conversion Advisor (Skill)',
    'Unistore Workload Conversion Advisor (Skill)',
    '2.0.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    '<CUSTOMER_NAME>',
    '<ACCOUNT_ID>',
    '<DEPLOYMENT>',
    'RUN_ANALYSIS',
    PARSE_JSON('{
        \"analysis_days\": <DAYS>,
        \"tables_analyzed\": <COUNT>,
        \"hybrid_candidates\": <COUNT>,
        \"ia_candidates\": <COUNT>,
        \"top_hybrid_candidate\": \"<TABLE_NAME>\",
        \"top_ia_candidate\": \"<TABLE_NAME>\",
        \"output_format\": \"<markdown|streamlit>\",
        \"report_path\": \"<REPORT_PATH>\"
    }'),
    TRUE,
    <DURATION_MS>;
"
```

### Telemetry Events
| Event | When to Log |
|-------|-------------|
| `RUN_ANALYSIS` | After successfully generating the analysis report |
| `ERROR_ANALYSIS` | If analysis fails (set SUCCESS=FALSE, include ERROR_MESSAGE) |

---

## Changelog

### v2.0.0 (2026-01-27)
- **Fixed:** Account lookup query - removed invalid columns (CLOUD_NAME, REGION_NAME), use CREATED_ON
- **Fixed:** Table name extraction - use SPLIT_PART instead of REGEXP_SUBSTR for reliability
- **Added:** Company name alias support (alternate/former names)
- **Added:** Account locator direct lookup
- **Added:** UPDATE pattern classification (ETL vs OLTP)
- **Added:** ETL/staging table filtering
- **Added:** Streamlit dashboard output option
- **Added:** Negative scoring for ETL patterns
- **Added:** Common company name aliases reference
- **Improved:** Scoring system with ETL awareness
- **Improved:** Query templates based on real-world testing (Elevance Health)
