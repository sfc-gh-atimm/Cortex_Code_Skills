# Output Report Template

```markdown
# Customer Workload Conversion Analysis

**Customer:** [Customer Name]
**Account ID:** [ID]
**Account Name:** [NAME]
**Deployment:** [Deployment]
**Analysis Period:** Last [X] days
**Report Date:** [Date]

---

## Executive Summary

**Total Queries Analyzed:** [X]M
**Statement Distribution:** [X]% SELECT, [X]% INSERT, [X]% UPDATE, [X]% DELETE
**Hybrid Table Candidates:** [X] tables
**Interactive Analytics Candidates:** [X] tables

**Key Finding:** [1-2 sentence summary of main opportunity]

---

## Account Activity Summary

| Metric | Value |
|--------|-------|
| Total Queries | [X] |
| Daily Average | [X] |
| Peak Day | [Date]: [X] queries |
| Avg Query Duration | [X]ms |

### Statement Type Distribution

| Type | Count | % | Avg Duration | P50 Duration |
|------|-------|---|--------------|--------------|
| SELECT | [X] | [X]% | [X]ms | [X]ms |
| INSERT | [X] | [X]% | [X]ms | [X]ms |
| UPDATE | [X] | [X]% | [X]ms | [X]ms |
| DELETE | [X] | [X]% | [X]ms | [X]ms |
| MERGE | [X] | [X]% | [X]ms | [X]ms |

### UPDATE Pattern Classification

| Pattern | Count | Avg Duration | Assessment |
|---------|-------|--------------|------------|
| Point Update (Parameterized) | [X] | [X]ms | ✅ HT Candidate |
| Point Update (Literal) | [X] | [X]ms | ⚠️ Needs Review |
| ETL/Staging | [X] | [X]ms | ❌ Exclude |
| Bulk/Other | [X] | [X]ms | ❌ Exclude |

---

## Top Hybrid Table Candidates

| Rank | Table | Score | UPDATE Count | Parameterized % | P50 Latency | Key Indicators |
|------|-------|-------|--------------|-----------------|-------------|----------------|
| 1 | [TABLE_1] | [X/15] | [X] | [X]% | [X]ms | [indicators] |
| 2 | [TABLE_2] | [X/15] | [X] | [X]% | [X]ms | [indicators] |

### Detailed Analysis: [TOP_CANDIDATE]

**Why Hybrid Tables:**
1. [Reason 1 with data]
2. [Reason 2 with data]
3. [Reason 3 with data]

**Sample Query Patterns:**
```sql
-- Parameterized UPDATE example
[QUERY_SAMPLE]
```

**Expected Improvement:**
| Metric | Current | Expected with HT |
|--------|---------|------------------|
| UPDATE P50 | [X]ms | <20ms |
| UPDATE P99 | [X]ms | <100ms |

---

## Top Interactive Analytics Candidates

| Rank | Table | Score | Query Count | Read % | P50 Latency | IA Fit |
|------|-------|-------|-------------|--------|-------------|--------|
| 1 | [TABLE_1] | [X/12] | [X] | [X]% | [X]ms | STRONG |
| 2 | [TABLE_2] | [X/12] | [X] | [X]% | [X]ms | MODERATE |

### Detailed Analysis: [TOP_CANDIDATE]

**Why Interactive Analytics:**
1. [Reason 1 with data]
2. [Reason 2 with data]

**Expected Improvement:**
| Metric | Current | Expected with IA |
|--------|---------|------------------|
| P50 latency | [X]ms | <500ms |
| P99 latency | [X]ms | <2s |

---

## Tables NOT Recommended for Conversion

| Table | Reason |
|-------|--------|
| TEMP_DB.* | ETL/Staging tables |
| *_STG tables | Staging tables for data pipelines |
| *_TEMP tables | Temporary processing tables |

---

## Snowflake Postgres Assessment

### Postgres Data Flow Summary

| Flow Direction | Pattern Type | Operations | Assessment |
|----------------|--------------|------------|------------|
| INBOUND | [FIVETRAN_POSTGRES/HVR/DEBEZIUM/etc] | [X] | [Strong/Moderate/Low] |
| OUTBOUND | [S3_EXPORT/STAGE_EXPORT/etc] | [X] | [Strong/Moderate/Low] |

### Top Tables with Postgres Lineage

| Table | ETL Tool | Load Operations | Avg Load (ms) |
|-------|----------|-----------------|---------------|
| [TABLE_1] | [FIVETRAN/HVR/etc] | [X] | [X]ms |
| [TABLE_2] | [AIRBYTE/DEBEZIUM/etc] | [X] | [X]ms |

### Snowflake Postgres Recommendation

**Score: [X/16]** — [STRONG/MODERATE/LOW] candidate

[If Strong]:
Customer has significant Postgres data flowing into and/or out of Snowflake. Snowflake Postgres could consolidate external Postgres instances and simplify ETL pipelines.

**Conversation Points:**
- "You have [X] operations moving data from Postgres sources. Snowflake Postgres could consolidate this."
- "Your data export patterns suggest feeding external databases. Consider Snowflake Postgres as unified endpoint."

---

## Next Steps

### For Hybrid Table Candidates:
1. [ ] Validate primary key structure on candidate tables
2. [ ] Review query patterns with customer DBA
3. [ ] Assess application compatibility (driver, connection pooling)
4. [ ] Create POC plan for top candidate

### For Interactive Analytics Candidates:
1. [ ] Confirm workload is truly read-only or accept limited DML
2. [ ] Validate dashboard/BI access patterns
3. [ ] Review current caching strategies
4. [ ] Create POC plan for top candidate

### Customer Conversation Points:
- [Key talking point based on analysis]
- [ROI opportunity]
- [Recommended starting point]
```
