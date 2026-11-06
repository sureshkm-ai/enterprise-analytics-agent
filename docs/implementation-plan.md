# Implementation plan

## Milestone 1: local semantic execution — complete (`64cbea4`)

1. Inspect the repository and active Python environment; preserve existing work.
2. Record architecture boundaries and net revenue assumptions before implementing calculations.
3. Add a Poetry src-layout package, versioned Pydantic v2 contracts, a backend-independent adapter protocol, and a governed metric catalog.
4. Generate six deterministic Parquet tables from a fixed seed and date interval.
5. Implement a local DuckDB snapshot adapter with deduplication, governed dimensions, parameterized values, and trusted-context authorization.
6. Add a CLI demonstrating net revenue by region.
7. Verify independently calculated scenarios for partial refunds, canceled orders, multiple items, duplicate events, empty results, exclusive end boundaries, and authorization. Run pytest, Ruff, mypy, and the CLI; resolve failures and update progress.

## Milestone 2: complete local semantics and CI — merged and hosted CI verified

1. Reconcile documentation with Git and the active `enterprise-analytics` environment; run the unchanged baseline checks and create a feature branch.
2. Document gross sales, unchanged net revenue, distinct order count, aggregate average order value, and physical-return order rate before implementation.
3. Preserve v1 net revenue and add v2 contracts for currency/count/nullable-ratio results, logical grains, and business metadata.
4. Add deterministic physical return events without changing the original six tables for a given seed. Keep six-table snapshots usable; require return data for return rate.
5. Implement all five governed metrics, tenant/region isolation, exact aggregate ratios, final ROUND_HALF_UP rounding, and CLI metric selection while preserving defaults.
6. Add independently calculated regressions for joins, returns versus refunds, ratios, empty/date-boundary cases, authorization, serialization, and v1 compatibility.
7. Add push/PR GitHub Actions CI from current official documentation, with pinned actions/Poetry and locked dependency installation; no AWS credentials.
8. Run all required checks and demonstrate each metric, review the diff, update the four documents and README, and make a local milestone commit. Stop without pushing.

Acceptance: all five metrics and required edge cases pass; v1 net revenue and original generated sales/refunds retain their behavior; missing return data errors clearly; CI runs `poetry check --lock`, pytest, Ruff lint/format, and mypy; all local checks and CLI demonstrations succeed.

## Milestone 3: AWS data layer and Athena adapter with parity tests — development implementation, deployment, and live validation passed

The user reports `CDKToolkit` and `enterprise-analytics-dev-data-layer` at `CREATE_COMPLETE`, and **66 passed, 458 deselected in 111.94s** from the live command below. These are user-executed results, not operations rerun for this documentation update. The implementation and cancellation fix are committed through `ae68d2c`; this documentation checkpoint records the deployment/validation handoff. Hosted CI is recorded for readiness commit `7edd010`; confirmation for the current feature revision, final PR review, and merge remain outstanding. Development acceptance does not establish production readiness or authorize milestone 4.

The implementation sequence and approval gates were:

1. Preserve local work, reconcile milestone 2 merge/CI evidence, reuse `feat/milestone-3-athena`, verify the existing Conda/Poetry environment, and run baseline checks.
2. Select an explicit development profile; verify account/region using read-only AWS calls. Never fall back silently to the default profile.
3. Define Python CDK v2 infrastructure with private encrypted retained source storage, separate expiring result storage, explicit version-scoped Glue schemas, enforced Athena workgroup settings/scan limit/monitoring, and separate loader/query roles. Synthesis must not need AWS lookups.
4. Prepare validated canonical snapshots and manifests, preserving absent versus empty returns and legacy six-table support. Publish source files and checksums before making a ready manifest visible.
5. Implement all semantic operations through Athena without changing public v1/v2 contracts or metric definitions. Use governed identifiers, encoded execution parameters, exact numeric translation, bounded/retried query lifecycle, cancellation, pagination, and internal diagnostics.
6. Add offline unit/CDK tests and explicitly enabled live parity tests against DuckDB and independently calculated fixture expectations. Missing live configuration must fail, not silently skip.
7. Finish offline code, documentation, checks, and synthesis. Present account/profile/region, resources, IAM, costs, commands, and cleanup for approval; bootstrap is part of deployment.
8. **Only after deployment approval:** bootstrap/deploy the agreed development resources, publish snapshots, and run live parity. Keep the milestone incomplete until these tests pass. Record readiness separately from deployment/live evidence; make local commits without pushing.

Configured development profile: `analytics-dev`, account `453711491609`, region `us-west-2`, previously verified read-only. The successful reported live run satisfies the development parity gate; prior local checks cover the current implementation and cancellation regressions. Full evidence and remaining handoff work are in [progress](progress.md). The user authorized the local documentation commit; further AWS operations, infrastructure changes, and pushes remain outside this task.

User-executed live validation command, from the repository root:

```sh
poetry run pytest tests --run-aws --aws-config=infrastructure/cdk/config.development.json -m aws_integration -q
```

The documentation diff was reviewed with no actionable findings. Next: the user can push the local documentation checkpoint when ready, confirm hosted CI for that revision, and finish PR review/merge. Do not restart deployment or begin Bedrock, AgentCore, or Cube work under this request.

## Milestone 4: Bedrock and AgentCore integration — not authorized

Add the Bedrock agent and AgentCore hosting, binding the four semantic tools to authenticated trusted context and the governed adapters. Verify current official SDK documentation first. No implementation or deployment in milestone 2.

Cube remains a later adapter extension; it is outside milestones 2–4 unless separately requested.
