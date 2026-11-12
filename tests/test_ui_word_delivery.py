"""Real provider-word callbacks, bounded delivery and disconnected worker ownership."""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from queue import Queue
from typing import Any, Literal, cast
from uuid import uuid4

import boto3
import pytest
from test_streaming_hosting import response
from test_ui_streaming import FakeBackend, FakeBudget

from enterprise_analytics_agent.ui import local, server
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult
from enterprise_analytics_agent.ui.server import AgentModel, Workbench


@pytest.fixture(autouse=True)
def no_aws_or_fixture_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("word-delivery tests must remain offline")

    def directory_only(directory: Path, *, seed: int) -> None:
        directory.mkdir(parents=True)

    monkeypatch.setattr(boto3, "Session", forbidden)
    monkeypatch.setattr(local, "generate_retail_data", directory_only)


class WordBackend:
    """A fake approved transport which emits already-validated provider words."""

    def __init__(self) -> None:
        self.model_id = "us.amazon.nova-lite-v1:0"
        self.ledger = FakeBudget()
        self.calls: list[AskRequest] = []
        self.legacy_calls: list[AskRequest] = []
        self.started, self.finished = threading.Event(), threading.Event()
        self.words_finished, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.before_word: Callable[[int], None] = lambda index: None
        self.word_count = 4
        self.failure: BaseException | None = None
        self.malformed: dict[str, object] | None = None
        self.result_change: Callable[[UiResult], object] = lambda result: result

    def public_state(self, mode: str) -> dict[str, object]:
        return {"enabled": True, "model_id": self.model_id, "dataset": "retail-v1"}

    def ask(self, request: AskRequest) -> UiResult:
        self.legacy_calls.append(request)
        raise AssertionError("streaming transport must never fall back to legacy ask")

    def ask_with_events(
        self, request: AskRequest, emit: Callable[[dict[str, object]], None]
    ) -> UiResult:
        self.calls.append(request)
        self.started.set()
        value = response()
        answer = "Validated " * self.word_count + value.answer
        result = UiResult(
            mode=request.mode,
            response=value.model_copy(update={"answer": answer}),
            elapsed_ms=25,
            presentation_status="streamed",
        )
        try:
            for index, word in enumerate(answer.split(" ")):
                self.before_word(index)
                emit(
                    self.malformed
                    if self.malformed is not None
                    else {
                        "type": "answer_delta",
                        "text": word + (" " if index < len(answer.split(" ")) - 1 else ""),
                        "source": "bedrock",
                        "validated": True,
                    }
                )
            self.words_finished.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("authored backend bookkeeping not released")
            if self.failure is not None:
                raise self.failure
            return cast(UiResult, self.result_change(result))
        finally:
            self.finished.set()


def app_for(tmp_path: Path, backend: WordBackend | FakeBackend) -> Workbench:
    return Workbench(
        tmp_path / "offline-samples",
        model_backends=(
            AgentModel(
                key="nova-lite",
                label="Amazon Nova Lite",
                model_id="us.amazon.nova-lite-v1:0",
                local_agent=backend,
                live=backend,
            ),
        ),
    )


def request(mode: Literal["local_agent", "live"] = "live") -> dict[str, object]:
    return {
        "question": "Show net_revenue for yesterday.",
        "request_id": str(uuid4()),
        "mode": mode,
        "model_key": "nova-lite",
    }


def close(stream: Iterator[dict[str, object]]) -> None:
    cast(Any, stream).close()


@pytest.mark.parametrize("mode", ["local_agent", "live"])
def test_provider_words_arrive_in_order_before_bookkeeping_and_validated_final(
    tmp_path: Path, mode: Literal["local_agent", "live"]
) -> None:
    backend = WordBackend()
    backend.release.clear()
    app = app_for(tmp_path, backend)
    stream = app.ask_stream(request(mode))
    frames: list[dict[str, object]] = []
    try:
        assert next(stream)["type"] == "status"
        assert backend.started.wait(timeout=1)
        while not backend.words_finished.is_set() or len(frames) < backend.word_count + 5:
            frame = next(stream)
            if frame["type"] == "answer_delta":
                frames.append(frame)
            if len(frames) == backend.word_count + 5:
                break
        assert frames and all(frame["validated"] is True for frame in frames)
        assert not backend.finished.is_set() and app.lock.locked()
        with pytest.raises(UiError, match="Another question"):
            app.ask(request(mode))
        backend.release.set()
        remaining = list(stream)
        results = [frame for frame in remaining if frame["type"] == "result"]
        assert len(results) == 1
        result = UiResult.model_validate(results[0]["result"])
        assert "".join(cast(str, frame["text"]) for frame in frames) == result.response.answer
        assert result.response.results == response().results
        assert result.response.metric_versions == {"net_revenue": "1.0.0"}
        assert result.mode == mode and result.presentation_status == "streamed"
        assert backend.calls[0].model_key is None
        assert len(backend.calls) == 1 and backend.legacy_calls == []
        assert not app.lock.locked()
    finally:
        backend.release.set()
        close(stream)


