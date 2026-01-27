# SLOW_CTAS_LOAD

## What This Means

The **SLOW_CTAS_LOAD** finding means a `CREATE TABLE AS SELECT` (CTAS) operation inserted a very large number of rows but achieved lower-than-expected throughput. In plain terms: this was a big bulk load into a table, and it took longer than it should have for that volume of data.

---

## Why This Hurts Performance

Bulk loads are usually one-time or infrequent operations where we want to **max out throughput** and **minimize wall-clock time**. When a CTAS is slow:

- It delays downstream jobs (e.g., backfills, migrations, reindexing).
- It ties up warehouse resources and may interfere with other workloads if sharing a warehouse.
- It can mask design issues (e.g., running CTAS on an already "dirty" or heavily-indexed table, competing traffic, or non-optimal warehouse choice).

For Hybrid Table-related pipelines, slow CTAS operations also make it harder to run realistic performance tests or to re-create test datasets quickly.

---

## Real-World Context

**Field Experience:**
- **Migrations**: Moving a large fact table or operational dataset into Snowflake or Hybrid Tables using CTAS on a busy shared warehouse → hours-long jobs and missed cutover windows → moving CTAS to a dedicated XS/S warehouse and scheduling it after compaction finished reduced wall-clock time dramatically.

- **Backfills**: Teams running CTAS for partial backfills (e.g., last 90 days) while other heavy workloads ran on the same warehouse → bulk loads were starved of resources and appeared "slow" → isolating CTAS to its own warehouse and cleaning up the SELECT (no unnecessary joins/columns) resolved the issue.

**Common Pattern:**
A CTAS is launched against a large dataset on a multi-purpose warehouse during peak hours, sometimes with unnecessary joins, wide rows, or poorly filtered source tables. The CTAS itself is fine in principle, but the **environment and query shape** make it much slower than it needs to be.

---

## How to Fix It

### Step 1: Confirm It's Truly a Bulk Load

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Confirm bulk load
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT
  UUID,
  QUERY_TEXT,
  ROWS_INSERTED,
  TOTAL_ELAPSED_TIME / 1000.0 AS duration_s
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE UUID = '{{QUERY_UUID}}';
```

#### 👤 For Customer Use

```sql
-- Customer: Confirm bulk load
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT
  QUERY_ID,
  QUERY_TEXT,
  ROWS_INSERTED,
  TOTAL_ELAPSED_TIME / 1000.0 AS duration_s
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_ID = '{{QUERY_UUID}}';
```

Rules of thumb for the **SLOW_CTAS_LOAD** pattern:

- `QUERY_TYPE` is `CREATE_TABLE_AS_SELECT`.
- `ROWS_INSERTED` is in the millions (e.g., 10M+).
- `duration_s` is high relative to your expectations or similar jobs.

### Step 2: Run CTAS on a Dedicated Warehouse

```sql
-- Create or reuse a dedicated warehouse for bulk loads
CREATE WAREHOUSE IF NOT EXISTS HT_CTAS_WH
  WAREHOUSE_SIZE = 'SMALL'
  AUTO_SUSPEND   = 300
  AUTO_RESUME    = TRUE;

USE WAREHOUSE HT_CTAS_WH;

CREATE OR REPLACE TABLE TARGET_TABLE AS
SELECT ...
FROM SOURCE_TABLE
WHERE ...;
```

*Avoid running large CTAS on the same warehouse that serves latency-sensitive HT queries or BI workloads.*

### Step 3: Simplify the CTAS Query

```sql
-- Before: CTAS with many unnecessary columns and joins
CREATE OR REPLACE TABLE TARGET_TABLE AS
SELECT *
FROM BIG_SOURCE S
JOIN OTHER_TABLE O   ON S.KEY = O.KEY
JOIN LOOKUP L        ON S.CODE = L.CODE
WHERE S.EVENT_DATE >= '2025-01-01';

-- After: minimal, bulk-friendly CTAS
CREATE OR REPLACE TABLE TARGET_TABLE AS
SELECT
  S.PRIMARY_KEY,
  S.EVENT_DATE,
  S.METRIC_1,
  S.METRIC_2
FROM BIG_SOURCE S
WHERE S.EVENT_DATE >= '2025-01-01';
```

*Strip out unnecessary joins, columns, and filters that don't affect the target table's purpose.*

### Step 4: Schedule CTAS After Heavy Maintenance / Compaction

If your environment has maintenance/compaction windows, schedule CTAS **outside of those periods** to avoid competing for I/O and compute.

---

## Expected Improvement

- **Query Time**: [Before] → [After] (e.g., bulk CTAS going from hours to tens of minutes, or minutes to a few minutes).
- **Resource Usage**: [Before] → [After] (more consistent CPU/I/O usage with less backpressure and fewer retries).
- **Operational Impact**: [Before] → [After] (less interference with user-facing workloads and more predictable ETL windows).

**Confidence:** Medium–High. Impact depends on how much of the slowdown was due to environment (warehouse sharing, timing) vs query shape or data skew.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**

- The CTAS is small (e.g., thousands of rows) and not on any critical path; minor slowness is not worth added complexity.
- The perceived "slowness" is actually dominated by **upstream** operations (e.g., external system latency, staged file availability), not the CTAS itself.

✅ **Do consider alternatives if:**

- You are **rebuilding the same table repeatedly**: consider a stable pattern of `CTAS INTO NEW_TABLE` + rename/swap instead of fat incremental DML.
- You have **strict SLAs** on the derived table: plan CTAS as part of a well-defined batch window with dedicated capacity, not as an ad-hoc manual run.

---

## Related Findings

See also:

- `findings/BULK_DML_SHOULD_BE_CTAS.md` – large INSERT/MERGE/UPDATE statements that are better as CTAS + swap.
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` – analytic-style scans on tables meant for operational workloads.

---

## Additional Resources

- Snowflake docs: CTAS best practices and bulk loading guidance.
- Internal: Unistore / Hybrid Tables POC guides and performance testing docs.

---

**Last Updated:** 2025-12-06  
**Contributor:** AFE / SE Field Manual  
**Field Validated:** Yes

