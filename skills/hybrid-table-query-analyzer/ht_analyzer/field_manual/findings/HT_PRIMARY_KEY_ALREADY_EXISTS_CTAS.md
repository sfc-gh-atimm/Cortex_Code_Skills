# HT_PRIMARY_KEY_ALREADY_EXISTS_CTAS

## What This Means

When running a `CREATE OR REPLACE HYBRID TABLE ... AS SELECT ...` statement with a `PRIMARY KEY` definition, the error:

> `200001 (22000): A primary key already exists.`

almost always means that **the result set of the SELECT contains duplicate values in the declared PRIMARY KEY column(s)**. The wording sounds like a duplicate constraint definition, but for Hybrid Tables this is typically a **primary-key uniqueness violation on the data being loaded**, not a schema-level conflict.

---

## Why This Hurts Performance

This is primarily a **correctness and reliability** issue, but it has performance implications:

- The CTAS repeatedly **fails and retries**, consuming warehouse time and HT resources without successfully materializing the table.
- Teams sometimes attempt "fixes" like changing warehouses or toggling features, which doesn't address the root cause and wastes engineering cycles.
- Workarounds like adding `LIMIT 1` or other arbitrary filters can hide the real data quality problem, leading to **partial, incorrect datasets** that break downstream pipelines.

---

## Real-World Context

**Field Experience:**
- **Utility / Metering Data**: Customer created a Hybrid Table via CTAS from a 2B-row staging table and consistently hit `200001: A primary key already exists.` Investigation found ~147M duplicate combinations of `(MEASR_COMP_ID, MSRMT_DTTM)` that violated the declared PK. → Introduced a deduplication step in staging + re-evaluated PK choice → CTAS succeeded and HT loads became stable.
- **SaaS Recommendations Engine (dbt)**: dbt job `CREATE OR REPLACE HYBRID TABLE ... PRIMARY KEY (user_id, model)` started failing with `200001` after a data change. Root cause: ~40K duplicate `(user_id, model)` pairs in the source query. → Added `ROW_NUMBER()`-based dedupe in the model and tightened upstream uniqueness guarantees → PK constraint honored; job returned to normal operations.

**Common Pattern:**
Customers interpret "A primary key already exists" as "the table already has a PK defined" or "I can't add this constraint", when in reality the **incoming data violates the PK uniqueness requirement**. In CTAS workflows, especially with large staging tables or UNIONed queries, duplicates in the intended PK columns are common and must be identified and cleaned up before the Hybrid Table can be created.

---

## How to Fix It

### Step 1: Identify the Intended PK and Source Query

Locate the failing CTAS:

```sql
CREATE OR REPLACE HYBRID TABLE TARGET_DB.SCHEMA.MY_HT (
  PK_COL_1   <type>,
  PK_COL_2   <type>,
  -- ...
  PRIMARY KEY (PK_COL_1, PK_COL_2)
)
AS
SELECT ...
FROM   SOURCE_DB.SCHEMA.SOURCE_TABLE_OR_VIEW
-- possibly with UNION/UNION ALL, joins, filters, etc.
;
```

Confirm exactly which columns are in the `PRIMARY KEY (...)` clause.

### Step 2: Check for Duplicate PK Combinations in the Source

Run a grouped-count query over the **source query**, not just a base table if the CTAS uses joins/UNIONs:

```sql
WITH src AS (
    -- Use the same SELECT as in CTAS, but WITHOUT the CREATE OR REPLACE
    SELECT
        PK_COL_1,
        PK_COL_2,
        -- other columns...
    FROM SOURCE_DB.SCHEMA.SOURCE_TABLE_OR_VIEW
    -- same joins/filters/UNIONs used in CTAS
)
SELECT
    PK_COL_1,
    PK_COL_2,
    COUNT(*) AS CNT
FROM src
GROUP BY PK_COL_1, PK_COL_2
HAVING COUNT(*) > 1
ORDER BY CNT DESC;
```

If this returns any rows, the CTAS will fail: those PK combinations are not unique.

### Step 3: Add a Dedupe Step or Redefine the PK

**Option A – Deduplicate in the CTAS source:**

Use `ROW_NUMBER()` to pick a single representative row per PK combination:

```sql
CREATE OR REPLACE HYBRID TABLE TARGET_DB.SCHEMA.MY_HT (
  PK_COL_1 <type>,
  PK_COL_2 <type>,
  -- other columns...
  PRIMARY KEY (PK_COL_1, PK_COL_2)
)
AS
WITH src AS (
    SELECT
        t.*,
        ROW_NUMBER() OVER (
            PARTITION BY PK_COL_1, PK_COL_2
            ORDER BY <your_preferred_ordering>
        ) AS rn
    FROM SOURCE_DB.SCHEMA.SOURCE_TABLE_OR_VIEW t
)
SELECT
    *
EXCEPT (rn)
FROM src
WHERE rn = 1;
```

**Option B – Stage and clean, then CTAS from the cleaned stage:**

