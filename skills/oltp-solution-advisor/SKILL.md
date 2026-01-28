---
name: oltp-solution-advisor
description: "Analyze OLTP discovery templates to recommend Hybrid Tables vs Postgres vs Interactive Tables. Triggers: discovery template, OLTP fit, product recommendation, should this customer use Hybrid Tables."
---

# OLTP Solution Advisor

Analyzes completed OLTP Discovery Templates to recommend the best-fit Snowflake solution.

## When to Apply

- User provides a discovery template file path
- User asks "analyze this discovery template"
- User asks "is Hybrid Tables a good fit for this customer"
- User asks "should this customer use Postgres or Hybrid Tables"
- User asks "what should I recommend for this OLTP use case"
- User mentions "OLTP discovery" or "discovery template"

## Products Evaluated

| Product | Best For |
|---------|----------|
| **Hybrid Tables** | True OLTP: sub-50ms point lookups, high single-row DML, transactional consistency |
| **Snowflake Postgres** | Postgres-native apps, Postgres expertise, complex extensions/stored procs |
| **Interactive Tables** | Read-heavy analytics requiring sub-second (not sub-10ms) response |
| **Standard Tables** | Batch analytics, aggregations, cost-optimized queries |

> **For detailed decision criteria:** Read `references/product_guidance.md`

---

## Workflow

### Step 0: Determine User Intent

Use `ask_user_question` to determine if user wants to:
1. **Generate a blank questionnaire** - Create template for AE/SE to complete with customer
2. **Analyze a completed questionnaire** - Get product recommendation

### Step 0a: Generate Blank Template

If generating a blank template:
1. Ask for customer name and output path
2. Read `references/blank_template.md` for the standard template format
3. Save with customer name filled in

### Step 1: Collect Discovery Template

For analysis, ask for the path to the completed template file.

### Step 2: Parse Template and Extract Fields

#### Critical Fields (Assessment cannot proceed without):
- AVG operations per second
- PEAK operations per second  
- P50 Latency Expectation
- P99 Latency Expectation
- Bulk Writes & Updates
- Primary Keys well defined?

#### Latency Value Parsing

| Raw Value | Interpretation |
|-----------|----------------|
| `<1s`, `sub-second` | < 1000ms |
| `<100ms` | < 100ms |
| `<10ms`, `sub-10ms` | < 10ms |
| `1-10ms`, `10-50ms`, `50-100ms` | Range in ms |

**Important:** "less than 1 second" is a valid, specific requirement (sub-second latency).

### Step 3: Completeness Check

If critical fields are missing, use `ask_user_question` to gather them before proceeding.

### Step 3.5: Snowhouse Validation (Optional)

If Snowflake account info is present, offer to validate with actual telemetry:

> **For Snowhouse queries:** Read `references/snowhouse_queries.md`

### Step 4: Decision Matrix Evaluation

> **For scoring model and decision tree:** Read `references/product_guidance.md`

Use the scoring model (0-3 scale) to evaluate each product. Identify:
- **Best Fit**: Highest score with no blockers
- **Alternative**: Second-highest score with no blockers
- **Not Recommended**: Products with blockers or low scores

### Step 5: Log Telemetry (REQUIRED)

**After completing the assessment, you MUST log telemetry.** Execute via `snow sql`:

