"""Offline wire-protocol, fixed-target proof and operator dispatch regressions."""

import base64
import hashlib
import json
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import boto3
import pytest
from test_model_streams_review import releases, target
from test_model_streams_review import review as review

from enterprise_analytics_agent.adapters import model_stream_ui as transport
from enterprise_analytics_agent.adapters.bedrock_word_stream import StreamProtocolError
from enterprise_analytics_agent.agent.contracts import AgentDiagnostics, AgentResponse
from enterprise_analytics_agent.contracts_v2 import (
    MetricRowV2,
    QueryMetricResponseV2,
    TimeRangeV2,
)
from enterprise_analytics_agent.ui.model_streams import StreamingReview
from enterprise_analytics_agent.ui.models import AskRequest, UiError


def metric_answer() -> AgentResponse:
    return AgentResponse(
        status="answer",
        answer=("net_revenue [2025-03-31, 2025-04-01); definition 1.0.0:\ntotal: 110.25 USD"),
        results=(
            QueryMetricResponseV2(
                metric_id="net_revenue",
                definition_version="1.0.0",
                time_range=TimeRangeV2(start="2025-03-31", end="2025-04-01"),
                group_by=(),
                unit="currency",
                currency="USD",
                rows=(MetricRowV2(dimensions={}, value="110.25"),),
            ),
        ),
        dataset_version="retail-v1",
        metric_versions={"net_revenue": "1.0.0"},
        diagnostics=AgentDiagnostics(model_id="us.amazon.nova-lite-v1:0", model_calls=3),
    )


class Body:
    def __init__(self, events: list[dict[str, object]], *, truncated: bool = False) -> None:
        self.data = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)
        if truncated:
            self.data = self.data[:-1]
        self.closed = 0

    def iter_lines(self, *, chunk_size: int) -> Any:
        # Large StreamingBody reads can wait to fill their buffer, delaying words.
        assert chunk_size == 1
        return iter(self.data.splitlines())

    def close(self) -> None:
        self.closed += 1


def wire_events(response: AgentResponse | None = None) -> list[dict[str, object]]:
    response = response or metric_answer()
    return [
        {"type": "verified", "response": response.model_dump(mode="json")},
        *[
            {
                "type": "answer_delta",
                "text": response.answer[index : index + 4],
                "source": "bedrock",
                "validated": True,
            }
            for index in range(0, len(response.answer), 4)
        ],
        {
            "type": "result",
            "response": response.model_dump(mode="json"),
            "presentation_status": "streamed",
            "model_calls": [{"operation": "ConverseStream"}],
        },
    ]


@pytest.fixture(autouse=True)
def no_implicit_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("No real AWS sessions may be created by these offline tests")

    monkeypatch.setattr(boto3, "Session", forbidden)


def test_runtime_sse_stream_revalidates_typed_answer_before_publishing_words() -> None:
    body = Body(wire_events())
    published: list[dict[str, object]] = []
    result = transport.read_runtime_stream(body, target(), published.append)
    assert result.response.results[0].rows[0].value == metric_answer().results[0].rows[0].value
    assert result.response.answer == "".join(str(event["text"]) for event in published)
    assert all(
        event
        == {"type": "answer_delta", "text": event["text"], "source": "bedrock", "validated": True}
        for event in published
    )
    assert result.mode == "live" and result.presentation_status == "streamed"
    assert body.closed == 1


@pytest.mark.parametrize(
    "change",
    [
        "before_verified",
        "wrong_amount",
        "wrong_model",
        "wrong_dataset",
        "changed_final",
        "unvalidated_delta",
        "duplicate_verified",
        "after_final",
        "missing_final",
        "truncated_event",
    ],
)
def test_invalid_runtime_stream_is_closed_and_never_retried(change: str) -> None:
    events = wire_events()
    if change == "before_verified":
        events.pop(0)
    elif change == "wrong_amount":
        for event in events:
            if event["type"] == "answer_delta":
                event["text"] = "9999.99 USD"
                break
    elif change in {"wrong_model", "wrong_dataset"}:
        response = events[0]["response"]
        assert isinstance(response, dict)
        if change == "wrong_dataset":
            response["dataset_version"] = "unreviewed-retail"
        else:
            response["diagnostics"]["model_id"] = "another-model"
    elif change == "changed_final":
        response = events[-1]["response"]
        assert isinstance(response, dict)
        response["answer"] = "9999.99 USD"
    elif change == "unvalidated_delta":
        events[1]["validated"] = False
    elif change == "duplicate_verified":
        events.insert(1, deepcopy(events[0]))
    elif change == "after_final":
        events.append(
            {"type": "answer_delta", "text": "more", "validated": True, "source": "bedrock"}
        )
    elif change == "missing_final":
        events.pop()
    body = Body(events, truncated=change == "truncated_event")
    with pytest.raises((UiError, ValueError, StreamProtocolError)):
        transport.read_runtime_stream(body, target(), lambda _: None)
    assert body.closed == 1


