---
name: oltp-discovery-advisor
description: "Analyze OLTP discovery templates to recommend Hybrid Tables, Snowflake Postgres, Interactive Tables, or Standard Tables. Use when: reviewing discovery templates, determining OLTP fit, preparing customer recommendations. Triggers: discovery template, OLTP discovery, hybrid tables fit, postgres fit, interactive tables fit."
---

# OLTP Discovery Advisor

## Overview
This skill analyzes completed (or partially completed) OLTP Discovery Templates to determine the best-fit Snowflake solution for customer workloads. It identifies missing information, evaluates requirements against product capabilities, and generates talking points for AEs. This skill assumes the role of a Senior Applied Field Engineer that guides an AE and SE through discovery questions with the end customer. It should always do the following in its assessment:
1. Don't make assumptions about the current state of products. Verify with current internal product documentation
2. Take into account factors not included in discovery template such as"
2a. Archtictectural complexity of adding/integrating the proposed solution
2b. The associated overhead of implementing/maintaining the proposed solution
2c. Ask questions around the customers current ETL process and desire for eliminating it
2d. Does the customer require a fully GA, supported solution or are they open to a Private Preview or Public Preview option?

## Products Evaluated
| Product | Best For |
|---------|----------|
| **Hybrid Tables** | True OLTP workloads with sub-10ms point lookups, high single-row DML, transactional consistency |
| **Snowflake Postgres** | Postgres-native applications, Postgres expertise, complex Postgres features (extensions, stored procs) |
| **Interactive Tables** | Read-heavy analytical workloads requiring sub-second (not sub-10ms) response times|
| **Standard Tables** | Batch analytics, aggregations, cost-optimized analytical queries |

---

## Workflow

### Step 0: Determine User Intent
First, determine if the user wants to:
1. **Generate a blank questionnaire** for AE/SE to complete with customer
2. **Analyze a completed questionnaire** to get a recommendation

Use ask_user_question:
```json
{
  "questions": [
    {"header": "Action", "question": "What would you like to do?", "type": "options", "multiSelect": false, "options": [
      {"label": "Generate blank questionnaire", "description": "Create a new discovery questionnaire for an AE/SE to complete with a customer"},
      {"label": "Analyze completed questionnaire", "description": "Review a completed questionnaire and provide product recommendations"}
    ]}
  ]
}
```

---

### Step 0a: Generate Blank Discovery Template (if selected)

If user wants to generate a blank template, collect basic info:

```json
{
  "questions": [
    {"header": "Customer", "question": "Customer name", "type": "text", "defaultValue": "Customer Name"},
    {"header": "Output Path", "question": "Where should the template be saved?", "type": "text", "defaultValue": "/path/to/customer/folder/"}
  ]
}
```

Then generate the template using the standard OLTP Discovery Template v2 format:

```markdown
# OLTP Discovery Template

| Customer Name | [CUSTOMER_NAME] |  |  |
| :---- | ----- | :---- | ----- |
| **Use Case Name** |  |  |  |
| **Use Case Link (in SFDC)** |  | \<link\> |  |
| **Opportunity Link (in SFDC)** |  | \<link\> |  |
| **Date** |  |  |  |
| **Account Executive**  |  |  |  |
| **Sales Engineer** |  |  |  |
| **Other Snowflake contributors (e.g. from AFE, APG, Professional Services)** |  |  |  |
| **Customer points of contact** |  |  |  |
| **Snowflake Account Names in Scope** |  |  |  |
| **What Snowflake Features are being considered?** |  | \<Postgres, Unistore, Interactive, Dynamic Tables, etc.\> |  |
| **Is the Customer a Postgres Expert?** |  |  |  |
| **Is workload migrating from Postgres?** |  |  |  |

# Opportunity Overview

## Use Case Summary

Place a short summary here. Full documentation should be at the SFDC Use Case link.

## Business Goal

1-2 sentences regarding the business goal or desired outcome.

## Solution-space

**Current Solution:** Currently using \<articulate current scenario\>

**Possible alternative solutions:** \<articulate what other options customer has\>

# Use Case Requirements & Technical details:

### Architecture diagram & description

Please provide if available.

### Overall Technical Requirements

Answers to these questions will assist the specialist team in recommending solution options:

| Data Volume / Size | \<data size on disk\> |
| :---- | :---- |
| **Row size range** | \<row counts for largest tables\> |
| **AVG operations per second** | \<system expected TPS\> |
| **PEAK operations per second** | \<system expected TPS\> |
| **P50 Latency Expectation** | \<i.e. 1-10ms, 10-50ms, \<100ms\> |
| **P99 Latency Expectation** | \<i.e. 1-10ms, 10-50ms, \<100ms\> |
| **Bulk Writes & Updates** | Hourly bulk updates, periodic row updates |
| **Are Primary Keys well defined?** |  |
| **Total Direct Cost** | ? |
| **Application Client** | \<JDBC/NodeJS, etc.\> |
| **Are there custom data types?** | \<details\> |
| **Is Elastic Compute important?** |  |
| **What ETL Tooling is in place?** | \<describe how data moves from OLTP to Snowflake today\> |
| **NOTES** | \<provide additional information you feel is helpful\> |

*Add additional requirements as needed*

### Workload Details

If some of the workload details are known, please place them here

| Query Name | SQL | Latency (current / expected) | Expected Throughput |
| :---- | :---- | :---- | :---- |
| *Example Query* |  |  |  |
```

