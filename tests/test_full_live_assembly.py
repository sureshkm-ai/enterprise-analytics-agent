"""Offline regression for CDK deploying the cached retail template after a file edit."""

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import pytest

from enterprise_analytics_agent.retail_evaluation import assembly_assets as assets
from enterprise_analytics_agent.retail_evaluation.full_live import FullLiveReview
from infrastructure.agentcore import full_live

ROOT = Path(__file__).parents[1]


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory: Path) -> dict[str, str]:
    return {str(p.relative_to(directory)): digest(p) for p in directory.rglob("*") if p.is_file()}


@pytest.fixture
def assembly(tmp_path: Path) -> Path:
    """Authored single-stack metadata independent of the production helper."""
    directory = tmp_path / "assembly"
    directory.mkdir()
    settings = {
        "dataset_version": "retail-v1",
        "tenant_id": "retail_demo",
        "reference_date": "2025-04-01",
    }
    write(
        directory / assets.TEMPLATE,
        {
            "Resources": {
                "AnalyticsRuntime": {
                    "Properties": {
                        "EnvironmentVariables": {"ANALYTICS_RUNTIME_CONFIG": json.dumps(settings)}
                    }
                }
            }
        },
    )
    checksum = digest(directory / assets.TEMPLATE)
    write(
        directory / "manifest.json",
        {
            "version": "55.0.0",
            "artifacts": {
                "enterprise-analytics-dev-agent-runtime": {
                    "type": "aws:cloudformation:stack",
                    "environment": "aws://453711491609/us-west-2",
                    "properties": {
                        "templateFile": "enterprise-analytics-dev-agent-runtime.template.json",
                        "stackTemplateAssetObjectUrl": (
                            "s3://cdk-hnb659fds-assets-453711491609-us-west-2/" + checksum + ".json"
                        ),
                        "additionalDependencies": ["enterprise-analytics-dev-agent-runtime.assets"],
                    },
                    "dependencies": ["enterprise-analytics-dev-agent-runtime.assets"],
                    "additionalMetadataFile": (
                        "enterprise-analytics-dev-agent-runtime.metadata.json"
                    ),
                },
                "enterprise-analytics-dev-agent-runtime.assets": {
                    "type": "cdk:asset-manifest",
                    "properties": {"file": "enterprise-analytics-dev-agent-runtime.assets.json"},
                },
                "Tree": {"type": "cdk:tree", "properties": {"file": "tree.json"}},
                "aws-cdk-lib/feature-flag-report": {"type": "cdk:feature-flag-report"},
            },
        },
    )
    write(
        directory / assets.ASSET_FILE,
        {
            "version": "55.0.0",
            "files": {
                checksum: {
                    "displayName": "enterprise-analytics-dev-agent-runtime Template",
                    "source": {
                        "path": "enterprise-analytics-dev-agent-runtime.template.json",
                        "packaging": "file",
                    },
                    "destinations": {
                        "453711491609-us-west-2-b94ee4b7": {
                            "bucketName": "cdk-hnb659fds-assets-453711491609-us-west-2",
                            "objectKey": checksum + ".json",
                            "region": "us-west-2",
                            "assumeRoleArn": (
                                "arn:${AWS::Partition}:iam::453711491609:role/"
                                "cdk-hnb659fds-file-publishing-role-453711491609-us-west-2"
                            ),
                        }
                    },
                }
            },
            "dockerImages": {},
        },
    )
    write(directory / "cdk.out", {"version": "55.0.0"})
    write(directory / "tree.json", {})
    write(directory / "validation-report.json", {"pluginReports": []})
    write(
        directory / (assets.STACK + ".metadata.json"),
        {"/" + assets.STACK: [{"type": "aws:cdk:templateFile", "data": assets.TEMPLATE}]},
    )
    return directory


def altered_template(directory: Path) -> str:
    path = directory / assets.TEMPLATE
    value = json.loads(path.read_bytes())
    write(path, full_live.parity_variant(value))
    return digest(path)


def test_template_edit_with_cached_asset_metadata_is_rejected(assembly: Path) -> None:
    changed = altered_template(assembly)
    with pytest.raises(ValueError, match="asset URL"):
        assets.validate_assembly(assembly, changed)


