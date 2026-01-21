"""
Enhanced SQL Analysis Rules based on GLEAN feedback (2024-12-03)

Improvements:
1. Separate "No Index Coverage" from "Non-Sargable" predicates
2. Conditional ORDER BY+LIMIT warnings (only for large result sets)
3. Generate specific index DDL recommendations
4. Smart primary cause ranking based on runtime metrics
"""

from typing import Dict, List, Tuple, Optional
import re
from sqlglot import expressions as exp
from .parser import ParsedQuery


def generate_index_ddl(
    table: str,
    pred_eq_cols: List[str],
    first_range_col: Optional[str],
    select_cols: List[str],
    rows_produced: int,
    include_clause: bool = True
) -> str:
    """
    Generate CREATE INDEX DDL with proper column ordering.
    
    Best practices:
    - Equality columns first (most selective first is ideal, but we use appearance order)
    - Range column after equalities
    - INCLUDE clause for projection columns when:
      - Result set is small-medium (hundreds to low thousands)
      - Many columns projected that aren't in key
    
    Args:
        table: Fully qualified table name
        pred_eq_cols: List of equality predicate columns in order
        first_range_col: First range predicate column (or None)
        select_cols: List of projected columns from SELECT
        rows_produced: Number of rows returned (from runtime metrics)
        include_clause: Whether to consider INCLUDE clause
    
    Returns:
        CREATE INDEX statement
    
    Reference: GLEAN 2024-12-03, section 3.3
    """
    if not pred_eq_cols:
        return ""
    
    # Build key columns: equalities first, then range
    key_cols = pred_eq_cols.copy()
    if first_range_col and first_range_col not in key_cols:
        key_cols.append(first_range_col)
    
    # Generate index name
    # Format: idx_<table_name>_<col1>_<col2>...
    table_parts = table.split('.')
    table_name = table_parts[-1].strip('"').lower()
    col_suffix = "_".join(c.strip('"').lower()[:12] for c in key_cols[:3])  # First 3 cols, truncated
    index_name = f"idx_{table_name}_{col_suffix}"[:63]  # Snowflake identifier limit
    
    # Build basic CREATE INDEX
    key_list = ", ".join(f'"{c}"' if not c.startswith('"') else c for c in key_cols)
    ddl = f"CREATE INDEX {index_name}\nON {table} ({key_list})"
    
    # Add INCLUDE clause if appropriate
    if include_clause and rows_produced is not None and rows_produced < 5000:  # Small-medium result sets benefit from INCLUDE
        # Find columns that are projected but not in key
        key_set = {c.strip('"').lower() for c in key_cols}
        include_cols = []
        
        for col in select_cols:
            # Skip *, functions, and columns already in key
            if col.strip() == '*':
                continue
            if '(' in col or ')' in col:  # Skip function calls
                continue
            
            col_name = col.split('.')[-1].strip('"').lower()
            if col_name not in key_set:
                include_cols.append(col)
        
        if include_cols and len(include_cols) <= 10:  # Don't make INCLUDE too wide
            include_list = ", ".join(f'"{c}"' if not c.startswith('"') else c for c in include_cols[:10])
            ddl += f"\nINCLUDE ({include_list})"
    
    ddl += ";"
    
    return ddl


