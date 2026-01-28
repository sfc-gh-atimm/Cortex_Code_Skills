import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import json
import os
import time
from pathlib import Path
from datetime import datetime
from io import StringIO

try:
    from snowflake.snowpark import Session
    SNOWPARK_AVAILABLE = True
except ImportError:
    SNOWPARK_AVAILABLE = False

try:
    from telemetry import (
        TelemetryEvents,
        log_event,
        log_error,
        track_analysis_loaded,
        track_workload_analysis,
        track_tab_view,
    )
    TELEMETRY_AVAILABLE = True
except ImportError:
    TELEMETRY_AVAILABLE = False

st.set_page_config(
    page_title="Unistore Workload Conversion Advisor",
    page_icon="🔄",
    layout="wide"
)


def get_snowpark_session() -> "Session":
    """Get or create Snowpark session for telemetry."""
    if "snowpark_session" not in st.session_state:
        st.session_state.snowpark_session = None
        if SNOWPARK_AVAILABLE:
            try:
                conn_name = os.getenv("SNOWFLAKE_CONNECTION_NAME", "Snowhouse")
                st.session_state.snowpark_session = Session.builder.config(
                    "connection_name", conn_name
                ).create()
            except Exception:
                pass
    return st.session_state.snowpark_session


def log_telemetry(action_type: str, **kwargs) -> bool:
    """Log telemetry event if available."""
    if not TELEMETRY_AVAILABLE:
        return False
    session = get_snowpark_session()
    if session is None:
        return False
    try:
        return log_event(session, action_type, **kwargs)
    except Exception:
        return False


if "app_launched" not in st.session_state:
    st.session_state.app_launched = True
    log_telemetry(TelemetryEvents.APP_LAUNCH if TELEMETRY_AVAILABLE else "APP_LAUNCH")

st.title("🔄 Unistore Workload Conversion Advisor")

def load_analysis(folder_path: str) -> dict:
    """Load analysis data from output folder."""
    folder = Path(folder_path)
    data = {}
    
    metadata_file = folder / "analysis_metadata.json"
    if metadata_file.exists():
        with open(metadata_file) as f:
            data["metadata"] = json.load(f)
    
    for data_file in ["daily_activity", "statement_summary", "update_patterns", 
                         "hybrid_candidates", "ia_candidates", "delete_activity"]:
        csv_path = folder / f"{data_file}.csv"
        parquet_path = folder / f"{data_file}.parquet"
        if csv_path.exists():
            data[data_file] = pd.read_csv(csv_path)
        elif parquet_path.exists():
            data[data_file] = pd.read_parquet(parquet_path)
    
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
        
        load_duration_ms = int((time.time() - load_start) * 1000)
        if TELEMETRY_AVAILABLE and "metadata" in st.session_state.data:
            meta = st.session_state.data["metadata"]
            session = get_snowpark_session()
            if session:
                track_analysis_loaded(
                    session=session,
                    customer_name=meta.get("customer_name", "Unknown"),
                    account_id=meta.get("account_id"),
                    deployment=meta.get("deployment"),
                    analysis_days=meta.get("analysis_days"),
                    total_queries=meta.get("total_queries"),
                    hybrid_candidates=meta.get("hybrid_candidates_count"),
                    ia_candidates=meta.get("ia_candidates_count"),
                    duration_ms=load_duration_ms,
                )
    except Exception as e:
        import traceback
        st.sidebar.error(f"Error loading: {e}")
        st.sidebar.code(traceback.format_exc())
        
        if TELEMETRY_AVAILABLE:
            session = get_snowpark_session()
            if session:
                log_error(
                    session=session,
                    action_type="ERROR_LOAD",
                    error=e,
                    context={"analysis_path": analysis_path},
                )

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

def track_tab(tab_name: str):
    """Track tab view in telemetry."""
    if TELEMETRY_AVAILABLE and "metadata" in data:
        session = get_snowpark_session()
        if session:
            track_tab_view(
                session=session,
                customer_name=data["metadata"].get("customer_name", "Unknown"),
                tab_name=tab_name,
                deployment=data["metadata"].get("deployment"),
            )

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Daily Timeline", 
    "🎯 Hybrid Tables", 
    "📊 Interactive Analytics",
    "🔍 UPDATE Patterns",
    "📋 Summary"
])

with tab1:
    track_tab("Daily Timeline")
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
    track_tab("Hybrid Tables")
    st.header("🎯 Hybrid Table Candidates")
    st.markdown("Tables with UPDATE/DELETE patterns suitable for sub-10ms OLTP workloads.")
    
    if "hybrid_candidates" in data and not data["hybrid_candidates"].empty:
        df = data["hybrid_candidates"].copy()
        
        strong = len(df[df.get("SCORE", 0) >= 8]) if "SCORE" in df.columns else 0
        moderate = len(df[(df.get("SCORE", 0) >= 5) & (df.get("SCORE", 0) < 8)]) if "SCORE" in df.columns else 0
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Candidates", len(df))
        col2.metric("Strong Fit", strong, help="Score >= 8")
        col3.metric("Moderate Fit", moderate, help="Score 5-7")
        
        fig = px.scatter(
            df,
            x="UPDATE_COUNT",
            y="P50_DURATION_MS",
            size="UPDATE_COUNT",
            color="PARAMETERIZED_PCT" if "PARAMETERIZED_PCT" in df.columns else None,
            hover_name="TABLE_NAME",
            hover_data=["AVG_DURATION_MS", "P99_DURATION_MS"] if "P99_DURATION_MS" in df.columns else None,
            title="UPDATE Volume vs Latency",
            labels={
                "UPDATE_COUNT": "UPDATE Count (30 days)",
                "P50_DURATION_MS": "P50 Latency (ms)",
                "PARAMETERIZED_PCT": "Parameterized %"
            },
            color_continuous_scale="RdYlGn"
        )
        fig.update_xaxes(type="log")
        fig.update_yaxes(type="log")
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)
        
        st.subheader("📋 Candidate Details")
        display_cols = ["TABLE_NAME", "UPDATE_COUNT", "PARAMETERIZED_COUNT", 
                       "AVG_DURATION_MS", "P50_DURATION_MS", "P99_DURATION_MS", "SCORE"]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(
            df[display_cols].sort_values(by="UPDATE_COUNT", ascending=False),
            use_container_width=True,
            hide_index=True
        )
        
        if "delete_activity" in data and not data["delete_activity"].empty:
            st.subheader("🗑️ DELETE Activity")
            st.dataframe(data["delete_activity"], use_container_width=True, hide_index=True)
    else:
        st.info("No Hybrid Table candidates identified.")

with tab3:
    track_tab("Interactive Analytics")
    st.header("📊 Interactive Analytics Candidates")
    st.markdown("Read-heavy tables suitable for sub-second analytical queries.")
    
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
    track_tab("UPDATE Patterns")
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
    
    lines.append("# Unistore Workload Conversion Analysis Report")
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
    
    lines.append("---")
    lines.append("")
    lines.append("_Generated by Unistore Workload Conversion Advisor v2.1_")
    
    return "\n".join(lines)


with tab5:
    track_tab("Summary")
    st.header("📋 Executive Summary")
    
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
    
    with st.sidebar:
        st.markdown("---")
        telemetry_status = "🟢 Connected" if get_snowpark_session() else "🔴 Disconnected"
        st.caption(f"Telemetry: {telemetry_status}")
    
    st.caption("Generated by Unistore Workload Conversion Advisor v2.1")
