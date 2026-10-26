"""The model connection plus every guard around it: consent, daily budget, per-run limits,
usage/cost logging (numbers only), prompt-injection flagging, and secret redaction."""

from __future__ import annotations

import os
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import cache
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from . import db
from .config import (DAILY_BUDGET_USD, MAX_OUTPUT_TOKENS, MODEL_NAME, PORTKEY_BASE_URL, REASONING_EFFORT,
                     RUN_REQUEST_LIMIT, RUN_TOKEN_LIMIT, portkey_api_key)


class AIBlocked(Exception):
    """Raised before any model call when consent, key, or budget says no. The message is shown to the user."""


# The course's Portkey config can replay identical requests from its gateway cache. Replays report the
# original token counts with ~0 latency, which would make our measurements wrong, so by default we ask the
# gateway for a fresh answer and record its cache status for every response. Our own ai_cache (pipeline.py)
# already avoids repeating identical work.
FORCE_FRESH = os.getenv("PORTKEY_CACHE_FORCE_REFRESH", "true").lower() not in {"0", "false", "no"}
_gateway_status: ContextVar[list[str] | None] = ContextVar("gateway_status", default=None)


async def _note_gateway(response: httpx.Response) -> None:
    seen = _gateway_status.get()
    if seen is not None:
        seen.append(response.headers.get("x-portkey-cache-status", "n/a"))


@cache
def model() -> OpenAIResponsesModel:
    key = portkey_api_key()
    headers = {"x-portkey-api-key": key}
    if FORCE_FRESH:
        headers["x-portkey-cache-force-refresh"] = "true"
    client = AsyncOpenAI(base_url=PORTKEY_BASE_URL, api_key=key, default_headers=headers, max_retries=1, timeout=120,
                         http_client=httpx.AsyncClient(timeout=120, event_hooks={"response": [_note_gateway]}))
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def settings(cache_key: str) -> OpenAIResponsesModelSettings:
    # The prompt cache key groups requests that share our long static instructions, so repeat
    # workflows get billed at the cached-input rate.
    return OpenAIResponsesModelSettings(openai_reasoning_effort=REASONING_EFFORT, max_tokens=MAX_OUTPUT_TOKENS,
                                        openai_prompt_cache_key=cache_key, openai_store=False)


def limits(tool_calls: int | None = None) -> UsageLimits:
    return UsageLimits(request_limit=RUN_REQUEST_LIMIT, total_tokens_limit=RUN_TOKEN_LIMIT, tool_calls_limit=tool_calls)


# --- prices: genai-prices' published gpt-6-luna rates (USD per million tokens), recorded at build time.
PRICE_IN, PRICE_CACHED_IN, PRICE_OUT = 0.10, 0.01, 0.50


def cost_usd(input_tokens: int, cached: int, output: int) -> float:
    return ((input_tokens - cached) * PRICE_IN + cached * PRICE_CACHED_IN + output * PRICE_OUT) / 1_000_000


def spent_today() -> float:
    day = datetime.now(timezone.utc).date().isoformat()
    r = db.row("SELECT COALESCE(SUM(cost_usd),0) AS s FROM usage_log WHERE ts >= ?", (day,))
    return float(r["s"])


def consent_given() -> bool:
    return db.get_setting("ai_consent") == "yes"


def preflight() -> None:
    if not consent_given():
        raise AIBlocked("AI features are off until you agree to send the selected health text to OpenAI "
                        "(through the Portkey gateway). Tracking and search keep working without AI.")
    if not os.getenv("PORTKEY_API_KEY"):
        raise AIBlocked("No PORTKEY_API_KEY found in .env (repo folder or the folder above). AI features are off.")
    spent = spent_today()
    if spent >= DAILY_BUDGET_USD:
        raise AIBlocked(f"Today's AI budget (${DAILY_BUDGET_USD:.2f}) is used up (${spent:.4f}). "
                        "AI features resume tomorrow; everything else still works.")


