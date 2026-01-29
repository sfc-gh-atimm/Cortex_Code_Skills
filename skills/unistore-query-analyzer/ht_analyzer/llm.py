"""
Thin helpers that call SNOWFLAKE.CORTEX.COMPLETE (via Snowpark or SQL)
using the prompt templates.
"""

import json
from typing import Any, Dict, List, Optional

from .llm_prompts import (
    ASE_SYSTEM_PROMPT,
    ASE_USER_PROMPT_TEMPLATE,
    COMPARISON_SECTION_TEMPLATE,
    REASONING_HINTS_SECTION_TEMPLATE,
    FIELD_MANUAL_SECTION_TEMPLATE,
)

_session = None

ESSENTIAL_METADATA_FIELDS = {
    "QUERY_ID",
    "QUERY_TEXT",
    "TOTAL_ELAPSED_TIME",
    "TOTAL_DURATION",
    "DUR_COMPILING",
    "DUR_GS_EXECUTING",
    "DUR_XP_EXECUTING",
    "COMPILATION_TIME",
    "EXECUTION_TIME",
    "ROWS_PRODUCED",
    "BYTES_SCANNED",
    "ERROR_CODE",
    "ERROR_MESSAGE",
    "ACCESS_KV_TABLE",
    "FDB_IO_BYTES",
    "SNOWTRAM_FDB_IO_BYTES",
    "QUERY_TYPE",
    "EXECUTION_STATUS",
    "WAREHOUSE_NAME",
    "CACHEDPLANID",
}


def _slim_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Extract only essential fields for LLM prompt to reduce token usage."""
    return {k: v for k, v in metadata.items() if k in ESSENTIAL_METADATA_FIELDS}


def set_session(session):
    """Set the Snowpark session for Cortex calls."""
    global _session
    _session = session


def call_cortex_complete(system_prompt: str, user_prompt: str, model: str = "claude-3-5-sonnet") -> str:
    """
    Call SNOWFLAKE.CORTEX.COMPLETE using the module's session.
    """
    if _session is None:
        raise RuntimeError("LLM session not set. Call set_session() first.")
    
    # Build the messages array for Cortex COMPLETE conversation format
    # When using options, prompt must be an array of role/content objects
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    
    # Execute via SQL with options (empty object) to enable conversation mode
    messages_json = json.dumps(messages)
    sql = f"""
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
            '{model}',
            PARSE_JSON($${messages_json}$$),
            {{}}
        ) AS result
    """
    
    result = _session.sql(sql).collect()
    if result and len(result) > 0:
        # Response is JSON object with choices[0].messages containing the text
        response_str = result[0]["RESULT"]
        try:
            response_obj = json.loads(response_str)
            return response_obj.get("choices", [{}])[0].get("messages", "")
        except (json.JSONDecodeError, IndexError, KeyError):
            return response_str
    return ""


def generate_next_steps_for_ase(analysis_features: Dict[str, Any],
                                candidate_actions: List[Dict[str, Any]]) -> str:
    """
    Build the ASE prompt and call Cortex to get next steps.
    Uses slimmed-down metadata to reduce token usage.
    Includes field manual context and reasoning hints when available.
    """
    full_metadata = analysis_features.get("metadata", {})
    slim_metadata = _slim_metadata(full_metadata)
    
    metadata_json = json.dumps(slim_metadata, indent=2, default=str)
    bp_findings_json = json.dumps(analysis_features.get("bp_findings", {}), indent=2, default=str)
    sql_findings_json = json.dumps(analysis_features.get("sql_findings", []), indent=2, default=str)
    coverage_json = json.dumps(analysis_features.get("coverage", []), indent=2, default=str)
    history_context_json = json.dumps(analysis_features.get("history_context", {}), indent=2, default=str)
    candidate_actions_json = json.dumps(candidate_actions, indent=2, default=str)

    reasoning_hints_section = ""
    hints = analysis_features.get("reasoning_hints", [])
    if hints:
        hints_text = "\n".join(f"- {h}" for h in hints[:5])
        reasoning_hints_section = REASONING_HINTS_SECTION_TEMPLATE.format(hints=hints_text)
    
    field_manual_section = ""
    field_manual_context = analysis_features.get("field_manual_context", "")
    if field_manual_context:
        field_manual_section = FIELD_MANUAL_SECTION_TEMPLATE.format(
            field_manual_context=field_manual_context[:2000]
        )
    
    comparison_section = ""
    comparison_result = analysis_features.get("comparison_result")
    if comparison_result and analysis_features.get("analysis_mode") == "compare":
        comparison_section = COMPARISON_SECTION_TEMPLATE.format(
            primary_cause=comparison_result.get("primary_cause", "UNKNOWN"),
            primary_cause_description=comparison_result.get("primary_cause_description", ""),
            secondary_cause=comparison_result.get("secondary_cause", "None"),
            diff_summary=comparison_result.get("diff_summary", "No differences computed"),
        )

    user_prompt = ASE_USER_PROMPT_TEMPLATE.format(
        query_uuid=analysis_features.get("query_uuid", ""),
        deployment=analysis_features.get("deployment", ""),
        metadata_json=metadata_json,
        bp_findings_json=bp_findings_json,
        sql_findings_json=sql_findings_json,
        coverage_json=coverage_json,
        history_context_json=history_context_json,
        candidate_actions_json=candidate_actions_json,
        reasoning_hints_section=reasoning_hints_section,
        field_manual_section=field_manual_section,
        comparison_section=comparison_section,
    )

    return call_cortex_complete(
        system_prompt=ASE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )