# Progress

Updated: 2026-11-06 (America/Chicago).

## Current milestone and repository state

**Milestone 4 — recovery attempted; Runtime creation denied on tagging; live acceptance pending.** This session began on clean `feat/milestone-4-bedrock-agentcore` at `7360cc4c552fccce3bcdeab60dd2637d7ab6e2b4`. The user confirmed `7360cc4` was pushed and both hosted CI runs passed: [42292758353](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42292758353) and [42292764712](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42292764712). Those runs cover hosted offline checks, separately from this checkpoint's local checks and unrun live acceptance. Administrator-reported active M4 **Version 2** matches the policy committed at `7360cc4`. The approved empty failed-stack deletion succeeded; deployment of the approved corrected assembly then failed on `TagResource`. Foundation, trust, uploaded ZIP, M3 permissions and datasets were retained. **0/40 Runtime invocations used.** A one-action tagging correction is prepared locally but not applied. Milestone 4 remains **open**; this checkpoint stays local, with no agent push or production-readiness claim.

**Milestone 3 is complete: implemented, deployed, live-validated, merged, and hosted-CI verified.** The user confirmed [PR #2](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/2), merge [`ae378e4c289144164a8a7a6a85fa8c71ae5bcacc`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/ae378e4c289144164a8a7a6a85fa8c71ae5bcacc), and successful [CI run 42166641840](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42166641840). Local starting main `6bf1220` contains that merge and its documentation update. Historical AWS/live results below retain their user-executed attribution; that parity suite was not rerun during milestone 4 preparation.

**Milestone 2 remains implemented, merged into `main`, and verified by hosted CI.** [PR #1](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/1) merged implementation commit `e13b1ea` at merge commit `9dc5989353459e2651ba5cced882534d8d573783`. [GitHub Actions run 42113416826](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42113416826) passed for that merge commit, as confirmed by the user.

## Approved recovery from `7360cc4` — actual results

Reviewed commit `7360cc4`, AGENTS, progress, implementation plan and deployment plan. Verified Python 3.12.16 in the existing `enterprise-analytics` Conda environment and Poetry 2.3.1. STS confirmed profile `analytics-dev`, account `453711491609`, developer SSO principal and region `us-west-2`. Every AWS call in this session used that profile/region; no alternate profile or region was used.

Parsed the administrator-supplied active default **Version 2 JSON** (normalizing Markdown wildcard escaping) and compared every statement with the committed file: exact JSON equality, file SHA `5687259426158d8e761554a0308718a0fdf7c42b266f46be7cc933930daac5c6`. This is administrator-provided active-policy evidence, not a direct IAM read or write by the agent. The unchanged policy did not need reattachment.

Retained ZIP SHA `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1`, 39,117,152 bytes, and uploaded VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9` matched the local checkpoint and version-specific S3 HEAD checksum. Corrected assembly hashes: base `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb`; legacy `bbfe710402345ae04c7b1c73ec6187b7cde602d8344e1233b8e721848efe0ffc`; empty returns `ed4f4d446f2307959f87b19d3023412f976bebe8cf2ed7a6b0b9c5c021e82c96`. Asset manifests agree, lookup context is complete, and each variant differs only in its trusted dataset override. The approved corrected template/ZIP bytes remain unchanged; no rebuild or resynthesis was needed.

| Step / command actually run | Actual result |
| --- | --- |
| Read-only CloudFormation resources/events, full Runtime-list pagination and S3 version HEAD | Original failed runtime stack was ROLLBACK_COMPLETE with no surviving resources or matching Runtime. Foundation/data templates matched retained reviewed templates. Evidence preserved in `artifacts/agentcore/recovery.before-delete.json`. |
| `aws cloudformation delete-stack --stack-name enterprise-analytics-dev-agent-runtime --profile analytics-dev --region us-west-2 --no-cli-pager` followed by `aws cloudformation wait stack-delete-complete ...` | Succeeded; deleted only the previously failed runtime stack record. |
| Repository-local `cdk deploy --app artifacts/cdk.agentcore.endpoint-fix.out enterprise-analytics-dev-agent-runtime --parameters ArtifactVersionId=HSRXiFjg0w2W77InULH4.fn32Y.JH8b9 --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices --outputs-file artifacts/agentcore/recovery.runtime.outputs.json` | CREATE_FAILED / AccessDenied; CLI exit 1. Final runtime stack ROLLBACK_COMPLETE, suffix `0357ee30-da27-11f1-be37-0a8587e72127`. No matching live Runtime found. |
| Runtime/DEFAULT READY, counted warm-up, retention, three live suites | **Not run:** creation failed before a Runtime/endpoint ID existed. No model usage or live acceptance is claimed. |
| Restore corrected parity-v1 | Not applicable: no Runtime or dataset variant was deployed. Parity-v1 READY/restoration remains unverified. |

Foundation remains CREATE_COMPLETE; data layer remains UPDATE_COMPLETE. No foundation deployment, trust update, bootstrap, dataset publication, code upload or IAM write was repeated. Actual resource state is saved in ignored `artifacts/agentcore/recovery.checkpoint.json`. The existing invocation ledger remains empty: **0/40**, with all 40 originally authorized attempts unconsumed. The ignored counted warm-up/operator helpers were prepared but never invoked.

## Recovery authorization diagnosis and proposed tagging addition

The complete new CloudTrail record is retained in `artifacts/agentcore/recovery.create-denials.json`. Its **`responseElements.message`** identifies:

- Time: `2026-11-06T21:14:23Z` (15:14:23 America/Chicago); request `4074f7e9-3e5d-4278-a0d7-d48fe5f1a8b6`; CloudFormation token `4e3dab07-5d61-d749-656f-914e574f43f4`.
- Principal: `arn:aws:sts::453711491609:assumed-role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2/AWSCloudFormation`. The stack RoleARN and session issuer independently confirm the same CloudFormation execution role.
- **Action: `bedrock-agentcore:TagResource`. Resource: `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/*`. Reason: no identity-based policy allows that action on this resource.**
- The request retains the correct Project tag, account, region, model/runtime configuration and exact uploaded VersionId. Active V2's tagging grant remains restricted to the named runtime prefix, which does not match the creation-time wildcard. No evidence justifies changes to PassRole, runtime/query permissions, or optional features.

Prepared only **`bedrock-agentcore:TagResource`** in the Action list of `CreateTaggedDefaultEndpointDuringRuntimeCreation`. Its resource and exact region/account/Project conditions are unchanged. Removing just that action reproduces the entire administrator-supplied V2 JSON, with frozen canonical SHA `48939891d9f2183a398aa2918a8dcc374e33c6b3a1fbb821c135e31fc03dbac9`. Existing statements and M3 policy/attachments remain intact. Proposed full policy SHA: **`bf418e5de83729ecb5916b76d14ae7fd760187628fa77f9a5427c4cf42ddc35b`**.

Official authorization documentation confirms runtime creation's tagging dependency and request-tag conditions for runtime tagging. The supplied Project tag constrains submitted tags, not existing-resource ownership; effective live authorization still needs verification. An administrator must review/apply a new default version of the existing M4 managed policy after approval. No new policy version was applied, no extra deployment retry ran, and conditions were not loosened. The corrected base/variant templates are already approved and unchanged; no new template/package approval is needed. Further recovery waits on the additional IAM grant and authorization to resume.

## Recovery checkpoint local verification

Before the new tagging proposal, all required checks passed on `7360cc4`, including **660 passed, 84 skipped in 54.97s**. Final local results below cover the additional policy/test change, separately from both hosted CI runs and live acceptance:

| Command | Actual result |
| --- | --- |
| `poetry run pytest tests/test_agentcore_cdk.py -q -k creation_tagging_matches_new_denial_and_preserves_active_version2` | **1 failed against active V2**, 23 deselected in 1.47s: no tagging grant matched the recorded resource. Passes with the proposed action addition in the focused/full runs. |
| `poetry run pytest tests/test_agentcore_cdk.py tests/test_cdk.py -q` | **49 passed in 3.53s**. |
| `poetry check --lock` | Passed: All set. No dependencies/lockfile changes. |
| `poetry run pytest` | **661 passed, 84 skipped in 54.90s**. The 66 AWS parity and 18 live-agent skips are not acceptance evidence. |
| `poetry run ruff check .` / `poetry run ruff format --check .` | Passed; **76 files** formatted. |
| `poetry run mypy src tests` / extended `src tests infrastructure/cdk infrastructure/agentcore` | Passed: **57 / 67 source files**. |
| `aws accessanalyzer validate-policy --profile analytics-dev --region us-west-2 --policy-type IDENTITY_POLICY --policy-document file://infrastructure/cdk/agentcore-deployment-policy.development.json --output json --no-cli-pager` | Read-only proposed-policy validation: **zero findings**, not proof of live authorization. |
| Artifact/assembly/active-policy comparison, final read-only resource/ledger checks | Passed: one additional action only; unchanged corrected templates, code object/version and retained resources; no surviving matching Runtime; ledger 0/40. |
| `git diff --check` / `git diff --cached --check` | Passed; five-file checkpoint reviewed. Ten plan shell blocks passed `zsh -n` without running administrator/recovery commands. |

## Historical first milestone 4 deployment — `c29e8cb`

The user confirmed in the administrator console that both `enterprise-analytics-dev-cdk-execution` and `enterprise-analytics-dev-agentcore-cdk-execution` are attached to `cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2`, and developer SSO trust remains on the query role. Later, the user provided the active M4 policy's default **Version 1 JSON**. These are user-confirmed administrator facts, not policy writes performed here.

Read AGENTS, progress, implementation plan and the approved deployment plan; verified the clean branch/commit and existing Conda Python 3.12.16 / Poetry 2.3.1 interpreter. Explicit STS verified `analytics-dev`, account `453711491609`, region `us-west-2`. ZIP SHA `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` and all three reviewed template hashes matched the plan; artifacts were present, so no rebuild was needed. New stack names were absent. Comparing the deployed data-layer template with the reviewed template confirmed only the additive query-role trust statement changes; developer access remains in the applied template. SDK OrderedDict output was normalized before structural JSON comparison.

| Approved step | Actual result |
| --- | --- |
| Foundation deployment | `enterprise-analytics-dev-agent-foundation`: **CREATE_COMPLETE**, four resources. Code bucket `enterprise-analytics-dev-453711491609-us-west-2-agent-code`; runtime role `arn:aws:iam::453711491609:role/enterprise-analytics-dev-agent-runtime`. Stack suffix `e9cbb980-da1f-11f1-b570-025fb7172dff`. |
| Data-stack trust addition | `enterprise-analytics-dev-data-layer`: **UPDATE_COMPLETE**; CloudFormation events show only the query role updated. Original developer principal preserved and runtime principal added. Existing datasets, workgroup, Glue and M3 permissions retained. |
| Conditional code upload | Exact reviewed archive at `releases/51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1/agent.zip`; S3 **VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`**, SSE-S3, 39,117,152 bytes. Returned and version-specific HEAD SHA-256 verified. |
| Runtime deployment | Exact uploaded VersionId passed to the approved runtime template. `AnalyticsRuntime` **CREATE_FAILED / AccessDenied**; stack **ROLLBACK_COMPLETE**, suffix `82b6e930-da20-11f1-bd44-020708c932fd`. No matching Runtime returned by a full service-list pagination. |
| READY, warm-up, log retention and three live suites | **Not run** because Runtime creation failed. No runtime/endpoint ID, live version, model usage or live acceptance is claimed. |
| Restore parity-v1 | Not applicable: no Runtime was created and no variant was deployed. The intended initial config remains parity-v1; READY/restoration are not established. |

No bootstrap, dataset publication, speculative IAM broadening, deployment retry, manual resource cleanup or push occurred. The foundation, additive trust and immutable code version remain available for approved recovery. Ignored evidence includes `deployment-preflight.json`, stack/output snapshots, `upload.json`, `deployment-checkpoint.json` and sanitized CloudTrail records under `artifacts/agentcore/`.

## Historical authorization diagnosis and corrections — `7360cc4`

The full CloudTrail record identifies the denial inside **`responseElements.message`**. The initial short extraction inspected `errorMessage`, which is absent; the complete record resolves the cause:

- Actual CloudFormation `RoleARN` and CloudTrail session issuer: `arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2`.
- Denied session: `arn:aws:sts::453711491609:assumed-role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2/AWSCloudFormation`.
- Failed API: `CreateAgentRuntime`, at `2026-11-06T20:27:49Z`; request ID `8dcb800c-7f91-4598-8d0d-b9dc5d74c61e`.
- **Denied dependent action: `bedrock-agentcore:CreateAgentRuntimeEndpoint`. Resource: `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/*`. Reason: no identity-based policy allows that action on that resource.**
- The recorded region/account/Project tag match the top-level creation statement. The endpoint-creation grant is instead limited to `runtime/enterprise_analytics_dev_agent-*`, which does not match the creation-time wildcard resource. The denial does not identify PassRole, the runtime/query execution roles, or model invocation as the problem.

The administrator-supplied active Version 1 matches the committed `c29e8cb` policy. A successful CloudTrail `CreatePolicy` record at `20:07:58Z` independently has identical JSON; no relevant later policy-version write was found in that audit window. IAM is global, so these read-only audit events were inspected in `us-east-1`; actual deployment stayed in `us-west-2`. Direct `iam:GetPolicy` remains denied to `analytics-dev`. Reattaching the identical policy is not a correction.

Prepared **one additive statement** in the M4 deployment-policy JSON: only `CreateAgentRuntimeEndpoint`, resource `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/*`, with exact region/account/Project request-tag conditions. All original V1 statements are unchanged, guarded by canonical SHA `026a4cf0ecf5716d6ff72f16b3dd7dda9c3bdb0343f48605ffaed25bec8d5e17` after removing the addition. The M3 policy file, its attachment, and data permissions are unchanged. An administrator must review/apply a new default version of the existing M4 managed policy; none was applied here. This single-action resource exception covers all runtime names in the account/region subject to the Project tag. Request-tag support is documented, but propagation into automatic endpoint authorization still needs live validation; keep it fail-closed.

Separately corrected the local DEFAULT endpoint policy/output ARN from `/endpoint/DEFAULT` to `/runtime-endpoint/DEFAULT`, verified against the official SDK pattern and authorization reference. This is not asserted to have caused the earlier creation failure. Corrected base/variant assemblies are prepared under `artifacts/cdk.agentcore.endpoint-fix*.out`; the original approved assemblies remain frozen. The proposed runtime template SHA is **`dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb`**. Only its endpoint resource, endpoint policy JSON and endpoint output differ; foundation and Runtime ZIP bytes are unchanged. Revised IAM/template/recovery approval is required before any further AWS mutation.

The operator-only ignored invocation wrapper uses a persistent locked ledger, reserves/fsyncs before dispatch, counts failures, requires SDK `total_max_attempts=1`, and refuses request 41. Its offline self-test passed. The actual ledger is empty: **0/40**. No live suite command was executed; `run_live.py` and the ledger are retained for continuation.

## Deployment checkpoint local verification

All commands used the existing `enterprise-analytics` environment. Before the local corrections, the approved code's required checks passed again, including **658 passed, 84 skipped in 54.93s**. The following results cover the final local IAM/endpoint corrections, separately from hosted CI at `c29e8cb`:

| Command | Actual result |
| --- | --- |
| `poetry run pytest tests/test_agentcore_cdk.py -q -k default_endpoint_policy_and_output_match_official_sdk_arn_pattern` | **1 failed against the old ARN**, 21 deselected in 2.55s; passes after correction in the focused/full runs. |
| `poetry run pytest tests/test_agentcore_cdk.py -q -k creation_dependency_matches_recorded_denial_without_changing_existing_grants` | **1 failed against active V1**, 22 deselected in 1.42s: no grant matched the actual creation resource. Passes with the proposed addition. |
| `poetry run pytest tests/test_agentcore_cdk.py tests/test_cdk.py -q` | **48 passed in 3.33s**. |
| `poetry check --lock` | Passed: All set. No dependency/lockfile changes. |
| `poetry run pytest` | **660 passed, 84 skipped in 55.53s**. The 66 live AWS and 18 live-agent tests remain gated, not acceptance evidence. |
| `poetry run ruff check .` / `poetry run ruff format --check .` | Passed; **76 files** formatted. |
| `poetry run mypy src tests` | Passed: **57 source files**. |
| `poetry run mypy src tests infrastructure/cdk infrastructure/agentcore` | Passed: **67 source files**. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.development.json --phase all' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.agentcore.endpoint-fix.out --quiet` | Passed offline; unchanged four-resource foundation and three-resource corrected runtime proposal. Nonblocking deprecation/feature-flag advisories remain. |
| Same offline runtime synthesis with each `artifacts/agentcore/deploy.<version>.json`, `--phase runtime`, and `--output artifacts/cdk.agentcore.endpoint-fix.<version>.out` | Passed once each for parity-legacy-v1 and parity-no-returns-v1; not deployed. |
| `aws accessanalyzer validate-policy --profile analytics-dev --region us-west-2 --policy-type IDENTITY_POLICY --policy-document file://infrastructure/cdk/agentcore-deployment-policy.development.json --output json --no-cli-pager` | Read-only validation of the proposed addition: **zero findings**; not proof of effective live authorization. |
| ZIP/template delta, version-specific object checksum and ledger checks | Passed; approved ZIP unchanged, exactly three endpoint template paths differ, 0 Runtime invocations. |
| `git diff --check` and `git diff --cached --check` | Passed; six-file checkpoint reviewed. Ten deployment-plan shell blocks passed `zsh -n` without executing administrator/recovery commands. |

The [deployment plan](agentcore-deployment-plan.md) records exact retained state, one-statement administrator correction and proposed recovery using the existing uploaded version. At that checkpoint its revised template and IAM proposal had not been approved/applied; the later V2 application, corrected-template approval and failed tagging recovery are recorded above. No application metric or semantic-contract changes were made.

## Historical milestone 4 question-scope fix — `c29e8cb`, now pushed/hosted CI verified

Started on clean `feat/milestone-4-bedrock-agentcore` at `5e72b51668c0ae5e7717db4f621aa06073340126`; the local remote-tracking branch also pointed there. No branch switch, fetch, AWS operation or billable evaluation was performed. Read AGENTS, plan, progress and the AgentCore deployment plan; verified the existing Conda Python 3.12.16 / Poetry 2.3.1 environment. Readiness commit `5e72b51` was pushed by the user and passed [CI run 42279109681](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42279109681). The subsequent scope fix `c29e8cb` was also pushed and passed the separately recorded CI run 42283659374. Those hosted results do not cover this deployment checkpoint's local corrections.

Fixed partial scope recognition: unknown clauses can no longer disappear merely because a known metric/month was found. The guard validates all coordinated grouping members, clarifies OR across dimensions rather than converting it to AND, and checks remaining words against the conservative question vocabulary after accounting for recognized semantic phrases. Unknown measures, unsupported dimensions, temporal refinements and other unrepresented clauses clarify. A clarified `QuestionScope` also rejects query validation directly. Existing metric definitions, calculations and v1/v2 schemas are unchanged.

Authored parser and model/agent regressions cover all four supplied reproductions, reversed/coordinated variants, ambiguous Boolean mixtures, and supported neighbors (same-dimension alternatives, cross-dimension conjunctions, region/channel grouping, explicit exclusive intervals, relative periods and metric/period comparisons). Each behavioral reproduction queues the formerly accepted contract-valid incorrect model request; the fixed agent clarifies before consuming it or executing a semantic query.

All checks used the existing `enterprise-analytics` environment. No application dependencies, lockfile, public schemas, metric definitions or IAM source policies changed.

| Command | Actual follow-up result |
| --- | --- |
| `poetry run pytest tests/test_question_scope.py tests/test_agent.py -k 'scope_requires_the_complete_request or incomplete_question_never_accepts' -q` | Before the fix: **8 failed, 86 deselected in 0.39s**. All four partial model requests produced an incorrect `answer`. These tests pass in the final focused/full runs below. |
| `poetry run pytest tests/test_agent.py tests/test_agent_limits.py -q` | Before the fix: **91 existing tests passed, 4 new regressions failed in 3.77s**. |
| `poetry run pytest tests/test_question_scope.py tests/test_agent.py tests/test_agent_limits.py -q` | After fix and supported-grammar review: **132 passed in 4.15s**. |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **658 passed, 84 skipped in 55.37s**. Only the explicitly gated 66 AWS parity and 18 live-agent tests skipped; no live acceptance claimed. |
| `poetry run ruff check .` / `poetry run ruff format --check .` | Passed; **76 files** formatted. Initial test line-length failure was fixed. |
| `poetry run mypy src tests` | Passed: **57 source files**, after fixing the new test helper's typed keyword call. |
| `poetry run mypy src tests infrastructure/cdk infrastructure/agentcore` | Passed: **67 source files**. |
| `poetry run python -m infrastructure.agentcore.package --config infrastructure/agentcore/runtime.development.json --output artifacts/agentcore/agent.zip --offline` | Passed: **39,117,152 compressed / 85,644,266 unpacked bytes**; 13 unchanged locked dependency wheels. SHA-256 **`51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1`**. |
| Same packaging command with `--output artifacts/agentcore/agent.repeat.zip --project-wheel artifacts/agentcore/project-dist/enterprise_analytics_agent-0.1.0-py3-none-any.whl --offline` | Passed: identical archive bytes/checksum; packaged question-scope source matches the working source and native libraries are AArch64 ELF. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.development.json --phase all' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.agentcore.reviewed.out --quiet` | Passed offline: **4 foundation + 3 runtime resources**. Current template hashes are recorded in the deployment plan. Nonblocking CDK deprecation/feature-flag advisories remain. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.m4-data-trust.cli.out --quiet` | Passed offline: **41 resources**, template hash unchanged from readiness (`716f5905…02c2bd4`). |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.agentcore_app --config artifacts/agentcore/deploy.<version>.json --phase runtime' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.agentcore.<version>.out --quiet` | Passed once each for `parity-legacy-v1` and `parity-no-returns-v1`; three runtime resources each, refreshed checksum key, unchanged dataset overrides and required S3 VersionId parameter. |
| Artifact/source/config checksum assertions and deployment-plan shell syntax validation | Passed; all current checksum references match, eight shell blocks pass `zsh -n` without executing deployment commands. |
| `git diff --check` / staged diff check | Passed for the final seven-file fix before its local commit. |

Independent read-only review identified and helped preserve supported `Which` discovery, coordinated `each` grouping, repeated grouping prefixes, grouped-by wording, and parenthesized same-dimension alternatives. Final review found no remaining blocker within the four reported reproduction families.

The ARM64 package, pinned development checksum, base/variant synthesized templates and deployment plan are refreshed for this fix. No upload or deployment occurred. Initial development vocabulary remains intentionally conservative; unrecognized phrasing may clarify. At that fix checkpoint, hosted CI and deployment approval were pending; successful CI for `c29e8cb` and the later partial deployment are recorded above. Live acceptance remains pending.

## Milestone 4 readiness work and decisions

- Read AGENTS, README, architecture, metric definitions, implementation plan, progress and deployment record; inspected Git/history and asserted the existing `enterprise-analytics` Conda interpreter, Python 3.12.16 and Poetry 2.3.1. Baseline lockfile, pytest (**458 passed, 66 skipped in 45.67s**), Ruff lint/format and mypy all passed before implementation.
- Added an injected, bounded Bedrock Converse loop exposing exactly the four existing semantic operations through validated v2 requests. Existing v1/v2 semantic schemas, catalog calculations, and adapter query semantics are unchanged. Multiple tool IDs, malformed responses/arguments, recovery, failures and time/iteration/tool/token limits are covered offline.
- Typed agent answers render exact validated tool numbers, units, nulls, groups, periods and metric/dataset versions. A deliberately conservative question guard clarifies ambiguity/unsupported requests, anchors relative periods to server configuration, and rejects model plans that change requested scope. Independent review fixed exclusion wording interpreted as inclusion, combined comparison results, ignored unsupported metrics/time grains, and unrequested catalog searches. Catalog search remains available to direct semantic callers; the initial agent lists the full catalog.
- Added a stateless manual HTTP runtime with only `question` accepted in payloads. IAM-approved callers share fixed server scope `t1` / North+South; prompts, sessions, headers and history never authorize access. Workload credentials assume the narrow query role with expiry refresh. No local profile/SSO credentials enter the package. Logs record configuration, tokens, latency, tools and Athena execution diagnostics.
- Prepared a Poetry-locked Python 3.12 Linux ARM64 ZIP, checksum manifest, separate CDK foundation/runtime stacks, explicit caller policies, scoped model/log permissions, immutable/versioned code publication, and an additive query-role trust change. Offline comparison with the deployed data-layer template found only query-role trust changed. The data layer is reused; no bootstrap or dataset republishing is planned.
- Ordinary pytest/CI remains AWS-free. Added offline agent/runtime/packaging/CDK regressions and explicit live-agent gates with authored literal expectations, all five metrics, period/filter/grouping validation, missing/empty returns and same-session isolation. Missing live configuration fails instead of reporting skipped acceptance. Live evaluation artifacts record semantic plans/results rather than grade prose.
- Updated README, architecture, metric definitions, implementation plan, root instructions, and milestone 3 deployment handoff. [AgentCore deployment/live plan](agentcore-deployment-plan.md) specifies the exact resources, IAM changes, usage allowance, commands, costs, retention and cleanup. No Cube, UI, Gateway, Memory or other additional AgentCore services were implemented.

## Historical milestone 4 read-only preparation evidence

The user explicitly selected `analytics-dev` and renewed SSO after expiration. Subsequent read-only STS verified account `453711491609` / `us-west-2`; no default-profile fallback occurred. Existing data-layer stack is `CREATE_COMPLETE`. Ready manifests, 27 Glue schemas and object checksum/length metadata verified all four snapshots, including `retail-v1`; ignored evidence is `artifacts/m4-snapshot-verification.json`. These are metadata checks, not rerun live metric queries or a retail agent demonstration.

Selected configurable profile `us.amazon.nova-lite-v1:0` is ACTIVE; Nova Lite model availability reports AVAILABLE/AUTHORIZED. Official Converse/tool-use support was checked. US inference may route to us-west-2/us-east-1/us-east-2; model access is not yet proved by invocation. At that preparation checkpoint, `iam:GetRole` was denied and administrator attachment/trust verification remained pending; the user later confirmed those prerequisites, as recorded above. Read-only Access Analyzer found two invalid S3 action names initially; corrections were verified against official S3 permissions and revalidation returned **zero findings**. No permissions were changed.

## Historical milestone 4 readiness verification — commit `5e72b51`

All Python/Poetry commands below use `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python`. These results cover the original readiness commit, before the follow-up scope fix recorded above. Live AWS/agent suites were intentionally excluded pending approval.

| Command | Actual result |
| --- | --- |
| Interpreter assertion, `poetry --version` | Existing Conda Python **3.12.16**, Poetry **2.3.1**. |
| `poetry check --lock` | Passed: All set. `poetry lock` refreshed only the content hash for the explicit packaging development dependency; no locked package versions changed. An attempted `poetry lock --offline` was unsupported by Poetry and was replaced by the successful cached `poetry lock`. |
| `poetry run pytest` | **617 passed, 84 skipped in 54.65s**. Skips: 66 existing live AWS cases and 18 new base live-agent cases. No live acceptance claimed. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: **75 files** already formatted. |
| `poetry run mypy src tests` | Passed: **56 source files**. |
| `poetry run mypy src tests infrastructure/cdk infrastructure/agentcore` | Passed: **66 source files**. |
| `poetry run pytest tests --run-agent-live --collect-only -q` | Expected exit **4**: `--run-agent-live requires --agent-config; no live agent acceptance was run`. No AWS call. |
| `poetry run python -m infrastructure.agentcore.package --config infrastructure/agentcore/runtime.development.json --output artifacts/agentcore/agent.zip --offline` | Passed; 13 locked main dependency wheels, **39,115,757 compressed / 85,640,244 unpacked bytes**. Initial wheels were downloaded from PyPI; final builds reused the cache. |
| Same packaging command with `--output artifacts/agentcore/agent.repeat.zip --project-wheel artifacts/agentcore/project-dist/enterprise_analytics_agent-0.1.0-py3-none-any.whl --offline` | Passed; archive bytes identical. SHA-256 **`843bf34fdde1d471bcf7b4741536e04c3fa08cdc5651f677f9804146ecaa55b6`**; both native libraries verified AArch64 ELF. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.development.json --phase all' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.agentcore.reviewed.out --quiet` | Passed offline: **4 foundation + 3 runtime resources**, no missing lookup context. Nonblocking CDK dependency deprecation and feature-flag advisories emitted. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.m4-data-trust.cli.out --quiet` | Passed; **41 existing resources**, deployed-template comparison proves only the additive query-role trust statement changes. |
| `poetry run python -m infrastructure.cdk.agentcore_app --config artifacts/agentcore/deploy.<version>.json --phase runtime --outdir artifacts/cdk.agentcore.<version>.out` | Passed once for each of `parity-legacy-v1` and `parity-no-returns-v1`; three resources each. No AWS calls. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.example.json --outdir artifacts/cdk.ci-final.out` | Passed, matching offline CI's existing-data synthesis. |
| `poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.example.json --phase foundation --outdir artifacts/cdk.agentcore-ci-final.out` | Passed, matching offline CI's new foundation synthesis. |
| `aws accessanalyzer validate-policy --profile analytics-dev --region us-west-2 --policy-type IDENTITY_POLICY --policy-document file://infrastructure/cdk/agentcore-deployment-policy.development.json --output json --no-cli-pager` | Read-only verification passed: **zero findings**, after fixing the initial invalid S3 actions. |
| `git diff --check` / `git diff --cached --check` | Both passed; the 44-file implementation/test/documentation diff was reviewed before the local readiness commit. Eight deployment-plan shell blocks passed `zsh -n` syntax validation without execution. |

The historical hashes/sizes above describe readiness commit `5e72b51`; current ignored `artifacts/agentcore/agent.manifest.json` and synthesized paths now hold the refreshed follow-up build, whose hash is recorded above. Deployment configuration pins that current archive SHA-256. Native wheel ABI/platform checks passed. Foundation/runtime and existing-data trust synthesis use no account lookups. Offline readiness is not hosted CI or deployed-agent acceptance.

## Historical milestone 3 merge-status documentation update verification

Read AGENTS, this progress log, and the implementation plan. Inspected `git status --short`, `git log -5 --oneline`, the current branch and tracking refs, and `git rev-parse HEAD main origin/main` before describing the checkout. GitHub merge/CI details are the user's confirmed evidence. `git diff --check -- docs/progress.md` passed and the document diff was reviewed. Only `docs/progress.md` changed. Historical local checks and user-reported live results were preserved; no application tests, lint/type checks, hosted workflows, or AWS operations were rerun. No other files, branch switches, commits, or pushes are part of this update.

## User-executed AWS deployment and live validation

| Operation | Result reported by the user |
| --- | --- |
| `CDKToolkit` bootstrap | `CREATE_COMPLETE` |
| `enterprise-analytics-dev-data-layer` | `CREATE_COMPLETE` |
| Live parity suite | **66 passed, 458 deselected in 111.94 seconds** |

Exact user-executed command from the repository root:

```sh
poetry run pytest tests --run-aws --aws-config=infrastructure/cdk/config.development.json -m aws_integration -q
```

The suite compares both Athena and DuckDB independently with authored literal expectations across all five metrics and the three parity snapshot variants. This reported run satisfies the development live-parity gate. It does not independently establish synthetic `retail-v1` publication, exact deployed IAM attachments/resource outputs, measured costs, or live cancellation fault injection; those were not reported or audited here. The [deployment record](aws-deployment-plan.md) retains the reviewed configuration and cleanup behavior. No AWS operations were repeated for this update.

## Historical deployment documentation checkpoint and offline-check coverage

The user requested a local commit after the documentation review found no actionable issues. The six reviewed Markdown files were committed in `3424d07`, with commit-status wording reconciled beforehand. `git diff --check` and `git diff --cached --check` passed. No application checks or AWS operations were rerun then; existing results below covered unchanged code. That checkpoint was subsequently pushed and merged through PR #2.

Read AGENTS and all project documentation; inspected Git status/log, the `ae68d2c` commit, executor cleanup logic, and its regression tests. The committed executor blob `1c8f729d9e29dea65155689d6f8be6d8e70f0021` and lifecycle-test blob `a040fd1241f7abe84028bc9536c598acc0167de1` match the versions covered by the recorded checks below. All other code/tests, infrastructure, dependencies/lockfile, and CI configuration are unchanged from readiness commit `7edd010`.

Offline evidence available at that checkpoint was **458 passed, 66 skipped**, 61 lifecycle tests passed, lockfile validation passed, Ruff lint/format passed, and mypy passed. These checks were **not rerun** during that documentation update or commit preparation. At that stage, milestone 3 hosted CI had been confirmed for `7edd010`; newer hosted results had not been checked or inferred from local/live results. Only README and project documentation changed then; no source, tests, infrastructure, dependencies, or AWS operations changed. The preceding documentation-only update made no commits or pushes; the later user request authorized local commit `3424d07`, with no agent push. The completed merge and merge-commit CI are recorded in the current status above.

## Historical cancellation fix verification — now committed in `ae68d2c`

The local fix session started at `54d868a` (`update progress.md with milestone 3`) with a clean working tree and left the fix uncommitted as requested at that time. The user subsequently committed it in `ae68d2c`. During that fix session, read AGENTS, implementation plan, progress, executor/adapter code, and lifecycle tests; inspected Git status/log. Verified Poetry 2.3.1 and `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python` (Python 3.12.16) before tests; all checks used this existing Conda environment. No existing work was discarded. The following are recorded results, not reruns in this update.

- Abnormal exits after receiving a query ID now request best-effort cancellation while the query may still be running, including exhausted polling service/connection errors and malformed responses. Separate terminal-state tracking is reset for each execution attempt. Known SUCCEEDED/FAILED/CANCELLED executions are never stopped, including result-fetch failures/timeouts and failed-query retry backoff. Polling errors never resubmit a potentially running query.
- Cleanup reuses lifecycle retries with a fresh `min(query timeout, 5 seconds)` scheduling budget, independent of the expired main deadline. Existing Athena SDK client factories retain finite connect/read timeouts (at most 5/10 seconds) and disable nested SDK retries. An in-flight call can outlast the scheduling budget; cleanup is not a hard wall-clock guarantee. No follow-up terminal-state polling is added.
- Original exceptions/causes survive cleanup failure. Internal diagnostics add cancellation attempt counts and `REQUEST_ACCEPTED`, `REQUEST_FAILED`, or `DEADLINE_EXCEEDED`; acceptance does **not** assert confirmed CANCELLED status. Malformed statistics cannot replace the primary exception during diagnostic recording. Semantic contracts and legitimate terminal-failure query retries are unchanged.

| Command | Actual local result |
| --- | --- |
| `poetry run pytest tests/test_athena_execution.py -q` | Baseline **39 passed**; after fix/regressions **61 passed in 0.05s**. |
| `poetry run pytest tests/test_athena_execution.py -q -k exhausted_poll_retries_cancel_running_query` | **2 failed against the original implementation**: service/connection retry exhaustion produced no stop call. Same tests **2 passed after the fix**, preserving original error causes and issuing one stop request without resubmission. |
| `poetry check --lock` | Passed: All set. Dependencies/lockfile unchanged. |
| `poetry run pytest` | **458 passed, 66 skipped in 33.22s**. Only explicitly gated live AWS tests skipped; no live acceptance claimed. |
| `poetry run ruff check .` | Passed after fixing test formatting found by the initial checks. |
| `poetry run ruff format --check .` | Passed: 50 files already formatted. |
| `poetry run mypy src tests` | Passed: 38 source files. |
| `git diff --check` | Passed; final implementation, tests, and progress diff reviewed. |

Regression coverage includes malformed polling responses/statistics, permanent/transient/connection polling errors, failed cleanup preserving the original exception object, retry/time budgets, cleanup after main timeout, per-attempt query IDs, and no stop without an ID or after a known terminal state. Independent read-only review found no additional actionable defects. Checked official [StopQueryExecution](https://docs.aws.amazon.com/boto3/latest/reference/services/athena/client/stop_query_execution.html), [query-state](https://docs.aws.amazon.com/boto3/latest/reference/services/athena/client/get_query_execution.html), and [SDK timeout/retry](https://docs.aws.amazon.com/botocore/latest/reference/config.html) documentation during that session. No live AWS calls, IAM changes, deployments, publications, live tests, commits, or pushes were made by the agent during that local fix session; only the executor, its lifecycle tests, and this document changed then.

## Historical milestone 3 hosted CI and documentation update

[GitHub Actions CI run 42152288133](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42152288133), triggered by the push to `feat/milestone-3-athena`, completed with **success** for commit `7edd01079fb7ee606305cebd62f5123d1fbc14cf` on 2026-11-05 (America/Chicago). GitHub's run/job records confirm the lockfile check, locked dependency installation, pytest, Ruff lint/format, mypy, and offline CDK synthesis all passed. This is hosted offline verification; it does not establish AWS deployment or live Athena parity.

For that earlier documentation-only update, read AGENTS, implementation plan, and progress; inspected `git status --short`, `git log -5 --oneline`, branch tracking, and remotes; verified the remote branch SHA and successful CI job steps through the GitHub connector. The working tree was clean before editing. `git diff --check` passed and the document diff was reviewed. Only `docs/progress.md` changed then; application tests, linting, type checks, synthesis, and AWS verification were not rerun. No AWS operations, commits, or pushes were performed during that update.

## Historical milestone 3 preparation and decisions — before deployment

This section records the original readiness checkpoint. Its missing-stack/permission findings and lack of uploads/live queries describe that earlier stage; the user-reported deployment and live results above supersede the pending-deployment status.

- Python CDK v2 defines retained private/versioned/SSE-S3 source and result buckets, explicit Glue schemas for four versioned snapshots (27 tables), an engine 3 Athena workgroup, a 10 MiB per-query cutoff, metrics/alarm, and separate exact-key loader/query roles. Results expire after 7 days; incomplete uploads after 1 day. Offline synthesis has 41 application resources and no missing lookup context.
- Canonical publication freezes and validates schema, tenant-scoped relationships, required fields, and event conflicts; collapses exact replays; records version/seed/inventory/checksums; verifies deployed schemas and uploaded bytes; conditionally publishes the ready manifest last. Existing or partially uploaded versions fail rather than overwrite. Absent versus empty returns and legacy six-table support are preserved. At that readiness checkpoint, candidate manifests/data existed only under ignored `artifacts/`; the agent had not uploaded them.
- Athena implements all four semantic operations and five metrics behind unchanged v1/v2 contracts and catalog definitions. Parameters are encoded SQL literals, identifiers governed, and trusted tenant/region predicates mandatory. DECIMAL(38,0) aggregates and exact integer final rounding avoid float and join fanout. Bounded polling/retries, timeout cancellation, pagination, strict result parsing, and private diagnostic records are tested offline.
- Added 64 authored parity cases with independent literal answers, plus live missing-source and v1/dimension checks. Both adapters must independently match the literals. Totals are gross $53.00, net $41.50, count 3, AOV $13.83, return rate 0.666667. Default pytest/CI use no AWS; explicitly requested live runs fail on missing configuration. CI adds offline synthesis.
- The user selected `analytics-dev`; read-only STS verified account `453711491609`, region `us-west-2`. At initial verification, `CDKToolkit` was absent and Athena listed only `primary`. `iam:GetRole` was denied, so bootstrap/admin privileges and the derived stable SSO trust ARN needed administrator confirmation then. No implicit default-profile fallback is allowed.
- Prepared a resource-scoped CloudFormation execution policy instead of default AdministratorAccess, including read-only access to the assembly's exact bootstrap-version SSM parameter. Read-only IAM Access Analyzer returned no findings; this was not proof of deployment compatibility/privileges. At that stage, bootstrap required separate approval and IAM permission. Tenant filtering is application enforcement, **not Lake Formation row-level security**; direct data-role access can read all approved snapshot rows.
- The existing global CDK CLI 2.1138.0 could not read library 2.275.0's assembly. Kept it unchanged; added repository-local CLI 2.1148.0 with npm lockfile. Its synthesis passed. During readiness preparation, no account lookups, credential output, resource creation, publication, or Athena queries occurred.

## Historical milestone 3 readiness verification

All application commands used the existing `enterprise-analytics` Conda interpreter `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python` (Python 3.12.16), explicitly asserted before final checks; Poetry 2.3.1 reused that environment. Before changes, all five required checks passed, including **212 tests in 21.91s**. Locked installation added 24 packages with no updates/removals; a later install registered the publication entry point.

| Command | Actual result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **436 passed, 66 skipped in 49.07s**. Skips are the explicitly gated live AWS tests, not acceptance evidence. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 50 files already formatted. |
| `poetry run mypy src tests` | Passed: 38 source files. |
| `poetry run mypy src tests infrastructure/cdk` | Passed: 42 source files. Two test-only typing failures found during final checks were fixed. |
| `poetry run pytest tests/test_aws_runtime.py -q` | Passed: 7 tests in 0.53s after the test-only typing fix. |
| `poetry run pytest --run-aws --collect-only -q` (historical missing-config guard, not a live-run command) | Expected exit 4: `--run-aws requires --aws-config; no live acceptance was run`. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.example.json --outdir artifacts/cdk.out` | Passed offline. Local CDK commands used `JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache` for sandbox-safe caching. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json --outdir artifacts/cdk.development.out` | Passed offline. |
| Repository-local `cdk synth --app 'poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.development.json' --profile analytics-dev --region us-west-2 --no-lookups --no-telemetry --no-notices --output artifacts/cdk.reviewed.out --quiet` | Passed; 41 resources, no missing context. Template SHA-256 is recorded in the deployment plan. Only a feature-flag advisory was emitted. |
| Repository-local `cdk bootstrap --show-template --profile analytics-dev --region us-west-2 --no-telemetry --no-notices` | Displayed bootstrap YAML locally; did not create resources. |
| `npm ci --prefix infrastructure/cdk/tooling --ignore-scripts --offline --cache /private/tmp/enterprise-analytics-npm-cache` | Passed after approved initial installation; local CLI version 2.1148.0. |
| `poetry run python tests/aws_fixture_data.py --output-dir artifacts/aws-datasets` | Prepared local retail, independent parity, legacy, and empty-return snapshots. Canonical inventories/checksums inspected locally. |
| `poetry run analytics-publish --help` | Passed without AWS calls; no publication command executed. |
| `aws sts get-caller-identity`, profile region inspection, `aws cloudformation describe-stacks --stack-name CDKToolkit`, `aws athena list-work-groups`, `aws iam get-role` | Explicit `analytics-dev`/`us-west-2`: identity verified; bootstrap absent; only primary workgroup; IAM inspection denied. |
| `aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://infrastructure/cdk/deployment-policy.development.json --profile analytics-dev --region us-west-2` | Passed with `findings: []`; read-only policy validation. |
| `git diff --check` and `git diff --cached --check` | Passed; diff reviewed before the local readiness commit. |

Focused CDK, publication, lifecycle, contract, runtime, and fixture checks also passed during implementation. Review tightened source IAM to exact canonical keys (preventing append-after-readiness), added account guards, and rejected a stale returns file when preparing a legacy fixture. No live acceptance was attempted at that readiness checkpoint.

Historical milestone 2 baseline: inspection read AGENTS, README, and all four docs; `main` was clean at `64cbea4`. Before implementation, all five required checks passed, including 68 tests in 7.07s. Python and Poetry both used `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python` (Python 3.12.16, Poetry 2.3.1). A second explicit environment assertion confirmed the same existing Conda environment before final tests. No local environment replacement or dependency upgrade was needed; milestone 2 did not change `pyproject.toml` or `poetry.lock`.

## Historical milestone 2 completed work

- Documented all five metric definitions before calculations; preserved net revenue definition 1.0.0 and its eligibility/time semantics.
- Added all five metrics through separate v2 contracts: exact currency/count/nullable-ratio values, appropriate grains, units, precision, and public business metadata. V1 contracts remain byte-unchanged; nine frozen schema fingerprints and literal net revenue JSON protect compatibility.
- Added optional deterministic physical return events, statuses, quantities, tenant-scoped references, duplicate handling, and missing-return-data errors. Six-table snapshots remain usable for the other metrics.
- Preserved all original six logical datasets for the same seed, verified with twelve frozen milestone 1 fingerprints (six tables, two seeds). Return generation uses a separate random stream and guarantees financial/physical return distinctions at the order level.
- Added item/order aggregation without join fanout; distinct received-return order flags; exact aggregate ratios rounded only at the end. The CLI preserves default v1 net revenue and adds metric/API selection.
- Retained the original accounting, contract, and authorization coverage and added independent multi-metric, return, precision, compatibility, filtering, and CLI tests.
- Added push/PR GitHub Actions CI with SHA-pinned official actions, Python 3.12, Poetry 2.3.1, read-only permissions, locked dependency sync, and the five required checks. README, all four docs, and root instructions reflect milestone 2 and the new roadmap.

## Historical milestone 2 decisions and reasons

- V1 remains net-revenue-only. V2 supports currency, count, and ratio results without changing published v1 schemas. Currency and ratio values are decimal strings; counts are integers. Nonmonetary v2 results have `currency: null`.
- Completed/shipped USD orders with at least one valid item qualify. Invalid snapshot records fail validation. Tenant/region scope comes only from trusted application context; purchase-time region/channel control grouping and authorization.
- Refunds and physical returns are independent facts. Approved refunds reduce net revenue; received physical returns count an order once, even with partial returns or multiple returned items. Both use the original order date and loaded snapshot with no as-of cutoff.
- Average order value uses aggregate net revenue / aggregate order count; return rate uses returned-order count / eligible order count. Integer rational arithmetic applies final ROUND_HALF_UP at 2/6 places independently of Decimal context. Zero denominators are null. Payment events never join metric aggregates.
- The generated-table assertion was extended from six to seven; legacy schemas and fixture helpers stay six-table-compatible. Golden dataset fingerprints are compatibility checks, never expected answers for metrics; metric tests use authored data and literal arithmetic.
- CI configuration follows current official action releases and Poetry docs, linked in README/architecture. Local `poetry sync --help` confirmed the pinned Poetry supports the flags; sync was not executed against the existing Conda environment.

## Historical local verification — milestone 2 implementation

These commands and results were recorded during milestone 2 implementation. They were not rerun during the earlier documentation-only merge update. The separate milestone 3 baseline/final checks are recorded above.

| Command | Recorded result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **212 passed in 23.71s**. |
| `poetry run ruff check .` | Passed: all checks passed. |
| `poetry run ruff format --check .` | Passed: 28 files already formatted. |
| `poetry run mypy src tests` | Passed: no issues in 22 source files. |
| `poetry sync --help` | Confirmed support for `--with dev --no-interaction`. |
| `git diff --check` and `git diff --cached --check` | Passed. Reviewed the 19-file milestone diff; v1 contracts, project dependencies, and lockfile are unchanged. |

During milestone 2 implementation, all five CLI commands below exited 0 using the fixed default period/seed. They were executed sequentially against `data/retail`; these are historical demo outputs, not test oracles. The demonstrations were not rerun during this update:

`poetry run analytics-demo --data-dir data/retail --metric <metric>` was run once for each row:

| Metric | East | North | South | West |
| --- | ---: | ---: | ---: | ---: |
| gross_sales (USD, v2) | 1294.75 | 1150.50 | 733.50 | 1233.50 |
| net_revenue (USD, v1) | 1158.41 | 1023.15 | 643.88 | 1119.27 |
| order_count (v2) | 16 | 18 | 9 | 17 |
| average_order_value (USD, v2) | 72.40 | 56.84 | 71.54 | 65.84 |
| return_rate (fraction, v2) | 0.000000 | 0.166667 | 0.111111 | 0.117647 |

Independent worked fixture: gross $53.00, net $42.50, three orders, AOV $14.17, return rate 0.333333; the regional ratios are not averaged. Tests also cover half-up ties ($0.005 -> $0.01 and 1/128 -> 0.007813), caller Decimal precision 2, missing versus empty return sources, received returns without refunds, refunds without returns, multiple items/events, exact/conflicting replays, empty queries, boundaries, and tenant/region isolation for every metric.

Focused verification was run while implementing; initial formatting/lint issues were fixed. Independent read-only source/CI review found no concrete blockers. No required local checks were skipped.

## Historical documentation-only merge update

Read AGENTS, this progress log, and the implementation plan. Inspected `git status --short`, `git log -5 --oneline`, the current branch, HEAD, and local `main` before describing the repository state. `git diff --check` passed and the document diff was reviewed. Only `docs/progress.md` changed; local application tests, linting, and type checks were not rerun. No application changes, AWS operations, commits, or pushes were made during this update.

## Completion status and known limitations

Milestones 1–3 are complete; historical implementation, user-run AWS parity, merge and hosted CI evidence remain separate. Milestone 4 retains its foundation, trust addition and verified uploaded archive. The endpoint-creation correction is administrator-reported active as V2 and the corrected endpoint template is approved; recovery creation failed on the subsequently identified tagging permission. A one-action tagging addition is locally tested and unapplied, pending administrator update and recovery continuation. Hosted CI passed twice for `7360cc4`, separately from this new local proposal; live acceptance and review/merge remain pending. The conservative vocabulary covers named metrics/months, explicit exclusive ISO ranges, region/channel inclusions and side-by-side results; change/exclusion calculations, arbitrary time grains and broader natural language may clarify. Numeric answers use deterministic rendering rather than model prose. Session history is intentionally not retained.

Runtime packaging targets Linux ARM64, not the local macOS native libraries. API/CloudFormation/model compatibility is checked offline and against official documentation but requires approved live acceptance. Scheduling deadlines and Athena cancellation remain best effort; an in-flight SDK call can outlast them. The operator's denied IAM inspection is an administrator prerequisite, not a reason to broaden permissions automatically. Initial acceptance uses parity snapshots even though retail publication metadata is now verified. No production isolation/policy service or measured-cost claim is made.

Source versions are immutable through the approved loader protocol; partial publication is deliberately not resumed automatically. New dataset versions require reviewed infrastructure inventory changes. Athena aggregates have a 38-digit bound. Application authorization is not a database security boundary, and 10 MiB per-query limits do not cap aggregate spend. Stored data is retained by default; no explicit cleanup was reported or performed in this update.

Historical milestone 2 branch creation was initially denied by the sandbox's read-only Git metadata restriction; the approved retry succeeded. Its implementation commit, merge, and hosted CI verification are complete.

Milestone 2 introduced no AWS credentials, calls, deployment, Athena adapter, or Bedrock/AgentCore integration. Milestone 2 used an application-controlled in-memory snapshot; there is no production policy service, FX, as-of history, streaming, or complete financial/cumulative physical-return ledger. Over-refunds can produce negative net revenue/AOV. Present optional return files are validated even when another metric is queried.

## Exact next task

**Milestone 4 remains open.** Review the single `TagResource` action addition to the existing conditional creation statement in the M4 managed policy. After approval, an administrator must create/set a new default policy version while preserving active V2 for rollback. Keep all resource/region/account/Project conditions and M3 permissions intact. The already-approved corrected template and uploaded ZIP/version do not change.

When the new permission is applied and recovery continuation is authorized, inspect/preserve the current empty ROLLBACK_COMPLETE runtime stack, delete only that failed stack record, and retry `artifacts/cdk.agentcore.endpoint-fix.out` using retained VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`. Verify Runtime/DEFAULT READY before the counted warm-up, log retention and three authored live suites. Restore only the corrected parity-v1 base. Keep the existing ledger and original **40 total** invocation limit; **0 used** so far. Capture any further authorization failure's full `responseElements.message` before proposing another grant.

Do not repeat completed foundation, trust, upload, bootstrap or dataset-publication steps. Keep this checkpoint commit local; the user will push. CI runs 42292758353/42292764712 cover `7360cc4`, not these new local changes; PR #4 remains separate from live acceptance. Do not mark M4 complete until all agreed live gates pass and parity-v1 is READY. No Cube, UI or additional AgentCore services.
