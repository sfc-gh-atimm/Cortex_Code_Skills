"""
Hybrid Table Query Optimization Helpers

This module provides lightweight, text-based analysis utilities for
Snowflake Hybrid Table (HT) queries. It is designed to be called from
your higher-level SQL analysis pipeline, *not* to parse the full query
plan.

Functions:
    - analyze_ht_query_optimization(sql_text, is_ht_query)
    - detect_bound_variables(sql_text)

Both functions are safe to call for any SQL text. They only return
findings when patterns are detected.

Integration expectations:
    - For Hybrid Table queries, pass is_ht_query=True when ACCESS_KV_TABLE = true.
    - The result of analyze_ht_query_optimization can be merged into your
      existing sql_findings list and/or used as an input to your
      primary-cause ranking logic.

This module has no external dependencies beyond the Python standard library.

Source: GLEAN recommendations 2024-12-03
"""

from __future__ import annotations

import re
from typing import Optional, Dict, Any, List, Tuple

# ─────────────────────────────────────────────────────────────
# Regex helpers: comments & strings
# ─────────────────────────────────────────────────────────────

COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
STRING_RE = re.compile(r"'([^']|'')*'")

def _strip_comments_and_strings(sql: str) -> str:
    """
    Remove comments and mask string literals so pattern rules
    don't fire on commented-out code or sample SQL in strings.

    Example:
        SELECT 'LOWER(x)' AS sample -- LOWER(y)
    becomes:
        SELECT '' AS sample
    """
    if not sql:
        return ""
    without_comments = re.sub(COMMENT_RE, " ", sql)
    # Replace string bodies with empty quotes to keep structure but
    # avoid matching parameter markers or functions inside literals.
    return re.sub(STRING_RE, "''", without_comments)


# ─────────────────────────────────────────────────────────────
# DDL Detection Helpers
# ─────────────────────────────────────────────────────────────

# DDL prefixes that should bypass DML-focused analysis
DDL_PREFIXES = (
    'CREATE ', 'ALTER ', 'DROP ', 'TRUNCATE ',
    'GRANT ', 'REVOKE ', 'COMMENT ', 'DESCRIBE ', 'SHOW '
)


def is_ddl_statement(sql_text: Optional[str]) -> bool:
    """
    Check if the SQL is a DDL statement (CREATE, ALTER, DROP, etc.)
    that should bypass DML-focused analysis.
    
    DDL statements don't have WHERE clauses, bound variables, or filtering -
    they're metadata operations. Applying DML analysis to DDL produces
    misleading findings.
    
    Args:
        sql_text: The SQL text to check
        
    Returns:
        True if this is a DDL statement
    """
    if not sql_text:
        return False
    sql_upper = sql_text.strip().upper()
    return sql_upper.startswith(DDL_PREFIXES)


def get_ddl_type(sql_text: Optional[str]) -> Optional[str]:
    """
    Return the specific DDL type if this is a DDL statement.
    
    This helps route to the appropriate DDL-specific analysis.
    
    Args:
        sql_text: The SQL text to analyze
        
    Returns:
        DDL type string ('CREATE_INDEX', 'CREATE_HYBRID_TABLE', etc.) or None
    """
    if not sql_text:
        return None
    
    sql_upper = sql_text.strip().upper()
    
    # Not a DDL statement
    if not sql_upper.startswith(DDL_PREFIXES):
        return None
    
    # CREATE statements
    if sql_upper.startswith('CREATE'):
        # CREATE INDEX
        if 'INDEX' in sql_upper and 'CREATE' in sql_upper:
            return 'CREATE_INDEX'
        
        # CREATE HYBRID TABLE ... AS SELECT (CTAS)
        if 'HYBRID' in sql_upper and 'TABLE' in sql_upper:
            if ' AS ' in sql_upper and 'SELECT' in sql_upper:
                return 'CREATE_HYBRID_TABLE_AS'
            return 'CREATE_HYBRID_TABLE'
        
        # Other CREATE TABLE variants
        if 'TABLE' in sql_upper:
            if ' AS ' in sql_upper:
                return 'CREATE_TABLE_AS'
            return 'CREATE_TABLE'
        
        # CREATE VIEW, PROCEDURE, etc.
        if 'VIEW' in sql_upper:
            return 'CREATE_VIEW'
        if 'PROCEDURE' in sql_upper:
            return 'CREATE_PROCEDURE'
        if 'FUNCTION' in sql_upper:
            return 'CREATE_FUNCTION'
        
        return 'CREATE_OTHER'
    
    # ALTER statements
    if sql_upper.startswith('ALTER'):
        if 'TABLE' in sql_upper:
            return 'ALTER_TABLE'
        return 'ALTER_OTHER'
    
    # DROP statements
    if sql_upper.startswith('DROP'):
        if 'INDEX' in sql_upper:
            return 'DROP_INDEX'
        if 'TABLE' in sql_upper:
            return 'DROP_TABLE'
        return 'DROP_OTHER'
    
    # TRUNCATE
    if sql_upper.startswith('TRUNCATE'):
        return 'TRUNCATE_TABLE'
    
    # Administrative commands
    if sql_upper.startswith(('GRANT', 'REVOKE')):
        return 'ACCESS_CONTROL'
    if sql_upper.startswith(('DESCRIBE', 'SHOW', 'COMMENT')):
        return 'METADATA_QUERY'
    
    return 'DDL_OTHER'


