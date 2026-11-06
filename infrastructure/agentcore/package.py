"""Build a deterministic Python 3.12 Linux ARM64 ZIP from the committed Poetry lock."""

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from packaging.markers import Marker, default_environment
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename

from enterprise_analytics_agent.hosting.config import RuntimeSettings

PLATFORMS = (
    "manylinux_2_28_aarch64",
    "manylinux_2_26_aarch64",
    "manylinux_2_17_aarch64",
    "manylinux2014_aarch64",
)
MAX_ZIPPED_BYTES = 250_000_000
MAX_UNZIPPED_BYTES = 750_000_000


def _name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def main_packages(lock_path: Path) -> tuple[dict[str, Any], ...]:
    """Evaluate lock markers for the deployment target, never the macOS build host."""
    lock = tomllib.loads(lock_path.read_text())
    environment = {key: str(value) for key, value in default_environment().items()}
    environment.update(
        os_name="posix",
        sys_platform="linux",
        platform_system="Linux",
        platform_machine="aarch64",
        implementation_name="cpython",
        implementation_version="3.12.0",
        platform_python_implementation="CPython",
        platform_release="",
        platform_version="",
        python_version="3.12",
        python_full_version="3.12.0",
    )
    selected: list[dict[str, Any]] = []
    for package in lock["package"]:
        if "main" not in package["groups"] or package.get("optional", False):
            continue
        marker = package.get("markers")
        if isinstance(marker, dict):
            marker = marker.get("main")
        if marker is not None:
            if not isinstance(marker, str):
                raise ValueError("Unsupported Poetry lock marker shape")
            if not Marker(marker).evaluate(environment):
                continue
        if "source" in package:
            raise ValueError("Deployment requires locked index packages, not local/VCS sources")
        selected.append(package)
    names = [_name(package["name"]) for package in selected]
    if len(set(names)) != len(names):
        raise ValueError("The target has multiple active locked versions of a package")
    return tuple(sorted(selected, key=lambda package: _name(package["name"])))


def write_requirements(lock_path: Path, target: Path) -> None:
    lines = []
    for package in main_packages(lock_path):
        hashes = sorted(
            {record["hash"] for record in package["files"] if record["file"].endswith(".whl")}
        )
        if not hashes:
            raise ValueError(f"No wheel hashes are locked for {package['name']}")
        lines.append(
            f"{package['name']}=={package['version']} "
            + " ".join(f"--hash={value}" for value in hashes)
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n")


def download_wheels(requirements: Path, wheel_dir: Path) -> None:
    wheel_dir.mkdir(parents=True, exist_ok=True)
    arguments = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--cache-dir",
        str(wheel_dir.parent / "pip-cache"),
        "--retries",
        "2",
        "--timeout",
        "30",
        "--require-hashes",
        "--no-deps",
        "--only-binary=:all:",
        "--implementation",
        "cp",
        "--python-version",
        "312",
        "--abi",
        "cp312",
        "--abi",
        "abi3",
        "--abi",
        "none",
    ]
    for platform in PLATFORMS:
        arguments.extend(("--platform", platform))
    arguments.extend(("--dest", str(wheel_dir), "-r", str(requirements)))
    subprocess.run(arguments, check=True)


def _wheel_entries(path: Path) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as wheel:
        for item in wheel.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in item.filename:
                raise ValueError("Wheel contains an unsafe archive path")
            if item.is_dir():
                continue
            parts = name.parts
            if len(parts) >= 3 and parts[0].endswith(".data"):
                if parts[1] == "scripts":
                    # AgentCore launches runtime_entry.py, not dependency CLI
                    # utilities such as jmespath's optional jp.py script.
                    continue
                if parts[1] not in ("purelib", "platlib"):
                    raise ValueError("Wheel requires unsupported non-library installation data")
                name = PurePosixPath(*parts[2:])
            if name.suffix in (".pyc", ".pyo") or "__pycache__" in name.parts:
                continue
            entries[str(name)] = wheel.read(item)
    return entries


