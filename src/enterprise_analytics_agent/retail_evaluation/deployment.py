"""Offline review of the only approved retail deployment delta."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from enterprise_analytics_agent.retail_evaluation.repair_config import RepairReview

BASE_TEMPLATE_SHA256 = "dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb"
BASE_ASSEMBLY = Path("artifacts/cdk.agentcore.endpoint-fix.out")
TEMPLATE_NAME = "enterprise-analytics-dev-agent-runtime.template.json"
RETAIL_ASSEMBLY = Path("artifacts/milestone-5/cdk.retail.out")
RESTORE_ASSEMBLY = Path("artifacts/milestone-5/cdk.restore.out")
CHANGES = {
    "dataset_version": ("parity-v1", "retail-v1"),
    "tenant_id": ("t1", "retail_demo"),
    "reference_date": ("2025-02-01", "2025-04-01"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def review_templates(base: dict[str, Any], retail: dict[str, Any]) -> dict[str, object]:
    """Reject any delta other than three trusted settings, including extra resources/IAM."""
    changed = deepcopy(retail)
    before_env = base["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"]
    after_env = changed["Resources"]["AnalyticsRuntime"]["Properties"]["EnvironmentVariables"]
    before = json.loads(before_env["ANALYTICS_RUNTIME_CONFIG"])
    after = json.loads(after_env["ANALYTICS_RUNTIME_CONFIG"])
    for key, (original, proposed) in CHANGES.items():
        if before.get(key) != original or after.get(key) != proposed:
            raise ValueError(f"Unexpected trusted configuration change: {key}")
        after[key] = original
    if after != before:
        raise ValueError("Additional trusted runtime configuration changed")
    after_env["ANALYTICS_RUNTIME_CONFIG"] = before_env["ANALYTICS_RUNTIME_CONFIG"]
    if changed != base:
        raise ValueError("Deployment changes resources or properties beyond the reviewed scope")
    return {key: {"before": old, "after": new} for key, (old, new) in CHANGES.items()}


def candidate_review_templates(
    base: dict[str, Any], candidate: dict[str, Any], *, candidate_sha256: str
) -> dict[str, object]:
    """Permit the reviewed retail settings and one new SHA-addressed code object only.

    The VersionId parameter remains unresolved until an approved upload supplies its
    real immutable version. Bucket, permissions, roles, platform and every other
    CloudFormation field must remain exactly equal to the original corrected base.
    """
    if len(candidate_sha256) != 64 or any(
        value not in "0123456789abcdef" for value in candidate_sha256
    ):
        raise ValueError("Candidate artifact checksum is not a SHA-256 digest")
    changed = deepcopy(candidate)
    path = (
        "Resources",
        "AnalyticsRuntime",
        "Properties",
        "AgentRuntimeArtifact",
        "CodeConfiguration",
        "Code",
        "S3",
    )
    original: dict[str, Any] = base
    proposed: dict[str, Any] = changed
    for name in path:
        original = original[name]
        proposed = proposed[name]
    expected = f"releases/{candidate_sha256}/agent.zip"
    if proposed.get("Prefix") != expected or original.get("Prefix") == expected:
        raise ValueError("Candidate must name its new SHA-addressed code key")
    proposed["Prefix"] = original["Prefix"]
    changes = review_templates(base, changed)
    return {**changes, "artifact_key": {"before": original["Prefix"], "after": expected}}


def review_assemblies() -> dict[str, object]:
    base_path = BASE_ASSEMBLY / TEMPLATE_NAME
    restore_path = RESTORE_ASSEMBLY / TEMPLATE_NAME
    retail_path = RETAIL_ASSEMBLY / TEMPLATE_NAME
    if digest(base_path) != BASE_TEMPLATE_SHA256 or digest(restore_path) != BASE_TEMPLATE_SHA256:
        raise ValueError("Corrected base/restoration assembly differs from the frozen checkpoint")
    changes = review_templates(
        json.loads(base_path.read_text()), json.loads(retail_path.read_text())
    )
    return {
        "base_template_sha256": digest(base_path),
        "restore_template_sha256": digest(restore_path),
        "retail_template_sha256": digest(retail_path),
        "changes": changes,
    }


def review_candidate_assemblies(review: RepairReview) -> dict[str, object]:
    """Verify candidate bytes and original restoration bytes before selecting a live target."""
    base_path = BASE_ASSEMBLY / TEMPLATE_NAME
    restoration_path = Path(review.restoration_assembly_path) / TEMPLATE_NAME
    candidate_path = Path(review.candidate_assembly_path) / TEMPLATE_NAME
    if (
        digest(base_path) != BASE_TEMPLATE_SHA256
        or digest(restoration_path) != BASE_TEMPLATE_SHA256
        or digest(Path(review.restoration_artifact_path)) != review.restoration_sha256
    ):
        raise ValueError("Original restoration artifact or assembly differs from its frozen pin")
    if digest(Path(review.candidate_artifact_path)) != review.candidate_sha256:
        raise ValueError("Candidate ZIP differs from the reviewed checksum")
    if digest(candidate_path) != review.candidate_template_sha256:
        raise ValueError("Candidate assembly differs from the reviewed checksum")
    changes = candidate_review_templates(
        json.loads(base_path.read_text()),
        json.loads(candidate_path.read_text()),
        candidate_sha256=review.candidate_sha256,
    )
    return {
        "review_sha256": review.review_sha256,
        "candidate_sha256": review.candidate_sha256,
        "candidate_template_sha256": review.candidate_template_sha256,
        "restoration_sha256": review.restoration_sha256,
        "restoration_template_sha256": BASE_TEMPLATE_SHA256,
        "changes": changes,
    }
