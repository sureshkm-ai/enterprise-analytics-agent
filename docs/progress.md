# Progress

Updated: 2026-11-11 (America/Chicago).

## Current task: UI input clearing, progress streaming and trusted model selection

Implemented the requested local UI changes on **feat/ui-streaming-model-selection**,
branched from pushed **2488e284395b3038f781f14f1e8a0d5dd621506c** with a clean working
tree. Preserved the enterprise-analytics Conda environment: Python **3.12.16**,
Poetry **2.3.1**, existing lockfile. The earlier activation handoff is
[PR #10](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/10), with
successful [push CI 43108364020](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43108364020)
and [PR CI 43108417902](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43108417902)
for **2488e28**. Those hosted results predate this feature and do not cover it.

### Completed behavior and boundaries

- Clicking Run captures the question, immediately clears the text box and leaves
  it empty on success/failure. A neutral placeholder avoids displaying the example
  question in the cleared composer. The submitted question remains in its result card.
- `/api/ask/stream` sends actual NDJSON accepted/running/elapsed progress while one
  worker executes, then the validated result or a safe terminal error. Deep dump and
  revalidation reject invalid nested Pydantic instances before either JSON or stream
  publication, including model_copy bypasses found during review. The existing
  JSON API remains compatible. This is **live progress with validated final output**,
  not raw Bedrock-token streaming or invented tool-stage/typewriter output.
- A model selector uses trusted `AgentModel` backend bindings and an opaque
  `model_key`; the key is stripped before backend dispatch and the SDK payload
  remains question-only. Unknown/mode-incompatible choices fail before execution;
  returned model/mode diagnostics must match. Multiple choices were exercised with
  offline fake backends. The actual approved shared release still exposes only
  **Amazon Nova Lite**; review pins/model configuration were not loosened.
- A disconnected browser cannot retry the operation or release the execution lock
  before its worker finishes backend accounting. Interrupted/invalid streams display
  an error without a second POST. Existing authorization, counters and expiry apply.
- Stopped only the verified idle task-owned old UI (PID 44994), after confirming no
  incomplete attempt. Reloaded the same approved session/release on
  **http://127.0.0.1:8501**, task-owned PID **51167**. Both agent modes are enabled;
  refresh the browser to load the new assets/token. Startup/status made no AWS call.

Local ledger inspection before reload found the user had completed one AWS question
after Q18: **2/20 used**, **17 regular questions remaining**, two Runtime SDK attempts
total, no failures/incomplete work. All **10** existing session files remained
byte-for-byte unchanged through implementation/tests/reload. Expiry stays
**2026-11-13T23:59Z**; the protected original-rollback slot remains unavailable.
No automated billable question, AWS operation, deployment, IAM change, upload,
rebuild, publication, dataset change or ledger reset was performed for this feature.

### Actual verification

| Command/check | Result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | Final **1,599 passed, 85 deselected in 65.16s, zero skipped**, including the deep nested-validation correction. Earlier 1,594 / 1,597 runs passed before the final authorization/publication regressions. Live suites were not run. |
| `poetry run pytest tests/test_ui_streaming.py -q` | Final **29 passed in 10.40s** (earlier 27 passed in 8.75s): real HTTP early progress/heartbeat, exact Decimal/Unicode, trusted routing, errors, disconnect ownership, no retries, authorization and legacy JSON. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: **163** files formatted. |
| `poetry run mypy src tests` | Passed: **128** source files. |
| `node --check src/enterprise_analytics_agent/ui/assets/app.js` | Passed. |
| Actual Playwright browser checks | **18 passed**, only fake model backends/deterministic offline data: immediate empty composer/neutral prompt, early progress, selected-model routing, exact result/Unicode, safe errors, truncated-stream no retry, busy controls and offline mode. Final browser run: four test POSTs; zero AWS clients/calls and no real allowance spent. |
| Offline source/artifact/canonical verification | `verify_local_release` passed with AWS session creation blocked: unchanged 25-file common source, dependencies, accepted ZIP and canonical publication bytes. **203** protected historical files and the 10 current-session files unchanged. |

Initial HTTP tests required loopback sandbox escalation; their socket-bind
PermissionErrors were environment restrictions, not application failures. The
focused and final suites then passed. Documentation checks passed across **7 Markdown
files / 87 local links / 27 shell blocks parsed without execution**, along with
`git diff --check`. Infrastructure and frozen runtime
are unchanged; no deployment/synthesis/live-acceptance result is inferred from UI tests.
Retained local evidence: `artifacts/ui-shared/ui-streaming-preparation/`; browser
screenshots at `output/playwright/streaming-in-progress.png` and
`output/playwright/streaming-complete.png`. The offline test browser/server were closed.

### Exact next task and limitations

Refresh **http://127.0.0.1:8501** and use the new composer/progress/model controls
within the existing user-owned allowance. The current model remains Nova Lite.
Adding real models or upstream model-token streaming needs a separately reviewed
server/runtime configuration, applicable access verification and deployment scope;
this feature neither creates those resources nor expands the live budget. Official
AWS references and the unchanged launch command are in [the UI runbook](local-ui.md).
This feature is a local implementation/verification checkpoint; it has no new hosted
CI claim. M1–M5, frozen assets, existing releases and all historical acceptance remain
complete/preserved; no new milestone or production-readiness claim is implied.

## Completed session 02 activation and push/PR handoff at 2488e28 — historical

The user approved the exact session scope at **319a872aaf5de89075d59f78221122efa1d43e30**
and explicitly requested a push and PR. Preserved the clean checkout on
**docs/ui-interactive-session-02**; fetched origin and verified main remains
**1dfd788a9b773fbf8abd39a554033cccd683c4ee**. No application, infrastructure,
dependency, metric, source, artifact or permission change was required.

### Actual approved activation — November 11, 2026

- Used only **analytics-dev / 453711491609 / us-west-2**. Fresh full pre-dispatch
  proof at **21:52:13.167966Z** verified exact candidate-retail Runtime/DEFAULT
  **READY v15**, stack **UPDATE_COMPLETE**, templates/parameters, policies,
  seven-day retention, 25-file source/dependency closure and canonical S3/Glue data.
  The existing frozen ZIP/S3 version and configuration remain unchanged.
- Ran the one approved counted verification command documented in
  [the session runbook](ui-interactive-session-02.md). Q18 **passed** against the
  complete independent request/result: **net_revenue 110.25 USD**, ungrouped,
  no filters, **[2025-03-31,2025-04-01)**, metric version 1.0.0 / retail-v1.
  Request `0dddc9ee-a875-4d96-91c2-16c1119bef3d`; one Runtime SDK attempt,
  one model call, **1,131 input / 110 output tokens**, **2,871ms** server latency,
  **5,015 Athena bytes** scanned. No retry, failed or incomplete attempt.
- Campaign **ui-shared-retail-v1-02** at activation: **1/20 used** (Q18 only),
  **18 user-owned regular questions remain** across Local Bedrock/AWS combined.
  The unused original-rollback slot is **unapproved/unavailable**. Expiry remains
  **2026-11-13T23:59Z**, November 13 **5:59 p.m. CST**. No other campaign funds this
  window. Do not repeat the successful verification or automate ordinary questions.
- Started the single loopback UI at **http://127.0.0.1:8501**, task-owned PID 44994.
  Actual Playwright mode-selection checks confirmed Local agent (Bedrock/DuckDB)
  and AWS AgentCore (Bedrock/Athena) enabled, retail-v1 and cost notices visible.
  **Zero ordinary questions submitted**; screenshots/snapshots retained under
  `output/playwright/`. Closed only the readiness browser and left the UI running.
  Its incidental missing favicon returned 404; no application script error occurred.

The committed [activation summary](../evaluations/ui-shared/interactive-02.activation.json)
pins approval, release, Q18 judgment/preflight, immutable activation-counter snapshots,
browser and offline-audit
evidence. Raw records remain in `artifacts/ui-shared/interactive-02-preparation/`
and `artifacts/ui-shared/ui-shared-retail-v1-02/`. The earlier readiness JSON and
preparation entry below remain immutable history, with their original attribution.

### Verification and preservation

All required local checks had already passed on this unchanged application code
at 319a872: `poetry check --lock`; `poetry run pytest` **1,570 passed, 85 deselected,
zero skipped in 55.45s**; Ruff lint/format (**161** files); mypy (**127** source files).
Those checks were not repeated for this documentation/evidence-only activation.
All 85 live items retain their separate completed acceptance, not a new suite run.
The fresh saved-evidence audit independently rejudged full Q18, strict release and
counter receipts with AWS client creation blocked. It verified both modes enabled
and all **203 + 121 + 134 + 50** protected inventory entries unchanged (inventories
overlap; counts are not a unique-file total). Historical campaigns, original/candidate
ZIPs, S3 VersionIds, corrected assemblies, source/data/goldens and claims are preserved.
Documentation checks passed across **10 Markdown files / 101 local links / 34 shell
blocks parsed without execution**; all **14** activation evidence pins, immutable
review/readiness records, final budget and `git diff --check` passed. The live journals
remain mutable authorities for later usage; their saved activation copies preserve
the original evidence pins. Exact-final-commit hosted CI will be inspected after
the authorized normal push and reported in the PR/final handoff; earlier CI is not
its evidence.

### Exact next task

Use the running UI for up to **18 user-chosen questions** in either billable mode,
before expiry and within the persistent allowance. Offline playground/Saved runs
remain AWS-free. Read the session runbook for the exact restart command; do not
start a second server or rerun Q18. On drift/failure/expiry/exhaustion, stop dispatch,
retain retail v15 and diagnostics; no deployment, original rollback or permission
change is authorized. The documentation branch is to be pushed normally with an
open PR and successful exact-head CI handed back for the user's merge. M1–M5 and
full validation remain complete; no new milestone or production-readiness claim.

## Historical session 02 preparation at 319a872 — superseded by approved activation above

Inspected instructions/plan/progress, clean Git status and recent history; fetched
origin without resetting work. Local main and origin/main both matched
**1dfd788a9b773fbf8abd39a554033cccd683c4ee**. Created local branch
**docs/ui-interactive-session-02**. Reused enterprise-analytics Conda Python 3.12.16,
Poetry 2.3.1 and its committed lockfile. No application/infrastructure/dependency change.

### Verified GitHub closeout

- [PR #8](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/8) merged at
  **2026-11-11T17:14:04Z**, merge **e22287538e22e1917eb2a21efbeadc4cec5c6d75**.
- [PR #9](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/9) merged at
  **2026-11-11T21:09:33Z**, merge **1dfd788a9b773fbf8abd39a554033cccd683c4ee**,
  completion head **39d7edb644d4c6d6229d7864d639f9f19410bf18**.
- [PR CI 43099154919](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43099154919)
  passed for that completion head. [Main CI 43100659276](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43100659276)
  passed for the merge: **1,570 offline passed, 85 deselected, zero skipped in 137.85s**,
  plus lockfile/lint/format/types/two offline syntheses. These hosted runs cover
  their named earlier commits, not this new local documentation/review preparation.

Replaced stale current local/unpushed/pending-merge/PR #8-unmerged handoffs across
current project instructions/docs. Preserved dated failures, approvals, historical
verification and all immutable acceptance records. M1–M5, shared UI and all 85 live
items remain complete and merged; no production-readiness or new milestone is implied.

### Fresh interactive readiness, without a billable call

The user requested a fresh allowance/release verification. Prepared separate review
[evaluations/ui-shared/interactive-02.proposed.json](../evaluations/ui-shared/interactive-02.proposed.json)
and [concrete session plan](ui-interactive-session-02.md). Campaign
**ui-shared-retail-v1-02**, review SHA
**385f936a719ca17ee09fe4c62af7d7153d04e8cc9d6ee3e2aaf7bd7defa8bbc8**.
Propose **19 usable attempts**: one required AWS Q18 probe + 18 interactive questions
shared across Local Bedrock/AWS. Existing schema ceiling 20 retains one original-parity
rollback slot that is **unavailable/unapproved** in this no-deployment session. It
cannot be relabeled as a retail smoke or ordinary retry. Expiry **2026-11-13T23:59Z**
(November 13, 5:59 p.m. CST). The explicit billable scope/quantity/expiry decision remains
pending; preparation/read-only verification is not approval to consume it.

Fresh read-only command, using only analytics-dev/account 453711491609/us-west-2:

```sh
poetry run python -m infrastructure.agentcore.ui_workflow preflight \
  --kind candidate \
  --review evaluations/ui-shared/interactive-02.proposed.json \
  --output artifacts/ui-shared/interactive-02-preparation/preflight.json
```

Passed at **2026-11-11T21:26:03.819419Z**: selected identity, Runtime/DEFAULT
**READY v15**, stack UPDATE_COMPLETE, full template/parameters, fixed retail tenant/
region/model/reference-date configuration, both policies, seven-day retention,
25-file source/dependency closure, exact ZIP/S3 VersionId and canonical S3/Glue bindings.
Extracted the validated new-review release record unchanged from that fresh proof;
never edited the historical v13 record. New record SHA
**3908c11e5de25907451e0cc382afe54260b2a1d41a517438003e719449630ebe**;
preflight SHA **59d83c0c8f863df5800440b92c6b74975b9c23209cfecf969ba5aed32b98bfa8**.
Retained preparation is `artifacts/ui-shared/interactive-02-preparation/`.
The saved proof is an observation; each future question must verify fresh state.

No deployment, IAM change, code upload/rebuild, dataset publication, Athena execution
or model/Runtime call occurred. New question ledger/claim is **not created**, new usage
**0/20**, regular 18 remaining. Offline construction/status with boto3.Session patched
to fail proved no AWS session creation and both billable modes disabled before Q18.
Historical counters/claims and records remain unchanged; no reserved old quota is reused.
If an interactive attempt fails, stop dispatch and preserve retail v15 and diagnostics;
this new scope does not authorize original restoration or any deployment/rollback.

### Actual local checks

| Command/check | Actual result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **1,570 passed, 85 deselected in 55.45s, zero skipped**. Offline only; prior 85 live acceptance was not rerun. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 161 files formatted. |
| `poetry run mypy src tests` | Passed: 127 source files. |
| New review/record/config assertions | Passed: only campaign/expiry differ, new review hash distinct, v15 record bound, zero ledger creation, pre-Q18 modes disabled, no startup/status AWS session. |
| Preservation | All 203 captured historical question/SDK/receipt/claim/review/evidence files unchanged; broader frozen assets/source/goldens verified in preflight. |

No new test or calculation was added: existing later-version, drift, quota, expiry,
SDK-limit, protected-slot and complete-Q18 regression coverage applies unchanged.
Infrastructure is unchanged; its successful main-CI offline synthesis evidence was
not relabeled as a fresh local synthesis. Documentation/link/diff and final
preservation checks passed: **10 Markdown files, 98 local links, 33 shell blocks**
parsed without execution, JSON/review/record/evidence pins and `git diff --check`.
All 203 captured campaign files, 121 historical protected files and the full-live
parent/completion inventories remain unchanged. No app/infra/test/dependency file
changed and no new live ledger exists. Keep this new commit local.

### Exact next task

Approve or decline the exact [interactive session 02](ui-interactive-session-02.md):
**one Q18 verification + 18 interactive questions across both modes**, expiring
November 13 at 5:59 p.m. CST. Then run only the counted probe; if its full independent
request/result gate passes, launch the UI with the new review and prepared v15
record. The user owns regular submissions. Do not replay old reviews, consume the
protected original-rollback slot, change resources/permissions or reset counters.

## Completed full-live validation — merged through PR #9, zero skipped tests

The user approved the corrected continuation at **09ef680** and review SHA
**70161d5cb64bdc44f72a1cd61a3df614c53bdd879bb102e21a6c28dc07f0bc8a**,
including 20 new Runtime calls and the increase to aggregate 57. Executed once on
November 11, 2026, using only `analytics-dev`, account 453711491609, us-west-2.
The checkout was clean on `feat/full-live-validation` at the reviewed commit;
Conda Python 3.12.16/Poetry 2.3.1 and the committed lockfile were unchanged.

### Actual results and final deployment

| Gate | Actual result |
| --- | --- |
| Fresh approved preflight | Passed **19:53:14Z**: exact accepted candidate-retail READY v13, identity, artifact/version, full template/parameters, both policies, retention, canonical publication and process guards. |
| `poetry run pytest` inside the supervised continuation | **1,570 passed, 85 deselected in 52.15s; zero skipped**. No AWS calls in this phase. |
| Corrected parity deployment | Accepted exact template/configuration on **Runtime/DEFAULT READY v14**, stack UPDATE_COMPLETE, proof **19:55:17Z**. Controller 38.818s, CDK 0, owned process reaped, no cleanup signals. |
| Remaining parity-agent pytest | **18 passed, 1,637 deselected in 117.45s; zero skipped**. All 19 requests passed independent expectations, including both same-session requests. |
| Mandatory accepted-retail restoration | Exact pinned candidate-retail restored on **Runtime/DEFAULT READY v15**, stack UPDATE_COMPLETE, proof **19:57:52Z**. Controller 35.740s, CDK 0, owned process reaped. |
| Protected restoration smoke | Full Q18 request/result passed: **110.25 USD [2025-03-31,2025-04-01)** on retail-v1/v15. |
| Final read-only checkpoint | Passed **19:59:56Z**, Runtime/DEFAULT **READY v15**, stack UPDATE_COMPLETE, exact artifact/config/template/parameters/policies/retention/publication, counters unchanged. |
| Combined offline evidence audit | **1,655 distinct pytest items passed: 1,570 offline + 85 live; zero skips, failures or unrun items.** Live 85 = parent Athena 66 + parent retail 1 (all 36 requests) + continuation agent 18. |

The earlier failed parity attempt and its successful retail 36/Athena 66 results were
preserved, not repeated or relabeled. The combined audit validates the complete
JUnit inventory, literal/independent expectations, all retail case judgments,
shared-session behavior, typed responses, both restoration smokes and diagnostics.
The completed development validation is not a production-readiness claim.

### Exact commands and evidence

```sh
poetry run python -m infrastructure.agentcore.full_live_continuation verify-offline \
  --review evaluations/full-live/continuation.proposed.json \
  --output artifacts/full-live/verification/continuation-approved-offline.json
poetry run python -m infrastructure.agentcore.full_live_continuation preflight \
  --review evaluations/full-live/continuation.proposed.json \
  --output artifacts/full-live/operations/continuation-approved-preflight
poetry run python -m infrastructure.agentcore.full_live_continuation run \
  --execute-approved \
  --review evaluations/full-live/continuation.proposed.json \
  --output artifacts/full-live/operations/continuation-approved-run
poetry run python /private/tmp/full-live-continuation-final-audit.py \
  --run artifacts/full-live/operations/continuation-approved-run
```

Preflight's first tool permission review timed out before process launch; confirmed
no output/log existed and retried once as explicitly permitted by that tool result.
It then passed. This was not an AWS retry, deployment attempt or invocation.
The final read-only check reused the existing strict operation/checkpoint functions,
compared actual restored versions and verified counters unchanged. No repeat billable
call or ordinary campaign retry occurred.

[Committed acceptance summary](../evaluations/full-live/acceptance-2026-11-11.json)
binds both tested commits (parent 870e350 and continuation 09ef680), review, budgets,
versions, complete diagnostics and evidence hashes. Retained authority:

- `artifacts/full-live/operations/continuation-approved-run/`: offline/agent JUnit,
  CDK/controller stdout/stderr/results, strict checkpoints and protected smoke.
- `audit/aggregate-audit.json`, SHA
  **ac1c238c422928de13fe6bdbca9232c4c4adf52e53f89d651ae5cbecff92e653**,
  reports accepted=true/errors=[] and 1,655 unique passes. Current appended AgentCore
  responses 19 are extracted separately from historical JSONL prefixes.
- `final-verification/final-checkpoint.json` records the final observed v15 state.
  Completion inventory `artifacts/full-live/verification/continuation-completion-inventory.json`
  binds 50 new-campaign/report/review/approval files. Parent 134-file inventory stays fixed.

### Budget, preservation and verification

New campaign **20/20**: parity 19 + protected smoke 1. Prior parent **37**; aggregate
**57/57**, zero remaining Runtime calls. Direct Athena remains **67** from the parent;
continuation submitted **0** direct queries. No failed/incomplete SDK attempt,
Runtime retry, extra warm-up or demonstration. Both durable claims/counters remain
blocked/exhausted; expiry 2026-11-13T23:59Z does not authorize reuse of spent quota.
Historical M4/M5/repair/UI ledgers are unchanged.

Aggregate 57 Runtime responses reported **118 model calls**, **175,099 input / 13,799
output tokens**. Parity server latency p95 **5.367s**; retained retail client p95
**9.011s**. Across direct and Runtime-internal Athena work: **117 unique queries,
313,177 reported scanned bytes**, zero missing scan diagnostics. These totals include
both parent/current protected smokes and exclude unrelated historical campaigns.

Preservation passed without discrepancies: **121 historical files, 25 session snapshots,
13 UI acceptance files, all 134 parent pins, 18 original preparation files and 18 corrected
preparation files unchanged**. Frozen ZIP 398/S3 VersionId V5, 25-file shared source,
canonical data/goldens, original restoration assets, M3/foundation resources and
permissions remain fixed. Only the approved trusted Runtime configuration updates and
normal corrected CloudFormation template asset publication occurred.

The lockfile, Ruff lint/format, mypy and offline data/foundation synthesis results
recorded for 09ef680 below cover this unchanged implementation. They were not rerun
for this documentation-only outcome. The supervised run did freshly execute the
full offline pytest suite. Documentation/link/preservation and diff checks cover
that final documentation change. Hosted CI was not claimed at the local completion
handoff; PR/main CI subsequently passed as recorded above.
Final documentation verification passed: **9 Markdown files, 85 local links, 30 shell
blocks parsed without execution**, acceptance JSON/evidence hashes and
`git diff --check`. All 50 completion-inventory files are unchanged. A scoped Git
check confirms only documentation and the new acceptance summary changed; application,
infrastructure, frozen inputs, counters and claims were preserved.

### Completed handoff

Completion commit 39d7edb was pushed, passed PR CI and merged through PR#9 at 1dfd788;
PR#8 is also merged. The merge facts and current interactive-session decision are
recorded above. The original completion handoff had not yet claimed hosted CI;
its local/live checks remain historical evidence. M1–M5/UI/full validation remain
complete for the development scope, and their exhausted allowances stay closed.

## Historical full-live-v1 attempt and continuation preparation at 09ef680

The user approved the exact plan at local commit **870e350** on November 11, 2026,
including the new 56 Runtime / 201 direct Athena caps and expiry
**2026-11-13T23:59:00Z**. This means November 13 at **5:59 p.m. CST**: a billable
execution cutoff, not permission to replay a campaign before that date. Start/switch
margins protect cleanup; nonbillable restoration remains available after expiry.
Approval is retained at `artifacts/full-live/approval-20261111.json`.

### Actual approved run and safe stop

Fresh identity/checkpoint/publication preflight passed at 18:10:03Z using only
`analytics-dev`, account 453711491609, us-west-2. The existing candidate ZIP/S3 VersionId,
25-file source closure/dependencies, canonical retail bindings, exact template/
parameters, policies and retention matched accepted **Runtime/DEFAULT READY v13**.
No profile, permission, code upload, source publication or dataset change occurred.

The supervised command was:

```sh
poetry run python -m infrastructure.agentcore.full_live preflight \
  --review evaluations/full-live/review.proposed.json \
  --output artifacts/full-live/operations/approved-preflight-20261111
poetry run python -m infrastructure.agentcore.full_live run --execute-approved \
  --review evaluations/full-live/review.proposed.json \
  --output artifacts/full-live/operations/approved-run-20261111
```

| Executed gate | Actual result |
| --- | --- |
| Offline pytest | **1,460 passed, zero skipped**, 85 deselected in 49.74s. |
| Direct Athena parity | **66 passed, zero skipped**, 1,479 deselected in 141.00s. All 67 expected logical queries completed. |
| Retail pytest | **1 passed, zero skipped**, 1,544 deselected in 249.95s; all **36/36** independent request/result cases passed, including sessions/auth/clarification. |
| Temporary parity deployment | **Not accepted.** CDK exited 0 and reported no changes; strict controller timed out after 130.342s without accepting the wrong configuration. |
| Agent parity | **18 items unrun**, zero parity requests. They are not passed or labeled skipped. |
| Mandatory cleanup | Exact accepted-retail proof at **18:20:29Z**, READY **v13**, stack UPDATE_COMPLETE. Already current; no mutation/new version. Protected Q18 **110.25 USD [2025-03-31,2025-04-01)** passed. |

The preparation missed CDK asset metadata: parity template bytes were 9b8415..., but
`manifest.json`'s template URL and the asset manifest's identity/key still pointed
at retail's faca6d23... cached template. This explains CDK's no-change result;
there is no evidence of an IAM denial or transport failure. The controller correctly
prevented parity questions running against retail. Its owned process was reaped,
return code 0, no cleanup signals. It then freshly verified unchanged retail and
spent the protected smoke. No deployment or billable retry followed the failure.

This requested full-validation acceptance is **incomplete: 67/85 live items passed,
18 unrun**. All selected executed tests had zero skips. Parent campaign is blocked
at **37/56 Runtime calls** (retail 36+smoke 1) and **67/201 Athena submissions**, with
zero failed/incomplete SDK attempts. Its durable claim and spent restoration phase
prevent ordinary reuse. Historical M4/M5/repair/UI budgets remain unchanged.
Retail client p95 **9.011s**; current 37 calls reported 77 model calls,
113,106 input/9,177 output tokens and 35 internal Athena queries/189,856 bytes.
Direct Athena 67 added 91,059 bytes; combined 102 queries/280,915 reported scanned bytes.

[Committed checkpoint](../evaluations/full-live/checkpoint-2026-11-11.json) binds the
raw run/controller/JUnit/retail/restoration evidence. Parent preservation inventory
pins **134 files**, SHA **5f60b2a02da1b0f84cb5872292382d92aa9e545831e3954a74aefa9984657dcb**.
Historical JSONL prefixes are unchanged; extracted new rows are retained separately.
The original 18 preparation files are unchanged, including the defective parity copy.

### Offline correction and proposed continuation

- Added complete CDK asset consistency validation and a repair applied only to fresh
  copies. Check actual template bytes against stack URL, asset identity/source,
  every destination and full metadata/file inventory before any AWS client.
- Prepared `artifacts/full-live/prepared-v2/`: parity template 9b8415... unchanged;
  corrected only its two metadata files. Retail restoration matches the accepted
  assembly byte-for-byte. ZIP 398/S3 V5, source closure, goldens and permissions remain fixed.
- Added a separate strict continuation review/counter and operator. Preserve parent
  bytes and actual 37/67 accounting before dispatch, use fresh retail-v13 preflight,
  run only missing 18 items/19 requests, and always restore retail+protected Q18 smoke.
  No new real continuation ledger/claim or AWS operation was created in preparation.
- New proposal is **20 calls**, prior 37, **aggregate 57**: **one additional call beyond
  the original 56 approval**. The nineteen original unused calls cannot also fund a
  replacement smoke; counters cannot be reset/reopened. Execution requires a new
  explicit decision. No passed Athena/retail suite is repeated.

[Continuation plan](full-live-continuation-proposal.md) and
[review](../evaluations/full-live/continuation.proposed.json), SHA
**70161d5cb64bdc44f72a1cd61a3df614c53bdd879bb102e21a6c28dc07f0bc8a**,
pin prepared inventory **8d1b2b88f933d80e7283019bcae5dcaeae8e3fb05fa622d665964ca3de249bd2**.
Expiry remains November 13 23:59Z. Offline readiness verifies **0/20 new**, prior 37,
aggregate 37/57, with no ledger/claim created. The original review/pins are unchanged.

### Actual correction verification

| Command | Actual final result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **1,570 passed, 85 deselected in 51.31s; zero skipped**, no AWS flags/calls. |
| `poetry run pytest tests/test_full_live_workflow.py tests/test_full_live_assembly.py tests/test_full_live_continuation_workflow.py tests/test_full_live_continuation_budget.py -q` | **150 passed in 2.75s**. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 161 files already formatted. |
| `poetry run mypy src tests infrastructure/agentcore/full_live.py infrastructure/agentcore/full_live_continuation.py` | Passed: 129 source files. |
| Offline data/foundation CDK synthesis | Both passed into separate `artifacts/full-live/verification/metadata-fix.cdk-{data,foundation}.out`, without lookups/credentials. |
| New preparation + continuation `verify-offline` | Passed: full metadata/inventory/source/parent pins; 0/20 new, prior 37/aggregate 37/57, no campaign/claim created. |

The first correction-wide pytest found one captured-default preparation-path
regression; fixed dynamic default resolution, reran 150 affected regressions and then
the full suite above. Meaningful new coverage includes the exact stale-URL defect,
changed asset keys/destinations, rejection before AWS, preserved source/restoration,
parent tampering/missing/alias detection, aggregate budget, duplicate claims,
interruption, process cleanup and mandatory restoration. No test expectation or
metric/golden was weakened to obtain a pass.

Final documentation checks passed: **7 Markdown files, 65 local links, 17 shell
blocks parsed without execution**; `git diff --check` passed. Preservation verified
**121 historical files, 25 session snapshots, 13 UI acceptance files, all 134 parent
pins and 18 original preparation files unchanged**. Only two parity metadata files
differ in the fresh preparation. No real continuation ledger or claim was created.
Hosted CI does not cover these new local commits. The old UI PR/CI evidence below is
unchanged and must not be attributed to this correction.

### Historical handoff before continuation approval

At this checkpoint, the next decision was to approve or decline the
[20-call continuation](full-live-continuation-proposal.md), including the one-call
increase to aggregate 57. Only after approval: fresh exact retail-v13 identity/
artifact/publication/process preflight, corrected parity deployment, missing 18 agent
items, mandatory accepted-retail restoration and protected smoke. Do not rerun/reopen
full-live-v1. Keep commits local, PR #8 unchanged/unmerged. M1–M5 and the earlier UI
acceptance remain complete; the new full-live validation remains incomplete.

## Preparation checkpoint at 870e350 — historical, before approval

The user clarified that all **85 live tests must actually run**. Test exclusion is
not accepted as live coverage. Prepared a separate full-validation operator and
[concrete execution plan](full-live-validation-plan.md), without an AWS call or
billable invocation. Live execution remains pending the new scoped budget/configuration
approval required by the repository's existing allowance rules.

Started clean on the completed UI branch at `0c5b57e2427f3932c5407f46b991406397b704c9`;
read instructions/progress/plan, inspected Git/environment, and isolated this new
preparation on local **`feat/full-live-validation`**. PR #8 and its pushed head/CI
remain unchanged. Existing Conda Python 3.12.16 / Poetry 2.3.1 and lockfile are reused.

### Prepared implementation and exact scope

- New `FullLiveReview`/`FullLiveBudget` and adapter SDK guard bind profile/account/
  region/Runtime/configuration/pins and reserve every dispatch durably. Maximum
  **56 Runtime invocations**: retail36 + parity19 + protected restored-retail smoke1.
  Direct Athena cap **201 total StartQueryExecution SDK attempts**, including
  existing idempotent/terminal retry behavior; no Runtime SDK retries or extra reserve.
- New operator runs every offline test, **66 direct Athena items**, **one retail
  campaign item (all36 requests)**, then a temporary candidate/parity configuration
  for **18 agent items (19 requests)**. Exact suite/JUnit counts, no skipped/duplicate
  items, complete retail reports and actual dispatch totals are acceptance gates.
- Typed trusted live dependencies let the existing retail runner use the new
  candidate-aware checkpoint/counter. The default historical path is unchanged:
  no closed M5/repair/UI ledger is reset or redirected. No metric/contract/agent
  calculation or runtime artifact change.
- Temporary parity changes only dataset `parity-v1`, tenant `t1`, reference
  `2025-02-01`; candidate ZIP398/S3V5 and all other properties remain unchanged.
  The operator restores accepted candidate/retail config and runs full Q18 smoke
  **110.25 USD [2025-03-31,2025-04-01)**. It records actual resulting versions.
  Start requires four hours left; parity update requires two hours for bounded
  tests/restoration. Nonbillable cleanup is independent of source/canonical/accounting
  availability; untrusted accounting blocks smoke and records unknown usage.
- Default pytest/CI explicitly select the offline suite and `--fail-on-skip` makes
  a selected skip fail verification. The 85 excluded live items are never labeled
  passed; only the separately executed staged campaign can satisfy that requirement.

Review: [review.proposed.json](../evaluations/full-live/review.proposed.json), SHA
**bd3724d46181ec3e7b0181987c48d3a535ab4815d02897305cd36b7ba44d8845**,
proposed expiry **2026-11-13T23:59:00Z**. This is not an extension of any old approval.
Prepared copies/inventory: `artifacts/full-live/prepared/`.
Parity template SHA **9b84152070e6e5babf4f2469abdde3a6e504d29c8887127a155f71ab871df83d**;
retail restoration template remains **faca6d23...**. The complete M3 configuration is
also pinned, preventing an alternate profile from being selected before clients exist.

### Actual offline verification

| Command | Actual result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **1,460 passed, 85 deselected in 52.77s; zero skipped**. This is offline verification, not the requested live acceptance. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 155 files formatted. |
| `poetry run mypy src tests infrastructure/agentcore/full_live.py` | Passed: 124 source files. |
| Offline CDK data/foundation synthesis | Both passed into separate `artifacts/full-live/verification/` directories; no lookups or credentials. |
| `python -m infrastructure.agentcore.full_live prepare` / `verify-offline` through Poetry | Passed: exact retained ZIP/source/dependencies/canonical inputs, environment-only parity delta and review-bound inventory. Final evidence `artifacts/full-live/offline-readiness.final.json`. |
| Failure/recovery and gate regressions | Source/config drift, no implicit profiles, skip-failure/empty-suite rules, 56/201 caps, SDK retry/unknown outcomes, primary-error preservation, interruption, exact JUnit counts, protected smoke, and cleanup independent of unavailable source/accounting covered. |

Historical verification counts remain unchanged below. Official pytest marker,
hook and fixture documentation was checked for these changes. Final checks passed:
**6 Markdown files, 55 local links, 14 shell blocks parsed without execution**,
review JSON/model/pins and `git diff --check`. All **121 present protected files**,
**25 session snapshots** and **13 UI acceptance evidence files** remain unchanged.
Fresh offline readiness records **0/56 Runtime calls, 0/201 Athena submissions**,
with no real campaign/claim created. No new live ledger,
claim, profile, permissions, source publication, artifact rebuild/upload or deployment
was created; last accepted AWS state remains the recorded candidate/retail **READY v13**.

At this historical preparation checkpoint, execution approval and all 85 live items
were still pending. The actual approved run and corrected continuation status above
supersede that handoff; its original command results remain evidence of preparation.

## Completed task: shared UI deployment and live acceptance — passed; PR #8 handoff

Approved scope at `a1132205b54b31dcec712425a8a0861f650fdcfa` executed on November 11,
2026, using only analytics-dev / account 453711491609 / us-west-2. GitHub confirms
that approved commit is pushed and [CI 43060085091](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/43060085091)
passed for that exact SHA. Metadata is retained at
`artifacts/ui-shared/github/20261111T164640Z/approved-commit-ci.json`. Final outcome
PR/CI coverage is reported separately in the handoff, without another self-CI commit.

### Actual deployment and acceptance

- Fresh original preflight passed at **16:46:09Z**: original Runtime/DEFAULT READY v12,
  exact code/version/config/template/parameters, both policies, retention, process
  guards and canonical publication. Review SHA matched the approved
  `168abce7775cf9620992c545037643193c41b6756e61179f093c5a8a5653283d`.
- Bounded controller deployment succeeded, updating only the existing Runtime's pinned
  candidate code/version and trusted retail configuration. Runtime/DEFAULT are
  **READY v13**, runtime stack **UPDATE_COMPLETE**. Final exact proof at **16:58:11Z**
  reverified artifact/configuration/templates/parameters/policies/retention/publication.
  The matching candidate remains deployed; no original restoration was needed.
- Protected Q18 verification passed full plan/result **110.25 USD [2025-03-31,2025-04-01)**.
  All **18 actual-UI paired outcomes passed**, nine reviewed questions per backend,
  against frozen independent plans/values, including all five metrics, filters,
  relative dates, clarification and authorization boundaries.
- The user submitted Q02 once per mode, then explicitly confirmed those two calls.
  Automation's pre-dispatch ledger read encountered that in-flight lock before sending
  any question. Paused the UI, preserved/graded both outcomes, confirmed ownership and
  resumed only the other sixteen cases. No duplicate question or billable retry.
- Final campaign **19/20**: verification1 + regular18 + rollback0. All regular slots
  are exhausted; protected smoke unused. SDK work **16 direct Converse attempts**,
  **10 Runtime invocations**, zero failed/incomplete attempts. Expiry remains
  **2026-11-11T23:59:00Z**; no extension/reset/remainder reuse.
- Pair p95 execution latency: local **4.186s**, AWS **8.926s**. Local pair tokens
  **23,283 input / 1,750 output**; AWS pair tokens **25,149 / 1,819**. Paired AWS
  queries **7 / 41,157 scanned bytes**; including protected Q18 **8 / 46,172 bytes**.
  These execution timings exclude separate read-only preflight overhead; browser
  per-case logs also preserve end-to-end UI timing. Model prose/call counts can differ.

### Evidence, preservation and verification

[Committed acceptance summary](../evaluations/ui-shared/acceptance-2026-11-11.json)
binds observed versions, results, budget and evidence hashes. Retained raw authority:

- `artifacts/ui-shared/operations/approved-deploy/`: deployment logs, controller
  reconciliation, exact original/candidate checkpoints and actual-version release record.
- `artifacts/ui-shared/verification.json`, `paired-report.json`,
  `final-preflight.json`, and complete browser/counter/operator evidence.
  Paired report SHA **5b9db8c3b90d44d5fc63f42367dd36fd7cb158e1ab340bb5c4dc6910cdec613d**;
  final proof SHA **0f4b438fb5264b6d3ec5f28df160dca854765a76a87ed7384c5a6f3ea9159324**.
- `artifacts/ui-shared/acceptance-evidence-inventory.json`: **218** files captured at
  acceptance, SHA **b03ce3ae161494489daebb3bd980b00a83da579e35b269443d3a80861a197349**.
  Later final-commit GitHub evidence is separate from that capture.
- Two validated nine-case viewer exports, `replay-local-agent.json` and
  `replay-aws-agentcore.json`, explicitly marked replay and bound to the paired report.
  New screenshot `docs/images/analytics-workbench-live-accepted.png`; old images intact.

All **121 present protected files** and **25** session snapshots are unchanged:
original/candidate ZIPs, actual S3 VersionIds, corrected original assemblies, canonical
inputs, goldens, prior ledgers and claims. M4 28/40, original M5 closed38/40, repair1/40,
continuation1/39, recovery closed38/38 (aggregate40/40) remain intact. No rebuild,
upload, dataset/publication, permission/trust, bootstrap or retained-infrastructure
change occurred. Supplied policy provenance remains administrator-reported; actual
direct Bedrock/candidate execution succeeded, without another denied IAM inspection
or a claim to enumerate every effective policy/attachment.

Commands actually executed include the reviewed ui_workflow preflight/deploy commands,
one ui_shared protected verification, eighteen actual UI submissions (two by user),
paired_report and final candidate preflight. Each automated question was judged before
continuing. The task-owned browser and server were stopped after evidence capture.

Final repository changes are documentation, a screenshot and acceptance JSON only.
`git diff a113220 -- src tests infrastructure pyproject.toml poetry.lock` is empty.
The same implementation already passed today's required checks: **1,331 tests passed,
85 live-gated skips**, lockfile, Ruff, formatting and mypy; hosted CI 43060085091 also
covers that exact source. Those unchanged checks/syntheses were not needlessly rerun.
Final documentation/link/shell syntax, JSON/model validation and evidence/preservation
checks passed: **8 Markdown files, 73 local links, 34 shell blocks parsed without
execution, 1 JSON block, 218 evidence-file hashes, two nine-case viewer exports**.
`poetry run python /private/tmp/ui-approved-closeout-check.py` and `git diff --check`
passed. Source/infrastructure/lockfile diffs from the approved commit are empty.
Final staged-scope review accompanies the outcome commit; its hosted CI links are
returned in the session handoff rather than recorded by a self-CI follow-up commit.

### Exact next task and launch

The session handoff supplies the normally pushed outcome commit, UI PR and verified
exact-commit CI links. The next task is **user review and merge decision**. No new milestone, further
billable question or production-readiness claim is implied. Additional live UI work
needs a separately approved allowance; the protected slot cannot fund demonstrations.
Historical original-v12 restoration remains recorded; observed UI steady state is v13.

Valid offline/saved-result launch from the original checkout:

```sh
conda activate enterprise-analytics
poetry run python -m enterprise_analytics_agent.ui \
  --report artifacts/ui-shared/replay-aws-agentcore.json --port 8501
```

Choose **Saved runs**. This replays recorded AWS acceptance without another call.
Omit `--report` for the offline playground. The spent live-review startup is
intentionally blocked; do not advertise it as an enabled allowance.

## Previous task: administrator policy review — completed before execution approval

On **November 11, 2026**, continued on clean `feat/local-testing-ui` at local
implementation `d3925321b3631e355e08dda34c9b552faaf6185c`. Read root instructions,
current progress/implementation plan and shared UI runbooks; inspected status/history
and verified the existing Conda Python 3.12.16 / Poetry 2.3.1 interpreter. No branch
switch or unrelated changes. No AWS service call occurred during this review.

Recorded the two administrator-console documents supplied by the user in
[evaluations/ui-shared/admin-policy-evidence.json](../evaluations/ui-shared/admin-policy-evidence.json),
including unchanged semantic contents, canonical JSON hashes, reported role
associations, exact required actions/ARNs and explicit verification limitations.

- PowerUserAccess's Allow/NotAction excludes IAM, Organizations and Account, leaving
  `bedrock:InvokeModel` allowed on `*`: the configured Nova Lite inference profile
  and all three regional model ARNs have **policy-content coverage**.
- The runtime candidate-code statement explicitly allows `s3:GetObject` and
  `s3:GetObjectVersion` on the exact accepted candidate key; the pinned S3 VersionId
  remains separately enforced.
- Association with the named roles is **administrator-reported**. Current attachment,
  default-version identity and effective access are **not independently verified**.
  These documents do not enumerate boundaries/session policies, organization controls
  or other applicable denies. The historical denied IAM inspection establishes no
  missing Bedrock/S3 access. **No specific gap, duplicate grant or IAM change is proposed.**

Finalized [the concrete proposal](ui-shared-code-live.md): reuse the accepted frozen
candidate/S3 version and prepared assemblies; analytics-dev only, account 453711491609,
us-west-2. New UI allowance remains **0/20, uncreated**, unchanged review hash
`168abce7775cf9620992c545037643193c41b6756e61179f093c5a8a5653283d`,
expiry **2026-11-11T23:59:00Z**. Allocation: Q18 verification 1, nine frozen questions
in each agent mode 18, protected original-restoration smoke 1. Successful acceptance
leaves the matching candidate/retail release; failed deployment/evaluation requires
original restoration and smoke. Fresh exact original-v12/process/source/publication
preflight is mandatory during later approved execution. November 10 AWS observations
are retained historical evidence, not a new effective-access/READY assertion.

Independent read-only review found no further implementation blocker. Corrected the
runbook's shared ledger filename to `question-attempts.jsonl`. Application code,
IAM/infrastructure definitions, review/pins and all frozen inputs are unchanged.
Policy evidence is documentation, never an input to IAM deployment.

### Actual offline verification — November 11

| Command/check | Actual result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **1,331 passed, 85 live-gated skips in 45.10s**; no AWS/live markers. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 147 files already formatted. |
| `poetry run mypy src tests` | Passed: 117 source files. |
| `poetry run python /private/tmp/ui-admin-policy-offline-check.py` | Passed; narrow policy-content/hash/action/resource assertions, 25-file source/dependency/canonical verification, prepared assembly inventories and 25 retained session snapshots unchanged. AWS Session construction is forbidden by the check. |
| Documentation/JSON/diff/preservation checks | Passed: 7 Markdown files, 58 local links, 20 shell blocks parsed with `zsh -n` without execution; supplied evidence JSON/hashes validated. All 121 present protected files and 25 session snapshots unchanged; the historically absent untracked patch remains absent. `git diff --check` passed. |

Offline review evidence:
`artifacts/ui-shared/policy-review/20261111T163148Z/offline-review.json`.
The new question allowance was not created; all historical ledgers/claims remain
unchanged (M4 28/40, original M5 closed 38/40, repair 1/40, continuation 1/39,
recovery closed 38/38, aggregate repair 40/40). Prior offline CDK syntheses remain
valid for unchanged infrastructure/source and were not rerun for this evidence-only
update. Official IAM NotAction/evaluation, Bedrock routing and S3 permission references
were checked and linked in the proposal. No upload, deployment, new profile, IAM
change, Athena execution or billable invocation occurred; no push/merge is authorized.

### Exact next task

Review/approve the finalized candidate deployment, 20-attempt allocation, expiry,
success steady state and failure rollback **with the administrator-reported policy
evidence limitations understood**. Deployment and billable questions stay paused
until that decision. If approval arrives after expiry or cannot leave adequate cleanup
time, obtain a separately reviewed unconsumed allowance/window; do not silently edit
the existing review or reset a ledger. Current content establishes no need for another
grant. Preserve all historical proof-of-concept completion evidence.

## Previous preparation: shared Bedrock UI — November 10 implementation evidence

Continued in the **original Mac checkout** on `feat/local-testing-ui`, based on
`c6e6818fb134ed67249d3eab2bdec7149df2a57b`; branch/history and working tree inspected.
The user's 19 existing UI files were backed up before changes at
`/private/tmp/analytics-ui-before-20261110T202858Z`, with hashes and tracked diff.
No branch switch, reset or unrelated overwrite. The downloaded preflight patch
passed forward `git apply --check`, was applied once, then passed reverse checking.
Subsequent implementation intentionally extends its files.

Completed three explicit UI modes: deterministic/AWS-free offline playground,
billable local `BedrockAnalyticsAgent` with canonical DuckDB, and billable shared
AgentCore/Athena. Both use the existing agent/catalog/v2 contracts/guard/tools;
cost notices precede submission. Browser scope/config/history overrides are rejected.
No runtime/metric/contract/dependency change or artifact rebuild is required.

The accepted candidate's **25-file** common closure matches exactly, fingerprint
`aefa4ffa38d1d52ad152e98e0293356221bc964be86e3022c12c6871545830be`.
Original ZIP differs in the Q18 agent/question files. Frozen dependency versions/
checksums match, with macOS versus ARM64 platform limits explicit. Canonical
seven-table bytes/schemas/provenance and 36 goldens verify. Offline report:
`artifacts/ui-shared/preparation/offline-release-audit.json`, SHA
`ae2e41af49661cc82a2fbf2f1f59e2f0eaf5ce3fa5bf07692902bfc9a64237f9`.
Prepared exact candidate/rollback assembly copies and inventory at
`artifacts/ui-shared/deployment/`; pins are in [the runbook/proposal](ui-shared-code-live.md).

Fresh **read-only** analytics-dev STS verified account `453711491609`/us-west-2.
Evidence at `artifacts/ui-shared/preflight/20261110T204310Z/`: actual Runtime/DEFAULT
**READY v12**, stack **UPDATE_COMPLETE**, exact original artifact/config/templates/
parameters, both policies, seven-day retention and process guards passed. Candidate
S3 version and fresh canonical downloads verify. Nova Lite profile/routing/availability
passed. Additional `20261110T212343Z/publication-proof.json` verifies eight latest
S3 identities, seven exact single-object table prefixes and seven Glue bindings.

At the November 10 preflight, administrator policy contents were pending: IAM
simulation and runtime inline-policy inspection returned AccessDenied. These establish
**inspection limits, not missing Bedrock/S3 permission**. The November 11 review above
records the subsequently supplied contents and their limitations. No profile/permission
change, deployment, upload, Athena execution, Runtime invocation or billable model call occurred.
Matching retained source is established; the active original-v12 release differs,
so shared live equivalence remains pending.

Persistent `ui-shared-live-v1` counting reserves/fsyncs question and SDK receipts
before dispatch; no billable retries, failures/unknowns retained, UTC expiry and
protected verification/rollback slots enforced. Both modes share one new allowance.
Release records bind actual observed versions; strict source/config/data checks run
before every new attempt. Offline paired reporting judges complete frozen plans/
results and missing diagnostics. The operator workflow uses bounded exact-state
deployment reconciliation, retains failures/interruption evidence, and restores the
independent original on deployment failure. Evaluation failure requires the explicit
rollback/smoke commands. Cleanup works independently of candidate/canonical inputs
and after expiry; new billable smoke still obeys expiry.

The proposed new campaign `ui-shared-retail-v1-01` is **0/20, uncreated**, expiry
**2026-11-11T23:59:00Z**: Q18 verification 1 + paired regular questions 18 + protected
original-restoration smoke 1. All five historical ledger files and claims remain
unchanged: M4 28/40; original M5 closed 38/40; repair 1/40; continuation 1/39;
recovery closed 38/38, aggregate repair 40/40. Success would leave the matching
candidate/retail deployment; rollback restores original/parity and disables shared
billable modes. No remainder is reused and no new milestone begins.

### Actual local verification for this preparation

| Command actually run | Result |
| --- | --- |
| Environment assertion / `poetry run python` | Existing enterprise-analytics Conda Python 3.12.16, Poetry 2.3.1; no dependency/environment replacement. |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **1,331 passed, 85 explicitly gated skips in 47.24s**. No AWS/live markers. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 147 files formatted. |
| `poetry run mypy src tests` | Passed: 117 source files. |
| `node --check src/enterprise_analytics_agent/ui/assets/app.js` | Passed. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.example.json --outdir artifacts/ui-shared/verification/cdk.data.out` | Passed offline; separate output, no account lookup. |
| `poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.example.json --phase foundation --outdir artifacts/ui-shared/verification/cdk.foundation.out` | Passed offline; reviewed assemblies untouched. |
| `poetry run python -m infrastructure.agentcore.ui_workflow prepare --review evaluations/ui-shared/review.proposed.json --output artifacts/ui-shared/deployment` | Passed; copies/validates retained candidate and original inventories, no upload/build/deployment. |
| Endpoint regression, original versus fixed | Original **1 failed**, corrected **1 passed**; isolated module replacement, no production rollback. Logs: `/private/tmp/ui-endpoint-regression-20261110/`. |
| Shared release/publication/workflow/source tests | 90 passed; state drift, exact version/template/config, missing source, bounded reads, failed/interrupted/expired deployment and independent rollback. |
| Shared operator/HTTP boundary + paired report | 36 + 16 passed; full injected command paths, all metrics, scope/session boundaries, canonical drift before reservation, full Q18 plans/values and offline report gates. |
| Documentation and preservation audit | 7 Markdown files, 53 local links, 20 shell blocks parsed with `zsh -n` without execution; fences/newlines valid. 121 present protected files and 25 session snapshots unchanged. The old untracked `milestone-5-q18-fix.patch` was already absent; not recreated. |
| `git diff --check` / staged scope review | Passed. No frozen assets, credentials or generated data staged. |

The first sandbox baseline hit 17 loopback-binding errors; the permitted rerun uses
loopback for offline HTTP fixtures. Final full-suite failures in two pre-existing
checkpoint tests were fixed by distinguishing Runtime reads from the new publication
reads and adding their own bounded retry/diagnostic regressions. Final tests above
cover the current code. Logs are under `/private/tmp/ui-shared-*`; ignored raw cloud
evidence remains local. Default CI stays AWS-free. No hosted CI is claimed for this
unpushed UI commit.


Browser checks used the actual default offline server: one fresh question rendered
exact typed DuckDB results with generated-sample labeling; local Bedrock and AWS cost
notices appeared before submission and their buttons stayed disabled; switching
modes cleared the visible prior answer. Desktop 1440px and mobile 390px had no document
overflow. Browser network evidence showed only localhost requests; the sole console
error was the harmless missing favicon (404). Separate screenshot:
`docs/images/analytics-workbench-shared-ui.png`; original screenshot preserved.
Task-owned browser/server were stopped. No live flags were enabled.

### Exact next task for the UI follow-on

The administrator policy-content review is now recorded above. Obtain explicit
approval of [the finalized deployment/20-attempt proposal](ui-shared-code-live.md)
with its reported-association/effective-access limitations before any mutation or
billable question. Repeat fresh original-v12/process/source/publication checks at
execution time; bind the actual resulting candidate version.
Keep this implementation commit local. Historical M1–M5 completion/CI evidence below
does not cover these new UI changes.

## Historical supplied preflight patch — isolated handoff evidence

The user completed local UI testing and requests live AWS testing with a common
codebase. GitHub main remains `c6e6818`; the remote branch list does not yet contain
the local UI branch. Continued from the previously supplied UI patch in an isolated
`fix/ui-aws-readiness` branch, preserving the user's separate original checkout.

Found and fixed a UI preflight bug: the actual AgentCore endpoint response exposes
`liveVersion`, not `agentRuntimeVersion`. The previous fake response reproduced the
same incorrect field as the implementation. The updated fixture is now validated
against the installed SDK's `GetAgentRuntimeEndpoint` response shape. Its successful
dispatch regression failed with `KeyError` against the original patch, then passed
with the one-field correction. Runtime/endpoint identity and all other strict
checkpoint gates remain intact; no retry, quota or IAM change was introduced.

Added `infrastructure.agentcore.source_audit`, an offline checksum-pinned ZIP comparison
against the local runtime/agent/DuckDB static import closure and entrypoint. The current
closure contains **25** files; this is an explicitly scoped comparison, not the earlier
28-file preservation inventory or a claim that all packaged operator files match.
It follows package/relative imports without executing inspected code and returns
nonzero on changed/missing source or invalid archive/checksum. Actual restoration and
candidate ZIP audits still require the retained files in the original checkout.

[The shared-code handoff](ui-shared-code-live.md) records the important distinction:
the two modes currently share semantic code, but local bypasses the Bedrock agent,
and the last recorded AWS original-v12 archive predates the Q18-corrected source.
For identical agent behavior, reuse `BedrockAnalyticsAgent` in both runners with
DuckDB/Athena adapters, make local Bedrock usage explicit and counted, and match the
actual release/configuration and verified data. That runner/release alignment is
**not yet implemented or deployed** by this preflight patch. The detailed task is
prepared for Codex in the original checkout, which has the artifacts and AWS session.

Verification: **1161 passed, 85 gated skips in 96.29s**; targeted UI/audit tests
**75 passed**. `poetry check --lock`, Ruff lint/format (**137 files**),
`mypy src tests` (**108 source files**) and `git diff --check` passed. Official AWS
endpoint/Converse documentation was consulted. No AWS SDK operation, invocation,
profile/IAM change, source upload, deployment, push or merge occurred. Historical
campaigns, frozen assets, runtime source and semantic definitions remain unchanged.

Next: apply this incremental patch once in the original UI checkout and follow
`docs/ui-shared-code-live.md`. Complete shared-agent wiring and read-only release,
configuration, data and permission verification; produce the concrete new bounded
live proposal before deployment/invocation. Keep the existing original-v12 guard until
a separately reviewed replacement is implemented; do not bypass it to enable a toggle.

## Historical supplied local UI — isolated implementation evidence

The user separately requested a professional UI with a **Local DuckDB / AWS AgentCore**
toggle. Prepared `feat/local-testing-ui` in an isolated snapshot of main
`c6e6818fb134ed67249d3eab2bdec7149df2a57b`; all 155 baseline tracked file blobs matched
the GitHub tree before editing. This environment is not the original Mac checkout.
The portable patch applies to the real main tree; the local snapshot's Git ancestry
is not a replacement for the repository history.

[PR #7](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/7) is merged at
that SHA, and [main CI 42876498184](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42876498184)
passed for it. This closes the earlier documentation branch's pending merge/CI state.
Those hosted results cover the baseline, **not this new UI implementation**.

Implemented a loopback browser workspace with responsive styling, backend toggle,
suggested questions, exact typed result tables, Execution/JSON tabs, saved-run
upload/replay/download, a metric catalog and a code guide. Local mode uses the existing
question guard, generated temporary Parquet and real DuckDB semantics; it calls no LLM
or AWS service. AWS mode uses only analytics-dev and the existing original-v12 strict
checkpoint/invocation adapters. It requires a separately approved 1–20-call review,
expiry, persistent UI ledger/reservation receipts and the existing operator/deployment
leases. No automatic invocation retries or infrastructure mutation route was added.
See [local-ui.md](local-ui.md) for launch commands, examples and the concrete live proposal.

Verification actually run in Python 3.12 / Poetry 2.3.1, using the existing locked
environment and this checkout's `src` on PYTHONPATH:

- `poetry run pytest -q`: **1155 passed, 85 gated skips in 109.21s**. The 69 new UI
  cases cover independent accounting fixtures, HTTP/input boundaries, replay/missing
  diagnostics, failed/uncertain/duplicate dispatch, review/receipt binding and AWS
  adapter behavior with fake transports. No live marker was enabled.
- `poetry check --lock`, `poetry run ruff check .`,
  `poetry run ruff format --check .` (**134 files**),
  `poetry run mypy src tests` (**107 source files**) and `git diff --check` passed.
- `node --check src/enterprise_analytics_agent/ui/assets/app.js` passed. Node is a
  verification tool only, not an application dependency.
- The binary portable patch applied cleanly to a separate baseline worktree; all
  19 resulting files matched this implementation byte-for-byte. Documentation
  relative links and fenced blocks passed inspection.
- Browser QA passed real local single/multi-metric questions, execution details,
  metric catalog, AWS-disabled routing, JSON download and saved-response upload/replay.
  Layout had no document overflow at **1348px** and **449px** CSS widths; the narrow
  backend toggle remained usable. A screenshot is retained in `docs/images/`.
  The browser's DevTools policy prevented device emulation; the narrow breakpoint
  was checked using ordinary browser zoom. Test servers were stopped afterward.

All existing application/runtime source, dependencies, evaluation inputs, goldens and
infrastructure files remain byte-identical to the main snapshot. Only documentation
is edited among pre-existing files; UI implementation/tests and the guide/screenshot
are additions. Original ignored ZIPs, deployment assemblies and historical ledgers
were not available in this isolated checkout and were not opened, rebuilt or modified.
No AWS operation, invocation, profile/IAM change, deployment, push or merge occurred.
M1–M5 completion and all historical live accounting remain unchanged.

Next: apply/review the patch in the original checkout, launch local mode, then commit,
push and review hosted CI if desired. Optional AWS testing needs explicit approval
of the new scope/cap/expiry and a fresh original-v12 preflight with retained files;
the completed M5 aggregate cannot fund it. Local UI readiness is verified; new UI
live acceptance and hosted CI have not run.

## Completed milestones and retained repository history

**Milestones 1–5 are complete for the agreed development proof of concept.** M5 is implemented, deployed against the frozen retail candidate, live-validated, merged into main and verified by hosted CI. [PR #6](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/6) merged **November 10, 2026**, at [`c0d2c5a569e2d242bf840a715c31050888b579ab`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/c0d2c5a569e2d242bf840a715c31050888b579ab), containing completion commit [`7905d13f59e13d0b5a1b11231348721471a19411`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/7905d13f59e13d0b5a1b11231348721471a19411). [Main CI 42872516193](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42872516193) passed for that exact merge; GitHub API metadata and local merge ancestry confirm the associations. These hosted results cover the named merge, not this documentation closeout.

Historical acceptance remains unchanged: Q18 **110.25 USD [2025-03-31, 2025-04-01)** passed, all **36 frozen suite requests** passed, and original restoration/smoke passed on **Runtime/DEFAULT READY v12**, runtime stack **UPDATE_COMPLETE**. Recovery is closed **38/38**, aggregate repair **40/40**, with no invocation failures/retries/incomplete reservations. Original M5 **38/40**, M4 **28/40**, both earlier repair histories, frozen assets/goldens and claims remain preserved. The v12 checkpoint was verified during the completed live window; **no AWS operations or live invocations were performed for this documentation closeout**. Any further development requires a separately defined scope. Production readiness is not established.

Reviewed operator `f223877` passed [push CI 42861036450](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42861036450) and [PR CI 42861051831](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42861051831). Completion `7905d13` passed [push CI 42870548228](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42870548228) and [PR CI 42870557328](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42870557328), as verified in the completion handoff. Those earlier results remain separate from merge CI and this documentation branch's own checks.

**Milestone 4 — implemented, deployed, live-validated, merged into main and verified by hosted CI for the agreed development scope.** [PR #4](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/4) merged on November 8, 2026, at [`47c3afc1dd948fa8ddcb074151b9f22af31dad48`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/47c3afc1dd948fa8ddcb074151b9f22af31dad48), containing completion commit [`51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf). The completion commit passed [push CI 42515746487](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515746487) and [PR CI 42515722610](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515722610); the merge passed [main CI 42516820774](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42516820774). GitHub API metadata confirms the PR/commit/run associations. Recorded live evidence remains **18 + 3 + 3 tests plus warm-up**, **28/40 invocations used**, corrected `parity-v1` restored, Runtime `enterprise_analytics_dev_agent-HlWywlG60h` and DEFAULT **READY on version 4**, and runtime stack UPDATE_COMPLETE. The reviewed artifact/S3 VersionId, M3 infrastructure, query trust and permissions remain unchanged. Historical live tests were not rerun; M5 read-only verification below freshly confirms the deployment checkpoint without modifying it. No production-readiness claim.

Milestone 4's documentation handoff is also merged: Git records PR #5 at `d7e0f19e646f239bcf2f2641cb829cd1090be562`, with parents `47c3afc` and `39523f402c6cdf499b162efaccff72282fc8f360`. After `git fetch origin` and `git merge --ff-only origin/main`, clean main/HEAD/origin/main matched `d7e0f19` (already up to date). Created the requested feature branch without resetting or discarding work. Earlier hosted CI results below cover their named M4 commits; no CI result for PR #5 or this new planning commit was inferred.

**Milestone 3 is complete: implemented, deployed, live-validated, merged, and hosted-CI verified.** The user confirmed [PR #2](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/2), merge [`ae378e4c289144164a8a7a6a85fa8c71ae5bcacc`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/ae378e4c289144164a8a7a6a85fa8c71ae5bcacc), and successful [CI run 42166641840](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42166641840). Milestone 4 implementation originally started from main `6bf1220`, containing that merge and its documentation update. Historical AWS/live results below retain their user-executed attribution; that parity suite was not rerun during milestone 4 preparation.

**Milestone 2 remains implemented, merged into `main`, and verified by hosted CI.** [PR #1](https://github.com/sureshkm-ai/enterprise-analytics-agent/pull/1) merged implementation commit `e13b1ea` at merge commit `9dc5989353459e2651ba5cced882534d8d573783`. [GitHub Actions run 42113416826](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42113416826) passed for that merge commit, as confirmed by the user.

## Documentation closeout — 2026-11-10

Verified PR #6's merged state/date, exact head/completion and merge SHAs, and the successful main push run against GitHub. `git fetch origin` confirmed `origin/main` at `c0d2c5a569e2d242bf840a715c31050888b579ab`; its second parent is completion `7905d13`, and the merge tree matches that completion tree. Started with a clean working tree on the old feature branch and created **`docs/milestone-5-closeout` directly from fetched `origin/main`**, without resetting, stashing or overwriting local work. No synchronization claim is made for the separate local `main` branch.

Reconciled current merge/CI/next-task statements in README, root instructions, implementation/architecture/deployment documents and M5 plans/runbooks/proposals. Dated failure, approval, recovery and verification entries remain historical, with original attribution and pins. The next task is now to define a separate scope before any further development; production/per-user authorization, broader vocabulary, long-duration fault injection and measured cost remain unverified.

Local preservation snapshot verified all **121 present files** from the historical 122-file inventory, all **28 runtime sources**, frozen ZIPs/assemblies/goldens and all five ledgers/both claims. The sole discrepancy already existed at session start: untracked input `milestone-5-q18-fix.patch` is absent. It was not recreated and no historical pin was changed. The recovery stays closed 38/38, aggregate 40/40. Application code, infrastructure, stored artifacts and histories are unchanged by this documentation work.

All applicable offline checks ran in the existing `enterprise-analytics` Conda environment (Python **3.12.16**, Poetry **2.3.1**, exact interpreter verified):

| Command/check actually run for closeout | Result |
| --- | --- |
| `poetry check --lock` | Passed; lockfile unchanged. |
| `poetry run pytest` | **1086 passed, 85 live-gated skips in 36.87s**, no live flags or AWS calls. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: **124 files** already formatted. |
| `poetry run mypy src tests` | Passed: **98 source files**. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.example.json --outdir artifacts/m5-closeout-checks/data-example.out` | Passed offline: **41 resources**, no missing lookup context. |
| `poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.example.json --phase foundation --outdir artifacts/m5-closeout-checks/agentcore-foundation-example.out` | Passed offline: **4 resources**, no missing lookup context. |
| Documentation/link checks, diff/scope review and before/after preservation | Passed: **12 Markdown files**, **87 local links**, **36 shell blocks** parsed with `zsh -n` without execution, **2 JSON blocks**; final newlines/fences valid. Only Markdown changes; all protected files present at the start remain byte-identical. `git diff --check` passed. |

Used the existing writable jsii caches under `/private/tmp/q18-recovery-*`; synthesis outputs are separate verification directories and do not overwrite reviewed assemblies. No dedicated Markdown lint tool is configured. New merge/CI links and commit/run associations were verified with GitHub; dated historical matches were reviewed and preserved. These fresh local checks are separate from both the historical live results and main CI. Hosted CI for this documentation commit is reported in the final PR handoff, with no extra commit solely to record its own CI. No AWS operation or live test was rerun.

## Approved Q18 recovery and M5 completion — 2026-11-10

Executed the user's exact approval at `f223877` using only `analytics-dev`, account **453711491609**, region **us-west-2**. The checkout/remote ref matched that commit, with only the preserved untracked `milestone-5-q18-fix.patch`. Rechecked all 122 protected files, both frozen ZIPs and actual VersionId records, corrected assemblies, goldens, closed parent ledgers/claim and inactive process guards. The pure offline command returned **0/38 new, prior 2, aggregate 2/40** without creating a ledger/claim.

Fresh read-only preflight verified original Runtime/DEFAULT **READY v10**, full original configuration/artifact, exact CloudFormation templates/complete parameter inventory, both resource policies, seven-day retention and retained foundation/data/query trust. Version-specific S3 reads verified the original `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9` and candidate `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` pins. Fresh canonical retail downloads into the new evidence directory match committed provenance; all seven Glue schemas/source locations match. No goldens or dataset objects changed.

The first command launch was rejected before process creation because automatic permission review timed out. Inspected files/processes to confirm no operator, recovery claim, ledger or mutation had started, then used the tool's single permitted retry of the same approved command. The actual workflow executed **once**. A transient CloudFormation `describe_stacks` connection failure recovered on bounded read attempt 2; its operation-level diagnostics remain in the journal. No deployment or billable invocation was automatically repeated.

| Gate / operation | Actual result |
| --- | --- |
| Candidate deployment/reconciliation | Passed: exact frozen candidate on Runtime/DEFAULT **READY v11**; controller **123.441476s**, CDK exit 0, owned process reaped, no cleanup signals. |
| Fully judged Q18 probe serving as warm-up | Passed: ungrouped `net_revenue`, no filters, **[2025-03-31, 2025-04-01)**, **110.25 USD**, metric definition **1.0.0**, dataset **retail-v1**. One model call; full expected request/result matched. |
| Unchanged suite | **36/36 passed**, no failures/unrun cases. Numeric 27/27, clarifications 4/4, authorization 2/2, metadata 3/3; complete structured requests/results and shared S01 session pair verified. No false clarification or authorization leak. |
| Reporting/latency | Complete token/tool/Athena diagnostics. Client median **8.541s**, p95 **13.381s**, maximum **15.467s** (36 samples; nearest-rank p95), meeting the unchanged **90s** gate. Server p95 **6.661s**. |
| Suite work counters | **74 model calls**, **108643 input / 8994 output tokens**; **36 unique successful Athena queries**, **194837 scanned bytes**. These are reported work counters, not measured charges. |
| Mandatory original restoration | Passed: Runtime/DEFAULT **READY v12**, runtime stack **UPDATE_COMPLETE**, original ZIP/key/VersionId and parity-v1/t1/North/South/reference **2025-02-01**, both policies, seven-day retention and retained stack templates verified. CDK exit 0; process reaped. A separate final read-only checkpoint confirms the exact final state/parameters. |
| Protected counted smoke | Passed on original v12: `net_revenue` **[2025-01-01, 2025-02-01)** by region, North **28.50 USD**, South **13.00 USD**, definition **1.0.0**. |
| Invocation accounting | **38/38 reserved and completed**: probe 1 + suite 36 + smoke 1. Prior 2 gives **40/40 aggregate**, zero remaining; no failed, retried, timed-out or incomplete invocation. Recovery is retail-closed, durable attempt claim retained, final reservation is the protected smoke. |
| Scope/preservation | All **122** protected files and **28** runtime sources remain unchanged, including historical ledgers/claims/evidence and all frozen pins. No upload, rebuild, dataset publication/modification, profile/IAM change, extra demonstration, quota reset or additional campaign. Deployment journal inactive; no operator/CDK process remains. |

Evidence root: `artifacts/milestone-5/q18-recovery-v1/operations/20261110T173634Z/`. It contains fresh identity/preflight/canonical evidence, `original-checkpoint.json`, both controller reports/logs/outputs, `live/candidate-ready/run-context.json`, `live/probe.json`, complete `live/suite/{report.json,summary.md,attempts.jsonl}`, `live/{campaign-result.json,restored-proof.json,smoke.json}`, final strict checkpoint/parameters and independent acceptance/preservation audits. Raw evidence remains ignored locally. `campaign-summary.json` binds all **51** retained evidence files, SHA-256 **`347e3b556d7f8be17b16646add79740d6f0af78d16688c1a3441090a1f6d8362`**; suite report SHA-256 `f07e6c1ae3554fd6b97c02547f015285ef9d236ef4b061d41b2589d00432ea7f`. `campaign-result.json` has **accepted:true**. The suite-only report deliberately leaves `live_acceptance_claimed:false`; its **live_gates_passed:true** is combined with restoration/smoke by the enclosing campaign, rather than claiming full acceptance before restoration.

Recovery ledger SHA-256: **`2a4004c2056351a4c923c78a3a4aba357baf0500c46e5845ffc8d71e71fa04ce`**. New attempt claim SHA-256: `2d7dda32673198fd9a0aeae8e45dc0472fe01e1792531bdcef373044bc614dd5`. Original M5/M4 and both prior repair ledgers/claim stay byte-identical. Across all 38 new calls, diagnostics report **78 model calls**, **114373 input / 9448 output tokens**, **38 unique Athena queries / 202104 bytes**; probe and smoke are excluded from suite latency samples. Historical failure causes below remain qualified; successful recovery does not retroactively establish their transport cause.

### Checks actually run for this execution

Existing Conda Python **3.12.16** / Poetry **2.3.1**, exact Poetry interpreter verified. `poetry check --lock` passed; default `poetry run pytest` **1086 passed, 85 gated skips in 36.29s**; `poetry run ruff check .` passed; `poetry run ruff format --check .` passed (**124 files**); `poetry run mypy src tests` passed (**98 source files**). These fresh offline results preceded the deployment and are separate from live evaluation and f223877 CI. No application/operator source changed afterward.

Offline synthesis also passed into separate verification directories: `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.example.json --outdir artifacts/q18-recovery-completion-verification/data-example.out` (**41 resources**) and `poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.example.json --phase foundation --outdir artifacts/q18-recovery-completion-verification/agentcore-foundation-example.out` (**4 resources**), no missing lookup context. Retained deployment assemblies were not regenerated. Documentation links/fences, shell examples parsed with `zsh -n` without execution, and `git diff --check` passed. Final report/preservation review found no remaining acceptance blocker.

At this completion checkpoint, the next task was outcome-commit CI and PR #6 review; the PR subsequently merged as recorded in the closeout above. The agreed development scope is complete. No live allowance remains; further development requires a separately defined scope.

## Historical offline recovery verification and GitHub handoff — 2026-11-10

Inspected the applied diff on `feat/milestone-5-retail-evaluation` at `75d7c9f`; the tracked remote branch and PR #6 head matched that SHA. PR #6 is open and unmerged. Preserved the unrelated untracked `milestone-5-q18-fix.patch`. Used the existing `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python`, Python **3.12.16**, Poetry **2.3.1**; no environment replacement or dependency change. No AWS operations were performed.

Reviewed deployment reconciliation, checkpoint reads, invocation setup, complete evaluation and mandatory restoration together. Allowlisted transient reads have at most three operator attempts, finite socket timeouts and shared monotonic deadlines; denied/invalid reads fail without retry. Mutations and billable dispatch are outside this retry wrapper. Controller acceptance still requires exact template/parameters plus the full artifact/configuration/policy/readiness proof, and only its fresh in-memory result may bypass immediate duplicate verification. Restoration cache expiry/invalidation and primary/restoration/accounting diagnostics are covered.

Fixed one additional gap: Runtime client construction after STS now records operation-level setup diagnostics, rejects a late client before dispatch, and keeps client construction and `InvokeAgentRuntime` unretried. The optional injected factory preserves existing invocation callers. Three realistic setup/dispatch regressions failed before this correction and pass afterward; they verify safe endpoint/target diagnostics, redaction, no invocation after setup failure, per-target reuse and exactly one SDK attempt.

Local preservation audit passed against the retained 122-file inventory (SHA-256 `5ebc3997e8c1ce7682ce54c5e47d8e3c83118d768ab0a273c0e2e42110a46ee3`). Frozen candidate/original ZIPs, S3 VersionId records, corrected candidate/restoration assemblies, goldens, historical review JSON, both closed repair ledgers and the prior attempt claim match their pins. All 28 runtime sources are unchanged; 47 packaged project sources match the frozen baseline, with operator-only changes intentionally excluded. The M4 **28/40**, original M5 **38/40**, repair **1/40** and continuation **1/39** histories are byte-for-byte unchanged. No recovery ledger or attempt claim was created. The retained deployment journal is inactive; no earlier task-owned operator/CDK process was active at inspection.

Inspected the actual retained first-repair and continuation operation directories: all **28 + 30** summary-linked evidence hashes match. The first local CDK timeout and later post-controller `ConnectTimeoutError` remain distinct failures. The latter's exact SDK operation/transport cause was not captured and remains unproved. Retained evidence establishes original Runtime/DEFAULT READY **v10**, stack UPDATE_COMPLETE and successful original smoke; this session made no fresh AWS state claim. The historical v8 review is unchanged. Later approved recovery must freshly prove the separate original-v10 checkpoint.

| Command actually run in this checkout | Actual result |
| --- | --- |
| `poetry run analytics-repair --campaign q18-recovery-v1 verify-offline --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json` | Passed: **0/38 new, prior 2, aggregate 2/40, remaining 38**, one protected restoration slot; no ledger/claim created. |
| `poetry check --lock` | Passed; lockfile unchanged. |
| `poetry run pytest` | **1086 passed, 85 gated skips in 36.12s**; no live flags or AWS calls. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: **124 files** already formatted. |
| `poetry run mypy src tests` | Passed: **98 source files**. |
| `poetry run python -m infrastructure.cdk.app --config infrastructure/cdk/config.example.json --outdir artifacts/q18-recovery-verification/data-example.out` | Passed offline: **41 resources**, no missing context. |
| `poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.example.json --phase foundation --outdir artifacts/q18-recovery-verification/agentcore-foundation-example.out` | Passed offline: **4 resources**, no missing context. |
| Documentation links/fences and `zsh -n` on shell examples; `git diff --check` | Passed; examples parsed only, not executed. |

The first jsii verification attempt encountered a corrupt pre-existing shared cache. Kept it untouched and reran successfully with separate caches under `/private/tmp/q18-recovery-jsii-fresh-*`; final tests used `/private/tmp/q18-recovery-final-jsii-tests`. Syntheses use separate verification directories and do not replace approved deployment assemblies. The patch author's **1083-test** result below is historical reference, not this checkout's result.

GitHub handoff: normally pushed implementation commit **`8f6b2714cecbe97a40ef65dd2901acd9ec9a2ed4`** to the existing branch. GitHub reports successful **push 42860069230** and **PR 42860082151**, both with that exact head SHA; hosted lockfile, tests, Ruff, formatting, mypy and both offline synthesis steps passed. This documentation-only follow-up records those completed runs; they do not cover the follow-up commit. Its own push/PR CI will be inspected after the normal push and reported separately in the session handoff. No source changed after the recorded full local checks; documentation links/fences, shell syntax and diff checks were rerun for the follow-up. PR #6 remains open/unmerged. No live recovery, upload, rebuild, IAM change or invocation is authorized in this handoff.

## Historical portable-patch review — 2026-11-10

The patch author reported the following reference verification in a separate source snapshot, before this checkout verification. Reconstructed a clean review checkout by verifying all 147 repository blobs against GitHub 75d7c9f, then reviewed the controller, adapter, complete workflow, invocation transport and quota paths. This is a source snapshot for a portable patch, not the user's original Git history. The original Mac checkout's ignored ZIPs, deployment assemblies, raw live logs, ledgers and 122-file preservation inventory are unavailable here; their live observations retain their recorded attribution and must be checked in that checkout before approval. No actual historical ledger was initialized, edited or consumed here.

Implemented together:

- Controller returns the final strict checkpoint after process cleanup; the workflow uses it directly, with a 60-second freshness check. Exact template/parameters, account/region, Runtime/DEFAULT/artifact/configuration/policy/retention requirements remain. A second full verifier no longer introduces the reported post-controller failure point.
- A shared read pool gives each allowlisted AWS read at most 3 attempts with finite socket timeouts, exponential backoff and existing monotonic deadlines. STS during invocation-client construction is included; invocation clients are reused. Access denial/validation errors do not retry. Mutations, Athena submissions and model/Runtime invocations cannot use this read wrapper; invocation SDK attempts remain 1.
- Persistent, payload-free read diagnostics record operation/phase/endpoint hostname/safe target/attempt/timing and available AWS code/request ID. Workflow evidence retains primary, restoration and accounting failures separately. The old timeout's exact SDK operation cannot be recovered from the committed evidence and is not guessed.
- Restoration consumes the controller's verified in-memory proof through the immediate smoke gate, with 60-second expiry and invalidation before mutation. Original preflight or saved JSON cannot populate this cache. Expired restoration proof requires a fresh read.
- Proposed q18-recovery-v1 requires freshly verified original v10 and a new ledger/claim tied to both closed parent histories and the old continuation claim. Global operator exclusion covers all repair selectors. Planned usage is Q18 probe/warm-up 1 + unchanged suite 36 + protected smoke 1 =38; aggregate prior 2 + 38 =40. No old review or counter is rewritten. Execution is pending a reviewed scope decision, not authorized by unused quota.

### Patch-author reference verification (not this checkout)

Used Python 3.12.14 and Poetry 2.3.1 with the existing locked dependency environment, explicitly resolving imports to this review checkout. Installed package versions match the lockfile (the Windows-only colorama package is not applicable on this Linux host). `AWS_EC2_METADATA_DISABLED=true` and a writable jsii cache were used for offline verification.

| Check actually run | Result |
| --- | --- |
| Full default `poetry run pytest -q` | **1083 passed, 85 gated skips in 101.00s**; no live flags. |
| Focused controller/read/recovery tests before final transport addition | **87 passed**; the final full suite includes the additional invocation-setup regression. |
| `poetry check --lock` | Passed; dependencies/lockfile unchanged. |
| `poetry run ruff check .`, `ruff format --check .`, `mypy src tests` | Passed: 123 files formatted; 97 typed source files. |
| Offline CDK example data/foundation synthesis | Passed: both example assemblies generated without AWS lookups or missing context. |
| Documentation, patch application and preservation checks | Passed: 6 Markdown files, 39 local links, 12 shell blocks parsed without execution. Patch applies cleanly to the verified baseline and reproduces all 23 changed files. Protected tracked inputs/old reviews/contracts/policies/dependencies unchanged. |

A regression was also reproduced against the original 75d7c9f wrapper: one connection timeout aborts immediately; the corrected wrapper succeeds on the second read attempt. Fault injection covers every strict-checkpoint SDK operation, transient retry exhaustion, denied access, late responses, no read-wrapper access to billable/mutating operations, unretried invocation timeout, final controller receipt, stale proof, original-proof cache expiry/invalidation, preflight report-directory reservation, full38-call acceptance with both session requests, failed probe, interruption, restoration-only recovery, dual failures, final accounting failure, parent/claim drift and cross-selector operator exclusion. All36 frozen cases and historical review/binding hashes remain unchanged. Existing semantic/Q18 regression coverage also passes.

At that historical handoff, the next task was to apply/review the portable patch and verify it in the original checkout. That offline verification is now complete as recorded above; live execution still requires approval of the concrete 38-call proposal. Preserve the v10 checkpoint, frozen candidate/version, original restoration assets, all historical records and existing permissions; no new profile, rebuild/upload or IAM change is proposed.

## Approved Q18 continuation live window — 2026-11-09

The user approved the exact e8e4b0f controller/proposal, all 39 remaining calls including the formerly controlled reserve, and mandatory original restoration/smoke. Used only q18-continuation-v1, analytics-dev/account 453711491609/us-west-2 and the existing candidate/version. Remote HEAD and push/PR CI 42698850994/42698861471 were independently verified; source/config/tests/lock matched the approved commit. Preserved the untracked patch. Explicit STS confirmed the existing approved developer SSO principal/account. No previous repair/CDK process, continuation ledger/claim or process journal was present.

Fresh preflight passed before mutation: exact original Runtime/DEFAULT READY v8; complete CloudFormation parameter inventory/values and original template; both policies, seven-day retention and retained foundation/data/query-trust templates; actual candidate S3 VersionId/checksum/size; canonical ready manifest/all seven source objects and Glue schemas; closed parent and all 122 protected file hashes. No code upload, rebuild/resynthesis, publication or IAM change was needed.

| Gate / step | Actual result |
| --- | --- |
| Candidate deployment/controller | **Passed**, candidate **v9**; exact reviewed template/parameters and full strict checkpoint before/after process reaping. Controller 43.431s; CDK exit 0, process reaped, no cleanup signal. Historical GetAgentRuntime v9 readback confirms the existing candidate code/version. |
| Additional candidate checkpoint | **Failed with `ConnectTimeoutError`** after controller acceptance and before candidate-ready context or any retail reservation. The exact SDK operation/endpoint and full exception message were not recorded by the workflow; do not infer them or a network/service root cause. |
| Candidate acceptance | **Unrun:** no warm-up, Q18 probe or 36-case suite; no new metric-quality or latency-gate result. `accepted:false`; workflow exit 1. |
| Mandatory original restoration | **Passed** in `finally`; restore controller accepted in 67.194s, CDK exit 0, process reaped. Runtime/DEFAULT **READY v10**, runtime stack UPDATE_COMPLETE. Fresh independent verification confirms original parity-v1/t1/North/South/reference 2025-02-01, original ZIP/key/VersionId/template/configuration, both policies, seven-day retention and retained infrastructure. |
| Counted restoration smoke | **Passed on v10**, net revenue[2025-01-01,2025-02-01), North **28.50** / South **13.00 USD**, definition 1.0.0. |
| Continuation accounting | **1/39** reserved/completed, solely restoration smoke; zero incomplete reservations, invocation failures/timeouts or retries. Retail dispatch closed; durable attempt claim retained. |
| Aggregate repair budget | Parent 1 + continuation 1 = **2/40 used, 38 remaining**. Parent ledger remains closed 1/40, original M5 38/40 and M4 28/40 unchanged. The remaining 38 cannot fit the required 39-call sequence; do not reopen/reset or borrow another campaign's quota. |
| Scope / process state | No application-source/IAM/profile/data or frozen ZIP/S3-version/assembly changes, uploads, permission expansion or repeated deployment attempt. Deployment journal is inactive with no process group; operator exited. Captured CloudTrail has two successful Runtime updates and two change-set executions with no error codes/messages; it does not identify the connection timeout or prove exhaustive absence of transport failures. |

The sole smoke reported **3 model calls**, **4599 input / 345 output tokens**, **8498ms client / 4769ms server latency**, **one successful Athena query / 2252 scanned bytes**. These are work counters, not measured charges or retail-suite acceptance. The connection timeout occurred outside the invocation ledger, so zero invocation-timeout counters do not erase the failed checkpoint.

Evidence root: `artifacts/milestone-5/q18-continuation-v1/operations/20261109T215224Z/`. Retained local/fresh preflight, original full checkpoint/proof/parameters, fresh candidate-version verification, controller reports/logs/outputs, `live/{run-context.json,campaign-result.json,restored-proof.json,smoke.json}`, candidate v9 readback, final v10 full checkpoint/events/resources, CloudTrail and independent audits. No probe/suite report exists because dispatch never began. Summary SHA **`4d04ea290defddd9f136e21134bc535a7f57556be302c3d722483770ad77f8b0`**; continuation ledger SHA **`4943c554d4a856621ef126389f7666bfcd2e32a16be2ef2cd024c0d4ab5d9ca5`**; retained claim SHA `a741c8a0bb6c7acfaebe0c3e2a92c43d8d8df3147c95a039561760dd7e4be137`. All 122 protected files and earlier evidence remain byte-identical. Independent saved-file audit confirms accounting/restoration and unrun gates.

### Checks actually run in this execution

Existing Conda Python 3.12.16 / Poetry 2.3.1 interpreter verified; writable jsii cache used as documented. Before deployment, unchanged execution source passed `poetry check --lock`; default `poetry run pytest` (**1042 passed, 85 gated skips in 38.99s**); `poetry run ruff check .`; `poetry run ruff format --check .` (**117 files**); `poetry run mypy src tests` (**92 source files**); `git diff --check`. Pure-local continuation verification passed in 0.57s and created no ledger/claim. These are actual fresh local results, separate from hosted CI and the failed live checkpoint. No source changed afterward, so source checks were not repeated for documentation-only edits. Final `git diff --check` and documentation checks passed: 11 Markdown files, 74 local links, 33 shell blocks parsed without execution, 2 JSON blocks. Independent final diff/evidence review found no blocking issue; source and all 122 protected files remained unchanged.

**Remaining blocker:** additional post-controller verification raised a connection timeout before candidate testing. Diagnose it offline with better SDK-operation/error evidence before proposing further live work. The reviewed v8 continuation is now closed and the actual restored checkpoint is v10. A fresh unchanged 39-call sequence would bring aggregate usage to 41, exceeding the authorized 40; a new reviewed scope/budget decision is required before execution. No further call, permission or deployment is authorized automatically. M5 remains open and PR #6 unmerged.

## Historical controller correction and continuation preparation — 2026-11-09

Read repository/milestone instructions and all retained operation files under `artifacts/milestone-5/q18-repair-v1/operations/20261109T193234Z/`. Verified 41 prior protected hashes, 28 operation-evidence hashes and a new 122-file preservation inventory, including the three historical ledgers, frozen candidate/original ZIPs/assemblies, goldens/configuration and 28 runtime-source files. All 47 packaged Python sources match the e0f028c build baseline; intentionally changed operator modules do not require a new runtime ZIP. Existing enterprise-analytics Conda Python 3.12.16 / Poetry 2.3.1 and Poetry interpreter were verified. GitHub-only reads verified remote/CI; no AWS client operation ran.

**Evidence correction:** CloudFormation completion, exact candidate READY v7 proof, local 1800s `TimeoutExpired`, no candidate reservations, original restoration READY v8 and one passed smoke are established by retained files. The one-second native sample establishes an event loop waiting in `uv__io_poll`/`kevent`; it does not identify a pending SDK request or prove a transport cause. Captured CloudTrail has no authorization error, without establishing exhaustive absence of service/transport errors. Earlier I/O wording is qualified accordingly; raw historical evidence is unchanged.

Implemented together:

- A bounded CDK controller reconciles stable named CloudFormation state, full template/parameters and the strict Runtime/DEFAULT artifact/configuration/policy/retention checkpoint. A stalled owned child can be cleaned up after independently verified AWS success, then the whole proof is repeated. A zero CLI exit or READY alone cannot pass; rollback, nonzero exit (including during verification), stale/wrong state or unavailable proof fail closed. Baseline drift is checked before mutation.
- Owned process-group cleanup is bounded; logs and structured controller evidence are retained. A global deployment lock, durable process-intent journal and previous-update barrier prevent overlap. Unresolved child/update state blocks further mutation, including restoration until safe; no foreign process is killed.
- Separate reviewed `q18-continuation-v1` configuration pins the original v8 checkpoint and actual existing candidate/version, with fresh original proof required. Historical v6 handling remains isolated for the old closed campaign; no original artifact/configuration pin is relaxed.
- New immutable continuation identity/ledger binds the parent ledger SHA `6f39bc49361a718e221fd1bd4b38fc12c2b0c305cfa30246ef1a22005d5bf7e8`, existing candidate/version and reviewed checkpoint. Parent reads are read-only; drift blocks accounting. A durable exclusive claim prevents a duplicate zero-call attempt; an operator lease excludes concurrent evaluation/recovery. The cap is 39 new calls, aggregate 1 + 39 = 40, with the last continuation call protected for fresh-verified original restoration. No historic counter is reopened/reset.
- Complete offline command/workflow tests cover v8 start, incorrect/stale checkpoints, all 36 cases plus probe/warm-up/smoke, aggregate limits, session pair, failed probe/deployment, interrupted invocation, missing claim and restoration-only recovery. Default tests remain credential/AWS-free.

[One continuation proposal](milestone-5-q18-continuation-proposal.md) contains fixed pins, read-only offline verification, later gated deployment/evaluation/restoration commands, exact bounds and failure handling. Proposed usage is 1 warm-up + 1 Q18 probe + 36 suite + 1 original smoke = 39. Together with the prior smoke this exhausts 40 and uses the previously controlled reserve; **explicit approval is required before execution**. No automatic spare/retry is proposed. The candidate upload VersionId remains `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu`; no upload or version-record rewrite is needed.

### Actual local verification

All required final checks ran in the existing enterprise-analytics Conda environment:

| Command/check actually run | Actual result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **1042 passed, 85 gated skips in 39.68s**; includes 82 additional controller/continuation cases, original semantic/agent regressions and offline CDK assertions. No live flags or credentials. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 117 files. |
| `poetry run mypy src tests` | Passed: 92 source files. |
| `git diff --check` and documentation checks | Passed: 10 Markdown files, 65 local links, 23 shell blocks parsed without execution, 1 JSON block. Final diff/source and evidence reviews found no remaining blocking issues. |
| Protected artifact/history verification | Passed: 122 unchanged files; historical M4 28/40, original M5 38/40 and closed repair 1/40 remain byte-identical. |

An initial full pytest run stopped with two CDK collection errors because the default
jsii cache was outside writable sandbox roots. Setting
`JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache` resolved
that environment issue for the successful full run; no dependency or interpreter change
was made. Focused verification also passed15 continuation-flow cases and58 controller/configuration
cases. Review identified and fixed a late nonzero-CDK-exit
race and baseline parameter/template drift before the final complete checks. A final
regression rejects prior candidatev7, currentv8 or malformed version responses after the
reviewed v8 start, before any candidate invocation; original restoration still runs.

Pure local `poetry run analytics-repair --campaign q18-continuation-v1 verify-offline --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json` passed against retained actual pins, showing continuation 0/39 and aggregate 1/40; no continuation directory, ledger or claim was created. Review SHA `13f9bff2a91cc17fc5177e9e8d7814101231ab0d8fc9d839ec19d47cbaae3354`; binding SHA `6988ae16e484bfe9229994eb473c3bb9b8361086a69d7cdd76e7e35b63205333`. Parent/historical ledgers and protected artifacts were byte-identical at that preparation checkpoint. That controller commit became e8e4b0f, was pushed and passed CI 42698850994/42698861471 before the separately recorded live attempt above. No retail acceptance is inferred from hosted/offline checks.

## Approved Q18 repair live window — 2026-11-09

Used only analytics-dev/account 453711491609/us-west-2; STS verified the expected developer SSO principal. The user approved the exact proposal and supplied administrator policy `enterprise-analytics-dev-q18-candidate-code` on `enterprise-analytics-dev-agent-runtime`. Its Sid/actions/exact candidate-key resource match the reviewed statement. This is supplied administrator evidence, not a new IAM inspection or change by this agent. Remote HEAD/PR #6 and successful hosted checks for 661aba9 were verified separately from this execution.

Fresh original preflight passed on parity-v1 READY v6: original ZIP/version/templates/policies/retention and retained foundation/data/query trust; canonical ready manifest and all seven source object identifiers/hashes/sizes/schemas plus Glue tables. Candidate/reproduction/source and review/template/golden pins matched. All 41 protected file hashes, including both historical ledgers, remained unchanged throughout. The new repair allowance began at 0/40.

| Step / gate | Actual result |
| --- | --- |
| Conditional candidate upload | Uploaded **once**, with owner/checksum/If-None-Match guards and AWS_MAX_ATTEMPTS=1. SHA `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1`; actual returned S3 VersionId **`V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu`**. |
| Actual version binding | `analytics-repair --campaign q18-repair-v1 bind-upload --verify-upload` passed version-specific HEAD/checksum/size/owner verification; write-once candidate-version record retained. |
| Candidate deployment | Approved assembly updated the Runtime stack to UPDATE_COMPLETE; strict independent verification confirmed Runtime/DEFAULT **READY v7**, exact candidate artifact/version/template/configuration, both policies and seven-day retention. |
| Local deployment command | The CDK child did not return after the successful AWS update. The reviewed **1800-second subprocess bound** raised `TimeoutExpired`; supervised workflow exited 1 after restoration. The native sample shows an event-loop wait; logs do not establish the pending request or transport cause. No deployment retry occurred. |
| Candidate acceptance | **Not run:** no warm-up, Q18 probe or 36-case suite dispatch. No candidate quality/report pass is claimed; `accepted:false`. |
| Mandatory restoration | `finally` deployed `artifacts/milestone-5/cdk.restore.out` using original VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`; CDK succeeded (37.34s total). Runtime/DEFAULT **READY v8**, stack UPDATE_COMPLETE. Original parity-v1/t1/North/South/reference 2025-02-01, ZIP/template/configuration, both policies, seven-day logs and retained foundation/data/query trust verify. |
| Counted restoration smoke | Passed on v8: net revenue for [2025-01-01,2025-02-01), North **28.50** / South **13.00 USD**, definition 1.0.0. One reserved call and one answer outcome. |
| Final repair ledger | **1/40**, solely restoration smoke; 39 unspent, no incomplete reservation, invocation failure, invocation timeout or retry. Retail dispatch is closed; reserve was not used. The CDK timeout is recorded separately from invocation counters. M4 remains 28/40; original M5 remains 38/40, byte-for-byte. |
| Authorization / scope | Captured CloudTrail CFN/Runtime records contain no authorization error; no additional permissions proposed. No IAM/profile/data/publication/foundation/M3 changes or original code upload. |

Evidence root: `artifacts/milestone-5/q18-repair-v1/operations/20261109T193234Z/`. Retained local/fresh preflight, administrator comparison, original/candidate/final checkpoints, upload/version binding, stack events/resources, CloudTrail, process sample, CDK logs/restore outputs and `live/{run-context.json,campaign-result.json,restored-proof.json,smoke.json}`. Probe and suite files are absent because dispatch never began. `campaign-summary.json` SHA **`8e24b5f83de7f36ecf1d8f05d3dba170c58dce3562ee9d87fb6d51362d8a2c5e`**; repair ledger SHA **`6f39bc49361a718e221fd1bd4b38fc12c2b0c305cfa30246ef1a22005d5bf7e8`**. Candidate binding SHA `7201841f3570412e02a02b7f769351eb3aff1a2719ab35ba35964559552fdb4b`. An independent saved-evidence audit passed strict restoration and preservation checks.

The sole smoke reported **3 model calls**, **4599 input / 328 output tokens**, **9927ms client / 4743ms server latency**, and **one successful Athena query / 2252 scanned bytes**. These are work counters, not measured charges or suite-quality evidence. No automatic reserve use or selective rerun occurred.

### Verification actually run in this execution

Existing enterprise-analytics Conda Python 3.12.16 / Poetry 2.3.1 was verified. Before deployment, the unchanged execution source passed:

| Command | Result |
| --- | --- |
| `poetry check --lock` | Passed. |
| `poetry run pytest` | **960 passed, 85 gated skips in 53.94s**; no live flags. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 112 files. |
| `poetry run mypy src tests` | Passed: 88 source files. |
| `analytics-repair --campaign q18-repair-v1 verify-offline`, protected hash/source audit | Passed; no rebuild, resynthesis or dependency update. |
| Final read-only restoration and saved-evidence audit | Passed: READY v8, stack UPDATE_COMPLETE, original scope/artifact/policies/retention, smoke and unchanged protected inputs. |
| `git diff --check` and documentation checks | Passed: 9 Markdown files, 63 local links, 30 shell blocks parsed without execution, 2 JSON blocks; independent final diff/evidence review found no blocking issue. Historical local/pending matches were reviewed separately from current status. |

Source checks were not rerun after documentation-only edits. That checkpoint was local when created as e0f028c; it has since been pushed and passed CI 42691865683/42691880796 as recorded above. Those runs do not cover the later controller correction. **M5 remains open.** Diagnose the CDK completion wait offline and prepare a reviewed continuation that preserves the closed ledger and restoration allowance; do not replay the current command, reset counters or automatically consume the reserve.

## Historical Q18 offline preparation — 2026-11-09 (before approval)

Read instructions, implementation/progress and the supplied patch; the repair document was introduced by that patch. Both compatibility checks passed before application. Preserved the original input patch (SHA recorded in the review) unmodified/untracked. Inspected retained `artifacts/milestone-5/operations/20261109T171341Z/retail-evaluation/report.json`, verifying SHA `7ccd5b43ec1ea38dfc0a17c562e1cd51a74f36e0bff247fac5a1759da5855021`, Q18's one model call/no tools/clarification and frozen 110.25 USD expectation. Existing Conda interpreter is Python 3.12.16, Poetry 2.3.1, `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python`; no replacement environment or dependency update.

Completed bundle:

- Shared validated executor plus once-only resolved-plan fallback, with trusted context and whole-plan limits preserved. Focused source/limits/question tests **187 passed**. Independent authored no-tool turns through real canonical DuckDB/guard/agent/tool/render matched all 36 frozen cases; this is offline orchestration evidence, not live quality.
- Candidate Python 3.12 Linux ARM64 ZIP built in `artifacts/milestone-5/q18-repair-v1/candidate/`; two separate Poetry wheel builds and ZIP builds reproduced byte-for-byte. All packaged project source files match the checkout; resolved-plan correction is present, dependencies match the committed lock/cache. Original ZIP untouched. A public Botocore CA certificate initially tripped an overly broad archive assertion; narrowed that check, created the candidate config and reran synthesis successfully. No package contents changed to remove dependency certificates.
- Candidate assembly permits only the new SHA-addressed code key and the existing three trusted retail settings. Original restoration assembly/config/ZIP/version stay pinned; a bundle copy was compared byte-for-byte. No IAM resources/policies, model, networking, lifecycle, dataset, limits or public contracts changed.
- Candidate/original verification is explicit. Candidate local ZIP/template and post-upload VersionId/checksum/size/key bind to a canonical review digest. Fresh version-specific HEAD is required before future CloudFormation mutation. Original restoration retains its original constants/proof; it cannot accept the candidate. No real candidate VersionId was invented or recorded.
- `analytics-repair --campaign q18-repair-v1` provides offline review, gated upload-version binding, run and restoration-only commands. New campaign `milestone-5-q18-repair-v1` fixes its separate ledger path and40-call cap; every event binds review/candidate/template/upload-record hashes. Historical/default campaign behavior remains unchanged. The new real ledger is absent/unused; no histories were reset or redirected.
- Full operator tests execute a 39-call successful mock path: warm-up 1, separate frozen Q18 probe 1, complete 36-request suite including Q18/S01, original smoke 1. Failed probe stops before the suite; failures/interruption still restore. Coverage includes wrong hashes/versions, old-ledger reuse, binding drift, SDK timestamps/redaction, alternate Runtime targets, SIGTERM/Ctrl-C cleanup and recovery without retail/candidate input access. Review identified and corrected the latter three lifecycle/scope issues before packaging.

| Reviewed artifact | SHA-256 |
| --- | --- |
| New candidate ZIP | `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1` |
| New project wheel | `4b8f655516c53a33aac3772311024b7301663aeda5c7a6cdf8960ef85c4476cd` |
| Candidate template | `faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368` |
| Canonical review identity | `14a817f1ba1ad2b2fa5b5b6c1cfb4aa6250513f971153003b9ddc5ca8b193401` |
| Original restoration ZIP | `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` |
| Original restoration template | `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb` |

Candidate sizes 39171778 / 85816131 compressed/unpacked bytes. Original VersionId remains `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`. Review/build/template manifests are under `evaluations/retail-v1/q18-*.json`; binary/reproduction/source inspection evidence stays ignored under the new candidate directory. Build inputs use SOURCE_DATE_EPOCH=1735689600; original embedded base config is retained, with the reviewed environment selecting retail scope.

### Commands actually run and verification

| Command | Actual result |
| --- | --- |
| `git apply --check milestone-5-q18-fix.patch`; `git apply milestone-5-q18-fix.patch` | Passed; no force/reset or conflict discard. |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **960 passed, 85 gated skips in 56.70s**; earlier complete run 960/85 in 56.62s. Skips are explicit live gates, not acceptance. |
| `poetry run ruff check .`; `poetry run ruff format --check .` | Passed; 112 files already formatted. Intermediate formatting/type issues were fixed before final checks/build. |
| `poetry run mypy src tests`; extended `poetry run mypy src tests infrastructure/cdk` | Passed: 88/95 source files. |
| `poetry build -f wheel --output <candidate/reproduction>/project-dist` | Both passed; identical wheel SHA above. |
| `poetry run python -m infrastructure.agentcore.package --offline --config infrastructure/agentcore/runtime.development.json --output <candidate/reproduction>/agent.zip --wheel-dir artifacts/agentcore/wheels --project-wheel <matching explicit wheel>` | Both passed with cached checksum-locked wheels; identical ZIP SHA above, original output untouched. |
| Locked CDK `synth --app 'poetry run python -m infrastructure.cdk.agentcore_app --config infrastructure/cdk/agentcore.config.q18-repair.json --phase runtime' --no-lookups --no-telemetry --no-notices --output artifacts/milestone-5/q18-repair-v1/cdk.candidate.out --quiet` | Passed offline; exact scoped diff and original restore hash verified. Existing deprecation/feature-flag advisories only. |
| `poetry install --only-root --no-interaction`; `poetry run analytics-repair --help`; `poetry run analytics-repair --campaign q18-repair-v1 verify-offline` | Passed; only editable entry point registered in existing environment, no dependency changes or AWS client construction. |
| `git diff --check`, documentation checks, preservation/source audit | Passed: preservation/source audit and 9 Markdown files / 53 local links / 20 shell blocks (parsed only); final diff reviewed. |

All 72 captured historical/input hashes remain unchanged, including both real ledgers, original ZIP/assemblies, golden files and original report. New candidate-version/ledger files are absent. The supplied patch's separate review-checkout results below retain their original attribution and do not substitute for these actual checks. No AWS API, publication, upload, deployment, invocation, profile/permission mutation or PR merge occurred.

### Proposal and prerequisite at that preparation checkpoint

[One concrete proposal](milestone-5-q18-deployment-proposal.md) covers immutable candidate upload, actual returned VersionId binding, fresh original preflight, candidate deployment/READY, counted warm-up/probe/full suite, mandatory original restoration/proof/smoke and recovery. Proposed new maximum 40 = 1 + 1 + 36 + 1 + 1 reserve; normal successful use 39. Existing original M5/M4 quotas are not borrowed. The future run stops after a failed probe and preserves the full-suite denominator.

The retained runtime execution-role policy grants reads only to the old SHA key. Current official Python deployment requirements require package S3 access. No live IAM inspection is authorized here: an administrator must confirm candidate-key access and separately approve an exact additive read grant if missing. The proposal supplies the precise statement; no current permission or foundation stack was changed. Candidate upload and deployment are not claimed ready under unchanged effective IAM. M5 remains open pending separately approved live acceptance and original restoration; the last reported deployed state remains parity-v1 READYv6, not a fresh AWS assertion.

## Supplied patch-author Q18 review — 2026-11-09

The supplied patch records this separate review (not rerun or independently attributed to the current session): reconstructed and Git-blob-verified all 126 files at upstream `28ffcf18` in an isolated local review checkout. The local baseline commit is a source snapshot, not imported upstream history. Inspected instructions, milestone progress/plan, agent/question/tool code, evaluator, deployment and campaign verification. In that patch-author review checkout, original ignored operation reports and frozen artifacts/ledgers were not present; they are present and separately verified in the current preparation above.

Recorded Q18 evidence is one model call/no tools, so a valid numeric request reached the generic empty-end-turn clarification path. The date guard already computes March 31–April 1 correctly. Extracted one shared tool executor and added a bounded, once-only server-plan fallback for fully resolved numeric scopes with no prior metric result/tool error. It preserves the exact trusted context, contracts, response checks, limits and diagnostics, then renders actual adapter results. Server-planned record IDs are distinct; no model messages or numerical answers are fabricated. Unsupported/ambiguous intent and model/tool failures remain fail-closed.

Seven selected regressions failed before the correction (all five metrics, Q18 and tool budget). Focused initial verification passed **183 tests** before additional session, metadata-ID, missing-source and multi-period regressions were added. The new file has 55 cases, including all 36 frozen cases through real agent orchestration. Independent real-adapter Q18 fixture arithmetic produces 110.25 USD; mock golden replay is explicitly not live answer-quality evidence.

Final verification ran in the isolated review checkout using the existing locked Python 3.12.14 environment, with `PYTHONPATH` pointing at this checkout's `src` and SDK metadata access disabled. Poetry 2.3.1 was installed in a separate temporary tooling environment after the prior temporary Poetry path was no longer present; no project dependency or lockfile changed.

| Check actually run | Result |
| --- | --- |
| `python -m pytest -q` | **892 passed, 85 gated live skips in 91.59s**. |
| `poetry check --lock` | Passed: All set. |
| `python -m ruff check .` | Passed. One test string line-length issue was corrected before the final run. |
| `python -m ruff format --check .` | Passed: 103 files already formatted. |
| `python -m mypy src tests` | Passed: 80 source files. |
| `git diff --check` | Passed. |
| Markdown links/fences/newlines | Passed: 5 Markdown files and 20 local links. |
| Upstream Git blob comparison excluding the six intentionally edited existing files | **120 unchanged file hashes**, including all goldens, policies, configs, pinned checks and the first-campaign implementation. |

The full suite includes the corrected serialization regression and all new agent regressions. No live gate was enabled and no upstream CI result is claimed for this local repair.

Preservation: only agent orchestration, its explanatory docstring, a new regression file and repair documentation are changed. No metric calculation, public schema, golden, IAM/profile, original artifact pin, campaign counter or restored baseline is changed. The new preparation document identifies the necessary candidate-versus-restore verifier and separate campaign work before any live approval, so the old closed-ledger/frozen-artifact workflow is not reused accidentally. No AWS calls, source publication, ZIP rebuild/upload, deployment or Runtime invocations occurred.

Exact next task: apply this reviewed patch in the original checkout and prepare the entire candidate artifact, explicit artifact checks, new campaign selection/ledger and restoration bundle offline as described in [the repair plan](milestone-5-q18-repair.md). Review retained evidence there, complete all checks, then request one concrete approval for upload/deployment and a new bounded campaign. Keep the failed first campaign and M4 history intact and M5 open.

## Milestone 5 approved live campaign — 2026-11-09

The user approved the existing runbook's environment-only retail Runtime update, counted warm-up and 36-request evaluation, mandatory corrected-base restoration and counted smoke, within **40 total M5 calls**. Git status was clean on the requested branch at `850bbc8`; `git ls-remote --heads origin feat/milestone-5-retail-evaluation` returned exact SHA `850bbc8c3a16a4343ece3a4144e3e047eba0917d`. User-confirmed push CI `42660104374` covers that correction and predates this live campaign. Existing Conda Python 3.12.16/Poetry interpreter and explicit analytics-dev STS account 453711491609/us-west-2 passed. No alternative profile was selected.

Fresh preflight passed: reviewed retail/restore template hashes and exactly three trusted configuration deltas; frozen ZIP/S3 version; both inbound policies; live parity-v1 READY v4 and stack UPDATE_COMPLETE; retained foundation/data/query-trust templates; seven-day retention; canonical version-pinned ready manifest and all seven source byte hashes/sizes/schemas; seven Glue schemas/locations. Frozen question/oracle/golden/contribution bindings passed. M4 ledger hash/count verified unchanged at 28/40; M5 began at 0/40 with its final restoration slot protected.

Operation evidence is retained under ignored `artifacts/milestone-5/operations/20261109T171341Z/`: local/fresh preflight, original checkpoint, deploy outputs/logs, execution-state, suite run context/report/attempts, restoration proof/checkpoint and smoke outputs. Deployment/evaluation/restoration execute sequentially under a supervisor that enters restoration in `finally` after any attempted retail update; no automatic Runtime retries are enabled. CDK may publish the reviewed CloudFormation template as part of deployment; the frozen code ZIP is never rebuilt/uploaded.

### Actual deployment, evaluation and restoration results

| Gate / evidence | Actual result |
| --- | --- |
| Retail deployment | Approved assembly deployed; Runtime/DEFAULT READY **v5**, stack UPDATE_COMPLETE. |
| Counted warm-up | Passed; net revenue North 172.17 / South 313.44 USD; one M5 reservation. |
| Authored retail suite | **35 passed, 1 failed, 0 unrun**; CLI exited 1. All 29 observed metric requests matched complete independent frozen plans/results. |
| Q18 failure | `Show net_revenue for yesterday.` returned clarification after **1 model call, zero tools/results**. Expected net_revenue for **[2025-03-31,2025-04-01)**, ungrouped **110.25 USD**. No adapter query was issued; no AWS denial/transport failure occurred. |
| Other behavioral gates | Four expected clarifications, both authorization cases, all three metadata cases and S01 shared-session isolation passed. Numeric answer coverage 26/27; false clarification 1/27. |
| Diagnostics / latency | Complete diagnostics, no missing samples/scans; client median 7.354s / p95 10.403s / max 10.649s (36 samples, nearest rank, warm-up excluded). Server p95 6.849s; latency gate passed. |
| Suite usage | **77 model calls**, **114378 input / 9301 output tokens**, **33 unique successful Athena queries / 179826 scanned bytes**; zero failed queries. |
| Corrected-base restoration | Deployed the reviewed restore assembly; Runtime/DEFAULT **READY v6**, stack UPDATE_COMPLETE, parity-v1/t1/North/South/reference 2025-02-01; exact base template/configuration, policies, artifact/version, seven-day retention and retained data/foundation/trust verify. |
| Counted restoration smoke | Passed on v6; independent net revenue North **28.50** / South **13.00** USD. Fresh restoration proof is stored in its ledger reservation. |
| Final M5 counter | **38/40**: warm-up 1 + suite 36 + restoration smoke 1; all 38 outcomes recorded; zero incomplete reservations, transport failures, timeouts or retries. Retail dispatch is closed; 2 unused calls remain. |
| M4 / preservation | Original ledger remains **28/40**, hash `f04f9cc568d4842b6c9e0118f01cf5b92e496c40658f25a9fdc364075eb17f14`; all 35 captured frozen-input/ZIP/assembly/M4 hashes unchanged. No IAM/profile changes, code ZIP rebuild/upload, bootstrap, source publication or foundation/data deployment. |

Whole campaign including warm-up/smoke: **83 model calls**, **123820 input / 9974 output tokens**, **35 unique Athena queries / 188403 scanned bytes**. These are reported work counters, not measured charges. The suite report snapshots 37 reservations before restoration; final `campaign-summary.json` and the persistent ledger include the 38th smoke. The ledger records valid clarification outcomes separately from judge correctness, so zero transport failures does not make Q18 pass.

Retained local evidence: operation root `artifacts/milestone-5/operations/20261109T171341Z/`; `retail-evaluation/{run-context.json,attempts.jsonl,report.json,summary.md}`, deploy outputs/logs, restored/final checkpoint, smoke output, CloudFormation events/resources and `campaign-summary.json`. Suite report SHA **`7ccd5b43ec1ea38dfc0a17c562e1cd51a74f36e0bff247fac5a1759da5855021`**; final M5 ledger SHA **`fad2f259d79c98d694b6452aec675df474726c225ff5bf72244b5abbef7713c9`**. An independent agent review verified source/hash/attempt/session associations and all passed/failed gates using saved evidence only. No reruns or selective omissions were used. M4's version 4 acceptance remains historical; v6 is the new operational restoration.

### Verification and checkpoint status

Required offline checks passed on unchanged execution code: `poetry check --lock`; `poetry run pytest` (**837 passed, 85 gated skips in 51.22s**); `poetry run ruff check .`; `poetry run ruff format --check .` (**101 files**); `poetry run mypy src tests` (**79 source files**). Final `git diff --check` and documentation checks passed: **7 Markdown files, 47 local links and 26 shell blocks**, parsed without executing the embedded commands. These results and hosted CI are separate from the failed live quality gate. Application code, public contracts, calculations and goldens were not changed in this window.

**M5 remains open solely because the all-cases correctness gate failed at Q18.** Restoration and infrastructure/diagnostic/authorization gates passed; no additional permission was requested or needed. Investigate Q18 offline using the saved one-model-call/no-tool response, preserving the frozen numeric expectation and existing runtime artifact. Prepare a reviewed correction; any changed runtime package/deployment or fresh full campaign needs separate approval. The current campaign is retail-closed at 38/40, so its two unused slots cannot cover another 36-request suite; preserve both ledgers and never reset/relabel the failed result.

## Milestone 5 checkpoint serialization correction — 2026-11-09

Inspected AGENTS, current milestone documents, branch/status/history and the reporting/runner/checkpoint path. Initial working tree was clean at `e6f4325`. Confirmed existing Conda Python 3.12.16 and Poetry use `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python`; focused baseline `poetry run pytest tests/test_retail_evaluation.py -q` passed **53 tests in 0.43s**.

The checkpoint contains nested Runtime/endpoint `createdAt`/`lastUpdatedAt` and S3 `LastModified` datetime objects. Plain context JSON serialization raised TypeError after opening the destination, leaving an empty file before dispatch. The correction explicitly normalizes supported datetime values with `isoformat()` (retaining offset and precision), keeps existing redaction, and fully serializes context JSON before creating its exclusive final file. Unsupported objects still fail before any invocation instead of being silently stringified.

Four new regressions failed against the original code (**4 failed in 0.34s**), then passed after the fix. Focused `poetry run pytest tests/test_retail_reporting.py tests/test_retail_evaluation.py -q` passed **57 tests in 0.49s**. The complete command path uses realistic timestamp-bearing checkpoints, mocked AWS/invocation boundaries and a real temporary campaign ledger/client: it verifies context/report JSON, timezone offsets/microseconds/redaction, **36 reservations and 36 matching outcomes**, fresh question sessions plus the shared S01 pair. Unsupported values cause zero dispatch/reservations and leave the final context file absent. These authored mock responses verify the operator path, not live answer quality; neither real ledger is used.

Required checks in the existing environment:

| Command | Actual result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **837 passed, 85 skipped in 54.04s**; skips are explicitly gated live suites, not acceptance evidence. |
| `poetry run ruff check .` | Passed. |
| `poetry run ruff format --check .` | Passed: 101 files already formatted. |
| `poetry run mypy src tests` | Passed: 79 source files. |
| `git diff --check` and documentation checks | Passed; 4 Markdown files, 33 local links and 10 shell blocks checked without executing commands. |

Preservation checks passed for all **54 protected file hashes/absence states**, including frozen inputs/goldens, ZIP, corrected assemblies, deployment configuration and both real ledgers. The S3 VersionId, M3 permissions and existing analytics-dev profile are unchanged. No AWS state or live result is refreshed here.

Exact next task: review the local correction, then obtain separate deployment/live approval and follow the existing M5 runbook. M5 remains open until deployed evaluation and corrected-base restoration pass. CI `42567676599` is user-confirmed earlier-commit evidence, not validation of this fix.

## Historical Milestone 5 implementation checkpoint — 2026-11-08 America/Chicago

Read root instructions and current plan/architecture/metric definitions/progress; inspected branch/status/history, implementation and Conda/Poetry interpreter. Python and Poetry use `/opt/homebrew/anaconda3/envs/enterprise-analytics/bin/python`, Python 3.12.16 / Poetry 2.3.1. Existing work was clean at `ec77533`; continued on the same branch without branch switching or resetting. M4 completion/merge and documentation handoff ancestry is intact.

Completed locally:

- Added `analytics-ask` with saved-response replay and injectable counted invocation, exact numeric/unit/null/date/version display, sanitized diagnostics and answer/clarification/error exits. Added strict retail target/case/golden/report models, all Q01–Q34 plus S01A/B, complete-plan/result judge and reusable `analytics-evaluate` replay/live gate. Default tests and replay create no AWS clients. Existing public schemas, agent/runtime behavior, metrics and M4 tests remain unchanged.
- Added independent row-decoding oracle with its own tenant-scoped keys/relationship checks, duplicate/conflict rules, integer-cent ledger and final HALF_UP ratios; **48 handwritten oracle tests**. Source acquisition uses only STS and version/ETag-pinned S3 HEAD/GET. No generator, adapter or demo output supplied expected values.
- Frozen all 36 case records, 480 item contributions and cohort worksheets from verified canonical inputs. Root-agent arithmetic review covers January totals/aggregate versus subgroup AOV, full-period totals, refund-only and return-only cohorts, and March 31's three-item order. This is automated-agent review, not human/live acceptance. All **30 complete structured metric queries** then matched DuckDB against these frozen literals across all five metrics, without rewriting expectations.
- Added durable attempt/context reports with correctness/clarification denominators, separate client/server latency (nearest-rank p95), missing token/scan evidence and unique Athena query IDs/scans. Failed/incomplete cases cannot disappear. Review fixed dispatch continuing after actual Athena errors and invalid scan counters incorrectly satisfying completeness; regressions cover both. Report directories are reserved before dispatch; fsynced per-case/context evidence survives interruption.
- Added separate repository-anchored locked/fsynced M5 counter, reserve-before-dispatch, SDK invocation attempts=1, durable failure/timeout/interruption accounting, 39-call retail ceiling and protected fresh-verified parity smoke slot. No real M5 ledger was initialized/consumed. M4 ledger remains 28 reservations with SHA `f04f9cc568d4842b6c9e0118f01cf5b92e496c40658f25a9fdc364075eb17f14`.
- Prepared separate retail runtime/CDK settings and offline retail/restoration assemblies; three trusted JSON fields only: parity-v1→retail-v1, t1→retail_demo, February 1→April 1. North/South, model, limits, artifact/S3 version, IAM/resource policies and all other properties stay fixed. Retail template SHA `ecfbfa8a2f011ce6fe3c765c29660a81e02ad1ca765ad6e497e2502f1fe46ac3`; restore SHA exactly matches corrected base `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb`. First direct Python synthesis lacked CLI path metadata; reran through the locked CDK CLI to reproduce the exact reviewed bytes, without changing original assemblies.

### Read-only canonical and deployment evidence

Initial `aws sts get-caller-identity --profile analytics-dev --region us-west-2` failed because SSO expired, before any retrieval. After the user's login, the same explicit profile verified account `453711491609`, region `us-west-2`, selected SSO PowerUser principal. No alternate profile or administrator IAM inspection was used.

Downloaded ready manifest SHA **`99e9115edc990decf5b15e5de1ad693772e3bd03ec6767b880ebbdd4135b8797`**, S3 VersionId **`cvCWKV3bv9Ub4iZOPSh79W4TnizV6FmJ`**, from `enterprise-analytics-dev-453711491609-us-west-2-data/manifests/retail-v1.json`. All seven exact source versions passed hash/size/schema/inventory/required-field checks, followed by independent relationships/duplicates validation. Inventory: customers48/products24/orders240/items480/payments240/refunds96/returns40. Published canonical bytes were used; raw/generated local files and the earlier prepared-manifest serialization were not substituted. Committed `evaluations/retail-v1/{ready-manifest.json,oracle-provenance.json}` preserve object IDs and hashes; downloaded Parquet stays ignored under `artifacts/milestone-5/canonical/retail-v1`.

Read-only CloudFormation/AgentCore/S3/Logs checks confirmed Runtime `enterprise_analytics_dev_agent-HlWywlG60h` and DEFAULT READY **v4**, runtime stack UPDATE_COMPLETE, exact corrected template/base settings, both policies matching, seven-day retention, frozen local ZIP/upload checksum and VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`, and retained foundation/data/query-trust templates. Seven Glue GetTable reads confirmed retail source locations and schemas. No Athena query access/execution was tested. Full ignored records: `artifacts/milestone-5/{preimplementation-checkpoint.json,verified-checkpoint.json,glue-verification.json}`. Canonical/provenance timestamps are UTC (November 9 UTC / November 8 America/Chicago).

### Local verification for this implementation

| Command actually run | Result |
| --- | --- |
| Existing tracked-test baseline via `poetry run pytest <git ls-files tests/test_*.py>` | **663 passed, 84 skipped in 50.31s** before new tests. |
| `poetry install --only-root --no-interaction` | Installed only editable project/new CLI entry points in the existing environment; dependencies/lockfile unchanged. |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **833 passed, 85 skipped in 55.93s** on final current code. Skips are explicitly gated live suites, not acceptance evidence. First invocation without the sandbox cache override hit two jsii collection permission errors; setting `JSII_RUNTIME_PACKAGE_CACHE_ROOT=/private/tmp/enterprise-analytics-jsii-cache` resolved it. An intermediate complete run passed **827 tests, 85 skipped in 54.93s** before final review regressions. |
| `poetry run ruff check .`; `poetry run ruff format --check .`; `poetry run mypy src tests`; extended `poetry run mypy src tests infrastructure/cdk` | All passed: Ruff lint clean, **100 files already formatted**, mypy **78 source files**, extended mypy **85 source files**. Formatting/type issues found while implementing were fixed. |
| Locked CDK `synth --app 'poetry run python -m infrastructure.cdk.agentcore_app --config <retail/development config> --phase runtime' --no-lookups --no-telemetry --no-notices --output artifacts/milestone-5/cdk.<retail/restore>.out --quiet` | Both passed offline; scoped template review passed. Existing CDK deprecation/feature-flag advisories only. No source ZIP rebuild/upload. |
| `poetry run python -m enterprise_analytics_agent.adapters.retail_provenance --directory artifacts/milestone-5/canonical/retail-v1` | Local manifest/hash/size/schema/inventory verification; read-only acquisition was performed before the module was moved into adapters. |
| Offline frozen canonical comparison script using DuckDB and existing public v2 requests | **30 queries passed**, exact independent literal results. Initial script omitted keyword-only `context=`; corrected and reran successfully. |
| `poetry run analytics-ask --help`; `poetry run analytics-evaluate --help` | Passed after editable entry-point installation; no AWS client construction. |
| `poetry run analytics-ask --response-file artifacts/milestone-5/authored-replay/Q02.json --format text`; `poetry run analytics-evaluate --target-config evaluations/retail-v1/target.json --response-dir artifacts/milestone-5/authored-replay --report-dir artifacts/milestone-5/runs/authored-offline-replay` | Passed: exact January North172.17/South313.44 display and **36/36 authored replay cases**. This checks tool/report behavior, not model quality; diagnostics missingness is explicit and live gates are false. |
| `poetry run pytest --run-retail-live --collect-only -q` | Expected exit4: missing `--retail-config`; no invocation. |
| `git diff --check`; documentation shell/link/JSON checks | Passed: diff reviewed; **7 Markdown files, 39 local links, 16 shell blocks** parsed without execution, all retail JSON parsed. |

Required live work remains pending approval. Reports/CLI tests use authored saved responses and make no model-quality claim. Metadata grading checks tool/metric selection only because current public agent responses do not expose structured metadata contents. Independent synthetic data is small and fixed; no production/per-user authorization or broad natural-language capability is claimed. Future restoration advances the Runtime version; do not relabel M4's historical v4 acceptance.

### Exact next task

Review this local implementation checkpoint, frozen provenance/worksheets, three-field deployment diff, separate 40-call campaign and [runbook](milestone-5-runbook.md). Obtain explicit approval for the supervised environment-only Runtime update and billable campaign. Then, within that scope only: fresh read-only preflight, retail update/READY check, counted warm-up and 36-case evaluation, mandatory corrected-base restoration/fresh proof/counted independent smoke, report review and M5 completion evidence. Do not deploy/invoke from this implementation authorization, push the local commit, or start another milestone.

## Historical Milestone 5 planning — 2026-11-08

Read AGENTS, README, architecture, metric definitions, implementation plan and progress. Inspected CLI, agent/request contracts, question guard, evaluator/live tests, generator, snapshot publication, runtime settings, CDK configuration and retained local manifests/checkpoints. Git ancestry confirms both M4 completion `51c1d4c`/merge `47c3afc` and documentation `39523f4`/merge `d7e0f19` are in current main. No AWS or GitHub API calls were used to refresh cloud/CI state; the only remote operation was the requested Git fetch.

Proposed work: a separate analytics-ask CLI, versioned retail cases/independent literal expectations, multi-result semantic judging, and an evaluation report covering correctness/clarification, client versus server latency, tokens and unique Athena scans. The current CLI is direct DuckDB metric execution; the M4 evaluator is parity-only and assumes one result, so retail needs a separate operator path. Application code stays unchanged in this session.

Important decisions and dependencies:

- Retail data uses tenant `retail_demo`, not `t1`. Propose separate trusted deployment settings for `retail-v1`/`retail_demo`, retaining North/South, with reference date `2025-04-01`. The same retained ZIP/version can accept this environment JSON; no model/IAM/foundation/data/publication change is expected. Future source/config verification and a reviewed environment-only diff are prerequisites, not an assertion of fresh cloud readiness.
- Exact published canonical source files must be verified before goldens are frozen. Existing raw local files differ in bytes from the publication inventory; do not calculate expected results using the generator, adapters or demo output. The plan specifies independent calculations, contribution ledgers and handwritten fixture proofs.
- Proposed live usage is **40 separate M5 calls**: 1 warm-up + 34 individual cases + 2 session requests + 1 restored parity smoke + 2 reserve. Preserve M4 ledger `artifacts/agentcore/runtime-invocations.jsonl` at **28 reservations**, SHA `f04f9cc568d4842b6c9e0118f01cf5b92e496c40658f25a9fdc364075eb17f14`. Protect the final M5 call for restored-parity smoke; retail/demo/retry dispatch must stop at 39 total reservations. No new ledger was created or invocation used.
- Restore exact corrected M4 scope/configuration after any attempted retail change, even on failure. The resulting Runtime version advances; do not claim a return to numerical version 4 or modify that historical M4 evidence. Completion requires all agreed result/security/clarification/report and restoration gates.

This session creates only `docs/milestone-5-plan.md` and updates implementation/progress documentation. Documentation checks passed: `git diff --check`; a local Python check across **3 Markdown files**, **15 local links**, balanced fences/newlines and **3 shell blocks** parsed with `zsh -n` without execution. It also verified all **34 question IDs**, the **40-call** budget arithmetic/protected restoration slot, unchanged M4 ledger hash/count, unchanged historical recovery text, and only the three intended documentation files touched. Two independent read-only implementation/plan reviews found no blocking issue; the protected restoration reserve was added from review feedback. No implementation tests or live results are claimed; M5 implementation/deployment/live acceptance remain pending a separate authorized task.

## Milestone 4 merge and hosted CI — 2026-11-08

Verified the user-provided links through read-only GitHub PR, commit and workflow-run API records for `sureshkm-ai/enterprise-analytics-agent`. PR #4 is merged into `main`, head/completion SHA `51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf`, merge SHA `47c3afc1dd948fa8ddcb074151b9f22af31dad48`, merged at `2026-11-08T19:47:45Z` (November 8 America/Chicago). The merge commit's parents include the completion commit; local ancestry confirms it is in fetched main.

| Hosted evidence | Trigger / branch | Verified commit | Result |
| --- | --- | --- | --- |
| [push CI 42515746487](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515746487) | push / `feat/milestone-4-bedrock-agentcore` | [`51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf) | completed / success |
| [PR CI 42515722610](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42515722610) | pull_request / `feat/milestone-4-bedrock-agentcore` | [`51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/51c1d4ccb0581ed35e2cace9bafb758bf1f05dbf) | completed / success |
| [main CI 42516820774](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42516820774) | push / `main` | [`47c3afc1dd948fa8ddcb074151b9f22af31dad48`](https://github.com/sureshkm-ai/enterprise-analytics-agent/commit/47c3afc1dd948fa8ddcb074151b9f22af31dad48) | completed / success |

Read root AGENTS and project documentation; inspected status/history before fetching. Initial working tree was clean. Updated only README and the four requested status documents, preserving all historical recovery/failure entries and original verification attribution. Existing 663-test offline and 24-test live results below are historical evidence, **not reruns**. No application tests, live acceptance, AWS operations, package/template rebuilds, infrastructure/permissions changes or next milestone work were performed.

Documentation verification passed: `git diff --check`; a local Python Markdown check across **5 files**, **26 local link targets**, balanced fences/final newlines, **18 shell blocks** parsed with `zsh -n` without execution, and **1 JSON block** parsed. Remaining local/pending matches were reviewed as historical checkpoint statements or this new documentation-branch handoff; stale current Milestone 4 push/CI/merge claims were replaced. No dedicated Markdown lint/link-check tool is configured. These checks and this documentation commit are separate from the hosted results above. Exact next task is the documentation-branch review/handoff, with Milestone 4 already merged and verified.

## Active-report recovery and completed acceptance — 2026-11-08

Read AGENTS, progress, implementation/deployment plans and both reports; optional `docs/agentcore-recovery.md` is absent. Verified clean branch/history and existing Conda Python 3.12.16 / Poetry 2.3.1 interpreter. Before any AWS mutation, required active-report checks passed: mode `cloudshell-active`, top-level passed true, `aws.active_policy_matches` true, empty AWS/offline failures/reference gaps, exact CloudFormation execution role and policy checksum. Reported default v5 matches the committed reviewed policy; proposal v4 mismatch is historical, not acceptance. Active report SHA `90740251407ada706100c8bcbb35fb6da4d2a581d7169db2f4c22f7618da0458`; proposal SHA `a0db6f4f67dd6f2b6bb6d1c65e36e0a37d5544d0779e99862e5a7190e5c2b2e5`. These are administrator-generated IAM inspection/simulation evidence, separate from fresh `analytics-dev` STS and actual service execution. No new profile or IAM change was made.

Fresh read-only checks verified all retained hashes, exact S3 VersionId/checksum/length/encryption, unchanged foundation/data/trust templates, old runtime ROLLBACK_COMPLETE with no live resources or matching Runtime, and failed identity not found. Preserved full stack/events/resources in `artifacts/agentcore/v5.before-delete.json`; original reports, historical CloudTrail, ZIP/assemblies and ledger remain intact. Deleted only that empty failed stack record and waited successfully. No artifact rebuild/upload, bootstrap, dataset publication, foundation/trust deployment or IAM mutation was repeated. CDK published its reviewed deployment templates as part of deployment; the retained code ZIP was never rebuilt or uploaded.

### Actual deployment and live results

All four deployments used repository-local `infrastructure/cdk/tooling/node_modules/.bin/cdk deploy`, stack `enterprise-analytics-dev-agent-runtime`, `--parameters ArtifactVersionId=HSRXiFjg0w2W77InULH4.fn32Y.JH8b9 --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices --outputs-file artifacts/agentcore/recovery.runtime.outputs.json`.

| Step / command or reviewed assembly | Actual result |
| --- | --- |
| `aws cloudformation delete-stack --stack-name enterprise-analytics-dev-agent-runtime --profile analytics-dev --region us-west-2 --no-cli-pager`, then `aws cloudformation wait stack-delete-complete ...` | Previous empty failed stack deleted; evidence retained. |
| `--app artifacts/cdk.agentcore.endpoint-fix.out` initial deployment | Exit 0; CREATE_COMPLETE; deployment 27.70s, total 36.39s. Runtime/DEFAULT READY version **1**, effective dataset `parity-v1`. |
| `poetry run python artifacts/agentcore/recovery_operator.py warmup` | Independent North net revenue **28.50** / South **13.00** USD passed; 1 invocation; 3 model calls, 4,599 input / 344 output tokens, 4,899 ms server latency. |
| `poetry run python artifacts/agentcore/recovery_operator.py retention` | Set seven-day retention on only this Runtime's log group; verified again after restoration. |
| Counted `parity-v1` live suite | **18 passed, 729 deselected in 116.64s**; 19 suite invocations; cumulative **20/40** including warm-up. |
| `--app artifacts/cdk.agentcore.endpoint-fix.parity-legacy-v1.out` | Exit 0; UPDATE_COMPLETE; deployment 22.87s, total 33.84s; Runtime/DEFAULT READY version **2**. |
| Counted `parity-legacy-v1` live suite | **3 passed, 729 deselected in 27.60s**; 4 invocations; cumulative **24/40**. Missing returns produces the expected MissingMetricDataError while net revenue/session isolation pass. |
| `--app artifacts/cdk.agentcore.endpoint-fix.parity-no-returns-v1.out` | Exit 0; UPDATE_COMPLETE; deployment 22.67s, total 33.62s; Runtime/DEFAULT READY version **3**. |
| Counted `parity-no-returns-v1` live suite | **3 passed, 729 deselected in 30.08s**; 4 invocations; cumulative **28/40**. Empty returns yields zero return rate, with successful net revenue/session isolation. |
| `--app artifacts/cdk.agentcore.endpoint-fix.out` restoration | Exit 0; UPDATE_COMPLETE; deployment 22.73s, total 32.33s; Runtime/DEFAULT READY version **4**. Dataset override removed; packaged default `parity-v1` verified. No extra invocation needed. |
| `poetry run python artifacts/agentcore/recovery_operator.py ready <dataset>` after each deployment, then `python artifacts/agentcore/v5_final_verify.py` | Pinned version, code/runtime/model/trusted scope, final READY versions, both policies, exact corrected base template, retained foundation/data/trust and seven-day log retention verified read-only. |

Each live suite actually ran `ANALYTICS_ACCEPTANCE_LABEL=<dataset> poetry run python artifacts/agentcore/run_live.py tests --run-agent-live --agent-config=artifacts/agentcore/live.<dataset>.json -m agent_live -q -s -x` (output retained with pipefail/tee in `artifacts/agentcore/v5.<dataset>.log`). The existing wrapper reserved/fsynced each attempt before dispatch, disabled SDK retries, and preserved the original ledger. No failed-case rerun or extra evaluation was needed.

The initial ignored readiness reader assumed endpoint `targetVersion` was always present; actual READY responses omit it. Corrected only that local helper to require READY and `liveVersion == latest Runtime version`, plus matching targetVersion when supplied. Both policy reads were semantically identical to reviewed JSON after normalizing only scalar/singleton Principal.AWS and aws:PrincipalArn forms. Raw responses/comparisons are preserved; these local-reader corrections did not change Runtime source, approved artifacts, AWS settings or acceptance criteria. Official GetAgentRuntimeEndpoint/GetResourcePolicy documentation was consulted. No new AWS denial occurred in this recovery.

### Completion checkpoint and diagnostics

| Output | Verified value |
| --- | --- |
| Runtime stack | `arn:aws:cloudformation:us-west-2:453711491609:stack/enterprise-analytics-dev-agent-runtime/1324c990-dba9-11f1-b2cf-0ae4036e3efb`, UPDATE_COMPLETE |
| Runtime ARN | `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/enterprise_analytics_dev_agent-HlWywlG60h` |
| DEFAULT endpoint | Runtime ARN + `/runtime-endpoint/DEFAULT`; READY, live/latest version **4** |
| Source artifact | SHA `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1`; 39,117,152 bytes; VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`, unchanged |
| Corrected base / legacy / empty template SHA | `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb` / `bbfe710402345ae04c7b1c73ec6187b7cde602d8344e1233b8e721848efe0ffc` / `ed4f4d446f2307959f87b19d3023412f976bebe8cf2ed7a6b0b9c5c021e82c96` |
| Configuration | `us.amazon.nova-lite-v1:0`, `parity-v1`, reference date `2025-02-01`, trusted tenant `t1`, regions North/South; workload credentials and existing query role |
| Retained infrastructure | Foundation CREATE_COMPLETE; data layer UPDATE_COMPLETE; exact reviewed templates/query trust unchanged |
| Ledger | **28/40**, 28 sequential reservations and SDK returns, zero SDK failures; warm-up 1 + base 19 + legacy 4 + empty 4 |
| Model diagnostics, all 28 responses | **67 calls**, **103,374 input / 7,493 output tokens**; selected model matches throughout |
| Athena diagnostics | **22 unique queries, all SUCCEEDED**, **44,597 scanned bytes**; no cancellation attempts |

Independent offline revalidation of the 27 suite JSONL responses plus warm-up passed the authored literal metric/tool/filter/date/version/error expectations. Same-session North→South isolation passed for all three snapshots; tenant override clarification and unauthorized region isolation passed. Response statuses were 23 answers, four clarifications and one expected missing-source error. Reported server latency sums to 100,999 ms (not wall time or AWS billing); Athena reports 18,804 ms engine / 1,919 ms queue / 22,648 ms total across distinct queries. No measured-dollar cost is claimed.

Ignored evidence includes original reports/ledger, `v5.before-delete.json`, `recovery.runtime.outputs.json`, `ready.<dataset>.<version>.json`, `recovery.warmup.response.json`, `v5.runtime-policy-verification.json`, `v5.policy-checks.json`, three `v5.<dataset>.log` files, `artifacts/agent-live-evaluations.jsonl`, and **`v5.final-verification.json`** / **`v5.completion.json`**. Historical CloudTrail/failure records remain intact.

### Historical completion-session local checks and handoff

Required checks ran in the existing environment before deployment and cover the unchanged application/infrastructure code; this completion changes documentation only. No package rebuild/upload or template resynthesis was performed. Reviewed deployment bytes remain frozen; future builds require their own checksum review.

| Command | Actual result |
| --- | --- |
| `poetry check --lock` | Passed: All set. |
| `poetry run pytest` | **663 passed, 84 skipped in 38.10s**. Offline skips are separate from the explicitly executed live suites above. |
| `poetry run ruff check .` / `poetry run ruff format --check .` | Passed; **76 files** formatted. |
| `poetry run mypy src tests` / extended infrastructure mypy | Passed: **57 / 67 files**. |
| Strict report gates / local artifact hashes / fresh final AWS verification | Passed; no source, IAM policy, data or artifact changes. |
| `git diff --check` / independent completion review | Passed; five documentation files reviewed against final AWS/ledger/live evidence, no blocking finding. |

At completion commit `51c1d4c`, the development acceptance gates had passed and its Git handoff was still pending. That completion commit was subsequently pushed, passed push/PR CI, and merged in PR #4; main CI passed for `47c3afc`, as recorded above. No additional Runtime calls or AWS work are needed for this acceptance. Production hardening, a retail demonstration, Cube, UI and extra AgentCore services remain outside this work.

## Historical Version 4 recovery — 2026-11-08

Read AGENTS, progress, implementation plan and the current deployment plan; inspected the clean starting branch/status/history and existing Conda Python 3.12.16 / Poetry 2.3.1 interpreter. The supplied active V4 JSON matches `a5b690c` and the starting source exactly (file SHA `edda39f7f695cc44b763eea12598c7ce5b501048a0ab445c0204889a7cb94fb9`). Application/default-version evidence is administrator-reported, not an IAM write or fresh direct IAM read by the agent. Explicit STS verified only `analytics-dev`, account `453711491609`, developer `AWSReservedSSO_PowerUserAccess_95483085e85e3a9b/suresh`, region `us-west-2`.

Verified unchanged ZIP SHA `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` (39,117,152 bytes), pinned configuration/plan, exact S3 VersionId `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`, version-specific HEAD/checksum/SSE-S3, asset manifests and absence of missing context. Corrected base SHA `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb`; legacy `bbfe710402345ae04c7b1c73ec6187b7cde602d8344e1233b8e721848efe0ffc`; empty returns `ed4f4d446f2307959f87b19d3023412f976bebe8cf2ed7a6b0b9c5c021e82c96`. Variants differ only in their trusted dataset override. Independent local artifact/ledger audit found no blocker. No rebuild, resynthesis or upload was needed.

| Command / approved step actually run | Actual result |
| --- | --- |
| Read-only STS, CloudFormation templates/resources/events, full Runtime-list pagination and S3 version HEAD | Approved account/profile/region and checkpoints verified. Foundation CREATE_COMPLETE; data UPDATE_COMPLETE, with templates matching reviewed state. Previous failed runtime ROLLBACK_COMPLETE, no surviving resources or matching Runtime. Full evidence preserved in `artifacts/agentcore/v4.before-delete.json`. |
| `aws cloudformation delete-stack --stack-name enterprise-analytics-dev-agent-runtime --profile analytics-dev --region us-west-2 --no-cli-pager`, then `aws cloudformation wait stack-delete-complete ...` | Succeeded; deleted only the old empty failed runtime stack record. |
| Repository-local `cdk deploy --app artifacts/cdk.agentcore.endpoint-fix.out enterprise-analytics-dev-agent-runtime --parameters ArtifactVersionId=HSRXiFjg0w2W77InULH4.fn32Y.JH8b9 --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices --outputs-file artifacts/agentcore/recovery.runtime.outputs.json` | Exit 1; Runtime CREATE_FAILED / AccessDenied, then ROLLBACK_COMPLETE. New stack suffix `d2c0dc90-db99-11f1-81e0-02cde3d69019`. |
| Read-only CloudTrail `LookupEvents` | Retried evidence reads after delivery lag; complete parent and nested denial captured. Initial local extraction mishandled a null responseElements on a successful list event; corrected the ignored diagnostic helper and extracted the saved records. No AWS mutation was repeated. |
| Final read-only stack/resources, full Runtime-list pagination and `GetWorkloadIdentity` | Runtime resource DELETE_COMPLETE without physical ID; stack ROLLBACK_COMPLETE. No matching Runtime. Denied identity `enterprise_analytics_dev_agent-RRZqgv4r4W` returns ResourceNotFoundException. Foundation remains CREATE_COMPLETE; data UPDATE_COMPLETE. |
| READY, warm-up, seven-day log retention, three live suites and corrected parity-v1 restoration | **Not run:** creation failed before any Runtime/endpoint existed. No variant was deployed; restoration was not applicable and parity-v1 READY remains unverified. Existing ledger **0/40**. |

No repeated foundation/trust/bootstrap/publication/upload operations and no IAM write. M3 permissions and datasets remain intact. Ignored evidence: `v4.before-delete.json`, `v4.failed-stack.json`, `v4.failed-events.json`, `v4.agentcore-cloudtrail.json`, `v4.denials.json`, `v4.final-state.json`, and `v4.checkpoint.json` under `artifacts/agentcore/`; earlier checkpoints remain preserved.

### Full denial and smallest proposed correction

Time `2026-11-08T17:28:44Z` (11:28:44 America/Chicago); CloudFormation token `f0cd64b1-060d-c7c3-5563-88c9f1f6118b`. Parent CreateAgentRuntime request `bfe5f689-1552-443f-892d-7baf1c4ddcbd`; nested CreateWorkloadIdentity request `79af8502-c9ee-4003-8315-bd0bb29a0f61`. Both stack RoleARN and CloudTrail session issuer confirm `arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2`.

The parent's complete **`responseElements.message`** is:

> User: arn:aws:sts::453711491609:assumed-role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2/AWSCloudFormation is not authorized to perform: bedrock-agentcore:TagResource on resource: arn:aws:bedrock-agentcore:us-west-2:453711491609:workload-identity-directory/default because no identity-based policy allows the bedrock-agentcore:TagResource action (Service: BedrockAgentCoreControl, Status Code: 403, Request ID: 79af8502-c9ee-4003-8315-bd0bb29a0f61) (SDK Attempt Count: 1)

The child has the same complete identity/action/resource/reason text in **`responseElements.Message`** (uppercase key), without the parent's service/status/request/attempt suffix. It explicitly submits `Project=enterprise-analytics-dev`, `Milestone=4`, and CloudFormation tags for identity `enterprise_analytics_dev_agent-RRZqgv4r4W`. The archive/version and parent configuration are correct. V4 permits tagging named identities but not their exact directory; this denial identifies that additional authorization check. Reattaching unchanged V4 cannot add the missing grant.

Prepared only the separate **`TagAutomaticRuntimeWorkloadIdentityDirectory`** statement: sole action `bedrock-agentcore:TagResource`, exact resource `arn:aws:bedrock-agentcore:us-west-2:453711491609:workload-identity-directory/default`, and exact region/account/Project request-tag conditions. No directory wildcard or extra action. All V4 statements and M3 permissions are unchanged; removing only the addition reproduces the entire supplied V4 (canonical SHA `7160dae5f016fa634e29fdf9c88a8278914efd270f53a7b0d849636413a14143`). Proposed policy file SHA **`ac2942537a6d917b899d3a156efd328953d6176f152b9db925b5e5a13c104419`**.

The [official authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html) lists identity and directory resources for CreateWorkloadIdentity and supports request-tag conditions for directory TagResource. Combined with the nested Project tag, this supports keeping the existing conditions. The default directory is shared in this account/region: its ARN cannot restrict this new grant by runtime name. The submitted Project tag constrains the request, not directory ownership. This is an explicit narrow shared-directory exception requiring administrator review; it is not claimed to be runtime-name isolation or production readiness.

At the V4 checkpoint the proposal was local and unapplied; the agent made no IAM mutation or additional retry then. The later administrator-generated active report verifies the reviewed full policy as default v5. Authorized recovery, all deployed acceptance gates and corrected-base restoration subsequently passed as recorded above. Earlier failure evidence is historical; it is not the current deployment state.

### Historical Version 4 verification

Baseline required checks passed before recovery: **662 passed, 84 skipped in 37.23s**, lock validation, Ruff/formatting and mypy (57/67 files). These checks are separate from both hosted CI runs and unrun live acceptance. Final results cover the new local policy/test change:

| Command | Actual result |
| --- | --- |
| `poetry run pytest tests/test_agentcore_cdk.py -q -k directory_tagging_matches_denial_and_preserves_active_version 4` | **1 failed, 25 deselected in 1.04s against active V4**: no matching directory grant. Passes with the proposal in focused/full checks. |
| `poetry run pytest tests/test_agentcore_cdk.py tests/test_cdk.py -q` | **51 passed in 2.26s**. |
| `poetry check --lock` | Passed: All set. No dependency/lockfile changes. |
| `poetry run pytest` | **663 passed, 84 skipped in 36.45s**. The 66 AWS parity and 18 billable agent tests remain gated; no live acceptance is claimed. |
| `poetry run ruff check .` / `poetry run ruff format --check .` | Passed; **76 files** formatted. Initial new-test line-length/format failure was fixed with `poetry run ruff format tests/test_agentcore_cdk.py`, then both checks rerun successfully. |
| `poetry run mypy src tests` / extended `src tests infrastructure/cdk infrastructure/agentcore` | Passed: **57 / 67 source files**. |
| `aws accessanalyzer validate-policy --profile analytics-dev --region us-west-2 --policy-type IDENTITY_POLICY --policy-document file://infrastructure/cdk/agentcore-deployment-policy.development.json --output json --no-cli-pager` | Read-only validation: **zero findings**; not proof of live authorization. |
| Final artifact/policy/state/ledger assertions | **Seven SHA checks passed**, exact V4 preservation confirmed, final empty runtime rollback verified, original ledger **0/40** preserved. |
| `git diff --check` / deployment-plan shell syntax | Passed; five-file diff reviewed independently without a blocking finding; **10 shell blocks** pass `zsh -n` without executing administrator/recovery commands. |

## Historical Version 3 recovery — 2026-11-08

Read AGENTS, progress, implementation plan and deployment plan; inspected branch/status/history and verified the existing Conda Python 3.12.16 / Poetry 2.3.1 interpreter. Compared the supplied active V3 JSON with commit `4727b1c`: exact equality, file SHA `bf418e5de83729ecb5916b76d14ae7fd760187628fa77f9a5427c4cf42ddc35b`. Active-version/application evidence is administrator-reported, not a direct IAM read or write by the agent. After the initial expired-token error, the user renewed SSO; explicit STS then verified `analytics-dev`, account `453711491609`, developer `AWSReservedSSO_PowerUserAccess_95483085e85e3a9b/suresh`, region `us-west-2`. No other profile/region was used.

Verified unchanged ZIP SHA `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` (39,117,152 bytes), the pinned configuration/plan, version-specific S3 HEAD/checksum, corrected base/variant assembly hashes, asset manifests and absence of missing lookup context. Uploaded VersionId remains `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9`. Base SHA `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb`; legacy `bbfe710402345ae04c7b1c73ec6187b7cde602d8344e1233b8e721848efe0ffc`; empty returns `ed4f4d446f2307959f87b19d3023412f976bebe8cf2ed7a6b0b9c5c021e82c96`. Variants differ only in the trusted dataset override. No package rebuild, resynthesis or upload was needed.

| Command / approved step actually run | Actual result |
| --- | --- |
| Read-only STS, CloudFormation templates/resources/events, full Runtime-list pagination and version-specific S3 HEAD | Confirmed the approved target; old runtime stack ROLLBACK_COMPLETE with no surviving resources or matching Runtime. Foundation/data templates match retained reviewed bytes. Evidence saved in `artifacts/agentcore/v3.before-delete.json`. |
| `aws cloudformation delete-stack --stack-name enterprise-analytics-dev-agent-runtime --profile analytics-dev --region us-west-2 --no-cli-pager`, then `aws cloudformation wait stack-delete-complete ...` | Succeeded; removed only the previous failed runtime stack record. |
| Repository-local `cdk deploy --app artifacts/cdk.agentcore.endpoint-fix.out enterprise-analytics-dev-agent-runtime --parameters ArtifactVersionId=HSRXiFjg0w2W77InULH4.fn32Y.JH8b9 --profile analytics-dev --region us-west-2 --require-approval never --no-telemetry --no-notices --outputs-file artifacts/agentcore/recovery.runtime.outputs.json` | Exit 1; Runtime CREATE_FAILED / AccessDenied, then ROLLBACK_COMPLETE. New stack suffix `8b484200-db93-11f1-afab-0279724cff07`. |
| Read-only CloudTrail `LookupEvents` for CreateAgentRuntime, CreateWorkloadIdentity and TagResource | Captured complete parent/child `responseElements.message`, exact principal, resource and submitted tags. No permissions were changed. |
| Final stack/resources, full Runtime-list pagination and `GetWorkloadIdentity` | Runtime stack ROLLBACK_COMPLETE; its Runtime resource DELETE_COMPLETE without a physical ID. No matching Runtime. Denied identity returns ResourceNotFoundException. Foundation CREATE_COMPLETE; data layer UPDATE_COMPLETE. |
| Runtime/DEFAULT readiness, warm-up, seven-day retention, three live suites, parity-v1 restoration | **Not run:** no Runtime/endpoint was created. No dataset variant was deployed, so no restoration was applicable; parity-v1 READY remains unverified. Existing ledger **0/40**. |

Foundation, query-role trust, uploaded archive/version, M3 permissions and datasets were preserved. No repeated bootstrap, foundation deployment, trust change, publication, code upload or IAM write. Ignored evidence is preserved as `artifacts/agentcore/v3.before-delete.json`, `v3.failed-stack.json`, `v3.failed-events.json`, `v3.create-denials.json`, `v3.identity-denials.json`, `v3.final-state.json`, and `v3.checkpoint.json`; earlier checkpoint evidence remains available.

### Exact authorization diagnosis and local correction

Failure time `2026-11-08T16:43:46Z` (10:43:46 America/Chicago). CloudFormation token `1aded960-d76f-a2c5-44b5-82bfae35697e`; parent CreateAgentRuntime request `84fd1184-9e49-4321-92df-c4eb5b58dc79`; nested CreateWorkloadIdentity request `4d57cf38-f993-4a41-9b63-36630bf41275`. The stack RoleARN and CloudTrail session issuer both confirm execution role `arn:aws:iam::453711491609:role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2`.

The nested event's complete `responseElements.message` is:

> User: arn:aws:sts::453711491609:assumed-role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2/AWSCloudFormation is not authorized to perform: bedrock-agentcore:TagResource on resource: arn:aws:bedrock-agentcore:us-west-2:453711491609:workload-identity-directory/default/workload-identity/enterprise_analytics_dev_agent-PUtFzA3UY3 because no identity-based policy allows the bedrock-agentcore:TagResource action

The parent preserves that full denial plus service status 403, nested request ID and SDK attempt count 1. The child request explicitly carries `Project=enterprise-analytics-dev`, `Milestone=4`, and CloudFormation tags. V3's runtime tagging grants cannot match this workload-identity ARN; its existing identity lifecycle permits Create/Get/Delete but not TagResource. Reattaching unchanged V3 would not remedy that mismatch.

Prepared a separate **`TagAutomaticRuntimeWorkloadIdentity`** statement: only `bedrock-agentcore:TagResource`, only `workload-identity-directory/default/workload-identity/enterprise_analytics_dev_agent-*` in the approved account/region, with exact region/account/Project request-tag conditions. It does not add directory tagging or unrelated identity access. Removing only the new statement reproduces the entire supplied V3 (canonical SHA `ece7e0db64342e9dce9994c0d8c832cdfcad38de3416fe357f53f6320f7f209f`); original V1/V2 preservation guards also pass. Proposed full policy file SHA **`edda39f7f695cc44b763eea12598c7ce5b501048a0ab445c0204889a7cb94fb9`**. M3 permissions and all V3 statements remain unchanged. The [official authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html) documents workload-identity TagResource and request-tag support; [CreateWorkloadIdentity](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateWorkloadIdentity.html) accepts tags. These references plus the child event support keeping the Project condition; effective authorization still requires a successful approved deployment.

At this V3 checkpoint the identity-tagging proposal was local and unapplied; the agent made no IAM write or additional retry then. The administrator subsequently applied it as V4 and the user authorized recovery. That later directory-tagging failure is recorded above. Corrected templates and uploaded ZIP/version remain approved and unchanged; Milestone 4 stays open.

### Historical Version 3 local verification

Before the new proposal, all five required checks passed, including **661 passed, 84 skipped in 33.57s**. Those baseline checks are separate from hosted CI and live acceptance. Final checks below cover the local policy/test change:

| Command | Actual result |
| --- | --- |
| `poetry run pytest tests/test_agentcore_cdk.py -q -k workload_identity_tagging_matches_denial_and_preserves_active_version3` | **1 failed, 24 deselected in 1.07s against active V3**: no tagging grant matched the recorded identity ARN. Passes with the proposal in focused/full runs. |
| `poetry run pytest tests/test_agentcore_cdk.py tests/test_cdk.py -q` | **50 passed in 1.95s**. |
| `poetry check --lock` | Passed: All set. No dependency/lockfile changes. |
| `poetry run pytest` | **662 passed, 84 skipped in 37.57s**. The 66 AWS parity and 18 billable agent tests remain explicitly gated; no live acceptance is claimed. |
| `poetry run ruff check .` / `poetry run ruff format --check .` | Passed; **76 files** already formatted. |
| `poetry run mypy src tests` / extended `src tests infrastructure/cdk infrastructure/agentcore` | Passed: **57 / 67 source files**. |
| `aws accessanalyzer validate-policy --profile analytics-dev --region us-west-2 --policy-type IDENTITY_POLICY --policy-document file://infrastructure/cdk/agentcore-deployment-policy.development.json --output json --no-cli-pager` | Read-only validation: **zero findings**; not proof of live authorization. |
| Final artifact/policy/ledger assertions and plan shell syntax | Five SHA checks passed; removing only the new statement gives exact committed V3 JSON; existing ledger remains empty (0/40); **10 shell blocks** pass `zsh -n` without executing administrator/recovery commands. |
| `git diff --check` | Passed; reviewed the five-file checkpoint and received an independent local diff review with no blocking issues. |

## Historical Version 2 recovery from `7360cc4` — 2026-11-06

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

## Historical Version 2 diagnosis and tagging addition — now applied as V3

The complete new CloudTrail record is retained in `artifacts/agentcore/recovery.create-denials.json`. Its **`responseElements.message`** identifies:

- Time: `2026-11-06T21:14:23Z` (15:14:23 America/Chicago); request `4074f7e9-3e5d-4278-a0d7-d48fe5f1a8b6`; CloudFormation token `4e3dab07-5d61-d749-656f-914e574f43f4`.
- Principal: `arn:aws:sts::453711491609:assumed-role/cdk-hnb659fds-cfn-exec-role-453711491609-us-west-2/AWSCloudFormation`. The stack RoleARN and session issuer independently confirm the same CloudFormation execution role.
- **Action: `bedrock-agentcore:TagResource`. Resource: `arn:aws:bedrock-agentcore:us-west-2:453711491609:runtime/*`. Reason: no identity-based policy allows that action on this resource.**
- The request retains the correct Project tag, account, region, model/runtime configuration and exact uploaded VersionId. Active V2's tagging grant remains restricted to the named runtime prefix, which does not match the creation-time wildcard. No evidence justifies changes to PassRole, runtime/query permissions, or optional features.

Prepared only **`bedrock-agentcore:TagResource`** in the Action list of `CreateTaggedDefaultEndpointDuringRuntimeCreation`. Its resource and exact region/account/Project conditions are unchanged. Removing just that action reproduces the entire administrator-supplied V2 JSON, with frozen canonical SHA `48939891d9f2183a398aa2918a8dcc374e33c6b3a1fbb821c135e31fc03dbac9`. Existing statements and M3 policy/attachments remain intact. Proposed full policy SHA: **`bf418e5de83729ecb5916b76d14ae7fd760187628fa77f9a5427c4cf42ddc35b`**.

At the V2 checkpoint, official documentation supported the runtime-tagging proposal and request-tag conditions; Access Analyzer was not live authorization proof. The agent made no IAM write or additional retry then. The administrator subsequently applied this proposal as V3 and the user authorized recovery. That later attempt and its separate workload-identity denial are recorded above; the original corrected templates remain approved and unchanged.

## Historical Version 2 checkpoint local verification

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

Milestones **1–5 are complete for the agreed development proof of concept**. M4's merged/CI evidence and 28/40 history remain intact. M5's first 35/36 campaign and both failed repair attempts remain historical evidence; the approved recovery now passed Q18 and all 36 frozen cases, reporting gates and original restoration/smoke on **READY v12**, runtime stack UPDATE_COMPLETE. The recovery ledger is closed **38/38**, aggregate repair **40/40**; earlier M5 **38/40**, M4 **28/40**, repair **1/40** and continuation **1/39** histories are unchanged. The implementation/recovery checkpoint `f223877` passed the exact push/PR CI linked above. Completion `7905d13` is merged through PR #6 at `c0d2c5a569e2d242bf840a715c31050888b579ab` on November 10, 2026, and [main CI 42872516193](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42872516193) passed for that exact merge. This documentation closeout has separate PR/CI coverage. Broader vocabulary, production authorization, long-duration fault injection and measured cost remain unverified.

Runtime packaging targets Linux ARM64, not the local macOS native libraries. API/CloudFormation/model compatibility passed the agreed development live acceptance; broader production behavior remains unverified. Scheduling deadlines and Athena cancellation remain best effort; an in-flight SDK call can outlast them. Administrator evidence supplies the candidate-key grant; no new IAM failure occurred in this execution. The retail candidate passed the agreed full live suite; original parity scope and artifact are restored on v12. Denied IAM inspection is not a reason to broaden permissions automatically. No production isolation/policy service or measured-cost claim is made.

Source versions are immutable through the approved loader protocol; partial publication is deliberately not resumed automatically. New dataset versions require reviewed infrastructure inventory changes. Athena aggregates have a 38-digit bound. Application authorization is not a database security boundary, and 10 MiB per-query limits do not cap aggregate spend. Stored data is retained by default; no explicit cleanup was reported or performed in this update.

Historical milestone 2 branch creation was initially denied by the sandbox's read-only Git metadata restriction; the approved retry succeeded. Its implementation commit, merge, and hosted CI verification are complete.

Milestone 2 introduced no AWS credentials, calls, deployment, Athena adapter, or Bedrock/AgentCore integration. Milestone 2 used an application-controlled in-memory snapshot; there is no production policy service, FX, as-of history, streaming, or complete financial/cumulative physical-return ledger. Over-refunds can produce negative net revenue/AOV. Present optional return files are validated even when another metric is queried.

## Exact next task

The agreed development proof of concept for **Milestones 1–5 is complete**, merged and hosted-CI verified. The separately approved shared UI follow-on also passed Q18/all 18 paired outcomes on candidate READY v13. Its next task is the outcome PR/CI/user-review handoff recorded above; no ordinary live allowance remains. Other development still requires a separately defined scope. Preserve the recorded original READY v12 checkpoint, frozen assets/goldens and all closed ledgers/claims. **Recovery 38/38 and aggregate repair 40/40 are exhausted**; no rerun, additional demonstration, quota reset, AWS operation or next milestone is authorized by closeout. Production-readiness limitations above remain explicit.
