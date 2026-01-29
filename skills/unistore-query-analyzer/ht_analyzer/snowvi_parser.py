# snowvi_parser.py
"""
SnowVI JSON Parser for Hybrid Table Index Metadata

Extracts index definitions and plan operators from SnowVI JSON exports.
Works entirely client-side - no Snowhouse queries needed.

Features:
- Extract primary key columns from SDL
- Extract kvUniqueIndices and kvSecondaryIndices
- Detect index operators in execution plan
- Enrich existing coverage with SnowVI metadata

Usage:
    from snowvi_parser import (
        extract_ht_index_metadata_from_snowvi_json,
        extract_ht_index_operators_from_snowvi_json,
        enrich_coverage_with_snowvi_index_metadata
    )
    
    # Parse SnowVI JSON
    index_meta = extract_ht_index_metadata_from_snowvi_json(snowvi_json)
    index_ops = extract_ht_index_operators_from_snowvi_json(snowvi_json)
    
    # Enrich coverage
    enriched = enrich_coverage_with_snowvi_index_metadata(
        coverage, index_meta, index_ops
    )
"""

import json
from typing import Any, Dict, List, Union, Optional

SnowviPlan = Union[str, Dict[str, Any]]


def _normalize_table_name(name: str) -> str:
    """
    Normalize table names to a comparable form.
    We keep schema-qualified names but fold to upper and strip quotes.
    """
    if not name:
        return ""
    return name.replace('"', "").upper()


