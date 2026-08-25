# STREAMLIT DASHBOARD
# Non-technical, executive-ready interface for 3-way payment reconciliation.
# Includes ROI Calculator, Reconciliation Funnel, Live Search, Transaction Inspector, and Executive Report Export.

import os
import pandas as pd
import streamlit as st

from main import run_pipeline
from settlematch.generator import generate_dataset

# Page configuration - wide layout for business metrics
st.set_page_config(page_title="SettleMatch - Payment Reconciliation Controller", layout="wide")

AUDIT_PATH = "data/audit_log.csv"


def _generate_and_run(seed=None):
    os.makedirs("data", exist_ok=True)
    settlements, bank, ledger = generate_dataset(n_records=65, seed=seed)
    settlements.to_csv("data/settlement_report.csv", index=False)
    bank.to_csv("data/bank_statement.csv", index=False)
    ledger.to_csv("data/merchant_ledger.csv", index=False)
    run_pipeline("data/settlement_report.csv", "data/bank_statement.csv", "data/merchant_ledger.csv")


# HEADER: Title + Control Button
header_col, btn_col = st.columns([3, 1], vertical_alignment="center")
with header_col:
    st.title("SettleMatch - Payment Reconciliation Controller")
    st.caption("Automated 3-Way Reconciliation between Settlement Reports, Bank Statements, and Merchant Ledgers")
with btn_col:
    if st.button("Generate New Data & Run Pipeline", type="primary", use_container_width=True):
        with st.spinner("Processing reconciliation pipeline..."):
            _generate_and_run(seed=None)
            st.rerun()

st.divider()

# SYSTEM OVERVIEW & HOW IT WORKS BANNER
with st.expander("System Overview & How SettleMatch Works", expanded=True):
    st.markdown("""
    **What is SettleMatch?**  
    SettleMatch is an **AI-powered 3-Way Reconciliation Controller** designed for payment gateways and e-commerce merchants. It automatically reconciles payment data across three financial sources:
    1. **Razorpay Settlement Reports** (payout amounts, UTR numbers, gross/net fees)
    2. **Bank Statements** (actual bank account credits & value dates)
    3. **Merchant ERP Ledgers** (internal invoice orders, refunds, and receivables)
    
    ---
    **How the Reconciliation Pipeline Operates:**
    - **Step 1: Rule Engine (Fast Match)** — Instantly matches exact UTRs, 1-digit UTR typos, and multi-order batch deposits for 0 API cost.
    - **Step 2: AI Finance Controller (Discrepancy Adjudication)** — Analyzes ambiguous records with fee differences, calculates MDR rates (1.5% - 2.5%), 18% GST tax, and refund timing, and automatically adjudicates matches.
    - **Step 3: Audit Trail & Exception Management** — Produces a human-readable audit log with full financial reasoning and isolates true missing entries for manual review.
    
    *Click **"Generate New Data & Run Pipeline"** in the top right to simulate new randomized payment datasets and execute the pipeline.*
    """)

st.divider()

# Auto-initialize dataset on first launch
if not os.path.exists(AUDIT_PATH):
    with st.spinner("Initializing sample dataset and executing reconciliation pipeline..."):
        _generate_and_run(seed=42)

# Load audit log data
df = pd.read_csv(AUDIT_PATH)
total_records = len(df)

# Traditional Rule Engine Matches (Auto, Fuzzy, Batch)
rule_matches = len(df[df["decision"].isin(["AUTO_APPROVED", "FUZZY_APPROVED", "BATCH_SPLIT_APPROVED"])])
rule_accuracy = round(rule_matches / total_records * 100, 1) if total_records > 0 else 0.0

# Discrepancies sent to AI
ai_discrepancies = len(df[df["method"] == "llm"])

# Resolved by AI
ai_resolved = len(df[df["decision"] == "LLM_MATCHED"])

# Final Total Matched after AI
final_matched = rule_matches + ai_resolved
final_accuracy = round(final_matched / total_records * 100, 1) if total_records > 0 else 0.0

# Final Unresolved Exceptions
final_exceptions = len(df[df["decision"].isin(["LLM_ESCALATED", "MISSING_COUNTERPART"])])

# Net AI Automation Improvement
automation_diff = round(final_accuracy - rule_accuracy, 1)

# FINANCIAL ROI & TIME SAVED CALCULATOR
# Standard industry metric: 15 mins manual audit per complex fee/MDR exception @ $30/hr
time_saved_hours = round(ai_resolved * 15 / 60, 1)
cost_saved_run = round(time_saved_hours * 30.0, 2)
annualized_savings = round(cost_saved_run * 365, 0)
workload_reduction = round((ai_resolved / (ai_discrepancies + final_exceptions) * 100), 1) if (ai_discrepancies + final_exceptions) > 0 else 100.0


