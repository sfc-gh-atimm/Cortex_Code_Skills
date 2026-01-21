"""
Snowhouse runtime checks for Hybrid Table efficiency
Based on Glean's recommendations (00_GLEAN_output_HT Analyzer.md)

These queries use SNOWHOUSE_IMPORT ETL views (compatible with SALES_ENGINEER role)
to analyze actual query execution metrics for Hybrid Tables.
"""

from typing import Optional, Dict, Any, List, Tuple
import pandas as pd

try:
    import snowflake.connector as sf
    import streamlit as st
except Exception:
    sf = None
    st = None

def _read_df(cur, sql: str, params: Tuple = ()):
    """Execute SQL and return results as DataFrame"""
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    return pd.DataFrame.from_records(rows, columns=cols)

def map_to_sfdc_account(cur, deployment: str, account_id: int, asof_ts: str) -> Optional[Dict[str, Any]]:
    """
    Resolve (deployment, account_id, date) to Salesforce Account (Id, Name).
    Tries multiple strategies in order of preference:
    1. SNOWSCIENCE.DIMENSIONS.DIM_ACCOUNTS_HISTORY (with date)
    2. SNOWSCIENCE.DIMENSIONS.DIM_ACCOUNTS_HISTORY (latest)
    3. Snowhouse mapping tables (if available)
    4. Direct account lookup by deployment/account
    
    Args:
        cur: Snowflake cursor
        deployment: Snowflake deployment name
        account_id: Snowflake account ID
        asof_ts: Timestamp as string (will be converted to date)
        
    Returns:
        Dict with SALESFORCE_ACCOUNT_ID and SALESFORCE_ACCOUNT_NAME or None
    """
    # Strategy 1: SNOWSCIENCE with specific date
    try:
        sql = """
        SELECT SALESFORCE_ACCOUNT_ID, SALESFORCE_ACCOUNT_NAME
        FROM SNOWSCIENCE.DIMENSIONS.DIM_ACCOUNTS_HISTORY
        WHERE SNOWFLAKE_DEPLOYMENT = ?
          AND SNOWFLAKE_ACCOUNT_ID = ?
          AND GENERAL_DATE = TO_DATE(?)
        QUALIFY ROW_NUMBER() OVER (ORDER BY GENERAL_DATE DESC) = 1
        """
        cur.execute(sql, (deployment, account_id, asof_ts))
        row = cur.fetchone()
        if row:
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))
    except Exception:
        pass
    
    # Strategy 2: SNOWSCIENCE without date (latest record)
    try:
        sql = """
        SELECT SALESFORCE_ACCOUNT_ID, SALESFORCE_ACCOUNT_NAME
        FROM SNOWSCIENCE.DIMENSIONS.DIM_ACCOUNTS_HISTORY
        WHERE SNOWFLAKE_DEPLOYMENT = ?
          AND SNOWFLAKE_ACCOUNT_ID = ?
        QUALIFY ROW_NUMBER() OVER (ORDER BY GENERAL_DATE DESC) = 1
        """
        cur.execute(sql, (deployment, account_id))
        row = cur.fetchone()
        if row:
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))
    except Exception:
        pass
    
    # Strategy 3: Snowhouse DEPLOYMENT_ACCOUNT_MAP (if available)
    try:
        sql = """
        SELECT SALESFORCE_ACCOUNT_ID, SALESFORCE_ACCOUNT_NAME
        FROM SNOWHOUSE_IMPORT.PROD.DEPLOYMENT_ACCOUNT_MAP
        WHERE DEPLOYMENT = ?
          AND ACCOUNT_ID = ?
        LIMIT 1
        """
        cur.execute(sql, (deployment, account_id))
        row = cur.fetchone()
        if row:
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))
    except Exception:
        pass
    
    # Strategy 4: Try alternative Snowhouse metadata sources
    try:
        sql = """
        SELECT DISTINCT
            a.SALESFORCE_ACCOUNT_ID,
            a.SALESFORCE_ACCOUNT_NAME
        FROM SNOWHOUSE_IMPORT.PROD.ACCOUNTS a
        WHERE a.DEPLOYMENT = ?
          AND a.ACCOUNT_ID = ?
        LIMIT 1
        """
        cur.execute(sql, (deployment, account_id))
        row = cur.fetchone()
        if row:
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))
    except Exception:
        pass
    
    # Strategy 5: Look in SSM (Snowflake Subscription Management) if available
    try:
        sql = """
        SELECT 
            SALESFORCE_ACCOUNT_ID,
            SALESFORCE_ACCOUNT_NAME
        FROM SNOWHOUSE_IMPORT.SSM.SNOWFLAKE_SUBSCRIPTION_HISTORY
        WHERE SNOWFLAKE_DEPLOYMENT = ?
          AND SNOWFLAKE_ACCOUNT_ID = ?
        QUALIFY ROW_NUMBER() OVER (ORDER BY UPDATED_AT DESC) = 1
        """
        cur.execute(sql, (deployment, account_id))
        row = cur.fetchone()
        if row:
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))
    except Exception:
        pass
    
    return None

