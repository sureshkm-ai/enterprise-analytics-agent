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

## Milestone 4: Bedrock and AgentCore Runtime — implemented, deployed, live-validated, merged and hosted CI verified

1. Inspect the merged main checkout and preserve local work; branch `feat/milestone-4-bedrock-agentcore`, existing Conda Python 3.12/Poetry, required baseline checks. Reconcile milestone 3 status without redeploying it.
2. Verify current official Converse/tool-use and AgentCore requirements. Use an explicit configurable model/profile; verify regional availability and account prerequisites with read-only calls. The selected development profile is `us.amazon.nova-lite-v1:0`, sourced in `us-west-2` and routed to the three verified US regions.
3. Implement a bounded injected-client Converse loop with exactly four v2 semantic tools, matching IDs/multiple calls, validation/error recovery, and iteration/time/token limits. Preserve published v1/v2 schemas and calculations.
4. Render exact numeric answers only from validated semantic results. Include structured results and dataset/metric versions, ask for clarification on ambiguous intent, and anchor relative periods to explicit server configuration.
5. Implement stateless IAM-authenticated development hosting with fixed server-owned tenant/region scope. Reject identity/config/history payload fields. Use workload credentials and refreshable assumption of the existing narrow Athena query role, preserving developer trust.
6. Build a reproducible Poetry-locked Python 3.12 Linux ARM64 ZIP and synthesize separate AgentCore foundation/runtime infrastructure without lookups. Prepare an exact trust-only update for the existing data stack, scoped runtime/model/logging/caller permissions, immutable versioned code upload, and cleanup.
7. Add deterministic offline tests and default-CI infrastructure checks. Prepare explicitly enabled live evaluations using independent authored values across all five metrics, metadata, clarification, boundaries, missing/empty sources, authorization, and sessions; grade tool plans/results rather than prose.
8. Complete code, offline checks, packaging, documentation, and synthesis. Present `docs/agentcore-deployment-plan.md` for approval of exact resource/IAM changes and billable calls. Make a local readiness commit, with no push.
9. **After approval only:** deploy the agreed phases/trust update, upload the approved archive, invoke/evaluate the deployed runtime within the approved usage scope, and record actual evidence. Keep milestone 4 open until all agreed deployed evaluations pass, then update progress and make the completion commit. Do not begin Cube, a UI, or additional AgentCore services.

Completed development acceptance (2026-11-08): strict administrator active-report gates passed for v5 and reviewed policy SHA `ac2942537a6d917b899d3a156efd328953d6176f152b9db925b5e5a13c104419`. With explicit `analytics-dev` account/region verification, preserved/deleted only the empty failed runtime stack and deployed the retained corrected assembly/code version. Warm-up and all **24 live tests (18 + 3 + 3)** passed using **28/40** invocations. Legacy and empty-return variants ran on versions 2/3; corrected `parity-v1` was restored and Runtime/DEFAULT are READY on version **4**, stack UPDATE_COMPLETE. Both policies, seven-day retention, retained foundation/data/query trust, exact templates and pinned S3 version verify. No new IAM change, package rebuild/upload, bootstrap or dataset publication was performed. Milestone 4 is complete for the agreed development scope and merged into main through [PR #4](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/4) on November 8, 2026, at [`47c3afc1dd948fa8ddcb074151b9f22af31dad48`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/47c3afc1dd948fa8ddcb074151b9f22af31dad48). Completion commit [`51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf) passed [push CI 42515746487](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515746487) and [PR CI 42515722610](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515722610); the merge passed [main CI 42516820774](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42516820774). These hosted results are separate from live acceptance and do not cover this new documentation-only commit. Historical failures, commands and evidence remain in progress/deployment plan. No next milestone is started.

## Milestone 5: repeatable retail demonstration and answer-quality evaluation — proposed, planning only

The concrete [Milestone 5 plan](milestone-5-plan.md) records inspected implementation gaps, a question CLI, a versioned 34-case retail question set plus two-request session sequence, independent golden-result provenance, report fields, offline checks and proposed live acceptance/restoration gates. Current authorization covers inspection/planning and a local documentation commit only; application changes, AWS calls, deployment, IAM changes and invocations are not authorized.

1. Preserve Milestone 4 completion/merge/CI evidence and its immutable **28/40** ledger. Main `d7e0f19` contains PR #4's merge `47c3afc` and PR #5's documentation handoff `39523f4`; the new branch is `feat/milestone-5-retail-evaluation`.
2. After a separate offline implementation request, add a question-only typed CLI and retail evaluator without changing analytics-demo, metric definitions, public schemas or existing M4 expectations. Freeze reviewed independent expectations before any model run.
3. Verify published canonical retail input provenance under later read-only approval: local raw Parquet bytes differ from the canonical manifest, so raw files are not publication checksum evidence. Build an independent item/order calculation ledger and literal results; no adapter/generator-derived oracle.
4. Prepare separate trusted retail settings: dataset `retail-v1`, tenant `retail_demo`, North/South, reference date `2025-04-01`. Dataset-only override with parity tenant `t1` would return empty results. Reuse the pinned ZIP/version, model/profile/query role; expected deployment is an environment-only update to the existing Runtime stack, with no IAM or data-layer change.
5. Complete required offline checks and review the environment diff/restore proposal before requesting deployment/live approval. Propose a new **40-call M5 budget**, separate from M4: warm-up 1 + single cases 34 + session requests 2 + restored parity smoke 1 + reserve 2. No M5 invocation is approved or used now.
6. Future live acceptance requires all frozen numeric/request/security and clarification gates, complete diagnostics/reporting, the agreed latency target, and restoration of corrected parity-v1 scope/configuration with READY matching live/latest versions. Restoration creates a later Runtime version; preserve M4's version-4 evidence as historical. Do not mark M5 complete before all gates pass.

Exact next task: review the proposal and authorize offline implementation, beginning with versioned case/target/report contracts and handwritten-fixture proofs for the independent oracle. Canonical S3 input verification and runtime changes/calls require separate later authorization. No next milestone is started by this plan.

Cube remains a later adapter extension; it is outside milestones 2–5 unless separately requested.
