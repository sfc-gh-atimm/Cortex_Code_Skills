# COMPOSITE_INDEX_MISALIGNED

## What This Means

A composite (multi-column) index exists, but the query predicates don't match the **leading columns** of the index, so the index is completely ignored. Query performs full table scan despite "having an index."

---

## Why This Hurts Performance

Composite indexes work **left-to-right** only. If your index is `(A, B, C)` but your query filters on `B` or `C` alone, the index is **useless**:
- Query planner can't use the index → full table scan
- This is subtle - looks like "index exists but not used"
- Common when queries evolved but indexes didn't
- AFEs often miss this without careful EXPLAIN analysis

**Index Math:**
- Index `(A, B, C)` → Can optimize: `WHERE A=`, `WHERE A= AND B=`, `WHERE A= AND B= AND C=`
- Index `(A, B, C)` → **Cannot optimize**: `WHERE B=`, `WHERE C=`, `WHERE B= AND C=`

---

## Real-World Context

**Field Experience:**
- **Financial Services**: Had index `(region_id, account_id, transaction_date)` but queries filtered `WHERE account_id = X` → Index useless, 5s queries → Reordered to `(account_id, region_id, transaction_date)` → 100ms queries
- **Retail**: Created index `(store_id, product_id, sale_date)` for reporting, but 80% of queries were `WHERE product_id = Y AND sale_date > Z` → No store_id filter = no index usage → Created second index `(product_id, sale_date)` → Solved
- **SaaS**: "Why is this query slow? We have indexes!" → Index was `(tenant_id, user_id, created_at)` but query was `WHERE user_id = X` (forgot tenant_id filter) → Added tenant_id to query → 50x faster

**Common Mistake:**
Creating indexes based on column names that "seem related" rather than actual query patterns. **Always design indexes for your queries, not your schema.**

---

## How to Fix It

### Option 1: Reorder the Index (If All Queries Use Same Columns)

```sql
-- BAD: Index doesn't match queries
CREATE INDEX idx_old ON ORDERS_HT (region_id, customer_id, order_date);

-- Queries mostly do:
SELECT * FROM ORDERS_HT WHERE customer_id = ? AND order_date > ?;
-- ❌ No region_id → index not used!

-- GOOD: Reorder index to match queries
DROP INDEX idx_old ON ORDERS_HT;

CREATE INDEX idx_customer_date ON ORDERS_HT (
    customer_id,     -- Most selective, always in WHERE
    order_date       -- Range filter
);

-- Now this query uses the index:
SELECT * FROM ORDERS_HT WHERE customer_id = ? AND order_date > ?;
-- ✅ Index scan on (customer_id, order_date)
```

### Option 2: Create Multiple Indexes (For Different Query Patterns)

```sql
-- Pattern 1: Lookup by customer
CREATE INDEX idx_customer ON ORDERS_HT (customer_id, order_date);

-- Pattern 2: Lookup by region
CREATE INDEX idx_region ON ORDERS_HT (region_id, order_date);

-- Pattern 3: Admin queries with full context
CREATE INDEX idx_admin ON ORDERS_HT (region_id, customer_id, order_date);

-- Now all three query types are optimized
```

### Option 3: Add Missing Predicate to Query

```sql
-- Sometimes the fix is in the query, not the index
-- If index is (tenant_id, user_id, event_type)

-- BAD: Missing leading column
SELECT * FROM EVENTS_HT 
WHERE user_id = ? AND event_type = ?;
-- ❌ No tenant_id → full scan

-- GOOD: Add the leading column
SELECT * FROM EVENTS_HT 
WHERE tenant_id = ? AND user_id = ? AND event_type = ?;
-- ✅ Index fully utilized

-- Often tenant_id can be pulled from session context:
-- WHERE tenant_id = CURRENT_TENANT() AND user_id = ?
```

### Step-by-Step Diagnosis

```sql
-- 1. Check existing indexes
SHOW INDEXES ON ORDERS_HT;

-- 2. Check query plan BEFORE fix
EXPLAIN 
SELECT * FROM ORDERS_HT WHERE customer_id = 12345;
-- Look for "TableScan" = bad, "IndexScan" = good

-- 3. Identify the mismatch
-- Index: (region_id, customer_id, order_date)
-- Query: WHERE customer_id = ?
--        ^^^ Missing region_id!

-- 4. Fix: Either reorder index OR add region_id to query

-- 5. Verify AFTER fix
EXPLAIN 
SELECT * FROM ORDERS_HT WHERE customer_id = 12345;
-- Should now show IndexScan on the new index
```

---

## Expected Improvement

- **Query Time**: 3-30s (full scan) → 50-500ms (index scan) = **6-60x faster**
- **Resource Usage**: 200 credits/day → 10-20 credits/day = **90-95% reduction**
- **Concurrency**: Limited → High (index scans don't lock as much)
- **Cost**: Often $100s-$1000s saved per month

**Confidence:** High - seen at 15+ customers, fix is usually immediate

---

## When NOT to Apply This Fix

⚠️ **Don't blindly reorder if:**
- **Multiple query patterns** exist and reordering helps one but breaks others
  - Solution: Create multiple indexes for different patterns
- **Write performance** is critical and you already have too many indexes
  - Solution: Consolidate indexes, accept some queries won't optimize
- **Data volume is tiny** (<10K rows) where index overhead outweighs benefit

✅ **Better approach:**
- **Analyze actual query patterns** from query history (last 7-30 days)
- **Count execution frequency** - optimize for the 80% case
- **Create 2-3 indexes** for different access patterns rather than one "universal" index

---

## Index Design Rules for Composite Indexes

**Ordering Principles:**
1. **Equality before range**: `WHERE a = X AND b > Y` → index on `(a, b)`
2. **Selectivity first**: Highest-cardinality column first (if all equality)
3. **Common patterns first**: If 90% of queries filter on column A, put A first
4. **Range last**: Range predicates (`>, <, BETWEEN`) should be last column

**Examples:**

```sql
-- ✅ GOOD: Equality (tenant_id) before range (created_at)
CREATE INDEX idx_tenant_date ON DATA (tenant_id, created_at);
-- Optimizes: WHERE tenant_id = ? AND created_at > ?

-- ❌ BAD: Range before equality
CREATE INDEX idx_date_tenant ON DATA (created_at, tenant_id);
-- Doesn't optimize: WHERE tenant_id = ?

-- ✅ GOOD: High-selectivity first
CREATE INDEX idx_user_status ON TASKS (user_id, status, priority);
-- user_id (millions of values) before status (3-5 values)

-- ❌ BAD: Low-selectivity first
CREATE INDEX idx_status_user ON TASKS (status, user_id, priority);
-- status has only 3 values, not selective enough to lead
```

---

## Related Findings

See also:
- `findings/HT_WITHOUT_INDEXES.md` - Creating your first indexes
- `findings/HT_INDEXES_NOT_USED_RUNTIME.md` - Other reasons indexes aren't used
- `patterns/oltp_best_practices.md` - Complete index design guide

---

## Additional Resources

- [Composite Index Design](https://docs.snowflake.com/en/user-guide/tables-hybrid-indexes#composite-indexes)
- [Query Profile Analysis](https://docs.snowflake.com/en/user-guide/ui-query-profile)
- [EXPLAIN Command](https://docs.snowflake.com/en/sql-reference/sql/explain)

---

**Last Updated:** 2025-12-06  
**Contributor:** Unistore Team  
**Field Validated:** Yes (15+ customer implementations)

