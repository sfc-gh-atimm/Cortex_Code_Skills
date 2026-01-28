from __future__ import annotations

import json
import os
from typing import Any

from snowflake.snowpark import Session

TELEMETRY_DATABASE = "AFE"
TELEMETRY_SCHEMA = "PUBLIC_APP_STATE"
TELEMETRY_TABLE = "APP_EVENTS"


def _get_events_table() -> str:
    return f"{TELEMETRY_DATABASE}.{TELEMETRY_SCHEMA}.{TELEMETRY_TABLE}"


def _get_identity(session: Session) -> dict[str, str]:
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
    app_name: str,
    action_type: str,
    account: str | None = None,
    recommendation: str | None = None,
    context: dict[str, Any] | None = None,
    success: bool = True,
    error: str | None = None,
    app_version: str = "1.0.0",
) -> bool:
    """
    Log a telemetry event to Snowflake.

    Args:
        session: Snowpark session
        app_name: Skill/app identifier (e.g., "oltp-solution-advisor")
        action_type: Event type (e.g., "ASSESSMENT", "TEMPLATE_PARSE", "ERROR")
        account: Customer's Snowflake account being analyzed (not caller's account)
        recommendation: Final recommendation output (e.g., "HT", "PG", "IA", "STANDARD")
        context: Flexible dict for all analysis details, scores, input documents, etc.
        success: Whether the operation succeeded
        error: Error message if success=False
        app_version: Version string for the skill/app

    Returns:
        True if event was logged successfully, False otherwise

    Example:
        log_event(
            session,
            app_name="oltp-solution-advisor",
            action_type="ASSESSMENT",
            account="OX56889",
            recommendation="HT",
            context={
                "customer_name": "Vistra",
                "use_case": "Retail Product Comparison",
                "scores": {"ht": 85, "pg": 60, "ia": 45},
                "input_document": "<template content>",
            }
        )
    """
    try:
        ident = _get_identity(session)
        ctx = context.copy() if context else {}
        if request_id := os.environ.get("CORTEX_REQUEST_ID"):
            ctx["cortex_request_id"] = request_id
        ctx_json = json.dumps(ctx, default=str)

        if error and len(error) > 500:
            error = error[:497] + "..."

        insert_sql = f"""
            INSERT INTO {_get_events_table()} (
                APP, APP_NAME, APP_VERSION,
                USER_NAME, ROLE_NAME, SNOWFLAKE_ACCOUNT,
                SNOWFLAKE_ACCOUNT_ID,
                ACTION_TYPE, ACTION_CONTEXT,
                RECOMMENDATION,
                SUCCESS, ERROR_MESSAGE
            )
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, PARSE_JSON(?), ?, ?, ?
        """

        session.sql(
            insert_sql,
            params=[
                app_name,
                app_name,
                app_version,
                ident["user_name"],
                ident["role_name"],
                ident["account_name"],
                account,
                action_type,
                ctx_json,
                recommendation,
                success,
                error,
            ],
        ).collect()
        return True
    except Exception:
        return False


def log_error(
    session: Session,
    app_name: str,
    action_type: str,
    error: Exception | str,
    account: str | None = None,
    context: dict[str, Any] | None = None,
) -> bool:
    """Convenience wrapper for logging errors."""
    return log_event(
        session=session,
        app_name=app_name,
        action_type=action_type,
        account=account,
        context=context,
        success=False,
        error=str(error),
    )


class TelemetryEvents:
    """Event type constants for OLTP Solution Advisor."""
    APP_LAUNCH = "APP_LAUNCH"
    RUN_DISCOVERY_ASSESSMENT = "RUN_DISCOVERY_ASSESSMENT"
    TEMPLATE_PARSED = "TEMPLATE_PARSED"
    REPORT_GENERATED = "REPORT_GENERATED"
    CLARIFYING_QUESTIONS_GENERATED = "CLARIFYING_QUESTIONS_GENERATED"
    ERROR_PARSE = "ERROR_PARSE"
    ERROR_ASSESSMENT = "ERROR_ASSESSMENT"
    ERROR_REPORT = "ERROR_REPORT"


APP_NAME = "oltp-solution-advisor"


def track_template_parse(
    session: Session,
    customer_name: str,
    template_path: str,
    fields_found: int,
    fields_missing: int,
    duration_ms: int | None = None,
    account: str | None = None,
) -> bool:
    """Track template parsing event."""
    return log_event(
        session=session,
        app_name=APP_NAME,
        action_type=TelemetryEvents.TEMPLATE_PARSED,
        account=account,
        context={
            "customer_name": customer_name,
            "template_path": template_path,
            "fields_found": fields_found,
            "fields_missing": fields_missing,
            "duration_ms": duration_ms,
        },
    )


def track_discovery_assessment(
    session: Session,
    customer_name: str,
    use_case: str,
    recommendation: str,
    alternative: str | None = None,
    confidence: str = "Medium",
    template_completeness: str = "PARTIAL",
    missing_fields: list[str] | None = None,
    scores: dict[str, int] | None = None,
    duration_ms: int | None = None,
    account: str | None = None,
    use_case_link: str | None = None,
) -> bool:
    """Track full discovery assessment event."""
    return log_event(
        session=session,
        app_name=APP_NAME,
        action_type=TelemetryEvents.RUN_DISCOVERY_ASSESSMENT,
        account=account,
        recommendation=recommendation,
        context={
            "customer_name": customer_name,
            "use_case": use_case,
            "use_case_link": use_case_link,
            "alternative": alternative,
            "confidence": confidence,
            "template_completeness": template_completeness,
            "missing_fields": missing_fields or [],
            "scores": scores or {},
            "duration_ms": duration_ms,
        },
    )


def track_report_generated(
    session: Session,
    customer_name: str,
    recommendation: str,
    output_path: str,
    duration_ms: int | None = None,
    account: str | None = None,
) -> bool:
    """Track report generation event."""
    return log_event(
        session=session,
        app_name=APP_NAME,
        action_type=TelemetryEvents.REPORT_GENERATED,
        account=account,
        recommendation=recommendation,
        context={
            "customer_name": customer_name,
            "output_path": output_path,
            "duration_ms": duration_ms,
        },
    )
