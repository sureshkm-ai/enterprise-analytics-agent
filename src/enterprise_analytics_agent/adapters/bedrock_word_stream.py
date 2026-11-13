"""Bounded Bedrock presentation streams over already validated analytics answers.

This adapter publishes matching provider characters, never simulated typing or
unverified model calculations. SDK reference:
https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse_stream.html
"""

import hashlib
import json
import math
import re
import time
from collections import deque
from collections.abc import Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from botocore.exceptions import ClientError

from enterprise_analytics_agent.adapters.bedrock_agent import ConverseClient


class StreamProtocolError(RuntimeError):
    """An authored presentation/protocol failure with no provider text attached."""


class ConverseStreamClient(Protocol):
    def converse_stream(self, **kwargs: object) -> dict[str, object]: ...


class _EventStream(Protocol):
    def __iter__(self) -> Iterator[object]: ...

    def close(self) -> None: ...


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise StreamProtocolError("Bedrock returned an invalid response structure.")
    return cast(dict[str, object], value)


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise StreamProtocolError("Bedrock returned invalid stream accounting or indices.")
    return value


def _usage(value: object) -> tuple[int, int, int]:
    usage = _mapping(value)
    incoming = _integer(usage.get("inputTokens"))
    outgoing = _integer(usage.get("outputTokens"))
    total = _integer(usage.get("totalTokens"))
    if total != incoming + outgoing:
        raise StreamProtocolError("Bedrock returned inconsistent token accounting.")
    return incoming, outgoing, total


def _text_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise StreamProtocolError("Bedrock returned invalid Unicode text.") from exc


def _size(value: object) -> int:
    """Conservatively bound decoded events, including private binary reasoning."""
    if isinstance(value, str):
        return _text_size(value) + 2
    if isinstance(value, bytes):
        return len(value) + 2
    if value is None or isinstance(value, bool):
        return 5
    if isinstance(value, int):
        return len(str(value))
    if isinstance(value, float) and math.isfinite(value):
        return len(str(value))
    if isinstance(value, list):
        return 2 + sum(_size(item) + 1 for item in value)
    if isinstance(value, dict):
        mapping = _mapping(value)
        return 2 + sum(_size(key) + _size(item) + 2 for key, item in mapping.items())
    raise StreamProtocolError("Bedrock returned an unsupported event value.")


class CanonicalWordGate:
    """Release complete words that actually arrived and match canonical text.

    The final word, including trailing whitespace, stays private until finish().
    Call finish only after the complete provider stream and usage have validated.
    """

    def __init__(
        self, canonical: str, on_word: Callable[[str], None], *, max_bytes: int = 262_144
    ) -> None:
        if (
            not isinstance(canonical, str)
            or not canonical.strip()
            or type(max_bytes) is not int
            or max_bytes <= 0
            or not callable(on_word)
            or _text_size(canonical) > max_bytes
        ):
            raise StreamProtocolError("The canonical answer is empty or exceeds the stream limit.")
        self.canonical, self.on_word, self.max_bytes = canonical, on_word, max_bytes
        words = list(re.finditer(r"\S+", canonical))
        last_word = words[-1].start()
        self._boundaries = deque(
            match.end() for match in re.finditer(r"\s+", canonical) if match.end() <= last_word
        )
        self._pending: deque[str] = deque()
        self._published: list[str] = []
        self._position = self._emitted = self._bytes = 0
        self._finished = self._failed = False

    def _check_open(self) -> None:
        if self._finished or self._failed:
            raise StreamProtocolError("The presentation word gate is already closed.")

    def _emit(self, length: int) -> None:
        pieces = []
        remaining = length
        while remaining:
            part = self._pending.popleft()
            taken = min(len(part), remaining)
            pieces.append(part[:taken])
            if taken < len(part):
                self._pending.appendleft(part[taken:])
            remaining -= taken
        text = "".join(pieces)
        try:
            self.on_word(text)
        except BaseException:
            self._failed = True
            raise
        self._published.append(text)
        self._emitted += length

    def feed(self, delta: str) -> None:
        self._check_open()
        if not isinstance(delta, str):
            self._failed = True
            raise StreamProtocolError("Bedrock returned a non-text presentation delta.")
        try:
            self._bytes += _text_size(delta)
        except StreamProtocolError:
            self._failed = True
            raise
        end = self._position + len(delta)
        if self._bytes > self.max_bytes or delta != self.canonical[self._position : end]:
            self._failed = True
            raise StreamProtocolError("The model presentation differs from the validated answer.")
        self._position = end
        if delta:
            self._pending.append(delta)
        while self._boundaries and self._boundaries[0] <= self._position:
            self._emit(self._boundaries.popleft() - self._emitted)

    def finish(self) -> str:
        self._check_open()
        if self._position != len(self.canonical):
            self._failed = True
            raise StreamProtocolError("The model presentation ended before the validated answer.")
        if self._position > self._emitted:
            self._emit(self._position - self._emitted)
        self._finished = True
        return "".join(self._published)


