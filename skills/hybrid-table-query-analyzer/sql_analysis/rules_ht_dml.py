# src/sql_analysis/rules_ht_dml.py
"""
DML-specific rules for Hybrid Table INSERT validation
"""
from typing import Dict, List
from sqlglot import expressions as exp

def _fqn_from_table(t: exp.Table) -> str:
    """Extract fully-qualified name from table reference"""
    parts = [t.catalog, t.db, t.name]
    return ".".join([str(p) for p in parts if p])

def _is_dynamic_identifier(target_expr: exp.Expression) -> bool:
    """Check if expression is IDENTIFIER(...) function call"""
    # IDENTIFIER('DB.SCHEMA.TABLE') parses as an "anonymous" function in sqlglot
    return isinstance(target_expr, exp.Anonymous) and (target_expr.name or "").upper() == "IDENTIFIER"

def _insert_values_count(stmt: exp.Insert) -> int:
    """Count number of rows in INSERT ... VALUES"""
    vals = stmt.args.get("expression")
    if isinstance(vals, exp.Values):
        return len(vals.expressions or [])
    return 0

def rule_dynamic_identifier_target(stmt: exp.Expression) -> List[dict]:
    """
    Flags INSERT target that uses IDENTIFIER(...), which prevents metadata checks.
    """
    findings: List[dict] = []
    if isinstance(stmt, exp.Insert):
        target = stmt.this
        if _is_dynamic_identifier(target):
            findings.append({
                "severity": "MEDIUM",
                "rule": "DYNAMIC_IDENTIFIER_TARGET",
                "message": "INSERT target uses IDENTIFIER(...); analyzer cannot verify Hybrid Table/PK/indexes.",
                "suggestion": "Use an explicit FQN (DB.SCHEMA.TABLE) or provide a resolver to supply metadata for the resolved table.",
            })
    return findings

def rule_single_row_values_insert(stmt: exp.Expression) -> List[dict]:
    """
    Warn on INSERT ... VALUES with a single row (common anti-pattern for HT when looped).
    """
    findings: List[dict] = []
    if isinstance(stmt, exp.Insert):
        nrows = _insert_values_count(stmt)
        if nrows == 1:
            findings.append({
                "severity": "MEDIUM",
                "rule": "SINGLE_ROW_VALUES_INSERT",
                "message": "Single-row INSERT ... VALUES detected. Frequent 1-row commits are inefficient on Hybrid Tables.",
                "suggestion": "Batch rows: multi-row VALUES, array binding (commit every 500–2,000 rows), or staged INSERT ... SELECT.",
            })
    return findings

def rule_ht_pk_coverage_on_insert(stmt: exp.Expression, meta: Dict[str, dict]) -> List[dict]:
    """
    If target is a resolved HT, ensure INSERT includes all PK columns.
    """
    findings: List[dict] = []
    if not isinstance(stmt, exp.Insert):
        return findings
    target = stmt.this
    if isinstance(target, exp.Table):
        fqn = _fqn_from_table(target)
        tmeta = meta.get(fqn, {})
        if tmeta.get("is_hybrid"):
            pk = [c.lower() for c in (tmeta.get("pk") or [])]
            cols = []
            if stmt.columns:
                for c in stmt.columns:
                    # Columns may be exp.Identifier or exp.Column
                    if isinstance(c, exp.Identifier):
                        cols.append(c.name.lower())
                    elif isinstance(c, exp.Column):
                        cols.append((c.name or "").lower())
            missing = [c for c in pk if c not in cols]
            if pk and missing:
                findings.append({
                    "severity": "HIGH",
                    "rule": "HT_PK_NOT_IN_INSERT",
                    "message": f"Hybrid Table PK columns missing in INSERT column list: {missing}.",
                    "suggestion": "Include all PK columns (or ensure defaults) to avoid PK violations/retries; consider MERGE for upserts.",
                })
    # If IDENTIFIER(...) we can't check; rule_dynamic_identifier_target covers that.
    return findings

def rule_ht_write_amplification(stmt: exp.Expression, meta: Dict[str, dict]) -> List[dict]:
    """
    If target is HT with many secondary indexes, warn about cost of frequent small inserts.
    """
    findings: List[dict] = []
    if not isinstance(stmt, exp.Insert):
        return findings
    target = stmt.this
    if isinstance(target, exp.Table):
        fqn = _fqn_from_table(target)
        tmeta = meta.get(fqn, {})
        if tmeta.get("is_hybrid"):
            pk = [c.lower() for c in (tmeta.get("pk") or [])]
            idxs = tmeta.get("indexes") or []
            # Count non-PK indexes by comparing column lists (case-insensitive)
            def _is_same_cols(a, b):
                return [x.lower() for x in (a or [])] == [y.lower() for y in (b or [])]
            non_pk = [i for i in idxs if not _is_same_cols(i, pk)]
            if len(non_pk) >= 3:
                findings.append({
                    "severity": "MEDIUM",
                    "rule": "HT_WRITE_AMPLIFICATION",
                    "message": f"Hybrid Table has {len(non_pk)} secondary indexes; frequent small inserts will be costly.",
                    "suggestion": "Batch inserts and/or prune secondary indexes to the minimum necessary.",
                })
    return findings

def analyze_ht_dml_rules(pq, meta: Dict[str, dict]) -> List[dict]:
    """
    Entry point called by the main rule engine (rules.py).
    
    Args:
        pq: ParsedQuery object
        meta: Table metadata dict
        
    Returns:
        List of finding dicts with severity, rule, message, suggestion
    """
    stmt = pq.ast  # single-statement support
    findings: List[dict] = []
    findings += rule_dynamic_identifier_target(stmt)
    findings += rule_single_row_values_insert(stmt)
    findings += rule_ht_pk_coverage_on_insert(stmt, meta)
    findings += rule_ht_write_amplification(stmt, meta)
    return findings
