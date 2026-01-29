# FULL_SORT_ON_HT

## What This Means

The **FULL_SORT_ON_HT** finding indicates that a query against a Hybrid Table performs an `ORDER BY` over a large result set *without* a `LIMIT`/`FETCH`, forcing a full sort in the Hybrid Table engine. This is effectively an analytic operation on an operational storage engine.

---

## Why This Hurts Performance

Full sorts over large Hybrid Table result sets:

- Require materializing and ordering many rows in memory.
- Increase CPU and memory usage within the HT engine.
- Often provide little extra value for interactive APIs or UIs that only show a page of results.

Standard tables or pre-sorted analytical structures are usually better suited for full-result sorting, especially when the user only needs the "top K" rows.

---

## Real-World Context

**Field Experience:**
- **Order history UIs**: Endpoints returned "all orders" for a customer sorted by date, then the front-end paginated → HT did heavy sorts across thousands of rows when the user only saw the first page → adding `LIMIT` and moving full exports to analytics tables produced much better responsiveness.

- **Audit log viewers**: Admin tools requested full event histories sorted by timestamp, even though operators typically reviewed only recent entries → changing to paged, time-windowed views (with LIMIT and proper ordering) eliminated unnecessary sorts over historical data.

**Common Pattern:**
Developers default to "return everything sorted" and paginate on the client, masking the fact that the database did far more work than the user needed.

---

## How to Fix It

### Step 1: Clarify UX / API Requirements

Talk with the product/UX owner:

- How many rows do users actually need per interaction?
- Is there a real use case for "download all," and how often is it used?

This often reveals that a single page or small window of results is sufficient for most operations.

### Step 2: Use Top‑K Queries for Interactive Paths

```sql
-- Before: full sort across many rows
SELECT *
FROM EVENTS_HT
WHERE USER_ID = ?
ORDER BY EVENT_TIMESTAMP DESC;

-- After: top-K for UI/API
SELECT *
FROM EVENTS_HT
WHERE USER_ID = ?
ORDER BY EVENT_TIMESTAMP DESC
LIMIT 100;
```

For pagination, consider keyset pagination using the sort key instead of large offset values.

### Step 3: Route Full Historical Exports to Analytic Tables

```sql
-- Historical / export path: use standard table
CREATE OR REPLACE TABLE EVENTS_HISTORY AS
SELECT * FROM EVENTS_HT;

-- For exports / reports
SELECT *
FROM EVENTS_HISTORY
WHERE USER_ID = ?
  AND EVENT_TIMESTAMP >= DATEADD(DAY, -90, CURRENT_TIMESTAMP())
ORDER BY EVENT_TIMESTAMP DESC;
```

Keep the HT-focused on low-latency operational slices, while analytics and bulk exports run on standard tables.

---

## Expected Improvement

- **Query Time**: [Before] → [After] (e.g., multi-second full sorts → sub-second top-K queries).
- **Resource Usage**: [Before] → [After] (less memory and CPU pressure in the HT engine).
- **Throughput**: [Before] → [After] (more concurrent interactive operations at consistent latency).

**Confidence:** High, when the query currently sorts many rows but users only need a small subset.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- The business requirement truly demands returning all rows for compliance or data export, and the result set is necessarily large and user-visible.
- The result sets are naturally small (tens of rows) so the cost of sorting isn't material.

✅ **Do consider alternatives if:**
- You need rich pagination or complex sorting beyond a single key; look at keyset pagination or using an analytic table dedicated to heavy exploration.
- You need analytical sorts over large history; those are usually better on standard tables, MVs, or dynamic tables, not on HT.

---

## Related Findings

See also:
- `findings/ANALYTIC_WORKLOAD_ON_HT.md` – General analytic/reporting behavior on Hybrid Tables.
- `findings/HT_INDEXES_NOT_USED_RUNTIME.md` – Index inefficiency that can coexist with full sorts.

---

## Additional Resources

- Hybrid Tables best practices: query pattern guidance
- Internal enablement decks that cover when HT is not a good fit for BI/analytic dashboards

---

**Last Updated:** 2025-12-06  
**Contributor:** AFE / SE Field Manual (Hybrid Tables)  
**Field Validated:** Yes