def check_no_index_coverage(
    coverage: List[dict],
    access_kv_table: bool,
    cte_names: set = None
) -> List[dict]:
    """
    Rule: NO_INDEX_COVERAGE_ON_PREDICATES
    
    Separate from non-sargable predicates. This flags when:
    - Query accesses HT (ACCESS_KV_TABLE = true)
    - Indexes exist OR could exist
    - Predicates don't align with leftmost index columns
    
    This is different from non-sargable, which is about functions in predicates.
    
    Reference: GLEAN 2024-12-03, section 3.1
    """
    findings = []
    
    if not access_kv_table:
        return findings
    
    if cte_names is None:
        cte_names = set()
    
    # If ACCESS_KV_TABLE = true, analyze ALL tables in the query
    # Runtime metrics trump schema metadata for HT detection
    for entry in coverage:
        table = entry["table"]
        
        # Skip CTEs - they're not real tables
        table_name_upper = table.split('.')[-1].strip('"').upper()
        if table_name_upper in cte_names:
            continue
        
        # Trust runtime: if query touched KV table, analyze all tables
        is_hybrid = entry.get("is_hybrid", False) or access_kv_table
        
        if not is_hybrid:
            continue
        
        best_eq_prefix = entry.get("best_eq_prefix", 0)
        pred_eq_cols = entry.get("pred_eq_cols", [])
        indexes = entry.get("indexes", [])
        
        # PATCH 3: Check index metadata source
        # If source is "unknown", we can't claim there are no indexes
        index_source = entry.get("index_metadata_source", "unknown")
        
        # Case 1: No indexes at all + predicates exist = need to create index
        # BUT: Only fire if we have confirmed index metadata
        if not indexes and pred_eq_cols:
            if index_source == "unknown":
                # Can't recommend indexes when we don't know if they exist
                # Add INFO-level finding instead of HIGH
                findings.append({
                    "severity": "INFO",
                    "rule": "INDEX_METADATA_UNKNOWN",
                    "message": (
                        f"HT table '{table}': Query filters/joins on columns [{', '.join(pred_eq_cols[:5])}] "
                        "but index metadata was not available in SnowVI export. "
                        "Cannot determine if indexes exist."
                    ),
                    "suggestion": (
                        "Check actual table DDL with SHOW INDEXES or DESC TABLE to see if indexes exist. "
                        "If no indexes, consider creating one on the predicate columns."
                    ),
                    "table": table,
                    "pred_eq_cols": pred_eq_cols,
                    "has_indexes": None  # Unknown
                })
            else:
                # Confirmed: SnowVI says no indexes
                col_list = ', '.join(pred_eq_cols[:5])  # Top 5 columns
                findings.append({
                    "severity": "HIGH",
                    "rule": "NO_INDEX_COVERAGE_ON_PREDICATES",
                    "message": (
                        f"HT table '{table}': Zero indexes but query filters/joins on columns: [{col_list}]. "
                        "Without index support, every access scans the KV store row-by-row."
                    ),
                    "suggestion": (
                        f"CREATE INDEX idx_{table.split('.')[-1].lower()}_optimized ON {table} ({col_list}); "
                        "Order columns by selectivity (most selective first). This typically provides 5-50x speedup."
                    ),
                    "table": table,
                    "pred_eq_cols": pred_eq_cols,
                    "has_indexes": False
                })
        
        # Case 2: Indexes exist but predicates don't align
        elif indexes and best_eq_prefix == 0 and pred_eq_cols:
            existing_keys = [idx[0] if idx else "?" for idx in indexes]
            findings.append({
                "severity": "HIGH",
                "rule": "NO_INDEX_COVERAGE_ON_PREDICATES",
                "message": f"HT table '{table}': Equality predicates on {pred_eq_cols} don't align with leftmost columns of existing indexes (which start with {existing_keys}). Query will do full scan or expensive probe.",
                "suggestion": f"Create new index OR reorder existing index to start with: {pred_eq_cols}. Put most selective column first.",
                "table": table,
                "pred_eq_cols": pred_eq_cols,
                "has_indexes": True,
                "existing_index_starts": existing_keys
            })
    
    return findings


