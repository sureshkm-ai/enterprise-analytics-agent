"""Gemma's AWS-only HTTP bridge: refreshed signing and strict stream conversion."""

import json
from collections import deque
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import boto3
import pytest
from botocore.awsrequest import AWSPreparedRequest
from botocore.credentials import Credentials

from enterprise_analytics_agent.adapters import bedrock_mantle as mantle


class Session:
    def __init__(self) -> None:
        self.calls = 0

    def get_credentials(self) -> Credentials:
        self.calls += 1
        return Credentials("ACCESS" + str(self.calls), "SECRET", "SESSION" + str(self.calls))


class Raw:
    def __init__(self, chunks: list[bytes | Exception]) -> None:
        self.chunks = deque(chunks)
        self.closed = 0
        self.cleanup_failure = False

    def read1(self, amount: int, *, decode_content: bool) -> bytes:
        assert amount == 4096 and decode_content is False
        value = self.chunks.popleft() if self.chunks else b""
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self) -> None:
        self.closed += 1
        if self.cleanup_failure:
            raise RuntimeError("private cleanup marker")


class Transport:
    def __init__(self, *responses: Any) -> None:
        self.responses = deque(responses)
        self.requests: list[AWSPreparedRequest] = []
        self.closed = 0

    def send(self, request: AWSPreparedRequest) -> Any:
        self.requests.append(request)
        value = self.responses.popleft()
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self) -> None:
        self.closed += 1


@pytest.fixture(autouse=True)
def no_sdk_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("the offline Mantle bridge must not create a profile or AWS session")

    monkeypatch.setattr(boto3, "Session", forbidden)


def response(body: bytes, *, stream: bool = False, status: int = 200) -> Any:
    return SimpleNamespace(
        status_code=status,
        headers={"Content-Type": "text/event-stream" if stream else "application/json"},
        raw=Raw([body[index : index + 7] for index in range(0, len(body), 7)]),
    )


def reply(*, calls: list[dict[str, object]] | None = None) -> dict[str, object]:
    message: dict[str, object] = {"role": "assistant", "content": "An exact result."}
    if calls:
        message["content"] = None
        message["tool_calls"] = calls
    return {
        "model": mantle.MODEL_ID,
        "choices": [
            {"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def request() -> dict[str, object]:
    return {
        "modelId": mantle.MODEL_ID,
        "system": [{"text": "Use governed tools."}],
        "messages": [{"role": "user", "content": [{"text": "Show net_revenue."}]}],
        "inferenceConfig": {"maxTokens": 512, "temperature": 0},
    }


def tool_config() -> dict[str, object]:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": "query_metric",
                    "description": "Governed metric.",
                    "inputSchema": {"json": {"type": "object"}},
                }
            }
        ],
        "toolChoice": {"auto": {}},
    }


def signature(request: AWSPreparedRequest) -> str:
    value = request.headers["Authorization"]
    return value.decode() if isinstance(value, bytes) else str(value)


def test_constructor_is_offline_and_signing_refreshes_credentials_each_dispatch() -> None:
    session = Session()
    first = response(json.dumps(reply()).encode())
    second = response(json.dumps(reply()).encode())
    transport = Transport(first, second)
    client = mantle.BedrockMantleClient(session=session, transport=transport)
    assert session.calls == 0 and transport.requests == []
    result = client.converse(**request())
    client.converse(**request())
    assert result["stopReason"] == "end_turn"
    assert result["usage"] == {"inputTokens": 10, "outputTokens": 3, "totalTokens": 13}
    assert len(transport.requests) == session.calls == 2
    assert all(item.url == mantle.ENDPOINT and item.method == "POST" for item in transport.requests)
    assert "/us-west-2/bedrock-mantle/aws4_request" in signature(transport.requests[0])
    assert "Credential=ACCESS1/" in signature(transport.requests[0])
    assert "Credential=ACCESS2/" in signature(transport.requests[1])
    assert first.raw.closed == second.raw.closed == 1
    assert transport.closed == 0, "the caller owns an injected shared HTTP transport"


def test_tool_definitions_call_ids_and_results_convert_without_parallel_execution() -> None:
    call: dict[str, object] = {
        "id": "call_01",
        "type": "function",
        "function": {"name": "query_metric", "arguments": '{"metric_id":"net_revenue"}'},
    }
    raw = response(json.dumps(reply(calls=[call])).encode())
    transport = Transport(raw)
    client = mantle.BedrockMantleClient(session=Session(), transport=transport)
    query = request()
    query["toolConfig"] = tool_config()
    query["messages"] = [
        {"role": "user", "content": [{"text": "Question"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "toolUse": {
                        "toolUseId": "prior_01",
                        "name": "query_metric",
                        "input": {"metric_id": "net_revenue"},
                    }
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "prior_01",
                        "status": "success",
                        "content": [{"json": {"rows": [{"value": "110.25"}]}}],
                    }
                }
            ],
        },
    ]
    converted = client.converse(**query)
    raw_body = transport.requests[0].body
    assert isinstance(raw_body, (str, bytes, bytearray))
    payload = json.loads(raw_body)
    assert payload["parallel_tool_calls"] is False
    assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["function"]["name"] == "query_metric"
    assert payload["messages"][2]["tool_calls"][0]["id"] == "prior_01"
    assert payload["messages"][3] == {
        "role": "tool",
        "tool_call_id": "prior_01",
        "content": '{"rows":[{"value":"110.25"}]}',
    }
    message = converted["output"]
    assert isinstance(message, dict)
    assert message["message"]["content"] == [
        {
            "toolUse": {
                "toolUseId": "call_01",
                "name": "query_metric",
                "input": {"metric_id": "net_revenue"},
            }
        }
    ]
    assert converted["stopReason"] == "tool_use"


@pytest.mark.parametrize(
    "change",
    [
        {"modelId": "google.gemini-anything"},
        {"endpoint_url": "https://untrusted.example"},
        {"region_name": "us-east-1"},
        {"messages": [{"role": "user", "content": [{"image": {}}]}]},
        {"toolConfig": {**tool_config(), "toolChoice": {"any": {}}}},
        {"inferenceConfig": {"maxTokens": True}},
        {"inferenceConfig": {"maxTokens": 1, "temperature": float("nan")}},
        {"inferenceConfig": {"maxTokens": 1, "temperature": True}},
    ],
)
def test_unsupported_request_fails_before_credentials_or_http(change: dict[str, object]) -> None:
    session, transport = Session(), Transport()
    client = mantle.BedrockMantleClient(session=session, transport=transport)
    with pytest.raises(mantle.MantleError):
        client.converse(**{**request(), **change})
    assert session.calls == 0 and transport.requests == []


@pytest.mark.parametrize("status", [301, 307, 403, 429, 500])
def test_http_failure_is_closed_redacted_and_never_retried(status: int) -> None:
    raw = response(b'{"message":"PRIVATE_PROVIDER_SECRET"}', status=status)
    transport = Transport(raw)
    client = mantle.BedrockMantleClient(session=Session(), transport=transport)
    with pytest.raises(mantle.MantleError) as caught:
        client.converse(**request())
    assert caught.value.diagnostic["http_status"] == status
    assert "PRIVATE_PROVIDER_SECRET" not in str(caught.value)
    assert len(transport.requests) == raw.raw.closed == 1


def test_transport_failure_has_one_attempt_and_no_signed_error_details() -> None:
    transport = Transport(OSError("https://secret?X-Amz-Signature=PRIVATE"))
    client = mantle.BedrockMantleClient(session=Session(), transport=transport)
    with pytest.raises(mantle.MantleError, match="transport_or_credentials_error") as caught:
        client.converse(**request())
    assert "PRIVATE" not in str(caught.value) and len(transport.requests) == 1


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {"prompt_tokens": True},
        {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 12},
    ],
)
def test_invalid_usage_never_becomes_accepted_counts(usage: object) -> None:
    value = {**reply(), "usage": usage}
    raw = response(json.dumps(value).encode())
    client = mantle.BedrockMantleClient(session=Session(), transport=Transport(raw))
    with pytest.raises(mantle.MantleError):
        client.converse(**request())
    assert raw.raw.closed == 1


def event(value: object) -> bytes:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return ("data: " + text + "\r\n\r\n").encode()


def stream_body(*, done: bool = True, usage: bool = True, reason: str = "stop") -> bytes:
    chunks = [
        b": heartbeat\n\n",
        event(
            {
                "model": mantle.MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "Café ",
                            "reasoning_content": "PRIVATE_THOUGHT",
                        },
                        "finish_reason": None,
                    }
                ],
            }
        ),
        event({"choices": [{"index": 0, "delta": {"content": "sales "}, "finish_reason": None}]}),
        event({"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}),
    ]
    if usage:
        chunks.append(
            event(
                {
                    "choices": [],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
                }
            )
        )
    if done:
        chunks.append(event("[DONE]"))
    return b"".join(chunks)


def test_fragmented_utf8_sse_yields_real_deltas_exact_usage_and_private_blocks_stay_private() -> (
    None
):
    raw = response(stream_body(), stream=True)
    transport = Transport(raw)
    client = mantle.BedrockMantleClient(session=Session(), transport=transport)
    result = client.converse_stream(**request())
    stream = result["stream"]
    assert isinstance(stream, Iterator)
    assert raw.raw.closed == 0
    first = next(stream)
    assert first == {"messageStart": {"role": "assistant"}}
    chunks = list(stream)
    text = "".join(
        item["contentBlockDelta"]["delta"]["text"] for item in chunks if "contentBlockDelta" in item
    )
    assert text == "Café sales "
    assert "PRIVATE_THOUGHT" not in json.dumps(chunks)
    assert chunks[-2] == {"messageStop": {"stopReason": "end_turn"}}
    assert chunks[-1] == {
        "metadata": {"usage": {"inputTokens": 8, "outputTokens": 2, "totalTokens": 10}}
    }
    raw_body = transport.requests[0].body
    assert isinstance(raw_body, (str, bytes, bytearray))
    payload = json.loads(raw_body)
    assert payload["stream_options"] == {"include_usage": True}
    assert raw.raw.closed == len(transport.requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        stream_body(done=False),
        stream_body(usage=False),
        b"data: bad-json\n\n",
        event({"error": {"message": "PRIVATE_PROVIDER_SECRET"}}),
        b"data: \xff\n\n",
        event({"choices": [{"delta": {"tool_calls": [{"id": "bad"}]}}]}),
    ],
)
def test_invalid_truncated_or_tool_stream_fails_closed_without_retry(body: bytes) -> None:
    raw = response(body, stream=True)
    transport = Transport(raw)
    client = mantle.BedrockMantleClient(session=Session(), transport=transport)
    output = client.converse_stream(**request())
    with pytest.raises(mantle.MantleError) as caught:
        list(cast_stream(output))
    assert "PRIVATE_PROVIDER_SECRET" not in str(caught.value)
    assert raw.raw.closed == len(transport.requests) == 1


def cast_stream(output: dict[str, object]) -> Iterator[dict[str, Any]]:
    value = output["stream"]
    assert isinstance(value, Iterator)
    return value


@pytest.mark.parametrize("before_iteration", [True, False])
def test_explicit_close_disposes_http_even_before_first_event(before_iteration: bool) -> None:
    raw = response(stream_body(), stream=True)
    client = mantle.BedrockMantleClient(session=Session(), transport=Transport(raw))
    stream = cast_stream(client.converse_stream(**request()))
    if not before_iteration:
        next(stream)
    close = cast(Any, stream).close
    close()
    close()
    assert raw.raw.closed == 1


def test_streaming_tool_config_is_rejected_before_dispatch() -> None:
    session, transport = Session(), Transport()
    client = mantle.BedrockMantleClient(session=session, transport=transport)
    with pytest.raises(mantle.MantleError, match="streaming_tools_not_configured"):
        client.converse_stream(**{**request(), "toolConfig": tool_config()})
    assert session.calls == 0 and transport.requests == []


def test_stream_deadline_stays_bounded_and_cleanup_failure_keeps_original_failure() -> None:
    now = [0.0]
    raw = response(stream_body(), stream=True)
    raw.raw.cleanup_failure = True
    transport = Transport(raw)
    client = mantle.BedrockMantleClient(
        session=Session(), transport=transport, timeout_seconds=1, clock=lambda: now[0]
    )
    stream = cast_stream(client.converse_stream(**request()))
    next(stream)
    now[0] = 2.0
    with pytest.raises(mantle.MantleError, match="deadline_exceeded"):
        next(stream)
    assert len(transport.requests) == raw.raw.closed == 1


def test_response_frame_and_total_size_limits_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mantle, "MAX_LINE_BYTES", 10)
    raw = response(b"data: " + b"x" * 50 + b"\n\n", stream=True)
    client = mantle.BedrockMantleClient(session=Session(), transport=Transport(raw))
    with pytest.raises(mantle.MantleError, match="stream_frame_too_large"):
        list(cast_stream(client.converse_stream(**request())))
    assert raw.raw.closed == 1


def test_owned_http_transport_has_bounded_timeouts_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = response(json.dumps(reply()).encode())
    transport = Transport(raw)
    settings: list[dict[str, object]] = []

    def factory(**kwargs: object) -> Transport:
        settings.append(kwargs)
        return transport

    monkeypatch.setattr(mantle, "URLLib3Session", factory)
    client = mantle.BedrockMantleClient(session=Session())
    client.converse(**request())
    assert settings == [{"timeout": (5, 30)}]
    assert transport.closed == 1 and raw.raw.closed == 1


def test_normalized_mantle_stream_passes_the_shared_canonical_word_gate() -> None:
    from enterprise_analytics_agent.adapters.bedrock_word_stream import consume_presentation

    raw = response(stream_body(), stream=True)
    transport = Transport(raw)
    client = mantle.BedrockMantleClient(session=Session(), transport=transport, clock=lambda: 0.0)
    published: list[str] = []
    result = consume_presentation(
        client, request(), "Café sales ", published.append, deadline=90.0, clock=lambda: 0.0
    )
    assert result.text == "".join(published) == "Café sales "
    assert published == ["Café ", "sales "]
    assert result.usage == {"inputTokens": 8, "outputTokens": 2, "totalTokens": 10}
    assert len(transport.requests) == raw.raw.closed == 1


def test_owned_transport_is_closed_without_replacing_send_interruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = KeyboardInterrupt()
    transport = Transport(original)
    monkeypatch.setattr(mantle, "URLLib3Session", lambda **kwargs: transport)
    client = mantle.BedrockMantleClient(session=Session())
    with pytest.raises(KeyboardInterrupt) as caught:
        client.converse(**request())
    assert caught.value is original
    assert transport.closed == len(transport.requests) == 1
