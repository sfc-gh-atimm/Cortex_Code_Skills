# HT_INDEX_USED_DESPITE_WEAK_COVERAGE

## What This Means

Static analysis suggests weak index coverage (e.g., no strong equality prefix), but the SnowVI execution plan still shows an HT index operator on the table. The optimizer found a way to use the index even though the static "best_eq_prefix" signal is low.

---

## Why This Hurts Performance

It often doesn't hurt performance directly; the danger is *misdiagnosis*. Static coverage alone would suggest drastic index redesign, but the runtime plan shows the index is already being used. Overreacting here can lead to unnecessary index churn and complexity instead of focusing on real bottlenecks (e.g., compilation, client latency, quota, or data model).

---

## Real-World Context

**Field Experience:**
- **Payments Provider**: Static coverage showed only partial alignment on `(TENANT_ID, CREATED_AT)`; HT index still used for common query with a range on `CREATED_AT` and equality on `TENANT_ID` → indexes were "good enough"; real issue was missing bound variables → fixing binding reduced compilation time from ~1.5s to <200ms.

- **Ad Tech**: Complex predicate on multiple columns made static rules pessimistic, but plan showed HT index scans plus effective post-filters → main bottleneck was FDB throttling from bulk loads, not index design → addressing quota/ingest patterns improved stability and latency.

**Common Pattern:**
AFE sees "weak coverage" in static UI and starts redesigning indexes, but plan proves the existing index is in use and reasonably effective. The real root cause is elsewhere.

---

## How to Fix It

### Step 1: Trust the plan over static heuristics

The SnowVI plan data confirms the HT index operator is present and the index is being used. Static coverage is guidance, not gospel.

### Step 2: Prioritize root causes before redesigning indexes

1. Check for **bound variables** and plan cache reuse.
2. Check **quota / HT throttling** and bulk-load patterns.
3. Validate workload fit (OLTP vs analytic) for this table.

### Step 3: Refine, don't rebuild, where needed

```sql
-- Example: add a covering column if range scans are still acceptable
CREATE INDEX idx_orders_tenant_created
  ON ORDERS_HT (TENANT_ID, CREATED_AT)
  INCLUDE (STATUS);
```

---

## Expected Improvement

- **Query Time**: Often unchanged for this finding alone; improvement comes from fixing the *actual* bottleneck (e.g., compilation or quota).
- **Resource Usage**: Small gains if you refine index design; major wins come from overall workload tuning.
- **Throughput**: Improved mainly when underlying cause is compilation or FDB throttling.

**Confidence:** Medium – this finding is primarily about *avoiding misdiagnosis*.

---

## When NOT to Apply This Fix

⚠️ **Don't treat this as a "must redesign index" signal if:**
- The plan already shows acceptable row counts and selectivity.
- Latency is dominated by compilation, client wait, or quota, not scan volume.

✅ **Do consider index redesign if:**
- Plan shows large scan volumes and poor selectivity *despite* index usage, and workload is truly OLTP.
- You have clear evidence (metrics and plan) that better leading columns would dramatically reduce scan rows.

---

## Related Findings

See also:
- `findings/HT_INDEXES_NOT_USED_PLAN.md` - Index exists but is never used in the plan.
- `findings/HT_INDEX_RANGE_SCAN.md` - Index used, but behaves like a wide range scan.
- `findings/NO_BOUND_VARIABLES.md` - Missing parameterization causing compilation overhead.

---

## Additional Resources

- [Hybrid Table Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)

---

**Last Updated:** 2025-01-10  
**Contributor:** Transactional Workload / HT AFE Team  
**Field Validated:** Yes