# ─────────────────────────────────────────────────────────────
# Regex helpers: JOIN functions, case transforms, mixed tables
# ─────────────────────────────────────────────────────────────

# Functions in JOIN predicates (critical, HT-specific).
# We restrict search to a short window after ON to avoid
# matching random functions elsewhere in the query.
JOIN_FUNC_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bON\b[^;]{0,200}\bLOWER\s*\(", re.IGNORECASE), "LOWER()", "Case transformation in JOIN"),
    (re.compile(r"\bON\b[^;]{0,200}\bUPPER\s*\(", re.IGNORECASE), "UPPER()", "Case transformation in JOIN"),
    (re.compile(r"\bON\b[^;]{0,200}\bTRIM\s*\(",  re.IGNORECASE), "TRIM()",  "Whitespace removal in JOIN"),
    (re.compile(r"\bON\b[^;]{0,200}\bLTRIM\s*\(", re.IGNORECASE), "LTRIM()", "Whitespace removal in JOIN"),
    (re.compile(r"\bON\b[^;]{0,200}\bRTRIM\s*\(", re.IGNORECASE), "RTRIM()", "Whitespace removal in JOIN"),
    (re.compile(r"\bON\b[^;]{0,200}\bSUBSTR(ING)?\s*\(", re.IGNORECASE), "SUBSTR()", "String manipulation in JOIN"),
    (re.compile(r"\bON\b[^;]{0,200}\b(CAST|CONVERT)\s*\(", re.IGNORECASE), "CAST()", "Type conversion in JOIN"),
    (re.compile(r"\bON\b[^;]{0,200}\bCOALESCE\s*\(", re.IGNORECASE), "COALESCE()", "Null handling in JOIN"),
]

# Simple indicators that *may* imply mixed HT + standard-table usage.
STANDARD_TABLE_INDICATORS: List[str] = [
    "INFORMATION_SCHEMA",
    "ACCOUNT_USAGE",
    "_STANDARD",
    "_STD",
]

LOWER_RE = re.compile(r"\bLOWER\s*\(", re.IGNORECASE)
UPPER_RE = re.compile(r"\bUPPER\s*\(", re.IGNORECASE)


# ─────────────────────────────────────────────────────────────
# Public API: Hybrid Table optimization analysis
# ─────────────────────────────────────────────────────────────

