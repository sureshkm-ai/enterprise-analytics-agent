from datetime import date
from pathlib import Path

import pytest

from enterprise_analytics_agent.cli import main
from enterprise_analytics_agent.contracts import QueryMetricResponse


def test_cli_produces_repeatable_versioned_region_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "retail"
    arguments = ["--data-dir", str(directory)]
    assert main(arguments) == 0
    first = capsys.readouterr()
    result = QueryMetricResponse.model_validate_json(first.out)
    assert first.err == ""
    assert result.api_version == "v1"
    assert result.metric_id == "net_revenue"
    assert result.time_range.start == date(2025, 1, 1)
    assert result.time_range.end == date(2025, 4, 1)
    assert {row.dimensions["region"] for row in result.rows} == {"East", "North", "South", "West"}
    assert main(arguments) == 0
    second = capsys.readouterr()
    assert second.out == first.out
    assert second.err == ""


def test_cli_rejects_invalid_date_range_before_creating_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "invalid"
    with pytest.raises(SystemExit) as error:
        main(["--data-dir", str(directory), "--start", "2025-02-01", "--end", "2025-02-01"])
    assert error.value.code == 2
    assert "start must be before exclusive end" in capsys.readouterr().err
    assert not directory.exists()


def test_cli_does_not_accept_model_supplied_tenant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--data-dir", str(tmp_path / "invalid"), "--tenant-id", "forged"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
