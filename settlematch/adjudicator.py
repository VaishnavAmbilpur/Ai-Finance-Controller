from __future__ import annotations

import json
import os
import time
from enum import Enum

from openai import OpenAI
from pydantic import BaseModel, field_validator


class DecisionType(str, Enum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class AdjudicationResult(BaseModel):
    decision: DecisionType
    reason: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        assert 0.0 <= v <= 1.0, "Confidence must be between 0 and 1"
        return round(v, 3)

    @field_validator("reason")
    @classmethod
    def reason_not_generic(cls, v: str) -> str:
        assert len(v.strip()) > 20, "Reason must be specific, not a one-word answer"
        return v


SYSTEM_PROMPT = """You are a financial reconciliation engine for an Indian payment merchant using Razorpay.

You will receive one unmatched settlement record and its closest candidates from the bank statement and merchant ledger. Your job is to determine whether they represent the same underlying transaction.

Common reasons amounts differ in Indian payment reconciliation:
- MDR (Merchant Discount Rate): typically 1.75-2% deducted by Razorpay
- GST on MDR: 18% of MDR amount
- Partial refund: merchant refunded a customer, reducing their net receivable
- Paise rounding: different rounding rules between Razorpay, the bank, and the merchant ERP
- Batched settlement: multiple orders netted into one bank credit

Return ONLY valid JSON in this exact schema:
{"decision": "MATCH"|"NO_MATCH"|"ESCALATE_TO_HUMAN", "reason": "<specific reason referencing actual field values>", "confidence": <0.0-1.0>}

Do not include any text before or after the JSON."""

MAX_RETRIES = 1
RETRY_DELAY_SECONDS = 2.0

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
    return _client


def get_model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "openrouter/free")


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "N/A"
    return str(value)


def build_prompt(settlement_row, candidates: dict) -> str:
    bank = candidates.get("bank_row") or {}
    ledger = candidates.get("ledger_row") or {}
    return (
        f"Settlement record (from Razorpay settlement report):\n"
        f"settlement_id: {_fmt(settlement_row.get('settlement_id'))}\n"
        f"order_id: {_fmt(settlement_row.get('order_id'))}\n"
        f"gross_amount: {_fmt(settlement_row.get('gross_amount'))}\n"
        f"mdr_amount: {_fmt(settlement_row.get('mdr_amount'))}\n"
        f"gst_on_mdr: {_fmt(settlement_row.get('gst_on_mdr'))}\n"
        f"net_amount: {_fmt(settlement_row.get('net_amount'))}\n"
        f"settlement_date: {_fmt(settlement_row.get('settlement_date'))}\n"
        f"utr: {_fmt(settlement_row.get('utr'))}\n"
        f"\n"
        f"Closest bank statement candidate:\n"
        f"utr: {_fmt(bank.get('utr'))}\n"
        f"credit_amount: {_fmt(bank.get('credit_amount'))}\n"
        f"value_date: {_fmt(bank.get('value_date'))}\n"
        f"narration: {_fmt(bank.get('narration'))}\n"
        f"\n"
        f"Closest merchant ledger candidate:\n"
        f"order_id: {_fmt(ledger.get('order_id'))}\n"
        f"invoice_amount: {_fmt(ledger.get('invoice_amount'))}\n"
        f"payment_received_date: {_fmt(ledger.get('payment_received_date'))}\n"
        f"refund_amount: {_fmt(ledger.get('refund_amount'))}\n"
        f"net_receivable: {_fmt(ledger.get('net_receivable'))}\n"
        f"\n"
        f"Do these represent the same underlying transaction? Respond with only the JSON object."
    )


def _call_llm(prompt: str) -> str:
    try:
        response = get_client().chat.completions.create(
            model=get_model(),
            max_tokens=400,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        message = str(e).lower()
        if "response_format" in message or "json_object" in message:
            response = get_client().chat.completions.create(
                model=get_model(),
                max_tokens=400,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        else:
            raise
    return response.choices[0].message.content


def adjudicate(settlement_row, candidates: dict) -> AdjudicationResult:
    prompt = build_prompt(settlement_row, candidates)

    raw = None
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            raw = _call_llm(prompt)
            break
        except Exception as e:
            last_error = str(e)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

    if raw is None:
        return AdjudicationResult(
            decision=DecisionType.ESCALATE_TO_HUMAN,
            reason=f"API error during adjudication after retry: {last_error[:200]}",
            confidence=0.0,
        )

    try:
        parsed = json.loads(raw.strip())
        return AdjudicationResult(**parsed)
    except json.JSONDecodeError:
        snippet = raw.strip()[:100]
        return AdjudicationResult(
            decision=DecisionType.ESCALATE_TO_HUMAN,
            reason=f"LLM output could not be parsed as JSON: {snippet}",
            confidence=0.0,
        )
    except Exception as e:
        return AdjudicationResult(
            decision=DecisionType.ESCALATE_TO_HUMAN,
            reason=f"LLM output failed validation: {str(e)[:200]}",
            confidence=0.0,
        )
