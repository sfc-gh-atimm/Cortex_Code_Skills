# PRIMARY_KEY_NOT_USED - Hybrid Table Field Guide

## What This Means

Your Hybrid Table has a PRIMARY KEY defined, but your query doesn't use any PK columns in equality predicates (`WHERE pk_col = ?`).

**Why it hurts**: Hybrid Tables are specifically optimized for PRIMARY KEY-based row access. Skipping the PK often forces broader index probes or table scans, resulting in higher bytes scanned per row and increased latency.

## Real-World Context

### Scenario 1: Reporting query on operational HT

**Customer situation**:
- "We have an `orders` HT with PK on `order_id`"
- "But our BI dashboards query by `customer_id` for analytics"
- **Reality**: Analytic scan pattern on operational table architecture

**Field-validated fix**:
- Move reporting/analytic queries to **standard tables** or **materialized views**
- Keep HT for operational point lookups (`WHERE order_id = ?`)
- Expected: 10-100x better analytics performance on columnar storage

### Scenario 2: Composite PK misunderstanding

**Customer situation**:
- "We have PK (`region`, `order_id`) but query by `order_id` only"
- "Why is performance bad?"
- **Reality**: Left-prefix not honored defeats PK optimization

**Field-validated fix**:
```sql
-- Bad: Missing left-most PK column
SELECT * FROM orders WHERE order_id = 'ORD-123';

-- Good: Include left-prefix
SELECT * FROM orders 
WHERE region = 'US-WEST' AND order_id = 'ORD-123';

-- Or: Redefine PK order based on actual query patterns
ALTER TABLE orders DROP PRIMARY KEY;
ALTER TABLE orders ADD PRIMARY KEY (order_id, region);
```

**Expected**: Latency drops from 100-500ms to 5-15ms for point lookups

### Scenario 3: Missing WHERE clause optimization

**Customer situation**:
- "Application fetches all recent orders, then filters client-side"
- "Performance degraded as table grew to 100M+ rows"
- **Reality**: Full table scan when PK lookup would work

**Field-validated fix**:
```sql
-- Bad: No PK predicate, fetches everything
SELECT * FROM orders WHERE created_at >= CURRENT_DATE - 7;

-- Good: Add PK predicate if known
SELECT * FROM orders 
WHERE order_id IN (SELECT order_id FROM order_queue WHERE status = 'PENDING')
  AND created_at >= CURRENT_DATE - 7;

-- Better: Use event-driven architecture
-- Store pending order_ids in separate HT, query by PK
```

**Expected**: Bytes scanned drops 100-1000x, latency approaches single-digit milliseconds

## How to Fix

### Operational Workload (Point Lookups)

**Use PK equality predicates**:
```sql
-- Single-column PK
SELECT * FROM orders WHERE order_id = :order_id;

-- Composite PK (MUST use left-prefix)
SELECT * FROM orders 
WHERE region = :region AND order_id = :order_id;

-- Composite PK with IN clause (OK for small lists)
SELECT * FROM orders 
WHERE region = 'US-WEST' 
  AND order_id IN (:id1, :id2, :id3);
```

### If You Can't Use PK

**Add secondary index aligned with actual predicates**:
```sql
-- Query by customer_id frequently?
CREATE INDEX idx_customer ON orders(customer_id);

-- Query by status + customer_id?
CREATE INDEX idx_status_customer ON orders(status, customer_id);

-- Verify SnowVI shows index is used
```

### Analytic Workload (Scans/Aggregations)

**Don't chase PK usage - move to standard tables**:
```sql
-- This pattern doesn't belong on HT:
SELECT customer_id, COUNT(*), SUM(amount), AVG(amount)
FROM orders
WHERE created_at >= '2024-01-01'
GROUP BY customer_id;

-- Solution 1: Move to standard table
CREATE TABLE orders_analytics CLONE orders;  -- For existing data
ALTER TABLE orders_analytics SET ENABLE_SCHEMA_EVOLUTION = TRUE;

-- Solution 2: Materialized View (auto-refresh)
CREATE MATERIALIZED VIEW mv_customer_orders AS
SELECT customer_id, DATE_TRUNC('day', created_at) AS order_date,
       COUNT(*) AS order_count,
       SUM(amount) AS total_amount
FROM orders
GROUP BY customer_id, DATE_TRUNC('day', created_at);

-- Solution 3: Snowflake Postgres with hybrid query routing
```

## Expected Impact

### With PK Equality:
- **Bytes scanned**: ↓ 10-1000x (depends on table size and selectivity)
- **Latency**: ↓ 50-95% (single-digit milliseconds for point lookups)
- **Confidence**: HIGH

### With Secondary Index on Actual Predicates:
- **Bytes scanned**: ↓ 5-100x
- **Latency**: ↓ 30-80%
- **Confidence**: MEDIUM-HIGH (verify with SnowVI)

### Move Analytic to Standard Tables:
- **Scan performance**: ↑ 10-100x (columnar storage benefits)
- **Cost**: ↓ 50-90% (compute credits for scans)
- **Confidence**: HIGH

