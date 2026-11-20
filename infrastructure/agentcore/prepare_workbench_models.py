"""Prepare new workbench model bindings offline; never deploy or approve a campaign.

Existing reviews, artifacts, acceptance records and ledgers are read-only. The
output is a fresh proposal, including exact templates and additional permission
resources for administrator comparison with current effective permissions.
"""

import argparse
import hashlib
import json
import re
import zipfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from aws_cdk import App, Environment
from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_analytics_agent.adapters.bedrock_model_catalog import get_model
from enterprise_analytics_agent.adapters.model_stream_ui import source_digest
from enterprise_analytics_agent.ui.model_streams import StreamingReview
from infrastructure.cdk.streaming_app import (
    ACCOUNT,
    PREFIX,
    REGION,
    StreamingDeploymentConfig,
    StreamingRuntimeStack,
)

SELECTION = "evaluations/bedrock-streaming/models.account-available.json"
BASELINE = "infrastructure/cdk/streaming.workbench.proposed.json"


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["bedrock-workbench-model-selection-v1"]
    requested_models: Annotated[tuple[str, ...], Field(min_length=1)]
    retained_models: tuple[str, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        return self.requested_models + self.retained_models

    @model_validator(mode="after")
    def distinct_models(self) -> Self:
        if len(self.keys) > 10 or len(set(self.keys)) != len(self.keys):
            raise ValueError(
                "Select up to ten distinct models without duplicating retained targets"
            )
        for key in self.keys:
            get_model(key)
        return self


def configuration(
    baseline: StreamingDeploymentConfig, selection: ModelSelection, artifact_sha256: str
) -> StreamingDeploymentConfig:
    """Preserve retail scope/callers; derive exact model grants without AWS discovery."""
    raw = baseline.model_dump(mode="json")
    raw.update(
        artifact_sha256=artifact_sha256,
        artifact_key=f"releases/{artifact_sha256}/agent.zip",
        artifact_version_id=None,
        retained_artifact_keys=[baseline.artifact_key],
    )
    models = []
    for key in selection.keys:
        model = get_model(key)
        if model.transport == "mantle_chat":
            raise ValueError("This selection prepares Bedrock Runtime models only")
        settings = baseline.models[0].settings.model_dump(mode="json")
        settings["model_id"] = model.model_id
        resources: list[str] = []
        regions: tuple[str, ...] = (REGION,)
        if model.model_id.startswith("us."):
            resources.append(
                f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/{model.model_id}"
            )
            # Linked model cards for the US profiles list these Oregon destinations.
            # A fresh GetInferenceProfile read must confirm them before deployment.
            regions = ("us-east-1", "us-east-2", "us-west-2")
        for region in regions:
            resources.extend(model.foundation_model_arns(region))
        models.append(
            {
                "key": key,
                "runtime_name": "enterprise_analytics_stream_" + key.replace("-", "_"),
                "settings": settings,
                "transport": model.transport,
                "model_resource_arns": resources,
            }
        )
    raw["models"] = models
    return StreamingDeploymentConfig.model_validate(raw)


def permission_additions(
    root: Path, baseline: StreamingDeploymentConfig, candidate: StreamingDeploymentConfig
) -> dict[str, Any]:
    """Additions only; do not replace existing grants or query-role trust."""
    old = {model.key for model in baseline.models}
    new = [model for model in candidate.models if model.key not in old]
    roles = [f"arn:aws:iam::{ACCOUNT}:role/{PREFIX}-{model.key}" for model in new]
    runtime_prefix = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:"
    runtimes = [runtime_prefix + f"runtime/{model.runtime_name}-*" for model in new]
    identities = [
        runtime_prefix
        + "workload-identity-directory/default/workload-identity/"
        + model.runtime_name
        + "-*"
        for model in new
    ]
    role_policy = json.loads(
        (root / "infrastructure/cdk/streaming-deployment-policy.roles.proposed.json").read_bytes()
    )
    agent_policy = json.loads(
        (
            root / "infrastructure/cdk/streaming-deployment-policy.agentcore.proposed.json"
        ).read_bytes()
    )
    statements = []
    for original in role_policy["Statement"] + agent_policy["Statement"]:
        resources: Any = {
            "ReadOnlyReviewedStreamingCode": (
                f"arn:aws:s3:::{candidate.code_bucket}/{candidate.artifact_key}"
            ),
            "TenStreamingRuntimeRoles": roles,
            "PassOnlyTenStreamingRuntimeRoles": roles,
            "NamedStreamingRuntimeLifecycle": runtimes,
            "AutomaticStreamingWorkloadIdentities": identities,
            "TagAutomaticStreamingWorkloadIdentities": identities,
        }.get(original["Sid"])
        if not resources:
            continue
        statement = deepcopy(original)
        statement["Sid"] = "AdditionalModels" + original["Sid"]
        statement["Resource"] = resources
        statements.append(statement)
    return {
        "cloudformation_execution_additions": {"Version": "2012-10-17", "Statement": statements},
        "query_role_trust_additions": {
            "Version": "2012-10-17",
            "Statement": (
                [
                    {
                        "Sid": "AllowAdditionalReviewedStreamingRuntimes",
                        "Effect": "Allow",
                        "Principal": {"AWS": roles},
                        "Action": "sts:AssumeRole",
                    }
                ]
                if roles
                else []
            ),
        },
    }


def verify_archive(root: Path, artifact: Path) -> str:
    """Reject a stale ZIP instead of claiming that local and hosted sources match."""
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = json.loads(artifact.with_suffix(".manifest.json").read_bytes())
    if (
        manifest["zip_sha256"] != checksum
        or manifest["zipped_bytes"] != artifact.stat().st_size
        or manifest["poetry_lock_sha256"]
        != hashlib.sha256((root / "poetry.lock").read_bytes()).hexdigest()
    ):
        raise ValueError("The package manifest, lockfile or ZIP differs")
    with zipfile.ZipFile(artifact) as archive:
        source = root / "src"
        members = {
            str(path.relative_to(source)): path.read_bytes()
            for path in (source / "enterprise_analytics_agent").rglob("*")
            if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}
        }
        packaged = [
            name
            for name in archive.namelist()
            if name.startswith("enterprise_analytics_agent/")
            and Path(name).suffix in {".py", ".js", ".css", ".html"}
        ]
        if len(packaged) != len(set(packaged)) or set(packaged) != set(members):
            raise ValueError("The candidate source member inventory differs")
        if any(archive.read(name) != content for name, content in members.items()):
            raise ValueError("The candidate source bytes differ")
        if (
            archive.read("runtime_entry.py")
            != (root / "infrastructure/agentcore/streaming_entry.py").read_bytes()
        ):
            raise ValueError("The candidate is not the streaming entry point")
    return checksum


