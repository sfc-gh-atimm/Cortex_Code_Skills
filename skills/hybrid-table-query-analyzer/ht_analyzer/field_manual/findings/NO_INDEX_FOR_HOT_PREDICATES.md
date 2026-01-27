# NO_INDEX_FOR_HOT_PREDICATES

## What This Means

The **NO_INDEX_FOR_HOT_PREDICATES** finding means this Hybrid Table query has equality predicates (e.g., `WHERE CUSTOMER_ID = ?`) on columns that are **not covered by any index** (primary or secondary). For HT, this usually forces larger scans and higher I/O than necessary.

---

## Why This Hurts Performance

Hybrid Tables are optimized for **indexed point lookups and narrow-range scans**. When your query filters on non-indexed columns:

- **No fast index probe** → engine must scan more rows to find matches
- **Higher FDB I/O** → touching more row-store pages than necessary
- **Higher latency** → what should be a <10ms lookup becomes 50-200ms
- **HT quota pressure** → burning through HT request quota on inefficient scans

**The Core Problem:**
Your query pattern says "operational lookup" (equality predicates, small result set), but the table structure says "scan" (no supporting index).

---

## Real-World Context

**Field Experience:**

- **E-commerce POC**: Customer built an HT "order status" table with a primary key on `ORDER_ID`, but their API looked up orders by `EMAIL` (no index) → every lookup scanned thousands of rows → p95 latency was 300ms instead of the target <50ms. After adding a secondary index on `EMAIL`, p95 dropped to 12ms.

- **Multi-tenant SaaS**: Application queried HT by `TENANT_ID` + `RECORD_ID`, but only had a primary key on `RECORD_ID` (globally unique) → every tenant lookup scanned all tenants → under load, HT throttling kicked in. After creating a composite index `(TENANT_ID, RECORD_ID)`, queries went from 150ms p95 to 8ms p95, and throttling disappeared.

**Common Pattern:**
- Table is designed with a "natural" primary key (e.g., UUID, auto-increment ID)
- Application lookups use a different access pattern (email, tenant+ID, external_reference)
- No one notices until QPS scales up or latency SLAs are tested

---

## How to Fix It

### Step 1: Identify the Hot Predicates

Look at your application's actual query patterns:

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: What columns are used in WHERE clauses for this table?
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT
  QUERY_TEXT,
  COUNT(*) AS execution_count
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE QUERY_TEXT ILIKE '%{{TABLE_NAME}}%'
  AND START_TIME >= DATEADD(day, -7, CURRENT_DATE())
GROUP BY QUERY_TEXT
ORDER BY execution_count DESC
LIMIT 20;
```

#### 👤 For Customer Use

```sql
-- Customer: What columns are used in WHERE clauses for this table?
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT
  QUERY_TEXT,
  COUNT(*) AS execution_count
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_TEXT ILIKE '%{{TABLE_NAME}}%'
  AND START_TIME >= DATEADD(day, -7, CURRENT_DATE())
GROUP BY QUERY_TEXT
ORDER BY execution_count DESC
LIMIT 20;
```

Extract the WHERE clause columns from the top queries.

---

### Step 2: Create Secondary Indexes for Hot Predicates

**Example: Single-Column Index**

```sql
-- Application queries by EMAIL frequently
CREATE INDEX IDX_CUSTOMER_EMAIL
  ON CUSTOMER_STATE_HT (EMAIL);
```

**Example: Composite Index (Order Matters!)**

```sql
-- Application queries by TENANT_ID + RECORD_ID
-- Put TENANT_ID first (most selective for multi-tenant)
CREATE INDEX IDX_TENANT_RECORD
  ON CUSTOMER_STATE_HT (TENANT_ID, RECORD_ID);
```

**Index Naming Convention:**
- `IDX_<table>_<col1>_<col2>` or `IDX_<purpose>` (e.g., `IDX_EMAIL_LOOKUP`)

---

### Step 3: Validate Index Effectiveness

After creating the index, re-run a representative query and check runtime metrics:

```sql
-- Enable query profiling
ALTER SESSION SET USE_CACHED_RESULT = FALSE;

-- Run the query
SELECT * FROM CUSTOMER_STATE_HT WHERE EMAIL = 'test@example.com';