def check_order_by_limit_conditional(
    pq: ParsedQuery,
    rows_produced: Optional[int],
    coverage: List[dict],
    access_kv_table: bool
) -> Optional[dict]:
    """
    Rule: ORDER_BY_NO_LIMIT (conditional on result set size)
    
    Only flag ORDER BY without LIMIT when:
    - rows_produced > 10,000 (large result set)
    - AND either:
      - It's an HT query with ORDER BY on indexed key, OR
      - Evidence of large sort (can't detect from static analysis alone)
    
    For small result sets (like 7 rows), this is not a problem.
    
    Reference: GLEAN 2024-12-03, section 3.2
    """
    if not pq.order_by or pq.limit is not None:
        return None
    
    # If we don't have runtime metrics, use conservative threshold
    if rows_produced is None:
        # Without runtime info, only flag if it's clearly a problem
        # (we can't know for sure, so be conservative)
        return None
    
    # Small result set - ORDER BY without LIMIT is fine
    if rows_produced <= 10000:
        return None
    
    # Large result set - check if this is an HT query with indexed ORDER BY
    order_cols = [c for c, _ in pq.order_by]
    order_str = ", ".join(order_cols)
    
    # Check if ORDER BY is on an indexed column for HT
    if access_kv_table:
        for entry in coverage:
            if entry.get("is_hybrid") and entry.get("order_by_prefix", 0) > 0:
                # ORDER BY aligns with index - top-K optimization possible
                return {
                    "severity": "HIGH",
                    "rule": "ORDER_BY_NO_LIMIT",
                    "message": f"ORDER BY [{order_str}] on HT index without LIMIT will sort {rows_produced:,} rows. Top-K optimization is possible but not enabled.",
                    "suggestion": "Add LIMIT to enable top-K index optimization. For HT, ORDER BY on PK/index + LIMIT allows early termination.",
                    "rows_produced": rows_produced
                }
    
    # General case: large result set with ORDER BY, no LIMIT
    return {
        "severity": "MEDIUM",
        "rule": "ORDER_BY_NO_LIMIT",
        "message": f"ORDER BY [{order_str}] without LIMIT will sort {rows_produced:,} rows.",
        "suggestion": "Add LIMIT to reduce sort cost, or use seek pagination on indexed columns.",
        "rows_produced": rows_produced
    }


def check_mixed_ht_standard_tables(
    coverage: List[dict],
    cte_names: set = None
) -> Optional[dict]:
    """
    Rule: MIXED_HT_AND_STANDARD_TABLES
    
    Detect when a query mixes Hybrid Tables with standard tables.
    This is important because:
    - Overall latency is dominated by standard table scans
    - HT benefits are limited to point-lookup portions only
    - Warehouse scaling behaves like standard tables, not HT
    
    Reference: GLEAN 2026-01-07 conversation
    """
    if not coverage:
        return None
    
    if cte_names is None:
        cte_names = set()
    
    # Separate HT from standard tables (excluding CTEs)
    ht_tables = []
    std_tables = []
    
    for cov in coverage:
        table_name = cov.get('table', '')
        short_name = table_name.split('.')[-1].strip('"').upper()
        
        # Skip CTEs
        if short_name in cte_names:
            continue
        
        if cov.get('is_hybrid'):
            ht_tables.append(table_name)
        else:
            std_tables.append(table_name)
    
    # Only flag if there's a mix
    if ht_tables and std_tables:
        return {
            "severity": "MEDIUM",
            "rule": "MIXED_HT_AND_STANDARD_TABLES",
            "message": (
                f"Query mixes {len(ht_tables)} Hybrid Table(s) with {len(std_tables)} standard table(s). "
                "Overall latency will be dominated by standard table scans, not HT point lookups."
            ),
            "suggestion": (
                "Treat this as a standard analytical query for performance expectations. "
                "Scale warehouse for standard table scans. HT benefits are limited to indexed point-lookup "
                "portions of the query. Consider migrating frequently-joined standard tables to HT, or "
                "splitting the workload into HT-only OLTP and standard analytics."
            ),
            "ht_tables": ht_tables,
            "std_tables": std_tables
        }
    
    return None


def rank_primary_cause(
    findings: List[dict],
    runtime_metrics: Optional[Dict] = None
) -> Optional[dict]:
    """
    Rank findings to identify PRIMARY CAUSE of performance issues.
    
    Uses a scoring system based on:
    - SQL finding severity (HIGH > MEDIUM > LOW)
    - Runtime metrics weight:
      - Zero index coverage on HT query: +50 points
      - Remote spill: +40 points
      - High throttling with tiny result set: +30 points
      - Huge scan vs filtered rows ratio: +20 points
    
    Returns the top-scored finding with explanation.
    
    Reference: GLEAN 2024-12-03, section 3.4
    """
    if not findings:
        return None
    
    if not runtime_metrics:
        # Without runtime metrics, just return highest severity finding
        severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
        sorted_findings = sorted(findings, key=lambda f: severity_order.get(f.get("severity", "INFO"), 0), reverse=True)
        return sorted_findings[0] if sorted_findings else None
    
    # Score each finding
    scored_findings = []
    
    for finding in findings:
        score = 0
        
        # Base score from severity
        severity = finding.get("severity", "LOW")
        if severity == "HIGH":
            score += 30
        elif severity == "MEDIUM":
            score += 15
        elif severity == "LOW":
            score += 5
        
        rule = finding.get("rule", "")
        
        # Runtime metric weights (ensure None values become 0 for comparisons)
        access_kv_table = runtime_metrics.get("ACCESS_KV_TABLE", False)
        rows_produced = runtime_metrics.get("ROWS_PRODUCED") or 0
        bytes_scanned = runtime_metrics.get("BYTES_SCANNED") or 0
        spill_remote = runtime_metrics.get("SPILL_REMOTE_BYTES") or 0
        spill_local = runtime_metrics.get("SPILL_LOCAL_BYTES") or 0
        fdb_throttling_ms = runtime_metrics.get("FDB_THROTTLING_MS") or 0
        
        # HT without indexes = CATASTROPHIC (architectural problem)
        if "HT_WITHOUT_INDEXES" in rule:
            score += 100  # Highest priority - you're paying for HT with ZERO benefit
        
        # HT indexes not used = CRITICAL (misconfigured queries)
        if "HT_INDEXES_NOT_USED" in rule:
            score += 60  # Very high - indexes exist but wasted
        
        # Zero index coverage on HT = CRITICAL
        if access_kv_table and "NO_INDEX_COVERAGE" in rule:
            score += 50
        
        # Remote spill = CRITICAL
        if spill_remote > 0:
            score += 40
        
        # Local spill = HIGH
        if spill_local > 0:
            score += 20
        
        # High throttling with tiny result set = indicates inefficient access pattern
        if fdb_throttling_ms > 5000 and rows_produced < 100:
            score += 30
        
        # Huge scan with small result = inefficient filtering
        if bytes_scanned > 1_000_000_000 and rows_produced < 1000:
            scan_to_row_ratio = bytes_scanned / max(rows_produced, 1)
            if scan_to_row_ratio > 1_000_000:  # >1MB per row
                score += 20
        
        # ORDER BY without LIMIT on large result
        if "ORDER_BY_NO_LIMIT" in rule and rows_produced > 100000:
            score += 15
        
        scored_findings.append((score, finding))
    
    # Sort by score descending
    scored_findings.sort(key=lambda x: x[0], reverse=True)
    
    if scored_findings:
        top_score, top_finding = scored_findings[0]
        
        # Add explanation of why this is primary cause
        explanation_parts = [top_finding.get("message", "")]
        
        # Add runtime context
        if access_kv_table and "NO_INDEX_COVERAGE" in top_finding.get("rule", ""):
            explanation_parts.append("🔴 PRIMARY CAUSE: Zero index coverage on Hybrid Table query forces full table scan or expensive probes.")
        elif spill_remote > 0:
            explanation_parts.append(f"🔴 PRIMARY CAUSE: Remote spill detected ({spill_remote / (1024**3):.2f} GB). Query exceeds warehouse memory.")
        elif fdb_throttling_ms > 5000 and rows_produced < 100:
            explanation_parts.append(f"🔴 PRIMARY CAUSE: High FDB throttling ({fdb_throttling_ms}ms) with tiny result set indicates inefficient access pattern.")
        
        top_finding["primary_cause_explanation"] = " ".join(explanation_parts)
        top_finding["primary_cause_score"] = top_score
        
        return top_finding
    
    return None


def _extract_cte_names(pq: ParsedQuery) -> set:
    """
    Extract CTE (Common Table Expression) names from the parsed query.
    CTEs cannot have indexes, so we should exclude them from DDL generation.
    """
    cte_names = set()
    
    # Find all WITH clauses
    for with_node in pq.ast.find_all(exp.With):
        for cte in with_node.expressions:
            if hasattr(cte, 'alias'):
                cte_names.add(str(cte.alias).strip('"').upper())
            elif hasattr(cte, 'this') and hasattr(cte.this, 'alias'):
                cte_names.add(str(cte.this.alias).strip('"').upper())
    
    return cte_names


def analyze_query_enhanced(
    pq: ParsedQuery,
    meta: Dict[str, dict],
    coverage: List[dict],
    runtime_metrics: Optional[Dict] = None
) -> Tuple[List[dict], Optional[dict], List[str]]:
    """
    Enhanced query analysis incorporating GLEAN recommendations.
    
    Returns:
        - findings: List of all findings
        - primary_cause: Top-ranked finding (or None)
        - index_ddl: List of CREATE INDEX recommendations
    
    This should be called AFTER the standard analyze_query() to augment findings.
    """
    findings = []
    index_ddl_statements = []
    
    # Extract runtime metrics (ensure safe defaults for comparisons)
    access_kv_table = runtime_metrics.get("ACCESS_KV_TABLE", False) if runtime_metrics else False
    rows_produced_raw = runtime_metrics.get("ROWS_PRODUCED") if runtime_metrics else None
    rows_produced = rows_produced_raw if rows_produced_raw is not None else 0
    
    # Extract CTE names to exclude from index recommendations
    cte_names = _extract_cte_names(pq)
    
    # 0. CRITICAL: Detect schema/runtime mismatch (HT without proper index usage)
    # If runtime says HT but schema says NOT HT = indexes missing or not used
    if access_kv_table:
        for entry in coverage:
            if not entry.get("is_hybrid"):
                # Runtime detected HT access, but schema says it's not HT
                # This means either no indexes exist OR they're not being used
                table = entry["table"]
                
                # Skip CTEs - they're not real tables
                table_name_upper = table.split('.')[-1].strip('"').upper()
                if table_name_upper in cte_names:
                    continue
                
                indexes = entry.get("indexes", [])
                pred_eq_cols = entry.get("pred_eq_cols", [])
                index_source = entry.get("index_metadata_source", "unknown")
                
                if not indexes:
                    # PATCH 3: Only claim "no indexes" if we have confirmed metadata
                    if index_source == "unknown":
                        # Can't claim no indexes when metadata is unknown
                        findings.append({
                            "severity": "INFO",
                            "rule": "HT_INDEX_METADATA_UNKNOWN",
                            "message": (
                                f"Table '{table}' accessed as Hybrid Table but index metadata was not available. "
                                "Cannot determine if indexes exist or are being used."
                            ),
                            "suggestion": "Check actual table DDL with SHOW INDEXES or DESC TABLE.",
                            "table": table,
                            "pred_eq_cols": pred_eq_cols
                        })
                    else:
                        # Case A: Confirmed - Hybrid Table with NO indexes
                        # GLEAN 2026-01-07: Include join columns in the message
                        if pred_eq_cols:
                            join_info = f"Join/filter columns ({', '.join(pred_eq_cols)}) are scanning KV store instead of using indexed lookups."
                            suggestion = f"Create indexes immediately on: {', '.join(pred_eq_cols)}. Put most selective column first."
                        else:
                            join_info = "All joins and filters are scanning the KV store without index support."
                            suggestion = "Analyze WHERE/JOIN columns and create indexes on equality predicates. Without indexes, HT queries are SLOWER than standard tables."
                        
                        findings.append({
                            "severity": "HIGH",
                            "rule": "HT_WITHOUT_INDEXES",
                            "message": f"CRITICAL: Table '{table}' is a Hybrid Table but has NO secondary indexes. {join_info}",
                            "suggestion": suggestion,
                            "table": table,
                            "pred_eq_cols": pred_eq_cols,
                            "estimated_improvement": "5-10x faster with proper indexes"
                        })
                else:
                    # Case B: Indexes exist but NOT being used (mismatch)
                    findings.append({
                        "severity": "HIGH",
                        "rule": "HT_INDEXES_NOT_USED",
                        "message": f"WARNING: Table '{table}' has indexes but query is not using them effectively. Runtime shows full table scan despite indexes existing.",
                        "suggestion": f"Review query predicates. Ensure WHERE clause columns match index leftmost columns. Current predicates: {pred_eq_cols if pred_eq_cols else 'none detected'}. Existing indexes: {[idx[0] if idx else '?' for idx in indexes[:3]]}.",
                        "table": table,
                        "indexes": indexes,
                        "estimated_improvement": "3-5x faster with proper predicate alignment"
                    })
    
    # 1. Check for no index coverage (separate from non-sargable)
    no_coverage_findings = check_no_index_coverage(coverage, access_kv_table, cte_names)
    findings.extend(no_coverage_findings)
    
    # 1.25. GLEAN 2026-01-07: Summary-level message when multiple HT tables have no indexes
    # "All HT tables in this query have zero secondary indexes"
    ht_tables_no_indexes = [
        f["table"] for f in findings 
        if f.get("rule") == "HT_WITHOUT_INDEXES" or (f.get("rule") == "NO_INDEX_COVERAGE_ON_PREDICATES" and not f.get("has_indexes"))
    ]
    if len(ht_tables_no_indexes) >= 2:
        # Collect all predicate columns across these tables
        all_pred_cols = set()
        for f in findings:
            if f.get("table") in ht_tables_no_indexes and f.get("pred_eq_cols"):
                all_pred_cols.update(f["pred_eq_cols"])
        
        # Only add summary if we haven't already (avoid duplicates)
        if not any(f.get("rule") == "MULTIPLE_HT_TABLES_NO_INDEXES" for f in findings):
            findings.insert(0, {
                "severity": "HIGH",
                "rule": "MULTIPLE_HT_TABLES_NO_INDEXES",
                "message": (
                    f"ALL {len(ht_tables_no_indexes)} Hybrid Tables in this query have ZERO secondary indexes. "
                    f"Tables: {', '.join(ht_tables_no_indexes)}. "
                    f"Join/filter columns ({', '.join(sorted(all_pred_cols)[:8])}) are scanning KV store row-by-row."
                ),
                "suggestion": (
                    "Create indexes on each HT table for the columns used in joins and filters. "
                    "This is a systemic issue - the application is treating HT as standard tables without leveraging indexed lookups."
                ),
                "ht_tables": ht_tables_no_indexes,
                "all_pred_cols": list(all_pred_cols)
            })
    
    # 1.5. Check for mixed HT + standard tables (important for performance expectations)
    mixed_finding = check_mixed_ht_standard_tables(coverage, cte_names)
    if mixed_finding:
        findings.append(mixed_finding)
    
    # 2. Conditional ORDER BY+LIMIT check (pass raw value for proper None handling)
    order_finding = check_order_by_limit_conditional(pq, rows_produced_raw, coverage, access_kv_table)
    if order_finding:
        findings.append(order_finding)
    
    # 3. Generate index DDL for each table with coverage issues
    # If ACCESS_KV_TABLE = true, analyze ALL tables (runtime metrics trump schema metadata)
    # Deduplicate by table name to avoid multiple recommendations for the same table
    seen_tables = set()
    
    for entry in coverage:
        # Trust runtime metrics over schema metadata for HT detection
        is_ht = entry.get("is_hybrid") or access_kv_table
        
        if not is_ht:
            continue
        
        table = entry["table"]
        
        # Skip CTEs - they can't have indexes created on them
        table_name_upper = table.split('.')[-1].strip('"').upper()
        if table_name_upper in cte_names:
            continue  # This is a CTE, not a real table
        
        # Skip if we already generated DDL for this table
        if table in seen_tables:
            continue
        
        pred_eq_cols = entry.get("pred_eq_cols", [])
        best_eq_prefix = entry.get("best_eq_prefix", 0)
        first_range_pos = entry.get("first_range_position")
        
        # Only generate DDL if we have predicates and poor coverage
        if pred_eq_cols and best_eq_prefix < len(pred_eq_cols):
            # Get first range column if present
            first_range_col = None
            if first_range_pos is not None and entry.get("best_index"):
                best_idx = entry["best_index"]
                if first_range_pos < len(best_idx):
                    first_range_col = best_idx[first_range_pos]
            
            # Generate DDL
            ddl = generate_index_ddl(
                table=table,
                pred_eq_cols=pred_eq_cols,
                first_range_col=first_range_col,
                select_cols=pq.select_cols,
                rows_produced=rows_produced or 0,
                include_clause=True
            )
            
            if ddl:
                index_ddl_statements.append(ddl)
                seen_tables.add(table)  # Mark table as processed
    
    # 4. Rank primary cause
    all_findings_for_ranking = findings.copy()
    primary_cause = rank_primary_cause(all_findings_for_ranking, runtime_metrics)
    
    return findings, primary_cause, index_ddl_statements

