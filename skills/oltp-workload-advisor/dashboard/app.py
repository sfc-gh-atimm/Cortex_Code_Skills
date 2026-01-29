import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import json
import time
from pathlib import Path
from datetime import datetime
from io import StringIO

st.set_page_config(
    page_title="OLTP Workload Advisor",
    page_icon="🔄",
    layout="wide"
)

st.title("🔄 OLTP Workload Advisor")

def load_analysis(folder_path: str) -> dict:
    """Load analysis data from output folder."""
    folder = Path(folder_path)
    data = {}
    
    metadata_file = folder / "analysis_metadata.json"
    if metadata_file.exists():
        with open(metadata_file) as f:
            data["metadata"] = json.load(f)
    
    for data_file in ["daily_activity", "statement_summary", "update_patterns", 
                         "hybrid_candidates", "ia_candidates", "delete_activity",
                         "postgres_inbound", "postgres_outbound", "postgres_tables",
                         "postgres_inbound_tables", "postgres_outbound_tables",
                         "executive_summary", "current_ht_usage", "current_ia_usage", 
                         "current_postgres_usage"]:
        csv_path = folder / f"{data_file}.csv"
        parquet_path = folder / f"{data_file}.parquet"
        txt_path = folder / f"{data_file}.txt"
        if csv_path.exists():
            data[data_file] = pd.read_csv(csv_path)
        elif parquet_path.exists():
            data[data_file] = pd.read_parquet(parquet_path)
        elif txt_path.exists():
            with open(txt_path, 'r') as f:
                data[data_file] = f.read()
    
    return data

with st.sidebar:
    st.header("📁 Load Analysis")
    
    available_analyses = []
    output_base = Path("/Users/atimm/Documents/Unistore/analysis_output")
    if output_base.exists():
        available_analyses = [d.name for d in output_base.iterdir() if d.is_dir()]
    
    if available_analyses:
        selected_analysis = st.selectbox(
            "Select analysis",
            options=available_analyses,
            index=0
        )
        analysis_path = str(output_base / selected_analysis)
    else:
        analysis_path = st.text_input(
            "Analysis folder path",
            value="/Users/atimm/Documents/Unistore/analysis_output/elevance_health",
            help="Path to folder containing analysis output files"
        )
    
    load_button = st.button("Load Analysis", type="primary", use_container_width=True)

if "data" not in st.session_state:
    st.session_state.data = None

if load_button:
    load_start = time.time()
    try:
        st.session_state.data = load_analysis(analysis_path)
        st.sidebar.success(f"Loaded analysis from {analysis_path}")
        
    except Exception as e:
        import traceback
        st.sidebar.error(f"Error loading: {e}")
        st.sidebar.code(traceback.format_exc())

if st.session_state.data is None:
    st.info("👈 Select an analysis folder and click 'Load Analysis' to begin.")
    st.stop()

data = st.session_state.data

if "metadata" in data:
    meta = data["metadata"]
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Customer:** {meta.get('customer_name', 'N/A')}")
    st.sidebar.markdown(f"**Account:** {meta.get('account_name', 'N/A')}")
    st.sidebar.markdown(f"**Deployment:** {meta.get('deployment', 'N/A')}")
    st.sidebar.markdown(f"**Period:** {meta.get('analysis_days', 30)} days")
    st.sidebar.markdown(f"**Generated:** {meta.get('generated_at', 'N/A')[:10]}")

tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📋 Executive Summary",
    "📈 Daily Timeline", 
    "🎯 Hybrid Tables", 
    "📊 Interactive Analytics",
    "🔍 UPDATE Patterns",
    "🐘 Snowflake Postgres",
    "📋 Full Report"
])

def compute_ht_score(row):
    """Compute Hybrid Table fit score (0-10) based on UPDATE patterns."""
    score = 0
    update_count = row.get('UPDATE_COUNT', 0)
    param_count = row.get('PARAMETERIZED_COUNT', 0)
    param_pct = (param_count / update_count * 100) if update_count > 0 else 0
    p50_ms = row.get('P50_DURATION_MS', 0)
    p99_ms = row.get('P99_DURATION_MS', 0)
    
    if update_count >= 100000:
        score += 3
    elif update_count >= 10000:
        score += 2
    elif update_count >= 1000:
        score += 1
    
    if param_pct >= 90:
        score += 4
    elif param_pct >= 70:
        score += 3
    elif param_pct >= 50:
        score += 2
    
    if p50_ms <= 500:
        score += 2
    elif p50_ms <= 1000:
        score += 1
    
    if p99_ms <= 2000:
        score += 1
    
    return min(score, 10)


def render_current_usage_section(data, product_type):
    """Render current usage section for a product type."""
    key_map = {
        "hybrid_tables": ("current_ht_usage", "Hybrid Tables", "🎯"),
        "interactive_analytics": ("current_ia_usage", "Interactive Analytics", "📊"),
        "snowflake_postgres": ("current_postgres_usage", "Snowflake Postgres", "🐘")
    }
    data_key, label, emoji = key_map.get(product_type, (None, None, None))
    
    if data_key and data_key in data:
        st.markdown(f"### {emoji} Current {label} Usage")
        usage_data = data[data_key]
        if isinstance(usage_data, pd.DataFrame) and not usage_data.empty:
            if 'STATUS' in usage_data.columns:
                status = usage_data['STATUS'].iloc[0]
                details = usage_data['DETAILS'].iloc[0] if 'DETAILS' in usage_data.columns else ""
                
                if 'Not Detected' in str(status) or 'No ' in str(details):
                    st.info(f"**{status}**\n\n{details}")
                else:
                    if 'TABLE_COUNT' in usage_data.columns:
                        table_count = usage_data['TABLE_COUNT'].iloc[0]
                    else:
                        table_count = len(usage_data)
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.metric(f"Active {label} Tables", table_count)
                    with col2:
                        st.dataframe(usage_data, use_container_width=True, hide_index=True)
            elif 'USAGE_STATUS' in usage_data.columns:
                status = usage_data['USAGE_STATUS'].iloc[0]
                notes = usage_data['NOTES'].iloc[0] if 'NOTES' in usage_data.columns else ""
                
                if 'No current' in str(status):
                    st.info(f"**{status}**\n\n{notes}")
                else:
                    if 'TABLE_COUNT' in usage_data.columns:
                        table_count = usage_data['TABLE_COUNT'].iloc[0]
                    else:
                        table_count = len(usage_data)
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.metric(f"Active {label} Tables", table_count)
                    with col2:
                        st.dataframe(usage_data, use_container_width=True, hide_index=True)
            else:
                if 'TABLE_COUNT' in usage_data.columns:
                    table_count = usage_data['TABLE_COUNT'].iloc[0]
                else:
                    table_count = len(usage_data)
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.metric(f"Active {label} Tables", table_count)
                with col2:
                    st.dataframe(usage_data, use_container_width=True, hide_index=True)
        elif isinstance(usage_data, str):
            st.info(usage_data)
        else:
            st.info(f"No current {label} usage detected in this account.")
    else:
        st.info(f"Current {label} usage data not available. Re-run analysis to collect.")


