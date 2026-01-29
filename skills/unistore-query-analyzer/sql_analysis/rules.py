"""
Rule engine for detecting SQL anti-patterns
Based on Glean's blueprint (lines 420-510)
Enhanced with binding/parameterization and predicate order checks (Glean lines 91-232)
Enhanced with DML-specific rules for Hybrid Tables (INSERT validation)
Enhanced with payload analysis rules for Hybrid Tables (INSERT payload validation)
"""

from typing import Dict, List, Optional, Tuple
import re
from .parser import ParsedQuery
from .rules_ht_dml import analyze_ht_dml_rules
from .rules_ht_payload import analyze_ht_payload_rules
from .rules_stored_proc import analyze_stored_proc_performance

_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")

def _distinct_unnecessary(pq: ParsedQuery) -> bool:
    """
    Check if DISTINCT is likely unnecessary
    
    DISTINCT is often unnecessary with EXISTS/semi-joins when no duplication 
    producers are present (Glean lines 675-677)
    """
    if not pq.has_distinct:
        return False
    # Heuristic: no joins or only EXISTS -> likely redundant
    if pq.has_exists and not pq.joins:
        return True
    return False

def _order_without_limit(pq: ParsedQuery) -> bool:
    """Check if ORDER BY is used without LIMIT/FETCH (expensive full sort)"""
    return bool(pq.order_by) and pq.limit is None

def _non_sargable_predicates(pq: ParsedQuery) -> List[str]:
    """
    Detect non-sargable predicates (functions/casts on indexed columns)
    
    Non-sargable predicates prevent index usage (Glean lines 813-817, 164-169)
    
    IMPORTANT: Only flag when functions are applied to the COLUMN (left side),
    not when column names happen to contain function keywords.
    """
    bad = []
    
    for p in pq.predicates:
        raw = p["raw"]
        raw_u = raw.upper()
        
        # Get the left side (column side) of the predicate
        # Split on comparison operators to isolate left side
        left_side = ""
        for op in [" = ", " <> ", " != ", " > ", " < ", " >= ", " <= ", " IN ", " LIKE ", " BETWEEN "]:
            if op in raw_u:
                left_side = raw_u.split(op)[0].strip()
                break
        
        if not left_side:
            left_side = raw_u  # Fallback to full predicate
        
        # Check for functions WRAPPING the column (left side only)
        # Pattern: FUNCTION(column) not just word "function" appearing
        function_patterns = [
            r'\bUPPER\s*\(',
            r'\bLOWER\s*\(',
            r'\bDATE\s*\(',           # DATE(column) not column named "date"
            r'\bCAST\s*\(',
            r'\bCONVERT\s*\(',
            r'\bCOALESCE\s*\(',
            r'\bNVL\s*\(',
            r'\bIFNULL\s*\(',
            r'\bSUBSTR\s*\(',
            r'\bSUBSTRING\s*\(',
            r'\bTO_CHAR\s*\(',
            r'\bTO_VARCHAR\s*\(',
            r'\bTO_DATE\s*\(',
            r'\bTO_TIMESTAMP\s*\(',
            r'\bTRIM\s*\(',
            r'\bLTRIM\s*\(',
            r'\bRTRIM\s*\(',
        ]
        
        for pattern in function_patterns:
            if re.search(pattern, left_side):
                bad.append(raw)
                break  # One match is enough
        
        # Check for leading wildcard in LIKE (leading % prevents index seek)
        if " LIKE " in raw_u and " '%" in raw_u:
            bad.append(raw)
        
        # Check for arithmetic on column side (e.g., col+1 = 5)
        # More precise: look for arithmetic on left side only
        if re.search(r"^[^=<>]*[A-Za-z0-9_\"\)]\s*[\+\-\*/]\s*\d+\s*[=<>]", raw_u):
            bad.append(raw)
    
    return bad

def _wide_projection(pq: ParsedQuery) -> bool:
    """
    Check for SELECT * which is expensive on HT
    
    HT secondary indexes are non-covering (Glean lines 719-721, 824-825)
    """
    return any(col.strip() == "*" for col in pq.select_cols)

def _literal_binding_hints(pq: ParsedQuery) -> List[str]:
    """
    Identify predicates with embedded literals (good candidates for bind parameters)
    
    Parameterization improves plan-cache reuse and reduces compile time (Glean lines 94-136)
    """
    hints = []
    for p in pq.predicates:
        right = p.get("right", "")
        # Simplistic literal detection: quoted string or numeric literal
        if right and ((right.startswith("'") and right.endswith("'")) or _NUMERIC_RE.match(right)):
            hints.append(p["raw"])
    return hints

def _type_mismatch_on_index(pq: ParsedQuery, meta: Dict[str, dict]) -> List[str]:
    """
    Detect type mismatches that cause implicit casts on indexed columns
    
    If a predicate compares a column to a literal of mismatched type (e.g., NUMBER to 
    quoted string), suggest casting the literal (not the column) (Glean lines 164-184)
    """
    issues = []
    for t, info in meta.items():
        col_types = {k.lower(): (v or "").upper() for k, v in info.get("columns", {}).items()}
        
        for p in pq.predicates:
            left = p.get("left", "").split(".")[-1].strip('"').lower()
            right = p.get("right", "")
            
            if left in col_types and right:
                ctype = col_types[left]
                is_str_lit = right.startswith("'") and right.endswith("'")
                is_num_lit = _NUMERIC_RE.match(right) is not None
                
                # NUMBER/INT column compared to string literal
                if ("NUMBER" in ctype or "INT" in ctype) and is_str_lit:
                    issues.append(f"{t}: {p['raw']} (cast the literal to NUMBER, not the column)")
                
                # DATE/TIMESTAMP column compared to string without TO_DATE/TO_TIMESTAMP
                if ("DATE" in ctype or "TIMESTAMP" in ctype) and is_str_lit:
                    if "TO_DATE(" not in p["raw"].upper() and "TO_TIMESTAMP" not in p["raw"].upper():
                        issues.append(f"{t}: {p['raw']} (wrap literal with TO_DATE/TO_TIMESTAMP to preserve pushdown)")
                
                # VARCHAR/TEXT column compared to numeric literal
                if ("VARCHAR" in ctype or "TEXT" in ctype) and is_num_lit:
                    issues.append(f"{t}: {p['raw']} (ensure consistent string literal to avoid implicit cast)")
    
    return issues

def _missing_where(pq: ParsedQuery) -> bool:
    """
    Check if WHERE clause is missing.
    
    Note: We primarily check has_where flag. If WHERE exists structurally,
    we trust that even if we couldn't extract all predicates (e.g., due to
    placeholders/parameters). Predicates list may be incomplete, but the
    presence of WHERE is what matters for filtering.
    """
    # If WHERE clause exists structurally, consider it present
    if pq.has_where:
        return False
    
    # Otherwise, check if we have any predicates extracted
    # (handles edge cases where has_where might be False but we found conditions)
    return len(pq.predicates) == 0

def _has_any_narrowing(pq: ParsedQuery) -> bool:
    """
    Check if query has ANY narrowing filter
    
    Narrowing filters include:
    - WHERE with at least one predicate
    - EXISTS / IN in predicates or subqueries
    - HAVING (post-aggregation filter)
    - QUALIFY (window filter)
    """
    if pq.has_where and len(pq.predicates) > 0:
        return True
    if pq.has_exists or pq.has_in:
        return True
    if pq.has_having or pq.has_qualify:
        return True
    return False

def _joins_without_on(pq: ParsedQuery) -> List[str]:
    """Detect joins without ON predicates (implicit cross joins)"""
    offenders = []
    for j in pq.joins:
        jt = (j.get("type") or "").upper()
        # CROSS joins are okay when explicit; flag implicit cross joins (missing ON)
        if jt in ("INNER", "LEFT", "RIGHT", "FULL") and not j.get("on"):
            offenders.append(j["raw"])
    return offenders


