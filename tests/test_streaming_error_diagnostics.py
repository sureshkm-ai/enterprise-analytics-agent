"""Private AWS denial evidence without public payload, credential or retry leakage."""

import json
from datetime import date
from decimal import Decimal
from typing import Any, cast

import boto3
import pytest
from botocore.exceptions import ClientError
from test_model_streams_review import settings
from test_streaming_hosting import Connection, handle, request, sse

from enterprise_analytics_agent.adapter import SemanticAdapter
from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
)
from enterprise_analytics_agent.adapters.s3_publication import (
    PublicationError,
    S3Client,
    get_ready_manifest,
)
from enterprise_analytics_agent.adapters.streaming_agent import (
    CallTrace,
    StreamingAnalyticsAgent,
    StreamingLimits,
    _CountedPlanner,
)
from enterprise_analytics_agent.adapters.streaming_diagnostics import report_aws_failure
from enterprise_analytics_agent.agent.contracts import AgentRequest
from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.contracts_v2 import QueryMetricRequestV2, QueryMetricResponseV2
from enterprise_analytics_agent.hosting.streaming_server import StreamingApplication

QUESTION = "Show net_revenue for yesterday."
MODEL = "us.anthropic.claude-sonnet-5-5"
AWS_REQUEST_ID = "11112222-3333-4444-5555-666677778888"
PRINCIPAL = (
    "arn:aws:sts::453711491609:assumed-role/"
    "enterprise-analytics-stream-claude-sonnet-5-5/BedrockAgentCore-authored"
)
RESOURCE = "arn:aws:bedrock:us-west-2:453711491609:inference-profile/us.anthropic.claude-sonnet-5-5"
DENIAL = (
    f"User: {PRINCIPAL} is not authorized to perform: bedrock:InvokeModel on resource: "
    f"{RESOURCE} because no identity-based policy allows the bedrock:InvokeModel action"
)
ANSWER = "net_revenue [2025-03-31, 2025-04-01); definition 1.0.0:\ntotal: 110.25 USD"


@pytest.fixture(autouse=True)
def forbid_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("AWS denial diagnostics use injected clients only")

    monkeypatch.setattr(boto3, "Session", forbidden)


class AccessDeniedException(ClientError):
    """Match the SDK's generated ClientError subclass without constructing a client."""


def denied(operation: str = "Converse", message: str = DENIAL) -> ClientError:
    # Deliberately include untrusted extra SDK-response fields to prove they are
    # never copied into the private allowlist or the public response.
    response: Any = {
        "Error": {
            "Code": "AccessDeniedException",
            "Message": message,
            "credentials": {"SecretAccessKey": "PRIVATE_ERROR_EXTRA"},
            "prompt": QUESTION,
        },
        "ResponseMetadata": {
            "RequestId": AWS_REQUEST_ID,
            "HTTPStatusCode": 403,
            "HTTPHeaders": {
                "authorization": "Bearer PRIVATE_HTTP_AUTH",
                "x-amz-security-token": "PRIVATE_HTTP_TOKEN",
                "x-private-header": "PRIVATE_HEADER",
            },
        },
        "requestBody": {"messages": QUESTION, "history": "PRIVATE_HISTORY"},
    }
    return AccessDeniedException(response, operation)


class Planner:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls = 0

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        assert kwargs["modelId"] == MODEL
        if self.error is not None:
            raise self.error
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": "Use tools."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 100, "outputTokens": 10, "totalTokens": 110},
        }


