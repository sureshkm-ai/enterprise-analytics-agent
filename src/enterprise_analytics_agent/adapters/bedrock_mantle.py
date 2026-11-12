"""AWS-only Gemma chat transport, normalized to the existing Converse boundary.

The fixed Bedrock Mantle route uses refreshed workload/developer AWS credentials,
never an OpenAI key or endpoint. Construction is offline. Each method sends one
signed HTTP request; streaming failures are terminal and never retried.
"""

import codecs
import json
import math
import re
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Protocol, cast

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSPreparedRequest, AWSRequest
from botocore.httpsession import URLLib3Session

MODEL_ID = "google.gemma-4-31b"
REGION = "us-west-2"
ENDPOINT = "https://bedrock-mantle.us-west-2.api.aws/openai/v1/chat/completions"
MAX_BYTES = 3_500_000
MAX_LINE_BYTES = 128 * 1024
MAX_EVENTS = 20_000


class MantleError(ValueError):
    """Authored, payload-free failure context safe for the operator diagnostics."""

    def __init__(self, code: str, *, status: int | None = None) -> None:
        self.code = code
        self.diagnostic = {
            "service": "bedrock-mantle",
            "operation": "CreateInference",
            "attempt": 1,
            "region": REGION,
            "endpoint_host": "bedrock-mantle.us-west-2.api.aws",
            "model_id": MODEL_ID,
            "error_code": code,
            "http_status": status,
            "will_retry": False,
        }
        super().__init__("Bedrock Mantle inference failed: " + code)


class HttpSender(Protocol):
    def send(self, request: AWSPreparedRequest) -> Any: ...

    def close(self) -> None: ...


class _ClosingStream(Iterator[dict[str, object]]):
    def __init__(self, events: Iterator[dict[str, object]], close: Callable[[], None]) -> None:
        self.events, self.cleanup = events, close

    def __next__(self) -> dict[str, object]:
        return next(self.events)

    def close(self) -> None:
        try:
            close = getattr(self.events, "close", None)
            if callable(close):
                close()
        finally:
            # A Python generator's finally does not run when closed before its
            # first next(). The HTTP response was already obtained synchronously.
            self.cleanup()


def _close(response: Any, owned: Any) -> None:
    for resource in (getattr(response, "raw", None), owned):
        if resource is not None:
            try:
                resource.close()
            except Exception:
                # Best-effort disposal cannot replace the original stream failure.
                pass


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise MantleError("malformed_response")
    return cast(dict[str, Any], value)


def _items(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise MantleError("malformed_response")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise MantleError("malformed_response")
    return value


def _identifier(value: object) -> str:
    text = _text(value)
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", text) is None:
        raise MantleError("malformed_tool_call")
    return text


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise MantleError("malformed_usage")
    return value


def _usage(value: object) -> dict[str, object]:
    source = _object(value)
    prompt, completion = (
        _integer(source.get("prompt_tokens")),
        _integer(source.get("completion_tokens")),
    )
    total = _integer(source.get("total_tokens"))
    if total != prompt + completion:
        raise MantleError("malformed_usage")
    return {"inputTokens": prompt, "outputTokens": completion, "totalTokens": total}


def _encoded(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise MantleError("unsupported_request") from None


def _messages(messages: object) -> list[dict[str, object]]:
    source = _items(messages)
    if not 1 <= len(source) <= 200:
        raise MantleError("unsupported_request")
    output: list[dict[str, object]] = []
    for raw in source:
        message = _object(raw)
        role = message.get("role")
        if set(message) != {"role", "content"} or role not in {"user", "assistant"}:
            raise MantleError("unsupported_request")
        content = _items(message["content"])
        if not content:
            raise MantleError("unsupported_request")
        texts: list[str] = []
        calls: list[dict[str, object]] = []
        results: list[dict[str, object]] = []
        for raw_block in content:
            block = _object(raw_block)
            if set(block) == {"text"}:
                texts.append(_text(block["text"]))
            elif set(block) == {"toolUse"} and role == "assistant":
                tool = _object(block["toolUse"])
                if set(tool) != {"toolUseId", "name", "input"}:
                    raise MantleError("unsupported_request")
                arguments = _object(tool["input"])
                calls.append(
                    {
                        "id": _identifier(tool["toolUseId"]),
                        "type": "function",
                        "function": {
                            "name": _identifier(tool["name"]),
                            "arguments": _encoded(arguments),
                        },
                    }
                )
            elif set(block) == {"toolResult"} and role == "user":
                tool = _object(block["toolResult"])
                if not set(tool) <= {"toolUseId", "content", "status"} or tool.get(
                    "status"
                ) not in {None, "success", "error"}:
                    raise MantleError("unsupported_request")
                result_content = _items(tool.get("content"))
                if not result_content:
                    raise MantleError("unsupported_request")
                values: list[object] = []
                for item in result_content:
                    item = _object(item)
                    if set(item) == {"json"}:
                        values.append(item["json"])
                    elif set(item) == {"text"}:
                        values.append(_text(item["text"]))
                    else:
                        raise MantleError("unsupported_request")
                value = values[0] if len(values) == 1 else values
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": _identifier(tool.get("toolUseId")),
                        "content": value if isinstance(value, str) else _encoded(value),
                    }
                )
            else:
                raise MantleError("unsupported_request")
        if results:
            if texts or calls:
                raise MantleError("unsupported_request")
            output.extend(results)
        else:
            if len(calls) > 1:
                raise MantleError("parallel_tools_unsupported")
            converted: dict[str, object] = {"role": role, "content": "".join(texts)}
            if calls:
                converted["content"] = "".join(texts) if texts else None
                converted["tool_calls"] = calls
            output.append(converted)
    return output


