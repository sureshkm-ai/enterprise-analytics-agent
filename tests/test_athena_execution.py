"""Credential-free lifecycle/result tests using authored SDK responses."""

from datetime import date, datetime
from decimal import Decimal
from typing import cast

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from enterprise_analytics_agent.adapters.athena_execution import (
    AthenaExecutionError,
    AthenaExecutor,
    AthenaTimeoutError,
    encode_parameter,
)
from enterprise_analytics_agent.errors import DataValidationError


def page(
    columns: tuple[tuple[str, str], ...],
    rows: list[tuple[str | None, ...]],
    *,
    header: bool = True,
    token: str | None = None,
) -> dict[str, object]:
    values = [tuple(name for name, _ in columns), *rows] if header else rows
    result: dict[str, object] = {
        "ResultSet": {
            "ResultSetMetadata": {
                "ColumnInfo": [{"Name": name, "Type": kind} for name, kind in columns]
            },
            "Rows": [
                {"Data": [{} if value is None else {"VarCharValue": value} for value in row]}
                for row in values
            ],
        }
    }
    if token is not None:
        result["NextToken"] = token
    return result


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.submissions: list[dict[str, object] | Exception] = [{"QueryExecutionId": "q1"}]
        self.executions: list[dict[str, object] | Exception] = [
            {
                "QueryExecution": {
                    "Status": {"State": "SUCCEEDED"},
                    "Statistics": {
                        "DataScannedInBytes": 12,
                        "EngineExecutionTimeInMillis": 3,
                        "QueryQueueTimeInMillis": 4,
                        "TotalExecutionTimeInMillis": 8,
                    },
                }
            }
        ]
        self.pages: list[dict[str, object] | Exception] = [page((("x", "bigint"),), [("7",)])]
        self.cancellations: list[dict[str, object] | Exception] = [{}]

    def _response(
        self, name: str, queue: list[dict[str, object] | Exception], kwargs: dict[str, object]
    ) -> dict[str, object]:
        self.calls.append((name, kwargs))
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(response, Exception):
            raise response
        return response

    def start_query_execution(self, **kwargs: object) -> dict[str, object]:
        return self._response("start", self.submissions, kwargs)

    def get_query_execution(self, **kwargs: object) -> dict[str, object]:
        return self._response("poll", self.executions, kwargs)

    def get_query_results(self, **kwargs: object) -> dict[str, object]:
        return self._response("results", self.pages, kwargs)

    def stop_query_execution(self, **kwargs: object) -> dict[str, object]:
        return self._response("cancel", self.cancellations, kwargs)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def executor(client: FakeClient, *, timeout: float = 2.0, max_attempts: int = 3) -> AthenaExecutor:
    timer = FakeTime()
    return AthenaExecutor(
        client,
        database="retail",
        workgroup="development",
        output_location="s3://query-results/results/",
        expected_bucket_owner="123456789012",
        timeout_seconds=timeout,
        poll_seconds=0.25,
        max_attempts=max_attempts,
        clock=timer.clock,
        sleep=timer.sleep,
    )


def run(engine: AthenaExecutor) -> list[tuple[object, ...]]:
    return engine.execute(
        "SELECT x FROM t WHERE tenant_id = ? AND d >= ?",
        ["t1", date(2025, 1, 1)],
        operation="query_metric",
        metric_id="net_revenue",
        metric_version="1.0.0",
        dataset_version="fixture-v1",
    )


def error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "test failure"}}, "TestOperation")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("North", "'North'"),
        ("x' OR 1=1 --", "'x'' OR 1=1 --'"),
        ("back\\slash", "'back\\slash'"),
        ("", "''"),
        (date(2025, 1, 1), "CAST('2025-01-01' AS DATE)"),
        (7, "7"),
        (-3, "-3"),
    ],
)
def test_parameter_literals_are_encoded(value: object, expected: str) -> None:
    assert encode_parameter(value) == expected


@pytest.mark.parametrize(
    "value",
    [1.5, float("nan"), float("inf"), True, None, Decimal("1"), datetime(2025, 1, 1), "x\n"],
)
def test_parameter_literals_reject_ambiguous_values(value: object) -> None:
    with pytest.raises(DataValidationError):
        encode_parameter(value)


def test_success_and_diagnostics_do_not_include_sql_or_identity() -> None:
    client = FakeClient()
    engine = executor(client)
    assert run(engine) == [(7,)]
    submitted = client.calls[0][1]
    assert submitted["ExecutionParameters"] == ["'t1'", "CAST('2025-01-01' AS DATE)"]
    assert submitted["WorkGroup"] == "development"
    assert submitted["QueryExecutionContext"] == {"Database": "retail", "Catalog": "AwsDataCatalog"}
    assert submitted["ResultConfiguration"] == {
        "OutputLocation": "s3://query-results/results/",
        "ExpectedBucketOwner": "123456789012",
        "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"},
    }
    diagnostic = engine.diagnostics[0]
    assert (diagnostic.query_id, diagnostic.scanned_bytes, diagnostic.engine_time_ms) == (
        "q1",
        12,
        3,
    )
    assert (diagnostic.queue_time_ms, diagnostic.total_time_ms) == (4, 8)
    assert (diagnostic.dataset_version, diagnostic.metric_version) == ("fixture-v1", "1.0.0")
    assert "t1" not in repr(diagnostic)
    assert "SELECT" not in repr(diagnostic)


def test_submission_retry_reuses_idempotency_token() -> None:
    client = FakeClient()
    client.submissions = [error("TooManyRequestsException"), {"QueryExecutionId": "q1"}]
    assert run(executor(client)) == [(7,)]
    submissions = [arguments for name, arguments in client.calls if name == "start"]
    assert len(submissions) == 2
    assert submissions[0] == submissions[1]


@pytest.mark.parametrize("operation", ["poll", "results"])
def test_transient_request_retry(operation: str) -> None:
    client = FakeClient()
    queue = client.executions if operation == "poll" else client.pages
    queue.insert(0, EndpointConnectionError(endpoint_url="https://offline.invalid"))
    assert run(executor(client)) == [(7,)]
    assert len([name for name, _ in client.calls if name == operation]) == 2


def test_retryable_execution_is_resubmitted_with_a_new_token() -> None:
    client = FakeClient()
    client.submissions = [{"QueryExecutionId": "q1"}, {"QueryExecutionId": "q2"}]
    client.executions.insert(
        0, {"QueryExecution": {"Status": {"State": "FAILED", "AthenaError": {"Retryable": True}}}}
    )
    engine = executor(client)
    assert run(engine) == [(7,)]
    tokens = [
        arguments["ClientRequestToken"] for name, arguments in client.calls if name == "start"
    ]
    assert len(tokens) == 2 and tokens[0] != tokens[1]
    assert [(row.query_id, row.state) for row in engine.diagnostics] == [
        ("q1", "FAILED"),
        ("q2", "SUCCEEDED"),
    ]


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED"])
def test_terminal_execution_failures_are_not_retried(state: str) -> None:
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": state}}}]
    engine = executor(client)
    with pytest.raises(AthenaExecutionError):
        run(engine)
    assert [name for name, _ in client.calls] == ["start", "poll"]
    assert engine.diagnostics[0].state == state
    assert engine.diagnostics[0].cancellation_attempts == 0
    assert engine.diagnostics[0].cancellation_outcome is None


def test_nontransient_and_exhausted_transient_errors_fail() -> None:
    for code in ("AccessDeniedException", "InvalidRequestException", "InternalServerException"):
        client = FakeClient()
        client.submissions = [error(code)]
        engine = executor(client)
        with pytest.raises(AthenaExecutionError):
            run(engine)
        attempts = 3 if code == "InternalServerException" else 1
        assert len(client.calls) == attempts
        assert engine.diagnostics[0].state == "SUBMISSION_FAILED"


@pytest.mark.parametrize(
    "poll_error",
    [
        error("InternalServerException"),
        EndpointConnectionError(endpoint_url="https://offline.invalid"),
    ],
    ids=["service", "connection"],
)
def test_exhausted_poll_retries_cancel_running_query(poll_error: Exception) -> None:
    client = FakeClient()
    client.executions = [
        {"QueryExecution": {"Status": {"State": "RUNNING"}}},
        poll_error,
    ]
    engine = executor(client)
    with pytest.raises(
        AthenaExecutionError, match="transient API retries were exhausted"
    ) as raised:
        run(engine)
    assert raised.value.__cause__ is poll_error
    assert [arguments for name, arguments in client.calls if name == "cancel"] == [
        {"QueryExecutionId": "q1"}
    ]
    assert sum(name == "start" for name, _ in client.calls) == 1
    assert sum(name == "poll" for name, _ in client.calls) == 4
    assert engine.diagnostics[0].cancellation_outcome == "REQUEST_ACCEPTED"
    assert engine.diagnostics[0].cancellation_attempts == 1


