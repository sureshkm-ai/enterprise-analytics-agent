"""Opt-in Bedrock-only UI transport; no client is constructed during status/replay."""

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
from botocore.config import Config

from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
    _render,
)
from enterprise_analytics_agent.adapters.bedrock_mantle import BedrockMantleClient
from enterprise_analytics_agent.adapters.bedrock_model_catalog import get_model
from enterprise_analytics_agent.adapters.bedrock_word_stream import CanonicalWordGate
from enterprise_analytics_agent.adapters.duckdb import DuckDBSemanticAdapter
from enterprise_analytics_agent.adapters.operator_reads import ReadPool
from enterprise_analytics_agent.adapters.streaming_agent import StreamingAnalyticsAgent
from enterprise_analytics_agent.adapters.ui_live import runtime_lease
from enterprise_analytics_agent.adapters.ui_release import verify_publication
from enterprise_analytics_agent.agent.contracts import AgentRequest, AgentResponse
from enterprise_analytics_agent.ui.model_streams import (
    StreamingLedger,
    StreamingReleases,
    StreamingReview,
    StreamRelease,
    StreamTarget,
    verify_approval,
)
from enterprise_analytics_agent.ui.models import AskRequest, UiError, UiResult
from enterprise_analytics_agent.ui.shared import SharedReview

CODE_BUCKET = "enterprise-analytics-dev-453711491609-us-west-2-agent-code"
READ_CONFIG = Config(connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 1})
CALLER = (
    "arn:aws:iam::453711491609:role/aws-reserved/sso.amazonaws.com/us-west-2/"
    "AWSReservedSSO_PowerUserAccess_95483085e85e3a9b"
)


def verify_developer_identity(identity: dict[str, Any]) -> None:
    role_name = CALLER.rsplit("/", 1)[1]
    caller = identity.get("Arn", "")
    if (
        identity.get("Account") != "453711491609"
        or not isinstance(caller, str)
        or not re.fullmatch(
            rf"arn:aws:sts::453711491609:assumed-role/{re.escape(role_name)}/[^/]+", caller
        )
    ):
        raise UiError("The selected AWS account/caller differs from the approved developer role.")


def source_digest(root: Path) -> str:
    inventory = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src").rglob("*"))
        if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}
    }
    return hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()


def verify_local_inputs(root: Path, review: StreamingReview, canonical: Path) -> None:
    if source_digest(root) != review.source_sha256:
        raise UiError("Local streaming source differs from the reviewed package source.")
    archive = root / review.artifact_path
    data = archive.read_bytes()
    if (
        len(data) != review.artifact_bytes
        or hashlib.sha256(data).hexdigest() != review.artifact_sha256
    ):
        raise UiError(
            "The new streaming archive checksum/size differs; do not reuse old artifacts."
        )
    # The legacy publication verifier is data-specific; it does not authorize or
    # invoke its old Nova model. Its immutable canonical inputs are shared here.
    from enterprise_analytics_agent.adapters.retail_provenance import verify_local

    verify_local(canonical)
    manifest_hash = hashlib.sha256((canonical / "manifest.json").read_bytes()).hexdigest()
    if manifest_hash != review.canonical_manifest_sha256:
        raise UiError("The verified canonical manifest differs from the streaming review.")
    # verify_local checks the exact retained provenance inventory and source bytes;
    # the frozen manifest pin is also bound by this review schema.


def _resolve(value: Any, resources: dict[str, Any], runtime_arn: str, version: str) -> Any:
    if isinstance(value, list):
        return [_resolve(item, resources, runtime_arn, version) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"Fn::Join"}:
        separator, parts = value["Fn::Join"]
        return separator.join(
            str(_resolve(part, resources, runtime_arn, version)) for part in parts
        )
    if set(value) == {"Ref"} and value["Ref"] == "ArtifactVersionId":
        return version
    if set(value) == {"Fn::GetAtt"}:
        name, attribute = value["Fn::GetAtt"]
        resource = resources[name]
        if resource["Type"] == "AWS::BedrockAgentCore::Runtime" and attribute == "AgentRuntimeArn":
            return runtime_arn
        if resource["Type"] == "AWS::IAM::Role" and attribute == "Arn":
            return "arn:aws:iam::453711491609:role/" + resource["Properties"]["RoleName"]
        raise UiError("Unsupported reviewed CloudFormation reference.")
    if any(str(key).startswith("Fn::") or key == "Ref" for key in value):
        raise UiError("Unresolved reviewed CloudFormation value.")
    return {key: _resolve(item, resources, runtime_arn, version) for key, item in value.items()}


