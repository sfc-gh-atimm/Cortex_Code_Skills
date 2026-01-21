from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .analysis_shared import infer_runtime_index_usage

SQL_ANALYSIS_AVAILABLE = False
try:
    from sql_analysis import analyze_query, parse_sql, score_indexes_for_tables
    from sql_analysis.rules_stored_proc import is_stored_proc_call

    SQL_ANALYSIS_AVAILABLE = True
except Exception:
    SQL_ANALYSIS_AVAILABLE = False

SNOWVI_PARSER_AVAILABLE = False
try:
    from .snowvi_parser import (
        enrich_coverage_with_snowvi_index_metadata,
        extract_ht_index_metadata_from_snowvi_json,
        extract_ht_index_operators_from_snowvi_json,
    )
    from sqlglot import expressions as exp

    SNOWVI_PARSER_AVAILABLE = True
except Exception:
    SNOWVI_PARSER_AVAILABLE = False


def run_sql_analysis(
    metadata: Dict[str, Any],
    snowvi_json: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Run SQL static analysis and coverage scoring using sql_analysis package.
    """
    sql_findings: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []
    sql_meta = {
        "sql_analysis_ran": False,
        "has_ctes": False,
        "is_stored_proc": False,
        "is_bulk_operation": False,
        "runtime_index_usage": {},
        "index_ops": {},
        "skipped_reason": None,
    }

    if not SQL_ANALYSIS_AVAILABLE:
        sql_meta["skipped_reason"] = "SQL analysis module unavailable"
        return sql_findings, coverage, sql_meta

    query_text = metadata.get("QUERY_TEXT", "") or ""
    if not query_text:
        sql_meta["skipped_reason"] = "No QUERY_TEXT in metadata"
        return sql_findings, coverage, sql_meta

    parsed = parse_sql(query_text)

    sql_meta["is_stored_proc"] = is_stored_proc_call(query_text)
    skip_sql_analysis = sql_meta["is_stored_proc"] and len(parsed.tables) == 0
    if skip_sql_analysis:
        sql_meta["sql_analysis_ran"] = True
        sql_meta["skipped_reason"] = "Stored procedure call detected"
        return sql_findings, coverage, sql_meta

    table_meta: Dict[str, Dict[str, Any]] = {}
    for table_name in parsed.tables:
        table_meta[table_name] = {
            "is_hybrid": False,
            "pk": [],
            "indexes": [],
            "columns": {},
        }

    index_meta = {}
    index_ops = {}
    if SNOWVI_PARSER_AVAILABLE and snowvi_json:
        index_meta = extract_ht_index_metadata_from_snowvi_json(snowvi_json)
        index_ops = extract_ht_index_operators_from_snowvi_json(snowvi_json)

        for table_name in parsed.tables:
            norm_name = table_name.upper().replace('"', "")
            short_name = norm_name.split(".")[-1]
            snowvi_meta = index_meta.get(norm_name) or index_meta.get(short_name)
            if not snowvi_meta:
                continue

            table_meta[table_name]["is_hybrid"] = True
            col_mapping = snowvi_meta.get("column_id_to_name", {})

            pk_names = []
            for col_id in snowvi_meta.get("primaryKeyColumns", []) or []:
                col_name = col_mapping.get(col_id)
                if col_name:
                    pk_names.append(col_name)
            table_meta[table_name]["pk"] = pk_names

            idx_names = []
            for idx_def in snowvi_meta.get("kvSecondaryIndices", []) or []:
                if isinstance(idx_def, dict):
                    cols = []
                    for col_id in idx_def.get("indexColumns", []) or []:
                        col_name = col_mapping.get(col_id)
                        if col_name:
                            cols.append(col_name)
                    if cols:
                        idx_names.append(cols)
            table_meta[table_name]["indexes"] = idx_names

            if short_name not in table_meta:
                table_meta[short_name] = table_meta[table_name].copy()
    else:
        if metadata.get("ACCESS_KV_TABLE"):
            for table_name in parsed.tables:
                table_meta[table_name]["is_hybrid"] = True

                norm_name = table_name.upper().replace('"', "")
                short_name = norm_name.split(".")[-1]
                if short_name not in table_meta:
                    table_meta[short_name] = table_meta[table_name].copy()

    sql_upper = query_text.upper().strip()
    is_insert_select = sql_upper.startswith("INSERT") and "SELECT" in sql_upper and "VALUES" not in sql_upper
    qtype = (metadata.get("QUERY_TYPE") or "").upper()
    sql_meta["is_bulk_operation"] = qtype in (
        "INSERT",
        "MERGE",
        "COPY",
        "UPDATE",
        "CREATE_TABLE_AS_SELECT",
        "CTAS",
    ) or is_insert_select

    coverage_raw = score_indexes_for_tables(parsed, table_meta)

    seen_tables = {}
    deduped_coverage = []
    for cov in coverage_raw:
        table_name = cov["table"]
        norm_name = table_name.upper().replace('"', "").split(".")[-1]
        if norm_name not in seen_tables:
            seen_tables[norm_name] = cov
            deduped_coverage.append(cov)
        else:
            existing = seen_tables[norm_name]
            if len(table_name) > len(existing["table"]):
                deduped_coverage.remove(existing)
                deduped_coverage.append(cov)
                seen_tables[norm_name] = cov

    coverage = deduped_coverage

    if SNOWVI_PARSER_AVAILABLE:
        cte_names = set()
        for with_node in parsed.ast.find_all(exp.With):
            for cte in with_node.expressions:
                if hasattr(cte, "alias"):
                    cte_names.add(str(cte.alias).strip('"').upper())
                elif hasattr(cte, "this") and hasattr(cte.this, "alias"):
                    cte_names.add(str(cte.this.alias).strip('"').upper())

        if cte_names:
            sql_meta["has_ctes"] = True
            coverage = [
                cov for cov in coverage
                if cov["table"].split(".")[-1].strip('"').upper() not in cte_names
            ]

    sql_findings = analyze_query(parsed, table_meta, coverage)
    sql_meta["sql_analysis_ran"] = True

    if SNOWVI_PARSER_AVAILABLE and index_meta:
        coverage = enrich_coverage_with_snowvi_index_metadata(
            coverage, index_meta, index_ops
        )
        sql_meta["index_ops"] = {
            key: {"index_ops": value.get("index_ops", [])}
            for key, value in (index_ops or {}).items()
        }

    sql_meta["runtime_index_usage"] = infer_runtime_index_usage(metadata, coverage)

    if metadata.get("ACCESS_KV_TABLE"):
        for cov in coverage:
            if not cov.get("is_hybrid"):
                continue

            pk_cols = cov.get("pk", [])
            if not pk_cols:
                continue

            pred_eq_cols = cov.get("pred_eq_cols", [])
            if not pred_eq_cols:
                sql_findings.append(
                    {
                        "severity": "MEDIUM",
                        "rule": "PRIMARY_KEY_NOT_USED",
                        "message": (
                            f"Table `{cov['table']}` has PRIMARY KEY {pk_cols} but query uses no "
                            "equality predicates. HT is optimized for PK-based row access."
                        ),
                        "suggestion": (
                            "Add WHERE clause with PK equality predicate for point lookups, or "
                            "move analytic workloads to standard tables/MVs."
                        ),
                    }
                )
                continue

            pk_upper = {c.upper().strip('"') for c in pk_cols}
            pred_upper = {c.upper().strip('"') for c in pred_eq_cols}

            if not (pk_upper & pred_upper):
                bytes_per_row = cov.get("bytes_scanned", 0) / max(cov.get("rows_produced", 1), 1)
                severity = "MEDIUM" if (cov.get("rows_produced", 0) > 10000 or bytes_per_row > 1000) else "INFO"
                sql_findings.append(
                    {
                        "severity": severity,
                        "rule": "PRIMARY_KEY_NOT_USED",
                        "message": (
                            f"Table `{cov['table']}` has PRIMARY KEY {pk_cols} but query predicates use "
                            f"{pred_eq_cols} instead. HT is optimized for PK-based lookups."
                        ),
                        "suggestion": (
                            "Add PK-based predicates for point lookups, or route analytic workloads "
                            "to standard tables/MVs."
                        ),
                    }
                )

    if sql_meta["is_bulk_operation"] and sql_findings:
        sql_findings = _filter_sql_findings_for_bulk(sql_findings)

    return sql_findings, coverage, sql_meta


def _filter_sql_findings_for_bulk(sql_findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    na_rules = {"NO_FILTERING_CLAUSES", "NO_WHERE_FILTER", "NO_FILTERING", "NO_BOUND_VARIABLES"}
    return [finding for finding in sql_findings if finding.get("rule", "").upper() not in na_rules]
