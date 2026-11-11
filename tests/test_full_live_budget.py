"""Complete-suite accounting with fake transports and temporary files only."""

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from pydantic import ValidationError

from enterprise_analytics_agent.retail_evaluation.full_live import (
    RUNTIME_ARN,
    FullLiveBudget,
    FullLiveBudgetError,
    FullLivePhase,
    FullLiveReview,
)

SDK: Any = BaseClient

NOW = datetime(2026, 11, 11, 18, tzinfo=UTC)


def review(**changes: Any) -> FullLiveReview:
    return FullLiveReview.model_validate(
        {
            "parity_template_sha256": "b" * 64,
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
            **changes,
        }
    )


@pytest.fixture
def budget(tmp_path: Path) -> FullLiveBudget:
    return FullLiveBudget(review(), repository_root=tmp_path, now=lambda: NOW)


def runtime_parameters(**changes: Any) -> dict[str, Any]:
    return {
        "agentRuntimeArn": RUNTIME_ARN,
        "qualifier": "DEFAULT",
        "runtimeSessionId": "d409bb5a-4f26-4beb-b357-2e58ee16a509",
        "payload": b'{"question":"Show net_revenue for January 2025."}',
        **changes,
    }


def invoke(
    budget: FullLiveBudget,
    phase: FullLivePhase = "agent_parity",
    *,
    parameters: dict[str, Any] | None = None,
    dispatch: Any = lambda: {"accepted": True},
) -> Any:
    return budget.call(
        phase,
        "bedrock-agentcore",
        "InvokeAgentRuntime",
        parameters or runtime_parameters(),
        dispatch,
    )


def query(budget: FullLiveBudget) -> None:
    budget.call(
        "athena_parity",
        "athena",
        "StartQueryExecution",
        {"WorkGroup": "enterprise-analytics-dev", "QueryString": "authored test query"},
        lambda: {"QueryExecutionId": "authored"},
    )


def sdk_client(service: str, *, retries: int = 1, region: str = "us-west-2") -> Any:
    return SimpleNamespace(
        meta=SimpleNamespace(
            service_model=SimpleNamespace(service_name=service),
            config=SimpleNamespace(retries={"total_max_attempts": retries}),
            region_name=region,
        )
    )