After generating, inform the user of the file path and that the AE/SE should complete it with the customer and return it for analysis.

---

### Step 1: Collect Discovery Template (for analysis)
Ask the user for the path to the completed discovery template file:

```json
{
  "questions": [
    {"header": "Template", "question": "Enter the path to the completed OLTP Discovery Template file", "type": "text", "defaultValue": "/path/to/discovery_template.md"}
  ]
}
```

### Step 2: Parse Template and Extract Fields
Read the template file and extract the following key fields:



#### Customer Info
- Customer Name
- Use Case Name
- Use Case Link - must have a link in the template, otherwise reject it and ask the AE to create one and link it to the Unistore product
- Account Executive
- Sales Engineer
- Is Customer a Postgres Expert?
- Is workload migrating from Postgres?

#### Latency Value Parsing
When extracting P50/P99 latency values from templates, interpret common notations as follows:

| Raw Value | Interpretation | Milliseconds |
|-----------|----------------|--------------|
| `<1s`, `< 1s`, `<1 second` | Less than 1 second | < 1000ms |
| `<100ms`, `< 100ms` | Less than 100ms | < 100ms |
| `<10ms`, `< 10ms` | Less than 10ms | < 10ms |
| `1-10ms` | 1 to 10 milliseconds | 1-10ms |
| `10-50ms` | 10 to 50 milliseconds | 10-50ms |
| `50-100ms` | 50 to 100 milliseconds | 50-100ms |
| `100ms-1s`, `100ms - 1s` | 100ms to 1 second | 100-1000ms |
| `sub-second` | Less than 1 second | < 1000ms |
| `sub-10ms` | Less than 10ms | < 10ms |
| `instant` | Very low latency | < 10ms |

**Important:** Treat `<1s` as a **valid and specific requirement** meaning "sub-second latency" (< 1000ms). This is NOT vague—it indicates the customer needs responses faster than 1 second, which is suitable for Interactive Tables or potentially Hybrid Tables depending on other factors.

#### Technical Requirements
| Field | Required for Assessment | Notes |
|-------|------------------------|-------|
| Data Volume / Size | Yes | Affects storage tier recommendations |
| Row size range | Yes | Large tables may have performance implications |
| AVG operations per second | **Critical** | Key differentiator for Hybrid vs Interactive |
| PEAK operations per second | **Critical** | Determines if elastic compute needed |
| P50 Latency Expectation | **Critical** | < 10ms = Hybrid Tables territory |
| P99 Latency Expectation | **Critical** | SLA requirements |
| Bulk Writes & Updates | Yes | Frequent bulk = Standard Tables may suffice |
| Primary Keys well defined? | Yes | Required for Hybrid Tables |
| Application Client | Yes | Postgres clients may prefer Snowflake Postgres |
| Custom data types? | Yes | May require Postgres compatibility |
| Elastic Compute important? | Yes | Favors Snowflake (Hybrid/Interactive) over Postgres |

---

### Step 3: Completeness Check
Evaluate the template for missing **critical** fields. If any of these are empty or unclear, generate questions for the user:

#### Critical Fields (Assessment cannot proceed without):
1. **AVG operations per second** - Required for throughput classification
2. **PEAK operations per second** - Required for burst capacity planning
3. **P50 Latency Expectation** - Required for product selection
4. **P99 Latency Expectation** - Required for SLA alignment
5. **Bulk Writes & Updates** - Required for write pattern analysis
6. **Primary Keys well defined?** - Required for Hybrid Tables eligibility

#### Important Fields (Assessment proceeds with assumptions):
- Data Volume / Size
- Row size range
- Application Client
- Custom data types?
- Is Customer a Postgres Expert?

If critical fields are missing, use ask_user_question to gather them:

```json
{
  "questions": [
    {"header": "TPS", "question": "What is the expected average operations per second (TPS)?", "type": "text", "defaultValue": "100"},
    {"header": "Latency", "question": "What is the P50 latency requirement?", "type": "options", "options": [
      {"label": "< 10ms", "description": "Sub-10ms point lookups (OLTP)"},
      {"label": "10-50ms", "description": "Fast transactional queries"},
      {"label": "50-100ms", "description": "Near-real-time analytics"},
      {"label": "> 100ms", "description": "Standard analytical queries"}
    ]}
  ]
}
```

---

### Step 3.5: Snowhouse Telemetry Validation (Optional)

After parsing the template, check if Snowflake account information is available (e.g., "Snowflake Account Name used for POC", deployment info, or account locator). If found, prompt the user to run Snowhouse analysis:

```json
{
  "questions": [
    {"header": "Snowhouse", "question": "Account information found in template. Would you like to validate the discovery template with actual Snowhouse telemetry data?", "type": "options", "multiSelect": false, "options": [
      {"label": "Yes, run Snowhouse analysis", "description": "Query Snowhouse for actual query patterns, latency metrics, and read:write ratios to validate template claims"},
      {"label": "No, proceed with template only", "description": "Generate recommendation based only on the discovery template information"}
    ]}
  ]
}
```

#### If user selects "Yes, run Snowhouse analysis":

##### 3.5.1 Find Account ID from Template Information
Extract account name and deployment from template, then query Snowhouse:

```bash
snow sql -c Snowhouse_PAT -q "
-- Find account ID from account name
SELECT ID as ACCOUNT_ID, DEPLOYMENT, NAME 
FROM SNOWHOUSE.PRODUCT.ALL_LIVE_ACCOUNTS 
WHERE UPPER(NAME) LIKE '%<ACCOUNT_NAME>%' 
  AND DEPLOYMENT LIKE '%<DEPLOYMENT>%'
ORDER BY DS DESC
LIMIT 5;
"
```

##### 3.5.2 Query Pattern Analysis (Last 30 Days)
```bash
snow sql -c Snowhouse_PAT -q "
-- Statement type distribution and latency
SELECT 
    st.STATEMENT_TYPE,
    SUM(jf.JOBS) as TOTAL_JOBS,
    ROUND(AVG(jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0)) / 1000, 3) as AVG_DURATION_SEC,
    ROUND(MEDIAN(jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0)) / 1000, 3) as MEDIAN_DURATION_SEC,
    MAX(jf.DURATION_TOTAL) / 1000 as MAX_DURATION_SEC,
    SUM(jf.HIT_CACHE_JOBS) as CACHE_HITS
FROM SNOWHOUSE.PRODUCT.JOB_FACT jf
JOIN SNOWHOUSE.PRODUCT.STATEMENT_TYPE st ON jf.STATEMENT_TYPE_ID = st.ID
WHERE jf.DEPLOYMENT = '<DEPLOYMENT>'
  AND jf.ACCOUNT_ID = <ACCOUNT_ID>
  AND jf.CREATED_HOUR >= DATEADD('day', -30, CURRENT_TIMESTAMP())
  AND st.STATEMENT_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE')
GROUP BY st.STATEMENT_TYPE
ORDER BY TOTAL_JOBS DESC;
"
```

##### 3.5.3 Calculate Read:Write Ratio
```bash
snow sql -c Snowhouse_PAT -q "
SELECT 
    SUM(CASE WHEN st.STATEMENT_TYPE = 'SELECT' THEN jf.JOBS ELSE 0 END) as TOTAL_SELECTS,
    SUM(CASE WHEN st.STATEMENT_TYPE IN ('INSERT', 'UPDATE', 'DELETE', 'MERGE') THEN jf.JOBS ELSE 0 END) as TOTAL_DML,
    ROUND(
        SUM(CASE WHEN st.STATEMENT_TYPE = 'SELECT' THEN jf.JOBS ELSE 0 END) * 1.0 / 
        NULLIF(SUM(CASE WHEN st.STATEMENT_TYPE IN ('INSERT', 'UPDATE', 'DELETE', 'MERGE') THEN jf.JOBS ELSE 0 END), 0)
    , 1) as READ_WRITE_RATIO
FROM SNOWHOUSE.PRODUCT.JOB_FACT jf
JOIN SNOWHOUSE.PRODUCT.STATEMENT_TYPE st ON jf.STATEMENT_TYPE_ID = st.ID
WHERE jf.DEPLOYMENT = '<DEPLOYMENT>'
  AND jf.ACCOUNT_ID = <ACCOUNT_ID>
  AND jf.CREATED_HOUR >= DATEADD('day', -30, CURRENT_TIMESTAMP());
"
```

##### 3.5.4 Latency Distribution
```bash
snow sql -c Snowhouse_PAT -q "
SELECT 
    CASE 
        WHEN jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0) < 10 THEN '1_< 10ms'
        WHEN jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0) < 100 THEN '2_10-100ms'
        WHEN jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0) < 1000 THEN '3_100ms-1s'
        WHEN jf.DURATION_TOTAL / NULLIF(jf.JOBS, 0) < 10000 THEN '4_1-10s'
        ELSE '5_> 10s' 
    END as LATENCY_BUCKET,
    SUM(jf.JOBS) as QUERY_COUNT,
    ROUND(SUM(jf.JOBS) * 100.0 / SUM(SUM(jf.JOBS)) OVER(), 2) as PERCENTAGE
FROM SNOWHOUSE.PRODUCT.JOB_FACT jf
JOIN SNOWHOUSE.PRODUCT.STATEMENT_TYPE st ON jf.STATEMENT_TYPE_ID = st.ID
WHERE jf.DEPLOYMENT = '<DEPLOYMENT>'
  AND jf.ACCOUNT_ID = <ACCOUNT_ID>
  AND jf.CREATED_HOUR >= DATEADD('day', -30, CURRENT_TIMESTAMP())
  AND st.STATEMENT_TYPE = 'SELECT'
GROUP BY LATENCY_BUCKET
ORDER BY LATENCY_BUCKET;
"
```

##### 3.5.5 Enhanced Decision Matrix with Read:Write Ratio

Use the Snowhouse data to enhance the scoring model:

| Read:Write Ratio | Hybrid Tables | Interactive Analytics | Standard Tables |
|------------------|---------------|----------------------|-----------------|
| > 10,000:1 | 0 (overkill for writes) | 3 (ideal) | 2 (acceptable) |
| 1,000:1 - 10,000:1 | 1 (consider if latency critical) | 3 (ideal) | 2 (acceptable) |
| 100:1 - 1,000:1 | 2 (good fit) | 2 (acceptable) | 2 (acceptable) |
| < 100:1 | 3 (designed for this) | 0 (too many writes) | 1 (batch writes only) |

##### 3.5.6 Snowhouse Validation Summary

Include the following in the recommendation report when Snowhouse analysis is performed:

```markdown
## Snowhouse Telemetry Validation

> ✅ **Template claims validated with actual Snowhouse data**

### Account Verified
| Field | Value |
|-------|-------|
| Account Name | [NAME] |
| Account ID | [ID] |
| Deployment | [DEPLOYMENT] |
| Analysis Period | Last 30 days |

### Actual vs Template Comparison
| Metric | Template Claim | Snowhouse Actual | Match? |
|--------|---------------|------------------|--------|
| Query Latency (P50) | [template value] | [actual value] | ✅/⚠️/❌ |
| Read:Write Ratio | [estimated/unknown] | [actual ratio]:1 | N/A |
| Daily Query Volume | [template value] | [actual value] | ✅/⚠️/❌ |
| Plan Cache Usage | [unknown] | [X]% hit rate | N/A |

### Key Insights from Snowhouse
- [Insight 1: e.g., "MERGE operations average 40 min - confirms bulk write concerns"]
- [Insight 2: e.g., "SELECT P50 is 55ms - better than <1s requirement"]
- [Insight 3: e.g., "Plan cache hit rate is 0% - optimization opportunity"]

### Confidence Adjustment
**Original confidence (template only):** [High/Medium/Low]
**Adjusted confidence (with Snowhouse):** [Very High/High/Medium/Low]
**Reason:** [Explanation of adjustment]
```

---

### Step 4: Decision Matrix Evaluation

#### 4.1 Primary Decision Criteria

| Criteria | Hybrid Tables | Snowflake Postgres | Interactive Tables | Standard Tables |
|----------|:-------------:|:-----------------:|:------------------:|:---------------:|
| **P50 Latency < 10ms** | ✓ Required | ✓ Capable | ✗ Not designed | ✗ Not designed |
| **Point Lookups (single-row)** | ✓ Optimized | ✓ Optimized | ~ Acceptable | ✗ Not optimal |
| **High TPS (> 1000)** | ✓ Designed | ✓ Capable | ~ With caveats | ✗ Not designed |
| **Single-row DML** | ✓ Optimized | ✓ Optimized | ✗ Read-focused | ✗ Batch-focused |
| **Transactional Consistency** | ✓ ACID | ✓ ACID | ~ Limited | ✗ Not ACID |
| **Postgres Compatibility** | ✗ No | ✓ Full | ✗ No | ✗ No |
| **Postgres Extensions** | ✗ No | ✓ Many | ✗ No | ✗ No |
| **Elastic Compute** | ✓ Yes | ✗ Fixed | ✓ Yes | ✓ Yes |
| **Sub-second Analytics** | ~ Limited | ~ Limited | ✓ Optimized | ✗ Seconds+ |
| **Bulk Write Performance** | ✗ Slower | ~ Moderate | ✗ Read-focused | ✓ Optimized |
| **Cost Efficiency (reads)** | ~ Moderate | ~ Moderate | ✓ High | ✓ High |
| **Cost Efficiency (writes)** | ~ Moderate | ~ Moderate | ✗ N/A | ✓ High |

#### 4.2 Decision Tree

```
START
  │
  ├─► Is P50 latency requirement < 10ms?
  │     │
  │     ├─► YES: Are there frequent single-row DML operations?
  │     │         │
  │     │         ├─► YES: Is Postgres compatibility required?
  │     │         │         │
  │     │         │         ├─► YES ──────────────────────► SNOWFLAKE POSTGRES
  │     │         │         │
  │     │         │         └─► NO: Is elastic compute important?
  │     │         │                   │
  │     │         │                   ├─► YES ────────────► HYBRID TABLES
  │     │         │                   │
  │     │         │                   └─► NO: Is customer Postgres expert?
  │     │         │                             │
  │     │         │                             ├─► YES ──► SNOWFLAKE POSTGRES
  │     │         │                             │
  │     │         │                             └─► NO ───► HYBRID TABLES
  │     │         │
  │     │         └─► NO (read-heavy): Is it dashboard/BI workload?
  │     │                   │
  │     │                   ├─► YES ──────────────────────► INTERACTIVE TABLES
  │     │                   │
  │     │                   └─► NO: Point lookup caching use case?
  │     │                             │
  │     │                             ├─► YES ────────────► HYBRID TABLES
  │     │                             │
  │     │                             └─► NO ─────────────► Evaluate Further
  │     │
  │     └─► NO (latency > 10ms): Is latency < 1 second required?
  │               │
  │               ├─► YES: Is workload read-heavy (> 90% reads)?
  │               │         │
  │               │         ├─► YES ──────────────────────► INTERACTIVE TABLES
  │               │         │
  │               │         └─► NO: Significant DML?
  │               │                   │
  │               │                   ├─► YES: Postgres required?
  │               │                   │         │
  │               │                   │         ├─► YES ──► SNOWFLAKE POSTGRES
  │               │                   │         │
  │               │                   │         └─► NO ───► HYBRID TABLES
  │               │                   │
  │               │                   └─► NO ─────────────► INTERACTIVE TABLES
  │               │
  │               └─► NO (latency > 1s acceptable): Is workload batch-oriented?
  │                         │
  │                         ├─► YES ──────────────────────► STANDARD TABLES
  │                         │
  │                         └─► NO ───────────────────────► STANDARD TABLES
  │
  └─► Special Cases:
        │
        ├─► Postgres migration + Postgres expertise ──────► SNOWFLAKE POSTGRES
        │
        ├─► Custom Postgres data types needed ────────────► SNOWFLAKE POSTGRES
        │
        ├─► Postgres stored procedures required ──────────► SNOWFLAKE POSTGRES
        │
        └─► Mixed OLTP + Analytics (same data) ──────────► HYBRID TABLES + join to Standard
```

