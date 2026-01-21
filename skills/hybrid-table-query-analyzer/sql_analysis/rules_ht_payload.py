# src/sql_analysis/rules_ht_payload.py
from typing import Dict, List, Tuple, Optional
import re
from sqlglot import expressions as exp

SQL_KEYWORDS_RE = re.compile(r"\b(DELETE|UPDATE|INSERT|SELECT)\b", re.IGNORECASE)

# NEW: simple extractor for "DELETE FROM <table> WHERE <col> IN (...)"
DELETE_IN_RE = re.compile(
    r"DELETE\s+FROM\s+([A-Z0-9_.\"`]+)\s+WHERE\s+([A-Z0-9_.\"`]+)\s+IN\s*\((?P<body>.*)\)",
    re.IGNORECASE | re.DOTALL
)
DELETE_IN_PREFIX_RE = re.compile(
    r"DELETE\s+FROM\s+([A-Z0-9_.\"`]+)\s+WHERE\s+([A-Z0-9_.\"`]+)\s+IN\s*\(",
    re.IGNORECASE | re.DOTALL
)

def _fqn_from_table(t: exp.Table) -> str:
    parts = [t.catalog, t.db, t.name]
    return ".".join([p for p in parts if p])

def _is_fully_qualified(t: exp.Table) -> bool:
    return bool(t.catalog and t.db and t.name)

def _extract_insert_literals(stmt: exp.Insert) -> List[str]:
    lits: List[str] = []
    values = stmt.args.get("expression")
    if isinstance(values, exp.Values):
        for tup in values.expressions or []:
            for e in getattr(tup, "expressions", []) or []:
                if isinstance(e, exp.Literal) and e.is_string:
                    lits.append(e.name or "")
    return lits

# NEW: parse target table, key column, and count items (not returning all values)
def _parse_delete_in_list(sql_text: str) -> Optional[Dict[str, str]]:
    m = DELETE_IN_RE.search(sql_text or "")
    if not m:
        return None
    target = m.group(1).strip()
    column = m.group(2).strip()
    body   = m.group("body").strip()
    # naive top-level split
    items = [x.strip() for x in re.split(r"\s*,\s*", body) if x.strip()]
    return {"target": target, "column": column, "items_count": len(items)}

def _parse_delete_target_col_prefix(s: str) -> Optional[Dict[str,str]]:
    m = DELETE_IN_PREFIX_RE.search(s or "")
    if not m:
        return None
    return {"target": m.group(1).strip(), "column": m.group(2).strip()}

def _looks_truncated(s: str, threshold: int = 8000) -> bool:
    if len(s) >= threshold:
        return True
    if s.rstrip().endswith(("...", "…")):
        return True
    opens = s.count("(")
    closes = s.count(")")
    if opens > closes:
        return True
    if s.count("'") % 2 == 1:
        return True
    return False

def _estimate_items_so_far(s: str) -> int:
    m = list(DELETE_IN_PREFIX_RE.finditer(s))
    if not m:
        return 0
    start = m[-1].end()
    body = s[start:]
    items = [x for x in re.split(r"\s*,\s*", body) if x.strip()]
    return max(0, len(items))

# NEW: build a remediation snippet (two options: VALUES and staged file)
def _remediation_for_delete_join(target: str, column: str, approx_items: Optional[int] = None) -> str:
    col = column.strip('"`')
    approx = f" (visible so far: ~{approx_items})" if approx_items else ""
    return f"""-- Remediation: replace huge IN list with a set-based join delete
-- Keys detected{approx}. Load full key list into a table, then join.
create temporary table keys_batch ({col} string);

-- Option A: paste keys in manageable batches (1–5K rows/batch)
insert into keys_batch ({col})
select v.{col}
from values
  ('key1'), ('key2') as v({col});

delete t
from {target} as t
join keys_batch k
  on k.{col} = t.{col};

-- Option B: stage a file with one key per line and load
-- copy into keys_batch from @mystage/keys_batch.csv file_format=(type=csv field_optionally_enclosed_by='\"');
-- delete t from {target} t join keys_batch k on k.{col}=t.{col};
"""

def rule_unqualified_target(stmt: exp.Expression) -> List[dict]:
    findings: List[dict] = []
    if isinstance(stmt, exp.Insert) and isinstance(stmt.this, exp.Table):
        if not _is_fully_qualified(stmt.this):
            findings.append({
                "severity": "MEDIUM",
                "rule": "UNQUALIFIED_TARGET",
                "message": "INSERT target is not fully qualified (missing DB and/or SCHEMA).",
                "suggestion": "Use DB.SCHEMA.TABLE so metadata (Hybrid Table, PK, indexes) can be verified.",
            })
    return findings

