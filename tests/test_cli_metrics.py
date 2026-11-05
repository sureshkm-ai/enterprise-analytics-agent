"""The local CLI opts into v2 metrics while preserving the default v1 result."""

import json
from pathlib import Path

import pytest

from enterprise_analytics_agent.cli import main
from enterprise_analytics_agent.contracts import QueryMetricResponse
from enterprise_analytics_agent.contracts_v2 import QueryMetricResponseV2


@pytest.mark.parametrize(
    ("metric_id", "unit", "currency"),
    [
        ("gross_sales", "currency", "USD"),
        ("order_count", "count", None),
        ("average_order_value", "currency", "USD"),
        ("return_rate", "ratio", None),
    ],
)
def test_cli_selects_v2_for_each_new_governed_metric(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    metric_id: str,
    unit: str,
    currency: str | None,
) -> None:
    assert main(["--data-dir", str(tmp_path / metric_id), "--metric", metric_id]) == 0
    output = capsys.readouterr()
    result = QueryMetricResponseV2.model_validate_json(output.out)
    assert output.err == ""
    assert result.api_version == "v2"
    assert result.metric_id == metric_id
    assert result.unit == unit
    assert result.currency == currency
    assert result.group_by == ("region",)
    assert {row.dimensions["region"] for row in result.rows} == {"East", "North", "South", "West"}
    for row in json.loads(output.out)["rows"]:
        assert row["api_version"] == "v2"
        if unit == "count":
            assert type(row["value"]) is int
            assert row["value"] > 0
        else:
            assert isinstance(row["value"], str)
            assert len(row["value"].split(".")[1]) == (6 if unit == "ratio" else 2)


def test_cli_explicit_net_revenue_v2_migration_preserves_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["--data-dir", str(tmp_path / "migration")]
    assert main(arguments) == 0
    original = capsys.readouterr()
    legacy = QueryMetricResponse.model_validate_json(original.out)
    assert main([*arguments, "--metric", "net_revenue", "--api-version", "v2"]) == 0
    migrated = capsys.readouterr()
    current = QueryMetricResponseV2.model_validate_json(migrated.out)
    assert original.err == migrated.err == ""
    assert legacy.api_version == "v1"
    assert current.api_version == "v2"
    assert [(row.dimensions, row.value) for row in legacy.rows] == [
        (row.dimensions, row.value) for row in current.rows
    ]
    assert legacy.time_range.start == current.time_range.start
    assert legacy.time_range.end == current.time_range.end
    assert legacy.definition_version == current.definition_version == "1.0.0"


@pytest.mark.parametrize(
    "metric_id", ["gross_sales", "order_count", "average_order_value", "return_rate"]
)
def test_cli_rejects_new_metrics_under_v1_before_creating_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], metric_id: str
) -> None:
    directory = tmp_path / "invalid-version"
    with pytest.raises(SystemExit) as failure:
        main(["--data-dir", str(directory), "--metric", metric_id, "--api-version", "v1"])
    assert failure.value.code == 2
    assert "v2" in capsys.readouterr().err
    assert not directory.exists()


@pytest.mark.parametrize("argument", [["--metric", "arbitrary_sql"], ["--api-version", "v3"]])
def test_cli_rejects_unknown_metrics_and_versions_before_creating_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argument: list[str]
) -> None:
    directory = tmp_path / "invalid-option"
    with pytest.raises(SystemExit) as failure:
        main(["--data-dir", str(directory), *argument])
    assert failure.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert not directory.exists()


def test_cli_v2_retains_business_date_validation_before_creating_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "invalid-date"
    with pytest.raises(SystemExit) as failure:
        main(
            [
                "--data-dir",
                str(directory),
                "--metric",
                "order_count",
                "--start",
                "2025-02-01",
                "--end",
                "2025-02-01",
            ]
        )
    assert failure.value.code == 2
    assert "start must be before exclusive end" in capsys.readouterr().err
    assert not directory.exists()
