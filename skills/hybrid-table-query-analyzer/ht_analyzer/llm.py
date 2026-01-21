"""
Thin helpers that call SNOWFLAKE.CORTEX.COMPLETE (via Snowpark or SQL)
using the prompt templates.

Cursor TODO:
- Replace the pseudo-code in call_cortex_complete() with your actual integration
  (either Python Snowpark Session or SQL execution).
"""

import json
from typing import Any, Dict, List

from .llm_prompts import (
    ASE_SYSTEM_PROMPT,
    ASE_USER_PROMPT_TEMPLATE,
    EMAIL_SYSTEM_PROMPT,
    EMAIL_USER_PROMPT_TEMPLATE,
)


def call_cortex_complete(system_prompt: str, user_prompt: str, model: str = "claude-3-5-sonnet") -> str:
    """
    Placeholder for a call to SNOWFLAKE.CORTEX.COMPLETE.

    Cursor TODO:
    - Implement this with your existing Streamlit logic:
      - Using a Snowflake Session and SQL like:
        SELECT SNOWFLAKE.CORTEX.COMPLETE(:model, :payload)::variant AS result;
      - Or the Python client wrapper if you already have one.
    """
    raise NotImplementedError("call_cortex_complete() must be wired to Cortex COMPLETE.")


def generate_next_steps_for_ase(analysis_features: Dict[str, Any],
                                candidate_actions: List[Dict[str, Any]]) -> str:
    """
    Build the ASE prompt and call Cortex to get next steps.
    """
    # Cursor TODO:
    #   Extract these fields from analysis_features to mirror the app.
    metadata_json = json.dumps(analysis_features.get("metadata", {}), indent=2)
    bp_findings_json = json.dumps(analysis_features.get("bp_findings", {}), indent=2)
    sql_findings_json = json.dumps(analysis_features.get("sql_findings", []), indent=2)
    coverage_json = json.dumps(analysis_features.get("coverage", []), indent=2)
    history_context_json = json.dumps(analysis_features.get("history_context", {}), indent=2)
    candidate_actions_json = json.dumps(candidate_actions, indent=2)

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


def generate_customer_email(analysis_features: Dict[str, Any],
                            candidate_actions: List[Dict[str, Any]]) -> str:
    """
    Build the customer email prompt and call Cortex to get email body.
    """
    high_level = {
        "query_uuid": analysis_features.get("query_uuid"),
        "deployment": analysis_features.get("deployment"),
        "grade": analysis_features.get("grade"),
        "score": analysis_features.get("score"),
    }
    diagnostics = {
        "bp_findings": analysis_features.get("bp_findings", {}),
        "sql_findings": analysis_features.get("sql_findings", []),
        "coverage": analysis_features.get("coverage", []),
        "history_context": analysis_features.get("history_context", {}),
    }

    high_level_json = json.dumps(high_level, indent=2)
    diagnostics_json = json.dumps(diagnostics, indent=2)
    candidate_actions_json = json.dumps(candidate_actions, indent=2)

    user_prompt = EMAIL_USER_PROMPT_TEMPLATE.format(
        high_level_json=high_level_json,
        diagnostics_json=diagnostics_json,
        candidate_actions_json=candidate_actions_json,
    )

    return call_cortex_complete(
        system_prompt=EMAIL_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )