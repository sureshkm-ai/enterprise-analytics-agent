# Q18 continuation: controller correction and 39-call proposal

**Current status (November 10, 2026): M5 passed the approved recovery and is complete
for the agreed development scope.** Q18 probe/warm-up and all **36/36** frozen
requests passed; the original artifact/parity configuration and counted smoke
passed on **Runtime/DEFAULT READY v12**, runtime stack UPDATE_COMPLETE. Recovery
is closed **38/38**, aggregate repair **40/40**; historical M5 **38/40**, M4 **28/40**
and both prior repair histories/claims are unchanged. PR #6 remains unmerged for
review. No live allowance remains. See [recovery results](milestone-5-q18-recovery-proposal.md)
and [progress](progress.md). The earlier preparation/failure records below are
historical; their commands cannot restart a closed campaign.

## Historical preparation and execution records

**Approved attempt finished without candidate acceptance; original restoration/smoke passed.**
M5 remains open and PR #6 remains unmerged. The approved controller commit `e8e4b0f`
was pushed and passed [push CI 42698850994](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42698850994)
and [PR CI 42698861471](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42698861471).
These cover preparation, not the later live checkpoint.

The approved continuation deployed candidate v9 successfully, but ConnectTimeoutError in the additional checkpoint stopped execution before any candidate call. Mandatory original restoration/smoke passed on Runtime/DEFAULT READY v10, stack UPDATE_COMPLETE. Continuation is 1/39 and closed, aggregate 2/40 with 38 remaining. The required 39-call sequence cannot fit that remainder; M5 remains open and PR #6 unmerged. No automatic retry or budget change is authorized.
The failed SDK operation/endpoint/message was not captured; do not infer the service or
underlying cause. Actual evidence, hashes, counts and fresh v10 verification are in
[progress](progress.md). Both command examples below are historical, not a replay recipe.

Charges would use the existing Bedrock/AgentCore/Athena/S3 resources and rates; no new
infrastructure or measured-dollar claim is proposed. Retain the existing 90s agent
deadline, six model iterations,12,000 total tokens, 16 tool calls and 10 MiB Athena per-query
scan limit. Invocation/token/scan limits constrain work, not an aggregate billing cap.

## Evidence and what is known

Reviewed every retained file under
`artifacts/milestone-5/q18-repair-v1/operations/20261109T193234Z/`.
CloudFormation completed the candidate update at 19:37:42.806Z; the independent
checkpoint later verified exact candidate configuration/artifact/policies and READY v7.
CDK stdout is empty; stderr stops at `deploying... [1/1]`. The supervisor records
`TimeoutExpired` with the configured 1800-second bound. There are no candidate-call
reservations or warm-up/probe/suite files. Mandatory original restoration completed
at 20:08:13.379Z; the original checkpoint and smoke verified READY v8.

The one-second native sample shows an event loop waiting in `uv__io_poll`/`kevent`.
It does **not** establish the specific pending request, SDK defect or network cause.
Captured CloudTrail records have no authorization error; this is not a claim that
all possible service/transport failures were captured. No new IAM grant is indicated.
The existing administrator-supplied candidate-key grant and original grants are preserved.

## Reviewed continuation identity and unchanged resources

| Item | Pin |
| --- | --- |
| Profile / account / region | analytics-dev / 453711491609 / us-west-2 |
| Runtime / endpoint | enterprise_analytics_dev_agent-HlWywlG60h / DEFAULT |
| Model | us.amazon.nova-lite-v1:0, same approved US routing and limits |
| Selector / campaign | `q18-continuation-v1` / `milestone-5-q18-continuation-v1` |
| New ledger | `artifacts/milestone-5/q18-continuation-v1/runtime-invocations.jsonl` |
| Closed parent ledger | `artifacts/milestone-5/q18-repair-v1/runtime-invocations.jsonl`, 1/40 |
| Parent ledger SHA-256 | `6f39bc49361a718e221fd1bd4b38fc12c2b0c305cfa30246ef1a22005d5bf7e8` |
| Continuation review | [q18-continuation-review.json](../evaluations/retail-v1/q18-continuation-review.json) |
| Review identity SHA-256 | `13f9bff2a91cc17fc5177e9e8d7814101231ab0d8fc9d839ec19d47cbaae3354` |
| Campaign binding SHA-256 | `6988ae16e484bfe9229994eb473c3bb9b8361086a69d7cdd76e7e35b63205333` |
| Reviewed starting checkpoint | Original parity-v1 READY v8 was freshly verified before this attempt; current restored state is v10. Preserve this historical review, do not rewrite it to retry. |
| Historical v8 proof SHA-256 | `79fd03cd2579af9c9315e5573edc72cd8669c966a8b00363f074dea3d1ebf29a` |
| Original configuration SHA-256 | `67056f86738cdfec508a9c00cd99c42767a8360b417c31928eb626eca3e530b3` |
| Candidate ZIP SHA-256 | `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1` |
| Existing candidate VersionId | `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` |
| Candidate assembly / template SHA | `artifacts/milestone-5/q18-repair-v1/cdk.candidate.out` / `faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368` |
| Original ZIP SHA-256 / VersionId | `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` / `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9` |
| Restoration assembly / template SHA | `artifacts/milestone-5/cdk.restore.out` / `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb` |

