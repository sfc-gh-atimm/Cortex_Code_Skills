from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from snowflake.snowpark import Session

TELEMETRY_DATABASE = "AFE"
TELEMETRY_SCHEMA = "PUBLIC_APP_STATE"
TELEMETRY_TABLE = "APP_EVENTS"
APP_NAME = "OLTP Workload Advisor"
APP_VERSION = "2.0.0"


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
        ctx_json = json.dumps(context or {}, default=str)

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
    salesforce_account_name: Optional[str] = None,
) -> bool:
    return log_event(
        session=session,
        action_type=action_type,
        success=False,
        error_message=str(error),
        context=context,
        salesforce_account_name=salesforce_account_name,
    )


def track_analysis_loaded(
    session: Session,
    customer_name: str,
    account_id: Optional[str] = None,
    deployment: Optional[str] = None,
    analysis_days: Optional[int] = None,
    total_queries: Optional[int] = None,
    hybrid_candidates: Optional[int] = None,
    ia_candidates: Optional[int] = None,
    duration_ms: Optional[int] = None,
) -> bool:
    context = {
        "customer_name": customer_name,
        "analysis_days": analysis_days,
        "total_queries": total_queries,
        "hybrid_candidates_count": hybrid_candidates,
        "ia_candidates_count": ia_candidates,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return log_event(
        session=session,
        action_type=TelemetryEvents.ANALYSIS_LOADED,
        salesforce_account_name=customer_name,
        snowflake_account_id=account_id,
        deployment=deployment,
        duration_ms=duration_ms,
        context=context,
    )


def track_workload_analysis(
    session: Session,
    customer_name: str,
    account_id: Optional[str] = None,
    deployment: Optional[str] = None,
    analysis_days: Optional[int] = None,
    total_queries: Optional[int] = None,
    hybrid_candidates: Optional[int] = None,
    ia_candidates: Optional[int] = None,
    strong_ht_candidates: Optional[int] = None,
    strong_ia_candidates: Optional[int] = None,
    update_patterns: Optional[Dict[str, int]] = None,
    duration_ms: Optional[int] = None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> bool:
    context = {
        "customer_name": customer_name,
        "analysis_days": analysis_days,
        "total_queries": total_queries,
        "hybrid_candidates_count": hybrid_candidates,
        "ia_candidates_count": ia_candidates,
        "strong_ht_candidates": strong_ht_candidates,
        "strong_ia_candidates": strong_ia_candidates,
        "update_patterns": update_patterns or {},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if extra_context:
        context.update(extra_context)

    return log_event(
        session=session,
        action_type=TelemetryEvents.RUN_WORKLOAD_ANALYSIS,
        salesforce_account_name=customer_name,
        snowflake_account_id=account_id,
        deployment=deployment,
        duration_ms=duration_ms,
        context=context,
    )


def track_tab_view(
    session: Session,
    customer_name: str,
    tab_name: str,
    deployment: Optional[str] = None,
) -> bool:
    context = {
        "customer_name": customer_name,
        "tab_name": tab_name,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return log_event(
        session=session,
        action_type=TelemetryEvents.TAB_VIEWED,
        salesforce_account_name=customer_name,
        deployment=deployment,
        context=context,
    )


def track_export(
    session: Session,
    customer_name: str,
    export_type: str,
    output_path: str,
    deployment: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> bool:
    context = {
        "customer_name": customer_name,
        "export_type": export_type,
        "output_path": output_path,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return log_event(
        session=session,
        action_type=TelemetryEvents.EXPORT_GENERATED,
        salesforce_account_name=customer_name,
        deployment=deployment,
        duration_ms=duration_ms,
        context=context,
    )


class TelemetryEvents:
    APP_LAUNCH = "APP_LAUNCH"
    ANALYSIS_LOADED = "ANALYSIS_LOADED"
    RUN_WORKLOAD_ANALYSIS = "RUN_WORKLOAD_ANALYSIS"
    TAB_VIEWED = "TAB_VIEWED"
    EXPORT_GENERATED = "EXPORT_GENERATED"
    CANDIDATE_REVIEWED = "CANDIDATE_REVIEWED"
    ERROR_LOAD = "ERROR_LOAD"
    ERROR_ANALYSIS = "ERROR_ANALYSIS"
