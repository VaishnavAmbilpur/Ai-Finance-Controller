# LLM ADJUDICATOR
# For the ~8% of records rules can't resolve, ask an AI (via OpenRouter) to judge.
# Uses Pydantic to validate every LLM response before trusting it.
# Never crashes — every failure path returns ESCALATE_TO_HUMAN.
#
# Day 2 fixes applied:
#   1. os.environ.get() + EnvironmentError instead of hard KeyError crash
#   2. AsyncOpenAI client + adjudicate_async() for concurrent LLM calls
#   3. asyncio.sleep() in retry instead of time.sleep() (non-blocking)

from __future__ import annotations

import asyncio
import json
import os
import time
from enum import Enum

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, field_validator


class DecisionType(str, Enum):
    """The 3 possible LLM decisions — anything else gets rejected."""
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class AdjudicationResult(BaseModel):
    """
    Pydantic model — validates every LLM response.
    This is the real safety net against bad LLM output.
    """
    decision: DecisionType
    reason: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        """Confidence must be between 0 and 1 — reject garbage like 1.5 or -1."""
        assert 0.0 <= v <= 1.0, "Confidence must be between 0 and 1"
        return round(v, 3)

    @field_validator("reason")
    @classmethod
    def reason_not_generic(cls, v: str) -> str:
        """Reason must be >20 chars — forces LLM to explain specifically, not just say 'differs'."""
        assert len(v.strip()) > 20, "Reason must be specific, not a one-word answer"
        return v


# SYSTEM PROMPT — teaches the LLM Indian payment context
# The LLM needs to know about MDR, GST, refunds, paise rounding, batched settlements
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

MAX_RETRIES = 1          # retry once on API error before escalating
RETRY_DELAY_SECONDS = 2.0  # wait 2 seconds between retries

# Lazy-init singletons — avoids crash when importing without API key
_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None


def _get_api_key() -> str:
    """Read API key — supports both OPENROUTER_API_KEY and OPENAI_API_KEY."""
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Neither OPENROUTER_API_KEY nor OPENAI_API_KEY is set. "
            "Copy .env.example to .env and add your API key, then re-run."
        )
    return api_key


def _get_base_url() -> str:
    """Read base URL — defaults to OpenRouter, or OpenAI if OPENAI_API_KEY is set."""
    if os.environ.get("OPENAI_BASE_URL"):
        return os.environ["OPENAI_BASE_URL"]
    if os.environ.get("OPENROUTER_BASE_URL"):
        return os.environ["OPENROUTER_BASE_URL"]
    if os.environ.get("OPENAI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
        return "https://api.openai.com/v1"
    return "https://openrouter.ai/api/v1"


def get_client() -> OpenAI:
    """Lazy synchronous OpenAI/OpenRouter client — created on first use."""
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=_get_base_url(),
            api_key=_get_api_key(),
            timeout=10.0,
        )
    return _client


def get_async_client() -> AsyncOpenAI:
    """Lazy async client for concurrent LLM calls — supports OpenAI and OpenRouter."""
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(
            base_url=_get_base_url(),
            api_key=_get_api_key(),
            timeout=10.0,
        )
    return _async_client


def get_model() -> str:
    """Read model from .env — supports OPENAI_MODEL and OPENROUTER_MODEL."""
    model = os.environ.get("OPENROUTER_MODEL") or os.environ.get("OPENAI_MODEL")
    if model:
        return model
    if os.environ.get("OPENAI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
        return "gpt-4o-mini"
    return "liquid/lfm-2.5-2.6b:free"


def _fmt(value) -> str:
    """Format a value for the prompt — handle None and NaN safely."""
    if value is None or (isinstance(value, float) and value != value):
        return "N/A"
    return str(value)


def build_prompt(settlement_row, candidates: dict) -> str:
    """
    Build the user message for the LLM.
    Shows the settlement record + bank candidate + ledger candidate.
    The LLM references specific field values in its reason.
    """
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
    """
    Make one synchronous API call to OpenRouter.
    If the model doesn't support response_format, retry without it.
    Kept for backwards-compatibility with sync callers.
    """
    try:
        response = get_client().chat.completions.create(
            model=get_model(),
            max_tokens=400,  # short — we only need JSON, not prose
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
    return response.choices[0].message.content or ""


async def _call_llm_async(prompt: str) -> str:
    """
    FIX #2: Async version of _call_llm — awaitable, non-blocking.
    Multiple of these can run concurrently via asyncio.gather in run_pipeline_async.
    Falls back to no response_format if the model doesn't support JSON mode.
    """
    try:
        response = await get_async_client().chat.completions.create(
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
            response = await get_async_client().chat.completions.create(
                model=get_model(),
                max_tokens=400,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        else:
            raise
    return response.choices[0].message.content or ""


def _clean_json_text(text: str) -> str:
    """
    Extract JSON substring from markdown code blocks or surrounding text.
    Handles ```json ... ``` wrappers and conversational preambles cleanly.
    """
    text = text.strip()
    # Strip markdown ```json wrapper if present
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Extract substring between first '{' and last '}'
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    return text


def _parse_llm_response(raw: str | None, last_error: str) -> AdjudicationResult:
    """
    Shared response-parsing logic used by both sync and async adjudicators.
    All error paths return ESCALATE_TO_HUMAN — never crashes.
    """
    if raw is None or not raw.strip():
        return AdjudicationResult(
            decision=DecisionType.ESCALATE_TO_HUMAN,
            reason=f"API error during adjudication after retry: {last_error[:200]}",
            confidence=0.0,
        )
    try:
        cleaned = _clean_json_text(raw)
        parsed = json.loads(cleaned)
        return AdjudicationResult(**parsed)  # Pydantic validates here — the real safety net
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


def adjudicate(settlement_row, candidates: dict) -> AdjudicationResult:
    """
    Synchronous entry point: ask the LLM to judge one ambiguous record.
    Kept for backwards-compatibility. Prefer adjudicate_async() for new code.

    Error handling (never crashes):
      - API error → retry once, then ESCALATE
      - Bad JSON → ESCALATE with raw output logged
      - Invalid enum (e.g. "UNCERTAIN") → Pydantic rejects → ESCALATE
      - Generic reason → Pydantic rejects → ESCALATE
    """
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
                time.sleep(RETRY_DELAY_SECONDS)  # sync callers: blocking sleep is acceptable
    return _parse_llm_response(raw, last_error)


async def adjudicate_async(settlement_row, candidates: dict) -> AdjudicationResult:
    """
    FIX #2 + #3: Async entry point — awaitable and non-blocking.
    Called via asyncio.gather in run_pipeline_async for concurrent LLM adjudication.
    Uses asyncio.sleep (non-blocking) instead of time.sleep on retry.

    Error handling (same as sync version — never crashes):
      - API error → retry once with asyncio.sleep, then ESCALATE
      - Bad JSON → ESCALATE
      - Invalid Pydantic → ESCALATE
    """
    prompt = build_prompt(settlement_row, candidates)
    raw = None
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            raw = await _call_llm_async(prompt)
            break
        except Exception as e:
            last_error = str(e)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY_SECONDS)  # FIX #3: non-blocking retry wait
    return _parse_llm_response(raw, last_error)
