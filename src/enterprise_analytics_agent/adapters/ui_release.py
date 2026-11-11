"""Exact reviewed UI release bindings, with fresh AWS reads kept in the adapter.

A saved ReleaseRecord is an expected version/pin set, never a cached AWS proof.
Original rollback binds a separate frozen archive; it does not claim the old code
matches the local Q18-corrected agent or the retail canonical publication.
"""

import base64
import json
import time
import tomllib
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any, Literal

import boto3
from pydantic import BaseModel, ConfigDict, Field, field_validator

from enterprise_analytics_agent.adapters.aws_schema import glue_table_name
from enterprise_analytics_agent.adapters.operator_reads import ReadPool, ReadSession
from enterprise_analytics_agent.adapters.retail_checkpoint import (
    _normalize,
    _resolve,
    _verify_runtime,
    verify_candidate_checkpoint,
    verify_checkpoint,
)
from enterprise_analytics_agent.adapters.retail_provenance import validate_manifest, verify_local
from enterprise_analytics_agent.retail_evaluation.campaign import CODE_SHA256, CODE_VERSION
from enterprise_analytics_agent.retail_evaluation.cases import (
    load_goldens,
    load_suite,
    verify_frozen_inputs,
)
from enterprise_analytics_agent.retail_evaluation.deployment import (
    BASE_TEMPLATE_SHA256,
    TEMPLATE_NAME,
    canonical_hash,
    digest,
)
from enterprise_analytics_agent.retail_evaluation.repair_config import (
    CandidateVersionBinding,
    load_review,
)
from enterprise_analytics_agent.ui.shared import SharedReview

