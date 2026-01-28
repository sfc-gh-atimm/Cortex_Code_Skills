# OLTP Solution Advisor

An interactive Cortex Code skill that analyzes OLTP Discovery Templates and recommends the best-fit Snowflake solution.

## Purpose

This skill helps OLTP Sales Specialists and Applied Field Engineers (AFEs) quickly assess customer discovery templates and generate:

1. **Completeness feedback** - Identifies missing critical fields
2. **Product recommendations** - Hybrid Tables, Snowflake Postgres, Interactive Tables, or Standard Tables
3. **AE talking points** - Ready-to-use conversation starters and objection handlers

## Supported File Formats

| Format | Method |
|--------|--------|
| Markdown (.md) | Read directly |
| Word (.docx) | python-docx extraction (venv at `~/.cortex/venvs/oltp-solution-advisor/`) |
| PDF (.pdf) | Native `read` tool support |

## Usage

Invoke the skill by mentioning discovery templates or OLTP fit assessment:

```
"Analyze the discovery template at /path/to/template.md"
"Analyze /path/to/template.docx"
"Is Hybrid Tables a good fit for this customer?"
"Review this OLTP discovery and recommend a solution"
```

## Workflow

1. Provide path to the completed (or partial) discovery template (.md, .docx, or .pdf)
2. Skill parses template and checks for missing critical fields
3. If incomplete, skill asks clarifying questions
4. Skill evaluates requirements against product capabilities
5. Generates recommendation report **appended to the original template** with:
   - Quick recommendation summary table
   - Clarifying questions for customer
   - Full recommendation report with scoring breakdown
   - AE talking points

## Output

Assessment output is **appended** to the original template file (not saved as a separate file).

## Products Evaluated

| Product | Use Case |
|---------|----------|
| Hybrid Tables | Sub-50ms OLTP, transactional DML |
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

## Dependencies

- **python-docx**: Auto-installed in skill venv at `~/.cortex/venvs/oltp-solution-advisor/`

## Telemetry

Usage is logged to `AFE.PUBLIC_APP_STATE.APP_EVENTS`:

```python
from telemetry_cli import log_event

log_event(
    session,
    app_name="oltp-solution-advisor",
    action_type="ASSESSMENT",
    account="CUSTOMER_ACCOUNT",
    recommendation="HT",
    context={"customer_name": "...", "scores": {...}, "input_document": "..."}
)
```

Key queryable columns:
- `USER_NAME` - Who ran the assessment
- `SNOWFLAKE_ACCOUNT_ID` - Customer account analyzed  
- `RECOMMENDATION` - Final recommendation (HT, PG, IA, STANDARD)
- `ACTION_CONTEXT` - Full analysis details (VARIANT)

### Joining with Cortex Code CLI Telemetry

The `cortex_request_id` is automatically captured in `ACTION_CONTEXT` when running inside Cortex Code, enabling correlation with CLI request telemetry:

```sql
SELECT 
    e.EVENT_TS,
    e.USER_NAME,
    e.RECOMMENDATION,
    e.ACTION_CONTEXT,
    r.*
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS e
LEFT JOIN <db>.CORTEX_CODE_CLI_REQUEST_FACT r
    ON e.ACTION_CONTEXT:cortex_request_id::STRING = r.REQUEST_ID
WHERE e.APP_NAME = 'oltp-solution-advisor'
ORDER BY e.EVENT_TS DESC;
```