def _request(kwargs: Mapping[str, object], *, stream: bool) -> dict[str, object]:
    if not set(kwargs) <= {"modelId", "messages", "system", "toolConfig", "inferenceConfig"}:
        raise MantleError("unsupported_request")
    if kwargs.get("modelId") != MODEL_ID:
        raise MantleError("unconfigured_model")
    messages: list[dict[str, object]] = []
    system = kwargs.get("system")
    if system is not None:
        parts = []
        for raw in _items(system):
            block = _object(raw)
            if set(block) != {"text"}:
                raise MantleError("unsupported_request")
            parts.append(_text(block["text"]))
        messages.append({"role": "system", "content": "\n".join(parts)})
    messages.extend(_messages(kwargs.get("messages")))
    result: dict[str, object] = {"model": MODEL_ID, "messages": messages, "stream": stream}
    config = _object(kwargs.get("inferenceConfig", {}))
    if not set(config) <= {"maxTokens", "temperature", "topP", "stopSequences"}:
        raise MantleError("unsupported_request")
    maximum = _integer(config.get("maxTokens", 1024))
    if not 1 <= maximum <= 4096:
        raise MantleError("unsupported_request")
    result["max_tokens"] = maximum
    for source, target, upper in (("temperature", "temperature", 2), ("topP", "top_p", 1)):
        if source in config:
            value = config[source]
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not 0 <= value <= upper
            ):
                raise MantleError("unsupported_request")
            result[target] = value
    if "stopSequences" in config:
        stops = _items(config["stopSequences"])
        if not 1 <= len(stops) <= 10 or any(not isinstance(item, str) for item in stops):
            raise MantleError("unsupported_request")
        result["stop"] = stops
    if "toolConfig" in kwargs:
        if stream:
            raise MantleError("streaming_tools_not_configured")
        tools = _object(kwargs["toolConfig"])
        if not set(tools) <= {"tools", "toolChoice"} or tools.get("toolChoice", {"auto": {}}) != {
            "auto": {}
        }:
            raise MantleError("unsupported_request")
        translated = []
        for raw in _items(tools.get("tools")):
            wrapper = _object(raw)
            if set(wrapper) != {"toolSpec"}:
                raise MantleError("unsupported_request")
            spec = _object(wrapper["toolSpec"])
            if not set(spec) <= {"name", "description", "inputSchema"}:
                raise MantleError("unsupported_request")
            schema = _object(spec.get("inputSchema"))
            if set(schema) != {"json"}:
                raise MantleError("unsupported_request")
            translated.append(
                {
                    "type": "function",
                    "function": {
                        "name": _identifier(spec.get("name")),
                        "description": _text(spec.get("description", "")),
                        "parameters": _object(schema["json"]),
                    },
                }
            )
        if not 1 <= len(translated) <= 4:
            raise MantleError("unsupported_request")
        result["tools"] = translated
        result["tool_choice"] = "auto"
        result["parallel_tool_calls"] = False
    if stream:
        result["stream_options"] = {"include_usage": True}
    return result


def _choice(value: object) -> dict[str, Any]:
    choices = _items(value)
    if len(choices) != 1:
        raise MantleError("malformed_response")
    choice = _object(choices[0])
    if choice.get("index", 0) != 0:
        raise MantleError("malformed_response")
    return choice


def _reply(value: object) -> dict[str, object]:
    reply = _object(value)
    if "error" in reply or reply.get("model", MODEL_ID) != MODEL_ID:
        raise MantleError("malformed_response")
    choice = _choice(reply.get("choices"))
    message = _object(choice.get("message"))
    if message.get("role") != "assistant":
        raise MantleError("malformed_response")
    content: list[dict[str, object]] = []
    text = message.get("content")
    if text is not None:
        content.append({"text": _text(text)})
    calls = _items(message.get("tool_calls", []))
    if len(calls) > 1:
        raise MantleError("parallel_tools_unsupported")
    for raw in calls:
        call = _object(raw)
        function = _object(call.get("function"))
        if call.get("type") != "function":
            raise MantleError("malformed_tool_call")
        try:
            arguments = json.loads(_text(function.get("arguments")))
        except ValueError:
            raise MantleError("malformed_tool_call") from None
        content.append(
            {
                "toolUse": {
                    "toolUseId": _identifier(call.get("id")),
                    "name": _identifier(function.get("name")),
                    "input": _object(arguments),
                }
            }
        )
    reason = choice.get("finish_reason")
    if not isinstance(reason, str):
        raise MantleError("malformed_response")
    stop = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}.get(reason)
    if stop is None or bool(calls) != (stop == "tool_use"):
        raise MantleError("malformed_response")
    if not content:
        content.append({"text": ""})
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": _usage(reply.get("usage")),
    }


