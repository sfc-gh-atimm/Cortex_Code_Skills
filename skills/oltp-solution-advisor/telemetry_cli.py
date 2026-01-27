from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from snowflake.snowpark import Session

TELEMETRY_DATABASE = "AFE"
TELEMETRY_SCHEMA = "PUBLIC_APP_STATE"
TELEMETRY_TABLE = "APP_EVENTS"
APP_NAME = "OLTP Discovery Advisor (Skill)"
APP_VERSION = "1.0.0"


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


def track_discovery_assessment(
    session: Session,
    customer_name: str,
    use_case: Optional[str] = None,
    use_case_link: Optional[str] = None,
    recommendation: Optional[str] = None,
    alternative: Optional[str] = None,
    confidence: Optional[str] = None,
    template_completeness: Optional[str] = None,
    missing_fields: Optional[List[str]] = None,
    scores: Optional[Dict[str, int]] = None,
    duration_ms: Optional[int] = None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> bool:
    context = {
        "customer_name": customer_name,
        "use_case": use_case,
        "use_case_link": use_case_link,
        "recommendation": recommendation,
        "alternative": alternative,
        "confidence": confidence,
        "template_completeness": template_completeness,
        "missing_fields": missing_fields or [],
        "scores": scores or {},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if extra_context:
        context.update(extra_context)

    return log_event(
        session=session,
        action_type=TelemetryEvents.RUN_DISCOVERY_ASSESSMENT,
        salesforce_account_name=customer_name,
        duration_ms=duration_ms,
        context=context,
    )


def track_template_parse(
    session: Session,
    customer_name: str,
    template_path: str,
    fields_found: int = 0,
    fields_missing: int = 0,
    duration_ms: Optional[int] = None,
) -> bool:
    context = {
        "customer_name": customer_name,
        "template_path": template_path,
        "fields_found": fields_found,
        "fields_missing": fields_missing,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return log_event(
        session=session,
        action_type=TelemetryEvents.TEMPLATE_PARSED,
        salesforce_account_name=customer_name,
        duration_ms=duration_ms,
        context=context,
    )


def track_report_generated(
    session: Session,
    customer_name: str,
    recommendation: str,
    output_path: str,
    duration_ms: Optional[int] = None,
) -> bool:
    context = {
        "customer_name": customer_name,
        "recommendation": recommendation,
        "output_path": output_path,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return log_event(
        session=session,
        action_type=TelemetryEvents.REPORT_GENERATED,
        salesforce_account_name=customer_name,
        duration_ms=duration_ms,
        context=context,
    )


class TelemetryEvents:
    APP_LAUNCH = "APP_LAUNCH"
    RUN_DISCOVERY_ASSESSMENT = "RUN_DISCOVERY_ASSESSMENT"
    TEMPLATE_PARSED = "TEMPLATE_PARSED"
    REPORT_GENERATED = "REPORT_GENERATED"
    CLARIFYING_QUESTIONS_GENERATED = "CLARIFYING_QUESTIONS_GENERATED"
    ERROR_PARSE = "ERROR_PARSE"
    ERROR_ASSESSMENT = "ERROR_ASSESSMENT"
    ERROR_REPORT = "ERROR_REPORT"
