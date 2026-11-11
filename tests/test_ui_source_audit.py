"""Offline code-release comparison must not execute archive or checkout modules."""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from infrastructure.agentcore import source_audit


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    package = tmp_path / "src/enterprise_analytics_agent"
    files = {
        "__init__.py": "# package\n",
        "hosting/__init__.py": "",
        "hosting/server.py": "from .application import app\n",
        "hosting/application.py": "from ..adapters.bedrock_agent import Agent\napp = Agent\n",
        "adapters/__init__.py": "",
        "adapters/bedrock_agent.py": (
            "from enterprise_analytics_agent import catalog\nclass Agent: pass\n"
        ),
        "adapters/duckdb.py": "from enterprise_analytics_agent import catalog\n",
        "catalog.py": "raise RuntimeError('never execute inspected code')\n",
        "ui/server.py": "# outside runtime import closure\n",
    }
    for name, value in files.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    entry = tmp_path / "infrastructure/agentcore/runtime_entry.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("from enterprise_analytics_agent.hosting.server import main\n")
    return tmp_path


def archive(root: Path, *, change: str | None = None, omit: str | None = None) -> tuple[Path, str]:
    path = root / "candidate.zip"
    inventory = source_audit.source_inventory(root)
    with zipfile.ZipFile(path, "w") as output:
        for name in inventory:
            if name == omit:
                continue
            original = root / "src" / name
            if name == "runtime_entry.py":
                original = root / "infrastructure/agentcore/runtime_entry.py"
            output.writestr(name, b"# changed\n" if name == change else original.read_bytes())
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_closure_follows_relative_imports_without_executing(source_tree: Path) -> None:
    inventory = source_audit.source_inventory(source_tree)
    assert "enterprise_analytics_agent/catalog.py" in inventory
    assert "enterprise_analytics_agent/hosting/application.py" in inventory
    assert "enterprise_analytics_agent/__init__.py" in inventory
    assert "enterprise_analytics_agent/ui/server.py" not in inventory
    path, digest = archive(source_tree)
    result = source_audit.compare_archive(source_tree, path, digest)
    assert result["same_runtime_sources"] is True
    assert result["local_source_sha256"] == result["archived_source_sha256"]


@pytest.mark.parametrize("kind", ["change", "omit"])
def test_changed_or_missing_source_blocks_equality(source_tree: Path, kind: str) -> None:
    name = "enterprise_analytics_agent/catalog.py"
    path, digest = archive(source_tree, **{kind: name})
    result = source_audit.compare_archive(source_tree, path, digest)
    assert result["same_runtime_sources"] is False
    assert result["changed" if kind == "change" else "missing"] == [name]


def test_wrong_archive_checksum_fails_before_source_inspection(source_tree: Path) -> None:
    path, _ = archive(source_tree)
    with pytest.raises(ValueError, match="reviewed checksum"):
        source_audit.compare_archive(source_tree / "missing", path, "0" * 64)


def test_missing_root_module_cannot_give_vacuous_match(source_tree: Path) -> None:
    (source_tree / "src/enterprise_analytics_agent/hosting/server.py").unlink()
    with pytest.raises(ValueError, match="required source module"):
        source_audit.source_inventory(source_tree)


def test_source_audit_cli_mismatch_is_nonzero_and_json(
    source_tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, digest = archive(source_tree, change="runtime_entry.py")
    monkeypatch.setattr(
        sys,
        "argv",
        ["source_audit", "--root", str(source_tree), "--archive", str(path), "--sha256", digest],
    )
    assert source_audit.main() == 1
    assert json.loads(capsys.readouterr().out)["changed"] == ["runtime_entry.py"]


@pytest.mark.parametrize(
    "import_line",
    [
        "from enterprise_analytics_agent.catalog import METRICS\n",
        "from ..catalog import METRICS\n",
        "import enterprise_analytics_agent.catalog\n",
    ],
)
def test_deleted_explicit_transitive_module_cannot_shrink_audit(
    source_tree: Path, import_line: str
) -> None:
    # bedrock_agent first references catalog as a possible imported symbol. The
    # explicit DuckDB import must still require it, even if that optional lookup
    # occurred earlier in the traversal. Standard-library imports stay external.
    adapter = source_tree / "src/enterprise_analytics_agent/adapters/duckdb.py"
    adapter.write_text("import json\n" + import_line)
    path, digest = archive(source_tree)
    (source_tree / "src/enterprise_analytics_agent/catalog.py").unlink()
    with pytest.raises(ValueError, match="required source module.*catalog"):
        source_audit.compare_archive(source_tree, path, digest)


@pytest.mark.parametrize("package", ["hosting", "adapters"])
def test_deleted_package_initializer_cannot_shrink_audit(source_tree: Path, package: str) -> None:
    path, digest = archive(source_tree)
    (source_tree / f"src/enterprise_analytics_agent/{package}/__init__.py").unlink()
    with pytest.raises(ValueError, match="required source module"):
        source_audit.compare_archive(source_tree, path, digest)
