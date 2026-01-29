# Snowhouse Tables Reference

## Key Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `SNOWHOUSE.PRODUCT.ALL_LIVE_ACCOUNTS` | Account lookup | ID, NAME, DEPLOYMENT, CREATED_ON |
| `SNOWHOUSE.PRODUCT.JOB_FACT` | Query execution metrics (aggregated) | ACCOUNT_ID, DEPLOYMENT, DURATION_TOTAL, JOBS, CREATED_HOUR |
| `SNOWHOUSE.PRODUCT.STATEMENT_TYPE` | Statement type classification | ID, STATEMENT_TYPE |
| `SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V` | Query text and detailed metrics | ACCOUNT_ID, DEPLOYMENT, DESCRIPTION, TOTAL_DURATION, CREATED_ON |
| `SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_JPS_V` | **Deep HT analysis** (slow!) | All JOB_ETL_V columns + extended HT metrics |

## Performance Optimization: Deployment-Specific Schemas

**IMPORTANT:** Use deployment-specific schema instead of `PROD` for better performance:

| Instead of | Use |
|------------|-----|
| `SNOWHOUSE_IMPORT.PROD.JOB_ETL_V` | `SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V` |

**Examples:**
- `va` deployment: `SNOWHOUSE_IMPORT.VA.JOB_ETL_V`
- `va2` deployment: `SNOWHOUSE_IMPORT.VA2.JOB_ETL_V`
- `prod1` deployment: `SNOWHOUSE_IMPORT.PROD1.JOB_ETL_V`

---

## JOB_ETL_V Key Columns

### Identification
| Column | Type | Description |
|--------|------|-------------|
| `ACCOUNT_ID` | NUMBER | Customer account ID |
| `DEPLOYMENT` | VARCHAR | Deployment region |
| `SESSION_ID` | NUMBER | Session identifier |
| `UUID` | VARCHAR | Unique query identifier |
| `QUERY_PARAMETERIZED_HASH` | VARCHAR | Hash of parameterized query (find similar queries) |

### Timing Metrics
| Column | Type | Description |
|--------|------|-------------|
| `TOTAL_DURATION` | NUMBER | Total query duration (ms) |
| `DUR_COMPILING` | NUMBER | Compilation time (ms) |
| `DUR_XP_EXECUTING` | NUMBER | Execution time (ms) |
| `CREATED_ON` | TIMESTAMP | Query timestamp |

### Hybrid Tables Indicators
| Column | Type | Description |
|--------|------|-------------|
| `ACCESS_KV_TABLE` | BOOLEAN | TRUE if query accessed Hybrid Table |
| `KV_PROBES` | NUMBER | Number of KV lookups |
| `KV_RESULTS` | NUMBER | Number of KV results returned |

### Query Details
| Column | Type | Description |
|--------|------|-------------|
| `DESCRIPTION` | VARCHAR | SQL query text |
| `ERROR_CODE` | VARCHAR | NULL if successful |
| `CLIENT_APPLICATION_ID` | VARCHAR | Client application identifier |
| `WAREHOUSE_TYPE` | VARCHAR | Type of warehouse used |

---

## JOB_ETL_V vs JOB_ETL_JPS_V

**IMPORTANT: Use the right table for the right purpose!**

| Table | Use When | Performance |
|-------|----------|-------------|
| `JOB_ETL_V` | Health checks, latency trends, performance tiers, slow query lists | **Fast** - use for broad queries |
| `JOB_ETL_JPS_V` | Deep-dive on specific query IDs, detailed HT execution plans | **Slow** - use sparingly, filter by UUID |

**Best Practice:**
1. Use `JOB_ETL_V` for all health check queries (aggregations, trends, top-N lists)
2. Only use `JOB_ETL_JPS_V` when analyzing a **specific query UUID** for detailed HT metrics
3. Always filter `JOB_ETL_JPS_V` by `UUID = '<specific_query_id>'` to avoid slow scans

---

## Common Company Name Aliases

When initial search fails, try these common patterns:

| Current Name | Former/Alternate Names |
|--------------|------------------------|
| Elevance Health | Anthem |
| Meta | Facebook |
| Alphabet | Google |
| Warner Bros. Discovery | WarnerMedia, Discovery |

---

## Telemetry Configuration

| Setting | Value |
|---------|-------|
| Database | `AFE` |
| Schema | `PUBLIC_APP_STATE` |
| Table | `APP_EVENTS` |
| App Name | `oltp-health-check` |
| App Version | `1.0.0` |

---

## FDB Error Codes

Common FDB-related error patterns to look for:

| Error Pattern | Description |
|---------------|-------------|
| `%FDB%TIMEOUT%` | FDB operation timeout |
| `%FDB%RETRY%` | FDB retry limit exceeded |
| `%TRANSACTION_TOO_OLD%` | Long-running transaction |
| `%COMMIT_UNKNOWN_RESULT%` | Commit status unknown |
