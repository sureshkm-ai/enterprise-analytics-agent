"""Offline review of the only approved retail deployment delta."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

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
