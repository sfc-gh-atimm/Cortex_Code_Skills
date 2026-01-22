# Cortex Code Skills

This repo is the source of truth for local Cortex Code skills.

## Setup

Symlink this repo's skills folder to Cortex Code:
```bash
ln -s /Users/atimm/Documents/Unistore/cortex_skills_repo/skills ~/.snowflake/cortex/skills
```

## Structure

```
cortex_skills_repo/
├── skills/
│   ├── hybrid-table-query-analyzer/   # HT query performance analysis
│   └── workload-assessment/           # Table type recommendation
└── README.md
```

## Skills

| Skill | Description | Telemetry App |
|-------|-------------|---------------|
| [hybrid-table-query-analyzer](skills/hybrid-table-query-analyzer/README.md) | Analyzes Hybrid Table query performance using Snowhouse + SnowVI | `Hybrid Table Query Analyzer (Skill)` |
| [workload-assessment](skills/workload-assessment/README.md) | Recommends Standard/Hybrid/Interactive Analytics based on workload | `Workload Assessment (Skill)` |

## Connections Required

Both skills query Snowhouse. Configure in `~/.snowflake/connections.toml`:

| Connection | Auth Type | Usage |
|------------|-----------|-------|
| `Snowhouse_PAT` | Programmatic Access Token | Recommended (non-interactive) |
| `Snowhouse` | externalbrowser | Fallback (interactive) |

## Development Workflow

1. Edit skills directly in `skills/` folder
2. Test immediately in Cortex Code (reads from symlinked folder)
3. Commit changes to git

## Telemetry

All skills log events to `AFE.PUBLIC_APP_STATE.APP_EVENTS` for usage tracking.
