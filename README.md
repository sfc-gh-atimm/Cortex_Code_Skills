# Cortex Code Skills

This repo is the source of truth for local Cortex Code skills.

## Structure
- `skills/` — skills synced to `~/.snowflake/cortex/skills`
- `sync_skills.sh` — sync utility

## Skills

### hybrid-table-query-analyzer
Analyzes Hybrid Table query performance using Snowhouse telemetry and SnowVI JSON exports.

**Features:**
- Fetches Snowhouse metadata for a given query UUID
- Enriches analysis with SnowVI JSON exports (optional)
- Applies policy-guided best practices analysis
- Generates ASE-facing diagnosis and next steps via Cortex LLM
- Interactive mode prompts for inputs when invoked without flags

**Usage:**
```bash
python scripts/run_ht_analysis.py \
  --uuid "<query_uuid>" \
  --snowvi-path "<path_to_snowvi_json>" \
  --snowhouse-connection "Snowhouse" \
  --include-snowvi-link \
  --debug
```

**Flags:**
| Flag | Description |
|------|-------------|
| `--uuid` | Query UUID to analyze (required) |
| `--snowvi-path` | Path to SnowVI JSON export (optional) |
| `--deployment` | Snowflake deployment (auto-detected from SnowVI) |
| `--snowhouse-connection` | Snowflake CLI connection name (default: snowhouse) |
| `--include-snowvi-link` | Include SnowVI URL in output |
| `--include-history-table` | Include query history table and timeline |
| `--debug` | Show progress messages, disable telemetry |

### workload-assessment
Assesses workload suitability for Standard Tables, Hybrid Tables, or Interactive Analytics using customer session ID via Snowhouse queries.

**Features:**
- Analyzes query patterns from a customer session ID
- Calculates read:write ratio from 30-day account history
- Recommends optimal table type based on workload characteristics
- Generates markdown assessment reports
- Logs telemetry to `AFE.PUBLIC_APP_STATE.APP_EVENTS`
- Uses batched queries with PAT authentication for performance

**Input Parameters:**
| Parameter | Description |
|-----------|-------------|
| Session ID | Customer session ID to analyze |
| Deployment | Snowflake deployment region (e.g., va3) |
| Account Locator | Customer account locator (e.g., GCB59607) |
| Report Path | Where to save the assessment report |

**Decision Criteria:**
| Read:Write Ratio | Recommendation |
|------------------|----------------|
| > 10,000:1 | Interactive Analytics |
| 1,000:1 - 10,000:1 | Interactive Analytics (if read-only acceptable) |
| < 100:1 with OLTP pattern | Hybrid Tables |
| Batch analytical | Standard Tables |

**Connections Required:**
- `Snowhouse_PAT` (recommended) - PAT authentication for non-interactive use
- `Snowhouse` (fallback) - externalbrowser authentication

## Common Commands

Deploy repo skills to local Cortex folder:
```bash
./sync_skills.sh push
```

Pull current local Cortex skills into repo:
```bash
./sync_skills.sh pull
```
