# HT Bulk Load Failures (1079 / 201000 / 200017 / 200030)

## What This Means

Hybrid Table bulk loads (CTAS, COPY, INSERT…SELECT, MERGE) are failing with **bulk‑load–related errors** such as:

- **1079** – blob granule / FDB bulk read failures during Hybrid operations  
- **201000** – internal Hybrid Table failure often triggered by heavy index/constraint validation during large loads  
- **200017 (`EXCEED_MAX_TENANT_STORAGE_QUOTA`)** – Hybrid storage quota exceeded during bulk load  
- **200030** – "Worker aborting during bulk load operation due to peer worker failure" where the underlying cause is a bulk‑load failure (often 200017)  

These errors almost always show up when large MERGE/INSERT/CTAS/COPY workloads are bulk‑loading into Hybrid Tables and either:

- Use the **non‑optimized slow path** (row‑by‑row writes into FDB)  
- Or attempt to push a Hybrid database **over its storage or throughput quota** during a big backfill.

---

## Why This Hurts Performance

Large MERGE/INSERT/CTAS operations into Hybrid Tables that don't use the optimized empty‑table bulk‑load path behave like many single‑row operations. They:

- Generate huge transactional workloads against Data‑FDB and blob workers, touching many granules and index entries per transaction instead of using a streamlined bulk path.  
- Increase the chance of colliding with FDB throttling, recoveries, or S3 blips, which surfaces as 1079/201000 and heavy FDB throttling time.  
- Can drive Hybrid storage usage to or beyond the configured quota, which raises `EXCEED_MAX_TENANT_STORAGE_QUOTA` (200017) and aborts bulk loads.  
- In some cases, the customer sees only a generic execution error (200030 "Worker aborting during bulk load operation due to peer worker failure") even though the root cause is quota or bulk‑load failure.

The net effect is **unstable, slow, and expensive backfills** that may fail repeatedly, even on large warehouses.

---

## Real-World Context

**Field Experience:**

- **Health payer (Hybrid Table claims extract backfill)**: A 6‑month MERGE into a non‑empty Hybrid Table repeatedly failed with 201000/1079 as index validation and FDB load spiked → redesigned as CTAS into an empty HT followed by a table swap, with ongoing changes applied via small incremental MERGEs → eliminated recurring 1079/201000 failures and significantly reduced Data‑FDB and compaction load.

- **Digital analytics / feature store**: ETL job doing INSERT…SELECT from a 30GB standard table into a Hybrid Table started failing with 200030 "worker aborting during bulk load operation due to peer worker failure." XP logs showed root cause `EXCEED_MAX_TENANT_STORAGE_QUOTA` (200017) during bulk load → raised storage quota to an appropriate level, moved historical data to standard tables, and switched to CTAS + swap for big loads → bulk loads now complete without quota failures.

**Common Pattern:**

You see this when customers:

- Run **infrequent, very large backfills** (months of data) into Hybrid Tables via single MERGE or INSERT…SELECT statements.  
- Try to bulk‑load historical data into the **same Hybrid database** that's already close to its per‑db HT storage quota.  
- Use multiple warehouses or jobs concurrently into the same HT/database, compounding FDB and quota pressure during the load.

---

## How to Fix It

### Step 1: Prefer CTAS into an empty Hybrid Table for big historical loads

For initial backfills or large historical data loads, use the optimized empty‑table bulk‑load path instead of a giant MERGE into a populated table.

```sql
-- 1. Create a new empty Hybrid Table for the extract
CREATE OR REPLACE HYBRID TABLE MY_SCHEMA.MY_TABLE_NEW AS
SELECT
    col1,
    col2,
    col3,
    -- ... other columns
FROM MY_SCHEMA.SOURCE_TABLE
WHERE created_date >= '2022-05-31'
  AND created_date <= '2022-11-30';
```

Then do a controlled swap:

```sql
-- 2. Swap tables (pattern – adjust names as needed)
ALTER TABLE MY_SCHEMA.MY_TABLE RENAME TO MY_TABLE_OLD;
ALTER TABLE MY_SCHEMA.MY_TABLE_NEW RENAME TO MY_TABLE;

-- 3. Recreate constraints and indexes on the new HT as needed
```

This uses the **optimized bulk‑load path** for CTAS into an empty HT and avoids row‑by‑row FDB transactional work.

> **Quota angle (200017):** If this CTAS+swap would push the Hybrid database close to its storage quota, work with the customer to either (a) purge/archive older Hybrid data to standard tables first or (b) adjust the DB's Hybrid storage quota (within safe limits) before running the backfill.

---

### Step 2: Chunk and sequence MERGE operations when the HT is not empty

If you cannot recreate the table via CTAS (e.g., strict online SLA, complex constraints) and the HT already has data:

```sql
-- Example: break a 6‑month MERGE into monthly batches
MERGE INTO MY_SCHEMA.MY_TABLE TGT
USING (
    SELECT *
    FROM MY_SCHEMA.SOURCE_TABLE
    WHERE created_date >= '2022-05-31'
      AND created_date <  '2022-07-01'
) SRC
ON (TGT.pk_col = SRC.pk_col)
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT (...);

-- Repeat per time slice (monthly/weekly/daily), running each MERGE sequentially
```

Operational guidance:

- **One bulk MERGE at a time per Hybrid database.**  
- Use a **single, reasonably sized warehouse**, not multiple concurrent warehouses hammering the same HT.  
- Prefer **fewer, larger sequential MERGEs** over many small concurrent ones to avoid FDB thrash and quota spikes.

