"""
FAQ Library for Hybrid Table Query Analyzer

This library contains field-validated answers to frequently asked questions about
each finding/recommendation. These can be:
  - Embedded in Field Manual markdown files
  - Rendered in the UI when AFEs click "Why is this recommending X?"
  - Used in training materials and documentation
  - Included in JSON output for automation

Each FAQ is keyed by the rule name and includes question + detailed answer.
"""

from typing import List, Dict, Any, Optional


FINDING_FAQS = {
    "NO_INDEX_FOR_HOT_PREDICATES": [{
        "question": "My customer says they do have indexes. Why are you recommending creating indexes?",
        "answer": """There are three different things at play:

**1) "An index exists" vs "an index helps this query"**
This finding checks whether there is an index that actually lines up with the predicates used by this specific query. If the query filters on TENANT_ID and ORDER_ID but the only index is on STATUS, the existing index doesn't help.

**2) "Index exists" vs "index is used effectively at runtime"**
Even when an index is defined on the right columns, the optimizer may not use it because of:
- Functions or casts on indexed columns (e.g. `UPPER(email)`, `CAST(id AS STRING)`)
- Composite index order not matching the leftmost equality predicates
- Very low-cardinality leading columns (e.g. STATUS)

**3) Different environment / table / version**
The customer may be looking at a dev table with indexes, while the slow query is hitting a prod table without them.

**Next Steps:**
1. Confirm you're looking at the same database/schema/table as the UUID
2. Compare the WHERE clause to the index definitions and column order
3. Remove functions/casts on indexed columns and fix type mismatches"""
    }],
    
    "HT_INDEXES_NOT_USED_RUNTIME": [{
        "question": "My customer says they do have indexes. Why are you recommending creating indexes?",
        "answer": """This finding checks runtime behavior, not just index existence. Even when an index is defined, the optimizer may not use it because of:
- Functions or casts on indexed columns
- Composite index order not matching the leftmost equality predicates
- Very low-cardinality leading columns

**Next Steps:**
1. Confirm the same database/schema/table as the UUID
2. Compare WHERE clause to index definitions and column order
3. Remove functions/casts on indexed columns"""
    }],
    
    "COMPOSITE_INDEX_MISALIGNED": [{
        "question": "Why are you telling us to change composite index order? That sounds risky.",
        "answer": """Changing composite index order doesn't change table data; it only changes how lookups are accelerated:

- HT indexes are most effective when predicates match a left-aligned prefix of the index
- When the leading columns don't line up with the equality predicates, the index behaves more like a range scan

**Safe Rollout Pattern:**
1. Create a new index with the proposed order
2. Validate performance on representative traffic
3. Drop the old index only after you're confident the new one is serving the hot path"""
    }],
    
    "HT_WITHOUT_INDEXES": [{
        "question": "Why do we need another index? Won't this hurt write performance and storage?",
        "answer": """Yes, every additional HT index has a write and storage cost; that's why we only recommend them for hot predicates on latency-sensitive paths.

**In Practice:**
- Adding one or two well-chosen indexes on high-cardinality predicates usually reduces read cost enough to pay for the index maintenance
- If the table is extremely write-heavy and the access pattern isn't selective, that's usually a smell that HT may not be the right engine

**Good Pattern:**
- Keep a small number of highly targeted indexes for operational paths
- Push analytic/reporting workloads onto standard tables / MVs"""
    }],
    
    "ANALYTIC_WORKLOAD_ON_HT": [{
        "question": "Why are you telling me this looks like an analytic workload? HT is marketed as HTAP.",
        "answer": """HTAP doesn't mean "anything goes"; it means:

- HT row-store is optimized for high-QPS, low-latency point / narrow-range operations
- Analytic engines (standard tables, DTs, MVs) are optimized for large scans, joins, and aggregations

The analyzer calls this out as analytic when it sees patterns like:
- Large result sets (10k+ rows) plus GROUP BY, windows, or wide joins
- Long ORDER BY + no LIMIT (full-result sort)
- HT being read from the analytic/object store path

**The Goal:**
Not to forbid those queries, but to highlight that you'll usually get cheaper, more predictable performance by moving that part to standard tables."""
    }],
    
    "NO_BOUND_VARIABLES": [{
        "question": "Why are you saying there are no bound variables? Our ORM says it uses prepared statements.",
        "answer": """The analyzer looks at what reaches Snowflake, not what the ORM claims.

If each execution shows a different QUERY_TEXT and no stable QUERY_PARAMETERIZED_HASH, it means literals are being inlined into the SQL.

**Common reasons:**
- Some ORMs only parameterize certain parts of the query
- Custom query builders string-concatenate WHERE conditions
- Driver options disable parameterization

**The Field Fix:**
1. Inspect the actual SQL hitting Snowflake (Snowsight / QUERY_HISTORY)
2. Check QUERY_PARAMETERIZED_HASH patterns: if every execution has a unique hash, it's not truly parameterized
3. Adjust the ORM/driver config or use explicit prepared statements"""
    }],
    
    "CLIENT_SIDE_BOTTLENECK": [{
        "question": "Why is the tool blaming the client? My query 'feels' slow in the UI.",
        "answer": """The tool compares Snowhouse execution breakdown to total wall-clock time.

If engine time is small but total duration is large and dominated by client receive/transfer, then from Snowflake's perspective the query ran quickly.

**Typical Causes:**
- Large result sets pulled into a browser or Jupyter notebook
- High latency / low bandwidth between client and region
- Driver fetch size or client processing overhead

**The Fix is NOT "tune HT"; it's to:**
1. Reduce the result set size (add filters, LIMIT, pagination)
2. Move heavy post-processing closer to Snowflake
3. Run perf testing tools (like JMeter) in region, not from a laptop"""
    }],
    
    "HT_REQUEST_THROTTLING": [{
        "question": "What does HT request throttling mean? How do I fix it?",
        "answer": """Hybrid Table request throttling means the account/database is hitting HT request quotas under load.

This is a capacity/quota issue, not a query optimization issue.

**The Fix:**
1. Request an increased and/or isolated Hybrid Table quota for the target database
2. Verify you are not issuing unnecessary I/O-heavy queries on HT
3. Consider separating operational HT workloads from analytic workloads"""
    }],
    
    "WAREHOUSE_OVERSIZED_FOR_HT": [{
        "question": "Why are you suggesting XS warehouses for HT? Bigger should be faster, right?",
        "answer": """For HT row-store workloads, bigger warehouses don't significantly reduce single-query latency:

- Latency is dominated by a small number of KV probes and index operations, not massive parallel scans
- "Bigger" mostly buys you more parallelism, which helps scan-heavy analytics far more than point lookups

**Recommended Pattern:**
- Start HT workloads on XS (or S) with multi-cluster for concurrency
- Use larger warehouses for analytic workloads (standard tables / MVs)"""
    }],
    
    "HT_PURGE_PATTERN_DETECTED": [{
        "question": "Why can't I just run a single DELETE statement to clean up old data?",
        "answer": """For small deletes (<1,000 rows), a single DELETE is fine. But for large purge operations (10,000+ rows):

- Unbatched deletes can trigger HT_REQUEST_THROTTLING
- They block concurrent OLTP queries while processing
- All-or-nothing execution increases rollback risk

**Batching with QUALIFY ROW_NUMBER() <= 1000** gives you:
- Predictable per-batch latency (<1 second per batch)
- No throttling impact
- Progress tracking and easier recovery"""
    }],
    
    "BULK_DML_SHOULD_BE_CTAS": [{
        "question": "Why are you recommending CTAS instead of a big MERGE/INSERT?",
        "answer": """MERGE is great for incremental, row-level changes. Once you're touching millions of rows:

- MERGE/INSERT has to maintain row structure and indexes row by row
- CTAS can use bulk, append-oriented paths that are typically faster

**You can often:**
1. Preserve your business logic in a CTAS query
2. Use `ALTER TABLE ... SWAP WITH ...` for an atomic cutover

This maintains correctness while giving you more predictable bulk performance."""
    }],
    
    "MIXED_HT_AND_STANDARD_TABLES": [{
        "question": "Why is mixing Hybrid Tables and standard tables in one query a problem?",
        "answer": """When you join HT with standard/FDN tables, several HT fast-path optimizations don't apply:

- The execution plan needs to accommodate both row-store and columnar access patterns
- HT-specific scheduling and short-query optimizations become less effective

**Best Practices:**
1. Keep the operational lookup on HT as a separate, tight query
2. Use that result as input to analytic queries on standard tables"""
    }],
    
    "FULL_SORT_ON_HT": [{
        "question": "Why is ORDER BY without LIMIT a problem on Hybrid Tables?",
        "answer": """Sorting itself isn't the problem; sorting everything is:

- A full sort forces the engine to materialize and order many rows in memory
- Most APIs/UIs only display a page or two; the rest is wasted effort

**The Recommendation:**
1. For interactive UI/API paths, add `ORDER BY ... LIMIT N` (or keyset pagination)
2. For full-history exports, move that path to a standard table instead"""
    }],
}


def get_faq_for_finding(rule_name: str) -> List[Dict[str, str]]:
    """Get FAQ entries for a specific finding rule."""
    return FINDING_FAQS.get(rule_name.upper(), [])


def get_all_faqs_for_findings(finding_rules: List[str]) -> Dict[str, List[Dict[str, str]]]:
    """Get FAQs for multiple finding rules."""
    result = {}
    for rule in finding_rules:
        faqs = get_faq_for_finding(rule)
        if faqs:
            result[rule.upper()] = faqs
    return result


def render_faq_markdown(rule_name: str) -> str:
    """Render FAQ entries as markdown."""
    faqs = get_faq_for_finding(rule_name)
    if not faqs:
        return ""
    
    lines = ["## Common Questions / Objections\n"]
    for faq in faqs:
        lines.append(f"### Q: {faq['question']}\n")
        lines.append(f"{faq['answer']}\n")
        lines.append("---\n")
    
    return "\n".join(lines)


def get_available_faq_rules() -> List[str]:
    """Return list of all rules that have FAQs."""
    return list(FINDING_FAQS.keys())
