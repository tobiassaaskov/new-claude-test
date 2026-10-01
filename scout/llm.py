"""Thin helpers around the Anthropic SDK: client set-up, the pause_turn loop and cost tracking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic

# Server-side refusal fallback (beta): if a safety classifier declines a request,
# the API retries it on a fallback model instead of returning the refusal.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Claude Opus 5.5 list prices in USD, used only for the cost estimate shown on the dashboard.
PRICE_PER_MTOK = {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20}
PRICE_PER_WEB_SEARCH = 0.01

MAX_CONTINUATIONS = 8


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    web_searches: int = 0
    web_fetches: int = 0
    requests: int = 0

    def add(self, usage: Any) -> None:
        self.requests += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        server = getattr(usage, "server_tool_use", None)
        if server is not None:
            self.web_searches += getattr(server, "web_search_requests", 0) or 0
            self.web_fetches += getattr(server, "web_fetch_requests", 0) or 0

    @property
    def estimated_cost_usd(self) -> float:
        tokens = (
            self.input_tokens * PRICE_PER_MTOK["input"]
            + self.output_tokens * PRICE_PER_MTOK["output"]
            + self.cache_write_tokens * PRICE_PER_MTOK["cache_write"]
            + self.cache_read_tokens * PRICE_PER_MTOK["cache_read"]
        ) / 1_000_000
        return round(tokens + self.web_searches * PRICE_PER_WEB_SEARCH, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "web_searches": self.web_searches,
            "web_fetches": self.web_fetches,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


def make_client() -> anthropic.Anthropic:
    # Reads ANTHROPIC_API_KEY. Extra retries ride out rate limits on new API accounts.
    return anthropic.Anthropic(max_retries=6)


def base_params(model: str, effort: str) -> dict[str, Any]:
    return {
        "model": model,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


def run_until_done(
    client: anthropic.Anthropic, usage: Usage, *, messages: list[Any], **params: Any
) -> tuple[Any, list[Any]]:
    """Stream one request and resume it while the server-side tool loop pauses (stop_reason "pause_turn").
    Returns the final message and the conversation that produced it."""
    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(messages=messages, **params) as stream:
            message = stream.get_final_message()
        usage.add(message.usage)
        if message.stop_reason != "pause_turn":
            return message, messages
        # Send the paused turn back unchanged; the API resumes where it stopped.
        messages = messages + [{"role": "assistant", "content": message.content}]
    raise RuntimeError(f"Turn still paused after {MAX_CONTINUATIONS} continuations")


def tool_inputs(message: Any, tool_name: str) -> list[dict[str, Any]]:
    return [
        block.input
        for block in message.content
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name
    ]


def collect_tool_input(
    client: anthropic.Anthropic,
    usage: Usage,
    *,
    tool_name: str,
    nudge: str,
    messages: list[Any],
    **params: Any,
) -> tuple[list[dict[str, Any]], Any]:
    """Run a turn in which Claude should finish by calling our reporting tool, and return that tool's input.
    Forced tool choice isn't available on this model, so if Claude ends without calling it we ask once more."""
    message, messages = run_until_done(client, usage, messages=messages, **params)
    calls = tool_inputs(message, tool_name)
    if calls or message.stop_reason == "refusal":
        return calls, message
    messages = messages + [
        {"role": "assistant", "content": message.content},
        {"role": "user", "content": nudge},
    ]
    message, _ = run_until_done(client, usage, messages=messages, **params)
    return tool_inputs(message, tool_name), message
