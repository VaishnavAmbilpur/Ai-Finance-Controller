import os
import pandas as pd
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from settlematch.qa_agent import filter_audit_dataframe, answer_question


@pytest.fixture
def sample_audit_df():
    return pd.DataFrame([
        {
            "timestamp": "2026-09-03 10:00:00",
            "settlement_id": "setl_101",
            "decision": "AUTO_APPROVED",
            "method": "rule",
            "bank_utr": "UTR101",
            "ledger_order": "order_101",
            "amount_delta": "₹0.00",
            "reason": "Exact UTR and amount match",
        },
        {
            "timestamp": "2026-09-03 10:00:01",
            "settlement_id": "setl_102",
            "decision": "MISSING_COUNTERPART",
            "method": "rule",
            "bank_utr": "N/A",
            "ledger_order": "order_102",
            "amount_delta": "₹500.00",
            "reason": "Settlement record missing counterpart in bank statement",
        },
        {
            "timestamp": "2026-09-03 10:00:02",
            "settlement_id": "setl_103",
            "decision": "LLM_MATCHED",
            "method": "llm",
            "bank_utr": "UTR103",
            "ledger_order": "order_103",
            "amount_delta": "₹25.00",
            "reason": "AI Adjudicator: Verified Bank credit matches ledger after MDR fee deduction",
        },
    ])


def test_filter_by_settlement_id(sample_audit_df):
    matched_df, context = filter_audit_dataframe("Why was setl_102 flagged?", sample_audit_df)
    assert len(matched_df) == 1
    assert matched_df.iloc[0]["settlement_id"] == "setl_102"
    assert "setl_102" in context


def test_filter_by_decision_keyword(sample_audit_df):
    matched_df, _ = filter_audit_dataframe("List all MISSING_COUNTERPART records", sample_audit_df)
    assert len(matched_df) == 1
    assert matched_df.iloc[0]["decision"] == "MISSING_COUNTERPART"


def test_filter_general_exception_query(sample_audit_df):
    matched_df, _ = filter_audit_dataframe("How many exceptions were flagged?", sample_audit_df)
    # Records setl_102 (MISSING_COUNTERPART) and setl_103 (method=llm) match
    assert len(matched_df) == 2


import asyncio

def test_answer_question_with_mocked_llm(tmp_path, sample_audit_df):
    async def _test():
        csv_file = tmp_path / "audit_log.csv"
        sample_audit_df.to_csv(csv_file, index=False)

        mock_chat = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Settlement setl_102 was flagged because it has a MISSING_COUNTERPART in bank statements."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_chat.completions.create.return_value = mock_response

        mock_async_client = MagicMock()
        mock_async_client.chat = mock_chat

        with patch("settlematch.qa_agent._get_api_key", return_value="mock_key"), \
             patch("settlematch.qa_agent.get_async_client", return_value=mock_async_client):
            res = await answer_question("Why was setl_102 flagged?", audit_log_path=str(csv_file))

        assert "answer" in res
        assert "records_used" in res
        assert "matched_rows" in res
        assert res["records_used"] == 1
        assert "MISSING_COUNTERPART" in res["answer"]

    asyncio.run(_test())


def test_answer_question_missing_file():
    async def _test():
        res = await answer_question("Why was setl_999 flagged?", audit_log_path="data/non_existent_file.csv")
        assert res["records_used"] == 0
        assert "not found" in res["answer"]
        assert res["matched_rows"].empty

    asyncio.run(_test())
