# LOW_CARDINALITY_INDEX

## What This Means

The **LOW_CARDINALITY_INDEX** finding means an index on this Hybrid Table has a **leading column with very few distinct values** (e.g., a `STATUS` column with only 3 values: 'active', 'inactive', 'pending'). These indexes are usually **ineffective** at reducing I/O and may not be worth their write overhead.

---

## Why This Matters

HT indexes are most effective when they can **narrow down the search space significantly**. A low-cardinality leading column means:

- **Poor selectivity**: Many rows share the same key value
- **Large index buckets**: The engine still has to scan many rows even after the index lookup
- **Wasted write overhead**: Every INSERT/UPDATE/MERGE must maintain the index, but queries don't benefit much

**Example:**
- **Good index:** `INDEX ON (CUSTOMER_ID)` where `CUSTOMER_ID` has 10 million distinct values → each lookup touches 1-10 rows
- **Bad index:** `INDEX ON (COUNTRY)` where `COUNTRY` has 50 distinct values → each lookup touches 200,000+ rows (if 10M rows total)

---

## Real-World Context

**Field Experience:**

- **Multi-region App**: Customer created an index `(REGION, CUSTOMER_ID)` thinking "we always filter by region first". But `REGION` had only 5 values (us-east, us-west, eu, asia, global) → index lookups still scanned ~20% of the table per region. After flipping to `(CUSTOMER_ID, REGION)`, lookups went from 80ms to 8ms.

- **Order Status Table**: Index on `(STATUS, ORDER_ID)` where `STATUS` ∈ {pending, completed, cancelled} → 95% of orders were 'completed', so the index was effectively useless for the majority of lookups. Removing `STATUS` from the leading position and using `(ORDER_ID, STATUS)` improved query efficiency.

**Common Pattern:**
- Indexes mimic the conceptual "hierarchy" of the data (region → country → customer) rather than the actual **selectivity** of the query predicates
- Low-cardinality "metadata" columns (status, type, category) are placed first, thinking "we always filter by this"

---

## How to Fix It

### Step 1: Identify Low-Cardinality Columns

Check the distinct count of indexed columns:

```sql
-- For each indexed column, check cardinality
SELECT
  COUNT(DISTINCT REGION) AS region_cardinality,
  COUNT(DISTINCT CUSTOMER_ID) AS customer_id_cardinality,
  COUNT(*) AS total_rows
FROM CUSTOMER_STATE_HT;

-- Example output:
-- region_cardinality: 5
-- customer_id_cardinality: 10,000,000
-- total_rows: 10,000,000
```

**Rule of Thumb:**
- **High cardinality:** Distinct count ≈ total rows (good for leading index column)
- **Medium cardinality:** Distinct count = 1-10% of total rows (acceptable for secondary position)
- **Low cardinality:** Distinct count < 0.1% of total rows (poor for any index position)

---

### Step 2: Reorder or Drop the Index

**Option A: Reorder Composite Index (Move High-Cardinality First)**

```sql
-- Before: Low-cardinality leading column
-- INDEX (REGION, CUSTOMER_ID)

-- After: High-cardinality leading column
DROP INDEX IDX_REGION_CUSTOMER;
CREATE INDEX IDX_CUSTOMER_REGION
  ON CUSTOMER_STATE_HT (CUSTOMER_ID, REGION);
```

**Why this works:**
- `CUSTOMER_ID` is highly selective → index lookup narrows to 1 row immediately
- `REGION` is still in the index for rare cases where you filter by both

**Query Pattern Compatibility:**
- ✅ `WHERE CUSTOMER_ID = ?` → Uses index effectively
- ✅ `WHERE CUSTOMER_ID = ? AND REGION = ?` → Uses full index
- ❌ `WHERE REGION = ?` → Cannot use this index (wrong leading column)

If you truly need to filter by `REGION` alone frequently, consider a **separate single-column index** on a column with higher cardinality in that query pattern, or accept that region-only queries will be slower.

---

**Option B: Drop the Index Entirely**

```sql
-- If the index provides no measurable benefit, drop it
DROP INDEX IDX_REGION_CUSTOMER;
```

**When to drop:**
- Leading column has <100 distinct values
- Runtime metrics show no improvement in bytes scanned or latency
- Write volume is high and index maintenance is expensive

---