def _detect_purge_pattern(pq: ParsedQuery) -> Optional[Tuple[bool, str, List[str], List[str]]]:
    """
    Detect DELETE/UPDATE "purge" pattern with equality + time-range predicates.
    
    Pattern: DELETE FROM table WHERE equality_col = 'val' AND time_col < 'date'
    This is a common data retention/cleanup pattern that benefits from batching.
    
    Returns:
        Tuple of (is_purge_pattern, description, equality_cols, time_range_cols)
        or None if not a purge pattern
    """
    # Only analyze DELETE or UPDATE statements
    if not pq.ast:
        return None
    
    statement_type = pq.ast.__class__.__name__.upper()
    if statement_type not in ('DELETE', 'UPDATE', 'MERGE'):
        return None
    
    if not pq.predicates or len(pq.predicates) < 2:
        # Purge pattern typically has at least 2 predicates (equality + time-range)
        return None
    
    equality_cols = []
    time_range_cols = []
    
    # Common time column patterns
    time_col_patterns = [
        r'created',
        r'updated',
        r'modified',
        r'deleted',
        r'timestamp',
        r'date',
        r'time',
        r'_at$',
        r'_dt$',
        r'_date$',
        r'_time$'
    ]
    
    for pred in pq.predicates:
        op = pred.get('op', '').upper()
        left = pred.get('left', '').lower()
        
        # Check for equality predicates
        if op in ('EQ', 'IN'):
            equality_cols.append(left)
        
        # Check for time-range predicates (< or <= with date/time column)
        if op in ('LT', 'LTE', 'LESSTHAN', 'LESSTHANOREQUALTO'):
            # Check if column name suggests it's a time column
            is_time_col = any(re.search(pattern, left, re.IGNORECASE) for pattern in time_col_patterns)
            
            # Also check if right side looks like a date
            right = pred.get('right', '').lower()
            is_date_value = any(keyword in right for keyword in ['date', 'timestamp', 'current', 'dateadd', 'datediff'])
            
            if is_time_col or is_date_value:
                time_range_cols.append(left)
    
    # Purge pattern: at least 1 equality and 1 time-range predicate
    if equality_cols and time_range_cols:
        description = f"DELETE/UPDATE with equality filter ({', '.join(equality_cols[:2])}) and time-range ({', '.join(time_range_cols[:2])})"
        return (True, description, equality_cols, time_range_cols)
    
    return None

