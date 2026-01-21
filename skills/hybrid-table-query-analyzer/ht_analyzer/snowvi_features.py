"""
SnowVI Feature Extraction & Root Cause Classification

This module provides:
1. extract_snowvi_features() - Build a compact feature vector from SnowVI JSON
2. classify_run_pair() - Pre-classify root cause for 2-run comparison
3. classify_batch_queries() - Pre-classify root causes for batch analysis

The key insight (from GLEAN feedback): Classification should happen in CODE
(deterministic), not in AI prompts (non-deterministic). The AI then EXPLAINS
the pre-classified cause, ensuring narrative consistency with UI metrics.
"""

from typing import Any, Dict, List, Optional, Tuple


def safe_num(x: Any) -> float:
    """Safely convert a value to float, returning 0.0 on failure."""
    try:
        if x is None:
            return 0.0
        return float(x)
    except (ValueError, TypeError):
        return 0.0


def safe_dict_get(obj: Any, key: str, default: Any = None) -> Any:
    """Safely get from dict-like object, handling non-dict types."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


# =============================================================================
# HYBRID TABLE ACCESS PATH EXTRACTION (GLEAN 450+ Recommendations)
# =============================================================================

def extract_ht_access_paths_from_snowvi(snowvi_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Extract per-table Hybrid access paths from SnowVI JSON.
    
    Primary: Parses usageTrackingRecord to find accessContextMap and scanModeMap.
    Fallback: If usageTrackingRecord isn't available, extracts table names from SQL text
              and marks them as Hybrid Tables (access pattern unknown).
    
    Access modes help understand query behavior:
    - ADAPTIVE_PROBE: Row-by-row adaptive probe into FDB (many small lookups)
    - FDB_PROBE: Probe-style access through hybrid indexes
    - FDB_SCAN: Full scan through FDB storage
    - BLOB_SCAN: Scan through blob/object storage (more analytic-style)
    
    Args:
        snowvi_json: Full SnowVI JSON export
        
    Returns:
        Dict mapping table alias/name to access path info:
        { "TABLE_ALIAS": {"storageMode": "FDB", "accessMode": "SCAN", "scanMode": "ADAPTIVE_PROBE", ...} }
    """
    access_paths: Dict[str, Dict[str, Any]] = {}
    
    try:
        # Navigate to usageTrackingRecord
        query_data = safe_dict_get(snowvi_json, "queryData", {})
        data = safe_dict_get(query_data, "data", {})
        global_info = safe_dict_get(data, "globalInfo", {})
        query_overview = safe_dict_get(global_info, "queryOverview", {})
        records = safe_dict_get(query_overview, "usageTrackingRecord") or []
        
        for rec in records:
            if not isinstance(rec, dict):
                continue
                
            payload = safe_dict_get(rec, "payload", {})
            tables_ledger = safe_dict_get(payload, "tablesLedger", {})
            
            # accessContextMap: per-alias storage and access mode
            access_ctx = safe_dict_get(tables_ledger, "accessContextMap", {})
            
            # scanModeMap: per-alias scan mode (may also be at payload level)
            scan_mode_map = (
                safe_dict_get(tables_ledger, "scanModeMap") or 
                safe_dict_get(payload, "scanModeMap") or 
                {}
            )
            
            for alias, ctx in access_ctx.items():
                if not isinstance(ctx, dict):
                    continue
                    
                alias_upper = alias.upper()
                storage_mode = safe_dict_get(ctx, "storageMode")  # e.g., "FDB", "BLOB"
                access_mode = safe_dict_get(ctx, "accessMode")     # e.g., "SCAN", "PROBE"
                scan_mode = scan_mode_map.get(alias) if isinstance(scan_mode_map, dict) else None
                
                is_analytic = _is_analytic_access_pattern(storage_mode, access_mode, scan_mode)
                
                access_paths[alias_upper] = {
                    "storageMode": storage_mode,
                    "accessMode": access_mode,
                    "scanMode": scan_mode,
                    "is_analytic_pattern": is_analytic,
                    "recommendation": "Consider Standard (FDN) table" if is_analytic else "Hybrid Table appropriate",
                    "source": "usageTrackingRecord",
                }
                
    except Exception:
        pass
    
    # =========================================================================
    # FALLBACK: Extract table names from SQL text if no access paths found
    # This handles cases where usageTrackingRecord isn't in the export
    # =========================================================================
    if not access_paths:
        access_paths = _extract_tables_from_sql_fallback(snowvi_json)
    
    return access_paths


