"""Explicit future M5 gate; default pytest/CI never creates an AWS client here."""

from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.mark.retail_live
def test_approved_retail_campaign(request: pytest.FixtureRequest) -> None:
    from enterprise_analytics_agent.retail_evaluation.runner import main

    output = Path("artifacts/milestone-5/runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    result = main(
        [
            "--invoke-live",
            "--target-config",
            str(request.config.getoption("retail_config")),
            "--report-dir",
            str(output),
        ]
    )
    assert result == 0, f"Retail campaign failed; preserve {output}, restore base, inspect report"