#### 4.3 Scoring Model

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

### Step 5: Generate Initial Summary (Append to Discovery Template)

After evaluating the template, **append** the following summary directly to the end of the original discovery template file:

#### 5.1 Quick Recommendation Summary Table
This is the FIRST output - a concise table showing the top 2 recommended products:

```markdown

---

# OLTP Discovery Advisor Assessment
**Assessment Date:** [Date]
**Assessed By:** OLTP Discovery Advisor Skill

## Quick Recommendation Summary

| Rank | Product | Score | Key Fit Reasons | Primary Concerns |
|------|---------|-------|-----------------|------------------|
| 🥇 1st | [PRODUCT] | [X/15] | [2-3 bullet reasons] | [Any caveats] |
| 🥈 2nd | [PRODUCT] | [X/15] | [2-3 bullet reasons] | [Any caveats] |

**Confidence Level:** [High/Medium/Low] - [Brief explanation based on template completeness]

**Quick Take:** [1-2 sentence recommendation summary explaining why #1 is preferred over #2]
```

#### 5.2 Follow-up Questionnaire for Customer
After the summary table, generate a **targeted follow-up questionnaire** based on gaps identified in the initial template. Use business-friendly language (not technical jargon like P50/P99). Select relevant sections from this master questionnaire based on what's missing or unclear:

```markdown

---

## Follow-up Questions for Customer

Based on our initial analysis, we need additional information in the following areas:

### Response Time Requirements (if latency unclear)

**How fast do your applications need query responses?**

| Speed | Examples | Select |
|-------|----------|--------|
| Instant (< 10ms) | User login, account lookup, real-time pricing | [ ] |
| Very Fast (10-100ms) | Cart updates, inventory checks | [ ] |
| Fast (100ms - 1 sec) | Dashboard filters, search results | [ ] |
| Flexible (> 1 sec OK) | Reports, batch operations | [ ] |

**Are there contractual SLAs tied to response times?** [ ] Yes: _____________ [ ] No

### Transaction Volume (if TPS unclear)

**Average database operations per second:** [ ] < 100 [ ] 100-1,000 [ ] 1,000-10,000 [ ] > 10,000

**Peak traffic multiplier:** _____ x average | **Concurrent users (peak):** _____

### Read vs Write Patterns (if workload pattern unclear)

**What percentage of operations are reads (SELECT)?**
[ ] 90%+ reads | [ ] 70-90% reads | [ ] 50-70% reads | [ ] < 50% reads

**Most common read operations:** (check all that apply)
[ ] Single-record lookups (get by ID) | [ ] Range queries | [ ] Aggregations/reports | [ ] Complex joins

**Most common write operations:** (check all that apply)
[ ] Single-row inserts/updates | [ ] Bulk/batch loads | [ ] Merge/upsert | [ ] Deletes

**How frequent are UPDATEs and DELETEs?**
[ ] Very frequent (core logic) | [ ] Occasional | [ ] Rare (mostly append-only)

### Data Movement & ETL (always include - key differentiator)

**Do you currently have ETL pipelines moving data between OLTP and analytics systems?**
[ ] Yes - extensive ETL | [ ] Yes - some pipelines | [ ] Minimal | [ ] No ETL currently

**If yes, describe the current ETL landscape:**

| Question | Answer |
|----------|--------|
| Number of ETL jobs/pipelines | _____ |
| ETL tools used (Informatica, SSIS, custom, etc.) | _____________________ |
| How often do ETL jobs run? | [ ] Real-time [ ] Hourly [ ] Daily [ ] Weekly |
| ETL maintenance effort (hours/week) | _____ |

**Pain points with current ETL:** (check all that apply)
[ ] Data latency (analytics lag behind operational data)
[ ] Job failures requiring manual intervention
[ ] Complexity managing multiple pipelines
[ ] Data inconsistencies between systems
[ ] High infrastructure/licensing costs
[ ] Difficult to modify when source systems change

**Would eliminating ETL between OLTP and analytics be valuable?**
[ ] Very valuable - major pain point | [ ] Somewhat valuable | [ ] Not a priority

**Do downstream systems (BI tools, reports, ML) need direct access to operational data?**
[ ] Yes - currently blocked by ETL delays | [ ] Yes - but current delays acceptable | [ ] No

### Architecture & Security Simplification (always include - key differentiator)

**How many separate database platforms does your organization currently manage?**
[ ] 1-2 | [ ] 3-5 | [ ] 6-10 | [ ] 10+

List platforms: _________________________________________________________________

**Current state pain points:** (check all that apply)
[ ] Multiple database technologies requiring different skill sets
[ ] Inconsistent security policies across platforms
[ ] Separate access control systems to manage
[ ] Different backup/DR procedures per platform
[ ] Compliance auditing across multiple systems is complex
[ ] Difficult to get unified view of data across platforms

**How important is consolidating to fewer platforms?**
[ ] Critical - strategic initiative | [ ] Important | [ ] Nice to have | [ ] Not a priority

**Security & Governance considerations:**

| Question | Answer |
|----------|--------|
| Do you need unified role-based access control (RBAC) across OLTP and analytics? | [ ] Yes [ ] No |
| Is row-level or column-level security required? | [ ] Yes [ ] No |
| Do you need consistent audit logging across all data access? | [ ] Yes [ ] No |
| Are there data masking requirements for sensitive data? | [ ] Yes [ ] No |
| Must data stay within specific geographic regions? | [ ] Yes: _________ [ ] No |

**Would a single platform for OLTP + analytics simplify your compliance posture?**
[ ] Yes - significantly | [ ] Somewhat | [ ] No impact

**Current challenges with security/governance:** (check all that apply)
[ ] Different authentication mechanisms per platform
[ ] Inconsistent data classification across systems
[ ] Difficult to track data lineage end-to-end
[ ] Multiple tools needed for access reviews/audits
[ ] Shadow IT / ungoverned data copies

### Technology & Compatibility (if application details unclear)

**Does your team have Postgres expertise?** [ ] Yes - strong | [ ] Some | [ ] No

**Database features required:** (check all that apply)
[ ] Stored procedures (count: _____) | [ ] Triggers | [ ] ACID transactions | [ ] Geospatial data | [ ] Foreign keys

**Can application code be modified?** [ ] Yes - flexible | [ ] Limited changes only | [ ] No - need drop-in replacement

### Scalability & Analytics (if mixed workload unclear)

**How important is automatic scaling during peaks?**
[ ] Critical - must auto-scale | [ ] Prefer it | [ ] Can provision for peak | [ ] Not needed

**Will the same data serve both transactions AND analytics?** [ ] Yes | [ ] No

**How fresh does analytical data need to be?**
[ ] Real-time | [ ] Minutes | [ ] Hourly | [ ] Daily OK

### Migration Priority (rank 1-5, 1=highest)

[ ] Cost savings
[ ] Compliance/security
[ ] Hardware EOL
[ ] Performance improvement
[ ] Operational simplification
[ ] ETL elimination / real-time analytics
[ ] Platform consolidation

**Migration timeline:** Phase 1: _____________ | Full: _____________
```