with tab0:
    st.header("📋 Executive Summary")
    
    if "executive_summary" in data and data["executive_summary"]:
        st.markdown(data["executive_summary"])
    else:
        if "metadata" in data:
            meta = data["metadata"]
            st.markdown(f"""
### Analysis Overview
**Customer:** {meta.get('customer_name', 'N/A')}  
**Account:** {meta.get('account_name', 'N/A')} ({meta.get('account_id', 'N/A')})  
**Deployment:** {meta.get('deployment', 'N/A')}  
**Analysis Period:** {meta.get('analysis_days', 30)} days  
**Total Queries Analyzed:** {meta.get('total_queries', 0):,}

---

### Key Findings
            """)
            
            ht_count = meta.get('hybrid_candidates_count', 0)
            ia_count = meta.get('ia_candidates_count', 0)
            postgres_flag = meta.get('postgres_candidate', False)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Hybrid Table Candidates", ht_count)
            with col2:
                st.metric("Interactive Analytics Candidates", ia_count)
            with col3:
                st.metric("Snowflake Postgres Candidate", "Yes" if postgres_flag else "No")
            
            st.markdown("---")
            st.markdown("### Recommendations")
            
            if "hybrid_candidates" in data and not data["hybrid_candidates"].empty:
                df_ht = data["hybrid_candidates"].copy()
                if "SCORE" not in df_ht.columns:
                    df_ht["SCORE"] = df_ht.apply(compute_ht_score, axis=1)
                strong_ht = len(df_ht[df_ht["SCORE"] >= 8])
                moderate_ht = len(df_ht[(df_ht["SCORE"] >= 5) & (df_ht["SCORE"] < 8)])
                if strong_ht > 0:
                    st.success(f"✅ **Hybrid Tables**: {strong_ht} strong candidates identified with high UPDATE volumes and parameterized queries")
                elif moderate_ht > 0:
                    st.warning(f"⚠️ **Hybrid Tables**: {moderate_ht} moderate candidates worth reviewing")
                else:
                    st.info("ℹ️ **Hybrid Tables**: Candidates identified but need further evaluation")
            
            if "ia_candidates" in data and not data["ia_candidates"].empty:
                df_ia = data["ia_candidates"]
                strong_ia = len(df_ia[df_ia.get("IA_FIT") == "STRONG"]) if "IA_FIT" in df_ia.columns else 0
                moderate_ia = len(df_ia[df_ia.get("IA_FIT") == "MODERATE"]) if "IA_FIT" in df_ia.columns else 0
                if strong_ia > 0:
                    st.success(f"✅ **Interactive Analytics**: {strong_ia} strong candidates with high read percentages")
                elif moderate_ia > 0:
                    st.warning(f"⚠️ **Interactive Analytics**: {moderate_ia} moderate candidates")
            
            if postgres_flag or ("postgres_inbound" in data and not data["postgres_inbound"].empty):
                inbound_ops = data["postgres_inbound"]["INBOUND_OPS"].sum() if "postgres_inbound" in data and not data["postgres_inbound"].empty else 0
                if inbound_ops > 100000:
                    st.success(f"✅ **Snowflake Postgres**: Strong candidate with {inbound_ops:,} inbound Postgres operations")
                elif inbound_ops > 10000:
                    st.warning(f"⚠️ **Snowflake Postgres**: Moderate patterns detected ({inbound_ops:,} inbound ops)")
        else:
            st.info("Load an analysis to view executive summary.")
    
    st.markdown("---")
    st.markdown("### Current Product Usage")
    
    usage_col1, usage_col2, usage_col3 = st.columns(3)
    with usage_col1:
        render_current_usage_section(data, "hybrid_tables")
    with usage_col2:
        render_current_usage_section(data, "interactive_analytics")
    with usage_col3:
        render_current_usage_section(data, "snowflake_postgres")


with tab1:
    st.header("📈 Daily Query Activity")
    
    if "daily_activity" in data:
        df = data["daily_activity"].copy()
        df["DAY"] = pd.to_datetime(df["DAY"])
        df = df.sort_values("DAY")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Queries", f"{df['TOTAL_QUERIES'].sum():,.0f}")
        col2.metric("Avg Daily", f"{df['TOTAL_QUERIES'].mean():,.0f}")
        col3.metric("Peak Day", f"{df['TOTAL_QUERIES'].max():,.0f}")
        col4.metric("Avg Latency", f"{df['AVG_DURATION_MS'].mean():.0f}ms")
        
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=("Read Operations (SELECT, INSERT)", "Write Operations (UPDATE, DELETE)"),
            vertical_spacing=0.12
        )
        
        fig.add_trace(
            go.Scatter(x=df["DAY"], y=df["SELECTS"], name="SELECT", 
                      fill="tozeroy", line=dict(color="#2E86AB")),
            row=1, col=1
        )
        if "INSERTS" in df.columns:
            fig.add_trace(
                go.Scatter(x=df["DAY"], y=df["INSERTS"], name="INSERT",
                          fill="tonexty", line=dict(color="#A23B72")),
                row=1, col=1
            )
        
        fig.add_trace(
            go.Bar(x=df["DAY"], y=df["UPDATES"], name="UPDATE", marker_color="#E94F37"),
            row=2, col=1
        )
        fig.add_trace(
            go.Bar(x=df["DAY"], y=df["DELETES"], name="DELETE", marker_color="#F39237"),
            row=2, col=1
        )
        
        fig.update_layout(height=600, showlegend=True, barmode="group")
        st.plotly_chart(fig, use_container_width=True)
        
        with st.expander("📊 Raw Daily Data"):
            st.dataframe(df, use_container_width=True)
    else:
        st.warning("No daily activity data available.")