ROOT = Path(__file__).resolve().parents[3]
SHARED_SOURCE_SHA256 = "aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be"
ORIGINAL_SOURCE_SHA256 = "bba6aa482dd71976cf0f588ea8058b14812494d96e961711af0867ffd219c1a5"
CANDIDATE_CONFIG_SHA256 = "6f480b57d00cb5386556ec4c2d3ff5618dc6e0e51a9147577fbd730c8d764c4e"
ORIGINAL_CONFIG_SHA256 = "67056f86738cdfec508a9c00cd99c42767a8360b417c31928eb626eca3e530b3"
LOCK_SHA256 = "902a20a51b4dacb15add668ac06b11507b87ad2e96278b314e2b34d8584cf09a"
type ReleaseKind = Literal["candidate", "original"]
type Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ReleaseRecord(BaseModel):
    """Trusted operator evidence of an observed version, not authorization or freshness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["ui-shared-release-v1"] = "ui-shared-release-v1"
    kind: ReleaseKind
    observed_at: datetime
    runtime_arn: str
    runtime_version: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
    review_sha256: Sha256
    source_sha256: Sha256
    archive_sha256: Sha256
    artifact_version_id: str
    configuration_sha256: Sha256
    template_sha256: Sha256
    dataset_version: Literal["retail-v1", "parity-v1"]
    canonical_manifest_sha256: Sha256 | None

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("release observation requires a timezone")
        return value.astimezone(UTC)


def _paths(kind: ReleaseKind, *, root: Path = ROOT) -> tuple[Path, Path]:
    if kind == "candidate":
        return (
            root / "artifacts/milestone-5/q18-repair-v1/candidate/agent.zip",
            root / "artifacts/milestone-5/q18-repair-v1/cdk.candidate.out" / TEMPLATE_NAME,
        )
    if kind == "original":
        return (
            root / "artifacts/agentcore/agent.zip",
            root / "artifacts/milestone-5/cdk.restore.out" / TEMPLATE_NAME,
        )
    raise ValueError("unknown reviewed release kind")


def _pins(review: SharedReview, kind: ReleaseKind) -> dict[str, Any]:
    if kind not in {"candidate", "original"}:
        raise ValueError("unknown reviewed release kind")
    candidate = kind == "candidate"
    if review.source_sha256 != SHARED_SOURCE_SHA256:
        raise ValueError("shared review does not pin the accepted agent source closure")
    return {
        "review_sha256": review.sha256,
        "runtime_arn": review.target.runtime_arn,
        "source_sha256": review.source_sha256 if candidate else ORIGINAL_SOURCE_SHA256,
        "archive_sha256": review.archive_sha256 if candidate else CODE_SHA256,
        "artifact_version_id": review.artifact_version_id if candidate else CODE_VERSION,
        "configuration_sha256": CANDIDATE_CONFIG_SHA256 if candidate else ORIGINAL_CONFIG_SHA256,
        "template_sha256": review.runtime_template_sha256 if candidate else BASE_TEMPLATE_SHA256,
        "dataset_version": "retail-v1" if candidate else "parity-v1",
        "canonical_manifest_sha256": review.canonical_manifest_sha256 if candidate else None,
    }


def _template(kind: ReleaseKind, *, root: Path = ROOT) -> dict[str, Any]:
    _, path = _paths(kind, root=root)
    expected = (
        "faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368"
        if kind == "candidate"
        else BASE_TEMPLATE_SHA256
    )
    if digest(path) != expected:
        raise ValueError("reviewed UI deployment template changed")
    return json.loads(path.read_bytes())  # type: ignore[no-any-return]


def validate_record(
    review: SharedReview, record: ReleaseRecord, *, kind: ReleaseKind = "candidate"
) -> ReleaseRecord:
    """Bind an expected version to the review. Fresh verification is still mandatory."""
    record = ReleaseRecord.model_validate(record.model_dump())
    if record.kind != kind or any(
        getattr(record, name) != value for name, value in _pins(review, kind).items()
    ):
        raise ValueError("release record differs from the reviewed release/configuration/data pins")
    minimum = 13 if kind == "candidate" else 12
    if int(record.runtime_version) < minimum:
        raise ValueError("release record uses a historical version outside the new UI release")
    return record


def make_record(
    review: SharedReview,
    checkpoint: dict[str, Any],
    *,
    kind: ReleaseKind = "candidate",
    now: datetime | None = None,
) -> ReleaseRecord:
    """Validate the fresh in-memory strict checkpoint before creating version evidence."""
    observed = datetime.fromisoformat(checkpoint["observed_at"])
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("checkpoint timestamp requires a timezone")
    age = ((now or datetime.now(UTC)) - observed).total_seconds()
    if not 0 <= age <= 300:
        raise ValueError("checkpoint observation is stale or future-dated")
    pins = _pins(review, kind)
    template = _template(kind)
    runtime, endpoint = checkpoint["runtime"], checkpoint["endpoint"]
    _verify_runtime(
        runtime,
        endpoint,
        template,
        artifact_sha256=pins["archive_sha256"],
        artifact_version_id=pins["artifact_version_id"],
    )
    settings = json.loads(runtime["environmentVariables"]["ANALYTICS_RUNTIME_CONFIG"])
    if canonical_hash(settings) != pins["configuration_sha256"]:
        raise ValueError("checkpoint configuration differs from the reviewed shared/rollback scope")
    if checkpoint["identity"].get("Account") != review.target.account:
        raise ValueError("checkpoint identity account differs from the reviewed account")
    if checkpoint.get("retention_days") != 7:
        raise ValueError("checkpoint does not prove seven-day retention")
    stacks = checkpoint.get("stacks", {})
    if set(stacks) != {
        "enterprise-analytics-dev-agent-runtime",
        "enterprise-analytics-dev-agent-foundation",
        "enterprise-analytics-dev-data-layer",
    } or any(value not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"} for value in stacks.values()):
        raise ValueError("checkpoint does not prove all retained stacks are stable")
    for name, resource in template["Resources"].items():
        if resource["Type"] == "AWS::BedrockAgentCore::ResourcePolicy":
            expected = json.loads(_resolve(resource["Properties"]["Policy"]))
            if _normalize(checkpoint["policies"][name]) != _normalize(expected):
                raise ValueError("checkpoint resource policy differs from the reviewed policy")
    for name, expected in (
        ("artifact_sha256", pins["archive_sha256"]),
        ("artifact_version_id", pins["artifact_version_id"]),
        ("template_sha256", pins["template_sha256"]),
    ):
        if checkpoint.get(name) != expected:
            raise ValueError("checkpoint artifact/template pin differs from the reviewed release")
    head = checkpoint["artifact_head"]
    expected_size = 39171778 if kind == "candidate" else 39117152
    if (
        head.get("VersionId") != pins["artifact_version_id"]
        or head.get("ChecksumSHA256")
        != base64.b64encode(bytes.fromhex(pins["archive_sha256"])).decode()
        or head.get("ContentLength") != expected_size
    ):
        raise ValueError("checkpoint code object identity, checksum or size differs")
    return validate_record(
        review,
        ReleaseRecord(
            kind=kind,
            observed_at=observed,
            runtime_version=runtime["agentRuntimeVersion"],
            **pins,
        ),
        kind=kind,
    )


def verify_release(
    review: SharedReview, *, kind: ReleaseKind = "candidate", session: Any = None
) -> dict[str, Any]:
    """Read the exact reviewed release afresh; no invocation or mutation API is used."""
    pins = _pins(review, kind)
    if session is None:
        session = boto3.Session(
            profile_name=review.target.profile, region_name=review.target.region
        )
    reader = (
        session
        if isinstance(session, ReadSession)
        else ReadPool(session).view(time.monotonic() + 180, "ui-shared-release")
    )
    if kind == "candidate":
        repair = load_review()
        version = CandidateVersionBinding.model_validate_json(
            (ROOT / "artifacts/milestone-5/q18-repair-v1/candidate-version.json").read_bytes()
        )
        version.require_review(repair)
        if version.version_id != pins["artifact_version_id"]:
            raise ValueError("candidate version record differs from the shared review")
        checkpoint = verify_candidate_checkpoint(repair, version, session=reader)
    else:
        checkpoint = verify_checkpoint(scope="parity-v1", session=reader)
    stack = reader.client("cloudformation").describe_stacks(
        StackName="enterprise-analytics-dev-agent-runtime"
    )["Stacks"][0]
    template = _template(kind)
    expected = {
        name: str(value["Default"])
        for name, value in template["Parameters"].items()
        if "Default" in value
    }
    expected["ArtifactVersionId"] = pins["artifact_version_id"]
    records = stack.get("Parameters", [])
    actual = {value["ParameterKey"]: value["ParameterValue"] for value in records}
    if len(records) != len(expected) or actual != expected:
        raise ValueError("checkpoint CloudFormation parameter inventory/values differ")
    checkpoint["stack_parameters"] = actual
    make_record(review, checkpoint, kind=kind)
    return checkpoint


def verify_local_release(root: Path, review: SharedReview, canonical_dir: Path) -> dict[str, Any]:
    """Verify source/dependency/canonical bytes without creating SDK clients."""
    from infrastructure.agentcore.source_audit import compare_archive

    root = root.resolve()
    _pins(review, "candidate")
    archive, _ = _paths("candidate", root=root)
    source = compare_archive(root, archive, review.archive_sha256)
    if not source["same_runtime_sources"] or source["local_source_sha256"] != review.source_sha256:
        raise ValueError("local shared agent source differs from the accepted frozen candidate")
    lock = root / "poetry.lock"
    if digest(lock) != LOCK_SHA256:
        raise ValueError("Poetry lockfile differs from the frozen candidate build")
    manifest = json.loads(archive.with_suffix(".manifest.json").read_bytes())
    committed = json.loads((root / "evaluations/retail-v1/q18-build-manifest.json").read_bytes())
    if manifest != committed or manifest["zip_sha256"] != review.archive_sha256:
        raise ValueError("candidate build manifest differs from its immutable review")
    locked = tomllib.loads(lock.read_text())["package"]
    dependencies = []
    for dependency in manifest["dependencies"]:
        name, version = dependency["name"], dependency["version"]
        matches = [item for item in locked if item["name"] == name and item["version"] == version]
        if len(matches) != 1 or metadata.version(name) != version:
            raise ValueError("local dependency version differs from the frozen candidate")
        if "sha256:" + dependency["sha256"] not in {item["hash"] for item in matches[0]["files"]}:
            raise ValueError("candidate dependency checksum is not in the committed lockfile")
        dependencies.append({"name": name, "version": version})
    if len(dependencies) != 13:
        raise ValueError("candidate dependency inventory differs from its accepted build")
    canonical = verify_local(canonical_dir)
    provenance = json.loads((root / "evaluations/retail-v1/oracle-provenance.json").read_bytes())
    local_provenance = json.loads((canonical_dir / "provenance.json").read_bytes())
    if (
        digest(canonical_dir / "manifest.json") != review.canonical_manifest_sha256
        or local_provenance["manifest"] != provenance["manifest"]
        or local_provenance["objects"] != provenance["objects"]
    ):
        raise ValueError("local canonical publication identities differ from the frozen provenance")
    suite_path = root / "evaluations/retail-v1/questions.json"
    expected_path = root / "evaluations/retail-v1/expected-results.json"
    suite = load_suite(suite_path)
    golden = load_goldens(expected_path, suite)
    frozen = verify_frozen_inputs(
        suite_path, expected_path, root / "evaluations/retail-v1/oracle-provenance.json", golden
    )
    return {
        "source": source,
        "dependencies": dependencies,
        "poetry_lock_sha256": LOCK_SHA256,
        "canonical_manifest_sha256": review.canonical_manifest_sha256,
        "canonical_objects": local_provenance["objects"],
        "canonical_row_counts": {
            name: table["row_count"] for name, table in canonical["tables"].items()
        },
        "frozen_inputs": frozen,
        "limitations": (
            "Version-equal native macOS/Linux dependencies are not byte-identical platforms."
        ),
    }


def verify_publication(
    review: SharedReview, session: ReadSession, *, root: Path = ROOT
) -> dict[str, Any]:
    """Recheck actual Athena input bindings, not just retained bytes or CFN intent.

    Latest immutable identities must match the verified canonical provenance. Each
    unpartitioned table prefix must contain exactly the one reviewed Parquet part;
    extra objects or pagination fail rather than being omitted from the comparison.
    All SDK operations share the caller's bounded ReadSession and diagnostics.
    """
    if not isinstance(session, ReadSession):
        raise TypeError("publication verification requires a bounded operator read session")
    _pins(review, "candidate")
    manifest_path = root / "evaluations/retail-v1/ready-manifest.json"
    if digest(manifest_path) != review.canonical_manifest_sha256:
        raise ValueError("committed canonical manifest differs from the reviewed publication")
    manifest = json.loads(manifest_path.read_bytes())
    validate_manifest(manifest)
    provenance = json.loads((root / "evaluations/retail-v1/oracle-provenance.json").read_bytes())
    bucket = "enterprise-analytics-dev-453711491609-us-west-2-data"
    if (
        provenance.get("verified") is not True
        or provenance.get("account") != review.target.account
        or provenance.get("region") != review.target.region
        or provenance.get("dataset_version") != review.target.dataset_version
        or set(provenance.get("objects", {})) != set(manifest["tables"])
    ):
        raise ValueError("canonical provenance differs from the reviewed publication scope")
    identities = {"manifest": provenance["manifest"], **provenance["objects"]}
    if (
        identities["manifest"].get("key") != "manifests/retail-v1.json"
        or identities["manifest"].get("sha256") != review.canonical_manifest_sha256
    ):
        raise ValueError("canonical ready manifest identity differs from review")
    for name, table in manifest["tables"].items():
        identity = identities[name]
        if any(
            identity.get(field) != expected
            for field, expected in (
                ("key", table["key"]),
                ("size_bytes", table["size_bytes"]),
                ("sha256", table["sha256"]),
            )
        ):
            raise ValueError("canonical object provenance differs from the ready inventory")
    s3 = session.client("s3")
    heads = {}
    for name, identity in identities.items():
        if (
            identity.get("bucket") != bucket
            or not isinstance(identity.get("version_id"), str)
            or identity["version_id"].casefold() in {"", "null", "unknown"}
            or not isinstance(identity.get("etag"), str)
            or not identity["etag"]
        ):
            raise ValueError("canonical source lacks an immutable reviewed S3 identity")
        # Omit VersionId deliberately: checking an old version would hide drift
        # in the latest objects Athena actually reads from an external table.
        head = s3.head_object(
            Bucket=bucket, Key=identity["key"], ExpectedBucketOwner=review.target.account
        )
        if any(
            head.get(field) != expected
            for field, expected in (
                ("VersionId", identity["version_id"]),
                ("ContentLength", identity["size_bytes"]),
                ("ETag", identity["etag"]),
            )
        ):
            raise ValueError("latest canonical S3 object identity, size or ETag changed")
        heads[name] = {
            "key": identity["key"],
            "version_id": head["VersionId"],
            "size_bytes": head["ContentLength"],
            "etag": head["ETag"],
        }
    prefixes = {}
    for name, table in manifest["tables"].items():
        prefix = table["key"].rsplit("/", 1)[0] + "/"
        listed = s3.list_objects_v2(
            Bucket=bucket, Prefix=prefix, MaxKeys=2, ExpectedBucketOwner=review.target.account
        )
        objects = listed.get("Contents", [])
        if (
            listed.get("IsTruncated") is not False
            or listed.get("NextContinuationToken")
            or not isinstance(objects, list)
            or len(objects) != 1
            or objects[0].get("Key") != table["key"]
            or objects[0].get("Size") != table["size_bytes"]
            or objects[0].get("ETag") != identities[name]["etag"]
        ):
            raise ValueError("Athena source prefix contains unexpected or incomplete objects")
        prefixes[name] = {"prefix": prefix, "reviewed_part": table["key"], "object_count": 1}
    glue = session.client("glue")
    types = {"VARCHAR": "string", "BIGINT": "bigint", "INTEGER": "int", "DATE": "date"}
    tables = {}
    for name, table in manifest["tables"].items():
        identifier = glue_table_name(review.target.dataset_version, name, prefix="ea")
        actual = glue.get_table(
            CatalogId=review.target.account,
            DatabaseName="enterprise_analytics_dev",
            Name=identifier,
        )["Table"]
        descriptor = actual.get("StorageDescriptor", {})
        columns = [(item["Name"], item["Type"]) for item in descriptor.get("Columns", [])]
        expected_columns = [(item["name"], types[item["type"]]) for item in table["columns"]]
        expected_location = f"s3://{bucket}/{prefixes[name]['prefix']}"
        parameters = actual.get("Parameters", {})
        if (
            actual.get("Name") != identifier
            or actual.get("TableType") != "EXTERNAL_TABLE"
            or actual.get("PartitionKeys", []) != []
            or descriptor.get("Location") != expected_location
            or columns != expected_columns
            or descriptor.get("AdditionalLocations", []) != []
            or descriptor.get("SkewedInfo")
            or str(parameters.get("projection.enabled", "false")).lower() != "false"
            or parameters.get("storage.location.template")
            or descriptor.get("InputFormat")
            != "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
            or descriptor.get("OutputFormat")
            != "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
            or descriptor.get("SerdeInfo", {}).get("SerializationLibrary")
            != "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
        ):
            raise ValueError(
                "actual Glue source schema, location or table format differs from review"
            )
        tables[name] = {"name": identifier, "location": expected_location, "columns": columns}
    return {
        "canonical_manifest_sha256": review.canonical_manifest_sha256,
        "latest_heads": heads,
        "source_prefixes": prefixes,
        "glue_tables": tables,
        "verification": (
            "Latest version/size/ETag identities, exact source object sets and Glue bindings"
        ),
    }