# SECTION 1: EXECUTIVE PERFORMANCE & FINANCIAL ROI SUMMARY
st.subheader("Executive Performance & Financial ROI Summary")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Overall Reconciliation Accuracy", f"{final_accuracy}%", delta=f"+{automation_diff}% AI boost")
c2.metric("Manual Audit Time Saved", f"{time_saved_hours} Hours", delta=f"{ai_resolved} discrepancies automated")
c3.metric("Operational Cost Saved per Run", f"${cost_saved_run:,.2f}", help="Based on $30/hr finance analyst rate")
c4.metric("Projected Annualized ROI", f"${annualized_savings:,.0f} / year", help="Projected savings assuming daily runs")

st.divider()

# SECTION 2: VISUAL RECONCILIATION FUNNEL
st.subheader("Visual Reconciliation Funnel (Pipeline Processing Stages)")

pct_rule = round(rule_matches / total_records, 3) if total_records > 0 else 0.0
pct_ai = round(ai_resolved / total_records, 3) if total_records > 0 else 0.0
pct_manual = round(final_exceptions / total_records, 3) if total_records > 0 else 0.0

f_col1, f_col2, f_col3 = st.columns(3)

with f_col1:
    st.markdown(f"**Stage 1: Rule Engine Approved ({rule_matches} records / {round(pct_rule*100, 1)}%)**")
    st.progress(pct_rule)
    st.caption("Exact UTR, fuzzy UTR, and batch split matches approved instantly by rules.")

with f_col2:
    st.markdown(f"**Stage 2: AI Controller Resolved ({ai_resolved} records / {round(pct_ai*100, 1)}%)**")
    st.progress(pct_ai)
    st.caption("Complex MDR fee variances, tax deductions, and refund timing resolved by AI.")

with f_col3:
    st.markdown(f"**Stage 3: Manual Exception Escalation ({final_exceptions} records / {round(pct_manual*100, 1)}%)**")
    st.progress(pct_manual)
    st.caption("Unmatched missing entries requiring manual human audit review.")

st.divider()

# SECTION 3: BEFORE VS AFTER AI AUTOMATION COMPARISON
st.subheader("Automation Difference: Traditional Rules vs AI Finance Controller")

col_before, col_after = st.columns(2)

with col_before:
    st.markdown("### Traditional Rule-Based Engine")
    st.write("Strict hard-coded rules for exact UTR, exact amount, and standard date matching.")
    st.metric("Successful Rule Matches", f"{rule_matches} / {total_records}")
    st.metric("Discrepancies Flagged for Review", ai_discrepancies + final_exceptions)
    st.info("Traditional systems flag all fee variances, MDR deductions, and refund timing lags as manual exceptions.")

with col_after:
    st.markdown("### SettleMatch AI Finance Controller")
    st.write("Intelligent AI engine that evaluates merchant fee deductions, MDR taxes, and refund timing.")
    st.metric("Automatically Resolved by AI", f"{ai_resolved} / {ai_discrepancies}")
    st.metric("Workload Reduction", f"{workload_reduction}% less manual audit")
    st.success(f"AI automatically resolved {ai_resolved} complex fee & refund discrepancies without human intervention.")

st.divider()

# SECTION 4: INTERACTIVE SINGLE-TRANSACTION INSPECTOR
st.subheader("Interactive Transaction Inspector")
st.write("Select any Settlement ID to inspect its 3-way reconciliation details and decision reasoning:")

settlement_ids = df["settlement_id"].tolist()
if settlement_ids:
    selected_id = st.selectbox("Choose Settlement ID to inspect:", settlement_ids)
    selected_row = df[df["settlement_id"] == selected_id].iloc[0]

    i_col1, i_col2, i_col3 = st.columns(3)
    with i_col1:
        st.markdown("**Settlement Record**")
        st.write(f"- ID: `{selected_row['settlement_id']}`")
        st.write(f"- Timestamp: `{selected_row['timestamp']}`")
    with i_col2:
        st.markdown("**Bank Entry Match**")
        st.write(f"- Bank UTR: `{selected_row['bank_utr']}`")
        st.write(f"- Amount Delta: `{selected_row['amount_delta']}`")
    with i_col3:
        st.markdown("**Merchant Ledger Entry**")
        st.write(f"- Ledger Order: `{selected_row['ledger_order']}`")
        st.write(f"- Processing Method: `{selected_row['method'].upper()}`")

    st.info(f"**Decision: {selected_row['decision']}** — Reason: {selected_row['reason']}")

