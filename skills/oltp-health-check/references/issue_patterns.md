# Issue Patterns & Remediation Guide

## Hybrid Tables Issues

### HT-001: High P50 Latency (> 100ms)

**Severity:** CRITICAL

**Detection:**
```sql
AVG P50_MS > 100 over last 7 days
```

**Root Causes:**
1. Missing or inefficient index usage
2. Queries performing table scans instead of point lookups
3. Large result sets being returned
4. FDB cluster under pressure

**Remediation:**
1. Review top slow queries for patterns
2. Check if queries have proper WHERE clause predicates matching primary key
3. Verify index coverage using `SHOW INDEXES ON <table>`
4. Review query patterns - Hybrid Tables excel at point lookups, not scans
5. Consider if workload is better suited for Standard Tables

**Customer Talking Points:**
- "Hybrid Tables are optimized for sub-10ms point lookups by primary key"
- "Queries that scan ranges or filter on non-indexed columns may perform better on Standard Tables"
- "Let's review the query patterns to ensure they match Hybrid Table design principles"

---

### HT-002: FDB Timeout Rate > 0.1%

**Severity:** CRITICAL

**Detection:**
```sql
SUM(FDB_TIMEOUTS) / COUNT(*) > 0.001 over last 7 days
```

**Root Causes:**
1. FDB cluster capacity issues
2. Long-running transactions blocking
3. Network issues between compute and FDB
4. Unusually large transaction sizes

**Remediation:**
1. Check for any long-running transactions
2. Review transaction sizes (rows per transaction)
3. Escalate to Snowflake support if persistent
4. Check if other accounts on same FDB cluster are affected

**Customer Talking Points:**
- "FDB timeouts indicate backend storage pressure"
- "We're investigating the root cause with our infrastructure team"
- "In the meantime, consider batching smaller transactions"

---

### HT-003: Low Optimal Query Percentage (< 50%)

**Severity:** WARNING

**Detection:**
```sql
SUM(queries < 10ms) / COUNT(*) < 0.50
```

**Root Causes:**
1. Workload not well-suited for Hybrid Tables
2. Queries not leveraging primary key
3. Complex queries with JOINs or aggregations
4. Analytical queries on OLTP tables

**Remediation:**
1. Analyze query pattern distribution (point lookups vs. scans)
2. Review if analytical queries should target Standard Tables instead
3. Consider query routing to separate workloads
4. Evaluate if Hybrid Tables are the right fit

**Customer Talking Points:**
- "Your workload shows a mix of OLTP and analytical patterns"
- "Hybrid Tables are optimized for point lookups - analytical queries may perform better on Standard Tables"
- "Consider routing analytical queries to a replica or separate table"

---

### HT-004: Latency Degradation Trend

**Severity:** WARNING

**Detection:**
```sql
Current week P50 > Previous week P50 * 1.5
```

**Root Causes:**
1. Increased data volume
2. Changed query patterns
3. New application behavior
4. Infrastructure changes

**Remediation:**
1. Compare query volumes week-over-week
2. Identify new query patterns introduced
3. Check for data growth on affected tables
4. Review recent application deployments

**Customer Talking Points:**
- "We've detected a 50%+ increase in latency compared to last week"
- "Let's investigate if there were any workload or data changes"
- "This could indicate growing data volume requiring index optimization"

---

## Interactive Analytics Issues

### IA-001: Low Sub-Second Query Rate (< 70%)

**Severity:** WARNING

**Detection:**
```sql
SUM(queries < 1000ms) / COUNT(*) < 0.70
```

**Root Causes:**
1. Complex analytical queries
2. Large data volumes
3. Insufficient warehouse size
4. Query compilation overhead

**Remediation:**
1. Review top slow queries for optimization opportunities
2. Check warehouse size vs. query complexity
3. Analyze compilation times
4. Consider query result caching

**Customer Talking Points:**
- "Interactive Analytics targets sub-second response for dashboard queries"
- "Complex queries may benefit from materialized views or pre-aggregation"
- "Consider scaling up the Interactive warehouse for consistent performance"

---

### IA-002: High Compilation Overhead

**Severity:** WARNING

**Detection:**
```sql
SUM(DUR_COMPILING > 500ms) / COUNT(*) > 0.20
```

**Root Causes:**
1. Complex query structures
2. Many columns in SELECT
3. Dynamic SQL generation
4. Schema changes causing recompilation

**Remediation:**
1. Simplify query structures where possible
2. Use parameterized queries to leverage plan caching
3. Reduce dynamic SQL generation
4. Monitor for unnecessary schema changes

**Customer Talking Points:**
- "Query compilation is taking longer than expected"
- "Parameterized queries can leverage plan caching for faster compilation"
- "Consider simplifying complex queries or pre-computing results"

---

## Snowflake Postgres Issues

### PG-001: High Latency Distribution

**Severity:** WARNING

**Detection:**
```sql
SUM(TOTAL_DURATION > 100ms) / COUNT(*) > 0.50
```

**Root Causes:**
1. Complex queries through Postgres protocol
2. Large result sets
3. Connection pooling issues
4. Network latency

**Remediation:**
1. Review query patterns for optimization
2. Implement connection pooling if not present
3. Consider batch operations vs. individual queries
4. Check network path and latency

**Customer Talking Points:**
- "Over 50% of queries are taking more than 100ms"
- "Postgres-protocol queries have some overhead compared to native Snowflake"
- "Connection pooling and query optimization can help reduce latency"

---

### PG-002: Throughput Instability

**Severity:** INFO

**Detection:**
```sql
STDDEV(daily_queries) / AVG(daily_queries) > 0.5
```

**Root Causes:**
1. Batch job scheduling variability
2. Application deployment changes
3. Traffic pattern changes
4. Failover events

**Remediation:**
1. Review daily patterns for expected variability
2. Check for batch job schedules
3. Correlate with application deployment calendar
4. Verify no unexpected failovers occurred

**Customer Talking Points:**
- "Query throughput shows high variability day-over-day"
- "This could be normal for batch-oriented workloads"
- "Let's verify this aligns with expected application behavior"

---

## Cross-Product Issues

### CROSS-001: No OLTP Products in Use

**Severity:** INFO

**Detection:**
```sql
HT_QUERIES = 0 AND IA_QUERIES = 0 AND PG_QUERIES = 0
```

**Recommendation:**
- Offer to run `oltp-workload-advisor` to identify conversion candidates
- Customer may benefit from Hybrid Tables, IA, or Snowflake Postgres

**Customer Talking Points:**
- "No OLTP products are currently in use for this account"
- "Would you like me to analyze the workload for potential OLTP opportunities?"
- "I can run a workload analysis to identify tables that might benefit from Hybrid Tables or Interactive Analytics"
