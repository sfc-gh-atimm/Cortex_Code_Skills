from __future__ import annotations

from typing import Optional


def generate_snowvi_link(session, query_uuid: str, deployment: str) -> Optional[str]:
    """
    Generate a SnowVI URL for a query using temp.perfsol.get_deployment_link.

    Falls back to a constructed URL if the UDF is unavailable.
    """
    if not session or not query_uuid or not deployment:
        return None

    uuid = str(query_uuid).strip()
    deploy = str(deployment).strip()
    if not uuid or not deploy:
        return None

    fallback_url = f"https://snowvi.snowflakecomputing.com/{deploy.lower()}/{uuid.lower()}"
    try:
        query = f"""
        SELECT
            COALESCE(
                TRY_CAST(temp.perfsol.get_deployment_link('{deploy}', '{uuid}') AS STRING),
                '{fallback_url}'
            ) AS snowvi_url
        """
        result = session.sql(query).collect()
        if result and result[0][0]:
            return result[0][0]
    except Exception:
        return fallback_url

    return fallback_url