@dataclass(frozen=True)
class StreamedPresentation:
    text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    provider_latency_ms: int | None = None

    @property
    def usage(self) -> dict[str, int]:
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens,
        }


def _reasoning_delta(value: object) -> None:
    content = _mapping(value)
    if len(content) != 1:
        raise StreamProtocolError("Bedrock returned an invalid private reasoning block.")
    name, data = next(iter(content.items()))
    if name in {"text", "signature"} and isinstance(data, str):
        return
    if name == "redactedContent" and isinstance(data, bytes):
        return
    raise StreamProtocolError("Bedrock returned an unsupported private reasoning block.")


def _presentation_payload(payload: dict[str, object]) -> dict[str, object]:
    value = deepcopy(_mapping(payload))
    if "toolConfig" in value:
        raise StreamProtocolError("Presentation calls must not enable tools.")
    if not isinstance(value.get("modelId"), str) or not value["modelId"]:
        raise StreamProtocolError("A configured presentation model is required.")
    messages = value.get("messages")
    if not isinstance(messages, list) or not messages:
        raise StreamProtocolError("A text presentation request is required.")
    for raw in messages:
        message = _mapping(raw)
        content = message.get("content")
        if message.get("role") not in {"user", "assistant"} or not isinstance(content, list):
            raise StreamProtocolError("Presentation messages must contain only text.")
        for block in content:
            item = _mapping(block)
            if set(item) != {"text"} or not isinstance(item["text"], str):
                raise StreamProtocolError("Presentation messages must contain only text.")
    return value


def consume_presentation(
    client: ConverseStreamClient,
    payload: dict[str, object],
    canonical: str,
    on_word: Callable[[str], None],
    *,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
    max_bytes: int = 262_144,
    max_events: int = 20_000,
) -> StreamedPresentation:
    """Dispatch once; validate and close the complete SDK stream without retries."""
    gate = CanonicalWordGate(canonical, on_word, max_bytes=max_bytes)
    request = _presentation_payload(payload)
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, (float, int))
        or not math.isfinite(deadline)
        or type(max_events) is not int
        or max_events <= 0
    ):
        raise StreamProtocolError("A bounded presentation deadline and event limit are required.")
    started = clock()
    if started >= deadline:
        raise StreamProtocolError("The presentation deadline expired before dispatch.")
    response = _mapping(client.converse_stream(**request))
    stream = cast(_EventStream, response.get("stream"))
    close = getattr(stream, "close", None)
    if not callable(close):
        raise StreamProtocolError("Bedrock returned no closable presentation stream.")
    primary_error = False
    try:
        state = _PresentationState(gate, request, response.get("ResponseMetadata", {}))
        count = size = 0
        try:
            iterator = iter(stream)
        except TypeError as exc:
            raise StreamProtocolError("Bedrock returned an invalid presentation stream.") from exc
        for raw in iterator:
            count += 1
            if clock() >= deadline:
                raise StreamProtocolError("The presentation stream exceeded its deadline.")
            size += _size(raw)
            if count > max_events or size > max_bytes:
                raise StreamProtocolError("The presentation stream exceeded its bounded size.")
            state.accept(raw)
        if clock() >= deadline:
            raise StreamProtocolError("The presentation stream exceeded its deadline.")
        state.complete()
        text = gate.finish()  # Final word is released only after terminal/usage validation.
        assert state.usage is not None
        incoming, outgoing, total = state.usage
        return StreamedPresentation(
            text,
            incoming,
            outgoing,
            total,
            max(0, int((clock() - started) * 1000)),
            state.provider_latency_ms,
        )
    except BaseException:
        primary_error = True
        raise
    finally:
        try:
            close()
        except BaseException:
            if not primary_error:
                raise


