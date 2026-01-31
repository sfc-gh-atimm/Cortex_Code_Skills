#!/usr/bin/env python3
"""
SnowVI JSON Parser for Hybrid Table Query Analysis

This module parses SnowVI JSON exports to extract:
- Query metadata and SQL text
- Scan operators and index usage
- FDB performance stats
- Best practice violations
"""

import json
import re
from typing import Any
from dataclasses import dataclass, field


@dataclass
class ScanOperator:
    """Represents a scan operator from the query plan."""
    rso_id: int
    rso_type: str  # HybridKvTableScan, TableScan, etc.
    table_id: int
    table_name: str
    logical_id: int
    columns: list[dict]
    filter_push: list[dict]  # Pushed predicates
    scan_mode: int
    has_filter: bool = False


@dataclass
class HybridTableScanStats:
    """Performance stats for a Hybrid Table scan."""
    rso_name: str
    rso_id: int
    table_id: int
    exec_time_us: int
    num_filtered_rows: int
    total_num_rows: int
    total_num_bytes: int
    processed_ranges: int
    columnar_cache_bytes: int
    skew_percent: int


@dataclass 
class FdbStats:
    """FoundationDB I/O statistics."""
    db_id: int
    io_bytes: int
    compaction_io_bytes: int
    execution_us: int
    throttling_us: int


@dataclass
class SnowVIAnalysis:
    """Complete analysis results from SnowVI JSON."""
    query_id: str
    sql_text: str
    database_name: str
    schema_name: str
    account_name: str
    user_name: str
    
    scan_operators: list[ScanOperator] = field(default_factory=list)
    ht_scan_stats: list[HybridTableScanStats] = field(default_factory=list)
    fdb_stats: list[FdbStats] = field(default_factory=list)
    
    tables: dict[int, str] = field(default_factory=dict)  # table_id -> name
    columns: dict[int, dict] = field(default_factory=dict)  # col_id -> info
    
    has_literal_values: bool = False
    literal_examples: list[str] = field(default_factory=list)
    has_cte_with_join: bool = False
    
    total_fdb_io_bytes: int = 0
    total_fdb_execution_us: int = 0


def parse_snowvi_json(file_path: str) -> SnowVIAnalysis:
    """Parse a SnowVI JSON export file."""
    with open(file_path) as f:
        d = json.load(f)
    
    # Extract query metadata
    data = d.get('queryData', {}).get('data', {})
    gi = data.get('globalInfo', {})
    overview = gi.get('queryOverview', {})
    session = gi.get('session', {})
    
    analysis = SnowVIAnalysis(
        query_id=overview.get('id', d.get('queryId', '')),
        sql_text=overview.get('sqlText', ''),
        database_name=gi.get('databaseName', ''),
        schema_name=gi.get('schemaName', ''),
        account_name=session.get('accountName', ''),
        user_name=session.get('userName', ''),
    )
    
    # Parse SDL structure for scan operators
    sdls = d.get('sdls', {})
    _parse_sdls(sdls, analysis)
    
    # Parse worker data for performance stats
    workers = d.get('workersData', [])
    _parse_workers(workers, analysis)
    
    # Parse process stats for FDB metrics
    processes = d.get('processes', data.get('processes', []))
    _parse_processes(processes, analysis)
    
    # Analyze SQL for best practices
    _analyze_sql_best_practices(analysis)
    
    return analysis


def _parse_sdls(sdls: dict, analysis: SnowVIAnalysis) -> None:
    """Parse SDL structure for scan operators and catalog info."""
    for step_id, step in sdls.items():
        # Extract table catalog
        catalog = step.get('catalog', {})
        for obj in catalog.get('objects', []):
            table_id = obj.get('id')
            table_name = obj.get('name', '')
            if table_id:
                analysis.tables[table_id] = table_name
        
        # Extract column catalog
        for col in catalog.get('columns', []):
            col_id = col.get('id')
            if col_id:
                analysis.columns[col_id] = {
                    'label': col.get('label', ''),
                    'logical_type': col.get('logicalType', ''),
                    'physical_type': col.get('physicalType', ''),
                    'nullable': col.get('nullable', True),
                }
        
        # Extract RSOs (scan operators)
        for rso in step.get('rsos', []):
            rso_type = rso.get('type', '')
            if 'Scan' in rso_type:
                table_id = rso.get('object', 0)
                table_name = analysis.tables.get(table_id, f'table_{table_id}')
                
                scan_op = ScanOperator(
                    rso_id=rso.get('id', 0),
                    rso_type=rso_type,
                    table_id=table_id,
                    table_name=table_name,
                    logical_id=rso.get('logicalId', 0),
                    columns=rso.get('columns', []),
                    filter_push=rso.get('filterPush', []),
                    scan_mode=rso.get('blobScanMode', 0),
                    has_filter=len(rso.get('filterPush', [])) > 0,
                )
                analysis.scan_operators.append(scan_op)