def test_nontransient_first_poll_failure_cancels_without_resubmitting() -> None:
    client = FakeClient()
    poll_error = error("AccessDeniedException")
    client.executions = [poll_error]
    engine = executor(client)
    with pytest.raises(AthenaExecutionError, match="API request failed") as raised:
        run(engine)
    assert raised.value.__cause__ is poll_error
    assert [name for name, _ in client.calls] == ["start", "poll", "cancel"]
    assert engine.diagnostics[0].state == "POLLING_FAILED"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({}, "query execution"),
        ({"QueryExecution": None}, "query execution"),
        ({"QueryExecution": {}}, "query status"),
        ({"QueryExecution": {"Status": None, "Statistics": None}}, "query status"),
        (
            {"QueryExecution": {"Status": {"State": "mystery"}, "Statistics": []}},
            "unknown query status",
        ),
    ],
)
def test_malformed_poll_response_cancels_without_masking_validation_error(
    response: dict[str, object], message: str
) -> None:
    client = FakeClient()
    client.executions = [
        {"QueryExecution": {"Status": {"State": "RUNNING"}}},
        response,
    ]
    engine = executor(client)
    with pytest.raises(DataValidationError, match=message):
        run(engine)
    assert [name for name, _ in client.calls] == ["start", "poll", "poll", "cancel"]
    diagnostic = engine.diagnostics[0]
    assert diagnostic.state == "POLLING_FAILED"
    assert diagnostic.cancellation_outcome == "REQUEST_ACCEPTED"
    assert diagnostic.cancellation_attempts == 1
    assert diagnostic.scanned_bytes is None


@pytest.mark.parametrize(
    ("cleanup_error", "attempts"),
    [
        (error("AccessDeniedException"), 1),
        (error("InternalServerException"), 3),
        (EndpointConnectionError(endpoint_url="https://offline.invalid"), 3),
        (RuntimeError("unexpected cleanup failure"), 1),
    ],
    ids=["permanent", "service-retries", "connection-retries", "unexpected"],
)
def test_cleanup_failure_preserves_original_exception(
    cleanup_error: Exception, attempts: int
) -> None:
    client = FakeClient()
    original = AthenaExecutionError("original polling failure")
    client.executions = [original]
    client.cancellations = [cleanup_error]
    engine = executor(client)
    with pytest.raises(AthenaExecutionError) as raised:
        run(engine)
    assert raised.value is original
    assert raised.value.__cause__ is None
    assert sum(name == "cancel" for name, _ in client.calls) == attempts
    assert sum(name == "start" for name, _ in client.calls) == 1
    diagnostic = engine.diagnostics[0]
    assert diagnostic.cancellation_attempts == attempts
    assert diagnostic.cancellation_outcome == "REQUEST_FAILED"


@pytest.mark.parametrize(
    ("timeout", "max_attempts", "expected_attempts", "expected_elapsed"),
    [(0.5, 3, 2, 0.5), (120.0, 10, 5, 5.0)],
)
def test_cleanup_backoff_is_bounded_by_its_own_deadline(
    timeout: float, max_attempts: int, expected_attempts: int, expected_elapsed: float
) -> None:
    client = FakeClient()
    original = AthenaExecutionError("original polling failure")
    client.executions = [original]
    client.cancellations = [error("InternalServerException")]
    engine = executor(client, timeout=timeout, max_attempts=max_attempts)
    with pytest.raises(AthenaExecutionError) as raised:
        run(engine)
    assert raised.value is original
    assert engine.clock() == expected_elapsed
    assert sum(name == "cancel" for name, _ in client.calls) == expected_attempts
    diagnostic = engine.diagnostics[0]
    assert diagnostic.cancellation_attempts == expected_attempts
    assert diagnostic.cancellation_outcome == "DEADLINE_EXCEEDED"