def test_rebind_updates_all_operational_references_and_preserves_every_other_file(
    assembly: Path,
) -> None:
    checksum = altered_template(assembly)
    before = inventory(assembly)
    result = assets.rewrite_template_asset(assembly)
    assert result["template_sha256"] == checksum
    manifest = json.loads((assembly / "manifest.json").read_bytes())
    url = manifest["artifacts"][assets.STACK]["properties"]["stackTemplateAssetObjectUrl"]
    assert url == f"s3://cdk-hnb659fds-assets-453711491609-us-west-2/{checksum}.json"
    payload = json.loads((assembly / assets.ASSET_FILE).read_bytes())
    assert set(payload["files"]) == {checksum}
    assert {
        destination["objectKey"]
        for destination in payload["files"][checksum]["destinations"].values()
    } == {checksum + ".json"}
    after = inventory(assembly)
    assert {name for name in before if before[name] != after[name]} == {
        "manifest.json",
        assets.ASSET_FILE,
    }
    assert assets.validate_assembly(assembly, checksum) == result
    assert assets.rewrite_template_asset(assembly) == result
    assert inventory(assembly) == after  # Already consistent metadata is not reformatted.


@pytest.mark.parametrize(
    "change",
    [
        "url",
        "url_bucket",
        "template_path",
        "template_traversal",
        "metadata_path",
        "metadata_template_path",
        "asset_file_path",
        "asset_id",
        "asset_key",
        "source_path",
        "source_absolute",
        "source_packaging",
        "bucket",
        "region",
        "publish_role",
        "extra_destination",
        "extra_file_asset",
        "docker_asset",
        "extra_artifact",
        "dependency",
        "extra_file",
    ],
)
def test_invalid_asset_metadata_fails_even_with_locally_matching_template_bytes(
    assembly: Path, change: str
) -> None:
    checksum = digest(assembly / assets.TEMPLATE)
    manifest = json.loads((assembly / "manifest.json").read_bytes())
    payload = json.loads((assembly / assets.ASSET_FILE).read_bytes())
    stack = manifest["artifacts"][assets.STACK]
    source = payload["files"][checksum]["source"]
    destinations = payload["files"][checksum]["destinations"]
    destination = destinations[assets.DESTINATION]
    if change == "url":
        stack["properties"]["stackTemplateAssetObjectUrl"] = f"s3://{assets.BUCKET}/{'f' * 64}.json"
    elif change == "url_bucket":
        stack["properties"]["stackTemplateAssetObjectUrl"] = f"s3://other-bucket/{checksum}.json"
    elif change in {"template_path", "template_traversal"}:
        stack["properties"]["templateFile"] = (
            "other.template.json" if change == "template_path" else "../" + assets.TEMPLATE
        )
    elif change == "metadata_path":
        stack["additionalMetadataFile"] = "elsewhere.metadata.json"
    elif change == "metadata_template_path":
        write(
            assembly / (assets.STACK + ".metadata.json"),
            {"/" + assets.STACK: [{"type": "aws:cdk:templateFile", "data": "other.json"}]},
        )
    elif change == "asset_file_path":
        manifest["artifacts"][assets.ASSET_ARTIFACT]["properties"]["file"] = "../other.assets.json"
    elif change == "asset_id":
        payload["files"]["f" * 64] = payload["files"].pop(checksum)
    elif change == "asset_key":
        destination["objectKey"] = "stale.json"
    elif change == "source_path":
        source["path"] = "../" + assets.TEMPLATE
    elif change == "source_absolute":
        source["path"] = str(assembly / assets.TEMPLATE)
    elif change == "source_packaging":
        source["packaging"] = "zip"
    elif change == "bucket":
        destination["bucketName"] = "other-bucket"
    elif change == "region":
        destination["region"] = "us-east-1"
    elif change == "publish_role":
        destination["assumeRoleArn"] = "arn:aws:iam::453711491609:role/other"
    elif change == "extra_destination":
        destinations["unreviewed"] = deepcopy(destination)
    elif change == "extra_file_asset":
        payload["files"]["f" * 64] = deepcopy(payload["files"][checksum])
    elif change == "docker_asset":
        payload["dockerImages"]["unreviewed"] = {}
    elif change == "extra_artifact":
        manifest["artifacts"]["other-stack"] = deepcopy(stack)
    elif change == "dependency":
        stack["dependencies"] = []
    elif change == "extra_file":
        (assembly / "unreviewed.json").write_text("{}")
    write(assembly / "manifest.json", manifest)
    write(assembly / assets.ASSET_FILE, payload)
    before = inventory(assembly)
    with pytest.raises(ValueError):
        assets.validate_assembly(assembly, checksum)
    with pytest.raises(ValueError):
        assets.rewrite_template_asset(assembly)
    assert inventory(assembly) == before


def test_template_symlink_is_rejected_without_following_it(assembly: Path, tmp_path: Path) -> None:
    target = tmp_path / "unreviewed-template.json"
    shutil.move(assembly / assets.TEMPLATE, target)
    (assembly / assets.TEMPLATE).symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        assets.validate_assembly(assembly, digest(target))


