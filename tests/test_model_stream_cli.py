"""Complete streaming-operator commands with real judges and fake dispatch boundaries."""

import hashlib
import io
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import boto3
import pytest
from test_model_streams_review import review as review
from test_model_streams_review import settings

from enterprise_analytics_agent.adapters import model_stream_cli as cli
from enterprise_analytics_agent.adapters.bedrock_model_catalog import BEDROCK_MODELS
from enterprise_analytics_agent.agent.contracts import (
    AgentDiagnostics,
    AgentResponse,
    ToolCallRecord,
)
from enterprise_analytics_agent.retail_evaluation.models import GoldenCase, RetailCase
from enterprise_analytics_agent.ui.model_streams import (
    StreamingLedger,
    StreamingReleases,
    StreamingReview,
    StreamRelease,
    StreamTarget,
)
from enterprise_analytics_agent.ui.models import UiError, UiResult

REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_real_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Streaming CLI regression tests must not create real AWS sessions")

    monkeypatch.setattr(boto3, "Session", forbidden)


def ten_model_review(review: StreamingReview) -> StreamingReview:
    targets = tuple(
        StreamTarget(
            model_key=model.key,
            runtime_name="enterprise_analytics_stream_" + model.key.replace("-", "_"),
            settings=settings().model_copy(update={"model_id": model.model_id}),
            template_sha256="c" * 64,
        )
        for model in BEDROCK_MODELS[:10]
    )
    return review.model_copy(update={"targets": targets})


def release_set(review: StreamingReview) -> StreamingReleases:
    return StreamingReleases(
        review_sha256=review.sha256,
        artifact_version_id="real-returned-version-id",
        models=tuple(
            StreamRelease(
                model_key=target.model_key,
                runtime_arn=(
                    "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
                    + target.runtime_name
                    + "-Abc123"
                ),
                runtime_version="1",
                template_sha256=target.template_sha256,
                configuration_sha256=hashlib.sha256(
                    json.dumps(target.settings.model_dump(mode="json"), sort_keys=True).encode()
                ).hexdigest(),
            )
            for target in review.targets
        ),
    )


def prepare(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "verify_local_inputs", lambda *args: None)
    frozen_cases = cli.acceptance_cases(REPOSITORY)
    monkeypatch.setattr(cli, "acceptance_cases", lambda root: frozen_cases)
    review_path, releases_path, approval_path = (
        tmp_path / "review.json",
        tmp_path / "releases.json",
        tmp_path / "approval.json",
    )
    review_path.write_text(review.model_dump_json())
    releases_path.write_text(release_set(review).model_dump_json())
    approval_path.write_text(
        json.dumps(
            {
                "review_sha256": review.sha256,
                "approved": True,
                "maximum_attempts": 40,
                "expires_at": review.expires_at.isoformat(),
            }
        )
    )
    return [
        "--review",
        str(review_path),
        "--releases",
        str(releases_path),
        "--approval",
        str(approval_path),
    ]


def response(case: RetailCase, golden: GoldenCase, model_id: str) -> AgentResponse:
    return AgentResponse(
        status="answer",
        answer="Validated independent metric results.",
        results=golden.results,
        dataset_version="retail-v1",
        metric_versions={result.metric_id: result.definition_version for result in golden.results},
        diagnostics=AgentDiagnostics(
            model_id=model_id,
            configuration={"reference_date": "2025-04-01"},
            model_calls=3,
            input_tokens=100,
            output_tokens=30,
            latency_ms=10,
            tool_calls=tuple(
                ToolCallRecord(
                    tool_use_id=f"query-{index}",
                    name="query_metric",
                    status="success",
                    arguments=query.model_dump(mode="json"),
                )
                for index, query in enumerate(case.expected_queries)
            ),
            athena=({"bytes_scanned": 128, "execution_ms": 3},),
        ),
    )


def fake_runners(
    root: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fault: str | None = None,
) -> Any:
    cases = cli.acceptance_cases(root)
    state = SimpleNamespace(calls=[], constructors=[])

    class Runner:
        def __init__(
            self,
            actual_root: Path,
            actual_review: StreamingReview,
            releases: StreamingReleases,
            approval: object,
            model_key: str,
            canonical: Path,
            *,
            operator: bool,
        ) -> None:
            assert actual_root == root and actual_review == review and operator is True
            releases.validate_review(review)
            self.key = model_key
            self.model = next(
                target.settings.model_id
                for target in review.targets
                if target.model_key == model_key
            )
            state.constructors.append(model_key)

        def ask(self, request: Any) -> UiResult:
            assert request.mode == "live"
            case, golden = next(pair for pair in cases if pair[0].question == request.question)
            state.calls.append((self.key, request.question, str(request.request_id)))
            ledger = StreamingLedger(root, review)
            assert not (ledger.directory / "accepted.json").exists()
            with ledger.attempt(str(request.request_id), self.key, mode="live") as record:
                record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
                if fault in {"exception", "interrupt"}:
                    try:
                        if fault == "interrupt":
                            raise KeyboardInterrupt
                        raise ConnectionError("authored offline connection failure")
                    except BaseException as exc:
                        record(
                            {
                                "event": "failed",
                                "operation": "InvokeAgentRuntime",
                                "number": 1,
                                "error_type": type(exc).__name__,
                            }
                        )
                        raise
                value = response(case, golden, self.model)
                if fault == "number":
                    payload = value.model_dump(mode="json")
                    payload["results"][0]["rows"][0]["value"] = "9999.99"
                    value = AgentResponse.model_validate(payload)
                elif fault == "plan" and len(state.calls) == 2:
                    payload = value.model_dump(mode="json")
                    payload["diagnostics"]["tool_calls"][0]["arguments"]["group_by"] = []
                    value = AgentResponse.model_validate(payload)
                record({"event": "returned", "operation": "InvokeAgentRuntime", "number": 1})
                if fault == "fallback":
                    record({"event": "question_failed"})
            return UiResult(
                mode="live",
                response=value,
                elapsed_ms=12,
                presentation_status="fallback" if fault == "fallback" else "streamed",
            )

    monkeypatch.setattr(cli, "StreamingQuestions", Runner)
    return state


def test_all_five_case_preserves_frozen_literals_and_complete_requests() -> None:
    probe, combined = cli.acceptance_cases(REPOSITORY)
    assert probe[0].id == "Q18"
    assert probe[0].expected_queries[0].time_range.start.isoformat() == "2025-03-31"
    assert probe[0].expected_queries[0].time_range.end.isoformat() == "2025-04-01"
    assert str(probe[1].results[0].rows[0].value) == "110.25"
    assert [query.metric_id for query in combined[0].expected_queries] == [
        "gross_sales",
        "net_revenue",
        "order_count",
        "average_order_value",
        "return_rate",
    ]
    assert all(
        query.group_by == ("region",)
        and query.dimension_filters == {}
        and query.time_range.start.isoformat() == "2025-01-01"
        and query.time_range.end.isoformat() == "2025-02-01"
        for query in combined[0].expected_queries
    )
    # Literal frozen independently audited regional values, not adapter/generator outputs.
    assert [[str(row.value) for row in result.rows] for result in combined[1].results] == [
        ["195.50", "359.75"],
        ["172.17", "313.44"],
        ["5", "3"],
        ["34.43", "104.48"],
        ["0.200000", "0.333333"],
    ]