class Presenter:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls = 0

    def converse_stream(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        assert kwargs["modelId"] == MODEL
        if self.error is not None:
            raise self.error
        return {
            "stream": iter(
                [
                    {"messageStart": {"role": "assistant"}},
                    {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": ANSWER}}},
                    {"contentBlockStop": {"contentBlockIndex": 0}},
                    {"messageStop": {"stopReason": "end_turn"}},
                    {
                        "metadata": {
                            "usage": {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150}
                        }
                    },
                ]
            )
        }


class Adapter:
    def query_metric(
        self, request: QueryMetricRequestV2, *, context: AuthorizationContext
    ) -> QueryMetricResponseV2:
        assert context == settings().authorization_context()
        assert request.metric_id == "net_revenue"
        assert request.time_range.start == date(2025, 3, 31)
        assert request.time_range.end == date(2025, 4, 1)
        return QueryMetricResponseV2.model_validate(
            {
                "metric_id": "net_revenue",
                "definition_version": "1.0.0",
                "time_range": {"start": "2025-03-31", "end": "2025-04-01"},
                "group_by": [],
                "unit": "currency",
                "currency": "USD",
                "rows": [{"dimensions": {}, "value": Decimal("110.25")}],
            }
        )


def runner(
    phase: str, error: BaseException | None
) -> tuple[StreamingAnalyticsAgent, Planner, Presenter]:
    planner = Planner(error if phase == "planning" else None)
    presenter = Presenter(error if phase == "presentation" else None)
    agent = BedrockAnalyticsAgent(
        BedrockAgentConfig(model_id=MODEL, reference_date=date(2025, 4, 1)),
        client=planner,
        adapter=cast(SemanticAdapter, Adapter()),
        dataset_version="retail-v1",
    )
    return StreamingAnalyticsAgent(agent, presentation_client=presenter), planner, presenter


def test_allowlisted_aws_fields_keep_the_full_denial_without_headers_or_payloads() -> None:
    private: list[dict[str, object]] = []
    # Long ordinary text must survive intact; a shortened suffix could hide the real reason.
    message = DENIAL + "; " + "additional policy context " * 200 + "END_OF_DENIAL"
    report_aws_failure(
        denied(message=message), operation="Converse", number=1, diagnostic=private.append
    )
    assert private == [
        {
            "operation": "Converse",
            "number": 1,
            "aws_error": {
                "Code": "AccessDeniedException",
                "Message": message,
                "RequestId": AWS_REQUEST_ID,
                "HTTPStatusCode": 403,
            },
        }
    ]
    assert "PRIVATE_" not in json.dumps(private)
    assert QUESTION not in json.dumps(private)


@pytest.mark.parametrize(
    ("suffix", "secrets"),
    [
        ("; AWS_SECRET_ACCESS_KEY=PRIVATE_SECRET; done", ("PRIVATE_SECRET",)),
        ("; Authorization: Bearer PRIVATE_BEARER; done", ("PRIVATE_BEARER",)),
        (
            '; credentials={"AccessKeyId":"PRIVATE_KEY","SecretAccessKey":"PRIVATE_SECRET"}',
            ("PRIVATE_KEY", "PRIVATE_SECRET"),
        ),
        ('; payload={"messages":[{"text":"PRIVATE_PROMPT"}]}', ("PRIVATE_PROMPT",)),
        ('; history=[{"text":"PRIVATE_HISTORY"}]', ("PRIVATE_HISTORY",)),
        ('; question="PRIVATE_QUESTION"', ("PRIVATE_QUESTION",)),
        ('; system_prompt="PRIVATE_SYSTEM_PROMPT"', ("PRIVATE_SYSTEM_PROMPT",)),
        ('; headers={"x-private-header":"PRIVATE_HEADER"}', ("PRIVATE_HEADER",)),
        ("; X-Amz-Signature=PRIVATE_SIGNATURE&X-Amz-Date=20261112", ("PRIVATE_SIGNATURE",)),
        ("; credential ASIA1234567890ABCDEF was rejected", ("ASIA1234567890ABCDEF",)),
        ("; bearer PRIVATE_TOKEN", ("PRIVATE_TOKEN",)),
        ("; eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature", ("eyJhbGciOiJIUzI1NiJ9",)),
        ('; SecretAccessKey="PRIVATE_UNTERMINATED', ("PRIVATE_UNTERMINATED",)),
    ],
)
def test_secret_like_message_content_is_redacted_without_discarding_denial_context(
    suffix: str, secrets: tuple[str, ...]
) -> None:
    private: list[dict[str, object]] = []
    report_aws_failure(
        denied(message=DENIAL + suffix), operation="Converse", number=1, diagnostic=private.append
    )
    encoded = json.dumps(private)
    assert DENIAL in cast(dict[str, str], private[0]["aws_error"])["Message"]
    assert all(secret not in encoded for secret in secrets)


@pytest.mark.parametrize("phase", ["planning", "presentation"])
def test_aws_diagnostic_sink_is_separate_from_public_response_and_call_accounting(
    phase: str,
) -> None:
    operation = "Converse" if phase == "planning" else "ConverseStream"
    streaming, planner, presenter = runner(phase, denied(operation))
    private: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    words: list[str] = []
    outcome = streaming.run(
        AgentRequest(question=QUESTION),
        context=settings().authorization_context(),
        on_word=words.append,
        record=records.append,
        diagnostic=private.append,
    )
    assert len(private) == 1 and private[0]["operation"] == operation
    assert private[0]["number"] == (1 if phase == "planning" else 2)
    assert private[0]["aws_error"] == {
        "Code": "AccessDeniedException",
        "Message": DENIAL,
        "RequestId": AWS_REQUEST_ID,
        "HTTPStatusCode": 403,
    }
    assert planner.calls == 1 and presenter.calls == int(phase == "presentation")
    assert not words
    assert records[-1]["event"] == "failed"
    assert records[-1]["error_type"] == "AccessDeniedException"
    public = outcome.response.model_dump_json() + json.dumps(outcome.calls) + json.dumps(records)
    assert all(
        value not in public for value in (DENIAL, AWS_REQUEST_ID, PRINCIPAL, RESOURCE, "PRIVATE_")
    )
    if phase == "planning":
        assert outcome.response.error_code == "model_error" and not outcome.response.results
    else:
        assert outcome.presentation == "fallback"
        assert outcome.reason == "presentation_stream_rejected"
        assert outcome.response.answer == ANSWER
        assert outcome.response.results[0].rows[0].value == Decimal("110.25")


def test_diagnostic_sink_failure_preserves_the_original_exception_and_one_attempt() -> None:
    original = denied()
    planner = Planner(original)
    events: list[dict[str, object]] = []
    trace = CallTrace(StreamingLimits(), deadline=float("inf"), record=events.append)

    def broken(_: dict[str, object]) -> None:
        raise KeyboardInterrupt("PRIVATE_LOGGER_FAILURE")

    counted = _CountedPlanner(planner, trace, "Converse", broken)
    with pytest.raises(ClientError) as caught:
        counted.converse(modelId=MODEL)
    assert caught.value is original
    assert planner.calls == 1 and trace.failed
    assert [event["event"] for event in events] == ["reserved", "failed"]
    assert trace.calls[0]["status"] == "failed"
    assert "PRIVATE_LOGGER_FAILURE" not in json.dumps(events)


@pytest.mark.parametrize("phase", ["planning", "presentation"])
def test_runtime_logs_private_error_with_correlation_but_sse_stays_sanitized(phase: str) -> None:
    operation = "Converse" if phase == "planning" else "ConverseStream"
    streaming, planner, presenter = runner(phase, denied(operation))
    logs: list[str] = []
    events: list[dict[str, object]] = []
    configured = settings().model_copy(update={"model_id": MODEL})
    app = StreamingApplication(configured, factory=lambda _: streaming, log=logs.append)
    app.execute({"question": QUESTION}, events.append)
    decoded = [json.loads(line) for line in logs]
    private = [row for row in decoded if row["event"] == "streaming_aws_error"]
    public_calls = [row for row in decoded if row["event"] == "streaming_model_call"]
    assert len(private) == 1
    assert private[0]["aws_error"]["Message"] == DENIAL
    assert private[0]["aws_error"]["RequestId"] == AWS_REQUEST_ID
    assert private[0]["model_id"] == MODEL and private[0]["operation"] == operation
    assert {row["request_id"] for row in public_calls} == {private[0]["request_id"]}
    assert planner.calls == 1 and presenter.calls == int(phase == "presentation")
    encoded = json.dumps(events)
    assert all(
        value not in encoded for value in (DENIAL, AWS_REQUEST_ID, PRINCIPAL, RESOURCE, "PRIVATE_")
    )
    assert all("aws_error" not in row["call"] for row in public_calls)
    assert "PRIVATE_" not in "".join(logs)
    assert QUESTION not in "".join(logs)


@pytest.mark.parametrize("phase", ["planning", "presentation"])
def test_runtime_diagnostic_logger_failure_does_not_replace_the_model_failure(phase: str) -> None:
    streaming, planner, presenter = runner(phase, denied())
    logs: list[str] = []

    def log(value: str) -> None:
        if json.loads(value)["event"] == "streaming_aws_error":
            raise RuntimeError("PRIVATE_LOGGER_FAILURE")
        logs.append(value)

    configured = settings().model_copy(update={"model_id": MODEL})
    app = StreamingApplication(configured, factory=lambda _: streaming, log=log)
    events: list[dict[str, object]] = []
    app.execute({"question": QUESTION}, events.append)
    final = events[-1]
    response = cast(dict[str, object], final["response"])
    assert response["error_code"] == ("model_error" if phase == "planning" else None)
    assert final["presentation_status"] == ("not_needed" if phase == "planning" else "fallback")
    assert planner.calls == 1 and presenter.calls == int(phase == "presentation")
    assert "PRIVATE_LOGGER_FAILURE" not in json.dumps(events) + "".join(logs)


@pytest.mark.parametrize("phase", ["planning", "presentation"])
def test_generic_exception_text_is_never_logged_as_an_aws_diagnostic(phase: str) -> None:
    streaming, planner, presenter = runner(phase, RuntimeError("PRIVATE_GENERIC_EXCEPTION"))
    private: list[dict[str, object]] = []
    outcome = streaming.run(
        AgentRequest(question=QUESTION),
        context=settings().authorization_context(),
        on_word=lambda _: pytest.fail("No failed stream may publish words"),
        diagnostic=private.append,
    )
    assert not private
    assert planner.calls == 1 and presenter.calls == int(phase == "presentation")
    assert "PRIVATE_GENERIC_EXCEPTION" not in outcome.response.model_dump_json() + json.dumps(
        outcome.calls
    )


@pytest.mark.parametrize("logger_failure", [False, True])
@pytest.mark.parametrize("wrapped", [False, True])
def test_factory_sdk_denial_is_private_with_no_model_reservation_or_retry(
    logger_failure: bool,
    wrapped: bool,
) -> None:
    message = (
        f"User: {PRINCIPAL} is not authorized to perform: s3:GetObject on resource: "
        "arn:aws:s3:::authored-source/snapshots/retail-v1/manifest.json "
        "because no identity-based policy allows the s3:GetObject action"
    )
    sdk_response: Any = denied("GetObject", message).response
    sdk_response["Error"]["Code"] = "AccessDenied"
    original = ClientError(sdk_response, "GetObject")
    factory_calls = 0
    manifest_calls = 0
    logs: list[str] = []

    class DeniedSource:
        def get_object(self, **kwargs: object) -> dict[str, object]:
            nonlocal manifest_calls
            manifest_calls += 1
            raise original

    def factory(_: object) -> StreamingAnalyticsAgent:
        nonlocal factory_calls
        factory_calls += 1
        if wrapped:
            # Exercise the actual PublicationError-from-ClientError boundary,
            # rather than manufacturing the wrapper the runtime must traverse.
            get_ready_manifest(
                s3=cast(S3Client, DeniedSource()),
                bucket="authored-source",
                dataset_version="retail-v1",
                expected_account_id="453711491609",
            )
            raise AssertionError("Denied manifest setup must not construct a model runner")
        raise original

    def log(value: str) -> None:
        if logger_failure and json.loads(value)["event"] == "streaming_aws_error":
            raise RuntimeError("PRIVATE_SETUP_LOGGER_FAILURE")
        logs.append(value)

    configured = settings().model_copy(update={"model_id": MODEL})
    app = StreamingApplication(configured, factory=factory, log=log)
    connection = Connection(request({"question": QUESTION}))
    handle(app, connection)
    emitted = sse(connection)
    assert factory_calls == 1
    assert manifest_calls == int(wrapped)
    assert len(emitted) == 1 and emitted[0]["type"] == "result"
    assert emitted[0]["response"]["error_code"] == "streaming_runtime_unavailable"
    assert emitted[0]["response"]["diagnostics"]["model_calls"] == 0
    assert emitted[0]["model_calls"] == []
    decoded = [json.loads(value) for value in logs]
    assert decoded[-1]["event"] == "streaming_runtime_error"
    assert decoded[-1]["error_type"] == ("PublicationError" if wrapped else "ClientError")
    assert not any(value["event"] == "streaming_model_call" for value in decoded)
    private = [value for value in decoded if value["event"] == "streaming_aws_error"]
    if logger_failure:
        assert not private
    else:
        assert len(private) == 1
        assert private[0]["operation"] == "GetObject" and private[0]["number"] == 0
        assert private[0]["aws_error"] == {
            "Code": "AccessDenied",
            "Message": message,
            "RequestId": AWS_REQUEST_ID,
            "HTTPStatusCode": 403,
        }
        assert private[0]["request_id"] == decoded[-1]["request_id"]
    public = connection.output.decode()
    assert all(
        value not in public
        for value in (message, PRINCIPAL, RESOURCE, AWS_REQUEST_ID, "PRIVATE_", "GetObject")
    )
    assert "PRIVATE_" not in "".join(logs)


def test_setup_uses_trusted_fallback_for_an_invalid_sdk_operation_label() -> None:
    error = denied("PRIVATE_OPERATION with spaces")
    private: list[dict[str, object]] = []
    report_aws_failure(error, operation=None, number=0, diagnostic=private.append)
    assert private[0]["operation"] == "RuntimeSetup" and private[0]["number"] == 0
    assert "PRIVATE_OPERATION" not in json.dumps(private)


def test_generic_factory_exception_text_remains_withheld() -> None:
    logs: list[str] = []

    def factory(_: object) -> StreamingAnalyticsAgent:
        raise RuntimeError("PRIVATE_SETUP_ERROR")

    app = StreamingApplication(settings(), factory=factory, log=logs.append)
    events: list[dict[str, object]] = []
    app.execute({"question": QUESTION}, events.append)
    assert events[-1]["model_calls"] == []
    response = cast(dict[str, object], events[-1]["response"])
    diagnostics = cast(dict[str, object], response["diagnostics"])
    assert diagnostics["model_calls"] == 0
    assert [json.loads(value)["event"] for value in logs] == ["streaming_runtime_error"]
    assert "PRIVATE_SETUP_ERROR" not in json.dumps(events) + "".join(logs)


@pytest.mark.parametrize(("wrappers", "found"), [(7, True), (8, False)])
def test_sdk_cause_traversal_is_bounded_and_never_logs_wrapper_text(
    wrappers: int, found: bool
) -> None:
    error: BaseException = denied("GetObject")
    for _ in range(wrappers):
        wrapper = PublicationError("PRIVATE_WRAPPER_BODY")
        wrapper.__cause__ = error
        error = wrapper
    private: list[dict[str, object]] = []
    report_aws_failure(error, operation=None, number=0, diagnostic=private.append)
    assert bool(private) is found
    if found:
        assert private[0]["operation"] == "GetObject"
        assert cast(dict[str, object], private[0]["aws_error"])["Message"] == DENIAL
    assert "PRIVATE_WRAPPER_BODY" not in json.dumps(private)


def test_sdk_cause_cycles_and_implicit_context_are_withheld() -> None:
    outer = PublicationError("PRIVATE_OUTER_BODY")
    inner = RuntimeError("PRIVATE_INNER_BODY")
    outer.__cause__ = inner
    inner.__cause__ = outer
    private: list[dict[str, object]] = []
    report_aws_failure(outer, operation=None, number=0, diagnostic=private.append)
    assert not private
    context_only = PublicationError("PRIVATE_CONTEXT_BODY")
    context_only.__context__ = denied("GetObject")
    report_aws_failure(context_only, operation=None, number=0, diagnostic=private.append)
    assert not private
