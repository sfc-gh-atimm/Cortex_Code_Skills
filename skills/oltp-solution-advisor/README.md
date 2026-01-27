# OLTP Discovery Advisor

An interactive Cortex Code skill that analyzes OLTP Discovery Templates and recommends the best-fit Snowflake solution.

## Purpose

This skill helps OLTP Sales Specialists and Applied Field Engineers (AFEs) quickly assess customer discovery templates and generate:

1. **Completeness feedback** - Identifies missing critical fields
2. **Product recommendations** - Hybrid Tables, Snowflake Postgres, Interactive Tables, or Standard Tables
3. **AE talking points** - Ready-to-use conversation starters and objection handlers

## Usage

Invoke the skill by mentioning discovery templates or OLTP fit assessment:

```
"Analyze the discovery template at /path/to/template.md"
"Is Hybrid Tables a good fit for this customer?"
"Review this OLTP discovery and recommend a solution"
```

## Workflow

1. Provide path to the completed (or partial) discovery template
2. Skill parses template and checks for missing critical fields
3. If incomplete, skill asks clarifying questions
4. Skill evaluates requirements against product capabilities
5. Generates recommendation report with:
   - Best fit product and rationale
   - Scoring breakdown for all products
   - AE talking points
   - Next steps

## Output

Report saved as `<original_template>_recommendation.md` in the same folder.

## Products Evaluated

| Product | Use Case |
|---------|----------|
| Hybrid Tables | Sub-10ms OLTP, transactional DML |
| Snowflake Postgres | Postgres migrations, Postgres expertise |
| Interactive Tables | Sub-second analytics, dashboards |
| Standard Tables | Batch analytics, cost optimization |

## Critical Discovery Fields

These fields are required for accurate assessment:

- AVG operations per second
- PEAK operations per second  
- P50 Latency Expectation
- P99 Latency Expectation
- Bulk Writes & Updates
- Primary Keys well defined?

## Telemetry

Usage is logged to `AFE.PUBLIC_APP_STATE.APP_EVENTS` for tracking skill adoption.
