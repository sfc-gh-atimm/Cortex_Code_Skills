# SCALAR_UDF_ON_HYBRID_TABLE

## What This Means

The query is calling a **scalar UDF** that internally reads from a **Hybrid Table**.  
In SnowVI, the logical plan for the UDF has been inlined (TableScan/Filter/Sort/Result on a Hybrid Table), even though the top-level SQL only shows a UDF call.

---

## Why This Hurts Performance

Hybrid Tables are optimized for **simple, short-running point/range lookups** with plan cache and index-based access.  
Scalar UDFs often disable or limit some fast-path optimizations (e.g., plan cache for Hybrid Tables) and can obscure the real access pattern, making it harder to tune predicates and indexes directly.

If the UDF body performs more complex analytical work (large scans, aggregates, wide sorts) on a Hybrid Table, the query will behave like an **analytic workload on a row store**, which is outside the sweet spot for Hybrid Tables and can be significantly slower than using standard tables.

**Key Limitation:** Hybrid Tables do not currently support UDFs for plan cache purposes. Queries involving UDFs generally won't use the HT plan cache, losing some of the low-latency benefits intended for simple, parameterized HT queries.

---

## Real-World Context

**Field Experience:**
- **SaaS app / workflow state**: UDF used as a convenience wrapper over a Hybrid Table "serving" query. Latency was 300–600 ms p95 → inlined the SQL, added an index on the equality predicate, and parameterized the call → ~40–60 ms p95 and stable throughput.
- **Internal analytics-on-HT prototype**: complex scalar UDF over a Hybrid Table with joins and aggregates. Queries took seconds and plan cache wasn't used. Moving the analytic part to standard tables, leaving only a lightweight HT lookup, brought latency from 2–4 s → < 300 ms and cut Hybrid Table request credits by ~70%.

**Common Pattern:**
Customers wrap Hybrid Table access in a UDF to "simplify" their application API. Over time, more logic accretes in the UDF (joins, aggregations, conditional logic), and what started as a point lookup becomes a mini analytical query running on a Hybrid Table, often without clear visibility into predicates and index usage.

---

## How to Fix It

### Step 1: Expose the Actual Query Body

Use SnowVI (or the app's SnowVI parser) to inspect the **logical plan** for the UDF and reconstruct a simple pseudo-SQL:

```sql
-- Example of expanded UDF body (pseudo-SQL)
SELECT OBJECT_CONSTRUCT('memberId', HT_PRESESSION_SUMMARY_SERVING.USER_PID, ...)
FROM   PROD_NOVA_AI.CORE.HT_PRESESSION_SUMMARY_SERVING
WHERE  USER_PID = :user_pid
ORDER BY CREATED_UTC DESC
LIMIT 1;
```

Focus your tuning on this expanded query, not just the top-level `SELECT fn_my_udf(...)`.

### Step 2: Decide if the Workload is Operational or Analytical

- If the UDF body is a **simple point/range lookup** on a small result set:
  - Hybrid Table is likely a good fit.
- If the UDF body performs **large scans, aggregations, joins, or wide sorts**:
  - Treat this as an **analytic workload** and move that part to standard tables or other analytic structures (views, MVs, Dynamic Tables).

### Step 3: Move Hot Path Off the UDF (for HT-critical workloads)

For latency-sensitive Hybrid Table use cases:

1. **Inline the HT query** into the application instead of calling the UDF:

```sql
-- Before
SELECT core.fn_serve_presession_summary_by_user_pid(:user_pid) AS result;

-- After (app logic inlined)
SELECT OBJECT_CONSTRUCT('memberId', user_pid, ...) AS result
FROM   core.ht_presession_summary_serving
WHERE  user_pid = :user_pid
ORDER BY created_utc DESC
LIMIT 1;
```

2. Ensure the **predicate and index** are aligned:

```sql
-- Example: add secondary index on equality predicate
CREATE INDEX idx_ht_presession_user_pid
  ON core.ht_presession_summary_serving (user_pid);
```

3. Parameterize calls (bound variables) so Hybrid Table **plan cache** can be used consistently.

### Step 4: Route Analytics to Standard Tables

If the UDF body is doing analytics on HT:

1. Materialize the required data into a **standard table** or a **Dynamic Table**:

```sql
CREATE TABLE core.presession_summary_analytics AS
SELECT  ...
FROM    core.ht_presession_summary_serving;
```

or

```sql
CREATE OR REPLACE DYNAMIC TABLE core.presession_summary_dt
  TARGET_LAG = '5 minutes'
AS
SELECT ...
FROM core.ht_presession_summary_serving;
```

2. Update the UDF (or better, the application) to run the **analytic part** on the standard table, keeping Hybrid Tables for **operational state / point lookups only**.

---

## Expected Improvement

- **Query Time**:
  - Scalar UDF on HT (opaque body): 300–1000 ms p95  
  - Direct, parameterized HT lookup with aligned index: 20–80 ms p95 for point queries (depending on workload and quota).
- **Resource Usage**:
  - Excess Hybrid Table request credits from analytic patterns → reduced significantly when analytics are moved to standard tables.
- **Throughput**:
  - More stable QPS when plan cache and HT fast-path are consistently used.

**Confidence:** Medium–High (pattern seen across multiple app-style Hybrid Table PoCs and internal workloads)

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- The UDF is **not** touching Hybrid Tables at all (e.g., pure standard-table analytics or scalar math/string helpers).
- The UDF is a thin wrapper around **purely analytic standard tables**; in that case, normal UDF guidance applies.

✅ **Do consider alternatives if:**
- The UDF is part of a **multi-statement stored procedure** that's already the main bottleneck → focus on refactoring the stored procedure first.
- Security / governance requirements mandate a UDF boundary; then:
  - Keep the UDF body strictly to a **simple, parameterized HT lookup**.
  - Move heavy analytics behind views / MVs on standard tables.

---

## Related Findings

See also:
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` – Analytic workloads on Hybrid Tables (poor fit).
- `patterns/client_detection_for_performance_testing.md` – Performance testing patterns.

---

## Additional Resources

- [Internal Confluence: Hybrid Tables – Overview & Limitations]
- [Hybrid Tables Enablement Deck (Unistore Overview)]
- [Slack #sql-plan-cache thread – UDF and plan cache limitations for Hybrid Tables]

---

**Last Updated:** 2026-01-08  
**Contributor:** Applied Field Engineering (Hybrid Tables)  
**Field Validated:** No _(pattern observed, but not yet validated at 3+ named customers as a specific documented finding)_

