# Workload Assessment Skill

Assesses workload suitability for Standard Tables, Hybrid Tables, or Interactive Analytics using customer session ID via Snowhouse queries.

## Overview

This skill analyzes query patterns from a customer session ID using Snowhouse internal data to recommend the optimal table type. All queries run against Snowhouse - no customer environment access required.

## Features

- Analyzes query patterns from a customer session ID
- Calculates read:write ratio from 30-day account history
- Recommends optimal table type based on workload characteristics
- Generates markdown assessment reports
- Logs telemetry to `AFE.PUBLIC_APP_STATE.APP_EVENTS`
- Uses batched queries with PAT authentication for performance

## Input Parameters

| Parameter | Description |
|-----------|-------------|
| Session ID | Customer session ID to analyze |
| Deployment | Snowflake deployment region (e.g., va3) |
| Account Locator | Customer account locator (e.g., GCB59607) |
| Report Path | Where to save the assessment report |

## Decision Criteria

| Read:Write Ratio | Recommendation |
|------------------|----------------|
| > 10,000:1 | Interactive Analytics |
| 1,000:1 - 10,000:1 | Interactive Analytics (if read-only acceptable) |
| 100:1 - 1,000:1 | Evaluate latency requirements |
| < 100:1 with OLTP pattern | Hybrid Tables |
| Batch analytical | Standard Tables |

## Connections Required

| Connection | Auth Type | Usage |
|------------|-----------|-------|
| `Snowhouse` | Programmatic Access Token | Recommended (non-interactive) |
| `Snowhouse` | externalbrowser | Fallback (interactive) |

## Telemetry

Events are logged to `AFE.PUBLIC_APP_STATE.APP_EVENTS`:

| Event | Description |
|-------|-------------|
| `RUN_ASSESSMENT` | Successful assessment completed |
| `ERROR_ASSESSMENT` | Assessment failed |

App identifier: `Workload Assessment (Skill)`

## Example Trigger Phrases

- "Analyze session 5377868606057860091 for table optimization"
- "Is this workload suitable for Hybrid Tables?"
- "Would Interactive Analytics work for this customer?"
- "Assess workload for account GCB59607"

## Files

- `SKILL.md` - Main skill definition with workflow, queries, and templates
