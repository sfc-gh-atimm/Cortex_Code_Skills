# Cortex Code Skills

This repo is the source of truth for local Cortex Code skills.

## Structure
- `skills/` — skills synced to `~/.snowflake/cortex/skills`
- `sync_skills.sh` — sync utility

## Common commands

Deploy repo skills to local Cortex folder:
```
./sync_skills.sh push
```

Pull current local Cortex skills into repo:
```
./sync_skills.sh pull
```

Sync from app source (hybrid-table-query-analyzer):
```
./sync_skills.sh sync-from-app
```

## Notes
Set `SNOWSIGHT_APP_ROOT` if the app repo path changes:
```
export SNOWSIGHT_APP_ROOT=/path/to/snowsight_app
```
