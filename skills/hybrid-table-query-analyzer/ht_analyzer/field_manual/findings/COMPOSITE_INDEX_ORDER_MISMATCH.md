# COMPOSITE_INDEX_ORDER_MISMATCH

## What This Means

The **COMPOSITE_INDEX_ORDER_MISMATCH** pattern means a composite index exists on a Hybrid Table, but the left-most index columns don't match the equality predicates in the query's WHERE clause. The query is filtering on some of the indexed columns, but not in the order required for effective index seeks.

---

## Why This Hurts Performance

Hybrid Table indexes are most effective when predicates match a left-aligned prefix of the composite index (e.g., index `(A, B, C)` with predicates on `A` and `B`). If the query filters on `B` and `C` but not `A`, the planner may only partially use the index or fall back to scans.

This often shows up as "we have an index but the query is still slow" and as low `best_eq_prefix` coverage in analysis results, even though predicates and index columns overlap.

---

## Real-World Context

**Field Experience:**
- **Account / policy lookup**: Composite index on `(FIRST_NAME, LAST_NAME, DOB, ACCOUNT_ID)` while hot APIs filtered primarily by `ACCOUNT_ID` (and sometimes `DOB`) → index coverage for hot queries was effectively zero → redesigning indexes to put `ACCOUNT_ID` first, and creating a separate name-based index for rare workflows, produced much better latency.

- **Tracking/metadata tables**: Index `(COUNTRY, REGION, ID)` while production queries filter on `ID` only → planner can't treat it as a point lookup; it behaves like a much broader range scan → reordering to `(ID)` or `(ID, COUNTRY)` aligned the index with the real predicates and reduced the work dramatically.

**Common Pattern:**
Indexes are designed to mirror legacy schemas or follow human-friendly fields (e.g., names, geo) instead of technical keys that actually drive the application (IDs, keys, tenant identifiers).

---

## How to Fix It

### Step 1: Inspect Predicates vs Existing Indexes

Use your analyzer coverage or SnowVI metadata to compare:

- `PRED_EQ_COLS` (columns with equality predicates)
- `INDEX_COLUMNS` (existing composite index definitions)
- `BEST_EQ_PREFIX` (how many leading index columns are satisfied)

```sql
SELECT
  TABLE_NAME,
  INDEX_COLUMNS,
  PRED_EQ_COLS,
  BEST_EQ_PREFIX
FROM <HT_ANALYZER_COVERAGE_VIEW>
WHERE TABLE_NAME = '<HT_TABLE_NAME>';
```

Look for overlap between `PRED_EQ_COLS` and `INDEX_COLUMNS` combined with `BEST_EQ_PREFIX = 0` or very low values.

### Step 2: Redesign Composite Index Ordering

```sql
-- Example: current index (misaligned for API pattern)
CREATE OR REPLACE INDEX IDX_CUSTOMER_NAME
  ON CUSTOMERS_HT (FIRST_NAME, LAST_NAME, DOB, CUSTOMER_ID);

-- Better: align with hot path (ID-based lookup)
CREATE OR REPLACE INDEX IDX_CUSTOMER_ID
  ON CUSTOMERS_HT (CUSTOMER_ID, DOB);

-- Optional: secondary index for occasional name-based searches
CREATE OR REPLACE INDEX IDX_CUSTOMER_NAME_ALT
  ON CUSTOMERS_HT (LAST_NAME, FIRST_NAME);
```

Guidelines:

1. Put the **most selective, always-present** predicate columns first.
2. Consider separate indexes for fundamentally different access patterns.

### Step 3: Validate with Query Profile and Analyzer

```sql
-- Re-run hot queries and check coverage again
SELECT *
FROM <HT_ANALYZER_COVERAGE_VIEW>
WHERE TABLE_NAME = 'CUSTOMERS_HT';
```

In SnowVI or other profiling tools:

- Confirm the new index is used.
- Verify that index operators are present and scan ranges are small.

---

## Expected Improvement

- **Query Time**: [Before] → [After] (often large reductions for API-style point/range lookups).
- **Resource Usage**: [Before] → [After] (fewer bytes scanned and lower FDB I/O thanks to more selective index use).
- **Throughput**: [Before] → [After] (more concurrent point operations supported at same HT capacity).

**Confidence:** High, when a clear mismatch between index order and predicate order exists and hot paths are well-understood.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- The workload is predominantly analytic (large scans, aggregations) and does not have a stable, high-volume point-lookup path; in that case, index tuning may be less impactful than moving analytics off HT.
- Writes and updates are so frequent across many indexed columns that maintaining additional or reordered indexes would create unacceptable write amplification.

✅ **Do consider alternatives if:**
- You have multiple conflicting access patterns; consider separate Hybrid Tables or a combination of HT + standard tables tuned to each pattern.
- The primary bottleneck is data quality or poor selectivity (e.g., low-cardinality predicates), where index order alone can't solve the issue.

---

## Related Findings

See also:
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` – Query pattern is analytic rather than operational.
- `findings/HT_INDEXES_NOT_USED_RUNTIME.md` – Runtime metrics show index effectiveness problems even when static coverage looks OK.

---

## Additional Resources

- Hybrid Tables index design guidance (public docs)
- Internal Unistore / Hybrid Tables field implementation guides (indexing and workload fit)

---

**Last Updated:** 2025-12-06  
**Contributor:** AFE / SE Field Manual (Hybrid Tables)  
**Field Validated:** Yes

