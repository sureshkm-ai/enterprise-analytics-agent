"""Small hand-authored accounting fixtures, independent of the synthetic generator."""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from enterprise_analytics_agent.contracts import AuthorizationContext
from enterprise_analytics_agent.data import TABLE_SCHEMAS, DataRow


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-retail-live",
        action="store_true",
        help="Explicitly enable the separately approved M5 retail campaign",
    )
    parser.addoption("--retail-config", help="Reviewed M5 retail target JSON")
    parser.addoption(
        "--run-aws", action="store_true", help="Explicitly enable live AWS parity tests"
    )
    parser.addoption("--aws-config", help="Reviewed development deployment JSON for live AWS tests")
    parser.addoption(
        "--run-agent-live",
        action="store_true",
        help="Explicitly enable approved billable AgentCore/Bedrock evaluations",
    )
    parser.addoption(
        "--agent-config", help="Reviewed operator configuration for deployed-agent evaluations"
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("run_retail_live"):
        from enterprise_analytics_agent.retail_evaluation.models import RetailTarget

        path = config.getoption("retail_config")
        if not path:
            raise pytest.UsageError(
                "--run-retail-live requires --retail-config; no retail acceptance was run"
            )
        try:
            target = RetailTarget.model_validate_json(Path(path).read_text())
            if target.dataset_version != "retail-v1":
                raise ValueError("retail acceptance requires retail-v1")
        except (OSError, ValueError) as exc:
            raise pytest.UsageError(
                f"Retail target configuration is missing or invalid: {exc}"
            ) from exc
    if config.getoption("run_agent_live"):
        from enterprise_analytics_agent.agent.evaluation import LiveAgentConfig

        path = config.getoption("agent_config")
        if not path:
            raise pytest.UsageError(
                "--run-agent-live requires --agent-config; no live agent acceptance was run"
            )
        try:
            LiveAgentConfig.model_validate_json(Path(path).read_text())
        except (OSError, ValueError) as exc:
            raise pytest.UsageError(
                f"Live agent configuration is missing or invalid: {exc}"
            ) from exc
    if config.getoption("run_aws"):
        from enterprise_analytics_agent.adapters.aws_runtime import load_runtime_config

        path = config.getoption("aws_config")
        if not path:
            raise pytest.UsageError("--run-aws requires --aws-config; no live acceptance was run")
        try:
            load_runtime_config(Path(path))
        except Exception as exc:
            raise pytest.UsageError(f"Live AWS configuration is missing or invalid: {exc}") from exc


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    retail_items = [item for item in items if item.get_closest_marker("retail_live")]
    if config.getoption("run_retail_live"):
        if not retail_items:
            raise pytest.UsageError(
                "--run-retail-live selected no retail evaluation; acceptance not run"
            )
    else:
        for item in retail_items:
            item.add_marker(
                pytest.mark.skip(
                    reason="Retail campaign requires approval and --run-retail-live/--retail-config"
                )
            )
    agent_items = [item for item in items if item.get_closest_marker("agent_live")]
    if config.getoption("run_agent_live"):
        if not agent_items:
            raise pytest.UsageError(
                "--run-agent-live selected no agent evaluations; acceptance was not run"
            )
    else:
        for item in agent_items:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "Billable agent evaluations require explicit "
                        "--run-agent-live/--agent-config and deployment approval"
                    )
                )
            )
    live_items = [item for item in items if item.get_closest_marker("aws_integration")]
    if config.getoption("run_aws"):
        if not live_items:
            raise pytest.UsageError(
                "--run-aws selected no live parity tests; acceptance was not run"
            )
        return
    for item in live_items:
        item.add_marker(
            pytest.mark.skip(reason="Live AWS tests require explicit --run-aws/--aws-config")
        )


@pytest.fixture
def context() -> AuthorizationContext:
    return AuthorizationContext(
        principal_id="test-application", tenant_id="t1", allowed_regions=("North", "South")
    )


