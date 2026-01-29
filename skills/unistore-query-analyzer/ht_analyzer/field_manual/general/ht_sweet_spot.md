# Hybrid Tables Sweet Spot

## When to Use Hybrid Tables

Hybrid Tables excel at **OLTP-style workloads** with these characteristics:

###✅ Perfect Use Cases

1. **Point Lookups** (Single Row Access)
   - `WHERE primary_key = :value`
   - Sub-100ms response time requirements
   - High QPS (100-10,000+ queries per second)
   - Examples: Order lookup, user profile fetch, session retrieval

2. **Small Range Queries** (<1000 rows)
   - `WHERE user_id = :id AND timestamp > :recent`
   - Recent data access patterns
   - Indexed predicates with high selectivity
   - Examples: Recent transactions, active sessions, pending tasks

3. **Transactional Workloads**
   - INSERT, UPDATE, DELETE operations
   - Row-level locking requirements
   - ACID guarantees with immediate consistency
   - Examples: Shopping cart, inventory updates, user state

4. **Micro-Services / Application State**
   - API backends serving user requests
   - Caching layer for hot data
   - Session stores, feature flags
   - Real-time application data

---

## When NOT to Use Hybrid Tables

###❌ Poor Fit Scenarios

1. **BI / Reporting Queries**
   - Aggregations over millions of rows
   - GROUP BY, window functions on large datasets
   - Dashboard refresh queries
   - → **Use Standard Tables + Materialized Views**

2. **Analytical Scans**
   - Reading >10K rows regularly
   - Full table scans for analytics
   - Complex JOIN operations across large tables
   - → **Use Standard Tables with clustering**

3. **Data Warehouse Workloads**
   - ETL/ELT batch processing
   - Historical data analysis
   - Star/Snowflake schema queries
   - → **Use Standard Tables**

4. **Large Result Sets**
   - Queries returning >10K rows
   - Bulk exports
   - Reports over time ranges
   - → **Use Standard Tables or MVs**

---

## Decision Matrix

| Workload Characteristic | Use HT? | Use Standard? |
|-------------------------|---------|---------------|
| Point lookups (PK = X) | ✅ Yes | ❌ Slow |
| Range <1K rows | ✅ Yes | ⚠️ OK |
| Range >10K rows | ❌ Slow | ✅ Yes |
| Aggregations | ❌ Slow | ✅ Yes |
| High-concurrency reads | ✅ Yes | ⚠️ OK |
| Frequent writes | ✅ Yes | ⚠️ OK |
| Real-time consistency | ✅ Yes | ⚠️ Eventual |
| Low latency (<100ms) | ✅ Yes | ❌ Hard |
| BI/Dashboard queries | ❌ Slow | ✅ Fast |

---

## Hybrid Architecture Pattern

**Best practice: Use BOTH table types together**

```sql
-- OLTP Layer: Hybrid Tables for transactional operations
CREATE HYBRID TABLE OLTP.ORDERS (
    order_id NUMBER PRIMARY KEY,
    customer_id NUMBER,
    order_timestamp TIMESTAMP,
    total_amount DECIMAL(10,2),
    status VARCHAR(50)
);

CREATE INDEX idx_customer ON OLTP.ORDERS (customer_id, order_timestamp);

-- Fast point lookups: <100ms
SELECT * FROM OLTP.ORDERS WHERE order_id = :id;

-- Fast user history (recent): <500ms
SELECT * FROM OLTP.ORDERS 
WHERE customer_id = :id 
AND order_timestamp >= CURRENT_DATE - 30
ORDER BY order_timestamp DESC
LIMIT 100;

-- Analytical Layer: Materialized View for reporting
CREATE MATERIALIZED VIEW REPORTING.DAILY_ORDERS AS
SELECT 
    DATE_TRUNC('day', order_timestamp) as order_date,
    customer_id,
    COUNT(*) as order_count,
    SUM(total_amount) as daily_revenue,
    AVG(total_amount) as avg_order_value
FROM OLTP.ORDERS
GROUP BY 1, 2;

-- Fast aggregations: 1-2s
SELECT 
    order_date,
    SUM(daily_revenue) as total_revenue
FROM REPORTING.DAILY_ORDERS
WHERE order_date >= '2024-01-01'
GROUP BY 1
ORDER BY 1;
```

---

## Performance Guidelines

### Expected Query Times

**Hybrid Tables (with proper indexes):**
- Point lookup: 10-100ms
- Small range (<100 rows): 100-500ms
- Medium range (100-1000 rows): 500ms-2s
- Large range (>1000 rows): 2-30s (consider MV instead)

**Standard Tables:**
- Point lookup: 500ms-5s (not optimized for this)
- Aggregations: 1-10s (excellent)
- Large scans: 5-60s (with clustering)
- BI queries: 2-30s (excellent with MVs)

---

## Capacity Guidelines

**Table Size:**
- Sweet spot: 100K - 500M rows
- Works well: Up to few billion rows with good index design
- Struggles: >1TB single table (consult Product team)

**QPS (Queries Per Second):**
- Single warehouse (XS): 100-500 QPS (point lookups)
- Scale-out (multi-XS): 1000-10,000+ QPS
- Bottleneck: Usually FDB capacity, not warehouse

**Write Throughput:**
- Batch inserts: 10K-100K rows/sec
- Single-row writes: 1K-10K/sec
- Mixed read/write: Balance based on contention

---

## Common Anti-Patterns

###❌ "Let's put everything in Hybrid Tables"
- **Problem**: Forces analytical queries onto row-based storage
- **Fix**: Split OLTP (HT) and analytics (Standard + MV)

###❌ "No indexes, just create the HT"
- **Problem**: Full table scans, worse than standard tables
- **Fix**: Always add PK + secondary indexes for query patterns

###❌ "BI dashboard directly on HT"
- **Problem**: Slow aggregations, expensive, high latency
- **Fix**: Create MV for dashboard, query MV instead

###❌ "Reporting query on HT is slow, let's make warehouse XL"
- **Problem**: Warehouse size doesn't help analytical scans on HT
- **Fix**: Use standard table/MV for reporting

---

## Migration Guidance

**From RDBMS (MySQL, Postgres) to Snowflake:**

✅ **DO migrate to HT if:**
- Your app has OLTP patterns (point lookups, small ranges)
- You need row-level locking
- Sub-second latency requirements
- High-concurrency APIs

⚠️ **DON'T migrate to HT if:**
- Your app is mostly analytical (BI, reporting)
- You don't need ACID semantics
- Queries scan large portions of tables
- Low QPS, batch-oriented workload

**Hybrid approach often best:**
- HT for transactional tables (orders, users, sessions)
- Standard tables for dimension tables, historical data
- MVs for reporting and dashboards

---

## Field-Tested Rules of Thumb

1. **"If you're not sure, test both"** - POC with 10-20% of data
2. **"Point lookups = HT, Scans = Standard"** - 90% of the time
3. **"Always index HT"** - No exceptions for production
4. **"Scale out, not up"** - Multiple XS > One XL for HT
5. **"BI on MV, not HT"** - Create MVs for dashboards

---

**Last Updated:** 2025-12-06  
**Contributor:** Unistore Team  
**Field Validated:** Yes (100+ customer conversations)

