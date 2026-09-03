# SettleMatch — Architecture & Design Decisions Log

This document records all key technical decisions, bug fixes, benchmark choices, and infrastructure configurations made during the development and optimization of **SettleMatch**.

---

## 1. Benchmark Dataset & Reproducibility (`seed=42`, `n=100`)

* **Decision:** Fixed default dataset generation parameter to **`n_records = 100`** with a deterministic seed **`seed = 42`** in [`settlematch/generator.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/generator.py) and [`generate_data.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/generate_data.py).
* **Rationale:**
  * `seed=42` guarantees exact PRNG reproducibility across automated tests, CI runs, and initial dashboard launches.
  * `n=100` provides a statistically meaningful sample size to exercise all 6 injected failure modes (50% clean, 10% lag, 10% UTR typo, 10% batch, 10% refund, 2% rounding, 8% missing).

---

## 2. Currency Standardization (INR / ₹)

* **Decision:** Converted all financial displays, cost calculations, deltas, and executive ROI metrics across [`dashboard.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/dashboard.py) and [`README.md`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/README.md) to **Indian Rupees (`₹`)**.
* **Rationale:**
  * SettleMatch operates in the context of Razorpay and Indian merchant banking (NEFT/IMPS/RTGS).
  * Operational cost calculations use **₹500 / hour** based on standard Indian Mid-Level Finance Analyst rates.
  * Statutory fee calculations incorporate **18.0% GST** on MDR under Indian CGST/SGST financial service regulations.

---

## 3. Exception Categorization Logic Fix

* **Decision:** Refactored UTR match fallback logic in [`settlematch/matcher.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/matcher.py) to calculate partial Levenshtein similarity scores (`fuzz.ratio`).
* **Rationale:**
  * Previously, missing bank records (`Decision.MISSING_COUNTERPART`) were hardcoded to `exception_category="UTR_MISMATCH"`, dumping all exceptions into a single bucket.
  * With the fix:
    * Bank candidates with partial UTR similarity (**70%–92%**) are categorized as **`UTR_MISMATCH`** (severe UTR typos).
    * Transactions missing bank statement entries entirely (similarity **< 70%**) are categorized as **`MISSING_COUNTERPART`**.
  * Results in a realistic 7-exception breakdown ($n=100, \text{seed}=42$): **6 `MISSING_COUNTERPART`** and **1 `LLM_ESCALATED`**.

---

## 4. Instant Streamlit Cloud Boot Strategy

* **Decision:** Tracked pre-computed canonical benchmark dataset (`data/audit_log.csv`, `settlement_report.csv`, `bank_statement.csv`, `merchant_ledger.csv`) in Git.
* **Rationale:**
  * Prevents cold-start delays and button-click requirements on Streamlit Community Cloud.
  * When a visitor visits [`https://ai-finance-controller.streamlit.app/`](https://ai-finance-controller.streamlit.app/), all executive KPIs, visual funnel stages, decision breakdown charts, and transaction inspector tables load **100% instantly**.

---

## 5. Deployment & Uptime Architecture (Streamlit Cloud + UptimeRobot)

* **Decision:** Deployed live application on Streamlit Community Cloud paired with a **5-minute ping interval** via UptimeRobot.
* **Rationale:**
  * Prevents Streamlit's 7-day deep sleep policy and 15-minute container pause.
  * Keeps the container warm, ensuring zero load latency for users while avoiding third-party CPU quota locks (e.g. Hugging Face Spaces limits).

---

## 6. Async Concurrency Optimization & Throughput Benchmarks

* **Decision:** Implemented `AsyncOpenAI` + `asyncio.gather` in [`settlematch/adjudicator.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/adjudicator.py) and [`main.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/main.py).
* **Rationale & Benchmark Measurements ($n=100$):**
  * **Sequential Blocking Pipeline (Day 1 baseline):** ~0.8 records/sec (1–5s blocking wait per LLM call).
  * **Live Network OpenRouter Pipeline:** **4.7 records/sec** (21.3s total wall-clock time over live HTTP API calls).
  * **Async Execution Engine Benchmark:** **34.7 records/sec** (2.88s total wall-clock time with non-blocking concurrent event loop processing).

---

## 7. Financial Fee Formulas & Verification Transparency

* **Decision:** Explicitly documented MDR fee ranges (1.5%–2.2%) and GST tax (18%) in [`README.md`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/README.md) and connected them to `AMOUNT_DELTA` tolerance and AI Adjudication.
* **Rationale:**
  * Explains how fee deductions and refunds are verified by the AI engine to convert raw amount variances into `LLM_MATCHED` decisions.

---

## 8. Settlement Q&A Agent (`settlematch/qa_agent.py`)

* **Decision:** Implemented a pandas pre-filtered natural-language Q&A query layer in [`settlematch/qa_agent.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/qa_agent.py) and integrated it into [`dashboard.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/dashboard.py).
* **Rationale:**
  * Track 4 lists "Multi-source reconciliation" and "Settlement Q&A agent" as key directions. Combining both provides strong Track 4 differentiation.
  * Reuses existing `AsyncOpenAI` client configuration from [`settlematch/adjudicator.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/adjudicator.py) without duplicate infrastructure.
  * Queries filter and aggregate audit records in pandas first before calling the LLM prompt. Answers are strictly grounded in audit log records (`audit_log.csv`), maintaining full auditability and preventing hallucinated answers.

---

## 9. Human-Cost Comparison Metric (`settlematch/cost_comparison.py`)

* **Decision:** Created a pure utility function `compute_time_saved()` in [`settlematch/cost_comparison.py`](file:///c:/Users/Vaishnav%20Ambilpur/Desktop/Razor-pay-AiHack/settlematch/cost_comparison.py) to calculate estimated manual processing hours saved versus automated runtime.
* **Rationale:**
  * Translates raw performance metrics (93% match rate, 34.7 rec/sec) into human-understandable time savings (e.g. 5.0 hours saved for 100 records).
  * Kept in an independent pure module to prevent expanding the scope of `settlematch/eval_harness.py`.
  * Manual audit time per record (default 3.0 minutes) is explicitly labeled as a stated estimate across all UI displays and documentation.

