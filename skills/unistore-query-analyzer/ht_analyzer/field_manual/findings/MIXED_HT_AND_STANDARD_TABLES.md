# MIXED_HT_AND_STANDARD_TABLES

## What This Means

The **MIXED_HT_AND_STANDARD_TABLES** finding means the query joins **Hybrid Tables** with **standard/FDN tables** in the same SQL statement. In practice, an operational HT lookup is being combined directly with analytic tables, dimensions, or history tables in a single query.

---

## Why This Hurts Performance

Many of the optimizations that make Hybrid Tables fast for short, point-style queries are **disabled or less effective** when HTs are mixed with other table types:

- **Short-query scheduling paths may not apply** when the plan includes standard tables or large scans
- **HT-specific optimizations in the execution engine** are constrained when the engine has to produce results that combine HT with FDN/standard tables
- **The workload starts to look and behave like a mixed analytic workload** rather than a clean operational lookup

This often leads to **higher and more variable latency** than an HT-only lookup followed by separate analytic queries.

---

## Real-World Context

**Field Experience:**

- **Internal Apps**: APIs were written to join HT transaction/state tables with large analytic fact tables in a single query to "save a call" → HT lost its fast-path and latency became closer to a standard table join scenario
- **POC Tests**: Teams "proving out" HT by joining them directly into existing BI-style queries rather than testing the operational pattern alone → HT appeared not to meet latency targets, when in reality the query shape was no longer an HT-style workload

**Common Pattern:**
An HT table that is supposed to power a low-latency lookup API is wired directly into analytic joins and aggregations, so every lookup does more work than necessary.

---

## How to Fix It

### Step 1: Separate Operational and Analytic Paths

**Before (Mixed):**
```sql
-- One big query: HT + standard table join
SELECT
  C.CUSTOMER_ID,
  C.CURRENT_STATUS,
  C.TIER,
  F.TOTAL_SPEND,
  F.LAST_ORDER_DATE
FROM CUSTOMER_STATE_HT C
LEFT JOIN (
  SELECT
    CUSTOMER_ID,
    SUM(AMOUNT) AS TOTAL_SPEND,
    MAX(ORDER_DATE) AS LAST_ORDER_DATE
  FROM FACT_ORDERS
  WHERE ORDER_DATE >= DATEADD(day, -90, CURRENT_DATE())
  GROUP BY CUSTOMER_ID
) F ON C.CUSTOMER_ID = F.CUSTOMER_ID
WHERE C.CUSTOMER_ID = ?;
```

**Problem:**
- The query mixes a fast HT point lookup (`C.CUSTOMER_ID = ?`) with a large standard-table aggregation (90 days of FACT_ORDERS)
- HT fast-path optimizations don't fully apply
- Latency becomes dominated by the standard table scan

**After (Separated):**
```sql
-- Operational path: HT-only lookup (fast)
SELECT
  CUSTOMER_ID,
  CURRENT_STATUS,
  TIER
FROM CUSTOMER_STATE_HT
WHERE CUSTOMER_ID = ?;

-- Analytic path: standard tables (separate call or pre-materialized)
SELECT
  CUSTOMER_ID,
  SUM(AMOUNT) AS TOTAL_SPEND,
  MAX(ORDER_DATE) AS LAST_ORDER_DATE
FROM FACT_ORDERS
WHERE CUSTOMER_ID = ?
  AND ORDER_DATE >= DATEADD(day, -90, CURRENT_DATE())
GROUP BY CUSTOMER_ID;
```

**Benefits:**
- HT lookup runs in <50ms on XS warehouse
- Standard table aggregation can run on a separate, appropriately-sized warehouse
- You can cache/materialize the standard table results if they're used frequently

---

### Step 2: Use HT to Feed Analytic Structures

If you need combined data for reporting/analytics, use HT as a source that feeds standard tables or Dynamic Tables:

```sql
-- Nightly job to snapshot or aggregate HT data into standard tables
CREATE OR REPLACE TABLE CUSTOMER_STATE_SNAPSHOT AS
SELECT * FROM CUSTOMER_STATE_HT;

-- Or use a Dynamic Table for continuous refresh
CREATE OR REPLACE DYNAMIC TABLE CUSTOMER_SPEND_SUMMARY
  TARGET_LAG = '15 minutes'
  WAREHOUSE = ANALYTICS_WH
AS
SELECT
  C.CUSTOMER_ID,
  C.CURRENT_STATUS,
  C.TIER,
  SUM(F.AMOUNT) AS TOTAL_SPEND,
  MAX(F.ORDER_DATE) AS LAST_ORDER_DATE
FROM CUSTOMER_STATE_SNAPSHOT C  -- Standard table snapshot
LEFT JOIN FACT_ORDERS F
  ON C.CUSTOMER_ID = F.CUSTOMER_ID
WHERE F.ORDER_DATE >= DATEADD(day, -90, CURRENT_DATE())
GROUP BY C.CUSTOMER_ID, C.CURRENT_STATUS, C.TIER;
```

