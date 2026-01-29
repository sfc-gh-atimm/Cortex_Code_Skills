"""
Unit tests for ht_query_optimization module

Source: GLEAN recommendations 2024-12-03
Run with: pytest test_ht_query_optimization.py -v
"""

import pytest

from ht_query_optimization import (
    analyze_ht_query_optimization,
    detect_bound_variables,
)


@pytest.mark.parametrize("is_ht", [True, False])
def test_analyze_ht_query_optimization_no_sql(is_ht):
    # Empty / None SQL should return None (no issues), regardless of HT flag
    assert analyze_ht_query_optimization(None, is_ht) is None
    assert analyze_ht_query_optimization("", is_ht) is None


def test_analyze_ht_query_optimization_not_ht():
    sql = "SELECT 1"
    # Non-HT query should be ignored
    assert analyze_ht_query_optimization(sql, is_ht_query=False) is None


def test_analyze_ht_query_optimization_function_in_join():
    sql = """
        SELECT t1.id, t2.val
        FROM ht_table t1
        JOIN dim t2
          ON LOWER(t1.key) = LOWER(t2.key)
        WHERE t1.org_id = 123
    """
    res = analyze_ht_query_optimization(sql, is_ht_query=True)

    assert res is not None
    assert res["has_issues"] is True
    critical_types = {f["type"] for f in res["critical"]}
    assert "function_in_join" in critical_types


def test_analyze_ht_query_optimization_ignores_comments_and_strings():
    sql = """
        -- SELECT LOWER(col) FROM fake;
        SELECT 'LOWER(x)' AS sample
        FROM ht_table t
        WHERE t.id = 1;
    """
    res = analyze_ht_query_optimization(sql, is_ht_query=True)
    # No real LOWER() usage in predicates, only in comments / literals
    assert res is None


def test_analyze_ht_query_optimization_mixed_table_indicator():
    sql = """
        SELECT *
        FROM ht_table t
        JOIN INFORMATION_SCHEMA.COLUMNS c
          ON t.col_name = c.COLUMN_NAME
    """
    res = analyze_ht_query_optimization(sql, is_ht_query=True)

    assert res is not None
    assert res["has_issues"] is True
    warning_types = {f["type"] for f in res["warnings"]}
    assert "potential_mixed_join" in warning_types


def test_analyze_ht_query_optimization_case_transform_threshold():
    sql = """
        SELECT *
        FROM ht_table t
        WHERE LOWER(t.col1) = 'a'
           OR UPPER(t.col2) = 'B'
           OR LOWER(t.col3) = 'c';
    """
    res = analyze_ht_query_optimization(sql, is_ht_query=True)

    assert res is not None
    assert res["has_issues"] is True
    types = {f["type"] for f in res["warnings"] + res["critical"]}
    assert "data_quality_issue" in types


def test_detect_bound_variables_positive():
    sql = "SELECT * FROM t WHERE org_id = ? AND status = :status AND pos = $1;"
    has_binds, msg = detect_bound_variables(sql)

    assert has_binds is True
    assert "Bound variables detected" in msg


def test_detect_bound_variables_negative():
    sql = "SELECT * FROM t WHERE org_id = 123 AND status = 'ACTIVE';"
    has_binds, msg = detect_bound_variables(sql)

    assert has_binds is False
    assert "No bound variables" in msg


def test_detect_bound_variables_ignores_literals():
    sql = """
        SELECT '=? :1 $2' AS sample
        FROM t
        WHERE id = 1;
    """
    has_binds, msg = detect_bound_variables(sql)

    assert has_binds is False


def test_smartlab_query_no_false_positive():
    """
    Test the actual SmartLab query that triggered false positive.
    Column named "date" should NOT trigger DATE() function detection.
    """
    sql = """
        select
            "date",
            sum("session_count") as "total_sessions"
        from
            smartlab_emobility_dev.shared."cpo_sessions"
        where
            "orga_id" = 481
        and 
            "date" between '2024-03-01' and '2024-03-07'
        group by 
            "date"
        order by 
            "date" asc;
    """
    res = analyze_ht_query_optimization(sql, is_ht_query=True)
    
    # Should return None (no issues) - query is perfectly sargable
    assert res is None, f"Expected no issues but got: {res}"


if __name__ == "__main__":
    # Run tests when called directly
    pytest.main([__file__, "-v"])

