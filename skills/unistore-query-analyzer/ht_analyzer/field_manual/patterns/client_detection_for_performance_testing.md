# Client Detection for Performance Testing Guidance

This guide shows how to detect **what type of client** executed a query (Snowsight, JMeter, programmatic driver) and provide appropriate performance testing guidance.

---

## What This Solves

**Problem:** Users often analyze queries from Snowsight/interactive UIs and draw conclusions about production performance, not realizing that:
- Interactive UIs add overhead not present in programmatic access
- Single-query tests don't reflect sustained load behavior
- Proper load testing requires JMeter or similar tools

**Solution:** Automatically detect the client type and show contextual guidance:
- ⚠️ "This was run from Snowsight - not a real perf test"
- ✅ "This is a JMeter load test - check AGGREGATE_QUERY_HISTORY for p95/p99"
- ℹ️ "For production validation, use JMeter with sustained load"

---

## How to Detect Client Type

### Step 1: Enrich Metadata with Client Info

Add client detection fields from `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`:

```python
def get_query_metadata(query_uuid: str):
    # Existing Snowhouse query
    metadata, error = _get_snowhouse_metadata(query_uuid)
    if error:
        return None, error

    # Enrich with client info from QUERY_HISTORY
    try:
        qh_result = session.sql(f"""
            SELECT
                APPLICATION_NAME,
                CLIENT_DRIVER,
                CLIENT_VERSION,
                CLIENT_ENV,
                QUERY_TAG
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE QUERY_ID = '{query_uuid}'
            LIMIT 1
        """).collect()

        if qh_result:
            row = qh_result[0]
            metadata["APPLICATION_NAME"] = row["APPLICATION_NAME"]
            metadata["CLIENT_DRIVER"] = row["CLIENT_DRIVER"]
            metadata["CLIENT_VERSION"] = row["CLIENT_VERSION"]
            metadata["CLIENT_ENV"] = row["CLIENT_ENV"]
            metadata["QUERY_TAG"] = row["QUERY_TAG"]
    except Exception:
        # Fail soft; client info is nice-to-have
        pass

    return metadata, None
```

### Step 2: Classify the Client

Create a helper to categorize client types:

```python
def classify_client(metadata: dict) -> str:
    """
    Classify client type based on application name, driver, and query tag.
    
    Returns:
        'jmeter' - Automated load test (reliable perf data)
        'interactive_ui' - Snowsight/worksheet (NOT reliable for perf)
        'driver' - Programmatic access (somewhat reliable)
        'unknown' - Can't determine
    """
    app = (metadata.get("APPLICATION_NAME") or "").lower()
    drv = (metadata.get("CLIENT_DRIVER") or "").lower()
    tag = (metadata.get("QUERY_TAG") or "").lower()

    # Explicit JMeter tagging is best
    if "jmeter" in app or "jmeter" in drv or "ht_jmeter" in tag:
        return "jmeter"

    # Snowsight / worksheets / UI
    if "snowsight" in app or "worksheet" in app or "ui" in app:
        return "interactive_ui"

    # Generic programmatic drivers
    if any(x in drv for x in ["jdbc", "odbc", "python", "node", "go", "dotnet"]):
        return "driver"

    return "unknown"
```

### Step 3: Show Contextual Guidance

In your UI (Executive Summary or similar):

