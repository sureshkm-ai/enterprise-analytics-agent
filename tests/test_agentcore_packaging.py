"""Authored wheels prove deterministic packaging without downloads or AWS."""

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from infrastructure.agentcore.package import build_archive, main_packages, write_requirements


def write_wheel(path: Path, files: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


@pytest.fixture
def package_inputs(tmp_path: Path) -> dict[str, Path]:
    wheels = tmp_path / "wheels"
    wheel = write_wheel(
        wheels / "fixture_dependency-1.0-py3-none-any.whl", {"dependency.py": "x = 1\n"}
    )
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    lock = tmp_path / "poetry.lock"
    lock.write_text(
        '[[package]]\nname="fixture-dependency"\nversion="1.0"\ngroups=["main"]\n'
        f'files=[{{file="{wheel.name}",hash="sha256:{digest}"}}]\n'
        '[[package]]\nname="dev-only"\nversion="9"\ngroups=["dev"]\nfiles=[]\n'
        '[[package]]\nname="mac-only"\nversion="9"\ngroups=["main"]\n'
        "markers=\"sys_platform == 'darwin'\"\nfiles=[]\n"
    )
    project = write_wheel(tmp_path / "project-0.1-py3-none-any.whl", {"project/__init__.py": ""})
    config = tmp_path / "runtime.json"
    config.write_text(Path("infrastructure/agentcore/runtime.example.json").read_text())
    entrypoint = tmp_path / "entry.py"
    entrypoint.write_text("print('entrypoint')\n")
    return {
        "lock_path": lock,
        "wheel_dir": wheels,
        "project_wheel": project,
        "runtime_config": config,
        "entrypoint": entrypoint,
        "output": tmp_path / "agent.zip",
    }


def test_target_markers_and_requirements_exclude_development_dependencies(
    package_inputs: dict[str, Path], tmp_path: Path
) -> None:
    packages = main_packages(package_inputs["lock_path"])
    assert [package["name"] for package in packages] == ["fixture-dependency"]
    target = tmp_path / "requirements.txt"
    write_requirements(package_inputs["lock_path"], target)
    assert target.read_text().startswith("fixture-dependency==1.0 --hash=sha256:")
    assert "dev-only" not in target.read_text() and "mac-only" not in target.read_text()


def test_archive_is_reproducible_and_has_correct_entrypoint_and_permissions(
    package_inputs: dict[str, Path], tmp_path: Path
) -> None:
    first = build_archive(**package_inputs)
    second = build_archive(**(package_inputs | {"output": tmp_path / "second.zip"}))
    assert first["zip_sha256"] == second["zip_sha256"]
    assert first["runtime"] == "PYTHON_3_12"
    assert first["platform"] == "linux/arm64"
    with zipfile.ZipFile(package_inputs["output"]) as archive:
        assert "runtime_entry.py" in archive.namelist()
        assert "runtime-config.json" in archive.namelist()
        assert json.loads(archive.read("runtime-config.json"))["tenant_id"] == "t1"
        for item in archive.infolist():
            assert stat.S_IMODE(item.external_attr >> 16) == (0o755 if item.is_dir() else 0o644)
            assert item.date_time == (1980, 1, 1, 0, 0, 0)


def test_modified_wheel_is_rejected(package_inputs: dict[str, Path]) -> None:
    wheel = next(package_inputs["wheel_dir"].glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"modified")
    with pytest.raises(ValueError, match="checksum-verified"):
        build_archive(**package_inputs)


def test_unexpected_wheels_are_rejected(package_inputs: dict[str, Path]) -> None:
    write_wheel(package_inputs["wheel_dir"] / "unexpected-1-py3-none-any.whl", {})
    with pytest.raises(ValueError, match="Unexpected wheels"):
        build_archive(**package_inputs)


def test_wrong_platform_wheel_is_rejected(package_inputs: dict[str, Path]) -> None:
    original = next(package_inputs["wheel_dir"].glob("*.whl"))
    wrong = original.with_name("fixture_dependency-1.0-cp312-cp312-macosx_11_0_arm64.whl")
    original.rename(wrong)
    package_inputs["lock_path"].write_text(
        package_inputs["lock_path"].read_text().replace(original.name, wrong.name)
    )
    with pytest.raises(ValueError, match="Linux ARM64"):
        build_archive(**package_inputs)


def test_wrong_python_abi_is_rejected(package_inputs: dict[str, Path]) -> None:
    original = next(package_inputs["wheel_dir"].glob("*.whl"))
    wrong = original.with_name("fixture_dependency-1.0-cp313-cp313-manylinux2014_aarch64.whl")
    original.rename(wrong)
    package_inputs["lock_path"].write_text(
        package_inputs["lock_path"].read_text().replace(original.name, wrong.name)
    )
    with pytest.raises(ValueError, match="Python 3.12"):
        build_archive(**package_inputs)


def test_archive_paths_cannot_escape(package_inputs: dict[str, Path]) -> None:
    write_wheel(package_inputs["project_wheel"], {"../escape.py": ""})
    with pytest.raises(ValueError, match="unsafe archive path"):
        build_archive(**package_inputs)


def test_dependency_cli_scripts_are_not_needed_by_the_runtime(
    package_inputs: dict[str, Path],
) -> None:
    write_wheel(
        package_inputs["project_wheel"],
        {"project/__init__.py": "", "project-0.1.data/scripts/unused.py": ""},
    )
    build_archive(**package_inputs)
    with zipfile.ZipFile(package_inputs["output"]) as archive:
        assert "project/__init__.py" in archive.namelist()
        assert not any("unused.py" in name for name in archive.namelist())