def test_cleanup_does_not_retry_after_an_inflight_call_uses_its_budget() -> None:
    class SlowClient(FakeClient):
        def stop_query_execution(self, **kwargs: object) -> dict[str, object]:
            engine.sleep(0.5)
            return super().stop_query_execution(**kwargs)

    client = SlowClient()
    original = AthenaExecutionError("original polling failure")
    client.executions = [original]
    client.cancellations = [error("InternalServerException")]
    engine = executor(client, timeout=0.5)
    with pytest.raises(AthenaExecutionError) as raised:
        run(engine)
    assert raised.value is original
    assert [name for name, _ in client.calls] == ["start", "poll", "cancel"]
    assert engine.diagnostics[0].cancellation_outcome == "DEADLINE_EXCEEDED"
    assert engine.diagnostics[0].cancellation_attempts == 1


@pytest.mark.parametrize("failure_stage", ["submission", "polling"])
def test_cleanup_only_targets_the_current_execution_attempt(failure_stage: str) -> None:
    client = FakeClient()
    original = AthenaExecutionError("second execution attempt failure")
    client.submissions = [
        {"QueryExecutionId": "q1"},
        original if failure_stage == "submission" else {"QueryExecutionId": "q2"},
    ]
    client.executions = [
        {"QueryExecution": {"Status": {"State": "FAILED", "AthenaError": {"Retryable": True}}}},
        {"QueryExecution": {"Status": {"State": "RUNNING"}}},
        original,
    ]
    engine = executor(client)
    with pytest.raises(AthenaExecutionError) as raised:
        run(engine)
    assert raised.value is original
    assert sum(name == "start" for name, _ in client.calls) == 2
    expected_stops = [] if failure_stage == "submission" else [{"QueryExecutionId": "q2"}]
    assert [arguments for name, arguments in client.calls if name == "cancel"] == expected_stops
    assert engine.diagnostics[0].query_id == "q1"
    assert engine.diagnostics[0].state == "FAILED"
    assert engine.diagnostics[0].cancellation_outcome is None
    assert engine.diagnostics[1].query_id == (None if failure_stage == "submission" else "q2")


def test_failed_query_with_invalid_error_details_is_not_cancelled() -> None:
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": "FAILED", "AthenaError": None}}}]
    engine = executor(client)
    with pytest.raises(DataValidationError, match="query error"):
        run(engine)
    assert [name for name, _ in client.calls] == ["start", "poll"]
    assert engine.diagnostics[0].cancellation_outcome is None


def test_timeout_during_retry_backoff_does_not_cancel_a_failed_query() -> None:
    client = FakeClient()
    client.executions = [
        {"QueryExecution": {"Status": {"State": "FAILED", "AthenaError": {"Retryable": True}}}}
    ]
    engine = executor(client, timeout=0.25)
    with pytest.raises(AthenaTimeoutError):
        run(engine)
    assert [name for name, _ in client.calls] == ["start", "poll"]
    assert engine.diagnostics[0].cancellation_outcome is None


def test_timeout_cancels_running_query_with_no_result_fetch() -> None:
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": "RUNNING"}}}]
    engine = executor(client, timeout=0.5)
    with pytest.raises(AthenaTimeoutError):
        run(engine)
    assert [name for name, _ in client.calls] == ["start", "poll", "poll", "cancel"]
    assert engine.diagnostics[0].state == "TIMED_OUT"
    assert engine.diagnostics[0].cancellation_attempts == 1
    assert engine.diagnostics[0].cancellation_outcome == "REQUEST_ACCEPTED"


def test_timeout_cleanup_can_retry_after_the_main_deadline_expires() -> None:
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": "RUNNING"}}}]
    client.cancellations = [error("InternalServerException"), {}]
    engine = executor(client, timeout=0.5)
    with pytest.raises(AthenaTimeoutError):
        run(engine)
    assert engine.clock() == 0.75  # Main deadline was 0.5; cleanup has a fresh budget.
    assert [name for name, _ in client.calls] == ["start", "poll", "poll", "cancel", "cancel"]
    assert engine.diagnostics[0].state == "TIMED_OUT"
    assert engine.diagnostics[0].cancellation_attempts == 2
    assert engine.diagnostics[0].cancellation_outcome == "REQUEST_ACCEPTED"


def test_cancellation_failure_is_preserved_in_diagnostics() -> None:
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": "QUEUED"}}}]
    client.cancellations = [error("AccessDeniedException")]
    engine = executor(client, timeout=0.5)
    with pytest.raises(AthenaTimeoutError):
        run(engine)
    assert engine.diagnostics[0].state == "TIMED_OUT_CANCELLATION_FAILED"
    assert engine.diagnostics[0].cancellation_outcome == "REQUEST_FAILED"