def test_retained_read_lock_is_allowed_but_other_lock_paths_are_not(assembly: Path) -> None:
    checksum = digest(assembly / assets.TEMPLATE)
    (assembly / "read.123.1.lock").write_text("retained inventory")
    assets.validate_assembly(assembly, checksum)
    (assembly / "other.lock").write_text("unexpected payload")
    with pytest.raises(ValueError, match="inventory"):
        assets.validate_assembly(assembly, checksum)


def test_prepare_repairs_only_new_parity_copy_and_preserves_the_frozen_source(
    assembly: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    source = root / "artifacts/milestone-5/q18-repair-v1/cdk.candidate.out"
    source.parent.mkdir(parents=True)
    shutil.copytree(assembly, source)
    review_path = root / "evaluations/ui-shared/review.proposed.json"
    review_path.parent.mkdir(parents=True)
    write(review_path, {"target": {"dataset_version": "retail-v1", "reference_date": "2025-04-01"}})
    monkeypatch.setattr(full_live, "local_review", lambda root: {"authored": True})
    monkeypatch.setattr(boto3, "Session", lambda **k: pytest.fail("Preparation must be offline"))
    before = inventory(source)
    output = root / "new-output"
    result = full_live.prepare(output, root=root)
    assert inventory(source) == before
    assert inventory(output / "retail") == before
    assert result["retail_template_sha256"] != result["parity_template_sha256"]
    assets.validate_assembly(output / "retail", result["retail_template_sha256"])
    assets.validate_assembly(output / "parity", result["parity_template_sha256"])
    assert result["files"] == {
        name: checksum
        for name, checksum in inventory(output).items()
        if name != "assembly-review.json"
    }


def prepared_fixture(
    assembly: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, FullLiveReview, Path]:
    root = tmp_path / "root"
    prepared = root / "artifacts/full-live/prepared"
    prepared.mkdir(parents=True)
    shutil.copytree(assembly, prepared / "retail")
    shutil.copytree(assembly, prepared / "parity")
    parity_hash = altered_template(prepared / "parity")
    config = root / "infrastructure/cdk/config.development.json"
    config.parent.mkdir(parents=True)
    config.write_bytes((ROOT / "infrastructure/cdk/config.development.json").read_bytes())
    review = FullLiveReview(
        parity_template_sha256=parity_hash, expires_at=datetime(2026, 11, 13, 23, 59, tzinfo=UTC)
    ).model_copy(update={"retail_template_sha256": digest(prepared / "retail" / assets.TEMPLATE)})
    write(
        prepared / "assembly-review.json", {"files": inventory(prepared), "configuration_delta": {}}
    )
    monkeypatch.setattr(full_live, "ROOT", root)
    monkeypatch.setattr(full_live, "local_review", lambda *a: pytest.fail("Reject metadata first"))
    monkeypatch.setattr(
        full_live, "FullLiveBudget", lambda *a, **k: pytest.fail("Reject metadata first")
    )
    monkeypatch.setattr(boto3, "Session", lambda **k: pytest.fail("No AWS session is allowed"))
    return root, review, prepared


def test_recomputed_inventory_cannot_hide_stale_cdk_metadata_or_reach_aws(
    assembly: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, review, prepared = prepared_fixture(assembly, tmp_path, monkeypatch)
    # The inventory is accurate and all template hashes match their input pins;
    # the operational metadata still points at the old retail asset.
    assert json.loads((prepared / "assembly-review.json").read_bytes())["files"] == {
        name: checksum
        for name, checksum in inventory(prepared).items()
        if name != "assembly-review.json"
    }
    with pytest.raises(ValueError, match="asset URL"):
        full_live.verify_offline(review, root=root)
    with pytest.raises(ValueError, match="asset URL"):
        full_live.operations(review, root / "operations", prepared=prepared)


def test_restoration_validation_ignores_bad_or_absent_parity_and_source_configuration(
    assembly: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, review, prepared = prepared_fixture(assembly, tmp_path, monkeypatch)
    shutil.rmtree(prepared / "parity")
    (root / "infrastructure/cdk/config.development.json").unlink()
    archive = root / "artifacts/milestone-5/q18-repair-v1/candidate/agent.zip"
    monkeypatch.setattr(
        full_live,
        "digest",
        lambda path: review.archive_sha256 if path == archive else digest(path),
    )
    result = full_live.verify_offline(review, root=root, restore_only=True)
    assert result["local"]["scope"] == "Frozen retail restoration; no current source/data required"
