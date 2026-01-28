# Product-Specific Guidance

## Hybrid Tables - When to Recommend

**Strong Indicators:**
- P50 latency < 50ms required
- Point lookups dominate workload
- Single-row INSERT/UPDATE/DELETE operations
- Need for elastic compute during spikes
- Primary keys are well-defined
- No Postgres-specific requirements

**Caution Flags:**
- Heavy bulk write operations per day
- Complex stored procedures
- Customer strongly prefers Postgres
- Analytical aggregations are primary workload

---

## Snowflake Postgres - When to Recommend

**Strong Indicators:**
- Customer is Postgres expert
- Migrating from existing Postgres
- Postgres extensions needed (PostGIS, etc.)
- Complex Postgres stored procedures
- Postgres-native application clients
- Custom Postgres data types

**Caution Flags:**
- Need for elastic compute
- Tight Snowflake ecosystem integration required
- Customer wants "all-Snowflake" architecture
- Scale requirements exceed Postgres limits

---

## Interactive Tables - When to Recommend

**Strong Indicators:**
- Sub-second (not sub-10ms) latency needed
- Read-heavy workload (> 90% reads)
- Dashboard/BI query patterns
- Dynamic filtering on large datasets
- Cost-efficiency for read workloads important

**Caution Flags:**
- Sub-10ms latency required
- Requires significant DML operations
- True transactional requirements
- Single-row lookups dominate

---

## Standard Tables - When to Recommend

**Strong Indicators:**
- Batch analytics workload
- Latency tolerance > 1 second
- Heavy aggregations and joins
- Bulk write/update patterns
- Cost optimization is primary concern

**Caution Flags:**
- Real-time requirements
- Point lookup patterns
- Sub-second latency needed
- Transactional consistency required

---

## Decision Matrix - Primary Criteria

| Criteria | Hybrid Tables | Snowflake Postgres | Interactive Tables | Standard Tables |
|----------|:-------------:|:-----------------:|:------------------:|:---------------:|
| **P50 Latency < 10ms** | ✗ Not designed | ✓ Capable | ✗ Not designed | ✗ Not designed |
| **Point Lookups (single-row)** | ✓ Optimized | ✓ Optimized | ~ Acceptable | ✗ Not optimal |
| **High TPS (> 1000)** | ✓ Designed | ✓ Designed | ~ With caveats | ✗ Not designed |
| **Single-row DML** | ✓ Optimized | ✓ Optimized | ✗ Read-focused | ✗ Batch-focused |
| **Transactional Consistency** | ✓ ACID | ✓ ACID | ~ Limited | ✗ Not ACID |
| **Postgres Compatibility** | ✗ Limited | ✓ Full | ✗ No | ✗ No |
| **Postgres Extensions** | ✗ No | ✓ Many | ✗ No | ✗ No |
| **Elastic Compute** | ✓ Yes | ✗ Fixed | ✓ Yes | ✓ Yes |
| **Sub-second Analytics** | ~ Limited | ~ Limited | ✓ Optimized | ✗ Seconds+ |
| **Bulk Write Performance** | ✗ Slower | ~ Moderate | ✗ Read-focused | ✓ Optimized |
| **Cost Efficiency (reads)** | ~ Moderate | ~ Low | ✓ Low | ✓ Moderate |
| **Cost Efficiency (writes)** | ~ Moderate | ~ Moderate | ✗ N/A | ✓ Low |

---

## Read:Write Ratio Scoring

| Read:Write Ratio | Hybrid Tables | Interactive Analytics | Standard Tables |
|------------------|---------------|----------------------|-----------------|
| > 10,000:1 | 0 (overkill for writes) | 3 (ideal) | 2 (acceptable) |
| 1,000:1 - 10,000:1 | 1 (consider if latency critical) | 3 (ideal) | 2 (acceptable) |
| 100:1 - 1,000:1 | 2 (good fit) | 2 (acceptable) | 2 (acceptable) |
| < 100:1 | 3 (designed for this) | 0 (too many writes) | 1 (batch writes only) |

---

## Scoring Model

For each requirement, assign a compatibility score:

| Score | Meaning |
|-------|---------|
| 3 | Excellent fit - product is designed for this |
| 2 | Good fit - product handles this well |
| 1 | Acceptable - product can do this with caveats |
| 0 | Poor fit - product not designed for this |
| -1 | Blocker - product cannot meet this requirement |

Calculate total score for each product and identify:
- **Best Fit**: Highest positive score with no blockers
- **Alternative**: Second-highest score with no blockers
- **Not Recommended**: Products with blockers or low scores

---

## Support References

### Unistore References
1. [#unistore-workload](https://snowflake.enterprise.slack.com/archives/C02GHK5EN1Z) - Unistore GTM Sales and Technical Specialists
2. [#support-unistore](https://snowflake.enterprise.slack.com/archives/C02R14PHAC9) - Support and problem questions
3. Tag: `@unistore-gtm-team`
4. Hybrid Tables Compass page

### Postgres References
1. [#ask-snowflake-postgres](https://snowflake.enterprise.slack.com/archives/C08V01BHQBX) - Snowflake Postgres questions
2. Postgres Compass page

### Interactive Analytics References
1. Interactive Compass page
