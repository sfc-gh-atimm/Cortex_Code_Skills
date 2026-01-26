# HT_INDEXES_NOT_USED_RUNTIME — Indexes Present in SnowVI but Not Used at Runtime

## What This Means

SnowVI shows that one or more **Hybrid Tables** have secondary indexes defined on columns that match query predicates, but **JOB_ETL_JPS_V runtime metadata indicates those indexes are not being used** (e.g., no index operators, zero equality coverage, high FDB I/O).  

In practice, this means the workload is paying Hybrid Table overhead and index maintenance cost **without actually benefiting from indexed access**.

---

## Why This Hurts Performance

When Hybrid Table queries bypass existing indexes, they fall back to **row-by-row storage I/O or wide range scans**, dramatically increasing FDB I/O, latency, and contention on hot keys.  

You also pay **extra write and maintenance overhead** for indexes that never participate in the plan, which is pure cost with no benefit.  

Over time, unused indexes + non-sargable predicates often **amplify p95/p99 latency under load**, even if p50 looks acceptable in light testing.

---

## Real-World Context

**Field Experience:**
- **B2C E‑commerce**: Checkout service had a secondary index on `ORDER_ID`, but queries filtered on `TO_VARCHAR(ORDER_ID)` from the app → plans never used the index, FDB I/O ~5–10x higher than expected and p95 > 500 ms. → Fixed by aligning predicate type to numeric `ORDER_ID` and removing the function call → SnowVI showed index probes, FDB I/O dropped by ~70%, p95 stabilized around 80–100 ms.

- **Fintech (card auth API)**: Auth table indexed on `ACCOUNT_ID, AUTH_ID`, but API sent predicates on `LOWER(ACCOUNT_ID)` with leading‑wildcard `LIKE` patterns → all point lookups degenerated into scans, Hybrid Table throttling spikes during peak hours. → Refactored API to send case‑normalized `ACCOUNT_ID` and equality predicates, plus moved large analytic queries to a columnar table → removed throttling events, p99 latency improved from ~900 ms to <200 ms.

**Common Pattern:**

You upload SnowVI JSON and see **healthy index definitions** on the right tables and columns, but JOB_ETL_JPS_V shows:

* `ACCESS_KV_TABLE = TRUE` and `FDB_IO_BYTES` high for the query

* `best_eq_prefix = 0` and/or no index operators in the plan

* Predicates use functions, casts, or incompatible types on the indexed column, or the workload is actually **analytic / scan-heavy** running against a Hybrid Table.  

The AFE or app developer assumes "we already have the right index," but **fundamental best practices (sargable predicates, equality filters, OLTP fit) are not being followed**, so the optimizer cannot take the index path.

---

## How to Fix It

### Step 1: Confirm "index exists but not used" with SnowVI + Runtime Metadata

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Confirm Hybrid Table + suspect index usage
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT
    uuid,
    access_kv_table              AS access_kv_table,
    stats:stats.snowTramFDBIOBytes::NUMBER AS fdb_io_bytes,
    stats:stats.producedRows::NUMBER       AS rows_produced,
    total_duration,
    database_name,
    schema_name,
    table_name
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_JPS_V
WHERE uuid = '{{QUERY_UUID}}';
```

#### 👤 For Customer Use

```sql
-- Customer: Check query metrics for index usage indicators
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT
    QUERY_ID,
    QUERY_TEXT,
    TOTAL_ELAPSED_TIME,
    BYTES_SCANNED,
    ROWS_PRODUCED
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_ID = '{{QUERY_UUID}}';
```

**Tip for Customers:** Use SnowVI to visualize the execution plan and verify whether index operators (`IndexProbe`, `IndexRange`) are present.

In SnowVI for the same UUID:

* Verify the table is **Hybrid** and has one or more indexes on the columns used in the `WHERE` clause.

* Confirm the plan **does not show** `IndexProbe` / `IndexRange` operators on those indexes.

This combination (indexes in SnowVI, no index usage in runtime metadata) is what triggers `HT_INDEXES_NOT_USED_RUNTIME`.

---

### Step 2: Make predicates sargable and type‑aligned with the indexed columns

1. **Remove functions/casts on the indexed column.**

```sql
-- Anti-pattern: function on indexed column prevents index usage
SELECT ...
FROM ht_orders
WHERE TO_DATE(order_ts) = '2025-12-18';

-- Better: range predicate on the raw indexed column
SELECT ...
FROM ht_orders
WHERE order_ts >= '2025-12-18'::TIMESTAMP_NTZ
  AND order_ts <  '2025-12-19'::TIMESTAMP_NTZ;
```

2. **Align data types with the index / PK definition.**

```sql
-- Anti-pattern: implicit cast from VARCHAR → NUMBER
SELECT ...
FROM ht_accounts
WHERE account_id = :account_id_str;  -- :account_id_str is VARCHAR

-- Better: send correct type or cast the parameter, not the column
SELECT ...
FROM ht_accounts
WHERE account_id = :account_id_num;  -- numeric bound variable

-- If needed:
WHERE account_id = :account_id_str::NUMBER;
```

3. **Avoid leading‑wildcard patterns on indexed columns.**

```sql
-- Anti-pattern: leading wildcard kills index usage
WHERE email LIKE '%@example.com';

