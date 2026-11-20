"""Requested models use distinct identities, bounded AWS transports and exact grants."""

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import boto3
import pytest
from aws_cdk import App, Environment
from aws_cdk.assertions import Template
from botocore.exceptions import ClientError
from pydantic import ValidationError
from test_bedrock_mantle import Session, Transport, reply, request, response, signature, tool_config
from test_model_streams_review import settings

from enterprise_analytics_agent.adapters.bedrock_agent import (
    BedrockAgentConfig,
    BedrockAnalyticsAgent,
)
from enterprise_analytics_agent.adapters.bedrock_model_catalog import get_model, model_catalog
from enterprise_analytics_agent.adapters.bedrock_runtime_chat import (
    BedrockRuntimeChatClient,
    RuntimeChatError,
)
from enterprise_analytics_agent.adapters.streaming_diagnostics import report_aws_failure
from enterprise_analytics_agent.hosting import streaming_server
from enterprise_analytics_agent.ui.model_streams import StreamingLedger, StreamingReview
from infrastructure.agentcore.prepare_workbench_models import (
    BASELINE,
    SELECTION,
    ModelSelection,
    configuration,
    permission_additions,
    prepare,
    verify_archive,
)
from infrastructure.cdk.streaming_app import (
    ACCOUNT,
    PREFIX,
    REGION,
    StreamingDeploymentConfig,
    StreamingRuntimeStack,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6-v1",
    "gemma-3-12b": "google.gemma-3-12b-it",
    "nemotron-3-super": "nvidia.nemotron-super-3-120b",
    "qwen3-vl-235b": "qwen.qwen3-vl-235b-a22b",
    "kimi-k3": "us.moonshotai.kimi-k3",
    "deepseek-v3-2": "deepseek.v3.2",
}


@pytest.fixture(autouse=True)
def no_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(boto3, "Session", Mock(side_effect=AssertionError("No AWS in model tests")))


@pytest.mark.parametrize("key,identifier", EXPECTED.items())
def test_requested_models_have_exact_ids_and_a_single_ui_choice(key: str, identifier: str) -> None:
    assert get_model(key).model_id == identifier
    assert sum(model.model_id == identifier for model in model_catalog()) == 1
    assert get_model(key).label


def test_requested_versions_do_not_inherit_failed_historical_aliases() -> None:
    assert get_model("claude-sonnet-4-6").model_id != get_model("claude-sonnet-5-5").model_id
    assert get_model("claude-opus-4-6").model_id != get_model("claude-opus-5-5").model_id
    assert get_model("gemma-3-12b").transport == "converse"
    assert get_model("gemma-4-31b").transport == "mantle_chat"
    assert get_model("qwen3-vl-235b").model_id != get_model("qwen3-235b").model_id


@pytest.mark.parametrize("key", EXPECTED)
def test_hosted_factory_keeps_shared_agent_and_uses_correct_transport(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = get_model(key)
    configured = settings().model_copy(update={"model_id": model.model_id})
    native = Mock()
    shared = BedrockAnalyticsAgent(
        BedrockAgentConfig(model_id=model.model_id, reference_date=configured.reference_date),
        client=native,
        adapter=Mock(),
        dataset_version="retail-v1",
    )
    build, workload, chat = Mock(return_value=shared), Mock(), Mock()
    monkeypatch.setattr(streaming_server, "build_agent", build)
    monkeypatch.setattr(streaming_server, "workload_session", workload)
    monkeypatch.setattr(streaming_server, "BedrockRuntimeChatClient", chat)
    runner = streaming_server.build_streaming_agent(configured)
    assert runner.agent is shared and runner.readable is True
    if key in {"kimi-k3", "nemotron-3-super"}:
        chat.assert_called_once_with(
            model_key=key, session=workload.return_value, timeout_seconds=90
        )
        assert runner.presentation_client is chat.return_value
        assert runner.planner_operation == "ChatCompletions"
        assert runner.presentation_operation == "ChatCompletionsStream"
    else:
        chat.assert_not_called()
        workload.assert_not_called()
        assert runner.presentation_client is native
        assert runner.planner_operation == "Converse"


@pytest.mark.parametrize("key", ["kimi-k3", "nemotron-3-super"])
def test_runtime_chat_signs_bedrock_target_and_disables_reasoning_on_each_turn(key: str) -> None:
    model = get_model(key)
    session = Session()
    raw = {**reply(), "model": model.model_resource_ids[0]}
    transport = Transport(response(json.dumps(raw).encode()), response(json.dumps(raw).encode()))
    client = BedrockRuntimeChatClient(model_key=key, session=session, transport=transport)
    assert session.calls == 0
    query = {**request(), "modelId": model.model_id, "toolConfig": tool_config()}
    assert client.converse(**query)["stopReason"] == "end_turn"
    client.converse(**query)
    assert session.calls == len(transport.requests) == 2
    for sent in transport.requests:
        assert (
            sent.url == "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1/chat/completions"
        )
        assert "/us-west-2/bedrock/aws4_request" in signature(sent)
        payload = json.loads(cast(bytes, sent.body))
        assert payload["model"] == model.model_id
        assert payload["reasoning_effort"] == "none"
        assert payload["max_tokens"] == 512
        assert payload["parallel_tool_calls"] is False
        assert payload["tools"][0]["function"]["name"] == "query_metric"


def chat_stream(*, model: str = "moonshotai.kimi-k3", done: bool = True) -> bytes:
    chunks: list[dict[str, Any]] = [
        {"model": model, "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
        {"model": model, "choices": [{"index": 0, "delta": {"reasoning_content": "PRIVATE"}}]},
        {
            "model": model,
            "choices": [{"index": 0, "delta": {"content": "Net revenue: 110.25 USD"}}],
        },
        {"model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {
            "model": model,
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    ]
    return b"".join(b"data: " + json.dumps(chunk).encode() + b"\n\n" for chunk in chunks) + (
        b"data: [DONE]\n\n" if done else b""
    )


def test_runtime_chat_stream_preserves_words_usage_and_closes_without_reasoning_leak() -> None:
    raw = response(chat_stream(), stream=True)
    transport = Transport(raw)
    client = BedrockRuntimeChatClient(model_key="kimi-k3", session=Session(), transport=transport)
    result = client.converse_stream(**{**request(), "modelId": EXPECTED["kimi-k3"]})
    events = list(cast(Any, result["stream"]))
    assert "PRIVATE" not in json.dumps(events)
    assert events[-1] == {
        "metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}}
    }
    assert raw.raw.closed == 1 and len(transport.requests) == 1
    payload = json.loads(cast(bytes, transport.requests[0].body))
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["reasoning_effort"] == "none"


@pytest.mark.parametrize("change", ["wrong_model", "truncated", "http_denial", "invalid_request"])
def test_runtime_chat_failure_is_closed_and_never_retried(change: str) -> None:
    raw = response(
        chat_stream(
            model="wrong" if change == "wrong_model" else "moonshotai.kimi-k3",
            done=change != "truncated",
        ),
        stream=True,
    )
    if change == "http_denial":
        raw = response(
            b'{"error":{"code":"AccessDeniedException","message":"Denied; token=PRIVATE"}}',
            status=403,
        )
        raw.headers["x-amzn-requestid"] = "aws-chat-request-123"
    transport, session = Transport(raw), Session()
    client = BedrockRuntimeChatClient(model_key="kimi-k3", session=session, transport=transport)
    query = {
        **request(),
        "modelId": "unconfigured" if change == "invalid_request" else EXPECTED["kimi-k3"],
    }
    with pytest.raises((RuntimeChatError, ClientError)) as error:
        result = client.converse_stream(**query)
        list(cast(Any, result["stream"]))
    if change == "invalid_request":
        assert session.calls == len(transport.requests) == 0
    else:
        assert len(transport.requests) == raw.raw.closed == 1
    if change == "http_denial":
        diagnostics: list[dict[str, object]] = []
        report_aws_failure(
            error.value, operation="ChatCompletionsStream", number=1, diagnostic=diagnostics.append
        )
        assert "PRIVATE" not in json.dumps(diagnostics)
        assert diagnostics[0]["aws_error"] == {
            "Code": "AccessDeniedException",
            "Message": "Denied; token=[redacted]",
            "RequestId": "aws-chat-request-123",
            "HTTPStatusCode": 403,
        }


def selected_config() -> tuple[StreamingDeploymentConfig, StreamingDeploymentConfig]:
    baseline = StreamingDeploymentConfig.model_validate_json((ROOT / BASELINE).read_bytes())
    selection = ModelSelection.model_validate_json((ROOT / SELECTION).read_bytes())
    assert selection.requested_models == tuple(EXPECTED)
    candidate = configuration(baseline, selection, "a" * 64)
    return baseline, candidate


def test_synthesis_covers_all_requested_models_and_keeps_permissions_scoped(tmp_path: Path) -> None:
    baseline, config = selected_config()
    assert len(config.models) == 10
    assert config.artifact_version_id is None
    assert config.retained_artifact_keys == (baseline.artifact_key,)
    app = App(outdir=str(tmp_path / "assembly"), analytics_reporting=False)
    stacks = []
    for model in config.models:
        stack = StreamingRuntimeStack(
            app,
            f"{PREFIX}-{model.key}",
            config=config,
            model=model,
            env=Environment(account=ACCOUNT, region=REGION),
            allow_unbound_artifact=True,
        )
        stacks.append(stack)
    app.synth()
    for model, stack in zip(config.models, stacks, strict=True):
        template = Template.from_stack(stack).to_json()
        resource = template["Resources"]["StreamingRuntime"]["Properties"]
        assert (
            json.loads(resource["EnvironmentVariables"]["ANALYTICS_RUNTIME_CONFIG"])["model_id"]
            == model.settings.model_id
        )
        statements = [
            statement
            for value in template["Resources"].values()
            if value["Type"] == "AWS::IAM::Policy"
            for statement in value["Properties"]["PolicyDocument"]["Statement"]
        ]
        grant = next(s for s in statements if "bedrock:InvokeModel" in s["Action"])
        resources = grant["Resource"]
        assert set(resources if isinstance(resources, list) else [resources]) == set(
            model.model_resource_arns
        )
        assert "bedrock:InvokeModelWithResponseStream" in grant["Action"]
        assert not any("bedrock-mantle" in json.dumps(s) for s in statements)
        assert len(model.model_resource_arns) == (
            4 if model.settings.model_id.startswith("us.") else 1
        )
        assert model.settings.tenant_id == "retail_demo" and model.settings.allowed_regions == (
            "North",
            "South",
        )
    additions = permission_additions(ROOT, baseline, config)
    trust = additions["query_role_trust_additions"]["Statement"][0]["Principal"]["AWS"]
    assert len(trust) == 6 and all("deepseek" not in arn for arn in trust)
    assert all("*" not in arn for arn in trust)
    grants = additions["cloudformation_execution_additions"]["Statement"]
    assert len(grants) == 6
    assert all(s["Resource"] != "*" for s in grants)
    tag = next(s for s in grants if s["Sid"].endswith("TagAutomaticStreamingWorkloadIdentities"))
    assert tag["Condition"]["StringEquals"]["aws:RequestTag/Project"] == PREFIX


def test_selection_rejects_duplicate_deepseek_and_unknown_browser_model_id() -> None:
    raw = json.loads((ROOT / SELECTION).read_bytes())
    raw["retained_models"] = ["deepseek-v3-2"]
    with pytest.raises(ValidationError, match="distinct"):
        ModelSelection.model_validate(raw)
    raw["retained_models"] = ["https://other-provider.invalid"]
    with pytest.raises(ValidationError, match="catalog"):
        ModelSelection.model_validate(raw)


def test_historical_reviews_and_allowances_are_not_rewritten_or_implicitly_recovered(
    tmp_path: Path,
) -> None:
    path = ROOT / "evaluations/bedrock-streaming/review.workbench.proposed.json"
    review = StreamingReview.model_validate_json(path.read_bytes())
    assert review.sha256 == "c17f1bb9a7c3a29620c42bcf1a0217298a2fd6b0d473b9fcce7608ca90d247b3"
    assert "recover_requests" not in review.model_dump(mode="json")
    assert StreamingLedger(tmp_path, review).recover_requests is False
    fresh = StreamingReview.model_validate({**review.model_dump(), "recover_requests": True})
    assert StreamingLedger(tmp_path, fresh).recover_requests is True
    assert fresh.sha256 != review.sha256


def test_stale_archive_and_expired_or_reused_review_fail_before_preparation(tmp_path: Path) -> None:
    artifact = tmp_path / "agent.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("enterprise_analytics_agent/not-current.py", "stale")
    (tmp_path / "poetry.lock").write_text("locked")
    artifact.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "zip_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "zipped_bytes": artifact.stat().st_size,
                "poetry_lock_sha256": hashlib.sha256(b"locked").hexdigest(),
            }
        )
    )
    with pytest.raises(ValueError, match="inventory"):
        verify_archive(tmp_path, artifact)
    with pytest.raises(ValueError, match="future expiry"):
        prepare(
            ROOT,
            ROOT / "candidate.zip",
            ROOT / "artifacts/unused-model-proposal",
            campaign_id="bedrock-stream-new",
            expires_at=datetime(2026, 11, 15, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="historical campaign"):
        prepare(
            ROOT,
            ROOT / "candidate.zip",
            ROOT / "artifacts/unused-model-proposal",
            campaign_id="bedrock-stream-workbench-v1-01",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