def _parse_workers(workers: list, analysis: SnowVIAnalysis) -> None:
    """Parse worker data for additional SDL info."""
    for worker in workers:
        worker_data = worker.get('data', {})
        query_sdl = worker_data.get('querySDL', {})
        
        # Get catalog from worker SDL if not already populated
        if not analysis.tables:
            catalog = query_sdl.get('catalog', {})
            for obj in catalog.get('objects', []):
                table_id = obj.get('id')
                table_name = obj.get('name', '')
                if table_id:
                    analysis.tables[table_id] = table_name


def _parse_processes(processes: list, analysis: SnowVIAnalysis) -> None:
    """Parse process stats for FDB and HT scan performance."""
    for proc in processes:
        last_report = proc.get('lastReport') or {}
        
        # Extract FDB stats
        for fdb in last_report.get('snowtramFdbStats') or []:
            stats = FdbStats(
                db_id=fdb.get('dbId', 0),
                io_bytes=fdb.get('fdbIoBytes', 0) or 0,
                compaction_io_bytes=fdb.get('fdbCompactionIoBytes', 0) or 0,
                execution_us=fdb.get('fdbExecutionUs', 0) or 0,
                throttling_us=fdb.get('fdbThrottlingUs', 0) or 0,
            )
            analysis.fdb_stats.append(stats)
            analysis.total_fdb_io_bytes += stats.io_bytes
            analysis.total_fdb_execution_us += stats.execution_us
        
        # Extract HT scan performance stats
        for perf in last_report.get('xpRsoPerfAnalyzerStats') or []:
            if perf.get('statType') == 'hybridTableScanPerformanceStats':
                ht_stats = HybridTableScanStats(
                    rso_name=perf.get('rso', ''),
                    rso_id=perf.get('rsoId', 0),
                    table_id=perf.get('tableId', 0),
                    exec_time_us=perf.get('execTime', 0),
                    num_filtered_rows=perf.get('numFilteredRows', 0),
                    total_num_rows=perf.get('totalNumRows', 0),
                    total_num_bytes=perf.get('totalNumBytes', 0),
                    processed_ranges=perf.get('processedRanges', 0),
                    columnar_cache_bytes=perf.get('columnarCacheParquetBytes', 0),
                    skew_percent=perf.get('skew', 0),
                )
                analysis.ht_scan_stats.append(ht_stats)


def _analyze_sql_best_practices(analysis: SnowVIAnalysis) -> None:
    """Analyze SQL text for best practice violations."""
    sql = analysis.sql_text
    sql_upper = sql.upper()
    
    # Check 1: Literal values in predicates
    string_literals = re.findall(r"(\w+)\s*=\s*'([^']+)'", sql)
    number_literals = re.findall(r"(\w+)\s*=\s*(\d+)(?!\d*-)", sql)
    
    if string_literals or number_literals:
        analysis.has_literal_values = True
        for col, val in string_literals[:5]:
            analysis.literal_examples.append(f"{col} = '{val}'")
        for col, val in number_literals[:5]:
            analysis.literal_examples.append(f"{col} = {val}")
    
    # Check 2: CTE with JOIN
    has_cte = "WITH " in sql_upper and " AS " in sql_upper
    has_join = " JOIN " in sql_upper
    analysis.has_cte_with_join = has_cte and has_join


def get_scan_summary(analysis: SnowVIAnalysis) -> list[dict]:
    """Get summary of scan operators with index usage info."""
    summary = []
    for scan in analysis.scan_operators:
        summary.append({
            'type': scan.rso_type,
            'table': scan.table_name,
            'has_filter_pushdown': scan.has_filter,
            'filter_count': len(scan.filter_push),
            'is_hybrid_table': 'Hybrid' in scan.rso_type or 'Kv' in scan.rso_type,
        })
    return summary