@st.cache_data(ttl=86400, show_spinner=False) if st else lambda f: f  # 24 hour cache
def find_job_union_view(_cur, query_uuid: str) -> pd.DataFrame:
    """
    Discover deployment/account for a UUID across all deployments.
    Uses union view: SNOWHOUSE_IMPORT.prod.job_etl_v
    
    Glean ref: "Always start with SNOWHOUSE_IMPORT.prod.JOB_ETL_V to find 
    the deployment by UUID" (line 83-84)
    Note: _cur prefixed with underscore to exclude from cache key
    """
    sql = """
    SELECT
      deployment, account_id, uuid, job_id, created_on, end_time,
      warehouse_id, warehouse_name, user_name, error_code, error_message,
      dur_txn_lock, dur_queued_load, total_duration,
      access_kv_table
    FROM SNOWHOUSE_IMPORT.prod.job_etl_v
    WHERE uuid = ?
    ORDER BY created_on DESC
    LIMIT 1
    """
    return _read_df(_cur, sql, (query_uuid,))

def job_latest_row(cur, query_uuid: str) -> Optional[Dict[str, Any]]:
    """Get latest job row for UUID, returns dict or None"""
    df = find_job_union_view(cur, query_uuid)
    if df.empty:
        return None
    return df.iloc[0].to_dict()

@st.cache_data(ttl=86400, show_spinner=False) if st else lambda f: f  # 24 hour cache
def usage_index_selection(_cur, query_uuid: str) -> pd.DataFrame:
    """
    HYBRID_TABLE_INDEX_SELECTION telemetry - which index was chosen and why
    Note: _cur prefixed with underscore to exclude from cache key
    
    Glean ref: "Inspect HYBRID_TABLE_INDEX_SELECTION payload to see the 
    ranking/rules" (lines 19-27)
    """
    # Try last_90 first for speed
    sql90 = """
    SELECT deployment, account_id, feature, timestamp, payload
    FROM SNOWHOUSE_IMPORT.prod.usage_tracking_v_last_90
    WHERE job_uuid = ? AND feature = 'HYBRID_TABLE_INDEX_SELECTION'
    ORDER BY timestamp DESC
    """
    df = _read_df(_cur, sql90, (query_uuid,))
    
    if df.empty:
        # Fallback to full table
        sql = """
        SELECT deployment, account_id, feature, timestamp, payload
        FROM SNOWHOUSE_IMPORT.prod.usage_tracking_v
        WHERE job_uuid = ? AND feature = 'HYBRID_TABLE_INDEX_SELECTION'
        ORDER BY timestamp DESC
        LIMIT 100
        """
        df = _read_df(_cur, sql, (query_uuid,))
    
    return df

@st.cache_data(ttl=86400, show_spinner=False) if st else lambda f: f  # 24 hour cache
def usage_scan_perf(_cur, query_uuid: str) -> pd.DataFrame:
    """
    HYBRID_TABLE_SCAN_PERF_STATS - probe efficiency metrics
    Note: _cur prefixed with underscore to exclude from cache key
    Extracts kvNumProbesFDB/Blob counters
    
    Glean ref: "Pull per-probe stats from usage tracking to see base-table 
    (FDB) vs blob probes" (lines 4-14)
    """
    sql90 = """
    SELECT deployment, account_id, feature, timestamp, payload
    FROM SNOWHOUSE_IMPORT.prod.usage_tracking_v_last_90
    WHERE job_uuid = ? AND feature = 'HYBRID_TABLE_SCAN_PERF_STATS'
    ORDER BY timestamp DESC
    """
    df = _read_df(_cur, sql90, (query_uuid,))
    
    if df.empty:
        sql = """
        SELECT deployment, account_id, feature, timestamp, payload
        FROM SNOWHOUSE_IMPORT.prod.usage_tracking_v
        WHERE job_uuid = ? AND feature = 'HYBRID_TABLE_SCAN_PERF_STATS'
        ORDER BY timestamp DESC
        LIMIT 100
        """
        df = _read_df(_cur, sql, (query_uuid,))
    
    # Extract probe counters from JSON payload
    if not df.empty and 'payload' in df.columns:
        def extract_probe_stats(payload):
            """Extract kvNumProbesFDB and kvNumProbesBlob from payload"""
            try:
                import json
                if isinstance(payload, str):
                    payload = json.loads(payload)
                
                stats = payload.get('stats', [])
                if isinstance(stats, list) and len(stats) > 0:
                    # Find entry with hybridTableOperationType = 4 (scan)
                    for s in stats:
                        if s.get('hybridTableOperationType') == 4:
                            return {
                                'kvNumProbesFDB': s.get('kvNumProbesFDB'),
                                'kvNumProbesBlob': s.get('kvNumProbesBlob')
                            }
                return {'kvNumProbesFDB': None, 'kvNumProbesBlob': None}
            except Exception:
                return {'kvNumProbesFDB': None, 'kvNumProbesBlob': None}
        
        probe_stats = df['payload'].apply(extract_probe_stats)
        df['kvNumProbesFDB'] = probe_stats.apply(lambda x: x['kvNumProbesFDB'])
        df['kvNumProbesBlob'] = probe_stats.apply(lambda x: x['kvNumProbesBlob'])
    
    return df

