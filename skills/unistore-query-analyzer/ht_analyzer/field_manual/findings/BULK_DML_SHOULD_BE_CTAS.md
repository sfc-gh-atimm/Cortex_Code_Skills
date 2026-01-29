# BULK_DML_SHOULD_BE_CTAS

## What This Means

The **BULK_DML_SHOULD_BE_CTAS** finding means a single `INSERT`, `MERGE`, or `UPDATE` statement modified a very large number of rows and took long enough that it looks more like a **full table rewrite** than a normal transactional operation. In these cases, a `CREATE TABLE AS SELECT` (CTAS) into a new table plus an atomic swap is usually a better pattern.

---

## Why This Hurts Performance

Row-by-row or large-set DML against millions of rows:

- Increases write amplification and logging overhead compared to CTAS.
- Can lock or stress the target table for longer than necessary.
- Often competes with other workloads on the same warehouse, especially if it runs in peak hours.

For large structural changes or backfills, **CTAS + swap** is generally:

- Faster (bulk path).
- Easier to reason about (old vs new version).
- Less disruptive to concurrent workloads.

---

## Real-World Context

**Field Experience:**
- **Backfill MERGEs**: A team used `MERGE` to update tens of millions of rows in a wide table to correct historical data → multi-hour jobs, contention, and frustrated users → rewriting the pattern to `CTAS` into a new table and then swapping the table name cut wall-clock times significantly and reduced operational risk.

- **Large INSERT…SELECT**: Periodic "rebuild" of a derived table using `INSERT INTO target SELECT ... FROM source` over the full history → repeated heavy DML on the same table → switching to `CREATE TABLE AS SELECT` (CTAS) into a fresh table plus a swap removed the need for repeated DML and simplified maintenance.

**Common Pattern:**
DML is chosen by default because it seems "simple," but the number of rows and runtime make it clear the statement is acting like a **batch rebuild** rather than a small transactional update.

---

## How to Fix It

### Step 1: Confirm It's Bulk DML

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Confirm bulk DML
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT
  UUID,
  QUERY_TEXT,
  QUERY_TYPE,
  ROWS_INSERTED,
  ROWS_UPDATED,
  TOTAL_ELAPSED_TIME / 1000.0 AS duration_s
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE UUID = '{{QUERY_UUID}}';
```

#### 👤 For Customer Use

```sql
-- Customer: Confirm bulk DML
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT
  QUERY_ID,
  QUERY_TEXT,
  QUERY_TYPE,
  ROWS_INSERTED,
  ROWS_UPDATED,
  TOTAL_ELAPSED_TIME / 1000.0 AS duration_s
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_ID = '{{QUERY_UUID}}';
```

*Heuristics for BULK_DML_SHOULD_BE_CTAS:*

- `QUERY_TYPE` in (`INSERT`, `MERGE`, `UPDATE`).
- `ROWS_INSERTED + ROWS_UPDATED` is in the millions.
- `duration_s` is high enough that the statement is clearly not a small, short-lived update.

### Step 2: Rewrite as CTAS Into a New Table

**Before: Large INSERT…SELECT**

```sql
-- Before: bulk DML into existing table
INSERT INTO TARGET_TABLE
SELECT ...
FROM SOURCE_TABLE
WHERE <complex predicate>;
```

**After: CTAS + swap pattern**

```sql
-- Step 1: create a new table with the desired contents
CREATE OR REPLACE TABLE TARGET_TABLE_NEW AS
SELECT ...
FROM SOURCE_TABLE
WHERE <same predicate>;

-- Step 2: (optional) validate TARGET_TABLE_NEW (row counts, checks)
SELECT COUNT(*) FROM TARGET_TABLE_NEW;

-- Step 3: swap in the new table atomically
ALTER TABLE TARGET_TABLE SWAP WITH TARGET_TABLE_NEW;
```

### Step 3: MERGE to CTAS Pattern

**Before: Large MERGE**

```sql
MERGE INTO TARGET_TABLE T
USING SOURCE_TABLE S
  ON T.ID = S.ID
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT (...);
```

**After: CTAS that materializes the "final state"**

```sql
-- Build the desired final state
CREATE OR REPLACE TABLE TARGET_TABLE_NEW AS
SELECT
  COALESCE(S.ID, T.ID)           AS ID,
  -- choose values from S or T as appropriate
  ...
FROM TARGET_TABLE T
FULL OUTER JOIN SOURCE_TABLE S
  ON T.ID = S.ID;

-- Validate if needed, then swap
ALTER TABLE TARGET_TABLE SWAP WITH TARGET_TABLE_NEW;
```

> Note: You lose row-level "who changed what" semantics in CTAS, but gain simplicity and high throughput for large structural changes.

---

## Expected Improvement

- **Query Time**: [Before] → [After] (e.g., multi-hour MERGE → significantly shorter CTAS + swap).
- **Operational Risk**: [Before] → [After] (shorter lock/impact window; more predictable rollback via old table).
- **Maintainability**: [Before] → [After] (clear "old vs new" separation; easier debugging of data issues).

**Confidence:** High when:

- The DML touches a large share of the table.
- The operation is periodic / batch-like (e.g., daily or weekly rebuilds).

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**

- The DML is **truly transactional**, updating a small subset of rows frequently (e.g., user profile changes on a live app).
- You rely on statement-level auditing or exact row-level change history for compliance that's difficult to reconstruct from CTAS flows.

✅ **Do consider alternatives if:**

- You only need to update a **small partition/window** (e.g., last N days) and can restrict DML with tight predicates.
- You need partial CTAS + incremental DML: bulk rebuild a large portion via CTAS, then apply small targeted MERGEs for edge cases.

---

## Related Findings

See also:

- `findings/SLOW_CTAS_LOAD.md` – CTAS operations that are themselves slow or poorly configured.
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` – analytics-heavy workloads that could be offloaded from operational tables.

---

## Additional Resources

- Snowflake docs: CTAS, `ALTER TABLE ... SWAP WITH`, and bulk load patterns.
- Internal: POC performance testing guides discussing CTAS vs MERGE trade-offs.

---

**Last Updated:** 2025-12-06  
**Contributor:** AFE / SE Field Manual  
**Field Validated:** Yes

