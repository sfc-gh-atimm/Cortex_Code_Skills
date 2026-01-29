# ANALYTIC_WORKLOAD_ON_HT

## What This Means

The **ANALYTIC_WORKLOAD_ON_HT** finding means the query is doing large scans, aggregations, or full-result sorting on a Hybrid Table instead of small, index-driven point or narrow-range lookups. In other words, the workload looks like a BI/reporting query, but it's pointed at a Hybrid Table.

---

## Why This Hurts Performance

Hybrid Tables are optimized for low-latency, index-based random reads/writes over small result sets, not for scanning and aggregating large volumes of rows. When you run a heavy analytic query on a Hybrid Table, the engine often behaves like a scan over the analytical/object store but still pays Hybrid Table overheads.

This typically leads to higher latency, more I/O, and wasted Hybrid Table capacity compared to putting the same workload on a standard table, materialized view, or dynamic table designed for analytics.

---

## Real-World Context

**Field Experience:**
- **Operational app with embedded reporting**: Dashboard queries were pointed at the same Hybrid Table used for point-lookups → slow dashboards and noisy HT metrics → moved reporting queries to a standard table + MVs fed from the same ingest pipeline → dashboards became responsive and HT metrics reflected only true operational traffic.

- **API + batch analytics sharing the same HT**: Latency-sensitive API queries and nightly analytics ran on the same Hybrid Table → API occasionally missed SLAs during heavy reporting windows → split design so that APIs hit HT while analytics ran on standard tables → API latencies stabilized and analytics became easier to tune independently.

**Common Pattern:**
Teams start with Hybrid Tables for an operational API and then bolt on more and more analytic queries "because the data is already there." Over time, dashboard/reporting workloads dominate, and the system behaves like a data warehouse running on a transactional storage engine.

---

## How to Fix It

### Step 1: Identify the Analytic Workload

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Look for large scans / aggregations on HT tables
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT *
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.AGGREGATE_QUERY_HISTORY
WHERE DATABASE_NAME   = '{{DATABASE_NAME}}'
  AND SCHEMA_NAME     = '{{SCHEMA_NAME}}'
  AND TABLE_NAME      = '{{HT_TABLE_NAME}}'
  AND ROWS_PRODUCED   > 100000      -- tune for your environment
  AND QUERY_TYPE ILIKE '%SELECT%'
ORDER BY AVG_DURATION_MS DESC
LIMIT 50;
```

#### 👤 For Customer Use

```sql
-- Customer: Look for large scans / aggregations on HT tables
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT
    QUERY_ID,
    QUERY_TEXT,
    TOTAL_ELAPSED_TIME,
    BYTES_SCANNED,
    ROWS_PRODUCED,
    QUERY_TYPE
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE DATABASE_NAME = '{{DATABASE_NAME}}'
  AND ROWS_PRODUCED > 100000
  AND QUERY_TYPE ILIKE '%SELECT%'
  AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY TOTAL_ELAPSED_TIME DESC
LIMIT 50;
```

### Step 2: Create an Analytic Copy on a Standard Table

```sql
-- One-time snapshot
CREATE OR REPLACE TABLE ANALYTIC_<HT_TABLE_NAME> AS
SELECT *
FROM <DB>.<SCHEMA>.<HT_TABLE_NAME>;

-- Ongoing: keep fresh with a dynamic table (or task)
CREATE OR REPLACE DYNAMIC TABLE DT_ANALYTIC_<HT_TABLE_NAME>
TARGET_LAG = '5 MINUTES'
WAREHOUSE  = <WAREHOUSE>
AS
SELECT *
FROM <DB>.<SCHEMA>.<HT_TABLE_NAME>;
```

### Step 3: Redirect BI / Reporting Queries

```sql
-- Before (BAD for analytics)
SELECT ...
FROM <DB>.<SCHEMA>.<HT_TABLE_NAME>
WHERE EVENT_DATE BETWEEN '2025-01-01' AND '2025-01-31'
GROUP BY ...;

-- After (BETTER: analytic copy)
SELECT ...
FROM <DB>.<SCHEMA>.ANALYTIC_<HT_TABLE_NAME>
WHERE EVENT_DATE BETWEEN '2025-01-01' AND '2025-01-31'
GROUP BY ...;
```

### Step 4: Validate Improvement

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Compare before/after by query hash
-- Replace {{DEPLOYMENT}} with the actual deployment
SELECT QUERY_TEXT_HASH,
       AVG_DURATION_MS,
       AVG_BYTES_SCANNED,
       AVG_ROWS_PRODUCED
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.AGGREGATE_QUERY_HISTORY
WHERE QUERY_TEXT_HASH IN ('{{BEFORE_HASH}}', '{{AFTER_HASH}}')
GROUP BY 1;
```

#### 👤 For Customer Use

```sql
-- Customer: Compare before/after by query hash
SELECT QUERY_PARAMETERIZED_HASH,
       AVG(TOTAL_ELAPSED_TIME)   AS AVG_DURATION_MS,
       AVG(BYTES_SCANNED)        AS AVG_BYTES_SCANNED,
       AVG(ROWS_PRODUCED)        AS AVG_ROWS_PRODUCED
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_PARAMETERIZED_HASH IN ('{{BEFORE_HASH}}', '{{AFTER_HASH}}')
  AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY QUERY_PARAMETERIZED_HASH;
```

---

## Expected Improvement

- **Query Time**: [Before] → [After] (e.g., 20–60s → low single-digit seconds)
- **Resource Usage**: [Before] → [After] (e.g., significantly fewer bytes scanned, less HT request volume)
- **Throughput**: [Before] → [After] (e.g., HT capacity freed up for true OLTP-style queries)

**Confidence:** High, when the workload is clearly reporting/analytic in nature.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- The workload is truly *operational* (small result sets, strict latency SLAs) and the slow query is due to missing/incorrect indexes or parameter binding rather than analytic behavior.
- Analytic queries are rare and non-SLA-critical (e.g., occasional manual investigations).

✅ **Do consider alternatives if:**
- You can reframe the query as a **small, index-driven lookup** (add strict filters and `LIMIT`) instead of scanning the full HT.
- You can move heavy aggregations into **dynamic tables** or **materialized views** built on standard tables already fed by the same pipeline.

---

## Related Findings

See also:
- `findings/HT_INDEXES_NOT_USED_RUNTIME.md` – Runtime metrics show indexes are not providing expected benefit.
- `findings/FULL_SORT_ON_HT.md` – `ORDER BY` without `LIMIT` on HT causing full sorts over large result sets.

---

## Additional Resources

- Hybrid Tables best practices (public docs)
- Internal: Unistore / Hybrid Tables field implementation guides and enablement decks

---

**Last Updated:** 2025-12-06  
**Contributor:** AFE / SE Field Manual (Hybrid Tables)  
**Field Validated:** Yes