@st.cache_data(ttl=86400, show_spinner=False) if st else lambda f: f  # 24 hour cache
def lock_wait_and_queue(_cur, deployment: str, query_uuid: str) -> Optional[Dict[str, Any]]:
    """
    Per-query lock wait (DUR_TXN_LOCK) and queueing (DUR_QUEUED_LOAD)
    Note: _cur prefixed with underscore to exclude from cache key
    
    Glean ref: "DUR_TXN_LOCK in JOB_ETL_V is the authoritative per-query 
    lock wait" (lines 38-45)
    """
    sql = f"""
    SELECT uuid, 
           ROUND(dur_txn_lock/1000, 2) AS lock_sec,
           ROUND(dur_queued_load/1000, 2) AS queued_sec,
           ROUND(total_duration/1000, 2) AS total_sec
    FROM SNOWHOUSE_IMPORT.{deployment}.job_etl_v
    WHERE uuid = ?
    QUALIFY ROW_NUMBER() OVER (ORDER BY created_on DESC) = 1
    """
    df = _read_df(_cur, sql, (query_uuid,))
    if df.empty:
        return None
    return df.iloc[0].to_dict()

@st.cache_data(ttl=86400, show_spinner=False) if st else lambda f: f  # 24 hour cache
def queueing_context(_cur, deployment: str, account_id: int, warehouse_id: int, 
                     start_iso: str, end_iso: str) -> pd.DataFrame:
    """
    Aggregate warehouse queueing over time window (hourly)
    
    Glean ref: "Check dur_queued_load to rule out warehouse pressure" (lines 47-55)
    Note: _cur prefixed with underscore to exclude from cache key
    """
    sql = f"""
    SELECT DATE_TRUNC(HOUR, created_on) AS hour,
           AVG(dur_queued_load) AS avg_q_ms,
           MAX(dur_queued_load) AS max_q_ms,
           COUNT(*) AS query_count
    FROM SNOWHOUSE_IMPORT.{deployment}.job_etl_v
    WHERE account_id = ?
      AND warehouse_id = ?
      AND created_on BETWEEN ? AND ?
    GROUP BY 1
    ORDER BY 1
    """
    return _read_df(_cur, sql, (account_id, warehouse_id, start_iso, end_iso))

@st.cache_data(ttl=86400, show_spinner=False) if st else lambda f: f  # 24 hour cache
def incidents_for_job(_cur, deployment: str, account_id: int, job_id: int) -> pd.DataFrame:
    """
    Incidents linked to the job (timeouts, index issues, etc.)
    Note: _cur prefixed with underscore to exclude from cache key
    
    Glean ref: "Join WA_INCIDENTS_ETL_V to catch HT-related incidents" (lines 73-74)
    """
    sql = f"""
    SELECT created_on, source_error_signature, internal_message, 
           stack_trace, xp_stack_trace
    FROM SNOWHOUSE_IMPORT.{deployment}.wa_incidents_etl_v
    WHERE account_id = ? AND job_id = ?
    ORDER BY created_on DESC
    """
    return _read_df(_cur, sql, (account_id, job_id))