def _extract_tables_from_sql_fallback(snowvi_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Fallback: Extract table names from SQL text when usageTrackingRecord isn't available.
    
    Looks for tables that appear to be Hybrid Tables based on:
    1. Table names with "HT_" prefix (common naming convention)
    2. Tables with known HT-related keywords
    3. Any table referenced in FROM/JOIN clauses
    
    Returns partial access path info (source="sql_fallback") with unknown access modes.
    """
    import re
    
    access_paths: Dict[str, Dict[str, Any]] = {}
    
    try:
        query_data = safe_dict_get(snowvi_json, "queryData", {})
        data = safe_dict_get(query_data, "data", {})
        global_info = safe_dict_get(data, "globalInfo", {})
        query_overview = safe_dict_get(global_info, "queryOverview", {})
        
        sql_text = safe_dict_get(query_overview, "sqlText") or ""
        if not sql_text:
            return access_paths
        
        sql_upper = sql_text.upper()
        
        # Pattern to match table references: FROM table, JOIN table, etc.
        # Handles: schema.table, database.schema.table, "quoted".table
        table_pattern = r'(?:FROM|JOIN|INTO|UPDATE|MERGE\s+INTO)\s+(["\w]+(?:\.["\w]+)*)'
        matches = re.findall(table_pattern, sql_upper, re.IGNORECASE)
        
        seen_tables = set()
        for match in matches:
            # Clean up the table name (remove quotes, get last part as table name)
            table_parts = match.replace('"', '').split('.')
            table_name = table_parts[-1].upper()  # Get actual table name
            full_name = match.replace('"', '').upper()
            
            if table_name in seen_tables:
                continue
            seen_tables.add(table_name)
            
            # Check if this looks like a Hybrid Table
            is_likely_ht = (
                table_name.startswith("HT_") or
                "_HT" in table_name or
                "HYBRID" in table_name
            )
            
            # Only include tables that look like Hybrid Tables
            # (We don't want to show every table as "access path unknown")
            if is_likely_ht:
                access_paths[table_name] = {
                    "storageMode": "FDB (inferred)",
                    "accessMode": "Unknown",
                    "scanMode": "Unknown",
                    "is_analytic_pattern": None,  # Can't determine without detailed metrics
                    "recommendation": "Load detailed SnowVI export for access pattern analysis",
                    "source": "sql_fallback",
                    "full_table_ref": full_name,
                }
        
        # If no HT-prefixed tables found but we have KV metrics, 
        # include all tables as potential HTs
        if not access_paths:
            # Check if there's any evidence of HT activity
            has_ht_activity = _has_ht_activity_indicators(snowvi_json)
            
            if has_ht_activity and seen_tables:
                # Include all referenced tables since we detected HT activity
                for table_name in list(seen_tables)[:5]:  # Limit to 5 tables
                    access_paths[table_name] = {
                        "storageMode": "FDB (inferred from KV activity)",
                        "accessMode": "Unknown",
                        "scanMode": "Unknown",
                        "is_analytic_pattern": None,
                        "recommendation": "Hybrid Table activity detected but detailed access paths unavailable",
                        "source": "sql_fallback",
                    }
                    
    except Exception:
        pass
    
    return access_paths


def _has_ht_activity_indicators(snowvi_json: Dict[str, Any]) -> bool:
    """
    Check if there's any indication of Hybrid Table activity in the JSON.
    
    Looks for KV metrics, FDB stats, or HybridTable operator names.
    """
    try:
        query_data = safe_dict_get(snowvi_json, "queryData", {})
        data = safe_dict_get(query_data, "data", {})
        global_info = safe_dict_get(data, "globalInfo", {})
        query_overview = safe_dict_get(global_info, "queryOverview", {})
        
        # Check for KV/FDB metrics in various locations
        for key in ["kvNumScannedRows", "kvIndexScannedRows", "fdbTotalDurationMs", 
                    "snowTramFDBIOBytes", "profHybridTableProbe"]:
            if query_overview.get(key):
                return True
        
        # Check in stats_tree if present
        stats_tree = safe_dict_get(query_overview, "stats_tree", {})
        if stats_tree:
            stats_str = str(stats_tree)
            if any(ht_term in stats_str for ht_term in ["HybridTable", "kvNum", "fdb"]):
                return True
        
        # Check topNRsoNames for HybridTable operators
        rso_names = safe_dict_get(query_overview, "topNRsoNames") or []
        if any("Hybrid" in str(rso) for rso in rso_names):
            return True
            
    except Exception:
        pass
    
    return False


def _is_analytic_access_pattern(
    storage_mode: Optional[str], 
    access_mode: Optional[str], 
    scan_mode: Optional[str]
) -> bool:
    """
    Determine if the access pattern suggests analytic workload (better as standard table).
    
    Returns True if the pattern indicates large scans typical of analytical queries.
    """
    if not any([storage_mode, access_mode, scan_mode]):
        return False
    
    # BLOB storage is typically analytic (object store scans)
    if storage_mode and "BLOB" in str(storage_mode).upper():
        return True
    
    # Full scans are analytic
    if access_mode and str(access_mode).upper() == "SCAN":
        # FDB_SCAN or BLOB_SCAN patterns
        return True
    
    # Check scan mode for analytic patterns
    if scan_mode:
        scan_upper = str(scan_mode).upper()
        # These typically indicate analytical access
        if any(p in scan_upper for p in ["BLOB_SCAN", "FDB_SCAN", "FULL_SCAN"]):
            return True
    
    return False


# =============================================================================
# JOIN EXPLOSION DETECTION (GLEAN 450+ Recommendations)
# =============================================================================

def detect_join_explosions(
    snowvi_json: Dict[str, Any], 
    threshold_ratio: float = 10.0
) -> List[Dict[str, Any]]:
    """
    Detect join operators with high rows_out / rows_in ratios (join explosions).
    
    A join explosion is when the output rows >> input rows, indicating
    a many-to-many join or poor join selectivity. This causes:
    - High memory usage
    - Increased XP execution time
    - Potential OOM errors
    
    Args:
        snowvi_json: Full SnowVI JSON export
        threshold_ratio: Minimum rows_out/rows_in to flag as explosion (default 10x)
        
    Returns:
        List of dicts with: {operator_id, operator_name, rows_in, rows_out, ratio, is_explosion}
        Sorted by ratio descending.
    """
    explosions: List[Dict[str, Any]] = []
    seen_operators: set = set()
    
    try:
        # Navigate to stats_tree in workerDetail
        workers_data = safe_dict_get(snowvi_json, "workersData") or []
        if not workers_data:
            return []
        
        worker_data = safe_dict_get(workers_data[0], "data", {})
        worker_detail = safe_dict_get(worker_data, "workerDetail", {})
        stats_tree = safe_dict_get(worker_detail, "stats_tree", {})
        
        # Also check for RSO stats (alternative location)
        rso_stats = safe_dict_get(worker_data, "rsoStats") or []
        
        # Walk stats_tree looking for join operators
        def walk_stats_tree(node: Any, path: str = "") -> None:
            if not isinstance(node, dict):
                return
            
            # Check if this node has join-like stats
            op_name = (
                safe_dict_get(node, "name") or 
                safe_dict_get(node, "operator") or 
                safe_dict_get(node, "rsoName") or
                ""
            )
            op_id = safe_dict_get(node, "id") or path
            
            # Look for join operators (HashJoin, NestedLoop, Merge)
            if any(jt in str(op_name).lower() for jt in ["join", "hashjoin", "nestedloop", "mergejoin"]):
                rows_in = safe_num(
                    safe_dict_get(node, "inputRows") or 
                    safe_dict_get(node, "rows_in") or
                    safe_dict_get(node, "leftInputRows", 0) + safe_dict_get(node, "rightInputRows", 0) or
                    0
                )
                rows_out = safe_num(
                    safe_dict_get(node, "outputRows") or 
                    safe_dict_get(node, "rows_out") or
                    safe_dict_get(node, "rowsProduced") or
                    0
                )
                
                if rows_in > 0 and str(op_id) not in seen_operators:
                    ratio = rows_out / rows_in
                    seen_operators.add(str(op_id))
                    explosions.append({
                        "operator_id": op_id,
                        "operator_name": op_name,
                        "rows_in": int(rows_in),
                        "rows_out": int(rows_out),
                        "ratio": round(ratio, 2),
                        "is_explosion": ratio >= threshold_ratio,
                    })
            
            # Recurse into children
            for key, val in node.items():
                if isinstance(val, dict):
                    walk_stats_tree(val, f"{path}/{key}")
                elif isinstance(val, list):
                    for i, item in enumerate(val):
                        if isinstance(item, dict):
                            walk_stats_tree(item, f"{path}/{key}[{i}]")
        
        walk_stats_tree(stats_tree)
        
        # Also check RSO stats for HashJoinProbe
        for rso in rso_stats:
            if not isinstance(rso, dict):
                continue
            name = safe_dict_get(rso, "name") or ""
            rso_id = safe_dict_get(rso, "id")
            
            if any(jt in str(name).lower() for jt in ["join", "hashjoin"]):
                rows_in = safe_num(safe_dict_get(rso, "inputRows") or 0)
                rows_out = safe_num(safe_dict_get(rso, "outputRows") or 0)
                
                if rows_in > 0 and str(rso_id) not in seen_operators:
                    ratio = rows_out / rows_in
                    seen_operators.add(str(rso_id))
                    explosions.append({
                        "operator_id": rso_id,
                        "operator_name": name,
                        "rows_in": int(rows_in),
                        "rows_out": int(rows_out),
                        "ratio": round(ratio, 2),
                        "is_explosion": ratio >= threshold_ratio,
                    })
        
    except Exception:
        pass
    
    # Sort by ratio descending
    explosions.sort(key=lambda x: x["ratio"], reverse=True)
    return explosions


def has_join_explosion(snowvi_json: Dict[str, Any], threshold_ratio: float = 10.0) -> bool:
    """Quick check: does this query have any join explosions above the threshold?"""
    explosions = detect_join_explosions(snowvi_json, threshold_ratio)
    return any(e["is_explosion"] for e in explosions)


def get_join_explosion_summary(snowvi_json: Dict[str, Any], threshold_ratio: float = 10.0) -> Dict[str, Any]:
    """
    Get a summary of join explosion data for a query.
    
    Returns:
        Dict with: has_explosion, max_ratio, explosion_count, worst_operator
    """
    explosions = detect_join_explosions(snowvi_json, threshold_ratio)
    flagged = [e for e in explosions if e["is_explosion"]]
    
    return {
        "has_explosion": len(flagged) > 0,
        "max_ratio": max((e["ratio"] for e in explosions), default=0.0),
        "explosion_count": len(flagged),
        "worst_operator": flagged[0]["operator_name"] if flagged else None,
        "all_explosions": flagged[:5],  # Top 5 for display
    }


def extract_snowvi_features(snowvi_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a compact feature vector from a SnowVI all-data JSON export.
    
    Safe to use even when some fields are missing. This provides a consistent
    structure that can be used for:
    - UI display (metrics tables)
    - Classification heuristics
    - AI prompt context
    
    Args:
        snowvi_json: The full SnowVI JSON export
        
    Returns:
        Dict with standardized feature keys and numeric values
    """
    # Navigate to queryOverview (handle nested structure)
    query_data = safe_dict_get(snowvi_json, "queryData", {})
    data = safe_dict_get(query_data, "data", {})
    global_info = safe_dict_get(data, "globalInfo", {})
    qi = safe_dict_get(global_info, "queryOverview", {})
    
    # Stats can be in multiple locations
    stats = safe_dict_get(qi, "stats", {})
    if isinstance(stats, dict):
        stats_global = safe_dict_get(stats, "global", stats)
    else:
        stats_global = {}
    
    # Combine stats sources (some exports have flat stats, some have nested)
    def get_stat(key: str) -> float:
        """Try multiple stat locations."""
        val = safe_dict_get(stats_global, key)
        if val is None:
            val = safe_dict_get(stats, key)
        if val is None:
            val = safe_dict_get(qi, key)
        return safe_num(val)

    features: Dict[str, Any] = {}

    # =========================================================================
    # IDENTITY / HASHES - For detecting query changes
    # =========================================================================
    features["query_id"] = (
        safe_dict_get(snowvi_json, "queryId") or 
        safe_dict_get(qi, "id") or
        safe_dict_get(qi, "uuid")
    )
    features["sanitized_sql_hash"] = safe_dict_get(qi, "sanitizedSqlTextHash")
    features["sql_plan_hash"] = safe_dict_get(qi, "sqlPlanHash")
    features["parameterized_query_hash"] = safe_dict_get(qi, "parameterizedQueryHash")
    features["sql_text"] = safe_dict_get(qi, "sqlText", "")

    # =========================================================================
    # DURATIONS (ms) - Primary timing breakdown
    # =========================================================================
    features["total_ms"] = safe_num(safe_dict_get(qi, "totalDuration"))
    features["gs_exec_ms"] = safe_num(safe_dict_get(qi, "gsExecDuration"))
    features["gs_compile_ms"] = safe_num(safe_dict_get(qi, "gsCompileDuration"))
    features["xp_ms"] = safe_num(safe_dict_get(qi, "xpExecDuration"))
    
    # Compilation from stats (may differ from gs_compile)
    compile_ns = safe_num(safe_dict_get(qi, "plancacheCompilationDurationNs"))
    features["compile_ms_ns_source"] = compile_ns / 1_000_000 if compile_ns else 0.0
    features["compile_ms_stats"] = get_stat("compilationTime")

    # =========================================================================
    # RESULT SIZE - Helps classify OLTP vs analytic
    # =========================================================================
    features["rows_produced"] = get_stat("producedRows") or get_stat("returnedRows") or get_stat("numRowsInResult")
    features["bytes_scanned"] = get_stat("bytesScanned")

    # =========================================================================
    # HYBRID TABLE / KV METRICS - Critical for HT analysis
    # =========================================================================
    features["kv_rows_scanned"] = get_stat("kvNumScannedRows")
    features["kv_index_rows_scanned"] = get_stat("kvIndexScannedRows")
    features["kv_probes_blob"] = get_stat("kvNumProbesBlob")
    features["kv_probes_fdb"] = get_stat("kvNumProbesFDB")
    features["snowtram_kvs_txn"] = get_stat("snowTramKvsTransactionExecuted")
    features["kv_ranges_scanned"] = get_stat("kvNumRangesScannedForProbing")

    # =========================================================================
    # FDB TIMING - Storage layer performance
    # =========================================================================
    features["fdb_num_txn"] = get_stat("fdbNumTransactions")
    features["fdb_total_ms"] = get_stat("fdbTotalDurationMs")
    features["fdb_io_bytes"] = get_stat("snowTramFDBIOBytes") or get_stat("ioRemoteKvBlobReadBytes")

    # =========================================================================
    # XP PROFILING - Operator-level breakdown (when available)
    # =========================================================================
    features["prof_cpu"] = get_stat("profCpu")
    features["prof_idle"] = get_stat("profIdle")
    features["prof_hybrid_probe"] = get_stat("profHybridTableProbe")
    features["prof_hash_join"] = get_stat("profHjRso")
    features["prof_filter"] = get_stat("profFilterRso")
    features["prof_proj"] = get_stat("profProjRso")
    features["prof_fs_meta"] = get_stat("profFsMeta")
    features["prof_xp_msg"] = get_stat("profXpMsg")
    features["prof_mutex"] = get_stat("profMutex")

    # =========================================================================
    # WAREHOUSE / SCHEDULING
    # =========================================================================
    features["warehouse_name"] = safe_dict_get(qi, "warehouseName")
    features["warehouse_size"] = get_stat("warehouseSize") or safe_dict_get(qi, "warehouseSize")
    features["schedule_time_ms"] = get_stat("scheduleTime")
    features["server_count"] = get_stat("serverCount")

    # =========================================================================
    # PLAN CACHE
    # =========================================================================
    features["plan_cache_original_uuid"] = safe_dict_get(qi, "plancacheOriginalJobUuid")
    features["plan_is_cacheable"] = safe_dict_get(qi, "planIsCacheable")
    features["plan_cache_reused"] = bool(features["plan_cache_original_uuid"])

    # =========================================================================
    # HOT OPERATORS (topNRso)
    # =========================================================================
    top_rso_names = safe_dict_get(qi, "topNRsoNames", [])
    top_rso_times = safe_dict_get(qi, "topNRsoProfiledTimes", [])
    if isinstance(top_rso_names, list) and isinstance(top_rso_times, list):
        features["hot_rsos"] = [
            {"name": name, "time_ms": safe_num(time)}
            for name, time in zip(top_rso_names[:5], top_rso_times[:5])
        ]
    else:
        features["hot_rsos"] = []

    # =========================================================================
    # DERIVED METRICS - Calculated from raw values
    # =========================================================================
    total = features["total_ms"] or 1.0
    xp = features["xp_ms"] or 0.0
    gs_exec = features["gs_exec_ms"] or 0.0
    gs_compile = features["gs_compile_ms"] or 0.0
    
    features["xp_share"] = xp / total if total > 0 else 0.0
    features["gs_exec_share"] = gs_exec / total if total > 0 else 0.0
    features["gs_compile_share"] = gs_compile / total if total > 0 else 0.0
    
    # KV efficiency metrics
    total_probes = (features["kv_probes_blob"] or 0) + (features["kv_probes_fdb"] or 0)
    features["kv_rows_per_probe"] = (
        features["kv_rows_scanned"] / max(total_probes, 1.0)
    ) if total_probes > 0 else features["kv_rows_scanned"]
    
    # FDB share of XP time
    features["fdb_share_of_xp"] = (
        features["fdb_total_ms"] / max(xp, 1.0)
    ) if xp > 0 else 0.0

    # =========================================================================
    # WORKLOAD CLASSIFICATION FLAGS
    # =========================================================================
    # OLTP-like: low rows, fast, low KV scans
    features["is_oltp_like"] = (
        features["total_ms"] < 500 and 
        features["rows_produced"] < 1000 and
        features["kv_rows_scanned"] < 10000
    )
    
    # Analytic-like: high rows, long duration, large scans
    features["is_analytic_like"] = (
        features["total_ms"] > 5000 or
        features["rows_produced"] > 100000 or
        features["kv_rows_scanned"] > 1000000
    )
    
    # Bound variables detection (check SQL for ? or :param)
    sql = features.get("sql_text", "") or ""
    features["uses_bound_variables"] = (
        '?' in sql or 
        any(f':{p}' in sql.lower() for p in ['1', '2', '3', 'var', 'param', 'id', 'value'])
    )

    # =========================================================================
    # DATA COMPLETENESS FLAGS
    # =========================================================================
    features["_has_kv_metrics"] = features["kv_rows_scanned"] > 0 or features["snowtram_kvs_txn"] > 0
    features["_has_fdb_metrics"] = features["fdb_num_txn"] > 0 or features["fdb_total_ms"] > 0
    features["_has_xp_profiling"] = features["prof_cpu"] > 0 or features["prof_idle"] > 0
    features["_has_hot_rsos"] = len(features["hot_rsos"]) > 0

    # =========================================================================
    # JOIN EXPLOSION DETECTION (GLEAN 450+ Recommendations)
    # =========================================================================
    try:
        explosion_summary = get_join_explosion_summary(snowvi_json, threshold_ratio=10.0)
        features["has_join_explosion"] = explosion_summary["has_explosion"]
        features["max_join_ratio"] = explosion_summary["max_ratio"]
        features["join_explosion_count"] = explosion_summary["explosion_count"]
        features["worst_explosion_operator"] = explosion_summary["worst_operator"]
    except Exception:
        features["has_join_explosion"] = False
        features["max_join_ratio"] = 0.0
        features["join_explosion_count"] = 0
        features["worst_explosion_operator"] = None

    # =========================================================================
    # HYBRID ACCESS PATHS (GLEAN 450+ Recommendations)
    # =========================================================================
    try:
        access_paths = extract_ht_access_paths_from_snowvi(snowvi_json)
        features["access_paths"] = access_paths
        features["has_access_paths"] = len(access_paths) > 0
        # Check if any table has analytic access pattern
        features["has_analytic_access_pattern"] = any(
            ap.get("is_analytic_pattern", False) 
            for ap in access_paths.values()
        )
        # List tables with analytic patterns
        features["analytic_access_tables"] = [
            alias for alias, ap in access_paths.items()
            if ap.get("is_analytic_pattern", False)
        ]
    except Exception:
        features["access_paths"] = {}
        features["has_access_paths"] = False
        features["has_analytic_access_pattern"] = False
        features["analytic_access_tables"] = []

    return features


# =============================================================================
# ROOT CAUSE CLASSIFICATION - 2-Run Comparison
# =============================================================================

# Root cause labels (used in classification and prompts)
ROOT_CAUSE_LABELS = {
    "QUERY_CHANGE": "Different query (SQL hash changed)",
    "NO_REGRESSION": "No significant performance change",
    "COMPILATION": "Compilation time increased significantly",
    "DATA_VOLUME": "Data volume increased (more KV rows scanned)",
    "INDEX_PATH": "Index path changed (different index usage)",
    "FDB_LATENCY": "FDB storage layer latency spike",
    "XP_EXECUTION_ENVIRONMENT": "XP execution environment (warehouse load, concurrency)",
    "XP_EXECUTION": "XP execution issue (generic)",
    "JOIN_SKEW_OR_EXPLOSION": "Join explosion or data skew",
    "PLAN_CACHE": "Plan cache miss (recompilation)",
    "UNKNOWN": "Unable to classify (insufficient data)",
}


def classify_run_pair(
    features_a: Dict[str, Any], 
    features_b: Dict[str, Any]
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Compare two feature dicts and return pre-classified root cause.
    
    This is the CORE classification logic. It runs in code (deterministic),
    not in AI (non-deterministic). The AI then EXPLAINS this classification.
    
    Args:
        features_a: Feature dict for baseline (usually faster) run
        features_b: Feature dict for comparison (usually slower) run
        
    Returns:
        Tuple of:
        - primary_cause: Root cause label (e.g., "DATA_VOLUME")
        - secondary_cause: Optional secondary factor (e.g., "FDB_LATENCY")  
        - diff: Dict of metric deltas with a/b/delta values
    """
    fa, fb = features_a, features_b
    
    # Build diff dict for key metrics
    diff: Dict[str, Any] = {}
    metrics_to_compare = [
        "total_ms", "xp_ms", "gs_exec_ms", "gs_compile_ms",
        "kv_rows_scanned", "snowtram_kvs_txn", "fdb_total_ms", "fdb_num_txn",
        "rows_produced", "bytes_scanned"
    ]
    
    for key in metrics_to_compare:
        a = fa.get(key) or 0.0
        b = fb.get(key) or 0.0
        pct = ((b - a) / max(a, 1.0)) * 100 if a > 0 else (100 if b > 0 else 0)
        diff[key] = {
            "a": a, 
            "b": b, 
            "delta": b - a,
            "pct": pct,
            "increased": b > a,
        }

    secondary_cause: Optional[str] = None
    
    # =========================================================================
    # CLASSIFICATION HEURISTICS (in priority order)
    # =========================================================================
    
    # 1) Different SQL hash → QUERY_CHANGE
    hash_a = fa.get("sanitized_sql_hash")
    hash_b = fb.get("sanitized_sql_hash")
    if hash_a and hash_b and hash_a != hash_b:
        return "QUERY_CHANGE", "", diff

    # 2) If total_ms is essentially the same (within 20%) → NO_REGRESSION
    total_a = fa.get("total_ms") or 0.0
    total_b = fb.get("total_ms") or 0.0
    if total_a > 0 and abs(diff["total_ms"]["delta"]) <= 0.2 * total_a:
        return "NO_REGRESSION", "", diff

    # 3) Compilation time exploded (>50% of baseline total) → COMPILATION
    compile_delta = diff["gs_compile_ms"]["delta"]
    if compile_delta > 0.5 * max(total_a, 1.0):
        return "COMPILATION", "", diff

    # 4) Plan cache hit vs miss detection
    cache_a = fa.get("plan_cache_reused", False)
    cache_b = fb.get("plan_cache_reused", False)
    if cache_a and not cache_b:
        # A had cache hit, B had cache miss
        secondary_cause = "PLAN_CACHE"

    # 5) Focus on XP-dominated execution (common for HT queries)
    xp_share_a = fa.get("xp_share") or 0.0
    xp_share_b = fb.get("xp_share") or 0.0
    
    if xp_share_a > 0.5 or xp_share_b > 0.5:
        # XP is significant portion of execution
        
        # Check KV volume change
        kv_a = fa.get("kv_rows_scanned") or 0.0
        kv_b = fb.get("kv_rows_scanned") or 0.0
        
        if kv_a > 0 and kv_b > 0:
            kv_ratio = kv_b / kv_a
        elif kv_b > 0:
            kv_ratio = float('inf')
        else:
            kv_ratio = 1.0

        # Check KV transaction count change
        txn_a = fa.get("snowtram_kvs_txn") or 0.0
        txn_b = fb.get("snowtram_kvs_txn") or 0.0
        
        if txn_a > 0 and txn_b > 0:
            txn_ratio = txn_b / txn_a
        elif txn_b > 0:
            txn_ratio = float('inf')
        else:
            txn_ratio = 1.0

        # 5a) Big KV row increase (>2x) → DATA_VOLUME
        if kv_ratio > 2.0:
            return "DATA_VOLUME", secondary_cause or "", diff

        # 5b) Same KV volume but XP time exploded → check FDB vs XP environment
        if 0.5 <= kv_ratio <= 2.0 and 0.5 <= txn_ratio <= 2.0:
            # KV work is similar between runs
            
            fdb_a = fa.get("fdb_total_ms") or 0.0
            fdb_b = fb.get("fdb_total_ms") or 0.0
            xp_a = fa.get("xp_ms") or 0.0
            xp_b = fb.get("xp_ms") or 0.0
            
            # FDB time exploded and dominates XP time → FDB_LATENCY
            if fdb_b > 3 * max(fdb_a, 1.0) and fdb_b > 0.3 * max(xp_b, 1.0):
                return "FDB_LATENCY", secondary_cause or "", diff

            # Otherwise: same KV work, but XP time larger → execution environment
            if xp_b > 2 * max(xp_a, 1.0):
                return "XP_EXECUTION_ENVIRONMENT", secondary_cause or "", diff

        # 5c) Index path change detection (if we have index metadata)
        # TODO: Add index_operator comparison when available
        
        # 5d) Join explosion detection (from hot RSOs)
        hot_rsos_b = fb.get("hot_rsos", [])
        for rso in hot_rsos_b:
            if "HashJoin" in rso.get("name", "") and rso.get("time_ms", 0) > 0.5 * xp_b:
                return "JOIN_SKEW_OR_EXPLOSION", secondary_cause or "", diff

    # Fallback: generic XP execution issue
    if diff["xp_ms"]["delta"] > 0.5 * max(total_a, 1.0):
        return "XP_EXECUTION", secondary_cause or "", diff

    return "UNKNOWN", secondary_cause or "", diff


# =============================================================================
# ROOT CAUSE CLASSIFICATION - Batch Analysis
# =============================================================================

# Batch query labels
BATCH_QUERY_LABELS = {
    "OLTP_OPTIMAL": "Well-optimized OLTP query (<100ms, low KV)",
    "OLTP_SLOW": "Slow OLTP query (should be <100ms but isn't)",
    "HYBRID_ANALYTIC": "Analytic workload on Hybrid Table (large scans)",
    "MISSING_INDEX": "Likely missing index (high KV scans, low index usage)",
    "FDB_BOTTLENECK": "FDB storage layer bottleneck",
    "COMPILATION_HEAVY": "High compilation overhead (plan cache miss)",
    "JOIN_HEAVY": "Join-dominated execution",
    "UNKNOWN": "Unable to classify",
}


def classify_single_query(features: Dict[str, Any], threshold_ms: int = 1000) -> str:
    """
    Classify a single query based on its features.
    
    Args:
        features: Feature dict from extract_snowvi_features()
        threshold_ms: Duration threshold for fast vs slow
        
    Returns:
        Classification label (e.g., "OLTP_OPTIMAL", "HYBRID_ANALYTIC")
    """
    total_ms = features.get("total_ms") or 0.0
    xp_ms = features.get("xp_ms") or 0.0
    gs_compile = features.get("gs_compile_ms") or 0.0
    kv_rows = features.get("kv_rows_scanned") or 0.0
    kv_index_rows = features.get("kv_index_rows_scanned") or 0.0
    rows_produced = features.get("rows_produced") or 0.0
    fdb_ms = features.get("fdb_total_ms") or 0.0
    
    # OLTP optimal: fast, low KV work
    if total_ms < 100 and kv_rows < 1000:
        return "OLTP_OPTIMAL"
    
    # Compilation-heavy: high compile share
    if total_ms > 0 and gs_compile / total_ms > 0.5:
        return "COMPILATION_HEAVY"
    
    # Hybrid analytic: large KV scans OR many rows produced
    if kv_rows > 100000 or rows_produced > 10000:
        return "HYBRID_ANALYTIC"
    
    # FDB bottleneck: FDB time dominates XP time
    if xp_ms > 0 and fdb_ms / xp_ms > 0.5 and fdb_ms > 100:
        return "FDB_BOTTLENECK"
    
    # Missing index: high KV scans but low index usage
    if kv_rows > 1000 and kv_index_rows < kv_rows * 0.1:
        return "MISSING_INDEX"
    
    # Check hot RSOs for join-heavy
    hot_rsos = features.get("hot_rsos", [])
    for rso in hot_rsos:
        if "HashJoin" in rso.get("name", ""):
            return "JOIN_HEAVY"
    
    # Slow OLTP: should be fast but isn't
    if total_ms >= threshold_ms and kv_rows < 10000 and rows_produced < 1000:
        return "OLTP_SLOW"
    
    return "UNKNOWN"


def classify_batch_queries(
    all_features: List[Dict[str, Any]], 
    threshold_ms: int = 1000
) -> Dict[str, Any]:
    """
    Classify a batch of queries and identify patterns.
    
    This pre-classifies each query in code, then aggregates to find
    the dominant root causes in the batch.
    
    Args:
        all_features: List of feature dicts from extract_snowvi_features()
        threshold_ms: Duration threshold for fast vs slow
        
    Returns:
        Dict with:
        - fast_queries: List of (features, label) for fast queries
        - slow_queries: List of (features, label) for slow queries
        - slow_buckets: Dict mapping label → list of features
        - dominant_slow_cause: Most common cause among slow queries
        - summary: Human-readable summary
    """
    fast_queries = []
    slow_queries = []
    slow_buckets: Dict[str, List[Dict[str, Any]]] = {}
    
    for features in all_features:
        total_ms = features.get("total_ms") or 0.0
        label = classify_single_query(features, threshold_ms)
        
        if total_ms < threshold_ms:
            fast_queries.append({"features": features, "label": label})
        else:
            slow_queries.append({"features": features, "label": label})
            
            # Group slow queries by label
            if label not in slow_buckets:
                slow_buckets[label] = []
            slow_buckets[label].append(features)
    
    # Find dominant cause among slow queries
    dominant_slow_cause = "UNKNOWN"
    max_count = 0
    for label, queries in slow_buckets.items():
        if len(queries) > max_count:
            max_count = len(queries)
            dominant_slow_cause = label
    
    # Build summary
    total = len(all_features)
    fast_count = len(fast_queries)
    slow_count = len(slow_queries)
    
    summary_parts = [
        f"Analyzed {total} queries: {fast_count} fast (<{threshold_ms}ms), {slow_count} slow (≥{threshold_ms}ms)."
    ]
    
    if slow_count > 0:
        bucket_summary = ", ".join([
            f"{label}: {len(queries)}" 
            for label, queries in sorted(slow_buckets.items(), key=lambda x: -len(x[1]))
        ])
        summary_parts.append(f"Slow query breakdown: {bucket_summary}.")
        summary_parts.append(f"Primary root cause: {BATCH_QUERY_LABELS.get(dominant_slow_cause, dominant_slow_cause)}.")
    
    return {
        "fast_queries": fast_queries,
        "slow_queries": slow_queries,
        "slow_buckets": slow_buckets,
        "dominant_slow_cause": dominant_slow_cause,
        "summary": " ".join(summary_parts),
        "total_count": total,
        "fast_count": fast_count,
        "slow_count": slow_count,
    }


def build_comparison_diff_summary(diff: Dict[str, Any]) -> str:
    """
    Build a human-readable summary of metric differences.
    
    Args:
        diff: Diff dict from classify_run_pair()
        
    Returns:
        Formatted string showing key differences
    """
    lines = []
    
    # Format key metrics
    key_metrics = [
        ("total_ms", "Total Duration", "ms"),
        ("xp_ms", "XP Execution", "ms"),
        ("gs_compile_ms", "Compilation", "ms"),
        ("kv_rows_scanned", "KV Rows Scanned", "rows"),
        ("snowtram_kvs_txn", "KV Transactions", "txns"),
        ("fdb_total_ms", "FDB Duration", "ms"),
    ]
    
    for key, label, unit in key_metrics:
        if key in diff:
            d = diff[key]
            a, b, delta, pct = d["a"], d["b"], d["delta"], d["pct"]
            if a > 0 or b > 0:
                direction = "↑" if delta > 0 else "↓" if delta < 0 else "="
                lines.append(f"- {label}: {a:.0f} → {b:.0f} {unit} ({direction} {abs(pct):.1f}%)")
    
    return "\n".join(lines) if lines else "No significant differences detected."


# =============================================================================
# XP EXECUTION DETAIL CLASSIFICATION
# =============================================================================

# Sub-classifications for XP_EXECUTION issues (when we need to drill deeper)
XP_DETAIL_LABELS = {
    "HYBRID_PROBE_BOUND": "HybridTableProbe dominates XP time - likely index/predicate issue",
    "JOIN_BOUND": "Hash join operations dominate - check join order and filter placement",
    "EXECUTION_SKEW": "High idle time indicates data skew or resource contention",
    "HYBRID_PROBE_DOMINANT": "Single HybridTableProbe operator dominates - ensure predicates are indexed",
    "HASH_JOIN_DOMINANT": "Single HashJoin operator dominates - optimize join strategy",
    "FILTER_DOMINANT": "FilterRSO dominates - predicates applied too late in plan",
    "XP_PROFILING_UNAVAILABLE": "XP profiling data not available in this export",
}


def classify_xp_execution_detail(
    features: Dict[str, Any]
) -> Tuple[str, str, str]:
    """
    When XP execution is the primary issue, drill deeper using profiling data
    to provide specific sub-classification and actionable recommendations.
    
    This is Step 1 of the analysis: CODE-based classification that gives
    specific, actionable insight into WHY XP is slow.
    
    Args:
        features: Feature dict from extract_snowvi_features()
        
    Returns:
        Tuple of (sub_cause_label, explanation, specific_recommendation)
    """
    xp_ms = features.get("xp_ms") or 1.0
    
    # Check profiling breakdown (if available)
    prof_hybrid = features.get("prof_hybrid_probe") or 0
    prof_hash_join = features.get("prof_hash_join") or 0
    prof_idle = features.get("prof_idle") or 0
    prof_cpu = features.get("prof_cpu") or 0
    prof_filter = features.get("prof_filter") or 0
    
    has_profiling = prof_cpu > 0 or prof_idle > 0 or prof_hybrid > 0 or prof_hash_join > 0
    
    if has_profiling:
        # Calculate shares of XP time
        hybrid_share = prof_hybrid / xp_ms if xp_ms > 0 else 0
        join_share = prof_hash_join / xp_ms if xp_ms > 0 else 0
        idle_share = prof_idle / xp_ms if xp_ms > 0 else 0
        filter_share = prof_filter / xp_ms if xp_ms > 0 else 0
        
        # Classify based on dominant component
        if hybrid_share > 0.5:
            return (
                "HYBRID_PROBE_BOUND",
                f"HybridTableProbe consumes {hybrid_share*100:.0f}% of XP time ({prof_hybrid:.0f}ms of {xp_ms:.0f}ms).",
                "CREATE INDEX on the columns used in WHERE predicates. "
                "Verify predicate columns match index key order (leftmost prefix rule)."
            )
        
        if join_share > 0.3:
            return (
                "JOIN_BOUND",
                f"Hash join operations consume {join_share*100:.0f}% of XP time ({prof_hash_join:.0f}ms).",
                "Apply filters BEFORE joining to reduce intermediate result size. "
                "Check for missing join key indexes. Consider query rewrite to filter earlier."
            )
        
        if idle_share > 0.3:
            return (
                "EXECUTION_SKEW",
                f"High idle time ({idle_share*100:.0f}% of XP) indicates data skew or resource wait.",
                "Check for hot keys causing data skew. Consider workload isolation "
                "with dedicated warehouse. Review concurrent query load during execution."
            )
        
        if filter_share > 0.3:
            return (
                "FILTER_DOMINANT",
                f"FilterRSO consumes {filter_share*100:.0f}% of XP time - predicates applied late.",
                "Push predicates earlier in the query plan. Consider adding index on filter columns. "
                "Review query structure to ensure WHERE clauses are applied to indexed columns."
            )
    
    # Check hot RSOs (if available and profiling wasn't conclusive)
    hot_rsos = features.get("hot_rsos", [])
    if hot_rsos:
        top_rso = hot_rsos[0]
        rso_name = top_rso.get("name", "")
        rso_time = top_rso.get("time_ms", 0)
        rso_share = rso_time / xp_ms if xp_ms > 0 else 0
        
        if rso_share > 0.4:  # This operator dominates
            if "HybridTableProbe" in rso_name:
                return (
                    "HYBRID_PROBE_DOMINANT",
                    f"'{rso_name}' takes {rso_share*100:.0f}% of XP time ({rso_time:.0f}ms).",
                    "Ensure WHERE predicate columns have covering indexes. "
                    "Check that index key order matches predicate column order."
                )
            
            if "HashJoin" in rso_name:
                return (
                    "HASH_JOIN_DOMINANT",
                    f"'{rso_name}' takes {rso_share*100:.0f}% of XP time ({rso_time:.0f}ms).",
                    "Review join order - filter tables before joining. "
                    "Check for Cartesian products or missing join conditions."
                )
            
            if "Filter" in rso_name:
                return (
                    "FILTER_DOMINANT",
                    f"'{rso_name}' takes {rso_share*100:.0f}% of XP time ({rso_time:.0f}ms).",
                    "Filter is being applied late in execution. "
                    "Add index on filter columns or restructure query to filter earlier."
                )
    
    # Fallback: no profiling data or inconclusive
    return (
        "XP_PROFILING_UNAVAILABLE",
        "XP profiling data not available in this SnowVI export.",
        "Export SnowVI with 'Save All' to include detailed profiling. "
        "Check warehouse concurrency and resource utilization during query execution."
    )


# =============================================================================
# BATCH ROOT CAUSE CLASSIFICATION - Fast vs Slow Group Comparison
# =============================================================================

# Labels for batch-level root cause (comparing group averages)
BATCH_ROOT_CAUSE_LABELS = {
    "QUERY_CHANGE": "Different queries (SQL hashes differ between groups)",
    "DATA_VOLUME": "Slow queries scan more KV rows (data volume difference)",
    "FDB_BOUND": "FDB storage layer dominates XP time and differs significantly",
    "XP_EXECUTION_ENVIRONMENT": "Same KV work but XP time differs (warehouse load, concurrency, engine)",
    "JOIN_SKEW_OR_EXPLOSION": "Join explosion or data skew causing row multiplication",
    "COMPILATION": "High compilation overhead in slow group",
    "MIXED": "Multiple contributing factors (no single dominant cause)",
    "INSUFFICIENT_DATA": "Not enough data to classify",
}


def classify_batch_root_cause(
    fast_summary: Dict[str, Any], 
    slow_summary: Dict[str, Any],
    slow_features_sample: Optional[Dict[str, Any]] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    Classify the PRIMARY root cause for why slow queries are slow compared to fast.
    
    This compares GROUP AVERAGES (not individual queries) to determine the
    dominant factor explaining the performance difference.
    
    When XP execution is the primary issue, drills deeper using XP profiling
    data to provide specific sub-classification.
    
    Based on GLEAN recommendations (lines 1199-1227):
    - If SQL hash differs → QUERY_CHANGE
    - If KV rows differ significantly → DATA_VOLUME  
    - If FDB dominates XP and differs → FDB_BOUND
    - If KV/FDB similar but XP up → XP_EXECUTION (with sub-classification)
    
    Args:
        fast_summary: Dict with avg metrics for fast queries
        slow_summary: Dict with avg metrics for slow queries
        slow_features_sample: Optional sample features from a slow query for
                             XP profiling data (used for sub-classification)
        
    Returns:
        Tuple of (root_cause_label, delta_dict with optional xp_detail)
    """
    # Extract key averages with safe defaults
    fast_dur = fast_summary.get("duration_avg_ms") or 0
    slow_dur = slow_summary.get("duration_avg_ms") or 0
    fast_xp = fast_summary.get("xp_exec_avg_ms") or 0
    slow_xp = slow_summary.get("xp_exec_avg_ms") or 0
    fast_kv = fast_summary.get("kv_scanned_rows_avg") or 0
    slow_kv = slow_summary.get("kv_scanned_rows_avg") or 0
    fast_fdb = fast_summary.get("fdb_duration_avg_ms") or 0
    slow_fdb = slow_summary.get("fdb_duration_avg_ms") or 0
    fast_txn = fast_summary.get("fdb_transactions_avg") or 0
    slow_txn = slow_summary.get("fdb_transactions_avg") or 0
    fast_compile = fast_summary.get("compile_time_avg_ms") or 0
    slow_compile = slow_summary.get("compile_time_avg_ms") or 0
    
    # Build delta dict for reporting
    delta: Dict[str, Any] = {
        "duration_ms": {"fast": fast_dur, "slow": slow_dur, "delta": slow_dur - fast_dur},
        "xp_exec_ms": {"fast": fast_xp, "slow": slow_xp, "delta": slow_xp - fast_xp},
        "kv_rows_scanned": {"fast": fast_kv, "slow": slow_kv, "delta": slow_kv - fast_kv},
        "fdb_duration_ms": {"fast": fast_fdb, "slow": slow_fdb, "delta": slow_fdb - fast_fdb},
        "fdb_transactions": {"fast": fast_txn, "slow": slow_txn, "delta": slow_txn - fast_txn},
        "compile_time_ms": {"fast": fast_compile, "slow": slow_compile, "delta": slow_compile - fast_compile},
    }
    
    # Handle insufficient data
    if fast_dur == 0 or slow_dur == 0:
        return "INSUFFICIENT_DATA", delta
    
    # Check if sanitized hashes differ (would need individual query data)
    # This is a batch-level check, so we skip hash comparison here
    # (Individual classification handles QUERY_CHANGE)
    
    # 1) Compilation exploded
    compile_delta = slow_compile - fast_compile
    if compile_delta > 0.5 * fast_dur:
        return "COMPILATION", delta
    
    # 2) Big KV row increase (>2x) → DATA_VOLUME
    if fast_kv > 0:
        kv_ratio = slow_kv / fast_kv
        if kv_ratio > 2.0:
            return "DATA_VOLUME", delta
    
    # 2.5) Check for join explosion in slow queries (GLEAN 450+ Recommendations)
    if slow_features_sample:
        has_explosion = slow_features_sample.get("has_join_explosion", False)
        max_ratio = slow_features_sample.get("max_join_ratio", 0)
        
        # Strong join explosion detected (>20x ratio)
        if has_explosion and max_ratio > 20:
            delta["join_explosion"] = {
                "max_ratio": max_ratio,
                "operator": slow_features_sample.get("worst_explosion_operator"),
                "explanation": f"Join with {max_ratio:.0f}x row multiplication detected"
            }
            return "JOIN_SKEW_OR_EXPLOSION", delta
    
    # 3) Check if KV and FDB transactions are similar (within 20%)
    kv_similar = (abs(slow_kv - fast_kv) / max(fast_kv, slow_kv, 1)) < 0.2
    txn_similar = (abs(slow_txn - fast_txn) / max(fast_txn, slow_txn, 1)) < 0.2
    
    # 4) FDB dominates XP and grows significantly → FDB_BOUND
    if slow_xp > 0 and slow_fdb > 0:
        fdb_share_of_xp = slow_fdb / slow_xp
        fdb_ratio = slow_fdb / max(fast_fdb, 1)
        
        # FDB dominates (>50% of XP) and grew >3x
        if fdb_share_of_xp > 0.5 and fdb_ratio > 3.0:
            return "FDB_BOUND", delta
    
    # 5) Same KV/FDB volume but XP time much larger → XP execution issue
    #    Drill deeper using XP profiling data for sub-classification
    if kv_similar and txn_similar:
        xp_delta = slow_xp - fast_xp
        if xp_delta > 0.5 * max(fast_xp, 1):
            # Try to sub-classify using XP profiling data
            if slow_features_sample:
                xp_sub_cause, xp_explanation, xp_recommendation = classify_xp_execution_detail(
                    slow_features_sample
                )
                delta["xp_detail"] = {
                    "sub_cause": xp_sub_cause,
                    "explanation": xp_explanation,
                    "recommendation": xp_recommendation,
                }
                # Return combined label for more specificity
                if xp_sub_cause != "XP_PROFILING_UNAVAILABLE":
                    return f"XP_EXECUTION:{xp_sub_cause}", delta
            
            return "XP_EXECUTION_ENVIRONMENT", delta
    
    # 6) Multiple factors or unclear
    return "MIXED", delta


def get_batch_recommendation_constraints(
    root_cause: str, 
    delta: Dict[str, Any],
    all_slow_use_bound_vars: bool = False
) -> List[str]:
    """
    Generate specific recommendation constraints based on batch root cause.
    
    This prevents the AI from making generic recommendations that don't
    match the data (e.g., recommending FDB optimization when FDB isn't the issue).
    
    Based on GLEAN recommendations (lines 1259-1279).
    
    Args:
        root_cause: The classified root cause label
        delta: The delta dict from classify_batch_root_cause()
        all_slow_use_bound_vars: Whether all slow queries already use bound vars
        
    Returns:
        List of constraint strings to include in the AI prompt
    """
    constraints = []
    
    # Global constraint: don't recommend what's already in use
    if all_slow_use_bound_vars:
        constraints.append(
            "⚠️ ALL slow queries already use bound variables. "
            "Do NOT recommend parameterization."
        )
    
    # Root cause specific constraints
    if root_cause == "XP_EXECUTION_ENVIRONMENT":
        constraints.append(
            "The root cause is XP EXECUTION ENVIRONMENT (warehouse load, concurrency, "
            "engine behavior). KV and FDB metrics are SIMILAR between groups. "
            "Focus recommendations on: warehouse sizing, concurrency limits, workload isolation. "
            "Do NOT recommend FDB optimization or query rewrites."
        )
        
        # Check if FDB is actually similar
        fdb_fast = delta.get("fdb_duration_ms", {}).get("fast", 0)
        fdb_slow = delta.get("fdb_duration_ms", {}).get("slow", 0)
        if fdb_fast > 0 and abs(fdb_slow - fdb_fast) / fdb_fast < 0.5:
            constraints.append(
                f"FDB duration is similar (fast: {fdb_fast:.0f}ms, slow: {fdb_slow:.0f}ms). "
                "FDB is NOT the bottleneck. Do NOT recommend FDB optimization."
            )
    
    elif root_cause == "FDB_BOUND":
        constraints.append(
            "The root cause is FDB STORAGE LAYER. FDB time dominates XP execution. "
            "Focus recommendations on: batching Hybrid DML, reducing per-row operations, "
            "using bulk-load patterns, checking throttling/quota."
        )
    
    elif root_cause == "DATA_VOLUME":
        constraints.append(
            "The root cause is DATA VOLUME. Slow queries scan significantly more KV rows. "
            "Focus recommendations on: predicates, indexes, table type choice (HT vs Standard)."
        )
    
    elif root_cause == "JOIN_SKEW_OR_EXPLOSION":
        join_info = delta.get("join_explosion", {})
        max_ratio = join_info.get("max_ratio", 0)
        constraints.append(
            f"The root cause is JOIN EXPLOSION. A join produces {max_ratio:.0f}x more rows than inputs. "
            "Focus recommendations on: reviewing join keys, adding predicates to reduce row multiplication, "
            "pre-aggregating data, or breaking up the query. "
            "Do NOT recommend index changes or warehouse sizing as primary fixes."
        )
    
    elif root_cause == "COMPILATION":
        constraints.append(
            "The root cause is COMPILATION overhead. Slow queries spend more time compiling. "
            "Focus recommendations on: bound variables (if not already used), plan cache reuse."
        )
        if all_slow_use_bound_vars:
            constraints.append(
                "NOTE: Bound variables are already in use. The compilation issue may be "
                "due to complex query patterns or schema changes. Consider query simplification."
            )
    
    elif root_cause == "MIXED":
        constraints.append(
            "Multiple factors contribute to the performance difference. "
            "Prioritize recommendations based on the largest metric deltas."
        )
        
    # Add constraint about not recommending generic rewrites
    kv_fast = delta.get("kv_rows_scanned", {}).get("fast", 0)
    kv_slow = delta.get("kv_rows_scanned", {}).get("slow", 0)
    if kv_fast > 0 and abs(kv_slow - kv_fast) / kv_fast < 0.2:
        constraints.append(
            "KV rows scanned are SIMILAR between groups. The query pattern is "
            "not the primary issue. Do NOT recommend generic query rewrites."
        )
    
    return constraints