**IMPORTANT:** When generating the follow-up questionnaire:
1. **Always include** the "Data Movement & ETL" and "Architecture & Security Simplification" sections - these are key differentiators for Snowflake
2. **Conditionally include** other sections based on gaps in the initial template
3. Remove sections where the initial template already has clear answers
4. Use business-friendly language throughout (avoid P50, P99, TPS jargon)

---

#### 5.3 Additional Clarifying Questions
After the questionnaire sections, append specific clarifying questions based on the analysis:

```markdown

---

## Clarifying Questions for Customer

The following questions will help validate our recommendation and uncover any factors that might change our assessment:

### Critical Questions (Must Ask)
1. [Question based on missing/unclear critical field]
2. [Question to validate key assumption in recommendation]
3. [Question about specific technical requirement]

### Architecture & Integration Questions
4. What is the current architecture for this workload? (existing database, application stack, deployment environment)
5. What is your current ETL process and would eliminating/simplifying it be valuable?
6. How tightly does this need to integrate with your existing Snowflake environment?

### Operational Questions
7. Who will maintain this system? (Postgres expertise vs Snowflake expertise on the team)
8. What is your tolerance for operational complexity vs performance optimization?
9. Are there compliance or data residency requirements we should consider?

### Scale & Growth Questions
10. What does your 12-month and 24-month growth trajectory look like for this workload?
11. Do you anticipate needing elastic compute to handle traffic spikes?

### Red Flags to Probe
- [Specific concern from template that needs clarification]
- [Potential blocker that needs validation]
```

---

### Step 6: Generate Full Recommendation Report (Appended)

After the summary and clarifying questions, append the full detailed report to the same discovery template file:

```markdown
## Full Recommendation Report

**Customer:** [Customer Name]
**Use Case:** [Use Case Name]
**Date:** [Assessment Date]
**Assessed By:** OLTP Discovery Advisor Skill

---

## Executive Summary

**Recommended Solution:** [PRODUCT NAME]

[1-2 sentence recommendation with primary rationale]

**Confidence Level:** [High/Medium/Low] - based on completeness of discovery data

---

## Template Completeness

### Missing Critical Fields
[List any critical fields that were missing and assumptions made]

### Fields Used for Assessment
| Field | Value | Impact on Decision |
|-------|-------|-------------------|
| P50 Latency | [value] | [how it affected recommendation] |
| ... | ... | ... |

---

## Product Fit Analysis

### Scoring Summary
| Product | Score | Blockers | Fit Assessment |
|---------|-------|----------|----------------|
| Hybrid Tables | [X/15] | [None/List] | [Best Fit/Alternative/Not Recommended] |
| Snowflake Postgres | [X/15] | [None/List] | [Best Fit/Alternative/Not Recommended] |
| Interactive Tables | [X/15] | [None/List] | [Best Fit/Alternative/Not Recommended] |
| Standard Tables | [X/15] | [None/List] | [Best Fit/Alternative/Not Recommended] |

### Detailed Scoring
[Breakdown of how each requirement scored for each product]

---

## Primary Recommendation: [PRODUCT NAME]

### Why This Solution
1. [Key reason 1 tied to customer requirement]
2. [Key reason 2 tied to customer requirement]
3. [Key reason 3 tied to customer requirement]

### Caveats & Considerations
- [Caveat 1]
- [Caveat 2]

### Expected Outcomes
| Metric | Customer Requirement | Expected with [Product] |
|--------|---------------------|-------------------------|
| P50 Latency | [requirement] | [expected] |
| P99 Latency | [requirement] | [expected] |
| TPS | [requirement] | [supported] |

---

## Alternative Consideration: [SECOND PRODUCT]

### When to Consider Instead
- [Scenario 1 where alternative might be better]
- [Scenario 2 where alternative might be better]

### Trade-offs vs Primary Recommendation
| Aspect | [Primary] | [Alternative] |
|--------|-----------|---------------|
| [Aspect 1] | [comparison] | [comparison] |
| [Aspect 2] | [comparison] | [comparison] |

---

## Solutions NOT Recommended

### [PRODUCT 3] - Not Recommended
**Reason:** [Why this product doesn't fit]
- [Specific blocker or mismatch 1]
- [Specific blocker or mismatch 2]

### [PRODUCT 4] - Not Recommended  
**Reason:** [Why this product doesn't fit]
- [Specific blocker or mismatch 1]

---

## AE Talking Points

### Opening the Conversation
> "Based on our analysis of your requirements, we believe [PRODUCT] is the best fit for your [USE CASE] because [PRIMARY REASON]."

### Key Value Propositions for [RECOMMENDED PRODUCT]
1. **[Value Prop 1]:** [Specific benefit tied to customer need]
2. **[Value Prop 2]:** [Specific benefit tied to customer need]
3. **[Value Prop 3]:** [Specific benefit tied to customer need]

### Handling Objections

#### "Why not [ALTERNATIVE PRODUCT]?"
> "[Alternative] is a strong option, and here's how we compared them: [KEY DIFFERENTIATOR]. Given your requirement for [SPECIFIC NEED], [Recommended] provides [SPECIFIC ADVANTAGE]."

#### "What about cost?"
> [Cost positioning for recommended product vs alternatives]

#### "Can we start with [OTHER PRODUCT] and migrate later?"
> [Migration path considerations and recommendations]

### Discovery Questions to Validate Fit
Ask these questions to confirm the recommendation:
1. [Question to validate key assumption 1]
2. [Question to validate key assumption 2]
3. [Question to uncover potential blockers]

### Red Flags to Watch For
- [Red flag 1 that might change recommendation]
- [Red flag 2 that might change recommendation]

---

## Next Steps

1. [ ] Validate recommendation with customer during follow-up call
2. [ ] [Product-specific POC step]
3. [ ] [Technical deep-dive step]
4. [ ] [Pricing/sizing step]

---

## Appendix: Product Comparison Quick Reference

### Hybrid Tables
- **Best for:** True OLTP, sub-10ms point lookups, transactional DML
- **Not for:** Heavy analytics, bulk writes, Postgres compatibility
- **Elastic:** Yes
- **Latency:** < 10ms point lookups

### Snowflake Postgres
- **Best for:** Postgres migrations, Postgres expertise, Postgres extensions
- **Not for:** Elastic scale, Snowflake ecosystem integration
- **Elastic:** No (fixed compute)
- **Latency:** < 10ms point lookups

### Interactive Tables
- **Best for:** Sub-second analytics, dashboards, read-heavy workloads
- **Not for:** Sub-10ms requirements, heavy writes
- **Elastic:** Yes
- **Latency:** Sub-second (not sub-10ms)

### Standard Tables
- **Best for:** Batch analytics, aggregations, cost optimization
- **Not for:** Real-time queries, low latency requirements
- **Elastic:** Yes
- **Latency:** Seconds to minutes
```

---

## Step 7: Save All Output (Append to Original Template)

**IMPORTANT:** All output (summary table, clarifying questions, and full report) should be **appended** to the end of the original discovery template file, NOT saved as a separate file.

```python
import os

# Read the original template
with open(input_template_path, 'r') as f:
    original_content = f.read()

# Append all assessment output to the original template
full_output = original_content + "\n\n" + summary_table + "\n\n" + clarifying_questions + "\n\n" + full_report

# Write back to the SAME file
with open(input_template_path, 'w') as f:
    f.write(full_output)

# Example: If input was /path/to/discovery_template.md
# Output is written to the SAME file: /path/to/discovery_template.md
```

**Output Structure (appended to original template):**
1. `---` separator
2. Quick Recommendation Summary (table with top 2 products)
3. `---` separator  
4. Clarifying Questions for Customer
5. `---` separator
6. Full Recommendation Report

**Note:** The original discovery template content is preserved - assessment output is appended to the end.

---

## When to Apply This Skill

- User provides a discovery template file path
- User asks "analyze this discovery template"
- User asks "is Hybrid Tables a good fit for this customer"
- User asks "should this customer use Postgres or Hybrid Tables"
- User asks "what should I recommend for this OLTP use case"
- User mentions "OLTP discovery" or "discovery template"
- User asks for talking points or recommendations for OLTP products
- User asks to "validate the template with Snowhouse" or "check actual telemetry"

---

## Snowhouse Integration (Optional Enhancement)

This skill can optionally integrate with Snowhouse to validate discovery template claims with actual telemetry data. When account information is present in the template, the skill will prompt the user to run Snowhouse analysis.

### Benefits of Snowhouse Validation
1. **Quantitative confirmation** of qualitative POC findings
2. **Read:Write ratio calculation** for product selection
3. **Actual latency metrics** (P50, P99) vs documented estimates
4. **Plan cache analysis** to identify optimization opportunities
5. **Ongoing monitoring queries** for continued assessment

