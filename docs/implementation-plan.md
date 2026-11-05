# Implementation plan

## Milestone 1: local semantic execution

1. Inspect the repository and active Python environment; preserve existing work.
2. Record architecture boundaries and net revenue assumptions before implementing calculations.
3. Add a Poetry src-layout package, versioned Pydantic v2 contracts, a backend-independent adapter protocol, and a governed metric catalog.
4. Generate six deterministic Parquet tables from a fixed seed and date interval.
5. Implement a local DuckDB snapshot adapter with deduplication, governed dimensions, parameterized values, and trusted-context authorization.
6. Add a CLI demonstrating net revenue by region.
7. Verify independently calculated scenarios for partial refunds, canceled orders, multiple items, duplicate events, empty results, exclusive end boundaries, and authorization. Run pytest, Ruff, mypy, and the CLI; resolve failures and update progress.

## Later milestones (not implemented)

- Add the Bedrock agent and AgentCore hosting after verifying current official SDK documentation. Map tools to the same semantic contracts and derive authorization from authenticated application context.
- Add an AWS-native governed metrics adapter through Athena, including warehouse authorization, query lifecycle, limits, observability, and production credentials handling.
- Add Cube behind the semantic adapter protocol. Keep Cube-specific modeling and client logic out of agent contracts.
- Extend the governed catalog with additional metrics, currency/time policies, lineage, validation, operational controls, and contract compatibility tests.
