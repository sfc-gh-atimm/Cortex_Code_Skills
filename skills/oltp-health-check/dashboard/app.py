import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import json
from pathlib import Path
from datetime import datetime

st.set_page_config(
    page_title="OLTP Health Check",
    page_icon="🏥",
    layout="wide"
)

st.title("🏥 OLTP Health Check Dashboard")

def load_health_data(folder_path: str) -> dict:
    folder = Path(folder_path)
    data = {}
    
    metadata_file = folder / "health_metadata.json"
    if metadata_file.exists():
        with open(metadata_file) as f:
            data["metadata"] = json.load(f)
    
    csv_files = [
        "ht_latency_trends", "ht_performance_tiers", "ht_fdb_health",
        "ht_query_patterns", "ht_slow_queries",
        "ia_daily_performance", "ia_compile_tiers",
        "postgres_latency", "postgres_throughput",
        "issues_detected"
    ]
    
    for data_file in csv_files:
        csv_path = folder / f"{data_file}.csv"
        if csv_path.exists():
            data[data_file] = pd.read_csv(csv_path)
    
    return data

def get_health_color(score: int) -> str:
    if score >= 80:
        return "#2E7D32"
    elif score >= 50:
        return "#F57C00"
    else:
        return "#C62828"

def get_health_status(score: int) -> str:
    if score >= 80:
        return "HEALTHY"
    elif score >= 50:
        return "WARNING"
    else:
        return "CRITICAL"

