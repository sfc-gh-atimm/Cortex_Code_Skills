# HT_PURGE_PATTERN_DETECTED

## What This Means

This finding indicates that your DELETE, UPDATE, or MERGE query follows a **data purge/cleanup pattern**:
- **Equality predicate** on a key column (e.g., `tenant_id = 'ABC'`, `user_id = 123`)
- **Time-range predicate** for old data (e.g., `created_at < '2024-01-01'`, `deleted_at <= CURRENT_DATE() - 90`)

This is a common operational pattern for:
- Data retention policies (delete records older than X days)
- Cleanup operations (purge soft-deleted records)
- Archive workflows (move old data to cold storage)

**Why it matters**: Large purge operations (>1,000 rows) on Hybrid Tables can:
- Trigger throttling if quota is limited
- Impact concurrent OLTP queries
- Take longer than expected if not batched properly

---

## Field Experience

### Real-World Context

**Scenario 1: Multi-Tenant SaaS Cleanup**
- Customer: SaaS platform with 1000+ tenants
- Pattern: `DELETE FROM logs WHERE tenant_id = ? AND created_at < ?`
- Volume: 50,000–500,000 rows per tenant per month
- **Problem**: Unbatched deletes caused 20+ second throttling, impacting live transactions
- **Fix**: Batched deletes (1,000 rows per batch, 100ms delay) + composite index `(tenant_id, created_at)`
- **Result**: Purge time reduced from 45s to 8s, zero throttling impact

**Scenario 2: GDPR Right-to-Delete**
- Customer: E-commerce platform
- Pattern: `DELETE FROM user_activity WHERE user_id = ? AND event_date < ?`
- Volume: 10,000–100,000 rows per user
- **Problem**: Customer reported "slow deletes" during business hours
- **Fix**: Batch pattern + off-peak scheduling + archive-before-delete
- **Result**: 10x faster deletes, archived data for compliance audits

**Scenario 3: Soft-Delete Purge Under Quota Pressure**
- Customer: Financial services (strict HT quota limits)
- Pattern: `DELETE FROM transactions WHERE deleted_at IS NOT NULL AND deleted_at < DATEADD(day, -30, CURRENT_DATE())`
- Volume: 200,000+ rows per day
- **Problem**: Purge job triggered throttling (HT_REQUEST_THROTTLING), blocked critical queries
- **Fix**: Rate-limited batches (500 rows, 200ms delay) + quota increase request + index on `(deleted_at)`
- **Result**: Purge runs without throttling, peak performance maintained

---

## How to Fix

### **Step 1: Batch Your Deletes**

**Pattern**: Use `ROW_NUMBER()` with `QUALIFY` to limit rows per batch.

```sql
-- ❌ BAD: Unbatched (deletes all matching rows at once)
DELETE FROM orders_ht
WHERE tenant_id = 'ABC'
  AND created_at < '2024-01-01';

-- ✅ GOOD: Batched (limits to 1,000 rows per execution)
DELETE FROM orders_ht
WHERE order_id IN (
    SELECT order_id
    FROM orders_ht
    WHERE tenant_id = 'ABC'
      AND created_at < '2024-01-01'
    QUALIFY ROW_NUMBER() OVER (ORDER BY created_at) <= 1000
);
```

**Why 1,000 rows?**
- Balances throughput vs. impact
- Stays well below typical throttling thresholds
- Allows index seeks to remain efficient

---

### **Step 2: Add Rate-Limiting (If Throttling is Present)**

If `HT_REQUEST_THROTTLING` is also detected, add delays between batches:

```python
import time

batch_size = 1000
delay_ms = 100  # Adjust based on quota

while True:
    cursor.execute("""
        DELETE FROM orders_ht
        WHERE order_id IN (
            SELECT order_id FROM orders_ht
            WHERE tenant_id = ? AND created_at < ?
            QUALIFY ROW_NUMBER() OVER (ORDER BY created_at) <= ?
        )
    """, (tenant_id, cutoff_date, batch_size))
    
    rows_deleted = cursor.rowcount
    if rows_deleted == 0:
        break
    
    print(f"Deleted {rows_deleted} rows, sleeping {delay_ms}ms...")
    time.sleep(delay_ms / 1000.0)
```

