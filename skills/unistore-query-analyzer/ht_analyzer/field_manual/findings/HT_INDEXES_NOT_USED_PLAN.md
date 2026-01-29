# HT_INDEXES_NOT_USED_PLAN

## What This Means

The Hybrid Table has one or more indexes that *should* match the query predicates, but the SnowVI execution plan shows no HT index operators for that table. The optimizer has chosen a non-index path (often a broader scan) despite apparently good index coverage.

---

## Why This Hurts Performance

When expected indexes are not used, the engine often has to scan far more rows than necessary. This increases FDB I/O, memory usage, and total elapsed time, especially for high-cardinality filters that are ideal for index lookups. In HT workloads, the cost of missing an index seek is amplified because you lose the main benefit of the KV row store while still paying its overhead.

---

## Real-World Context

**Field Experience:**
- **SaaS Operational App**: Login and session queries on HT scanned millions of rows despite a composite index on `(TENANT_ID, USER_ID)` → predicates wrapped in `UPPER()` and implicit type casts blocked index usage → after normalizing types and removing functions from predicates, plan switched to HT index seek → p95 dropped from ~1.2s to ~80ms.

- **Retail Order API**: Order lookup endpoint scanned the analytic copy instead of using an HT index on `ORDER_ID` → root cause was a VARCHAR vs NUMBER mismatch and string concatenation in the WHERE clause → after fixing types and simplifying the predicate, the HT index operator appeared in plan → p99 improved from 2–3s to <150ms at peak.

**Common Pattern:**
Queries look correct at the SQL level, but subtle issues (functions on indexed columns, type mismatches, overly complex predicates) cause the optimizer to avoid the HT index. Developers often assume "we created the index, so it must be used", but the plan tells a different story.

---

## How to Fix It

### Step 1: Review the SnowVI plan for missing index operators

The SnowVI execution plan data has already been loaded. Check the "Hybrid Table Execution Plan" section in the Full Report to confirm no index operator appears for this table.

### Step 2: Make predicates sargable and types consistent

```sql
-- BAD: Function on indexed column
SELECT *
FROM ORDERS_HT
WHERE UPPER(ORDER_ID) = UPPER(:order_id);

-- GOOD: No function; normalized data types
SELECT *
FROM ORDERS_HT
WHERE ORDER_ID = :order_id::NUMBER;
```

```sql
-- BAD: Implicit casts / concatenation
WHERE TENANT_ID || '-' || USER_ID = :tenant_user_key;

-- GOOD: Direct equality on indexed columns
WHERE TENANT_ID = :tenant_id
  AND USER_ID   = :user_id;
```

### Step 3: Re-run and verify index usage

After fixing predicates, re-run the query and upload fresh SnowVI JSON. The plan should now show an HT index operator on the Hybrid Table.

---

## Expected Improvement

- **Query Time**: 500–2000ms → 30–150ms for point/range lookups on well-indexed HT tables.
- **Resource Usage**: FDB I/O and scanned rows typically drop by 10–100x.
- **Throughput**: 5–10 QPS → 50–200 QPS on the same warehouse for hot OLTP endpoints.

**Confidence:** High based on multiple HT customers where fixing non-sargable predicates and type mismatches unlocked index usage.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- The workload is intentionally analytic and scans a large fraction of the table; HT might not be the right engine.
- The table has no appropriate index at all (the problem then is index design, not index usage).

✅ **Do consider alternatives if:**
- You still see no index operator after fixing predicates and data types → reconsider whether this belongs on a Hybrid Table at all and move it to a standard table or MV.
- The query is aggregation/reporting heavy; focus on columnar/MV design instead of forcing HT index usage.

---

## Related Findings

See also:
- `findings/NO_INDEX_FOR_HOT_PREDICATES.md` - Predicates not covered by any index.
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` - Analytic/reporting workloads mis-placed on Hybrid Tables.
- `findings/HT_INDEX_USED_DESPITE_WEAK_COVERAGE.md` - When plan uses index despite weak static coverage.

---

## Additional Resources

- [Snowflake Docs: Hybrid Table Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)
- [Snowflake Docs: Search Optimization and Sargability](https://docs.snowflake.com/en/user-guide/querying-search-optimization)

---

**Last Updated:** 2025-01-10  
**Contributor:** Transactional Workload / HT AFE Team  
**Field Validated:** Yes