def test_verify_offline_creates_no_aws_session_or_campaign(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = prepare(tmp_path, ten_model_review(review), monkeypatch)
    assert cli.main(args + ["verify-offline"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is True and result["aws_calls"] == 0
    assert len(result["models"]) == 10 and result["acceptance_questions_per_model"] == 2
    assert result["budget"]["used"] == 0 and result["budget"]["protected_cleanup"] == 1
    assert not (tmp_path / "artifacts").exists()


def test_evaluate_needs_explicit_execution_gate_before_backend_construction(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = prepare(tmp_path, review, monkeypatch)
    state = fake_runners(tmp_path, review, monkeypatch)
    assert cli.main(args + ["evaluate", "--output", str(tmp_path / "reports")]) == 1
    assert state.calls == state.constructors == []
    assert not (tmp_path / "artifacts").exists()


def test_json_serialization_failure_does_not_leave_empty_evidence(tmp_path: Path) -> None:
    output = tmp_path / "unserializable.json"
    with pytest.raises(TypeError):
        cli._write_json_new(output, {"unsupported": object()})
    assert not output.exists()


def test_evaluate_uses_exactly_twenty_calls_and_accepts_only_after_all_judgments(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = ten_model_review(review)
    args = prepare(tmp_path, review, monkeypatch)
    state = fake_runners(tmp_path, review, monkeypatch)
    output = tmp_path / "reports"
    assert cli.main(args + ["evaluate", "--invoke-live", "--output", str(output)]) == 0
    ledger = StreamingLedger(tmp_path, review)
    accepted = json.loads((ledger.directory / "accepted.json").read_bytes())
    assert accepted["passed"] is True and accepted["questions"] == 20
    assert accepted["models"] == [target.model_key for target in review.targets]
    assert len(state.calls) == len({item[2] for item in state.calls}) == 20
    assert len(state.constructors) == 10
    reports = [json.loads(path.read_bytes()) for path in output.glob("*.json")]
    assert len(reports) == 20
    assert {report["case"] for report in reports} == {"Q18", "all-five-regionals"}
    assert all(report["judgment"]["status"] == "passed" for report in reports)
    assert ledger.summary()["used"] == 20 and ledger.summary()["protected_cleanup"] == 1
    assert ledger.summary()["incomplete"] is False
    original_reports = {path.name: path.read_bytes() for path in output.glob("*.json")}
    assert cli.main(args + ["evaluate", "--invoke-live", "--output", str(tmp_path / "retry")]) == 1
    assert len(state.calls) == 20 and ledger.summary()["used"] == 20
    assert original_reports == {path.name: path.read_bytes() for path in output.glob("*.json")}


@pytest.mark.parametrize("fault, expected_calls", [("number", 1), ("plan", 2), ("fallback", 1)])
def test_failed_value_plan_or_word_stream_stops_with_report_and_no_acceptance(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    expected_calls: int,
) -> None:
    args = prepare(tmp_path, review, monkeypatch)
    state = fake_runners(tmp_path, review, monkeypatch, fault=fault)
    output = tmp_path / "failed-reports"
    assert cli.main(args + ["evaluate", "--invoke-live", "--output", str(output)]) == 1
    ledger = StreamingLedger(tmp_path, review)
    assert len(state.calls) == expected_calls and ledger.summary()["used"] == expected_calls
    assert len(list(output.glob("*.json"))) == expected_calls
    assert not (ledger.directory / "accepted.json").exists()


@pytest.mark.parametrize(
    "fault, exit_code, error_type",
    [("exception", 1, "ConnectionError"), ("interrupt", 130, "KeyboardInterrupt")],
)
def test_invocation_failure_is_spent_once_and_never_marks_acceptance(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    exit_code: int,
    error_type: str,
) -> None:
    args = prepare(tmp_path, review, monkeypatch)
    state = fake_runners(tmp_path, review, monkeypatch, fault=fault)
    output = tmp_path / "failed"
    assert cli.main(args + ["evaluate", "--invoke-live", "--output", str(output)]) == exit_code
    ledger = StreamingLedger(tmp_path, review)
    assert len(state.calls) == 1
    assert ledger.summary()["used"] == 1 and ledger.summary()["failed"] is True
    assert ledger.summary()["incomplete"] is False
    assert not (ledger.directory / "accepted.json").exists()
    failure_reports = [json.loads(path.read_bytes()) for path in output.glob("*.json")]
    assert len(failure_reports) == 1
    failure = failure_reports[0]
    assert failure["model_key"] == "nova-lite" and failure["case"] == "Q18"
    assert failure["request_id"] == state.calls[0][2]
    assert failure["source_case_ids"] == ["Q18"] and failure["status"] == "failed"
    assert failure["error_type"] == error_type
    assert failure["operation"] == "model_acceptance"
    assert "authored offline connection failure" not in json.dumps(failure)


@pytest.mark.parametrize("version", [None, "", "null", "pending", "unknown"])
def test_binding_rejects_missing_real_upload_version_before_aws(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    version: str | None,
) -> None:
    args = prepare(tmp_path, review, monkeypatch)
    upload = tmp_path / "upload.json"
    upload.write_text(json.dumps({"VersionId": version}))
    output = tmp_path / "bound.json"
    assert (
        cli.main(
            args
            + [
                "bind-releases",
                "--read-only-aws",
                "--upload-response",
                str(upload),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists() and not (tmp_path / "artifacts").exists()


def fake_read_session(monkeypatch: pytest.MonkeyPatch, *, wrong_identity: bool = False) -> Any:
    state = SimpleNamespace(calls=[], sessions=[])

    class Client:
        def get_caller_identity(self) -> dict[str, str]:
            state.calls.append("identity")
            role = (
                "UnapprovedRole"
                if wrong_identity
                else "AWSReservedSSO_PowerUserAccess_95483085e85e3a9b"
            )
            return {
                "Account": "453711491609",
                "Arn": ("arn:aws:sts::453711491609:assumed-role/" + role + "/offline-test"),
            }

        def describe_stacks(self, *, StackName: str) -> dict[str, object]:
            state.calls.append(StackName)
            key = StackName.removeprefix("enterprise-analytics-stream-")
            arn = (
                "arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/"
                "enterprise_analytics_stream_" + key.replace("-", "_") + "-Abc123"
            )
            return {"Stacks": [{"Outputs": [{"OutputKey": "RuntimeArn", "OutputValue": arn}]}]}

        def get_agent_runtime(self, **kwargs: object) -> dict[str, str]:
            state.calls.append("runtime")
            return {"agentRuntimeVersion": "2"}

    class Session:
        def client(self, name: str, *, config: Any) -> Client:
            assert name in {"sts", "cloudformation", "bedrock-agentcore-control"}
            assert config.retries["total_max_attempts"] == 1
            return Client()

    def session(**kwargs: object) -> Session:
        assert kwargs == {"profile_name": "analytics-dev", "region_name": "us-west-2"}
        state.sessions.append(kwargs)
        return Session()

    class Reads:
        def __init__(self, *args: object) -> None:
            self.session: Any = None

        def view(self, deadline: float, label: str) -> Any:
            assert deadline > 0
            assert label in {"streaming-release-binding", "streaming-legacy-cleanup"}
            return self.session

    from enterprise_analytics_agent.adapters import operator_reads

    monkeypatch.setattr(boto3, "Session", session)
    monkeypatch.setattr(operator_reads, "ReadPool", Reads)
    return state


@pytest.mark.parametrize("failure", [None, "identity", "checkpoint"])
def test_binding_saves_actual_version_only_after_every_exact_target_is_verified(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    review = ten_model_review(review)
    args = prepare(tmp_path, review, monkeypatch)
    state = fake_read_session(monkeypatch, wrong_identity=failure == "identity")
    verified: list[str] = []

    def verify(
        session: Any,
        actual: StreamingReview,
        actual_releases: StreamingReleases,
        target: StreamTarget,
        release: StreamRelease,
    ) -> dict[str, object]:
        assert actual == review
        actual_releases.validate_review(actual)
        assert actual_releases.artifact_version_id == "returned-s3-version-7"
        assert release.runtime_version == "2"
        assert target.model_key == release.model_key
        verified.append(target.model_key)
        if failure == "checkpoint":
            raise UiError("offline exact artifact/configuration mismatch")
        return {"passed": True}

    monkeypatch.setattr(cli, "verify_target", verify)
    upload = tmp_path / "upload.json"
    upload.write_text(json.dumps({"VersionId": "returned-s3-version-7"}))
    output = tmp_path / "actual-releases.json"
    result = cli.main(
        args
        + [
            "bind-releases",
            "--read-only-aws",
            "--upload-response",
            str(upload),
            "--output",
            str(output),
        ]
    )
    assert len(state.sessions) == 1
    if failure:
        assert result == 1 and not output.exists()
        assert verified == ([] if failure == "identity" else [review.targets[0].model_key])
    else:
        assert result == 0 and len(verified) == 10
        bound = StreamingReleases.model_validate_json(output.read_bytes())
        assert bound.artifact_version_id == "returned-s3-version-7"
        assert {release.runtime_version for release in bound.models} == {"2"}
    assert StreamingLedger(tmp_path, review).summary()["used"] == 0


@pytest.mark.parametrize("scenario", ["success", "drift", "body_failure"])
def test_cleanup_uses_protected_slot_without_new_source_or_release_dependencies(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    from enterprise_analytics_agent.adapters import agentcore_invocation, ui_live, ui_release

    args = prepare(tmp_path, review, monkeypatch)
    drift = scenario == "drift"
    for path in (
        "evaluations/ui-shared/interactive-02.proposed.json",
        "artifacts/ui-shared/interactive-02-preparation/release-record.json",
    ):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((REPOSITORY / path).read_bytes())
    expected = ui_release.ReleaseRecord.model_validate_json(
        (
            tmp_path / ("artifacts/ui-shared/interactive-02-preparation/release-record.json")
        ).read_bytes()
    )
    state = fake_read_session(monkeypatch)
    monkeypatch.setattr(ui_live, "runtime_lease", lambda root: nullcontext())
    monkeypatch.setattr(
        ui_release,
        "verify_release",
        lambda *args, **kwargs: {
            "identity": {
                "Account": "453711491609",
                "Arn": (
                    "arn:aws:sts::453711491609:assumed-role/"
                    "AWSReservedSSO_PowerUserAccess_95483085e85e3a9b/offline-test"
                ),
            }
        },
    )
    monkeypatch.setattr(
        ui_release,
        "make_record",
        lambda *args, **kwargs: (
            expected.model_copy(update={"runtime_version": "14"}) if drift else expected
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_local_inputs",
        lambda *args: pytest.fail(
            "Cleanup must not depend on the new source/archive/canonical files"
        ),
    )
    (tmp_path / "releases.json").unlink()
    ledger = StreamingLedger(tmp_path, review)
    with (
        pytest.raises(ConnectionError),
        ledger.attempt(str(uuid4()), "nova-lite", mode="live") as record,
    ):
        record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
        record(
            {
                "event": "failed",
                "operation": "InvokeAgentRuntime",
                "number": 1,
                "error_type": "ConnectionError",
            }
        )
        raise ConnectionError("retained ordinary failure")
    prior = ledger.path.read_bytes()
    frozen = tmp_path / "artifacts/ui-shared/historical-ledger.jsonl"
    frozen.write_bytes(b"closed historical evidence\n")
    attempts: list[dict[str, object]] = []
    case, golden = cli.acceptance_cases(tmp_path)[0]
    body: Any = io.BytesIO(
        response(case, golden, "us.amazon.nova-lite-v1:0").model_dump_json().encode()
    )
    primary = ConnectionError("original read failure with sensitive provider detail")
    if scenario == "body_failure":

        class FailedBody:
            closed = False

            def read(self) -> bytes:
                raise primary

            def close(self) -> None:
                self.closed = True
                raise OSError("secondary cleanup failure")

        body = FailedBody()

    def invoker(*args: object, **kwargs: object) -> Any:
        def invoke(**request: object) -> Any:
            attempts.append(request)
            payload = request["payload"]
            assert isinstance(payload, bytes)
            assert json.loads(payload) == {"question": "Show net_revenue for yesterday."}
            assert json.loads(ledger.path.read_text().splitlines()[-1])["event"] == "sdk_reserved"
            return SimpleNamespace(body=body)

        return invoke

    monkeypatch.setattr(agentcore_invocation, "create_runtime_invoker", invoker)
    output = tmp_path / "cleanup.json"
    if scenario == "body_failure":
        approval = json.loads((tmp_path / "approval.json").read_bytes())
        with pytest.raises(ConnectionError) as error:
            cli._cleanup(review, approval, output)
        assert error.value is primary
        result = 1
    else:
        result = cli.main(args + ["cleanup", "--invoke-live", "--output", str(output)])
    assert len(state.sessions) == 1 and frozen.read_bytes() == b"closed historical evidence\n"
    assert ledger.path.read_bytes().startswith(prior)
    if drift:
        assert result == 1 and attempts == []
        assert ledger.summary()["used"] == 1 and ledger.summary()["protected_cleanup"] == 1
        report = json.loads(output.read_bytes())
        assert report["status"] == "failed" and report["error_type"] == "UiError"
        assert report["expected_runtime_version"] == "15"
        assert report["campaign_id"] == review.campaign_id
    elif scenario == "body_failure":
        assert result == 1 and len(attempts) == 1 and body.closed is True
        report = json.loads(output.read_bytes())
        assert report["status"] == "failed"
        assert report["operation"] == "legacy_cleanup" and report["error_type"] == "ConnectionError"
        assert report["campaign_id"] == review.campaign_id
        assert report["expected_runtime_version"] == "15"
        assert "sensitive provider detail" not in output.read_text()
        journal = [json.loads(line) for line in ledger.path.read_text().splitlines()]
        assert journal[-2]["event"] == "sdk_failed"
        assert journal[-2]["error_type"] == "ConnectionError"
        assert report["request_id"] == journal[-2]["request_id"]
        assert ledger.summary()["used"] == 2 and ledger.summary()["protected_cleanup"] == 0
        assert ledger.summary()["incomplete"] is False
    else:
        assert result == 0 and len(attempts) == 1 and body.closed is True
        report = json.loads(output.read_bytes())
        assert report["restored_runtime_version"] == "15"
        assert report["judgment"]["status"] == "passed"
        assert ledger.summary()["used"] == 2 and ledger.summary()["protected_cleanup"] == 0
        assert ledger.summary()["blocked"] is True