def log_usage(workflow: str, usage: Any, started: float, ok: bool, error: str | None = None,
              cache_hit: bool = False, gateway: list[str] | None = None) -> dict:
    inp = getattr(usage, "input_tokens", 0) or 0
    cached = getattr(usage, "cache_read_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    reasoning = (getattr(usage, "output_reasoning_tokens", 0) or
                 (getattr(usage, "details", {}) or {}).get("reasoning_tokens", 0))
    rec = dict(ts=db.now(), workflow=workflow, model=MODEL_NAME, requests=getattr(usage, "requests", 0) or 0,
               input_tokens=inp, cached_tokens=cached, output_tokens=out, reasoning_tokens=reasoning,
               latency_ms=int((time.perf_counter() - started) * 1000), cost_usd=round(cost_usd(inp, cached, out), 7),
               cache_hit=int(cache_hit), ok=int(ok), error=(error or "")[:200] or None,
               gateway_cache=",".join(gateway or []) or None)
    db.execute(f"INSERT INTO usage_log({','.join(rec)}) VALUES({','.join('?' for _ in rec)})", list(rec.values()))
    return rec


async def run(agent: Agent, prompt: Any, workflow: str, deps: Any = None, tool_calls: int | None = None):
    """Run an agent with all guards. Returns (output, usage record, result)."""
    preflight()
    started = time.perf_counter()
    gateway: list[str] = []
    token = _gateway_status.set(gateway)
    try:
        result = await agent.run(prompt, deps=deps, model=model(), usage_limits=limits(tool_calls),
                                 model_settings=settings(f"ummacare-{workflow}"))
    except Exception as e:
        usage = getattr(e, "usage", None)
        log_usage(workflow, usage, started, ok=False, error=type(e).__name__, gateway=gateway)
        raise
    finally:
        _gateway_status.reset(token)
    u = result.usage() if callable(result.usage) else result.usage
    rec = log_usage(workflow, u, started, ok=True, gateway=gateway)
    return result.output, rec, result


# --- untrusted text -----------------------------------------------------------------------

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"disregard (your|the|all) (instructions|rules|system)",
    r"(you are|act as) (now )?(an? |the )?(system|admin|developer|root)\b",
    r"\bsystem (prompt|message|override)\b", r"\bnew instructions\b",
    r"(api[_ ]?key|portkey|\.env|secret|password|token)s?\b.{0,40}(print|reveal|show|send|output|tell)",
    r"(print|reveal|show|send|output|tell).{0,40}(api[_ ]?key|portkey|\.env|secret|password)",
    r"(change|increase|double|stop|lower|update|set)\b.{0,40}\b(dose|dosage|medication|levothyroxine|mcg|mg)\b",
    r"\b(book|cancel|confirm)\b.{0,30}\bappointment\b.{0,30}\b(now|immediately|automatically)\b",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
_CAUTION = re.compile(r"^\W*(\d{1,2}:\d{2}\s+)?(never|don't|do not)\b", re.I)   # "Never change your dose without…" is advice, not an attack


def _flagged(sentence: str) -> bool:
    return any(p.search(sentence) for p in _INJ) and not _CAUTION.search(sentence)


def scan_untrusted(text: str) -> list[str]:
    """Flag (never execute) instruction-like text inside transcripts or imported notes."""
    hits = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if _flagged(sentence):
            hits.append(sentence.strip()[:240])
    return hits[:10]


NEUTRALIZED = "[instruction-like text removed before AI processing; shown to the user separately]"


def neutralize(text: str) -> str:
    """Replace flagged instruction-like sentences with a marker before text is sent to the model.
    The original stays in the database and is shown to the user with a warning."""
    parts = re.split(r"((?<=[.!?])\s+|\n)", text)
    return "".join(NEUTRALIZED if _flagged(x) else x for x in parts)


def record_safety_event(kind: str, source: str, detail: str) -> None:
    db.execute("INSERT INTO safety_events(ts,kind,source,detail) VALUES(?,?,?,?)", (db.now(), kind, source, detail[:500]))


_SECRET_SHAPES = [re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), re.compile(r"pk-[A-Za-z0-9_\-]{16,}")]


def redact(text: str) -> str:
    """Last line of defense: never let the real key (or anything key-shaped) leave the backend."""
    key = os.getenv("PORTKEY_API_KEY") or ""
    if key and key in text:
        text = text.replace(key, "[redacted secret]")
        record_safety_event("secret_redacted", "model_output", "Model output contained the API key; redacted.")
    for pat in _SECRET_SHAPES:
        text = pat.sub("[redacted secret]", text)
    return text


def wrap_untrusted(label: str, text: str) -> str:
    text = text.replace("</untrusted", "<​/untrusted")
    return f"<untrusted {label}>\n{text}\n</untrusted>"