-- Better: structure data or predicates to keep the left side anchored
WHERE email LIKE 'adam.%@example.com';
```

Update application code to:

* Use **bound variables / prepared statements** (no string concatenation of literals).

* Remove unnecessary casts and functions from the **left-hand side** of predicates on indexed columns.

---

### Step 3: Route analytic / scan-heavy queries off Hybrid Tables

If JOB_ETL_JPS_V and SnowVI show:

* Large `BYTES_SCANNED` and wide scans/aggregations on the Hybrid Table, or

* The query mostly does reporting-style work (GROUP BY, large ranges, full-table scans),

then the right fix is **architectural**, not more index tuning:

```sql
-- Example: create a columnar reporting table
CREATE OR REPLACE TABLE rpt_orders AS
SELECT
    order_id,
    customer_id,
    created_at,
    status,
    total_amount
FROM ht_orders;

-- Optionally, use a task or stream to keep it fresh
```

Point dashboards and heavy analytics to `rpt_orders` (or an MV) and keep the Hybrid Table for **OLTP-style, indexed point lookups**.

---

### Step 4: Validate index usage and runtime improvement

1. **Re‑run the query and inspect in SnowVI:**

   * Look for `IndexProbe`/`IndexRange` operators on the expected index.

2. **Re-check runtime metrics for the same UUID/hash:**

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Validate improvement after changes
-- Replace {{DEPLOYMENT}} with the actual deployment
SELECT
    uuid,
    stats:stats.snowTramFDBIOBytes::NUMBER AS fdb_io_bytes,
    stats:stats.producedRows::NUMBER       AS rows_produced,
    total_duration
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_JPS_V
WHERE uuid = '{{NEW_QUERY_UUID}}';
```

3. **Track parameterized hash over time** (if using bound variables):

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Track performance by parameterized hash
SELECT
    query_parameterized_hash,
    COUNT(*)                 AS executions,
    AVG(total_duration)      AS avg_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_duration) AS p95_ms
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_JPS_V
WHERE query_parameterized_hash = '{{HASH}}'
GROUP BY query_parameterized_hash;
```

#### 👤 For Customer Use

```sql
-- Customer: Track performance by parameterized hash
SELECT
    QUERY_PARAMETERIZED_HASH,
    COUNT(*)                      AS executions,
    AVG(TOTAL_ELAPSED_TIME)       AS avg_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) AS p95_ms
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_PARAMETERIZED_HASH = '{{HASH}}'
  AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY QUERY_PARAMETERIZED_HASH;
```

You should see:

* Lower `FDB_IO_BYTES` per row

* Stable or improved `total_duration` and p95

* Index operators visible in SnowVI

---

## Expected Improvement

- **Query Time**: Often **2–10× faster** for hot point‑lookup paths once indexes are actually used (e.g., 800 ms → 80–300 ms), depending on data size and contention.

- **Resource Usage**: **FDB I/O and Hybrid Table throttling** can drop by **50–80%** for the affected queries when non-sargable predicates are fixed and analytic scans are moved off HT.

- **Throughput**: For OLTP workloads, enabling effective index usage and proper query shapes can unlock **2–5× more QPS** at the same warehouse size before hitting latency or throttling limits.

**Confidence:** Medium – this pattern has shown consistent wins in multiple HT performance investigations, but numbers vary widely based on workload mix and data model.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**

- **The predicates do not actually target the indexed columns.** If SnowVI shows indexes on `(A,B)` but the query filters on unrelated columns, "fixing" predicates to force index usage may be incorrect for the business logic.

- **The workload is intentionally analytic / scan-heavy.** For large reporting or batch workloads, trying to force index usage on Hybrid Tables can *hurt* performance; these queries belong on regular tables or MVs.

- **The query is already within SLOs under realistic load.** If p95 latency and FDB I/O are acceptable, chasing index usage purely for aesthetic reasons may add risk with little benefit.

✅ **Do consider alternatives if:**

- You primarily see **large scans, GROUP BY, or aggregations** on the Hybrid Table → design a **columnar reporting table or MV** and route analytics there.

- Indexes in SnowVI clearly target **rare or different access paths** than the one you're analyzing → it may be better to **add a new, justified index** for the real hot path (after confirming you are following HT best practices and not misusing the table for analytics).

---

## Related Findings

See also:

- `findings/HT_WITHOUT_INDEXES.md` – Hybrid Table used without any indexes defined.

- `findings/NO_INDEX_FOR_HOT_PREDICATES.md` – Hot predicates that have no supporting index at all.

- `findings/COMPOSITE_INDEX_MISALIGNED.md` – Composite index exists but leading columns don't match equality predicates.

- `findings/PRIMARY_KEY_NOT_USED.md` – Primary key defined but not used in predicates.

- `findings/ANALYTIC_WORKLOAD_ON_HT.md` – Analytic/reporting workloads incorrectly running on Hybrid Tables.

---

## Additional Resources

- [Hybrid Table Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)

- Internal: **Hybrid Table Query Analyzer** app overview and architecture (Snowhouse/Snowsight)

- Internal Field Manual: `general/ht_sweet_spot.md` – When (and when not) to use Hybrid Tables

---

**Last updated:** 2025-12-19  
**Contributor:** Adam Timm / Unistore Workload Team  
**Field Validated:** Yes _(Validated at B2C E-commerce and Fintech customers)_
