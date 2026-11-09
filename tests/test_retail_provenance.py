"""Read-only acquisition must fail closed before marking canonical inputs verified."""

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from enterprise_analytics_agent.adapters.retail_provenance import (
    ACCOUNT,
    MANIFEST_KEY,
    SCHEMAS,
    _read_object,
    download_canonical,
    verify_local,
)


class Identity:
    def __init__(self, account: str = ACCOUNT) -> None:
        self.account = account

    def get_caller_identity(self) -> dict[str, Any]:
        return {"Account": self.account, "Arn": "test-principal"}


class Source:
    def __init__(self, objects: dict[str, bytes], *, version: str | None = "version-1") -> None:
        self.objects = objects
        self.version = version
        self.calls: list[dict[str, Any]] = []
        self.change_version = False

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "ContentLength": len(self.objects[kwargs["Key"]]),
            "VersionId": self.version,
            "ETag": '"opaque-identity"',
        }

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "Body": io.BytesIO(self.objects[kwargs["Key"]]),
            "ETag": '"opaque-identity"',
            "VersionId": "racing-version" if self.change_version else self.version,
        }


@pytest.fixture
def source(tmp_path: Path) -> Source:
    objects: dict[str, bytes] = {}
    tables: dict[str, Any] = {}
    # Authored empty files are sufficient to prove schema/inventory acquisition;
    # independent accounting fixtures are covered in the oracle tests.
    with duckdb.connect(":memory:") as connection:
        for name, schema in SCHEMAS.items():
            columns = ", ".join(f"{column} {kind}" for column, kind in schema)
            connection.execute(f"CREATE TABLE {name} ({columns})")
            path = tmp_path / f"{name}.parquet"
            connection.execute(f"COPY {name} TO ? (FORMAT PARQUET)", [str(path)])
            content = path.read_bytes()
            key = f"snapshots/retail-v1/{name}/part-00000.parquet"
            objects[key] = content
            tables[name] = {
                "key": key,
                "columns": [{"name": c, "type": t} for c, t in schema],
                "row_count": 0,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
    manifest = {
        "manifest_version": "v1",
        "dataset_version": "retail-v1",
        "state": "ready",
        "seed": 20260101,
        "tables": tables,
    }
    objects[MANIFEST_KEY] = json.dumps(manifest).encode()
    return Source(objects)


def test_exact_version_pinning_and_offline_reverification(source: Source, tmp_path: Path) -> None:
    destination = tmp_path / "canonical"
    result = download_canonical(destination, s3=source, sts=Identity())
    assert result["verified"] is True
    assert len(source.calls) == 16  # one HEAD and one exact GET for manifest + seven files
    assert all(call["ExpectedBucketOwner"] == ACCOUNT for call in source.calls)
    assert all(call["VersionId"] == "version-1" for call in source.calls[1::2])
    assert verify_local(destination)["state"] == "ready"
    assert download_canonical(destination, s3=source, sts=Identity()) == result


def test_account_mismatch_stops_before_any_s3_access(source: Source, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unexpected AWS account"):
        download_canonical(tmp_path, s3=source, sts=Identity("000000000000"))
    assert not source.calls


def test_failed_checksum_never_publishes_verified_provenance(
    source: Source, tmp_path: Path
) -> None:
    source.objects["snapshots/retail-v1/returns/part-00000.parquet"] += b"changed"
    with pytest.raises(ValueError, match="ready inventory"):
        download_canonical(tmp_path, s3=source, sts=Identity())
    assert not (tmp_path / "provenance.json").exists()


@pytest.mark.parametrize("change", ["missing_returns", "wrong_source", "not_ready", "schema"])
def test_unreviewed_manifest_is_rejected(source: Source, tmp_path: Path, change: str) -> None:
    manifest = json.loads(source.objects[MANIFEST_KEY])
    if change == "missing_returns":
        del manifest["tables"]["returns"]
    elif change == "wrong_source":
        manifest["tables"]["orders"]["key"] = "snapshots/other/orders/part-00000.parquet"
    elif change == "not_ready":
        manifest["state"] = "preparing"
    else:
        manifest["tables"]["orders"]["columns"][0]["type"] = "INTEGER"
    source.objects[MANIFEST_KEY] = json.dumps(manifest).encode()
    with pytest.raises(ValueError):
        download_canonical(tmp_path, s3=source, sts=Identity())
    assert not (tmp_path / "provenance.json").exists()


def test_version_race_is_rejected(source: Source) -> None:
    source.change_version = True
    with pytest.raises(ValueError, match="identity changed"):
        _read_object(source, MANIFEST_KEY, 100_000)


def test_unversioned_object_requires_conditional_read(source: Source) -> None:
    source.version = None
    _read_object(source, MANIFEST_KEY, 100_000)
    assert source.calls[-1]["IfMatch"] == '"opaque-identity"'
    assert "VersionId" not in source.calls[-1]


def test_retained_evidence_and_modified_local_bytes_are_not_overwritten(
    source: Source, tmp_path: Path
) -> None:
    download_canonical(tmp_path, s3=source, sts=Identity())
    (tmp_path / "orders.parquet").write_bytes(b"unrelated-existing-work")
    with pytest.raises(ValueError, match="checksum/size"):
        verify_local(tmp_path)
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        download_canonical(tmp_path, s3=source, sts=Identity())


def test_committed_manifest_and_object_identities_bind_frozen_inputs() -> None:
    evidence = Path(__file__).resolve().parents[1] / "evaluations/retail-v1"
    content = (evidence / "ready-manifest.json").read_bytes()
    manifest = json.loads(content)
    provenance = json.loads((evidence / "oracle-provenance.json").read_bytes())
    assert hashlib.sha256(content).hexdigest() == provenance["manifest"]["sha256"]
    assert set(manifest["tables"]) == set(provenance["objects"]) == set(SCHEMAS)
    for name, item in manifest["tables"].items():
        identity = provenance["objects"][name]
        assert identity["key"] == item["key"]
        assert identity["size_bytes"] == item["size_bytes"]
        assert identity["sha256"] == item["sha256"]
        assert identity["version_id"]