## When NOT to Apply

1. **Analytic queries**: Scans, aggregations, windowing, reporting → **Use standard tables/MVs**
2. **Required predicates don't match PK**: Add secondary index instead of forcing PK usage
3. **Small tables**: PK vs full scan difference is negligible (< 1,000 rows)
4. **Batch/ETL loads**: CTAS + swap pattern doesn't need PK access

## Discovery Questions

Use these with customers to guide architecture decisions:

1. **"Is this query meant to return one specific row or many rows?"**
   - One row → Operational, use PK
   - Many rows → Analytic, consider standard tables

2. **"Do you know the PK value(s) before running this query?"**
   - Yes → Use WHERE pk = ?
   - No → May need secondary index or different architecture

3. **"Is this operational (real-time lookup) or analytic (reporting/BI)?"**
   - Operational → HT with PK access
   - Analytic → Standard tables, MVs, or Snowflake Postgres

4. **"How often does this query run, and with what latency SLA?"**
   - High QPS, low latency → HT with PK
   - Low QPS, flexible latency → Standard tables acceptable

5. **"What's the typical result set size?"**
   - 1-100 rows → HT point lookup
   - 1,000+ rows → Reconsider architecture

## Success Metrics

### Immediate (after fix):
- Bytes scanned per query drops significantly (check `BYTES_SCANNED` in `QUERY_HISTORY`)
- Latency approaches single-digit milliseconds for point lookups
- Query plan in SnowVI shows "PK equality probe" or "index seek"

### Sustained (over days/weeks):
- p50/p95/p99 latencies stable and predictable
- Cost per query drops (fewer bytes scanned = less compute)
- No client-side timeouts or performance complaints

### Validation SQL:

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Before/after comparison
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT 
    QUERY_PARAMETERIZED_HASH,
    COUNT(*) AS execution_count,
    MEDIAN(TOTAL_ELAPSED_TIME) AS p50_ms,
    APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.95) AS p95_ms,
    AVG(BYTES_SCANNED) AS avg_bytes,
    AVG(BYTES_SCANNED) / NULLIF(AVG(ROWS_PRODUCED), 0) AS bytes_per_row
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE QUERY_TEXT ILIKE '%{{TABLE_NAME}}%'
  AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY QUERY_PARAMETERIZED_HASH
ORDER BY execution_count DESC;
```

#### 👤 For Customer Use

```sql
-- Customer: Before/after comparison
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT 
    QUERY_PARAMETERIZED_HASH,
    COUNT(*) AS execution_count,
    MEDIAN(TOTAL_ELAPSED_TIME) AS p50_ms,
    APPROX_PERCENTILE(TOTAL_ELAPSED_TIME, 0.95) AS p95_ms,
    AVG(BYTES_SCANNED) AS avg_bytes,
    AVG(BYTES_SCANNED) / NULLIF(AVG(ROWS_PRODUCED), 0) AS bytes_per_row
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_TEXT ILIKE '%{{TABLE_NAME}}%'
  AND START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY QUERY_PARAMETERIZED_HASH
ORDER BY execution_count DESC;
```

## Talk Track for Customers

**Opening**:
> "I see your query isn't using the PRIMARY KEY you defined on this Hybrid Table. That's interesting - tell me about the use case. Are you doing point lookups by order_id, or is this more of a reporting query?"

**If operational** (point lookups):
> "Perfect - this is exactly what Hybrid Tables excel at. Let's add a WHERE clause on order_id to leverage that PK. You should see latency drop from X00ms to single-digit milliseconds."

**If analytic** (scans/aggregations):
> "Got it - this is an analytic workload. Hybrid Tables aren't the right fit here. Let's move these queries to a standard table or materialized view where Snowflake's columnar storage shines. You'll get 10-100x better scan performance."

**If mixed**:
> "Interesting - you have both operational and analytic access patterns. Have you considered Snowflake Postgres with hybrid query routing? Or we could split the workload: HT for real-time lookups, MV for analytics."

## Related Findings

Often appears with:
- `HT_WITHOUT_INDEXES` - No indexes at all (PK should be there)
- `COMPOSITE_INDEX_MISALIGNED` - Similar left-prefix issue with secondary indexes
- `ANALYTIC_WORKLOAD_ON_HT` - Root cause architectural mismatch
- `NO_INDEX_FOR_HOT_PREDICATES` - Missing secondary index for non-PK predicates

## Additional Resources

- [Hybrid Tables Best Practices](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices)
- [Snowflake Postgres (Unistore)](https://docs.snowflake.com/en/user-guide/unistore)
- [Materialized Views](https://docs.snowflake.com/en/user-guide/views-materialized)
- Field Manual: `ANALYTIC_WORKLOAD_ON_HT.md`

---

**Key Takeaway**: If you have a PK but don't use it, either change your query pattern (operational) or change your table type (analytic). Don't try to make HT fit an analytic workload.

