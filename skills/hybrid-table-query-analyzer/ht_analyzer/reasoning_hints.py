"""
Reasoning Hints - Domain Interaction Rules

These hints help the AI understand cross-finding interactions and causal chains
specific to Hybrid Tables. They force explicit "because → mechanism → therefore" reasoning.

These are injected into the Analysis prompt to prevent generic recommendations
and ensure the AI explains WHY findings appear together.
"""

from typing import List, Set

REASONING_HINTS = [
    "If NO_BOUND_VARIABLES is true and QUERY_PARAMETERIZED_HASH reuse is low and COMPILATION_TIME is high, "
    "then enabling bound variables should increase plan cache reuse and often unlock stable, index-seeking plans "
    "on HT (lower p95/p99, bytes/row). Fix binding BEFORE creating new indexes.",
    
    "If best_eq_prefix=0 but predicates overlap indexed columns, the leading column order likely mismatches; "
    "reordering to align leftmost equality predicates improves selectivity and bytes/row. "
    "Don't create new indexes - REORDER existing ones.",
    
    "If ORDER BY without LIMIT, large result sets, or GROUP BY exist, this is analytic behavior; "
    "moving to standard tables/MVs/DTs reduces scan and sort costs and frees HT capacity. "
    "HT indexes won't help analytic patterns.",
    
    "For HT point lookups, larger warehouses seldom reduce latency; XS with multi-cluster is preferred. "
    "Scale-up helps analytic scans, not row-store probes. Bigger ≠ faster for HT.",
    
    "If client_receive_ms is a large share of TOTAL_DURATION, or client_type = interactive_ui (Snowsight), "
    "reduce transfer size (add filters, LIMIT/pagination) or run representative perf test (JMeter in-region). "
    "HT tuning (indexes, warehouse) won't fix client/network bottlenecks.",
    
    "If functions/casts on indexed columns (UPPER, TRIM, CAST) are present and HT_INDEXES_NOT_USED_RUNTIME "
    "with high bytes_per_row, make predicates sargable first; avoid new indexes. "
    "The optimizer can't use indexes when predicates aren't sargable.",
    
    "If workload_type == MIXED or join of HT with standard/FDN tables is detected, "
    "separate the operational HT lookup from analytic joins. Many HT fast-path optimizations "
    "(short-query scheduling, HT-specific execution paths) are disabled when mixed with other table types.",
    
    "If distinct count for leading column ≤ 100 (LOW_CARDINALITY_INDEX), "
    "don't recommend indexes led by low-cardinality columns; recommend high-cardinality leading keys "
    "(IDs, tenant keys) or move analytics to columnar structures.",
    
    "If (ROWS_INSERTED + ROWS_UPDATED) is large and duration is long (SLOW_CTAS_LOAD or BULK_DML_SHOULD_BE_CTAS), "
    "recommend CTAS+swap patterns; avoid index tuning to 'fix' bulk rewrite time. "
    "Index maintenance during large DML is the bottleneck, not query optimization.",
    
    "If FDB throttling or HT throttled ms/count in telemetry (HT_REQUEST_THROTTLING), "
    "prioritize quota increase/isolation and HT I/O reduction; no index tuning as first-line fix. "
    "Quota pressure indicates resource contention, not index design issues.",
    
    "If ORDER BY with rows_produced well above UI needs (FULL_SORT_ON_HT), "
    "first action must be top-K/pagination (ORDER BY ... LIMIT N) for interactive calls; "
    "no index prescriptions until top-K validated. Sorting 1M rows to show 10 is the problem.",
    
    "If for a QUERY_PARAMETERIZED_HASH, p99/p50 ratio > 5 across days, "
    "propose plan-stabilizing refactors (binding, sargability, simplifications), not new indexes first. "
    "High variance indicates unstable plan selection, not missing indexes.",
    
    "If large projected column set or SELECT * with high bytes_per_row relative to a small result set, "
    "recommend narrowing projection and only selecting needed columns; avoid index prescriptions first. "
    "Returning many columns inflates I/O regardless of index design.",
    
    "If writes >> reads and many indexes on HT, index maintenance overhead is suspected. "
    "Recommend index rationalization (drop unused/low value indexes) before adding any new ones. "
    "Too many indexes can slow writes more than they help reads.",
]

POLICY_PRIORITY = [
    "NO_BOUND_VARIABLES",
    "ANALYTIC_WORKLOAD_ON_HT",
    "CLIENT_SIDE_BOTTLENECK",
    "HT_REQUEST_THROTTLING",
    "UUID_ONLY_NO_INDEXES",
    "INDEXES_EXIST_NOT_USED",
    "COMPOSITE_INDEX_MISALIGNED",
    "MIXED_HT_AND_STANDARD_TABLES",
    "LOW_CARDINALITY_INDEX",
    "BULK_DML_SHOULD_BE_CTAS",
]


def get_reasoning_hints_text(max_tokens: int = 800) -> str:
    """Return reasoning hints as formatted text for injection into prompts."""
    lines = ["**Domain Interaction Rules:**"]
    char_budget = max_tokens * 4
    current_chars = 0
    
    for hint in REASONING_HINTS:
        if current_chars + len(hint) + 10 > char_budget:
            break
        lines.append(f"- {hint}")
        current_chars += len(hint) + 10
    
    return "\n".join(lines)


def get_applicable_hints(finding_ids: Set[str]) -> List[str]:
    """Return only hints relevant to the detected findings."""
    applicable = []
    finding_upper = {f.upper() for f in finding_ids}
    
    hint_triggers = {
        "NO_BOUND_VARIABLES": [0],
        "COMPOSITE_INDEX_MISALIGNED": [1],
        "ANALYTIC_WORKLOAD_ON_HT": [2],
        "CLIENT_SIDE_BOTTLENECK": [4],
        "HT_INDEXES_NOT_USED_RUNTIME": [5],
        "MIXED_HT_AND_STANDARD_TABLES": [6],
        "LOW_CARDINALITY_INDEX": [7],
        "SLOW_CTAS_LOAD": [8],
        "BULK_DML_SHOULD_BE_CTAS": [8],
        "HT_REQUEST_THROTTLING": [9],
        "FULL_SORT_ON_HT": [10],
    }
    
    added_indices = set()
    for finding in finding_upper:
        if finding in hint_triggers:
            for idx in hint_triggers[finding]:
                if idx not in added_indices and idx < len(REASONING_HINTS):
                    applicable.append(REASONING_HINTS[idx])
                    added_indices.add(idx)
    
    return applicable


def get_prioritized_findings(finding_ids: Set[str]) -> List[str]:
    """Return findings sorted by policy priority."""
    finding_upper = {f.upper() for f in finding_ids}
    prioritized = []
    
    for priority_finding in POLICY_PRIORITY:
        if priority_finding in finding_upper:
            prioritized.append(priority_finding)
    
    for finding in sorted(finding_upper):
        if finding not in prioritized:
            prioritized.append(finding)
    
    return prioritized
