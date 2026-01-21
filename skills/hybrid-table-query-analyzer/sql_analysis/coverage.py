"""
Index coverage scoring for Hybrid Tables
Based on Glean's blueprint (lines 514-596)
Enhanced with PK coverage checks (Glean lines 140-162)
"""

from typing import Dict, List, Tuple, Optional
from .parser import ParsedQuery

def _normalize_predicates(preds: List[dict]) -> Dict[str, str]:
    """
    Normalize predicates to map column -> operation type ('EQ' or 'RANGE')
    
    Args:
        preds: List of predicate dicts from ParsedQuery
        
    Returns:
        Dict mapping column name to operation type
    """
    col_ops: Dict[str, str] = {}
    for p in preds:
        op = (p.get("op") or "").upper()
        left = p.get("left", "")
        
        if not left:
            continue
        
        # Extract column name (handle table.column format)
        col = left.split(".")[-1].strip('"')
        
        # Categorize operation
        if op in ("EQ", "EQUAL"):
            col_ops[col] = "EQ"
        elif op in ("GT", "LT", "GTE", "LTE", "BETWEEN", "LIKE", "IN", "NEQ", "NOT_EQ"):
            col_ops[col] = "RANGE"
    
    return col_ops

def _eq_prefix_for_index(pred_ops: Dict[str, str], index_cols: List[str]) -> Tuple[int, Optional[int]]:
    """
    Count leading equality predicates on index columns.
    
    Returns:
        (eq_prefix, first_range_position)
        - eq_prefix: Number of leading columns with equality predicates
        - first_range_position: Position of first range predicate (or None)
    
    Glean lines 217-233
    """
    eq = 0
    first_range = None
    
    for i, col in enumerate(index_cols or []):
        # Try both quoted and unquoted column names
        op = pred_ops.get(col) or pred_ops.get(col.strip('"'))
        
        if op == "EQ":
            eq += 1
            continue
        elif op == "RANGE":
            first_range = i
            break
        else:
            # No predicate on this column - stop counting
            break
    
    return eq, first_range

def score_indexes_for_tables(pq: ParsedQuery, meta: Dict[str, dict]) -> List[dict]:
    """
    Compute index coverage scores for each table.
    
    For each table, calculates:
      - pk_eq_prefix: Leading equality coverage on PRIMARY KEY (Glean lines 142-162, 256)
      - best_eq_prefix: Number of leading index columns matched by equality predicates
      - first_range_position: Position of first range predicate in best index
      - order_by_prefix: Number of leading columns matched by ORDER BY
    
    This scoring helps identify:
      - Whether PK is being used effectively for HT point lookups
      - Which indexes are being used effectively
      - Where new indexes should be created
      - How to reorder index columns for better performance
    
    Args:
        pq: ParsedQuery object
        meta: Metadata dict from SnowflakeMetadata or LocalMetadata
        
    Returns:
        List of coverage analysis dicts, one per table
    """
    order_cols = [c for c, _ in pq.order_by]
    pred_ops = _normalize_predicates(pq.predicates)
    coverage_rows: List[dict] = []

    for table, info in meta.items():
        pk = info.get("pk", []) or []
        
        # Collect all indexes (PK + secondary)
        indexes: List[List[str]] = []
        if pk:
            indexes.append(pk)
        indexes += info.get("indexes", [])

        # Calculate PK equality prefix
        pk_eq_prefix, _ = _eq_prefix_for_index(pred_ops, pk)

        # Score each index to find best match
        best_eq_prefix = -1
        best_idx = None
        best_first_range = None

        for idx in indexes:
            eq_prefix, first_range = _eq_prefix_for_index(pred_ops, idx)
            
            # Track best index
            if eq_prefix > best_eq_prefix:
                best_eq_prefix = eq_prefix
                best_idx = idx
                best_first_range = first_range

        # Calculate ORDER BY alignment (simple prefix match)
        order_prefix = 0
        if order_cols and best_idx:
            for i, col in enumerate(order_cols):
                if i < len(best_idx) and col.strip('"').lower() == best_idx[i].strip('"').lower():
                    order_prefix += 1
                else:
                    break

        coverage_rows.append({
            "table": table,
            "is_hybrid": info.get("is_hybrid", False),
            "pk": pk,
            "indexes": indexes,
            "best_index": best_idx,
            "best_eq_prefix": max(best_eq_prefix, 0),
            "first_range_position": best_first_range,
            "order_by_prefix": order_prefix,
            "pk_eq_prefix": pk_eq_prefix,
            "pred_eq_cols": [c for c, op in pred_ops.items() if op == "EQ"],
        })

    return coverage_rows