```bash
snow sql -c Snowhouse -q "
INSERT INTO AFE.PUBLIC_APP_STATE.APP_EVENTS (
    APP, APP_NAME, APP_VERSION,
    USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
    SNOWFLAKE_ACCOUNT_ID,
    ACTION_TYPE, ACTION_CONTEXT,
    RECOMMENDATION,
    SUCCESS
)
SELECT
    'oltp-solution-advisor',
    'oltp-solution-advisor',
    '1.0.0',
    CURRENT_USER(),
    CURRENT_ROLE(),
    CURRENT_ACCOUNT(),
    '<ACCOUNT_ID>',
    'RUN_DISCOVERY_ASSESSMENT',
    PARSE_JSON('{
        \"customer_name\": \"<CUSTOMER_NAME>\",
        \"use_case\": \"<USE_CASE>\",
        \"use_case_link\": \"<SFDC_LINK>\",
        \"alternative\": \"<ALTERNATIVE>\",
        \"confidence\": \"<High|Medium|Low>\",
        \"template_completeness\": \"<COMPLETE|PARTIAL>\",
        \"scores\": {\"hybrid_tables\": <HT>, \"postgres\": <PG>, \"interactive\": <IA>, \"standard\": <ST>},
        \"cortex_request_id\": \"<CORTEX_REQUEST_ID>\",
        \"coco_context\": {
            \"session_id\": \"<CORTEX_SESSION_ID>\",
            \"conversation_id\": \"<CORTEX_CONVERSATION_ID>\",
            \"user_id\": \"<CORTEX_USER_ID>\",
            \"account\": \"<CORTEX_ACCOUNT>\",
            \"model\": \"<CORTEX_MODEL>\"
        },
        \"assessment_details\": {
            \"template_path\": \"<TEMPLATE_FILE_PATH>\",
            \"missing_fields\": [<LIST_OF_MISSING_FIELDS>],
            \"blockers\": [<LIST_OF_BLOCKERS>],
            \"key_factors\": [<KEY_DECISION_FACTORS>],
            \"snowhouse_validated\": <true|false>,
            \"latency_requirements\": {\"p50\": \"<P50_MS>\", \"p99\": \"<P99_MS>\"},
            \"ops_per_second\": {\"avg\": <AVG_OPS>, \"peak\": <PEAK_OPS>}
        }
    }'),
    '<RECOMMENDATION>',
    TRUE
;"
```

Replace `<PLACEHOLDERS>` with actual values from the assessment.

---

## Output Format

**Append all output to the original discovery template file.** Do not create separate files.

### Quick Recommendation Summary (append first)

```markdown
---

# OLTP Solution Advisor Assessment
**Assessment Date:** [Date]

## Quick Recommendation Summary

| Rank | Product | Score | Key Fit Reasons | Primary Concerns |
|------|---------|-------|-----------------|------------------|
| 1st | [PRODUCT] | [X/15] | [reasons] | [caveats] |
| 2nd | [PRODUCT] | [X/15] | [reasons] | [caveats] |

**Confidence Level:** [High/Medium/Low]
**Quick Take:** [1-2 sentence summary]
```

### Follow-up Questions for Customer

Generate business-friendly questions (avoid P50/P99 jargon) for missing/unclear areas:
- Response time requirements
- Transaction volume
- Read vs Write patterns
- **Data Movement & ETL** (always include - key differentiator)
- **Architecture & Security Simplification** (always include - key differentiator)
- Technology compatibility
- Scalability needs

### Full Recommendation Report

Include:
1. Executive Summary with confidence level
2. Template Completeness analysis
3. Product Fit Analysis with scoring breakdown
4. Primary Recommendation with reasons and caveats
5. Alternative Consideration with trade-offs
6. Solutions NOT Recommended with reasons
7. AE Talking Points (opening, value props, objection handling)
8. Next Steps checklist

### Support References (always append)

```markdown
## Helpful Unistore References
- [#unistore-workload](https://snowflake.enterprise.slack.com/archives/C02GHK5EN1Z)
- [#support-unistore](https://snowflake.enterprise.slack.com/archives/C02R14PHAC9)
- Tag: `@unistore-gtm-team`

## Helpful Postgres References
- [#ask-snowflake-postgres](https://snowflake.enterprise.slack.com/archives/C08V01BHQBX)

## Helpful Interactive Analytics References
- Interactive Compass page
```

---

## Telemetry Configuration

| Setting | Value |
|---------|-------|
| Database | `AFE` |
| Schema | `PUBLIC_APP_STATE` |
| Table | `APP_EVENTS` |
| App Name | `oltp-solution-advisor` |

---

## Key Considerations

When making recommendations, also evaluate:
1. Architectural complexity of adding/integrating the proposed solution
2. Overhead of implementing/maintaining the proposed solution
3. Customer's current ETL process and desire to eliminate it
4. Whether customer requires GA, Public Preview, or accepts Private Preview