Then your BI tools query `CUSTOMER_SPEND_SUMMARY` (standard table) for reporting, while your operational API queries `CUSTOMER_STATE_HT` directly for low-latency lookups.

---

### Step 3: Only Join HT with Standard Tables When Necessary

If you **must** combine HT and standard tables in a single query:

- **Keep result sets small** (narrow predicates, LIMIT)
- **Avoid full history joins**; filter aggressively on HT keys/time
- **Treat it as an analytic query** and do not expect pure HT latency

Example:
```sql
-- Acceptable: tight join, small result set
SELECT
  C.CUSTOMER_ID,
  C.CURRENT_STATUS,
  O.ORDER_ID,
  O.ORDER_DATE
FROM CUSTOMER_STATE_HT C
INNER JOIN ORDERS_LAST_30_DAYS O  -- Pre-filtered standard table
  ON C.CUSTOMER_ID = O.CUSTOMER_ID
WHERE C.CUSTOMER_ID = ?
LIMIT 10;
```

---

## Talk Track for Customers

> **Customer:** "We want to join our HT customer state with order history in one query. Why is that a problem?"
>
> **You:** "It's not a problem for correctness, but it changes the performance profile. Here's what happens:
>
> - **HT-only lookup:** Point query on indexed column → <50ms p95
> - **HT + standard table join:** The engine has to accommodate both row-store (HT) and columnar (standard) access, and many HT fast-path optimizations don't apply → 200-500ms p95
>
> The recommended pattern is:
> 1. **Operational API path:** Query HT directly for real-time customer state (<50ms)
> 2. **Analytic/reporting path:** Use a Dynamic Table or materialized view that combines HT snapshots with order history, refreshed every 5-15 minutes
>
> That way:
> - Your API stays fast and predictable
> - Your BI tools get the combined view they need
> - Each workload runs on the right engine and warehouse size"

---

## When Mixed Queries Are Acceptable

There are cases where mixing HT and standard tables makes sense:

1. **Enrichment Lookups (Dimensions)**
   - HT + small dimension tables (e.g., country codes, product categories)
   - If the dimension is truly small (<1000 rows), the overhead is minimal

2. **Debugging / Admin Queries**
   - One-off investigations where latency isn't critical
   - It's fine to join HT with standard tables in Snowsight for troubleshooting

3. **Batch Processing (Not Latency-Sensitive)**
   - ETL jobs that combine HT with history for bulk transforms
   - If the query runs in a batch window and doesn't need <100ms latency, mixing is fine

**Rule of Thumb:**
- **Latency-sensitive operational paths:** Keep HT-only
- **Analytic/reporting paths:** Use standard tables (fed by HT snapshots/DTs)
- **Batch/admin paths:** Mix as needed, but don't expect operational latency

---

## Common Questions / Objections

### Q: Why is mixing Hybrid Tables and standard tables in one query a problem?

When you join HT with standard/FDN tables in the same statement, several HT fast-path optimizations either don't apply or are constrained:

- The execution plan needs to accommodate both row-store and columnar access patterns
- HT-specific scheduling and short-query optimizations become less effective when the rest of the plan is heavy

You can still do it, but the analyzer is warning that: *"This isn't a clean HT point lookup anymore; it's a hybrid OLTP/OLAP query."*

**Best Practices:**
1. Keep the operational lookup on HT as a separate, tight query
2. Use that result as input to analytic queries on standard tables (or materialize a snapshot into a standard table for joins)

---

## Impact

- **Latency Impact:** HIGH - Can increase p95 from <50ms (HT-only) to 200-500ms (mixed)
- **Predictability Impact:** HIGH - Mixed queries have more variable latency
- **Cost Impact:** MEDIUM - May require larger warehouses than pure HT workloads

---

## Estimated Improvement

**After Separation:**
- **Operational Path Latency:** 3-10x faster (50ms → <10ms for HT-only lookups)
- **Analytic Path Throughput:** 2-5x faster (standard tables optimized for scans/aggregations)
- **Overall Architecture:** Cleaner separation of concerns, easier to scale and optimize independently

---

## See Also

- [ANALYTIC_WORKLOAD_ON_HT](./ANALYTIC_WORKLOAD_ON_HT.md) - Related workload fit issue
- [HT Sweet Spot](../general/ht_sweet_spot.md) - When to use HT vs standard tables
- [WAREHOUSE_OVERSIZED_FOR_HT](./WAREHOUSE_OVERSIZED_FOR_HT.md) - Warehouse sizing for HT workloads

