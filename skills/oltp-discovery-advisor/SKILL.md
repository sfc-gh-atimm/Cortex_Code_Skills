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

### Step 1: Collect Discovery Template
Ask the user for the path to the discovery template file:

```json
{
  "questions": [
    {"header": "Template", "question": "Enter the path to the OLTP Discovery Template file", "type": "text", "defaultValue": "/path/to/discovery_template.md"}
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

#### 5.2 Clarifying Questions for Customer Follow-up
Immediately after the summary table, append clarifying questions the AE should take back to the customer:

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

### Log Assessment Event
After generating the recommendation report:

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
