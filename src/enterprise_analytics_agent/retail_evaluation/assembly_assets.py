"""Offline consistency checks for the reviewed single-stack CDK cloud assemblies.

CDK can deploy a cached template URL instead of reading ``templateFile``. A
template edit therefore must update its asset identity, destinations and stack
URL together. No SDK client, publication or deployment belongs in these helpers.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

STACK = "enterprise-analytics-dev-agent-runtime"
TEMPLATE = STACK + ".template.json"
ASSET_FILE = STACK + ".assets.json"
ASSET_ARTIFACT = STACK + ".assets"
BUCKET = "cdk-hnb659fds-assets-453711491609-us-west-2"
REGION = "us-west-2"
DESTINATION = "453711491609-us-west-2-b94ee4b7"
PUBLISH_ROLE = (
    "arn:${AWS::Partition}:iam::453711491609:"
    "role/cdk-hnb659fds-file-publishing-role-453711491609-us-west-2"
)
_FILES = {
    "manifest.json",
    "cdk.out",
    "tree.json",
    "validation-report.json",
    TEMPLATE,
    ASSET_FILE,
    STACK + ".metadata.json",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("CDK assembly JSON must contain an object: " + path.name)
    return value


def _inspect(
    assembly: Path, expected_asset_hash: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Check complete asset metadata, allowing a deliberately changed template."""
    if re.fullmatch(r"[a-f0-9]{64}", expected_asset_hash) is None:
        raise ValueError("Expected CDK template hash must be a SHA-256 digest")
    if assembly.is_symlink() or not assembly.is_dir():
        raise ValueError("CDK assembly must be a real directory")
    files = list(assembly.rglob("*"))
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError("CDK assembly contains a symlink or unexpected directory")
    names = {str(p.relative_to(assembly)) for p in files}
    # Retained CDK-generated read locks are historical inventory, not payloads.
    extras = {n for n in names - _FILES if re.fullmatch(r"read\.\d+\.\d+\.lock", n) is None}
    if not _FILES <= names or extras:
        raise ValueError("CDK assembly file inventory differs from the reviewed single stack")
    manifest = _json(assembly / "manifest.json")
    assets = _json(assembly / ASSET_FILE)
    metadata = _json(assembly / (STACK + ".metadata.json"))
    template_entries = [
        entry
        for entries in metadata.values()
        if isinstance(entries, list)
        for entry in entries
        if isinstance(entry, dict) and entry.get("type") == "aws:cdk:templateFile"
    ]
    if template_entries != [{"type": "aws:cdk:templateFile", "data": TEMPLATE}]:
        raise ValueError("CDK stack metadata template-file binding differs")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        STACK,
        ASSET_ARTIFACT,
        "Tree",
        "aws-cdk-lib/feature-flag-report",
    }:
        raise ValueError("CDK assembly artifact inventory differs")
    stack = artifacts[STACK]
    properties = stack.get("properties", {})
    if (
        stack.get("type") != "aws:cloudformation:stack"
        or stack.get("environment") != "aws://453711491609/us-west-2"
        or properties.get("templateFile") != TEMPLATE
        or stack.get("additionalMetadataFile") != STACK + ".metadata.json"
        or stack.get("dependencies") != [ASSET_ARTIFACT]
        or properties.get("additionalDependencies") != [ASSET_ARTIFACT]
    ):
        raise ValueError("CDK stack template path, environment or asset dependencies differ")
    if properties.get("stackTemplateAssetObjectUrl") != (
        f"s3://{BUCKET}/{expected_asset_hash}.json"
    ):
        raise ValueError("CDK stack template asset URL differs from the template hash")
    asset_artifact = artifacts[ASSET_ARTIFACT]
    if (
        asset_artifact.get("type") != "cdk:asset-manifest"
        or asset_artifact.get("properties", {}).get("file") != ASSET_FILE
        or manifest.get("version") != assets.get("version")
    ):
        raise ValueError("CDK asset manifest binding or version differs")
    if (
        artifacts["Tree"].get("type") != "cdk:tree"
        or artifacts["Tree"].get("properties", {}).get("file") != "tree.json"
    ):
        raise ValueError("CDK assembly tree binding differs")
    entries = assets.get("files")
    if (
        not isinstance(entries, dict)
        or set(entries) != {expected_asset_hash}
        or assets.get("dockerImages") != {}
        or set(assets) != {"version", "files", "dockerImages"}
    ):
        raise ValueError("CDK template asset identity or asset inventory differs")
    asset = entries[expected_asset_hash]
    if set(asset) != {"displayName", "source", "destinations"} or asset.get("source") != {
        "path": TEMPLATE,
        "packaging": "file",
    }:
        raise ValueError("CDK template asset source path or packaging differs")
    if asset.get("destinations") != {
        DESTINATION: {
            "bucketName": BUCKET,
            "objectKey": expected_asset_hash + ".json",
            "region": REGION,
            "assumeRoleArn": PUBLISH_ROLE,
        }
    }:
        raise ValueError("CDK template asset destination bucket, key, region or role differs")
    return manifest, assets, _sha(assembly / TEMPLATE)


def validate_assembly(assembly: Path, expected_template_sha256: str) -> dict[str, str]:
    """Reject cached-template metadata inconsistent with the reviewed template bytes."""
    _, _, actual = _inspect(assembly, expected_template_sha256)
    if actual != expected_template_sha256:
        raise ValueError("CDK template bytes differ from their reviewed asset hash")
    return {
        "template_sha256": actual,
        "asset_manifest_sha256": _sha(assembly / ASSET_FILE),
        "manifest_sha256": _sha(assembly / "manifest.json"),
        "template_asset_url": f"s3://{BUCKET}/{actual}.json",
    }


def rewrite_template_asset(assembly: Path) -> dict[str, str]:
    """Rebind coherent metadata only in a newly copied, locally edited assembly.

    Callers must preserve retained/reviewed assemblies. Validate all old references
    before changing either file; a malformed or broadened assembly is never repaired.
    """
    entries = _json(assembly / ASSET_FILE).get("files")
    if not isinstance(entries, dict) or len(entries) != 1:
        raise ValueError("Expected exactly one reviewed CDK template file asset")
    old_hash = next(iter(entries))
    manifest, assets, new_hash = _inspect(assembly, old_hash)
    if old_hash != new_hash:
        asset = assets["files"].pop(old_hash)
        asset["destinations"][DESTINATION]["objectKey"] = new_hash + ".json"
        assets["files"][new_hash] = asset
        manifest["artifacts"][STACK]["properties"]["stackTemplateAssetObjectUrl"] = (
            f"s3://{BUCKET}/{new_hash}.json"
        )
        for name, value in (("manifest.json", manifest), (ASSET_FILE, assets)):
            (assembly / name).write_text(json.dumps(value, indent=2) + "\n")
    return validate_assembly(assembly, new_hash)