def analyze_ht_query_optimization(sql_text: Optional[str],
                                  is_ht_query: bool) -> Optional[Dict[str, Any]]:
    """
    Analyze a query for common Hybrid Table (HT) performance anti-patterns.

    This is intentionally lightweight and text-based. It does NOT inspect
    query plans or metadata; those should be handled by your higher-level
    analyzer.

    Args:
        sql_text: The SQL text of the query.
        is_ht_query: True if this query accesses Hybrid Tables
                     (ACCESS_KV_TABLE = true); False otherwise.

    Returns:
        None if there are no detected issues or if not an HT query.
        Otherwise, a dict with:
            {
              "has_issues": bool,
              "critical": [ { ... } ],
              "warnings": [ { ... } ],
              "info": [ { ... } ],
            }

        Each finding has:
            - type: short machine-readable string
            - description: human-readable explanation
            - impact: "HIGH" | "MEDIUM" (critical/warnings)
            - recommendation: how to fix or improve
            - estimated_improvement: string hint (e.g. "50-70%")
            - (optional) root_cause: string
    """
    if not sql_text or not is_ht_query:
        return None

    findings: Dict[str, Any] = {
        "has_issues": False,
        "critical": [],
        "warnings": [],
        "info": [],
    }

    clean_sql = _strip_comments_and_strings(sql_text)
    sql_upper = clean_sql.upper()

    # 1) Functions in JOIN predicates (CRITICAL)
    for pattern, func_name, description in JOIN_FUNC_PATTERNS:
        if pattern.search(sql_upper):
            findings["critical"].append({
                "type": "function_in_join",
                "function": func_name,
                "description": description,
                "impact": "HIGH",
                "recommendation": (
                    f"Remove {func_name} from JOIN predicates. Pre-normalize data, "
                    "store normalized values, or use a computed column so JOIN conditions "
                    "can use plain equality on indexed columns."
                ),
                "estimated_improvement": "50-70%",
            })
            findings["has_issues"] = True

    # 2) Potential mixed HT + standard-table usage (WARNING)
    for indicator in STANDARD_TABLE_INDICATORS:
        if indicator in sql_upper:
            findings["warnings"].append({
                "type": "potential_mixed_join",
                "indicator": indicator,
                "description": (
                    f'Query text references "{indicator}", which may indicate joins '
                    "between Hybrid Tables and standard tables."
                ),
                "impact": "MEDIUM-HIGH",
                "recommendation": (
                    "Verify which tables are Hybrid vs standard. Joins that pull large "
                    "standard-table scans can dominate HT latency. Consider converting hot "
                    "joined tables to Hybrid Tables or pre-aggregating data into standard "
                    "tables for analytics."
                ),
                "estimated_improvement": "30-50%",
            })
            findings["has_issues"] = True
            # Only need to flag once per indicator; break to avoid duplicates
            break

    # 3) INSERT/MERGE with JOIN (INFO)
    if ("INSERT INTO" in sql_upper or "MERGE INTO" in sql_upper) \
       and "JOIN" in sql_upper and "FROM" in sql_upper:
        findings["info"].append({
            "type": "insert_with_join",
            "description": "INSERT/MERGE with JOIN detected.",
            "recommendation": (
                "Ensure source and target Hybrid Tables used in the JOIN have appropriate "
                "primary keys, foreign keys, and secondary indexes on the join keys to "
                "avoid wide row-store scans."
            ),
        })
        findings["has_issues"] = True

    # 4) Multiple case transformations (DATA-QUALITY / WARNING)
    lower_count = len(LOWER_RE.findall(sql_upper))
    upper_count = len(UPPER_RE.findall(sql_upper))
    total_case_funcs = lower_count + upper_count

    # Threshold: 3+ visible LOWER/UPPER in predicates is suspicious.
    if total_case_funcs >= 3:
        severity = "HIGH" if total_case_funcs >= 10 else "MEDIUM"
        bucket = "critical" if severity == "HIGH" else "warnings"

        findings[bucket].append({
            "type": "data_quality_issue",
            "description": (
                f"Multiple case transformations detected in predicates "
                f"({total_case_funcs} occurrences of LOWER/UPPER)."
            ),
            "impact": "HIGH" if severity == "HIGH" else "MEDIUM",
            "recommendation": (
                "Standardize text casing at load time and avoid LOWER()/UPPER() in "
                "WHERE/JOIN predicates. Store normalized values and use plain equality "
                "on indexed columns."
            ),
            "estimated_improvement": "40-60%",
            "root_cause": "Inconsistent data casing requires runtime transformation.",
        })
        findings["has_issues"] = True

    return findings if findings["has_issues"] else None