**Rate-limit tuning**:
- **No throttling**: 0–50ms delay (fast cleanup)
- **Occasional throttling**: 100–200ms delay (safe)
- **Frequent throttling**: 200–500ms delay + quota increase request

---

### **Step 3: Ensure Composite Index Exists**

For efficient purge operations, create a composite index with:
1. **Equality column first** (for fast partition seeking)
2. **Time column second** (for range filtering within partition)

```sql
-- For tenant_id = X AND created_at < Y
CREATE INDEX IF NOT EXISTS idx_purge_tenant_time 
ON orders_ht (tenant_id, created_at);

-- For user_id = X AND deleted_at < Y
CREATE INDEX IF NOT EXISTS idx_purge_user_deleted
ON user_activity_ht (user_id, deleted_at);
```

**Why this order?**
- Equality predicate narrows to specific tenant/user (index seek)
- Time-range predicate scans only within that tenant/user's data
- Avoids full table scans

**Verification**:
```sql
-- Check if index is used
EXPLAIN USING TABULAR
DELETE FROM orders_ht
WHERE tenant_id = 'ABC' AND created_at < '2024-01-01';

-- Look for "Index Scan" on your composite index in the output
```

---

### **Step 4: Archive Before Deleting (Best Practice)**

Before purging, archive to columnar storage for:
- Compliance/audit requirements
- Analytics on historical trends
- Cost-effective long-term retention

```sql
-- 1. Archive to columnar table (standard table)
CREATE TABLE IF NOT EXISTS orders_archive (LIKE orders_ht);

INSERT INTO orders_archive
SELECT * FROM orders_ht
WHERE tenant_id = 'ABC' AND created_at < '2024-01-01';

-- 2. THEN batch-delete from HT
DELETE FROM orders_ht
WHERE order_id IN (
    SELECT order_id FROM orders_ht
    WHERE tenant_id = 'ABC' AND created_at < '2024-01-01'
    QUALIFY ROW_NUMBER() OVER (ORDER BY created_at) <= 1000
);
```

---

## Expected Impact

### **Before** (Unbatched):
- ⏱ **Latency**: 20–60 seconds (for 50,000 rows)
- 🚨 **Throttling**: Likely if quota is limited
- 💥 **Impact**: Concurrent queries blocked or delayed
- ❌ **Rollback risk**: All-or-nothing (if error occurs mid-delete)

### **After** (Batched + Rate-Limited + Indexed):
- ⏱ **Latency**: 5–15 seconds (for 50,000 rows across 50 batches)
- ✅ **Throttling**: Minimal to none
- ✅ **Impact**: Concurrent queries unaffected
- ✅ **Rollback risk**: Per-batch (easier recovery)
- 📊 **Progress tracking**: Can monitor batch completion

**Typical improvement**: **60–80% faster** with zero throttling impact.

---

## When NOT to Apply

### **Scenario 1: Small Deletes (<100 rows)**
If you're deleting fewer than 100–200 rows, batching adds unnecessary complexity.
- **Action**: Keep simple `DELETE` statement
- **Reason**: Overhead of batching logic outweighs benefit

### **Scenario 2: Infrequent Purges (Weekly/Monthly)**
If purges happen infrequently (e.g., once per week during maintenance window):
- **Action**: Run unbatched during off-peak hours
- **Reason**: No impact on concurrent workload
- **But**: Still recommend composite index for speed

### **Scenario 3: Already Using CTAS+Swap**
If you're rebuilding the entire table (not purging a subset):
- **Action**: Use `CTAS` + `ALTER TABLE ... SWAP WITH` instead
- **Reason**: More efficient for large-scale rewrites
- **See**: `BULK_DML_SHOULD_BE_CTAS` finding for details

---

## Common Pitfalls