def extract_ht_index_metadata_from_snowvi_json(
    plan_json: SnowviPlan,
) -> Dict[str, Dict[str, Any]]:
    """
    Extract Hybrid Table index metadata from a SnowVI JSON export.

    Supports multiple SnowVI JSON formats:
      Format 1: data.catalog.baseTables[*]
      Format 2: sdls['1'].catalog.objects[*]
      Format 3: catalog.baseTables[*] or catalog.objects[*]

    Expected fields per table:
      - tableName or name
      - primaryKeyColumns
      - kvUniqueIndices
      - kvSecondaryIndices

    Returns:
        {
            "<TABLE_NAME>": {
                "primaryKeyColumns": [...],
                "kvUniqueIndices": [...],
                "kvSecondaryIndices": [...],
            },
            ...
        }
    """
    # Parse if needed
    if isinstance(plan_json, str):
        try:
            plan = json.loads(plan_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
    else:
        plan = plan_json

    # Try multiple paths to find catalog and table array
    catalog = None
    base_tables = None
    
    if isinstance(plan, dict):
        # Format 1: data.catalog.baseTables (original format)
        if "data" in plan and isinstance(plan["data"], dict):
            catalog = plan["data"].get("catalog")
            if catalog and isinstance(catalog, dict):
                base_tables = catalog.get("baseTables") or catalog.get("basetables")
        
        # Format 2: sdls['X'].catalog.objects (alternative SnowVI format)
        if not base_tables and "sdls" in plan:
            sdls = plan["sdls"]
            if isinstance(sdls, dict):
                # Try numeric keys first ('1', '2', etc.)
                for key in sorted(sdls.keys()):
                    sdl_entry = sdls[key]
                    if isinstance(sdl_entry, dict) and "catalog" in sdl_entry:
                        catalog = sdl_entry["catalog"]
                        if isinstance(catalog, dict):
                            base_tables = catalog.get("objects") or catalog.get("baseTables")
                            if base_tables:
                                break
        
        # Format 3: catalog.baseTables or catalog.objects (direct)
        if not base_tables:
            catalog = plan.get("catalog")
            if catalog and isinstance(catalog, dict):
                base_tables = (
                    catalog.get("objects") or 
                    catalog.get("baseTables") or 
                    catalog.get("basetables")
                )

    if not base_tables or not isinstance(base_tables, list):
        return {}

    ht_index_meta: Dict[str, Dict[str, Any]] = {}

    for bt in base_tables:
        if not isinstance(bt, dict):
            continue

        # Build fully qualified table name (schema.table or database.schema.table)
        table_name = bt.get("tableName") or bt.get("name") or ""
        schema_name = bt.get("schemaName", "")
        database_name = bt.get("databaseName", "")
        
        # Try multiple naming formats to maximize match probability
        table_names = []
        if table_name:
            # Add short name
            table_names.append(_normalize_table_name(table_name))
            # Add schema.table
            if schema_name:
                table_names.append(_normalize_table_name(f"{schema_name}.{table_name}"))
            # Add database.schema.table
            if database_name and schema_name:
                table_names.append(_normalize_table_name(f"{database_name}.{schema_name}.{table_name}"))
        
        if not table_names:
            continue

        # Extract column schema for ID→name mapping
        columns = bt.get("columns", [])
        col_id_to_name = {}
        if columns:
            for col in columns:
                if isinstance(col, dict):
                    col_id = col.get("id") or col.get("columnId")
                    col_name = col.get("name") or col.get("columnName")
                    if col_id is not None and col_name:
                        col_id_to_name[col_id] = col_name
        
        # PATCH 1: Detect whether SnowVI actually provided any index metadata fields
        # This distinguishes "no indexes exist" from "index metadata not visible"
        has_index_metadata = any(
            key in bt for key in ("primaryKeyColumns", "kvUniqueIndices", "kvSecondaryIndices")
        )
        
        # Store metadata under all possible name formats
        metadata = {
            "primaryKeyColumns": bt.get("primaryKeyColumns", []),
            "kvUniqueIndices": bt.get("kvUniqueIndices", []),
            "kvSecondaryIndices": bt.get("kvSecondaryIndices", []),
            "column_id_to_name": col_id_to_name,  # Add mapping for enrichment
            "has_index_metadata": has_index_metadata,  # NEW: Track if SnowVI had index DDL
        }
        
        for name in table_names:
            ht_index_meta[name] = metadata

    return ht_index_meta


def extract_ht_index_operators_from_snowvi_json(
    plan_json: SnowviPlan,
) -> Dict[str, Dict[str, Any]]:
    """
    Walk the SnowVI plan JSON and look for index-related operators by table.

    Heuristic: inspect keys like "operator", "op", "rsoName" and
    "object_name"/"table"/"tableName"/"targetObjectName" for 'INDEX'.

    Supports multiple SnowVI JSON formats:
      - Standard plan JSON (data.plan or plan)
      - SnowVI with processes array
      - SnowVI with selectedProcessDetail

    Returns:
        {
            "<TABLE_NAME>": {
                "index_ops": [
                    {
                        "op_type": "<operator name>",
                        "node": <raw node dict>,
                    },
                    ...
                ]
            },
            ...
        }
    """
    if isinstance(plan_json, str):
        try:
            plan = json.loads(plan_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
    else:
        plan = plan_json

    index_ops: Dict[str, Dict[str, Any]] = {}
    
    # Try to find the plan/operator tree in various locations
    plan_root = None
    if isinstance(plan, dict):
        # Standard format: data.plan or plan or selectedProcessDetail
        if "data" in plan and isinstance(plan["data"], dict):
            plan_root = plan["data"].get("plan") or plan["data"].get("selectedProcessDetail")
        if not plan_root:
            plan_root = plan.get("plan") or plan.get("selectedProcessDetail")
        # If still nothing, try queryData path
        if not plan_root and "queryData" in plan:
            query_data = plan.get("queryData", {}).get("data", {})
            plan_root = query_data.get("selectedProcessDetail") or query_data.get("processes")
        # Fallback: use the whole plan object
        if not plan_root:
            plan_root = plan

    def record(table: str, op_type: str, node: Dict[str, Any]):
        t = _normalize_table_name(table)
        if not t:
            return
        bucket = index_ops.setdefault(t, {"index_ops": []})
        bucket["index_ops"].append(
            {
                "op_type": op_type,
                "node": node,
            }
        )

    def walk(node: Any):
        if isinstance(node, dict):
            op_type = str(
                node.get("operator")
                or node.get("op")
                or node.get("rsoName")
                or ""
            )

            object_name = (
                node.get("object_name")
                or node.get("table")
                or node.get("tableName")
                or node.get("targetObjectName")
                or ""
            )

            if op_type and "INDEX" in op_type.upper():
                record(object_name, op_type, node)

            for key in ("children", "inputs", "nodes", "plans", "subPlans"):
                if key in node and isinstance(node[key], list):
                    for child in node[key]:
                        walk(child)

        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(plan)
    return index_ops


def enrich_coverage_with_snowvi_index_metadata(
    coverage: List[Dict[str, Any]],
    snowvi_index_meta: Dict[str, Dict[str, Any]],
    snowvi_index_ops: Dict[str, Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Attach SnowVI index metadata to each coverage entry (in-place).

    New fields per coverage row:
        snowvi_primary_key_columns
        snowvi_kv_secondary_indices
        snowvi_kv_unique_indices
        snowvi_index_ops  (if provided)
    
    Args:
        coverage: List of coverage dicts from score_indexes_for_tables
        snowvi_index_meta: Output from extract_ht_index_metadata_from_snowvi_json
        snowvi_index_ops: Optional output from extract_ht_index_operators_from_snowvi_json
    
    Returns:
        The same coverage list (modified in-place)
    """
    if not coverage or not snowvi_index_meta:
        return coverage

    snowvi_index_ops = snowvi_index_ops or {}

    for cov in coverage:
        table_name = _normalize_table_name(cov.get("table", ""))
        if not table_name:
            continue

        # PATCH 2: Default - we don't yet know where index metadata came from
        cov.setdefault("index_metadata_source", "unknown")

        meta = snowvi_index_meta.get(table_name)
        if not meta:
            continue

        cov["snowvi_primary_key_columns"] = meta.get("primaryKeyColumns", [])
        cov["snowvi_kv_secondary_indices"] = meta.get("kvSecondaryIndices", [])
        cov["snowvi_kv_unique_indices"] = meta.get("kvUniqueIndices", [])

        ops = snowvi_index_ops.get(table_name)
        if ops:
            cov["snowvi_index_ops"] = ops["index_ops"]
        
        # PATCH 2: Only attempt to synthesize index lists if SnowVI actually
        # contained index metadata fields. This distinguishes:
        #   - "SnowVI says 0 indexes" (confirmed)
        #   - "SnowVI has no index DDL visible" (unknown)
        if not meta.get("has_index_metadata"):
            # SnowVI JSON didn't include catalog/index metadata for this table
            # Don't touch the indexes field - leave source as "unknown"
            continue
        
        # SnowVI HAS index metadata - mark source and process it
        cov["index_metadata_source"] = "snowvi"
        
        # CRITICAL FIX: Populate the main "indexes" field from SnowVI data
        # This fixes the "Indexes Found: 0" false negative when SnowVI shows indices
        col_mapping = meta.get("column_id_to_name", {})
        snowvi_indexes = []
        
        # Add primary key as first index
        pk_cols = meta.get("primaryKeyColumns", [])
        if pk_cols and col_mapping:
            pk_names = []
            for col_id in pk_cols:
                col_name = col_mapping.get(col_id)
                if col_name:
                    pk_names.append(col_name)
            if pk_names:
                snowvi_indexes.append(pk_names)
        
        # Add secondary indices
        secondary = meta.get("kvSecondaryIndices", [])
        for idx_def in secondary:
            if isinstance(idx_def, dict):
                idx_cols = idx_def.get("indexColumns", [])
                if idx_cols and col_mapping:
                    idx_names = []
                    for col_id in idx_cols:
                        col_name = col_mapping.get(col_id)
                        if col_name:
                            idx_names.append(col_name)
                    if idx_names:
                        snowvi_indexes.append(idx_names)
        
        # Update the main "indexes" field that scoring logic uses
        # Only override if SnowVI provides better data than Snowhouse
        if snowvi_indexes:
            existing_indexes = cov.get("indexes", [])
            if not existing_indexes:  # Snowhouse has no indexes - use SnowVI
                cov["indexes"] = snowvi_indexes
            else:  # Merge: prefer SnowVI if it has more indices
                if len(snowvi_indexes) > len(existing_indexes):
                    cov["indexes"] = snowvi_indexes

    return coverage


def extract_ht_index_usage_from_plan(
    plan_json: Any,
    coverage: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Extract Hybrid Table index usage information from query plan JSON.
    
    This function analyzes the execution plan to determine:
    - Whether index operators are present for each Hybrid Table
    - Which indexes are being used
    - Storage path (KV vs Analytic store)
    - Row estimates/actuals from the plan
    
    Args:
        plan_json: Query execution plan (from SnowVI or Snowhouse PLAN_JSON column)
        coverage: List of coverage dicts with table information
    
    Returns:
        Dict keyed by normalized table name, each containing:
            {
                "index_operator_found": bool,
                "index_name": str or None,
                "storage_source": "KV" | "ANALYTIC" | "UNKNOWN",
                "estimated_rows": float,
                "actual_rows": float
            }
    """
    if not plan_json or not coverage:
        return {}
    
    # Build a set of HT table names we're looking for
    ht_tables = set()
    for cov in coverage:
        if cov.get("is_hybrid"):
            table_name = _normalize_table_name(cov.get("table", ""))
            if table_name:
                ht_tables.add(table_name)
    
    if not ht_tables:
        return {}
    
    result = {}
    
    # Initialize result dict with defaults for each HT
    for table_name in ht_tables:
        result[table_name] = {
            "index_operator_found": False,
            "index_name": None,
            "storage_source": "UNKNOWN",
            "estimated_rows": 0.0,
            "actual_rows": 0.0
        }
    
    def walk_plan_node(node: Any, parent_context: Dict[str, Any] = None):
        """
        Recursively walk plan nodes looking for index operators on Hybrid Tables.
        """
        if not isinstance(node, dict):
            return
        
        # Common fields to check
        node_name = node.get("name", "")
        node_id = node.get("id", "")
        operator_type = node.get("operatorType", "")
        
        # Check for table scan operators
        table_name_raw = (
            node.get("tableName") or
            node.get("TableName") or
            node.get("table") or
            ""
        )
        
        if table_name_raw:
            table_name = _normalize_table_name(table_name_raw)
            
            # Only process if this is one of our HT tables
            if table_name in ht_tables:
                # Check for index-related operators
                is_index_op = False
                index_name = None
                storage_source = "UNKNOWN"
                
                # Look for index operator signatures
                # Common patterns: INDEX_SCAN, INDEX_LOOKUP, KV_LOOKUP, etc.
                if any(keyword in operator_type.upper() for keyword in ["INDEX", "KV_LOOKUP", "POINT_LOOKUP"]):
                    is_index_op = True
                    index_name = node.get("indexName") or node.get("IndexName")
                
                # Check for storage path indicators
                if "KV" in operator_type.upper() or "KEY_VALUE" in node_name.upper():
                    storage_source = "KV"
                elif any(keyword in operator_type.upper() for keyword in ["COLUMNAR", "ANALYTIC", "OBJECT"]):
                    storage_source = "ANALYTIC"
                elif "SCAN" in operator_type.upper() and not is_index_op:
                    # Full scan typically means analytic store path
                    storage_source = "ANALYTIC"
                
                # Extract row counts
                estimated_rows = 0.0
                actual_rows = 0.0
                
                try:
                    if "estimatedRows" in node:
                        estimated_rows = float(node["estimatedRows"])
                    elif "estimated_rows" in node:
                        estimated_rows = float(node["estimated_rows"])
                    elif "cardinality" in node:
                        estimated_rows = float(node["cardinality"])
                except (TypeError, ValueError):
                    pass
                
                try:
                    if "actualRows" in node:
                        actual_rows = float(node["actualRows"])
                    elif "actual_rows" in node:
                        actual_rows = float(node["actual_rows"])
                except (TypeError, ValueError):
                    pass
                
                # Update result if we found something significant
                if is_index_op or storage_source != "UNKNOWN" or estimated_rows > 0:
                    current = result[table_name]
                    
                    # Prefer index operators over non-index info
                    if is_index_op and not current["index_operator_found"]:
                        current["index_operator_found"] = True
                        current["index_name"] = index_name
                    
                    # Update storage source if we have better info
                    if storage_source != "UNKNOWN" and current["storage_source"] == "UNKNOWN":
                        current["storage_source"] = storage_source
                    
                    # Update row counts (use highest values found)
                    if estimated_rows > current["estimated_rows"]:
                        current["estimated_rows"] = estimated_rows
                    if actual_rows > current["actual_rows"]:
                        current["actual_rows"] = actual_rows
        
        # Recurse into children
        children = node.get("children") or node.get("inputs") or []
        for child in children:
            walk_plan_node(child, {"parent": node})
    
    # Start walking from the root
    walk_plan_node(plan_json)
    
    return result


def extract_udf_usage_from_snowvi_json(snowvi_json: Any) -> List[Dict[str, Any]]:
    """
    Extract UDF usage from SnowVI JSON via queryOverview.usageTrackingRecord.
    
    For scalar SQL UDFs, Snowflake records the UDF name in:
      queryData.data.globalInfo.queryOverview.usageTrackingRecord[*]
        .payload.CHECK_PARSE_TREE.additionalInfo.udfName
    
    Returns:
        List of entries: [{ "udf_name": str, "extra": dict }, ...]
    """
    udfs: List[Dict[str, Any]] = []

    try:
        query_overview = (
            snowvi_json
            .get("queryData", {})
            .get("data", {})
            .get("globalInfo", {})
            .get("queryOverview", {})
        )
        records = query_overview.get("usageTrackingRecord", []) or []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            payload = rec.get("payload") or {}
            cpt = payload.get("CHECK_PARSE_TREE") or {}
            info = cpt.get("additionalInfo") or {}
            udf_name = info.get("udfName")
            if udf_name:
                udfs.append({
                    "udf_name": udf_name,
                    "extra": info,
                })
    except Exception:
        # Be defensive; never break caller on malformed JSON
        return []

    return udfs


def extract_udtf_usage_from_snowvi_json(snowvi_json: Any) -> List[Dict[str, Any]]:
    """
    Detect table function / UDTF calls from SnowVI JSON using sqlText.
    
    Searches for TABLE(...) function calls in the SQL text and extracts
    the fully qualified function name.
    
    Returns:
      [
        {
          "full_name": "META_TV.GET_ADS_FN",
          "database": "META_TV_DB" or None,
          "schema": "META_TV" or None,
          "name": "GET_ADS_FN",
          "sql_snippet": "TABLE(meta_tv.get_ads_fn(...))"
        },
        ...
      ]
    """
    import re
    
    # Regex to match TABLE(function_name(...)) patterns
    # Include both uppercase and lowercase letters in function name
    TABLE_CALL_RE = re.compile(r'\bTABLE\s*\(\s*([A-Za-z0-9_."$]+)\s*\(', re.IGNORECASE)
    
    # Built-in table functions to exclude
    _BUILTIN_TABLE_FUNCS = {"FLATTEN", "GENERATOR", "RESULT_SCAN"}
    
    try:
        qov = (
            snowvi_json
            .get("queryData", {})
            .get("data", {})
            .get("globalInfo", {})
            .get("queryOverview", {})
        )
        sql = (qov.get("sqlText") or "").strip()
        if not sql:
            return []

        udtfs: List[Dict[str, Any]] = []
        for match in TABLE_CALL_RE.finditer(sql):
            raw_fqn = match.group(1).replace('"', '')
            parts = raw_fqn.split('.')
            db = schema = name = None

            if len(parts) == 3:
                db, schema, name = parts
            elif len(parts) == 2:
                schema, name = parts
            elif len(parts) == 1:
                name = parts[0]

            if not name:
                continue

            # Skip obvious built-ins
            if name.upper() in _BUILTIN_TABLE_FUNCS:
                continue

            udtfs.append({
                "full_name": raw_fqn,
                "database": db,
                "schema": schema,
                "name": name,
                "sql_snippet": match.group(0)
            })

        return udtfs
    except Exception:
        # Be defensive; never break caller on malformed JSON
        return []


def reconstruct_simple_sql_from_logical_plan(snowvi_json: Any) -> Optional[str]:
    """
    Best-effort pseudo-SQL reconstruction from SnowVI logical plan.
    
    Target pattern (common for scalar SQL UDFs):
      Result -> SortWithLimit -> Filter -> TableScan
    
    For scalar SQL UDFs, the planner inlines the UDF body into the logical plan,
    so we can reconstruct an approximate SQL statement from the plan nodes.
    
    Returns:
        A pseudo-SQL string or None if the pattern is too complex.
    """
    try:
        logical = (
            snowvi_json
            .get("queryData", {})
            .get("data", {})
            .get("globalInfo", {})
            .get("logical", [])
        )
        if not logical or not isinstance(logical, list):
            return None

        # Find core nodes
        table_scan = next(
            (n for n in logical if n.get("displayName") == "TableScan"),
            None,
        )
        if not table_scan:
            return None

        scan_ann = table_scan.get("annotations", {}) or {}
        table_name = scan_ann.get("tableName")
        if not table_name:
            return None

        filt = next(
            (n for n in logical if n.get("displayName") == "Filter"),
            None,
        )
        sort = next(
            (n for n in logical if n.get("displayName") == "SortWithLimit"),
            None,
        )
        result = next(
            (n for n in logical if n.get("displayName") == "Result"),
            None,
        )

        # WHERE
        where_clause = None
        if filt:
            where_clause = (filt.get("annotations") or {}).get("filter")

        # ORDER BY / LIMIT
        order_by = None
        limit = None
        if sort:
            s_ann = sort.get("annotations") or {}
            keys = s_ann.get("keys") or []
            if keys:
                order_by = ", ".join(keys)
            # rowCount is the target number of rows; use it as LIMIT if > 0
            rc = s_ann.get("rowCount")
            if isinstance(rc, int) and rc > 0:
                limit = rc

        # SELECT list – default to *, or use first expression from Result
        select_expr = "*"
        if result:
            r_ann = result.get("annotations") or {}
            exprs = r_ann.get("expressions") or []
            if exprs:
                # For scalar UDFs, the first expression is typically the object_construct() or scalar expression
                select_expr = exprs[0]

        parts = [f"SELECT {select_expr}", f"FROM {table_name}"]
        if where_clause:
            parts.append(f"WHERE {where_clause}")
        if order_by:
            parts.append(f"ORDER BY {order_by}")
        if limit is not None:
            parts.append(f"LIMIT {limit}")

        return "\n".join(parts) + ";"
    except Exception:
        return None


def extract_uuid_from_snowvi_json(snowvi_json: Any) -> Optional[str]:
    """
    Extract the query UUID from a SnowVI JSON export.
    
    The UUID can be found at multiple locations depending on SnowVI format:
      - queryData.data.globalInfo.queryOverview.queryId
      - queryData.queryId
      - queryOverview.queryId
      - data.queryId
      - queryId (top-level)
    
    Returns:
        Query UUID string or None if not found.
    """
    if not snowvi_json or not isinstance(snowvi_json, dict):
        return None
    
    # Try multiple known paths for the query ID
    paths_to_try = [
        # Standard SnowVI format
        lambda d: d.get("queryData", {}).get("data", {}).get("globalInfo", {}).get("queryOverview", {}).get("queryId"),
        # Alternative paths
        lambda d: d.get("queryData", {}).get("queryId"),
        lambda d: d.get("queryData", {}).get("data", {}).get("queryId"),
        lambda d: d.get("queryOverview", {}).get("queryId"),
        lambda d: d.get("data", {}).get("queryId"),
        lambda d: d.get("queryId"),
        # Sometimes it's called 'uuid' instead
        lambda d: d.get("queryData", {}).get("data", {}).get("globalInfo", {}).get("queryOverview", {}).get("uuid"),
        lambda d: d.get("uuid"),
    ]
    
    for path_fn in paths_to_try:
        try:
            value = path_fn(snowvi_json)
            if value and isinstance(value, str):
                # Validate it looks like a UUID (basic check)
                if len(value) >= 32 and '-' in value:
                    return value
        except (KeyError, TypeError, AttributeError):
            continue
    
    return None


def extract_deployment_from_snowvi_json(snowvi_json: Any) -> Optional[str]:
    """
    Extract the deployment/region from a SnowVI JSON export.
    
    The deployment is typically found at:
      - queryData.data.globalInfo.queryOverview.deployment
      - queryData.region
      - deployment (top-level)
    
    Returns:
        Deployment string (e.g., 'PROD', 'VA3', 'AWS_US_WEST_2') or None.
    """
    if not snowvi_json or not isinstance(snowvi_json, dict):
        return None
    
    paths_to_try = [
        lambda d: d.get("queryData", {}).get("data", {}).get("globalInfo", {}).get("queryOverview", {}).get("deployment"),
        lambda d: d.get("queryData", {}).get("region"),
        lambda d: d.get("queryData", {}).get("deployment"),
        lambda d: d.get("deployment"),
        lambda d: d.get("region"),
    ]
    
    for path_fn in paths_to_try:
        try:
            value = path_fn(snowvi_json)
            if value and isinstance(value, str):
                return value.upper()
        except (KeyError, TypeError, AttributeError):
            continue
    
    return None

