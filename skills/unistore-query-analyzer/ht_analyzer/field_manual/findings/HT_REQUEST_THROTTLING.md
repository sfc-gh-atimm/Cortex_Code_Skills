# HT_REQUEST_THROTTLING

## What This Means

The **HT_REQUEST_THROTTLING** finding means that Hybrid Table request throttling was observed for this workload. This indicates the **account or database is hitting HT request quotas** under load.

---

## Why This Matters

Hybrid Tables have **request-level quotas** to manage capacity and ensure fair resource allocation across accounts. When throttling occurs:

- **Queries are delayed** (queued until quota is available)
- **Latency becomes unpredictable** (p95/p99 can spike significantly)
- **SLA violations** (what should be a 20ms query becomes 200ms+ under load)

**This is NOT a query optimization issue** — it's a capacity/quota issue.

---

## Real-World Context

**Field Experience:**

- **POC Throttling**: Customer ran a load test with 500 concurrent threads hitting HT at 5000 QPS → saw "HT request throttling" after ~2 minutes → p95 latency spiked from 30ms to 800ms → test was declared a failure. **Fix:** Requested an isolated HT quota for the POC database, re-ran test at same QPS with no throttling → p95 stayed at 35ms.

- **Shared Database Throttling**: Production HT workload shared a database with analytic queries that occasionally scanned HT tables for reporting → analytic scans consumed quota → operational API started throttling during business hours. **Fix:** Separated operational HT into a dedicated database with its own quota; moved analytic HT snapshots to standard tables.

**Common Pattern:**
- POCs run on default (shared) quotas without isolation
- HT is used for both operational (point lookups) and analytic (scans) patterns in the same database
- No one monitors HT quota usage until latency degrades under load

---

## How to Fix It

### Step 1: Verify Throttling is the Root Cause

Check runtime metrics to confirm throttling is the issue.

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Query Snowhouse telemetry for HT throttling indicators
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT
  UUID,
  QUERY_TEXT,
  TOTAL_ELAPSED_TIME,
  QUEUED_PROVISIONING_TIME,
  QUEUED_REPAIR_TIME,
  QUEUED_OVERLOAD_TIME,
  ACCESS_KV_TABLE
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE UUID = '{{QUERY_UUID}}';
```

#### 👤 For Customer Use

```sql
-- Customer: Query ACCOUNT_USAGE for throttling indicators
-- Note: ACCOUNT_USAGE has 45min-3hr latency; recent queries may not appear yet
SELECT
  QUERY_ID,
  QUERY_TEXT,
  TOTAL_ELAPSED_TIME,
  QUEUED_PROVISIONING_TIME,
  QUEUED_REPAIR_TIME,
  QUEUED_OVERLOAD_TIME
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_ID = '{{QUERY_UUID}}';
```

**Look for:**
- `QUEUED_OVERLOAD_TIME` > 0 (query was delayed due to quota/overload)
- High `TOTAL_ELAPSED_TIME` relative to execution time (most time spent waiting, not running)

---

### Step 2: Request an Increased or Isolated HT Quota

**For POCs:**
Contact Snowflake support or your account team to request:
- **Isolated HT quota** for the POC database
- **Increased quota** if you're testing at high QPS (e.g., 5000+ QPS)

**Sample Request:**
> "We're running a Hybrid Tables POC and are seeing HT request throttling under load testing (5000 QPS). Can we get an isolated HT quota for database `POC_HT_DB` to ensure fair capacity allocation during the evaluation period?"

**For Production:**
- Work with Snowflake to right-size HT quotas based on your expected workload
- Consider **dedicated databases** for high-QPS HT workloads vs mixed-use databases

---

### Step 3: Reduce Unnecessary HT Request Volume

Not all queries should hit HT. Review your workload for inefficiencies:

**A) Analytic Queries on HT**
```sql
-- BAD: Analytic scan of HT (burns quota)
SELECT STATUS, COUNT(*)
FROM ORDERS_HT
WHERE CREATED_AT >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY STATUS;

-- GOOD: Same query on a standard table snapshot
SELECT STATUS, COUNT(*)
FROM ORDERS_SNAPSHOT  -- Standard table, refreshed hourly
WHERE CREATED_AT >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY STATUS;
```

**B) Full-Table Scans**
```sql
-- BAD: Debug query with no WHERE clause (scans entire HT)
SELECT * FROM CUSTOMER_STATE_HT LIMIT 100;

