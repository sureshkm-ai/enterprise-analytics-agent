# Implementation plan

## Milestone 1: local semantic execution — complete (`64cbea4`)

1. Inspect the repository and active Python environment; preserve existing work.
2. Record architecture boundaries and net revenue assumptions before implementing calculations.
3. Add a Poetry src-layout package, versioned Pydantic v2 contracts, a backend-independent adapter protocol, and a governed metric catalog.
4. Generate six deterministic Parquet tables from a fixed seed and date interval.
5. Implement a local DuckDB snapshot adapter with deduplication, governed dimensions, parameterized values, and trusted-context authorization.
6. Add a CLI demonstrating net revenue by region.
7. Verify independently calculated scenarios for partial refunds, canceled orders, multiple items, duplicate events, empty results, exclusive end boundaries, and authorization. Run pytest, Ruff, mypy, and the CLI; resolve failures and update progress.

## Milestone 2: complete local semantics and CI — acceptance passed, local checkpoint

1. Reconcile documentation with Git and the active `enterprise-analytics` environment; run the unchanged baseline checks and create a feature branch.
2. Document gross sales, unchanged net revenue, distinct order count, aggregate average order value, and physical-return order rate before implementation.
3. Preserve v1 net revenue and add v2 contracts for currency/count/nullable-ratio results, logical grains, and business metadata.
4. Add deterministic physical return events without changing the original six tables for a given seed. Keep six-table snapshots usable; require return data for return rate.
5. Implement all five governed metrics, tenant/region isolation, exact aggregate ratios, final ROUND_HALF_UP rounding, and CLI metric selection while preserving defaults.
6. Add independently calculated regressions for joins, returns versus refunds, ratios, empty/date-boundary cases, authorization, serialization, and v1 compatibility.
7. Add push/PR GitHub Actions CI from current official documentation, with pinned actions/Poetry and locked dependency installation; no AWS credentials.
8. Run all required checks and demonstrate each metric, review the diff, update the four documents and README, and make a local milestone commit. Stop without pushing.

Acceptance: all five metrics and required edge cases pass; v1 net revenue and original generated sales/refunds retain their behavior; missing return data errors clearly; CI runs `poetry check --lock`, pytest, Ruff lint/format, and mypy; all local checks and CLI demonstrations succeed.

## Milestone 3: AWS data layer and Athena adapter with parity tests — not authorized

Prepare the governed AWS data layer and implement Athena behind the semantic interface, with parity tests against local metric fixtures. Verify current official SDK documentation before implementation; address warehouse authorization, credentials, query lifecycle, limits, and observability. No implementation or deployment in milestone 2.

## Milestone 4: Bedrock and AgentCore integration — not authorized

Add the Bedrock agent and AgentCore hosting, binding the four semantic tools to authenticated trusted context and the governed adapters. Verify current official SDK documentation first. No implementation or deployment in milestone 2.

Cube remains a later adapter extension; it is outside milestones 2–4 unless separately requested.
