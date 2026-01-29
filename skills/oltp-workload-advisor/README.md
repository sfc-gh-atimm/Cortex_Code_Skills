# OLTP Workload Advisor

Analyzes customer workloads via Snowhouse telemetry to identify tables/queries suitable for conversion to Hybrid Tables, Interactive Analytics, or Snowflake Postgres.

## Overview

This skill takes a customer name (or other identifying information) and queries Snowhouse for activity to find:

1. **Hybrid Table candidates** - Tables with high UPDATE/DELETE activity, parameterized point lookups, OLTP patterns
2. **Interactive Analytics candidates** - Read-heavy tables (95%+ reads) with sub-second latency requirements, wide tables
3. **Snowflake Postgres candidates** - Postgres CDC pipelines, pg_* table patterns, RDS/Aurora data flows

## Features

- Customer account lookup by name, alternate name, or account locator
- Automated analysis of query patterns across all customer tables
- ETL vs OLTP classification for UPDATE patterns
- Scoring system for candidate prioritization
- Sample query extraction for validation
- **Two output formats:**
  - Markdown report with actionable recommendations
  - Interactive Streamlit dashboard with Plotly visualizations
- Telemetry logging with CoCo request ID tracking

## Skill Structure

```
oltp-workload-advisor/
├── SKILL.md                    # Main skill definition (workflow + queries)
├── README.md                   # This file
├── references/
│   ├── snowhouse_reference.md  # Table schemas, company aliases
│   ├── scoring_guide.md        # Decision framework, scoring criteria
│   └── report_template.md      # Markdown output template
└── dashboard/
    ├── app.py                  # Streamlit dashboard application
    └── telemetry.py            # Dashboard telemetry helpers
```

## Input Parameters

| Parameter | Description |
|-----------|-------------|
| Customer Name | Full or partial customer name for account lookup |
| Alternate Name | Former/alternate company name (optional) |
| Account Locator | Direct account locator if known (e.g., GCB59607) |
| Deployment | Deployment region (or 'unknown' to search all) |
| Analysis Period | 7, 14, or 30 days of history |
| Output Format | Markdown Report or Streamlit Dashboard |
| Report Path | Where to save analysis output |

## Products Evaluated

| Product | Best For | Key Indicators |
|---------|----------|----------------|
| **Hybrid Tables** | True OLTP with sub-10ms point lookups | High UPDATE/DELETE %, parameterized queries |
| **Interactive Analytics** | Read-heavy analytics on wide tables | 99%+ reads, wide tables, dashboard patterns |
| **Snowflake Postgres** | PostgreSQL-compatible workloads | Postgres CDC pipelines, pg_* tables, RDS/Aurora |

## Connections Required

| Connection | Auth Type | Usage |
|------------|-----------|-------|
| `Snowhouse` | Programmatic Access Token | Required for Snowhouse queries |

## Telemetry

Events are logged to `AFE.PUBLIC_APP_STATE.APP_EVENTS`:

| Setting | Value |
|---------|-------|
| App Name | `oltp-workload-advisor` |
| App Version | `2.5.0` |
| Action Type | `RUN_PROPENSITY_ANALYSIS` |

Telemetry includes CoCo request/session ID for traceability.

## Example Trigger Phrases

- "Analyze workloads for Acme Corp"
- "Find Hybrid Table candidates for customer XYZ"
- "Which tables should be Interactive Analytics for [customer]"
- "Prospect [customer] for Unistore opportunities"
- "Identify conversion candidates for account ABC123"
- "Is [customer] a good fit for Snowflake Postgres"
- "Detect Postgres data flows for [customer]"
- "Find customers with Postgres ETL patterns"

## Dashboard

Launch the interactive dashboard after generating analysis output:

```bash
streamlit run dashboard/app.py --server.port 8502 --server.headless true
```

Dashboard features:
- Daily timeline with stacked area charts
- Hybrid Table candidate scatter plots (volume vs latency)
- Interactive Analytics read-heavy table analysis
- Snowflake Postgres inbound/outbound flow visualization
- Executive summary with recommendations
