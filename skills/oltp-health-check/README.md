# OLTP Health Check Skill

Health monitoring and performance diagnostics for existing OLTP workloads (Hybrid Tables, Interactive Analytics, Snowflake Postgres).

## Purpose

This skill monitors **existing** OLTP product usage and identifies performance issues. It complements the `oltp-workload-advisor` skill which focuses on **prospecting** (finding conversion candidates).

| Skill | Purpose |
|-------|---------|
| `oltp-workload-advisor` | Find tables that should be HT/IA/Postgres |
| `oltp-health-check` | Monitor how existing HT/IA/Postgres are performing |

## Features

- **Usage Detection**: Automatically detects which OLTP products are in use
- **Health Scoring**: 0-100 health scores for each product
- **Latency Trends**: Daily P50/P99 latency tracking
- **Issue Detection**: Identifies performance problems with severity levels
- **Remediation Guidance**: Provides specific recommendations for each issue
- **Interactive Dashboard**: Streamlit visualization with health cards and charts

## Products Monitored

### Hybrid Tables
- P50/P99 latency trends
- Performance tier distribution (optimal vs. slow queries)
- FDB timeout rate
- Query pattern analysis

### Interactive Analytics
- Sub-second query percentage
- Compilation time overhead
- Daily performance trends

### Snowflake Postgres
- Query latency distribution
- Daily throughput and session counts
- Connection patterns

## Usage

```
"Check the health of Acme Corp's OLTP workloads"
"How are Hybrid Tables performing for customer X?"
"Are there any FDB issues for Elevance Health?"
"Run an OLTP health check on account GCB59607"
```

## Output

- **Markdown Report**: Health scores, trends, issues, and recommendations
- **Streamlit Dashboard**: Interactive visualization at http://localhost:8503

## Health Scoring

| Score | Status | Meaning |
|-------|--------|---------|
| 80-100 | HEALTHY | Workload performing as expected |
| 50-79 | WARNING | Some optimization opportunities |
| 0-49 | CRITICAL | Immediate action required |

## Files

```
oltp-health-check/
├── SKILL.md                       # Main skill definition
├── README.md                      # This file
├── references/
│   ├── health_scoring_guide.md    # Scoring thresholds
│   ├── snowhouse_reference.md     # Snowhouse table schemas
│   └── issue_patterns.md          # Issue detection & remediation
└── dashboard/
    └── app.py                     # Streamlit health dashboard
```

## Prerequisites

- Snowhouse connection configured (`Snowhouse` with PAT authentication)
- Access to `SNOWHOUSE.PRODUCT` and `SNOWHOUSE_IMPORT.<DEPLOYMENT>` views