def test_runtime_stream_closes_when_browser_callback_disconnects() -> None:
    body = Body(wire_events())

    def disconnected(_: dict[str, object]) -> None:
        raise BrokenPipeError

    with pytest.raises(BrokenPipeError):
        transport.read_runtime_stream(body, target(), disconnected)
    assert body.closed == 1


@pytest.mark.parametrize("failure", ["protocol", "callback"])
def test_body_cleanup_failure_preserves_the_original_exception(failure: str) -> None:
    primary: BaseException = (
        UiError("original protocol failure")
        if failure == "protocol"
        else BrokenPipeError("original disconnect")
    )

    class FailingCleanupBody(Body):
        def iter_lines(self, *, chunk_size: int) -> Any:
            if failure == "protocol":
                raise primary
            return super().iter_lines(chunk_size=chunk_size)

        def close(self) -> None:
            self.closed += 1
            raise OSError("secondary close failure")

    def publish(_: dict[str, object]) -> None:
        raise primary

    body = FailingCleanupBody(wire_events())
    with pytest.raises(type(primary)) as observed:
        transport.read_runtime_stream(body, target(), publish)
    assert observed.value is primary and body.closed == 1


def test_typed_prelude_cannot_replace_calculated_metric_with_different_number() -> None:
    response = metric_answer().model_copy(update={"answer": "The net revenue is 9999.99 USD."})
    body = Body(wire_events(response))
    published: list[dict[str, object]] = []
    with pytest.raises(UiError):
        transport.read_runtime_stream(body, target(), published.append)
    assert body.closed == 1 and published == []


def test_error_result_can_report_pre_planning_failure_without_fake_words() -> None:
    response = AgentResponse(
        status="error",
        answer="The request stopped safely.",
        error_code="model_error",
        dataset_version="retail-v1",
        diagnostics=AgentDiagnostics(model_id=target().settings.model_id),
    )
    body = Body(
        [
            {
                "type": "result",
                "response": response.model_dump(mode="json"),
                "presentation_status": "not_needed",
            }
        ]
    )
    result = transport.read_runtime_stream(body, target(), lambda _: pytest.fail("No fake words"))
    assert result.response.error_code == "model_error" and body.closed == 1