class BedrockMantleClient:
    """Converse-shaped Gemma bridge; injected credentials are refreshed per request."""

    def __init__(
        self,
        *,
        session: Any,
        transport: HttpSender | None = None,
        timeout_seconds: float = 90,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("Mantle timeout must be within (0,300] seconds")
        self.session, self.transport = session, transport
        self.timeout_seconds, self.clock = timeout_seconds, clock

    def _deadline(self, deadline: float) -> None:
        if self.clock() >= deadline:
            raise MantleError("deadline_exceeded")

    def _send(self, payload: dict[str, object], deadline: float) -> tuple[Any, Any]:
        body = _encoded(payload).encode()
        if len(body) > MAX_BYTES:
            raise MantleError("request_too_large")
        self._deadline(deadline)
        owned = self.transport is None
        transport = self.transport
        try:
            credentials = self.session.get_credentials()
            if credentials is None:
                raise MantleError("credentials_unavailable")
            frozen = credentials.get_frozen_credentials()
            self._deadline(deadline)
            request = AWSRequest(
                method="POST",
                url=ENDPOINT,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                    "Accept": "text/event-stream" if payload["stream"] else "application/json",
                },
                stream_output=True,
            )
            SigV4Auth(frozen, "bedrock-mantle", REGION).add_auth(request)
            if transport is None:
                # botocore's single-send transport uses urllib3 Retry(False), so
                # neither SDK retries nor HTTP redirect replay can add a dispatch.
                transport = URLLib3Session(
                    # botocore accepts a (connect, read) tuple; its stub is narrower.
                    timeout=(min(5, self.timeout_seconds), min(30, self.timeout_seconds))  # type: ignore[arg-type]
                )
            self._deadline(deadline)
            response = transport.send(request.prepare())
        except MantleError:
            if owned and transport is not None:
                _close(None, transport)
            raise
        except Exception:
            if owned and transport is not None:
                _close(None, transport)
            raise MantleError("transport_or_credentials_error") from None
        except BaseException:
            if owned and transport is not None:
                _close(None, transport)
            raise
        try:
            self._deadline(deadline)
            if response.status_code != 200:
                raise MantleError("http_error", status=response.status_code)
            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
            expected = "text/event-stream" if payload["stream"] else "application/json"
            if headers.get("content-type", "").split(";", 1)[0].strip().lower() != expected:
                raise MantleError("unexpected_content_type")
            if headers.get("content-encoding", "identity").lower() != "identity":
                raise MantleError("unsupported_content_encoding")
            length = headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
                raise MantleError("response_too_large")
        except MantleError:
            _close(response, transport if owned else None)
            raise
        except Exception:
            _close(response, transport if owned else None)
            raise MantleError("malformed_response") from None
        except BaseException:
            _close(response, transport if owned else None)
            raise
        return response, transport if owned else None

    def _chunks(self, response: Any, deadline: float) -> Iterator[bytes]:
        size = 0
        while True:
            self._deadline(deadline)
            try:
                content = response.raw.read1(4096, decode_content=False)
            except Exception:
                raise MantleError("stream_read_error") from None
            self._deadline(deadline)
            if not isinstance(content, bytes):
                raise MantleError("malformed_response")
            if not content:
                return
            size += len(content)
            if size > MAX_BYTES:
                raise MantleError("response_too_large")
            yield content

    def converse(self, **kwargs: object) -> dict[str, object]:
        payload = _request(kwargs, stream=False)
        deadline = self.clock() + self.timeout_seconds
        response, owned = self._send(payload, deadline)
        try:
            content = b"".join(self._chunks(response, deadline))
            try:
                value = json.loads(content)
            except (ValueError, UnicodeError):
                raise MantleError("malformed_response") from None
            return _reply(value)
        finally:
            _close(response, owned)

    def _sse(self, response: Any, deadline: float) -> Iterator[str]:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        buffer = ""
        data: list[str] = []
        events = 0
        try:
            for chunk in self._chunks(response, deadline):
                buffer += decoder.decode(chunk)
                if len(buffer.encode()) > MAX_BYTES:
                    raise MantleError("stream_frame_too_large")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.removesuffix("\r")
                    if len(line.encode()) > MAX_LINE_BYTES:
                        raise MantleError("stream_frame_too_large")
                    if not line:
                        if data:
                            events += 1
                            if events > MAX_EVENTS:
                                raise MantleError("too_many_stream_events")
                            yield "\n".join(data)
                            data = []
                    elif line.startswith("data:"):
                        data.append(line[5:].removeprefix(" "))
                        if sum(len(part.encode()) for part in data) > MAX_LINE_BYTES:
                            raise MantleError("stream_frame_too_large")
                    elif not line.startswith((":", "event:", "id:", "retry:")):
                        raise MantleError("malformed_stream")
                if len(buffer.encode()) > MAX_LINE_BYTES:
                    raise MantleError("stream_frame_too_large")
            buffer += decoder.decode(b"", final=True)
        except UnicodeError:
            raise MantleError("malformed_utf8") from None
        if buffer.strip() or data:
            raise MantleError("truncated_stream")

    def converse_stream(self, **kwargs: object) -> dict[str, object]:
        payload = _request(kwargs, stream=True)
        deadline = self.clock() + self.timeout_seconds
        response, owned = self._send(payload, deadline)
        closed = False

        def cleanup() -> None:
            nonlocal closed
            if not closed:
                closed = True
                _close(response, owned)

        def events() -> Iterator[dict[str, object]]:
            stop: str | None = None
            usage: dict[str, object] | None = None
            try:
                yield {"messageStart": {"role": "assistant"}}
                for data in self._sse(response, deadline):
                    if data == "[DONE]":
                        if stop is None or usage is None:
                            raise MantleError("incomplete_stream")
                        yield {"contentBlockStop": {"contentBlockIndex": 0}}
                        yield {"messageStop": {"stopReason": stop}}
                        yield {"metadata": {"usage": usage}}
                        return
                    try:
                        chunk = _object(json.loads(data))
                    except ValueError:
                        raise MantleError("malformed_stream") from None
                    if "error" in chunk or chunk.get("model", MODEL_ID) != MODEL_ID:
                        raise MantleError("provider_stream_error")
                    if chunk.get("usage") is not None:
                        current = _usage(chunk["usage"])
                        if usage is not None and current != usage:
                            raise MantleError("malformed_usage")
                        usage = current
                    choices = _items(chunk.get("choices"))
                    if not choices:
                        if chunk.get("usage") is None:
                            raise MantleError("malformed_stream")
                        continue
                    choice = _choice(choices)
                    delta = _object(choice.get("delta"))
                    if delta.get("role", "assistant") != "assistant" or delta.get("tool_calls"):
                        raise MantleError("unexpected_stream_tool")
                    text = delta.get("content")
                    # Provider reasoning, signatures and private metadata are never
                    # forwarded to the public text delta or semantic interface.
                    if text is not None:
                        text = _text(text)
                        if stop is not None and text:
                            raise MantleError("output_after_stop")
                        if text:
                            yield {
                                "contentBlockDelta": {
                                    "contentBlockIndex": 0,
                                    "delta": {"text": text},
                                }
                            }
                    reason = choice.get("finish_reason")
                    if reason is not None:
                        if stop is not None or reason not in {"stop", "length"}:
                            raise MantleError("malformed_stream")
                        stop = "end_turn" if reason == "stop" else "max_tokens"
                raise MantleError("truncated_stream")
            finally:
                cleanup()

        return {"stream": _ClosingStream(events(), cleanup)}
