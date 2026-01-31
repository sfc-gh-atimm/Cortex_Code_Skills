# SQL-Only Fallback Queries

Use these queries when the Python script cannot run (e.g., Snowpark unavailable).

## Step 1: Lookup Query & Check SnowVI Availability

This query resolves the deployment, checks if SnowVI data was persisted, and generates the SnowVI link.

```sql
WITH params AS (
    SELECT
        '<QUERY_UUID>'::string AS uuid,
        TO_TIMESTAMP(TO_NUMBER(LEFT('<QUERY_UUID>', 8), 'XXXXXXXX') * 60) AS uuid_ts
)
SELECT
    q.uuid AS QUERY_ID,
    q.deployment AS DEPLOYMENT,
    q.total_duration AS TOTAL_DURATION_MS,
    q.account_id AS ACCOUNT_ID,
    LEFT(q.description, 200) AS QUERY_PREVIEW,
    CASE 
        WHEN BITAND(q.flags, 1125899906842624) = 1125899906842624 
        THEN true ELSE false 
    END AS SNOWVI_DATA_AVAILABLE,
    CASE 
        WHEN BITAND(q.flags, 1125899906842624) = 1125899906842624 
        THEN temp.perfsol.get_deployment_link(q.deployment, q.uuid)
        ELSE NULL 
    END AS SNOWVI_LINK
FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_JPS_V q
JOIN params p ON q.uuid = p.uuid
WHERE q.created_on BETWEEN DATEADD(hour, -2, p.uuid_ts) AND DATEADD(hour, 1, p.uuid_ts)
LIMIT 1;
```

**If `SNOWVI_DATA_AVAILABLE = true`:**

Present the `SNOWVI_LINK` from the query result with download instructions:
```
To download the SnowVI JSON:
1. Open the SnowVI link above
2. Wait for the query profile to load
3. Click the "Export" button (top-right)
4. Select "Export as JSON"
5. Save the file locally
```

---

## Step 2: Resolve Deployment for UUID (Alternative)

```sql
WITH params AS (
    SELECT
        '<QUERY_UUID>'::string AS uuid,
        TO_TIMESTAMP(TO_NUMBER(LEFT('<QUERY_UUID>', 8), 'XXXXXXXX') * 60) AS uuid_ts
),
job_etl AS (
    SELECT deployment, 1 as priority
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V j
    JOIN params p ON j.uuid = p.uuid
    WHERE j.created_on BETWEEN DATEADD(hour, -3, p.uuid_ts) AND DATEADD(hour, 3, p.uuid_ts)
    QUALIFY ROW_NUMBER() OVER (ORDER BY j.created_on DESC) = 1
),
jps AS (
    SELECT deployment, 2 as priority
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_JPS_V j
    JOIN params p ON j.uuid = p.uuid
    WHERE j.created_on BETWEEN DATEADD(hour, -3, p.uuid_ts) AND DATEADD(hour, 3, p.uuid_ts)
    QUALIFY ROW_NUMBER() OVER (ORDER BY j.created_on DESC) = 1
)
SELECT deployment FROM (SELECT * FROM job_etl UNION ALL SELECT * FROM jps)
ORDER BY priority LIMIT 1;
```

## Step 3: Fetch Query Metadata

Use the `DEPLOYMENT` value from Step 1 as the schema.

```sql
WITH params AS (
    SELECT
        '<QUERY_UUID>'::string AS uuid,
        '<DEPLOYMENT>'::string AS deployment,
        TO_TIMESTAMP(TO_NUMBER(LEFT('<QUERY_UUID>', 8), 'XXXXXXXX') * 60) AS uuid_ts
)
SELECT
    q.uuid AS QUERY_ID,
    q.deployment AS DEPLOYMENT,
    q.total_duration AS TOTAL_DURATION_MS,
    q.dur_compiling AS DUR_COMPILING_MS,
    q.dur_gs_executing AS DUR_GS_EXECUTING_MS,
    q.dur_xp_executing AS DUR_XP_EXECUTING_MS,
    q.access_kv_table AS ACCESS_KV_TABLE,
    q.database_name AS DATABASE_NAME,
    q.schema_name AS SCHEMA_NAME,
    q.warehouse_name AS WAREHOUSE_NAME,
    q.account_id AS ACCOUNT_ID,
    LEFT(q.description, 500) AS QUERY_PREVIEW,
    q.stats:stats.producedRows::NUMBER AS ROWS_PRODUCED,
    q.stats:stats.snowTramFDBIOBytes::NUMBER AS FDB_IO_BYTES,
    q.error_code AS ERROR_CODE,
    q.cachedplanid AS CACHEDPLANID,
    q.query_parameterized_hash AS QUERY_HASH,
    q.created_on AS CREATED_ON
FROM TABLE(SNOWHOUSE_IMPORT.INFORMATION_SCHEMA.DYNAMIC_TABLE_REF('JOB_ETL_JPS_V', p.deployment)) q
JOIN params p ON q.uuid = p.uuid
WHERE q.created_on BETWEEN DATEADD(day, -1, p.uuid_ts) AND DATEADD(day, 1, p.uuid_ts)
LIMIT 1;
```

**Alternative (if DYNAMIC_TABLE_REF unavailable):** Replace `<DEPLOYMENT>` placeholder manually:
```sql
FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_JPS_V q
```

## Step 4: Fetch Query History (Optional)

Use the `DEPLOYMENT`, `QUERY_HASH`, and `ACCOUNT_ID` values from previous steps.

```sql
WITH executions AS (
    SELECT
        DATE(created_on) AS execution_date,
        total_duration AS duration_ms
    FROM SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_JPS_V
    WHERE query_parameterized_hash = '<QUERY_HASH>'
      AND account_id = '<ACCOUNT_ID>'
      AND created_on >= DATEADD(day, -30, CURRENT_TIMESTAMP())
      AND error_code IS NULL
)
SELECT
    execution_date,
    COUNT(*) AS execution_count,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50_latency,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_latency,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_latency
FROM executions
GROUP BY execution_date
ORDER BY execution_date DESC;
```

**Note:** Replace `<DEPLOYMENT>` with the deployment from Step 1 (e.g., `SNOWHOUSE_IMPORT.AWSUSWEST2.JOB_ETL_JPS_V`).

## Analysis Heuristics

After fetching metadata, apply these rules:

| Metric | Threshold | Finding |
|--------|-----------|---------|
| `TOTAL_DURATION_MS` > 1000 | Slow query | Review execution plan |
| `DUR_XP_EXECUTING_MS` > 500 | XP bottleneck | Check index usage |
| `FDB_IO_BYTES` > 10MB | High FDB I/O | Consider index optimization |
| `ACCESS_KV_TABLE` = false | Not using HT path | Query may not benefit from HT |
| `DUR_COMPILING_MS` > 200 | Slow compilation | Check for plan cache issues |