def aws_proof(review: StreamingReview) -> tuple[Any, Any]:
    release_set = releases(review)
    release = release_set.models[0]
    fixed = review.targets[0]
    policy: dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": transport.CALLER},
                "Action": "bedrock-agentcore:InvokeAgentRuntime",
                "Resource": release.runtime_arn,
            }
        ],
    }
    endpoint_policy = deepcopy(policy)
    endpoint_arn = release.runtime_arn + "/runtime-endpoint/DEFAULT"
    endpoint_policy["Statement"][0]["Resource"] = endpoint_arn
    role_arn = "arn:aws:iam::453711491609:role/enterprise-analytics-stream-nova-lite"
    properties: dict[str, Any] = {
        "AgentRuntimeName": fixed.runtime_name,
        "RoleArn": role_arn,
        "PlatformVersion": "AWS_LINUX_2",
        "EnvironmentVariables": {"ANALYTICS_RUNTIME_CONFIG": fixed.settings.model_dump_json()},
        "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
        "ProtocolConfiguration": "HTTP",
        "LifecycleConfiguration": {"IdleRuntimeSessionTimeout": 300, "MaxLifetime": 900},
        "AgentRuntimeArtifact": {
            "CodeConfiguration": {
                "Runtime": "PYTHON_3_12",
                "EntryPoint": ["runtime_entry.py"],
                "Code": {
                    "S3": {
                        "Bucket": transport.CODE_BUCKET,
                        "Prefix": review.artifact_key,
                        "VersionId": {"Ref": "ArtifactVersionId"},
                    }
                },
            }
        },
    }
    template = {
        "Parameters": {"ArtifactVersionId": {"Type": "String"}},
        "Resources": {
            "Runtime": {"Type": "AWS::BedrockAgentCore::Runtime", "Properties": properties},
            "RuntimePolicy": {
                "Type": "AWS::BedrockAgentCore::ResourcePolicy",
                "Properties": {"ResourceArn": release.runtime_arn, "Policy": policy},
            },
            "EndpointPolicy": {
                "Type": "AWS::BedrockAgentCore::ResourcePolicy",
                "Properties": {"ResourceArn": endpoint_arn, "Policy": endpoint_policy},
            },
        },
    }
    release = release.model_copy(
        update={
            "template_sha256": hashlib.sha256(
                json.dumps(template, sort_keys=True).encode()
            ).hexdigest()
        }
    )
    fixed = fixed.model_copy(update={"template_sha256": release.template_sha256})
    review = review.model_copy(update={"targets": (fixed,)})
    release_set = release_set.model_copy(
        update={"review_sha256": review.sha256, "models": (release,)}
    )
    runtime = {
        "agentRuntimeArn": release.runtime_arn,
        "agentRuntimeName": fixed.runtime_name,
        "status": "READY",
        "agentRuntimeVersion": release.runtime_version,
        "environmentVariables": properties["EnvironmentVariables"],
        "roleArn": role_arn,
        "platformVersion": "AWS_LINUX_2",
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 300, "maxLifetime": 900},
        "agentRuntimeArtifact": {
            "codeConfiguration": {
                "runtime": "PYTHON_3_12",
                "entryPoint": ["runtime_entry.py"],
                "code": {
                    "s3": {
                        "bucket": transport.CODE_BUCKET,
                        "prefix": review.artifact_key,
                        "versionId": release_set.artifact_version_id,
                    }
                },
            }
        },
    }
    endpoint = {
        "status": "READY",
        "liveVersion": release.runtime_version,
        "targetVersion": release.runtime_version,
        "agentRuntimeEndpointArn": endpoint_arn,
    }
    proof = SimpleNamespace(
        runtime=runtime,
        endpoint=endpoint,
        template=template,
        stack={
            "StackStatus": "UPDATE_COMPLETE",
            "Parameters": [
                {
                    "ParameterKey": "ArtifactVersionId",
                    "ParameterValue": release_set.artifact_version_id,
                }
            ],
        },
        policies={release.runtime_arn: policy, endpoint_arn: endpoint_policy},
        head={
            "VersionId": release_set.artifact_version_id,
            "ContentLength": review.artifact_bytes,
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(review.artifact_sha256)).decode(),
        },
        retention=7,
        calls=[],
    )

    class Client:
        def get_agent_runtime(self, **kwargs: object) -> Any:
            return proof.runtime

        def get_agent_runtime_endpoint(self, **kwargs: object) -> Any:
            return proof.endpoint

        def describe_stacks(self, **kwargs: object) -> Any:
            return {"Stacks": [proof.stack]}

        def get_template(self, **kwargs: object) -> Any:
            return {"TemplateBody": proof.template}

        def get_resource_policy(self, *, resourceArn: str) -> Any:
            proof.calls.append(resourceArn)
            return {"policy": proof.policies[resourceArn]}

        def head_object(self, **kwargs: object) -> Any:
            assert kwargs == {
                "Bucket": transport.CODE_BUCKET,
                "Key": review.artifact_key,
                "VersionId": release_set.artifact_version_id,
                "ChecksumMode": "ENABLED",
                "ExpectedBucketOwner": review.account,
            }
            return proof.head

        def describe_log_groups(self, *, logGroupNamePrefix: str) -> Any:
            return {
                "logGroups": [
                    {"logGroupName": logGroupNamePrefix, "retentionInDays": proof.retention}
                ]
            }

    class Session:
        def client(self, name: str, *, config: Any) -> Client:
            assert config.retries["total_max_attempts"] == 1
            return Client()

    return proof, SimpleNamespace(
        session=Session(), review=review, target=fixed, releases=release_set, release=release
    )