---

### Step 3: Use staging + deferred MERGE patterns

Keep heavy historical processing in standard tables; treat Hybrid Tables as the **operational delta store**.

```sql
-- 1. Stage data into a standard table (existing or new)
COPY INTO STAGING_TABLE
FROM @source_stage/files...
FILE_FORMAT = (TYPE = CSV ...);

-- 2. Periodically MERGE only the delta into the Hybrid Table
MERGE INTO MY_HYBRID_TABLE TGT
USING (
    SELECT *
    FROM STAGING_TABLE
    WHERE load_ts >  :last_loaded_ts
      AND load_ts <= :this_batch_ts
) SRC
ON (TGT.pk_col = SRC.pk_col)
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT (...);
```

Keep each batch **small and frequent** (e.g., hourly/daily) so:

- MERGE statements stay short and low‑volume.  
- The Hybrid KV/index layer stays focused on incremental operational data instead of multi‑month history.

---

### Step 4: Minimize index work during backfills (where allowed)

Secondary indexes amplify write volume and constraint validation during big loads, which is a common trigger for 201000/1079.

```sql
-- 1. Drop non‑critical secondary indexes before the backfill
ALTER TABLE MY_HYBRID_TABLE DROP INDEX IF EXISTS IDX_NONCRITICAL_1;
ALTER TABLE MY_HYBRID_TABLE DROP INDEX IF EXISTS IDX_NONCRITICAL_2;

-- 2. Run CTAS / MERGE backfill (Steps 1–3)

-- 3. Recreate indexes after the backfill completes
ALTER TABLE MY_HYBRID_TABLE ADD INDEX IDX_NONCRITICAL_1 (col1, col2);
ALTER TABLE MY_HYBRID_TABLE ADD INDEX IDX_NONCRITICAL_2 (col3);
```

Only keep "must‑have" indexes during a large load; add the rest once the data is in place.

---

### Step 5: Address storage and throughput quotas explicitly (200017 / 1079)

When errors or logs show **`EXCEED_MAX_TENANT_STORAGE_QUOTA` (200017)** or HT FDB throttling during bulk loads:

1. **Confirm if the load truly needs that much hot data in HT**  
   - Move older years or "cold" data to standard tables before the bulk load.  
   - Consider splitting data across multiple Hybrid databases (observing per‑db quota).

2. **Check current Hybrid storage & throughput quotas**  
   - Use internal dashboards / Snowhouse views (e.g., `HYBRID_TABLE_USAGE_HISTORY`, EFDB quota views) to inspect current quota vs usage.

3. **Adjust quotas where safe and justified**  
   - Follow the Hybrid quota runbook to change storage and/or throughput quota for the relevant capacity group / database, within documented max limits (e.g., up to 5 TB per DB in many clusters).

Only **after** right‑sizing the data model and quotas should you retry the bulk load.

---

## Expected Improvement

- **Stability**:  
  - 1079/201000/200017/200030 errors for bulk loads should disappear once:
    - CTAS into empty HTs is used for big loads, **or**  
    - MERGE/INSERT batches are chunked and sequenced and  
    - Storage/throughput quotas are set appropriately.

- **Throughput & Predictability**:  
  - CTAS into empty HTs typically runs **4–10x faster** than equivalent slow‑path bulk DML and avoids expensive compaction work.  
  - Chunked & staged MERGE patterns significantly reduce FDB throttling time and make runtimes more predictable.

**Confidence:** High – these patterns match internal design docs and multiple customer remediations for 1079/201000/200017/200030.

---

## When NOT to Apply This Fix

**Don't use this fix if:**

- The failure is clearly due to **business logic or data correctness** (e.g., PK/FK violations, NOT NULL constraint errors), not bulk‑load volume or quotas. Fix the data/constraints first.  
- The workload is **small and purely transactional** (tiny batches < 10k rows per statement) and errors are rare or correlated only with FDB incidents/outages.

**Do consider alternatives if:**

- The workload is mainly **analytic** (large scans, aggregations, joins). In that case, move those workloads to **standard tables, MVs, or Dynamic Tables** instead of Hybrid Tables.  
- The failure is dominated by **HT throttling** due to many mixed workloads in the same database. Then you must also:
  - Increase or isolate quotas for the HT database.  
  - Move heavy analytic workloads off the HT DB.  
  - Move problematic bulk jobs to off‑peak windows.

---

## Related Findings

See also:

- `findings/SLOW_CTAS_LOAD.md` – CTAS bulk load throughput and warehouse sizing patterns.  
- `findings/BULK_DML_SHOULD_BE_CTAS.md` – When large MERGE/INSERT/UPDATE should be CTAS + swap instead of row‑by‑row DML.  
- `findings/HT_REQUEST_THROTTLING.md` – Handling HT request quota and throttling issues that often coexist with 1079/201000/200017.

---

## Additional Resources

- [Snowflake Docs – Hybrid Table Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)  
- [Snowflake Docs – Hybrid Table Quotas and Limits](https://docs.snowflake.com/)  
- Internal:
  - *Troubleshooting Hybrid Quotas and DB Limit* (Global Support wiki).  
  - *Troubleshooting Hybrid Tables Billing* and related dashboards for Hybrid requests/storage.  
  - *Hybrid Tables Direct Bulk Loading* design doc (Bulk Load V1/V2/V3/V4 roadmap).

---

**Last updated:** 2025‑12‑23  
**Contributor:** Adam Timm (Solution Engineering)  
**Field Validated:** Yes _(observed at multiple customers and internal workloads)_

