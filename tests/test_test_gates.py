"""Exercise the real pytest gates in isolated processes without AWS access."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATES = (
    ("aws_integration", "--run-aws", "--aws-config", "selected no live parity tests"),
    ("agent_live", "--run-agent-live", "--agent-config", "selected no agent evaluations"),
    ("retail_live", "--run-retail-live", "--retail-config", "selected no retail evaluation"),
)
OFFLINE = "not aws_integration and not agent_live and not retail_live"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Copy the actual configuration/hooks; keep test bodies authored and inert."""
    target = tmp_path / "project"
    tests = target / "tests"
    tests.mkdir(parents=True)
    shutil.copyfile(ROOT / "pyproject.toml", target / "pyproject.toml")
    shutil.copyfile(ROOT / "tests/conftest.py", tests / "conftest.py")
    # This guard is active before conftest/configuration/collection, unlike a
    # fixture. An accidental client construction can never reach AWS.
    (target / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        "import boto3\n"
        "def refuse(*args, **kwargs):\n"
        "    Path('aws-session-created').write_text('unexpected')\n"
        "    raise AssertionError('AWS session forbidden in gate regression')\n"
        "boto3.Session = refuse\n"
    )
    (tests / "test_authored.py").write_text(
        "from pathlib import Path\n"
        "import pytest\n"
        "def test_offline():\n"
        "    assert 2 + 3 == 5\n"
        "@pytest.mark.aws_integration\n"
        "def test_athena():\n"
        "    Path('aws_integration-executed').write_text('once')\n"
        "@pytest.mark.agent_live\n"
        "def test_agent():\n"
        "    Path('agent_live-executed').write_text('once')\n"
        "@pytest.mark.retail_live\n"
        "def test_retail():\n"
        "    Path('retail_live-executed').write_text('once')\n"
    )
    return target


def run(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment.update(
        PYTHONPATH=os.pathsep.join((str(project), str(ROOT / "src"), str(ROOT))),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        AWS_EC2_METADATA_DISABLED="true",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(project / "pyproject.toml"), "-q", *arguments],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert not (project / "aws-session-created").exists(), result.stdout + result.stderr
    return result


def config_file(project: Path, marker: str) -> Path:
    if marker == "aws_integration":
        target = project / "aws.json"
        shutil.copyfile(ROOT / "infrastructure/cdk/config.development.json", target)
        return target
    import json

    target = project / (marker + ".json")
    target.write_text(
        json.dumps(
            {
                "profile": "analytics-dev",
                "account": "453711491609",
                "region": "us-west-2",
                "runtime_arn": (
                    "arn:aws:bedrock-agentcore:us-west-2:453711491609:"
                    "runtime/enterprise_analytics_dev_agent-HlWywlG60h"
                ),
                "qualifier": "DEFAULT",
                "model_id": "us.amazon.nova-lite-v1:0",
                "dataset_version": "retail-v1" if marker == "retail_live" else "parity-v1",
                "reference_date": "2025-04-01" if marker == "retail_live" else "2025-02-01",
            }
        )
    )
    return target


def test_default_ci_selection_is_explicitly_offline_with_no_skips(project: Path) -> None:
    result = run(project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 3 deselected" in result.stdout
    assert "skipped" not in result.stdout
    assert not list(project.glob("*-executed"))


@pytest.mark.parametrize("marker,flag,config,message", GATES)
def test_selected_live_suite_without_opt_in_cannot_be_green(
    project: Path, marker: str, flag: str, config: str, message: str
) -> None:
    result = run(project, "-o", "addopts=", "--fail-on-skip", "-m", marker)
    assert result.returncode == pytest.ExitCode.TESTS_FAILED, result.stdout + result.stderr
    assert "Selected tests skipped: verification is incomplete" in result.stdout
    assert "1 skipped" in result.stdout
    assert not list(project.glob("*-executed"))


@pytest.mark.parametrize("marker,flag,config,message", GATES)
def test_explicit_live_opt_in_requires_configuration_before_any_test(
    project: Path, marker: str, flag: str, config: str, message: str
) -> None:
    result = run(project, "-o", "addopts=", "--fail-on-skip", flag, "-m", marker)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert f"{flag} requires {config}" in result.stderr
    assert not list(project.glob("*-executed"))


@pytest.mark.parametrize("marker,flag,config,message", GATES)
def test_opt_in_with_valid_config_but_no_selected_suite_is_an_error(
    project: Path, marker: str, flag: str, config: str, message: str
) -> None:
    path = config_file(project, marker)
    result = run(
        project,
        "-o",
        "addopts=",
        "--fail-on-skip",
        flag,
        f"{config}={path}",
        "-m",
        OFFLINE,
    )
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert message in result.stderr
    assert not list(project.glob("*-executed"))


@pytest.mark.parametrize("marker,flag,config,message", GATES)
def test_valid_explicit_selection_reaches_authored_suite_without_skipping(
    project: Path, marker: str, flag: str, config: str, message: str
) -> None:
    path = config_file(project, marker)
    result = run(
        project,
        "-o",
        "addopts=",
        "--fail-on-skip",
        flag,
        f"{config}={path}",
        "-m",
        marker,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 3 deselected" in result.stdout
    assert "skipped" not in result.stdout
    assert (project / f"{marker}-executed").read_text() == "once"
    assert len(list(project.glob("*-executed"))) == 1


def test_an_unexpected_offline_skip_fails_the_default_ci_run(project: Path) -> None:
    (project / "tests/test_unexpected.py").write_text(
        "import pytest\ndef test_unexpected():\n    pytest.skip('authored unexpected skip')\n"
    )
    result = run(project)
    assert result.returncode == pytest.ExitCode.TESTS_FAILED, result.stdout + result.stderr
    assert "Selected tests skipped: verification is incomplete" in result.stdout
    assert "1 passed, 1 skipped, 3 deselected" in result.stdout