def verify_target(
    session: Any,
    review: StreamingReview,
    release_set: StreamingReleases,
    target: StreamTarget,
    release: StreamRelease,
) -> dict[str, object]:
    """Fresh read-only proof of exact code/configuration/template/policies, not READY alone."""
    release_set.validate_review(review)
    if target not in review.targets or release not in release_set.models:
        raise UiError("The requested target/release is outside the reviewed deployment.")
    control = session.client("bedrock-agentcore-control", config=READ_CONFIG)
    runtime_id = release.runtime_arn.rsplit("/", 1)[1]
    runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
    endpoint = control.get_agent_runtime_endpoint(agentRuntimeId=runtime_id, endpointName="DEFAULT")
    if (
        runtime.get("agentRuntimeArn") != release.runtime_arn
        or runtime.get("agentRuntimeName") != target.runtime_name
        or runtime.get("status") != "READY"
        or endpoint.get("status") != "READY"
        or runtime.get("agentRuntimeVersion") != release.runtime_version
        or endpoint.get("liveVersion") != release.runtime_version
        or endpoint.get("targetVersion", release.runtime_version) != release.runtime_version
        or endpoint.get("agentRuntimeEndpointArn")
        != release.runtime_arn + "/runtime-endpoint/DEFAULT"
    ):
        raise UiError("Streaming Runtime/DEFAULT identity, readiness or version differs.")
    if runtime.get("environmentVariables") != {
        "ANALYTICS_RUNTIME_CONFIG": target.settings.model_dump_json()
    }:
        raise UiError("The streaming runtime's fixed trusted settings differ.")
    artifact = runtime["agentRuntimeArtifact"]["codeConfiguration"]
    if artifact != {
        "runtime": "PYTHON_3_12",
        "entryPoint": ["runtime_entry.py"],
        "code": {
            "s3": {
                "bucket": CODE_BUCKET,
                "prefix": review.artifact_key,
                "versionId": release_set.artifact_version_id,
            }
        },
    }:
        raise UiError("The streaming runtime uses different code or a different S3 version.")
    cfn = session.client("cloudformation", config=READ_CONFIG)
    stack_name = "enterprise-analytics-stream-" + target.model_key
    stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    if len(stacks) != 1 or stacks[0]["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise UiError("The reviewed streaming stack is not stable.")
    template = cfn.get_template(StackName=stack_name, TemplateStage="Original")["TemplateBody"]
    if isinstance(template, str):
        template = json.loads(template)
    digest = hashlib.sha256(json.dumps(template, sort_keys=True).encode()).hexdigest()
    if digest != release.template_sha256:
        raise UiError("The actual streaming stack template differs from the reviewed release.")
    expected_parameters = {}
    for key, parameter in template.get("Parameters", {}).items():
        if key == "ArtifactVersionId":
            expected_parameters[key] = release_set.artifact_version_id
        elif "Default" in parameter:
            expected_parameters[key] = str(parameter["Default"])
        else:
            raise UiError("The reviewed template has an unbound deployment parameter.")
    actual_parameters = {
        item["ParameterKey"]: item["ParameterValue"] for item in stacks[0].get("Parameters", [])
    }
    if actual_parameters != expected_parameters:
        raise UiError("Actual CloudFormation parameters differ from the reviewed deployment.")
    resources = template["Resources"]
    properties = next(
        item["Properties"]
        for item in resources.values()
        if item["Type"] == "AWS::BedrockAgentCore::Runtime"
    )
    wanted = _resolve(properties, resources, release.runtime_arn, release_set.artifact_version_id)
    for actual, expected in (
        ("roleArn", "RoleArn"),
        ("platformVersion", "PlatformVersion"),
        ("environmentVariables", "EnvironmentVariables"),
    ):
        if runtime.get(actual) != wanted[expected]:
            raise UiError("The actual streaming runtime differs from its reviewed template.")
    if runtime.get("networkConfiguration") != {
        "networkMode": wanted["NetworkConfiguration"]["NetworkMode"]
    }:
        raise UiError("Streaming runtime networking differs from the reviewed template.")
    if runtime.get("protocolConfiguration") != {"serverProtocol": wanted["ProtocolConfiguration"]}:
        raise UiError("Streaming runtime protocol differs from the reviewed template.")
    life = wanted["LifecycleConfiguration"]
    if runtime.get("lifecycleConfiguration") != {
        "idleRuntimeSessionTimeout": life["IdleRuntimeSessionTimeout"],
        "maxLifetime": life["MaxLifetime"],
    }:
        raise UiError("Streaming runtime lifecycle differs from the reviewed template.")
    policies = [
        resource
        for resource in resources.values()
        if resource["Type"] == "AWS::BedrockAgentCore::ResourcePolicy"
    ]
    if len(policies) != 2:
        raise UiError("The reviewed runtime must prove both Runtime and DEFAULT resource policies.")
    seen_policy_arns = set()
    for resource in policies:
        if resource["Type"] != "AWS::BedrockAgentCore::ResourcePolicy":
            continue
        policy = _resolve(
            resource["Properties"], resources, release.runtime_arn, release_set.artifact_version_id
        )
        seen_policy_arns.add(policy["ResourceArn"])
        expected = (
            json.loads(policy["Policy"]) if isinstance(policy["Policy"], str) else policy["Policy"]
        )
        actual = control.get_resource_policy(resourceArn=policy["ResourceArn"])["policy"]
        actual = json.loads(actual) if isinstance(actual, str) else actual
        if actual != expected:
            raise UiError("A streaming Runtime/DEFAULT resource policy differs.")
    if seen_policy_arns != {release.runtime_arn, release.runtime_arn + "/runtime-endpoint/DEFAULT"}:
        raise UiError("Both exact streaming resource-policy identities are required.")
    head = session.client("s3", config=READ_CONFIG).head_object(
        Bucket=CODE_BUCKET,
        Key=review.artifact_key,
        VersionId=release_set.artifact_version_id,
        ChecksumMode="ENABLED",
        ExpectedBucketOwner=review.account,
    )
    if (
        head.get("VersionId") != release_set.artifact_version_id
        or head.get("ContentLength") != review.artifact_bytes
        or head.get("ChecksumSHA256")
        != base64.b64encode(bytes.fromhex(review.artifact_sha256)).decode()
    ):
        raise UiError("The version-pinned streaming S3 object checksum or size differs.")
    logs = session.client("logs", config=READ_CONFIG)
    group = f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"
    found = logs.describe_log_groups(logGroupNamePrefix=group)["logGroups"]
    if not any(
        item["logGroupName"] == group and item.get("retentionInDays") == 7 for item in found
    ):
        raise UiError("The streaming runtime does not have verified seven-day log retention.")
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "model_key": target.model_key,
        "runtime_version": release.runtime_version,
        "template_sha256": digest,
    }