# ─────────────────────────────────────────────────────────────
# Public API: bound variable detection
# ─────────────────────────────────────────────────────────────

def detect_bound_variables(sql_text: Optional[str]) -> Tuple[Optional[bool], str]:
    """
    Detect whether the SQL text appears to use bound parameters.

    Returns:
        (has_bound_vars, message)

        has_bound_vars:
            True  -> at least one bound variable pattern detected
            False -> SQL is literal-only (no obvious bind markers)
            None  -> SQL is empty/None

        message:
            A short human-readable status string.
    """
    if sql_text is None:
        return None, ""

    raw = str(sql_text)
    if not raw.strip():
        return None, ""

    clean_sql = _strip_comments_and_strings(raw)

    # Parameter patterns:
    #   ?        -> JDBC / ODBC positional parameter
    #   :name    -> named parameter
    #   :1, :2   -> positional parameter (Oracle/JDBC style)
    #   $1, $2   -> PostgreSQL-style
    #
    # For '?' we need to catch multiple contexts:
    #   - col = ?           (comparison)
    #   - FUNCTION(?)       (function argument - UDF calls)
    #   - FUNCTION(?, ?)    (multiple function arguments)
    #   - IN (?, ?, ?)      (IN clause)
    #   - VALUES (?, ?)     (INSERT values)
    patterns = [
        # '?' in various contexts (expanded for UDF/function calls)
        re.compile(r"=\s*\?", re.IGNORECASE),      # col = ?
        re.compile(r"\(\s*\?", re.IGNORECASE),     # FUNC(? or (? - function arg start
        re.compile(r",\s*\?", re.IGNORECASE),      # , ? - function arg after comma
        re.compile(r"\?\s*\)", re.IGNORECASE),     # ?) - function arg end (standalone)
        re.compile(r"\?\s*,", re.IGNORECASE),      # ?, - function arg before comma
        # Named and positional parameters
        re.compile(r":\w+", re.IGNORECASE),        # :name
        re.compile(r":\d+", re.IGNORECASE),        # :1
        re.compile(r"\$\d+", re.IGNORECASE),       # $1
    ]

    for pat in patterns:
        if pat.search(clean_sql):
            return True, "✅ Bound variables detected (query is likely parameterized)."

    return False, "❌ No bound variables detected (query likely uses literal values only)."


# ─────────────────────────────────────────────────────────────
# CREATE INDEX DDL Analysis
# ─────────────────────────────────────────────────────────────

_CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)\s+ON\s+([^\s(]+)\s*\(([^)]+)\)",
    re.IGNORECASE
)


def _parse_create_index(sql_text: str) -> Optional[Dict[str, Any]]:
    """
    Lightweight parser for CREATE INDEX statements.
    
    Returns:
        {
          "index_name": str,
          "table_name": str,        # normalized, no quotes
          "columns": [str],         # in order
          "is_unique": bool
        }
        or None if not a CREATE INDEX.
    """
    if not sql_text:
        return None
    
    m = _CREATE_INDEX_RE.search(sql_text)
    if not m:
        return None

    unique_kw, idx_name, table_name, cols = m.groups()
    cols_list = [c.strip().strip('"').upper() for c in cols.split(",") if c.strip()]
    
    return {
        "index_name": idx_name.strip().strip('"').upper(),
        "table_name": table_name.strip().strip('"').upper(),
        "columns": cols_list,
        "is_unique": bool(unique_kw),
    }