def test_fresh_target_proof_requires_full_code_config_template_policies_and_retention(
    review: StreamingReview,
) -> None:
    proof, binding = aws_proof(review)
    result = transport.verify_target(
        binding.session, binding.review, binding.releases, binding.target, binding.release
    )
    assert result["runtime_version"] == binding.release.runtime_version
    assert result["template_sha256"] == binding.release.template_sha256
    assert set(proof.calls) == set(proof.policies)


@pytest.mark.parametrize(
    "drift",
    [
        "version",
        "target_version",
        "artifact_version",
        "config",
        "role",
        "template",
        "policy",
        "retention",
        "checksum",
        "stack_rollback",
        "network",
        "lifecycle",
        "endpoint_identity",
        "parameters",
    ],
)
def test_ready_alone_cannot_accept_checkpoint_drift(review: StreamingReview, drift: str) -> None:
    proof, binding = aws_proof(review)
    if drift == "version":
        proof.runtime["agentRuntimeVersion"] = "999"
    elif drift == "target_version":
        proof.endpoint["targetVersion"] = "999"
    elif drift == "artifact_version":
        proof.runtime["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]["versionId"] = (
            "old"
        )
    elif drift == "config":
        proof.runtime["environmentVariables"] = {}
    elif drift == "role":
        proof.runtime["roleArn"] = "arn:aws:iam::453711491609:role/wrong"
    elif drift == "template":
        proof.template["Resources"]["Unreviewed"] = {"Type": "AWS::S3::Bucket"}
    elif drift == "policy":
        proof.policies[binding.release.runtime_arn] = {"Statement": []}
    elif drift == "retention":
        proof.retention = None
    elif drift == "checksum":
        proof.head["ChecksumSHA256"] = "wrong"
    elif drift == "stack_rollback":
        proof.stack["StackStatus"] = "UPDATE_ROLLBACK_COMPLETE"
    elif drift == "network":
        proof.runtime["networkConfiguration"] = {"networkMode": "VPC"}
    elif drift == "lifecycle":
        proof.runtime["lifecycleConfiguration"]["maxLifetime"] = 1800
    elif drift == "endpoint_identity":
        proof.endpoint["agentRuntimeEndpointArn"] += "-other"
    else:
        proof.stack["Parameters"][0]["ParameterValue"] = "unreviewed-object-version"
    with pytest.raises(UiError):
        transport.verify_target(
            binding.session, binding.review, binding.releases, binding.target, binding.release
        )


def test_actual_template_cannot_rebind_its_own_reviewed_hash(review: StreamingReview) -> None:
    proof, binding = aws_proof(review)
    proof.template["Resources"]["Unreviewed"] = {"Type": "AWS::S3::Bucket"}
    forged = binding.release.model_copy(
        update={
            "template_sha256": hashlib.sha256(
                json.dumps(proof.template, sort_keys=True).encode()
            ).hexdigest()
        }
    )
    release_set = binding.releases.model_copy(update={"models": (forged,)})
    with pytest.raises(UiError, match="template"):
        transport.verify_target(
            binding.session, binding.review, release_set, binding.target, forged
        )


@pytest.mark.parametrize("missing", ["RuntimePolicy", "EndpointPolicy"])
def test_both_resource_policies_are_required_even_when_template_digest_matches(
    review: StreamingReview, missing: str
) -> None:
    proof, binding = aws_proof(review)
    del proof.template["Resources"][missing]
    digest = hashlib.sha256(json.dumps(proof.template, sort_keys=True).encode()).hexdigest()
    fixed = binding.target.model_copy(update={"template_sha256": digest})
    reviewed = binding.review.model_copy(update={"targets": (fixed,)})
    release = binding.release.model_copy(update={"template_sha256": digest})
    release_set = binding.releases.model_copy(
        update={"review_sha256": reviewed.sha256, "models": (release,)}
    )
    with pytest.raises(UiError, match="both Runtime and DEFAULT"):
        transport.verify_target(binding.session, reviewed, release_set, fixed, release)


