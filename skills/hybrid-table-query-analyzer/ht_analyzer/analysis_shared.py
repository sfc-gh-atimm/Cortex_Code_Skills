from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

SQL_ANALYSIS_AVAILABLE = False
try:
    from sql_analysis.ht_query_optimization import (
        analyze_create_index_statement,
        detect_ctas_pk_violation,
        get_ddl_type,
        is_ddl_statement,
    )

    SQL_ANALYSIS_AVAILABLE = True
except Exception:
    SQL_ANALYSIS_AVAILABLE = False


def detect_kv_heavy_pattern(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    stats = (metadata or {}).get("SNOWVI_STATS") or {}

    try:
        kv_rows = float(stats.get("kvNumScannedRows") or 0)
        fdb_bytes = float(stats.get("snowTramFDBIOBytes") or 0)
        rows = float(metadata.get("ROWS_PRODUCED") or 0) or 1.0
        duration_ms = float(metadata.get("TOTAL_ELAPSED_TIME") or 0)
    except (TypeError, ValueError):
        return None

    if duration_ms < 5000 or kv_rows < 1_000_000:
        return None

    ratio = kv_rows / rows
    if ratio < 1000:
        return None

    fdb_gb = fdb_bytes / (1024 * 1024 * 1024) if fdb_bytes else 0
    fdb_info = f", FDB I/O ~ {fdb_gb:.1f} GB" if fdb_gb > 0.1 else ""

    return {
        "rule": "KV_HEAVY_LOW_SELECTIVITY",
        "severity": "HIGH",
        "finding": (
            f"Hybrid Table KV activity is very heavy: ~{kv_rows:,.0f} KV rows "
            f"scanned to produce ~{rows:,.0f} rows over {duration_ms/1000:.1f}s "
            f"(~{ratio:,.0f}x scan-to-return ratio{fdb_info})."
        ),
        "suggestion": (
            "Review join predicates and WHERE clause selectivity. "
            "Consider adding composite indexes on frequently joined columns. "
            "If this is an analytical query pattern, consider using Standard tables instead of Hybrid."
        ),
    }


def detect_hybrid_bulk_load_pattern(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not metadata:
        return None

    sql_text = (metadata.get("QUERY_TEXT") or metadata.get("SQL_TEXT") or "").upper()
    stmt_type = (metadata.get("STATEMENT_TYPE") or metadata.get("QUERY_TYPE") or "").upper()

    stats = (metadata or {}).get("SNOWVI_STATS") or {}
    try:
        rows_loaded = float(
            metadata.get("ROWS_INSERTED")
            or metadata.get("ROWS_PRODUCED")
            or 0
        )
        fdb_bytes = float(stats.get("snowTramFDBIOBytes") or 0)
        duration_ms = float(metadata.get("TOTAL_ELAPSED_TIME") or 0)
    except (TypeError, ValueError):
        return None

    is_insert_like = (
        "INSERT" in stmt_type
        or "MERGE" in stmt_type
        or "COPY" in stmt_type
        or sql_text.startswith("INSERT INTO")
        or "COPY INTO" in sql_text
        or "MERGE INTO" in sql_text
    )
    if not is_insert_like:
        return None

    has_kv = bool(metadata.get("ACCESS_KV_TABLE")) or bool(stats)
    if not has_kv:
        return None

    is_large = rows_loaded > 5_000_000 or fdb_bytes > 5 * 1024 * 1024 * 1024 or duration_ms > 60_000
    if not is_large:
        return None

    return {
        "rule": "HT_BULK_LOAD_PATTERN",
        "severity": "HIGH",
        "finding": (
            "Large bulk load into Hybrid Table detected (high rows/FDB I/O/long runtime)."
        ),
        "suggestion": (
            "Prefer CTAS into an empty Hybrid Table for backfills, or chunk MERGE/INSERT workloads "
            "by time/key ranges to reduce KV pressure."
        ),
    }


def _attach_ht_bulk_load_failure_findings(findings: Dict[str, Any], metadata: Dict[str, Any], coverage):
    err_code = str(metadata.get("ERROR_CODE") or "")
    err_msg = (metadata.get("ERROR_MESSAGE") or "")

    qtype = (metadata.get("QUERY_TYPE") or "").upper()

    try:
        inserted = float(metadata.get("ROWS_INSERTED") or 0)
        updated = float(metadata.get("ROWS_UPDATED") or 0)
        changed = inserted + updated
    except (TypeError, ValueError):
        changed = 0.0

    try:
        dur_ms = float(metadata.get("TOTAL_ELAPSED_TIME") or 0)
    except (TypeError, ValueError):
        dur_ms = 0.0

    is_bulk_ctas = (qtype == "CREATE_TABLE_AS_SELECT" and dur_ms > 60_000)
    is_bulk_dml = (
        qtype in ("INSERT", "MERGE", "UPDATE", "COPY")
        and (changed > 5_000_000 or dur_ms > 60_000)
    )

    if err_code == "200017" or "EXCEED_MAX_TENANT_STORAGE_QUOTA" in err_msg.upper():
        cause = "Hybrid Table storage quota was exceeded during a bulk load operation."
    elif err_code == "200030":
        cause = (
            "A bulk load worker aborted due to a peer worker failure during Hybrid Table bulk load."
        )
    else:
        cause = (
            "Hybrid Table bulk load failed with internal error, likely driven by large bulk workloads."
        )

    base_finding = (
        f"Hybrid Table bulk load failed with error {err_code}. {cause} "
        "This usually occurs when large CTAS / COPY / INSERT...SELECT / MERGE operations into Hybrid Tables "
        "use the non-optimized transactional path or push the database over its Hybrid quotas."
    )

    suggestion = (
        "Apply HT bulk-load patterns:\n"
        "1) Prefer CTAS / COPY / INSERT...SELECT into an EMPTY Hybrid Table for initial backfills, then "
        "swap tables and recreate indexes;\n"
        "2) If the table is not empty, slice large MERGE/INSERT jobs by time/key ranges and run them "
        "sequentially;\n"
        "3) Stage data into standard tables and periodically MERGE only recent deltas into the Hybrid Table;\n"
        "4) Minimize non-critical secondary indexes during large backfills, recreating them afterwards;\n"
        "5) When errors show quota issues, verify Hybrid storage usage and adjust only after validation."
    )

    findings["errors"].append(
        {
            "check": "Hybrid Table Bulk Load Failures",
            "rule": "HT_BULK_LOAD_FAILURE_1079_201000",
            "severity": "HIGH",
            "source": "runtime",
            "finding": base_finding,
            "suggestion": suggestion,
        }
    )

    if is_bulk_ctas:
        findings["warnings"].append(
            {
                "check": "Bulk Load Pattern Context",
                "rule": "HT_BULK_LOAD_PATTERN_CONTEXT",
                "severity": "MEDIUM",
                "source": "runtime",
                "finding": (
                    "Large CTAS into Hybrid Table detected. Ensure the target HT is empty to use the "
                    "optimized bulk-load path."
                ),
            }
        )

    if is_bulk_dml:
        findings["warnings"].append(
            {
                "check": "Bulk Load Pattern Context",
                "rule": "HT_BULK_LOAD_PATTERN_CONTEXT",
                "severity": "MEDIUM",
                "source": "runtime",
                "finding": (
                    "Large MERGE/INSERT/UPDATE into Hybrid Table detected. Consider CTAS+swap for "
                    "historical loads and/or chunking by time/key."
                ),
            }
        )


def analyze_ht_best_practices(
    query_uuid: Optional[str],
    metadata: Dict[str, Any],
    sql_analysis_findings: Optional[List[Dict[str, Any]]] = None,
    coverage: Optional[List[Dict[str, Any]]] = None,
    sql_analysis_ran: bool = True,
) -> Dict[str, Any]:
    findings = {
        "score": 100,
        "grade": "A",
        "summary": "",
        "passed": [],
        "warnings": [],
        "errors": [],
    }

    err_code = str(metadata.get("ERROR_CODE") or "")
    err_msg = (metadata.get("ERROR_MESSAGE") or "").upper()

    ht_bulk_error_codes = {"1079", "201000", "200017", "200030"}
    is_ht = bool(metadata.get("ACCESS_KV_TABLE"))
    qtype = (metadata.get("QUERY_TYPE") or "").upper()

    try:
        inserted = float(metadata.get("ROWS_INSERTED") or 0)
        updated = float(metadata.get("ROWS_UPDATED") or 0)
        changed = inserted + updated
    except (TypeError, ValueError):
        changed = 0.0

    try:
        dur_ms = float(metadata.get("TOTAL_ELAPSED_TIME") or 0)
    except (TypeError, ValueError):
        dur_ms = 0.0

    is_bulk_shape = (
        qtype in ("CREATE_TABLE_AS_SELECT", "INSERT", "MERGE", "UPDATE", "COPY")
        and (changed > 5_000_000 or dur_ms > 60_000)
    )
    is_bulk_query_type = qtype in ("CREATE_TABLE_AS_SELECT", "INSERT", "MERGE", "UPDATE", "COPY")

    msg_looks_like_bulk = any(
        token in err_msg
        for token in (
            "BULK LOAD",
            "BULKLOAD",
            "EXCEED_MAX_TENANT_STORAGE_QUOTA",
            "WORKER ABORTING DURING BULK LOAD OPERATION",
            "HYBRID",
        )
    )

    if err_code in ht_bulk_error_codes:
        _attach_ht_bulk_load_failure_findings(findings, metadata, coverage)
        findings["score"] = 0
        findings["grade"] = "F"
        findings["summary"] = f"Hybrid Table bulk load failed with error {err_code}"
        return findings

    if msg_looks_like_bulk and (is_ht or is_bulk_query_type) and not err_code:
        _attach_ht_bulk_load_failure_findings(findings, metadata, coverage)
        findings["score"] = 0
        findings["grade"] = "F"
        findings["summary"] = "Hybrid Table bulk load failed (detected from error message)"
        return findings

    if metadata.get("ERROR_CODE"):
        findings["score"] = 0
        findings["grade"] = "F"
        findings["summary"] = "Query failed - automatic F grade"
        findings["errors"].append(
            {"check": "Execution Status", "finding": f"Query failed with error {metadata['ERROR_CODE']}"}
        )
        return findings

    findings["passed"].append({"check": "Execution Status", "finding": "Query executed successfully"})

    sql_text = metadata.get("QUERY_TEXT", "") or ""
    ddl_type = None
    is_ddl = False
    if SQL_ANALYSIS_AVAILABLE:
        try:
            is_ddl = is_ddl_statement(sql_text)
            ddl_type = get_ddl_type(sql_text) if is_ddl else None
        except Exception:
            pass

    if is_ddl and ddl_type:
        findings["passed"].append(
            {
                "check": "Query Type",
                "finding": f"DDL statement detected: {ddl_type}",
                "recommendation": "DDL analysis mode - DML checks not applicable",
            }
        )
        if ddl_type == "CREATE_INDEX" and SQL_ANALYSIS_AVAILABLE:
            try:
                ci_findings = analyze_create_index_statement(sql_text, coverage or [], metadata)
                for issue in ci_findings.get("critical", []):
                    findings["score"] -= 25
                    findings["errors"].append(
                        {
                            "check": "CREATE INDEX Review",
                            "rule": issue.get("rule", "CREATE_INDEX_ISSUE"),
                            "severity": issue.get("severity", "HIGH"),
                            "finding": issue["message"],
                            "suggestion": issue["recommendation"],
                        }
                    )
                for issue in ci_findings.get("warnings", []):
                    findings["score"] -= 10
                    findings["warnings"].append(
                        {
                            "check": "CREATE INDEX Review",
                            "rule": issue.get("rule", "CREATE_INDEX_WARNING"),
                            "severity": issue.get("severity", "MEDIUM"),
                            "finding": issue["message"],
                            "suggestion": issue["recommendation"],
                        }
                    )
            except Exception:
                pass

        if ddl_type == "CREATE_HYBRID_TABLE_AS" and SQL_ANALYSIS_AVAILABLE:
            try:
                ctas_pk_finding = detect_ctas_pk_violation(sql_text, metadata)
                if ctas_pk_finding:
                    findings["score"] -= 25
                    findings["errors"].append(
                        {
                            "check": "CTAS Primary Key Uniqueness",
                            "rule": ctas_pk_finding["rule"],
                            "severity": ctas_pk_finding.get("severity", "MEDIUM"),
                            "finding": ctas_pk_finding["message"],
                            "suggestion": ctas_pk_finding["recommendation"],
                            "impact": ctas_pk_finding.get("impact", "CTAS failure due to duplicate PK values"),
                        }
                    )
            except Exception:
                pass

        findings["ddl_type"] = ddl_type
        score = max(0, min(100, findings["score"]))
        findings["score"] = score
        findings["grade"] = _grade_for_score(score)
        findings["summary"] = f"DDL statement ({ddl_type}) analyzed - {len(findings['errors'])} issues"
        return findings

    sql_upper = sql_text.upper().strip()
    is_insert_select = sql_upper.startswith("INSERT") and "SELECT" in sql_upper and "VALUES" not in sql_upper
    is_bulk_sql_pattern = is_bulk_shape or is_insert_select

    has_bound_vars = "?" in sql_text or any(
        f":{p}" in sql_text.lower() for p in ["1", "2", "3", "var", "param", "id", "value"]
    )
    if not has_bound_vars and not is_bulk_sql_pattern:
        findings["score"] -= 10
        findings["warnings"].append(
            {
                "check": "Bound Variables",
                "rule": "NO_BOUND_VARIABLES",
                "severity": "MEDIUM",
                "finding": "Query uses literals instead of bound variables; plan cache reuse may be low.",
                "suggestion": "Use bind parameters to improve plan cache reuse.",
            }
        )

    if " WHERE " not in sql_upper and not is_bulk_sql_pattern:
        findings["score"] -= 10
        findings["warnings"].append(
            {
                "check": "Filtering",
                "rule": "NO_WHERE_FILTER",
                "severity": "MEDIUM",
                "finding": "Query has no WHERE clause; may scan the full Hybrid Table.",
                "suggestion": "Add selective predicates on indexed columns.",
            }
        )

    kv_heavy = detect_kv_heavy_pattern(metadata)
    if kv_heavy:
        findings["score"] -= 20
        findings["errors"].append(kv_heavy)

    bulk_load = detect_hybrid_bulk_load_pattern(metadata)
    if bulk_load:
        findings["score"] -= 15
        findings["warnings"].append(bulk_load)

    score = max(0, min(100, findings["score"]))
    findings["score"] = score
    findings["grade"] = _grade_for_score(score)
    findings["summary"] = f"{len(findings['errors'])} errors, {len(findings['warnings'])} warnings"
    return findings


def infer_runtime_index_usage(metadata: Dict[str, Any], coverage: List[Dict[str, Any]]) -> Dict[str, Any]:
    result = {}

    if not metadata.get("ACCESS_KV_TABLE") or not coverage:
        return result

    try:
        bytes_scanned = float(metadata.get("BYTES_SCANNED") or 0)
    except (TypeError, ValueError):
        bytes_scanned = 0.0

    try:
        rows = float(metadata.get("ROWS_PRODUCED") or 0)
    except (TypeError, ValueError):
        rows = 0.0

    try:
        fdb_io = float(
            metadata.get("SNOWTRAM_FDB_IO_BYTES")
            or metadata.get("FDB_IO_BYTES")
            or 0
        )
    except (TypeError, ValueError):
        fdb_io = 0.0

    if rows <= 0:
        rows = 1.0

    bytes_per_row = bytes_scanned / rows if bytes_scanned > 0 else 0.0

    try:
        duration_ms = float(metadata.get("TOTAL_ELAPSED_TIME") or 0)
    except (TypeError, ValueError):
        duration_ms = 0.0

    duration_sec = duration_ms / 1000.0

    for cov in coverage:
        if not cov.get("is_hybrid"):
            continue

        table = cov.get("table") or "<unknown>"
        idx_count = len(cov.get("indexes", []))
        best_eq_prefix = cov.get("best_eq_prefix", 0) or 0

        expected_index_use = idx_count > 0 and best_eq_prefix > 0
        runtime_suspect = False

        if expected_index_use:
            if bytes_per_row > 10_000:
                runtime_suspect = True
            if fdb_io > 0 and duration_sec > 5 and rows <= 10_000:
                runtime_suspect = True

        result[table] = {
            "expected_index_use": expected_index_use,
            "runtime_suspect": runtime_suspect,
            "bytes_per_row": bytes_per_row,
            "duration_sec": duration_sec,
            "fdb_io_bytes": fdb_io,
        }

    return result


def analyze_snowvi_plan_for_ht(
    index_ops: Dict[str, Any],
    coverage: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    workload_type: str,
) -> List[Dict[str, Any]]:
    findings = []

    try:
        rows_produced = int(metadata.get("ROWS_PRODUCED") or 0)
    except (TypeError, ValueError):
        rows_produced = 0

    try:
        duration_ms = float(metadata.get("TOTAL_ELAPSED_TIME") or metadata.get("TOTAL_DURATION") or 0)
    except (TypeError, ValueError):
        duration_ms = 0.0
    duration_sec = duration_ms / 1000.0 if duration_ms else 0.0

    index_ops_norm = {
        (t or "").upper(): ops.get("index_ops", []) if isinstance(ops, dict) else []
        for t, ops in (index_ops or {}).items()
    }

    for cov in coverage or []:
        if not cov.get("is_hybrid"):
            continue

        table_name = (cov.get("table") or "").upper()
        ops = index_ops_norm.get(table_name, [])

        idx_count = len(cov.get("indexes") or [])
        best_eq_prefix = int(cov.get("best_eq_prefix") or 0)

        expected_index_use = idx_count > 0 and best_eq_prefix > 0
        plan_has_index = any(o.get("index_name") for o in ops)

        if expected_index_use and not plan_has_index:
            findings.append(
                {
                    "check": "Index Coverage vs Plan",
                    "rule": "HT_INDEXES_NOT_USED_PLAN",
                    "severity": "HIGH",
                    "source": "plan",
                    "finding": (
                        f"Hybrid Table `{table_name}` has indexes and good predicate coverage, "
                        "but the SnowVI execution plan contains no HT index operator for this table."
                    ),
                    "suggestion": (
                        "Investigate why the optimizer avoided the index: look for non-sargable predicates "
                        "(functions/casts on indexed columns), implicit conversions, or skewed cardinality. "
                        "Simplify predicates or adjust indexes to better match access patterns."
                    ),
                }
            )

        if best_eq_prefix == 0 and plan_has_index:
            findings.append(
                {
                    "check": "Index Coverage vs Plan",
                    "rule": "HT_INDEX_USED_DESPITE_WEAK_COVERAGE",
                    "severity": "LOW",
                    "source": "plan",
                    "finding": (
                        f"Execution plan uses an HT index operator on `{table_name}` even though static "
                        "coverage appears weak. Static analysis may be conservative for this pattern."
                    ),
                    "suggestion": (
                        "Treat static coverage as guidance. The runtime plan confirms HT index usage; "
                        "prioritize other issues first (bound variables, quota, workload fit) before "
                        "redesigning indexes."
                    ),
                }
            )

        scan_rows = 0
        for o in ops:
            est = int(o.get("estimated_rows") or 0)
            act = int(o.get("actual_rows") or 0)
            scan_rows += act or est

        if plan_has_index and scan_rows > 10_000 and rows_produced > 0:
            ratio = scan_rows / rows_produced
            if ratio > 50:
                findings.append(
                    {
                        "check": "Index Scan Selectivity",
                        "rule": "HT_INDEX_RANGE_SCAN",
                        "severity": "MEDIUM",
                        "source": "plan",
                        "finding": (
                            f"Execution plan shows an HT index operator on `{table_name}`, but the index "
                            f"scan covers ~{scan_rows:,} rows to return only {rows_produced:,} rows "
                            f"(~{ratio:.0f}x more scanned than returned)."
                        ),
                        "suggestion": (
                            "If this query is used for reporting (wide date ranges, many rows), move it to a "
                            "regular columnar table or pre-aggregated MV. Reserve HT for point/small-range "
                            "lookups."
                        ),
                    }
                )

        storage_sources = {(o.get("storage_source") or "").upper() for o in ops}
        if "ANALYTIC" in storage_sources:
            analytic_rows = 0
            for o in ops:
                if (o.get("storage_source") or "").upper() == "ANALYTIC":
                    analytic_rows = max(
                        analytic_rows,
                        int(o.get("actual_rows") or 0),
                        int(o.get("estimated_rows") or 0),
                    )

            if analytic_rows > 10_000:
                severity = "MEDIUM"
                finding_text = (
                    f"Execution plan reads `{table_name}` from the analytic/object-store copy "
                    f"({analytic_rows:,} rows scanned). The Hybrid Table is behaving like a standard "
                    "table for this workload."
                )
            else:
                severity = "LOW"
                finding_text = (
                    f"Execution plan reads `{table_name}` from the analytic/object-store copy instead "
                    "of the KV row-store path. For this query the Hybrid Table behaves like a standard "
                    "analytic table scan."
                )

            findings.append(
                {
                    "check": "Hybrid Table Storage Path",
                    "rule": "HT_ANALYTIC_STORE_SCAN",
                    "severity": severity,
                    "source": "plan",
                    "finding": finding_text,
                    "suggestion": (
                        "For large analytic/reporting patterns, rely on standard columnar tables or MVs. "
                        "Use Hybrid Tables for low-latency OLTP-style point/range lookups."
                    ),
                    "analytic_rows": analytic_rows,
                }
            )

    qtype = (metadata.get("QUERY_TYPE") or "").upper()
    sql_text = (metadata.get("QUERY_TEXT") or "").upper().strip()
    is_bulk_dml = qtype in ("INSERT", "MERGE", "COPY", "UPDATE", "CREATE_TABLE_AS_SELECT", "CTAS")
    is_insert_select = sql_text.startswith("INSERT") and "SELECT" in sql_text and "VALUES" not in sql_text
    is_bulk_operation = is_bulk_dml or is_insert_select

    is_ht_query = bool(metadata.get("ACCESS_KV_TABLE"))
    if is_ht_query and workload_type in ("ANALYTIC", "MIXED") and not is_bulk_operation:
        if rows_produced > 10_000 and duration_sec > 0.3:
            findings.append(
                {
                    "check": "Engine Choice",
                    "rule": "ANALYTIC_WORKLOAD_ON_HT",
                    "severity": "MEDIUM",
                    "source": "heuristic+plan",
                    "finding": (
                        f"Query against a Hybrid Table behaves like an analytic/reporting workload: "
                        f"{rows_produced:,} rows over {duration_sec:.2f}s with large scans/sorts. "
                        "Hybrid Tables are optimized for point/small-range lookups, not large analytic workloads."
                    ),
                    "suggestion": (
                        "Route this workload to a regular (columnar) table or pre-aggregated table/MV. "
                        "Keep Hybrid Tables for OLTP-style queries."
                    ),
                }
            )

    return findings


def _grade_for_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
