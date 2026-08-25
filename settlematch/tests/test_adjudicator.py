"""
Unit tests for settlematch/adjudicator.py — LLM Adjudicator & Safety Net
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from settlematch.adjudicator import (
    AdjudicationResult,
    DecisionType,
    _fmt,
    _parse_llm_response,
    adjudicate,
    adjudicate_async,
    build_prompt,
    get_async_client,
    get_client,
    get_model,
)


# ---------------------------------------------------------------------------
# Pydantic Model Validation Tests
# ---------------------------------------------------------------------------

def test_valid_match_result():
    result = AdjudicationResult(
        decision=DecisionType.MATCH,
        reason="Bank credit 1155.63 equals settlement net minus MDR 20.65 and GST 3.72",
        confidence=0.92,
    )
    assert result.decision == DecisionType.MATCH
    assert result.confidence == 0.92


def test_valid_no_match_result():
    result = AdjudicationResult(
        decision=DecisionType.NO_MATCH,
        reason="Amounts differ beyond tolerance and LLM could not explain via MDR/GST/refund",
        confidence=0.15,
    )
    assert result.decision == DecisionType.NO_MATCH


def test_valid_escalate_result():
    result = AdjudicationResult(
        decision=DecisionType.ESCALATE_TO_HUMAN,
        reason="API timeout on retry — escalated rather than forced a match",
        confidence=0.0,
    )
    assert result.decision == DecisionType.ESCALATE_TO_HUMAN


def test_confidence_out_of_range_rejected():
    with pytest.raises(Exception):
        AdjudicationResult(
            decision=DecisionType.MATCH,
            reason="Bank credit matches settlement net amount",
            confidence=1.5,
        )


def test_confidence_negative_rejected():
    with pytest.raises(Exception):
        AdjudicationResult(
            decision=DecisionType.MATCH,
            reason="Bank credit matches settlement exactly within MDR tolerance",
            confidence=-0.1,
        )


def test_generic_reason_rejected():
    with pytest.raises(Exception):
        AdjudicationResult(
            decision=DecisionType.NO_MATCH,
            reason="differs",
            confidence=0.5,
        )


def test_deliberate_failure_uncertain_rejected():
    with pytest.raises(Exception):
        AdjudicationResult(
            decision="UNCERTAIN",  # type: ignore[arg-type]
            reason="Cannot determine match from given fields",
            confidence=0.5,
        )


def test_reason_boundary_length():
    result = AdjudicationResult(
        decision=DecisionType.NO_MATCH,
        reason="a" * 21,
        confidence=0.5,
    )
    assert len(result.reason) == 21

    with pytest.raises(Exception):
        AdjudicationResult(
            decision=DecisionType.NO_MATCH,
            reason="a" * 20,
            confidence=0.5,
        )


# ---------------------------------------------------------------------------
# Helper & Prompt Building Tests
# ---------------------------------------------------------------------------

def test_fmt_helper():
    assert _fmt(None) == "N/A"
    assert _fmt(float("nan")) == "N/A"
    assert _fmt(42) == "42"
    assert _fmt(1155.63) == "1155.63"
    assert _fmt("HDFC010124") == "HDFC010124"


def test_build_prompt_with_data():
    row = {
        "settlement_id": "setl_abc",
        "order_id": "order_123",
        "gross_amount": 1180.0,
        "mdr_amount": 20.65,
        "gst_on_mdr": 3.72,
        "net_amount": 1155.63,
        "settlement_date": "2024-01-14",
        "utr": "HDFC0101240000001",
    }
    cands = {
        "bank_row": {
            "utr": "HDFC0101240000001",
            "credit_amount": 1155.63,
            "value_date": "2024-01-15",
        },
        "ledger_row": None,
    }
    prompt = build_prompt(row, cands)
    assert "setl_abc" in prompt
    assert "1155.63" in prompt
    assert "N/A" in prompt


# ---------------------------------------------------------------------------
# Adjudicator Sync & Async Execution Tests
# ---------------------------------------------------------------------------

def test_adjudicate_sync_good_json():
    good_json = json.dumps({
        "decision": "MATCH",
        "reason": "Bank credit 1155.63 matches settlement net minus MDR and GST fees",
        "confidence": 0.95,
    })
    row = {"settlement_id": "s1", "order_id": "o1"}
    cands = {"bank_row": {"utr": "u1"}}
    with patch("settlematch.adjudicator._call_llm", return_value=good_json):
        res = adjudicate(row, cands)
    assert res.decision == DecisionType.MATCH


def test_adjudicate_sync_bad_json_escalates():
    row = {"settlement_id": "s1", "order_id": "o1"}
    cands = {}
    with patch("settlematch.adjudicator._call_llm", return_value="Invalid response from AI"):
        res = adjudicate(row, cands)
    assert res.decision == DecisionType.ESCALATE_TO_HUMAN


def test_adjudicate_async_good_json():
    good_json = json.dumps({
        "decision": "MATCH",
        "reason": "Bank credit 1155.63 matches settlement net minus MDR and GST fees",
        "confidence": 0.95,
    })
    row = {"settlement_id": "s1", "order_id": "o1"}
    cands = {}

    async def _run():
        with patch("settlematch.adjudicator._call_llm_async", new=AsyncMock(return_value=good_json)):
            return await adjudicate_async(row, cands)

    res = asyncio.run(_run())
    assert res.decision == DecisionType.MATCH


def test_adjudicate_async_api_error_escalates():
    row = {"settlement_id": "s1", "order_id": "o1"}
    cands = {}

    async def _run():
        with patch("settlematch.adjudicator._call_llm_async", new=AsyncMock(side_effect=Exception("Timeout"))):
            return await adjudicate_async(row, cands)

    res = asyncio.run(_run())
    assert res.decision == DecisionType.ESCALATE_TO_HUMAN


def test_parse_llm_response():
    assert _parse_llm_response(None, "err").decision == DecisionType.ESCALATE_TO_HUMAN
    assert _parse_llm_response("not json", "").decision == DecisionType.ESCALATE_TO_HUMAN


# ---------------------------------------------------------------------------
# Client & Model Configuration Tests
# ---------------------------------------------------------------------------

def test_get_model_default(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    assert get_model() == "liquid/lfm-2.5-2.6b:free"


def test_missing_api_key_raises_environment_error(monkeypatch):
    import settlematch.adjudicator as adj_module
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    adj_module._client = None
    adj_module._async_client = None
    with pytest.raises(EnvironmentError, match="OPENROUTER_API_KEY"):
        get_client()
    with pytest.raises(EnvironmentError, match="OPENROUTER_API_KEY"):
        get_async_client()
