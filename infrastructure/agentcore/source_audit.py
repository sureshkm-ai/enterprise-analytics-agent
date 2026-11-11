"""Compare the local agent/semantic import closure with a reviewed deployment ZIP.

This is an offline source comparison, not evidence that AWS currently runs the ZIP.
Never import or extract archive code. Bind the ZIP checksum/VersionId to a fresh
AWS checkpoint separately before claiming local/deployed code equivalence.
"""

import argparse
import ast
import hashlib
import importlib.util
import json
import zipfile
from collections import deque
from pathlib import Path
from typing import Any

PACKAGE = "enterprise_analytics_agent"
ROOTS = (
    f"{PACKAGE}.hosting.server",
    f"{PACKAGE}.adapters.bedrock_agent",
    f"{PACKAGE}.adapters.duckdb",
)
MAX_MODULE_BYTES = 1024 * 1024


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _module(root: Path, name: str) -> Path | None:
    if name != PACKAGE and not name.startswith(PACKAGE + "."):
        return None
    base = root / "src" / name.replace(".", "/")
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            if not path.resolve().is_relative_to((root / "src").resolve()):
                raise ValueError("source module escapes the selected checkout")
            return path
    return None


def source_inventory(root: Path) -> dict[str, str]:
    """Follow static package imports plus package initializers without executing code."""
    root = root.resolve()
    pending = deque((name, True) for name in ROOTS)
    visited: set[str] = set()
    inventory: dict[str, str] = {}
    while pending:
        name, required = pending.popleft()
        if name in visited:
            continue
        path = _module(root, name)
        if path is None:
            if required and (name == PACKAGE or name.startswith(PACKAGE + ".")):
                raise ValueError(f"required source module is missing: {name}")
            # An imported symbol need not be a module. Do not mark a missing
            # optional candidate visited: a later explicit import must require it.
            continue
        visited.add(name)
        content = path.read_bytes()
        if len(content) > MAX_MODULE_BYTES:
            raise ValueError("source module exceeds the audit size bound")
        inventory[path.relative_to(root / "src").as_posix()] = _sha(content)
        parts = name.split(".")
        pending.extend((".".join(parts[:index]), True) for index in range(1, len(parts)))
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(ast.parse(content, filename=str(path))):
            if isinstance(node, ast.Import):
                pending.extend((item.name, True) for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported = node.module or ""
                if node.level:
                    imported = importlib.util.resolve_name("." * node.level + imported, package)
                pending.append((imported, True))
                pending.extend((f"{imported}.{item.name}", False) for item in node.names)
    entry = root / "infrastructure/agentcore/runtime_entry.py"
    inventory["runtime_entry.py"] = _sha(entry.read_bytes())
    return dict(sorted(inventory.items()))


def compare_archive(root: Path, archive_path: Path, expected_sha256: str) -> dict[str, Any]:
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise ValueError("expected SHA-256 must be 64 lowercase hexadecimal characters")
    with archive_path.open("rb") as stream:
        archive_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    if archive_sha256 != expected_sha256:
        raise ValueError("archive does not match its reviewed checksum")
    inventory = source_inventory(root)
    archived: dict[str, str] = {}
    missing: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            raise ValueError("archive contains duplicate member names")
        for name in inventory:
            if name not in names:
                missing.append(name)
                continue
            item = archive.getinfo(name)
            if item.file_size > MAX_MODULE_BYTES:
                raise ValueError("archive module exceeds the audit size bound")
            archived[name] = _sha(archive.read(item))
    changed = [name for name in inventory if name in archived and archived[name] != inventory[name]]
    return {
        "schema_version": "runtime-source-audit-v1",
        "archive_sha256": archive_sha256,
        "local_source_sha256": _sha(json.dumps(inventory, sort_keys=True).encode()),
        "archived_source_sha256": _sha(json.dumps(archived, sort_keys=True).encode()),
        "source_count": len(inventory),
        "same_runtime_sources": not changed and not missing,
        "changed": changed,
        "missing": missing,
        "local_files": inventory,
        "archived_files": archived,
        "limitations": (
            "Static package import closure and entrypoint only. Does not prove active AWS "
            "artifact, dependencies, configuration, dataset parity, or dynamic imports. "
            "UI/operator modules are not part of this runtime-source equality claim."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        report = compare_archive(args.root, args.archive, args.sha256)
    except (ValueError, OSError, SyntaxError, zipfile.BadZipFile) as exc:
        print(json.dumps({"same_runtime_sources": False, "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["same_runtime_sources"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