### Key Snowhouse Tables Used
| Table | Purpose |
|-------|---------|
| `SNOWHOUSE.PRODUCT.JOB_FACT` | Query execution metrics (latency, volume) |
| `SNOWHOUSE.PRODUCT.STATEMENT_TYPE` | Statement type classification |
| `SNOWHOUSE.PRODUCT.ALL_LIVE_ACCOUNTS` | Account name to ID mapping |

### Connection Requirement
Requires `Snowhouse_PAT` connection with access to SNOWHOUSE.PRODUCT schema.

---

## Product-Specific Guidance

### Hybrid Tables - When to Recommend
**Strong Indicators:**
- P50 latency < 10ms required
- Point lookups dominate workload
- Single-row INSERT/UPDATE/DELETE operations
- Need for elastic compute during spikes
- Primary keys are well-defined
- No Postgres-specific requirements

**Caution Flags:**
- Heavy bulk write operations
- Complex Postgres stored procedures
- Customer strongly prefers Postgres
- Analytical aggregations are primary workload

### Snowflake Postgres - When to Recommend
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

### Interactive Tables - When to Recommend
**Strong Indicators:**
- Sub-second (not sub-10ms) latency needed
- Read-heavy workload (> 90% reads)
- Dashboard/BI query patterns
- Dynamic filtering on large datasets
- Cost-efficiency for read workloads important

**Caution Flags:**
- Sub-10ms latency required
- Significant DML operations
- True transactional requirements
- Single-row lookups dominate

### Standard Tables - When to Recommend
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

## Telemetry

### Telemetry Configuration
| Setting | Value |
|---------|-------|
| Database | `AFE` |
| Schema | `PUBLIC_APP_STATE` |
| Table | `APP_EVENTS` |
| App Name | `OLTP Discovery Advisor (Skill)` |
| App Version | `1.0.0` |

### Using the Telemetry Module
The skill includes a Python telemetry module at `telemetry_cli.py`. Use this for consistent event logging:

```python
import os
import snowflake.connector
from snowflake.snowpark import Session

# Connect to Snowhouse for telemetry logging
conn = snowflake.connector.connect(connection_name=os.getenv("SNOWFLAKE_CONNECTION_NAME") or "Snowhouse_PAT")
session = Session.builder.configs({"connection": conn}).create()

# Import the telemetry module
from telemetry_cli import (
    track_discovery_assessment,
    track_template_parse,
    track_report_generated,
    log_error,
    TelemetryEvents
)

# Track template parsing
track_template_parse(
    session=session,
    customer_name="Acme Corp",
    template_path="/path/to/discovery_template.md",
    fields_found=12,
    fields_missing=3,
    duration_ms=150
)

# Track the full discovery assessment
track_discovery_assessment(
    session=session,
    customer_name="Acme Corp",
    use_case="Real-time inventory lookup",
    recommendation="Hybrid Tables",
    alternative="Snowflake Postgres",
    confidence="High",
    template_completeness="COMPLETE",
    missing_fields=[],
    scores={"hybrid_tables": 13, "postgres": 10, "interactive": 6, "standard": 3},
    duration_ms=2500
)

# Track report generation
track_report_generated(
    session=session,
    customer_name="Acme Corp",
    recommendation="Hybrid Tables",
    output_path="/path/to/discovery_template.md",
    duration_ms=500
)

# Track errors
try:
    # ... assessment logic ...
    pass
except Exception as e:
    log_error(
        session=session,
        action_type=TelemetryEvents.ERROR_ASSESSMENT,
        error=e,
        context={"customer_name": "Acme Corp", "step": "scoring"},
        salesforce_account_name="Acme Corp"
    )
```

### Telemetry Events
| Event | Description |
|-------|-------------|
| `APP_LAUNCH` | Skill invoked |
| `RUN_DISCOVERY_ASSESSMENT` | Full assessment completed |
| `TEMPLATE_PARSED` | Discovery template parsed and validated |
| `REPORT_GENERATED` | Recommendation report appended to template |
| `CLARIFYING_QUESTIONS_GENERATED` | Questions for customer generated |
| `ERROR_PARSE` | Error parsing template |
| `ERROR_ASSESSMENT` | Error during assessment |
| `ERROR_REPORT` | Error generating report |

### Legacy SQL-Based Logging (Alternative)
For simple logging without the Python module:

```bash
snow sql -c Snowhouse_PAT -q "
INSERT INTO AFE.PUBLIC_APP_STATE.APP_EVENTS (
    APP, APP_NAME, APP_VERSION, USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
    SALESFORCE_ACCOUNT_NAME,
    ACTION_TYPE, ACTION_CONTEXT, SUCCESS, DURATION_MS
)
SELECT
    'OLTP Discovery Advisor (Skill)',
    'OLTP Discovery Advisor (Skill)',
    '1.0.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    '<CUSTOMER_NAME>',
    'RUN_DISCOVERY_ASSESSMENT',
    PARSE_JSON('{
        \"customer_name\": \"<CUSTOMER_NAME>\",
        \"use_case\": \"<USE_CASE>\",
        \"recommendation\": \"<RECOMMENDED_PRODUCT>\",
        \"confidence\": \"<HIGH/MEDIUM/LOW>\",
        \"template_completeness\": \"<COMPLETE/PARTIAL>\",
        \"missing_fields\": [\"field1\", \"field2\"]
    }'),
    TRUE,
    <DURATION_MS>;
"
```