```sql
CREATE OR REPLACE TABLE STAGING_DB.SCHEMA.MY_HT_DEDUPED AS
SELECT
    *
FROM (
    SELECT
        t.*,
        ROW_NUMBER() OVER (
            PARTITION BY PK_COL_1, PK_COL_2
            ORDER BY <your_preferred_ordering>
        ) AS rn
    FROM SOURCE_DB.SCHEMA.SOURCE_TABLE_OR_VIEW t
)
WHERE rn = 1;

CREATE OR REPLACE HYBRID TABLE TARGET_DB.SCHEMA.MY_HT (
  PK_COL_1 <type>,
  PK_COL_2 <type>,
  PRIMARY KEY (PK_COL_1, PK_COL_2)
)
AS
SELECT * FROM STAGING_DB.SCHEMA.MY_HT_DEDUPED;
```

**Option C – Revisit the PK definition:**

If duplicates are **expected** (e.g., same key at different timestamps, multiple recommendations per user), your PK design might be incorrect:

- Add additional columns to the PK (e.g., include timestamp or model identifier).
- Choose a different natural key that matches business uniqueness.
- Use a surrogate key if no natural key is truly unique, and enforce business uniqueness via other constraints or checks.

### Step 4: Understand Why `LIMIT 1` "Works"

You may see CTAS succeed when you temporarily add `LIMIT 1`:

```sql
CREATE OR REPLACE HYBRID TABLE TARGET_DB.SCHEMA.MY_HT (
  PK_COL_1 <type>,
  PK_COL_2 <type>,
  PRIMARY KEY (PK_COL_1, PK_COL_2)
)
AS
SELECT ...
FROM ...
LIMIT 1;
```

This "works" because:

- The PK is checked only on the **rows actually returned** by the SELECT.
- With `LIMIT 1`, you never surface multiple rows with the same PK value, so the constraint is trivially satisfied.
- The data problem (duplicates in the wider dataset) is still there; as soon as you remove `LIMIT 1` or try to load more rows, the error will return.

Use `LIMIT 1` only as a quick sanity check—not as a solution.

---

## Expected Improvement

- **Reliability**: CTAS operations go from "always failing with 200001" to **consistently succeeding**, unblocking HT adoption and downstream pipelines.
- **Data Quality**: Deduplication and/or corrected PK design ensure that Hybrid Tables correctly enforce business uniqueness invariants, reducing subtle downstream bugs.
- **Operational Efficiency**: Reduced need for trial-and-error reruns, smaller support/Jira footprint, and clearer handoff between Support, SE, and customer teams.

**Confidence:** High, based on multiple support cases and internal investigations where the root cause was confirmed to be **duplicate PK values in the CTAS source** (rather than a DDL bug).

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- The error is coming from a **pure DDL operation without data** (e.g., `ALTER TABLE ... ADD PRIMARY KEY` on an already-constrained table). In that case, investigate constraint definitions rather than data duplicates.
- The workload truly requires **non-unique semantics** on the nominated columns (e.g., legitimate multiple recommendations per `(user_id, model)`); in that case, forcing uniqueness by arbitrarily dropping rows may break business logic.
- The error is actually due to a **different constraint or error code** (e.g., non-HT engine behavior or object-exists error) being misread as PK duplication.

✅ **Do consider alternatives if:**
- The data model is fundamentally not relational/OLTP and you're trying to force a PK where the domain is inherently many-to-many. Consider:
  - Different PK columns (include timestamp or sequence),
  - A surrogate key plus secondary uniqueness checks,
  - Or moving the workload to a standard/columnar table where you enforce uniqueness differently.
- The cost of deduplication (2B+ row staging tables, complex business rules for which row to keep) is high; you may want a **dedicated data quality pipeline** or upstream changes in the data source.

---

## Related Findings

See also:
- `findings/HT_BULK_LOAD_FAILURE_200001.md` – Hybrid Table bulk loads/CTAS failing with PK constraint violations at scale.
- `patterns/HT_PK_MODELING_BEST_PRACTICES.md` – Choosing appropriate primary keys for Hybrid Tables based on workload and business semantics.

---

## Additional Resources

- [Hybrid Tables Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)
- [Hybrid Tables Overview](https://docs.snowflake.com/en/user-guide/tables-hybrid-overview)
- Internal Cases/Threads:
  - SNOW-1662352 – CTAS to Hybrid Table failing with `A primary key already exists` due to ~147M duplicate PK combinations.
  - SFDC Case *"Duplicate Primary Key Errors when create or replace hybrid tables"* – dbt workflow failing on duplicate `(user_id, model)` keys.
  - `#unistore-workload` Slack thread – CTAS error reproduced in demo due to duplicated PK row in source.

---

**Last Updated:** 2026-01-07  
**Contributor:** Adam Timm / AFE – Hybrid Tables  
**Field Validated:** Yes _(pattern confirmed across multiple Jiras, support cases, and internal Slack threads)_

