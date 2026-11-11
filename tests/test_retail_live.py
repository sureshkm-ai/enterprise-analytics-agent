"""Explicit future M5 gate; default pytest/CI never creates an AWS client here."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from enterprise_analytics_agent.retail_evaluation.runner import LiveRunDependencies


@pytest.fixture(scope="session")
def live_retail_dependencies(pytestconfig: pytest.Config) -> LiveRunDependencies | None:
    """Only a trusted pytest operator plugin can supply a new campaign binding."""
    dependencies = getattr(pytestconfig, "_reviewed_retail_dependencies", None)
    if dependencies is not None and not isinstance(dependencies, LiveRunDependencies):
        raise pytest.UsageError("Reviewed retail dependencies have an invalid type")
    return dependencies


@pytest.mark.retail_live
def test_approved_retail_campaign(
    request: pytest.FixtureRequest, live_retail_dependencies: LiveRunDependencies | None
) -> None:
    from enterprise_analytics_agent.retail_evaluation.runner import main

    reviewed_output = getattr(request.config, "_reviewed_retail_report_dir", None)
    if reviewed_output is not None:
        if live_retail_dependencies is None or not isinstance(reviewed_output, Path):
            raise pytest.UsageError("Reviewed report output requires trusted live dependencies")
        output = reviewed_output
    else:
        output = Path("artifacts/milestone-5/runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    result = main(
        [
            "--invoke-live",
            "--target-config",
            str(request.config.getoption("retail_config")),
            "--report-dir",
            str(output),
        ],
        live_dependencies=live_retail_dependencies,
    )
    assert result == 0, f"Retail campaign failed; preserve {output}, restore base, inspect report"
