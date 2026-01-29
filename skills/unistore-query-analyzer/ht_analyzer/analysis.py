from typing import Any, Dict, List, Optional, Tuple, Set

from .analysis_shared import (
    analyze_ht_best_practices,
    analyze_snowvi_plan_for_ht,
    detect_hybrid_bulk_load_pattern,
    detect_kv_heavy_pattern,
    infer_runtime_index_usage,
)
from .snowvi_features import (
    extract_snowvi_features as extract_snowvi_features_from_json,
    classify_single_query,
    classify_run_pair,
    ROOT_CAUSE_LABELS,
    BATCH_QUERY_LABELS,
    build_comparison_diff_summary,
    build_comprehensive_summary,
)
from .reasoning_hints import get_reasoning_hints_text, get_applicable_hints, get_prioritized_findings
from .field_manual_loader import get_field_manual_context
from .finding_faqs import get_all_faqs_for_findings


def build_analysis_features(
    meta: Dict[str, Any],
    snowvi_features: Dict[str, Any],
    history_context: Dict[str, Any],
    comparison_uuid: Optional[str] = None,
    analysis_mode: str = "single",
    snowvi_json: Optional[Dict[str, Any]] = None,
    comparison_snowvi_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the deterministic feature set used for downstream prompts and JSON output.
    
    Args:
        meta: Query metadata from Snowhouse
        snowvi_features: Pre-extracted SnowVI features (optional)
        history_context: Historical query context
        comparison_uuid: UUID for comparison mode
        analysis_mode: "single" or "compare"
        snowvi_json: Full SnowVI JSON for primary query
        comparison_snowvi_json: Full SnowVI JSON for comparison query
    """
    sql_findings, coverage, sql_meta = run_sql_analysis(
        metadata=meta,
        snowvi_json=snowvi_json,
    )
    bp_findings = snowvi_features.get("bp_findings", {}) if isinstance(snowvi_features, dict) else {}
    if not bp_findings:
        bp_findings = analyze_ht_best_practices(
            query_uuid=meta.get("QUERY_ID"),
            metadata=meta,
            sql_analysis_findings=sql_findings,
            coverage=coverage,
            sql_analysis_ran=sql_meta.get("sql_analysis_ran", False),
        )

    plan_index_ops = sql_meta.get("index_ops") or {}
    if plan_index_ops and coverage:
        workload_type = bp_findings.get("workload_type") or meta.get("WORKLOAD_TYPE") or "UNKNOWN"
        plan_findings = analyze_snowvi_plan_for_ht(
            index_ops=plan_index_ops,
            coverage=coverage,
            metadata=meta,
            workload_type=workload_type,
        )
        sql_findings = list(sql_findings) + list(plan_findings or [])

    all_findings = (bp_findings.get("errors", []) or []) + (bp_findings.get("warnings", []) or [])
    finding_rules = [f.get("rule", "") for f in all_findings if f.get("rule")]
    faqs = get_all_faqs_for_findings(finding_rules)
    
    root_cause_classification = None
    if snowvi_json:
        features = extract_snowvi_features_from_json(snowvi_json)
        classification_label = classify_single_query(features)
        root_cause_classification = {
            "label": classification_label,
            "description": BATCH_QUERY_LABELS.get(classification_label, classification_label),
        }
    
    comparison_result = None
    if analysis_mode == "compare" and snowvi_json and comparison_snowvi_json:
        features_a = extract_snowvi_features_from_json(snowvi_json)
        features_b = extract_snowvi_features_from_json(comparison_snowvi_json)
        primary_cause, secondary_cause, diff = classify_run_pair(features_a, features_b)
        comparison_result = {
            "primary_cause": primary_cause,
            "primary_cause_description": ROOT_CAUSE_LABELS.get(primary_cause, primary_cause),
            "secondary_cause": secondary_cause,
            "diff": diff,
            "diff_summary": build_comparison_diff_summary(diff),
        }
    
    workload_type = bp_findings.get("workload_type") or "UNKNOWN"
    snowvi_mode = "with" if snowvi_json else "without"
    field_manual_context = get_field_manual_context(
        findings=bp_findings,
        workload_type=workload_type,
        max_tokens=1500,
        include_general=True,
        snowvi_mode=snowvi_mode,
    )
    
    finding_ids: Set[str] = set(finding_rules)
    applicable_hints = get_applicable_hints(finding_ids)
    prioritized_findings = get_prioritized_findings(finding_ids)

    ht_operator_breakdown = None
    ht_diagnostics = []
    comprehensive_summary = None
    if isinstance(snowvi_features, dict):
        ht_operator_breakdown = snowvi_features.get("ht_operator_breakdown")
        ht_diagnostics = snowvi_features.get("ht_diagnostics", [])
        
        comprehensive_summary = build_comprehensive_summary(
            snowvi_features=snowvi_features,
            bp_findings=bp_findings,
            sql_findings=sql_findings,
            metadata=meta,
        )
    
    return {
        "query_uuid": meta.get("QUERY_ID"),
        "deployment": meta.get("DEPLOYMENT"),
        "metadata": meta,
        "bp_findings": bp_findings,
        "sql_findings": sql_findings,
        "coverage": coverage,
        "history_context": history_context,
        "analysis_mode": analysis_mode,
        "comparison_uuid": comparison_uuid,
        "grade": bp_findings.get("grade"),
        "score": bp_findings.get("score"),
        "sql_analysis": sql_meta,
        "faqs": faqs,
        "root_cause_classification": root_cause_classification,
        "comparison_result": comparison_result,
        "field_manual_context": field_manual_context,
        "reasoning_hints": applicable_hints,
        "prioritized_findings": prioritized_findings,
        "ht_operator_breakdown": ht_operator_breakdown,
        "ht_diagnostics": ht_diagnostics,
        "comprehensive_summary": comprehensive_summary,
    }


def build_candidate_actions(analysis_features: Dict[str, Any]) -> List[Dict[str, Any]]:
    return build_candidate_actions_impl(
        metadata=analysis_features.get("metadata", {}),
        bp_findings=analysis_features.get("bp_findings", {}),
        sql_findings=analysis_features.get("sql_findings", []),
        coverage=analysis_features.get("coverage", []),
    )


def build_candidate_actions_impl(metadata, bp_findings, sql_findings, coverage):
    """
    Construct structured candidate actions from static analysis + coverage.
    The LLM will only be allowed to select among these - NOT invent new ones.
    """
    actions = []
    query_text = metadata.get("QUERY_TEXT", "") or ""
    query_text_upper = query_text.upper()

    has_limit = (
        " LIMIT " in query_text_upper or " FETCH " in query_text_upper or " TOP " in query_text_upper
    )
    has_order_by = " ORDER BY " in query_text_upper
    has_bound_vars = "?" in query_text or any(
        f":{p}" in query_text.lower() for p in ["1", "2", "3", "var", "param", "id", "value"]
    )
    has_where = " WHERE " in query_text_upper

    errors = bp_findings.get("errors", [])
    warnings = bp_findings.get("warnings", [])
    finding_ids = {
        (f.get("rule") or f.get("id") or "").upper()
        for f in (sql_findings or []) + errors + warnings
    }

    for cov in coverage or []:
        if not cov.get("is_hybrid"):
            continue

        table = cov.get("table") or "<unknown>"
        pred_eq_cols = cov.get("pred_eq_cols") or []
        best_eq_prefix = int(cov.get("best_eq_prefix") or 0)
        indexes = cov.get("indexes") or []

        if pred_eq_cols and best_eq_prefix == 0:
            pred_eq_str = [str(c) for c in pred_eq_cols[:3]]
            ddl_cols = ", ".join(pred_eq_str)
            idx_name_parts = [c.lower().replace('"', "") for c in pred_eq_str[:2]]
            idx_name = f"idx_{'_'.join(idx_name_parts)}"
            ddl_sql = f"CREATE INDEX {idx_name} ON {table} ({ddl_cols});"

            actions.append(
                {
                    "id": f"ADD_INDEX_{table.replace('.', '_')}_{len(actions)}",
                    "kind": "CREATE_INDEX",
                    "table": table,
                    "columns": pred_eq_str,
                    "ddl_sql": ddl_sql,
                    "preconditions": {
                        "is_hybrid": True,
                        "best_eq_prefix": best_eq_prefix,
                        "indexes_exist": bool(indexes),
                    },
                    "evidence_rules": ["NO_INDEX_FOR_HOT_PREDICATES", "PK_NOT_EARLY_IN_PREDICATES"],
                    "estimated_impact": "5–20x faster lookups on these predicates",
                    "risk_level": "MEDIUM",
                }
            )

    if has_order_by and not has_limit:
        actions.append(
            {
                "id": "ADD_LIMIT_ON_ORDER_BY",
                "kind": "QUERY_REWRITE",
                "table": None,
                "columns": [],
                "ddl_sql": "-- Add LIMIT clause to bound the sort operation, e.g.:\n"
                "-- LIMIT 1000\n"
                "-- or use FETCH FIRST 1000 ROWS ONLY",
                "preconditions": {"has_order_by": True, "has_limit": False},
                "evidence_rules": ["ORDER_BY_NO_LIMIT"],
                "estimated_impact": "Bounds sort operation; enables early termination; prevents timeout on large result sets",
                "risk_level": "LOW",
            }
        )

    if not has_bound_vars:
        actions.append(
            {
                "id": "USE_BOUND_VARIABLES",
                "kind": "QUERY_REWRITE",
                "table": None,
                "columns": [],
                "ddl_sql": "-- Replace literal values with bind parameters:\n"
                "-- WHERE col = ?  (JDBC/ODBC)\n"
                "-- WHERE col = :1  (Snowpark)",
                "preconditions": {"has_bound_vars": False},
                "evidence_rules": ["BIND_PARAMETERS", "LITERAL_PLAN_CACHE_MISS"],
                "estimated_impact": "50-90% reduction in compilation time; better plan cache reuse",
                "risk_level": "LOW",
            }
        )

    if "ANALYTIC_WORKLOAD_ON_HT" in finding_ids or bp_findings.get("workload_type") == "ANALYTIC":
        actions.append(
            {
                "id": "ROUTE_ANALYTIC_TO_STANDARD_TABLE",
                "kind": "ENGINE_CHOICE",
                "table": None,
                "columns": [],
                "ddl_sql": "-- Option 1: Create a columnar replica for analytics\n"
                "-- CREATE TABLE analytics_replica AS SELECT * FROM hybrid_table;\n\n"
                "-- Option 2: Use Iceberg tables for analytics\n"
                "-- CREATE ICEBERG TABLE analytics_data ...;",
                "preconditions": {"workload_type": "ANALYTIC"},
                "evidence_rules": ["ANALYTIC_WORKLOAD_ON_HT"],
                "estimated_impact": "More predictable latency; better scan performance for large aggregations",
                "risk_level": "MEDIUM",
            }
        )

    if "STORED_PROCEDURE_DETECTED" in finding_ids:
        actions.append(
            {
                "id": "REFACTOR_STORED_PROCEDURE",
                "kind": "ARCHITECTURE_CHANGE",
                "table": None,
                "columns": [],
                "ddl_sql": "-- Refactor stored procedure to set-based SQL:\n"
                "-- 1. Extract the procedure body\n"
                "-- 2. Replace row-by-row loops with set operations\n"
                "-- 3. Use MERGE/INSERT ... SELECT instead of cursor loops\n"
                "-- 4. Test with equivalent direct SQL first",
                "preconditions": {"is_stored_proc": True},
                "evidence_rules": ["STORED_PROCEDURE_DETECTED"],
                "estimated_impact": "10-100x faster execution; visible telemetry; better optimization",
                "risk_level": "HIGH",
            }
        )

    if "HT_REQUEST_THROTTLING" in finding_ids:
        actions.append(
            {
                "id": "MITIGATE_HT_THROTTLING",
                "kind": "WORKLOAD_MANAGEMENT",
                "table": None,
                "columns": [],
                "ddl_sql": "-- Check quota status:\n"
                "SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY\n"
                "WHERE USAGE_DATE >= DATEADD('day', -7, CURRENT_DATE());\n\n"
                "-- Rate-limit requests; implement batching with delays between batches",
                "preconditions": {"is_throttled": True},
                "evidence_rules": ["HT_REQUEST_THROTTLING"],
                "estimated_impact": "Eliminates throttle-induced latency spikes; p95/p99 stabilizes",
                "risk_level": "LOW",
            }
        )

    if "HT_PURGE_PATTERN_DETECTED" in finding_ids:
        actions.append(
            {
                "id": "BATCH_PURGE_OPERATIONS",
                "kind": "QUERY_REWRITE",
                "table": None,
                "columns": [],
                "ddl_sql": "-- Batch deletes with ROW_NUMBER() QUALIFY:\n"
                "DELETE FROM table\n"
                "WHERE ... \n"
                "QUALIFY ROW_NUMBER() OVER (ORDER BY pk_col) <= 1000;\n\n"
                "-- Add 100ms delay between batches to avoid throttling",
                "preconditions": {"is_purge_pattern": True},
                "evidence_rules": ["HT_PURGE_PATTERN_DETECTED"],
                "estimated_impact": "Prevents quota exhaustion; smoother delete throughput",
                "risk_level": "LOW",
            }
        )

    is_bulk_operation = bp_findings.get("is_bulk_operation", False)
    is_udtf_driven = bp_findings.get("is_udtf_driven", False)

    if (
        not has_where
        and ("NO_WHERE_FILTER" in finding_ids or "NO_FILTERING_CLAUSES" in finding_ids)
        and not is_bulk_operation
        and not is_udtf_driven
    ):
        actions.append(
            {
                "id": "ADD_WHERE_FILTER",
                "kind": "QUERY_REWRITE",
                "table": None,
                "columns": [],
                "ddl_sql": "-- Add selective WHERE clause on indexed/PK columns:\n"
                "-- WHERE pk_column = :value\n"
                "-- or\n"
                "-- WHERE indexed_column IN (:val1, :val2)",
                "preconditions": {"has_where": False},
                "evidence_rules": ["NO_WHERE_FILTER", "NO_FILTERING_CLAUSES"],
                "estimated_impact": "Prevents full table scan; enables index usage",
                "risk_level": "MEDIUM",
            }
        )

    return actions


def run_sql_analysis(
    metadata: Dict[str, Any],
    snowvi_json: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    from .analysis_shared_sql import run_sql_analysis as shared_run_sql_analysis

    return shared_run_sql_analysis(metadata=metadata, snowvi_json=snowvi_json)


def analyze_snowvi_plan_for_ht(
    index_ops: Dict[str, Any],
    coverage: List[Dict[str, Any]],
    metadata: Dict[str, Any],
    workload_type: str,
) -> List[Dict[str, Any]]:
    from analysis_shared import analyze_snowvi_plan_for_ht as shared_analyze_snowvi_plan_for_ht

    return shared_analyze_snowvi_plan_for_ht(
        index_ops=index_ops,
        coverage=coverage,
        metadata=metadata,
        workload_type=workload_type,
    )


def _filter_sql_findings_for_bulk(sql_findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remove findings that don't apply to bulk DML operations.
    """
    na_rules = {"NO_FILTERING_CLAUSES", "NO_WHERE_FILTER", "NO_FILTERING", "NO_BOUND_VARIABLES"}
    return [finding for finding in sql_findings if finding.get("rule", "").upper() not in na_rules]


# Shared analysis helpers live in analysis_shared.py and analysis_shared_sql.py.