-- Check the Query Profile in Snowsight:
-- - "Rows Produced" should be small (1-100, not thousands)
-- - "Bytes Scanned" should be minimal
-- - Look for "Index Scan" in the operator tree (not "Table Scan")
```

Or use SnowVI to validate index coverage:
- `index_coverage_pct` should be high (>80%)
- `index_effectiveness` should show the index was used

---

### Step 4: Avoid Over-Indexing

**Don't create indexes for:**
- Rarely-used admin queries or debugging patterns
- Low-cardinality leading columns (e.g., `STATUS` with 3 values)
- Columns wrapped in functions (`UPPER(email)`, `CAST(id AS STRING)`)

**Good Pattern:**
- 1-3 well-chosen indexes for high-QPS operational paths
- Covering primary key + 1-2 secondary indexes for common lookups

**Bad Pattern:**
- 10+ indexes "just in case"
- Indexes on every column (high write overhead)

---

## Talk Track for Customers

> **Customer:** "We have an index on ORDER_ID, so why is the query slow when we look up by EMAIL?"
>
> **You:** "The index on ORDER_ID only helps queries that filter by ORDER_ID. Your API is filtering by EMAIL, and there's no index on that column, so Snowflake has to scan more rows to find matches.
>
> Think of it like a phone book:
> - **Primary key (ORDER_ID):** Sorted by order number → fast to find order 12345
> - **No index on EMAIL:** Not sorted by email → have to flip through every page to find 'customer@example.com'
>
> For Hybrid Tables, we recommend creating secondary indexes on the columns your high-QPS APIs actually filter by. In your case:
> ```sql
> CREATE INDEX IDX_EMAIL_LOOKUP ON ORDERS_HT (EMAIL);
> ```
>
> After that, your EMAIL lookups will go from ~200ms to <20ms, because the engine can use a fast index probe instead of scanning."

---

## When NOT to Create an Index

1. **Low-Cardinality Columns**
   - Columns with few distinct values (e.g., `COUNTRY` with 10 values, `STATUS` with 3 values)
   - Index won't be selective enough to help

2. **Rarely-Used Queries**
   - Debug queries, one-off reports, admin scans
   - Don't justify the write overhead of maintaining an index

3. **Functions in Predicates**
   - `WHERE UPPER(email) = UPPER(?)` won't use an index on `email`
   - Fix the query pattern first (normalize at write time)

4. **Write-Heavy Tables**
   - If the table has 10x more writes than reads, HT may not be the right engine
   - Consider standard tables for write-heavy workloads

---

## Common Questions / Objections

### Q: My customer says they do have indexes. Why are you recommending creating indexes?

There are three different things at play:

**1) "An index exists" vs "an index helps this query"**
This finding is not checking if any index exists on the table. It is checking whether there is an index that actually lines up with the predicates used by this specific query. If the query filters on TENANT_ID and ORDER_ID but the only index is on STATUS, the existing index doesn't help this workload.

**2) "Index exists" vs "index is used effectively at runtime"**
Even when an index is defined on the right columns, the optimizer may not use it (or only partially use it) because of:
- Functions or casts on indexed columns (e.g. `UPPER(email)`, `CAST(id AS STRING)`)
- Composite index order not matching the leftmost equality predicates
- Very low-cardinality leading columns (e.g. STATUS) that don't narrow the search

In those cases, the analyzer correctly flags that the query isn't actually benefitting from the index.

**3) Different environment / table / version**
The customer may be looking at a dev or staging table with indexes, while the slow query is hitting a prod table without them, or a renamed table. The analyzer always uses the exact table + query UUID you pasted, so it can disagree with what someone sees in a different environment.

**Bottom Line:**
The recommendation doesn't mean "there are zero indexes anywhere". It means: *for this HT query and table, there is no index (or no effectively used index) that matches the predicates driving your latency.*

**Next Steps:**
1. Confirm you're looking at the same database/schema/table as the UUID
2. Compare the WHERE clause to the index definitions and column order
3. Remove functions/casts on indexed columns and fix type mismatches

---

### Q: Why do we need another index? Won't this hurt write performance and storage?

Yes, every additional HT index has a write and storage cost; that's why we only recommend them for hot predicates on latency-sensitive paths. The tool is suggesting one of two things:

1. Either there is no index at all for the high-QPS API predicates, so every request is effectively a scan
2. Or the existing index is structurally misaligned (wrong leading column, low cardinality, functions in predicates), so you're paying the maintenance cost without getting the read benefit

**In Practice:**
- Adding one or two well-chosen indexes on high-cardinality, always-present predicates usually reduces read cost (FDB I/O, bytes/row) enough to more than pay for the index maintenance on write workloads
- If the table is extremely write-heavy and the access pattern truly isn't selective, that's usually a smell that HT may not be the right engine for that specific table or use case anyway, and the tool will nudge you toward standard tables instead

**Good Pattern:**
- Keep a small number of highly targeted indexes for operational paths
- Push analytic/reporting workloads onto standard tables / MVs fed from the same pipeline

---

## Impact

- **Latency Impact:** HIGH - Can reduce p95 from 200ms to <20ms
- **Throughput Impact:** HIGH - More efficient queries → higher sustainable QPS
- **Cost Impact:** LOW - Small index maintenance cost, but large reduction in I/O waste

---

## Estimated Improvement

**After Adding Index:**
- **Latency Reduction:** 5-20x faster (200ms → 10-40ms)
- **Bytes Scanned:** 10-100x reduction
- **HT Quota Headroom:** 3-5x more capacity (less waste per query)

---

## See Also

- [HT_INDEXES_NOT_USED_RUNTIME](./HT_INDEXES_NOT_USED_RUNTIME.md) - Index exists but isn't being used
- [COMPOSITE_INDEX_MISALIGNED](./COMPOSITE_INDEX_MISALIGNED.md) - Index order doesn't match query pattern
- [LOW_CARDINALITY_INDEX](./LOW_CARDINALITY_INDEX.md) - Index on wrong column type
- [HT_WITHOUT_INDEXES](./HT_WITHOUT_INDEXES.md) - No indexes at all on the table