-- GOOD: Targeted lookup with indexed predicate
SELECT * FROM CUSTOMER_STATE_HT
WHERE CUSTOMER_ID = 'C12345';
```

**C) Inefficient Queries (No Indexes)**
- If queries scan many rows due to missing indexes, they consume more quota
- See [NO_INDEX_FOR_HOT_PREDICATES](./NO_INDEX_FOR_HOT_PREDICATES.md)

---

### Step 4: Separate Operational and Analytic Workloads

**Pattern: Dedicated HT Database for Operational Workloads**

```sql
-- Create a dedicated database for HT operational workloads
CREATE DATABASE HT_OPERATIONAL;

-- Move operational HT tables here
CREATE OR REPLACE HYBRID TABLE HT_OPERATIONAL.PUBLIC.CUSTOMER_STATE
  ...;

-- Keep analytic workloads in a separate database
CREATE DATABASE ANALYTICS;

-- Use Dynamic Tables or standard tables for reporting
CREATE DYNAMIC TABLE ANALYTICS.PUBLIC.CUSTOMER_SUMMARY
  TARGET_LAG = '15 minutes'
  WAREHOUSE = ANALYTICS_WH
AS
SELECT * FROM HT_OPERATIONAL.PUBLIC.CUSTOMER_STATE;
```

**Benefits:**
- Operational HT gets isolated quota (no interference from analytic scans)
- Analytic workloads use standard tables (optimized for scans, no HT quota impact)

---

## Talk Track for Customers

> **Customer:** "Our load test is failing because of HT throttling. Doesn't this mean HT can't handle our workload?"
>
> **You:** "Not at all. HT throttling is a quota/capacity issue, not a fundamental performance limit. Here's what's happening:
>
> - **Your queries are fast** (20-30ms when they run)
> - **The account is hitting a default quota** (designed for mixed workloads across many databases)
> - **Under POC load, you're hitting that quota ceiling** → queries get queued → latency spikes
>
> The fix is straightforward:
> 1. **Request an isolated quota** for your POC database (standard for POCs)
> 2. **Verify you're not burning quota on analytic scans** (move those to standard tables)
> 3. **Re-run the load test** with proper quota allocation
>
> In production, Snowflake sizes quotas based on your actual workload. For POCs, we just need to request the right allocation upfront. I've seen this pattern many times — once quotas are set correctly, HT handles 10K+ QPS with no throttling."

---

## When Throttling is NOT the Issue

Sometimes latency issues are misdiagnosed as throttling. Check for:

1. **Client-Side Bottlenecks**
   - Large result sets
   - Network latency (out-of-region clients)
   - See [CLIENT_SIDE_BOTTLENECK](./CLIENT_SIDE_BOTTLENECK.md)

2. **Query Inefficiency**
   - Missing indexes
   - Full table scans
   - See [NO_INDEX_FOR_HOT_PREDICATES](./NO_INDEX_FOR_HOT_PREDICATES.md)

3. **Warehouse Queueing** (Not HT Throttling)
   - Warehouse is undersized or overloaded
   - Check `QUEUED_PROVISIONING_TIME` vs HT-specific throttling metrics

**How to Tell:**
- **HT throttling:** High `QUEUED_OVERLOAD_TIME`, queries wait before execution starts
- **Warehouse queueing:** High `QUEUED_PROVISIONING_TIME`, warehouse is waiting for compute
- **Query inefficiency:** Low queue time, but high execution time (scan-heavy query)

---

## Common Questions / Objections

### Q: What does HT request throttling mean? How do I fix it?

Hybrid Table request throttling means the account/database is hitting HT request quotas under load.

This is a capacity/quota issue, not a query optimization issue.

**The Fix:**
1. For POCs and production workloads, request an increased and/or isolated Hybrid Table quota for the target database
2. Also verify you are not issuing unnecessary I/O-heavy queries on HT (e.g., analytic scans or bulk updates)
3. Consider separating operational HT workloads from analytic workloads to reduce overall HT request volume

---

## Impact

- **Latency Impact:** CRITICAL - Can increase p95/p99 from <50ms to 500ms+ under throttling
- **Reliability Impact:** HIGH - Unpredictable latency makes SLA compliance impossible
- **User Experience Impact:** HIGH - Throttling = degraded service during peak load

---

## Estimated Improvement

**After Quota Adjustment:**
- **Throttling Incidents:** 100% elimination (with proper quota sizing)
- **Latency Stability:** p95/p99 return to expected levels (<50ms for point lookups)
- **Sustained QPS:** 5-10x higher sustainable load without degradation

---

## See Also

- [Performance Testing with JMeter](../patterns/performance_testing_with_jmeter.md) - How to test at scale without hitting quotas
- [NO_INDEX_FOR_HOT_PREDICATES](./NO_INDEX_FOR_HOT_PREDICATES.md) - Reduce quota waste by optimizing queries
- [ANALYTIC_WORKLOAD_ON_HT](./ANALYTIC_WORKLOAD_ON_HT.md) - Move analytic scans off HT to reduce quota pressure