with tab2:
    st.header("🎯 Hybrid Table Candidates")
    
    with st.expander("ℹ️ What are Hybrid Tables?", expanded=False):
        st.markdown("""
**Hybrid Tables** are optimized for OLTP (transactional) workloads requiring:
- **Sub-10ms point lookups** via indexed primary keys
- **High-frequency single-row UPDATEs** (e.g., status changes, counters)
- **Parameterized queries** that target specific rows by key

**Scoring Criteria (0-10 scale):**
| Factor | Points | Threshold |
|--------|--------|-----------|
| UPDATE Volume | 1-3 | 1K=1pt, 10K=2pt, 100K+=3pt |
| Parameterized % | 2-4 | 50%=2pt, 70%=3pt, 90%+=4pt |
| P50 Latency | 1-2 | ≤1000ms=1pt, ≤500ms=2pt |
| P99 Latency | 0-1 | ≤2000ms=1pt |

**Fit Categories:** Strong (8-10), Moderate (5-7), Low (<5)
        """)
    
    render_current_usage_section(data, "hybrid_tables")
    st.markdown("---")
    
    if "hybrid_candidates" in data and not data["hybrid_candidates"].empty:
        df = data["hybrid_candidates"].copy()
        
        if "SCORE" not in df.columns:
            df["SCORE"] = df.apply(compute_ht_score, axis=1)
        
        if "HT_FIT" not in df.columns:
            df["HT_FIT"] = df["SCORE"].apply(lambda s: "STRONG" if s >= 8 else ("MODERATE" if s >= 5 else "LOW"))
        
        strong = len(df[df["SCORE"] >= 8])
        moderate = len(df[(df["SCORE"] >= 5) & (df["SCORE"] < 8)])
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Candidates", len(df))
        col2.metric("Strong Fit", strong, help="Score >= 8: High volume + 90%+ parameterized + low latency")
        col3.metric("Moderate Fit", moderate, help="Score 5-7: Good potential, needs review")
        col4.metric("Low Fit", len(df) - strong - moderate, help="Score < 5")
        
        if "PARAMETERIZED_PCT" not in df.columns and "PARAMETERIZED_COUNT" in df.columns:
            df["PARAMETERIZED_PCT"] = (df["PARAMETERIZED_COUNT"] / df["UPDATE_COUNT"] * 100).round(1)
        
        color_col = "HT_FIT" if "HT_FIT" in df.columns else ("PARAMETERIZED_PCT" if "PARAMETERIZED_PCT" in df.columns else None)
        
        fig = px.scatter(
            df,
            x="UPDATE_COUNT",
            y="P50_DURATION_MS",
            size="UPDATE_COUNT",
            color=color_col,
            hover_name="TABLE_NAME",
            hover_data=["AVG_DURATION_MS", "P99_DURATION_MS", "SCORE", "PARAMETERIZED_PCT"] if "P99_DURATION_MS" in df.columns else ["SCORE"],
            title="UPDATE Volume vs Latency (colored by Fit)",
            labels={
                "UPDATE_COUNT": "UPDATE Count (30 days)",
                "P50_DURATION_MS": "P50 Latency (ms)",
                "HT_FIT": "HT Fit",
                "PARAMETERIZED_PCT": "Parameterized %"
            },
            color_discrete_map={"STRONG": "#2E86AB", "MODERATE": "#F39237", "LOW": "#CCCCCC"}
        )
        fig.update_xaxes(type="log")
        fig.update_yaxes(type="log")
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        if "HT_FIT" in df.columns:
            st.subheader("📊 Candidates by Fit Category")
            fit_order = {"STRONG": 0, "MODERATE": 1, "LOW": 2}
            df_sorted = df.copy()
            df_sorted["_sort"] = df_sorted["HT_FIT"].map(fit_order)
            df_sorted = df_sorted.sort_values(["_sort", "UPDATE_COUNT"], ascending=[True, False]).head(20)
            
            colors = df_sorted["HT_FIT"].map({"STRONG": "#2E86AB", "MODERATE": "#F39237", "LOW": "#CCCCCC"})
            
            fig2 = go.Figure(go.Bar(
                x=df_sorted["UPDATE_COUNT"],
                y=df_sorted["TABLE_NAME"],
                orientation="h",
                marker_color=colors,
                text=df_sorted["HT_FIT"] + " (" + df_sorted["SCORE"].astype(str) + ")",
                textposition="inside"
            ))
            fig2.update_layout(
                title="Top Candidates by UPDATE Volume",
                xaxis_title="UPDATE Count",
                yaxis_title="",
                height=max(400, min(len(df_sorted), 20) * 30),
                yaxis=dict(autorange="reversed")
            )
            st.plotly_chart(fig2, use_container_width=True)
        
        st.subheader("📋 Candidate Details")
        display_cols = ["TABLE_NAME", "UPDATE_COUNT", "PARAMETERIZED_COUNT", "PARAMETERIZED_PCT",
                       "AVG_DURATION_MS", "P50_DURATION_MS", "P99_DURATION_MS", "SCORE", "HT_FIT"]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(
            df[display_cols].sort_values(by="SCORE", ascending=False),
            use_container_width=True,
            hide_index=True
        )
        
        if "delete_activity" in data and not data["delete_activity"].empty:
            st.subheader("🗑️ DELETE Activity")
            st.dataframe(data["delete_activity"], use_container_width=True, hide_index=True)
    else:
        st.info("No Hybrid Table candidates identified.")