Review identities use sorted compact JSON, not file formatting. The existing write-once
candidate version record is reused, not regenerated. No ZIP rebuild, upload, resynthesis,
publication, profile creation, IAM change, foundation/data deployment or cleanup is proposed.
The only Runtime changes are the already reviewed candidate code key/version and three
retail settings, followed by exact original restoration. All source checksums, goldens,
original assemblies and M4 28/40 / original M5 38/40 / parent repair 1/40 histories remain intact.
The candidate's runtime source is unchanged; the corrected controller/evaluator runs locally.
Packaged operator modules remain their frozen build versions and are not used by the runtime.

## Completion controller

The controller supervises a task-owned CDK process group while independently observing AWS.
It requires the named stack/account/region, stable success, exact complete template and
parameter inventory (including the pinned ArtifactVersionId and reviewed BootstrapVersion
parameter), and the full strict checkpoint: Runtime and DEFAULT live versions, artifact,
trusted configuration, policies, retained infrastructure, S3 checksum/version and retention.
A fresh update must advance CloudFormation's update timestamp from the observed baseline.
Before any candidate invocation, Runtime and DEFAULT must also agree on a numeric
version newer than the reviewed v8 start; the earlier candidate v7 cannot authorize dispatch.
An already matching deployment is an explicit verified no-op, with no CDK process started.
READY alone, a zero exit code or a matching subset of parameters cannot establish success.

When AWS success is independently established while CDK remains running, terminate/reap
only that owned process group, then repeat the exact-state and full checkpoint checks.
Preserve stdout/stderr and per-deployment `candidate.controller.json` / `restore.controller.json`.
A natural nonzero CDK exit, rollback, wrong/stale state, missing evidence or unavailable
verification cannot pass. Do not submit another deployment while a preceding AWS update
is unresolved or a task-owned child cannot be confirmed stopped.

Default bounds: 900s for prior-stack settlement, 900s for deployment observation, 120s for
strict verification, and 5s each for TERM/KILL cleanup. SDK reads use 3s connect / 10s read
and one total attempt, checking the verification deadline before each call. An already
started bounded SDK read can outlast the scheduling deadline. Invocation SDK automatic
retries remain disabled. No new billable invocation is used to reconcile deployment.

A per-Runtime deployment lock and durable process-intent journal prevent overlap after
interruption/host loss. An unresolved active journal blocks new mutation; retain it and
inspect the task-owned process and AWS state before supervised recovery. Do not delete it
or signal unrelated/prior process groups to bypass the guard. A separate whole-continuation
operator lease prevents restoration-only recovery during an active evaluation. The durable,
exclusive attempt claim prevents a second candidate attempt even if zero calls were made.

## Aggregate allowance and acceptance

**The user approved all 39 then-remaining calls, including the controlled reserve. This
attempt consumed one for restoration; aggregate usage is2/40 with 38 remaining. The
ledger is closed and another full 39-call sequence exceeds that cap.** There is no new
40-call allocation, automatic retry, selective rerun, spare demo call or automatic reserve.

| Purpose | Maximum calls |
| --- | ---: |
| Counted warm-up | 1 |
| Independent frozen Q18 probe | 1 |
| Full unchanged suite, including Q18 again and S01A/B | 36 |
| Mandatory original restoration smoke | 1 |
| Total continuation | 39 |
| Already consumed parent smoke | 1 |
| Aggregate hard maximum | 40 |

