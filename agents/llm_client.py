"""LLM access via LiteLLM-style model strings, with zero-cost mock fallback.

If OPENAI_API_KEY is set, real calls go through the OpenAI SDK (works with
`openai/gpt-4o-mini`, `anthropic/claude-3-5-sonnet`, etc. when routed via an
OpenAI-compatible gateway). Without a key everything degrades to a fully
deterministic MockLLM so the prototype is 100% free to run and evaluate.
"""
from __future__ import annotations

import json
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from config import llm_configured

T = TypeVar("T", bound=BaseModel)


class MockLLM:
    """Deterministic offline 'model' used when no API key is configured."""

    @staticmethod
    def complete(prompt: str, schema: Type[T], **kwargs) -> T:
        name = schema.__name__
        if name == "ResearchOutput":
            return _mock_research(prompt, schema)
        if name == "DraftOutput":
            return _mock_draft(prompt, schema)
        if name == "IntentOutput":
            return _mock_intent(prompt, schema)
        if name == "FollowupOutput":
            return _mock_followup(prompt, schema)
        raise ValueError(f"No mock behaviour registered for schema {name}")


def generate(prompt: str, schema: Type[T], system: str = "") -> T:
    """Structured-output generation: returns a validated pydantic model."""
    if llm_configured():
        return _real_generate(prompt, schema, system)
    return MockLLM.complete(prompt, schema)


def _real_generate(prompt: str, schema: Type[T], system: str) -> T:
    from openai import OpenAI

    client = OpenAI()
    completion = client.chat.completions.create(
        model=_model_name(),
        messages=([{"role": "system", "content": system}] if system else [])
        + [{"role": "user", "content": prompt}],
        response_format=json_schema_or_text(schema),
    )
    raw = completion.choices[0].message.content or "{}"
    return schema.model_validate_json(raw)


def _model_name() -> str:
    from config import LLM_MODEL
    # tolerate LiteLLM-style prefixes ("openai/...") for OpenAI SDK use
    return LLM_MODEL.split("/", 1)[-1] if "/" in LLM_MODEL else LLM_MODEL


def json_schema_or_text(schema: Type[T]) -> dict:
    try:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "strict": True,
                "schema": schema.model_json_schema(),
            },
            # Some gateways reject strict mode; retry hint for callers.
        }
    except Exception:
        return {"type": "json_object"}


# ─────────────────────────── pydantic contracts ────────────────────────────
class ResearchOutput(BaseModel):
    companies: list  # populated by research agent fixtures/LLM


class DraftOutput(BaseModel):
    connection_note: str
    followup_angle: str
    sources: list[str] = []
    flags: str = ""


class IntentOutput(BaseModel):
    intent: str
    confidence: float
    reasoning: str


class FollowupOutput(BaseModel):
    message: str


# ──────────────────────────── mock behaviours ──────────────────────────────
def _mock_research(prompt: str, schema: Type[T]) -> T:
    # Research is fixture-driven in mock mode; see research_agent.
    return schema.model_validate({"companies": []})


def _mock_draft(prompt: str, schema: Type[T]) -> T:
    return schema.model_validate({
        "connection_note": (
            "Hi {name} — I lead partnerships for Agentic AI Build Week (Nov 10–14, "
            "{geo}-focused hackathon, 300+ AI builders). {hook} Would your team be open "
            "to sponsoring? Happy to send a one-pager."
        ),
        "followup_angle": "Reference the builder audience overlap and ask for 15 minutes.",
    })


def _mock_intent(prompt: str, schema: Type[T]) -> T:
    p = prompt.lower()
    if any(k in p for k in ("not interested", "pass on this", "not the right time",
                            "opt out", "unsubscribe", "stop contacting")):
        intent, conf = "DECLINED", 0.93
    elif any(k in p for k in ("deck", "more info", "pricing", "packages", "sponsorship involve")):
        intent, conf = "REQUEST_MORE_INFO", 0.9
    elif any(k in p for k in ("call", "meeting", "book", "chat", "interested")):
        intent, conf = "INTERESTED", 0.92
    elif len(prompt) > 240 or any(k in p for k in ("negotiate", "discount", "roi",
                                                   "budget cycle", "procurement")):
        intent, conf = "COMPLEX_QUESTION", 0.85
    else:
        intent, conf = "NEUTRAL_ACK", 0.6
    return schema.model_validate({
        "intent": intent, "confidence": conf,
        "reasoning": "MockLLM keyword rules — deterministic zero-budget classification.",
    })


def _mock_followup(prompt: str, schema: Type[T]) -> T:
    return schema.model_validate({
        "message": (
            "Just floating this back to the top of your inbox — with 300+ AI builders "
            "at Agentic AI Build Week, a sponsor slot is a fast way to reach hiring "
            "-ready talent. If timing is off, happy to loop in closer to the event."
        ),
    })