def test_review_and_local_input_failures_precede_session_or_billable_dispatch(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval = {
        "review_sha256": review.sha256,
        "approved": False,
        "maximum_attempts": 40,
        "expires_at": review.expires_at.isoformat(),
    }
    with pytest.raises(UiError, match="approval"):
        transport.StreamingQuestions(
            tmp_path, review, releases(review), approval, "nova-lite", tmp_path / "canonical"
        )
    approval["approved"] = True

    def stale(*args: object) -> None:
        raise UiError("The local source changed")

    monkeypatch.setattr(transport, "verify_local_inputs", stale)
    with pytest.raises(UiError, match="source changed"):
        transport.StreamingQuestions(
            tmp_path, review, releases(review), approval, "nova-lite", tmp_path / "canonical"
        )
    assert not (tmp_path / "artifacts").exists()


def test_public_status_constructs_no_sessions_or_attempts(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transport, "verify_local_inputs", lambda *args: None)
    approval = {
        "review_sha256": review.sha256,
        "approved": True,
        "maximum_attempts": 40,
        "expires_at": review.expires_at.isoformat(),
    }
    questions = transport.StreamingQuestions(
        tmp_path, review, releases(review), approval, "nova-lite", tmp_path / "canonical"
    )
    state = questions.public_state("live")
    assert state["model_id"] == "us.amazon.nova-lite-v1:0"
    assert state["word_streaming"] is True and state["enabled"] is False
    assert "acceptance" in str(state["error"])
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize("mode", ["local_agent", "live"])
def test_status_disables_accepted_target_after_local_source_changes(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setattr(transport, "verify_local_inputs", lambda *args: None)
    approval = {
        "review_sha256": review.sha256,
        "approved": True,
        "maximum_attempts": 40,
        "expires_at": review.expires_at.isoformat(),
    }
    questions = transport.StreamingQuestions(
        tmp_path, review, releases(review), approval, "nova-lite", tmp_path / "canonical"
    )
    questions.ledger.directory.mkdir(parents=True)
    (questions.ledger.directory / "accepted.json").write_text(
        json.dumps(
            {
                "review_sha256": review.sha256,
                "passed": True,
                "questions": 20,
                "models": [target.model_key for target in review.targets],
            }
        )
    )
    assert questions.public_state(mode)["enabled"] is True

    def changed(*args: object) -> None:
        raise UiError("source changed")

    monkeypatch.setattr(transport, "verify_local_inputs", changed)
    state = questions.public_state(mode)
    assert state["enabled"] is False and "source" in str(state["error"])
    assert not questions.ledger.path.exists()


def test_changed_local_inputs_are_rechecked_before_creating_any_aws_session(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(transport, "verify_local_inputs", lambda *args: None)
    approval = {
        "review_sha256": review.sha256,
        "approved": True,
        "maximum_attempts": 40,
        "expires_at": review.expires_at.isoformat(),
    }
    questions = transport.StreamingQuestions(
        tmp_path,
        review,
        releases(review),
        approval,
        "nova-lite",
        tmp_path / "canonical",
        operator=True,
    )

    def changed(*args: object) -> None:
        raise UiError("Source no longer matches the reviewed package")

    monkeypatch.setattr(transport, "verify_local_inputs", changed)
    with pytest.raises(UiError, match="no longer matches"):
        questions.ask(
            AskRequest(
                question="Show net_revenue for March 31 2025.", mode="live", request_id=uuid4()
            )
        )
    assert questions.ledger.summary()["used"] == 0


@pytest.mark.parametrize(
    "invalid", ["missing", "invalid_json", "wrong_review", "failed", "missing_model", "extra_model"]
)
def test_ui_requires_exact_deployed_acceptance_before_session_or_attempt(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(transport, "verify_local_inputs", lambda *args: None)
    approval = {
        "review_sha256": review.sha256,
        "approved": True,
        "maximum_attempts": 40,
        "expires_at": review.expires_at.isoformat(),
    }
    questions = transport.StreamingQuestions(
        tmp_path, review, releases(review), approval, "nova-lite", tmp_path / "canonical"
    )
    if invalid != "missing":
        questions.ledger.directory.mkdir(parents=True)
        acceptance: dict[str, object] = {
            "review_sha256": review.sha256,
            "passed": True,
            "models": ["nova-lite"],
        }
        if invalid == "wrong_review":
            acceptance["review_sha256"] = "f" * 64
        elif invalid == "failed":
            acceptance["passed"] = False
        elif invalid == "missing_model":
            acceptance["models"] = []
        elif invalid == "extra_model":
            acceptance["models"] = ["nova-lite", "unreviewed-model"]
        (questions.ledger.directory / "accepted.json").write_text(
            "{" if invalid == "invalid_json" else json.dumps(acceptance)
        )
    assert questions.public_state("live")["enabled"] is False
    with pytest.raises(UiError, match="acceptance"):
        questions.ask(
            AskRequest(
                question="Show net_revenue for March 31 2025.", mode="live", request_id=uuid4()
            )
        )
    assert questions.ledger.summary()["used"] == 0
    assert not questions.ledger.path.exists()


def test_exact_accepted_record_enables_status_without_dispatching(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transport, "verify_local_inputs", lambda *args: None)
    approval = {
        "review_sha256": review.sha256,
        "approved": True,
        "maximum_attempts": 40,
        "expires_at": review.expires_at.isoformat(),
    }
    questions = transport.StreamingQuestions(
        tmp_path, review, releases(review), approval, "nova-lite", tmp_path / "canonical"
    )
    questions.ledger.directory.mkdir(parents=True)
    (questions.ledger.directory / "accepted.json").write_text(
        json.dumps(
            {
                "review_sha256": review.sha256,
                "passed": True,
                "models": [fixed.model_key for fixed in review.targets],
            }
        )
    )
    assert questions.public_state("local_agent")["enabled"] is True
    assert questions.ledger.summary()["used"] == 0
    assert not questions.ledger.path.exists()


@pytest.mark.parametrize("field", ["tenant_id", "region", "authorization", "model_id", "history"])
def test_question_payload_cannot_override_identity_or_fixed_model(field: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AskRequest.model_validate(
            {
                "question": "Show net_revenue for March 31 2025.",
                "request_id": str(uuid4()),
                "mode": "live",
                field: "override",
            }
        )


def operator(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    *,
    account: str = "453711491609",
    principal: str | None = None,
    body: Body | None = None,
    failure: BaseException | None = None,
    content_type: object = "text/event-stream",
) -> tuple[transport.StreamingQuestions, Any]:
    monkeypatch.chdir(tmp_path)
    old = tmp_path / "evaluations/ui-shared/interactive-02.proposed.json"
    old.parent.mkdir(parents=True)
    source = (
        Path(__file__).resolve().parents[1] / "evaluations/ui-shared/interactive-02.proposed.json"
    )
    old.write_bytes(source.read_bytes())
    monkeypatch.setattr(transport, "verify_local_inputs", lambda *args: None)
    monkeypatch.setattr(transport, "runtime_lease", lambda root: nullcontext())
    monkeypatch.setattr(transport, "verify_target", lambda *args: {"runtime_version": "1"})
    monkeypatch.setattr(transport, "verify_publication", lambda *args, **kwargs: None)
    state = SimpleNamespace(invocations=[], sessions=[], body=body or Body(wire_events()))

    class Client:
        def get_caller_identity(self) -> dict[str, str]:
            return {
                "Account": account,
                "Arn": principal
                or (
                    "arn:aws:sts::453711491609:assumed-role/"
                    "AWSReservedSSO_PowerUserAccess_95483085e85e3a9b/offline-test"
                ),
            }

        def invoke_agent_runtime(self, **kwargs: object) -> dict[str, object]:
            state.invocations.append(kwargs)
            journal = next((tmp_path / "artifacts/bedrock-streaming").rglob("attempts.jsonl"))
            assert json.loads(journal.read_text().splitlines()[-1])["event"] == "sdk_reserved"
            if failure is not None:
                raise failure
            return {"statusCode": 200, "contentType": content_type, "response": state.body}

    class Session:
        def client(self, name: str, *, config: Any) -> Client:
            assert name in {"sts", "bedrock-agentcore"}
            assert config.retries["total_max_attempts"] == 1
            return Client()

    def session(**kwargs: object) -> Session:
        assert kwargs == {"profile_name": "analytics-dev", "region_name": "us-west-2"}
        state.sessions.append(kwargs)
        return Session()

    class Reads:
        def __init__(self, *args: object) -> None:
            self.session: Any = None

        def view(self, deadline: float, label: str) -> Session:
            assert deadline > 0 and label == "model-stream-preflight"
            return cast(Session, self.session)

    monkeypatch.setattr(boto3, "Session", session)
    monkeypatch.setattr(transport, "ReadPool", Reads)
    approval = {
        "review_sha256": review.sha256,
        "approved": True,
        "maximum_attempts": 40,
        "expires_at": review.expires_at.isoformat(),
    }
    questions = transport.StreamingQuestions(
        tmp_path,
        review,
        releases(review),
        approval,
        "nova-lite",
        tmp_path / "canonical",
        operator=True,
    )
    assert state.sessions == []
    return questions, state


def test_live_operator_dispatches_question_only_once_and_accounts_before_send(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions, state = operator(tmp_path, review, monkeypatch)
    events: list[dict[str, object]] = []
    request = AskRequest(
        question="Show net_revenue for March 31 2025.",
        mode="live",
        request_id=uuid4(),
        model_key="nova-lite",
    )
    result = questions.ask_with_events(request, events.append)
    assert result.response.answer == metric_answer().answer
    assert "".join(str(event["text"]) for event in events) == metric_answer().answer
    assert len(state.invocations) == len(state.sessions) == state.body.closed == 1
    assert json.loads(state.invocations[0]["payload"]) == {"question": request.question}
    assert state.invocations[0]["qualifier"] == "DEFAULT"
    assert questions.ledger.summary()["used"] == 1
    assert questions.ledger.summary()["incomplete"] is False
    assert list(questions.ledger.directory.glob("result-*.json"))


@pytest.mark.parametrize("content_type", [None, 7, "application/json"])
def test_invalid_runtime_mime_preserves_protocol_error_when_body_cleanup_fails(
    tmp_path: Path,
    review: StreamingReview,
    monkeypatch: pytest.MonkeyPatch,
    content_type: object,
) -> None:
    class BadClose(Body):
        def close(self) -> None:
            super().close()
            raise RuntimeError("secondary close failure")

    questions, state = operator(
        tmp_path, review, monkeypatch, body=BadClose(wire_events()), content_type=content_type
    )
    with pytest.raises(UiError, match="reviewed stream protocol"):
        questions.ask(
            AskRequest(question="Show net_revenue for yesterday.", mode="live", request_id=uuid4())
        )
    assert state.body.closed == 1 and len(state.invocations) == 1
    assert questions.ledger.summary()["used"] == 1
    assert questions.ledger.summary()["failed"] is True


@pytest.mark.parametrize("failure", ["sdk", "bad_stream", "browser_disconnect"])
def test_live_failure_is_spent_closed_and_never_automatically_retried(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    bad = wire_events()[:-1] if failure == "bad_stream" else wire_events()
    questions, state = operator(
        tmp_path,
        review,
        monkeypatch,
        body=Body(bad),
        failure=ConnectionError("offline transport failed") if failure == "sdk" else None,
    )

    def emit(_: dict[str, object]) -> None:
        if failure == "browser_disconnect":
            raise BrokenPipeError

    with pytest.raises((UiError, ConnectionError, BrokenPipeError)):
        questions.ask_with_events(
            AskRequest(
                question="Show net_revenue for March 31 2025.", mode="live", request_id=uuid4()
            ),
            emit,
        )
    summary = questions.ledger.summary()
    assert summary["used"] == 1 and summary["failed"] is True
    assert summary["incomplete"] is False
    assert len(state.invocations) == 1
    if failure != "sdk":
        assert state.body.closed == 1
    with pytest.raises(UiError):
        questions.ask_with_events(
            AskRequest(
                question="Show net_revenue for March 31 2025.", mode="live", request_id=uuid4()
            ),
            lambda _: None,
        )
    assert len(state.invocations) == 1


@pytest.mark.parametrize("identity", ["account", "caller"])
def test_wrong_identity_stops_before_attempt_reservation_and_invocation(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch, identity: str
) -> None:
    questions, state = operator(
        tmp_path,
        review,
        monkeypatch,
        account="000000000000" if identity == "account" else "453711491609",
        principal="arn:aws:sts::453711491609:assumed-role/UnapprovedRole/offline-test",
    )
    with pytest.raises(UiError):
        questions.ask(
            AskRequest(
                question="Show net_revenue for March 31 2025.", mode="live", request_id=uuid4()
            )
        )
    assert state.invocations == [] and questions.ledger.summary()["used"] == 0
