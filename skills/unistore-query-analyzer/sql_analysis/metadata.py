"""
Metadata adapters for fetching table information
Based on Glean's blueprint (lines 299-416)
"""

from typing import Dict, List
import os

try:
    import snowflake.connector as sf
except Exception:
    sf = None

class LocalMetadata:
    """
    Fallback metadata with conservative assumptions.
    - is_hybrid: False
    - pk/indexes: unknown (empty)
    
    Use this when no Snowflake connection is available.
    """
    def get_tables_metadata(self, tables: List[str]) -> Dict[str, dict]:
        md = {}
        for t in tables:
            md[t] = {"is_hybrid": False, "pk": [], "indexes": [], "columns": {}}
        return md

class SnowflakeMetadata:
    """
    Pulls PK and index info via Snowflake connector.
    
    Attempts:
      - PK: SHOW PRIMARY KEYS IN TABLE
      - Secondary indexes: SHOW INDEXES IN TABLE  
      - Columns and types: INFORMATION_SCHEMA.COLUMNS
      - Hybrid detection: GET_DDL and search for 'HYBRID TABLE'
    """
    def __init__(self, conn=None, account="", user="", password="", role="", warehouse="", database="", schema=""):
        """
        Initialize with either an existing connection or connection parameters.
        
        Args:
            conn: Existing Snowflake connection (if provided, other params ignored)
            account, user, password, role, warehouse, database, schema: Connection params
        """
        if conn:
            self.conn = conn
            self.own_conn = False
        else:
            if sf is None:
                raise RuntimeError("snowflake-connector-python not installed.")
            self.conn = sf.connect(
                account=account, user=user, password=password,
                role=role or None, warehouse=warehouse or None,
                database=database or None, schema=schema or None,
            )
            self.own_conn = True
        
        # Track errors for debugging
        self.errors = []

    def __del__(self):
        """Close connection if we created it"""
        if hasattr(self, 'own_conn') and self.own_conn and hasattr(self, 'conn'):
            try:
                self.conn.close()
            except:
                pass

    def _run(self, sql: str):
        """Execute SQL and return results"""
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall(), [c[0] for c in cur.description]
        finally:
            cur.close()

    def _columns(self, fqn: str) -> Dict[str, str]:
        """
        Get column names and types from INFORMATION_SCHEMA
        Expect fqn: db.schema.table
        """
        parts = fqn.split(".")
        if len(parts) != 3:
            return {}
        db, sch, tbl = parts
        sql = f"""
            SELECT column_name, data_type
            FROM {db}.information_schema.columns
            WHERE table_schema = '{sch}' AND table_name = '{tbl}'
        """
        try:
            rows, cols = self._run(sql)
            return {r[0]: r[1] for r in rows}
        except Exception as e:
            self.errors.append(f"Failed to fetch columns for {fqn}: {str(e)}")
            return {}

    def _pk(self, fqn: str) -> List[str]:
        """
        Get primary key columns via SHOW PRIMARY KEYS IN TABLE
        Returns columns in key sequence order
        """
        try:
            rows, cols = self._run(f"SHOW PRIMARY KEYS IN TABLE {fqn}")
            # columns: created_on, name, database_name, schema_name, table_name, column_name, key_sequence, ...
            # Sort by key_sequence (index 6) to get proper order
            rows_sorted = sorted(rows, key=lambda r: int(r[6]))
            return [r[5] for r in rows_sorted]
        except Exception as e:
            self.errors.append(f"Failed to fetch primary keys for {fqn}: {str(e)}")
            return []

    def _secondary_indexes(self, fqn: str) -> List[List[str]]:
        """
        Get secondary indexes via SHOW INDEXES IN TABLE
        Returns list of index column lists (each index is a list of columns in order)
        """
        try:
            rows, cols = self._run(f"SHOW INDEXES IN TABLE {fqn}")
            # rows contain one row per index column; group by index_name and order by column_position
            # columns (typical): name, database_name, schema_name, table_name, column_name, expression, position, ...
            name_idx = {c.lower(): i for i, c in enumerate(cols)}
            idxname_i = name_idx.get("name", 0)
            col_i     = name_idx.get("column_name", 4)
            pos_i     = name_idx.get("position", 6)
            
            # Group by index name
            grouped: Dict[str, List[tuple]] = {}
            for r in rows:
                grouped.setdefault(r[idxname_i], []).append((r[pos_i], r[col_i]))
            
            # Sort each index's columns by position
            res = []
            for _, items in grouped.items():
                items_sorted = [c for _, c in sorted(items, key=lambda x: int(x[0]))]
                res.append(items_sorted)
            return res
        except Exception as e:
            self.errors.append(f"Failed to fetch indexes for {fqn}: {str(e)}")
            return []

    def _is_hybrid(self, fqn: str) -> bool:
        """
        Detect if table is a Hybrid Table
        Uses GET_DDL to check for 'HYBRID TABLE' in DDL
        """
        try:
            rows, cols = self._run(f"SELECT GET_DDL('table', '{fqn}')")
            ddl = rows[0][0] if rows and rows[0] else ""
            return "HYBRID TABLE" in (ddl or "").upper()
        except Exception as e:
            self.errors.append(f"Failed to fetch DDL for {fqn}: {str(e)}")
            return False

    def get_tables_metadata(self, tables: List[str]) -> Dict[str, dict]:
        """
        Fetch metadata for all tables
        
        Args:
            tables: List of fully-qualified table names
            
        Returns:
            Dict mapping table FQN to metadata:
            {
                "is_hybrid": bool,
                "pk": [col1, col2, ...],
                "indexes": [[col1, col2], [col3], ...],
                "columns": {colname: type, ...}
            }
        """
        # Clear previous errors
        self.errors = []
        
        md = {}
        for fqn in tables:
            cols = self._columns(fqn)
            pk   = self._pk(fqn)
            idxs = self._secondary_indexes(fqn)
            md[fqn] = {
                "is_hybrid": self._is_hybrid(fqn),
                "pk": pk,
                "indexes": idxs,
                "columns": cols,
            }
        return md
    
    def get_errors(self) -> List[str]:
        """Return list of errors encountered during metadata fetching"""
        return self.errors

