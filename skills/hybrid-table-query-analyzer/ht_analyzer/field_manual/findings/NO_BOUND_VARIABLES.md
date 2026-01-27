# NO_BOUND_VARIABLES

## What This Means

The **NO_BOUND_VARIABLES** finding means the query uses literal values directly in the SQL string instead of prepared statements with bound parameters (e.g., `?`, `$1`, `:id`). As a result, each new value produces a different query text and prevents effective plan cache reuse.

---

## Why This Hurts Performance

Without parameter binding, Snowflake must compile a new query plan for every distinct literal combination, even when the logical query pattern is identical. For Hybrid Tables, compilation time can be a large portion of total latency on otherwise fast point queries.

This also clutters the plan cache and history views with near-duplicate queries, making troubleshooting harder because metrics are scattered across many similar texts.

---

## Real-World Context

**Field Experience:**
- **Operational lookup APIs**: Dynamic SQL concatenated with customer IDs or emails → high compilation overhead and unstable latencies → refactoring to prepared statements with bound parameters significantly reduced p50/p95 latencies and smoothed out long-tail outliers.

- **SaaS metadata services**: Multi-tenant metadata lookups built via string concatenation → plan cache mostly cold even for "identical" requests → adopting parameterized queries via the Snowflake driver improved both performance and observability.

**Common Pattern:**
Dynamic SQL in the app (often via ORMs or custom builders) emits full literal values in WHERE clauses and sometimes LIMIT/OFFSET. Each request gets its own unique query text, even though structurally it's the same query.

---

## How to Fix It

### Step 1: Confirm Parameterization Status

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Inspect recent queries for parameterization issues
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT QUERY_TEXT,
       QUERY_PARAMETERIZED_HASH,
       TOTAL_ELAPSED_TIME,
       COMPILATION_TIME,
       EXECUTION_TIME,
       ACCESS_KV_TABLE
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE APPLICATION_NAME = '{{APPLICATION_NAME}}'
  AND DATABASE_NAME    = '{{DATABASE_NAME}}'
  AND ACCESS_KV_TABLE  = TRUE
ORDER BY START_TIME DESC
LIMIT 50;
```

#### 👤 For Customer Use

```sql
-- Customer: Inspect recent queries for parameterization issues
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT QUERY_TEXT,
       QUERY_PARAMETERIZED_HASH,
       TOTAL_ELAPSED_TIME,
       COMPILATION_TIME,
       EXECUTION_TIME
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE DATABASE_NAME = '{{DATABASE_NAME}}'
  AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY START_TIME DESC
LIMIT 50;
```

If `QUERY_PARAMETERIZED_HASH` is mostly NULL or unique per row, your app likely isn't using bound parameters effectively.

### Step 2: Switch to Prepared Statements in the App

```sql
-- Pseudo-SQL / driver pattern
PREPARE SELECT_PATIENT
FROM
  SELECT *
  FROM PATIENTS_HT
  WHERE PATIENT_FIRST_NAME = ?
    AND PATIENT_LAST_NAME  = ?
    AND PATIENT_DOB        = ?
    AND TENANT_ID          = ?;

-- Later, execute with bound values
EXECUTE SELECT_PATIENT USING ('JOHN', 'DOE', '1980-01-01', 'ACME_TENANT');
```

Key points:

1. Use prepared/parameterized statements in your driver or ORM.
2. Ensure bound parameter data types match column types.
3. Reuse statement templates instead of constructing ad-hoc SQL strings per request.

### Step 3: Validate Plan Cache Reuse

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: After refactor, validate reuse by parameterized hash
-- Replace {{DEPLOYMENT}} with the actual deployment
SELECT QUERY_PARAMETERIZED_HASH,
       COUNT(*)                 AS EXECUTIONS,
       AVG(TOTAL_ELAPSED_TIME) AS AVG_MS,
       AVG(COMPILATION_TIME)   AS AVG_COMPILE_MS
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE APPLICATION_NAME = '{{APPLICATION_NAME}}'
  AND QUERY_PARAMETERIZED_HASH IS NOT NULL
GROUP BY QUERY_PARAMETERIZED_HASH
ORDER BY EXECUTIONS DESC
LIMIT 20;
```

#### 👤 For Customer Use

```sql
-- Customer: After refactor, validate reuse by parameterized hash
SELECT QUERY_PARAMETERIZED_HASH,
       COUNT(*)                 AS EXECUTIONS,
       AVG(TOTAL_ELAPSED_TIME) AS AVG_MS,
       AVG(COMPILATION_TIME)   AS AVG_COMPILE_MS
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE DATABASE_NAME = '{{DATABASE_NAME}}'
  AND QUERY_PARAMETERIZED_HASH IS NOT NULL
  AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY QUERY_PARAMETERIZED_HASH
ORDER BY EXECUTIONS DESC
LIMIT 20;
```

You should see:

- Fewer distinct `QUERY_PARAMETERIZED_HASH` values.
- Lower average compilation times for hot queries.

---

## Expected Improvement

- **Query Time**: [Before] → [After] (e.g., multi-hundred-ms → low-hundreds or double-digit ms when compilation was a major fraction).
- **Resource Usage**: [Before] → [After] (less CPU spent on compilation; cleaner plan cache).
- **Throughput**: [Before] → [After] (higher QPS at same warehouse size for short, repeatable queries).

**Confidence:** High, when workload is dominated by repeatable point or small-range queries.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- Queries are truly ad-hoc analytics with different structure each time; parameterization won't meaningfully improve reuse.
- You are issuing one-off queries in Snowsight or notebooks for investigation.

✅ **Do consider alternatives if:**
- Your ORM/framework makes it hard to use prepared statements; consider a lower-level data access layer using the Snowflake driver directly.
- You already use bound variables but still see high compilation time; then focus on simplifying the query and stabilizing the plan (e.g., reduce unnecessary complexity).

---

## Related Findings

See also:
- `findings/HT_INDEXES_NOT_USED_RUNTIME.md` – Runtime metrics show index effectiveness problems even when plan cache is used.
- `patterns/COMPOSITE_INDEX_ORDER_MISMATCH.md` – Composite index exists but order doesn't align with predicates.

---

## Additional Resources

- Snowflake driver documentation for your language (prepared/parameterized queries)
- Internal HT implementation / field guides: sections on parameter binding

---

**Last Updated:** 2025-12-06  
**Contributor:** AFE / SE Field Manual (Hybrid Tables)  
**Field Validated:** Yes