```python
def show_performance_testing_guidance(metadata: dict):
    client_type = classify_client(metadata)

    if client_type == "interactive_ui":
        st.warning(
            "⚠️ **Interactive UI Query Detected**\n\n"
            "This query was executed from an interactive UI (e.g., Snowsight/worksheet). "
            "These environments add overhead and are **not representative** for high-QPS Hybrid Table workloads.\n\n"
            "**For realistic performance testing:**\n"
            "- Use a load generator such as **JMeter** from an in-region VM\n"
            "- Run sustained load (15+ minutes with 5-minute warmup)\n"
            "- Analyze results via `AGGREGATE_QUERY_HISTORY` for p50/p95/p99\n\n"
            "📖 See: `patterns/performance_testing_with_jmeter.md`"
        )
    
    elif client_type == "driver":
        st.info(
            "ℹ️ **Programmatic Driver Detected**\n\n"
            "This query was executed via a programmatic driver. For full performance validation:\n"
            "- Use a load generator (JMeter/Locust) with **sustained traffic**\n"
            "- Review metrics in `AGGREGATE_QUERY_HISTORY` (not `QUERY_HISTORY`)\n"
            "- Ensure bound variables are used for plan cache reuse\n\n"
            "📖 See: `patterns/performance_testing_with_jmeter.md`"
        )
    
    elif client_type == "jmeter":
        st.success(
            "✅ **Automated Performance Test Detected**\n\n"
            "This query appears to be part of an automated performance test (JMeter/tagged load).\n\n"
            "**Next Steps:**\n"
            "- Use `AGGREGATE_QUERY_HISTORY` to analyze p50/p95/p99 latency\n"
            "- Filter by `QUERY_TAG` or `QUERY_PARAMETERIZED_HASH`\n"
            "- Compare client-side (JMeter) and server-side (Snowflake) metrics\n"
            "- Discard first 5 minutes as warmup\n\n"
            "📖 See: `patterns/performance_testing_with_jmeter.md`"
        )
    
    else:
        st.info(
            "ℹ️ **Client Type Unknown**\n\n"
            "For serious Hybrid Table performance testing:\n"
            "- Use a dedicated load generator (e.g., JMeter) in the same cloud region\n"
            "- Set `QUERY_TAG = 'ht_jmeter_perf'` for easy filtering\n"
            "- Analyze via `AGGREGATE_QUERY_HISTORY`\n\n"
            "📖 See: `patterns/performance_testing_with_jmeter.md`"
        )
```

---

## Best Practice: Tag Your JMeter Tests

To make detection reliable, **always set a QUERY_TAG** in JMeter tests:

### Option 1: JDBC Connection String

```
jdbc:snowflake://<account>.snowflakecomputing.com/
  ?warehouse=PERF_TEST_WH
  &db=TESTDB
  &schema=PUBLIC
  &query_tag=ht_jmeter_perf
```

### Option 2: Session Alter in JMeter Setup

In your JMeter "setUp Thread Group", add a JDBC Request:

```sql
ALTER SESSION SET QUERY_TAG = 'ht_jmeter_perf';
```

Then your classifier can reliably detect:

```python
if "ht_jmeter_perf" in tag:
    return "jmeter"
```

---

## Query to Analyze Your Performance Tests

Once tagged, analyze your JMeter run:

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Aggregate latency percentiles by query type
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT
    QUERY_PARAMETERIZED_HASH,
    COUNT(*) AS EXECUTIONS,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) AS P50_MS,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) AS P95_MS,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) AS P99_MS,
    AVG(TOTAL_ELAPSED_TIME) AS AVG_MS,
    MAX(TOTAL_ELAPSED_TIME) AS MAX_MS
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.AGGREGATE_QUERY_HISTORY
WHERE QUERY_TAG = 'ht_jmeter_perf'
  AND START_TIME >= DATEADD(HOUR, -1, CURRENT_TIMESTAMP())
  AND QUERY_PARAMETERIZED_HASH IS NOT NULL
GROUP BY QUERY_PARAMETERIZED_HASH
ORDER BY EXECUTIONS DESC;
```

#### 👤 For Customer Use

```sql
-- Customer: Aggregate latency percentiles by query type
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT
    QUERY_PARAMETERIZED_HASH,
    COUNT(*) AS EXECUTIONS,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) AS P50_MS,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) AS P95_MS,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) AS P99_MS,
    AVG(TOTAL_ELAPSED_TIME) AS AVG_MS,
    MAX(TOTAL_ELAPSED_TIME) AS MAX_MS
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_TAG = 'ht_jmeter_perf'
  AND START_TIME >= DATEADD(HOUR, -1, CURRENT_TIMESTAMP())
  AND QUERY_PARAMETERIZED_HASH IS NOT NULL
GROUP BY QUERY_PARAMETERIZED_HASH
ORDER BY EXECUTIONS DESC;
```

---

## Benefits

**For AFEs:**
- Automatically educate customers on proper perf testing
- Prevent "Snowsight is slow" misconceptions
- Point to right resources based on context

**For Customers:**
- Clear guidance on when results are meaningful
- Links to proper testing methodology
- Reduced confusion about performance

---

## Related Guides

See also:
- `patterns/performance_testing_with_jmeter.md` - Complete JMeter testing guide
- `findings/NO_BOUND_VARIABLES.md` - Plan cache reuse for performance

---

**Last Updated:** 2025-12-06  
**Contributor:** AFE / SE Field Manual (Hybrid Tables)  
**Field Validated:** Yes