def analyze_create_index_statement(
    sql_text: str,
    coverage: List[Dict[str, Any]],
    metadata: Dict[str, Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Analyze a CREATE INDEX statement using existing coverage + metadata.
    
    Uses ONLY:
      - coverage: from score_indexes_for_tables / SnowVI enrichment
      - metadata: HT flags, workload type, row counts, throttling, etc.
    
    Returns:
        {
          "critical": [...],
          "warnings": [...],
          "info": [...]
        }
        
    Each finding has:
        - rule: machine-readable identifier (e.g., CREATE_INDEX_REDUNDANT)
        - severity: HIGH / MEDIUM / LOW / INFO
        - message: human-readable explanation
        - recommendation: how to fix or improve
    """
    result: Dict[str, List[Dict[str, Any]]] = {"critical": [], "warnings": [], "info": []}

    parsed = _parse_create_index(sql_text)
    if not parsed:
        return result  # not a CREATE INDEX statement

    idx_name = parsed["index_name"]
    table_name = parsed["table_name"]
    idx_cols = parsed["columns"]

    # Find matching table coverage (normalized)
    cov_for_table = None
    for cov in coverage or []:
        cov_table = str(cov.get("table", "")).upper().replace('"', "")
        # Match full path or just table name
        if cov_table.endswith(table_name) or cov_table == table_name:
            cov_for_table = cov
            break

    existing_indexes = (cov_for_table or {}).get("indexes") or []
    pred_eq_cols = set((cov_for_table or {}).get("pred_eq_cols") or [])
    is_hybrid = bool((cov_for_table or {}).get("is_hybrid") or metadata.get("ACCESS_KV_TABLE"))
    workload_type = (metadata.get("workload_type") or "UNKNOWN").upper()

    # ------------------------------------------------------------------
    # 1) Redundancy vs existing indexes / PK
    # ------------------------------------------------------------------
    # Normalize existing indexes into list-of-column-lists
    existing_index_cols: List[List[str]] = []
    for idx in existing_indexes:
        if isinstance(idx, dict):
            cols = [c.strip().upper() for c in (idx.get("columns") or [])]
        elif isinstance(idx, (list, tuple)):
            cols = [str(c).strip().upper() for c in idx]
        else:
            cols = [str(idx).strip().upper()]
        if cols:
            existing_index_cols.append(cols)

    # Check for exact duplicate or left-prefix coverage
    for ex_cols in existing_index_cols:
        if ex_cols == idx_cols:
            result["warnings"].append({
                "rule": "CREATE_INDEX_REDUNDANT",
                "severity": "MEDIUM",
                "message": (
                    f"CREATE INDEX {idx_name} on {table_name}({', '.join(idx_cols)}) "
                    f"appears redundant: an existing index has the same column list."
                ),
                "recommendation": "Reuse the existing index instead of creating a duplicate."
            })
            break
        if ex_cols[: len(idx_cols)] == idx_cols:
            # Existing composite covers this as left prefix
            result["warnings"].append({
                "rule": "CREATE_INDEX_REDUNDANT_PREFIX",
                "severity": "MEDIUM",
                "message": (
                    f"Existing composite index on {table_name}({', '.join(ex_cols)}) "
                    f"already covers the proposed index columns as a left-most prefix."
                ),
                "recommendation": (
                    "Avoid creating a separate index; rely on the existing composite index "
                    "or adjust its column order if needed."
                )
            })
            break

    # ------------------------------------------------------------------
    # 2) Predicate alignment for current workload
    # ------------------------------------------------------------------
    if pred_eq_cols:
        used_in_predicates = bool(set(idx_cols) & pred_eq_cols)
        if not used_in_predicates:
            result["warnings"].append({
                "rule": "CREATE_INDEX_NOT_USED_BY_PREDICATES",
                "severity": "MEDIUM",
                "message": (
                    f"Proposed index columns {idx_cols} do not appear in equality predicates "
                    f"for the analyzed query on {table_name}."
                ),
                "recommendation": (
                    "Confirm that these columns are actually used in WHERE/JOIN predicates for "
                    "your target workload. Prefer indexing hot predicate columns."
                )
            })
    else:
        result["info"].append({
            "rule": "CREATE_INDEX_NO_PREDICATE_DATA",
            "severity": "LOW",
            "message": (
                f"Cannot confirm predicate usage for {idx_cols} on {table_name} from current query. "
                "Index usefulness cannot be validated from this query alone."
            ),
            "recommendation": (
                "Review other queries on this table to ensure these columns are heavily used in predicates."
            )
        })

    # ------------------------------------------------------------------
    # 3) Composite index order sanity (for multi-column indexes)
    # ------------------------------------------------------------------
    if len(idx_cols) > 1 and pred_eq_cols:
        leftmost = idx_cols[0]
        if leftmost not in pred_eq_cols:
            result["warnings"].append({
                "rule": "CREATE_INDEX_MISALIGNED_COMPOSITE",
                "severity": "MEDIUM",
                "message": (
                    f"Composite index {idx_name} on {table_name}({', '.join(idx_cols)}) has "
                    f"left-most column {leftmost}, which does not appear in equality predicates "
                    "for the analyzed query."
                ),
                "recommendation": (
                    "Reorder composite index so equality predicate columns come first, "
                    "in the same order they appear in the WHERE/JOIN clause."
                )
            })

    # ------------------------------------------------------------------
    # 4) HT-specific cost / workload fit heuristics
    # ------------------------------------------------------------------
    if is_hybrid:
        # Heuristic: if workload is ANALYTIC or MIXED, flag that indexing may
        # not be the primary fix.
        if workload_type in {"ANALYTIC", "MIXED"}:
            result["warnings"].append({
                "rule": "CREATE_INDEX_ON_ANALYTIC_WORKLOAD_HT",
                "severity": "MEDIUM",
                "message": (
                    "The target table appears to be a Hybrid Table serving analytic or mixed workloads. "
                    "Indexes may help point lookups but will not fix large scans or analytic patterns."
                ),
                "recommendation": (
                    "Consider routing analytic/scan-heavy queries to standard tables/MVs/DTs. "
                    "Use Hybrid Table indexes primarily for OLTP-style point/range lookups."
                )
            })

        # Use existing throttling / write-amp signals from metadata if present
        ht_throttled_ms = float(metadata.get("HT_THROTTLED_MS") or metadata.get("FDB_THROTTLING_MS") or 0)
        rows_inserted = float(metadata.get("ROWS_INSERTED") or 0)
        rows_updated = float(metadata.get("ROWS_UPDATED") or 0)
        write_heavy = rows_inserted + rows_updated > 1_000_000

        if ht_throttled_ms > 0 or write_heavy:
            result["warnings"].append({
                "rule": "CREATE_INDEX_HT_WRITE_COST",
                "severity": "MEDIUM",
                "message": (
                    "Hybrid Table writes for this workload are already non-trivial "
                    f"(rows changed ≈ {int(rows_inserted + rows_updated):,}, "
                    f"HT throttling {ht_throttled_ms:.0f} ms). Adding another index "
                    "will increase write amplification and quota pressure."
                ),
                "recommendation": (
                    "Validate that this index will materially reduce read latency on hot paths "
                    "before adding it. Consider limiting the number of indexes on write-heavy HT tables."
                )
            })

    # ------------------------------------------------------------------
    # 5) Positive confirmation when all checks pass
    # ------------------------------------------------------------------
    if not result["warnings"] and not result["critical"]:
        result["info"].append({
            "rule": "CREATE_INDEX_LOOKS_GOOD",
            "severity": "INFO",
            "message": (
                f"Index {idx_name} on {table_name}({', '.join(idx_cols)}) appears "
                "well-aligned with predicates and not redundant with existing indexes."
            ),
            "recommendation": (
                "Verify expected improvement with a test query after creation. "
                "Check SnowVI for index usage confirmation."
            )
        })

    return result


def is_create_index_statement(sql_text: Optional[str]) -> bool:
    """
    Quick check if the SQL text is a CREATE INDEX statement.
    
    Args:
        sql_text: The SQL text to check
        
    Returns:
        True if this appears to be a CREATE INDEX statement
    """
    if not sql_text:
        return False
    return bool(_CREATE_INDEX_RE.search(sql_text))


# ─────────────────────────────────────────────────────────────
# COPY INTO Stage from HT Analysis
# ─────────────────────────────────────────────────────────────

_COPY_INTO_RE = re.compile(
    r"^\s*COPY\s+INTO\s+([^\s(]+)",
    re.IGNORECASE | re.DOTALL
)


def analyze_copy_into_stage_from_ht(
    sql_text: str,
    coverage: List[Dict[str, Any]],
    metadata: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Detect COPY INTO statements that write to a stage (@...) while reading from Hybrid Tables.
    
    This is an anti-pattern because:
    - Hybrid Tables are optimized for OLTP-style workloads, not analytic exports
    - Exporting to CSV bypasses Snowflake's optimizer for downstream consumers
    - It suggests analytic workloads are being served from operational tables
    
    Args:
        sql_text: Full SQL text for the query.
        coverage: Index / table coverage entries (from score_indexes_for_tables + SnowVI).
        metadata: Query metadata (for QUERY_TYPE, ACCESS_KV_TABLE, etc.)
    
    Returns:
        List of finding dicts (to append to sql_findings).
    """
    findings: List[Dict[str, Any]] = []

    m = _COPY_INTO_RE.search(sql_text or "")
    if not m:
        return findings

    target = (m.group(1) or "").strip()
    # Only interested in COPY INTO @stage, not COPY INTO <table>
    if not target.startswith("@"):
        return findings

    # Check if any covered tables are Hybrid
    ht_tables = []
    for cov in coverage or []:
        if cov.get("is_hybrid"):
            tbl = str(cov.get("table") or "").upper()
            if tbl:
                ht_tables.append(tbl)

    # Fallback: metadata.ACCESS_KV_TABLE when coverage is empty
    is_ht_query = bool(metadata.get("ACCESS_KV_TABLE")) or bool(ht_tables)
    if not is_ht_query:
        return findings

    # Heuristic: GROUP BY / UNION suggests analytic/reporting export
    sql_up = sql_text.upper()
    has_group_by = "GROUP BY" in sql_up
    has_union = "UNION ALL" in sql_up or "UNION " in sql_up

    msg_tables = ", ".join(sorted(set(ht_tables))) if ht_tables else "Hybrid Tables"
    pattern_desc = []
    if has_group_by:
        pattern_desc.append("aggregated (GROUP BY)")
    if has_union:
        pattern_desc.append("UNIONed")
    pattern_str = ""
    if pattern_desc:
        pattern_str = " Data is " + " and ".join(pattern_desc) + "."

    findings.append({
        "rule": "COPY_INTO_STAGE_FROM_HT",
        "severity": "MEDIUM",
        "message": (
            f"COPY INTO writes to stage target {target} using data from {msg_tables}.{pattern_str} "
            "This pattern exports Hybrid Table data to CSV instead of writing directly into a "
            "table optimized for analytic/reporting workloads."
        ),
        "recommendation": (
            "Review whether this export should instead populate a standard/columnar reporting table, "
            "materialized view, or downstream analytic structure. For Hybrid Tables, keep OLTP-style "
            "point/range workloads on HT and route analytic/reporting workloads to standard tables. "
            "If this export is part of an HT migration, consider COPY INTO the Hybrid Table or a "
            "staging/reporting table rather than long-term CSV pipelines."
        ),
        "impact": (
            "Using stage/CSV as an intermediate store can introduce extra hops, inconsistent schemas, "
            "and bypass Snowflake's optimizer for downstream consumers. For HT, it also suggests that "
            "analytic workloads are being served from operational tables."
        )
    })

    return findings


def is_copy_into_stage(sql_text: Optional[str]) -> bool:
    """
    Quick check if the SQL text is a COPY INTO @stage statement.
    
    Args:
        sql_text: The SQL text to check
        
    Returns:
        True if this appears to be a COPY INTO @stage statement
    """
    if not sql_text:
        return False
    m = _COPY_INTO_RE.search(sql_text)
    if not m:
        return False
    target = (m.group(1) or "").strip()
    return target.startswith("@")


# ─────────────────────────────────────────────────────────────
# CTAS Primary Key Violation Detection
# ─────────────────────────────────────────────────────────────

def detect_ctas_pk_violation(
    sql_text: str,
    metadata: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Detect CTAS to Hybrid Table failures due to PK uniqueness violations.
    
    The error "200001: A primary key already exists" typically means the
    SELECT returns duplicate values in the PRIMARY KEY columns, NOT a
    schema-level conflict. The error wording is misleading.
    
    Args:
        sql_text: The SQL text of the query
        metadata: Query metadata including error codes/messages
        
    Returns:
        Finding dict if pattern detected, None otherwise
    """
    if not sql_text:
        return None
    
    sql_upper = sql_text.upper()
    
    # Check if this is a CTAS to Hybrid Table
    # Look for CREATE ... HYBRID TABLE ... AS pattern
    is_ctas_ht = (
        'CREATE' in sql_upper and
        'HYBRID' in sql_upper and
        'TABLE' in sql_upper and
        ' AS ' in sql_upper  # Space around AS to avoid matching column aliases
    )
    
    if not is_ctas_ht:
        return None
    
    # Check for PK constraint in the DDL
    has_pk = 'PRIMARY KEY' in sql_upper
    
    # Check for the specific error (200001)
    error_code = str(metadata.get('ERROR_CODE') or metadata.get('SQLCODE') or '')
    error_msg = str(metadata.get('ERROR_MESSAGE') or '').upper()
    
    is_pk_violation = (
        error_code == '200001' or
        'PRIMARY KEY ALREADY EXISTS' in error_msg or
        'A PRIMARY KEY ALREADY EXISTS' in error_msg
    )
    
    if is_pk_violation:
        # PK violation detected - HIGH severity
        return {
            "rule": "HT_PRIMARY_KEY_ALREADY_EXISTS_CTAS",
            "severity": "HIGH",
            "message": (
                "CTAS to Hybrid Table failed with 'A primary key already exists' (error 200001). "
                "This typically means the SELECT returns duplicate values in the PRIMARY KEY columns, "
                "NOT a schema-level conflict. The error wording is misleading."
            ),
            "recommendation": (
                "1. Identify the PK columns in your CREATE statement. "
                "2. Run: SELECT <pk_cols>, COUNT(*) FROM (<your_source_query>) GROUP BY <pk_cols> HAVING COUNT(*) > 1. "
                "3. If duplicates exist, add ROW_NUMBER() deduplication to pick one row per PK combination. "
                "4. Alternatively, revise the PK definition if duplicates are expected in the domain."
            ),
            "impact": (
                "CTAS will repeatedly fail until duplicates are resolved. "
                "Teams often waste time trying unrelated fixes (warehouse changes, feature toggles) "
                "when the root cause is data quality."
            )
        }
    
    # If no error detected but it's a CTAS with PK, provide an INFO-level check
    if has_pk:
        return {
            "rule": "HT_CTAS_PK_UNIQUENESS_CHECK",
            "severity": "INFO",
            "message": (
                "This CTAS creates a Hybrid Table with a PRIMARY KEY constraint. "
                "Ensure the source query returns unique values for the PK columns to avoid "
                "error 200001 ('A primary key already exists')."
            ),
            "recommendation": (
                "Before running, validate uniqueness with: "
                "SELECT <pk_cols>, COUNT(*) FROM (<source>) GROUP BY <pk_cols> HAVING COUNT(*) > 1. "
                "If duplicates exist, add ROW_NUMBER() deduplication or revise the PK definition."
            )
        }
    
    return None


def is_ctas_hybrid_table(sql_text: Optional[str]) -> bool:
    """
    Quick check if the SQL text is a CREATE ... HYBRID TABLE ... AS statement.
    
    Args:
        sql_text: The SQL text to check
        
    Returns:
        True if this appears to be a CTAS to Hybrid Table
    """
    if not sql_text:
        return False
    sql_upper = sql_text.upper()
    return (
        'CREATE' in sql_upper and
        'HYBRID' in sql_upper and
        'TABLE' in sql_upper and
        ' AS ' in sql_upper
    )


# ─────────────────────────────────────────────────────────────
# CLI / quick test harness
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Simple manual test when running this module directly.
    sample_sql = """
        SELECT t1.id, t2.val
        FROM ht_table t1
        JOIN dim t2
          ON LOWER(t1.key) = LOWER(t2.key)
        WHERE t1.org_id = ? AND t1.category = :cat
    """

    print("=== analyze_ht_query_optimization ===")
    result = analyze_ht_query_optimization(sample_sql, is_ht_query=True)
    print(result)

    print("\n=== detect_bound_variables ===")
    has_binds, msg = detect_bound_variables(sample_sql)
    print(f"has_bound_vars={has_binds}, msg={msg}")