class _PresentationState:
    def __init__(
        self, gate: CanonicalWordGate, request: dict[str, object], metadata: object = None
    ) -> None:
        self.gate = gate
        self.started = self.stopped = self.metadata = False
        self.active: int | None = None
        self.kind: str | None = None
        self.closed: set[int] = set()
        self.usage: tuple[int, int, int] | None = None
        self.provider_latency_ms: int | None = None
        self.max_output = _mapping(request.get("inferenceConfig", {})).get("maxTokens")
        self.response_metadata = metadata if isinstance(metadata, dict) else {}

    def _block(self, event: dict[str, object], *, explicit: bool = False) -> None:
        if not self.started or self.stopped:
            raise StreamProtocolError("Bedrock returned content outside its message.")
        index = _integer(event.get("contentBlockIndex"))
        if self.active is None:
            if index != len(self.closed):
                raise StreamProtocolError("Bedrock returned out-of-order content blocks.")
            self.active = index
            self.kind = None
        elif explicit or self.active != index:
            raise StreamProtocolError("Bedrock returned overlapping content blocks.")

    def accept(self, raw: object) -> None:
        event = _mapping(raw)
        if len(event) != 1:
            raise StreamProtocolError("Bedrock returned an invalid tagged stream event.")
        name, value = next(iter(event.items()))
        data = _mapping(value)
        if name in {
            "internalServerException",
            "modelStreamErrorException",
            "serviceUnavailableException",
            "throttlingException",
            "validationException",
        }:
            # Preserve the SDK evidence privately; only an authored message is
            # raised at the public boundary. The diagnostic sink redacts it.
            cause = ClientError(
                cast(
                    Any,
                    {
                        "Error": {
                            "Code": name,
                            "Message": data.get("message", data.get("originalMessage", "")),
                        },
                        "ResponseMetadata": self.response_metadata,
                    },
                ),
                "ConverseStream",
            )
            raise StreamProtocolError("Bedrock reported a presentation stream failure.") from cause
        if name == "messageStart":
            if self.started or self.stopped or data.get("role") != "assistant":
                raise StreamProtocolError("Bedrock returned an invalid message start.")
            self.started = True
        elif name == "contentBlockStart":
            self._block(data, explicit=True)
            if _mapping(data.get("start")):
                raise StreamProtocolError("Presentation streams may not request tools or media.")
        elif name == "contentBlockDelta":
            self._block(data)
            delta = _mapping(data.get("delta"))
            if len(delta) != 1:
                raise StreamProtocolError("Bedrock returned an invalid content delta.")
            kind, text = next(iter(delta.items()))
            if kind not in {"text", "reasoningContent"} or self.kind not in {None, kind}:
                raise StreamProtocolError("Bedrock returned unsupported presentation content.")
            self.kind = kind
            if kind == "reasoningContent":
                _reasoning_delta(text)  # Private reasoning never enters the public word gate.
            elif isinstance(text, str):
                self.gate.feed(text)
            else:
                raise StreamProtocolError("Bedrock returned a non-text presentation delta.")
        elif name == "contentBlockStop":
            index = _integer(data.get("contentBlockIndex"))
            if self.active != index or not self.started or self.stopped:
                raise StreamProtocolError("Bedrock returned an unmatched content-block stop.")
            self.closed.add(index)
            self.active = self.kind = None
        elif name == "messageStop":
            if not self.started or self.stopped or self.active is not None or not self.closed:
                raise StreamProtocolError("Bedrock stopped a message with unfinished content.")
            if data.get("stopReason") != "end_turn":
                raise StreamProtocolError("The presentation did not end normally.")
            self.stopped = True
        elif name == "metadata":
            if not self.stopped or self.metadata:
                raise StreamProtocolError("Bedrock returned out-of-order usage metadata.")
            self.usage = _usage(data.get("usage"))
            if self.max_output is not None and self.usage[1] > _integer(self.max_output):
                raise StreamProtocolError("The presentation exceeded its output-token limit.")
            metrics = _mapping(data.get("metrics", {}))
            if "latencyMs" in metrics:
                self.provider_latency_ms = _integer(metrics["latencyMs"])
            self.metadata = True
        else:
            raise StreamProtocolError("Bedrock returned an unsupported or failed stream event.")

    def complete(self) -> None:
        if not self.started or not self.stopped or not self.metadata or self.active is not None:
            raise StreamProtocolError("Bedrock returned an incomplete presentation stream.")