def rule_large_literal_payload(stmt: exp.Expression, max_len: int = 8192) -> List[dict]:
    """
    Flag very large string literals in INSERT payloads.
    """
    findings: List[dict] = []
    if not isinstance(stmt, exp.Insert):
        return findings
    literals = _extract_insert_literals(stmt)
    too_big = [s for s in literals if len(s) >= max_len]
    if too_big:
        findings.append({
            "severity": "MEDIUM",
            "rule": "LARGE_LITERAL_PAYLOAD",
            "message": f"Very large string literal detected in INSERT payload (>= {max_len} bytes).",
            "suggestion": "Store large text externally (stage/object store) or as structured pieces; keep HT rows small.",
        })
    return findings

def rule_embedded_sql_in_literal(stmt: exp.Expression) -> List[dict]:
    """
    Detect SQL-looking content inside string literals (dynamic SQL payload).
    """
    findings: List[dict] = []
    if not isinstance(stmt, exp.Insert):
        return findings
    literals = _extract_insert_literals(stmt)
    sqlish = [s for s in literals if SQL_KEYWORDS_RE.search(s or "")]
    if sqlish:
        findings.append({
            "severity": "MEDIUM",
            "rule": "EMBEDDED_SQL_LITERAL",
            "message": "String literal appears to contain SQL (e.g., DELETE/INSERT/UPDATE/SELECT).",
            "suggestion": "Avoid storing full SQL text in HT rows. Log structured fields (operation type, target table, batch_id) and keep key lists in staging tables.",
        })
    return findings

def rule_massive_in_list_in_literal(stmt: exp.Expression, min_items: int = 100) -> List[dict]:
    findings: List[dict] = []
    if not isinstance(stmt, exp.Insert):
        return findings
    literals = _extract_insert_literals(stmt)
    for s in literals:
        if not SQL_KEYWORDS_RE.search(s or ""):
            continue
        info = _parse_delete_in_list(s or "")
        if not info:
            continue
        if info["items_count"] >= min_items:
            remediation_sql = _remediation_for_delete_join(
                target=info["target"], column=info["column"], approx_items=info["items_count"]
            )
            findings.append({
                "severity": "HIGH",
                "rule": "MASSIVE_IN_LIST_IN_LITERAL",
                "message": f"Embedded SQL contains an IN list with {info['items_count']} items (>= {min_items}).",
                "suggestion": "Stage keys in a table and delete via join (set-based) instead of a huge IN list.",
                "remediation_sql": remediation_sql,
                "context": {"target": info["target"], "column": info["column"], "items_count": info["items_count"]},
            })
            break
    return findings

def rule_massive_in_list_truncated(stmt: exp.Expression, min_visible_items: int = 20) -> List[dict]:
    """
    If an embedded SQL literal appears truncated but clearly starts a DELETE ... WHERE col IN ( ...,
    estimate visible item count and attach remediation anyway.
    """
    findings: List[dict] = []
    if not isinstance(stmt, exp.Insert):
        return findings
    for s in _extract_insert_literals(stmt):
        if not SQL_KEYWORDS_RE.search(s or ""):
            continue
        if not _looks_truncated(s or ""):
            continue
        info = _parse_delete_target_col_prefix(s or "")
        if not info:
            continue
        est = _estimate_items_so_far(s or "")
        if est >= min_visible_items:
            remediation_sql = _remediation_for_delete_join(
                target=info["target"], column=info["column"], approx_items=est or None
            )
            findings.append({
                "severity": "HIGH",
                "rule": "MASSIVE_IN_LIST_TRUNCATED",
                "message": f"Embedded SQL appears truncated but shows a large IN list (visible items ≈ {est}).",
                "suggestion": "Use a set-based delete via staged keys; avoid giant IN lists.",
                "remediation_sql": remediation_sql,
                "context": {"target": info["target"], "column": info["column"], "visible_items": est, "truncated": True},
            })
            break
    return findings

def analyze_ht_payload_rules(pq, meta: Dict[str, dict]) -> List[dict]:
    stmt = pq.ast
    res: List[dict] = []
    res += rule_unqualified_target(stmt)
    res += rule_large_literal_payload(stmt)
    res += rule_embedded_sql_in_literal(stmt)
    res += rule_massive_in_list_in_literal(stmt)
    res += rule_massive_in_list_truncated(stmt)
    return res