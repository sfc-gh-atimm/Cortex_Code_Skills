"""
Smart loader for AFE Field Manual content.

Loads relevant field experience based on detected findings and workload type.
Token-efficient: Only loads content that's relevant to the current analysis.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set


def get_field_manual_context(
    findings: Dict[str, any],
    workload_type: str = "UNKNOWN",
    max_tokens: int = 2000,
    include_general: bool = True,
    snowvi_mode: str = "without"
) -> str:
    """
    Load relevant field manual snippets based on detected findings.
    
    Args:
        findings: Dict with 'errors', 'warnings', 'passed' from analyze_ht_best_practices()
        workload_type: OLTP, ANALYTIC, MIXED, UNKNOWN
        max_tokens: Maximum tokens to return (rough estimate: 1 token ≈ 4 chars)
        include_general: Whether to include general HT guidance
        snowvi_mode: "with" or "without" - when "with", filters out SnowVI confirmation recommendations
    
    Returns:
        str: Concatenated relevant guidance (markdown formatted)
    """
    manual_dir = Path(__file__).parent / "field_manual"
    context_parts = []
    
    if include_general:
        if workload_type == "ANALYTIC":
            context_parts.append(_load_section(
                manual_dir / "general/ht_sweet_spot.md",
                section_name="When NOT to Use Hybrid Tables",
                max_lines=30
            ))
        elif workload_type == "OLTP":
            context_parts.append(_load_section(
                manual_dir / "general/ht_sweet_spot.md",
                section_name="When to Use Hybrid Tables",
                max_lines=25
            ))
        elif workload_type == "MIXED":
            context_parts.append(_load_section(
                manual_dir / "general/ht_sweet_spot.md",
                section_name="Hybrid Architecture Pattern",
                max_lines=40
            ))
    
    all_findings = findings.get('errors', []) + findings.get('warnings', [])
    detected_rules = {f.get('rule', '') for f in all_findings if f.get('rule')}
    
    PRIORITY_FINDINGS = [
        'NO_BOUND_VARIABLES',
        'HT_REQUEST_THROTTLING',
        'FAULT_HANDLING_HIGH',
        'SCALAR_UDF_ON_HYBRID_TABLE',
        'ANALYTIC_WORKLOAD_ON_HT',
        'HT_WITHOUT_INDEXES',
        'HT_INDEXES_NOT_USED_PLAN',
        'PRIMARY_KEY_NOT_USED',
        'NO_INDEX_FOR_HOT_PREDICATES',
        'COMPOSITE_INDEX_MISALIGNED',
        'HT_INDEX_RANGE_SCAN',
        'HT_ANALYTIC_STORE_SCAN',
        'HT_PURGE_PATTERN_DETECTED',
        'SLOW_CTAS_LOAD',
        'BULK_DML_SHOULD_BE_CTAS',
        'NO_FILTERING',
        'CLIENT_SIDE_BOTTLENECK',
        'MIXED_HT_AND_STANDARD_TABLES',
        'WAREHOUSE_OVERSIZED_FOR_HT',
        'HT_INDEXES_NOT_USED_RUNTIME',
        'LOW_CARDINALITY_INDEX',
        'FULL_SORT_ON_HT',
    ]
    
    char_budget = max_tokens * 4
    current_chars = sum(len(p) for p in context_parts)
    
    sorted_rules = []
    for priority_rule in PRIORITY_FINDINGS:
        if priority_rule in detected_rules:
            sorted_rules.append(priority_rule)
    for rule in detected_rules:
        if rule not in sorted_rules:
            sorted_rules.append(rule)
    
    for rule in sorted_rules:
        if current_chars >= char_budget:
            break
        
        finding_path = manual_dir / f"findings/{rule}.md"
        if finding_path.exists():
            content = _load_file(finding_path, max_chars=char_budget - current_chars)
            if content:
                if snowvi_mode == "with":
                    content = _filter_snowvi_confirm_recs(content)
                context_parts.append(f"### Field Manual: {rule}\n{content}")
                current_chars += len(content) + 30
    
    return "\n\n".join(filter(None, context_parts))


def _load_section(
    filepath: Path,
    section_name: Optional[str] = None,
    max_lines: int = 50
) -> Optional[str]:
    """Load a section from a markdown file."""
    if not filepath.exists():
        return None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if not section_name:
            lines = content.split('\n')[:max_lines]
            return '\n'.join(lines)
        
        import re
        pattern = rf'^##\s*{re.escape(section_name)}\s*$'
        match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
        
        if not match:
            return None
        
        start = match.end()
        next_section = re.search(r'^##\s', content[start:], re.MULTILINE)
        
        if next_section:
            section_content = content[start:start + next_section.start()]
        else:
            section_content = content[start:]
        
        lines = section_content.strip().split('\n')[:max_lines]
        return '\n'.join(lines)
    except Exception:
        return None


def _load_file(filepath: Path, max_chars: int = 2000) -> Optional[str]:
    """Load a file with character limit."""
    if not filepath.exists():
        return None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n_[Content truncated for token efficiency]_"
        
        return content.strip()
    except Exception:
        return None


def _filter_snowvi_confirm_recs(content: str) -> str:
    """Filter out 'Confirm with SnowVI' style recommendations when SnowVI is available."""
    import re
    patterns_to_filter = [
        r'(?i)confirm\s+(?:this\s+)?with\s+snowvi',
        r'(?i)verify\s+(?:this\s+)?(?:in|with)\s+snowvi',
        r'(?i)check\s+snowvi\s+(?:to|for)',
        r'(?i)load\s+(?:the\s+)?snowvi\s+export',
    ]
    
    lines = content.split('\n')
    filtered_lines = []
    
    for line in lines:
        should_filter = any(re.search(p, line) for p in patterns_to_filter)
        if not should_filter:
            filtered_lines.append(line)
    
    return '\n'.join(filtered_lines)


def get_available_findings() -> Set[str]:
    """Return set of finding rule names that have field manual entries."""
    manual_dir = Path(__file__).parent / "field_manual" / "findings"
    if not manual_dir.exists():
        return set()
    
    return {p.stem.upper() for p in manual_dir.glob("*.md")}


def get_finding_guidance(rule_name: str) -> Optional[str]:
    """Load guidance for a specific finding rule."""
    manual_dir = Path(__file__).parent / "field_manual" / "findings"
    filepath = manual_dir / f"{rule_name.upper()}.md"
    
    if not filepath.exists():
        filepath = manual_dir / f"{rule_name}.md"
    
    return _load_file(filepath, max_chars=4000)