@st.cache_data(ttl=86400, show_spinner=False) if st else lambda f: f  # 24 hour cache
def tables_touched(_cur, deployment: str, account_id: int, query_uuid: str, 
                   start_ts: str, end_ts: str) -> pd.DataFrame:
    """
    Tables accessed by the job + Hybrid Table classification
    
    Glean ref: "Combine with TABLE_ACCESS logs and TABLE_ETL_V" (lines 75-76)
    Uses is_key_value flag to identify Hybrid Tables
    Note: _cur prefixed with underscore to exclude from cache key
    """
    sql = f"""
    WITH acc AS (
      SELECT TRY_TO_NUMBER(o:objectId) AS table_id_local
      FROM SNOWHOUSE_IMPORT.{deployment}.table_access_logs_v a,
           LATERAL FLATTEN(input => a.objects_modified) o
      WHERE a.account_id = ?
        AND a.created_on BETWEEN ? AND ?
        AND a.job_uuid = ?
      UNION ALL
      SELECT TRY_TO_NUMBER(o:objectId)
      FROM SNOWHOUSE_IMPORT.{deployment}.table_access_logs_v a,
           LATERAL FLATTEN(input => a.target_select_tables) o
      WHERE a.account_id = ?
        AND a.created_on BETWEEN ? AND ?
        AND a.job_uuid = ?
    )
    SELECT d.name AS database_name,
           s.name AS schema_name,
           t.name AS table_name,
           t.id AS table_id_local,
           t.is_key_value AS is_hybrid
    FROM SNOWHOUSE_IMPORT.{deployment}.table_etl_v t
    JOIN SNOWHOUSE_IMPORT.{deployment}.schema_etl_v s 
      ON s.id = t.parent_id AND s.deleted_on IS NULL
    JOIN SNOWHOUSE_IMPORT.{deployment}.database_etl_v d 
      ON d.id = s.parent_id AND d.deleted_on IS NULL
    JOIN acc ON acc.table_id_local = t.id
    WHERE t.account_id = ?
      AND t.deleted_on IS NULL
    ORDER BY database_name, schema_name, table_name
    """
    return _read_df(_cur, sql, (account_id, start_ts, end_ts, query_uuid,
                               account_id, start_ts, end_ts, query_uuid,
                               account_id))

def plan_cache_analysis(cur, deployment: str, account_id: int, 
                        date_filter: str = "CURRENT_DATE") -> pd.DataFrame:
    """
    Plan-cache effectiveness via QUERY_PARAMETERIZED_HASH
    
    Glean ref: "Use QUERY_PARAMETERIZED_HASH to group runs" (lines 57-64)
    """
    sql = f"""
    SELECT query_parameterized_hash, 
           COUNT(*) AS runs, 
           AVG(dur_compiling) AS avg_compile_ms,
           MIN(dur_compiling) AS min_compile_ms,
           MAX(dur_compiling) AS max_compile_ms
    FROM SNOWHOUSE_IMPORT.{deployment}.job_etl_v
    WHERE account_id = ?
      AND created_on::DATE = {date_filter}
      AND query_parameterized_hash IS NOT NULL
    GROUP BY 1
    ORDER BY runs DESC
    LIMIT 50
    """
    return _read_df(cur, sql, (account_id,))

@st.cache_data(ttl=86400, show_spinner=False) if st else lambda f: f  # 24 hour cache
def parameterization_quality(_cur, days: int = 7) -> pd.DataFrame:
    """
    Plan-cache reuse quality across all deployments (union view).
    Note: _cur prefixed with underscore to exclude from cache key
    Shows parameterized hashes with high distinct SQL text counts and compile time.
    
    Use this to identify queries that should be better parameterized to reduce
    compilation churn and improve plan-cache hit rates.
    
    Glean ref: "Measure plan-cache reuse using JOB_ETL_V" (lines 101-136, 202-220)
    """
    sql = f"""
    SELECT
      deployment, account_id,
      query_parameterized_hash,
      COUNT(*)                              AS runs,
      COUNT(DISTINCT sql_text_hash)         AS distinct_sql_texts,
      ROUND(AVG(dur_compiling)/1000, 3)     AS avg_compile_sec,
      ROUND(AVG(total_duration)/1000, 3)    AS avg_total_sec
    FROM SNOWHOUSE_IMPORT.prod.job_etl_v
    WHERE created_on >= DATEADD(DAY, -{days}, CURRENT_TIMESTAMP())
      AND query_parameterized_hash IS NOT NULL
    GROUP BY 1, 2, 3
    HAVING runs >= 5
    ORDER BY distinct_sql_texts DESC, avg_compile_sec DESC
    LIMIT 200
    """
    return _read_df(_cur, sql)