with tab3:
    st.header("📊 Interactive Analytics Candidates")
    
    with st.expander("ℹ️ What is Interactive Analytics?", expanded=False):
        st.markdown("""
**Interactive Analytics (IA)** tables are optimized for read-heavy analytical workloads requiring:
- **Sub-second query response** for dashboards and BI tools
- **High read-to-write ratios** (80%+ SELECT operations)
- **Frequent repeated queries** against the same tables

**Fit Criteria:**
| Factor | Strong | Moderate |
|--------|--------|----------|
| Read % | ≥90% | ≥70% |
| Total Operations | ≥10K | ≥1K |
| Avg SELECT Latency | ≤2000ms | ≤5000ms |

**Ideal Use Cases:** Dashboard backing tables, report caches, frequently-queried dimension tables
        """)
    
    render_current_usage_section(data, "interactive_analytics")
    st.markdown("---")
    
    if "ia_candidates" in data and not data["ia_candidates"].empty:
        df = data["ia_candidates"].copy()
        
        strong = len(df[df.get("IA_FIT") == "STRONG"]) if "IA_FIT" in df.columns else 0
        moderate = len(df[df.get("IA_FIT") == "MODERATE"]) if "IA_FIT" in df.columns else 0
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Candidates", len(df))
        col2.metric("Strong Fit", strong)
        col3.metric("Moderate Fit", moderate)
        
        fig = px.scatter(
            df,
            x="TOTAL_OPS",
            y="AVG_SELECT_MS",
            size="SELECTS",
            color="READ_PCT",
            hover_name="TABLE_NAME",
            title="Query Volume vs Read Latency",
            labels={
                "TOTAL_OPS": "Total Operations",
                "AVG_SELECT_MS": "Avg SELECT Latency (ms)",
                "READ_PCT": "Read %"
            },
            color_continuous_scale="Blues"
        )
        fig.update_xaxes(type="log")
        fig.update_yaxes(type="log")
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        if "IA_FIT" in df.columns:
            fit_order = {"STRONG": 0, "MODERATE": 1, "LOW": 2}
            df["_sort"] = df["IA_FIT"].map(fit_order)
            df = df.sort_values(["_sort", "TOTAL_OPS"], ascending=[True, False])
            
            colors = df["IA_FIT"].map({"STRONG": "#2E86AB", "MODERATE": "#F39237", "LOW": "#CCCCCC"})
            
            fig2 = go.Figure(go.Bar(
                x=df["TOTAL_OPS"],
                y=df["TABLE_NAME"],
                orientation="h",
                marker_color=colors,
                text=df["IA_FIT"],
                textposition="inside"
            ))
            fig2.update_layout(
                title="Candidates by Query Volume",
                xaxis_title="Total Operations",
                yaxis_title="",
                height=max(400, len(df) * 25),
                yaxis=dict(autorange="reversed")
            )
            st.plotly_chart(fig2, use_container_width=True)
        
        st.subheader("📋 Candidate Details")
        display_cols = ["TABLE_NAME", "TOTAL_OPS", "SELECTS", "DML", "READ_PCT", 
                       "AVG_SELECT_MS", "P50_SELECT_MS", "IA_FIT"]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
    else:
        st.info("No Interactive Analytics candidates identified.")

with tab4:
    st.header("🔍 UPDATE Pattern Classification")
    st.markdown("Distinguishing OLTP point updates from ETL bulk operations.")
    
    if "update_patterns" in data and not data["update_patterns"].empty:
        df = data["update_patterns"].copy()
        
        color_map = {
            "Point Update (Parameterized)": "#2E86AB",
            "Point Update (Literal)": "#A23B72",
            "ETL/Staging": "#CCCCCC",
            "Bulk Update (Subquery)": "#F39237",
            "Bulk/Other": "#E94F37"
        }
        
        fig = px.pie(
            df, 
            values="COUNT", 
            names="UPDATE_TYPE",
            title="UPDATE Pattern Distribution",
            color="UPDATE_TYPE",
            color_discrete_map=color_map
        )
        fig.update_layout(height=400)
        
        fig2 = px.bar(
            df,
            x="UPDATE_TYPE",
            y="AVG_DURATION_MS",
            color="UPDATE_TYPE",
            color_discrete_map=color_map,
            title="Average Latency by Pattern Type"
        )
        fig2.update_layout(height=400, showlegend=False)
        
        col1, col2 = st.columns(2)
        with col1:
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            st.plotly_chart(fig2, use_container_width=True)
        
        st.subheader("Pattern Assessment")
        for _, row in df.iterrows():
            pattern = row["UPDATE_TYPE"]
            count = row["COUNT"]
            avg_ms = row.get("AVG_DURATION_MS", 0)
            
            if "Parameterized" in pattern:
                st.success(f"✅ **{pattern}**: {count:,} queries @ {avg_ms:.0f}ms avg — Strong HT candidate")
            elif "ETL" in pattern or "Staging" in pattern:
                st.warning(f"⚠️ **{pattern}**: {count:,} queries @ {avg_ms:.0f}ms avg — Exclude from HT consideration")
            elif "Bulk" in pattern:
                st.error(f"❌ **{pattern}**: {count:,} queries @ {avg_ms:.0f}ms avg — Not suitable for HT")
            else:
                st.info(f"ℹ️ **{pattern}**: {count:,} queries @ {avg_ms:.0f}ms avg — Needs review")
        
        with st.expander("📊 Raw Pattern Data"):
            st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No UPDATE pattern data available.")

