"""Independent model acceptance never reopens old budgets or retries failed calls."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_model_stream_cli import fake_runners, prepare, release_set, ten_model_review
from test_model_stream_cli import (
    no_real_aws_or_generated_artifacts as no_real_aws_or_generated_artifacts,
)
from test_model_streams_review import review as review
from test_model_streams_review import sdk

from enterprise_analytics_agent.adapters import model_stream_cli as cli
from enterprise_analytics_agent.adapters import model_stream_ui as ui
from enterprise_analytics_agent.ui.model_streams import StreamingLedger, StreamingReview
from enterprise_analytics_agent.ui.models import UiError


def workbench(review: StreamingReview) -> StreamingReview:
    payload = ten_model_review(review).model_dump(mode="json")
    payload.update(schema_version="bedrock-model-workbench-v1", parent=None)
    payload["targets"] = payload["targets"][:2]
    return StreamingReview.model_validate(payload)


def test_completed_failure_quarantines_one_model_and_preserves_spent_attempts(
    tmp_path: Path, review: StreamingReview
) -> None:
    current = workbench(review)
    ledger = StreamingLedger(tmp_path, current)
    with ledger.attempt(str(uuid4()), "nova-lite", mode="live") as record:
        sdk(record, "InvokeAgentRuntime", 1, failure=True)
    state = ledger.summary()
    assert state["failed"] and not state["blocked"] and state["used"] == 1
    assert state["blocked_models"] == ["nova-lite"]
    with pytest.raises(UiError, match="closed"):
        with ledger.attempt(str(uuid4()), "nova-lite", mode="local_agent"):
            pytest.fail("A failed model must not be retried in another mode")
    with ledger.attempt(str(uuid4()), current.targets[1].model_key, mode="live") as record:
        sdk(record, "InvokeAgentRuntime", 1)
    assert ledger.summary()["used"] == 2


def test_historical_reviews_keep_global_failure_and_reject_testing(
    tmp_path: Path, review: StreamingReview
) -> None:
    ledger = StreamingLedger(tmp_path, review)
    with ledger.attempt(str(uuid4()), "nova-lite", mode="live") as record:
        sdk(record, "InvokeAgentRuntime", 1, failure=True)
    assert ledger.summary()["blocked"]
    with pytest.raises(UiError, match="historical"):
        ui.StreamingQuestions(
            tmp_path, review, release_set(review), {}, "nova-lite", tmp_path, model_testing=True
        )


def test_incomplete_sdk_accounting_still_blocks_all_models(
    tmp_path: Path, review: StreamingReview
) -> None:
    current = workbench(review)
    ledger = StreamingLedger(tmp_path, current)
    with ledger.attempt(str(uuid4()), "nova-lite", mode="live") as record:
        record({"event": "reserved", "operation": "InvokeAgentRuntime", "number": 1})
    state = ledger.summary()
    assert state["incomplete"] and state["blocked"]
    with pytest.raises(UiError, match="closed"):
        with ledger.attempt(str(uuid4()), current.targets[1].model_key, mode="live"):
            pytest.fail("Incomplete accounting must prevent another model dispatch")


def test_testing_requires_exact_fresh_approval_and_status_makes_no_calls(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = workbench(review)
    monkeypatch.setattr(ui, "verify_local_inputs", lambda *args: None)
    approval = {
        "review_sha256": current.sha256,
        "approved": True,
        "maximum_attempts": 40,
        "expires_at": current.expires_at.isoformat(),
    }
    with pytest.raises(UiError, match="approval"):
        ui.StreamingQuestions(
            tmp_path,
            current,
            release_set(current),
            {**approval, "approved": False},
            "nova-lite",
            tmp_path,
            model_testing=True,
        )
    runner = ui.StreamingQuestions(
        tmp_path,
        current,
        release_set(current),
        approval,
        "nova-lite",
        tmp_path,
        model_testing=True,
    )
    state = runner.public_state("live")
    assert state["enabled"] and state["acceptance_status"] == "testing"
    assert not runner.ledger.directory.exists()
    normal = ui.StreamingQuestions(
        tmp_path, current, release_set(current), approval, "nova-lite", tmp_path
    )
    assert not normal.public_state("live")["enabled"]
    acceptance = runner.ledger.directory / "acceptance" / "nova-lite.json"
    acceptance.parent.mkdir(parents=True)
    acceptance.write_text(json.dumps({"passed": False, "review_sha256": current.sha256}))
    assert not runner.public_state("live")["enabled"]


def test_selected_acceptance_claim_is_immutable_and_other_model_is_independent(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = workbench(review)
    args = prepare(tmp_path, current, monkeypatch)
    state = fake_runners(tmp_path, current, monkeypatch)
    command = [
        *args,
        "evaluate",
        "--invoke-live",
        "--model",
        "nova-lite",
        "--output",
        str(tmp_path / "first"),
    ]
    assert cli.main(command) == 0
    assert len(state.calls) == 2
    assert cli.main(command) != 0
    assert len(state.calls) == 2
    assert (
        cli.main(
            [
                *args,
                "evaluate",
                "--invoke-live",
                "--model",
                current.targets[1].model_key,
                "--output",
                str(tmp_path / "second"),
            ]
        )
        == 0
    )
    assert len(state.calls) == 4
    ledger = StreamingLedger(tmp_path, current)
    assert ledger.summary()["used"] == 4
    assert not (ledger.directory / "accepted.json").exists()
    for target in current.targets:
        record = json.loads(
            (ledger.directory / "acceptance" / f"{target.model_key}.json").read_bytes()
        )
        assert record["passed"] and record["cases"] == ["Q18", "all-five-regionals"]


@pytest.mark.parametrize("fault", ["fallback", "exception", "number"])
def test_completed_acceptance_failures_keep_separate_evidence_without_retry(
    tmp_path: Path, review: StreamingReview, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    current = workbench(review)
    args = prepare(tmp_path, current, monkeypatch)
    state = fake_runners(tmp_path, current, monkeypatch, fault=fault)
    output = tmp_path / "failed"
    assert cli.main([*args, "evaluate", "--invoke-live", "--output", str(output)]) == 1
    assert [item[0] for item in state.calls] == [item.model_key for item in current.targets]
    summary = json.loads((output / "summary.json").read_bytes())
    assert summary["models"] == [] and summary["questions"] == 2
    ledger = StreamingLedger(tmp_path, current)
    assert ledger.summary()["used"] == 2 and not ledger.summary()["blocked"]
    for target in current.targets:
        record = json.loads(
            (ledger.directory / "acceptance" / f"{target.model_key}.json").read_bytes()
        )
        assert not record["passed"]
