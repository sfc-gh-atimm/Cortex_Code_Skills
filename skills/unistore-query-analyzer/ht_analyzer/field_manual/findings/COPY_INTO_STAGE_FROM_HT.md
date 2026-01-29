# COPY_INTO_STAGE_FROM_HT

## What This Means

This pattern flags queries that use `COPY INTO @stage` to export data **from Hybrid Tables** to CSV or other file formats. This typically indicates an analytic/reporting workload being served from operational (HT) tables, which is a workload/engine mismatch.

---

## Why This Hurts Performance

Hybrid Tables are optimized for **low-latency, transactional (OLTP) workloads**—point lookups, small range scans, and single-row DML. When you run `COPY INTO @stage` with `GROUP BY`, `UNION ALL`, or large scans against HT:

- **Latency suffers**: HT's row-store architecture is not optimized for analytic scans or aggregations.
- **Resource contention**: Large scans on HT can cause request throttling and compete with operational workloads.
- **Unnecessary hops**: Exporting to CSV adds file I/O and schema maintenance overhead; downstream consumers lose Snowflake optimizer benefits.

This pattern essentially uses HT as a reporting source, which is outside its design sweet spot.

---

## Real-World Context

**Field Experience:**

- **Payer / Claims Platform**: Customer ran nightly `COPY INTO @stage` from HT claims tables with `GROUP BY ALL` and `UNION ALL` to produce row-count CSVs for reconciliation. Queries took 15–30 minutes during batch window, caused HT throttling, and slowed operational inserts → moved aggregation logic to a **columnar reporting table** (standard table refreshed via TASK), `COPY INTO` from that → export dropped to 30–60 seconds, HT throttling eliminated.

- **Retail / Inventory**: Team exported daily inventory snapshots from HT to S3 stage for downstream BI tool → HT scans dominated warehouse, latency for point lookups degraded → created a **Materialized View (MV)** on the standard table replica of HT data for analytic consumers, removed direct HT export → operational HT p95 improved by ~40%, export latency improved by ~5x.

**Common Pattern:**

Customers often use HT as a "single source of truth" for both OLTP and reporting, then discover that analytic exports (CSV, Parquet, JSON) run slowly and compete with operational workloads. The fix is to **route analytic/reporting workloads off HT** to standard tables, MVs, or DTs.

---

## How to Fix It

### Step 1: Identify the Export Target and Workload

Review the `COPY INTO` statement to understand:
- What is being exported (row counts, full data, aggregations)?
- How often (hourly, daily, ad-hoc)?
- Who consumes the output (BI tool, downstream system, reconciliation)?

```sql
-- Example: current anti-pattern
COPY INTO @MY_STAGE/export.csv
FROM (
  SELECT EDL_LOAD_DTM, COUNT(*) AS RCNT
  FROM   MY_DATABASE.MY_SCHEMA.MY_HYBRID_TABLE
  GROUP BY ALL
)
FILE_FORMAT = (TYPE='CSV' COMPRESSION='GZIP')
SINGLE = TRUE;
```

### Step 2: Create a Columnar Reporting Table or MV

For analytic exports, create a standard (columnar) table or MV that can be scanned efficiently:

```sql
-- Option A: Standard reporting table (refreshed via TASK or STREAM/TASK)
CREATE OR REPLACE TABLE MY_SCHEMA.MY_HYBRID_TABLE_RPT AS
SELECT *
FROM   MY_DATABASE.MY_SCHEMA.MY_HYBRID_TABLE;

-- Option B: Materialized View (auto-refreshed, simpler maintenance)
CREATE MATERIALIZED VIEW MY_SCHEMA.MY_HYBRID_TABLE_MV AS
SELECT EDL_LOAD_DTM, COUNT(*) AS RCNT
FROM   MY_DATABASE.MY_SCHEMA.MY_HYBRID_TABLE
GROUP BY EDL_LOAD_DTM;
```

### Step 3: Redirect COPY INTO to the Reporting Structure

Point the export at the columnar table or MV instead of the HT:

```sql
-- Better: export from columnar reporting table
COPY INTO @MY_STAGE/export.csv
FROM (
  SELECT EDL_LOAD_DTM, RCNT
  FROM   MY_SCHEMA.MY_HYBRID_TABLE_MV
)
FILE_FORMAT = (TYPE='CSV' COMPRESSION='GZIP')
SINGLE = TRUE;
```

### Step 4: Validate Performance and Remove HT Export

Compare latency and resource usage before/after. Once validated, remove or deprecate the direct HT export path.

```sql
-- Validate: compare p50/p95 latency for the COPY INTO job
SELECT
  QUERY_TEXT,
  TOTAL_ELAPSED_TIME,
  BYTES_SCANNED,
  ROWS_PRODUCED
FROM TABLE(SNOWFLAKE.INFORMATION_SCHEMA.QUERY_HISTORY())
WHERE QUERY_TEXT ILIKE '%COPY INTO%MY_STAGE%'
ORDER BY START_TIME DESC
LIMIT 10;
```

---

## Expected Improvement

- **Export Latency**: Typically improves from **10–30 minutes → 30–120 seconds** when moving from HT scan to columnar table/MV scan.
- **HT Throughput**: Operational HT workloads often see **20–50% improvement** in p95 latency after removing large analytic scans.
- **Resource Usage**: Reduced HT request throttling and warehouse contention during export windows.

**Confidence:** High – pattern observed and remediated at 4+ customers across payer, retail, and digital health workloads.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**

- The `COPY INTO` is a **one-time migration or backfill**, not a recurring pattern. One-off exports may not justify creating additional structures.
- The Hybrid Table is **small** (< 1M rows) and the export is infrequent (weekly or less). In this case, the overhead may be acceptable.
- The export is **already fast** (< 30 seconds) and not causing HT throttling or operational impact.

✅ **Do consider alternatives if:**

- You need **real-time or streaming exports** → consider Snowpipe or Streams/Tasks to push data to downstream systems.
- The downstream consumer can **query Snowflake directly** → expose a VIEW or SECURE VIEW instead of exporting to files.
- The export is for **backup/archival** → consider using Snowflake's native time-travel or data retention instead of CSV exports.

---

## Related Findings

See also:
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` – Analytic/reporting queries running on Hybrid Tables (same root cause, different symptom).
- `findings/HT_REQUEST_THROTTLING.md` – Throttling caused by large scans or write contention on HT.
- `patterns/workload_separation.md` – Guidance on splitting OLTP and OLAP workloads.

---

## Additional Resources

- [Hybrid Table Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)
- [Materialized Views](https://docs.snowflake.com/en/user-guide/views-materialized)
- [Streams and Tasks](https://docs.snowflake.com/en/user-guide/streams-intro)
- Internal Field Enablement: *Hybrid Tables – Workload Separation Patterns* (SKE / enablement deck, internal link)

---

**Last Updated:** 2026-01-06  
**Contributor:** Adam Timm / AFE – Hybrid Tables  
**Field Validated:** Yes _(pattern observed and remediated at 4+ customers)_

