#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_SKILLS_DIR="$REPO_DIR/skills"
SNOWFLAKE_SKILLS_DIR="$HOME/.snowflake/cortex/skills"

APP_ROOT_DEFAULT="/Users/atimm/Documents/Unistore/General_Cusotmer_query/snowsight_app"
SNOWSIGHT_APP_ROOT="${SNOWSIGHT_APP_ROOT:-$APP_ROOT_DEFAULT}"
APP_SKILL_DIR="$SNOWSIGHT_APP_ROOT/cortex_code_skill/skills"

usage() {
  cat <<USAGE
Usage: $0 <command>

Commands:
  push            Sync repo skills -> ~/.snowflake/cortex/skills
  pull            Sync ~/.snowflake/cortex/skills -> repo skills
  sync-from-app   Sync app skill source -> repo skills/hybrid-table-query-analyzer
  deploy          Alias for push
USAGE
}

cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  usage
  exit 1
fi

case "$cmd" in
  push|deploy)
    mkdir -p "$SNOWFLAKE_SKILLS_DIR"
    rsync -a --delete "$REPO_SKILLS_DIR/" "$SNOWFLAKE_SKILLS_DIR/"
    echo "Synced repo -> $SNOWFLAKE_SKILLS_DIR"
    ;;
  pull)
    mkdir -p "$REPO_SKILLS_DIR"
    rsync -a --delete "$SNOWFLAKE_SKILLS_DIR/" "$REPO_SKILLS_DIR/"
    echo "Synced $SNOWFLAKE_SKILLS_DIR -> repo"
    ;;
  sync-from-app)
    if [[ ! -d "$APP_SKILL_DIR" ]]; then
      echo "App skill directory not found: $APP_SKILL_DIR" >&2
      exit 1
    fi
    mkdir -p "$REPO_SKILLS_DIR/hybrid-table-query-analyzer"
    rsync -a --delete "$APP_SKILL_DIR/hybrid-table-query-analyzer/" "$REPO_SKILLS_DIR/hybrid-table-query-analyzer/"
    if [[ -f "$SNOWSIGHT_APP_ROOT/analysis_shared.py" ]]; then
      mkdir -p "$REPO_SKILLS_DIR/hybrid-table-query-analyzer/ht_analyzer"
      cp "$SNOWSIGHT_APP_ROOT/analysis_shared.py" "$REPO_SKILLS_DIR/hybrid-table-query-analyzer/ht_analyzer/analysis_shared.py"
    fi
    if [[ -f "$SNOWSIGHT_APP_ROOT/analysis_shared_sql.py" ]]; then
      mkdir -p "$REPO_SKILLS_DIR/hybrid-table-query-analyzer/ht_analyzer"
      cp "$SNOWSIGHT_APP_ROOT/analysis_shared_sql.py" "$REPO_SKILLS_DIR/hybrid-table-query-analyzer/ht_analyzer/analysis_shared_sql.py"
    fi
    echo "Synced app -> repo (hybrid-table-query-analyzer)"
    ;;
  *)
    usage
    exit 1
    ;;
esac
