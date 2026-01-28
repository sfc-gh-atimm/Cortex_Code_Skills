# Unistore Propensity

Analyzes customer workloads via Snowhouse telemetry to identify tables/queries suitable for conversion to Hybrid Tables or Interactive Analytics.

## Overview

This skill takes a customer name (or other identifying information) and queries Snowhouse for the last 30 days of activity to find:

1. **Hybrid Table candidates** - Tables with high UPDATE/DELETE activity, point lookup patterns, and sub-10ms latency needs
2. **Interactive Analytics candidates** - Read-heavy tables (99%+ reads) with sub-second latency requirements

## Features

- Customer account lookup by name (partial match supported)
- Automated analysis of query patterns across all customer tables
- Scoring system for candidate prioritization
- Sample query extraction for validation
- Markdown report generation with actionable recommendations
- Telemetry logging to `AFE.PUBLIC_APP_STATE.APP_EVENTS`

## Input Parameters

| Parameter | Description |
|-----------|-------------|
| Customer Name | Full or partial customer name for account lookup |
| Deployment | Deployment region (or 'unknown' to search all) |
| Analysis Period | 7, 14, or 30 days of history |
| Report Path | Where to save the analysis report |

## Hybrid Table Scoring Criteria

| Criteria | Score |
|----------|-------|
| UPDATE % > 1% | +3 |
| DELETE % > 0.5% | +2 |
| Point lookups > 50% | +3 |
| P50 latency need < 10ms | +3 |
| Single-row DML dominant | +2 |
| Primary key in WHERE | +2 |

**Score >= 8**: Strong candidate

## Interactive Analytics Scoring Criteria

| Criteria | Score |
|----------|-------|
| Read % >= 99% | +3 |
| Read % 95-99% | +2 |
| P50 latency 100ms-1s | +3 |
| Dashboard/BI patterns | +2 |
| Current latency > 1s | +2 |
| High query volume | +1 |

**Score >= 8**: Strong candidate

## Connections Required

| Connection | Auth Type | Usage |
|------------|-----------|-------|
| `Snowhouse` | Programmatic Access Token | Recommended (non-interactive) |
| `Snowhouse` | externalbrowser | Fallback (interactive) |

## Telemetry

Events are logged to `AFE.PUBLIC_APP_STATE.APP_EVENTS`:

| Event | Description |
|-------|-------------|
| `RUN_ANALYSIS` | Successful analysis completed |
| `ERROR_ANALYSIS` | Analysis failed |

App identifier: `Unistore Propensity (Skill)`

## Example Trigger Phrases

- "Analyze workloads for Acme Corp"
- "Find Hybrid Table candidates for customer XYZ"
- "Which tables should be Interactive Analytics for [customer]"
- "Prospect [customer] for Unistore opportunities"
- "Identify conversion candidates for account ABC123"

## Files

- `SKILL.md` - Main skill definition with workflow, queries, and templates