def _sse(body: Any, *, maximum_bytes: int = 16 * 1024 * 1024) -> Iterator[dict[str, Any]]:
    data: list[str] = []
    size = 0
    # StreamingBody.read(large_amount) may wait to fill that amount. A one-byte
    # chunk lets iter_lines yield each SSE frame promptly, rather than buffering
    # several words/heartbeats behind an arbitrary kilobyte boundary.
    for raw in body.iter_lines(chunk_size=1):
        size += len(raw) + 1
        if size > maximum_bytes or len(raw) > 1048576:
            raise UiError("The Runtime stream exceeded its reviewed size bound.")
        line = raw.decode("utf-8", errors="strict")
        if not line:
            if data:
                value = json.loads("\n".join(data))
                if not isinstance(value, dict):
                    raise UiError("The Runtime stream contained an invalid event.")
                yield value
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not (line.startswith(":") or line.startswith("event:") or line.startswith("id:")):
            raise UiError("The Runtime stream used an unsupported event field.")
    if data:
        raise UiError("The Runtime stream ended inside an event.")


def read_runtime_stream(
    body: Any,
    target: StreamTarget,
    emit: Callable[[dict[str, object]], None],
) -> UiResult:
    verified: AgentResponse | None = None
    gate: CanonicalWordGate | None = None
    final: UiResult | None = None
    primary: BaseException | None = None

    def checked(value: object) -> AgentResponse:
        response = AgentResponse.model_validate(value)
        if (
            response.status == "answer"
            and response.results
            and response.answer != _render(list(response.results))
        ):
            raise UiError("The numeric answer differs from validated metric results.")
        return response

    try:
        for event in _sse(body):
            if final is not None:
                raise UiError("The Runtime emitted data after its final result.")
            kind = event.get("type")
            if kind == "verified" and verified is None:
                verified = checked(event["response"])
                if (
                    verified.diagnostics.model_id != target.settings.model_id
                    or verified.dataset_version != "retail-v1"
                ):
                    raise UiError("The verified Runtime answer has a different model/dataset.")
                gate = CanonicalWordGate(
                    verified.answer,
                    lambda text: emit(
                        {
                            "type": "answer_delta",
                            "text": text,
                            "source": "bedrock",
                            "validated": True,
                        }
                    ),
                )
            elif (
                kind == "answer_delta"
                and gate is not None
                and event.get("validated") is True
                and event.get("source") == "bedrock"
            ):
                if not isinstance(event.get("text"), str):
                    raise UiError("The Runtime word event is invalid.")
                gate.feed(event["text"])
            elif kind == "result":
                response = checked(event["response"])
                if (
                    response.diagnostics.model_id != target.settings.model_id
                    or response.dataset_version != "retail-v1"
                ):
                    raise UiError("The Runtime result has a different model/dataset.")
                if verified is None:
                    if response.status != "error":
                        raise UiError("The Runtime omitted its verified answer prelude.")
                elif any(
                    getattr(response, field) != getattr(verified, field)
                    for field in (
                        "answer",
                        "results",
                        "dataset_version",
                        "metric_versions",
                        "status",
                        "error_code",
                    )
                ):
                    raise UiError("The Runtime changed its verified answer after streaming.")
                status = event.get("presentation_status")
                if status == "streamed":
                    if gate is None:
                        raise UiError("The Runtime omitted verified word-stream evidence.")
                    gate.finish()
                final = UiResult(
                    mode="live",
                    response=response,
                    presentation_status=status,
                    metadata=[{"streaming_model_calls": event.get("model_calls", [])}],
                    unreported_diagnostics=("input_tokens", "output_tokens")
                    if any(
                        call.get("usage_complete") is False or call.get("event") == "failed"
                        for call in event.get("model_calls", [])
                    )
                    else (),
                )
            else:
                raise UiError("The Runtime stream contains an unexpected or unverified event.")
        if final is None:
            raise UiError("The Runtime stream ended without a validated final result.")
        return final
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            body.close()
        except BaseException:
            if primary is None:
                raise