@pytest.fixture
def snapshot_rows() -> dict[str, list[DataRow]]:
    jan1 = date(2025, 1, 1)
    jan2 = date(2025, 1, 2)
    jan3 = date(2025, 1, 3)
    jan4 = date(2025, 1, 4)
    feb1 = date(2025, 2, 1)
    feb15 = date(2025, 2, 15)
    dec31 = date(2024, 12, 31)
    return {
        "customers": [
            ("t1", "c1", "North customer", "North"),
            ("t1", "c2", "South customer", "South"),
            ("t1", "c3", "East customer", "East"),
            ("t2", "c1", "Other tenant customer", "North"),
        ],
        "products": [
            ("t1", "p1", "First product", "home", 1000),
            ("t1", "p2", "Second product", "food", 800),
            ("t2", "p1", "Other tenant product", "home", 1000),
        ],
        "orders": [
            ("t1", "o1", "c1", jan1, "completed", "USD", "North", "online", 250, 700),
            ("t1", "o2", "c2", jan2, "shipped", "USD", "South", "store", 104, 0),
            ("t1", "o-cancel", "c1", jan3, "canceled", "USD", "North", "online", 800, 0),
            ("t1", "o-pending", "c1", jan3, "pending", "USD", "North", "online", 400, 0),
            ("t1", "o-end", "c1", feb1, "completed", "USD", "North", "online", 56, 0),
            ("t1", "o-before", "c1", dec31, "completed", "USD", "North", "online", 72, 0),
            ("t1", "o-eur", "c1", jan4, "completed", "EUR", "North", "eur-channel", 720, 0),
            ("t1", "o-hidden", "c3", jan4, "completed", "USD", "East", "secret-east", 600, 0),
            ("t2", "o1", "c1", jan1, "completed", "USD", "North", "secret-t2", 8000, 0),
        ],
        "order_items": [
            ("t1", "i1", "o1", "p1", 2, 1000, 300),
            ("t1", "i2", "o1", "p2", 1, 800, 0),
            ("t1", "i3", "o2", "p1", 3, 500, 200),
            ("t1", "i-cancel", "o-cancel", "p1", 1, 10000, 0),
            ("t1", "i-pending", "o-pending", "p1", 1, 5000, 0),
            ("t1", "i-end", "o-end", "p1", 1, 700, 0),
            ("t1", "i-before", "o-before", "p1", 1, 900, 0),
            ("t1", "i-eur", "o-eur", "p1", 1, 9000, 0),
            ("t1", "i-hidden", "o-hidden", "p1", 1, 7500, 0),
            ("t2", "i1", "o1", "p1", 1, 100000, 0),
        ],
        "payments": [
            ("t1", "pay1", "o1", jan1, "captured", 1100, "USD"),
            ("t1", "pay2", "o1", jan1, "captured", 2350, "USD"),
            ("t1", "pay3", "o2", jan2, "pending", 1404, "USD"),
        ],
        "refunds": [
            ("t1", "r1", "i1", feb15, feb15, "approved", 400, "USD"),
            ("t1", "r2", "i1", feb15, feb15, "approved", 150, "USD"),
            ("t1", "r-pending", "i1", jan3, None, "pending", 900, "USD"),
            ("t1", "r-rejected", "i1", jan3, None, "rejected", 777, "USD"),
            ("t1", "r-cancel", "i-cancel", jan4, jan4, "approved", 1000, "USD"),
            ("t1", "r-before", "i-before", feb15, feb15, "approved", 200, "USD"),
            ("t2", "r1", "i1", feb15, feb15, "approved", 5000, "USD"),
        ],
    }


def write_snapshot(directory: Path, rows: dict[str, list[DataRow]]) -> Path:
    """Write exact fixture records; this helper performs no revenue calculations."""
    directory.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        for table, schema in TABLE_SCHEMAS.items():
            definitions = ", ".join(f"{column} {kind}" for column, kind in schema)
            connection.execute(f"CREATE TABLE {table} ({definitions})")
            if rows[table]:
                placeholders = ", ".join("?" for _ in schema)
                connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows[table])
            connection.table(table).write_parquet(str(directory / f"{table}.parquet"))
    return directory


@pytest.fixture
def snapshot_dir(tmp_path: Path, snapshot_rows: dict[str, list[DataRow]]) -> Path:
    return write_snapshot(tmp_path / "fixture", snapshot_rows)