def test_running_to_queued_transition_is_polled() -> None:
    client = FakeClient()
    success = client.executions[0]
    states: list[dict[str, object] | Exception] = [
        {"QueryExecution": {"Status": {"State": state}}} for state in ("RUNNING", "QUEUED")
    ]
    client.executions = [*states, success]
    assert run(executor(client)) == [(7,)]


def test_pagination_preserves_nulls_empty_strings_exact_numbers_and_header_like_data() -> None:
    columns = (("name", "varchar"), ("n", "bigint"), ("money", "decimal(38,2)"))
    client = FakeClient()
    client.pages = [
        page(columns, [("", "9223372036854775808", "12345678901234567890.05")], token="next"),
        page(columns, [("name", "-7", None), (None, "0", "-0.01")], header=False),
    ]
    assert run(executor(client)) == [
        ("", 9223372036854775808, Decimal("12345678901234567890.05")),
        ("name", -7, None),
        (None, 0, Decimal("-0.01")),
    ]
    requests = [arguments for name, arguments in client.calls if name == "results"]
    assert "NextToken" not in requests[0]
    assert requests[1]["NextToken"] == "next"


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("bigint", "1.0"),
        ("decimal", "NaN"),
        ("decimal", "Infinity"),
        ("decimal", "oops"),
        ("double", "1.0"),
    ],
)
def test_inexact_or_malformed_result_types_fail(kind: str, value: str) -> None:
    client = FakeClient()
    client.pages = [page((("n", kind),), [(value,)])]
    engine = executor(client)
    with pytest.raises(DataValidationError):
        run(engine)
    assert engine.diagnostics[0].state == "RESULTS_FAILED"
    assert not any(name == "cancel" for name, _ in client.calls)


@pytest.mark.parametrize("code", ["AccessDeniedException", "InternalServerException"])
def test_result_api_failure_does_not_cancel_a_succeeded_query(code: str) -> None:
    client = FakeClient()
    client.pages = [error(code)]
    engine = executor(client)
    with pytest.raises(AthenaExecutionError):
        run(engine)
    assert not any(name == "cancel" for name, _ in client.calls)
    assert engine.diagnostics[0].state == "RESULTS_FAILED"
    assert engine.diagnostics[0].cancellation_outcome is None


@pytest.mark.parametrize("change", ["header", "width", "metadata", "token", "no_header"])
def test_malformed_results_fail_closed(change: str) -> None:
    client = FakeClient()
    first = page((("x", "bigint"),), [("7",)], token="next")
    second = page((("x", "bigint"),), [("8",)], header=False)
    if change == "header":
        first = page((("x", "bigint"),), [], header=False)
    elif change == "width":
        first = page((("x", "bigint"),), [("7", "8")])
    elif change == "metadata":
        second = page((("y", "bigint"),), [("8",)], header=False)
    elif change == "token":
        second["NextToken"] = "next"
    else:
        result_set = cast(dict[str, object], first["ResultSet"])
        result_set["Rows"] = []
    client.pages = [first, second]
    with pytest.raises(DataValidationError):
        run(executor(client))


def test_unrecognized_status_and_missing_query_id_fail_closed() -> None:
    client = FakeClient()
    client.submissions = [{}]
    with pytest.raises(DataValidationError):
        run(executor(client))
    assert [name for name, _ in client.calls] == ["start"]
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": "mystery"}}}]
    with pytest.raises(DataValidationError):
        run(executor(client))


def test_result_pagination_timeout_does_not_cancel_a_succeeded_query() -> None:
    class SlowClient(FakeClient):
        def get_query_results(self, **kwargs: object) -> dict[str, object]:
            engine.sleep(0.5)
            return super().get_query_results(**kwargs)

    client = SlowClient()
    engine = executor(client, timeout=0.5)
    client.pages = [page((("x", "bigint"),), [("7",)], token="next")]
    with pytest.raises(AthenaTimeoutError):
        run(engine)
    assert [name for name, _ in client.calls] == ["start", "poll", "results"]
    assert engine.diagnostics[0].state == "TIMED_OUT"
    assert engine.diagnostics[0].cancellation_attempts == 0
    assert engine.diagnostics[0].cancellation_outcome is None
