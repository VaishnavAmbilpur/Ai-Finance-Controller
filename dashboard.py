# STREAMLIT DASHBOARD
# Presentation layer — shows 4 metric cards, exception charts, audit log.
# Under 80 lines. The judge sees numbers, clicks an exception, reads the reason.
# Run: python -m streamlit run dashboard.py

import streamlit as st
import pandas as pd
import os

from settlematch.generator import generate_dataset
from main import run_pipeline

# Page config — wide layout for metric cards
st.set_page_config(page_title="SettleMatch", layout="wide")

AUDIT_PATH = "data/audit_log.csv"

def _generate_and_run(seed=None):
    os.makedirs("data", exist_ok=True)
    settlements, bank, ledger = generate_dataset(n_records=65, seed=seed)
    settlements.to_csv("data/settlement_report.csv", index=False)
    bank.to_csv("data/bank_statement.csv", index=False)
    ledger.to_csv("data/merchant_ledger.csv", index=False)
    run_pipeline("data/settlement_report.csv", "data/bank_statement.csv", "data/merchant_ledger.csv")

# HEADER: Title + inline small control button
col_header, col_btn = st.columns([3, 1], vertical_alignment="center")
with col_header:
    st.title("SettleMatch — Reconciliation Results")
    st.caption("⚡ Automated 3-way reconciliation (Razorpay Settlement vs Bank Statement vs Merchant Ledger)")
with col_btn:
    if st.button("🎲 Generate New Data & Run", type="primary", use_container_width=True):
        with st.spinner("Running AI pipeline..."):
            _generate_and_run(seed=None)
            st.rerun()

st.divider()

# Check if audit log exists — auto-generate dataset on first launch if missing
if not os.path.exists(AUDIT_PATH):
    with st.spinner("Initializing dataset and running SettleMatch pipeline for first launch..."):
        _generate_and_run(seed=42)


# Load audit log and compute metrics
df = pd.read_csv(AUDIT_PATH)
total = len(df)
matched = len(df[df["decision"].isin(["AUTO_APPROVED", "FUZZY_APPROVED", "BATCH_SPLIT_APPROVED", "LLM_MATCHED"])])
exceptions = total - matched
match_rate = round(matched / total * 100, 1) if total > 0 else 0.0
llm_calls = len(df[df["method"] == "llm"])
llm_rate = round(llm_calls / total * 100, 1) if total > 0 else 0.0

# ROW 1: 4 metric cards at the top
c1, c2, c3, c4 = st.columns(4)
c1.metric("Match Rate", f"{match_rate}%")
c2.metric("Total Records", total)
c3.metric("LLM Call Rate", f"{llm_rate}%")
c4.metric("Exceptions", exceptions)

# ROW 2: Decision distribution bar chart
st.subheader("Decision Distribution")
decision_counts = df["decision"].value_counts()
st.bar_chart(decision_counts)

# ROW 3: Exception breakdown — only shows if there are exceptions
st.subheader("Exception Breakdown")
exc_df = df[~df["decision"].isin(["AUTO_APPROVED", "FUZZY_APPROVED", "BATCH_SPLIT_APPROVED", "LLM_MATCHED"])]
if not exc_df.empty:
    exc_counts = pd.Series(exc_df["decision"]).value_counts()
    st.bar_chart(exc_counts)
else:
    st.success("No exceptions — all records matched!")

# ROW 4: Filterable audit log table with download button
st.subheader("Audit Log")
with st.expander("Filter & search audit log"):
    filter_decision = st.multiselect(
        "Filter by decision",
        options=df["decision"].unique(),
        default=df["decision"].unique(),
    )
    filtered = df[df["decision"].isin(filter_decision)]
    st.dataframe(filtered, width="stretch", height=400)

    # Download button — judge can download the full audit log
    if st.button("Download audit_log.csv"):
        st.download_button(
            label="Download CSV",
            data=df.to_csv(index=False),
            file_name="audit_log.csv",
            mime="text/csv",
        )
