"""
Stored Procedure Analysis Rules

Detects and classifies slow stored procedure calls, particularly data ingestion
procedures that orchestrate COPY, MERGE, and DML operations.

Based on analysis from glean.md for proc_ingestRCADataFromS3_v8 patterns.
"""

from typing import Dict, List, Any, Optional, Tuple
import re


def human_bytes(n: float) -> str:
    """Convert bytes to human-readable format"""
    if not n or n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    import math
    i = min(int(math.floor(math.log(n, 1024))), len(units) - 1)
    return f"{n / (1024 ** i):.2f} {units[i]}"


def is_stored_proc_call(query_text: str) -> Optional[str]:
    """
    Check if query is a stored procedure call and return the procedure name.
    
    Returns:
        Procedure name if it's a CALL statement, None otherwise
    """
    if not query_text:
        return None
    
    query_lower = query_text.lower().strip()
    
    # Match: CALL schema.proc_name(...)
    call_pattern = r'call\s+([a-z0-9_\.]+)\s*\('
    match = re.search(call_pattern, query_lower)
    
    if match:
        return match.group(1)
    
    return None


def classify_child_bottleneck(
    child_rows: List[Dict[str, Any]], 
    child_stats: Dict[str, Dict[str, Any]],
    total_parent_sec: float
) -> Tuple[List[str], Dict[str, float]]:
    """
    Classify bottleneck types based on child query patterns.
    
    Args:
        child_rows: List of child query metadata (uuid, description, total_sec, etc.)
        child_stats: Dict mapping uuid to HT stats (fdb_throttle_ms, spill_bytes, etc.)
        total_parent_sec: Total duration of parent stored proc call
    
    Returns:
        Tuple of (classification_labels, breakdown_metrics)
    """
    labels = []
    breakdown = {
        'copy_sec': 0.0,
        'ht_dml_sec': 0.0,
        'other_dml_sec': 0.0,
        'queued_sec': 0.0,
        'other_sec': 0.0,
        'max_throttle_ratio': 0.0,
        'max_spill_bytes': 0.0
    }
    
    if not child_rows:
        return labels, breakdown
    
    # Analyze each child query
    for row in child_rows:
        desc = (row.get('description') or row.get('DESCRIPTION') or '').lower()
        total_sec = float(row.get('total_sec') or row.get('TOTAL_SEC') or 0)
        access_kv = row.get('access_kv_table') or row.get('ACCESS_KV_TABLE')
        queued_ms = float(row.get('dur_queued_load') or row.get('DUR_QUEUED_LOAD') or 0)
        
        # Classify by query type
        if 'copy into' in desc or 'copy from' in desc:
            breakdown['copy_sec'] += total_sec
        elif access_kv and any(k in desc for k in ['merge', 'update', 'delete', 'insert']):
            breakdown['ht_dml_sec'] += total_sec
        elif any(k in desc for k in ['merge', 'update', 'delete', 'insert']):
            breakdown['other_dml_sec'] += total_sec
        else:
            breakdown['other_sec'] += total_sec
        
        breakdown['queued_sec'] += (queued_ms / 1000.0)
    
    # Analyze HT-specific signals from child_stats
    for uuid, stats in child_stats.items():
        total_sec = float(stats.get('total_sec', 0))
        if total_sec <= 0:
            continue
        
        fdb_throttle_ms = float(stats.get('fdb_throttle_ms', 0))
        spill_remote = float(stats.get('spill_remote_bytes', 0))
        spill_local = float(stats.get('spill_local_bytes', 0))
        
        throttle_ratio = fdb_throttle_ms / (total_sec * 1000.0) if total_sec > 0 else 0
        breakdown['max_throttle_ratio'] = max(breakdown['max_throttle_ratio'], throttle_ratio)
        breakdown['max_spill_bytes'] = max(breakdown['max_spill_bytes'], spill_remote, spill_local)
    
    # Generate classification labels (order matters - most specific first)
    if breakdown['copy_sec'] >= 0.6 * total_parent_sec:
        labels.append("COPY bottleneck → combine files into 100-250MB chunks; ensure same-region stage; batch COPY operations")
    
    if breakdown['ht_dml_sec'] >= 0.6 * total_parent_sec:
        labels.append("HT DML bottleneck → prune unnecessary secondary indexes; align index keys to predicates; batch commits; use bulk-load on empty tables")
    
    if breakdown['queued_sec'] >= 0.1 * total_parent_sec:
        labels.append("Warehouse queuing → upsize warehouse; enable multi-cluster; schedule off-peak")
    
    if breakdown['max_throttle_ratio'] >= 0.30:
        labels.append("HT throttling ≥30% → pause concurrent HT churn; improve index coverage; project only needed columns")
    elif breakdown['max_throttle_ratio'] >= 0.15:
        labels.append("HT throttling ≥15% → reduce concurrent writes; verify index alignment")
    
    if breakdown['max_spill_bytes'] > 0:
        if breakdown['max_spill_bytes'] >= 1024**3:  # 1 GB
            labels.append(f"Remote/Local spill ({human_bytes(breakdown['max_spill_bytes'])}) → reduce intermediates; upsize warehouse; add LIMIT/Top-K")
        elif breakdown['max_spill_bytes'] >= 128 * 1024**2:  # 128 MB
            labels.append(f"Local spill ({human_bytes(breakdown['max_spill_bytes'])}) → consider upsizing or reducing intermediate volume")
    
    return labels, breakdown


