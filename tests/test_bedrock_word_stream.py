"""Authored SDK streams and private planner turns; no AWS clients or credentials."""

from collections.abc import Iterator, Mapping
from copy import deepcopy
from typing import Any

import pytest

from enterprise_analytics_agent.adapters.bedrock_word_stream import (
    CanonicalWordGate,
    ProfiledConverseClient,
    StreamProtocolError,
    consume_presentation,
)

CANONICAL = "North: 110.25 USD"


def events(*chunks: str) -> list[object]:
    return [
        {"messageStart": {"role": "assistant"}},
        *[
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": chunk}}}
            for chunk in chunks
        ],
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
        {
            "metadata": {
                "usage": {"inputTokens": 20, "outputTokens": 8, "totalTokens": 28},
                "metrics": {"latencyMs": 37},
            }
        },
    ]


def payload() -> dict[str, object]:
    return {
        "modelId": "reviewed.test-model",
        "messages": [{"role": "user", "content": [{"text": "Repeat the verified answer."}]}],
        "inferenceConfig": {"maxTokens": 32},
    }


class Stream:
    def __init__(self, values: list[object], *, close_error: Exception | None = None) -> None:
        self.values = values
        self.closed = False
        self.close_error = close_error
        self.consumed = 0

    def __iter__(self) -> Iterator[object]:
        for value in self.values:
            self.consumed += 1
            if isinstance(value, Exception):
                raise value
            yield deepcopy(value)

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class Client:
    def __init__(self, stream: Stream) -> None:
        self.stream = stream
        self.calls: list[dict[str, object]] = []

    def converse_stream(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(deepcopy(kwargs))
        return {"stream": self.stream}


def consume(client: Client, words: list[str], **changes: Any) -> Any:
    return consume_presentation(
        client,
        payload(),
        changes.pop("canonical", CANONICAL),
        words.append,
        deadline=changes.pop("deadline", 10.0),
        clock=changes.pop("clock", lambda: 0.0),
        **changes,
    )


def test_actual_fragmented_words_and_final_word_wait_for_validated_stream() -> None:
    words: list[str] = []
    stream = Stream(events("North: ", "110.", "25 ", "USD"))
    client = Client(stream)

    def capture(word: str) -> None:
        words.append(word)
        if word == "USD":
            assert stream.consumed == len(stream.values)

    result = consume_presentation(
        client, payload(), CANONICAL, capture, deadline=10, clock=lambda: 0
    )
    assert words == ["North: ", "110.25 ", "USD"]
    assert result.text == CANONICAL
    assert result.usage == {"inputTokens": 20, "outputTokens": 8, "totalTokens": 28}
    assert result.provider_latency_ms == 37 and result.latency_ms == 0
    assert stream.closed and len(client.calls) == 1
    assert "toolConfig" not in client.calls[0]


@pytest.mark.parametrize("canonical", ["Café\t— 110.25 USD\n", "  Exact  Unicode\u00a0words  "])
def test_word_gate_preserves_actual_unicode_and_whitespace(canonical: str) -> None:
    words: list[str] = []
    gate = CanonicalWordGate(canonical, words.append)
    for character in canonical:
        gate.feed(character)
    assert "".join(words) != canonical  # The final word remains held through usage validation.
    assert gate.finish() == canonical
    assert "".join(words) == canonical
    with pytest.raises(StreamProtocolError, match="closed"):
        gate.feed("again")


def test_wrong_amount_fragment_never_publishes_partial_numeric_word() -> None:
    words: list[str] = []
    client = Client(Stream(events("North: ", "110.", "99 USD")))
    with pytest.raises(StreamProtocolError, match="differs"):
        consume(client, words)
    assert words == ["North: "]
    assert client.stream.closed and len(client.calls) == 1


@pytest.mark.parametrize(
    "canonical,wrong",
    [
        ("Period [2025-03-31,2025-04-01) revenue 110.25 USD", "Period [2025-03-30,"),
        (CANONICAL, "Here is North: 110.25 USD"),
        (CANONICAL, CANONICAL + " additional claim"),
    ],
)
def test_changed_dates_prefix_or_extra_claims_fail_without_publication(
    canonical: str, wrong: str
) -> None:
    words: list[str] = []
    client = Client(Stream(events(wrong)))
    with pytest.raises(StreamProtocolError, match="differs"):
        consume(client, words, canonical=canonical)
    assert words == [] and client.stream.closed


def test_complete_words_are_not_invented_when_provider_truncates() -> None:
    words: list[str] = []
    client = Client(Stream(events("North: ", "110.")))
    with pytest.raises(StreamProtocolError, match="ended before"):
        consume(client, words)
    assert words == ["North: "] and client.stream.closed


@pytest.mark.parametrize(
    "change",
    [
        {"usage": {"inputTokens": 20, "outputTokens": 8, "totalTokens": 27}},
        {"usage": {"inputTokens": True, "outputTokens": 8, "totalTokens": 9}},
        {"usage": {"inputTokens": 20, "outputTokens": -1, "totalTokens": 19}},
        {"usage": {"inputTokens": 20, "totalTokens": 28}},
        {"usage": {"inputTokens": 20, "outputTokens": 40, "totalTokens": 60}},
        {"metrics": {"latencyMs": "not-an-integer"}},
    ],
)
def test_invalid_accounting_does_not_release_final_word(change: dict[str, object]) -> None:
    values = events(CANONICAL)
    metadata = values[-1]
    assert isinstance(metadata, dict) and isinstance(metadata["metadata"], dict)
    metadata["metadata"].update(change)
    words: list[str] = []
    client = Client(Stream(values))
    with pytest.raises(StreamProtocolError):
        consume(client, words)
    assert "USD" not in words and client.stream.closed and len(client.calls) == 1


@pytest.mark.parametrize("remove", [0, -3, -2, -1])
def test_missing_message_or_block_terminal_metadata_is_rejected(remove: int) -> None:
    values = events(CANONICAL)
    values.pop(remove)
    client = Client(Stream(values))
    words: list[str] = []
    with pytest.raises(StreamProtocolError):
        consume(client, words)
    assert "USD" not in words and client.stream.closed


@pytest.mark.parametrize(
    "bad",
    [
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": CANONICAL}}},
        {"contentBlockDelta": {"contentBlockIndex": True, "delta": {"text": CANONICAL}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": 123}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": "{}"}}}},
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"name": "x"}}}},
        {"messageStart": {"role": "assistant"}},
        {"SDK_UNKNOWN_MEMBER": {"name": "private unknown"}},
        {"internalServerException": {"message": "private amount 999.99"}},
    ],
)
def test_bad_provider_events_do_not_leak_or_retry(bad: object) -> None:
    values = events(CANONICAL)
    values.insert(1, bad)
    client = Client(Stream(values))
    words: list[str] = []
    with pytest.raises(StreamProtocolError) as error:
        consume(client, words)
    assert "private amount" not in str(error.value)
    assert words == [] and client.stream.closed and len(client.calls) == 1


