# WAREHOUSE_OVERSIZED_FOR_HT

## What This Means

The **WAREHOUSE_OVERSIZED_FOR_HT** finding means this Hybrid Table query is running on a warehouse larger than XS (Extra Small). For pure HT row-store workloads (point lookups, small-range scans), larger warehouses typically do **not** reduce single-query latency but **do** increase costs.

---

## Why This Matters

Hybrid Table performance is dominated by:
- **Fast index probes** (primary/secondary indexes on FDB)
- **Small row-store operations** (fetch a few rows, narrow range scans)

Unlike analytic queries that benefit from massive parallelism, HT lookups:
- Touch a small number of KV pairs
- Don't benefit significantly from additional compute nodes
- Are already optimized for sub-50ms latency on XS warehouses

**What happens with larger warehouses:**
- **No latency improvement** for typical HT patterns
- **Higher credit consumption** (paying for unused parallelism)
- **Misleading perf conclusions** ("we tried 2XL and it was still slow, so HT must be broken")

---

## Real-World Context

**Field Experience:**
- **POC Testing**: Teams routinely test HT on Large or X-Large warehouses (same as their analytic workloads) and report "HT is only marginally faster than standard tables" → when they switch to XS with proper indexing, latency drops 3-5x and costs drop 80%
- **Production Deployment**: A customer running HT API lookups on Medium warehouse saw no p95 improvement vs XS, but was burning 4x the credits. After switching to XS with multi-cluster auto-scaling, they achieved better concurrency handling at 25% of the cost

**Common Pattern:**
- HT workload shares a warehouse with standard table analytics
- "Bigger is safer" mentality from traditional OLAP carries over to OLTP patterns
- No one questions warehouse sizing until the bill arrives

---

## How to Fix It

### Step 1: Separate Operational and Analytic Warehouses

```sql
-- Dedicated XS warehouse for HT operational workloads
CREATE WAREHOUSE HT_OLTP_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  MIN_CLUSTER_COUNT = 1
  MAX_CLUSTER_COUNT = 5      -- Scale out for concurrency, not up
  SCALING_POLICY = 'STANDARD';

-- Keep larger warehouses for analytic queries
CREATE WAREHOUSE ANALYTICS_WH
  WAREHOUSE_SIZE = 'LARGE'
  AUTO_SUSPEND = 300
  AUTO_RESUME = TRUE;
```

### Step 2: Route HT Queries to the Right Warehouse

**In application code:**
```python
# Set session to use HT-specific warehouse
session.sql("USE WAREHOUSE HT_OLTP_WH").collect()

# Run HT lookup
result = session.sql("""
    SELECT *
    FROM CUSTOMER_STATE_HT
    WHERE CUSTOMER_ID = ?
""", params=[customer_id]).collect()
```

**Or use query tags to identify workloads:**
```sql
ALTER SESSION SET QUERY_TAG = 'ht_api_lookup';
```

### Step 3: Enable Multi-Cluster for Concurrency (Not Size)

For high-QPS workloads:
- **Don't** increase warehouse size (S → M → L)
- **Do** enable multi-cluster scaling (1 → 3 → 5 clusters of XS)

```sql
ALTER WAREHOUSE HT_OLTP_WH SET
  MIN_CLUSTER_COUNT = 2
  MAX_CLUSTER_COUNT = 10
  SCALING_POLICY = 'STANDARD';  -- or ECONOMY for cost-sensitive workloads
```

This gives you:
- Same fast point-lookup latency (XS is sufficient)
- Horizontal scaling for thousands of concurrent requests
- Pay-per-query efficiency (auto-suspend keeps idle costs low)

### Step 4: Validate with Performance Testing

Run a proper load test (JMeter, in-region) comparing:

| Warehouse Size | p50 (ms) | p95 (ms) | p99 (ms) | Credits/Hour | Result          |
|----------------|----------|----------|----------|--------------|-----------------|
| XS (1 cluster) | 35       | 48       | 65       | 1            | ✅ Baseline     |
| SMALL          | 34       | 47       | 64       | 2            | ❌ No improvement, 2x cost |
| MEDIUM         | 35       | 49       | 67       | 4            | ❌ No improvement, 4x cost |
| XS (3 clusters)| 36       | 50       | 68       | 1-3 (dynamic)| ✅ Best for concurrency |

**Expected Outcome:**
- p50/p95/p99 stay roughly the same across warehouse sizes for HT point lookups
- Multi-cluster XS gives you the best cost/performance for high concurrency

---

## Talk Track for Customers

> **Customer:** "We're running our HT lookups on a Large warehouse because we want the best performance."
>
> **You:** "For Hybrid Tables, larger warehouses don't help single-query latency because HT operations are dominated by fast index probes, not parallelizable scans. What you'll see is:
> - XS: ~40ms p95
> - Large: ~40ms p95, but 8x the cost
>
> The recommended pattern is XS with multi-cluster scaling. That gives you:
> - Same latency for individual queries
> - Better handling of concurrent load (auto-scaling)
> - 80-90% lower costs for typical HT workloads
>
> Let's run a quick A/B test: same query on XS vs Large, measure p50/p95 over 1000 executions. I'll bet you see nearly identical latency but a big difference in the bill."

---

## When to Use Larger Warehouses

There are legitimate cases for **not** using XS:

1. **Mixed Workloads (HT + Standard Tables in same query)**
   - If your query joins HT with large standard tables, it's no longer a pure HT workload
   - The standard table scan benefits from parallelism → use Medium/Large

2. **Complex Transformations During Retrieval**
   - If you're doing heavy aggregations, window functions, or large joins after the HT lookup, those benefit from more compute
   - But consider refactoring: do the HT lookup on XS, then feed results to a separate analytic query

3. **Write-Heavy CTAS / Bulk Operations**
   - Large CTAS, bulk MERGE, or initial table loads benefit from larger warehouses
   - But those aren't latency-sensitive operational queries

**Bottom Line:**
If your query is a **pure HT point/small-range lookup**, stick with XS and scale out (multi-cluster), not up (warehouse size).

---

## Common Questions / Objections

### Q: Why are you suggesting XS warehouses for HT? Bigger should be faster, right?

For HT row-store workloads, bigger warehouses don't significantly reduce single-query latency:

- Latency is dominated by a small number of KV probes and index operations, not massive parallel scans
- All warehouse sizes use the same underlying hardware; "bigger" mostly buys you more parallelism, which helps scan-heavy analytics far more than it helps point lookups

**Recommended Pattern:**
- Start HT workloads on XS (or S) with multi-cluster for concurrency
- Use larger warehouses for analytic workloads (standard tables / MVs)

The tool warns when it sees HT-only queries on large warehouses to help avoid wasted credits and misleading perf conclusions ("we tried 2XL and it was still slow, so HT must be slow" when the real bottleneck is the query pattern).

---

## Impact

- **Cost Impact:** HIGH - Running HT on Medium vs XS = 4x higher costs for no latency benefit
- **Performance Impact:** NONE - Larger warehouses don't improve HT point-lookup latency
- **Reliability Impact:** MEDIUM - Using multi-cluster XS is better for handling concurrency spikes than a single large warehouse

---

## Estimated Improvement

- **Cost Reduction:** 50-80% (depending on current warehouse size)
- **Latency Change:** ~0% (XS is already optimal for HT)
- **Concurrency Improvement:** 2-5x (with multi-cluster scaling)

---

## See Also

- [Performance Testing with JMeter](../patterns/performance_testing_with_jmeter.md) - How to validate warehouse sizing with load tests
- [HT Sweet Spot](../general/ht_sweet_spot.md) - When to use HT vs standard tables
- [MIXED_HT_AND_STANDARD_TABLES](./MIXED_HT_AND_STANDARD_TABLES.md) - Why mixed queries need different sizing

