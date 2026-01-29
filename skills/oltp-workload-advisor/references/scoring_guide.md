# Decision Framework & Scoring Guide

## Hybrid Table Candidates

### Positive Scoring
| Criteria | Score | Description |
|----------|-------|-------------|
| UPDATE % > 1% of table ops | +3 | Significant UPDATE activity |
| DELETE % > 0.5% of table ops | +2 | Non-trivial DELETE activity |
| Parameterized queries (? or :param) | +3 | OLTP-style prepared statements |
| P50 latency > 500ms (room for improvement) | +2 | Current latency is slow |
| WHERE clause with equality predicates | +2 | Point lookup pattern |
| Non-ETL/staging table | +3 | Production operational table |

### Negative Scoring
| Criteria | Score | Description |
|----------|-------|-------------|
| Table name contains TEMP/STG/WORK | -5 | ETL/staging table |
| Bulk operations (IN subquery, no WHERE) | -3 | Not suitable for HT |
| Non-parameterized bulk queries | -2 | Batch pattern |

**Score >= 8**: Strong Hybrid Table candidate
**Score 5-7**: Moderate candidate, needs validation
**Score < 5**: Likely not a good fit

---

## Interactive Analytics Candidates

### Positive Scoring
| Criteria | Score | Description |
|----------|-------|-------------|
| Read % >= 99% | +3 | Almost exclusively reads |
| Read % 95-99% | +2 | Very read-heavy |
| P50 latency 100ms-5s | +3 | Sub-second target, room to improve |
| Query volume > 100K/month | +2 | Frequently accessed |
| Current latency > 1s | +2 | Significant improvement potential |
| No DML activity | +2 | Purely read workload |
| Wide table (50+ columns) | +3 | Ideal for IA's dynamic column access |
| Wide table (20-50 columns) | +2 | Good fit for IA |
| Dynamic column selection in queries | +2 | IA excels at this pattern |

### Negative Scoring
| Criteria | Score | Description |
|----------|-------|-------------|
| Narrow table (<10 columns) | -2 | May not benefit from IA's wide-table optimization |
| Warehouse cost sensitivity | -3 | IA requires always-on warehouse |
| Intermittent/bursty access | -2 | May not justify always-on warehouse cost |

**Score >= 8**: Strong IA candidate
**Score 5-7**: Moderate candidate, needs validation
**Score < 5**: May not benefit significantly

**Important:** IA requires always-on warehouse. Discuss with customer whether they can justify compute costs.

---

## Snowflake Postgres Candidates

### Positive Scoring
| Criteria | Score | Description |
|----------|-------|-------------|
| **Inbound Indicators** | | |
| High volume Postgres CDC (Fivetran/Airbyte/HVR/Debezium) | +4 | Active Postgres replication |
| Tables with pg_* or *_rds_* naming patterns | +3 | Postgres-sourced tables |
| COPY INTO from stages with postgres/rds naming | +2 | Direct Postgres data loads |
| Multiple ETL tools replicating from Postgres | +3 | Complex Postgres ecosystem |
| **Outbound Indicators** | | |
| COPY INTO to stages with postgres/rds naming | +4 | Data exported to Postgres |
| High volume S3/Azure/GCS exports with reverse-ETL | +3 | Potential Postgres destinations |
| Frequent scheduled exports (TASK-driven COPY INTO) | +2 | Automated data feeds |
| **Consolidation Signals** | | |
| Both inbound AND outbound Postgres patterns | +5 | Strong consolidation opportunity |
| Customer has known external Postgres (AWS RDS, Aurora) | +3 | Known Postgres estate |
| ETL complexity (3+ different tools involved) | +2 | Simplification opportunity |

### Negative Scoring
| Criteria | Score | Description |
|----------|-------|-------------|
| No Postgres-related patterns detected | -10 | Not a candidate |
| Low volume (<1000 ops/month) | -3 | May not justify migration |
| Postgres patterns only in staging/temp tables | -2 | Not production workload |

**Score >= 10**: Strong Snowflake Postgres candidate
**Score 5-9**: Moderate candidate - Worth exploring
**Score < 5**: Low priority

---

## Product Comparison Matrix

| Consideration | Hybrid Tables | Interactive Analytics | Snowflake Postgres |
|---------------|---------------|----------------------|-------------------|
| **Warehouse Requirement** | Can shut down | Must always run | Dedicated compute |
| **Best Table Shape** | Narrow tables | Wide tables (50+ cols) | Any Postgres schema |
| **Column Access Pattern** | Known, fixed columns | Dynamic any-column | Standard SQL/Postgres |
| **Latency Target** | Sub-10ms | Sub-second (100ms-1s) | Sub-second OLTP |
| **Write Pattern** | High single-row DML | Primarily read-only | Full ACID DML |
| **Cost Model** | Pay per DML | Pay for always-on WH | Pay compute + storage |
| **Best Use Case** | Native Snowflake OLTP | BI/Dashboard accel | Postgres app consolidation |
| **Protocol** | Snowflake native | Snowflake native | Postgres wire protocol |