def analyze_stored_proc_performance(
    metadata: Dict[str, Any],
    child_queries: Optional[List[Dict[str, Any]]] = None,
    child_stats: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Analyze stored procedure performance and classify bottlenecks.
    
    Args:
        metadata: Query metadata (QUERY_TEXT, TOTAL_ELAPSED_TIME, etc.)
        child_queries: Optional list of child queries from same request_id
        child_stats: Optional dict of HT stats for child UUIDs
    
    Returns:
        List of findings with severity, message, suggestions, and breakdown
    """
    findings = []
    
    query_text = metadata.get('QUERY_TEXT', '')
    total_ms = metadata.get('TOTAL_ELAPSED_TIME', 0) or metadata.get('DURATION_MS', 0)
    total_sec = total_ms / 1000.0 if total_ms else 0
    
    # Check if this is a stored procedure call
    proc_name = is_stored_proc_call(query_text)
    if not proc_name:
        return findings
    
    # ALWAYS flag stored procedures with at least a warning
    # (even if execution time is reasonable)
    if total_sec < 60:  # Less than 1 minute - still critical for HT architecture
        findings.append({
            "rule": "STORED_PROCEDURE_DETECTED",
            "check": "Stored Procedure Architecture",  # Display name for UI
            "category": "Architecture",
            "severity": "HIGH",
            "message": f"Stored procedure call detected: {proc_name}",
            "suggestion": "Refactor to set-based SQL for better HT performance. Replace row-by-row loops with bulk operations (staging + MERGE/INSERT). Align indexes to equality predicates and batch commits.",
            "context": f"Execution time: {total_sec:.1f}s (acceptable, but stored procedures have critical architectural concerns for Hybrid Tables)",
            "remediation": """
**Why Stored Procedures Are Problematic for Hybrid Tables:**

• **Row-by-row processing:** Stored procedures often encourage row-by-row or file-by-file loops, which defeat set-based execution and amplify Hybrid Table probe and index maintenance costs.

• **Obscured telemetry:** They obscure query plans and telemetry (fewer direct UUIDs/REQUEST_IDs), making HT bottlenecks (throttling, lock waits, spill) harder to diagnose and optimize.

• **Increased lock contention:** Long, monolithic transactions inside procedures increase lock contention and HT write-amplification (every secondary index is updated for each DML).

• **Missed bulk optimizations:** Procedural orchestration tends to run serial COPY/DML instead of bulk loads and batched MERGE/INSERT, missing HT bulk-load paths and efficient commit patterns.

• **Anti-pattern enabler:** They make it easy to create small-file COPY anti-patterns and non-covering index probes, both of which drastically slow HT workloads.

**Recommended Approach:**
Refactor to set-based SQL (staging + single COPY/MERGE per batch), align indexes to equality predicates, and batch commits. This typically outperforms stored-proc patterns on Hybrid Tables by 10-100x.
"""
        })
        return findings
    
    # Determine severity based on duration for longer-running procedures
    severity = None
    if total_sec >= 3600:  # 1 hour
        severity = "CRITICAL"
    elif total_sec >= 1800:  # 30 minutes
        severity = "HIGH"
    elif total_sec >= 600:  # 10 minutes
        severity = "MEDIUM"
    elif total_sec >= 60:  # 1 minute+
        severity = "MEDIUM"
    
    # Classify bottleneck if we have child query data
    labels = []
    breakdown = {}
    
    if child_queries:
        labels, breakdown = classify_child_bottleneck(
            child_queries, 
            child_stats or {}, 
            total_sec
        )
    
    # Build finding
    suggestion = " | ".join(labels) if labels else (
        "Investigate child queries via request_id to identify bottleneck "
        "(COPY vs DML vs queuing). See 'Stored Procedure Analysis' tab for details."
    )
    
    # Add architectural recommendation
    if labels:
        suggestion += " | Consider refactoring to set-based SQL with staging + bulk MERGE/INSERT instead of procedural loops."
    else:
        suggestion = "Refactor to set-based SQL (staging + MERGE/INSERT) instead of procedural logic. This eliminates row-by-row overhead and improves HT performance by 10-100x."
    
    context = f"Stored procedure: {proc_name}"
    if breakdown:
        context += f"\nCOPY: {breakdown['copy_sec']:.1f}s, HT DML: {breakdown['ht_dml_sec']:.1f}s, "
        context += f"Other DML: {breakdown['other_dml_sec']:.1f}s, Queued: {breakdown['queued_sec']:.1f}s"
    
    findings.append({
        "rule": "SLOW_STORED_PROC",
        "check": "Stored Procedure Performance",  # Display name for UI
        "category": "Performance",
        "severity": severity,
        "message": f"Stored procedure ran for {total_sec:.0f}s ({total_sec/60:.1f} minutes)",
        "suggestion": suggestion,
        "context": context,
        "breakdown": breakdown,
        "proc_name": proc_name,
        "remediation": """
**Why Stored Procedures Are Problematic for Hybrid Tables:**

• **Row-by-row processing:** Stored procedures often encourage row-by-row or file-by-file loops, which defeat set-based execution and amplify Hybrid Table probe and index maintenance costs.

• **Obscured telemetry:** They obscure query plans and telemetry (fewer direct UUIDs/REQUEST_IDs), making HT bottlenecks (throttling, lock waits, spill) harder to diagnose and optimize.

• **Increased lock contention:** Long, monolithic transactions inside procedures increase lock contention and HT write-amplification (every secondary index is updated for each DML).

• **Missed bulk optimizations:** Procedural orchestration tends to run serial COPY/DML instead of bulk loads and batched MERGE/INSERT, missing HT bulk-load paths and efficient commit patterns.

• **Anti-pattern enabler:** They make it easy to create small-file COPY anti-patterns and non-covering index probes, both of which drastically slow HT workloads.

**Recommended Approach:**
Refactor to set-based SQL (staging + single COPY/MERGE per batch), align indexes to equality predicates, and batch commits. This typically outperforms stored-proc patterns on Hybrid Tables by 10-100x.
"""
    })
    
    return findings


def fetch_child_queries(conn, request_id: str, limit: int = 100, 
                        parent_metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Fetch child queries for a given request_id from Snowhouse.
    Falls back to SESSION_ID + time window if REQUEST_ID is not available.
    
    Args:
        conn: Snowflake connection
        request_id: The request_id of the parent stored proc call
        limit: Maximum number of child queries to fetch
        parent_metadata: Parent query metadata for SESSION_ID fallback
    
    Returns:
        List of child query metadata
    """
    # Try REQUEST_ID first (preferred method)
    if request_id:
        query = f"""
        SELECT
            UUID,
            DESCRIPTION,
            ROUND(TO_NUMBER(TOTAL_DURATION) / 1000, 2) AS TOTAL_SEC,
            ACCESS_KV_TABLE,
            ERROR_CODE,
            DUR_QUEUED_LOAD,
            CREATED_ON,
            END_TIME
        -- IMPORTANT: Use JOB_ETL_JPS_V so we include JPS-only HT/Unistore jobs
        FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_JPS_V
        WHERE REQUEST_ID = ?
          AND (IS_INTERNAL IS NULL OR IS_INTERNAL = FALSE)
        ORDER BY TOTAL_DURATION DESC
        LIMIT {limit}
        """
        
        try:
            cur = conn.cursor()
            cur.execute(query, (request_id,))
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
            
            children = [dict(zip(cols, row)) for row in rows]
            if children:
                return children
        except Exception as e:
            print(f"Warning: Could not fetch child queries by REQUEST_ID: {e}")
    
    # FALLBACK: Use SESSION_ID + time window correlation
    if parent_metadata:
        session_id = parent_metadata.get('SESSION_ID')
        parent_uuid = parent_metadata.get('QUERY_ID') or parent_metadata.get('UUID')
        created_on = parent_metadata.get('START_TIME') or parent_metadata.get('CREATED_ON')
        end_time = parent_metadata.get('END_TIME')
        user_name = parent_metadata.get('USER_NAME')
        warehouse_name = parent_metadata.get('WAREHOUSE_NAME')
        
        if session_id and created_on and end_time and parent_uuid:
            # Build query with optional filters
            optional_filters = []
            params = [session_id, parent_uuid]
            
            if user_name:
                optional_filters.append("AND J.USER_NAME = ?")
                params.append(user_name)
            
            if warehouse_name:
                optional_filters.append("AND J.WAREHOUSE_NAME = ?")
                params.append(warehouse_name)
            
            optional_filter_clause = " ".join(optional_filters)
            
            query = f"""
            SELECT
                J.UUID,
                J.DESCRIPTION,
                ROUND(TO_NUMBER(J.TOTAL_DURATION) / 1000, 2) AS TOTAL_SEC,
                J.ACCESS_KV_TABLE,
                J.ERROR_CODE,
                J.DUR_QUEUED_LOAD,
                J.CREATED_ON,
                J.END_TIME
            -- IMPORTANT: Use JOB_ETL_JPS_V so we include JPS-only HT/Unistore jobs
            FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_JPS_V J
            WHERE J.SESSION_ID = ?
              AND J.UUID <> ?
              AND J.CREATED_ON >= DATEADD(SECOND, -2, TO_TIMESTAMP('{created_on}'))
              AND J.END_TIME <= DATEADD(SECOND, 2, TO_TIMESTAMP('{end_time}'))
              AND (J.IS_INTERNAL IS NULL OR J.IS_INTERNAL = FALSE)
              {optional_filter_clause}
            ORDER BY TO_NUMBER(J.TOTAL_DURATION) DESC
            LIMIT {limit}
            """
            
            try:
                cur = conn.cursor()
                cur.execute(query, params)
                cols = [c[0] for c in cur.description]
                rows = cur.fetchall()
                
                return [dict(zip(cols, row)) for row in rows]
            except Exception as e:
                print(f"Warning: Could not fetch child queries by SESSION_ID fallback: {e}")
    
    return []


def fetch_child_ht_stats(conn, uuids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch HT-specific stats for a list of UUIDs.
    
    Args:
        conn: Snowflake connection
        uuids: List of UUIDs to fetch stats for
    
    Returns:
        Dict mapping UUID to HT stats
    """
    if not uuids:
        return {}
    
    # Limit to top 20 UUIDs to avoid huge queries
    uuids = uuids[:20]
    
    placeholders = ','.join(['?' for _ in uuids])
    query = f"""
    SELECT
        UUID,
        ROUND(TO_NUMBER(TOTAL_DURATION) / 1000, 2) AS TOTAL_SEC,
        DUR_TXN_LOCK AS LOCK_MS,
        stats:stats.snowTramFDBIOBytes::NUMBER AS FDB_IO_BYTES,
        stats:stats.snowTramFdbTotalThrottlingTime::NUMBER AS FDB_THROTTLE_MS,
        stats:stats.ioLocalTempWriteBytes::NUMBER AS SPILL_LOCAL_BYTES,
        stats:stats.ioRemoteTempWriteBytes::NUMBER AS SPILL_REMOTE_BYTES
    -- IMPORTANT: Use JOB_ETL_JPS_V so we include JPS-only HT/Unistore jobs
    FROM SNOWHOUSE_IMPORT.PROD.JOB_ETL_JPS_V
    WHERE UUID IN ({placeholders})
    """
    
    try:
        cur = conn.cursor()
        cur.execute(query, uuids)
        cols = [c[0].lower() for c in cur.description]
        rows = cur.fetchall()
        
        result = {}
        for row in rows:
            row_dict = dict(zip(cols, row))
            uuid = row_dict.pop('uuid')
            result[uuid] = row_dict
        
        return result
    except Exception as e:
        print(f"Warning: Could not fetch HT stats: {e}")
        return {}