def render_health_card(title: str, score: int, icon: str, details: dict = None):
    color = get_health_color(score)
    status = get_health_status(score)
    
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, {color}22, {color}11); 
                border-left: 4px solid {color}; 
                padding: 20px; 
                border-radius: 8px;
                margin-bottom: 10px;">
        <div style="font-size: 24px; margin-bottom: 5px;">{icon} {title}</div>
        <div style="font-size: 48px; font-weight: bold; color: {color};">{score}</div>
        <div style="font-size: 14px; color: {color}; font-weight: bold;">{status}</div>
    </div>
    """, unsafe_allow_html=True)
    
    if details:
        for key, value in details.items():
            st.metric(key, value)

with st.sidebar:
    st.header("📁 Load Health Data")
    
    available_checks = []
    output_base = Path("/Users/atimm/Documents/Unistore/health_check_output")
    if output_base.exists():
        available_checks = [d.name for d in output_base.iterdir() if d.is_dir()]
    
    if available_checks:
        selected_check = st.selectbox(
            "Select health check",
            options=available_checks,
            index=0
        )
        data_path = str(output_base / selected_check)
    else:
        data_path = st.text_input(
            "Health check folder path",
            value="/Users/atimm/Documents/Unistore/health_check_output/customer_name",
            help="Path to folder containing health check output files"
        )
    
    load_button = st.button("Load Health Data", type="primary", use_container_width=True)

if "data" not in st.session_state:
    st.session_state.data = None

if load_button:
    try:
        st.session_state.data = load_health_data(data_path)
        st.sidebar.success(f"Loaded health data from {data_path}")
    except Exception as e:
        st.sidebar.error(f"Error loading: {e}")

if st.session_state.data is None:
    st.info("👈 Select a health check folder and click 'Load Health Data' to begin.")
    st.stop()

data = st.session_state.data

if "metadata" in data:
    meta = data["metadata"]
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Customer:** {meta.get('customer_name', 'N/A')}")
    st.sidebar.markdown(f"**Account:** {meta.get('account_name', 'N/A')}")
    st.sidebar.markdown(f"**Deployment:** {meta.get('deployment', 'N/A')}")
    st.sidebar.markdown(f"**Period:** {meta.get('analysis_days', 30)} days")
    st.sidebar.markdown(f"**Generated:** {meta.get('generated_at', 'N/A')[:10] if meta.get('generated_at') else 'N/A'}")

tab0, tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Overview",
    "🎯 Hybrid Tables",
    "📈 Interactive Analytics",
    "🐘 Snowflake Postgres",
    "⚠️ Issues"
])

with tab0:
    st.header("📊 Health Overview")
    
    if "metadata" in data:
        meta = data["metadata"]
        health_scores = meta.get("health_scores", {})
        usage = meta.get("usage_detected", {})
        
        col1, col2, col3, col4 = st.columns(4)
        
        overall_score = meta.get("overall_health_score", 0)
        with col1:
            render_health_card("Overall Health", overall_score, "🏥")
        
        ht_score = health_scores.get("hybrid_tables", 0)
        ht_active = usage.get("hybrid_tables", False)
        with col2:
            if ht_active:
                render_health_card("Hybrid Tables", ht_score, "🎯")
            else:
                st.info("🎯 Hybrid Tables\n\n**Not in use**")
        
        ia_score = health_scores.get("interactive_analytics", 0)
        ia_active = usage.get("interactive_analytics", False)
        with col3:
            if ia_active:
                render_health_card("Interactive Analytics", ia_score, "📈")
            else:
                st.info("📈 Interactive Analytics\n\n**Not in use**")
        
        pg_score = health_scores.get("snowflake_postgres", 0)
        pg_active = usage.get("snowflake_postgres", False)
        with col4:
            if pg_active:
                render_health_card("Snowflake Postgres", pg_score, "🐘")
            else:
                st.info("🐘 Snowflake Postgres\n\n**Not in use**")
        
        st.markdown("---")
        
        issues = meta.get("issues_found", {})
        if any(issues.values()):
            st.subheader("⚠️ Issues Summary")
            issue_col1, issue_col2, issue_col3 = st.columns(3)
            with issue_col1:
                critical = issues.get("critical", 0)
                st.metric("Critical Issues", critical, delta=None if critical == 0 else f"-{critical}", delta_color="inverse")
            with issue_col2:
                warning = issues.get("warning", 0)
                st.metric("Warnings", warning)
            with issue_col3:
                info_count = issues.get("info", 0)
                st.metric("Info", info_count)
        
        st.markdown("---")
        st.subheader("📋 Summary")
        
        summary_col1, summary_col2 = st.columns(2)
        with summary_col1:
            st.markdown(f"""
            **Customer:** {meta.get('customer_name', 'N/A')}  
            **Account:** {meta.get('account_name', 'N/A')} (ID: {meta.get('account_id', 'N/A')})  
            **Deployment:** {meta.get('deployment', 'N/A')}  
            """)
        with summary_col2:
            st.markdown(f"""
            **Analysis Period:** {meta.get('analysis_days', 30)} days  
            **Total Queries Analyzed:** {meta.get('total_queries', 0):,}  
            **Report Generated:** {meta.get('generated_at', 'N/A')}
            """)
    else:
        st.warning("No metadata available. Please ensure health_metadata.json exists.")

with tab1:
    st.header("🎯 Hybrid Tables Health")
    
    if "ht_latency_trends" in data and not data["ht_latency_trends"].empty:
        df = data["ht_latency_trends"].copy()
        df["DAY"] = pd.to_datetime(df["DAY"])
        df = df.sort_values("DAY")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total HT Queries", f"{df['HT_QUERIES'].sum():,.0f}")
        col2.metric("Avg P50", f"{df['P50_MS'].mean():.1f}ms")
        col3.metric("Avg P99", f"{df['P99_MS'].mean():.1f}ms")
        col4.metric("Max Latency", f"{df['MAX_MS'].max():.0f}ms")
        
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=("Daily HT Query Volume", "Latency Trends (P50, P95, P99)"),
            vertical_spacing=0.12
        )
        
        fig.add_trace(
            go.Bar(x=df["DAY"], y=df["HT_QUERIES"], name="HT Queries", marker_color="#2E86AB"),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(x=df["DAY"], y=df["P50_MS"], name="P50", line=dict(color="#2E7D32", width=2)),
            row=2, col=1
        )
        fig.add_trace(
            go.Scatter(x=df["DAY"], y=df["P95_MS"], name="P95", line=dict(color="#F57C00", width=2)),
            row=2, col=1
        )
        fig.add_trace(
            go.Scatter(x=df["DAY"], y=df["P99_MS"], name="P99", line=dict(color="#C62828", width=2)),
            row=2, col=1
        )
        
        fig.add_hline(y=10, line_dash="dash", line_color="green", annotation_text="Target (<10ms)", row=2, col=1)
        fig.add_hline(y=100, line_dash="dash", line_color="orange", annotation_text="Warning (100ms)", row=2, col=1)
        
        fig.update_layout(height=600, showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
        
        if "ht_performance_tiers" in data and not data["ht_performance_tiers"].empty:
            st.subheader("Performance Tier Distribution")
            tier_df = data["ht_performance_tiers"]
            
            color_map = {
                "1_OPTIMAL (<10ms)": "#2E7D32",
                "2_ACCEPTABLE (10-100ms)": "#F57C00",
                "3_SLOW (100ms-1s)": "#E65100",
                "4_CRITICAL (>1s)": "#C62828"
            }
            
            fig_pie = px.pie(
                tier_df,
                values="QUERY_COUNT",
                names="PERFORMANCE_TIER",
                title="Query Distribution by Performance Tier",
                color="PERFORMANCE_TIER",
                color_discrete_map=color_map
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        if "ht_fdb_health" in data and not data["ht_fdb_health"].empty:
            st.subheader("FDB Health")
            fdb_df = data["ht_fdb_health"]
            fdb_df["DAY"] = pd.to_datetime(fdb_df["DAY"])
            
            total_timeouts = fdb_df["FDB_TIMEOUTS"].sum()
            total_queries = fdb_df["TOTAL_HT_QUERIES"].sum()
            timeout_rate = (total_timeouts / total_queries * 100) if total_queries > 0 else 0
            
            fdb_col1, fdb_col2 = st.columns(2)
            fdb_col1.metric("FDB Timeouts", f"{total_timeouts:,}")
            fdb_col2.metric("Timeout Rate", f"{timeout_rate:.4f}%")
            
            if total_timeouts > 0:
                fig_fdb = px.bar(
                    fdb_df,
                    x="DAY",
                    y="FDB_TIMEOUTS",
                    title="Daily FDB Timeouts",
                    color_discrete_sequence=["#C62828"]
                )
                st.plotly_chart(fig_fdb, use_container_width=True)
        
        if "ht_query_patterns" in data and not data["ht_query_patterns"].empty:
            st.subheader("Query Pattern Distribution")
            pattern_df = data["ht_query_patterns"]
            
            fig_pattern = px.bar(
                pattern_df,
                x="QUERY_TYPE",
                y="COUNT",
                color="AVG_MS",
                title="HT Query Types",
                color_continuous_scale="RdYlGn_r"
            )
            st.plotly_chart(fig_pattern, use_container_width=True)
        
        if "ht_slow_queries" in data and not data["ht_slow_queries"].empty:
            st.subheader("Top Slow Queries")
            slow_df = data["ht_slow_queries"]
            
            has_uuid = "QUERY_UUID" in slow_df.columns
            has_hash = "QUERY_PARAMETERIZED_HASH" in slow_df.columns
            has_full_sql = "FULL_SQL" in slow_df.columns
            
            summary_cols = ["DURATION_MS", "COMPILE_MS", "EXEC_MS", "CREATED_ON"]
            if has_uuid:
                summary_cols = ["QUERY_UUID"] + summary_cols
            if "QUERY_PREVIEW" in slow_df.columns:
                summary_cols.append("QUERY_PREVIEW")
            
            display_cols = [c for c in summary_cols if c in slow_df.columns]
            st.dataframe(slow_df[display_cols], use_container_width=True, hide_index=True)
            
            if has_uuid or has_hash or has_full_sql:
                st.markdown("---")
                st.subheader("🔍 Query Inspector")
                st.caption("Select a query to view its full details and SQL")
                
                query_options = []
                for idx, row in slow_df.iterrows():
                    duration = row.get("DURATION_MS", 0)
                    preview = row.get("QUERY_PREVIEW", row.get("FULL_SQL", ""))[:60]
                    uuid_str = row.get("QUERY_UUID", f"row_{idx}")
                    query_options.append(f"{duration}ms - {preview}... ({uuid_str[:20]})")
                
                selected_query = st.selectbox(
                    "Select a slow query to inspect:",
                    options=range(len(query_options)),
                    format_func=lambda x: query_options[x]
                )
                
                if selected_query is not None:
                    selected_row = slow_df.iloc[selected_query]
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if has_uuid:
                            st.text_input("Query UUID", value=selected_row.get("QUERY_UUID", "N/A"), key="uuid_display", disabled=True)
                        if has_hash:
                            st.text_input("Parameterized Hash", value=selected_row.get("QUERY_PARAMETERIZED_HASH", "N/A"), key="hash_display", disabled=True)
                    with col2:
                        st.metric("Duration", f"{selected_row.get('DURATION_MS', 0):,.0f}ms")
                        st.metric("Compile Time", f"{selected_row.get('COMPILE_MS', 0):,.0f}ms")
                    
                    if has_full_sql:
                        st.markdown("**Full SQL:**")
                        st.code(selected_row.get("FULL_SQL", "N/A"), language="sql")
                    
                    if has_uuid:
                        st.markdown("**Next Steps:**")
                        st.markdown(f"- Use `/hybrid-table-query-analyzer {selected_row.get('QUERY_UUID', '')}` to deep dive into this query")
                        st.markdown(f"- Find related queries: `WHERE QUERY_PARAMETERIZED_HASH = '{selected_row.get('QUERY_PARAMETERIZED_HASH', '')}'`")
    else:
        st.info("No Hybrid Tables data available. Customer may not be using Hybrid Tables.")

with tab2:
    st.header("📈 Interactive Analytics Health")
    
    if "ia_daily_performance" in data and not data["ia_daily_performance"].empty:
        df = data["ia_daily_performance"].copy()
        df["DAY"] = pd.to_datetime(df["DAY"])
        df = df.sort_values("DAY")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total IA Queries", f"{df['TOTAL_QUERIES'].sum():,.0f}")
        col2.metric("Avg Sub-Second %", f"{df['SUB_SECOND_PCT'].mean():.1f}%")
        col3.metric("Avg P50", f"{df['P50_MS'].mean():.1f}ms")
        col4.metric("Avg P99", f"{df['P99_MS'].mean():.1f}ms")
        
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=("Daily IA Query Volume", "Sub-Second Query Percentage"),
            vertical_spacing=0.12
        )
        
        fig.add_trace(
            go.Bar(x=df["DAY"], y=df["TOTAL_QUERIES"], name="IA Queries", marker_color="#7B1FA2"),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(x=df["DAY"], y=df["SUB_SECOND_PCT"], name="Sub-Second %", 
                      fill="tozeroy", line=dict(color="#2E7D32")),
            row=2, col=1
        )
        
        fig.add_hline(y=90, line_dash="dash", line_color="green", annotation_text="Target (90%)", row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="orange", annotation_text="Warning (70%)", row=2, col=1)
        
        fig.update_layout(height=600, showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
        
        if "ia_compile_tiers" in data and not data["ia_compile_tiers"].empty:
            st.subheader("Compilation Time Distribution")
            compile_df = data["ia_compile_tiers"]
            
            color_map = {
                "1_FAST (<100ms)": "#2E7D32",
                "2_MODERATE (100-500ms)": "#F57C00",
                "3_SLOW (500ms-1s)": "#E65100",
                "4_VERY_SLOW (>1s)": "#C62828"
            }
            
            fig_compile = px.pie(
                compile_df,
                values="QUERY_COUNT",
                names="COMPILE_TIER",
                title="Queries by Compilation Time",
                color="COMPILE_TIER",
                color_discrete_map=color_map
            )
            st.plotly_chart(fig_compile, use_container_width=True)
    else:
        st.info("No Interactive Analytics data available. Customer may not be using IA.")

with tab3:
    st.header("🐘 Snowflake Postgres Health")
    
    if "postgres_throughput" in data and not data["postgres_throughput"].empty:
        df = data["postgres_throughput"].copy()
        df["DAY"] = pd.to_datetime(df["DAY"])
        df = df.sort_values("DAY")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Postgres Queries", f"{df['TOTAL_QUERIES'].sum():,.0f}")
        col2.metric("Avg Daily Sessions", f"{df['UNIQUE_SESSIONS'].mean():.0f}")
        col3.metric("Avg P50 Latency", f"{df['P50_MS'].mean():.1f}ms")
        
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=("Daily Postgres Query Volume", "Latency Trend (P50)"),
            vertical_spacing=0.12
        )
        
        fig.add_trace(
            go.Bar(x=df["DAY"], y=df["TOTAL_QUERIES"], name="Queries", marker_color="#336791"),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(x=df["DAY"], y=df["P50_MS"], name="P50 Latency", 
                      line=dict(color="#336791", width=2)),
            row=2, col=1
        )
        
        fig.update_layout(height=600, showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
        
        if "postgres_latency" in data and not data["postgres_latency"].empty:
            st.subheader("Latency Distribution")
            latency_df = data["postgres_latency"]
            
            color_map = {
                "1_<10ms": "#2E7D32",
                "2_10-100ms": "#689F38",
                "3_100ms-1s": "#F57C00",
                "4_>1s": "#C62828"
            }
            
            fig_latency = px.bar(
                latency_df,
                x="LATENCY_BUCKET",
                y="QUERY_COUNT",
                color="LATENCY_BUCKET",
                title="Query Distribution by Latency",
                color_discrete_map=color_map
            )
            fig_latency.update_layout(showlegend=False)
            st.plotly_chart(fig_latency, use_container_width=True)
    else:
        st.info("No Snowflake Postgres data available. Customer may not be using Snowflake Postgres.")

with tab4:
    st.header("⚠️ Detected Issues")
    
    if "issues_detected" in data and not data["issues_detected"].empty:
        issues_df = data["issues_detected"]
        
        severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        issues_df["_sort"] = issues_df["SEVERITY"].map(severity_order)
        issues_df = issues_df.sort_values("_sort")
        
        for _, issue in issues_df.iterrows():
            severity = issue["SEVERITY"]
            if severity == "CRITICAL":
                st.error(f"**{issue['ISSUE_CODE']}**: {issue['DESCRIPTION']}")
            elif severity == "WARNING":
                st.warning(f"**{issue['ISSUE_CODE']}**: {issue['DESCRIPTION']}")
            else:
                st.info(f"**{issue['ISSUE_CODE']}**: {issue['DESCRIPTION']}")
            
            with st.expander(f"Remediation for {issue['ISSUE_CODE']}"):
                st.markdown(issue.get("REMEDIATION", "No remediation guidance available."))
        
        st.markdown("---")
        st.subheader("📋 All Issues")
        display_cols = ["SEVERITY", "ISSUE_CODE", "PRODUCT", "DESCRIPTION"]
        display_cols = [c for c in display_cols if c in issues_df.columns]
        st.dataframe(issues_df[display_cols], use_container_width=True, hide_index=True)
    else:
        st.success("🎉 No issues detected! All OLTP workloads appear healthy.")

st.markdown("---")
st.caption("Generated by OLTP Health Check v1.0.0")
