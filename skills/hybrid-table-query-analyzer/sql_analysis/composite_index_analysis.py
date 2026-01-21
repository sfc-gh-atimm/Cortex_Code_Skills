"""
Composite Index Analysis for Hybrid Tables

Detects when composite indexes (multi-column indexes/PKs) are:
1. Misaligned - none of the leading columns match equality predicates
2. Partially used - only some leading columns are used in equality predicates
3. Suggests better index shapes based on observed predicate patterns

Based on GLEAN guidance from 20251204.md lines 2842-3020
"""

from typing import List, Dict, Any, Tuple


def prefix_eq_coverage(idx_cols: List[str], pred_eq_cols: List[str]) -> int:
    """
    Calculate how many leading index columns are covered by equality predicates.
    
    For a composite index to be effective in Hybrid Tables, equality predicates
    should match the LEADING columns in order.
    
    Example:
        idx_cols = ["UNIC_ID", "CONSENT_NAME", "ORG_ID"]
        pred_eq_cols = ["UNIC_ID"]
        
        Returns: 1 (only first column matched)
    
    Args:
        idx_cols: List of column names in index order
        pred_eq_cols: List of columns used in equality predicates
    
    Returns:
        Number of leading index columns matched by equality predicates
    """
    if not idx_cols or not pred_eq_cols:
        return 0
    
    pred_set = {c.upper().strip('"') for c in pred_eq_cols}
    count = 0
    
    for col in idx_cols:
        col_norm = col.upper().strip('"')
        if col_norm in pred_set:
            count += 1
        else:
            # Stop at first non-match (prefix matching)
            break
    
    return count


def analyze_composite_indexes(coverage: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Analyze composite indexes across all tables in coverage.
    
    Detects:
    - COMPOSITE_INDEX_MISALIGNED: No leading columns match equality predicates
    - COMPOSITE_INDEX_PARTIAL_PREFIX: Only some leading columns are used
    
    Args:
        coverage: List of coverage dicts from score_indexes_for_tables
                  Each should have: table, indexes, pred_eq_cols, is_hybrid
    
    Returns:
        Tuple of (findings_list, suggested_ddl_list)
    """
    findings = []
    suggested_ddl = []
    
    for cov in coverage:
        table = cov.get("table", "<unknown>")
        pred_eq_cols = cov.get("pred_eq_cols", [])
        indexes = cov.get("indexes", [])
        is_hybrid = cov.get("is_hybrid", False)
        
        # Only analyze HT tables with equality predicates
        if not is_hybrid or not pred_eq_cols:
            continue
        
        # Track if ANY index provides good coverage
        has_good_index = False
        
        for idx_cols in indexes:
            if len(idx_cols) <= 1:
                # Simple index - skip composite analysis
                continue
            
            eq_prefix = prefix_eq_coverage(idx_cols, pred_eq_cols)
            
            # Case 1: Composite index with NO leading column match
            if eq_prefix == 0:
                findings.append({
                    "severity": "HIGH",
                    "rule": "COMPOSITE_INDEX_MISALIGNED",
                    "message": (
                        f"Hybrid Table `{table}` has composite index ({', '.join(idx_cols)}) "
                        f"but NONE of its leading columns are used in equality predicates "
                        f"{pred_eq_cols}. The optimizer cannot use this index effectively."
                    ),
                    "suggestion": (
                        "For Hybrid Tables, composite indexes are only effective when equality "
                        "predicates match the LEADING columns. Consider:\n"
                        f"1. Create a new index starting with {pred_eq_cols[0]}, or\n"
                        f"2. Reorder this composite index to start with equality predicate columns."
                    ),
                    "table": table,
                    "index_cols": idx_cols,
                    "pred_eq_cols": pred_eq_cols,
                    "prefix_matched": 0,
                })
            
            # Case 2: Partial prefix match
            elif eq_prefix < len(idx_cols):
                # Check if this at least covers ALL equality predicates
                # (even if index has more columns)
                if eq_prefix >= len(pred_eq_cols):
                    # This is actually GOOD - all predicates covered by leading prefix
                    has_good_index = True
                else:
                    # Only some predicates covered
                    findings.append({
                        "severity": "MEDIUM",
                        "rule": "COMPOSITE_INDEX_PARTIAL_PREFIX",
                        "message": (
                            f"Hybrid Table `{table}` has composite index ({', '.join(idx_cols)}) "
                            f"where only {eq_prefix} of {len(idx_cols)} leading columns match "
                            f"equality predicates {pred_eq_cols}. Index effectiveness is reduced."
                        ),
                        "suggestion": (
                            f"The index starts well but doesn't cover all equality predicates. Consider:\n"
                            f"1. Reorder the index to cover all equality columns first: {', '.join(pred_eq_cols)}, or\n"
                            f"2. Create an additional index optimized for this query pattern."
                        ),
                        "table": table,
                        "index_cols": idx_cols,
                        "pred_eq_cols": pred_eq_cols,
                        "prefix_matched": eq_prefix,
                    })
            else:
                # Full match - good coverage
                has_good_index = True
        
        # Generate suggested DDL if no good index exists
        if not has_good_index and pred_eq_cols:
            # Suggest a new index with all equality predicates
            suggested_cols = pred_eq_cols.copy()
            
            # Add first range column if present
            first_range_pos = cov.get("first_range_position")
            if first_range_pos is not None and cov.get("best_index"):
                best_idx = cov["best_index"]
                if first_range_pos < len(best_idx):
                    range_col = best_idx[first_range_pos]
                    if range_col not in suggested_cols:
                        suggested_cols.append(range_col)
            
            # Generate DDL
            table_short = table.split('.')[-1].lower()
            col_names = '_'.join(c.lower().strip('"') for c in suggested_cols[:3])
            idx_name = f"idx_{table_short}_{col_names}"
            ddl = (
                f"-- Suggested index for equality predicates {pred_eq_cols}\n"
                f"CREATE INDEX IF NOT EXISTS {idx_name}\n"
                f"  ON {table} ({', '.join(suggested_cols)});\n"
            )
            suggested_ddl.append(ddl)
    
    return findings, suggested_ddl


def summarize_composite_index_issues(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate a summary of composite index issues for reporting.
    
    Args:
        findings: List of composite index findings
    
    Returns:
        Summary dict with counts and affected tables
    """
    misaligned = [f for f in findings if f.get("rule") == "COMPOSITE_INDEX_MISALIGNED"]
    partial = [f for f in findings if f.get("rule") == "COMPOSITE_INDEX_PARTIAL_PREFIX"]
    
    affected_tables = {f.get("table") for f in findings}
    
    return {
        "total_issues": len(findings),
        "misaligned_count": len(misaligned),
        "partial_prefix_count": len(partial),
        "affected_tables": list(affected_tables),
        "severity": "HIGH" if misaligned else ("MEDIUM" if partial else "LOW"),
    }

