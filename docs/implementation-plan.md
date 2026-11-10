# Implementation plan

**Milestones 1–5 are complete for the agreed development proof of concept.** M5 completion [`7905d13`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/7905d13f59e13d0b5a1b11231348721471a19411) merged through [PR #6](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/6) on **November 10, 2026**, at [`c0d2c5a569e2d242bf840a715c31050888b579ab`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/c0d2c5a569e2d242bf840a715c31050888b579ab). [Main CI 42872516193](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42872516193) passed for that exact merge. Further development requires a separately defined scope; no production-readiness or new-milestone claim follows from this closeout.

## Follow-on scope: local testing UI

The separately authorized shared-code UI implementation is offline ready. Default
playground remains deterministic/AWS-free. Local agent uses the existing
BedrockAnalyticsAgent with canonical DuckDB data; AWS uses the same class with Athena.
Three modes, cost notices, strict release records, persistent shared question/SDK
counting, offline paired grading and bounded deploy/rollback workflow are implemented.
All original metric definitions, contracts, frozen data and historical budgets remain
unchanged. Actual verification is in [progress](progress.md).

Source/dependency/data audits match the accepted frozen candidate; no rebuild/upload
is needed. Read-only AWS checks find original Runtime/DEFAULT READY v12, not the
matching candidate. Canonical bytes/current S3 prefixes/Glue bindings verify. Denied
IAM inspection proves no permission gap; administrator evidence is pending.

Next gate: compare administrator evidence, then seek separate approval of the
[concrete proposal](ui-shared-code-live.md) and review JSON. Proposed maximum 20
question attempts (18 paired + Q18 verification + protected original rollback),
expiring 2026-11-11T23:59:00Z, entirely separate from M1–M5 histories. Success leaves
the matching candidate/retail deployment; failure requires original restoration.
No deployment, upload, IAM change or billable call is authorized by offline readiness.

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

Completed development acceptance (2026-11-08): strict administrator active-report gates passed for v5 and reviewed policy SHA `ac2942537a6d917b899d3a156efd328953d6176f152b9db925b5e5a13c104419`. With explicit `analytics-dev` account/region verification, preserved/deleted only the empty failed runtime stack and deployed the retained corrected assembly/code version. Warm-up and all **24 live tests (18 + 3 + 3)** passed using **28/40** invocations. Legacy and empty-return variants ran on versions 2/3; corrected `parity-v1` was restored and Runtime/DEFAULT are READY on version **4**, stack UPDATE_COMPLETE. Both policies, seven-day retention, retained foundation/data/query trust, exact templates and pinned S3 version verify. No new IAM change, package rebuild/upload, bootstrap or dataset publication was performed. Milestone 4 is complete for the agreed development scope and merged into main through [PR #4](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/4) on November 8, 2026, at [`47c3afc1dd948fa8ddcb074151b9f22af31dad48`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/47c3afc1dd948fa8ddcb074151b9f22af31dad48). Completion commit [`51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf) passed [push CI 42515746487](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515746487) and [PR CI 42515722610](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515722610); the merge passed [main CI 42516820774](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42516820774). These M4 hosted results cover their named commits and are separate from M5 live acceptance. Historical failures, commands and evidence remain in progress/deployment plan. No next milestone is started.

## Milestone 5: repeatable retail demonstration and answer-quality evaluation — complete; merged and hosted CI verified

Approved recovery at `f223877` passed the Q18 probe/warm-up, **36/36 unchanged suite requests**, full reporting/security/session gates and original-restoration smoke. Candidate **v11**; restored original Runtime/DEFAULT **READY v12**, runtime stack UPDATE_COMPLETE. New usage **38/38**, aggregate repair **40/40**; all historical ledgers and frozen inputs unchanged. Exact results, fresh offline verification and f223877 push/PR CI links are in [progress](progress.md). M5 is complete for the agreed development proof of concept and merged through PR #6 at `c0d2c5a569e2d242bf840a715c31050888b579ab` on November 10, 2026, with successful [main CI 42872516193](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42872516193). These hosted results cover the merge, not this documentation closeout. The v12 state is preserved live-window evidence; no AWS checks were repeated for closeout. The sequence below preserves earlier preparation and failed attempts.

The approved [plan](milestone-5-plan.md) is implemented for local review on `feat/milestone-5-retail-evaluation`. Planning commit `ec77533` passed push CI `42561649592`. The user also confirms implementation commit `e6f43253a38fceb03508d239b4e8a8842f8bbcfa` was pushed and [push CI 42567676599](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42567676599) passed. Timestamp correction `850bbc8c3a16a4343ece3a4144e3e047eba0917d` was subsequently pushed and passed user-confirmed [push CI 42660104374](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42660104374). This CI predates live acceptance. That first approved window permitted the reviewed environment-only update and its counted campaign/restoration; the later repair is separately recorded below.

1. Preserved M4's completed/merged/CI evidence and immutable **28/40** ledger. Existing Runtime/DEFAULT were freshly verified READY v4 on corrected parity-v1, stack UPDATE_COMPLETE, with unchanged artifact/version, policies, retention and retained M3/foundation/data/trust templates.
2. Downloaded the published ready retail-v1 manifest and exact seven canonical source objects using analytics-dev in the approved account/region. Version-pinned hashes/sizes/schema/inventory/relationships are verified; source provenance, independent handwritten oracle tests, literal goldens and 480-item contributions are reviewable. Existing local raw/generated files were not substituted.
3. Added operator-side `analytics-ask` and `analytics-evaluate`, versioned cases/targets/reports, exact full-plan/result judging for 34 questions and S01A/B, durable per-attempt reports, latency/token/scan accounting and diagnostic missingness. Existing public contracts, runtime, metric calculations and M4 tests are preserved.
4. Added a separate locked/fsynced M5 campaign with reserve-before-dispatch, no automatic invocation retries, failure/interrupt accounting, repository-anchored persistent quota and protected fresh-verified restoration slot. **M5 calls used:38/40**, including warm-up,36-case suite and restored parity smoke; the campaign is retail-closed. M4 remains 28/40.
5. Prepared trusted retail settings and offline assemblies: only dataset retail-v1, tenant retail_demo and reference date April 1 change; North/South and every other property remain fixed. Corrected restore template matches the original base bytes. [Runbook](milestone-5-runbook.md) records hashes, commands, failure handling, SDK references and restoration.
6. Approved live execution deployed retail Runtime v5 and passed warm-up, then **35/36 cases**; Q18 returned clarification after one model call/no tools instead of yesterday's 110.25 USD. All 29 observed metric requests, planned clarification/authorization/metadata/session gates, diagnostics and latency passed (client p95 10.403s). Mandatory corrected-base restoration and independent smoke passed on READY v6, stack UPDATE_COMPLETE. All-cases acceptance remains unsatisfied; keep M5 open.

7. The separately approved repair at pushed 661aba9 (successful push CI 42677910109 and PR CI 42677922211) uploaded the reviewed candidate once, bound actual VersionId `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` and verified READY v7. Local CDK timed out after the successful AWS update; no candidate warm-up/probe/suite ran. Mandatory original restoration/smoke passed on READY v8, stack UPDATE_COMPLETE. Repair ledger is 1/40, closed;39 unspent, no reserve used. Original M5/M4 histories, goldens, artifacts and permissions remain intact.

8. Pushed checkpoint e0f028c passed CI 42691865683/42691880796. At that preparation checkpoint, the operator controller correction and continuation were prepared offline: exact CloudFormation/template/parameter and full Runtime reconciliation, bounded owned-process cleanup and overlap guards, explicit fresh v8 start, immutable parent 1/40 binding and a separate 39-call ledger with a protected final restoration call. The candidate ZIP/version, original artifacts, goldens and historical ledgers remain unchanged. Candidate evaluation had not resumed at that preparation checkpoint.

9. Controller commit e8e4b0f was pushed and passed CI 42698850994/42698861471. Its exact39-call continuation was approved, including the controlled reserve. Fresh v8/candidate/parent preflight and candidate v9 controller verification passed, but ConnectTimeoutError in the additional checkpoint prevented warm-up/probe/suite. Mandatory original restoration/smoke passed on READY v10, UPDATE_COMPLETE. Continuation1/39 closed; aggregate 2/40, 38 remaining. No source, artifact, permission or historical-ledger change occurred.

10. Checkpoint75d7c9f is pushed with successful [push CI42709874036](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42709874036) and [PR CI42709898730](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42709898730). Recovery implementation `8f6b271` is normally pushed and verified by [push CI 42860069230](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42860069230) and [PR CI 42860082151](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42860082151), separate from this documentation follow-up. The original-checkout verification passed with **1086 passed, 85 gated skips**, lockfile/lint/format/type checks and separate offline synthesis: bounded and journaled operator reads, direct controller-proof handoff, covered invocation-setup STS and Runtime client-construction diagnostics, fresh restoration-proof reuse, cross-selector exclusion and proposed v10 recovery capped at 38 new calls. Its Q18 probe also serves as warm-up; all 36 suite cases and restoration smoke remain mandatory. Both closed histories and the aggregate 40 cap are preserved.

11. Approved `q18-recovery-v1` executed once from fresh original v10: deployed pinned candidate READY v11, Q18 **110.25 USD [2025-03-31,2025-04-01)** and all **36/36** cases passed; client p95 **13.381s**, complete diagnostics. Mandatory original restore/smoke and separate read-only final verification passed on READY v12. Recovery **38/38**, aggregate **40/40**, no retries/failures/incomplete calls. All 122 protected files and historical ledgers/claims unchanged. No code/upload/IAM/dataset changes during execution.

Exact next task: M1–M5 remain complete. For the separately requested UI follow-on, compare administrator permission evidence and obtain explicit approval of the shared-release/20-attempt proposal before deployment or billable questions. Preserve the verified original-v12 checkpoint and all closed historical allowances; no new milestone is started. Production authorization, broader language coverage, long-duration operational hardening and measured cost remain outside the verified scope.

Cube remains a later adapter extension outside milestones 2–5 unless separately requested.