def get_fdb_summary(analysis: SnowVIAnalysis) -> dict:
    """Get summary of FDB statistics."""
    return {
        'total_io_bytes': analysis.total_fdb_io_bytes,
        'total_execution_us': analysis.total_fdb_execution_us,
        'total_execution_ms': analysis.total_fdb_execution_us / 1000,
        'worker_count': len(analysis.fdb_stats),
    }


def get_ht_scan_summary(analysis: SnowVIAnalysis) -> list[dict]:
    """Get summary of Hybrid Table scan performance."""
    summary = []
    for ht in analysis.ht_scan_stats:
        table_name = analysis.tables.get(ht.table_id, f'table_{ht.table_id}')
        summary.append({
            'rso': ht.rso_name,
            'table': table_name,
            'exec_time_ms': ht.exec_time_us / 1000,
            'rows_scanned': ht.total_num_rows,
            'rows_returned': ht.num_filtered_rows,
            'selectivity': ht.num_filtered_rows / ht.total_num_rows if ht.total_num_rows > 0 else 0,
            'bytes_scanned': ht.total_num_bytes,
            'ranges_processed': ht.processed_ranges,
            'cache_bytes': ht.columnar_cache_bytes,
            'skew_percent': ht.skew_percent,
        })
    return summary


def format_analysis_report(analysis: SnowVIAnalysis) -> str:
    """Format the analysis as a readable report."""
    lines = []
    
    lines.append("## SnowVI Analysis Report")
    lines.append(f"\n**Query ID:** `{analysis.query_id}`")
    lines.append(f"**Database:** {analysis.database_name}")
    lines.append(f"**Account:** {analysis.account_name}")
    lines.append(f"**User:** {analysis.user_name}")
    
    # Scan operators
    lines.append("\n### Scan Operators")
    for scan in get_scan_summary(analysis):
        icon = "✅" if scan['has_filter_pushdown'] else "⚠️"
        ht_tag = " [HT]" if scan['is_hybrid_table'] else ""
        lines.append(f"- {icon} `{scan['type']}`{ht_tag} on `{scan['table']}`")
        if scan['has_filter_pushdown']:
            lines.append(f"  - Filter pushdown: {scan['filter_count']} predicate(s)")
    
    # HT Scan Performance
    if analysis.ht_scan_stats:
        lines.append("\n### Hybrid Table Scan Performance")
        for ht in get_ht_scan_summary(analysis):
            lines.append(f"- **{ht['rso']}** on `{ht['table']}`")
            lines.append(f"  - Execution: {ht['exec_time_ms']:.2f} ms")
            lines.append(f"  - Rows: {ht['rows_returned']:,} / {ht['rows_scanned']:,} ({ht['selectivity']:.1%} selectivity)")
            lines.append(f"  - Ranges: {ht['ranges_processed']}, Skew: {ht['skew_percent']}%")
    
    # FDB Stats
    fdb = get_fdb_summary(analysis)
    if fdb['total_execution_us'] > 0:
        lines.append("\n### FDB Statistics")
        lines.append(f"- Total I/O: {fdb['total_io_bytes']:,} bytes")
        lines.append(f"- Total Execution: {fdb['total_execution_ms']:.2f} ms")
        lines.append(f"- Workers: {fdb['worker_count']}")
    
    # Best Practices
    lines.append("\n### Best Practice Checks")
    if analysis.has_literal_values:
        lines.append("⚠️ **Literal values in predicates:**")
        for ex in analysis.literal_examples[:3]:
            lines.append(f"  - `{ex}`")
    else:
        lines.append("✅ No literal values detected (using bind parameters)")
    
    if analysis.has_cte_with_join:
        lines.append("⚠️ **CTE with JOIN detected** - FK optimization may be bypassed")
    else:
        lines.append("✅ No CTE+JOIN pattern detected")
    
    return "\n".join(lines)


# CLI entry point
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python snowvi_parser.py <path_to_snowvi_json>")
        sys.exit(1)
    
    analysis = parse_snowvi_json(sys.argv[1])
    print(format_analysis_report(analysis))
