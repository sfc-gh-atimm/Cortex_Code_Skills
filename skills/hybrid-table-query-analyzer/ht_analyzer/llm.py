"""
Thin helpers that call SNOWFLAKE.CORTEX.COMPLETE (via Snowpark or SQL)
using the prompt templates.
"""

import json
from typing import Any, Dict, List, Optional

from .llm_prompts import (
    ASE_SYSTEM_PROMPT,
    ASE_USER_PROMPT_TEMPLATE,
)

# Module-level session reference (set by run_ht_analysis.py)
_session = None


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
    """
    # Cursor TODO:
    #   Extract these fields from analysis_features to mirror the app.
    metadata_json = json.dumps(analysis_features.get("metadata", {}), indent=2, default=str)
    bp_findings_json = json.dumps(analysis_features.get("bp_findings", {}), indent=2, default=str)
    sql_findings_json = json.dumps(analysis_features.get("sql_findings", []), indent=2, default=str)
    coverage_json = json.dumps(analysis_features.get("coverage", []), indent=2, default=str)
    history_context_json = json.dumps(analysis_features.get("history_context", {}), indent=2, default=str)
    candidate_actions_json = json.dumps(candidate_actions, indent=2, default=str)

    user_prompt = ASE_USER_PROMPT_TEMPLATE.format(
        query_uuid=analysis_features.get("query_uuid", ""),
        deployment=analysis_features.get("deployment", ""),
        metadata_json=metadata_json,
        bp_findings_json=bp_findings_json,
        sql_findings_json=sql_findings_json,
        coverage_json=coverage_json,
        history_context_json=history_context_json,
        candidate_actions_json=candidate_actions_json,
    )

    return call_cortex_complete(
        system_prompt=ASE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )