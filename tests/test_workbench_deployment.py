"""New workbench deployment scope does not reopen the historical continuation."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_streaming_completion_workflow import Edges, Ledger, approval, prepared
from test_streaming_completion_workflow import no_aws as no_aws

from enterprise_analytics_agent.ui.model_streams import (
    StreamingLedger,
    StreamingReleases,
    StreamingReview,
)
from infrastructure.agentcore import streaming_completion as module


def workbench(root: Path) -> module.Prepared:
    item = prepared(root)
    review = StreamingReview.model_validate(
        {
            **item.review.model_dump(mode="json"),
            "schema_version": "bedrock-model-workbench-v1",
            "parent": None,
            "maximum_attempts": 40,
            "ordinary_limit": 38,
        }
    )
    releases = item.baseline_releases.model_copy(
        update={
            "models": tuple(
                record.model_copy(update={"runtime_version": "3"})
                for record in item.baseline_releases.models
            ),
        }
    )
    plan = item.plan.model_copy(
        update={
            "schema_version": "bedrock-workbench-preparation-v1",
            "review_sha256": review.sha256,
        }
    )
    return replace(item, review=review, plan=plan, baseline_releases=releases)


def test_fresh_review_binds_restored_v3_baseline_without_historical_parent_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = workbench(tmp_path)
    files = {
        "review.json": item.review.model_dump_json(),
        "baseline-review.json": item.baseline_review.model_dump_json(),
        "baseline-releases.json": item.baseline_releases.model_dump_json(),
        "infrastructure/agentcore/streaming_completion.py": "# fixture operator\n",
        "src/enterprise_analytics_agent/adapters/deployment_controller.py": "# controller\n",
        "candidate.zip": "fixture package",
        "old-guard.json": json.dumps(
            {
                "active": False,
                "requires_inspection": False,
                "process_reaped": True,
                "strict_checkpoint_verified": True,
            }
        ),
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    plan = item.plan.model_copy(
        update={
            "baseline_releases_sha256": module.digest(tmp_path / "baseline-releases.json"),
            "process_guard_sha256": module.digest(tmp_path / "old-guard.json"),
            "pinned_files": {
                **item.plan.pinned_files,
                **{name: module.digest(tmp_path / name) for name in files},
            },
        }
    )
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json())
    monkeypatch.setattr(module, "verify_local_inputs", lambda *args: None)
    result = module.load_prepared(tmp_path, path)
    assert result.review.parent is None
    assert {row.runtime_version for row in result.baseline_releases.models} == {"3"}
    old_schema = plan.model_copy(
        update={"schema_version": "bedrock-streaming-completion-preparation-v1"}
    )
    path.write_text(old_schema.model_dump_json())
    with pytest.raises(ValueError, match="pins differ"):
        module.load_prepared(tmp_path, path)


def test_partial_acceptance_retains_working_deployments_without_historical_claim(
    tmp_path: Path,
) -> None:
    item = workbench(tmp_path)
    output = tmp_path / "execution"
    ledger = Ledger()

    class PartialEdges(Edges):
        def upload(self) -> str:
            assert self.active and not self.ledger.claimed
            self.upload_calls += 1
            return "ACTUAL-NEW-S3-VERSION"

        def evaluate(self, releases: StreamingReleases) -> None:
            super().evaluate(releases)
            (output / "acceptance").mkdir()
            (output / "acceptance/summary.json").write_text(json.dumps({"passed": False}))

    edges = PartialEdges(item, ledger)
    module.CompletionWorkflow(item, output, approval(item), edges, ledger=ledger).run()
    assert not ledger.claimed and ledger.calls == []
    assert len(edges.updates) == 10 and edges.restorations == []
    assert edges.cleanup_calls == 0 and edges.evaluation_calls == 1
    assert json.loads((output / "outcome.json").read_bytes())["status"] == "partially_accepted"


@pytest.mark.parametrize("accepted_count", [0, 9, 10])
def test_deployed_acceptance_requires_individual_bound_model_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accepted_count: int
) -> None:
    item = workbench(tmp_path)
    output = tmp_path / "execution"
    (output / "acceptance").mkdir(parents=True)
    ledger = StreamingLedger(tmp_path, item.review)
    records = ledger.directory / "acceptance"
    records.mkdir(parents=True)
    accepted_models = []
    for index, target in enumerate(item.review.targets):
        passed = index < accepted_count
        if passed:
            accepted_models.append(target.model_key)
        (records / f"{target.model_key}.json").write_text(
            json.dumps(
                {
                    "review_sha256": item.review.sha256,
                    "model_key": target.model_key,
                    "passed": passed,
                    "cases": ["Q18", "all-five-regionals"] if passed else [],
                }
            )
        )
    (output / "acceptance/summary.json").write_text(
        json.dumps(
            {
                "passed": accepted_count == 10,
                "models": accepted_models,
                "review_sha256": item.review.sha256,
            }
        )
    )
    live = module.LiveBoundaries(item, output, None)
    monkeypatch.setattr(live, "_cli", lambda *args, **kwargs: None)
    if accepted_count:
        live.evaluate(item.baseline_releases)
        path = records / f"{accepted_models[0]}.json"
        invalid = json.loads(path.read_bytes())
        invalid["review_sha256"] = "0" * 64
        path.write_text(json.dumps(invalid))
        with pytest.raises(ValueError, match="different binding"):
            live.evaluate(item.baseline_releases)
    else:
        with pytest.raises(ValueError, match="No independently accepted"):
            live.evaluate(item.baseline_releases)