def build_archive(
    *,
    lock_path: Path,
    wheel_dir: Path,
    project_wheel: Path,
    runtime_config: Path,
    entrypoint: Path,
    output: Path,
) -> dict[str, object]:
    """Verify every dependency hash and platform before creating the local archive."""
    packages = main_packages(lock_path)
    wheels: list[Path] = []
    inventory: list[dict[str, str]] = []
    remaining = set(wheel_dir.glob("*.whl"))
    supported_tags = set(cpython_tags((3, 12), abis=["cp312"], platforms=PLATFORMS)) | set(
        compatible_tags((3, 12), interpreter="cp312", platforms=PLATFORMS)
    )
    for package in packages:
        prefix = f"{package['name'].replace('-', '_')}-{package['version']}-".lower()
        matches = [path for path in remaining if path.name.lower().startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one target wheel for {package['name']}")
        path = matches[0]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        locked = {record["file"]: record["hash"] for record in package["files"]}
        if locked.get(path.name) != f"sha256:{digest}":
            raise ValueError(f"Wheel is not the checksum-verified locked file: {path.name}")
        _, _, _, wheel_tags = parse_wheel_filename(path.name)
        if not supported_tags.intersection(wheel_tags):
            raise ValueError(f"Wheel is not Python 3.12 Linux ARM64 compatible: {path.name}")
        remaining.remove(path)
        wheels.append(path)
        inventory.append({"name": package["name"], "version": package["version"], "sha256": digest})
    if remaining:
        raise ValueError("Unexpected wheels found; use a clean target wheel directory")
    settings = RuntimeSettings.model_validate_json(runtime_config.read_text())
    entries: dict[str, bytes] = {}
    for wheel in [*wheels, project_wheel]:
        for name, content in _wheel_entries(wheel).items():
            if name in entries and entries[name] != content:
                raise ValueError(f"Wheel contents conflict at {name}")
            entries[name] = content
    for reserved in ("runtime_entry.py", "runtime-config.json"):
        if reserved in entries:
            raise ValueError(f"Project wheel conflicts with deployment file {reserved}")
    entries["runtime_entry.py"] = entrypoint.read_bytes()
    entries["runtime-config.json"] = settings.model_dump_json(indent=2).encode()
    unzipped = sum(len(content) for content in entries.values())
    if unzipped > MAX_UNZIPPED_BYTES:
        raise ValueError("Deployment exceeds AgentCore's unzipped size limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        directories = {
            str(parent) + "/"
            for name in entries
            for parent in PurePosixPath(name).parents
            if str(parent) != "."
        }
        for name in sorted(directories | entries.keys()):
            information = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            directory = name.endswith("/")
            information.create_system = 3
            information.external_attr = (
                stat.S_IFDIR | 0o755 if directory else stat.S_IFREG | 0o644
            ) << 16
            information.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(information, b"" if directory else entries[name])
    if output.stat().st_size > MAX_ZIPPED_BYTES:
        output.unlink()
        raise ValueError("Deployment exceeds AgentCore's zipped size limit")
    result: dict[str, object] = {
        "runtime": "PYTHON_3_12",
        "platform": "linux/arm64",
        "entrypoint": ["runtime_entry.py"],
        "poetry_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        "project_wheel_sha256": hashlib.sha256(project_wheel.read_bytes()).hexdigest(),
        "runtime_config_sha256": hashlib.sha256(entries["runtime-config.json"]).hexdigest(),
        "dependencies": inventory,
        "zip_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "zipped_bytes": output.stat().st_size,
        "unzipped_bytes": unzipped,
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/agentcore/agent.zip"))
    parser.add_argument("--wheel-dir", type=Path, default=Path("artifacts/agentcore/wheels"))
    parser.add_argument("--project-wheel", type=Path)
    parser.add_argument(
        "--offline", action="store_true", help="Use already downloaded locked wheels"
    )
    args = parser.parse_args()
    requirements = args.output.parent / "requirements-linux-arm64.txt"
    write_requirements(Path("poetry.lock"), requirements)
    if not args.offline:
        download_wheels(requirements, args.wheel_dir)
    project_wheel = args.project_wheel
    if project_wheel is None:
        project_dir = args.output.parent / "project-dist"
        subprocess.run(["poetry", "build", "-f", "wheel", "-o", str(project_dir)], check=True)
        built = list(project_dir.glob("*.whl"))
        if len(built) != 1:
            raise ValueError("Expected one project wheel; clean the build directory")
        project_wheel = built[0]
    result = build_archive(
        lock_path=Path("poetry.lock"),
        wheel_dir=args.wheel_dir,
        project_wheel=project_wheel,
        runtime_config=args.config,
        entrypoint=Path("infrastructure/agentcore/runtime_entry.py"),
        output=args.output,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
