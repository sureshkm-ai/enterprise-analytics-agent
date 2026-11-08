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

The user reports `CDKToolkit` and `enterprise-analytics-dev-data-layer` at `CREATE_COMPLETE`, and **66 passed, 458 deselected in 111.94s** from the live command below. Milestone 3 merged through PR #2 at `ae378e4` with successful hosted CI run `42166641840`; PR #3 at `6bf1220` merged its status documentation. Those historical results retain their original attribution. Milestone 4 starts from that main checkout without repeating the data-layer deployment or live parity.

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

The milestone 3 merge/CI handoff is complete. The milestone 4 request below separately authorizes implementation and read-only verification; it does not authorize AWS mutations or billable inference before approval.

## Milestone 4: Bedrock and AgentCore Runtime — implementation authorized, live acceptance pending

1. Inspect the merged main checkout and preserve local work; branch `feat/milestone-4-bedrock-agentcore`, existing Conda Python 3.12/Poetry, required baseline checks. Reconcile milestone 3 status without redeploying it.
2. Verify current official Converse/tool-use and AgentCore requirements. Use an explicit configurable model/profile; verify regional availability and account prerequisites with read-only calls. The selected development profile is `us.amazon.nova-lite-v1:0`, sourced in `us-west-2` and routed to the three verified US regions.
3. Implement a bounded injected-client Converse loop with exactly four v2 semantic tools, matching IDs/multiple calls, validation/error recovery, and iteration/time/token limits. Preserve published v1/v2 schemas and calculations.
4. Render exact numeric answers only from validated semantic results. Include structured results and dataset/metric versions, ask for clarification on ambiguous intent, and anchor relative periods to explicit server configuration.
5. Implement stateless IAM-authenticated development hosting with fixed server-owned tenant/region scope. Reject identity/config/history payload fields. Use workload credentials and refreshable assumption of the existing narrow Athena query role, preserving developer trust.
6. Build a reproducible Poetry-locked Python 3.12 Linux ARM64 ZIP and synthesize separate AgentCore foundation/runtime infrastructure without lookups. Prepare an exact trust-only update for the existing data stack, scoped runtime/model/logging/caller permissions, immutable versioned code upload, and cleanup.
7. Add deterministic offline tests and default-CI infrastructure checks. Prepare explicitly enabled live evaluations using independent authored values across all five metrics, metadata, clarification, boundaries, missing/empty sources, authorization, and sessions; grade tool plans/results rather than prose.
8. Complete code, offline checks, packaging, documentation, and synthesis. Present `docs/agentcore-deployment-plan.md` for approval of exact resource/IAM changes and billable calls. Make a local readiness commit, with no push.
9. **After approval only:** deploy the agreed phases/trust update, upload the approved archive, invoke/evaluate the deployed runtime within the approved usage scope, and record actual evidence. Keep milestone 4 open until all agreed deployed evaluations pass, then update progress and make the completion commit. Do not begin Cube, a UI, or additional AgentCore services.

Current acceptance boundary (2026-11-08): administrator-reported active M4 policy V4 exactly matches pushed `a5b690c`, whose hosted CI runs 42502992593/42502997060 passed separately from live acceptance. Approved corrected recovery was retried once after preserving/deleting the empty failed stack, using the verified retained S3 version. Creation failed on `bedrock-agentcore:TagResource` for the exact default workload-identity directory; complete parent/child CloudTrail messages and submitted Project tag are preserved. Final runtime stack is ROLLBACK_COMPLETE, no matching Runtime, denied identity not found; foundation/data/trust/upload remain intact. A separate directory-only tagging statement with region/account/Project conditions is prepared locally and unapplied, preserving all V4 and M3 grants. This shared-directory exception needs administrator approval/application and recovery continuation. Corrected templates/ZIP remain unchanged and approved. **0/40 Runtime invocations used; Milestone 4 stays open** until warm-up, retention, all live gates and corrected parity-v1 READY/restoration pass. See progress/deployment plan for exact state and next steps.

Cube remains a later adapter extension; it is outside milestones 2–4 unless separately requested.
