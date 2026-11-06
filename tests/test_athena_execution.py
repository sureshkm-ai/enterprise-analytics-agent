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


def executor(client: FakeClient, *, timeout: float = 2.0) -> AthenaExecutor:
    timer = FakeTime()
    return AthenaExecutor(
        client,
        database="retail",
        workgroup="development",
        output_location="s3://query-results/results/",
        expected_bucket_owner="123456789012",
        timeout_seconds=timeout,
        poll_seconds=0.25,
        max_attempts=3,
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


def test_timeout_cancels_running_query_with_no_result_fetch() -> None:
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": "RUNNING"}}}]
    engine = executor(client, timeout=0.5)
    with pytest.raises(AthenaTimeoutError):
        run(engine)
    assert [name for name, _ in client.calls] == ["start", "poll", "poll", "cancel"]
    assert engine.diagnostics[0].state == "TIMED_OUT"


def test_cancellation_failure_is_preserved_in_diagnostics() -> None:
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": "QUEUED"}}}]
    client.cancellations = [error("AccessDeniedException")]
    engine = executor(client, timeout=0.5)
    with pytest.raises(AthenaTimeoutError):
        run(engine)
    assert engine.diagnostics[0].state == "TIMED_OUT_CANCELLATION_FAILED"


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
    client = FakeClient()
    client.executions = [{"QueryExecution": {"Status": {"State": "mystery"}}}]
    with pytest.raises(DataValidationError):
        run(executor(client))


def test_total_deadline_also_bounds_result_pagination() -> None:
    class SlowClient(FakeClient):
        def get_query_results(self, **kwargs: object) -> dict[str, object]:
            engine.sleep(0.5)
            return super().get_query_results(**kwargs)

    client = SlowClient()
    engine = executor(client, timeout=0.5)
    client.pages = [page((("x", "bigint"),), [("7",)], token="next")]
    with pytest.raises(AthenaTimeoutError):
        run(engine)
    assert client.calls[-1][0] == "cancel"
