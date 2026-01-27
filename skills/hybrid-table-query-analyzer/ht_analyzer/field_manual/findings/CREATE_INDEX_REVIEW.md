# CREATE_INDEX_REVIEW

## What This Means

This pattern flags situations where a proposed or existing `CREATE INDEX` on a Hybrid Table is **not well-aligned with the actual workload**—for example, it duplicates an existing index, uses the wrong column order in a composite index, or adds write cost on an HT that serves mostly analytic/reporting queries rather than OLTP-style lookups.

---

## Why This Hurts Performance

Poorly chosen indexes on Hybrid Tables **add write amplification and quota pressure** without delivering corresponding read latency benefits. Each additional index increases HT write cost, fault-handling overhead, and the risk of HT request throttling, especially on high‑churn workloads.

When index columns don’t match equality predicates (or are redundant with existing composites), the optimizer often performs full or wide scans anyway. In these cases, you “pay” the ongoing HT index maintenance cost while still seeing slow queries, making the overall design strictly worse.

---

## Real-World Context

**Field Experience:**
- **Payer / Claims Platform**: Customer added multiple single‑column HT indexes on large claims tables based on schema intuition, not actual predicates → writes slowed down, HT throttling increased, query p95 stayed ~500–800 ms → rationalized to 2 composite indexes aligned with hot `WHERE`/`JOIN` predicates and dropped redundant ones → write latency stabilized and p95 improved to ~80–200 ms for operational lookups.
- **Digital Health / Patient Journeys**: Team added a new index on a low‑cardinality status column to “speed up reporting” on an HT → no measurable read benefit (queries were analytic, scanning many rows), but HT bulk loads and merges became unstable under load → moved reporting workloads to a standard columnar table and removed the HT index → HT write stability returned and reporting queries improved by ~5–10x on the columnar path.

**Common Pattern:**
Customers often propose `CREATE INDEX` on Hybrid Tables to “fix” slow queries **after** the fact, without checking whether:
- The indexed columns actually appear in equality predicates.
- A composite index already covers the same columns as a left‑most prefix.
- The query is truly OLTP‑style (point/range lookups) vs analytic (GROUP BY, large scans).
This leads to a growing set of HT indexes that increase write cost and throttling but don’t meaningfully reduce read latency.

---

## How to Fix It

### Step 1: Check for Redundancy and Predicate Alignment

1. Use the HT Query Analyzer / SnowVI to list existing indexes and hot predicates for the slow query.
2. Compare the proposed index columns to existing ones:
   - Is it a duplicate or left‑prefix of an existing composite?
   - Are the columns actually present in equality `WHERE`/`JOIN` predicates?

```sql
-- Example: existing composite index already covers MBR_KEY
-- Existing:
CREATE INDEX IDX_RX_CLAIM_MBR_KEY_EDLDT
  ON U01_MLLMN.MLLMN.MLLMN_RX_CLM_EXTRCT (MBR_KEY, EDL_LOAD_DTM);

-- Proposed (likely redundant):
CREATE INDEX IDX_RX_CLAIM_MBR_KEY
  ON U01_MLLMN.MLLMN.MLLMN_RX_CLM_EXTRCT (MBR_KEY);
```

If an existing index already has `(MBR_KEY, EDL_LOAD_DTM)` as its left‑most columns, a new `(MBR_KEY)` index is typically redundant.

### Step 2: Fix Composite Index Order for Hot Predicates

When the workload uses multiple equality predicates, ensure **left‑most index columns match the equality predicate order**, especially on HT:

```sql
-- Typical predicate pattern:
-- WHERE MBR_KEY = ? AND EDL_LOAD_DTM = ? AND CLM_STAT_CD = ?

-- Better composite index for this workload:
CREATE INDEX IDX_RX_CLAIM_MBR_EDL_STAT
  ON U01_MLLMN.MLLMN.MLLMN_RX_CLM_EXTRCT (MBR_KEY, EDL_LOAD_DTM, CLM_STAT_CD);
```

Avoid composites where the first column is *not* used in equality predicates for the hot path; those rarely get used efficiently by the optimizer.

### Step 3: Avoid Indexing HT for Analytic / Export Workloads

If the slow workload is clearly analytic (large scans, `GROUP BY`, `UNION ALL`, `ORDER BY` without `LIMIT`), focus on **moving that workload off HT**, not adding more HT indexes:

```sql
-- Example: route analytic pattern to a columnar reporting table
CREATE OR REPLACE TABLE MLLMN.MLLMN_RX_CLM_EXTRCT_RPT AS
SELECT *
FROM   U01_MLLMN.MLLMN.MLLMN_RX_CLM_EXTRCT;  -- initial backfill

-- Then run analytic/reporting queries against the columnar table:
SELECT EDL_LOAD_DTM, COUNT(*) AS RCNT
FROM   MLLMN.MLLMN_RX_CLM_EXTRCT_RPT
GROUP BY EDL_LOAD_DTM;
```

Keep Hybrid Tables focused on low‑latency OLTP‑style lookups; use standard tables/MVs/DTs for scans and aggregations.

### Step 4: Validate Impact and Clean Up Redundant Indexes

After adding or reordering an index, validate that it is actually used and improves the target workload:

```sql
-- 1) Verify plan and index usage via EXPLAIN / SnowVI
EXPLAIN
SELECT *
FROM   U01_MLLMN.MLLMN.MLLMN_RX_CLM_EXTRCT
WHERE  MBR_KEY = :1
  AND  EDL_LOAD_DTM = :2;

-- 2) Compare before/after p50/p95/p99 latencies using QUERY_HISTORY
SELECT
  DATE_TRUNC('hour', START_TIME) AS HOUR,
  MEDIAN(TOTAL_ELAPSED_TIME)     AS P50_MS
FROM TABLE(SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY())
WHERE QUERY_TEXT ILIKE '%MLLMN_RX_CLM_EXTRCT%'
  AND QUERY_PARAMETERIZED_HASH = :hash
GROUP BY 1
ORDER BY 1;
```

Once a new index is validated, **remove redundant or unused indexes** to reduce HT write cost:

```sql
DROP INDEX IF EXISTS IDX_RX_CLAIM_MBR_KEY
  ON U01_MLLMN.MLLMN.MLLMN_RX_CLM_EXTRCT;
```

---

## Expected Improvement

- **Query Time**: Operational point/range lookups often improve from **300–1000 ms → 50–200 ms** when an aligned composite index replaces a missing/misaligned index (or redundant ones are cleaned up).
- **Resource Usage**: HT write and throttling overhead typically **stabilize or drop** as redundant indexes are removed and only high‑value indexes remain.
- **Throughput**: For high‑QPS transactional workloads, we commonly see **2–5x** improvement in sustainable QPS once index design is aligned with predicates and unnecessary HT index maintenance is removed.

**Confidence:** High, based on multiple Hybrid Table customers across payer, retail, and digital health workloads where index rationalization + composite realignment materially improved both latency and HT stability.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- The query is **purely analytic/reporting** and runs against HT primarily for convenience; adding HT indexes here won’t fix the core workload/engine mismatch.
- The columns you want to index are **not present in equality predicates** in your hot path queries; indexing them will add write cost with little or no read benefit.
- The Hybrid Table is already under significant **HT request throttling or bulk‑load stress**, and you don’t have clear evidence that a new index will significantly reduce read latency on a critical path.

✅ **Do consider alternatives if:**
- The main issue is **workload fit** (analytic patterns on HT) → move or mirror the workload to **standard tables, MVs, or DTs** optimized for scans.
- The bottleneck is **no bound variables / plan cache misses** → fix parameterization first; index tuning is secondary if every query compilation dominates latency.
- Runtime analysis shows **client‑side dominated latency** (network/result transfer) → reduce payload or adjust client behavior before doing index design work.

---

## Related Findings

See also:
- `findings/NO_BOUND_VARIABLES.md` – Query uses literals instead of bound variables, causing plan cache misses and compilation overhead.
- `findings/NO_INDEX_FOR_HOT_PREDICATES.md` – Hot predicate columns are not indexed, leading to full or wide scans on HT.
- `patterns/ANALYTIC_WORKLOAD_ON_HT.md` – Analytic/reporting workloads running on Hybrid Tables instead of columnar structures.

---

## Additional Resources

- [Hybrid Table Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)
- [Hybrid Table Quick Starts](https://www.snowflake.com/en/developers/guides/?searchTerm=Hybrid)
- Internal Field Enablement: *Hybrid Tables – Index Design & Workload Fit* (SKE / enablement deck, internal link)

---

**Last Updated:** 2026-01-06  
**Contributor:** Adam Timm / AFE – Hybrid Tables  
**Field Validated:** Yes _(pattern observed and remediated at 3+ customers)_