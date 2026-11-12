# Implementation plan

**Milestones 1–5 are complete for the agreed development proof of concept.** M5 completion [`7905d13`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/7905d13f59e13d0b5a1b11231348721471a19411) merged through [PR #6](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/6) on **November 10, 2026**, at [`c0d2c5a569e2d242bf840a715c31050888b579ab`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/c0d2c5a569e2d242bf840a715c31050888b579ab). [Main CI 42872516193](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42872516193) passed for that exact merge. Further development requires a separately defined scope; no production-readiness or new-milestone claim follows from this closeout.

## Follow-on scope: local testing UI

The separately authorized shared-code UI scope is implemented and accepted. The
default playground stays AWS-free; local Bedrock uses canonical DuckDB and the same
agent class/catalog/contracts/tools as candidate AgentCore/Athena. Source/dependency/
canonical verification, exact release records, persistent question/SDK counting,
bounded deployment/rollback and offline paired reporting are implemented.

Approved execution at a113220 passed Q18 and **18/18 paired actual-UI outcomes**.
Fresh final proof at November 11, 2026, 16:58:11Z verifies candidate/retail
Runtime/DEFAULT **READY v13**, runtime stack UPDATE_COMPLETE. Candidate ZIP/version
and reviewed configuration remain pinned. Existing infrastructure, permissions,
goldens and historical M1–M5 ledgers are unchanged.

The separate allowance used **19/20**: verification1 + regular18, protected rollback0.
All normal slots are spent; no further demonstration/retry/reset is permitted.
Success intentionally leaves the shared candidate deployed. New billable work needs
a separately reviewed scope/allowance. Administrator policy contents covered the
required actions; actual calls succeeded, without independently enumerating policy
attachments or broadening IAM. See [acceptance/results](ui-shared-code-live.md) and
[progress](progress.md).

The UI outcome is pushed and merged through [PR #8](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/8) on November 11, 2026, at `e22287538e22e1917eb2a21efbeadc4cec5c6d75`. Its historical acceptance and CI retain their original attribution. Default/offline saved-report viewing remains available without a new invocation. No next milestone or production-readiness claim is implied.

## Follow-on UI interaction: composer, progress and model selection

The user requested immediate input clearing, streaming output and model choices.
Local implementation clears the composer on submission, streams truthful execution
progress followed by validated results, and routes opaque model selections through
trusted server-configured backend bindings. The existing JSON endpoint, question-only
agent request, shared semantic rules and accepted runtime/source/artifact remain
unchanged. A disconnected browser does not retry or abandon durable accounting.

The current accepted live configuration exposes **Nova Lite only**. Its existing
JSON runtime and progress stream remain separate from the newly requested word
streaming release below. The initial interaction-only change performed no AWS
operation, rebuild, upload, deployment, IAM change or billable test, and did not
expand any allowance.
Local inspection found session 02 at **2/20 used / 17 regular remaining** before UI
reload; counters and historical evidence are preserved. Exact verification results
and the local feature commit are handed off through [progress](progress.md).

## Follow-on scope: Bedrock-only models and provider word streaming

The separately requested implementation merged through PR #11 at `01aabc1`. The
user approved deployment/live evaluation on November 11, 2026. PR #12 merged the
policy-packaging correction, with successful PR CI. Read-only verification on
November 12 confirms all three model agreements and both attached policy parts;
the directory grant is now administrator-applied with exact readback and an
allowed simulation. Fresh preflight and the one-time ZIP upload passed. Only the
new Nova stack was created; verification stopped on AWS singleton policy shape
and a workload-role logging denial. The user approved the
[recovery plan](bedrock-streaming-recovery-plan.md) at **7dad05a**; its
[approval record](../evaluations/bedrock-streaming/recovery-approval.json) binds
the exact review and execution-proposal hashes. Fresh preflight
**20261112T200119Z** passed; only the reviewed unused Nova stack was deleted and
all ten corrected stacks verified **CREATE_COMPLETE**, Runtime/DEFAULT **READY v1**,
exact artifact/configuration/policy proofs and seven-day retention at **20:20:07Z**.
The administrator-applied trust readback matches the exact reviewed addition,
preserving both old statements; release binding passed. Nova Q18 passed streaming,
but the all-five question returned `token_limit` despite all exact requests/results
and only 3,215 reported tokens. Offline replay identified conservative conversation
byte reservation before an unnecessary planner turn. Acceptance stopped; no other
model ran and no new choices were enabled. Protected legacy v15 cleanup smoke
passed; the campaign is closed **3/40** (two ordinary, one cleanup), reserve
untouched. Those are historical results of the closed original campaign.

The [completion replacement](bedrock-streaming-completion-plan.md) was then
explicitly approved at **f591498**. Its one-time upload returned S3 VersionId
**PQbNv3gkC1HwVYNNiAe95r1XuQDkfKvb**; all ten existing stacks and Runtime/DEFAULT
verified **UPDATE_COMPLETE / READY v2**. Nova Q18 and the all-five regional question
passed exact result and provider-streaming gates. Sonnet Q18 failed its first
Converse call with **AccessDeniedException / model_error**, without a semantic
query. Execution stopped after three acceptance attempts, with no accepted UI
binding. Mandatory original restoration passed with all ten original code/config
bindings **UPDATE_COMPLETE / Runtime and DEFAULT READY v3**. Protected legacy-v15
Q18 smoke passed **110.25 USD** at approximately **22:29:52Z**. All new choices
remain disabled. Parent **3/40** stays closed; child **4/37** is closed/blocked
(three ordinary attempts and cleanup), aggregate **7/40**, with no incomplete
attempt. Remaining ordinary quota is unusable. No retry, reserve use, new campaign
or additional permission follows from that quota.

The implementation commit **f591498** is pushed; [push CI 43316129337](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43316129337) and [PR CI 43316722939](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43316722939) passed for that commit. Those checks do not cover later outcome documentation.

The original model scope covered nine additional Bedrock choices and a streaming
Nova baseline, each with a separate fixed-model role/Runtime. Google is Gemma
through Bedrock Mantle; native OpenAI GPT choices remain inside Bedrock. Optional
catalog metadata is not a deployment or effective-access assertion.

1. Reuse the unchanged `BedrockAnalyticsAgent` tool loop and semantic contracts,
   with local canonical DuckDB and hosted Athena execution. Keep SQL/calculations
   inside the governed adapters and authorization outside model payloads.
2. Bound execution to five planning calls plus one tool-free presentation call,
   six model calls/12,000 tokens total. Complete a fifth sequential tool round
   only when the exact full governed plan already succeeded; never drop requested
   metrics or add a sixth planning call.
3. Release actual provider words only when they match the canonical validated
   answer prefix. Preserve exact numbers, units, dates, private reasoning and
   final protocol/usage checks. Label rejected streams and never retry billable calls.
4. Verify local source/artifact/canonical pins, strict isolated infrastructure,
   transport/errors/authorization, quota receipts, disconnect ownership and
   failure cleanup offline. Record this checkout's results independently of
   earlier hosted CI and historical live tests.
5. Obtain review of the concrete artifact/templates, exact additive IAM/trust
   changes and new budget before AWS execution. Require two independent AWS
   checks per model—Q18 and all five regional metrics—before enabling new models.

The original allocation was 20 acceptance + 18 user + protected cleanup + one
unapproved reserve. Its closed three-call history is preserved. The separately
approved completion child allocates 20 acceptance + 15 user + protected cleanup +
one unavailable reserve within the remaining **37**, aggregate ceiling **40**.
Expiry remains `2026-11-15T23:59Z`. Ordinary dispatch is stopped after the Sonnet
failure and verified original restoration. Reviewed IAM policy/simulation and
management-account verification establish no missing grant; diagnosis of the
original full service error from retained evidence/support material is next.
Historical
assets, goldens, original reviews and M1–M5 completion remain unchanged.

## Follow-on validation: execute every test — complete, zero skipped tests

The requested all-tests development validation passed on November 11, 2026:
**1,570 offline + all 85 live pytest items = 1,655 distinct passes, zero skips**.
Live coverage is 66 Athena items, one 36-request retail item and 18 agent items
(19 requests, including the shared session). Default CI remains AWS-free and fails
selected skips; live coverage comes from the approved staged executions.

The original approved run at 870e350 passed Athena 66 and retail 36, but stale CDK
asset references caused a rejected no-change parity deployment. Its cleanup/smoke
passed on unchanged retail v13, preserving the blocked parent at 37 Runtime/67 direct
Athena. The user then approved the [corrected continuation](full-live-continuation-proposal.md)
at 09ef680 and its 20 new calls, aggregate 57. Corrected parity verified READY v14;
all 18 remaining items passed, then mandatory accepted-retail restoration/smoke and
final read-only verification passed on **Runtime/DEFAULT READY v15**, stack UPDATE_COMPLETE.
New usage 20/20, aggregate 57/57, no failures/incomplete attempts or remaining allowance.
The [acceptance summary](../evaluations/full-live/acceptance-2026-11-11.json) binds
both commits/results, budgets, exact artifact/version/configuration and diagnostics.

Frozen archives/S3 VersionIds, source closure, independent goldens/publication,
permissions, M3/foundation infrastructure and every historical ledger/claim remain
unchanged. No code upload, rebuild, dataset change or IAM expansion occurred. The
completion commit `39d7edb644d4c6d6229d7864d639f9f19410bf18` is pushed and merged through [PR #9](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/9) on November 11, 2026, at `1dfd788a9b773fbf8abd39a554033cccd683c4ee`. [PR CI 43099154919](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43099154919) passed for the completion head; [main CI 43100659276](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43100659276) passed for the merge: **1,570 offline passed, 85 deselected, zero skipped in 137.85s**, with lockfile, lint, formatting, types and both offline syntheses passing. The live results remain separately attributed to their approved executions. These CI runs do not cover later local documentation or proposed review files.

[Interactive session 02](ui-interactive-session-02.md) was approved at `319a872` and
activated without an application/archive/deployment/IAM change. Fresh proof at
**21:52:13Z** on November 11, 2026 verified the existing candidate-retail Runtime/DEFAULT
**READY v15**, stack UPDATE_COMPLETE. Its single counted Q18 passed the full expected
request/result: **110.25 USD [2025-03-31,2025-04-01)**. The UI is running at
**http://127.0.0.1:8501** with both agent modes enabled.

The activation record used one verification / one Runtime invocation, zero ordinary
questions / zero direct local Converse calls, leaving **18 user-owned regular questions
across Local Bedrock/AWS** until **2026-11-13T23:59Z**; the protected original-rollback
slot is unavailable. Historical counters, records and frozen assets remain unchanged;
no automatic regular submissions or invocation retries are authorized. Exact next task:
the user may use those 18 questions in the active UI. The activation handoff reports
its exact commit, PR and CI links once verified; earlier CI links above cover their
named commits, not this new activation outcome. No next milestone
or production-readiness claim is implied.

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

Exact next task: diagnose the original Sonnet service error from retained evidence/support material; the full Error.Message, RequestId, session, resource and conditions remain unavailable. The supplied inline policy matches, administrator simulation allows both Bedrock actions on all four concrete resources with no missing context, and the user reports no permissions boundary. Read-only Organizations verification identifies this as the management account, whose roles are unaffected by SCPs. IAM evidence review is complete; no additional grant, repeat policy/boundary/simulator request or source-routing correction is justified. The bounded CloudTrail collection did not contain an AccessDenied event, and unrelated log errors are not an established cause. Nova's two gates passed, but multi-model acceptance remains incomplete; original restoration and protected smoke passed, with the child closed 4/37 and aggregate 7/40. Preserve all claims, sealed inputs, restored v3 bindings and legacy v15. No new grant, campaign, retry, reserve use or model call is authorized.

Cube remains a later adapter extension outside milestones 2–5 unless separately requested.