def analyze_query(pq: ParsedQuery, meta: Dict[str, dict], coverage: List[dict]) -> List[dict]:
    """
    Run all analysis rules and return findings
    
    Args:
        pq: ParsedQuery object
        meta: Table metadata
        coverage: Index coverage scores
        
    Returns:
        List of finding dicts with severity, rule, message, suggestion
    """
    findings: List[dict] = []
    
    # Rule -1: Detect purge pattern (for DELETE/UPDATE operations)
    # Check this early so we can provide specific guidance
    purge_pattern = _detect_purge_pattern(pq)
    if purge_pattern:
        is_purge, description, equality_cols, time_range_cols = purge_pattern
        
        # Recommend composite index for purge pattern
        index_suggestion = f"CREATE INDEX idx_purge ON <table> ({', '.join(equality_cols[:1] + time_range_cols[:1])})"
        
        findings.append({
            "severity": "INFO",
            "rule": "HT_PURGE_PATTERN_DETECTED",
            "message": f"Data purge/cleanup pattern detected: {description}",
            "suggestion": f"For efficient bulk deletes: 1) Batch with ROW_NUMBER() QUALIFY <= 1000, "
                         f"2) Rate-limit (e.g., 100ms between batches), 3) Ensure composite index exists: {index_suggestion}, "
                         f"4) Archive to columnar before deletion. See Field Manual for complete batching pattern.",
            "metadata": {
                "equality_columns": equality_cols,
                "time_range_columns": time_range_cols,
                "recommended_index": index_suggestion
            }
        })

    # Rule 0a: No filtering at all (CRITICAL)
    if not _has_any_narrowing(pq):
        findings.append({
            "severity": "HIGH",
            "rule": "NO_FILTERING_CLAUSES",
            "message": "No narrowing filters detected (no WHERE/IN/EXISTS/HAVING/QUALIFY). Query likely scans entire table(s).",
            "suggestion": "Add selective predicates (WHERE with equality on indexed/PK columns, EXISTS/IN) or apply QUALIFY/HAVING as appropriate. Full table scans are extremely inefficient for Hybrid Tables."
        })

    # Rule 0b: Missing WHERE (structural)
    if _missing_where(pq):
        findings.append({
            "severity": "HIGH",
            "rule": "NO_WHERE_FILTER",
            "message": "No WHERE clause with predicates found; query will scan all rows.",
            "suggestion": "Add equality/range predicates on indexed/PK columns to reduce scanned data. Hybrid Tables require selective filters for optimal performance."
        })

    # Rule 0c: Joins without ON => implicit cross joins
    bad_joins = _joins_without_on(pq)
    if bad_joins:
        join_list = ", ".join(bad_joins[:2])
        if len(bad_joins) > 2:
            join_list += f" ... ({len(bad_joins)} total)"
        findings.append({
            "severity": "HIGH",
            "rule": "JOIN_WITHOUT_ON",
            "message": f"Join(s) without ON predicate detected: {join_list}",
            "suggestion": "Provide explicit ON predicates; avoid implicit cross joins that create cartesian products and balloon result size."
        })

    # Rule 1: Unnecessary DISTINCT
    if _distinct_unnecessary(pq):
        findings.append({
            "severity": "HIGH",
            "rule": "DISTINCT_UNNECESSARY",
            "message": "DISTINCT appears unnecessary with EXISTS; remove to avoid global dedup.",
            "suggestion": "Remove DISTINCT unless duplicates are possible from the base table."
        })

    # Rule 2: ORDER BY without LIMIT/FETCH
    if _order_without_limit(pq):
        order_cols = ", ".join(c for c, _ in pq.order_by)
        findings.append({
            "severity": "HIGH",
            "rule": "ORDER_BY_NO_LIMIT",
            "message": f"ORDER BY [{order_cols}] without LIMIT/FETCH will sort entire result.",
            "suggestion": "Add LIMIT (e.g., LIMIT 1000) or FETCH FIRST n ROWS ONLY, or apply seek pagination on PK/index. For HT, ORDER BY on PK + LIMIT/FETCH enables top-K optimization."
        })

    # Rule 3: Non-sargable predicates (functions wrapping columns)
    non_sarg = _non_sargable_predicates(pq)
    if non_sarg:
        findings.append({
            "severity": "HIGH",
            "rule": "NON_SARGABLE_PREDICATES",
            "message": f"Functions applied to columns in predicates (prevents index usage): {non_sarg[:2]}",  # Limit display to 2
            "suggestion": "Move functions to the literal side: Instead of 'UPPER(col) = value', use 'col = UPPER(value)'. Or precompute values at load time. This allows indexes to be used.",
            "remediation": """
**Why this matters:** When you apply a function to a column in a WHERE clause (e.g., `UPPER(name) = 'JOHN'`), 
Snowflake cannot use indexes on that column because it must compute the function for every row.

**How to fix:**
1. **Move function to literal:** `name = UPPER('john')` → works with index on `name`
2. **Precompute at load:** Add computed column or normalize data at insert time
3. **Use collation:** For case-insensitive string matching, use `COLLATE 'en-ci'` instead of UPPER/LOWER

**Example:**
```sql
-- ❌ Non-sargable (index not used)
WHERE UPPER(email) = 'USER@EXAMPLE.COM'

-- ✅ Sargable (index can be used)
WHERE email = UPPER('user@example.com')  -- if storing normalized
-- OR
WHERE email COLLATE 'en-ci' = 'user@example.com'  -- case-insensitive collation
```
"""
        })

    # Rule 4: Wide projection (SELECT *)
    if _wide_projection(pq):
        findings.append({
            "severity": "MEDIUM",
            "rule": "WIDE_SELECT",
            "message": "SELECT * or wide projection increases base-table probe cost in HT.",
            "suggestion": "Project only needed columns to reduce base-table probes. HT secondary indexes are non-covering."
        })

    # Rule 5: Parameterization hints (bind parameters)
    literal_hints = _literal_binding_hints(pq)
    if len(literal_hints) >= 2:
        findings.append({
            "severity": "MEDIUM",
            "rule": "BIND_PARAMETERS",
            "message": f"Many literal predicates detected ({len(literal_hints)} found): {literal_hints[:4]}{' ...' if len(literal_hints)>4 else ''}",
            "suggestion": "Use bind parameters / parameterized queries to improve plan-cache reuse and reduce compile time."
        })
    
    # Rule 6: Type/literal mismatches (implicit casts)
    type_issues = _type_mismatch_on_index(pq, meta)
    if type_issues:
        findings.append({
            "severity": "MEDIUM",
            "rule": "TYPE_MISMATCH",
            "message": f"Potential implicit casts on indexed columns ({len(type_issues)} found): {type_issues[:4]}{' ...' if len(type_issues)>4 else ''}",
            "suggestion": "Cast the literal to the column's type (not the column) to keep predicates sargable and avoid index suppression."
        })

    # Rule 7: Index coverage analysis
    for entry in coverage:
        table = entry["table"]
        is_hybrid = entry.get("is_hybrid", False)
        
        # Only report index issues for known Hybrid Tables
        if not is_hybrid:
            continue
        
        # Check PK coverage (leftmost equality predicates)
        if entry.get("pk_eq_prefix", 0) == 0 and entry.get("pk"):
            pred_cols = entry.get("pred_eq_cols", [])
            findings.append({
                "severity": "HIGH",
                "rule": "PK_NOT_EARLY_IN_PREDICATES",
                "message": f"HT table '{table}': no equality on leftmost PK columns; HT lookups may devolve to probes/scans.",
                "suggestion": f"Add equality predicates on PK leftmost columns {entry['pk'][:2]} when feasible, or create a secondary index starting with {pred_cols}."
            })
        
        # Check if predicates align with any index
        if entry["best_eq_prefix"] == 0 and entry["indexes"]:
            pred_cols = entry.get("pred_eq_cols", [])
            findings.append({
                "severity": "HIGH",
                "rule": "INDEX_MISALIGNED",
                "message": f"HT table '{table}': equality predicates do not cover leftmost columns of any existing index.",
                "suggestion": f"Create or reorder index to start with equality columns: {pred_cols}. Put most selective equality column first."
            })
        
        # Check ORDER BY alignment with index
        if entry.get("order_by_prefix", 0) == 0 and pq.order_by and entry["indexes"]:
            order_cols = ", ".join(c for c, _ in pq.order_by)
            findings.append({
                "severity": "MEDIUM",
                "rule": "ORDER_MISALIGNED",
                "message": f"HT table '{table}': ORDER BY [{order_cols}] not aligned to PK/index left prefix.",
                "suggestion": "Align ORDER BY to PK/index prefix and add LIMIT/FETCH (Top-K / seek pagination) to enable early termination."
            })

    # Rule 8: JOIN pattern (suggest EXISTS if appropriate)
    if pq.joins and not pq.has_exists:
        findings.append({
            "severity": "MEDIUM",
            "rule": "JOIN_PATTERN",
            "message": f"Query uses {len(pq.joins)} JOIN(s) - consider if EXISTS would be more appropriate.",
            "suggestion": "If right side is not unique on join keys, use EXISTS to avoid row multiplication and potentially faster execution."
        })

    # Rule 9: DML-specific checks for Hybrid Tables (INSERT validation)
    findings += analyze_ht_dml_rules(pq, meta)
    
    # Rule 10: Payload analysis for Hybrid Tables (INSERT payload validation)
    findings += analyze_ht_payload_rules(pq, meta)

    return findings