def generate_markdown_report(data: dict) -> str:
    """Generate a distributable markdown report from analysis data."""
    lines = []
    meta = data.get("metadata", {})
    
    lines.append("# OLTP Workload Analysis Report")
    lines.append("")
    lines.append(f"**Customer:** {meta.get('customer_name', 'N/A')}")
    lines.append(f"**Account ID:** {meta.get('account_id', 'N/A')}")
    lines.append(f"**Account Name:** {meta.get('account_name', 'N/A')}")
    lines.append(f"**Deployment:** {meta.get('deployment', 'N/A')}")
    lines.append(f"**Analysis Period:** {meta.get('analysis_days', 30)} days")
    lines.append(f"**Report Generated:** {meta.get('generated_at', 'N/A')[:19] if meta.get('generated_at') else 'N/A'}")
    lines.append(f"**Total Queries Analyzed:** {meta.get('total_queries', 0):,}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- **Hybrid Table Candidates:** {meta.get('hybrid_candidates_count', 0)}")
    lines.append(f"- **Interactive Analytics Candidates:** {meta.get('ia_candidates_count', 0)}")
    lines.append(f"- **Snowflake Postgres Candidate:** {'Yes' if meta.get('postgres_candidate', False) else 'No'}")
    lines.append("")
    
    if "statement_summary" in data and not data["statement_summary"].empty:
        lines.append("### Statement Distribution")
        lines.append("")
        lines.append("| Statement Type | Count | % | Avg Duration (ms) |")
        lines.append("|----------------|-------|---|-------------------|")
        for _, row in data["statement_summary"].iterrows():
            lines.append(f"| {row['STATEMENT_TYPE']} | {row['TOTAL_QUERIES']:,} | {row.get('PCT', 0):.1f}% | {row.get('AVG_DURATION_MS', 0):.0f} |")
        lines.append("")
    
    if "update_patterns" in data and not data["update_patterns"].empty:
        lines.append("### UPDATE Pattern Classification")
        lines.append("")
        lines.append("| Pattern | Count | Avg Duration (ms) | Assessment |")
        lines.append("|---------|-------|-------------------|------------|")
        for _, row in data["update_patterns"].iterrows():
            pattern = row["UPDATE_TYPE"]
            if "Parameterized" in pattern:
                assessment = "✅ Strong HT Candidate"
            elif "ETL" in pattern or "Staging" in pattern:
                assessment = "⚠️ Exclude from HT"
            elif "Bulk" in pattern:
                assessment = "❌ Not suitable for HT"
            else:
                assessment = "ℹ️ Needs review"
            lines.append(f"| {pattern} | {row['COUNT']:,} | {row.get('AVG_DURATION_MS', 0):.0f} | {assessment} |")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    if "hybrid_candidates" in data and not data["hybrid_candidates"].empty:
        lines.append("## 🎯 Hybrid Table Candidates")
        lines.append("")
        lines.append("Tables with UPDATE/DELETE patterns suitable for sub-10ms OLTP workloads.")
        lines.append("")
        df = data["hybrid_candidates"]
        lines.append("| Rank | Table | UPDATE Count | Parameterized % | P50 Latency (ms) | P99 Latency (ms) |")
        lines.append("|------|-------|--------------|-----------------|------------------|------------------|")
        for idx, (_, row) in enumerate(df.nlargest(10, "UPDATE_COUNT").iterrows(), 1):
            param_pct = row.get('PARAMETERIZED_PCT', row.get('PARAMETERIZED_COUNT', 0) / max(row.get('UPDATE_COUNT', 1), 1) * 100)
            lines.append(f"| {idx} | `{row['TABLE_NAME']}` | {row['UPDATE_COUNT']:,} | {param_pct:.0f}% | {row.get('P50_DURATION_MS', 0):.0f} | {row.get('P99_DURATION_MS', 0):.0f} |")
        lines.append("")
        
        lines.append("**Recommended Next Steps:**")
        lines.append("1. Validate primary key structure on candidate tables")
        lines.append("2. Review query patterns with customer DBA")
        lines.append("3. Assess application compatibility (driver, connection pooling)")
        lines.append("4. Create POC plan for top candidate")
        lines.append("")
    else:
        lines.append("## 🎯 Hybrid Table Candidates")
        lines.append("")
        lines.append("_No strong Hybrid Table candidates identified._")
        lines.append("")
    
    if "delete_activity" in data and not data["delete_activity"].empty:
        lines.append("### DELETE Activity")
        lines.append("")
        lines.append("| Table | DELETE Count | Avg Duration (ms) |")
        lines.append("|-------|--------------|-------------------|")
        for _, row in data["delete_activity"].head(10).iterrows():
            lines.append(f"| `{row['TABLE_NAME']}` | {row['DELETE_COUNT']:,} | {row.get('AVG_DURATION_MS', 0):.0f} |")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    if "ia_candidates" in data and not data["ia_candidates"].empty:
        lines.append("## 📊 Interactive Analytics Candidates")
        lines.append("")
        lines.append("Read-heavy tables suitable for sub-second analytical queries.")
        lines.append("")
        df = data["ia_candidates"]
        
        if "IA_FIT" in df.columns:
            fit_order = {"STRONG": 0, "MODERATE": 1, "LOW": 2}
            df = df.copy()
            df["_sort"] = df["IA_FIT"].map(fit_order)
            df = df.sort_values(["_sort", "TOTAL_OPS"], ascending=[True, False])
        
        lines.append("| Rank | Table | Total Ops | Read % | Avg Latency (ms) | Fit |")
        lines.append("|------|-------|-----------|--------|------------------|-----|")
        for idx, (_, row) in enumerate(df.head(15).iterrows(), 1):
            fit = row.get('IA_FIT', 'N/A')
            fit_emoji = "🟢" if fit == "STRONG" else ("🟡" if fit == "MODERATE" else "⚪")
            lines.append(f"| {idx} | `{row['TABLE_NAME']}` | {row['TOTAL_OPS']:,} | {row.get('READ_PCT', 99):.0f}% | {row.get('AVG_SELECT_MS', 0):.0f} | {fit_emoji} {fit} |")
        lines.append("")
        
        lines.append("**Recommended Next Steps:**")
        lines.append("1. Confirm read-only or limited DML acceptable")
        lines.append("2. Validate dashboard/BI access patterns")
        lines.append("3. Review current caching strategies")
        lines.append("4. Create POC plan for top candidate")
        lines.append("")
    else:
        lines.append("## 📊 Interactive Analytics Candidates")
        lines.append("")
        lines.append("_No strong Interactive Analytics candidates identified._")
        lines.append("")
    
    has_postgres_data = any(key in data for key in ["postgres_inbound", "postgres_outbound", "postgres_tables"])
    if has_postgres_data:
        lines.append("---")
        lines.append("")
        lines.append("## 🐘 Snowflake Postgres Assessment")
        lines.append("")
        
        inbound_ops = data["postgres_inbound"]["INBOUND_OPS"].sum() if "postgres_inbound" in data and not data["postgres_inbound"].empty else 0
        outbound_ops = data["postgres_outbound"]["OUTBOUND_OPS"].sum() if "postgres_outbound" in data and not data["postgres_outbound"].empty else 0
        postgres_tables_count = len(data["postgres_tables"]) if "postgres_tables" in data and not data["postgres_tables"].empty else 0
        
        lines.append(f"- **Inbound Postgres Operations:** {inbound_ops:,}")
        lines.append(f"- **Outbound Export Operations:** {outbound_ops:,}")
        lines.append(f"- **Postgres-Sourced Tables:** {postgres_tables_count}")
        lines.append("")
        
        if "postgres_inbound" in data and not data["postgres_inbound"].empty:
            lines.append("### Inbound Data Sources (Postgres → Snowflake)")
            lines.append("")
            lines.append("| Source Pattern | Operations | Flow Direction |")
            lines.append("|----------------|------------|----------------|")
            for _, row in data["postgres_inbound"].iterrows():
                lines.append(f"| {row['SOURCE_PATTERN']} | {row['INBOUND_OPS']:,} | Inbound |")
            lines.append("")
        
        if "postgres_outbound" in data and not data["postgres_outbound"].empty:
            lines.append("### Outbound Data Exports (Snowflake → External)")
            lines.append("")
            lines.append("| Export Pattern | Operations |")
            lines.append("|----------------|------------|")
            for _, row in data["postgres_outbound"].iterrows():
                lines.append(f"| {row['EXPORT_PATTERN']} | {row['OUTBOUND_OPS']:,} |")
            lines.append("")
        
        if "postgres_tables" in data and not data["postgres_tables"].empty:
            lines.append("### Top Tables with Postgres Data Lineage")
            lines.append("")
            lines.append("| Table | ETL Tool | Load Ops | Avg Load (ms) |")
            lines.append("|-------|----------|----------|---------------|")
            for _, row in data["postgres_tables"].head(10).iterrows():
                lines.append(f"| `{row['TABLE_NAME']}` | {row.get('ETL_TOOL', 'N/A')} | {row['LOAD_OPS']:,} | {row.get('AVG_LOAD_MS', 0):.0f} |")
            lines.append("")
        
        lines.append("**Snowflake Postgres Recommendation:**")
        if inbound_ops > 100000 or (inbound_ops > 1000 and outbound_ops > 1000):
            lines.append("Strong candidate for Snowflake Postgres consolidation. Customer has significant Postgres data flows that could be simplified.")
        elif inbound_ops > 10000:
            lines.append("Moderate Postgres patterns detected. Worth exploring consolidation opportunity.")
        else:
            lines.append("Limited Postgres patterns. Focus on Hybrid Tables or Interactive Analytics.")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append("_Generated by OLTP Workload Advisor v2.5_")
    
    return "\n".join(lines)