def test_close_before_first_next_unblocks_a_full_queue_without_releasing_worker_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queues: list[Queue[dict[str, object]]] = []
    attempting_overflow = threading.Event()

    def queue_factory(*, maxsize: int) -> Queue[dict[str, object]]:
        assert maxsize == 32
        queue: Queue[dict[str, object]] = Queue(maxsize=maxsize)
        queues.append(queue)
        return queue

    backend = WordBackend()
    backend.word_count = 64
    backend.release.clear()
    backend.before_word = lambda index: attempting_overflow.set() if index == 32 else None
    monkeypatch.setattr(server, "Queue", queue_factory)
    app = app_for(tmp_path, backend)
    stream = app.ask_stream(request())
    try:
        assert attempting_overflow.wait(timeout=1)
        assert queues[0].qsize() == 32
        assert not backend.words_finished.is_set()
        close(stream)  # No next(stream) occurred: generator-finally alone is insufficient.
        assert backend.words_finished.wait(timeout=2)
        assert app.lock.locked() and not backend.finished.is_set()
        with pytest.raises(UiError, match="Another question"):
            app.ask(request())
        assert len(backend.calls) == 1 and backend.legacy_calls == []
        backend.release.set()
        assert backend.finished.wait(timeout=2)
        assert app.lock.acquire(timeout=2)
        app.lock.release()
        assert queues[0].qsize() == 32
        close(stream)  # Idempotent disconnect does not execute or replay anything.
        assert len(backend.calls) == 1
    finally:
        backend.release.set()
        close(stream)


@pytest.mark.parametrize(
    "invalid",
    [
        {"type": "answer_delta", "text": "private 9999.99", "source": "model", "validated": True},
        {
            "type": "answer_delta",
            "text": "private 9999.99",
            "source": "bedrock",
            "validated": False,
        },
        {
            "type": "answer_delta",
            "text": "private 9999.99",
            "source": "bedrock",
            "validated": "true",
        },
        {"type": "answer_delta", "text": 9999, "source": "bedrock", "validated": True},
        {"type": "result", "text": "private 9999.99", "source": "bedrock", "validated": True},
        {"type": "answer_delta", "text": "private 9999.99", "validated": True},
        {"type": "answer_delta", "text": "x" * 262145, "source": "bedrock", "validated": True},
    ],
)
def test_invalid_provider_word_flags_never_cross_browser_boundary_or_trigger_fallback(
    tmp_path: Path, invalid: dict[str, object]
) -> None:
    backend = WordBackend()
    backend.malformed = invalid
    app = app_for(tmp_path, backend)
    frames = list(app.ask_stream(request()))
    assert frames[-1] == {"type": "error", "error": "Invalid validated answer stream event."}
    assert not any(frame["type"] in {"result", "answer_delta"} for frame in frames)
    assert len(backend.calls) == 1 and backend.legacy_calls == []
    assert backend.finished.is_set() and not app.lock.locked()


def test_stream_transport_failure_is_not_retried_via_legacy_ask(tmp_path: Path) -> None:
    backend = WordBackend()
    backend.failure = RuntimeError("private AWS response and credentials")
    app = app_for(tmp_path, backend)
    frames = list(app.ask_stream(request()))
    assert frames[-1]["type"] == "error"
    assert "private AWS" not in str(frames)
    assert not any(frame["type"] == "result" for frame in frames)
    assert len(backend.calls) == 1 and backend.legacy_calls == []
    assert not app.lock.locked()


def test_final_streaming_result_is_deeply_validated_after_words(tmp_path: Path) -> None:
    backend = WordBackend()

    def corrupt(value: UiResult) -> UiResult:
        row = value.response.results[0].rows[0].model_copy(update={"value": "UNVALIDATED"})
        metric = value.response.results[0].model_copy(update={"rows": (row,)})
        return value.model_copy(
            update={"response": value.response.model_copy(update={"results": (metric,)})}
        )

    backend.result_change = corrupt
    app = app_for(tmp_path, backend)
    frames = list(app.ask_stream(request()))
    assert frames[-1]["type"] == "error"
    assert "UNVALIDATED" not in str(frames)
    assert not any(frame["type"] == "result" for frame in frames)
    assert len(backend.calls) == 1 and backend.legacy_calls == []


def test_legacy_backend_streams_progress_and_one_final_result_without_word_claims(
    tmp_path: Path,
) -> None:
    backend = FakeBackend("us.amazon.nova-lite-v1:0")
    app = app_for(tmp_path, backend)
    frames = list(app.ask_stream(request()))
    assert frames[0]["type"] == "status" and frames[-1]["type"] == "result"
    assert not any(frame["type"] == "answer_delta" for frame in frames)
    assert UiResult.model_validate(frames[-1]["result"]).response.results[0].currency == "USD"
    assert len(backend.calls) == 1 and not app.lock.locked()


def test_ordinary_json_api_does_not_opt_in_to_word_streaming(tmp_path: Path) -> None:
    backend = FakeBackend("us.amazon.nova-lite-v1:0")
    callback = MockWordCallback()
    backend.ask_with_events = callback  # type: ignore[attr-defined]
    app = app_for(tmp_path, backend)
    result = app.ask(request())
    assert result.response.results[0].currency == "USD"
    assert len(backend.calls) == 1 and callback.calls == 0


class MockWordCallback:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args: object, **kwargs: object) -> UiResult:
        self.calls += 1
        raise AssertionError("Ordinary JSON must not request a presentation stream")
