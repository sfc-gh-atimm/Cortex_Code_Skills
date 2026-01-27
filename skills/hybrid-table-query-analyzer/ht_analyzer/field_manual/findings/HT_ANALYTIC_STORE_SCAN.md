# HT_ANALYTIC_STORE_SCAN

## What This Means

SnowVI's plan shows that a Hybrid Table is being read via the analytic/object-store copy instead of the KV row-store path. For this query, the Hybrid Table behaves like a standard analytic table scan.

---

## Why This Hurts Performance

When the analytic path is used, you lose HT's low-latency, row-store benefits but keep the operational complexity and quota overhead of maintaining both stores. Analytic scans over large data sets are usually more efficient and cheaper on standard columnar tables or materialized views designed for that purpose.

---

## Real-World Context

**Field Experience:**
- **Subscription Analytics**: Customer kept all historical subscription events in HT; analytic queries hit the analytic copy, generating high storage and compute costs → moved history into a standard FACT table with clustering by date → long-running analytic queries went from minutes to seconds, and HT storage usage dropped.

- **Gaming Telemetry**: Session events stored in HT for "live" gameplay lookups, but BI dashboards read months of history via analytic copy → carved out a 7-day "hot" window in HT and moved older data to columnar → improved dashboard p95 and reduced HT quota pressure.

**Common Pattern:**
Teams default to HT "for everything" (operational + analytics). The optimizer correctly routes analytic patterns to the analytic store, but that's a sign the data model is mixing OLTP and OLAP concerns in the same HT.

---

## How to Fix It

### Step 1: Confirm analytic-store reads from SnowVI

The SnowVI plan data shows storage source for each operator. Check the "Hybrid Table Execution Plan" section in the Full Report for "Storage Path" = ANALYTIC.

### Step 2: Split hot HT vs analytic history

```sql
-- Keep recent/hot data on HT
CREATE OR REPLACE TABLE EVENTS_HT AS
SELECT *
FROM RAW_EVENTS
WHERE EVENT_TIME >= DATEADD('day', -7, CURRENT_DATE());

-- Move older data to columnar
CREATE OR REPLACE TABLE EVENTS_HISTORY AS
SELECT *
FROM RAW_EVENTS
WHERE EVENT_TIME < DATEADD('day', -7, CURRENT_DATE());
```

### Step 3: Point analytic queries at columnar/MVs

```sql
-- BI / reporting should use columnar
SELECT USER_ID, COUNT(*)
FROM EVENTS_HISTORY
WHERE EVENT_TIME BETWEEN :start_dt AND :end_dt
GROUP BY USER_ID;
```

---

## Expected Improvement

- **Query Time**: Analytic scans on HT analytic copy → moved to columnar; typical 2–10× speedup for wide scans.
- **Resource Usage**: HT quota usage and FDB I/O decrease as analytic traffic moves off HT.
- **Throughput**: More headroom on HT for truly transactional workloads.

**Confidence:** High when analytic traffic clearly dominates and is currently hitting HT.

---

## When NOT to Apply This Fix

⚠️ **Don't apply if:**
- The dataset is tiny and there's no meaningful analytic workload.
- You only see analytic-path reads in rare maintenance or diagnostic queries.

✅ **Do consider alternatives if:**
- You must keep a single table but still want OLTP + analytics → consider layering MVs or Dynamic Tables on top of a standard fact table instead of HT.
- Your workload is almost entirely analytic → skip HT altogether for that dataset.

---

## Related Findings

See also:
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` - When overall workload fit is analytic on HT.
- `findings/HT_INDEX_RANGE_SCAN.md` - Wide range scans via HT indexes.
- `findings/MIXED_HT_AND_STANDARD_TABLES.md` - Queries mixing HT and standard tables.

---

## Additional Resources

- [Hybrid Table Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)

---

**Last Updated:** 2025-01-10  
**Contributor:** Transactional Workload / HT AFE Team  
**Field Validated:** Yes

