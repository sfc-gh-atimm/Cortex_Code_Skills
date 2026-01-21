from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from snowflake.snowpark import Session

TELEMETRY_DATABASE = "AFE"
TELEMETRY_SCHEMA = "PUBLIC_APP_STATE"
TELEMETRY_TABLE = "APP_EVENTS"
APP_NAME = "Hybrid Table Query Analyzer (Skill)"
APP_VERSION = "2.1.0"


def _get_events_table() -> str:
    return f"{TELEMETRY_DATABASE}.{TELEMETRY_SCHEMA}.{TELEMETRY_TABLE}"


def _get_identity(session: Session) -> Dict[str, str]:
    try:
        row = session.sql(
            """
            SELECT CURRENT_USER() AS user_name,
                   CURRENT_ROLE() AS role_name,
                   CURRENT_ACCOUNT() AS account_name
            """
        ).collect()[0]
        return {
            "user_name": row["USER_NAME"],
            "role_name": row["ROLE_NAME"],
            "account_name": row["ACCOUNT_NAME"],
        }
    except Exception:
        return {
            "user_name": "UNKNOWN",
            "role_name": "UNKNOWN",
            "account_name": "UNKNOWN",
        }


def log_event(
    session: Session,
    action_type: str,
    success: bool = True,
    error_message: Optional[str] = None,
    salesforce_account_id: Optional[str] = None,
    salesforce_account_name: Optional[str] = None,
    snowflake_account_id: Optional[str] = None,
    deployment: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
) -> bool:
    try:
        ident = _get_identity(session)
        ctx_json = json.dumps(context or {})

        if error_message and len(error_message) > 500:
            error_message = error_message[:497] + "..."

        insert_sql = f"""
            INSERT INTO {_get_events_table()} (
                APP, APP_NAME, APP_VERSION, USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
                SALESFORCE_ACCOUNT_ID, SALESFORCE_ACCOUNT_NAME,
                SNOWFLAKE_ACCOUNT_ID, DEPLOYMENT,
                ACTION_TYPE, ACTION_CONTEXT, SUCCESS, ERROR_MESSAGE, DURATION_MS,
                VIEWER_EMAIL
            )
            SELECT
                ?, ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, PARSE_JSON(?), ?, ?, ?,
                ?
        """

        session.sql(
            insert_sql,
            params=[
                APP_NAME,
                APP_NAME,
                APP_VERSION,
                ident["user_name"],
                ident["role_name"],
                ident["account_name"],
                salesforce_account_id,
                salesforce_account_name,
                snowflake_account_id,
                deployment,
                action_type,
                ctx_json,
                success,
                error_message,
                duration_ms,
                None,
            ],
        ).collect()
        return True
    except Exception:
        return False


def log_error(
    session: Session,
    action_type: str,
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    snowflake_account_id: Optional[str] = None,
    deployment: Optional[str] = None,
) -> bool:
    return log_event(
        session=session,
        action_type=action_type,
        success=False,
        error_message=str(error),
        context=context,
        snowflake_account_id=snowflake_account_id,
        deployment=deployment,
    )


def track_analysis(
    session: Session,
    query_uuid: str,
    analysis_mode: str = "single",
    snowflake_account_id: Optional[str] = None,
    salesforce_account_id: Optional[str] = None,
    salesforce_account_name: Optional[str] = None,
    deployment: Optional[str] = None,
    duration_ms: Optional[int] = None,
    num_findings: int = 0,
    snowvi_enriched: bool = False,
    quick_mode: bool = False,
    extra_context: Optional[Dict[str, Any]] = None,
) -> bool:
    action_type = {
        "single": TelemetryEvents.RUN_ANALYSIS,
        "compare": TelemetryEvents.RUN_COMPARISON,
        "batch": TelemetryEvents.RUN_BATCH_ANALYSIS,
    }.get(analysis_mode, TelemetryEvents.RUN_ANALYSIS)

    context = {
        "query_uuid": query_uuid,
        "analysis_mode": analysis_mode,
        "num_findings": num_findings,
        "snowvi_enriched": snowvi_enriched,
        "quick_mode": quick_mode,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if extra_context:
        context.update(extra_context)

    return log_event(
        session=session,
        action_type=action_type,
        salesforce_account_id=salesforce_account_id,
        salesforce_account_name=salesforce_account_name,
        snowflake_account_id=snowflake_account_id,
        deployment=deployment,
        duration_ms=duration_ms,
        context=context,
    )


class TelemetryEvents:
    APP_LAUNCH = "APP_LAUNCH"
    RUN_ANALYSIS = "RUN_ANALYSIS"
    RUN_COMPARISON = "RUN_COMPARISON"
    RUN_BATCH_ANALYSIS = "RUN_BATCH_ANALYSIS"
    AI_SUMMARY_GENERATED = "AI_SUMMARY_GENERATED"
    AI_NEXT_STEPS_GENERATED = "AI_NEXT_STEPS_GENERATED"
    AI_EMAIL_GENERATED = "AI_EMAIL_GENERATED"
    AI_METRICS_EXPLAINED = "AI_METRICS_EXPLAINED"
    PLAN_CACHE_LOOKUP = "PLAN_CACHE_LOOKUP"
    METADATA_LOOKUP = "METADATA_LOOKUP"
    EXPORT_REPORT = "EXPORT_REPORT"
    EXPORT_EMAIL = "EXPORT_EMAIL"
    VIEW_FIELD_MANUAL = "VIEW_FIELD_MANUAL"
    ERROR_ANALYSIS = "ERROR_ANALYSIS"
    ERROR_AI = "ERROR_AI"
    ERROR_LOOKUP = "ERROR_LOOKUP"