def test_unused_proposal_and_summary_do_not_create_ledger_or_claim(budget: FullLiveBudget) -> None:
    result = budget.summary()
    assert result["runtime_used"] == result["direct_athena_submissions"] == 0
    assert result["runtime_remaining"] == 56
    assert result["phase_remaining"] == {
        "athena_parity": 201,
        "agent_parity": 19,
        "retail": 36,
        "restoration_smoke": 1,
    }
    assert not budget.directory.exists() and not budget.sdk_claim.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "default"},
        {"account": "999999999999"},
        {"region": "us-east-1"},
        {"campaign_id": "milestone-5"},
        {"runtime_arn": RUNTIME_ARN + "different"},
        {"qualifier": "UNREVIEWED"},
        {"maximum_runtime_invocations": 57},
        {"maximum_direct_athena_submissions": 202},
        {"agent_parity_invocations": 20},
        {"retail_invocations": 37},
        {"protected_restoration_invocations": 0},
        {"archive_sha256": "a" * 64},
        {"artifact_version_id": "new-version"},
        {"parity_template_sha256": "0" * 64},
        {"expires_at": "2026-11-12T00:00:00"},
        {"tenant_id": "model-supplied"},
    ],
)
def test_review_refuses_changed_trusted_scope_and_pending_pins(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        review(**change)


def test_review_is_immutable_and_hash_binds_expiry_and_parity() -> None:
    original = review()
    attempted_mutation: Any = original
    with pytest.raises(ValidationError):
        attempted_mutation.profile = "default"
    assert original.sha256 != review(parity_template_sha256="c" * 64).sha256
    assert original.sha256 != review(expires_at=NOW + timedelta(days=2)).sha256


def test_model_copy_cannot_bypass_review_validation_before_budget_paths(tmp_path: Path) -> None:
    copied = review().model_copy(update={"runtime_arn": RUNTIME_ARN + "unreviewed"})
    with pytest.raises(ValidationError):
        FullLiveBudget(copied, repository_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_reservation_and_receipt_are_durable_before_dispatch(budget: FullLiveBudget) -> None:
    def transport() -> dict[str, str]:
        rows = [json.loads(line) for line in budget.path.read_text().splitlines()]
        assert len(rows) == 1 and rows[0]["event"] == "reserved"
        assert json.loads((budget.claims / "1.json").read_bytes()) == rows[0]
        assert json.loads(budget.sdk_claim.read_bytes())["review_sha256"] == budget.review.sha256
        assert "Show net_revenue" not in budget.path.read_text()
        return {"status": "request accepted, not semantic acceptance"}

    assert invoke(budget, dispatch=transport) == {
        "status": "request accepted, not semantic acceptance"
    }
    rows = [json.loads(line) for line in budget.path.read_text().splitlines()]
    assert rows[-1]["status"] == "sdk_returned"
    assert budget.summary()["runtime_used"] == 1


def test_phase_limits_and_protected_smoke_enforce_56_total_without_reset(
    budget: FullLiveBudget,
) -> None:
    for _ in range(19):
        invoke(budget)
    with pytest.raises(FullLiveBudgetError, match="phase allowance"):
        invoke(budget)
    for _ in range(36):
        invoke(budget, "retail")
    with pytest.raises(FullLiveBudgetError, match="phase allowance"):
        invoke(budget, "retail")
    before = budget.summary()
    assert before["runtime_used"] == 55 and before["runtime_remaining"] == 1
    assert before["phase_remaining"] == {
        "athena_parity": 201,
        "agent_parity": 0,
        "retail": 0,
        "restoration_smoke": 1,
    }
    invoke(budget, "restoration_smoke")
    assert budget.summary()["runtime_used"] == 56
    assert budget.summary()["restoration_started"] is True
    with pytest.raises(FullLiveBudgetError, match="phase is closed"):
        query(budget)
    with pytest.raises(FullLiveBudgetError, match="phase is closed"):
        invoke(budget, "restoration_smoke")


def test_direct_athena_submission_cap_is_independent_from_runtime(
    budget: FullLiveBudget,
) -> None:
    for _ in range(201):
        query(budget)
    with pytest.raises(FullLiveBudgetError, match="phase allowance"):
        query(budget)
    result = budget.summary()
    assert result["direct_athena_submissions"] == 201 and result["runtime_used"] == 0
    invoke(budget, "restoration_smoke")
    assert budget.summary()["runtime_used"] == 1


@pytest.mark.parametrize("failure", [TimeoutError("signed secret"), KeyboardInterrupt()])
def test_failed_sdk_attempt_is_spent_original_error_survives_and_smoke_is_protected(
    budget: FullLiveBudget, failure: BaseException
) -> None:
    calls = 0

    def transport() -> None:
        nonlocal calls
        calls += 1
        raise failure

    with pytest.raises(type(failure)) as caught:
        invoke(budget, dispatch=transport)
    assert caught.value is failure and calls == 1
    assert budget.summary()["runtime_used"] == 1
    assert budget.summary()["failed"] is True
    with pytest.raises(FullLiveBudgetError, match="blocked"):
        invoke(budget, dispatch=transport)
    assert calls == 1
    invoke(budget, "restoration_smoke")
    assert budget.summary()["runtime_used"] == 2
    assert "signed secret" not in budget.path.read_text()


def test_operator_semantic_failure_blocks_future_tests_but_not_smoke(
    budget: FullLiveBudget,
) -> None:
    invoke(budget)
    budget.stop("pytest_phase_failed")
    assert budget.summary()["stopped"] is True and budget.summary()["failed"] is False
    with pytest.raises(FullLiveBudgetError, match="blocked"):
        query(budget)
    invoke(budget, "restoration_smoke")
    assert budget.summary()["runtime_used"] == 2


@pytest.mark.parametrize("reason", ["", "raw signed URL?secret=1", "not\na code", "x" * 81])
def test_stop_diagnostic_must_be_authored_code(budget: FullLiveBudget, reason: str) -> None:
    with pytest.raises(ValueError):
        budget.stop(reason)
    assert not budget.directory.exists()


def test_expiry_blocks_call_without_creating_evidence_or_spending_slot(tmp_path: Path) -> None:
    expired = FullLiveBudget(review(expires_at=NOW), repository_root=tmp_path, now=lambda: NOW)
    with pytest.raises(FullLiveBudgetError, match="expired before dispatch"):
        invoke(expired, dispatch=lambda: pytest.fail("no call"))
    assert not expired.directory.exists() and expired.summary()["runtime_used"] == 0


def test_expiry_is_rechecked_after_lock_before_reservation(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    times = iter([NOW, NOW + timedelta(days=2)])
    monkeypatch.setattr(budget, "now", lambda: next(times))
    with pytest.raises(FullLiveBudgetError, match="window/phase is closed"):
        invoke(budget, dispatch=lambda: pytest.fail("no call"))
    assert not budget.sdk_claim.exists()


def test_unknown_outcome_survives_logging_failure_and_does_not_allow_retry(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    append = budget._append

    def fail_outcome(stream: Any, value: dict[str, object]) -> None:
        if value["event"] == "outcome":
            raise OSError("authored disk failure")
        append(stream, value)

    monkeypatch.setattr(budget, "_append", fail_outcome)
    with pytest.raises(TimeoutError, match="original"):
        invoke(budget, dispatch=lambda: (_ for _ in ()).throw(TimeoutError("original")))
    assert budget.summary()["incomplete"] is True and budget.summary()["runtime_used"] == 1
    monkeypatch.setattr(budget, "_append", append)
    with pytest.raises(FullLiveBudgetError, match="blocked"):
        invoke(budget, dispatch=lambda: pytest.fail("not retried"))
    invoke(budget, "restoration_smoke")
    assert budget.summary()["runtime_used"] == 2


def test_broken_failure_diagnostics_never_replace_original_sdk_error(
    budget: FullLiveBudget,
) -> None:
    failure = TimeoutError("original SDK error")

    def broken_diagnostic(exc: BaseException) -> dict[str, object]:
        raise RuntimeError("diagnostic formatting failed")

    with pytest.raises(TimeoutError) as caught:
        budget.call(
            "agent_parity",
            "bedrock-agentcore",
            "InvokeAgentRuntime",
            runtime_parameters(),
            lambda: (_ for _ in ()).throw(failure),
            failure_detail=broken_diagnostic,
        )
    assert caught.value is failure
    assert budget.summary()["incomplete"] is True
    assert budget.summary()["runtime_used"] == 1


@pytest.mark.parametrize(
    "tamper", ["receipt", "extra_receipt", "journal", "claim", "delete_journal"]
)
def test_changed_or_missing_evidence_cannot_restart_count(
    budget: FullLiveBudget, tamper: str
) -> None:
    invoke(budget)
    if tamper == "receipt":
        (budget.claims / "1.json").write_text("{}")
    elif tamper == "extra_receipt":
        (budget.claims / "999.json").write_text("{}")
    elif tamper == "journal":
        budget.path.write_text(budget.path.read_text()[:-1])
    elif tamper == "claim":
        budget.sdk_claim.write_text("{}")
    else:
        budget.path.unlink()
    with pytest.raises(FullLiveBudgetError):
        budget.summary()


def test_review_change_and_duplicate_outcome_fail_closed(budget: FullLiveBudget) -> None:
    invoke(budget)
    changed = FullLiveBudget(
        review(parity_template_sha256="c" * 64), repository_root=budget.root, now=lambda: NOW
    )
    with pytest.raises(FullLiveBudgetError):
        changed.summary()
    with budget.path.open("a") as out:
        out.write(budget.path.read_text().splitlines()[-1] + "\n")
    with pytest.raises(FullLiveBudgetError):
        budget.summary()


def test_aliased_budget_path_cannot_touch_historical_ledger(tmp_path: Path) -> None:
    old = tmp_path / "artifacts/milestone-5"
    old.mkdir(parents=True)
    sentinel = old / "runtime-invocations.jsonl"
    sentinel.write_text("historical evidence")
    (tmp_path / "artifacts/full-live").symlink_to(old, target_is_directory=True)
    with pytest.raises(Exception, match="aliased"):
        FullLiveBudget(review(), repository_root=tmp_path)
    assert sentinel.read_text() == "historical evidence"


@pytest.mark.parametrize(
    "parameters",
    [
        runtime_parameters(agentRuntimeArn=RUNTIME_ARN + "other"),
        runtime_parameters(qualifier="OTHER"),
        runtime_parameters(payload=b'{"question":"Revenue?","tenant_id":"other"}'),
        runtime_parameters(runtimeSessionId="short"),
    ],
)
def test_wrong_runtime_target_or_identity_payload_never_reserves(
    budget: FullLiveBudget, parameters: dict[str, Any]
) -> None:
    with pytest.raises(FullLiveBudgetError):
        invoke(budget, parameters=parameters, dispatch=lambda: pytest.fail("no call"))
    assert not budget.directory.exists()


def test_sdk_guard_counts_before_real_transport_and_restores_patch(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def transport(client: Any, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        rows = [json.loads(line) for line in budget.path.read_text().splitlines()]
        assert rows[-1]["event"] == "reserved"
        calls.append((operation, parameters))
        return {"response": "authored"}

    monkeypatch.setattr(BaseClient, "_make_api_call", transport)
    client = sdk_client("bedrock-agentcore")
    with budget.counted_sdk("agent_parity"):
        assert SDK._make_api_call(client, "InvokeAgentRuntime", runtime_parameters()) == {
            "response": "authored"
        }
    assert SDK._make_api_call is transport
    assert len(calls) == 1 and budget.summary()["runtime_used"] == 1


@pytest.mark.parametrize(
    "service,operation,parameters,region,retries",
    [
        ("bedrock-agentcore", "InvokeAgentRuntime", runtime_parameters(), "us-east-1", 1),
        ("bedrock-agentcore", "InvokeAgentRuntime", runtime_parameters(), "us-west-2", 2),
        ("athena", "StartQueryExecution", {"WorkGroup": "wrong"}, "us-west-2", 1),
        ("bedrock-runtime", "Converse", {"modelId": "other"}, "us-west-2", 1),
        ("s3", "PutObject", {"Bucket": "source"}, "us-west-2", 1),
        ("sts", "AssumeRole", {"RoleArn": "unreviewed-role"}, "us-west-2", 1),
    ],
)
def test_sdk_guard_refuses_extra_targets_retries_model_calls_and_mutations(
    budget: FullLiveBudget,
    monkeypatch: pytest.MonkeyPatch,
    service: str,
    operation: str,
    parameters: dict[str, Any],
    region: str,
    retries: int,
) -> None:
    monkeypatch.setattr(BaseClient, "_make_api_call", lambda *args: pytest.fail("no SDK dispatch"))
    client = sdk_client(service, retries=retries, region=region)
    with budget.counted_sdk("athena_parity"):
        with pytest.raises(FullLiveBudgetError):
            SDK._make_api_call(client, operation, parameters)
    assert not budget.directory.exists()


def test_readonly_setup_passes_without_spending_and_sdk_failures_are_not_retried(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = []

    def transport(client: Any, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        attempts.append(operation)
        if operation == "InvokeAgentRuntime":
            raise TimeoutError("authored")
        return {"Account": "453711491609"}

    monkeypatch.setattr(BaseClient, "_make_api_call", transport)
    with budget.counted_sdk("agent_parity"):
        SDK._make_api_call(sdk_client("sts"), "GetCallerIdentity", {})
        with pytest.raises(TimeoutError):
            SDK._make_api_call(
                sdk_client("bedrock-agentcore"), "InvokeAgentRuntime", runtime_parameters()
            )
        with pytest.raises(FullLiveBudgetError, match="blocked"):
            SDK._make_api_call(
                sdk_client("bedrock-agentcore"), "InvokeAgentRuntime", runtime_parameters()
            )
    assert attempts == ["GetCallerIdentity", "InvokeAgentRuntime"]
    assert budget.summary()["runtime_used"] == 1


def test_nested_guards_fail_and_exception_releases_guard(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = SDK._make_api_call
    with pytest.raises(KeyboardInterrupt):
        with budget.counted_sdk("agent_parity"):
            with pytest.raises(FullLiveBudgetError, match="already active"):
                with budget.counted_sdk("retail"):
                    pytest.fail("no nested phase")
            raise KeyboardInterrupt()
    assert SDK._make_api_call is original
    with budget.counted_sdk("retail"):
        pass
    assert not budget.directory.exists()


def test_production_athena_transient_retries_remain_counted_and_bounded(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = []

    def transport(client: Any, operation: str, parameters: dict[str, Any]) -> dict[str, str]:
        attempts.append(parameters["ClientRequestToken"])
        if len(attempts) < 3:
            raise ClientError(
                {
                    "Error": {"Code": "ThrottlingException", "Message": "secret"},
                    "ResponseMetadata": {
                        "RequestId": "authored-request",
                        "HTTPStatusCode": 429,
                        "HTTPHeaders": {},
                        "HostId": "authored",
                        "RetryAttempts": 0,
                    },
                },
                operation,
            )
        return {"QueryExecutionId": "one-idempotent-query"}

    monkeypatch.setattr(BaseClient, "_make_api_call", transport)
    client = sdk_client("athena")
    parameters = {"WorkGroup": "enterprise-analytics-dev", "ClientRequestToken": "same-token"}
    with budget.counted_sdk("athena_parity"):
        for expected in (1, 2):
            with pytest.raises(ClientError):
                SDK._make_api_call(client, "StartQueryExecution", parameters)
            # The guard never retries; the adapter owns the next explicit call.
            assert len(attempts) == expected
        assert SDK._make_api_call(client, "StartQueryExecution", parameters) == {
            "QueryExecutionId": "one-idempotent-query"
        }
    summary = budget.summary()
    assert attempts == ["same-token"] * 3
    assert summary["direct_athena_submissions"] == 3
    assert summary["retryable_athena_failures"] == summary["failed_sdk_attempts"] == 2
    assert summary["failed"] is False and summary["ordinary_blocked"] is False
    rows = [json.loads(line) for line in budget.path.read_text().splitlines()]
    assert rows[1]["diagnostic"]["aws_error_code"] == "ThrottlingException"
    assert rows[1]["diagnostic"]["request_id"] == "authored-request"
    assert "secret" not in budget.path.read_text()


def test_terminal_athena_failure_blocks_ordinary_calls_until_cleanup(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(client: Any, operation: str, parameters: dict[str, Any]) -> None:
        raise ClientError({"Error": {"Code": "AccessDeniedException"}}, operation)

    monkeypatch.setattr(BaseClient, "_make_api_call", denied)
    with budget.counted_sdk("athena_parity"):
        with pytest.raises(ClientError):
            SDK._make_api_call(
                sdk_client("athena"),
                "StartQueryExecution",
                {"WorkGroup": "enterprise-analytics-dev"},
            )
    assert budget.summary()["failed"] is True
    with pytest.raises(FullLiveBudgetError, match="blocked"):
        invoke(budget)


def test_response_body_failure_never_refunds_or_reinvokes_runtime(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def broken_body() -> None:
        raise TimeoutError("body read failed after accepted invocation")

    def transport(client: Any, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        calls.append(operation)
        return {"response": SimpleNamespace(read=broken_body)}

    monkeypatch.setattr(BaseClient, "_make_api_call", transport)
    with budget.counted_sdk("retail"):
        response = SDK._make_api_call(
            sdk_client("bedrock-agentcore"), "InvokeAgentRuntime", runtime_parameters()
        )
        with pytest.raises(TimeoutError):
            response["response"].read()
        budget.stop("response_body_failed")
        with pytest.raises(FullLiveBudgetError, match="blocked"):
            SDK._make_api_call(
                sdk_client("bedrock-agentcore"), "InvokeAgentRuntime", runtime_parameters()
            )
    assert calls == ["InvokeAgentRuntime"] and budget.summary()["runtime_used"] == 1


def test_sdk_guard_refuses_billable_work_from_another_thread(
    budget: FullLiveBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors = []

    def other_thread() -> None:
        try:
            SDK._make_api_call(
                sdk_client("bedrock-agentcore"), "InvokeAgentRuntime", runtime_parameters()
            )
        except FullLiveBudgetError as exc:
            errors.append(str(exc))

    monkeypatch.setattr(BaseClient, "_make_api_call", lambda *args: pytest.fail("no dispatch"))
    with budget.counted_sdk("agent_parity"):
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join(timeout=3)
    assert errors == ["Billable work must stay in the owning operator thread"]
    assert not budget.directory.exists()
