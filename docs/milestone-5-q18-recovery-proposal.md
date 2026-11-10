# Q18 recovery from v10 — operator correction and completed 38-call sequence

Status: **approved and executed once at f223877; all live acceptance/restoration gates passed. Campaign closed; no calls remain.**
Source checkpoint: GitHub `75d7c9f688f8e0746b17b797016947e1ed41f4bb`.
At that historical source checkpoint M5 remained open. It passed [push CI](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42709874036)
and [PR CI](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42709898730).
Those results do not cover this new correction or establish retail acceptance.

## Executed recovery — 2026-11-10

The user approved this proposal at `f2238775e724630af14bcc0c14ac4cdc150f821c`,
whose [push CI 42861036450](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42861036450)
and [PR CI 42861051831](https://github.com/sureshkm-ai/enterprise-analytics-agent/actions/runs/42861051831)
were freshly verified. Those runs cover the reviewed operator, not the outcome documentation.

Fresh original **READY v10** preflight passed with exact pins, templates/parameters,
policies, retention, canonical source/Glue and process/history checks. The one workflow
then deployed the existing candidate on **READY v11**, passed the fully judged
**110.25 USD [2025-03-31,2025-04-01)** probe and **36/36 unchanged suite requests**, and
restored the original artifact/configuration on **Runtime/DEFAULT READY v12**,
stack **UPDATE_COMPLETE**. North **28.50 USD** / South **13.00 USD** smoke passed.
A separate final read-only checkpoint and independent report/preservation audits passed.

Suite client p95 **13.381s**, maximum **15.467s**, against unchanged 90s p95 gate;
complete diagnostics, all authorization/clarification/metadata/session criteria passed.
Suite work: **74 model calls, 108643 input / 8994 output tokens, 36 unique Athena queries,
194837 bytes scanned**. The probe is the warm-up and excluded from suite latency.
No threshold, question, golden, frozen ZIP/version, policy or dataset changed.

Usage is **38/38 new, aggregate 40/40**: probe 1 + suite 36 + protected smoke 1,
all completed, zero invocation failures/retries/timeouts/incomplete reservations.
The recovery claim remains retained and retail dispatch closed. **Do not replay
these commands, restore again or reset a ledger.** M5 is complete for the agreed
development scope; PR #6 remains unmerged for review, not production-ready.

Evidence root: `artifacts/milestone-5/q18-recovery-v1/operations/20261110T173634Z/`.
Review `live/probe.json`, `live/suite/{report.json,summary.md,attempts.jsonl}`,
`live/{campaign-result.json,restored-proof.json,smoke.json}`, final checkpoint,
controller/read journals and independent audits. `campaign-result.json` reports
**accepted:true**; the suite-only report's `live_gates_passed:true` is combined
with restoration/smoke by the campaign. Recovery ledger SHA-256 is
`2a4004c2056351a4c923c78a3a4aba357baf0500c46e5845ffc8d71e71fa04ce`.
All 122 protected files and historical ledgers/claims remain unchanged.

The following correction, allocation, pins and commands preserve the reviewed
procedure and historical offline handoff. The campaign has now completed.

## Evidence and correction

The retained execution record establishes successful candidate v9 deployment,
a subsequent `ConnectTimeoutError`, zero candidate invocations, and successful
original restoration/smoke on v10. It does not establish which SDK operation
timed out or the underlying network cause. The raw ignored operation files and all 28 + 30 summary-linked evidence hashes
were inspected in the original checkout during the offline handoff. The earlier
portable-patch review lacked these ignored files; that limitation no longer
applies to local preservation verification. No fresh AWS state was read.

The code exposes several avoidable failure paths, addressed together here:

- The controller now returns its final strict checkpoint after owned-process
  cleanup. The workflow consumes that fresh in-memory result instead of repeating
  the complete candidate verifier. Exact template/parameters, Runtime/DEFAULT,
  artifact/version/configuration, policies and retention checks remain mandatory.
- Every allowlisted operator read uses a shared connection pool, at most three
  attempts, 0.5/1-second backoff, five-second connection and ten-second read
  timeouts, and the existing monotonic verification deadline. Only identified
  transient failures retry. Authorization/validation errors fail immediately.
- The separate STS identity read during invocation-client construction uses the
  same bounded handling. Runtime client construction is journaled separately,
  without retries; late construction fails before dispatch. The operator reuses
  its invocation client per target.
  **InvokeAgentRuntime still has exactly one SDK attempt per durable reservation.**
- A successful restoration returns its strict proof. The same operator may reuse
  it for up to 60 seconds through the immediate smoke gate; expiry triggers fresh
  verification. Candidate or restoration mutation invalidates any cached proof.
  Starting-state proofs and saved JSON files cannot populate this cache.
- A persistent read journal records phase, service, operation, safe target fields,
  endpoint hostname, attempt, duration, error class, AWS code and request ID when
  available. It records the start before calling AWS. Raw exception messages,
  credentials, signed URLs, headers and payloads are excluded. Primary and
  restoration failures are retained separately; a final accounting error cannot
  erase their evidence or allow acceptance.
- One operator lease now spans the full repair lifecycle across selectors, in
  addition to the deployment process journal and exclusive attempt claims.

These are scheduling bounds, not a hard process wall-clock guarantee: an in-flight
read, credential resolution or OS networking can outlast a deadline. Late responses
do not pass verification. Permanent outages, denied access or semantic failures
still stop the run and trigger the existing restoration procedure. No automatic
second deployment campaign or billable invocation retry is introduced.

SDK behavior was checked against the official [retry guide](https://docs.aws.amazon.com/boto3/latest/guide/retries.html)
and [Botocore configuration reference](https://docs.aws.amazon.com/botocore/latest/reference/config.html).
`total_max_attempts=1` disables nested SDK retries; the operator owns read retries.

## Approved scope and budget (now fully consumed)

Use existing profile **analytics-dev**, account **453711491609**, region **us-west-2**.
No new AWS profile, IAM permission, ZIP build/upload, data publication or template
change is proposed. This is an operator-code correction; it does not require
rebuilding the frozen runtime candidate.

| Sequence | New Runtime calls |
| --- | ---: |
| Q18 probe, also serving as warm-up | 1 |
| Complete frozen suite, including Q18 and both session requests | 36 |
| Original parity restoration smoke | 1 |
| Total proposed | **38** |
| Two historical repair/restoration calls | **2** |
| Aggregate limit | **40** |

This explicitly replaces the separate warm-up request with the fully judged Q18
probe for this new selector. It omits no suite case and changes no golden or
acceptance threshold. The probe must match net_revenue for
`[2025-03-31,2025-04-01)` at **110.25 USD**, with the full expected plan/result.
It is reported separately from the 36-case latency sample; a warm-up does not
guarantee subsequent sessions are warm. The final call is protected for smoke.
There is no spare invocation. Another failed attempt needs another reviewed
decision, not a reset or automatic rerun.

The proposed selector is **q18-recovery-v1**. Its immutable review is
[`evaluations/retail-v1/q18-recovery-review.json`](../evaluations/retail-v1/q18-recovery-review.json).
It requires a freshly verified original **v10**, not the historical v8 review.
It binds and reads both closed parent histories and the prior claim without
rewriting them. Changing a run directory cannot reset quota or the attempt claim.

| Preserved item | Exact pin |
| --- | --- |
| Candidate ZIP SHA-256 | `398124e89d2be1e9ce00f5b57c263fe2cdde0654527b27f949b9f3abb58029f1` |
| Candidate S3 VersionId | `V5Q8e8e6w2tkkVghXn.BrFs1mqQU.Ncu` |
| Candidate template SHA-256 | `faca6d23b85038d5c8ad16b1fe73c95b910d9d05c6a4fccf3be8ca82cd9eb368` |
| Original ZIP SHA-256 | `51eaeac6b9eb107f4634aea9e3180fa1db7dce1380fbe166415fbfed8185ded1` |
| Original S3 VersionId | `HSRXiFjg0w2W77InULH4.fn32Y.JH8b9` |
| Original template SHA-256 | `dd217890a37cc42e54499c3cc8cba91886ed5ca3dee5de9a5bb11a5e153c64bb` |
| Closed repair ledger, 1/40 | `6f39bc49361a718e221fd1bd4b38fc12c2b0c305cfa30246ef1a22005d5bf7e8` |
| Closed continuation ledger, 1/39 | `4943c554d4a856621ef126389f7666bfcd2e32a16be2ef2cd024c0d4ab5d9ca5` |
| Closed continuation attempt claim | `a741c8a0bb6c7acfaebe0c3e2a92c43d8d8df3147c95a039561760dd7e4be137` |

The original M5 ledger stays at 38/40 and M4 at 28/40. Neither supplies this budget.
The new aggregate calculation is 1 historical repair + 1 historical continuation
+ up to 38 recovery calls. Versions after deployment are observed, never guessed.

## Verified offline handoff

The supplied patch is applied on `feat/milestone-5-retail-evaluation`. Local review,
required checks and separate offline example syntheses passed with **1086 tests
passed and 85 live-gated skips**. The actual preservation inventory, frozen ZIPs,
version records, corrected assemblies, goldens, historical ledgers/claim and
operation evidence match their pins. The historical v8 review stays unchanged;
this recovery's fresh original-v10 check remains a later live preflight gate.
No recovery ledger or claim was created, and no AWS operations were performed.

The repeatable **offline** check needs no AWS session:

```sh
poetry run analytics-repair --campaign q18-recovery-v1 verify-offline \
  --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json
```

Verified result: new campaign **0/38**; prior **2**; aggregate **2/40**, remaining
**38**. A missing/different file is a blocker; never manufacture evidence or
change pins to make it pass. Preserve historical journals/locks/claims.

The handoff includes normal push and exact-commit hosted CI verification, recorded
in [progress](progress.md). Hosted offline CI is separate from live acceptance.
At that offline checkpoint, later execution still required fresh AWS/process checks.
Those checks and the approved live run are now recorded above.

## Reviewed execution and restoration commands (historical; campaign closed)

Approval covers one existing-candidate deployment from freshly verified v10,
the 38-call sequence above, and mandatory original restoration/smoke. It authorizes
no new profile or permission changes. The original candidate-key permission must
still apply. The run performs read-only identity/artifact/checkpoint checks before
mutation; earlier reports alone cannot replace them.

From the repository root, choose a new report location and run once:

```sh
M5_RECOVERY_ROOT="artifacts/milestone-5/q18-recovery-v1/operations/$(date -u +%Y%m%dT%H%M%SZ)"
poetry run analytics-repair --campaign q18-recovery-v1 run --invoke-live \
  --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json \
  --report-dir "$M5_RECOVERY_ROOT/live"
```

Read diagnostics are at `$M5_RECOVERY_ROOT/live.operator-reads.jsonl`, including
failures before workflow setup. Controller proofs/logs and `campaign-result.json`
are under `live/`. Candidate-ready context contains the accepted controller proof;
`probe.json`, the complete `suite/`, restored proof and `smoke.json` supply the
acceptance evidence. Every unavailable or mismatching gate fails closed.

If interrupted, inspect the retained process journal and claim before recovery.
When the journal is resolved and restoration is still needed, the reviewed
restoration-only path uses the same ledger/claim and a new report directory:

```sh
poetry run analytics-repair --campaign q18-recovery-v1 restore --invoke-live \
  --version-record artifacts/milestone-5/q18-repair-v1/candidate-version.json \
  --report-dir "$M5_RECOVERY_ROOT/restoration-only"
```

Do not issue this after a successful smoke or reset a closed ledger to repeat it.
Restoration-only execution does not redeploy the candidate or start the suite.
An unresolved owned process, failed parent-hash check or exhausted quota requires
inspection and an explicit decision; never bypass the guard.

M5 can close only after the Q18 probe and all 36 suite cases meet unchanged gates,
original parity configuration/artifact/templates/policies/retention are verified,
and the counted North 28.50 / South 13.00 USD smoke passes. Record observed versions,
actual usage, raw report paths, commit and exact CI links; preserve earlier failed
attempts. Keep PR #6 unmerged until this evidence is reviewed.