def prepare(
    root: Path, artifact: Path, output: Path, *, campaign_id: str, expires_at: datetime
) -> StreamingReview:
    root = root.resolve()
    if re.fullmatch(r"bedrock-stream-[a-z0-9-]{1,48}", campaign_id) is None:
        raise ValueError("Use a valid distinct workbench campaign identifier")
    if artifact.resolve() != artifact or not artifact.is_relative_to(root):
        raise ValueError("Use an unaliased candidate artifact inside this checkout")
    if output.resolve() != output or not output.is_relative_to(root) or output.exists():
        raise ValueError("Use a new unaliased output directory inside this checkout")
    if expires_at.tzinfo is None or expires_at <= datetime.now(UTC):
        raise ValueError("Propose an explicit future expiry; old allowances remain closed")
    if (root / "artifacts/bedrock-streaming" / campaign_id).exists():
        raise ValueError("A retained campaign cannot be reused")
    for path in (root / "evaluations/bedrock-streaming").glob("review*.json"):
        if json.loads(path.read_bytes()).get("campaign_id") == campaign_id:
            raise ValueError("A historical campaign cannot be reused")
    selection = ModelSelection.model_validate_json((root / SELECTION).read_bytes())
    baseline = StreamingDeploymentConfig.model_validate_json((root / BASELINE).read_bytes())
    config = configuration(baseline, selection, verify_archive(root, artifact))
    assembly = output / "assembly"
    app = App(outdir=str(assembly), analytics_reporting=False)
    for model in config.models:
        StreamingRuntimeStack(
            app,
            f"{PREFIX}-{model.key}",
            config=config,
            model=model,
            env=Environment(account=ACCOUNT, region=REGION),
            allow_unbound_artifact=True,
        )
    app.synth()
    targets = []
    for model in config.models:
        template = json.loads((assembly / f"{PREFIX}-{model.key}.template.json").read_bytes())
        targets.append(
            {
                "model_key": model.key,
                "runtime_name": model.runtime_name,
                "settings": model.settings.model_dump(mode="json"),
                "template_sha256": hashlib.sha256(
                    json.dumps(template, sort_keys=True).encode()
                ).hexdigest(),
            }
        )
    review = StreamingReview.model_validate(
        {
            "schema_version": "bedrock-model-workbench-v1",
            "campaign_id": campaign_id,
            "recover_requests": True,
            "expires_at": expires_at,
            "artifact_sha256": config.artifact_sha256,
            "artifact_bytes": artifact.stat().st_size,
            "artifact_path": str(artifact.relative_to(root)),
            "artifact_key": config.artifact_key,
            "source_sha256": source_digest(root),
            "canonical_manifest_sha256": (
                "99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797"
            ),
            "targets": targets,
        }
    )
    documents = {
        "deployment.proposed.json": config.model_dump(mode="json"),
        "review.proposed.json": review.model_dump(mode="json"),
        "permissions.additions.proposed.json": permission_additions(root, baseline, config),
        "readiness.json": {
            "status": "offline-proposal",
            "review_sha256": review.sha256,
            "new_models": [
                m.key for m in config.models if m.key not in {v.key for v in baseline.models}
            ],
            "existing_models": [
                m.key for m in config.models if m.key in {v.key for v in baseline.models}
            ],
            "required_before_activation": [
                "Fresh original-checkout runtime/template/policy/publication evidence",
                "Confirm US inference-profile destination model ARNs",
                "Review additive IAM and query-role trust; preserve existing grants",
                "Explicit deployment and fresh 40-attempt approval with the proposed expiry",
                "Bind actual upload VersionId and exact Runtime/DEFAULT releases",
                "Run independent Q18/all-five acceptance; enable only passing models",
            ],
        },
    }
    for name, document in documents.items():
        with (output / name).open("x") as stream:
            stream.write(json.dumps(document, indent=2) + "\n")
    return review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--expires-at", type=datetime.fromisoformat, required=True)
    args = parser.parse_args()
    review = prepare(
        Path.cwd(),
        args.artifact.absolute(),
        args.output.absolute(),
        campaign_id=args.campaign_id,
        expires_at=args.expires_at,
    )
    print(
        json.dumps(
            {
                "status": "offline-proposal",
                "review_sha256": review.sha256,
                "models": [target.model_key for target in review.targets],
            }
        )
    )


if __name__ == "__main__":
    main()
