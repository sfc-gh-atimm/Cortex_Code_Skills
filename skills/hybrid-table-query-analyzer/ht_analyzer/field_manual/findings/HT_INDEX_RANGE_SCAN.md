# HT_INDEX_RANGE_SCAN

## What This Means

SnowVI's plan shows an HT index operator, but the index scan reads far more rows than the query returns (e.g., >10,000 rows scanned and >50× more rows scanned than produced). The index is effectively being used as a wide range scan, not a point or narrow lookup.

---

## Why This Hurts Performance

Wide range scans on HT increase FDB I/O, CPU, and memory, eroding the benefit of the KV row store. For reporting and analytic patterns, HT index scans can be much slower and more expensive than equivalent operations on a standard columnar table or materialized view.

---

## Real-World Context

**Field Experience:**
- **B2C Marketplace**: "Recent orders" API used a date range filter on HT with an index on `(TENANT_ID, ORDER_ID)` → index scan read millions of rows per tenant per day → moved reporting workload to a columnar history table with clustering → daily reporting latency fell from ~12s to <1s.

- **FinTech Ledger**: Balance report queries ran with HT index range scans over months of data → created a daily summary table and rewrote report to hit the summary → p95 went from ~8s to 300–500ms.

**Common Pattern:**
A query was originally intended as a point lookup on HT but gets repurposed for broader reporting (wide date ranges, no LIMIT). Indexes still appear in plan, but scan volumes behave like a full or large partial table scan.

---

## How to Fix It

### Step 1: Confirm range-scan behavior from SnowVI

The SnowVI plan data shows estimated/actual rows scanned by HT index operators. Check the "Hybrid Table Execution Plan" section in the Full Report to see row counts vs rows returned.

### Step 2: Separate OLTP and reporting paths

```sql
-- OLTP path: keep point/small-range lookups on HT
SELECT *
FROM ORDERS_HT
WHERE TENANT_ID = :tenant_id
  AND ORDER_ID  = :order_id;

-- Reporting path: move to columnar or MV
CREATE OR REPLACE TABLE ORDERS_HISTORY_CL AS
SELECT *
FROM ORDERS_HT
WHERE CREATED_AT < DATEADD('day', -7, CURRENT_DATE());

-- Reporting query now hits columnar table
SELECT TENANT_ID, COUNT(*), SUM(AMOUNT)
FROM ORDERS_HISTORY_CL
WHERE CREATED_AT BETWEEN :start_dt AND :end_dt
GROUP BY TENANT_ID;
```

### Step 3: Add summary/MV for heavy aggregations

```sql
CREATE OR REPLACE MATERIALIZED VIEW MV_DAILY_ORDER_COUNTS AS
SELECT TENANT_ID, DATE(CREATED_AT) AS ORDER_DATE, COUNT(*) AS CNT
FROM ORDERS_HISTORY_CL
GROUP BY TENANT_ID, DATE(CREATED_AT);
```

---

## Expected Improvement

- **Query Time**: 3–15s range-scan HT queries → 200–800ms on columnar/MV.
- **Resource Usage**: FDB I/O and HT storage pressure reduced significantly; analytic work shifts to cheaper columnar paths.
- **Throughput**: HT warehouse headroom increases because OLTP path is no longer competing with heavy scans.

**Confidence:** High for clear OLTP vs reporting separation patterns.

---

## When NOT to Apply This Fix

⚠️ **Don't do this if:**
- The workload is already small and local (few rows scanned, narrow ranges).
- You simply need a tighter WHERE clause or proper index, not a new data flow.

✅ **Do consider alternatives if:**
- You cannot tolerate additional data movement: use a small, well-indexed standard table in the same database instead of HT.
- The workload is almost entirely analytic: consider keeping all of it on standard tables and MVs, and avoid HT for that dataset.

---

## Related Findings

See also:
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` - Mixed/analytic workloads placed on Hybrid Tables.
- `findings/HT_ANALYTIC_STORE_SCAN.md` - Plan shows analytic/object-store path for HT.
- `findings/HT_INDEXES_NOT_USED_PLAN.md` - Index expected but not used at all.

---

## Additional Resources

- [Hybrid Table Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)

---

**Last Updated:** 2025-01-10  
**Contributor:** Transactional Workload / HT AFE Team  
**Field Validated:** Yes

