from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
from snowflake.snowpark import Session


def create_snowhouse_session(connection_name: str = "snowhouse") -> Session:
    """
    Create a Snowpark session using a named Snowflake CLI connection.
    """
    return Session.builder.configs({"connection_name": connection_name}).create()


def resolve_deployment_for_uuid(session: Session, uuid: str) -> str:
    deployment, error = get_deployment_for_uuid(session=session, query_uuid=uuid)
    if not deployment:
        raise ValueError(error or "Unable to resolve deployment for UUID")
    return deployment


def fetch_query_metadata(session: Session, uuid: str, deployment: Optional[str] = None) -> Dict[str, Any]:
    metadata, error = get_query_metadata(
        session=session,
        query_uuid=uuid,
        deployment_override=deployment,
    )
    if not metadata:
        raise ValueError(error or "No metadata returned for UUID")
    return metadata


def fetch_history_context(session: Session, meta: Dict[str, Any]) -> Dict[str, Any]:
    history_df, history_error = get_query_history_for_hash(session=session, metadata=meta, days=30)
    if history_error or history_df is None or getattr(history_df, "empty", False):
        return {}
    return analyze_query_history_context(metadata=meta, history_df=history_df)


def get_deployment_for_uuid(session: Session, query_uuid: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Fast-path: infer deployment for a UUID using tiered strategy.

    Lookup order (fastest to slowest):
    1. JOB_ETL_V ±3h (fast, but incomplete for HT/JPS jobs)
    2. USAGE_TRACKING_V_LAST_90 ±1 day (HT-aware, smaller than JPS)
    3. JOB_ETL_JPS_V ±3h (last resort, slower but complete)
    """
    if not query_uuid or len(query_uuid) < 8:
        return None, "Invalid UUID format (too short)"

    query_uuid = query_uuid.strip()

    query_job_etl_v = f"""
    WITH params AS (
        SELECT
            '{query_uuid}'::string AS uuid,
            TO_TIMESTAMP(TO_NUMBER(LEFT('{query_uuid}', 8), 'XXXXXXXX') * 60) AS uuid_ts
    )
    SELECT deployment
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_V j
    JOIN params p ON j.uuid = p.uuid
    WHERE j.created_on BETWEEN DATEADD(hour, -3, p.uuid_ts)
                           AND DATEADD(hour,  3, p.uuid_ts)
    QUALIFY ROW_NUMBER() OVER (ORDER BY j.created_on DESC) = 1
    """

    try:
        result = session.sql(query_job_etl_v).collect()
        if result and len(result) > 0 and result[0]["DEPLOYMENT"]:
            return result[0]["DEPLOYMENT"], None
    except Exception:
        pass

    query_usage = f"""
    WITH params AS (
        SELECT
            '{query_uuid}'::string AS uuid,
            TO_TIMESTAMP(TO_NUMBER(LEFT('{query_uuid}', 8), 'XXXXXXXX') * 60) AS uuid_ts
    )
    SELECT deployment
    FROM SNOWHOUSE_IMPORT.PROD.USAGE_TRACKING_V_LAST_90 ut
    JOIN params p ON ut.job_uuid = p.uuid
    WHERE ut.ds BETWEEN DATE(p.uuid_ts) - 1
                   AND DATE(p.uuid_ts) + 1
    QUALIFY ROW_NUMBER() OVER (ORDER BY ut.ds DESC) = 1
    """

    try:
        result = session.sql(query_usage).collect()
        if result and len(result) > 0 and result[0]["DEPLOYMENT"]:
            return result[0]["DEPLOYMENT"], None
    except Exception:
        pass

    query_jps = f"""
    WITH params AS (
        SELECT
            '{query_uuid}'::string AS uuid,
            TO_TIMESTAMP(TO_NUMBER(LEFT('{query_uuid}', 8), 'XXXXXXXX') * 60) AS uuid_ts
    )
    SELECT deployment
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_JPS_V j
    JOIN params p ON j.uuid = p.uuid
    WHERE j.created_on BETWEEN DATEADD(hour, -3, p.uuid_ts)
                           AND DATEADD(hour,  3, p.uuid_ts)
    QUALIFY ROW_NUMBER() OVER (ORDER BY j.created_on DESC) = 1
    """

    try:
        result = session.sql(query_jps).collect()
        if result and len(result) > 0 and result[0]["DEPLOYMENT"]:
            return result[0]["DEPLOYMENT"], None
    except Exception:
        pass

    return None, "UUID not found (checked JOB_ETL_V, USAGE_TRACKING, and JOB_ETL_JPS_V)"


def get_query_metadata(
    session: Session,
    query_uuid: str,
    deployment_override: Optional[str] = None,
    deep_search: bool = False,
):
    """
    Fetch query metadata from Snowhouse using Snowpark session.
    Uses JOB_ETL_JPS_V to include JPS-only HT/Unistore jobs.
    Implements adaptive time filtering for efficient UUID lookup.
    """
    return _get_query_metadata_uncached(
        session=session,
        query_uuid=query_uuid,
        deployment_override=deployment_override,
        deep_search=deep_search,
    )


def _get_query_metadata_uncached(
    session: Session,
    query_uuid: str,
    deployment_override: Optional[str] = None,
    deep_search: bool = False,
):
    """
    Internal function that actually fetches from Snowhouse (not cached).
    """
    if deployment_override and deployment_override.upper() != "PROD":
        deployment_upper = deployment_override.upper()
        base_schema = f"SNOWHOUSE_IMPORT.{deployment_upper}.JOB_ETL_JPS_V"
        deployment_filter = ""
    else:
        base_schema = "SNOWHOUSE_IMPORT.PROD.JOB_ETL_JPS_V"
        deployment_filter = ""

    last_error = None

    if deep_search:
        windows = [
            (0.25, 0.25),
            (1, 1),
            (7, 7),
            (30, 30),
        ]
    else:
        windows = [
            (0.25, 0.25),
            (1, 1),
        ]

    uuid_ts_expr = f"TO_TIMESTAMP(TO_NUMBER(LEFT('{query_uuid}', 8), 'XXXXXXXX') * 60)"

    for back_days, fwd_days in windows:
        query = f"""
        SELECT
          q.uuid AS QUERY_ID,
          q.description AS QUERY_TEXT,
          q.database_name AS DATABASE_NAME,
          q.schema_name AS SCHEMA_NAME,
          q.user_name AS USER_NAME,
          q.warehouse_name AS WAREHOUSE_NAME,
          q.client_send_time AS START_TIME,
          q.client_send_time AS CLIENT_SEND_TIME,
          q.created_on AS END_TIME,
          q.total_duration AS TOTAL_ELAPSED_TIME,
          q.stats:stats.compilationTime::NUMBER AS COMPILATION_TIME,
          q.stats:stats.executionTime::NUMBER AS EXECUTION_TIME,
          q.stats:stats.producedRows::NUMBER AS ROWS_PRODUCED,
          q.stats:stats.scanBytes::NUMBER AS BYTES_SCANNED,
          q.stats:stats.writtenBytes::NUMBER AS BYTES_WRITTEN,
          q.stats:stats.scanFiles::NUMBER AS SCAN_FILES,
          q.stats:stats.filteredFiles::NUMBER AS FILTERED_FILES,
          q.stats:stats.scanFiles::NUMBER AS PARTITIONS_SCANNED,
          q.stats:stats.filteredFiles::NUMBER AS PARTITIONS_TOTAL,
          q.stats:stats.bytes_spilled_to_local_storage::NUMBER AS SPILL_LOCAL_BYTES,
          q.stats:stats.bytes_spilled_to_remote_storage::NUMBER AS SPILL_REMOTE_BYTES,
          q.stats:stats.snowTramFDBIOBytes::NUMBER AS FDB_IO_BYTES,
          q.stats:stats.snowTramFDBIOBytes::NUMBER AS SNOWTRAM_FDB_IO_BYTES,
          q.stats:stats.snowTramFdbTotalThrottlingTime::NUMBER AS FDB_THROTTLING_MS,
          q.stats:stats.ioLocalReadBytes::NUMBER AS IO_LOCAL_READ_BYTES,
          q.stats:stats.ioRemoteReadBytes::NUMBER AS IO_REMOTE_READ_BYTES,
          q.stats:stats.percentageScannedCache::NUMBER AS PERCENTAGE_SCANNED_FROM_CACHE,
          q.stats:stats.queuedOverloadTime::NUMBER AS QUEUED_OVERLOAD_TIME,
          q.dur_txn_lock AS TRANSACTION_BLOCKED_TIME,
          q.access_kv_table AS ACCESS_KV_TABLE,
          {f"q.deployment AS DEPLOYMENT," if not deployment_override else f"'{deployment_override}' AS DEPLOYMENT,"}
          q.account_id AS ACCOUNT_ID,
          q.error_code AS ERROR_CODE,
          q.error_message AS ERROR_MESSAGE,
          q.session_id AS SESSION_ID,
          COALESCE(q.statement_properties::VARCHAR, 'UNKNOWN') AS QUERY_TYPE,
          'N/A' AS WAREHOUSE_SIZE,
          CASE
            WHEN q.error_code IS NOT NULL AND q.error_code != 0 THEN 'FAILED'
            ELSE 'SUCCESS'
          END AS EXECUTION_STATUS,
          q.total_duration AS TOTAL_DURATION,
          q.dur_receive_query AS DUR_RECEIVE_QUERY,
          q.dur_compiling AS DUR_COMPILING,
          q.dur_gs_executing AS DUR_GS_EXECUTING,
          q.dur_xp_executing AS DUR_XP_EXECUTING,
          q.dur_scheduling AS DUR_SCHEDULING,
          q.dur_file_set_initialization AS DUR_FILE_SET_INITIALIZATION,
          q.cachedplanid AS CACHEDPLANID,
          q.fault_handling_time AS FAULT_HANDLING_TIME,
          q.query_retry_time AS QUERY_RETRY_TIME,
          q.attempt_count AS ATTEMPT_COUNT,
          q.restarted_from_job_id AS RESTARTED_FROM_JOB_ID,
          q.query_parameterized_hash AS QUERY_PARAMETERIZED_HASH,
          q.request_id AS REQUEST_ID,
          q.created_on AS CREATED_ON
        FROM {base_schema} q
        WHERE q.uuid = '{query_uuid}'
          {deployment_filter}
          AND q.created_on BETWEEN
                DATEADD(day, -{back_days}, {uuid_ts_expr})
            AND DATEADD(day, {fwd_days}, {uuid_ts_expr})
        ORDER BY q.created_on DESC
        LIMIT 1
        """

        try:
            result = session.sql(query).collect()
            if result:
                row = result[0]
                metadata = row.asDict()

                query_id = metadata.get("QUERY_ID")
                if query_id:
                    try:
                        qh_result = session.sql(f"""
                            SELECT
                                CLIENT_APPLICATION_ID AS APPLICATION_NAME,
                                CLIENT_DRIVER_NAME AS CLIENT_DRIVER,
                                CLIENT_DRIVER_VERSION AS CLIENT_VERSION,
                                CLIENT_ENVIRONMENT AS CLIENT_ENV,
                                QUERY_TAG
                            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                            WHERE QUERY_ID = '{query_id}'
                            LIMIT 1
                        """).collect()

                        if qh_result:
                            qh_row = qh_result[0]
                            metadata["APPLICATION_NAME"] = qh_row["APPLICATION_NAME"]
                            metadata["CLIENT_DRIVER"] = qh_row["CLIENT_DRIVER"]
                            metadata["CLIENT_VERSION"] = qh_row["CLIENT_VERSION"]
                            metadata["CLIENT_ENV"] = qh_row["CLIENT_ENV"]
                            metadata["QUERY_TAG"] = qh_row["QUERY_TAG"]
                    except Exception:
                        pass

                return metadata, None
        except Exception as exc:
            last_error = str(exc)
            continue

    schema_info = f" (schema: {base_schema})"
    if deep_search:
        error_msg = (
            f"Query UUID not found in Snowhouse after checking {len(windows)} adaptive time window(s) "
            f"(±1d, ±7d, ±30d){schema_info}"
        )
        if last_error:
            error_msg += f"\nLast error: {last_error}"
        return None, error_msg

    error_msg = f"Query UUID not found in Snowhouse within ±1 day{schema_info}. Enable deep search to scan older data."
    if last_error:
        error_msg += f"\nLast error: {last_error}"
    return None, error_msg


def _get_query_history_uncached(
    session: Session,
    query_hash: str,
    account_id: str,
    deployment: str,
    days: int = 30,
):
    """
    Helper function for fetching query history.
    """
    try:
        if deployment and deployment.upper() != "PROD":
            schema = f"SNOWHOUSE_IMPORT.{deployment.upper()}.JOB_ETL_JPS_V"
        else:
            schema = "SNOWHOUSE_IMPORT.PROD.JOB_ETL_JPS_V"

        query = f"""
        WITH executions AS (
            SELECT
                DATE(created_on) AS execution_date,
                total_duration AS duration_ms
            FROM {schema}
            WHERE query_parameterized_hash = '{query_hash}'
              AND account_id = '{account_id}'
              AND created_on >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
              AND error_code IS NULL
        )
        SELECT
            execution_date,
            COUNT(*) AS execution_count,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50_latency,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_latency,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms) AS p99_latency
        FROM executions
        GROUP BY execution_date
        ORDER BY execution_date DESC
        """

        result = session.sql(query).to_pandas()

        if result.empty:
            return None, "No historical data found for this query hash"

        return result, None
    except Exception as exc:
        return None, f"Could not fetch query history: {str(exc)}"


def get_query_history_for_hash(session: Session, metadata: Dict[str, Any], days: int = 30):
    """
    Fetch historical execution data for the same query_parameterized_hash.
    """
    query_hash = metadata.get("QUERY_PARAMETERIZED_HASH")
    account_id = metadata.get("ACCOUNT_ID")
    deployment = metadata.get("DEPLOYMENT", "PROD")

    if not query_hash:
        return None, "QUERY_PARAMETERIZED_HASH not found in metadata"
    if not account_id:
        return None, "ACCOUNT_ID not found in metadata"

    return _get_query_history_uncached(
        session=session,
        query_hash=query_hash,
        account_id=account_id,
        deployment=deployment,
        days=days,
    )


def analyze_query_history_context(metadata: Dict[str, Any], history_df) -> Dict[str, Any]:
    """
    Analyze query history to provide context for AI diagnosis.
    """
    if history_df is None or history_df.empty:
        return {}

    current_latency = float(metadata.get("TOTAL_ELAPSED_TIME", 0) or 0)

    p50_historical = float(history_df["P50_LATENCY"].median())
    p95_historical = float(history_df["P95_LATENCY"].median())
    p99_historical = float(history_df["P99_LATENCY"].median())
    total_executions = int(history_df["EXECUTION_COUNT"].sum())
    avg_daily_executions = float(history_df["EXECUTION_COUNT"].mean())

    is_anomaly = current_latency > p95_historical * 1.5 if p95_historical > 0 else False
    anomaly_ratio = current_latency / p95_historical if p95_historical > 0 else 1.0

    execution_trend = _detect_execution_trend(history_df)
    load_correlation = _compute_load_latency_correlation(history_df)
    p50_trend = _detect_p50_trend_direction(history_df)

    HT_EXCELLENT_MS = 100
    HT_ACCEPTABLE_MS = 500

    if is_anomaly:
        diagnosis_framing = "ANOMALY"
    elif execution_trend == "RECENT_REGRESSION":
        diagnosis_framing = "RECENT_REGRESSION"
    elif p50_historical > HT_ACCEPTABLE_MS:
        diagnosis_framing = "ALWAYS_SLOW"
    elif p50_historical > HT_EXCELLENT_MS:
        diagnosis_framing = "NORMAL_BUT_IMPROVABLE"
    else:
        diagnosis_framing = "NORMAL"

    return {
        "current_latency": current_latency,
        "p50_historical": p50_historical,
        "p95_historical": p95_historical,
        "p99_historical": p99_historical,
        "total_executions": total_executions,
        "avg_daily_executions": avg_daily_executions,
        "execution_trend": execution_trend,
        "is_anomaly": is_anomaly,
        "anomaly_ratio": anomaly_ratio,
        "diagnosis_framing": diagnosis_framing,
        "load_correlation": load_correlation.get("interpretation", "UNKNOWN"),
        "load_correlation_value": load_correlation.get("correlation", 0.0),
        "load_correlation_description": load_correlation.get("description", ""),
        "p50_trend_direction": p50_trend.get("direction", "UNKNOWN"),
        "p50_trend_percent_change": p50_trend.get("percent_change", 0.0),
        "p50_trend_description": p50_trend.get("description", ""),
    }


def _detect_execution_trend(history_df, recent_days: int = 7) -> str:
    if len(history_df) < 5:
        return "INSUFFICIENT_DATA"

    recent = history_df.head(min(recent_days, len(history_df) // 2))
    baseline = history_df.tail(len(history_df) - len(recent))

    if baseline.empty:
        return "INSUFFICIENT_DATA"

    recent_p95 = recent["P95_LATENCY"].median()
    baseline_p95 = baseline["P95_LATENCY"].median()

    if baseline_p95 <= 0:
        return "INSUFFICIENT_DATA"

    ratio = recent_p95 / baseline_p95

    all_p95 = history_df["P95_LATENCY"]
    cv = all_p95.std() / all_p95.mean() if all_p95.mean() > 0 else 0

    if cv > 0.5:
        return "VOLATILE"
    if ratio > 1.5:
        return "RECENT_REGRESSION"
    if ratio < 0.7:
        return "RECENT_IMPROVEMENT"
    return "STABLE"


def _compute_load_latency_correlation(history_df) -> Dict[str, Any]:
    if history_df is None or len(history_df) < 3:
        return {
            "correlation": 0.0,
            "interpretation": "INSUFFICIENT_DATA",
            "description": "Not enough data points to determine correlation",
        }

    try:
        exec_counts = history_df["EXECUTION_COUNT"].values.astype(float)
        p50_latencies = history_df["P50_LATENCY"].values.astype(float)

        valid_mask = (
            (exec_counts > 0)
            & (p50_latencies > 0)
            & np.isfinite(exec_counts)
            & np.isfinite(p50_latencies)
        )
        exec_counts = exec_counts[valid_mask]
        p50_latencies = p50_latencies[valid_mask]

        if len(exec_counts) < 3:
            return {
                "correlation": 0.0,
                "interpretation": "INSUFFICIENT_DATA",
                "description": "Not enough valid data points",
            }

        correlation = float(np.corrcoef(exec_counts, p50_latencies)[0, 1])

        if np.isnan(correlation):
            return {
                "correlation": 0.0,
                "interpretation": "LOAD_INDEPENDENT",
                "description": "Latency appears constant regardless of load",
            }

        if correlation > 0.5:
            return {
                "correlation": correlation,
                "interpretation": "LOAD_CORRELATED",
                "description": (
                    f"Higher load correlates with higher latency (r={correlation:.2f}). "
                    "Suggests concurrency/throttling issues."
                ),
            }
        if correlation < -0.3:
            return {
                "correlation": correlation,
                "interpretation": "WARMUP_EFFECT",
                "description": (
                    f"Higher load correlates with LOWER latency (r={correlation:.2f}). "
                    'System performs better when "warmed up".'
                ),
            }

        return {
            "correlation": correlation,
            "interpretation": "LOAD_INDEPENDENT",
            "description": f"Latency is independent of load (r={correlation:.2f}).",
        }
    except Exception as exc:
        return {
            "correlation": 0.0,
            "interpretation": "ERROR",
            "description": f"Could not compute correlation: {str(exc)}",
        }


def _detect_p50_trend_direction(history_df) -> Dict[str, Any]:
    if history_df is None or len(history_df) < 3:
        return {
            "direction": "INSUFFICIENT_DATA",
            "percent_change": 0.0,
            "description": "Not enough data points to determine trend",
        }

    try:
        df_sorted = history_df.sort_values("EXECUTION_DATE", ascending=True)
        p50_values = df_sorted["P50_LATENCY"].values.astype(float)

        p50_values = p50_values[np.isfinite(p50_values) & (p50_values > 0)]
        if len(p50_values) < 3:
            return {
                "direction": "INSUFFICIENT_DATA",
                "percent_change": 0.0,
                "description": "Not enough valid data points",
            }

        x = np.arange(len(p50_values))
        slope, _ = np.polyfit(x, p50_values, 1)

        first_val = p50_values[0]
        last_val = p50_values[-1]
        percent_change = ((last_val - first_val) / first_val * 100) if first_val > 0 else 0

        cv = np.std(p50_values) / np.mean(p50_values) if np.mean(p50_values) > 0 else 0
        normalized_slope = slope / np.mean(p50_values) if np.mean(p50_values) > 0 else 0

        if cv > 0.5:
            return {
                "direction": "VOLATILE",
                "percent_change": percent_change,
                "description": f"P50 latency is highly variable (CV={cv:.0%}). No clear trend.",
            }
        if normalized_slope > 0.05 or percent_change > 20:
            return {
                "direction": "INCREASING",
                "percent_change": percent_change,
                "description": f"P50 latency is trending UP ({percent_change:+.0f}% over period).",
            }
        if normalized_slope < -0.05 or percent_change < -20:
            return {
                "direction": "DECREASING",
                "percent_change": percent_change,
                "description": f"P50 latency is trending DOWN ({percent_change:+.0f}% over period).",
            }

        return {
            "direction": "STABLE",
            "percent_change": percent_change,
            "description": f"P50 latency is stable ({percent_change:+.0f}% change).",
        }
    except Exception as exc:
        return {
            "direction": "ERROR",
            "percent_change": 0.0,
            "description": f"Could not compute trend: {str(exc)}",
        }