### Step 3: Validate Improvement

After reordering or dropping, re-run representative queries and check:

```sql
-- Test query
SELECT * FROM CUSTOMER_STATE_HT WHERE CUSTOMER_ID = 'C12345';

-- Check Query Profile:
-- - "Bytes Scanned" should be minimal (KB, not MB/GB)
-- - "Rows Produced" should match expected result set size
-- - Look for "Index Scan" (not "Table Scan" or "Range Scan" over large partition)
```

---

## Talk Track for Customers

> **Customer:** "We created an index on REGION first because our queries always filter by region. Why are you saying it's a bad index?"
>
> **You:** "It's not that the index is wrong conceptually, but it's not selective enough to help performance. Here's the issue:
>
> - You have 5 regions and 10 million rows
> - Each region has ~2 million rows
> - When you query `WHERE REGION = 'us-east'`, the index says 'here are 2 million rows in us-east'
> - The engine still has to scan those 2 million rows to find the specific customer
>
> If you flip the index to `(CUSTOMER_ID, REGION)`:
> - Query `WHERE CUSTOMER_ID = 'C12345'` → index says 'here's the 1 row for C12345' → 8ms
> - Query `WHERE CUSTOMER_ID = 'C12345' AND REGION = 'us-east'` → same fast lookup
>
> The trade-off:
> - ✅ Customer-specific queries (99% of your traffic): 10x faster
> - ⚠️ Region-only queries (1% of your traffic): Not accelerated by this index
>
> For the region-only use case, you can either accept slower performance (it's rare) or create a separate standard table / materialized view for that analytic pattern."

---

## When Low-Cardinality Indexes Are OK

There are rare cases where a low-cardinality leading column is acceptable:

1. **Filter + Sort Pattern**
   ```sql
   -- Index: (STATUS, CREATED_AT)
   SELECT * FROM ORDERS_HT
   WHERE STATUS = 'pending'
   ORDER BY CREATED_AT DESC
   LIMIT 10;
   ```
   - If `STATUS` is always used with `ORDER BY CREATED_AT`, the index can help with sorting
   - But this is better suited for a standard table with clustering

2. **Very Small Tables**
   - If the entire table is <10K rows, cardinality doesn't matter much
   - But then you probably don't need HT at all

3. **Composite with High-Cardinality Suffix**
   - If the low-cardinality column is truly always part of the filter AND combined with high-cardinality columns:
   ```sql
   -- INDEX (TENANT_ID, STATUS, ORDER_ID)
   -- Only if queries ALWAYS filter by TENANT_ID first (high cardinality)
   ```

**Rule of Thumb:**
If in doubt, put high-cardinality columns first.

---

## Common Questions / Objections

### Q: Why are you recommending dropping low-cardinality indexes?

Indexes on low-cardinality leading columns (e.g. STATUS, COUNTRY in a global table) usually don't filter enough rows to be useful:

- Many rows share the same key, so the engine still touches large portions of the table
- You still pay the maintenance cost on every write

The tool recommends dropping or redesigning these when it sees:
- Very small distinct_count on the index's leading column, and
- Little or no observed runtime benefit from that index

If those columns are business-critical filters in analytics, they're usually better handled by standard tables and columnar pruning, not as leading HT index keys.

---

## Impact

- **Latency Impact:** MEDIUM - Reordering can improve latency 5-10x for high-cardinality lookups
- **Write Performance Impact:** LOW-MEDIUM - Dropping unused indexes reduces write overhead
- **Storage Impact:** LOW - Indexes are relatively small, but every bit helps

---

## Estimated Improvement

**After Reordering or Dropping:**
- **Latency Reduction:** 3-10x for queries that benefit from high-cardinality leading columns
- **Write Throughput:** 5-15% improvement (less index maintenance)
- **HT Quota Headroom:** 2-3x (less wasted I/O)

---

## See Also

- [NO_INDEX_FOR_HOT_PREDICATES](./NO_INDEX_FOR_HOT_PREDICATES.md) - Missing indexes entirely
- [COMPOSITE_INDEX_MISALIGNED](./COMPOSITE_INDEX_MISALIGNED.md) - Index order doesn't match query predicates
- [HT_INDEXES_NOT_USED_RUNTIME](./HT_INDEXES_NOT_USED_RUNTIME.md) - Index exists but isn't effective

