"""Fault injection at every checkpoint operation, without credentials or AWS."""

import json
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError
from test_q18_artifacts import ReviewedFixture
from test_q18_artifacts import reviewed_fixture as reviewed_fixture

from enterprise_analytics_agent.adapters.operator_reads import READS, OperatorReadError, ReadPool
from enterprise_analytics_agent.adapters.repair_operations import _BudgetedSession
from enterprise_analytics_agent.adapters.retail_checkpoint import verify_candidate_checkpoint


class Session:
    def __init__(self, failures: list[BaseException]) -> None:
        self.failures = list(failures)
        self.calls = 0
        self.clients = 0

    def client(self, name: str, **kwargs: Any) -> Any:
        self.clients += 1
        assert kwargs["config"].retries == {"total_max_attempts": 1}
        return self

    def __getattr__(self, name: str) -> Any:
        if name == "meta":
            raise AttributeError(name)

        def call(**kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            if self.failures:
                raise self.failures.pop(0)
            return {"Account": "453711491609", "ResponseMetadata": {"RequestId": "authored"}}

        return call


def timeout() -> ConnectTimeoutError:
    return ConnectTimeoutError(endpoint_url="https://test.invalid/?secret=NEVER_LOG_THIS")


def test_regression_checkpoint_recovers_single_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.monotonic", lambda: 0.0)
    monkeypatch.setattr("time.sleep", lambda value: None)
    sdk = Session([timeout()])
    result = _BudgetedSession(sdk, 120).client("sts").get_caller_identity()
    assert result["Account"] == "453711491609" and sdk.calls == 2


@pytest.mark.parametrize("service,operation", [(s, op) for s, ops in READS.items() for op in ops])
def test_every_checkpoint_read_recovers_and_retains_complete_strict_validation(
    reviewed_fixture: ReviewedFixture,
    tmp_path: Path,
    service: str,
    operation: str,
) -> None:
    fixture = reviewed_fixture
    remaining = [2]

    class Faulted:
        def client(self, name: str, **kwargs: Any) -> Any:
            raw = fixture.session.client(name, **kwargs)
            if name == service:
                method = getattr(raw, operation)

                def read(**params: Any) -> Any:
                    if remaining[0]:
                        remaining[0] -= 1
                        raise timeout()
                    return method(**params)

                setattr(raw, operation, read)
            return raw

    journal = tmp_path / "reads.jsonl"
    pool = ReadPool(Faulted(), journal, monotonic=lambda: 0, sleep=lambda delay: None)
    result = verify_candidate_checkpoint(
        fixture.review, fixture.version, session=pool.view(120, "candidate-checkpoint")
    )
    assert result["artifact_sha256"] == fixture.review.candidate_sha256
    assert remaining == [0]
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    failures = [x for x in events if x["event"] == "failed"]
    assert [(x["service"], x["operation"], x["attempt"]) for x in failures] == [
        (service, operation, 1),
        (service, operation, 2),
    ]
    assert "NEVER_LOG_THIS" not in journal.read_text()
    assert "secret" not in journal.read_text()


@pytest.mark.parametrize(
    "code,retries",
    [("AccessDeniedException", 1), ("ValidationException", 1), ("ThrottlingException", 3)],
)
def test_terminal_error_retains_aws_code_and_attempts(
    tmp_path: Path,
    code: str,
    retries: int,
) -> None:
    error = ClientError(
        {
            "Error": {"Code": code, "Message": "secret"},
            "ResponseMetadata": {
                "RequestId": "request-1",
                "HTTPHeaders": {},
                "HTTPStatusCode": 403,
                "HostId": "test",
                "RetryAttempts": 0,
            },
        },
        "GetAgentRuntime",
    )
    sdk = Session([error] * 4)
    pool = ReadPool(sdk, tmp_path / "reads.jsonl", monotonic=lambda: 0, sleep=lambda x: None)
    with pytest.raises(OperatorReadError) as failure:
        pool.view(120, "restore").client("bedrock-agentcore-control").get_agent_runtime()
    assert sdk.calls == retries
    assert failure.value.diagnostic["aws_error_code"] == code
    assert failure.value.diagnostic["request_id"] == "request-1"
    assert failure.value.__cause__ is error
    assert "secret" not in (tmp_path / "reads.jsonl").read_text()


def test_deadline_prevents_retry_and_pool_reuses_connections() -> None:
    sdk = Session([timeout()])
    pool = ReadPool(sdk, monotonic=lambda: 0, sleep=lambda x: pytest.fail("no retry budget"))
    with pytest.raises(OperatorReadError):
        pool.view(0.25, "short-budget").client("sts").get_caller_identity()
    assert sdk.calls == 1
    pool.view(120, "next-check").client("sts").get_caller_identity()
    assert sdk.clients == 1


@pytest.mark.parametrize(
    "service,operation",
    [
        ("s3", "put_object"),
        ("cloudformation", "update_stack"),
        ("bedrock-agentcore", "invoke_agent_runtime"),
        ("athena", "start_query_execution"),
    ],
)
def test_mutations_and_billable_calls_cannot_use_read_retries(service: str, operation: str) -> None:
    sdk = Session([])
    pool = ReadPool(sdk, monotonic=lambda: 0)
    with pytest.raises(ValueError, match="allowlist"):
        getattr(pool.view(120, "must-refuse").client(service), operation)()
    assert sdk.calls == 0


def test_interrupt_is_journaled_but_never_retried(tmp_path: Path) -> None:
    sdk = Session([KeyboardInterrupt()])
    pool = ReadPool(sdk, tmp_path / "reads.jsonl", monotonic=lambda: 0)
    with pytest.raises(KeyboardInterrupt):
        pool.view(120, "preflight").client("sts").get_caller_identity()
    assert sdk.calls == 1
    events = [json.loads(line) for line in (tmp_path / "reads.jsonl").read_text().splitlines()]
    assert events[-1]["will_retry"] is False


def test_exhausted_connect_and_read_timeouts_retain_operation(tmp_path: Path) -> None:
    sdk = Session([timeout(), ReadTimeoutError(endpoint_url="secret"), timeout()])
    pool = ReadPool(sdk, tmp_path / "reads.jsonl", monotonic=lambda: 0, sleep=lambda x: None)
    with pytest.raises(OperatorReadError) as failure:
        pool.view(120, "candidate").client("s3").head_object(Bucket="code", Key="pinned")
    assert sdk.calls == 3
    assert failure.value.diagnostic["operation"] == "head_object"
    assert failure.value.diagnostic["target"] == {"Bucket": "code", "Key": "pinned"}


def test_invoker_setup_retries_sts_but_never_runtime_invocation(tmp_path: Path) -> None:
    from test_retail_client import target

    from enterprise_analytics_agent.adapters.agentcore_invocation import create_runtime_invoker

    identity = Session([timeout()])
    invocation_calls: list[str] = []

    class InvocationSession:
        def client(self, name: str, **kwargs: Any) -> Any:
            assert name == "bedrock-agentcore"
            assert kwargs["config"].retries["total_max_attempts"] == 1
            return self

        def invoke_agent_runtime(self, **kwargs: Any) -> Any:
            invocation_calls.append("invoke")
            raise timeout()

    reads = ReadPool(identity, tmp_path / "reads.jsonl", monotonic=lambda: 0, sleep=lambda x: None)
    invoke = create_runtime_invoker(
        target(), session=InvocationSession(), identity_session=reads.view(120, "invocation-setup")
    )
    assert identity.calls == 2
    with pytest.raises(TimeoutError):
        invoke(payload=b'{"question":"authored"}', session_id="s" * 36)
    assert invocation_calls == ["invoke"]
