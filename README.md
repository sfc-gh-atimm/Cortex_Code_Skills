# Cortex Code Skills

This repo is the source of truth for local Cortex Code skills.

## Structure

```
cortex_skills_repo/
├── skills/
│   ├── hybrid-table-query-analyzer/   # HT query performance analysis
│   └── workload-assessment/           # Table type recommendation
├── sync_skills.sh                     # Sync utility
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

## Sync Commands

Deploy repo skills to local Cortex folder:
```bash
./sync_skills.sh push
```

Pull current local Cortex skills into repo:
```bash
./sync_skills.sh pull
```

Sync hybrid-table-query-analyzer from Snowsight app source:
```bash
./sync_skills.sh sync-from-app
```

## Telemetry

All skills log events to `AFE.PUBLIC_APP_STATE.APP_EVENTS` for usage tracking.
