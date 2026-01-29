"""
SQL parsing helpers for Hybrid Table analysis
Based on Glean's blueprint (lines 186-294)
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
import sqlglot
from sqlglot import expressions as exp

TableRef = Tuple[Optional[str], Optional[str], str, Optional[str]]  # (catalog, schema, table, alias)
OrderCol = Tuple[str, str]  # (column_name, "ASC"/"DESC")

@dataclass
class ParsedQuery:
    raw_sql: str
    ast: exp.Expression
    tables: List[str] = field(default_factory=list)          # list of fully-qualified names if present
    table_alias: Dict[str, str] = field(default_factory=dict) # alias -> FQN or table name
    predicates: List[Dict] = field(default_factory=list)     # normalized predicates
    has_distinct: bool = False
    has_exists: bool = False
    has_in: bool = False                                      # Has IN predicates
    has_where: bool = False                                   # Has WHERE clause
    has_having: bool = False                                  # Has HAVING clause
    has_qualify: bool = False                                 # Has QUALIFY clause
    joins: List[Dict] = field(default_factory=list)
    order_by: List[OrderCol] = field(default_factory=list)
    limit: Optional[int] = None
    select_cols: List[str] = field(default_factory=list)

def _qual_name(t: exp.Table) -> str:
    """Extract fully-qualified name from table reference"""
    cat = t.args.get("catalog")
    db  = t.args.get("db")
    name= t.name
    # Convert Identifier objects to strings
    parts = [str(p) if p else None for p in [cat, db, name]]
    parts = [p for p in parts if p]
    return ".".join(parts) if parts else str(name)

def _extract_tables(ast: exp.Expression):
    """Extract all table references with aliases"""
    tables = []
    aliases = {}
    for t in ast.find_all(exp.Table):
        fq = _qual_name(t)
        tables.append(fq)
        if t.alias:
            # Convert alias to string
            aliases[str(t.alias)] = fq
    return list(dict.fromkeys(tables)), aliases

def _extract_order_by(ast: exp.Expression) -> List[OrderCol]:
    """Extract ORDER BY columns and directions"""
    order = ast.args.get("order")
    if not order:
        return []
    cols = []
    for e in order.expressions:
        dir = "DESC" if e.args.get("desc") else "ASC"
        col = e.this.alias_or_name
        # Convert to string if it's an Identifier
        cols.append((str(col), dir))
    return cols

def _extract_limit(ast: exp.Expression) -> Optional[int]:
    """
    Extract LIMIT or FETCH value if present.
    
    Handles both:
    - LIMIT n
    - FETCH FIRST n ROWS ONLY
    """
    # Check for LIMIT clause
    limit = ast.args.get("limit")
    if limit:
        try:
            return int(limit.this.name)
        except Exception:
            pass
    
    # Check for FETCH clause (FETCH FIRST n ROWS ONLY)
    fetch = ast.args.get("fetch")
    if fetch:
        try:
            # FETCH node contains the row count
            if hasattr(fetch, 'name'):
                return int(fetch.name)
            elif hasattr(fetch, 'this') and hasattr(fetch.this, 'name'):
                return int(fetch.this.name)
        except Exception:
            pass
    
    # Fallback: Look for FETCH in SQL text (if AST parsing fails)
    sql_upper = ast.sql().upper()
    if 'FETCH FIRST' in sql_upper or 'FETCH NEXT' in sql_upper:
        import re
        # Match patterns like "FETCH FIRST 1 ROWS ONLY" or "FETCH NEXT 100 ROWS ONLY"
        fetch_match = re.search(r'FETCH\s+(?:FIRST|NEXT)\s+(\d+)\s+ROW', sql_upper)
        if fetch_match:
            try:
                return int(fetch_match.group(1))
            except Exception:
                pass
    
    return None

def _extract_select_cols(ast: exp.Expression) -> List[str]:
    """Extract selected columns"""
    proj = ast.args.get("expressions") or []
    cols = []
    for e in proj:
        # Convert to string - alias_or_name might return Identifier
        col_name = e.alias_or_name or e.sql()
        cols.append(str(col_name))
    return cols

def _extract_predicates_from_where(where: exp.Expression, preds: List[Dict]) -> None:
    """
    Helper to extract predicates from a WHERE clause expression.
    Modifies preds list in-place.
    """
    if not where:
        return
    
    # Extract binary predicates (=, >, <, >=, <=, !=, etc.)
    for b in where.find_all(exp.Binary):
        left = b.left.sql()
        right = b.right.sql()
        op = b.__class__.__name__.upper()  # EQ, GT, LT, etc.
        preds.append({"left": left, "right": right, "op": op, "raw": b.sql()})
    
    # Extract IN predicates (column IN (value1, value2, ...))
    # IN is treated as equality for index coverage purposes
    for in_expr in where.find_all(exp.In):
        left = in_expr.this.sql()
        preds.append({"left": left, "right": "[IN_LIST]", "op": "EQ", "raw": in_expr.sql()[:100]})
    
    # Extract IS NULL / IS NOT NULL predicates
    for is_expr in where.find_all(exp.Is):
        left = is_expr.this.sql()
        right = is_expr.expression.sql() if is_expr.expression else "NULL"
        preds.append({"left": left, "right": right, "op": "IS", "raw": is_expr.sql()})


def _extract_predicates(ast: exp.Expression) -> List[Dict]:
    """
    Extract predicates from WHERE clauses, including CTEs.
    Works for SELECT, UPDATE, DELETE, and other DML statements.
    
    Enhanced to handle:
    - Main query WHERE clause
    - CTE (WITH ... AS) subquery WHERE clauses
    - JOIN ON conditions
    - IN predicates (treated as equality for index purposes)
    
    Note: If WHERE clause exists but contains placeholders/parameters,
    we may not extract all predicates, but that's okay - the presence
    of WHERE is more important than counting exact predicates.
    """
    preds = []
    
    # =========================================================================
    # 1. Extract predicates from CTE subqueries (WITH ... AS SELECT ...)
    # =========================================================================
    for cte in ast.find_all(exp.CTE):
        cte_expr = cte.this  # The SELECT inside the CTE
        if cte_expr:
            cte_where = cte_expr.args.get("where")
            if cte_where:
                _extract_predicates_from_where(cte_where, preds)
    
    # =========================================================================
    # 2. Extract predicates from main query WHERE clause
    # =========================================================================
    where = ast.args.get("where")
    
    # If not found in args, search the AST tree (works for UPDATE, DELETE, etc.)
    if not where:
        # Only get top-level WHERE clauses (not from CTEs which we already processed)
        for w in ast.find_all(exp.Where):
            # Check if this WHERE is not inside a CTE
            parent = w.parent
            is_in_cte = False
            while parent:
                if isinstance(parent, exp.CTE):
                    is_in_cte = True
                    break
                parent = getattr(parent, 'parent', None)
            if not is_in_cte:
                where = w
                break
    
    if where:
        _extract_predicates_from_where(where, preds)
    
    # =========================================================================
    # 3. Extract predicates from JOIN ON conditions
    # =========================================================================
    for join in ast.find_all(exp.Join):
        on_clause = join.args.get("on")
        if on_clause:
            # Extract equality conditions from JOIN ON
            for b in on_clause.find_all(exp.Binary):
                left = b.left.sql()
                right = b.right.sql()
                op = b.__class__.__name__.upper()
                # Only include equality predicates from JOINs (most relevant for indexes)
                if op == "EQ":
                    preds.append({"left": left, "right": right, "op": op, "raw": b.sql(), "source": "join"})
    
    # =========================================================================
    # 4. Fallback: if still no predicates but WHERE exists, add placeholder
    # =========================================================================
    if not preds:
        # Check if there's any WHERE clause in the entire query
        all_wheres = list(ast.find_all(exp.Where))
        if all_wheres:
            where_sql = all_wheres[0].sql()
            import re
            if re.search(r'(?:=|>|<|IN|LIKE|BETWEEN|IS\s+NOT|IS\s+NULL)', where_sql, re.IGNORECASE):
                preds.append({
                    "left": "WHERE_CLAUSE",
                    "right": "HAS_CONDITIONS",
                    "op": "EXISTS",
                    "raw": where_sql[:100] + "..." if len(where_sql) > 100 else where_sql
                })
    
    return preds

def _has_exists(ast: exp.Expression) -> bool:
    """Check if query contains EXISTS clause"""
    return any(isinstance(e, exp.Exists) for e in ast.find_all(exp.Exists))

def _has_in(ast: exp.Expression) -> bool:
    """Check if query contains IN predicates"""
    return any(isinstance(e, exp.In) for e in ast.find_all(exp.In))

def _extract_joins(ast: exp.Expression) -> List[Dict]:
    """Extract JOIN information"""
    joins = []
    for j in ast.find_all(exp.Join):
        jt = j.args.get("kind") or "INNER"
        on = j.args.get("on")
        joins.append({"type": str(jt).upper(), "on": on.sql() if on else None, "raw": j.sql()})
    return joins

def parse_sql(sql: str) -> ParsedQuery:
    """
    Parse SQL query into structured representation
    
    Args:
        sql: SQL query string
        
    Returns:
        ParsedQuery object with extracted components
        
    Raises:
        Exception: If SQL cannot be parsed
    """
    ast = sqlglot.parse_one(sql, read="snowflake")
    tables, aliases = _extract_tables(ast)
    
    # Check for WHERE clause (including CTEs and main query)
    has_where_clause = (
        ast.args.get("where") is not None or 
        len(list(ast.find_all(exp.Where))) > 0
    )
    
    # Extract predicates (now includes CTEs, JOINs, and IN predicates)
    predicates = _extract_predicates(ast)
    
    return ParsedQuery(
        raw_sql=sql,
        ast=ast,
        tables=tables,
        table_alias=aliases,
        predicates=predicates,
        has_distinct=ast.args.get("distinct") is not None,
        has_exists=_has_exists(ast),
        has_in=_has_in(ast),
        has_where=has_where_clause,
        has_having=ast.args.get("having") is not None,
        has_qualify=ast.args.get("qualify") is not None,
        joins=_extract_joins(ast),
        order_by=_extract_order_by(ast),
        limit=_extract_limit(ast),
        select_cols=_extract_select_cols(ast),
    )