@dataclass(frozen=True)
class _AssistantReplay:
    prefix: str
    filtered: dict[str, object]
    full: dict[str, object] = field(repr=False)


def _fingerprint(value: object) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (ValueError, TypeError) as exc:
        raise StreamProtocolError("The planner conversation is not valid JSON.") from exc
    return hashlib.sha256(encoded.encode()).hexdigest()


def _full_reasoning(value: object) -> None:
    content = _mapping(value)
    if len(content) != 1:
        raise StreamProtocolError("Bedrock returned invalid private reasoning content.")
    if "redactedContent" in content and isinstance(content["redactedContent"], bytes):
        return
    if "reasoningText" in content:
        text = _mapping(content["reasoningText"])
        if (
            set(text) <= {"text", "signature"}
            and isinstance(text.get("text"), str)
            and ("signature" not in text or isinstance(text["signature"], str))
        ):
            return
    raise StreamProtocolError("Bedrock returned unsupported private reasoning content.")


class ProfiledConverseClient:
    """Per-request planner client; retain signed reasoning only for exact SDK replay."""

    def __init__(self, client: ConverseClient, *, allow_temperature: bool = True) -> None:
        self.client, self.allow_temperature = client, allow_temperature
        self._replays: dict[int, _AssistantReplay] = {}
        self._context: str | None = None

    def converse(self, **kwargs: object) -> dict[str, object]:
        request = deepcopy(kwargs)
        original = request.get("messages")
        if not isinstance(original, list) or not original:
            raise StreamProtocolError("A planner conversation is required.")
        messages = deepcopy([_mapping(item) for item in original])
        context = _fingerprint(
            {
                key: value
                for key, value in request.items()
                if key not in {"messages", "inferenceConfig"}
            }
        )
        if len(messages) == 1:
            self._replays.clear()
            self._context = context
        elif self._context is not None and self._context != context:
            raise StreamProtocolError("The planner context changed during private replay.")
        for index, replay in self._replays.items():
            if index >= len(messages):
                raise StreamProtocolError("The planner conversation was truncated during replay.")
            if (
                replay.prefix != _fingerprint(original[:index])
                or replay.filtered != messages[index]
            ):
                raise StreamProtocolError("The planner conversation changed during private replay.")
            messages[index] = deepcopy(replay.full)
        request["messages"] = messages
        if not self.allow_temperature and "inferenceConfig" in request:
            inference = deepcopy(_mapping(request["inferenceConfig"]))
            inference.pop("temperature", None)
            request["inferenceConfig"] = inference
        raw = _mapping(self.client.converse(**request))
        _usage(raw.get("usage"))
        message = _mapping(_mapping(raw.get("output")).get("message"))
        content = message.get("content")
        if message.get("role") != "assistant" or not isinstance(content, list):
            raise StreamProtocolError("Bedrock returned an invalid planner message.")
        filtered = []
        for value in content:
            block = _mapping(value)
            if set(block) == {"reasoningContent"}:
                _full_reasoning(block["reasoningContent"])
            elif set(block) == {"text"} and isinstance(block["text"], str):
                filtered.append(deepcopy(block))
            elif set(block) == {"toolUse"} and isinstance(block["toolUse"], dict):
                filtered.append(deepcopy(block))
            else:
                raise StreamProtocolError("Bedrock returned unsupported planner content.")
        public_message: dict[str, object] = {"role": "assistant", "content": filtered}
        if len(self._replays) >= 20:
            raise StreamProtocolError("The planner private-replay limit was reached.")
        self._replays[len(original)] = _AssistantReplay(
            _fingerprint(original), deepcopy(public_message), deepcopy(message)
        )
        result: dict[str, object] = {
            "output": {"message": public_message},
            "stopReason": raw.get("stopReason"),
            "usage": deepcopy(raw["usage"]),
        }
        if "metrics" in raw:
            result["metrics"] = deepcopy(raw["metrics"])
        return result
