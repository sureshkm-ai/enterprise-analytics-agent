"""AWS timestamp evidence must survive the complete evaluator command without AWS calls."""

import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from enterprise_analytics_agent.agent.contracts import (
    AgentDiagnostics,
    AgentRequest,
    AgentResponse,
    ToolCallRecord,
)
from enterprise_analytics_agent.retail_evaluation.campaign import CampaignLedger
from enterprise_analytics_agent.retail_evaluation.cases import load_goldens, load_suite
from enterprise_analytics_agent.retail_evaluation.client import RuntimeInvoker, RuntimeReply
from enterprise_analytics_agent.retail_evaluation.models import GoldenCase, RetailCase, RetailTarget
from enterprise_analytics_agent.retail_evaluation.reporting import (
    prepare_run_directory,
    write_run_context,
)
from enterprise_analytics_agent.retail_evaluation.runner import main

EVIDENCE = Path(__file__).resolve().parents[1] / "evaluations/retail-v1"
CREATED = datetime(2026, 11, 8, 19, 47, 45, 123456, tzinfo=UTC)
UPDATED = datetime(2026, 11, 8, 14, 53, 2, 654321, tzinfo=timezone(timedelta(hours=-6)))
LAST_MODIFIED = datetime(2026, 11, 8, 23, 50, 6, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def authored_response(case: RetailCase, golden: GoldenCase) -> AgentResponse:
    """Use already-frozen literals to test transport/reporting, never model answer quality."""
    clarification = case.kind == "clarification" or case.id == "Q30"
    calls = tuple(
        ToolCallRecord(
            tool_use_id=f"{case.id}-{index}",
            name="query_metric",
            status="success",
            arguments=query.model_dump(mode="json"),
        )
        for index, query in enumerate(case.expected_queries)
    )
    if case.kind == "metadata":
        assert case.operation is not None
        calls = (
            ToolCallRecord(
                tool_use_id=f"{case.id}-metadata",
                name=case.operation,
                status="success",
                arguments={
                    "api_version": "v2",
                    **({"metric_id": case.metric_id} if case.metric_id else {}),
                },
            ),
        )
    return AgentResponse(
        status="clarification" if clarification else "answer",
        answer="Authored offline response for command-path verification.",
        results=golden.results,
        dataset_version="retail-v1",
        metric_versions={result.metric_id: result.definition_version for result in golden.results},
        diagnostics=AgentDiagnostics(
            model_id="us.amazon.nova-lite-v1:0",
            configuration={"reference_date": "2025-04-01"},
            model_calls=0 if clarification else 2,
            input_tokens=0 if clarification else 10,
            output_tokens=0 if clarification else 5,
            latency_ms=0 if clarification else 80,
            tool_calls=calls,
            athena=tuple(
                {
                    "query_id": f"{case.id}-query-{index}",
                    "operation": "query_metric",
                    "metric_id": query.metric_id,
                    "dataset_version": "retail-v1",
                    "state": "SUCCEEDED",
                    "scanned_bytes": 1024,
                }
                for index, query in enumerate(case.expected_queries)
            ),
        ),
    )


@dataclass
class MockedCampaign:
    ledger: CampaignLedger
    checkpoint: dict[str, Any]
    report_dir: Path
    calls: list[tuple[str, str]]
    arguments: list[str]
    target: RetailTarget


@pytest.fixture
def mocked_campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MockedCampaign:
    suite = load_suite(EVIDENCE / "questions.json")
    goldens = load_goldens(EVIDENCE / "expected-results.json", suite)
    target = RetailTarget.model_validate_json((EVIDENCE / "target.json").read_text())
    ledger = CampaignLedger(tmp_path / "campaign.jsonl")
    report_dir = tmp_path / "report"
    checkpoint: dict[str, Any] = {
        "runtime": {
            "agentRuntimeArn": target.runtime_arn,
            "status": "READY",
            "agentRuntimeVersion": "5",
            "createdAt": CREATED,
            "lastUpdatedAt": UPDATED,
        },
        "endpoint": {
            "status": "READY",
            "liveVersion": "5",
            "createdAt": CREATED,
            "lastUpdatedAt": UPDATED,
        },
        "artifact_head": {
            "LastModified": LAST_MODIFIED,
            "ResponseMetadata": {"HTTPHeaders": {"authorization": "signed-secret"}},
        },
        "nested": [
            {"history": (CREATED, UPDATED)},
            {"credentials": {"secret": "credential-secret"}},
        ],
    }
    calls: list[tuple[str, str]] = []
    cases = iter(zip(suite.cases, goldens.cases, strict=True))

    def invoke(*, payload: bytes, session_id: str) -> RuntimeReply:
        case, golden = next(cases)
        # This is the real CountedAgentClient's boundary: context is durable and the
        # reservation must already exist before the fake HTTP dispatch is reached.
        assert (report_dir / "run-context.json").is_file()
        assert ledger.summary()["used"] == len(calls) + 1
        assert ledger.summary()["completed"] == len(calls)
        request = AgentRequest.model_validate_json(payload)
        assert request.question == case.question
        assert set(json.loads(payload)) == {"question"}
        calls.append((case.id, session_id))
        response = authored_response(case, golden)
        return RuntimeReply(io.BytesIO(response.model_dump_json().encode()), f"fake-{case.id}")

    def factory(selected: RetailTarget) -> RuntimeInvoker:
        assert selected == target
        return invoke

    def checkpoint_reader(*, scope: str) -> dict[str, Any]:
        assert scope == "retail-v1"
        return checkpoint

    def forbid_aws(*args: object, **kwargs: object) -> Any:
        raise AssertionError("This regression must not construct an AWS session")

    monkeypatch.setattr("boto3.Session", forbid_aws)
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.retail_checkpoint.verify_checkpoint", checkpoint_reader
    )
    monkeypatch.setattr(
        "enterprise_analytics_agent.adapters.agentcore_invocation.create_runtime_invoker", factory
    )
    monkeypatch.setattr(
        "enterprise_analytics_agent.retail_evaluation.campaign.CampaignLedger", lambda: ledger
    )
    arguments = [
        "--invoke-live",
        "--questions",
        str(EVIDENCE / "questions.json"),
        "--expected",
        str(EVIDENCE / "expected-results.json"),
        "--provenance",
        str(EVIDENCE / "oracle-provenance.json"),
        "--target-config",
        str(EVIDENCE / "target.json"),
        "--report-dir",
        str(report_dir),
        "--run-id",
        "mocked-command-timestamps",
    ]
    return MockedCampaign(ledger, checkpoint, report_dir, calls, arguments, target)


def assert_timestamps_and_redaction(checkpoint: dict[str, Any]) -> None:
    for name in ("runtime", "endpoint"):
        assert datetime.fromisoformat(checkpoint[name]["createdAt"]) == CREATED
        assert datetime.fromisoformat(checkpoint[name]["lastUpdatedAt"]) == UPDATED
        assert checkpoint[name]["lastUpdatedAt"].endswith("-06:00")
        assert ".654321" in checkpoint[name]["lastUpdatedAt"]
    assert datetime.fromisoformat(checkpoint["artifact_head"]["LastModified"]) == LAST_MODIFIED
    assert checkpoint["artifact_head"]["LastModified"].endswith("+05:30")
    assert checkpoint["artifact_head"]["ResponseMetadata"] == "[redacted]"
    assert [datetime.fromisoformat(value) for value in checkpoint["nested"][0]["history"]] == [
        CREATED,
        UPDATED,
    ]
    assert checkpoint["nested"][1]["credentials"] == "[redacted]"


def test_live_command_serializes_aws_timestamps_then_dispatches_shared_session_pair(
    mocked_campaign: MockedCampaign,
) -> None:
    campaign = mocked_campaign
    assert main(campaign.arguments) == 0
    context = json.loads((campaign.report_dir / "run-context.json").read_text())
    report = json.loads((campaign.report_dir / "report.json").read_text())
    assert_timestamps_and_redaction(context["evidence"]["checkpoint"])
    assert_timestamps_and_redaction(report["evidence"]["checkpoint"])
    assert context["mode"] == report["mode"] == "live"
    assert context["run_id"] == report["run_id"] == "mocked-command-timestamps"
    assert context["evidence"]["campaign_before"]["used"] == 0
    assert report["summary"]["passed"] == 36 and report["summary"]["live_gates_passed"] is True
    assert report["campaign"]["used"] == report["campaign"]["completed"] == 36
    assert campaign.ledger.summary()["used"] == campaign.ledger.summary()["completed"] == 36
    records = [json.loads(line) for line in campaign.ledger.path.read_text().splitlines()]
    assert len(records) == 72
    reserved, outcomes = records[::2], records[1::2]
    assert all(record["event"] == "reserved" for record in reserved)
    assert all(record["event"] == "outcome" for record in outcomes)
    assert [record["number"] for record in reserved] == list(range(1, 37))
    assert [record["reservation_id"] for record in reserved] == [
        record["reservation_id"] for record in outcomes
    ]
    sessions = dict(campaign.calls)
    assert sessions["S01A"] == sessions["S01B"]
    assert len(set(sessions.values())) == 35
    assert sessions["S01A"] not in {
        session for case, session in campaign.calls if case.startswith("Q")
    }
    assert [record["session_id"] for record in reserved] == [
        session for _, session in campaign.calls
    ]
    assert len((campaign.report_dir / "attempts.jsonl").read_text().splitlines()) == 36
    # Normalization/redaction must not mutate the source evidence supplied by AWS.
    assert campaign.checkpoint["runtime"]["createdAt"] is CREATED
    assert (
        campaign.checkpoint["artifact_head"]["ResponseMetadata"]["HTTPHeaders"]["authorization"]
        == "signed-secret"
    )


def test_serialization_failure_dispatches_nothing_and_leaves_no_context_file(
    mocked_campaign: MockedCampaign,
) -> None:
    campaign = mocked_campaign
    campaign.checkpoint["runtime"]["unsupported"] = object()
    assert main(campaign.arguments) == 1
    assert campaign.calls == [] and campaign.ledger.summary()["used"] == 0
    assert not campaign.ledger.path.exists()
    assert not (campaign.report_dir / "run-context.json").exists()
    assert not (campaign.report_dir / "report.json").exists()
    assert not (campaign.report_dir / "attempts.jsonl").exists()


def test_context_serialization_is_explicit_and_redacts_before_encoding(tmp_path: Path) -> None:
    directory = tmp_path / "unit-context"
    prepare_run_directory(directory)
    target = RetailTarget.model_validate_json((EVIDENCE / "target.json").read_text())
    write_run_context(
        directory,
        target,
        {
            "nested": ({"timestamp": UPDATED},),
            "credentials": {"not_json": object()},
            "sql": "SELECT secret FROM private",
        },
        run_id="timestamp-unit",
        mode="replay",
    )
    body = json.loads((directory / "run-context.json").read_text())
    assert body["evidence"]["nested"] == [{"timestamp": UPDATED.isoformat()}]
    assert body["evidence"]["credentials"] == body["evidence"]["sql"] == "[redacted]"


def test_unsupported_context_value_raises_before_file_creation(tmp_path: Path) -> None:
    directory = tmp_path / "bad-context"
    prepare_run_directory(directory)
    target = RetailTarget.model_validate_json((EVIDENCE / "target.json").read_text())
    with pytest.raises(TypeError):
        write_run_context(directory, target, {"bad": object()}, run_id="bad", mode="replay")
    assert not (directory / "run-context.json").exists()