class StreamingQuestions:
    def __init__(
        self,
        root: Path,
        review: StreamingReview,
        releases: StreamingReleases,
        approval: object,
        model_key: str,
        canonical: Path,
        *,
        operator: bool = False,
    ) -> None:
        verify_approval(review, approval, now=datetime.now(UTC))
        releases.validate_review(review)
        verify_local_inputs(root, review, canonical)
        self.root, self.review, self.releases, self.approval = (
            root.resolve(),
            review,
            releases,
            approval,
        )
        if model_key not in {target.model_key for target in review.targets}:
            raise UiError("The selected model is not included in this streaming review.")
        self.target = next(target for target in review.targets if target.model_key == model_key)
        self.release = next(
            release for release in releases.models if release.model_key == model_key
        )
        self.canonical = canonical
        self.operator = operator
        self.ledger = StreamingLedger(root, review)

    def _accepted(self) -> bool:
        path = self.ledger.directory / "accepted.json"
        if not path.is_file() or path.resolve() != path:
            return False
        try:
            value = json.loads(path.read_bytes())
        except (ValueError, OSError):
            return False
        if not isinstance(value, dict):
            return False
        return bool(
            value.get("review_sha256") == self.review.sha256
            and value.get("passed") is True
            and isinstance(value.get("models"), list)
            and all(isinstance(key, str) for key in value["models"])
            and set(value["models"]) == {target.model_key for target in self.review.targets}
            and self.target.model_key in value["models"]
        )

    def public_state(self, mode: str) -> dict[str, object]:
        state = self.ledger.summary()
        model = get_model(self.target.model_key)
        return {
            "enabled": not state["blocked"] and self._accepted(),
            "error": "The model needs its reviewed deployed acceptance gates."
            if not self._accepted()
            else "",
            "dataset": "retail-v1",
            "tenant": "retail_demo",
            "regions": ["North", "South"],
            "reference_date": "2025-04-01",
            "model_id": model.model_id,
            "runtime_version": self.release.runtime_version,
            "description": f"{model.label} · Bedrock · verified words",
            "cost_notice": (
                "BILLABLE: up to five planning calls plus one verified presentation stream."
            ),
            "word_streaming": True,
        }

    def ask(self, request: AskRequest) -> UiResult:
        return self.ask_with_events(request, lambda event: None)

    def ask_with_events(
        self,
        request: AskRequest,
        emit: Callable[[dict[str, object]], None],
    ) -> UiResult:
        if request.mode not in ("local_agent", "live") or Path.cwd().resolve() != self.root:
            raise UiError("Start the approved streaming UI from the original checkout.")
        verify_approval(self.review, self.approval, now=datetime.now(UTC))
        if not self.operator and not self._accepted():
            raise UiError("This model has not passed its deployed acceptance gates.")
        verify_local_inputs(self.root, self.review, self.canonical)
        with runtime_lease(self.root):
            pool = ReadPool(None, self.ledger.directory / "operator-reads.jsonl")
            pool.session = boto3.Session(profile_name="analytics-dev", region_name="us-west-2")
            reads = pool.view(time.monotonic() + 180, "model-stream-preflight")
            identity = reads.client("sts", config=READ_CONFIG).get_caller_identity()
            verify_developer_identity(identity)
            proof = verify_target(reads, self.review, self.releases, self.target, self.release)
            old = SharedReview.model_validate_json(
                (self.root / "evaluations/ui-shared/interactive-02.proposed.json").read_bytes()
            )
            verify_publication(old, reads, root=self.root)
            self.ledger.directory.mkdir(parents=True, exist_ok=True)
            with (self.ledger.directory / f"preflight-{request.request_id}.json").open("x") as out:
                out.write(json.dumps(proof, indent=2) + "\n")
            started = time.monotonic()
            with self.ledger.attempt(
                str(request.request_id), self.target.model_key, mode=request.mode
            ) as record:
                if request.mode == "local_agent":
                    result = self._local(pool.session, request, emit, record)
                else:
                    client = pool.session.client("bedrock-agentcore", config=READ_CONFIG)
                    record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
                    try:
                        response = client.invoke_agent_runtime(
                            agentRuntimeArn=self.release.runtime_arn,
                            qualifier="DEFAULT",
                            runtimeSessionId=str(uuid4()),
                            contentType="application/json",
                            accept="text/event-stream",
                            payload=AgentRequest(question=request.question)
                            .model_dump_json()
                            .encode(),
                        )
                        body = response["response"]
                        content_type = response.get("contentType")
                        if (
                            response.get("statusCode", 200) != 200
                            or not isinstance(content_type, str)
                            or content_type.split(";", 1)[0] != "text/event-stream"
                        ):
                            try:
                                body.close()
                            except Exception:
                                pass
                            raise UiError("Runtime did not return the reviewed stream protocol.")
                        result = read_runtime_stream(body, self.target, emit)
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
                    record({"event": "returned", "operation": "InvokeAgentRuntime", "number": 1})
                if result.presentation_status == "fallback" or result.response.status == "error":
                    record({"event": "question_failed"})
                result = result.model_copy(
                    update={"elapsed_ms": int((time.monotonic() - started) * 1000)}
                )
            with (self.ledger.directory / f"result-{request.request_id}.json").open("x") as out:
                out.write(result.model_dump_json(indent=2) + "\n")
            return result

    def _local(
        self,
        session: Any,
        request: AskRequest,
        emit: Callable[[dict[str, object]], None],
        record: Callable[[dict[str, object]], None],
    ) -> UiResult:
        model = get_model(self.target.model_key)
        client = (
            BedrockMantleClient(session=session)
            if model.transport == "mantle_chat"
            else session.client("bedrock-runtime", config=READ_CONFIG)
        )
        settings = self.target.settings
        with DuckDBSemanticAdapter(self.canonical) as adapter:
            agent = BedrockAnalyticsAgent(
                BedrockAgentConfig(
                    model_id=settings.model_id,
                    reference_date=settings.reference_date,
                    max_iterations=5,
                    max_tool_calls=settings.max_tool_calls,
                    max_output_tokens=settings.max_output_tokens,
                    max_total_tokens=settings.max_total_tokens,
                    timeout_seconds=settings.timeout_seconds,
                ),
                client=client,
                adapter=adapter,
                dataset_version="retail-v1",
            )
            outcome = StreamingAnalyticsAgent(
                agent,
                presentation_client=client,
                allow_temperature=model.temperature_supported,
                planner_operation="ChatCompletions"
                if model.transport == "mantle_chat"
                else "Converse",
                presentation_operation="ChatCompletionsStream"
                if model.transport == "mantle_chat"
                else "ConverseStream",
            ).run(
                AgentRequest(question=request.question),
                context=settings.authorization_context(),
                on_word=lambda text: emit(
                    {"type": "answer_delta", "text": text, "source": "bedrock", "validated": True}
                ),
                record=record,
            )
        missing = (
            ("input_tokens", "output_tokens")
            if any(call["status"] == "failed" for call in outcome.calls)
            else ()
        )
        return UiResult(
            mode="local_agent",
            response=outcome.response,
            presentation_status=outcome.presentation,
            unreported_diagnostics=missing,
            metadata=[{"streaming_model_calls": list(outcome.calls)}],
        )
