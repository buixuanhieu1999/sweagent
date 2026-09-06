"""Provider contract and native Ollama HTTP adapter; no agent imports HTTP code."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ProviderResponse:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    done_reason: str = ""
    thinking: str = ""

    def message(self) -> dict[str, Any]:
        result: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.thinking:
            result["thinking"] = self.thinking
        return result


class LLMProvider(Protocol):
    model: str

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        stream: bool = False,
        response_schema: dict | None = None,
        on_text: Callable[[str], None] | None = None,
        model: str | None = None,
    ) -> ProviderResponse: ...

    def health(self) -> bool: ...


class OllamaProvider:
    def __init__(
        self,
        model: str,
        host: str,
        api_key: str | None = None,
        timeout: int = 600,
        keep_alive: str = "10m",
        think: Any = None,
    ):
        parsed = urllib.parse.urlsplit(host)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Ollama host must be an HTTP(S) URL without credentials/query/fragment"
            )
        self.host = host.rstrip("/")
        if not self.host.endswith("/api"):
            self.host += "/api"
        self.model, self.api_key = model, api_key
        self.timeout, self.keep_alive, self.think = timeout, keep_alive, think

    def _request(self, endpoint: str, payload: dict | None = None):
        return urllib.request.Request(
            self.host + endpoint,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(self._request("/tags"), timeout=5) as response:
                return isinstance(json.load(response).get("models"), list)
        except (OSError, ValueError):
            return False

    def complete(self, prompt: str, **kwargs) -> ProviderResponse:
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def chat(
        self,
        messages,
        tools=None,
        *,
        stream=False,
        response_schema=None,
        on_text=None,
        model=None,
    ) -> ProviderResponse:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": stream,
            "keep_alive": self.keep_alive,
        }
        if tools:
            payload["tools"] = tools
        if response_schema:
            payload["format"] = response_schema
        if self.think is not None:
            payload["think"] = self.think
        result = ProviderResponse()
        indexed: dict[int, dict] = {}
        finished = False
        try:
            response = None
            for attempt in range(3):
                try:
                    response = urllib.request.urlopen(
                        self._request("/chat", payload), timeout=self.timeout
                    )
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                        raise
                    time.sleep(2**attempt)
            with response:
                chunks = response if stream else [response.read()]
                for raw in chunks:
                    if not raw.strip():
                        continue
                    chunk = json.loads(raw)
                    if chunk.get("error"):
                        raise RuntimeError(f"Ollama: {chunk['error']}")
                    message = chunk.get("message")
                    if not isinstance(message, dict):
                        raise RuntimeError("Ollama returned no assistant message")
                    content = message.get("content", "")
                    if not isinstance(content, str) or not isinstance(
                        message.get("thinking", ""), str
                    ):
                        raise RuntimeError("Ollama returned invalid message text")
                    calls = message.get("tool_calls") or []
                    if not isinstance(calls, list) or any(
                        not isinstance(c, dict)
                        or not isinstance(c.get("function"), dict)
                        or not isinstance(c["function"].get("name", ""), str)
                        for c in calls
                    ):
                        raise RuntimeError("Ollama returned malformed tool calls")
                    result.content += content
                    result.thinking += message.get("thinking", "")
                    if on_text and content:
                        on_text(content)
                    for call in calls:
                        fn = call.get("function", {})
                        index = fn.get("index", call.get("index"))
                        if index is None:
                            result.tool_calls.append(call)
                            continue
                        target = indexed.setdefault(
                            index, {"function": {"name": "", "arguments": {}}}
                        )["function"]
                        if fn.get("name"):
                            target["name"] = fn["name"]
                        arguments = fn.get("arguments", {})
                        if isinstance(arguments, str):
                            previous = target["arguments"]
                            target["arguments"] = (
                                previous if isinstance(previous, str) else ""
                            ) + arguments
                        elif isinstance(arguments, dict):
                            if not isinstance(target["arguments"], dict):
                                raise RuntimeError(
                                    "Inconsistent streamed tool arguments"
                                )
                            target["arguments"].update(arguments)
                    if chunk.get("done"):
                        finished = True
                        result.done_reason = chunk.get("done_reason", "")
                        result.usage = {
                            k: chunk[k]
                            for k in ("prompt_eval_count", "eval_count")
                            if k in chunk
                        }
            if stream and not finished:
                raise RuntimeError("Ollama stream interrupted; no tools were executed")
            result.tool_calls.extend(indexed[k] for k in sorted(indexed))
            return result
        except urllib.error.HTTPError as exc:
            # Avoid reflecting server bodies that may contain credential-bearing requests.
            raise RuntimeError(
                f"Ollama HTTP {exc.code}; check endpoint, model and authentication"
            ) from exc
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