def test_private_reasoning_and_empty_explicit_start_are_not_published() -> None:
    values: list[object] = [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"text": "private 999.99"}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"signature": "private signature"}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"redactedContent": b"private bytes"}},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"contentBlockStart": {"contentBlockIndex": 1, "start": {}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": CANONICAL}}},
        {"contentBlockStop": {"contentBlockIndex": 1}},
        *events(CANONICAL)[-2:],
    ]
    words: list[str] = []
    result = consume(Client(Stream(values)), words)
    assert result.text == CANONICAL and "private" not in "".join(words)


def test_multiple_text_blocks_can_split_one_numeric_word() -> None:
    values: list[object] = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "North: 110."}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": "25 USD"}}},
        {"contentBlockStop": {"contentBlockIndex": 1}},
        *events(CANONICAL)[-2:],
    ]
    words: list[str] = []
    assert consume(Client(Stream(values)), words).text == CANONICAL
    assert words == ["North: ", "110.25 ", "USD"]


@pytest.mark.parametrize("limit", [{"max_bytes": 50}, {"max_events": 2}])
def test_byte_and_event_limits_close_stream(limit: dict[str, int]) -> None:
    client = Client(Stream(events(CANONICAL)))
    with pytest.raises(StreamProtocolError, match="bounded size"):
        consume(client, [], **limit)
    assert client.stream.closed and len(client.calls) == 1


def test_expired_deadline_does_not_dispatch_and_midstream_expiry_closes() -> None:
    client = Client(Stream(events(CANONICAL)))
    with pytest.raises(StreamProtocolError, match="before dispatch"):
        consume(client, [], deadline=0)
    assert client.calls == [] and not client.stream.closed
    ticks = iter([0.0, 1.0, 11.0])
    with pytest.raises(StreamProtocolError, match="deadline"):
        consume(client, [], clock=lambda: next(ticks))
    assert client.stream.closed and len(client.calls) == 1


def test_tools_are_rejected_before_sdk_and_payload_is_not_mutated() -> None:
    client = Client(Stream(events(CANONICAL)))
    request = payload() | {"toolConfig": {}}
    before = deepcopy(request)
    with pytest.raises(StreamProtocolError, match="must not enable tools"):
        consume_presentation(
            client, request, CANONICAL, lambda _: None, deadline=10, clock=lambda: 0
        )
    assert client.calls == [] and request == before


def test_callback_failure_preserves_original_even_when_close_also_fails() -> None:
    stream = Stream(events(CANONICAL), close_error=RuntimeError("private close error"))
    client = Client(stream)
    failure = OSError("observer disconnected")

    def observer(word: str) -> None:
        raise failure

    with pytest.raises(OSError) as error:
        consume_presentation(client, payload(), CANONICAL, observer, deadline=10, clock=lambda: 0)
    assert error.value is failure and stream.closed and len(client.calls) == 1


