"""Stand-ins for the Anthropic client so the pipeline can be tested without network access or an API key."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable


def usage(input_tokens: int = 1000, output_tokens: int = 200, searches: int = 0, fetches: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        server_tool_use=SimpleNamespace(web_search_requests=searches, web_fetch_requests=fetches),
    )


def tool_call(name: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload, id=f"toolu_{name}")


def text(value: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=value)


def message(*blocks: Any, stop_reason: str = "tool_use", usage_obj: Any = None, model: str = "claude-opus-5-5") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage_obj or usage(), model=model)


class _Stream:
    def __init__(self, result: Any):
        self._result = result

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def get_final_message(self) -> Any:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeClient:
    """Replays scripted responses. `script` is either a list consumed in order or a function of the request."""

    def __init__(self, script: list[Any] | Callable[[dict[str, Any]], Any]):
        self.calls: list[dict[str, Any]] = []
        self._script = script
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **params: Any) -> _Stream:
        self.calls.append(params)
        result = self._script(params) if callable(self._script) else self._script.pop(0)
        return _Stream(result)