with tab5:
    st.header("🐘 Snowflake Postgres Candidates")
    
    with st.expander("ℹ️ What is Snowflake Postgres?", expanded=False):
        st.markdown("""
**Snowflake Postgres** provides PostgreSQL wire-protocol compatibility for workloads requiring:
- **PostgreSQL client compatibility** (psycopg2, JDBC, etc.)
- **Consolidation of existing Postgres** data flows into Snowflake
- **Hybrid transaction/analytics** using familiar Postgres tooling

**Assessment Criteria:**
| Signal | Strong Indicator |
|--------|------------------|
| Inbound Postgres Ops | ≥100K (HVR, Fivetran, Airbyte loading from Postgres) |
| Postgres-Named Tables | Tables with "PG", "POSTGRES" in naming |
| Bidirectional Flow | Both inbound loads and outbound exports |

**Ideal Use Cases:** Postgres migration, hybrid OLTP consolidation, Postgres toolchain compatibility
        """)
    
    render_current_usage_section(data, "snowflake_postgres")
    st.markdown("---")
    
    has_postgres_data = any(key in data for key in ["postgres_inbound", "postgres_outbound", "postgres_tables"])
    
    if has_postgres_data:
        col1, col2, col3 = st.columns(3)
        
        inbound_ops = 0
        outbound_ops = 0
        postgres_tables_count = 0
        
        if "postgres_inbound" in data and not data["postgres_inbound"].empty:
            inbound_ops = data["postgres_inbound"]["INBOUND_OPS"].sum()
        if "postgres_outbound" in data and not data["postgres_outbound"].empty:
            outbound_ops = data["postgres_outbound"]["OUTBOUND_OPS"].sum()
        if "postgres_inbound_tables" in data and not data["postgres_inbound_tables"].empty:
            postgres_tables_count += len(data["postgres_inbound_tables"])
        if "postgres_outbound_tables" in data and not data["postgres_outbound_tables"].empty:
            postgres_tables_count += len(data["postgres_outbound_tables"])
        
        col1.metric("Inbound Postgres Ops", f"{inbound_ops:,}", help="Data flowing INTO Snowflake from Postgres sources")
        col2.metric("Outbound Export Ops", f"{outbound_ops:,}", help="Data flowing OUT of Snowflake (potential Postgres targets)")
        col3.metric("Postgres-Sourced Tables", postgres_tables_count, help="Tables receiving data from Postgres via ETL/CDC")
        
        sf_postgres_score = 0
        score_details = []
        
        if inbound_ops > 50000:
            sf_postgres_score += 4
            score_details.append("✅ High volume Postgres inbound data (+4)")
        elif inbound_ops > 5000:
            sf_postgres_score += 3
            score_details.append("✅ Moderate Postgres inbound data (+3)")
        elif inbound_ops > 1000:
            sf_postgres_score += 2
            score_details.append("✅ Some Postgres inbound data (+2)")
        
        if outbound_ops > 25000:
            sf_postgres_score += 4
            score_details.append("✅ High volume data exports (+4)")
        elif outbound_ops > 2500:
            sf_postgres_score += 3
            score_details.append("✅ Moderate data exports (+3)")
        elif outbound_ops > 500:
            sf_postgres_score += 2
            score_details.append("✅ Some data exports (+2)")
        
        if inbound_ops > 1000 and outbound_ops > 1000:
            sf_postgres_score += 4
            score_details.append("✅ Both inbound AND outbound patterns (+4)")
        
        if postgres_tables_count > 10:
            sf_postgres_score += 3
            score_details.append("✅ Many Postgres-sourced tables (+3)")
        elif postgres_tables_count > 5:
            sf_postgres_score += 2
            score_details.append("✅ Multiple Postgres-sourced tables (+2)")
        
        st.subheader("Snowflake Postgres Fit Score")
        
        if sf_postgres_score >= 10:
            st.success(f"**Score: {sf_postgres_score}/16** — STRONG Snowflake Postgres Candidate")
        elif sf_postgres_score >= 5:
            st.warning(f"**Score: {sf_postgres_score}/16** — Moderate candidate, worth exploring")
        else:
            st.info(f"**Score: {sf_postgres_score}/16** — Low Postgres activity detected")
        
        with st.expander("Score Breakdown"):
            for detail in score_details:
                st.markdown(detail)
            if not score_details:
                st.markdown("No significant Postgres patterns detected.")
        
        st.markdown("---")
        
        if "postgres_inbound" in data and not data["postgres_inbound"].empty:
            st.subheader("📥 Inbound Data Sources (Postgres → Snowflake)")
            df_in = data["postgres_inbound"]
            
            color_map = {
                "POSTGRES_DIRECT": "#336791",
                "PG_PREFIX_TABLE": "#4A90A4", 
                "AWS_RDS": "#FF9900",
                "AWS_AURORA": "#FF6600",
                "FIVETRAN_POSTGRES": "#00B2E2",
                "AIRBYTE_POSTGRES": "#615EFF",
                "STITCH_POSTGRES": "#00C853",
                "HVR_POSTGRES": "#E91E63",
                "DEBEZIUM_CDC": "#9C27B0",
                "MATILLION_POSTGRES": "#2196F3",
                "OTHER_POSTGRES": "#9E9E9E"
            }
            
            fig = px.pie(
                df_in,
                values="INBOUND_OPS",
                names="SOURCE_PATTERN",
                title="Inbound Postgres Data by Source Type",
                color="SOURCE_PATTERN",
                color_discrete_map=color_map
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
            
            st.dataframe(df_in, use_container_width=True, hide_index=True)
        
        if "postgres_outbound" in data and not data["postgres_outbound"].empty:
            st.subheader("📤 Outbound Data Exports (Snowflake → External)")
            df_out = data["postgres_outbound"]
            
            fig = px.bar(
                df_out,
                x="EXPORT_PATTERN",
                y="OUTBOUND_OPS",
                title="Data Export Patterns (Potential Postgres Destinations)",
                color="EXPORT_PATTERN"
            )
            fig.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
            
            st.dataframe(df_out, use_container_width=True, hide_index=True)
        
        if "postgres_tables" in data and not data["postgres_tables"].empty:
            st.subheader("📋 Tables with Postgres Data Lineage")
            df_tables = data["postgres_tables"]
            
            if "ETL_TOOL" in df_tables.columns:
                fig = px.scatter(
                    df_tables,
                    x="LOAD_OPS",
                    y="AVG_LOAD_MS",
                    color="ETL_TOOL",
                    hover_name="TABLE_NAME",
                    title="Postgres-Sourced Tables: Load Volume vs Latency",
                    labels={
                        "LOAD_OPS": "Load Operations",
                        "AVG_LOAD_MS": "Avg Load Duration (ms)",
                        "ETL_TOOL": "ETL Tool"
                    }
                )
                fig.update_xaxes(type="log")
                fig.update_layout(height=500)
                st.plotly_chart(fig, use_container_width=True)
            
            st.dataframe(df_tables, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        
        if "postgres_inbound_tables" in data and not data["postgres_inbound_tables"].empty:
            st.subheader("📥 Destination Tables (Postgres → Snowflake)")
            st.markdown("*Snowflake tables receiving data FROM external Postgres databases via HVR/Fivetran CDC*")
            df_inbound_tables = data["postgres_inbound_tables"]
            
            col_in1, col_in2 = st.columns([1, 2])
            with col_in1:
                st.metric("Unique Destination Tables", len(df_inbound_tables))
                total_inbound_ops = df_inbound_tables["INBOUND_LOAD_OPS"].sum() if "INBOUND_LOAD_OPS" in df_inbound_tables.columns else 0
                st.metric("Total Inbound Operations", f"{total_inbound_ops:,}")
            
            with col_in2:
                fig_in = px.bar(
                    df_inbound_tables.head(15),
                    x="INBOUND_LOAD_OPS" if "INBOUND_LOAD_OPS" in df_inbound_tables.columns else "DESTINATION_TABLE",
                    y="DESTINATION_TABLE",
                    orientation="h",
                    title="Top 15 Destination Tables by Load Operations",
                    color_discrete_sequence=["#336791"]
                )
                fig_in.update_layout(height=400, yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_in, use_container_width=True)
            
            with st.expander("📋 Full Inbound Table List", expanded=False):
                st.dataframe(df_inbound_tables, use_container_width=True, hide_index=True)
        
        if "postgres_outbound_tables" in data and not data["postgres_outbound_tables"].empty:
            st.subheader("📤 Source Tables (Snowflake → Postgres)")
            st.markdown("*Snowflake tables being exported TO external Postgres databases (identified by EXP_ naming patterns)*")
            df_outbound_tables = data["postgres_outbound_tables"]
            
            col_out1, col_out2 = st.columns([1, 2])
            with col_out1:
                st.metric("Unique Source Tables", len(df_outbound_tables))
                total_outbound_ops = df_outbound_tables["EXPORT_OPS"].sum() if "EXPORT_OPS" in df_outbound_tables.columns else 0
                st.metric("Total Export Operations", f"{total_outbound_ops:,}")
            
            with col_out2:
                fig_out = px.bar(
                    df_outbound_tables.head(15),
                    x="EXPORT_OPS" if "EXPORT_OPS" in df_outbound_tables.columns else "SOURCE_TABLE",
                    y="SOURCE_TABLE",
                    orientation="h",
                    title="Top 15 Source Tables by Export Operations",
                    color_discrete_sequence=["#E91E63"]
                )
                fig_out.update_layout(height=400, yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_out, use_container_width=True)
            
            with st.expander("📋 Full Outbound Table List", expanded=False):
                st.dataframe(df_outbound_tables, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.subheader("💡 Snowflake Postgres Recommendations")
        
        if sf_postgres_score >= 10:
            st.markdown("""
            **Strong consolidation opportunity detected:**
            
            **Key value proposition:** Migrate external Postgres sources to Snowflake Postgres to:
            - **Improve data/cost visibility** — All data in one platform with unified governance
            - **Reduce data movement** — Eliminate ETL pipelines moving data between systems
            - **Simplify architecture** — Single platform for OLTP and analytics
            
            **Recommended conversation points:**
            - "You have {inbound:,} operations moving data from Postgres sources. With Snowflake Postgres, this data could live natively in Snowflake."
            - "By consolidating Postgres workloads, you'd reduce infrastructure costs and eliminate data latency."
            - "Snowflake Postgres provides PostgreSQL compatibility with Snowflake's scalability and governance."
            """.format(inbound=inbound_ops))
        elif sf_postgres_score >= 5:
            st.markdown("""
            **Moderate Postgres integration opportunity:**
            
            **Key value proposition:** Migrate external Postgres sources to Snowflake Postgres to improve data/cost visibility and reduce data movement overhead.
            
            **Discovery questions:**
            - What external Postgres instances are feeding data into Snowflake?
            - What business processes depend on this data flow?
            - What latency requirements exist for the data?
            
            **Potential benefits:**
            - Unified governance and access control
            - Reduced ETL complexity and maintenance
            - Single source of truth for both transactional and analytical workloads
            """)
        else:
            st.markdown("Limited Postgres data flow patterns detected. Consider focusing on Hybrid Tables or Interactive Analytics for this account.")
    
    else:
        st.info("No Postgres data flow analysis available. Run the Snowflake Postgres detection steps (6c-6f) in the skill to populate this data.")
        st.markdown("""
        **To enable Snowflake Postgres analysis:**
        1. Re-run the skill with Postgres detection steps enabled
        2. Save `postgres_inbound.csv`, `postgres_outbound.csv`, and `postgres_tables.csv` to the analysis folder
        """)


with tab6:
    st.header("📋 Full Report")
    
    col_header1, col_header2 = st.columns([3, 1])
    with col_header2:
        if st.button("📄 Export Markdown", use_container_width=True, help="Generate distributable markdown report"):
            md_report = generate_markdown_report(data)
            st.session_state.md_report = md_report
    
    if "md_report" in st.session_state:
        with st.expander("📄 Markdown Report (click to expand)", expanded=False):
            st.download_button(
                label="⬇️ Download .md file",
                data=st.session_state.md_report,
                file_name=f"workload_analysis_{data.get('metadata', {}).get('customer_name', 'report').replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown",
                use_container_width=True
            )
            st.code(st.session_state.md_report, language="markdown")
    
    if "metadata" in data:
        meta = data["metadata"]
        
        st.subheader("Customer Overview")
        col1, col2, col3 = st.columns(3)
        col1.markdown(f"""
        **Customer:** {meta.get('customer_name', 'N/A')}  
        **Account ID:** {meta.get('account_id', 'N/A')}  
        **Account Name:** {meta.get('account_name', 'N/A')}
        """)
        col2.markdown(f"""
        **Deployment:** {meta.get('deployment', 'N/A')}  
        **Analysis Period:** {meta.get('analysis_days', 30)} days  
        **Generated:** {meta.get('generated_at', 'N/A')[:10]}
        """)
        col3.markdown(f"""
        **Total Queries:** {meta.get('total_queries', 0):,}  
        **HT Candidates:** {meta.get('hybrid_candidates_count', 0)}  
        **IA Candidates:** {meta.get('ia_candidates_count', 0)}
        """)
    
    st.subheader("Statement Distribution")
    if "statement_summary" in data:
        df = data["statement_summary"]
        
        fig = px.bar(
            df,
            x="STATEMENT_TYPE",
            y="TOTAL_QUERIES",
            color="STATEMENT_TYPE",
            text="PCT",
            title="Query Volume by Statement Type"
        )
        fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(df, use_container_width=True, hide_index=True)
    
    st.subheader("Recommendations")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🎯 Hybrid Tables")
        if "hybrid_candidates" in data and not data["hybrid_candidates"].empty:
            top_ht = data["hybrid_candidates"].nlargest(3, "UPDATE_COUNT")
            st.markdown("**Top candidates for sub-10ms OLTP:**")
            for _, row in top_ht.iterrows():
                st.markdown(f"- `{row['TABLE_NAME']}` ({row['UPDATE_COUNT']:,} updates)")
            
            st.markdown("""
            **Next Steps:**
            1. Validate primary key structure
            2. Review query patterns with DBA
            3. Assess driver compatibility
            4. Plan POC migration
            """)
        else:
            st.info("No strong Hybrid Table candidates identified.")
    
    with col2:
        st.markdown("### 📊 Interactive Analytics")
        if "ia_candidates" in data and not data["ia_candidates"].empty:
            if "IA_FIT" in data["ia_candidates"].columns:
                top_ia = data["ia_candidates"][data["ia_candidates"]["IA_FIT"] == "STRONG"].head(3)
            else:
                top_ia = data["ia_candidates"].nlargest(3, "TOTAL_OPS")
            
            st.markdown("**Top candidates for sub-second analytics:**")
            for _, row in top_ia.iterrows():
                st.markdown(f"- `{row['TABLE_NAME']}` ({row.get('READ_PCT', 99):.0f}% reads)")
            
            st.markdown("""
            **Next Steps:**
            1. Confirm read-only or limited DML acceptable
            2. Validate dashboard/BI access patterns
            3. Review current caching
            4. Plan POC migration
            """)
        else:
            st.info("No strong Interactive Analytics candidates identified.")
    
    st.markdown("---")
    
    st.caption("Generated by OLTP Workload Advisor v2.5")
