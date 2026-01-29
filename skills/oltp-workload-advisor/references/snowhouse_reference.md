# Snowhouse Tables Reference

## Key Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `SNOWHOUSE.PRODUCT.ALL_LIVE_ACCOUNTS` | Account lookup | ID, NAME, DEPLOYMENT, CREATED_ON |
| `SNOWHOUSE.PRODUCT.JOB_FACT` | Query execution metrics | ACCOUNT_ID, DEPLOYMENT, DURATION_TOTAL, JOBS, CREATED_HOUR |
| `SNOWHOUSE.PRODUCT.STATEMENT_TYPE` | Statement type classification | ID, STATEMENT_TYPE |
| `SNOWHOUSE_IMPORT.PROD.JOB_ETL_V` | Query text and detailed metrics | ACCOUNT_ID, DEPLOYMENT, DESCRIPTION, TOTAL_DURATION, CREATED_ON |

## Performance Optimization: Deployment-Specific Schemas

**IMPORTANT:** Use deployment-specific schema instead of `PROD` for better performance:

| Instead of | Use |
|------------|-----|
| `SNOWHOUSE_IMPORT.PROD.JOB_ETL_V` | `SNOWHOUSE_IMPORT.<DEPLOYMENT>.JOB_ETL_V` |

**Examples:**
- `va` deployment: `SNOWHOUSE_IMPORT.VA.JOB_ETL_V`
- `va2` deployment: `SNOWHOUSE_IMPORT.VA2.JOB_ETL_V`
- `prod1` deployment: `SNOWHOUSE_IMPORT.PROD1.JOB_ETL_V`

## Common Company Name Aliases

When initial search fails, try these common patterns:

| Current Name | Former/Alternate Names |
|--------------|------------------------|
| Elevance Health | Anthem |
| Meta | Facebook |
| Alphabet | Google |
| Warner Bros. Discovery | WarnerMedia, Discovery |

## Telemetry Configuration

| Setting | Value |
|---------|-------|
| Database | `AFE` |
| Schema | `PUBLIC_APP_STATE` |
| Table | `APP_EVENTS` |
| App Name | `oltp-workload-advisor` |
| App Version | `2.5.0` |