### **Pitfall 1: No Index on Time Column**
```sql
-- ❌ BAD: Only tenant_id indexed
CREATE INDEX idx_tenant ON orders_ht (tenant_id);

-- Purge still scans all tenant_id='ABC' rows to find old ones
DELETE FROM orders_ht WHERE tenant_id = 'ABC' AND created_at < '2024-01-01';
```
**Fix**: Add composite index `(tenant_id, created_at)`.

---

### **Pitfall 2: Wrong Index Column Order**
```sql
-- ❌ BAD: Time column first
CREATE INDEX idx_time_tenant ON orders_ht (created_at, tenant_id);

-- Optimizer can't seek to specific tenant efficiently
```
**Fix**: Equality column first, then time: `(tenant_id, created_at)`.

---

### **Pitfall 3: No Rate-Limiting Under Quota Pressure**
```sql
-- ⚠️ DANGER: Batched but no delay
while rows_deleted > 0:
    DELETE ... QUALIFY ROW_NUMBER() <= 1000;
    # No sleep() here!
```
**Problem**: Rapid-fire batches still trigger throttling.  
**Fix**: Add 100–200ms delay between batches.

---

## Discovery Questions

1. **"How often do you run this purge operation?"**
   - Daily/hourly → Batching + rate-limiting critical
   - Weekly/monthly → Can run unbatched during off-peak

2. **"What's the typical volume deleted per execution?"**
   - <1,000 rows → No batching needed
   - 1,000–50,000 rows → Batch with 1,000 rows per batch
   - 50,000+ rows → Batch + rate-limit + consider archiving first

3. **"Are you seeing HT_REQUEST_THROTTLING errors during purge?"**
   - Yes → Rate-limiting (200–500ms) + quota increase request
   - No → Batching alone may be sufficient

4. **"Do you need to retain the deleted data for compliance/audit?"**
   - Yes → Archive to columnar before deleting
   - No → Proceed with batched delete

5. **"Is this DELETE tied to a specific business workflow (e.g., GDPR request)?"**
   - Yes → Consider SLA/timeout requirements for batching
   - No → Optimize for minimal impact on OLTP workload

---

## Related Findings

- **`HT_REQUEST_THROTTLING`**: If purge triggers throttling, fix quota first, then batch
- **`BULK_DML_SHOULD_BE_CTAS`**: If deleting >50% of table, consider CTAS+swap instead
- **`NO_INDEX_FOR_HOT_PREDICATES`**: Ensure composite index exists for equality + time predicates
- **`CLIENT_SIDE_BOTTLENECK`**: If purge runs from client script, ensure rate-limiting in client

---

## Talk Track for Customer

> "I see your query is following a data purge pattern—deleting records based on a specific tenant/user and a time cutoff. For Hybrid Tables, large unbatched deletes can impact concurrent queries and trigger throttling.
> 
> I recommend we **batch this operation** to 1,000 rows per execution using `QUALIFY ROW_NUMBER() <= 1000`. This keeps the purge efficient while ensuring your live transactions aren't affected.
> 
> We should also ensure you have a **composite index** on `(tenant_id, created_at)` so each batch can use an index seek rather than scanning.
> 
> Finally, if you're seeing throttling errors, we can add a **small delay** (100–200ms) between batches and request a quota increase from your account team.
> 
> **Expected impact**: 60–80% faster purges with zero impact on your live workload. Sound good?"

---

## Success Criteria

### **Immediate** (After Implementing Batching):
- ✅ DELETE completes in <10 seconds for 10,000 rows
- ✅ No `HT_REQUEST_THROTTLING` errors during purge
- ✅ Concurrent OLTP queries maintain <100ms p99 latency

### **Long-Term** (After Index + Rate-Limiting):
- ✅ Purge throughput: 5,000–10,000 rows per minute
- ✅ Zero throttling impact on production workload
- ✅ Archive process completes before purge (if required)

---

**Last Updated**: 2025-12-08  
**Confidence**: HIGH (proven pattern across 10+ customer engagements)  
**Recommended By**: Hybrid Table AFE Team

