"""
SQL Analysis for Hybrid Tables
Based on Glean's recommendations (00_GLEAN_output.md lines 655-945)
Enhanced with GLEAN feedback 2024-12-03
"""

from .parser import ParsedQuery, parse_sql
from .metadata import SnowflakeMetadata, LocalMetadata
from .rules import analyze_query
from .coverage import score_indexes_for_tables
from .rules_enhanced import (
    analyze_query_enhanced,
    generate_index_ddl,
    check_no_index_coverage,
    check_order_by_limit_conditional,
    check_mixed_ht_standard_tables,
    rank_primary_cause
)
from .ht_query_optimization import (
    analyze_ht_query_optimization,
    detect_bound_variables,
    analyze_create_index_statement,
    is_create_index_statement,
    analyze_copy_into_stage_from_ht,
    is_copy_into_stage,
    detect_ctas_pk_violation,
    is_ctas_hybrid_table,
    is_ddl_statement,
    get_ddl_type
)
from .composite_index_analysis import (
    analyze_composite_indexes,
    prefix_eq_coverage,
    summarize_composite_index_issues
)

__all__ = [
    'ParsedQuery',
    'parse_sql',
    'SnowflakeMetadata',
    'LocalMetadata',
    'analyze_query',
    'score_indexes_for_tables',
    'analyze_query_enhanced',
    'generate_index_ddl',
    'check_no_index_coverage',
    'check_order_by_limit_conditional',
    'check_mixed_ht_standard_tables',
    'rank_primary_cause',
    'analyze_ht_query_optimization',
    'detect_bound_variables',
    'analyze_create_index_statement',
    'is_create_index_statement',
    'analyze_copy_into_stage_from_ht',
    'is_copy_into_stage',
    'detect_ctas_pk_violation',
    'is_ctas_hybrid_table',
    'is_ddl_statement',
    'get_ddl_type',
    'analyze_composite_indexes',
    'prefix_eq_coverage',
    'summarize_composite_index_issues',
]

