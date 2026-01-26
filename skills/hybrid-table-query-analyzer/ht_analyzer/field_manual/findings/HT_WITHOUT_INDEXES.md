# HT_WITHOUT_INDEXES

## What This Means

Hybrid Table has NO indexes defined (not even a primary key), so every query performs a full table scan. You're paying for HT overhead but getting none of the benefits.

---

## Why This Hurts Performance

Without indexes, Hybrid Tables are **worse than standard tables** for almost all workloads:
- Every query scans the entire table (no index seeks)
- Row-based storage is slower than columnar for scans
- You pay HT FDB overhead + locking complexity for zero benefit
- Concurrency suffers due to row-level lock contention on scans
- **This is the worst of both worlds**

---

## Real-World Context

**Field Experience:**
- **E-Commerce Startup**: Created HT for "faster queries" but forgot indexes → 5s lookups, 200 QPS max → Added PK + 2 secondary indexes → 50ms lookups, 2000+ QPS
- **Healthcare Provider**: Migrated from Aurora to Snowflake HT without understanding indexes → Queries slower than before → Added proper indexes → 10x faster than original Aurora
- **Gaming Company**: "HT is slow" complaint → Found zero indexes → Added composite index on (user_id, event_type, timestamp) → 100x faster

**Common Root Causes:**
1. **Migration**: Lifted-and-shifted from another DB, didn't create indexes
2. **Misunderstanding**: Thought HT automatically indexed everything
3. **Testing**: Created HT for POC with small data, never added indexes

**Red Flag:** If someone says "Hybrid Tables are slow", first question: "Do you have indexes?"

---

## How to Fix It

### Step 1: Add Primary Key (Critical!)

```sql
-- Every HT should have a PK - it's the most important index
ALTER TABLE ORDERS_HT 
ADD PRIMARY KEY (order_id);

-- For composite PK (multi-column uniqueness)
ALTER TABLE ORDER_ITEMS_HT
ADD PRIMARY KEY (order_id, line_item_id);
```

**Why PK First:**
- Enforces uniqueness (data quality)
- Automatically creates a clustered index
- Optimizes point lookups on PK columns
- Required for many JOIN patterns

### Step 2: Analyze Query Patterns

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Look at actual queries hitting this table
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT 
    query_text,
    COUNT(*) as execution_count,
    AVG(total_elapsed_time)/1000 as avg_duration_sec
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE query_text ILIKE '%{{TABLE_NAME}}%'
    AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
```

#### 👤 For Customer Use

```sql
-- Customer: Look at actual queries hitting this table
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT 
    query_text,
    COUNT(*) as execution_count,
    AVG(total_elapsed_time)/1000 as avg_duration_sec
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_text ILIKE '%{{TABLE_NAME}}%'
    AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
```

### Step 3: Create Secondary Indexes for Common Predicates

```sql
-- Example: Queries often filter by customer_id
CREATE INDEX idx_customer ON ORDERS_HT (customer_id);

-- Example: Queries filter by status + region
CREATE INDEX idx_status_region ON ORDERS_HT (status, region_id);

-- Example: Time-range queries
CREATE INDEX idx_timestamp ON EVENTS_HT (event_timestamp);

-- Example: Composite for multiple filters
CREATE INDEX idx_user_type_date ON SESSIONS_HT (
    user_id,           -- Highest cardinality first
    session_type,      -- Medium cardinality
    created_date       -- Lower cardinality
);
```

### Step 4: Validate Index Usage

```sql
-- Check that indexes exist
SHOW INDEXES ON ORDERS_HT;

-- Run a query and verify index is used
EXPLAIN 
SELECT * FROM ORDERS_HT 
WHERE customer_id = 12345;
-- Should show INDEX SCAN, not TABLE SCAN

-- Compare performance before/after
SELECT * FROM ORDERS_HT 
WHERE customer_id = 12345
LIMIT 1000;
-- Should be <100ms with index vs seconds without
```

---

## Expected Improvement

**For Point Lookups:**
- **Query Time**: 2-10s (full scan) → 10-100ms (index seek) = **20-100x faster**
- **Throughput**: 10-50 QPS → 1000+ QPS = **20-100x more queries**
- **Resource Usage**: 100 credits/day → 5-10 credits/day = **90-95% cost reduction**

**For Range Queries:**
- **Query Time**: 30s (full scan) → 500ms-2s (index scan) = **15-60x faster**
- **Concurrency**: Single-threaded (lock contention) → High concurrency = **100x more users**

**Confidence:** Extremely High - this is the #1 HT performance issue we see

---

## When NOT to Apply This Fix

⚠️ **Wait on indexes if:**
- Table is **very small** (<100K rows) where full scans are faster than index overhead (rare)
- You're doing **bulk loads** and will add indexes after load completes
- Table is **write-heavy** with rare reads (indexes slow down writes)

✅ **But seriously consider:**
- Even write-heavy tables benefit from indexes for the occasional read
- You can disable/drop indexes during bulk load, then recreate
- The performance gain from indexes almost always outweighs write overhead

**Bottom Line:** 99% of HTs should have at least a PK. If you're in the 1%, you know it.

---

## Index Design Best Practices

**Golden Rules:**
1. **PK first, always** - Start with a primary key
2. **Leading column matters** - Put highest-selectivity columns first in composite indexes
3. **Match query patterns** - Index the columns in your WHERE clauses
4. **Equality before range** - `WHERE a = X AND b > Y` → index on (a, b)
5. **Don't over-index** - Each index slows writes; 3-5 indexes is typical

**Common Composite Index Patterns:**
```sql
-- User lookup pattern: user_id (exact) + timestamp (range)
CREATE INDEX idx_user_time ON EVENTS_HT (user_id, event_timestamp);

-- Multi-tenant pattern: tenant_id (exact) + type (exact) + date (range)
CREATE INDEX idx_tenant_type_date ON DATA_HT (tenant_id, record_type, created_date);

-- Status-based pattern: status (exact) + priority (exact) + created (range)
CREATE INDEX idx_status_priority ON TASKS_HT (status, priority, created_at);
```

---

## Related Findings

See also:
- `findings/COMPOSITE_INDEX_MISALIGNED.md` - Index exists but not used effectively
- `findings/NO_FILTERING.md` - Queries missing WHERE clauses
- `general/ht_sweet_spot.md` - When HT makes sense vs standard tables
- `patterns/oltp_best_practices.md` - OLTP index design patterns

---

## Additional Resources

- [Hybrid Table Indexes](https://docs.snowflake.com/en/user-guide/tables-hybrid-indexes)
- [CREATE INDEX Syntax](https://docs.snowflake.com/en/sql-reference/sql/create-index-hybrid)
- [Index Design Patterns](https://docs.snowflake.com/en/user-guide/tables-hybrid-best-practices#index-design)

---

**Last Updated:** 2025-12-06  
**Contributor:** Unistore Team  
**Field Validated:** Yes (50+ customer implementations)