st.divider()

# SECTION 5: DECISION BREAKDOWN & DISTRIBUTION
st.subheader("Reconciliation Outcome Breakdown")

chart_col, details_col = st.columns([1, 1])

with chart_col:
    st.markdown("**Distribution of Processing Decisions**")
    decision_counts = df["decision"].value_counts()
    st.bar_chart(decision_counts)

with details_col:
    st.markdown("**Summary of System Actions**")
    st.write(f"- Auto Approved (Exact Match): {len(df[df['decision']=='AUTO_APPROVED'])}")
    st.write(f"- Fuzzy Approved (Minor UTR Typo): {len(df[df['decision']=='FUZZY_APPROVED'])}")
    st.write(f"- Batch Split Approved (Multi-Order Deposit): {len(df[df['decision']=='BATCH_SPLIT_APPROVED'])}")
    st.write(f"- AI Resolved (Fee/MDR Deduction Verified): {ai_resolved}")
    st.write(f"- Missing Counterpart (Manual Audit Required): {len(df[df['decision']=='MISSING_COUNTERPART'])}")

st.divider()

# SECTION 6: AI RESOLUTION DEEP-DIVE TABLE
st.subheader("AI Adjudication Deep-Dive - Verified Discrepancy Log")
with st.expander("View detailed records resolved by AI", expanded=True):
    available_cols = [
        c for c in ["settlement_id", "decision", "bank_utr", "ledger_order", "amount_delta", "reason"]
        if c in df.columns
    ]
    llm_df = df[df["method"] == "llm"][available_cols]
    if not llm_df.empty:
        st.write("The table below lists the exact transactions flagged by rules and automatically resolved by AI:")
        st.dataframe(llm_df, use_container_width=True, height=300)
    else:
        st.info("No records required AI resolution in this processing run.")

st.divider()

# SECTION 7: AUDIT TRAIL, LIVE SEARCH & EXPORT
st.subheader("Audit Trail & Log Export")
with st.expander("Filter, Search, and Export Complete Audit Log", expanded=True):
    search_query = st.text_input("Instant Search (type Settlement ID, Bank UTR, Order ID, or keyword):", placeholder="e.g. UTR or Order ID...")

    filter_options = df["decision"].unique().tolist()
    selected_decisions = st.multiselect("Filter audit log by decision:", options=filter_options, default=filter_options)

    filtered_df = df[df["decision"].isin(selected_decisions)]

    if search_query.strip():
        q = search_query.strip().lower()
        mask = filtered_df.astype(str).apply(lambda row: row.str.lower().str.contains(q).any(), axis=1)
        filtered_df = filtered_df[mask]

    st.dataframe(filtered_df, use_container_width=True, height=350)

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        st.download_button(
            label="Download Complete Audit Log (CSV)",
            data=df.to_csv(index=False),
            file_name="audit_log.csv",
            mime="text/csv",
        )
    with btn_col2:
        # Executive Text Report Generator
        exec_report = f"""=====================================================
SETTLEMATCH AI FINANCE CONTROLLER - EXECUTIVE SUMMARY
=====================================================
Total Records Processed: {total_records}
Rule Engine Accuracy (Without AI): {rule_accuracy}%
AI Controller Accuracy (With AI): {final_accuracy}%
Net AI Automation Improvement: +{automation_diff}%

FINANCIAL ROI & TIME SAVINGS:
- Manual Audit Time Saved: {time_saved_hours} Hours
- Operational Cost Saved per Run: ${cost_saved_run:,.2f}
- Projected Annualized Savings: ${annualized_savings:,.0f} / year
- Workload Reduction: {workload_reduction}%

DECISION BREAKDOWN:
- Auto Approved (Exact Match): {len(df[df['decision']=='AUTO_APPROVED'])}
- Fuzzy Approved (Minor UTR Typo): {len(df[df['decision']=='FUZZY_APPROVED'])}
- Batch Split Approved (Multi-Order): {len(df[df['decision']=='BATCH_SPLIT_APPROVED'])}
- AI Resolved (Fee/MDR Deduction Verified): {ai_resolved}
- Missing Counterpart (Manual Audit Required): {len(df[df['decision']=='MISSING_COUNTERPART'])}
=====================================================
"""
        st.download_button(
            label="Download Executive Summary Report (TXT)",
            data=exec_report,
            file_name="executive_reconciliation_summary.txt",
            mime="text/plain",
        )
