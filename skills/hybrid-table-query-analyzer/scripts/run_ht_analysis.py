#!/usr/bin/env python3
"""
run_ht_analysis.py

CLI entrypoint for the Hybrid Table Query Analyzer Cortex Code skill.

Responsibilities:
- Parse CLI args (UUID, deployment, optional SnowVI path, comparison UUID).
- Establish Snowflake / Snowhouse session.
- Delegate to shared analysis library that mirrors the Streamlit app logic.
- Print a JSON blob to stdout for Cortex Code to consume.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

APP_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = Path(__file__).resolve().parents[1] / "hybrid-table-query-analyzer"
SNOWSIGHT_APP_ROOT = os.getenv(
    "SNOWSIGHT_APP_ROOT",
    "/Users/atimm/Documents/Unistore/General_Cusotmer_query/snowsight_app",
)
EXTRA_ROOTS = [Path(SNOWSIGHT_APP_ROOT)] if SNOWSIGHT_APP_ROOT else []

for path in (APP_ROOT, SKILL_ROOT, *EXTRA_ROOTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SCHEMA_VERSION = "1.0"
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class SkillError(Exception):
    def __init__(self, message: str, code: str = "ANALYSIS_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _validate_uuid(value: str, field: str) -> str:
    if not value:
        raise SkillError(f"{field} is required", code="INVALID_UUID")
    value = value.strip()
    if UUID_RE.match(value):
        return value
    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return f"{value[0:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:32]}"
    raise SkillError(f"{field} must be a UUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)", code="INVALID_UUID")

# Cursor TODO:
#   Wire these imports to your actual app code. The names are chosen
#   to mirror the existing Streamlit modules conceptually.
try:
    from ht_analyzer.snowhouse import (
        create_snowhouse_session,
        resolve_deployment_for_uuid,
        fetch_query_metadata,
        fetch_history_context,
    )
    from ht_analyzer.snowvi import (
        load_snowvi_json,
        extract_snowvi_features,
    )
    from ht_analyzer.analysis import (
        build_analysis_features,
        build_candidate_actions,
    )
    from ht_analyzer.llm import (
        generate_next_steps_for_ase,
        generate_customer_email,
    )
except ImportError:
    # Minimal fallback so the file is syntactically valid even before wiring.
    def create_snowhouse_session(connection_name: str = "snowhouse"):
        raise NotImplementedError("create_snowhouse_session() not implemented")

    def resolve_deployment_for_uuid(session, uuid: str) -> str:
        raise NotImplementedError("resolve_deployment_for_uuid() not implemented")

    def fetch_query_metadata(session, uuid: str, deployment: Optional[str] = None):
        raise NotImplementedError("fetch_query_metadata() not implemented")

    def fetch_history_context(session, meta):
        return {}

    def load_snowvi_json(path: str):
        raise NotImplementedError("load_snowvi_json() not implemented")

    def extract_snowvi_features(snowvi_json, meta):
        return {}

    def build_analysis_features(meta, snowvi_features, history_context, comparison_uuid=None):
        return {}

    def build_candidate_actions(analysis_features):
        return []

    def generate_next_steps_for_ase(analysis_features, candidate_actions):
        return "Next steps placeholder – wire to Cortex COMPLETE."

    def generate_customer_email(analysis_features, candidate_actions):
        return None


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """
    Parse command-line arguments for the analysis script.
    """
    parser = argparse.ArgumentParser(
        description="Run Hybrid Table Query Analysis for a given query UUID."
    )

    parser.add_argument(
        "--uuid",
        "--query-uuid",
        dest="query_uuid",
        required=True,
        help="Snowflake job/query UUID to analyze.",
    )

    parser.add_argument(
        "--deployment",
        dest="deployment",
        help="Optional deployment name (e.g. azeastus2prod). "
             "If omitted, will be resolved from Snowhouse.",
    )

    parser.add_argument(
        "--snowvi-path",
        dest="snowvi_path",
        help="Optional path to a SnowVI JSON export to enrich the analysis.",
    )

    parser.add_argument(
        "--comparison-uuid",
        dest="comparison_uuid",
        help="Optional second UUID for before/after comparison.",
    )
    parser.add_argument(
        "--mode",
        dest="mode",
        choices=["single", "compare"],
        default="single",
        help="Analysis mode. Use 'compare' with --comparison-uuid.",
    )

    parser.add_argument(
        "--include-email",
        dest="include_email",
        action="store_true",
        help="If set, generate a customer-facing email draft as well.",
    )

    parser.add_argument(
        "--snowhouse-connection",
        dest="snowhouse_connection",
        default="snowhouse",
        help="Snowflake CLI connection name for Snowhouse (default: snowhouse).",
    )

    return parser.parse_args(argv)


def run_analysis(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute the Hybrid Table analysis workflow and return a JSON-serializable dict.

    This function is intentionally thin and delegates logic to shared library
    functions so that Streamlit and Cortex Code share the exact same stack.
    """
    query_uuid = _validate_uuid(args.query_uuid, "query_uuid")
    comparison_uuid = None
    if args.comparison_uuid:
        comparison_uuid = _validate_uuid(args.comparison_uuid, "comparison_uuid")

    if args.mode == "compare" and not comparison_uuid:
        raise SkillError("--mode compare requires --comparison-uuid", code="INVALID_COMPARISON_MODE")
    if args.mode == "single" and comparison_uuid:
        raise SkillError("--comparison-uuid requires --mode compare", code="INVALID_COMPARISON_MODE")

    # 1) Create Snowhouse session
    session = create_snowhouse_session(connection_name=args.snowhouse_connection)

    # 2) Resolve deployment if needed
    deployment = args.deployment or resolve_deployment_for_uuid(
        session=session,
        uuid=query_uuid,
    )

    # 3) Fetch core query metadata from Snowhouse (JOB_ETL / usage tracking views)
    meta = fetch_query_metadata(
        session=session,
        uuid=query_uuid,
        deployment=deployment,
    )

    # 4) Optional SnowVI enrichment
    snowvi_features: Dict[str, Any] = {}
    snowvi_json = None
    if args.snowvi_path:
        snowvi_json = load_snowvi_json(args.snowvi_path)
        snowvi_features = extract_snowvi_features(
            snowvi_json=snowvi_json,
            meta=meta,
        )

    # 5) History / anomaly context (e.g., parameterized hash behavior)
    history_ctx = fetch_history_context(session=session, meta=meta)

    # 6) Build deterministic feature set (no LLMs yet)
    analysis_features = build_analysis_features(
        meta=meta,
        snowvi_features=snowvi_features,
        history_context=history_ctx,
        comparison_uuid=comparison_uuid,
        analysis_mode=args.mode,
        snowvi_json=snowvi_json,
    )
    analysis_features.setdefault("query_uuid", query_uuid)
    analysis_features.setdefault("deployment", deployment)
    analysis_features.setdefault("metadata", meta)
    analysis_features.setdefault("history_context", history_ctx)
    analysis_features.setdefault("analysis_mode", args.mode)
    if comparison_uuid:
        analysis_features.setdefault("comparison_uuid", comparison_uuid)

    # 7) Build candidate actions (DDL, query rewrites, mitigations)
    candidate_actions = build_candidate_actions(analysis_features)

    # 8) AI-based explanation / next steps using Cortex (via ht_analyzer.llm)
    next_steps_markdown = generate_next_steps_for_ase(
        analysis_features,
        candidate_actions=candidate_actions,
    )

    customer_email_markdown = None
    if args.include_email:
        customer_email_markdown = generate_customer_email(
            analysis_features,
            candidate_actions=candidate_actions,
        )

    # 9) Assemble JSON payload
    # Cursor TODO:
    #   You can align this exactly with the ANALYSIS_SCHEMA that the Streamlit app uses.
    result: Dict[str, Any] = {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "analysis_mode": args.mode,
        "query_uuid": query_uuid,
        "comparison_uuid": comparison_uuid,
        "deployment": deployment,
        "analysis": analysis_features,
        "candidate_actions": candidate_actions,
        "next_steps_markdown": next_steps_markdown,
        "customer_email_markdown": customer_email_markdown,
        "history_context": history_ctx,
        # Optional convenience fields if present in analysis_features:
        "grade": analysis_features.get("grade"),
        "score": analysis_features.get("score"),
    }

    return result


def main(argv: Optional[list[str]] = None) -> int:
    """
    Main entrypoint for CLI usage.
    """
    args = parse_args(argv)

    try:
        result = run_analysis(args)
    except SkillError as exc:
        error_payload = {
            "status": "error",
            "schema_version": SCHEMA_VERSION,
            "error_code": exc.code,
            "error_message": str(exc),
            "details": exc.details,
            "query_uuid": getattr(args, "query_uuid", None),
            "comparison_uuid": getattr(args, "comparison_uuid", None),
        }
        print(json.dumps(error_payload, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        error_payload = {
            "status": "error",
            "schema_version": SCHEMA_VERSION,
            "error_code": "ANALYSIS_ERROR",
            "error_message": str(exc),
            "details": {"exception_type": type(exc).__name__},
            "query_uuid": getattr(args, "query_uuid", None),
            "comparison_uuid": getattr(args, "comparison_uuid", None),
        }
        print(json.dumps(error_payload, indent=2), file=sys.stderr)
        return 1

    # Print JSON to stdout for Cortex Code to consume.
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())