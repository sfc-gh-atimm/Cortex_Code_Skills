"""
Prompt templates for LLM calls used by the Hybrid Table Query Analyzer skill.

These are designed to mirror the behavior of the Streamlit app:
- LLM acts as an explainer and ranker, NOT as an unconstrained actor.
- All concrete actions must come from candidate_actions.
"""

from textwrap import dedent


ASE_SYSTEM_PROMPT = dedent("""
    You are a senior Snowflake Solutions Architect helping another Snowflake SE
    diagnose and remediate slow Hybrid Table queries.

    You MUST:
    - Use ONLY the candidate actions provided in the input JSON.
    - Never invent DDL, configuration changes, or indexes that are not present
      in candidate_actions.
    - Prioritize low-risk, high-impact changes.
    - Speak directly to an internal SE, NOT to the customer.
    - Keep recommendations concise and tactical (3–7 bullets).

    If you reference a specific action, always include its `id` in backticks,
    like `ADD_INDEX_HT_OFFERS_OFFER_CODE` so it can be automated later.
""").strip()


ASE_USER_PROMPT_TEMPLATE = dedent("""
    Analyze the following Hybrid Table query run and produce next steps for an
    Account SE.

    Context:
    - Query UUID: {query_uuid}
    - Deployment: {deployment}

    Metadata summary:
    ```json
    {metadata_json}
    ```

    Best-practices findings:
    ```json
    {bp_findings_json}
    ```

    SQL findings:
    ```json
    {sql_findings_json}
    ```

    Hybrid Table coverage:
    ```json
    {coverage_json}
    ```

    History / anomaly context:
    ```json
    {history_context_json}
    ```

    Candidate actions (you may ONLY select from these):
    ```json
    {candidate_actions_json}
    ```
    {reasoning_hints_section}
    {field_manual_section}
    {comparison_section}
    Instructions:
    1. Start with a one-sentence diagnosis of the main issue.
    2. Then produce a short, numbered list of 3–7 concrete next steps
       the SE should take.
    3. Every step MUST either:
       - Reference an existing `candidate_action.id`, or
       - Be a pure investigative/communication step (e.g. "confirm workload
         latency SLO with customer").
    4. Do NOT generate raw SQL beyond what is provided in `candidate_actions`.
    5. When multiple findings exist, follow the priority order from reasoning hints.
""").strip()


COMPARISON_SECTION_TEMPLATE = dedent("""
    Comparison Analysis:
    This is a before/after comparison between two query executions.
    - Primary root cause: {primary_cause} ({primary_cause_description})
    - Secondary factor: {secondary_cause}
    
    Metric differences:
    {diff_summary}
    
    Focus your analysis on explaining WHY the performance differs between runs,
    using the pre-classified root cause as your starting point.
""").strip()


REASONING_HINTS_SECTION_TEMPLATE = dedent("""
    Domain Reasoning Hints (apply these rules when explaining findings):
    {hints}
""").strip()


FIELD_MANUAL_SECTION_TEMPLATE = dedent("""
    Field Manual Context (use this context to inform your recommendations):
    {field_manual_context}
""").strip()