Every continuation event binds the parent hash, candidate/version record, starting
checkpoint and continuation review. The closed parent is opened read-only and revalidated
before summaries, reservations and outcomes. A separate new counter permits at most 38
non-restoration calls and protects its final call for a freshly verified original smoke.
Failures, interruptions and incomplete reservations count. Restoration closes retail dispatch.
Do not reset/reopen any ledger or start another continuation after a failed/partial attempt.

Require successful warm-up, Q18 probe with complete frozen request and **110.25 USD**,
all **36/36** unchanged cases (structured plans/values, clarification, authorization and
shared-session isolation), complete token/latency/unique-Athena-scan diagnostics and
client p95 ≤90s. Then require original artifact/configuration/policies/retention restoration,
matching Runtime/DEFAULT READY versions, stack UPDATE_COMPLETE and the independent parity
smoke (North 28.50 / South 13.00 USD). Only then may M5 be marked complete. Restoration creates
a later Runtime version; never assert that it returns to numeric version 8.

## Commands and failure procedure

The following command is **offline** and creates no AWS client, claim or continuation ledger:

```sh
conda activate enterprise-analytics
python --version
poetry env info --executable
poetry run analytics-repair --campaign q18-continuation-v1 verify-offline \
  --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json
```

The user approved this revised allowance and controller for the attempt now finished. The
following command records the executed procedure; do not run it again. The procedure required fresh
analytics-dev identity, original v8 checkpoint, version-specific candidate HEAD and exact
artifact/assembly checks through the gated operator. Stop on drift/denial. Use a new
report directory; the operator claims the attempt before any candidate deployment:

```sh
poetry run analytics-repair --campaign q18-continuation-v1 run --invoke-live \
  --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json \
  --report-dir artifacts/milestone-5/q18-continuation-v1/runs/approved-unique
```

Execution order is fresh preflight → exact reviewed candidate deployment/reconciliation →
READY proof → counted warm-up → Q18 probe → unchanged full suite → original restoration
in `finally` → strict original proof → counted smoke. Failed probe stops before the full
suite. Exceptions and SIGTERM/Ctrl-C enter mandatory restoration; the controller stops
its owned child and waits for stable AWS state before another deployment. If restoration
cannot be verified, no smoke is dispatched and acceptance stays false.

The attempt restored successfully and its smoke passed; no recovery call remains pending.
Do not execute the following restoration-only command for this finished attempt. It records
the previously reviewed recovery procedure. After host/process loss or an interrupted attempt,
preserve logs, process journal, claim,
ledgers and reports. First resolve any active process/update guard using evidence. A
restoration-only command uses the same continuation binding and remaining protected slot;
it cannot start another candidate or silently borrow a call after exhaustion:

```sh
poetry run analytics-repair --campaign q18-continuation-v1 restore --invoke-live \
  --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json \
  --report-dir artifacts/milestone-5/q18-continuation-v1/runs/restoration-unique
```

Restoration-only requires a valid prior attempt claim and does not depend on retail inputs
or candidate-object access. Do not run it concurrently with the operator. A missing or
unresolved claim/journal requires supervised diagnosis; do not remove/reset evidence.
For any AWS denial, retain full logs and complete parent/nested CloudTrail messages,
identify principal/action/resource/conditions and stop repeated attempts. No automatic
permission expansion, resource deletion or additional upload is authorized.

Offline verification, approval, fresh preflight and actual execution/restoration results
are recorded in [progress](progress.md). Do not replay this closed attempt. A new reviewed checkpoint/budget decision is required
before any later execution; no new upload, rebuild or permission is indicated.

Official references consulted for the correction: Boto3
[DescribeStacks](https://docs.aws.amazon.com/boto3/latest/reference/services/cloudformation/client/describe_stacks.html)
(stack identity/status, update times and parameter inventory),
[GetTemplate](https://docs.aws.amazon.com/boto3/latest/reference/services/cloudformation/client/get_template.html)
(Original template body), and Python 3.12
[subprocess](https://docs.python.org/3.12/library/subprocess.html)
(Popen sessions, finite waits, termination and reaping).