def test_transport_error_is_not_retried_and_stream_is_closed() -> None:
    failure = TimeoutError("SDK read timeout")
    stream = Stream([{"messageStart": {"role": "assistant"}}, failure])
    client = Client(stream)
    with pytest.raises(TimeoutError) as error:
        consume(client, [])
    assert error.value is failure and stream.closed and len(client.calls) == 1


def planner_response(*content: Mapping[str, object]) -> dict[str, object]:
    return {
        "output": {"message": {"role": "assistant", "content": list(content)}},
        "stopReason": "tool_use" if any("toolUse" in item for item in content) else "end_turn",
        "usage": {"inputTokens": 20, "outputTokens": 10, "totalTokens": 30},
        "metrics": {"latencyMs": 3},
    }


class Planner:
    def __init__(self, *responses: dict[str, object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(deepcopy(kwargs))
        return self.responses.pop(0)


def test_private_signed_reasoning_replayed_only_to_sdk_with_exact_original_prefix() -> None:
    reasoning = {
        "reasoningContent": {"reasoningText": {"text": "private chain", "signature": "signed"}}
    }
    redacted = {"reasoningContent": {"redactedContent": b"private binary"}}
    tool = {"toolUse": {"toolUseId": "call1", "name": "query_metric", "input": {}}}
    raw = Planner(planner_response(reasoning, redacted, tool), planner_response({"text": "Done"}))
    client = ProfiledConverseClient(raw, allow_temperature=False)
    first = payload() | {
        "system": [{"text": "fixed context"}],
        "inferenceConfig": {"maxTokens": 16, "temperature": 0},
    }
    original = deepcopy(first)
    response = client.converse(**first)
    assert first == original
    assert "reasoningContent" not in repr(response) and "private" not in repr(response)
    assert raw.calls[0]["inferenceConfig"] == {"maxTokens": 16}
    output = response["output"]
    assert isinstance(output, dict)
    history = first["messages"]
    assert isinstance(history, list)
    second = deepcopy(first)
    second["messages"] = [
        *history,
        output["message"],
        {
            "role": "user",
            "content": [
                {"toolResult": {"toolUseId": "call1", "content": [{"json": {"value": "110.25"}}]}}
            ],
        },
    ]
    before = deepcopy(second)
    reply = client.converse(**second)
    assert second == before and "private" not in repr(reply)
    sent = raw.calls[1]["messages"]
    assert isinstance(sent, list)
    assert sent[1]["content"] == [reasoning, redacted, tool]
    original_messages = second["messages"]
    assert isinstance(original_messages, list)
    assert original_messages[1]["content"] == [tool]


def test_fresh_first_turn_drops_previous_private_replay_even_for_same_question() -> None:
    reason = {
        "reasoningContent": {
            "reasoningText": {"text": "first request secret", "signature": "signed"}
        }
    }
    raw = Planner(planner_response(reason, {"text": "first"}), planner_response({"text": "second"}))
    client = ProfiledConverseClient(raw)
    client.converse(**payload())
    client.converse(**payload())
    assert len(raw.calls) == 2 and "first request secret" not in repr(raw.calls[1])
    assert len(client._replays) == 1


@pytest.mark.parametrize("change", ["model", "system", "prefix", "assistant"])
def test_modified_conversation_cannot_replay_private_content(change: str) -> None:
    reason = {
        "reasoningContent": {"reasoningText": {"text": "private chain", "signature": "signed"}}
    }
    raw = Planner(planner_response(reason, {"text": "one"}))
    client = ProfiledConverseClient(raw)
    initial = payload() | {"system": [{"text": "fixed"}]}
    response = client.converse(**initial)
    output = response["output"]
    assert isinstance(output, dict)
    history = initial["messages"]
    assert isinstance(history, list)
    second = initial | {
        "messages": [
            *history,
            output["message"],
            {"role": "user", "content": [{"text": "continue"}]},
        ]
    }
    if change == "model":
        second["modelId"] = "other-model"
    elif change == "system":
        second["system"] = [{"text": "other context"}]
    elif change == "prefix":
        second["messages"] = [
            {"role": "user", "content": [{"text": "other question"}]},
            output["message"],
        ]
    else:
        second["messages"] = [*history, {"role": "assistant", "content": [{"text": "changed"}]}]
    with pytest.raises(StreamProtocolError, match="changed"):
        client.converse(**second)
    assert len(raw.calls) == 1


def test_planner_rejects_malformed_usage_and_unknown_content_without_leaking() -> None:
    bad = planner_response({"text": "value"})
    bad["usage"] = {"inputTokens": 10, "outputTokens": 2, "totalTokens": 13}
    raw = Planner(bad, planner_response({"image": {"private": "secret"}}))
    client = ProfiledConverseClient(raw)
    for _ in range(2):
        with pytest.raises(StreamProtocolError) as error:
            client.converse(**payload())
        assert "secret" not in str(error.value)
    assert len(raw.calls) == 2
