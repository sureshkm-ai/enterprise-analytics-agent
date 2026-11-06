"""Session configuration and operator CLI checks never use actual credentials."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from enterprise_analytics_agent.adapters import publication_cli
from enterprise_analytics_agent.adapters.aws_runtime import (
    AWSConfigurationError,
    AWSRuntimeConfig,
    load_runtime_config,
    session_for_role,
)
from enterprise_analytics_agent.snapshots import PreparedSnapshot, SnapshotManifest


@pytest.fixture
def runtime_payload() -> dict[str, object]:
    return {
        "profile": "explicit-development",
        "account": "111122223333",
        "region": "us-west-2",
        "resource_prefix": "ea-dev",
        "database_name": "ea_dev",
        "workgroup_name": "ea-dev",
        "snapshots": [{"dataset_version": "parity-v1", "include_returns": True}],
    }


def write_config(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_runtime_configuration_requires_explicit_profile(
    tmp_path: Path, runtime_payload: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "must-not-be-used")
    runtime_payload.pop("profile")
    path = write_config(tmp_path / "invalid.json", runtime_payload)
    with pytest.raises(AWSConfigurationError):
        load_runtime_config(path)
    with pytest.raises(AWSConfigurationError):
        load_runtime_config(tmp_path / "absent.json")


@pytest.mark.parametrize("purpose", ["loader", "query"])
def test_runtime_verifies_account_then_assumes_only_the_narrow_role(
    runtime_payload: dict[str, object], monkeypatch: pytest.MonkeyPatch, purpose: str
) -> None:
    config = AWSRuntimeConfig.model_validate(runtime_payload)
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": "111122223333"}
    sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "test-access",
            "SecretAccessKey": "test-secret",
            "SessionToken": "test-token",
        }
    }
    base, assumed = Mock(), Mock()
    base.client.return_value = sts
    calls: list[dict[str, Any]] = []

    def session_factory(**kwargs: Any) -> Mock:
        calls.append(kwargs)
        return base if "profile_name" in kwargs else assumed

    monkeypatch.setattr("boto3.Session", session_factory)
    if purpose == "loader":
        actual = session_for_role(config, "loader")
        role = "ea-dev-dataset-loader"
    else:
        actual = session_for_role(config, "query")
        role = "ea-dev-query-executor"
    assert actual is assumed
    assert calls[0] == {"profile_name": "explicit-development", "region_name": "us-west-2"}
    sts.assume_role.assert_called_once_with(
        RoleArn=f"arn:aws:iam::111122223333:role/{role}",
        RoleSessionName=f"analytics-{purpose}",
        DurationSeconds=900,
    )
    assert calls[1]["region_name"] == "us-west-2"


def test_wrong_account_fails_before_role_assumption(
    runtime_payload: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    base = Mock()
    base.client.return_value.get_caller_identity.return_value = {"Account": "999900001111"}
    monkeypatch.setattr("boto3.Session", Mock(return_value=base))
    with pytest.raises(AWSConfigurationError, match="different account"):
        session_for_role(AWSRuntimeConfig.model_validate(runtime_payload), "loader")
    base.client.return_value.assume_role.assert_not_called()


def test_publication_cli_rejects_unreviewed_versions_before_sessions(
    tmp_path: Path,
    runtime_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = Mock(side_effect=AssertionError("No session should be constructed"))
    monkeypatch.setattr(publication_cli, "session_for_role", session)
    path = write_config(tmp_path / "config.json", runtime_payload)
    assert (
        publication_cli.main(
            [
                "--config",
                str(path),
                "--source-dir",
                str(tmp_path),
                "--dataset-version",
                "other-v1",
            ]
        )
        == 1
    )
    assert "inventory" in capsys.readouterr().err
    session.assert_not_called()


def test_publication_cli_rejects_returns_mismatch_before_sessions(
    tmp_path: Path,
    runtime_payload: dict[str, object],
    snapshot_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = Mock(side_effect=AssertionError("No session should be constructed"))
    monkeypatch.setattr(publication_cli, "session_for_role", session)
    path = write_config(tmp_path / "config.json", runtime_payload)
    assert (
        publication_cli.main(
            [
                "--config",
                str(path),
                "--source-dir",
                str(snapshot_dir),
                "--dataset-version",
                "parity-v1",
            ]
        )
        == 1
    )
    assert "Returns inventory" in capsys.readouterr().err
    session.assert_not_called()


def test_publication_cli_validates_data_before_loader_and_prints_ready_manifest(
    tmp_path: Path,
    runtime_payload: dict[str, object],
    snapshot_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_payload["snapshots"] = [{"dataset_version": "parity-v1", "include_returns": False}]
    session = Mock()
    factory = Mock(return_value=session)
    monkeypatch.setattr(publication_cli, "session_for_role", factory)

    def publish(prepared: PreparedSnapshot, **kwargs: object) -> SnapshotManifest:
        assert set(prepared.manifest.tables) == {
            "customers",
            "products",
            "orders",
            "order_items",
            "payments",
            "refunds",
        }
        return prepared.manifest

    monkeypatch.setattr(publication_cli, "publish_snapshot", publish)
    path = write_config(tmp_path / "config.json", runtime_payload)
    assert (
        publication_cli.main(
            [
                "--config",
                str(path),
                "--source-dir",
                str(snapshot_dir),
                "--dataset-version",
                "parity-v1",
            ]
        )
        == 0
    )
    factory.assert_called_once()
    assert factory.call_args.args[1] == "loader"
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "ready"
    assert payload["dataset_version"] == "parity-v1"
